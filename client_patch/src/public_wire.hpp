#pragma once
// Authored public queue v1 codec. No Unity objects, assets or network access.
#include "community_wire.hpp"

namespace ba_public_wire {
using ba_community_wire::Bytes;
using ba_community_wire::Deck;
using ba_community_wire::Packet;
using ba_community_wire::Reader;
using ba_community_wire::Writer;
using ba_community_wire::require;
enum Kind : unsigned char { Enter=58,Cancel,Ready,Return,StateKind,MatchKind,FrameKind };
enum Phase : unsigned char { Waiting,Offered,Preparing,Loading,Running,Results,Retired };
constexpr unsigned version=1,maxInput=65536,maxWaitMs=30000;
inline unsigned participants(unsigned mode) {
    require(mode==1 || mode==2 || mode==5,"unsupported public mode");
    return mode==1 ? 2 : 4;
}
inline Writer request(uint32_t id,uint64_t ticket) {
    require(ticket!=0,"invalid public ticket");
    auto w=ba_community_wire::request(id);w.number(version,2);w.number(ticket,8);return w;
}
inline Packet enter(uint32_t id,uint64_t ticket,unsigned mode,uint32_t waitMs,const Deck& deck) {
    participants(mode);require(waitMs<=maxWaitMs,"public deadline exceeds limit");
    auto w=request(id,ticket);w.number(mode,1);w.number(waitMs,4);w.deck(deck);return {Enter,std::move(w.bytes)};
}
inline Packet cancel(uint32_t id,uint64_t ticket) {
    auto w=request(id,ticket);return {Cancel,std::move(w.bytes)};
}
inline Packet ready(uint32_t id,uint64_t ticket,const std::string& match) {
    auto w=request(id,ticket);w.id(match);return {Ready,std::move(w.bytes)};
}
inline Packet returned(uint32_t id,uint64_t ticket,const std::string& match) {
    auto w=request(id,ticket);w.id(match);return {Return,std::move(w.bytes)};
}
inline uint64_t header(Reader& r) {
    require(r.u16()==version,"unsupported public protocol version");
    auto ticket=r.u64();require(ticket!=0,"invalid public ticket");return ticket;
}
struct State {
    uint64_t ticket=0;unsigned char phase=Waiting,mode=0;uint32_t elapsedMs=0;
    std::string match,reason;
};
inline State state(const Bytes& bytes) {
    Reader r(bytes);State value;value.ticket=header(r);value.phase=r.u8();value.mode=r.u8();
    value.elapsedMs=r.u32();value.match=r.id(true);value.reason=r.text();r.end();
    require(value.phase<=Retired,"invalid public queue phase");participants(value.mode);return value;
}
struct Assignment {
    uint64_t ticket=0;unsigned char mode=0,count=0,slot=0,humanMask=0,inputWindow=0;
    std::string match;Deck deck{};
};
inline Assignment assignment(const Bytes& bytes) {
    Reader r(bytes);Assignment value;value.ticket=header(r);value.mode=r.u8();value.count=r.u8();
    value.slot=r.u8();value.humanMask=r.u8();value.inputWindow=r.u8();value.match=r.id();value.deck=r.deck();r.end();
    require(value.count==participants(value.mode) && value.slot<value.count,"public assignment topology differs");
    const unsigned allowed=value.mode==5 ? 5 : ((1u<<value.count)-1);
    require((value.humanMask&(1u<<value.slot))!=0 && (value.humanMask&~allowed)==0,"invalid public human assignment");
    require(value.inputWindow>=2 && value.inputWindow<=12,"public input window bound");return value;
}
struct Frame {uint32_t number=0;std::vector<Bytes> inputs;};
inline Frame frame(const Bytes& bytes,unsigned count) {
    require((count==2 || count==4) && bytes.size()>=5 && bytes.size()<=5+count*(4+maxInput),"public frame size/count bound");
    // A four-seat frame can exceed the control reader's 32 KiB limit.
    size_t offset=0;
    auto u32=[&]() {
        require(bytes.size()-offset>=4,"truncated public frame field");uint32_t value=0;
        for(unsigned i=0;i<4;++i)value|=uint32_t(bytes[offset++])<<(8*i);return value;
    };
    Frame value;value.number=u32();
    require(value.number<0x80000000u && bytes[offset++]==count,"public frame number/count mismatch");
    for(unsigned slot=0;slot<count;++slot) {
        const auto size=u32();require(size && size<=maxInput && size<=bytes.size()-offset,"public frame input bound");
        value.inputs.emplace_back(bytes.begin()+offset,bytes.begin()+offset+size);offset+=size;
    }
    require(offset==bytes.size(),"extra public frame bytes");return value;
}
}
