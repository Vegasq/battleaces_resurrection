#pragma once
// Authored community control v1 codec. No Unity objects, game assets or OS API.
#include <algorithm>
#include <array>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <variant>
#include <vector>

namespace ba_community_wire {
using Bytes=std::vector<unsigned char>;
using Deck=std::array<uint32_t,8>;
enum Kind : unsigned char { Hello=40,WelcomeKind,DirectoryKind,Create,LobbyKind,Invite,
    Reply,Cancel,Start,Ready,Leave,SetDeck,Return,AckKind,InvitationKind,Refresh,AbortedKind,Practice };
enum Phase : unsigned char { None,Open,Starting,Loading,Running,Results };
constexpr unsigned version=1,gameVersion=3,maxPlayers=136;
inline void require(bool condition,const char* message) {
    if(!condition)throw std::runtime_error(message);
}
inline bool command(unsigned char kind) {
    return kind==Create || (kind>=Invite && kind<=Return) || kind==Refresh || kind==Practice;
}
inline void key(const std::string& text,bool empty=false) {
    require((empty || !text.empty()) && text.size()<=48,"invalid community key size");
    for(unsigned char c:text)require((c>='A'&&c<='Z') || (c>='a'&&c<='z') ||
        (c>='0'&&c<='9') || c=='_' || c=='-',"invalid community key");
}
inline size_t utf8(const std::string& text) {
    size_t characters=0;
    for(size_t i=0;i<text.size();++characters) {
        const unsigned char lead=static_cast<unsigned char>(text[i++]);
        require(lead>=32,"community text contains control characters");
        if(lead<128)continue;
        unsigned count=0;uint32_t value=0,minimum=0;
        if(lead>=0xc2 && lead<=0xdf){count=1;value=lead&31;minimum=0x80;}
        else if(lead>=0xe0 && lead<=0xef){count=2;value=lead&15;minimum=0x800;}
        else if(lead>=0xf0 && lead<=0xf4){count=3;value=lead&7;minimum=0x10000;}
        else throw std::runtime_error("invalid community UTF8");
        require(count<=text.size()-i,"truncated community UTF8");
        while(count--) {
            const unsigned char next=static_cast<unsigned char>(text[i++]);
            require((next&0xc0)==0x80,"invalid community UTF8 continuation");
            value=(value<<6)|(next&63);
        }
        require(value>=minimum && value<=0x10ffff && !(value>=0xd800&&value<=0xdfff),
            "invalid community Unicode scalar");
    }
    return characters;
}
struct Reader {
    const Bytes& bytes;size_t offset=0;
    explicit Reader(const Bytes& value):bytes(value) {
        require(bytes.size()<=32768,"community message too large");
    }
    uint64_t number(size_t width) {
        require(width<=8 && width<=bytes.size()-offset,"truncated community field");
        uint64_t value=0;for(size_t i=0;i<width;++i)value|=uint64_t(bytes[offset++])<<(8*i);
        return value;
    }
    uint8_t u8(){return static_cast<uint8_t>(number(1));}
    uint16_t u16(){return static_cast<uint16_t>(number(2));}
    uint32_t u32(){return static_cast<uint32_t>(number(4));}
    uint64_t u64(){return number(8);}
    bool flag(){const auto value=u8();require(value<=1,"invalid community boolean");return value!=0;}
    std::string text(size_t maximum=128) {
        const size_t length=u16();require(length<=maximum && length<=bytes.size()-offset,"community string bound");
        std::string result(bytes.begin()+offset,bytes.begin()+offset+length);offset+=length;
        utf8(result);return result;
    }
    std::string id(bool empty=false){auto value=text(48);key(value,empty);return value;}
    Deck deck(){Deck value{};for(auto& item:value)item=u32();return value;}
    void end(){require(offset==bytes.size(),"extra community fields");}
};
struct Writer {
    Bytes bytes;
    void number(uint64_t value,size_t width){for(size_t i=0;i<width;++i)bytes.push_back(static_cast<unsigned char>(value>>(8*i)));}
    void text(const std::string& value){require(value.size()<=128,"community string too long");utf8(value);number(value.size(),2);bytes.insert(bytes.end(),value.begin(),value.end());}
    void id(const std::string& value){key(value);text(value);}
    void deck(const Deck& value){for(auto item:value)number(item,4);}
};
struct Welcome {std::string profile;Deck deck;};
struct Player {std::string profile,name;unsigned char status;bool invitable;};
struct Directory {uint64_t revision;std::vector<Player> players;};
struct Member {std::string profile;Deck deck;bool ready,returned;};
struct Lobby {
    uint64_t revision=0;unsigned char phase=None;uint32_t epoch=0;
    std::string id,host,match,reason;std::vector<Member> members;
};
struct Ack {uint32_t request;unsigned char kind;bool success;std::string reason,object;};
struct Invitation {unsigned char status;uint32_t milliseconds;std::string id,lobby,sender,target;};
struct Aborted {std::string match,reason;};
using Event=std::variant<Welcome,Directory,Lobby,Ack,Invitation,Aborted>;
inline Event decode(unsigned char kind,const Bytes& bytes) {
    Reader r(bytes);Event result;
    switch(kind) {
    case WelcomeKind: {
        require(r.u16()==version && r.u16()==gameVersion,"unsupported community welcome version");
        Welcome value;value.profile=r.id();value.deck=r.deck();result=std::move(value);break;
    }
    case DirectoryKind: {
        Directory value;value.revision=r.u64();const auto count=r.u16();
        require(count<=maxPlayers,"community directory capacity");
        for(unsigned i=0;i<count;++i) {
            Player row;row.profile=r.id();row.name=r.text();row.status=r.u8();row.invitable=r.flag();
            require(!row.name.empty() && utf8(row.name)<=32,"community display name bound");
            require(row.status<=3 && (!row.invitable || row.status==0),"invalid community availability");
            require(value.players.empty() || value.players.back().profile<row.profile,"unsorted or duplicate community profile");
            value.players.push_back(std::move(row));
        }
        result=std::move(value);break;
    }
    case LobbyKind: {
        Lobby value;value.revision=r.u64();value.phase=r.u8();value.epoch=r.u32();
        require(value.phase<=Results,"invalid community lobby phase");
        value.id=r.id(true);value.host=r.id(true);value.match=r.id(true);value.reason=r.text(1024);
        const auto count=r.u8();require(count<=2,"community lobby member capacity");
        bool foundHost=false;
        for(unsigned i=0;i<count;++i) {
            Member member;member.profile=r.id();member.deck=r.deck();member.ready=r.flag();member.returned=r.flag();
            for(const auto& previous:value.members)require(previous.profile!=member.profile,"duplicate community member");
            foundHost|=member.profile==value.host;value.members.push_back(std::move(member));
        }
        if(value.phase==None)require(!value.revision && !value.epoch && value.id.empty() && value.host.empty() && value.match.empty() && !count,"invalid empty community lobby");
        else require(value.revision && !value.id.empty() && foundHost && count,"invalid community lobby ownership");
        if(value.phase>=Running)require(!value.match.empty(),"community match identity missing");
        result=std::move(value);break;
    }
    case AckKind: {
        Ack value;value.request=r.u32();value.kind=r.u8();value.success=r.flag();value.reason=r.text(1024);value.object=r.id(true);
        require(value.request && command(value.kind),"invalid community acknowledgement");result=std::move(value);break;
    }
    case InvitationKind: {
        Invitation value;value.status=r.u8();value.milliseconds=r.u32();
        require(value.status<=5 && value.milliseconds<=30000,"invalid community invitation status/expiry");
        value.id=r.id();value.lobby=r.id();value.sender=r.id();value.target=r.id();
        require(value.sender!=value.target,"community self invitation");result=std::move(value);break;
    }
    case AbortedKind: {Aborted value;value.match=r.id();value.reason=r.text(1024);result=std::move(value);break;}
    default:throw std::runtime_error("unknown community server message");
    }
    r.end();return result;
}
struct Packet {unsigned char kind;Bytes payload;};
inline Writer request(uint32_t id){require(id!=0,"community request ID must be positive");Writer w;w.number(id,4);return w;}
inline Packet create(uint32_t id){auto w=request(id);w.number(1,1);return {Create,std::move(w.bytes)};}
inline Packet invite(uint32_t id,const std::string& profile){auto w=request(id);w.id(profile);return {Invite,std::move(w.bytes)};}
inline Packet reply(uint32_t id,const std::string& invitation,bool accept){auto w=request(id);w.id(invitation);w.number(accept,1);return {Reply,std::move(w.bytes)};}
inline Packet cancel(uint32_t id,const std::string& invitation){auto w=request(id);w.id(invitation);return {Cancel,std::move(w.bytes)};}
inline Packet start(uint32_t id,const Lobby& lobby){auto w=request(id);w.id(lobby.id);w.number(lobby.revision,8);return {Start,std::move(w.bytes)};}
inline Packet ready(uint32_t id,const Lobby& lobby,bool value){auto w=request(id);w.id(lobby.id);w.number(lobby.epoch,4);w.number(value,1);return {Ready,std::move(w.bytes)};}
inline Packet leave(uint32_t id,const std::string& lobby){auto w=request(id);w.id(lobby);return {Leave,std::move(w.bytes)};}
inline Packet setDeck(uint32_t id,const Deck& deck){auto w=request(id);w.deck(deck);return {SetDeck,std::move(w.bytes)};}
inline Packet returned(uint32_t id,const std::string& match){auto w=request(id);w.id(match);return {Return,std::move(w.bytes)};}
inline Packet refresh(uint32_t id){auto w=request(id);return {Refresh,std::move(w.bytes)};}
inline Packet practice(uint32_t id,bool active){auto w=request(id);w.number(active,1);return {Practice,std::move(w.bytes)};}
}
