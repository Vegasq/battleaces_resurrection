#include "prediction_group_intent.hpp"
#include <iostream>
#include <set>
#include <string>
#include <type_traits>
#include <utility>

// Authored external-host cases exercise the ACTUAL policy header. The visible
// sets stand in for original group membership; no Unity/IL2CPP/native DLL loads.
namespace test {
using namespace ba_prediction_group_intent;
static unsigned cases=0;
static void check(bool value,const char* message) {
    if(!value)throw std::runtime_error(message);
}
template<class Call>static void rejected(Call call) {
    bool caught=false;try{call();}catch(const std::invalid_argument&){caught=true;}
    check(caught,"invalid policy input was accepted");
}
static constexpr Key key{4,11};
static constexpr Identity identity{1,1,11};
struct VisibleHost {
    Ledger policy;
    std::set<uint32_t> members{11,12};
    unsigned nativePurges=0;
    VisibleHost(){policy.reset(1);policy.remember(1,key,identity);}
    Decision observe(std::optional<Identity> canonical,bool admitted=false)const {
        return policy.classify(1,key,members.count(key.entity)!=0,canonical,admitted);
    }
    void originalPurgeSucceeded(){members.erase(key.entity);++nativePurges;policy.erase(1,key);}
};
static void speculativeAbsenceRetainsVisibleIntentWithoutMutation() {
    VisibleHost h;const auto before=h.members;
    for(unsigned frame=0;frame<12;++frame) {
        check(h.observe(identity)==Decision::Keep,"same confirmed incarnation was discarded");
        check(h.members==before && h.nativePurges==0 && h.policy.entries().size()==1,
              "readonly decision changed visible membership/metadata");
    }
    ++cases;
}
static void originalClearReplaceAndRemoveAlwaysWin() {
    for(unsigned mode=0;mode<4;++mode) {
        VisibleHost h;
        if(mode==0)h.members.clear();                       // Original Clear.
        if(mode==1)h.members={27,28};                       // Original replace.
        if(mode==2){h.members.erase(11);h.members.erase(11);} // Repeated/no-op remove.
        if(mode==3){h.members.clear();h.members.clear();}    // Repeated/no-op Clear.
        const auto accepted=h.members;
        check(h.observe(identity,true)==Decision::Forget,"user visible removal was not respected");
        // Even a simultaneous canonical death cannot supersede a visible user
        // removal and cause another original purge or a later re-add.
        check(h.observe(std::nullopt)==Decision::Forget,"canonical absence overrode user removal");
        h.policy.erase(1,key);
        check(h.members==accepted && h.nativePurges==0 && h.policy.entries().empty(),
              "forgetting intent resurrected/replaced user membership");
        ++cases;
    }
}
static void recreatedSameLeaseForgetsWithoutReassigning() {
    VisibleHost h;const auto before=h.members;
    check(h.observe(identity,true)==Decision::Forget,"same admitted incarnation did not retire metadata");
    h.policy.erase(1,key);
    check(h.members==before && h.nativePurges==0,"recreated unit changed original membership");++cases;
}
static void delayedCanonicalLossNeedsSuccessfulOriginalPurge() {
    VisibleHost h;
    check(h.observe(identity)==Decision::Keep,"pending absence was not retained");
    for(unsigned attempt=0;attempt<2;++attempt) {
        check(h.observe(std::nullopt)==Decision::Purge,"confirmed death did not demand purge");
        // Model refused/throwing original preflight: no erase acknowledgement.
        check(h.members.count(11)==1 && h.members.count(12)==1 && h.policy.entries().size()==1,
              "unsuccessful original purge changed policy membership");
    }
    h.originalPurgeSucceeded();
    check(h.members==std::set<uint32_t>{12} && h.nativePurges==1 && h.policy.entries().empty(),
          "successful canonical purge removed another member or kept metadata");++cases;
}
static void canonicalIdentityChangeAlwaysPurges() {
    for(const Identity changed:{Identity{2,1,11},Identity{1,0,11},Identity{1,1,12}}) {
        VisibleHost h;
        check(h.observe(changed,true)==Decision::Purge,"type/army/token mismatch was treated as same lease");
        check(h.policy.entries().at(key)==identity && h.members.count(11)==1,
              "classification overwrote the original incarnation");++cases;
    }
}
static void registrationIsBoundedIdempotentAndAtomic() {
    Ledger p(1);p.reset(1);p.remember(1,key,identity);p.remember(1,key,identity);
    check(p.entries().size()==1,"duplicate registration consumed budget");
    rejected([&]{p.remember(1,key,Identity{1,1,12});});
    rejected([&]{p.remember(1,Key{5,12},identity);});
    rejected([&]{p.remember(2,key,identity);});
    check(p.entries().size()==1 && p.entries().at(key)==identity,"failed registration mutated metadata");
    p.reset(1);check(p.entries().size()==1,"same active generation reset lost intent");++cases;
}
static void invalidKeysAndIdentitiesRefuseBeforeMutation() {
    Ledger p;p.reset(1);
    constexpr auto invalid=(std::numeric_limits<uint32_t>::max)();
    for(const Key bad:{Key{invalid,11},Key{16,11},Key{4,invalid}})
        rejected([&]{p.remember(1,bad,identity);});
    for(const Identity bad:{Identity{invalid,1,11},Identity{1,invalid,11},Identity{1,1,0}})
        rejected([&]{p.remember(1,key,bad);});
    check(p.entries().empty(),"invalid record changed policy");
    p.remember(1,Key{0,0},Identity{0,0,1}); // Original panel group zero and entity zero are legal.
    check(p.entries().size()==1 && p.classify(1,Key{0,0},true,Identity{0,0,1},false)==Decision::Keep,
          "legal original group zero/entity zero was rejected");
    rejected([]{Ledger invalidLimit(0);});
    rejected([]{Ledger invalidLimit(Ledger::maximumEntries+1);});++cases;
}
static void invalidObservationCannotRetireOrChangeMetadata() {
    VisibleHost h;
    rejected([&]{h.policy.classify(2,key,false,std::nullopt,false);});
    rejected([&]{h.policy.classify(1,Key{4,12},false,std::nullopt,false);});
    rejected([&]{h.policy.classify(1,key,true,Identity{1,1,0},false);});
    rejected([&]{h.policy.erase(2,key);});
    check(h.policy.entries().size()==1 && h.policy.entries().at(key)==identity &&
          h.members==std::set<uint32_t>{11,12},"invalid observation changed original state");++cases;
}
static void generationsAndRetirementRejectDelayedOldCallbacks() {
    VisibleHost h;
    rejected([&]{h.policy.reset(0);});
    check(h.policy.entries().size()==1,"invalid reset cleared pending metadata");
    h.policy.reset(2);check(h.policy.entries().empty(),"new world inherited old intent");
    rejected([&]{h.policy.remember(1,key,identity);});
    rejected([&]{h.policy.reset(1);});
    h.policy.remember(2,key,Identity{1,1,1});h.policy.clear();
    check(h.policy.generation()==0 && h.policy.entries().empty(),"retired world remains active");
    rejected([&]{h.policy.classify(2,key,false,std::nullopt,false);});
    rejected([&]{h.policy.reset(2);});
    h.policy.reset(3);h.policy.remember(3,key,identity);
    check(h.policy.entries().size()==1 && h.members==std::set<uint32_t>{11,12},
          "new generation mutated an unrelated original group");++cases;
}
static void independentGroupsHaveIndependentMetadata() {
    Ledger p;p.reset(1);p.remember(1,key,identity);p.remember(1,Key{5,11},identity);
    check(p.classify(1,key,false,identity,false)==Decision::Forget,"removed group did not forget");
    p.erase(1,key);
    check(p.classify(1,Key{5,11},true,identity,false)==Decision::Keep && p.entries().size()==1,
          "clearing one group removed another group's intent");++cases;
}
}
int main(){try{
    static_assert(std::is_same<decltype(std::declval<const ba_prediction_group_intent::Ledger&>().entries()),
        const ba_prediction_group_intent::Ledger::Entries&>::value,"policy exposes mutable entries");
    test::speculativeAbsenceRetainsVisibleIntentWithoutMutation();test::originalClearReplaceAndRemoveAlwaysWin();
    test::recreatedSameLeaseForgetsWithoutReassigning();test::delayedCanonicalLossNeedsSuccessfulOriginalPurge();
    test::canonicalIdentityChangeAlwaysPurges();test::registrationIsBoundedIdempotentAndAtomic();
    test::invalidKeysAndIdentitiesRefuseBeforeMutation();test::invalidObservationCannotRetireOrChangeMetadata();
    test::generationsAndRetirementRejectDelayedOldCallbacks();test::independentGroupsHaveIndependentMetadata();
    std::cout<<"group intent: "<<test::cases<<" actual-header authored cases PASS; no original/native runtime\n";
    return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
