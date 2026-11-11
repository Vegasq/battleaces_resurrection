#pragma once
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace ba_native_worker_wire {
using Bytes=std::vector<uint8_t>;
struct Log {int32_t kind=0;Bytes text;};
struct Response {int32_t result=0;std::vector<Log> logs;Bytes data;};
struct Header {uint8_t opcode=0;uint16_t flags=0;uint32_t requestId=0,payloadLength=0;};
constexpr size_t headerSize=16,maxPayload=32u*1024u*1024u,maxLogs=256,maxLogBytes=16u*1024u;
constexpr uint8_t version=1,shutdownOpcode=127;
class ProtocolError:public std::runtime_error {public:using std::runtime_error::runtime_error;};
class HostError:public ProtocolError {public:using ProtocolError::ProtocolError;};
inline void require(bool value,const char* message){if(!value)throw ProtocolError(message);}
inline bool nativeOpcode(uint8_t op) {
    return (op>=1 && op<=9) || op==11 || op==13 || op==15 ||
        (op>=17 && op<=19) || (op>=21 && op<=24) || (op>=64 && op<=71) || op==76 || op==shutdownOpcode;
}
inline void append32(Bytes& out,uint32_t value){for(unsigned i=0;i<4;++i)out.push_back(static_cast<uint8_t>(value>>(i*8)));}
inline void append64(Bytes& out,uint64_t value){for(unsigned i=0;i<8;++i)out.push_back(static_cast<uint8_t>(value>>(i*8)));}
inline uint32_t read32(const Bytes& in,size_t& at) {
    require(at<=in.size() && in.size()-at>=4,"truncated worker uint32");uint32_t value=0;
    for(unsigned i=0;i<4;++i)value|=uint32_t(in[at++])<<(i*8);return value;
}
inline uint64_t read64(const Bytes& in,size_t& at) {
    require(at<=in.size() && in.size()-at>=8,"truncated worker uint64");uint64_t value=0;
    for(unsigned i=0;i<8;++i)value|=uint64_t(in[at++])<<(i*8);return value;
}
inline Bytes readBytes(const Bytes& in,size_t& at,size_t count) {
    require(at<=in.size() && count<=in.size()-at,"truncated worker bytes");
    Bytes result(in.begin()+at,in.begin()+at+count);at+=count;return result;
}
inline bool utf8(const Bytes& bytes) {
    size_t at=0;
    while(at<bytes.size()) {
        const auto first=bytes[at++];if(first<0x80)continue;
        unsigned extra;uint32_t value,minimum;
        if(first>=0xc2 && first<=0xdf){extra=1;value=first&31;minimum=0x80;}
        else if(first>=0xe0 && first<=0xef){extra=2;value=first&15;minimum=0x800;}
        else if(first>=0xf0 && first<=0xf4){extra=3;value=first&7;minimum=0x10000;}
        else return false;
        if(bytes.size()-at<extra)return false;
        for(unsigned i=0;i<extra;++i){const auto next=bytes[at++];if((next&0xc0)!=0x80)return false;value=(value<<6)|(next&63);}
        if(value<minimum || value>0x10ffff || (value>=0xd800 && value<=0xdfff))return false;
    }
    return true;
}
inline Bytes encodeHeader(const Header& value,bool response) {
    const uint8_t op=response?static_cast<uint8_t>(value.opcode&0x7f):value.opcode;
    require(nativeOpcode(op) && (response?(value.opcode&0x80)!=0:(value.opcode&0x80)==0),"invalid worker opcode");
    require(value.flags<=(response?1:0),"invalid worker flags");
    require(value.requestId!=0 && value.payloadLength<=maxPayload,"invalid worker ID/size");
    Bytes out{'B','A','P','W',version,value.opcode,static_cast<uint8_t>(value.flags),static_cast<uint8_t>(value.flags>>8)};
    append32(out,value.requestId);append32(out,value.payloadLength);return out;
}
inline Header decodeHeader(const uint8_t* raw,size_t length,bool response) {
    require(raw && length==headerSize,"worker header must be16bytes");
    require(raw[0]=='B' && raw[1]=='A' && raw[2]=='P' && raw[3]=='W' && raw[4]==version,"worker magic/version differs");
    Bytes bytes(raw,raw+length);size_t at=8;
    Header value{raw[5],static_cast<uint16_t>(raw[6]|uint16_t(raw[7])<<8),read32(bytes,at),read32(bytes,at)};
    encodeHeader(value,response);return value;
}
inline Header decodeHeader(const Bytes& raw,bool response){return decodeHeader(raw.data(),raw.size(),response);}
inline Bytes encodeRequest(uint8_t opcode,uint32_t requestId,const Bytes& payload) {
    require(payload.size()<=maxPayload,"worker request payload exceeds32MiB");
    auto out=encodeHeader({opcode,0,requestId,static_cast<uint32_t>(payload.size())},false);
    out.insert(out.end(),payload.begin(),payload.end());return out;
}
inline Bytes responsePayload(const Response& response) {
    require(response.logs.size()<=maxLogs,"worker log count exceeds256");
    Bytes out;append32(out,static_cast<uint32_t>(response.result));append32(out,static_cast<uint32_t>(response.logs.size()));
    for(const auto& log:response.logs) {
        require(log.text.size()<=maxLogBytes && utf8(log.text),"invalid worker log UTF8/length");
        require(out.size()<=maxPayload-8-log.text.size(),"worker logs exceed payload cap");
        append32(out,static_cast<uint32_t>(log.kind));append32(out,static_cast<uint32_t>(log.text.size()));
        out.insert(out.end(),log.text.begin(),log.text.end());
    }
    require(response.data.size()<=maxPayload-out.size(),"worker response exceeds32MiB");
    out.insert(out.end(),response.data.begin(),response.data.end());return out;
}
inline Bytes encodeResponse(uint8_t opcode,uint32_t requestId,const Response& response) {
    require(nativeOpcode(opcode),"invalid worker response operation");
    auto payload=responsePayload(response);
    auto out=encodeHeader({static_cast<uint8_t>(opcode|0x80),0,requestId,static_cast<uint32_t>(payload.size())},true);
    out.insert(out.end(),payload.begin(),payload.end());return out;
}
inline Bytes encodeError(uint8_t opcode,uint32_t requestId,const Bytes& error) {
    require(nativeOpcode(opcode),"invalid worker error operation");
    require(utf8(error) && error.size()<=maxPayload-12,"invalid worker error UTF8/size");
    Bytes payload;append32(payload,0xffffffff);append32(payload,0);append32(payload,static_cast<uint32_t>(error.size()));
    payload.insert(payload.end(),error.begin(),error.end());
    auto out=encodeHeader({static_cast<uint8_t>(opcode|0x80),1,requestId,static_cast<uint32_t>(payload.size())},true);
    out.insert(out.end(),payload.begin(),payload.end());return out;
}
inline Response decodeResponse(const Header& header,const Bytes& payload,uint8_t expectedOpcode,uint32_t expectedId) {
    encodeHeader(header,true);
    require(header.opcode==static_cast<uint8_t>(expectedOpcode|0x80) && header.requestId==expectedId,
            "worker response opcode/ID differs");
    require(payload.size()==header.payloadLength && payload.size()>=8,"worker response payload length differs");
    size_t at=0;Response out;out.result=static_cast<int32_t>(read32(payload,at));const auto count=read32(payload,at);
    require(count<=maxLogs,"worker response log count exceeds256");out.logs.reserve(count);
    for(uint32_t i=0;i<count;++i) {
        Log log;log.kind=static_cast<int32_t>(read32(payload,at));const auto length=read32(payload,at);
        require(length<=maxLogBytes,"worker response log exceeds16KiB");log.text=readBytes(payload,at,length);
        require(utf8(log.text),"worker log is not UTF8");out.logs.push_back(std::move(log));
    }
    if(header.flags) {
        require(out.result==-1,"worker error response result must be-1");
        const auto length=read32(payload,at);const auto error=readBytes(payload,at,length);
        require(at==payload.size() && utf8(error),"malformed worker error response");
        throw HostError(std::string(error.begin(),error.end()));
    }
    out.data=readBytes(payload,at,payload.size()-at);return out;
}
}
