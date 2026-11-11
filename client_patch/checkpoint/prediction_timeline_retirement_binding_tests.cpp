// Authored original-API host of the ACTUAL repair ordering. No engine is loaded.
#include "prediction_actor_test_host.hpp"

namespace timeline_test {
namespace actors=ba_prediction_actors;
using host::Node;using host::Obj;using host::put;using host::check;
static unsigned char addCode[16]{},removeCode[16]{},poolCode[32]{},releaseCode[16]{},trackedCode[16]{};
static unsigned char stopCode[32]{},stateCode[32]{},callbackCode[32]{},controlledCode[24]{};
static host::Method addMethod,removeMethod,poolMethod,releaseMethod,trackedMethod,eventInvoke,stopMethod,stateMethod,callbackMethod,actionInvoke,controlledMethod;
struct UnitSet {
    Node set,array,ids;
    UnitSet(){set.klass=host::type("Uncapped.Collections","UnitSet");ids.klass=host::type("Uncapped.Collections","EntityIdSet");
        put(set,0x10,static_cast<Obj>(&array));put(set,0x18,static_cast<Obj>(&ids));put(array,0x18,uintptr_t{1});}
    void assign(Node* actor){put(ids,0x10,int32_t{actor?1:0});put(array,0x20,static_cast<Obj>(actor));
        ids.values=actor?std::vector<uint32_t>{host::read<uint32_t>(actor,0x14c)}:std::vector<uint32_t>{};}
};
struct Fixture:scope_test::Fixture {
    UnitSet active,retained,batch,released;
    scope_test::Selection current{99},preview{99},casting{99};
    Node player,states,pending,other0,other1,factory,pools,poolMap,subscribers,director,handler,invocationList,gameOwner;
    unsigned makes=0,stopCalls=0,poolAttempts=0,poolCompleted=0,callbackCalls=0;
    int32_t playState=1;
    uint32_t entity=0,armyValue=0;
    Obj subscriberTarget=nullptr,subscriberMethod=nullptr,subscriberList=nullptr;
    bool requiresStop=true,throwStop=false,remainPlaying=false,wrongStateBox=false;
    unsigned subscriberReads=0,stateReads=0;
    std::function<void()> subscriberHook,stateHook,stopHook;
    Fixture(){
        auto* unit=actor.klass;auto* directorClass=host::type("UnityEngine.Playables","PlayableDirector");
        auto* component=host::type("UnityEngine","Component");auto* object=host::type("UnityEngine","Object");
        auto* base=host::type("Uncapped","AbstractEventOwnerComponent");auto* action=host::type("System","Action`1");
        auto* delegate=host::type("System","Delegate");auto* multi=host::type("System","MulticastDelegate");
        auto* nothing=host::type("System","Void");auto* boolean=host::type("System","Boolean");
        auto* integer=host::type("System","Int32");auto* unitEvent=host::type("Uncapped","UnitEventArgs");
        auto* play=host::type("UnityEngine.Playables","PlayState");
        host::classParents[unit]=base;host::classParents[base]=component;host::classParents[directorClass]=component;
        host::classParents[component]=object;host::classParents[action]=multi;host::classParents[multi]=delegate;
        host::valueSizes[unitEvent]={16,8};host::enumClasses[play]=integer;host::valueSizes[play]={4,4};
        host::valueSizes[host::type("Uncapped","Id")]={4,4};
        host::valueSizes[host::type("System","IntPtr")]={8,8};
        host::extraLiterals[{play,"Paused"}]={0,play,play,0x56,0};host::extraLiterals[{play,"Playing"}]={0,play,play,0x56,1};
        player.klass=host::type("Uncapped","SimPlayer");states.klass=host::type("Authored","ComponentBuffer");
        for(auto* value:{&pending,&other0,&other1})value->klass=host::type("Uncapped.Collections","EntityIdSet");
        factory.klass=host::type("Uncapped","UnitFactory");pools.klass=host::type("Uncapped","UnitPoolManager");
        poolMap.klass=host::type("Authored","PoolDictionary");subscribers.klass=host::type("Authored","ReleaseDelegate");
        director.klass=directorClass;handler.klass=action;invocationList.klass=host::type("System","Delegate[]");
        gameOwner.klass=host::type("Authored","GameOwner");ba::owner=&gameOwner;
        addMethod={addCode,"Add",0x0600261b,boolean,1,0,active.set.klass};
        removeMethod={removeCode,"Remove",0x06002622,boolean,1,0,active.set.klass};
        poolMethod={poolCode,"Release",0x060021b1,nothing,1,0,pools.klass};
        releaseMethod={releaseCode,"ReleaseFromSim",0x060022a1,nothing,0,0,unit};
        trackedMethod={trackedCode,"Contains",0x060000ac,boolean,1,0,pending.klass};
        eventInvoke={reinterpret_cast<Obj>(&host::contains),"Invoke",0x06000001,nothing,2,0,subscribers.klass};
        stopMethod={stopCode,"Stop",0x06000018,nothing,0,0,directorClass};
        stateMethod={stateCode,"get_state",0x06000001,play,0,0,directorClass};
        callbackMethod={callbackCode,"OnPlayableDirectorStopped",0x06001c04,nothing,1,0,base};
        controlledMethod={controlledCode,"get_IsControlledBySim",0x060022dc,boolean,0,0,unit};
        actionInvoke={reinterpret_cast<Obj>(&host::contains),"Invoke",0x06000001,nothing,1,0,action};
        const unsigned char stopPrefix[]={0x40,0x53,0x48,0x83,0xec,0x20,0x48,0x8b,0x05,0xab,0x80,0xd8,0x01,0x48,0x8b,0xd9,0x48,0x85,0xc0,0x75,0x18,0x48,0x8d,0x0d,0xcc,0x34,0x62,0x00,0xe8,0xbf,0x91,0x53};
        const unsigned char statePrefix[]={0x40,0x53,0x48,0x83,0xec,0x20,0x48,0x8b,0x05,0x33,0x8c,0xd8,0x01,0x48,0x8b,0xd9,0x48,0x85,0xc0,0x75,0x18,0x48,0x8d,0x0d,0xf4,0x3d,0x62,0x00,0xe8,0xff,0x9c,0x53};
        const unsigned char callbackPrefix[]={0x40,0x53,0x48,0x83,0xec,0x20,0x48,0x8b,0x11,0x48,0x8b,0xd9,0x48,0x8b,0x82,0x18,0x03,0x00,0x00,0x48,0x8b,0x92,0x20,0x03,0x00,0x00,0xff,0xd0,0x84,0xc0,0x74,0x19};
        memcpy(stopCode,stopPrefix,sizeof(stopPrefix));memcpy(stateCode,statePrefix,sizeof(statePrefix));memcpy(callbackCode,callbackPrefix,sizeof(callbackPrefix));
        const unsigned char controlledPrefix[]={0x80,0xb9,0x60,0x01,0x00,0x00,0x00,0x74,0x03,0x32,0xc0,0xc3,0x48,0x83,0xb9,0x58,0x01,0x00,0x00,0x00,0x0f,0x97,0xc0,0xc3};
        memcpy(controlledCode,controlledPrefix,sizeof(controlledPrefix));
        active.set.klass->methods={&addMethod,&removeMethod};pools.klass->methods={&poolMethod};
        unit->methods={&releaseMethod,&controlledMethod};base->methods={&callbackMethod};directorClass->methods={&stateMethod,&stopMethod};
        selector.klass->methods.push_back(&host::removeSelectionMethod);
        pending.klass->methods.push_back(&trackedMethod);subscribers.klass->methods={&eventInvoke};action->methods={&actionInvoke};
        for(auto* method:{&addMethod,&removeMethod,&poolMethod,&releaseMethod,&trackedMethod,&eventInvoke,&stopMethod,&stateMethod,&callbackMethod,&actionInvoke,&controlledMethod})host::methodObjects.insert(method);
        host::parameterOverrides[&addMethod]={unit};host::parameterOverrides[&removeMethod]={unit};host::parameterOverrides[&poolMethod]={unit};
        host::parameterOverrides[&eventInvoke]={host::type("System","Object"),unitEvent};
        host::parameterOverrides[&callbackMethod]={directorClass};host::parameterOverrides[&actionInvoke]={directorClass};
        host::nativeOverrides={{0x3c6c280,addCode},{0x3c6c660,removeCode},{0x3be9770,poolCode},{0x3bfc570,releaseCode},{0x3782540,trackedCode},
            {0x50ddfb0,stopCode},{0x50dd470,stateCode},{0x3b927c0,callbackCode},{0x3c02a30,controlledCode},{0x3bf0cf0,host::removeSelectionMethod.function}};
        auto declare=[&](host::Class* owner,const char* name,size_t offset,host::Class* fieldType){host::heldFields[{owner,name}]={offset,fieldType,owner};};
        declare(manager.klass,"UnitsReleased",0x88,subscribers.klass);declare(actor.klass,"_playableDirector",0x48,directorClass);
        declare(actor.klass,"<EventOwnerId>k__BackingField",0x30,host::type("Uncapped","Id"));
        declare(directorClass,"m_CachedPtr",0x10,host::type("System","IntPtr"));declare(directorClass,"stopped",0x28,action);
        declare(config.klass,"IsHQ",0x2c,boolean);declare(actor.klass,"<DeadToTheSim>k__BackingField",0x160,boolean);
        declare(actor.klass,"_componentData",0x158,host::type("Authored","ComponentBuffer"));
        put(actor,0x14c,uint32_t{0});put(actor,0x150,uint32_t{0});put(config,0x10,uint32_t{3});put(config,0x2c,true);
        put(actor,0x160,true);put(actor,0x158,static_cast<Obj>(nullptr));put(actor,0x48,static_cast<Obj>(&director));put(actor,0x30,uint32_t{2});
        put(director,0x10,uintptr_t{0x1234});put(director,0x28,static_cast<Obj>(&handler));
        put(invocationList,0x18,uintptr_t{1});put(invocationList,0x20,static_cast<Obj>(&handler));
        subscriberTarget=&actor;subscriberMethod=&callbackMethod;subscriberList=&invocationList;
        put(manager,0x10,static_cast<Obj>(&active.set));put(manager,0xa0,static_cast<Obj>(&retained.set));
        put(manager,0x18,static_cast<Obj>(&pending));put(manager,0x28,static_cast<Obj>(&other0));put(manager,0x30,static_cast<Obj>(&other1));
        put(manager,0x50,static_cast<Obj>(&factory));put(manager,0x88,static_cast<Obj>(&subscribers));put(factory,0x10,static_cast<Obj>(&pools));put(pools,0x18,static_cast<Obj>(&poolMap));
        retained.assign(&actor);active.assign(nullptr);put(simulation,0x90,static_cast<Obj>(&player));put(player,0x38,uint32_t{0});
        position.components={{0,1}};type.components={{0,3}};army.components={{0,0}};states.components={{0,0}};
        frame.calls["get_StateBuffer"]=&states;put(frame,0x40,int32_t{157});
        state.identities.clear();state.identities[&actor]={{0,3,0},77};state.admission.entities.clear();state.admission.entities[0]={0,3,77};state.admission.frame=151;
        empty(current);empty(preview);empty(casting);empty(first);empty(second);tracked0.values.clear();tracked1.values.clear();rules0.values.clear();rules1.values.clear();
        put(selector,0x90,static_cast<Obj>(&current.set));put(selector,0x88,static_cast<Obj>(&preview.set));put(selector,0x98,static_cast<Obj>(&casting.set));
        put(selector,0xa0,int32_t{-1});put(selector,0x128,UINT32_MAX);put(selector,0x28,0.3f);
        host::makeHook=[&](const char* space,const char* name)->Obj{check(!strcmp(space,"Uncapped.Collections")&&!strcmp(name,"UnitSet")&&makes<2,"unexpected managed creation in retirement fixture");return makes++?&released.set:&batch.set;};
        host::callHook=[&](Obj receiver,const char* name,int count,void** args,Obj& result){
            if(receiver==&poolMap){check(!strcmp(name,"ContainsKey")&&count==1&&args&&*static_cast<uint32_t*>(args[0])==3,"pool lookup ABI differs");result=host::boolean(true);return true;}
            if(receiver==&handler){check(count==0&&!args,"stopped delegate query ABI differs");
                if(!strcmp(name,"GetInvocationList")){++subscriberReads;if(subscriberHook)subscriberHook();result=subscriberList;}
                else{check(!strcmp(name,"get_Target"),"unexpected delegate query");result=subscriberTarget;}return true;}
            return false;
        };
        host::getHook=[&](Obj receiver,const char* name,uintptr_t& value){if(receiver!=&handler)return false;check(!strcmp(name,"method"),"unexpected delegate field read");value=reinterpret_cast<uintptr_t>(subscriberMethod);return true;};
        host::invokeHook=[&,play](Obj method,Obj receiver,void** args,Obj& result){
            if(method==&addMethod){check(receiver==&batch.set&&args&&args[0]==&actor,"original batch Add ABI differs");batch.assign(&actor);result=host::boolean(true);return true;}
            if(method==&removeMethod){check(receiver==&retained.set&&args&&args[0]==&actor,"original retained Remove ABI differs");retained.assign(nullptr);result=host::boolean(true);return true;}
            if(method==&trackedMethod){check((receiver==&tracked0||receiver==&tracked1)&&args&&*static_cast<uint32_t*>(args[0])==entity,"tracked Contains ABI differs");result=host::boolean(false);return true;}
            if(method==&stateMethod){check(receiver==&director&&!args,"original state getter ABI differs");++stateReads;if(stateHook)stateHook();result=host::integer(playState);static_cast<Node*>(result)->klass=wrongStateBox?host::type("System","Int32"):play;return true;}
            if(method==&stopMethod){check(receiver==&director&&!args,"original Stop ABI differs");++stopCalls;host::interactionEvents.push_back("oldDirectorStop");
                check(host::read<bool>(&actor,0x160)&&!host::read<Obj>(&actor,0x158),"Stop callback observed live/rebound Unit");
                callbackCalls+=host::read<Obj>(&director,0x28)?static_cast<unsigned>(host::read<uintptr_t>(&invocationList,0x18)):0;
                if(stopHook)stopHook();if(throwStop)throw std::runtime_error("authored original Stop failure");
                if(!remainPlaying)playState=0;result=nullptr;return true;}
            if(method==&poolMethod){check(receiver==&pools&&args&&args[0]==&actor,"original pool Release ABI differs");++poolAttempts;host::interactionEvents.push_back("originalPoolRelease");
                check(!requiresStop||(stopCalls==1&&playState==0),"old retained HQ director was not stopped before original pool Release");++poolCompleted;result=nullptr;return true;}
            return false;
        };
        check(ba::method(&director,"Stop",0)==&stopMethod,"exact Stop metadata missing");
    }
    static void empty(scope_test::Selection& selection){selection.allIds.values.clear();selection.oldIds.values.clear();selection.set.components.clear();put(selection.all,0x18,UINT32_MAX);put(selection.oldType,0x18,UINT32_MAX);}
    void identity(uint32_t id,uint32_t armyId){entity=id;armyValue=armyId;put(actor,0x14c,id);put(actor,0x150,armyId);put(player,0x38,armyId);
        position.components={{id,1}};type.components={{id,3}};army.components={{id,armyId}};states.components={{id,0}};
        state.identities.clear();state.identities[&actor]={{id,3,armyId},77};state.admission.entities.clear();state.admission.entities[id]={armyId,3,77};retained.assign(&actor);}
    void repair(){actors::GroupChanges groups;actors::DeferredSelection selection;actors::repair(state,&manager,&frames,groups,selection);}
};
static unsigned cases=0;
static void run(const char* name,const std::function<void(Fixture&)>& body){Fixture fixture;try{body(fixture);++cases;}
    catch(...){std::cerr<<"FAIL "<<name<<" stop="<<fixture.stopCalls<<" poolAttempts="<<fixture.poolAttempts<<" poolCompleted="<<fixture.poolCompleted<<'\n';throw;}}
static void rejected(Fixture& f,unsigned stops=0){bool refused=false;try{f.repair();}catch(const std::exception&){refused=true;}
    check(refused,"actual retirement accepted invalid ownership/ABI");check(f.stopCalls==stops&&!f.poolAttempts,"refused preflight reached original Stop/pool mutation");
    check(host::read<int32_t>(&f.retained.ids,0x10)==1&&f.state.identities.count(&f.actor)==1,"refusal changed original actor membership");}
static void positive(Fixture& f,unsigned callbacks=1){const auto selector=f.selector.bytes,actor=f.actor.bytes,director=f.director.bytes;
    f.repair();check(f.stopCalls==1&&f.callbackCalls==callbacks&&f.poolCompleted==1,"original Stop/pool lifecycle counts differ");
    check(f.selector.bytes==selector&&!host::selectionRemovals&&!host::groupRemovals,"timeline retirement wrote original selection");
    check(f.actor.bytes==actor&&f.director.bytes==director,"repair wrote original actor/director fields");
    const auto stop=std::find(host::interactionEvents.begin(),host::interactionEvents.end(),"oldDirectorStop");
    const auto pool=std::find(host::interactionEvents.begin(),host::interactionEvents.end(),"originalPoolRelease");
    check(stop<pool&&f.state.identities.empty()&&!host::read<int32_t>(&f.retained.ids,0x10),"actual old actor retirement ordering differs");}
static void controls(){
    run("Core0 original Stop before pool",[](Fixture& f){positive(f);});
    run("Core5 original Stop before pool",[](Fixture& f){f.identity(5,1);positive(f);});
    run("already paused old graph still stops once",[](Fixture& f){f.playState=0;positive(f);});
    run("empty original invocation list",[](Fixture& f){put(f.invocationList,0x18,uintptr_t{0});positive(f,0);});
    run("null original stopped handler",[](Fixture& f){put(f.director,0x28,static_cast<Obj>(nullptr));positive(f,0);});
    run("duplicate exact original subscribers",[](Fixture& f){put(f.invocationList,0x18,uintptr_t{2});put(f.invocationList,0x28,static_cast<Obj>(&f.handler));positive(f,2);});
    run("no old director preserves ordinary path",[](Fixture& f){put(f.actor,0x48,static_cast<Obj>(nullptr));f.requiresStop=false;f.repair();check(!f.stopCalls&&f.poolCompleted==1,"missing director introduced a Stop");});
    run("still dead canonical HQ remains retained",[](Fixture& f){f.states.components[0]=6;f.repair();check(!f.stopCalls&&!f.poolAttempts&&host::read<int32_t>(&f.retained.ids,0x10)==1,"ordinary native death entered corrected-lifetime retirement");});
    run("fresh same-ID active actor is never stopped",[](Fixture& f){Node fresh=f.actor;put(fresh,0x160,false);put(fresh,0x158,static_cast<Obj>(&f.states));f.active.assign(&fresh);f.state.identities[&fresh]={{0,3,0},77};rejected(f);});
    run("destroyed original director",[](Fixture& f){put(f.director,0x10,uintptr_t{0});rejected(f);});
    run("old live Unit refused",[](Fixture& f){put(f.actor,0x160,false);rejected(f);});
    run("old rebound component refused",[](Fixture& f){put(f.actor,0x158,static_cast<Obj>(&f.states));rejected(f);});
    run("non-HQ original config refused",[](Fixture& f){put(f.config,0x2c,false);rejected(f);});
    run("zero old canonical incarnation",[](Fixture& f){f.state.identities.at(&f.actor).incarnation=0;rejected(f);});
    run("changed canonical token",[](Fixture& f){++f.state.admission.entities.at(0).incarnation;rejected(f);});
    run("missing canonical admission",[](Fixture& f){f.state.admission.entities.clear();rejected(f);});
    run("changed canonical army",[](Fixture& f){f.army.components[0]=1;f.state.admission.entities.at(0).army=1;rejected(f);});
    run("changed canonical type",[](Fixture& f){f.type.components[0]=4;f.state.admission.entities.at(0).type=4;rejected(f);});
    run("wrong Stop return ABI",[](Fixture& f){stopMethod.result=host::type("System","Boolean");rejected(f);});
    run("static Stop ABI",[](Fixture& f){stopMethod.flags=0x10;rejected(f);});
    run("wrong state return ABI",[](Fixture& f){stateMethod.result=host::type("System","Int32");rejected(f);});
    run("wrong PlayState scalar size",[](Fixture& f){host::valueSizes[host::type("UnityEngine.Playables","PlayState")].first=8;rejected(f);});
    run("Paused literal not literal",[](Fixture& f){host::extraLiterals[{host::type("UnityEngine.Playables","PlayState"),"Paused"}].flags=0x10;rejected(f);});
    run("wrong registry Id scalar size",[](Fixture& f){host::valueSizes[host::type("Uncapped","Id")].first=8;rejected(f);});
    run("wrong stopped declared field type",[](Fixture& f){host::heldFields[{f.director.klass,"stopped"}].type=host::type("System","Object");rejected(f);});
    run("wrong callback return ABI",[](Fixture& f){callbackMethod.result=host::type("System","UInt32");rejected(f);});
    run("wrong Action Invoke parameter",[](Fixture& f){host::parameterOverrides[&actionInvoke]={host::type("System","UInt32")};rejected(f);});
    run("other stopped subscriber target",[](Fixture& f){f.subscriberTarget=&f.config;rejected(f);});
    run("other stopped subscriber method",[](Fixture& f){f.subscriberMethod=&releaseMethod;rejected(f);});
    run("missing invocation list",[](Fixture& f){f.subscriberList=nullptr;rejected(f);});
    run("too many stopped subscribers",[](Fixture& f){put(f.invocationList,0x18,uintptr_t{17});rejected(f);});
    run("wrong original Stop prefix",[](Fixture& f){stopCode[0]^=1;rejected(f);});
    run("wrong original Unit control prefix",[](Fixture& f){controlledCode[0]^=1;rejected(f);});
    run("wrong original callback prefix",[](Fixture& f){callbackCode[0]^=1;rejected(f);});
    run("wrong original get_state box",[](Fixture& f){f.wrongStateBox=true;rejected(f);});
    run("original get_state throws",[](Fixture& f){f.stateHook=[](){throw std::runtime_error("authored original state query failure");};rejected(f);});
    run("world loss during subscriber preflight",[](Fixture& f){f.subscriberHook=[&](){if(f.subscriberReads==2)host::movementWorld=0;};rejected(f);});
    run("canonical token drift during state query",[](Fixture& f){f.stateHook=[&](){++f.state.admission.entities.at(0).incarnation;};rejected(f);});
    run("cached identity drift during state query",[](Fixture& f){f.stateHook=[&](){++f.state.identities.at(&f.actor).incarnation;};rejected(f);});
    run("raw entity drift during state query",[](Fixture& f){f.stateHook=[&](){put(f.actor,0x14c,uint32_t{99});};rejected(f);});
    run("registry Id drift during state query",[](Fixture& f){f.stateHook=[&](){put(f.actor,0x30,uint32_t{3});};rejected(f);});
    run("director destruction during state query",[](Fixture& f){f.stateHook=[&](){put(f.director,0x10,uintptr_t{0});};rejected(f);});
    run("stopped handler drift during state query",[](Fixture& f){f.stateHook=[&](){put(f.director,0x28,static_cast<Obj>(nullptr));};rejected(f);});
    run("frame collection drift during state query",[](Fixture& f){f.stateHook=[&](){put(f.simulation,0x148,static_cast<Obj>(nullptr));};rejected(f);});
    run("current frame node drift during state query",[](Fixture& f){Node fresh=f.frame;f.stateHook=[&](){f.frames.calls["get_Current"]=&fresh;};rejected(f);});
    run("simulation root loss during state query",[](Fixture& f){f.stateHook=[&](){host::failedRoot=&f.simulation;};rejected(f);});
    run("manager root loss during state query",[](Fixture& f){f.stateHook=[&](){host::failedRoot=&f.manager;};rejected(f);});
    run("original Stop throws without pooling",[](Fixture& f){f.throwStop=true;rejected(f,1);});
    run("original Stop does not pause",[](Fixture& f){f.remainPlaying=true;rejected(f,1);});
    run("owner lost inside original Stop",[](Fixture& f){f.stopHook=[](){host::movementWorld=0;};rejected(f,1);});
}
}
int main(){try{
    timeline_test::controls();
    std::cout<<"prediction timeline retirement actual binding tests PASS ("<<timeline_test::cases<<" cases)\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
