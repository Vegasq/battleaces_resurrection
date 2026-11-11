// Authored fake-host controls of ACTUAL clickCapture and HeldSelection.
// No original game, Unity, IL2CPP or Simulation DLL is loaded.
#include "prediction_actor_test_host.hpp"

namespace held_side {
namespace actors=ba_prediction_actors;namespace input=ba_prediction_input_observer;
namespace proof=ba_prediction_click_provenance;using host::Node;using host::put;using host::check;
struct Fixture:scope_test::Fixture {
    scope_test::Selection current{99},preview{99},casting{99};
    Node helper,camera,server,commands,player,component,active,activeArray,activeIds,fresh,freshConfig,gameOwner;
    uint32_t entity,armyId;uint64_t logicalToken=700;input::Ticket ticket;
    Fixture(uint32_t id,uint32_t armyValue,int slot):entity(id),armyId(armyValue) {
        host::heldFields.clear();host::heldMovementEnabled=true;host::heldSlot=slot;host::vector2Bytes=8;
        auto* selectorType=host::type("Uncapped","UnitSelector");auto* helperType=host::type("","SelectionChangeHelper");
        helperType->declaring=selectorType;helper.klass=helperType;camera.klass=host::type("UnityEngine","Camera");
        server.klass=host::type("Uncapped","GameServerIntegration");player.klass=host::type("Uncapped","SimPlayer");
        component.klass=host::type("Authored","ComponentBuffer");active.klass=host::type("Uncapped.Collections","UnitSet");
        activeIds.klass=host::type("Uncapped.Collections","EntityIdSet");fresh.klass=host::type("Uncapped","Unit");
        freshConfig.klass=host::type("Uncapped","EntityConfig");gameOwner.klass=host::type("Authored","GameOwner");
        auto declare=[&](host::Class* owner,const char* name,size_t offset,host::Class* fieldClass){host::heldFields[{owner,name}]={offset,fieldClass,owner};};
        auto* boolean=host::type("System","Boolean");auto* single=host::type("System","Single");auto* vector=host::type("UnityEngine","Vector2");
        auto* object=host::type("System","Object");auto* managerType=host::type("Uncapped","UnitManager");
        declare(selectorType,"_simulation",0x138,simulation.klass);declare(selectorType,"_unitManager",0x40,managerType);
        declare(selectorType,"_selectionChangeHelper",0x80,helperType);declare(selectorType,"_camera",0xc0,camera.klass);
        declare(selectorType,"_appendCommands",0x118,boolean);declare(selectorType,"<ForceSelectAllUnitsOfSameType>k__BackingField",0x190,boolean);
        declare(selectorType,"_doubleClickFirstClickReferencePosition",0x12c,vector);declare(selectorType,"_currentPointerPosition",0x14c,vector);
        declare(selectorType,"_pointerDownPosition",0x164,vector);declare(selectorType,"_lastPointerUpTime",0x154,single);
        declare(selectorType,"_doubleClickTime",0x28,single);declare(selectorType,"_focusChaseControlGroup",0xa0,host::type("System","Int32"));
        declare(helperType,"_unitSelector",0x20,selectorType);declare(helperType,"_unitManager",0x28,managerType);
        declare(helperType,"_confirmerOverride",0x18,object);declare(helperType,"<IsSuspended>k__BackingField",0x10,boolean);
        declare(helperType,"<AutoRaise>k__BackingField",0x11,boolean);declare(helperType,"_playerInitiatedChange",0x13,boolean);
        declare(simulation.klass,"_localPlayer",0x90,player.klass);declare(player.klass,"ArmyID",0x38,host::type("System","UInt32"));
        declare(config.klass,"IsHQ",0x2c,boolean);declare(server.klass,"_queuedInputCommands",0x180,object);
        put(selector,0x80,static_cast<void*>(&helper));put(selector,0xc0,static_cast<void*>(&camera));
        put(helper,0x20,static_cast<void*>(&selector));put(helper,0x28,static_cast<void*>(&manager));put(helper,0x11,true);
        put(selector,0x16c,true);put(selector,0x170,int32_t{1});put(selector,0x128,entity);put(selector,0xa0,int32_t{-1});
        put(selector,0x12c,100.0f);put(selector,0x130,200.0f);put(selector,0x14c,100.0f);put(selector,0x150,200.0f);
        put(selector,0x164,100.0f);put(selector,0x168,200.0f);put(selector,0x154,1.0f);put(selector,0x28,0.3f);
        put(simulation,0x90,static_cast<void*>(&player));put(player,0x38,armyId);put(server,0x140,static_cast<void*>(&simulation));
        put(server,0x180,static_cast<void*>(&commands));host::castingServer=&server;host::castingQueue=&commands;ba::owner=&gameOwner;
        setShape(current,true);setShape(preview,true);setShape(casting,false);
        put(selector,0x90,static_cast<void*>(&current.set));put(selector,0x88,static_cast<void*>(&preview.set));put(selector,0x98,static_cast<void*>(&casting.set));
        put(actor,0x14c,entity);put(actor,0x150,armyId);put(config,0x10,uint32_t{3});put(config,0x2c,true);
        put(actor,0x158,static_cast<void*>(&component));put(actor,0x160,false);
        put(active,0x10,static_cast<void*>(&activeArray));put(active,0x18,static_cast<void*>(&activeIds));
        put(manager,0x10,static_cast<void*>(&active));setActive(&actor);
        position.components={{entity,1}};type.components={{entity,3}};army.components={{entity,armyId}};
        frame.calls["get_StateBuffer"]=&component;component.components={{entity,0}};put(frame,0x40,int32_t{150});
        state.identities.clear();state.identities[&actor]={{entity,3,armyId},logicalToken};
        state.admission.entities.clear();state.admission.entities[entity]={armyId,3,logicalToken};state.admission.frame=150;state.inUpdate=false;
    }
    void setShape(scope_test::Selection& value,bool present) {
        value.allIds.values=present?std::vector<uint32_t>{entity}:std::vector<uint32_t>{};value.oldIds.values=value.allIds.values;
        value.set.components.clear();if(present)value.set.components[entity]=1;
        put(value.all,0x18,present?entity:UINT32_MAX);put(value.oldType,0x18,present?entity:UINT32_MAX);
        value.dictionary.typedBuckets.clear();value.dictionary.typedBuckets[3]=&value.oldType;
        put(value.set,0x48,static_cast<void*>(&frames));
    }
    void setActive(Node* value) {
        put(activeIds,0x10,int32_t{value?1:0});put(activeArray,0x18,uintptr_t{1});put(activeArray,0x20,static_cast<void*>(value));
    }
    void accept() {
        const input::Owner owner{state.groupGeneration,state.world,reinterpret_cast<uintptr_t>(&selector),reinterpret_cast<uintptr_t>(&manager),GetCurrentThreadId()};
        ticket=state.inputIntent.begin(owner,input::Kind::Down);check(state.inputIntent.markSingleDown(ticket),"genuine ledger marker refused");
        check(state.inputIntent.complete(ticket)&&state.inputIntent.accepted()&&proof::same(ticket,*state.inputIntent.accepted()),"completed accepted Down missing");
    }
    void graph() {
        actors::Current now(&frames);const auto identity=now.identity(entity);
        check(identity&&identity->unitType==3&&identity->armyId==armyId&&actors::confirmedToken(state,*identity)==logicalToken,
            "authored current/canonical identity differs");
        check(actors::clickSelectionShape(&current.set,entity,3,true)&&actors::clickSelectionShape(&preview.set,entity,3,true)&&
            actors::clickSelectionShape(&casting.set,entity,3,false),"authored raw typed shapes differ");
        check(host::read<uint32_t>(&player,0x38)==armyId&&host::read<bool>(&config,0x2c)&&host::queueLocks==0,"authored localArmy/HQ/queue graph differs");
    }
    bool capture(){accept();graph();check(!state.clickProvenance.press(),"Press was pre-seeded");
        actors::clickCapture(state,&selector,ticket);return state.clickProvenance.press().has_value();}
    void release() {
        state.inUpdate=true;put(frame,0x40,int32_t{163});put(actor,0x160,true);put(actor,0x158,static_cast<void*>(nullptr));setActive(nullptr);
    }
    std::vector<actors::Retire> retiring() {return {{&actor,{entity,3,armyId},{entity,3,armyId},true,logicalToken}};}
    void admit(bool reuse=false) {
        put(fresh,0x14c,entity);put(fresh,0x150,armyId);put(fresh,0x168,static_cast<void*>(&freshConfig));put(freshConfig,0x10,uint32_t{3});put(freshConfig,0x2c,true);
        put(fresh,0x158,static_cast<void*>(&component));put(fresh,0x160,false);state.identities.erase(&actor);
        if(reuse) {
            put(actor,0x158,static_cast<void*>(&component));put(actor,0x160,false);
            state.identities[&actor]={{entity,3,armyId},logicalToken};setActive(&actor);
        } else {state.identities[&fresh]={{entity,3,armyId},logicalToken};setActive(&fresh);}
    }
    void prepareComplete(bool reuse=false) {
        release();actors::HeldSelection held(state);
        check(held.prepare(&selector,retiring())&&held.allows(&selector),"actual HeldSelection prepare refused coherent captured episode");
        admit(reuse);held.complete(&selector);
        check(!held.allows(&selector)&&state.clickProvenance.phase()==proof::Phase::Held&&state.inputIntent.serial()==ticket.serial,
            "completion changed source/provenance or left exemption reusable");graph();
    }
};
struct Unwritten {
    Fixture& fixture;std::array<unsigned char,0x220> selector,helper;
    std::vector<std::vector<uint32_t>> sets;
    explicit Unwritten(Fixture& f):fixture(f),selector(f.selector.bytes),helper(f.helper.bytes) {
        for(auto* value:{&f.current,&f.preview,&f.casting})for(auto* ids:{&value->allIds,&value->oldIds,&value->newIds})sets.push_back(ids->values);
    }
    void verify(bool fields=true)const {
        check(!fields||(fixture.selector.bytes==selector&&fixture.helper.bytes==helper),"adapter wrote original click/history/helper fields");
        size_t index=0;for(auto* value:{&fixture.current,&fixture.preview,&fixture.casting})for(auto* ids:{&value->allIds,&value->oldIds,&value->newIds})
            check(ids->values==sets[index++],"adapter wrote original numeric selection");
        check(!host::selectionRemovals&&!host::groupRemovals&&!host::dirtyCalls&&!host::ledCalls&&!host::automaticCalls&&
            !host::controlGroupClears&&!host::castingClears&&!host::queueLocks,"adapter invoked a selection/dirty/casting mutator");
    }
};
static unsigned cases=0;
static void run(const std::string& name,const std::function<void(Fixture&)>& operation,uint32_t id=0,uint32_t army=0,int slot=0) {
    Fixture fixture(id,army,slot);
    try {operation(fixture);++cases;}catch(...){std::cerr<<"FAIL "<<name<<'\n';throw;}
}
static bool rejected(const std::function<bool()>& operation) {
    try{return !operation();}catch(const std::exception&){return true;}
}
static void refuseCapture(Fixture& f,bool fields=true) {
    Unwritten before(f);check(rejected([&]{actors::clickCapture(f.state,&f.selector,f.ticket);return bool(f.state.clickProvenance.press());}),
        "invalid actual capture accepted");check(!f.state.clickProvenance.press(),"refused capture retained a Press");before.verify(fields);
}
static void refusePrepare(Fixture& f) {
    Unwritten before(f);actors::HeldSelection held(f.state);
    check(rejected([&]{return held.prepare(&f.selector,f.retiring());}),"invalid actual held preservation prepared");before.verify();
}
static void paired() {
    for(int side=0;side<2;++side)for(bool reuse:{false,true})run("paired capture/prepare/complete",[=](Fixture& f){
        Unwritten before(f);check(f.capture(),"actual paired capture missing");
        const auto press=*f.state.clickProvenance.press();
        check(press.identity.entity==f.entity&&press.identity.army==f.armyId&&press.identity.type==3&&press.identity.token==700&&
            press.ticket.serial==f.ticket.serial&&f.state.clickSnapshot.graph[8]==&f.player,"captured source identity/player differs");
        f.prepareComplete(reuse);before.verify();
    },side?5u:0u,static_cast<uint32_t>(side),side);
    run("parameterized local identity independent of slot",[](Fixture& f){Unwritten before(f);check(f.capture(),"nonfixture local ID capture missing");f.prepareComplete();before.verify();},42,0,1);
}
static void captureControls() {
    for(int mode=0;mode<25;++mode){if(mode==12||mode==13)continue;run("capture refusal "+std::to_string(mode),[=](Fixture& f){
        f.accept();
        switch(mode) {
        case 0:put(f.player,0x38,uint32_t{1});break;
        case 1:put(f.selector,0x128,uint32_t{5});break;
        case 2:f.type.components[f.entity]=4;break;
        case 3:f.setShape(f.current,false);break;
        case 4:f.setShape(f.preview,false);break;
        case 5:f.current.allIds.values.push_back(99);break;
        case 6:f.preview.oldIds.values.push_back(99);break;
        case 7:f.current.dictionary.typedBuckets={{4,&f.current.oldType}};break;
        case 8:f.preview.newIds.values={f.entity};put(f.preview.newType,0x18,f.entity);f.preview.dictionary.objects.push_back(&f.preview.newType);break;
        case 9:put(f.config,0x2c,false);break;
        case 10:host::heldFields[{f.player.klass,"ArmyID"}].type=host::type("System","Int32");break;
        case 11:host::heldFields[{f.config.klass,"IsHQ"}].offset=0x30;break;
        case 12:host::heldFields[{f.selector.klass,"_simulation"}].offset=0x48;break;
        case 13:host::heldFields[{f.helper.klass,"_unitManager"}].offset=0x40;break;
        case 14:host::vector2Bytes=16;break;
        case 15:f.state.admission.entities[f.entity].type=4;break;
        case 16:f.state.admission.entities[f.entity].army=1;break;
        case 17:f.state.admission.entities[f.entity].incarnation=701;break;
        case 18:f.state.admission.entities[f.entity].incarnation=0;break;
        case 19:f.state.identities[&f.actor].incarnation=0;break;
        case 20:put(f.selector,0x128,UINT32_MAX);break;
        case 21:f.army.components[f.entity]=1;break;
        case 22:f.setShape(f.casting,true);break;
        case 23:host::heldFields[{f.player.klass,"ArmyID"}].parent=f.selector.klass;break;
        case 24:put(f.config,0x2c,uint8_t{2});break;
        }
        refuseCapture(f);
    });}
    for(int mode=0;mode<3;++mode)run("accepted Down marker contract "+std::to_string(mode),[=](Fixture& f){
        const input::Owner owner{f.state.groupGeneration,f.state.world,reinterpret_cast<uintptr_t>(&f.selector),reinterpret_cast<uintptr_t>(&f.manager),GetCurrentThreadId()};
        f.ticket=f.state.inputIntent.begin(owner,input::Kind::Down);
        if(mode!=0)check(f.state.inputIntent.markSingleDown(f.ticket),"marker setup refused");
        if(mode==0)check(f.state.inputIntent.complete(f.ticket),"unmarked completion failed");
        if(mode==2)f.state.inputIntent.abandon(f.ticket);
        refuseCapture(f);
    });
    for(int mode=0;mode<3;++mode)run("capture callback drift "+std::to_string(mode),[=](Fixture& f){
        f.accept();Node alternate;alternate.klass=f.player.klass;put(alternate,0x38,f.armyId);bool changed=false;
        host::lookupHook=[&](void*){if(changed)return;changed=true;
            if(mode==0)put(f.player,0x38,uint32_t{1});
            if(mode==1)put(f.simulation,0x90,static_cast<void*>(&alternate));
            if(mode==2)put(f.selector,0x128,uint32_t{99});
        };refuseCapture(f,false);check(changed,"capture callback did not execute");
    });
}
static void heldControls() {
    for(int mode=0;mode<12;++mode)run("post-capture identity/owner drift "+std::to_string(mode),[=](Fixture& f){
        check(f.capture(),"control genuine capture missing");f.release();Node alternate;alternate.klass=f.player.klass;put(alternate,0x38,f.armyId);
        switch(mode) {
        case 0:put(f.player,0x38,uint32_t{1});break;
        case 1:put(f.simulation,0x90,static_cast<void*>(&alternate));break;
        case 2:f.state.admission.entities[f.entity].incarnation=701;break;
        case 3:f.state.admission.entities[f.entity].incarnation=0;break;
        case 4:f.state.admission.entities[f.entity].type=4;break;
        case 5:f.state.admission.entities[f.entity].army=1;break;
        case 6:put(f.selector,0x128,uint32_t{99});break;
        case 7:f.state.groupGeneration++;break;
        case 8:f.state.world++;break;
        case 9:f.setShape(f.preview,false);break;
        case 10:put(f.selector,0x118,true);break;
        case 11:f.commands.values={12};break;
        }refusePrepare(f);
    });
    for(int mode=0;mode<9;++mode)run("replacement refusal "+std::to_string(mode),[=](Fixture& f){
        check(f.capture(),"replacement control capture missing");f.release();actors::HeldSelection held(f.state);
        check(held.prepare(&f.selector,f.retiring()),"replacement control prepare missing");
        Node alternate;alternate.klass=f.player.klass;put(alternate,0x38,f.armyId);
        if(mode!=0)f.admit();
        switch(mode) {
        case 0:f.setActive(&f.actor);break; // stale dead/released physical actor
        case 1:put(f.fresh,0x160,true);break;
        case 2:put(f.fresh,0x158,static_cast<void*>(nullptr));break;
        case 3:f.state.identities[&f.fresh].incarnation=701;break;
        case 4:put(f.freshConfig,0x2c,false);break;
        case 5:put(f.frame,0x40,int32_t{164});break;
        case 6:put(f.player,0x38,uint32_t{1});break;
        case 7:put(f.simulation,0x90,static_cast<void*>(&alternate));break;
        case 8:f.state.admission.entities[f.entity].incarnation=701;break;
        }
        Unwritten before(f);check(rejected([&]{held.complete(&f.selector);return true;}),"invalid replacement completed");before.verify();
    });
    for(int kind=0;kind<=static_cast<int>(input::Kind::ContextUp);++kind)run("later original callback invalidates "+std::to_string(kind),[=](Fixture& f){
        check(f.capture(),"later-input capture missing");f.release();unsigned originals=0;
        struct Access {Fixture& f;input::Kind kind;unsigned& originals;input::Ticket ticket;
            bool prepare(){ticket=f.state.inputIntent.begin(f.ticket.owner,kind);return true;}
            void original(){++originals;}void complete(){check(f.state.inputIntent.complete(ticket),"later input completion refused");}
            void failed(const char*){throw std::runtime_error("later input observer failed");}void abandon(){f.state.inputIntent.abandon(ticket);}
        } access{f,static_cast<input::Kind>(kind),originals,{}};
        input::forward(access);check(originals==1,"original callback did not forward once");refusePrepare(f);
    });
    run("no-op original selection observer invalidates",[](Fixture& f){
        check(f.capture(),"no-op capture missing");f.release();Unwritten before(f);actors::clickExternalEdit(f.state);
        check(!f.state.inputIntent.accepted()&&!f.state.clickProvenance.press(),"no-op observer retained provenance");refusePrepare(f);before.verify();
    });
    for(bool afterAdmission:{false,true})run("no-op invalidates prepared preservation",[=](Fixture& f){
        check(f.capture(),"prepared no-op capture missing");f.release();actors::HeldSelection held(f.state);
        check(held.prepare(&f.selector,f.retiring())&&held.allows(&f.selector),"prepared no-op setup differs");
        if(afterAdmission)f.admit();Unwritten before(f);actors::clickExternalEdit(f.state);
        check(!held.allows(&f.selector)&&rejected([&]{held.complete(&f.selector);return true;}),"prepared no-op left reusable permission");before.verify();
    });
    for(int side=0;side<2;++side)run("actual natural removal remains refused",[](Fixture& f){
        check(f.capture(),"natural capture missing");f.state.inUpdate=true;put(f.frame,0x40,int32_t{156});
        Node batch,ids;batch.klass=host::type("Uncapped.Collections","UnitSet");ids.klass=host::type("Uncapped.Collections","EntityIdSet");
        ids.values={f.entity};put(batch,0x18,static_cast<void*>(&ids));
        {actors::ClickOriginalUpdate update(f.state);proof::Removal operation;
            check(actors::clickBeginNatural(f.state,&f.selector,&batch,nullptr,operation),"actual natural start refused mirrored ID");
            put(f.helper,0x10,true);
            check(actors::clickObserveRemovalPart(f.state,&f.preview.set,f.entity,proof::RemovalPart::Preview),"actual preview part refused");
            f.setShape(f.preview,false);
            check(actors::clickObserveRemovalPart(f.state,&f.current.set,f.entity,proof::RemovalPart::Current),"actual current part refused");
            f.setShape(f.current,false);actors::clickSelectionCommit(f.state,&f.selector,&f.helper);put(f.helper,0x10,false);
            check(actors::clickFinishNatural(f.state,&f.selector,operation)&&f.state.clickProvenance.phase()==proof::Phase::Removed,
                "actual natural completion did not record Removed");
        }
        f.release();refusePrepare(f);
    },side?5u:0u,static_cast<uint32_t>(side),side);
}
}
int main(int argc,char** argv){try{
    if(argc==2&&(!strcmp(argv[1],"--bad-selector-layout")||!strcmp(argv[1],"--bad-helper-layout"))) {
        held_side::run("cold original class layout",[&](held_side::Fixture& f){
            f.accept();if(!strcmp(argv[1],"--bad-selector-layout"))host::heldFields[{f.selector.klass,"_simulation"}].offset=0x48;
            else host::heldFields[{f.helper.klass,"_unitManager"}].offset=0x40;
            held_side::refuseCapture(f);
        });
        std::cout<<"prediction held identity cold-layout refusal PASS (1 case)\n";return 0;
    }
    held_side::paired();held_side::captureControls();held_side::heldControls();
    std::cout<<"prediction held identity actual binding tests PASS ("<<held_side::cases<<" cases)\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
