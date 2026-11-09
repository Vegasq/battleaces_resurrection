#include "prediction_presentation_policy.hpp"
#include <functional>
#include <iostream>
#include <vector>

namespace p=ba_prediction_presentation;
static void check(bool result,const char* message) {
    if(!result)throw std::runtime_error(message);
}
static void rejects(const std::function<void()>& action) {
    bool rejected=false;try{action();}catch(const std::runtime_error&){rejected=true;}
    check(rejected,"invalid presentation evidence accepted");
}
static const p::Terminal end40{40,1,0,0x123456789abcdef0ULL};
static const p::Terminal different40{40,0,2,0x1111222233334444ULL};

static void delayedConfirmation() {
    p::TerminalGate gate;gate.reset(1);
    gate.confirmed(1,30,std::nullopt);
    gate.presented(1,40,end40);
    check(!gate.takeReady(1),"speculative game-over emitted before confirmation");
    // Original transition logic would fire at40. The displayed history is
    // already ended->ended by the time delayed authority reaches40.
    for(int32_t frame=41;frame<=48;++frame) {
        gate.presented(1,frame,end40);
        gate.confirmed(1,frame-10,std::nullopt);
        check(!gate.takeReady(1),"intermediate confirmation emitted game-over");
    }
    gate.confirmed(1,40,end40);
    check(gate.takeReady(1)==end40,"delayed terminal confirmation was lost");
    check(!gate.takeReady(1),"terminal event emitted twice");
    gate.confirmed(1,45,end40);gate.presented(1,49,end40);
    check(!gate.takeReady(1),"later ended frames duplicated completion");
}
static void correctionRetractsSpeculativeEnd() {
    p::TerminalGate gate;gate.reset(1);
    gate.presented(1,45,end40);
    check(!gate.takeReady(1),"unconfirmed end escaped");
    gate.presented(1,46,std::nullopt); // Real corrected next output is playing.
    gate.confirmed(1,40,std::nullopt);
    gate.confirmed(1,46,std::nullopt);
    check(!gate.takeReady(1) && !gate.emitted(),"retracted end still emitted");
    const p::Terminal later{55,0,0,0x5555};
    gate.presented(1,55,later);gate.confirmed(1,55,later);
    check(gate.takeReady(1)==later,"a later genuine completion was suppressed");
}
static void authorityAndPresentationMustAgree() {
    p::TerminalGate gate;gate.reset(1);
    gate.presented(1,46,end40);gate.confirmed(1,40,different40);
    check(!gate.takeReady(1),"wrong speculative winner/checksum emitted");
    gate.presented(1,47,different40);
    check(gate.takeReady(1)==different40,"corrected terminal payload did not emit");
    rejects([&]{gate.presented(1,48,std::nullopt);});

    p::TerminalGate authorityFirst;authorityFirst.reset(1);
    authorityFirst.confirmed(1,40,end40);
    check(!authorityFirst.takeReady(1),"terminal emitted before an actual output");
    authorityFirst.presented(1,39,std::nullopt);
    check(!authorityFirst.takeReady(1),"terminal emitted while visible output is playing");
    authorityFirst.presented(1,40,end40);
    check(authorityFirst.takeReady(1)==end40,"publication did not release confirmed end");
}
static void rematchAndStaleCallbacks() {
    p::TerminalGate gate;gate.reset(7);
    gate.presented(7,45,end40);gate.confirmed(7,40,end40);
    check(gate.takeReady(7).has_value(),"first match did not finish");
    gate.reset(8);
    check(!gate.presented(7,50,end40) && !gate.confirmed(7,50,end40) &&
          !gate.takeReady(7),"old match callback escaped generation guard");
    check(gate.presentedFrame()==-1 && gate.confirmedFrame()==-1 && !gate.emitted(),
          "rematch retained old terminal state");
    gate.presented(8,40,end40);gate.confirmed(8,40,end40);
    check(gate.takeReady(8)==end40,"same terminal key in new match was suppressed");
    gate.invalidate();
    check(!gate.presented(8,50,end40) && !gate.confirmed(8,50,end40) && !gate.takeReady(8),
          "invalidated match dispatched completion");
    rejects([&]{gate.reset(8);});rejects([&]{gate.reset(0);});
}
static void invalidAndDuplicateEvidence() {
    p::TerminalGate gate;gate.reset(1);
    rejects([&]{gate.presented(1,-1,std::nullopt);});
    rejects([&]{gate.presented(1,39,end40);});
    gate.presented(1,40,end40);gate.presented(1,40,end40);
    rejects([&]{gate.presented(1,40,std::nullopt);});
    rejects([&]{gate.presented(1,39,std::nullopt);});
    gate.confirmed(1,39,std::nullopt);gate.confirmed(1,39,std::nullopt);
    rejects([&]{gate.confirmed(1,38,std::nullopt);});
    rejects([&]{gate.confirmed(1,39,end40);});
    gate.confirmed(1,40,end40);gate.confirmed(1,40,end40);
    rejects([&]{gate.confirmed(1,40,different40);});
    rejects([&]{gate.confirmed(1,41,std::nullopt);});
    check(gate.takeReady(1)==end40,"rejected evidence mutated valid terminal decision");
}
static void actorMembershipAndIdentity() {
    const p::ActorIdentity crab{74,75,0},gunbot{74,1,0},enemyCrab{74,75,1};
    check(p::actorDecision({}, {})==p::ActorDecision::None,"empty actor state changed");
    check(p::actorDecision({},crab)==p::ActorDecision::Create,"skipped surviving spawn not created");
    check(p::actorDecision(crab,{})==p::ActorDecision::Release,"removed entity retained actor");
    check(p::actorDecision(crab,crab)==p::ActorDecision::Keep,"unchanged actor unnecessarily rebuilt");
    check(p::actorDecision(crab,gunbot)==p::ActorDecision::Reload,"same-ID type reuse kept wrong model");
    check(p::actorDecision(crab,enemyCrab)==p::ActorDecision::Reload,"same-ID army reuse kept wrong ownership");
    check(p::actorDecision(crab,p::ActorIdentity{74,1,1})==p::ActorDecision::Reload,
          "combined actor identity change was missed");
    rejects([&]{p::actorDecision(crab,p::ActorIdentity{75,75,0});});
    // A speculative death followed by corrected existence can recreate an
    // actor; this decision does not promise corpse/effect/selection cleanup.
    check(p::actorDecision({},crab)==p::ActorDecision::Create,"corrected survivor could not be recreated");
}
int main() {
    try {
        delayedConfirmation();correctionRetractsSpeculativeEnd();
        authorityAndPresentationMustAgree();rematchAndStaleCallbacks();
        invalidAndDuplicateEvidence();actorMembershipAndIdentity();
        std::cout<<"prediction presentation policy: 6 scenario groups PASS\n";return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
