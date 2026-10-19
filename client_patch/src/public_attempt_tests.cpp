#include "public_attempt.hpp"
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
    std::cout << "public client ticket/connection, deadline, stale proposal, cancel and ambiguous READY tests passed\n";
}
