#include "solo_ai_policy.hpp"
#include <cassert>
#include <iostream>
namespace ai=ba_solo_ai;
namespace q=ba_public_wire;
using ba_public_attempt::Attempt;
static const q::Deck deck={1,2,3,4,5,6,7,8};
static q::State state(unsigned mode,unsigned char phase,const char* reason="",const char* match="offer") {
    q::State value;value.ticket=9;value.mode=static_cast<unsigned char>(mode);
    value.phase=phase;value.reason=reason;value.match=match;return value;
}
static void offered(Attempt& attempt,const char* reason=ai::offerReason) {
    attempt.enter(7);attempt.state(7,state(attempt.mode,q::Waiting,"",""));
    attempt.state(7,state(attempt.mode,q::Offered,reason));
}
int main() {
    assert(ai::parseHost()==ai::Host::Local && ai::parseHost("local")==ai::Host::Local);
    assert(ai::parseHost("server")==ai::Host::Server);
    for(const char* invalid:{"","LOCAL","remote","local ","server2"}) {
        bool rejected=false;try{ai::parseHost(invalid);}catch(const std::runtime_error&){rejected=true;}
        assert(rejected);
    }
    // A marked ONE-human offer can switch only after the ticket is retired.
    // Empty/multihuman offers,old servers and server preference stay online.
    for(unsigned mode:{1u,2u,5u}) {
        Attempt searching(9,mode,deck,0);ai::Handoff route(ai::Host::Local);
        assert(route.observe(searching)==ai::Action::Online && !route.pending());
        searching.enter(7);searching.state(7,state(mode,q::Waiting,"",""));
        assert(route.observe(searching)==ai::Action::Online && !route.pending());
        // All three public modes must first search for humans,including2vAI's
        // possible human teammate. LocalAI is chosen from the actual offer.
        Attempt attempt(9,mode,deck,0);offered(attempt);
        ai::Handoff handoff(ai::Host::Local);
        assert(handoff.observe(attempt)==ai::Action::CancelOffer && handoff.pending());
        assert(!attempt.readySent && !attempt.committed && !attempt.assigned);
        for(int i=0;i<3;++i)assert(handoff.observe(attempt)==ai::Action::AwaitRetirement);
        attempt.state(7,state(mode,q::Retired,"player cancelled search",""));
        assert(handoff.observe(attempt)==ai::Action::StartLocal);
        assert(attempt.ticket==9 && attempt.deck==deck && !attempt.readySent);

        Attempt online(9,mode,deck,0);offered(online);
        ai::Handoff server(ai::Host::Server);
        assert(server.observe(online)==ai::Action::Online && !server.pending());
        for(const char* reason:{"","ordinary human offer","solo_ai_offer_more"}) {
            Attempt human(9,mode,deck,0);offered(human,reason);
            ai::Handoff local(ai::Host::Local);
            assert(local.observe(human)==ai::Action::Online && !local.pending());
        }
    }
    // Cancellation after a policy CANCEL still cannot turn into a local game.
    Attempt cancelled(9,1,deck,0);offered(cancelled);ai::Handoff user(ai::Host::Local);
    assert(user.observe(cancelled)==ai::Action::CancelOffer);cancelled.cancelled=true;
    cancelled.state(7,state(1,q::Retired,"search cancelled",""));
    assert(user.observe(cancelled)==ai::Action::Online && !user.pending() && !cancelled.mayFallback());

    Attempt ready(9,1,deck,0);offered(ready);ready.ready();
    ai::Handoff ambiguous(ai::Host::Local);
    assert(ambiguous.observe(ready)==ai::Action::Online && !ambiguous.pending());
    ready.state(7,state(1,q::Preparing,ai::offerReason));
    assert(ambiguous.observe(ready)==ai::Action::Online);
    ready.state(7,state(1,q::Retired,"proposal retired"));
    assert(ambiguous.observe(ready)==ai::Action::Online); // Policy never owned that READY.

    Attempt waiting(9,1,deck,0);waiting.enter(7);
    waiting.state(7,state(1,q::Waiting,ai::offerReason,""));ai::Handoff phaseGuard(ai::Host::Local);
    assert(phaseGuard.observe(waiting)==ai::Action::Online && !phaseGuard.pending());
    for(unsigned boundary:{0u,1u,2u,3u}) {
        Attempt late(9,2,deck,0);offered(late);ai::Handoff guarded(ai::Host::Local);
        assert(guarded.observe(late)==ai::Action::CancelOffer);
        if(boundary==0)late.readySent=true;
        if(boundary==1)late.committed=true;
        if(boundary==2)late.assigned=true;
        assert(guarded.observe(late,boundary==3)==ai::Action::Online && !guarded.pending());
    }

    // A replacement proposal may contain another human. Retire the attempted
    // transfer after CANCEL instead of silently converting the new proposal.
    Attempt changed(9,2,deck,0);offered(changed);ai::Handoff replacement(ai::Host::Local);
    assert(replacement.observe(changed)==ai::Action::CancelOffer);
    changed.state(7,state(2,q::Waiting,"proposal changed",""));
    assert(replacement.observe(changed)==ai::Action::AwaitRetirement);
    changed.state(7,state(2,q::Offered,"","human-offer"));
    assert(replacement.observe(changed)==ai::Action::AwaitRetirement);
    changed.state(7,state(2,q::Retired,"search cancelled",""));
    assert(replacement.observe(changed)==ai::Action::RetireOnly);

    // Full human loadout remains frozen throughout the transfer decision.
    ba_community_wire::Loadout selected;selected.deck=deck;selected.full=true;
    for(size_t i=0;i<17;++i)selected.cosmetics.slots[i]={static_cast<uint32_t>(i+1),static_cast<uint32_t>(100+i)};
    Attempt appearance(9,2,selected,0);offered(appearance);ai::Handoff frozen(ai::Host::Local);
    assert(frozen.observe(appearance)==ai::Action::CancelOffer);
    appearance.state(7,state(2,q::Retired,"search cancelled",""));
    assert(frozen.observe(appearance)==ai::Action::StartLocal && appearance.full && appearance.cosmetics==selected.cosmetics);
    std::cout<<"Solo AI host preference,marked-offer cancellation,retirement,commit safety and frozen loadout tests passed\n";
}
