// Isolated tests of the ACTUAL production predicate and original pure ledgers.
// No Unity, IL2CPP, native game/worker, device or process APIs are used.
#include "prediction_held_selection_policy.hpp"
#include <array>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <type_traits>
#include <utility>

namespace test {
namespace policy=ba_prediction_held_selection_policy;
namespace input=ba_prediction_input_observer;
namespace provenance=ba_prediction_click_provenance;
static unsigned groups=0,checks=0,queries=0;
static void check(bool value,const char* reason){++checks;if(!value)throw std::runtime_error(reason);}
struct Fixture {
    input::Ledger source;
    provenance::Ledger proof;
    input::Owner owner{1,91,100,200,1};
    provenance::Identity identity{5,3,1,700};
    policy::Retirement retirement{1,true,{5,3,1},{5,3,1},700,700};
    input::Ticket ticket;
    explicit Fixture(bool capture=true) {
        if(capture)accept();
    }
    void accept() {
        ticket=source.begin(owner,input::Kind::Down);
        check(source.markSingleDown(ticket),"genuine Down marker refused");
        check(source.complete(ticket),"genuine Down callback did not complete");
        proof.capture(source,{ticket,identity,300,150});
    }
    bool eligible()const {++queries;return policy::eligible(source,proof,owner,retirement);}
};
static void run(const char* name,const std::function<void()>& action) {
    action();++groups;std::cout<<"PASS "<<name<<'\n';
}
static bool samePress(const provenance::Press& a,const provenance::Press& b) {
    return provenance::same(a.ticket,b.ticket) && a.identity==b.identity && a.helper==b.helper && a.frame==b.frame;
}
static void exactCompletedPressIsReadonly() {
    Fixture f;const auto serial=f.source.serial();const auto press=*f.proof.press();
    const auto accepted=*f.source.accepted();
    for(int i=0;i<4;++i)check(f.eligible(),"exact preserved HQ eligibility refused");
    check(f.source.serial()==serial && provenance::same(*f.source.accepted(),accepted) &&
        samePress(*f.proof.press(),press) && f.proof.phase()==provenance::Phase::Held && !f.proof.operation(),
        "predicate changed original input/provenance ledger");
}
static void exactSingleAlreadyReleasedOnly() {
    for(size_t count:{size_t{0},size_t{2},size_t{8192}}) {
        Fixture f;f.retirement.count=count;check(!f.eligible(),"retirement batch count widened");
    }
    Fixture f;f.retirement.alreadyReleased=false;check(!f.eligible(),"active actor retirement admitted");
}
static void residentAndCurrentMustMatchCapturedHQ() {
    for(int side=0;side<2;++side)for(int field=0;field<3;++field)for(uint32_t value:{0u,2u,9u,UINT32_MAX}) {
        Fixture f;auto& identity=side?f.retirement.currentIdentity:f.retirement.residentIdentity;
        if(field==0)identity.entity=value;if(field==1)identity.type=value;if(field==2)identity.army=value;
        check(!f.eligible(),"another ID/type/army inherited held HQ policy");
    }
}
static void eitherCoreUsesItsExactCapturedIdentity() {
    for(const auto identity:std::array<provenance::Identity,2>{{{0,3,0,700},{5,3,1,701}}}) {
        Fixture f(false);f.identity=identity;
        const policy::Identity selected{identity.entity,identity.type,identity.army};
        f.retirement={1,true,selected,selected,identity.token,identity.token};f.accept();
        const auto press=*f.proof.press();const auto serial=f.source.serial();
        check(f.eligible(),"exact captured local Core identity was restricted to one player side");
        check(samePress(*f.proof.press(),press)&&f.source.serial()==serial,"paired identity query changed source intent");
    }
}
static void capturedIdentityCannotBeSubstituted() {
    for(int field=0;field<3;++field) {
        Fixture f(false);if(field==0)++f.identity.entity;if(field==1)++f.identity.type;if(field==2)f.identity.army=0;
        f.accept();check(!f.eligible(),"another captured identity borrowed preserved-set retirement");
    }
}
static void canonicalLogicalTokenMustStaySameAndNonzero() {
    for(int change=0;change<5;++change) {
        Fixture f;if(change==0)f.retirement.residentIncarnation=0;
        if(change==1)f.retirement.canonicalIncarnation=0;
        if(change==2)++f.retirement.residentIncarnation;
        if(change==3)++f.retirement.canonicalIncarnation;
        if(change==4)++f.retirement.residentIncarnation,++f.retirement.canonicalIncarnation;
        check(!f.eligible(),"zero/changed canonical token admitted");
    }
    Fixture changedPress(false);changedPress.identity.token=701;changedPress.accept();
    check(!changedPress.eligible(),"new press token matched only numeric identity");
    Fixture fresh(false);fresh.identity.token=701;fresh.retirement.residentIncarnation=701;
    fresh.retirement.canonicalIncarnation=701;fresh.accept();check(fresh.eligible(),"fresh exact token was hardcoded");
}
static void everyLaterInputInvalidatesEvenNoopCallbacks() {
    for(unsigned kind=0;kind<=static_cast<unsigned>(input::Kind::ContextUp);++kind) {
        Fixture f;const auto original=*f.proof.press();
        const auto later=f.source.begin(f.owner,static_cast<input::Kind>(kind));
        check(!f.eligible(),"open later input inherited held eligibility");
        check(f.source.complete(later),"later no-op callback did not complete");
        check(!f.eligible() && samePress(*f.proof.press(),original),"no-op callback rearmed stale provenance");
    }
}
static void completedNewDownDoesNotBorrowOldPress() {
    Fixture f;const auto later=f.source.begin(f.owner,input::Kind::Down);
    check(f.source.markSingleDown(later) && f.source.complete(later),"fresh original Down failed");
    check(!f.eligible(),"new completed Down borrowed preceding press snapshot");
    f.proof.capture(f.source,{later,f.identity,300,160});check(f.eligible(),"new independently captured press refused");
}
static void externalNoopEditAndDiscardRemainInvalid() {
    Fixture a;a.source.invalidate();check(!a.eligible(),"source no-op edit retained eligibility");
    Fixture b;b.proof.invalidate(b.source);check(!b.eligible(),"completed no-op scope retained eligibility");
    Fixture c;c.source.discard();check(!c.eligible(),"abandoned source retained eligibility");
    Fixture d;d.proof.clear();check(!d.eligible(),"cleared provenance retained eligibility");
}
static void freshlyExpectedOwnerMustMatchEveryComponent() {
    for(int field=0;field<5;++field)for(bool zero:{false,true}) {
        Fixture f;auto expected=f.owner;
        if(field==0)expected.generation=zero?0:2;if(field==1)expected.world=zero?0:92;
        if(field==2)expected.selector=zero?0:101;if(field==3)expected.manager=zero?0:201;
        if(field==4)expected.thread=zero?0:2;
        ++queries;check(!policy::eligible(f.source,f.proof,expected,f.retirement),"another expected graph/world/thread admitted");
    }
}
static void originalWorldCannotSurviveRematch() {
    Fixture f;const auto oldOwner=f.owner;f.owner={2,92,101,201,1};
    const auto ticket=f.source.begin(f.owner,input::Kind::Down);
    check(f.source.markSingleDown(ticket) && f.source.complete(ticket),"new world original Down failed");
    check(!f.eligible(),"new world borrowed old canonical press provenance");
    ++queries;check(!policy::eligible(f.source,f.proof,oldOwner,f.retirement),"old owner survived rematch");
    f.proof.capture(f.source,{ticket,f.identity,301,1});check(f.eligible(),"new world exact source capture refused");
}
static void incompleteOrUnmarkedDownCannotQualify() {
    Fixture empty(false);check(!empty.eligible(),"empty source/provenance qualified");
    Fixture unmarked(false);auto noMarker=unmarked.source.begin(unmarked.owner,input::Kind::Down);
    check(unmarked.source.complete(noMarker),"unmarked original callback failed");
    check(!unmarked.source.accepted() && !unmarked.eligible(),"unmarked mode-like state qualified");
    Fixture open(false);const auto ticket=open.source.begin(open.owner,input::Kind::Down);
    check(open.source.markSingleDown(ticket) && !open.eligible(),"unfinished original Down qualified");
    check(open.source.complete(ticket) && !open.eligible(),"accepted source without provenance snapshot qualified");
}
static void otherCallbackCannotForgeDownMarker() {
    Fixture f(false);auto ticket=f.source.begin(f.owner,input::Kind::Up);
    check(!f.source.markSingleDown(ticket) && f.source.complete(ticket) && !f.eligible(),"Up forged accepted Down");
    auto forged=ticket;forged.kind=input::Kind::Down;
    check(!f.source.markSingleDown(forged) && !f.eligible(),"forged ticket kind armed source");
}
static void removingAndRemovedAreDifferentUnqualifiedCases() {
    Fixture f;const auto operation=f.proof.beginRemoval(f.source,20,300,f.identity,156);
    check(!f.eligible(),"in-flight original removal qualified as preserved sets");
    for(auto part:{provenance::RemovalPart::Preview,provenance::RemovalPart::Current,provenance::RemovalPart::Commit}) {
        check(f.proof.observe(f.source,operation,part,300,5),"original removal part failed");
        check(!f.eligible(),"partial original loss qualified as preserved sets");
    }
    check(f.proof.finishRemoval(f.source,operation) && f.proof.phase()==provenance::Phase::Removed,
        "original loss did not complete");
    check(f.proof.current(f.source) && !f.eligible(),"natural removed case silently received preserved-set eligibility");
}
static void everyBoundaryMustRevalidateInsteadOfCachingTrue() {
    for(int race=0;race<5;++race) {
        Fixture f;check(f.eligible(),"prepared source was not eligible");
        if(race==0)f.source.begin(f.owner,input::Kind::Up);
        if(race==1)f.source.invalidate();if(race==2)f.proof.clear();
        if(race==3)f.retirement.canonicalIncarnation=701;if(race==4)f.retirement.alreadyReleased=false;
        check(!f.eligible(),"cached prepare decision bypassed later revalidation");
    }
}
static void declinedCandidatesDoNotDestroyValidIntent() {
    Fixture f;const auto press=*f.proof.press();const auto serial=f.source.serial();
    f.retirement.currentIdentity.army=0;check(!f.eligible(),"wrong candidate accepted");
    check(samePress(*f.proof.press(),press) && f.source.serial()==serial,"decline mutated valid source intent");
    f.retirement.currentIdentity.army=1;check(f.eligible(),"pure refusal changed later exact query");
}
}
int main() {
    static_assert(std::is_trivially_copyable<test::policy::Retirement>::value,"retirement facts must remain value-only");
    static_assert(noexcept(test::policy::eligible(std::declval<const test::input::Ledger&>(),
        std::declval<const test::provenance::Ledger&>(),std::declval<const test::input::Owner&>(),
        std::declval<const test::policy::Retirement&>())),"eligibility must not throw or mutate source");
    try {
        test::run("exact completed accepted Down, readonly",test::exactCompletedPressIsReadonly);
        test::run("exact one already released only",test::exactSingleAlreadyReleasedOnly);
        test::run("resident/current match captured HQ",test::residentAndCurrentMustMatchCapturedHQ);
        test::run("either Core retains its captured identity",test::eitherCoreUsesItsExactCapturedIdentity);
        test::run("captured identity exact",test::capturedIdentityCannotBeSubstituted);
        test::run("same nonzero canonical logical token",test::canonicalLogicalTokenMustStaySameAndNonzero);
        test::run("all13 later/no-op original inputs invalidate",test::everyLaterInputInvalidatesEvenNoopCallbacks);
        test::run("new completed Down requires fresh capture",test::completedNewDownDoesNotBorrowOldPress);
        test::run("no-op selection/source edit and abandon",test::externalNoopEditAndDiscardRemainInvalid);
        test::run("exact expected graph/world/thread",test::freshlyExpectedOwnerMustMatchEveryComponent);
        test::run("old world cannot survive rematch",test::originalWorldCannotSurviveRematch);
        test::run("missing marker/completion/snapshot refuse",test::incompleteOrUnmarkedDownCannotQualify);
        test::run("other callback cannot forge Down",test::otherCallbackCannotForgeDownMarker);
        test::run("Removing/Removed remain separately unqualified",test::removingAndRemovedAreDifferentUnqualifiedCases);
        test::run("later boundary races revalidate",test::everyBoundaryMustRevalidateInsteadOfCachingTrue);
        test::run("refusal leaves original intent unchanged",test::declinedCandidatesDoNotDestroyValidIntent);
        std::cout<<"PASS "<<test::groups<<" actual production policy groups, "<<test::queries<<" eligibility queries, "
            <<test::checks<<" checks; no native/game execution\n";return 0;
    } catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
