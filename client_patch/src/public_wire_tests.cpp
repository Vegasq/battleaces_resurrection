// Authored wire fixtures shared in layout with tests/test_public_protocol.py.
#include "public_wire.hpp"
#include <cassert>
#include <iostream>
namespace q=ba_public_wire;
namespace c=ba_community_wire;
template<class F> void rejects(F call){bool rejected=false;try{call();}catch(const std::exception&){rejected=true;}assert(rejected);}
int main() {
    const uint64_t ticket=0x123456789abcdef0ull;
    const c::Deck deck={100,101,102,103,104,105,106,107};
    for(unsigned mode:{1u,2u,5u})for(uint32_t remaining:{0u,1u,29999u,30000u}) {
        auto packet=q::enter(7,ticket,mode,remaining,deck);
        c::Reader r(packet.payload);assert(packet.kind==58 && packet.payload.size()==51);
        assert(r.u32()==7 && r.u16()==1 && r.u64()==ticket && r.u8()==mode && r.u32()==remaining && r.deck()==deck);r.end();
    }
    rejects([&]{q::enter(0,ticket,1,30000,deck);});rejects([&]{q::enter(1,0,1,30000,deck);});
    rejects([&]{q::enter(1,ticket,4,30000,deck);});rejects([&]{q::enter(1,ticket,1,30001,deck);});
    for(auto packet:{q::ready(8,9,"authored_match"),q::returned(8,9,"authored_match")}) {
        c::Reader r(packet.payload);assert(r.u32()==8 && r.u16()==1 && r.u64()==9 && r.id()=="authored_match");r.end();
    }
    assert(q::cancel(8,9).payload.size()==14);
    for(unsigned char kind:{q::Enter,q::Cancel,q::Ready,q::Return}) {
        c::Writer w;w.number(8,4);w.number(kind,1);w.number(1,1);w.text("");w.text("offer");
        auto ack=std::get<c::Ack>(c::decode(c::AckKind,w.bytes));assert(ack.kind==kind && ack.success);
    }
    c::Writer status;status.number(1,2);status.number(9,8);status.number(q::Offered,1);status.number(5,1);
    status.number(30000,4);status.id("offer");status.text("");
    auto state=q::state(status.bytes);assert(state.ticket==9 && state.phase==q::Offered && state.mode==5 && state.elapsedMs==30000 && state.match=="offer");
    for(unsigned mode:{1u,2u,5u})for(unsigned slot=0;slot<q::participants(mode);++slot) {
        if(mode==5 && slot%2)continue;
        c::Writer w;w.number(1,2);w.number(ticket,8);w.number(mode,1);w.number(q::participants(mode),1);
        w.number(slot,1);w.number(mode==5 ? 5 : (1u<<q::participants(mode))-1,1);w.number(6,1);w.id("frozen");w.deck(deck);
        auto assignment=q::assignment(w.bytes);assert(assignment.ticket==ticket && assignment.mode==mode && assignment.slot==slot && assignment.deck==deck);
        for(size_t length=0;length<w.bytes.size();++length)rejects([&]{q::assignment(c::Bytes(w.bytes.begin(),w.bytes.begin()+length));});
        for(auto field:{0u,10u,11u,12u,13u,14u}) {
            auto bad=w.bytes;bad[field]=255;rejects([&]{q::assignment(bad);});
        }
        auto bad=w.bytes;std::fill(bad.begin()+2,bad.begin()+10,0);rejects([&]{q::assignment(bad);});
        bad=w.bytes;bad.push_back(0);rejects([&]{q::assignment(bad);});
    }
    for(unsigned count:{2u,4u}) {
        c::Writer w;w.number(17,4);w.number(count,1);
        for(unsigned slot=0;slot<count;++slot){w.number(slot+1,4);w.bytes.insert(w.bytes.end(),slot+1,static_cast<unsigned char>(slot+1));}
        auto frame=q::frame(w.bytes,count);assert(frame.number==17 && frame.inputs.size()==count && frame.inputs.back()==c::Bytes(count,static_cast<unsigned char>(count)));
        for(size_t length=0;length<w.bytes.size();++length)rejects([&]{q::frame(c::Bytes(w.bytes.begin(),w.bytes.begin()+length),count);});
        rejects([&]{q::frame(w.bytes,6-count);});
        auto bad=w.bytes;bad.push_back(0);rejects([&]{q::frame(bad,count);});
        bad=w.bytes;bad[4]=3;rejects([&]{q::frame(bad,count);});
        bad=w.bytes;bad[5]=0;rejects([&]{q::frame(bad,count);});
        bad=w.bytes;bad[7]=1;rejects([&]{q::frame(bad,count);});
        bad=w.bytes;bad[3]=128;rejects([&]{q::frame(bad,count);});
        c::Writer maximum;maximum.number(0x7fffffff,4);maximum.number(count,1);
        for(unsigned slot=0;slot<count;++slot){maximum.number(q::maxInput,4);maximum.bytes.insert(maximum.bytes.end(),q::maxInput,static_cast<unsigned char>(slot));}
        auto full=q::frame(maximum.bytes,count);assert(full.inputs.back().size()==q::maxInput);
        maximum.bytes.push_back(0);rejects([&]{q::frame(maximum.bytes,count);});
    }
    for(size_t length=0;length<status.bytes.size();++length)rejects([&]{q::state(c::Bytes(status.bytes.begin(),status.bytes.begin()+length));});
    auto bad=status.bytes;bad[10]=7;rejects([&]{q::state(bad);});
    bad=status.bytes;bad[11]=4;rejects([&]{q::state(bad);});
    std::cout << "public queue v1 ticket, topology, shared ACK and bounded four-seat frame tests passed\n";
}
