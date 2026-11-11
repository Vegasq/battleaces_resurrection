// Authored actual-source group scope controls; shared fake ABI lives in the host.
#include "prediction_actor_test_host.hpp"

namespace scope_test {
static void exact(Node& values,std::vector<uint32_t> expected){auto actual=values.values;std::sort(actual.begin(),actual.end());std::sort(expected.begin(),expected.end());check(actual==expected,"scope raw membership differs");}
static void refused(const std::function<void()>& operation){bool rejected=false;try{operation();}catch(const std::exception&){rejected=true;}check(rejected,"actual scope refused contract was accepted");}
static unsigned cases=0;
static void run(const char* name,const std::function<void(Fixture&)>& body){Fixture f;try{body(f);++cases;}catch(...){std::cerr<<"FAIL "<<name<<'\n';throw;}}
}
int main(){using namespace scope_test;try{
    run("pending member and close idempotence",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes);changes.prune();
        exact(f.first.allIds,{99});exact(f.first.oldIds,{99});exact(f.tracked0,{99});
        check(changes.pruned&&host::dirtyCalls==1&&host::ledCalls==2,"actual prune not exercised");
        changes.close();changes.close();check(f.helper0.disposed==1&&!host::read<bool>(&f.helper0,0x10),"close did not dispose once");
        check(host::dirtyCalls==1&&host::ledCalls==2&&!host::controlGroupClears,"close adapted original membership");
        check(f.rules0.values==std::vector<uint32_t>{75},"automatic rule changed");
    });
    run("original initializer after close retains new assignment",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes);changes.prune();changes.close();f.automatic();
        exact(f.first.allIds,{7,99});exact(f.first.oldIds,{99});exact(f.first.newIds,{7});
        check(f.first.dictionary.objects.size()==2&&host::automaticCalls==1,"new original typed bucket not exercised");
        changes.close();exact(f.first.allIds,{7,99});exact(f.first.newIds,{7});
        check(host::ledCalls==2&&f.helper0.disposed==1,"later close re-pruned/re-disposed original assignment");
    });
    run("original initializer suspension diagnostic",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes);std::string failure;
        try{f.automatic();}catch(const std::exception& e){failure=e.what();}
        check(failure.find("eventSuspender is suspended")!=std::string::npos&&failure.find("UnitsInitialized")!=std::string::npos,"original wrapper diagnostic missing");
        check(!host::automaticCalls,"raw Add ran despite forbidden initializer suspension");
        exact(f.first.allIds,{7,99});changes.close(true);check(f.helper0.disposed==1,"negative wrapper leaked scope");
    });
    run("Dispose callback manual removal is not resurrected",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes);changes.prune();
        host::disposeHook=[&](void* helper){if(helper==&f.helper0)f.manual(99);};
        changes.close();exact(f.first.allIds,{});exact(f.first.oldIds,{});f.automatic();
        exact(f.first.allIds,{7});exact(f.first.newIds,{7});changes.close();exact(f.first.allIds,{7});
        check(host::groupRemovals==1&&host::ledCalls==2,"manual callback/purge provenance differs");
    });
    run("manual new assignment removal stays absent",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes);changes.prune();changes.close();f.automatic();f.manual(7);changes.close();
        exact(f.first.allIds,{99});exact(f.first.newIds,{});check(host::groupRemovals==1,"manual removal not exercised");
    });
    run("both groups prune pending IDs only",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);changes.prune();changes.close();
        exact(f.first.allIds,{99});exact(f.second.allIds,{100});exact(f.tracked0,{99});exact(f.tracked1,{100});
        check(f.helper0.disposed==1&&f.helper1.disposed==1&&host::dirtyCalls==2&&host::ledCalls==4,"two-group scope counts differ");
    });
    for(bool typed:{false,true})run(typed?"partial first-group purge failure":"first-group purge failure",[&](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);host::failLed=typed?&f.first.oldType:&f.first.all;
        refused([&]{changes.prune();});const auto calls=host::ledCalls;refused([&]{changes.prune();});changes.close(true);
        check(host::dirtyBySet[&f.second.set]==0&&host::ledByObject[&f.second.all]==0&&host::ledCalls==calls,"purge failure reached/retried later group");
        exact(f.second.allIds,{7,100});check(f.helper0.disposed==1&&f.helper1.disposed==1,"purge failure leaked begun scopes");
        check(host::read<int32_t>(&f.first.set,0x54)==-1,"partial failure left count valid");
    });
    run("first mark failure stops later group",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);
        host::markHook=[&](void* helper){if(helper==&f.helper0)throw std::runtime_error("injected original Mark failure");};
        refused([&]{changes.prune();});changes.close(true);exact(f.first.allIds,{99});exact(f.second.allIds,{7,100});
        check(!host::dirtyBySet[&f.second.set]&&f.helper0.disposed==1&&f.helper1.disposed==1,"mark failure mutated later group or leaked cleanup");
    });
    run("missing prune rejected after all cleanup",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);refused([&]{changes.close();});changes.close(true);
        check(f.helper0.disposed==1&&f.helper1.disposed==1&&!host::ledCalls,"missing-prune close mutated/retried");
        exact(f.first.allIds,{7,99});exact(f.second.allIds,{7,100});
    });
    run("cancelled pre-mutation cleanup never purges",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);changes.mutated=false;changes.close();
        check(!host::ledCalls&&!host::dirtyCalls&&f.helper0.disposed==1&&f.helper1.disposed==1,"pre-mutation cleanup pruned");
    });
    run("prune cannot repeat",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes);changes.prune();refused([&]{changes.prune();});changes.close();f.automatic();
        refused([&]{changes.prune();});changes.close();exact(f.first.allIds,{7,99});check(host::dirtyCalls==1,"repeat prune mutated new assignment");
    });
    run("prune cannot precede Begin",[](Fixture& f){
        actors::GroupChanges changes;changes.prepare({&f.group0},f.retired,&f.state);changes.mutated=true;
        refused([&]{changes.prune();});changes.close(true);check(!host::ledCalls&&!f.helper0.disposed,"unbegun scope mutated/disposed");
    });
    run("helper replacement before Begin",[](Fixture& f){
        actors::GroupChanges changes;changes.prepare({&f.group0},f.retired,&f.state);put(f.group0,0x40,static_cast<void*>(&f.helper1));
        refused([&]{changes.begin();});changes.close(true);check(!f.helper0.disposed&&!f.helper1.disposed&&!host::ledCalls,"receiver replacement entered original Begin");
    });
    run("selected replacement after Begin",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);put(f.group0,0x20,static_cast<void*>(&f.second.set));
        refused([&]{changes.prune();});refused([&]{changes.close(true);});
        check(f.helper0.disposed==1&&f.helper1.disposed==1&&!host::ledCalls,"root loss mutated or leaked cleanup");
    });
    run("owner loss before prune",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);host::movementWorld=0;
        refused([&]{changes.prune();});refused([&]{changes.close(true);});
        check(!host::ledCalls&&f.helper0.disposed==1&&f.helper1.disposed==1,"owner loss adapted or leaked cleanup");
    });
    run("Dispose callback owner loss blocks pool continuation",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);changes.prune();
        host::disposeHook=[&](void* helper){if(helper==&f.helper0)host::movementWorld=0;};
        bool poolContinuation=false;refused([&]{changes.close();actors::requireOwned(f.state);poolContinuation=true;});
        check(!poolContinuation&&f.helper0.disposed==1&&f.helper1.disposed==1&&host::ledCalls==4,"Dispose owner loss continued adaptation");
    });
    run("Dispose callback selected-root loss",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);changes.prune();
        host::disposeHook=[&](void* helper){if(helper==&f.helper0)put(f.group1,0x20,static_cast<void*>(&f.first.set));};
        refused([&]{changes.close();});check(f.helper0.disposed==1&&f.helper1.disposed==1&&host::ledCalls==4,"Dispose replacement retried adaptation/cleanup");
        exact(f.first.allIds,{99});exact(f.second.allIds,{100});
    });
    run("first Dispose failure still closes later scope",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);changes.prune();host::failDispose=&f.helper0;
        refused([&]{changes.close();});changes.close(true);
        check(host::disposeByHelper[&f.helper0]==1&&host::disposeByHelper[&f.helper1]==1&&host::ledCalls==4,"Dispose failure lost once-only cleanup");
    });
    run("frame epoch change rejected",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);put(f.frame,0x40,int32_t{111});
        refused([&]{changes.prune();});refused([&]{changes.close(true);});check(!host::ledCalls&&f.helper0.disposed==1&&f.helper1.disposed==1,"changed frame mutated/escaped cleanup");
    });
    for(int mode=0;mode<3;++mode)run(("missing or invalid original frame "+std::to_string(mode)).c_str(),[&](Fixture& f){
        if(mode==0)put(f.simulation,0x148,static_cast<void*>(nullptr));
        if(mode==1)f.frames.calls["get_Current"]=nullptr;
        if(mode==2)f.frame.klass=host::type("Authored","WrongFrame");
        actors::GroupChanges changes;refused([&]{f.prepare(changes);});changes.close(true);
        check(host::interactionEvents.empty()&&!host::dirtyCalls&&!host::ledCalls&&
            !f.helper0.disposed&&!f.helper1.disposed,"missing frame reached original group mutation/cleanup");
        exact(f.first.allIds,{7,99});exact(f.first.oldIds,{7,99});
    });
    run("tracked root change rejected",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);put(f.group0,0x10,static_cast<void*>(&f.tracked1));
        refused([&]{changes.prune();});refused([&]{changes.close(true);});check(!host::ledCalls&&f.helper0.disposed==1&&f.helper1.disposed==1,"tracked replacement adapted");
    });
    run("null original automatic rules retained",[](Fixture& f){
        put(f.group0,0x30,static_cast<void*>(nullptr));actors::GroupChanges changes;f.prepare(changes);changes.prune();changes.close();f.automatic();
        check(!host::read<void*>(&f.group0,0x30),"null rule set replaced");exact(f.first.allIds,{7,99});
    });
    run("canonical manual membership survives speculative presentation retirement",[](Fixture& f){
        // Original group4 still owns canonical75/0/token900 at numeric7.
        // The physical presentation being retired is speculative76/token0;
        // it never owned this group's logical membership. Pending99 is absent.
        Selection empty2{101},empty3{102},manual{99};
        Node group2,group3,group4,helper2,helper3,helper4,tracked2,tracked3,tracked4,rules2,rules3,rules4;
        for(auto* group:{&group2,&group3,&group4})group->klass=host::type("Uncapped","ControlGroup");
        for(auto* helper:{&helper2,&helper3,&helper4})helper->klass=host::type("Authored","GroupHelper");
        for(auto* tracked:{&tracked2,&tracked3,&tracked4})tracked->klass=host::type("Uncapped.Collections","EntityIdSet");
        for(auto* selected:{&empty2,&empty3}) {
            selected->allIds.values.clear();selected->oldIds.values.clear();
            put(selected->all,0x18,UINT32_MAX);put(selected->oldType,0x18,UINT32_MAX);
        }
        tracked4.values={7,99};
        f.setup(group2,helper2,tracked2,rules2,empty2,2);f.setup(group3,helper3,tracked3,rules3,empty3,3);
        f.setup(group4,helper4,tracked4,rules4,manual,4);put(group4,0x30,static_cast<void*>(nullptr));
        put(f.array,0x18,uintptr_t{5});put(f.array,0x30,static_cast<void*>(&group2));
        put(f.array,0x38,static_cast<void*>(&group3));put(f.array,0x40,static_cast<void*>(&group4));
        check(manual.dictionary.typedBuckets.at(75)==&manual.oldType,"canonical typed bucket key differs");
        f.position.components[7]=1;f.type.components[7]=75;f.army.components[7]=0;
        f.state.admission.frame=110;f.state.admission.entities[7]={0,75,900};
        f.state.groupIntent.remember(1,{4,7},{75,0,900});
        put(f.config,0x10,uint32_t{76});f.state.identities[&f.actor]={{7,76,0},0};
        f.retired={{&f.actor,{7,76,0},{7,75,0},false,0}};
        actors::Current current(&f.frames);const auto canonical=current.identity(7);
        check(canonical&&canonical->unitType==75&&canonical->armyId==0&&!current.identity(99)&&
            actors::confirmedToken(f.state,*canonical)==900&&actors::resident(&f.actor).unitType==76&&
            f.state.identities.at(&f.actor).incarnation==0,"ownership RED setup differs");
        check(f.state.groupIntent.classify(1,{4,7},true,ba_prediction_group_intent::Identity{75,0,900},false)==
            ba_prediction_group_intent::Decision::Keep,"original canonical intent does not own membership");
        exact(manual.allIds,{7,99});exact(manual.oldIds,{7,99});
        actors::GroupChanges changes;changes.prepare({&group4},f.retired,&f.state);changes.begin();changes.mutated=true;
        changes.prune();changes.close();
        check(helper4.disposed==1&&!host::read<bool>(&helper4,0x10)&&!host::controlGroupClears&&
            !host::automaticCalls&&!host::groupRemovals,"ownership case used Clear/re-add or leaked original scope");
        const auto remembered=f.state.groupIntent.entries().find({4,7});
        check(remembered!=f.state.groupIntent.entries().end()&&remembered->second==ba_prediction_group_intent::Identity{75,0,900},
            "canonical intent metadata vanished before same-lease admission");
        auto allIds=manual.allIds.values,typedIds=manual.oldIds.values;
        std::sort(allIds.begin(),allIds.end());std::sort(typedIds.begin(),typedIds.end());
        check(std::binary_search(allIds.begin(),allIds.end(),uint32_t{99})&&std::binary_search(typedIds.begin(),typedIds.end(),uint32_t{99}),
            "ownership case lost unrelated pending99");
        std::cout<<"OWNERSHIP CHECK priorCases="<<cases<<" allCount="<<manual.allIds.values.size()
            <<" allFirst="<<allIds.front()<<" typedCount="<<manual.oldIds.values.size()<<" typedFirst="<<typedIds.front()
            <<" ledgerToken="<<remembered->second.token
            <<" physicalType=76 physicalToken=0 canonicalType=75 canonicalToken=900"
            <<" originalAddCalls="<<host::automaticCalls<<" wholeClearCalls="<<host::controlGroupClears<<'\n';
        check(allIds==std::vector<uint32_t>({7,99})&&typedIds==std::vector<uint32_t>({7,99}),
            "RED: actual physical-ID prune drops canonical logical member7 while pending99 and canonical intent900 survive");
    });
    run("protected-only count dirty once and tracked lease retained",[](Fixture& f){
        CanonicalGroup g(f);actors::GroupChanges changes;g.prepare(f,changes);changes.prune();changes.close();
        exact(g.selected.allIds,{7,99});exact(g.selected.oldIds,{7,99});exact(g.tracked,{7,99});
        check(host::dirtyCalls==1&&!host::ledCalls&&!host::trackedRemoves&&!host::automaticCalls&&
            changes.values.front()->retainedIntents.size()==1&&f.state.groupIntent.entries().count({4,7})==1&&
            host::read<int32_t>(&g.selected.set,0x54)==-1&&g.helper.disposed==1,
            "protected logical membership/count/tracked state differs");
    });
    for(int mode=0;mode<5;++mode)run(("canonical absence or identity mismatch "+std::to_string(mode)).c_str(),[&](Fixture& f){
        CanonicalGroup g(f);
        if(mode==0)f.state.admission.entities.erase(7);
        if(mode==1){f.state.admission.entities[7].type=76;f.type.components[7]=76;f.retired[0].current.unitType=76;}
        if(mode==2){f.state.admission.entities[7].army=1;f.army.components[7]=1;f.retired[0].current.armyId=1;}
        if(mode==3)f.state.admission.entities[7].incarnation=901;if(mode==4)f.state.admission.entities[7].incarnation=0;
        actors::GroupChanges changes;g.prepare(f,changes);changes.prune();changes.close();
        exact(g.selected.allIds,{99});exact(g.selected.oldIds,{99});exact(g.tracked,{99});
        check(host::dirtyCalls==1&&host::ledCalls==2&&changes.values.front()->retainedIntents.empty()&&!host::automaticCalls,
            "noncanonical logical lease was protected or double-dirtied");
    });
    run("missing logical record does not protect speculative presentation",[](Fixture& f){
        CanonicalGroup g(f);f.state.groupIntent.erase(1,{4,7});actors::GroupChanges changes;g.prepare(f,changes);changes.prune();changes.close();
        exact(g.selected.allIds,{99});exact(g.selected.oldIds,{99});exact(g.tracked,{99});check(host::dirtyCalls==1&&host::ledCalls==2,"unrecorded ID protected");
    });
    for(bool ghost:{false,true})run(ghost?"original user removal wins and typed ghost purged":"original user removal stays absent",[&](Fixture& f){
        CanonicalGroup g(f);g.selected.allIds.values={99};put(g.selected.all,0x18,uint32_t{99});
        if(!ghost){g.selected.oldIds.values={99};put(g.selected.oldType,0x18,uint32_t{99});}
        actors::GroupChanges changes;g.prepare(f,changes);changes.prune();changes.close();
        exact(g.selected.allIds,{99});exact(g.selected.oldIds,{99});exact(g.tracked,{99});
        check(host::dirtyCalls==1&&host::ledCalls==(ghost?1u:0u)&&!host::automaticCalls&&!host::controlGroupClears&&
            changes.values.front()->retainedIntents.empty(),"user removal resurrected/protected stale membership");
    });
    for(bool multiple:{false,true})run(multiple?"canonical ownership multiple ghosts refuses before mutation":"canonical ownership wrong key refuses before mutation",[&](Fixture& f){
        CanonicalGroup g(f);
        if(multiple){g.selected.newIds.values={7};put(g.selected.newType,0x18,uint32_t{7});g.selected.dictionary.objects.push_back(&g.selected.newType);g.selected.dictionary.typedBuckets[76]=&g.selected.newType;}
        else {g.selected.dictionary.typedBuckets.erase(75);g.selected.dictionary.typedBuckets[76]=&g.selected.oldType;}
        actors::GroupChanges changes;g.prepare(f,changes,true);refused([&]{changes.prune();});changes.close(true);
        exact(g.selected.allIds,{7,99});exact(g.selected.oldIds,{7,99});exact(f.second.allIds,{7,100});
        check(!host::dirtyCalls&&!host::ledCalls&&!host::trackedRemoves&&g.helper.disposed==1&&f.helper1.disposed==1,
            "unproven typed ownership mutated a group or leaked cleanup");
    });
    run("mixed canonical protected and invalidated IDs",[](Fixture& f){
        CanonicalGroup g(f);Node actor8,config8;actor8.klass=host::type("Uncapped","Unit");config8.klass=host::type("Uncapped","EntityConfig");
        put(actor8,0x14c,uint32_t{8});put(actor8,0x150,uint32_t{0});put(actor8,0x168,static_cast<void*>(&config8));put(config8,0x10,uint32_t{77});
        f.state.identities[&actor8]={{8,77,0},0};f.position.components[8]=1;f.type.components[8]=78;f.army.components[8]=0;
        f.state.admission.entities[8]={0,78,901};f.retired.push_back({&actor8,{8,77,0},{8,78,0},false,0});
        g.selected.allIds.values={7,8,99};g.selected.newIds.values={8};put(g.selected.newType,0x18,uint32_t{8});
        g.selected.dictionary.objects.push_back(&g.selected.newType);g.selected.dictionary.typedBuckets[77]=&g.selected.newType;g.tracked.values={7,8,99};
        actors::GroupChanges changes;g.prepare(f,changes);changes.prune();changes.close();
        exact(g.selected.allIds,{7,99});exact(g.selected.oldIds,{7,99});exact(g.selected.newIds,{});exact(g.tracked,{7,99});
        check(host::dirtyCalls==1&&host::ledCalls==2&&host::trackedRemoves==1&&changes.values.front()->retainedIntents.size()==1&&
            f.state.groupIntent.entries().at({4,7}).token==900&&!host::automaticCalls,"mixed purge deleted canonical intent or rewrote pending members");
    });
    for(int mode=0;mode<5;++mode)run(("canonical owner drift during raw lookup "+std::to_string(mode)).c_str(),[&](Fixture& f){
        CanonicalGroup g(f);actors::GroupChanges changes;g.prepare(f,changes,true);
        host::lookupHook=[&](void*){
            if(mode==0)host::movementWorld=0;if(mode==1)f.state.admission.entities[7].type=76;
            if(mode==2)f.state.admission.entities[7].army=1;if(mode==3)f.state.admission.entities[7].incarnation=901;
            if(mode==4)f.state.groupIntent.erase(1,{4,7});
        };
        refused([&]{changes.prune();});try{changes.close(true);}catch(const std::exception&){}changes.close(true);
        exact(g.selected.allIds,{7,99});exact(g.selected.oldIds,{7,99});exact(f.second.allIds,{7,100});
        check(!host::dirtyCalls&&!host::ledCalls&&!host::trackedRemoves&&g.helper.disposed==1&&f.helper1.disposed==1,
            "lookup drift adapted a later group or retried cleanup");
    });
    run("canonical drift during Mark stops later groups",[](Fixture& f){
        CanonicalGroup g(f);actors::GroupChanges changes;g.prepare(f,changes,true);
        host::markHook=[&](void* helper){if(helper==&g.helper)f.state.admission.entities[7].incarnation=901;};
        refused([&]{changes.prune();});try{changes.close(true);}catch(const std::exception&){}changes.close(true);
        exact(g.selected.allIds,{7,99});exact(g.tracked,{7,99});exact(f.second.allIds,{7,100});
        check(host::dirtyCalls==1&&!host::ledCalls&&!host::dirtyBySet[&f.second.set]&&g.helper.disposed==1&&f.helper1.disposed==1,
            "post-query canonical drift continued adaptation/cleanup");
    });
    run("canonical token loss current-type route acknowledges only after Dispose",[](Fixture& f){
        CanonicalLoss g(f);f.type.components[7]=75;f.state.admission.entities[7]={0,75,901};
        bool markedPending=false,disposedPending=false;
        host::markHook=[&](void* helper){if(helper==&g.helper)markedPending=f.state.groupIntent.entries().count({4,7})==1;};
        host::disposeHook=[&](void* helper){if(helper==&g.helper)disposedPending=f.state.groupIntent.entries().count({4,7})==1;};
        actors::reconcileGroupIntent(f.state);
        exact(g.selected.allIds,{99});exact(g.selected.oldIds,{99});exact(g.selected.newIds,{});
        check(markedPending&&disposedPending&&f.state.groupIntent.entries().empty()&&g.helper.disposed==1&&
            host::groupMarks==1&&host::groupNotifications==1&&!host::automaticCalls&&!host::controlGroupClears,
            "canonical loss acknowledged before successful original scope/notification");
    });
    run("canonical loss original user Clear wins",[](Fixture& f){
        CanonicalLoss g(f);g.selected.allIds.values.clear();g.selected.oldIds.values.clear();g.selected.set.components.clear();
        put(g.selected.all,0x18,UINT32_MAX);put(g.selected.oldType,0x18,UINT32_MAX);
        actors::reconcileGroupIntent(f.state);exact(g.selected.allIds,{});exact(g.selected.oldIds,{});
        check(f.state.groupIntent.entries().empty()&&!host::groupRemovals&&!host::ledCalls&&!host::dirtyCalls&&
            !host::groupMarks&&!host::groupNotifications&&!g.helper.disposed&&!host::automaticCalls,
            "original Clear was resurrected or unnecessarily purged");
    });
    run("canonical loss original mutation exception keeps metadata and closes once",[](Fixture& f){
        CanonicalLoss g(f);host::failLed=&g.selected.all;
        refused([&]{actors::reconcileGroupIntent(f.state);});exact(g.selected.allIds,{7,99});exact(g.selected.oldIds,{7,99});
        check(f.state.groupIntent.entries().at({4,7}).token==900&&g.helper.disposed==1&&!host::read<bool>(&g.helper,0x10)&&
            !host::groupMarks&&!host::groupNotifications&&!host::groupRemovals&&host::ledCalls==1,
            "failed original mutation acknowledged metadata or retried/leaked scope");
    });
    for(int mode=0;mode<4;++mode)run(("canonical loss exact current owner refusal "+std::to_string(mode)).c_str(),[&](Fixture& f){
        CanonicalLoss g(f);
        if(mode==0)host::movementWorld=0;if(mode==1)put(f.simulation,0x148,static_cast<void*>(nullptr));
        if(mode==2)f.frame.klass=host::type("Authored","WrongFrame");if(mode==3)put(g.helper,0x18,static_cast<void*>(&f.group1));
        refused([&]{actors::reconcileGroupIntent(f.state);});exact(g.selected.allIds,{7,99});exact(g.selected.oldIds,{7,99});
        check(f.state.groupIntent.entries().size()==1&&!host::groupRemovals&&!host::ledCalls&&!host::dirtyCalls&&
            !host::groupMarks&&!g.helper.disposed,"invalid current owner reached canonical-loss mutation");
    });
    run("canonical loss Begin owner drift refuses and closes once",[](Fixture& f){
        CanonicalLoss g(f);host::beginHook=[&](void* group){if(group==&g.group)host::movementWorld=0;};
        refused([&]{actors::reconcileGroupIntent(f.state);});exact(g.selected.allIds,{7,99});exact(g.selected.oldIds,{7,99});
        check(f.state.groupIntent.entries().size()==1&&g.helper.disposed==1&&!host::read<bool>(&g.helper,0x10)&&
            !host::groupRemovals&&!host::ledCalls&&!host::dirtyCalls&&!host::groupMarks,
            "Begin owner drift continued mutation or failed once-only cleanup");
    });
    run("canonical loss Dispose owner drift keeps unacknowledged metadata",[](Fixture& f){
        CanonicalLoss g(f);f.type.components[7]=75;f.state.admission.entities[7]={0,75,901};
        host::disposeHook=[&](void* helper){if(helper==&g.helper)host::movementWorld=0;};
        refused([&]{actors::reconcileGroupIntent(f.state);});exact(g.selected.allIds,{99});exact(g.selected.oldIds,{99});
        check(f.state.groupIntent.entries().at({4,7}).token==900&&g.helper.disposed==1&&host::groupMarks==1&&host::groupNotifications==1,
            "Dispose owner drift acknowledged metadata or retried cleanup");
    });
    run("canonical loss current-type change needs every raw cached bucket purged",[](Fixture& f){
        CanonicalLoss g(f);check(!host::leaveGroupTyped,"canonical-loss RED must not inject a skipped typed removal");
        std::string failure;try{actors::reconcileGroupIntent(f.state);}catch(const std::exception& e){failure=e.what();}
        std::cout<<"CANONICAL LOSS CHECK priorCases="<<cases<<" currentTypeRoutes="<<host::removeCurrentTypeRoutes
            <<" resolvedType="<<host::lastRemoveType<<" allCount="<<g.selected.allIds.values.size()
            <<" oldTypedCount="<<g.selected.oldIds.values.size()<<" currentTypedCount="<<g.selected.newIds.values.size()
            <<" metadataEntries="<<f.state.groupIntent.entries().size()<<" disposed="<<g.helper.disposed
            <<" marks="<<host::groupMarks<<" notifications="<<host::groupNotifications
            <<" originalRemove="<<host::groupRemovals<<" rawLedRemove="<<host::ledCalls<<" skipTypedInjected="<<host::leaveGroupTyped
            <<" originalFailure="<<failure<<'\n';
        check(failure.empty(),"RED: actual canonical-loss reconciliation resolves only current type76 and leaves old typed75 ghost7");
        exact(g.selected.allIds,{99});exact(g.selected.oldIds,{99});exact(g.selected.newIds,{});
        check(f.state.groupIntent.entries().empty()&&g.helper.disposed==1&&host::groupMarks==1&&host::groupNotifications==1&&
            !host::controlGroupClears&&!host::automaticCalls&&!host::groupRemovals&&host::ledCalls==2,
            "canonical-loss cleanup did not surgically purge all original raw buckets before acknowledgment");
    });
    for(int stage=0;stage<3;++stage)for(int mode=0;mode<9;++mode)
        run(("canonical loss callback current snapshot "+std::to_string(stage)+":"+std::to_string(mode)).c_str(),[&](Fixture& f){
            CanonicalLoss g(f);Node otherFrames,otherFrame,otherBuffer;
            otherFrames.calls["get_Current"]=&f.frame;otherFrame.klass=f.frame.klass;otherFrame.calls=f.frame.calls;
            put(otherFrame,0x40,int32_t{110});otherBuffer.klass=host::type("Authored","ComponentBuffer");
            auto drift=[&](){
                if(mode==0)f.frames.calls["get_Current"]=&otherFrame; // Same collection/index, different current node.
                if(mode==1)put(f.frame,0x40,int32_t{111});
                if(mode==2)f.frame.calls["get_PositionBuffer"]=&otherBuffer;
                if(mode==3)f.frame.calls["get_TypeBuffer"]=&otherBuffer;
                if(mode==4)f.frame.calls["get_ArmyBuffer"]=&otherBuffer;
                if(mode==5)put(f.simulation,0x148,static_cast<void*>(&otherFrames));
                if(mode==6)f.state.admission.frame=111;
                if(mode==7)put(f.array,0x40,static_cast<void*>(&f.group1));
                if(mode==8)put(f.array,0x18,uintptr_t{4});
            };
            if(stage==0)host::beginHook=[&](void* group){if(group==&g.group)drift();};
            if(stage==1)host::markHook=[&](void* helper){if(helper==&g.helper)drift();};
            if(stage==2)host::disposeHook=[&](void* helper){if(helper==&g.helper)drift();};
            refused([&]{actors::reconcileGroupIntent(f.state);});
            exact(g.selected.allIds,stage==0?std::vector<uint32_t>{7,99}:std::vector<uint32_t>{99});
            exact(g.selected.oldIds,stage==0?std::vector<uint32_t>{7,99}:std::vector<uint32_t>{99});
            check(f.state.groupIntent.entries().at({4,7}).token==900&&g.helper.disposed==1&&
                host::disposeByHelper[&g.helper]==1&&!host::read<bool>(&g.helper,0x10)&&!host::groupRemovals&&
                host::dirtyCalls==(stage==0?0u:1u)&&host::ledCalls==(stage==0?0u:2u)&&
                host::groupMarks==(stage==0?0u:1u)&&host::groupNotifications==(stage==0?0u:1u),
                "current snapshot drift acknowledged metadata, continued mutation or retried cleanup");
        });
    for(int stage=0;stage<3;++stage)for(int mode=0;mode<6;++mode)
        run(("canonical loss callback identity snapshot "+std::to_string(stage)+":"+std::to_string(mode)).c_str(),[&](Fixture& f){
            CanonicalLoss g(f);
            auto drift=[&](){
                if(mode==0)f.state.admission.entities.erase(7);
                if(mode==1)f.state.admission.entities[7].type=75;
                if(mode==2)f.state.admission.entities[7].army=1;
                if(mode==3)f.state.admission.entities[7].incarnation=902;
                if(mode>=4)f.state.groupIntent.erase(1,{4,7});
                if(mode==5)f.state.groupIntent.remember(1,{4,7},{75,0,902});
            };
            if(stage==0)host::beginHook=[&](void* group){if(group==&g.group)drift();};
            if(stage==1)host::markHook=[&](void* helper){if(helper==&g.helper)drift();};
            if(stage==2)host::disposeHook=[&](void* helper){if(helper==&g.helper)drift();};
            refused([&]{actors::reconcileGroupIntent(f.state);});
            exact(g.selected.allIds,stage==0?std::vector<uint32_t>{7,99}:std::vector<uint32_t>{99});
            exact(g.selected.oldIds,stage==0?std::vector<uint32_t>{7,99}:std::vector<uint32_t>{99});
            if(mode==4)check(f.state.groupIntent.entries().empty(),"callback-removed metadata was resurrected");
            else check(f.state.groupIntent.entries().at({4,7}).token==(mode==5?902u:900u),"drifted callback metadata was erased or overwritten");
            check(g.helper.disposed==1&&host::disposeByHelper[&g.helper]==1&&!host::read<bool>(&g.helper,0x10)&&
                !host::groupRemovals&&host::dirtyCalls==(stage==0?0u:1u)&&host::ledCalls==(stage==0?0u:2u)&&
                host::groupMarks==(stage==0?0u:1u)&&host::groupNotifications==(stage==0?0u:1u),
                "identity drift continued adaptation or retried original cleanup");
        });
    run("canonical loss partial old-typed Led failure retains metadata",[](Fixture& f){
        CanonicalLoss g(f);host::failLed=&g.selected.oldType;
        refused([&]{actors::reconcileGroupIntent(f.state);});exact(g.selected.allIds,{99});exact(g.selected.oldIds,{7,99});
        check(f.state.groupIntent.entries().at({4,7}).token==900&&host::dirtyCalls==1&&host::ledCalls==2&&
            !host::groupRemovals&&!host::groupMarks&&!host::groupNotifications&&g.helper.disposed==1&&
            host::read<int32_t>(&g.selected.set,0x54)==-1,"partial Led failure acknowledged metadata or left count valid");
    });
    for(bool typed:{false,true})run(typed?"canonical loss typed Led throws after mutation":"canonical loss all Led throws after mutation",[&](Fixture& f){
        CanonicalLoss g(f);host::failLedAfter=typed?&g.selected.oldType:&g.selected.all;
        refused([&]{actors::reconcileGroupIntent(f.state);});exact(g.selected.allIds,{99});
        exact(g.selected.oldIds,typed?std::vector<uint32_t>{99}:std::vector<uint32_t>{7,99});
        check(f.state.groupIntent.entries().at({4,7}).token==900&&host::dirtyCalls==1&&host::ledCalls==(typed?2u:1u)&&
            !host::groupMarks&&!host::groupNotifications&&g.helper.disposed==1&&!host::groupRemovals,
            "after-mutation Led exception acknowledged metadata or continued mutation");
    });
    run("canonical loss original Dispose failure keeps completed purge unacknowledged",[](Fixture& f){
        CanonicalLoss g(f);host::failDispose=&g.helper;refused([&]{actors::reconcileGroupIntent(f.state);});
        exact(g.selected.allIds,{99});exact(g.selected.oldIds,{99});
        check(f.state.groupIntent.entries().at({4,7}).token==900&&host::dirtyCalls==1&&host::ledCalls==2&&
            host::groupMarks==1&&host::groupNotifications==1&&g.helper.disposed==1&&host::disposeByHelper[&g.helper]==1,
            "failed original Dispose acknowledged metadata or was retried");
    });
    run("canonical loss primary Led exception survives Dispose failure",[](Fixture& f){
        CanonicalLoss g(f);host::failLed=&g.selected.oldType;host::failDispose=&g.helper;
        std::string error;try{actors::reconcileGroupIntent(f.state);}catch(const std::exception& e){error=e.what();}
        check(error=="injected original Led.Remove failure","cleanup replaced the original Led exception");
        exact(g.selected.allIds,{99});exact(g.selected.oldIds,{7,99});
        check(f.state.groupIntent.entries().at({4,7}).token==900&&host::ledCalls==2&&!host::groupMarks&&
            !host::groupNotifications&&g.helper.disposed==1&&host::disposeByHelper[&g.helper]==1,"double failure lost metadata or retried cleanup");
    });
    run("canonical loss first partial failure stops later pending group",[](Fixture& f){
        CanonicalLoss g(f);Selection selected5{100};Node group5,helper5,tracked5,rules5;
        group5.klass=host::type("Uncapped","ControlGroup");helper5.klass=host::type("Authored","GroupHelper");
        tracked5.klass=host::type("Uncapped.Collections","EntityIdSet");f.setup(group5,helper5,tracked5,rules5,selected5,5);
        put(group5,0x30,static_cast<void*>(nullptr));put(f.array,0x18,uintptr_t{6});put(f.array,0x48,static_cast<void*>(&group5));
        f.state.groupIntent.remember(1,{5,7},{75,0,900});host::failLed=&g.selected.oldType;
        refused([&]{actors::reconcileGroupIntent(f.state);});exact(g.selected.allIds,{99});exact(g.selected.oldIds,{7,99});
        exact(selected5.allIds,{7,100});exact(selected5.oldIds,{7,100});
        check(f.state.groupIntent.entries().size()==2&&host::ledCalls==2&&host::dirtyCalls==1&&!host::dirtyBySet[&selected5.set]&&
            g.helper.disposed==1&&!helper5.disposed&&!host::groupMarks,"first failure adapted/acknowledged a later pending group");
    });
    run("canonical loss original removal during Begin uses no resurrection and one dirty",[](Fixture& f){
        CanonicalLoss g(f);host::beginHook=[&](void* group){if(group==&g.group){
            g.selected.allIds.values={99};g.selected.oldIds.values={99};g.selected.set.components.erase(7);
            put(g.selected.all,0x18,uint32_t{99});put(g.selected.oldType,0x18,uint32_t{99});
        }};
        actors::reconcileGroupIntent(f.state);exact(g.selected.allIds,{99});exact(g.selected.oldIds,{99});
        check(f.state.groupIntent.entries().empty()&&!host::ledCalls&&!host::groupRemovals&&host::dirtyCalls==1&&
            host::groupMarks==1&&host::groupNotifications==1&&g.helper.disposed==1&&!host::automaticCalls,
            "original removal during Begin was re-added or double-dirtied");
    });
    std::cout<<"PASS "<<cases<<" actual-source pre-pool group-scope cases; original initializer suspension diagnostic exercised; no Unity/IL2CPP/game/DLL loads\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
