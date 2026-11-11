#include "public_attempt.hpp"
#include "../checkpoint/native_worker_wire.hpp"
#include <cassert>
#include <iostream>
using ba_public_attempt::Attempt;
namespace q=ba_public_wire;
template<class F> void rejects(F call){bool rejected=false;try{call();}catch(const std::exception&){rejected=true;}assert(rejected);}
q::State state(uint64_t ticket,unsigned char phase,const char* match="offer") {
    q::State value;value.ticket=ticket;value.mode=2;value.phase=phase;value.match=match;return value;
}
int main() {
    const q::Deck deck={1,2,3,4,5,6,7,8};
    Attempt a(9,2,deck,1000);assert(a.remaining(1000)==30000 && a.remaining(30999)==1 && a.remaining(31000)==0);
    a.enter(4);assert(a.mayFallback());
    assert(!a.state(3,state(9,q::Offered)));assert(!a.state(4,state(8,q::Offered)));
    rejects([&]{a.state(4,state(10,q::Offered));});
    a.state(4,state(9,q::Waiting,""));a.state(4,state(9,q::Offered));a.ready();
    assert(!a.mayFallback());rejects([&]{a.ready();});
    rejects([&]{a.state(4,state(9,q::Offered,"different"));});
    a.state(4,state(9,q::Waiting,""));assert(a.mayFallback() && !a.readySent && a.remaining(31000)==0);
    a.state(4,state(9,q::Offered,"next"));assert(!a.readySent); // Old READY ACK cannot belong to this offer.
    a.ready();a.state(4,state(9,q::Preparing,"next"));
    rejects([&]{a.state(4,state(9,q::Waiting,""));});
    q::Assignment assigned;assigned.ticket=9;assigned.mode=2;assigned.count=4;assigned.slot=2;assigned.humanMask=5;
    assigned.inputWindow=6;assigned.match="next";assigned.deck=deck;
    auto wrong=assigned;wrong.deck[0]=10;rejects([&]{a.assignment(4,wrong);});
    assert(a.assignment(4,assigned));assert(!a.mayFallback());rejects([&]{a.assignment(4,assigned);});
    a.state(4,state(9,q::Loading,"next"));a.state(4,state(9,q::Running,"next"));
    rejects([&]{a.state(4,state(9,q::Retired,"next"));});
    a.state(4,state(9,q::Results,"next"));a.state(4,state(9,q::Retired,"next"));
    assert(!a.state(4,state(9,q::Loading,"next")) && !a.mayFallback());
    Attempt cancelled(10,2,deck,0);cancelled.enter(4);cancelled.state(4,state(10,q::Offered));cancelled.ready();
    cancelled.cancelled=true;cancelled.state(4,state(10,q::Preparing));assigned.ticket=10;assigned.match="offer";
    assert(!cancelled.assignment(4,assigned) && !cancelled.mayFallback());
    Attempt failure(11,2,deck,0);failure.enter(5);failure.state(5,state(11,q::Offered));failure.ready();
    failure.state(5,state(11,q::Preparing));assert(!failure.mayFallback());
    failure.state(5,state(11,q::Retired));assert(failure.mayFallback());
    ba_community_wire::Loadout selection;selection.deck=deck;selection.full=true;
    for(size_t i=0;i<17;++i)selection.cosmetics.slots[i]={static_cast<uint32_t>(i+1),static_cast<uint32_t>(100+i)};
    Attempt appearance(12,2,selection,0);appearance.enter(6);appearance.state(6,state(12,q::Offered));appearance.ready();appearance.state(6,state(12,q::Preparing));
    assigned.ticket=12;assigned.match="offer";rejects([&]{appearance.assignment(6,assigned);});
    assigned.full=true;assigned.cosmetics=selection.cosmetics;assigned.cosmetics.slots[0].second=999;
    rejects([&]{appearance.assignment(6,assigned);});assigned.cosmetics=selection.cosmetics;
    auto other=assigned;other.cosmetics.catalog[0]=1;rejects([&]{appearance.assignment(6,other);});
    assert(appearance.assignment(6,assigned));
    // Use the actual public ENTER/OFFER/READY/commit/assignment transitions.
    Attempt solo(13,1,deck,0);solo.enter(7);
    auto event=state(13,q::Offered,"solo");event.mode=1;
    solo.state(7,event);solo.ready();event.phase=q::Preparing;solo.state(7,event);
    q::Assignment bot;bot.ticket=13;bot.mode=1;bot.count=2;bot.slot=0;bot.humanMask=1;
    bot.inputWindow=6;bot.match="solo";bot.deck=deck;
    assert(!solo.ownsServerAiPrediction(7,"solo"));
    assert(solo.assignment(7,bot) && solo.ownsServerAiPrediction(7,"solo"));
    assert(!solo.ownsServerAiPrediction(8,"solo") && !solo.ownsServerAiPrediction(7,"old"));
    for(unsigned variant=0;variant<17;++variant) {
        auto changed=solo;
        switch(variant) {
            case 0:changed.cancelled=true;break;case 1:changed.retired=true;break;
            case 2:changed.entered=false;break;case 3:changed.readySent=false;break;
            case 4:changed.committed=false;break;case 5:changed.assigned=false;break;
            case 6:changed.mode=5;break;case 7:changed.seat.mode=2;break;
            case 8:changed.seat.count=4;break;case 9:changed.seat.slot=1;break;
            case 10:changed.seat.humanMask=3;break;case 11:changed.seat.ticket=12;break;
            case 12:changed.seat.match="old";break;case 13:changed.seat.deck[0]=99;break;
            case 14:changed.phase=q::Offered;break;case 15:changed.ticket=0;break;
            case 16:changed.seat.full=true;break;
        }
        assert(!changed.ownsServerAiPrediction(7,"solo"));
    }
    event.phase=q::Running;solo.state(7,event);assert(solo.ownsServerAiPrediction(7,"solo"));
    event.phase=q::Results;solo.state(7,event);assert(solo.ownsServerAiPrediction(7,"solo"));
    event.phase=q::Retired;solo.state(7,event);assert(!solo.ownsServerAiPrediction(7,"solo"));
    namespace worker=ba_native_worker_wire;
    worker::Bytes roster;worker::append64(roster,1);worker::append32(roster,0);
    const auto request=worker::encodeRequest(76,1,roster);
    assert(worker::decodeHeader(request.data(),16,false).opcode==76);
    for(uint8_t op=72;op<76;++op)rejects([&]{worker::encodeRequest(op,1,roster);});
    std::cout << "public client ticket/connection, deadline, stale proposal, cancel and ambiguous READY tests passed\n";
}
