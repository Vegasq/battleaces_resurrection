#pragma once
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

// Private inherited socket IPC only. TLS and invite credentials live in the
// parent transport process, never in this channel or the game command line.
namespace ba_secure {
class RemoteFailure : public std::runtime_error {
    unsigned code_;
    static const char* reason(unsigned code) {
        static const char* reasons[]={"Secure transport failed", "Server certificate verification failed", "Secure server unavailable",
            "Server invite authentication failed", "Server invite identity changed", "Secure transport input queue full",
            "Secure transport failed", "Secure server connection timed out", "Online connection is not configured",
            "Online connection settings are invalid"};
        return reasons[code<=9?code:0];
    }
public:
    explicit RemoteFailure(unsigned code):std::runtime_error(reason(code)),code_(code){}
    unsigned code() const noexcept {return code_;}
};
class Channel {
    using Bytes=std::vector<unsigned char>;
    static constexpr size_t chunk=65536,limit=2*1024*1024;
    SOCKET socket_=INVALID_SOCKET;
    bool winsock_=false,active_=false,closed_=false,eof_=false,ready_=false;
    unsigned char version_=1;
    std::string profile_;
    uint32_t session_=0;
    unsigned failure_=0;
    Bytes wireIn_,wireOut_,plain_;
    size_t written_=0,read_=0;
    static uint32_t word(const unsigned char* data) {uint32_t n;memcpy(&n,data,4);return n;}
    static void append(Bytes& out,uint32_t value) {
        auto data=reinterpret_cast<const unsigned char*>(&value);out.insert(out.end(),data,data+4);
    }
    static bool validProfile(const unsigned char* data,size_t size) {
        if(size!=34 || data[0]!='p' || data[1]!='_')return false;
        for(size_t i=2;i<size;++i)if(!((data[i]>='0' && data[i]<='9') || (data[i]>='a' && data[i]<='f')))return false;
        return true;
    }
    void checkFailure() const {if(failure_)throw RemoteFailure(failure_);}
    void queue(unsigned kind,const unsigned char* data=nullptr,size_t size=0) {
        if(size>chunk || wireOut_.size()-written_+size+10>limit)throw std::runtime_error("Secure transport send queue full");
        if(written_){wireOut_.erase(wireOut_.begin(),wireOut_.begin()+written_);written_=0;}
        append(wireOut_,static_cast<uint32_t>(size+6));wireOut_.push_back(version_);
        wireOut_.push_back(static_cast<unsigned char>(kind));append(wireOut_,session_);
        if(size)wireOut_.insert(wireOut_.end(),data,data+size);
    }
    void flush() {
        for(unsigned turn=0;written_<wireOut_.size() && turn<16;++turn) {
            int sent=::send(socket_,reinterpret_cast<const char*>(wireOut_.data()+written_),
                static_cast<int>((std::min)(chunk,wireOut_.size()-written_)),0);
            if(sent==SOCKET_ERROR && WSAGetLastError()==WSAEWOULDBLOCK)return;
            if(sent<=0)throw std::runtime_error("Secure transport process disconnected");
            written_+=sent;
        }
        if(written_==wireOut_.size()){wireOut_.clear();written_=0;}
    }
    void parse() {
        size_t at=0;
        while(wireIn_.size()-at>=4) {
            const uint32_t length=word(wireIn_.data()+at);
            if(length<6 || length>chunk+6)throw std::runtime_error("Invalid secure transport frame size");
            if(wireIn_.size()-at<length+4)break;
            const unsigned char* body=wireIn_.data()+at+4;
            const unsigned kind=body[1];const uint32_t identity=word(body+2);
            const size_t size=length-6;
            if(body[0]!=version_ || !identity || identity>session_ ||
                (kind!=2 && kind!=3 && kind!=4 && !(version_==2 && kind==5)) || (kind==2 && !size) ||
                (kind==3 && size) || (kind==4 && (size!=1 || body[6]<1 || body[6]>(version_==2?9:7))) ||
                (kind==5 && !validProfile(body+6,size)))
                throw std::runtime_error("Invalid secure transport message");
            if(identity==session_ && active_) {
                if(kind==2) {
                    if(closed_ || failure_ || !ready_ || plain_.size()-read_+size>limit)throw std::runtime_error("Secure transport receive queue invalid");
                    if(read_){plain_.erase(plain_.begin(),plain_.begin()+read_);read_=0;}
                    plain_.insert(plain_.end(),body+6,body+6+size);
                } else if(kind==5) {
                    if(closed_ || failure_ || ready_)throw std::runtime_error("Unexpected secure transport identity");
                    profile_.assign(reinterpret_cast<const char*>(body+6),size);ready_=true;
                } else {
                    if(kind==3)closed_=true;else failure_=body[6];
                    ready_=false;profile_.clear();
                }
            }
            at+=length+4;
        }
        if(at)wireIn_.erase(wireIn_.begin(),wireIn_.begin()+at);
    }
    void pump() {
        if(eof_)return;
        flush();
        unsigned char data[chunk];
        for(unsigned turn=0;turn<4;++turn) {
            const int received=::recv(socket_,reinterpret_cast<char*>(data),sizeof(data),0);
            if(received==SOCKET_ERROR && WSAGetLastError()==WSAEWOULDBLOCK)break;
            if(received==SOCKET_ERROR)throw std::runtime_error("Secure transport receive failed");
            if(!received){eof_=true;break;}
            wireIn_.insert(wireIn_.end(),data,data+received);
            if(wireIn_.size()>limit)throw std::runtime_error("Secure transport wire queue full");
        }
        parse();
        if(eof_ && !wireIn_.empty())throw std::runtime_error("Secure transport ended mid-message");
    }
    void discard() noexcept {
        if(socket_!=INVALID_SOCKET){closesocket(socket_);socket_=INVALID_SOCKET;}
        eof_=true;active_=false;ready_=false;profile_.clear();
    }
public:
    Channel()=default;
    Channel(const Channel&)=delete;
    Channel& operator=(const Channel&)=delete;
    ~Channel(){discard();if(winsock_)WSACleanup();}
    bool attached() const {return socket_!=INVALID_SOCKET;}
    bool active() const {return active_;}
    void attach(uintptr_t inherited,unsigned version=1) {
        if(attached() || winsock_ || !inherited || inherited==static_cast<uintptr_t>(INVALID_SOCKET) || (version!=1 && version!=2))
            throw std::runtime_error("Invalid inherited secure transport handle");
        version_=static_cast<unsigned char>(version);
        WSADATA data{};
        if(WSAStartup(MAKEWORD(2,2),&data))throw std::runtime_error("Secure transport Winsock startup failed");
        winsock_=true;socket_=static_cast<SOCKET>(inherited);
        try {
            int type=0,size=sizeof(type);sockaddr_in peer{};int peerSize=sizeof(peer);
            if(getsockopt(socket_,SOL_SOCKET,SO_TYPE,reinterpret_cast<char*>(&type),&size) || type!=SOCK_STREAM ||
                getpeername(socket_,reinterpret_cast<sockaddr*>(&peer),&peerSize) || peer.sin_family!=AF_INET ||
                (ntohl(peer.sin_addr.s_addr)&0xff000000)!=0x7f000000)
                throw std::runtime_error("Secure transport requires an inherited connected loopback socket");
            if(!SetHandleInformation(reinterpret_cast<HANDLE>(socket_),HANDLE_FLAG_INHERIT,0))
                throw std::runtime_error("Cannot protect inherited secure transport handle");
            u_long mode=1;
            if(ioctlsocket(socket_,FIONBIO,&mode))throw std::runtime_error("Secure transport nonblocking mode failed");
            BOOL yes=TRUE;setsockopt(socket_,IPPROTO_TCP,TCP_NODELAY,reinterpret_cast<char*>(&yes),sizeof(yes));
        } catch(...) {discard();throw;}
    }
    void begin() {
        if(!attached() || eof_ || session_==UINT32_MAX)throw std::runtime_error("Secure transport process unavailable");
        if(active_)end();
        if(eof_)throw std::runtime_error("Secure transport process unavailable");
        ++session_;active_=true;closed_=false;failure_=0;plain_.clear();read_=0;
        ready_=version_==1;profile_.clear();
        queue(1);
    }
    void end() noexcept {
        if(!active_)return;
        active_=false;ready_=false;profile_.clear();
        try {if(!eof_){queue(3);flush();}}catch(...){discard();}
    }
    // Version 2 supplies only the authenticated public identity, never an invite.
    // It must be ready before the game constructs its identity-bound HELLO.
    bool ready() {
        pump();checkFailure();
        if(!active_ || closed_ || eof_)throw std::runtime_error("Secure session is closed");
        return ready_;
    }
    const std::string& profile() const {
        checkFailure();
        if(version_!=2 || !active_ || !ready_ || closed_ || eof_)throw std::runtime_error("Secure identity is unavailable");
        return profile_;
    }
    // Return-1 for local backpressure/would-block,0 for orderly session EOF.
    int send(const char* data,int size) {
        checkFailure();
        if(!active_ || closed_ || eof_)throw std::runtime_error("Secure session is closed");
        if(version_==2 && !ready_ && !ready())return-1;
        if(size<=0)return 0;
        const size_t count=(std::min)(chunk,static_cast<size_t>(size));
        flush();
        if(wireOut_.size()-written_+count+10>limit)return-1;
        queue(2,reinterpret_cast<const unsigned char*>(data),count);
        return static_cast<int>(count);
    }
    int receive(char* data,int capacity) {
        if(capacity<=0)throw std::runtime_error("Invalid secure receive capacity");
        pump();
        checkFailure();
        const size_t count=(std::min)(static_cast<size_t>(capacity),plain_.size()-read_);
        if(count){memcpy(data,plain_.data()+read_,count);read_+=count;return static_cast<int>(count);}
        if(closed_)return 0;
        if(eof_)throw std::runtime_error("Secure transport process disconnected");
        return-1;
    }
};
}
