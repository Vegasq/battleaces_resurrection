#include "prediction_input_observer.hpp"
#include <functional>
#include <iostream>
#include <string>
#include <vector>

namespace test {
namespace input=ba_prediction_input_observer;
using Kind=input::Kind;
static void check(bool value,const char* reason){if(!value)throw std::runtime_error(reason);}
static input::Owner owner(uint64_t generation=1){return {generation,91,100,200,1};}
template<class F> static void rejected(F action){
    bool threw=false;try{action();}catch(const std::invalid_argument&){threw=true;}
    check(threw,"invalid input provenance was accepted");
}
static input::Ticket down(input::Ledger& ledger) {
    const auto ticket=ledger.begin(owner(),Kind::Down);
    check(ledger.markSingleDown(ticket) && ledger.complete(ticket),"accepted Down did not complete");
    check(ledger.accepted().has_value(),"completed positive Down was not retained");return ticket;
}
static void acceptanceNeedsTheCompletedPositiveOriginalDown() {
    input::Ledger ledger;
    auto ticket=ledger.begin(owner(),Kind::Down);
    check(!ledger.accepted(),"input began with an invented accepted Down");
    check(ledger.complete(ticket) && !ledger.accepted(),"Down without its original ProcessClick marker armed intent");
    ticket=ledger.begin(owner(),Kind::Down);
    check(ledger.markSingleDown(ticket) && !ledger.accepted(),"marker published intent before the callback completed");
    check(!ledger.markSingleDown(ticket),"duplicate positive marker was consumed twice");
    check(ledger.complete(ticket) && ledger.accepted(),"completed accepted Down was lost");
    check(!ledger.complete(ticket) && !ledger.markSingleDown(ticket),"completed callback was consumed twice");
}
static void everySubsequentInputInvalidatesIncludingNoops() {
    for(unsigned value=0;value<=static_cast<unsigned>(Kind::ContextUp);++value) {
        input::Ledger ledger;const auto first=down(ledger);
        // These callbacks are deliberately modeled with NO original state
        // change, matching empty cancel and repeated-value input operations.
        const auto next=ledger.begin(owner(),static_cast<Kind>(value));
        check(next.serial>first.serial && !ledger.accepted(),"no-op input preserved an old accepted click");
        check(!ledger.complete(first) && !ledger.markSingleDown(first),"old Down rearmed after a later input");
        check(ledger.complete(next) && !ledger.accepted(),"unmarked later input invented a fresh click");
    }
}
static void markersFromOtherCallbacksNeverArmSingle() {
    for(unsigned value=0;value<=static_cast<unsigned>(Kind::ContextUp);++value) {
        const auto kind=static_cast<Kind>(value);if(kind==Kind::Down)continue;
        input::Ledger ledger;const auto ticket=ledger.begin(owner(),kind);
        check(!ledger.markSingleDown(ticket),"non-Down callback armed Single intent");
        check(ledger.complete(ticket) && !ledger.accepted(),"non-Down completion armed Single intent");
    }
}
static void nestedInputCannotBeOverwrittenByItsParent() {
    input::Ledger ledger;const auto parent=ledger.begin(owner(),Kind::Down);
    check(ledger.markSingleDown(parent),"parent marker missing");
    const auto child=ledger.begin(owner(),Kind::Down);
    check(ledger.markSingleDown(child) && ledger.complete(child),"nested original Down failed");
    check(!ledger.complete(parent),"old parent completed over a newer callback");ledger.abandon(parent);
    check(ledger.accepted() && ledger.accepted()->serial==child.serial,"old parent cleanup erased a newer accepted Down");
}
static void scopeEditsAndAbortedCallbacksNeverRearm() {
    input::Ledger ledger;auto ticket=down(ledger);ledger.invalidate();
    check(!ledger.accepted() && !ledger.complete(ticket),"selection no-op scope retained click intent");
    ticket=ledger.begin(owner(),Kind::Down);check(ledger.markSingleDown(ticket),"marker missing before abort");
    ledger.abandon(ticket);
    check(!ledger.complete(ticket) && !ledger.accepted(),"throwing original callback rearmed its Down");
    ticket=down(ledger);ledger.discard();
    check(!ledger.complete(ticket) && !ledger.accepted(),"retired observer restored a stale callback");
}
static void ownershipCannotBeReusedAcrossWorldsOrObjects() {
    input::Ledger ledger;const auto old=down(ledger);
    for(int part=0;part<5;++part) {
        auto changed=owner();
        if(part==0)changed.world=92;if(part==1)changed.selector=101;
        if(part==2)changed.manager=201;if(part==3)changed.thread=2;if(part==4)changed.generation=0;
        rejected([&]{ledger.begin(changed,Kind::Down);});
    }
    const auto fresh=ledger.begin(owner(2),Kind::Down);
    check(!ledger.accepted() && !ledger.markSingleDown(old),"rematch inherited the old callback");
    check(ledger.markSingleDown(fresh) && ledger.complete(fresh),"fresh rematch input failed");
    rejected([&]{ledger.begin(owner(),Kind::Down);});
    check(ledger.accepted()->owner.generation==2,"old owner replaced current rematch intent");
}
struct OriginalError {};
struct Access {
    input::Ledger& ledger;
    input::Ticket ticket;
    std::vector<std::string>& events;
    std::function<void()> body;
    bool observe=true,failPrepare=false,failComplete=false;
    int originals=0,failures=0,abandoned=0;
    bool prepare(){
        events.push_back("prepare");if(failPrepare)throw std::runtime_error("prepare");
        if(!observe)return false;ticket=ledger.begin(owner(),Kind::Down);return true;
    }
    void original(){++originals;events.push_back("original");if(body)body();}
    void complete(){events.push_back("complete");if(failComplete)throw std::runtime_error("complete");ledger.complete(ticket);}
    void abandon()noexcept{++abandoned;ledger.abandon(ticket);}
    void failed(const char*)noexcept{++failures;ledger.discard();}
};
static void originalRunsOnceAcrossAllObserverFailures() {
    for(int mode=0;mode<4;++mode) {
        input::Ledger ledger;std::vector<std::string> events;Access access{ledger,{},events,{}};
        access.observe=mode!=1;access.failPrepare=mode==2;access.failComplete=mode==3;
        access.body=[&]{if(access.observe && !access.failPrepare)ledger.markSingleDown(access.ticket);};
        input::forward(access);
        check(access.originals==1 && access.abandoned==0,"observer failure repeated or skipped original callback");
        check(access.failures==(mode>=2?1:0),"observer failure classification differs");
        check(ledger.accepted().has_value()==(mode==0),"observer failure published accepted intent");
        check(events==std::vector<std::string>(mode==1 || mode==2?
            std::initializer_list<std::string>{"prepare","original"}:
            std::initializer_list<std::string>{"prepare","original","complete"}),"observer changed callback ordering");
    }
}
static void originalExceptionPropagatesWithoutRetryOrCompletion() {
    for(bool observe:{false,true}) {
        input::Ledger ledger;std::vector<std::string> events;Access access{ledger,{},events,{}};access.observe=observe;
        access.body=[&]{if(observe)ledger.markSingleDown(access.ticket);throw OriginalError{};};
        bool originalError=false;try{input::forward(access);}catch(const OriginalError&){originalError=true;}
        check(originalError && access.originals==1 && !access.failures && access.abandoned==(observe?1:0),
            "original exception was swallowed, changed, retried or blamed on observer");
        check(events==std::vector<std::string>{"prepare","original"} && !ledger.accepted(),
            "throwing original callback completed or armed a click");
    }
}
static void reentrantForwardKeepsOnlyTheNewestCompletedEpisode() {
    input::Ledger ledger;std::vector<std::string> events;
    Access outer{ledger,{},events,{}},inner{ledger,{},events,{}};
    inner.body=[&]{ledger.markSingleDown(inner.ticket);};
    outer.body=[&]{ledger.markSingleDown(outer.ticket);input::forward(inner);};
    input::forward(outer);
    check(outer.originals==1 && inner.originals==1 && ledger.accepted() &&
        ledger.accepted()->serial==inner.ticket.serial,"outer callback overwrote nested completed click");
}
}
int main(){try{
    test::acceptanceNeedsTheCompletedPositiveOriginalDown();
    test::everySubsequentInputInvalidatesIncludingNoops();test::markersFromOtherCallbacksNeverArmSingle();
    test::nestedInputCannotBeOverwrittenByItsParent();test::scopeEditsAndAbortedCallbacksNeverRearm();
    test::ownershipCannotBeReusedAcrossWorldsOrObjects();test::originalRunsOnceAcrossAllObserverFailures();
    test::originalExceptionPropagatesWithoutRetryOrCompletion();test::reentrantForwardKeepsOnlyTheNewestCompletedEpisode();
    std::cout<<"input observer:9 authored policy/forwarding groups PASS; original native callback ABI and held-click repair remain unqualified\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
