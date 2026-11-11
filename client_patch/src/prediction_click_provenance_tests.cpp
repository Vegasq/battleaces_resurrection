#include "prediction_click_provenance.hpp"
#include <functional>
#include <iostream>
#include <string>

namespace test {
namespace provenance=ba_prediction_click_provenance;
namespace input=ba_prediction_input_observer;
using Part=provenance::RemovalPart;
static void check(bool value,const char* reason){if(!value)throw std::runtime_error(reason);}
template<class F>static void rejected(F action){bool refused=false;
    try{action();}catch(const std::invalid_argument&){refused=true;}check(refused,"invalid removal provenance accepted");}
struct Fixture {
    input::Ledger source;provenance::Ledger ledger;
    input::Owner owner{1,91,100,200,1};
    provenance::Identity identity{5,3,1,700};
    input::Ticket ticket;
    Fixture(){ticket=source.begin(owner,input::Kind::Down);source.markSingleDown(ticket);source.complete(ticket);
        ledger.capture(source,{ticket,identity,300,150});}
    provenance::Removal begin(){return ledger.beginRemoval(source,20,300,identity,156);}
    bool part(const provenance::Removal& op,Part part){return ledger.observe(source,op,part,300,5);}
    void all(const provenance::Removal& op){check(part(op,Part::Preview)&&part(op,Part::Current)&&part(op,Part::Commit),"original removal sequence refused");}
};
static void exactOriginalRemovalIsACompletedWitnessOnly(){
    Fixture f;check(f.ledger.phase()==provenance::Phase::Held,"press did not bind");const auto op=f.begin();
    check(!f.ledger.finishRemoval(f.source,op),"removal completed without original operations");
    check(f.part(op,Part::Preview)&&!f.ledger.finishRemoval(f.source,op),"preview-only removal became complete");
    check(f.part(op,Part::Current)&&!f.ledger.finishRemoval(f.source,op),"removal completed before original selection scope");
    check(f.part(op,Part::Commit)&&f.ledger.finishRemoval(f.source,op),"exact original removal did not complete");
    check(f.ledger.phase()==provenance::Phase::Removed&&f.ledger.current(f.source),"original removal canceled the actual held episode");
    check(!f.ledger.finishRemoval(f.source,op),"same original removal completed twice");
}
static void wrongOriginalOrderOrDuplicateCannotCount(){
    for(Part first:{Part::Current,Part::Commit}){Fixture f;const auto op=f.begin();
        check(!f.part(op,first),"out-of-order operation counted");}
    for(Part part:{Part::Preview,Part::Current,Part::Commit}){Fixture f;const auto op=f.begin();
        check(f.part(op,Part::Preview),"preview refused");
        if(part!=Part::Preview)check(f.part(op,Part::Current),"current refused");
        if(part==Part::Commit)check(f.part(op,Part::Commit),"commit refused");
        check(!f.part(op,part),"duplicate mutation or scope commit counted");}
}
static void inputAndNoopEditsWinDuringEveryRemovalStage(){
    for(unsigned kind=0;kind<=static_cast<unsigned>(input::Kind::ContextUp);++kind)for(int stage=0;stage<4;++stage){
        Fixture f;const auto op=f.begin();
        if(stage>=1)f.part(op,Part::Preview);if(stage>=2)f.part(op,Part::Current);if(stage>=3)f.part(op,Part::Commit);
        f.source.begin(f.owner,static_cast<input::Kind>(kind));
        check(!f.ledger.current(f.source)&&!f.ledger.finishRemoval(f.source,op),"new/no-op input inherited original-removal permission");
    }
    for(int stage=0;stage<4;++stage){Fixture f;const auto op=f.begin();
        if(stage>=1)f.part(op,Part::Preview);if(stage>=2)f.part(op,Part::Current);if(stage>=3)f.part(op,Part::Commit);
        f.ledger.invalidate(f.source);
        check(!f.ledger.finishRemoval(f.source,op)&&!f.source.accepted()&&f.ledger.phase()==provenance::Phase::Empty,
            "external no-op selection mutation was resurrected");}
}
static void exactOwnerBatchIncarnationAndOriginalManagerRequired(){
    for(int mode=0;mode<8;++mode){Fixture f;auto identity=f.identity;uintptr_t helper=300;uint64_t managerUpdate=20;int frame=156;
        if(mode==0)identity.entity=6;if(mode==1)identity.type=4;if(mode==2)identity.army=0;
        if(mode==3)identity.token=701;if(mode==4)identity.token=0;if(mode==5)helper=301;
        if(mode==6)managerUpdate=0;if(mode==7)frame=149;
        rejected([&]{f.ledger.beginRemoval(f.source,managerUpdate,helper,identity,frame);});
        check(f.ledger.phase()==provenance::Phase::Held,"refused preflight changed the completed input episode");}
}
static void OperationNonceAndGraphCannotBeBorrowed(){
    for(int mode=0;mode<9;++mode){Fixture f;const auto real=f.begin();auto forged=real;
        if(mode==0)++forged.nonce;if(mode==1)++forged.managerUpdate;if(mode==2)++forged.ticket.serial;
        if(mode==3)++forged.ticket.owner.world;if(mode==4)++forged.helper;if(mode==5)++forged.identity.token;
        if(mode==6)++forged.frame;
        const auto helper=mode==7?301u:300u,id=mode==8?6u:5u;
        check(!f.ledger.observe(f.source,forged,Part::Preview,helper,id),"another operation borrowed natural provenance");
        check(!f.ledger.finishRemoval(f.source,forged),"forged operation completed");
        f.all(real);check(f.ledger.finishRemoval(f.source,real),"forged observation corrupted real operation");}
}
static void nestedOperationsAndOldWorldsCannotRearm(){
    Fixture f;const auto old=f.begin();rejected([&]{f.begin();});
    f.source.begin({2,92,101,201,1},input::Kind::Down);
    f.source.markSingleDown({{2,92,101,201,1},f.source.serial(),input::Kind::Down});
    f.source.complete({{2,92,101,201,1},f.source.serial(),input::Kind::Down});
    check(!f.ledger.current(f.source)&&!f.ledger.finishRemoval(f.source,old),"rematch inherited old removal");
    const auto next=*f.source.accepted();f.ledger.capture(f.source,{next,f.identity,301,1});
    const auto fresh=f.ledger.beginRemoval(f.source,21,301,f.identity,2);
    check(fresh.nonce>old.nonce,"original-operation nonce was reused across worlds");
    check(!f.ledger.observe(f.source,old,Part::Preview,300,5),"late old operation touched new click");
}
static void failuresCannotCompleteOrRetryAnOriginalOperation(){
    Fixture f;const auto op=f.begin();f.part(op,Part::Preview);f.ledger.clear();
    check(!f.ledger.observe(f.source,op,Part::Current,300,5)&&!f.ledger.finishRemoval(f.source,op),"exception/abandon completed an old removal");
    f.ledger.capture(f.source,{f.ticket,f.identity,300,150});const auto fresh=f.ledger.beginRemoval(f.source,21,300,f.identity,157);
    check(fresh.nonce>op.nonce,"retry reused a consumed operation nonce");
}
static void noPositiveInputNoSnapshotOrZeroTokenCannotCapture(){
    for(int mode=0;mode<6;++mode){Fixture f;auto press=*f.ledger.press();
        if(mode==0)f.source.invalidate();if(mode==1)press.ticket.kind=input::Kind::Up;
        if(mode==2)press.identity.token=0;if(mode==3)press.helper=0;if(mode==4)press.frame=-1;
        if(mode==5)++press.ticket.owner.selector;
        rejected([&]{f.ledger.capture(f.source,press);});}
}
}
int main(){try{
    test::exactOriginalRemovalIsACompletedWitnessOnly();test::wrongOriginalOrderOrDuplicateCannotCount();
    test::inputAndNoopEditsWinDuringEveryRemovalStage();test::exactOwnerBatchIncarnationAndOriginalManagerRequired();
    test::OperationNonceAndGraphCannotBeBorrowed();test::nestedOperationsAndOldWorldsCannotRearm();
    test::failuresCannotCompleteOrRetryAnOriginalOperation();test::noPositiveInputNoSnapshotOrZeroTokenCannotCapture();
    std::cout<<"click provenance:8 authored operation-policy groups PASS; no original callback, held repair or native execution\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
