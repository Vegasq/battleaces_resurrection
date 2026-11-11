#pragma once
// Include after ba/ba_local helpers and the movement-worker integration.
// The normal recipe does not install this CALL hook. No worker-thread mutation.
#include <map>
#include <set>
#include <memory>
#include <algorithm>
#include <exception>
#include "../checkpoint/prediction_presentation_policy.hpp"
#include "prediction_movement.hpp"
#include "prediction_casting_cleanup.hpp"
#include "prediction_group_intent.hpp"
#include "prediction_click_policy.hpp"
#include "prediction_input_observer.hpp"

namespace ba_prediction_actors {
using ba::Obj;
using ba_local::Root;
namespace policy=ba_prediction_presentation;
constexpr size_t maximumActors=8192;

static void require(bool value,const char* reason) {
    if(!value)throw std::runtime_error(reason);
}
struct Span {const uint32_t* values=nullptr;int count=0;int padding=0;};
static_assert(sizeof(Span)==16,"Original ReadOnlySpan<uint> ABI changed");
struct UnitEvent {Obj units=nullptr,currentFrame=nullptr;};
static_assert(sizeof(UnitEvent)==16,"Original UnitEventArgs ABI changed");
struct Resident {policy::ActorIdentity identity;uint64_t incarnation=0;};
struct Retire {
    Obj actor=nullptr;
    policy::ActorIdentity resident,current;
    bool alreadyReleased=false;
};
struct State {
    uint64_t world=0;
    std::string match;
    DWORD thread=0;
    bool checked=false,inUpdate=false,failed=false;
    std::unique_ptr<Root> simulation,manager;
    std::map<Obj,Resident> identities;
    std::map<uint32_t,policy::ActorIdentity> pending;
    ba_prediction_worker::MovementAdmission admission;
    std::set<uint32_t> confirmedRecreation;
    uint64_t groupGeneration=0;
    ba_prediction_group_intent::Ledger groupIntent;
    ba_prediction_input_observer::Ledger inputIntent;
};
static State& state(){static State* lifetime=new State;return *lifetime;}
static bool flag(){return ba::flag(L"-prediction-movement-experimental");}
static void clearInactive(State& s) {
    if(!s.world && !s.manager && !s.simulation && s.identities.empty() && s.pending.empty())return;
    require(!s.inUpdate && ba::initialThread && GetCurrentThreadId()==ba::initialThread &&
            (!s.thread || s.thread==GetCurrentThreadId()),
            "inactive actor cache retirement requires its retained Unity thread");
    // These roots/caches belong to this observer, not original actor ownership.
    // Native shutdown may set worldID=0 on another thread; only this original
    // main-thread presentation boundary frees GC handles. No actor pool/reset,
    // native world API, selection callback or original collection is touched.
    ba::log("Prediction actors inactive: world=%llu match=%s observerRootsOnly=1 actorsUntouched=1",
        static_cast<unsigned long long>(s.world),s.match.c_str());
    s.identities.clear();s.pending.clear();s.admission={};s.confirmedRecreation.clear();s.groupIntent.clear();s.inputIntent.discard();s.manager.reset();s.simulation.reset();
    s.world=0;s.match.clear();s.thread=0;s.checked=false;s.failed=false;
}

static void guard(uintptr_t rva,const char* bytes,size_t size) {
    require(!memcmp(ba::native<const void*>(rva),bytes,size),"actor repair original code guard differs");
}
static void guards() {
    guard(0x3c08010,"\x48\x8b\xc4\x48\x89\x50\x10\x48\x89\x48\x08\x53\x56\x57\x41\x54\x41",17);
    guard(0x3c0913c,"\xe8\xaf\xe8\xff\xff",5);
    guard(0x3c08655,"\xe8\xf6\x86\x50\xff",5);
    guard(0x3be9770,"\x48\x89\x6c\x24\x20\x57\x48\x83\xec\x20\x80\x3d\x71\xf7\x26\x03",16);
    guard(0x3bf0cf0,"\x48\x89\x5c\x24\x10\x48\x89\x4c\x24\x08\x56\x57\x41\x54\x41\x56",16);
    guard(0x3c6c660,"\x40\x53\x48\x83\xec\x20\x48\x8b\xd9\x48\x85\xd2\x0f\x84\xfa\x00",16);
    guard(0x3c54b2d,"\xe8\x0e\x15\x00\x00",5);
    guard(0x3e66151,"\xff\x57\x18",3);
    guard(0x3ea5790,"\x48\x83\xec\x28\x48\x8b\x49\x40\x48\x85\xc9\x74\x0c\x45\x33\xc0\x48\x83\xc4\x28\xe9\xe7\xc9\xc5\xff\xe8\x42\xef\x73\xfc\xcc",31);
    guard(0x3b02160,"\x33\xd2\xe9\x79\x01\x00\x00",7);
    guard(0x3ea6236,"\x8b\x97\x4c\x01\x00\x00\x45\x33\xc0\xe8\x2c\xc3\x8d\xff\x49\x8b\x4d\x20\x48\x85\xc9\x0f\x84\xf4\x00\x00\x00\x8b\x97\x4c\x01\x00\x00\x45\x33\xc0",36);
    guard(0x3c66610,"\x48\x89\x5c\x24\x18\x89\x54\x24\x10\x48\x89\x4c\x24\x08\x56\x57\x41\x57\x48\x81\xec\x80\x00\x00\x00\x8b\xf2\x48\x8b\xf9",30);
    guard(0x3b02170,"\x80\x79\x10\x00\x75\x11\x48\x8b\x01\x48\x8b\x90\x90\x01\x00\x00\x48\xff\xa0\x88\x01\x00\x00\xc6\x41\x12\x01\xc3",28);
}
static void field(Obj object,const char* name,size_t offset) {
    static std::map<std::pair<Obj,std::string>,size_t> checked;
    require(object!=nullptr,"actor repair field receiver missing");
    auto key=std::make_pair(ba::klass(object),std::string(name));auto found=checked.find(key);
    if(found!=checked.end()){require(found->second==offset,"actor field offset expectation changed");return;}
    require(object && ba::api<size_t(*)(Obj)>("il2cpp_field_get_offset")(ba::field(object,name))==offset,
            "actor repair original field layout differs");
    checked.emplace(std::move(key),offset);
}
static Obj type(const char* space,const char* name) {
    static std::map<std::pair<std::string,std::string>,Obj> checked;
    auto key=std::make_pair(std::string(space),std::string(name));auto found=checked.find(key);
    if(found!=checked.end())return found->second;
    Obj result=ba::find_class(space,name);require(result,"actor repair original class missing");
    checked.emplace(std::move(key),result);return result;
}
static void classIs(Obj object,const char* space,const char* name) {
    require(object && ba::klass(object)==type(space,name),"actor repair original concrete type differs");
}
static Obj method(Obj object,const char* name,unsigned count,uint32_t token,uintptr_t rva=0) {
    require(object!=nullptr,"actor repair method receiver missing");
    static std::map<std::pair<Obj,uint32_t>,Obj> checked;
    const auto key=std::make_pair(ba::klass(object),token);auto prior=checked.find(key);
    if(prior!=checked.end()) {
        require(!rva || ba::read<Obj>(prior->second,0)==ba::native<Obj>(rva),"actor method pointer changed");
        return prior->second;
    }
    for(Obj type=ba::klass(object);type;type=ba::api<Obj(*)(Obj)>("il2cpp_class_get_parent")(type)) {
        void* iter=nullptr;Obj found=nullptr;
        while(Obj value=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(type,&iter)) {
            if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(value),name) ||
               ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(value)!=count ||
               ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_token")(value)!=token)continue;
            require(!found && ba::read<Obj>(value,0) && (!rva || ba::read<Obj>(value,0)==ba::native<Obj>(rva)),
                    "actor repair original overload/pointer differs");found=value;
        }
        if(found){checked.emplace(key,found);return found;}
    }
    throw std::runtime_error("actor repair original method unavailable");
}
static Obj invoke(Obj methodInfo,Obj object,void** args=nullptr) {
    return ba_local::invokeMethod(methodInfo,object,args);
}
template<class T> static T unbox(Obj boxed) {
    require(boxed!=nullptr,"actor repair boxed result missing");
    return *ba::api<T*(*)(Obj)>("il2cpp_object_unbox")(boxed);
}
static bool contains(Obj values,uint32_t id) {
    Obj info=method(values,"Contains",1,0x0600013c);
    static std::set<Obj> checked;
    if(!checked.count(info)) {
        require(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(info,0))==type("System","UInt32") &&
            ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(info))==type("System","Boolean"),
            "actor component Contains signature differs");
        checked.insert(info);
    }
    // Exact original closed NativeSparseDataSet<T>.Contains(uint) ABI. Passing
    // its actual MethodInfo preserves generic context; no per-actor boxing.
    return reinterpret_cast<bool(*)(Obj,uint32_t,Obj)>(ba::read<Obj>(info,0))(values,id,info);
}
// Use exact non-generic original methods for mutating ID/Unit sets. Calling
// Remove by name/arity would choose between uint and Unit overloads ambiguously.
static void removeId(Obj set,uint32_t id) {
    void* args[]={&id};
    invoke(method(set,"Remove",1,0x060000ad,0x3782570),set,args);
}
static void removeUnit(Obj set,Obj unit) {
    void* args[]={unit};
    Root result(invoke(method(set,"Remove",1,0x06002622,0x3c6c660),set,args));
    require(unbox<bool>(result.get()),"old actor was missing during exact membership removal");
}
static std::vector<Obj> units(Obj set) {
    classIs(set,"Uncapped.Collections","UnitSet");
    field(set,"_units",0x10);field(set,"_entityIds",0x18);
    const Obj array=ba::read<Obj>(set,0x10),ids=ba::read<Obj>(set,0x18);
    require(array && ids,"actor repair UnitSet storage missing");
    const int count=ba::read<int>(ids,0x10);
    const uintptr_t capacity=ba::read<uintptr_t>(array,0x18);
    require(count>=0 && static_cast<size_t>(count)<=maximumActors && static_cast<uintptr_t>(count)<=capacity,
            "actor repair UnitSet count exceeds bound");
    std::vector<Obj> result;result.reserve(static_cast<size_t>(count));
    for(int index=0;index<count;++index) {
        Obj actor=ba::read<Obj>(array,0x20+static_cast<size_t>(index)*sizeof(Obj));
        classIs(actor,"Uncapped","Unit");result.push_back(actor);
    }
    return result;
}
static std::vector<uint32_t> ids(Obj set) {
    classIs(set,"Uncapped.Collections","EntityIdSet");
    // Original SparseSet.get_Values returns a sixteen-byte ReadOnlySpan<uint>
    // via a hidden result pointer (RCX); copy before any later managed call.
    Span span;
    ba::native<Span*(*)(Span*,Obj,Obj)>(0x3787d20)(&span,set,nullptr);
    require(span.count>=0 && static_cast<size_t>(span.count)<=maximumActors &&
            (!span.count || span.values),"pending ID span exceeds bound");
    if(!span.count)return {};
    return std::vector<uint32_t>(span.values,span.values+span.count);
}
static policy::ActorIdentity resident(Obj actor) {
    field(actor,"<EntityId>k__BackingField",0x14c);field(actor,"_fallbackArmyId",0x150);
    field(actor,"_entityConfig",0x168);
    Obj config=ba::read<Obj>(actor,0x168);classIs(config,"Uncapped","EntityConfig");
    field(config,"UnitType",0x10);
    return {ba::read<uint32_t>(actor,0x14c),ba::read<uint32_t>(config,0x10),ba::read<uint32_t>(actor,0x150)};
}
static uint64_t confirmedToken(const State& s,const policy::ActorIdentity& identity) {
    const auto found=s.admission.entities.find(identity.entityId);
    return found!=s.admission.entities.end() && found->second.type==identity.unitType &&
        found->second.army==identity.armyId?found->second.incarnation:0;
}
static bool confirmedInterval(const State& s,int frame) {
    // BEGIN requires the native allocation observer. It guards every14-tick
    // rolling interval; never extend that proof to an arbitrarily old map.
    const int64_t distance=static_cast<int64_t>(frame)-s.admission.frame;
    return frame>=-1 && s.admission.frame>=-1 && distance>=0 && distance<=12;
}
static bool tryValue(Obj buffer,uint32_t id,uint32_t& value) {
    // Original NativeComponentBuffer<T> inherits NativeSparseDataSet<T>, whose
    // TryGet returns a nullable value. Use its original Contains/get_Item pair;
    // validate the boxed value type before copying the uint32 identity.
    if(!contains(buffer,id))return false;
    Obj get=method(buffer,"get_Item",1,0x0600013d);
    require(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
        ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(get))==type("System","UInt32"),
        "actor identity component value is not uint32");
    value=reinterpret_cast<uint32_t(*)(Obj,uint32_t,Obj)>(ba::read<Obj>(get,0))(buffer,id,get);return true;
}
struct Current {
    Root frame,position,type,army;
    explicit Current(Obj frames):frame(ba::call(frames,"get_Current")),
        position(ba::call(frame.get(),"get_PositionBuffer")),
        type(ba::call(frame.get(),"get_TypeBuffer")),army(ba::call(frame.get(),"get_ArmyBuffer")) {
        classIs(frame.get(),"Uncapped.Collections.ComponentBuffers","SimFrameComponentBuffers");
    }
    std::optional<policy::ActorIdentity> identity(uint32_t id) const {
        if(!contains(position.get(),id))return std::nullopt;
        uint32_t unitType=0,armyId=0;
        require(tryValue(type.get(),id,unitType) && tryValue(army.get(),id,armyId),
                "present entity lacks corrected type/army");
        return policy::ActorIdentity{id,unitType,armyId};
    }
    bool retainedAlive(uint32_t id) const {
        Root states(ba::call(frame.get(),"get_StateBuffer"));
        require(contains(states.get(),id),"restored retained HQ lacks a current native state");
        Obj get=method(states.get(),"get_Item",1,0x0600013d);
        Obj valueType=ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(get));uint32_t alignment=0;
        require((valueType==ba_prediction_actors::type("System","UInt32") || ba::api<bool(*)(Obj)>("il2cpp_class_is_enum")(valueType)) &&
            ba::api<int32_t(*)(Obj,uint32_t*)>("il2cpp_class_value_size")(valueType,&alignment)==4,
            "retained HQ state scalar ABI differs");
        void* args[]={&id};Root boxed(invoke(get,states.get(),args));const auto value=unbox<uint32_t>(boxed.get());
        require(value!=0xffffffff,"retained HQ has no native state value");
        return value!=6; // An ordinary retained DEAD actor is not resurrection.
    }
};
static void remember(State& s,const std::vector<Obj>& actors,std::set<Obj>& live) {
    for(Obj actor:actors) {
        require(live.insert(actor).second,"same actor appears in two manager sets");
        const auto identity=resident(actor);
        const auto found=s.identities.find(actor);
        if(found==s.identities.end())s.identities.emplace(actor,Resident{identity,0});
        else require(found->second.identity.entityId==identity.entityId &&
            found->second.identity.unitType==identity.unitType && found->second.identity.armyId==identity.armyId,
            "resident actor changed creation identity outside repair");
    }
}
static void rememberPending(State& s,Obj pending,const Current& current) {
    std::map<uint32_t,policy::ActorIdentity> now;
    for(uint32_t id:ids(pending))if(auto identity=current.identity(id))now.emplace(id,*identity);
    s.pending=std::move(now);
}
static void checkContext(State& s,Obj manager,Obj frames) {
    require(GetCurrentThreadId()==ba::initialThread && ba::initialThread,"actor repair requires retained Unity main thread");
    classIs(manager,"Uncapped","UnitManager");
    field(manager,"_simulation",0x40);field(manager,"_units",0x10);
    field(manager,"_entitiesPendingCreation",0x18);field(manager,"_presentationOnlyUnits",0xa0);
    Obj simulation=ba::read<Obj>(manager,0x40);classIs(simulation,"Uncapped","Simulation");
    require(ba::read<Obj>(simulation,0x70)==manager && ba::read<Obj>(simulation,0x148)==frames,
            "actor repair manager/current collection owner differs");
    const auto world=ba_prediction_worker::movementWorldId();
    const auto& match=ba_prediction_worker::movementMatchId();
    require(world && match.size()==32,"actor repair movement identity missing");
    if(s.world!=world || s.match!=match) {
        require(s.groupGeneration!=UINT64_MAX,"actor group generation exhausted");
        s.groupIntent.reset(++s.groupGeneration);
        s.inputIntent.discard();
        s.identities.clear();s.pending.clear();s.admission={};s.confirmedRecreation.clear();s.simulation=std::make_unique<Root>(simulation);
        s.manager=std::make_unique<Root>(manager);s.world=world;s.match=match;s.thread=GetCurrentThreadId();
        s.failed=false;s.checked=false;
        ba::log("Prediction actors begin: world=%llu match=%s thread=%lu BA_RESURRECTION_PREDICTION_ACTORS_V1",
            static_cast<unsigned long long>(world),match.c_str(),s.thread);
    }
    require(!s.failed && s.thread==GetCurrentThreadId() && s.manager->get()==manager &&
            s.simulation->get()==simulation,"actor repair stale owner/generation");
    if(!s.checked){guards();s.checked=true;}
    s.admission=ba_prediction_worker::movementAdmission();
}
struct ReleaseEvent {
    Root callback;
    Obj invokeMethod=nullptr;
    explicit ReleaseEvent(Obj manager):callback(ba::read<Obj>(manager,0x88)) {
        field(manager,"UnitsReleased",0x88);
        require(callback.get()!=nullptr,"actor repair original release subscribers missing");
        Obj eventClass=ba::find_class("Uncapped","UnitEventArgs");uint32_t alignment=0;
        require(ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(eventClass) &&
                ba::api<int32_t(*)(Obj,uint32_t*)>("il2cpp_class_value_size")(eventClass,&alignment)==16,
                "actor repair UnitEventArgs value layout differs");
        invokeMethod=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")
            (ba::klass(callback.get()),"Invoke",2);
        require(invokeMethod && ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(invokeMethod,1))==eventClass,
            "actor repair release delegate event ABI differs");
    }
    void fire(Obj manager,Obj set,Obj frame) {
        UnitEvent value{set,frame};void* args[]={manager,&value};invoke(invokeMethod,callback.get(),args);
    }
};
static bool automaticType(Obj rules,uint32_t unitType) {
    if(!rules || !ba_local::count(rules))return false;
    Obj contains=method(rules,"Contains",1,0x06000d34);
    static std::set<Obj> checked;
    if(!checked.count(contains)) {
        Obj key=ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(contains,0));
        uint32_t alignment=0;
        require(key && ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(key) &&
            ba::api<int32_t(*)(Obj,uint32_t*)>("il2cpp_class_value_size")(key,&alignment)==4 &&
            !strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(key),"IntKey`1") &&
            !strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_namespace")(key),"Uncapped") &&
            ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
                ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(contains))==type("System","Boolean"),
            "automatic control-group IntKey<UnitType> Contains ABI differs");
        checked.insert(contains);
    }
    void* args[]={&unitType};Root result(invoke(contains,rules,args));return unbox<bool>(result.get());
}
static std::vector<Obj> affectedGroups(Obj selector,Obj simulation,const std::vector<Retire>& retire) {
    field(simulation,"_localPlayer",0x90);
    Root player(ba::read<Obj>(simulation,0x90));classIs(player.get(),"Uncapped","SimPlayer");
    field(player.get(),"ArmyID",0x38);const auto localArmy=ba::read<uint32_t>(player.get(),0x38);
    field(selector,"_controlGroupPanel",0x38);
    Root panel(ba::read<Obj>(selector,0x38));classIs(panel.get(),"Uncapped","ControlGroupPanel");
    field(panel.get(),"_controlGroups",0x38);
    Obj array=ba::read<Obj>(panel.get(),0x38);require(array,"actor repair control-group array missing");
    const uintptr_t count=ba::read<uintptr_t>(array,0x18);require(count>0 && count<=16,"actor repair group count bound");
    std::vector<Obj> result;
    for(uintptr_t i=0;i<count;++i) {
        Obj group=ba::read<Obj>(array,0x20+i*sizeof(Obj));classIs(group,"Uncapped","ControlGroup");
        field(group,"_unitIDs",0x20);field(group,"_trackedReleasedUnits",0x10);
        field(group,"_autoAssignments",0x30);
        Obj selected=ba::read<Obj>(group,0x20);require(selected,"actor repair group unit set missing");
        bool affected=false;
        for(const auto& actor:retire) {
            uint32_t id=actor.resident.entityId;void* args[]={&id};
            Root has(invoke(method(selected,"Contains",1,0x060025b7),selected,args));
            affected=affected || unbox<bool>(has.get());
            Obj tracked=ba::read<Obj>(group,0x10);
            Root remembered(invoke(method(tracked,"Contains",1,0x060000ac,0x3782540),tracked,args));
            affected=affected || unbox<bool>(remembered.get());
            if(!affected && actor.current.armyId==localArmy)
                affected=automaticType(ba::read<Obj>(group,0x30),actor.current.unitType);
        }
        if(affected) {
            method(group,"Clear",0,0x06001644,0x3ea5740);
            method(ba::read<Obj>(group,0x10),"Remove",1,0x060000ad,0x3782570);
            result.push_back(group);
        }
    }
    return result;
}
// Original Begin returns its SAME SuspendedEventHelper as IDisposable. Hold it
// through original recreation, clear only affected groups, then dispose once.
// No automatic rule is removed, rewritten or replaced. This is a source-backed
// candidate; original positive UI/group/HQ runtime qualification remains needed.
struct GroupChanges {
    struct Change {
        Root group,helper;
        Obj begin=nullptr,dispose=nullptr,clear=nullptr;
        bool begun=false,disposed=false;
        Change(Obj value):group(value),helper(ba::read<Obj>(value,0x40)){}
    };
    std::vector<std::unique_ptr<Change>> values;
    std::vector<uint32_t> retiredIds;
    bool mutated=false,closed=false;
    void prepare(const std::vector<Obj>& groups,const std::vector<Retire>& retire) {
        require(values.empty(),"actor group scopes prepared twice");
        for(const auto& actor:retire)retiredIds.push_back(actor.resident.entityId);
        values.reserve(groups.size());
        for(Obj group:groups) {
            field(group,"_controlGroupChangeHelper",0x40);
            auto value=std::make_unique<Change>(group);require(value->helper.get(),"original group change helper missing");
            field(value->helper.get(),"<IsSuspended>k__BackingField",0x10);
            Root suspended(invoke(method(value->helper.get(),"get_IsSuspended",0,0x060000c7,0x90fd60),value->helper.get()));
            require(!unbox<bool>(suspended.get()),"original group change already suspended");
            value->begin=method(group,"BeginControlGroupChange",1,0x06001645,0x3ea5790);
            value->dispose=method(value->helper.get(),"Dispose",0,0x060000cd,0x3b02160);
            value->clear=method(group,"Clear",0,0x06001644,0x3ea5740);
            values.push_back(std::move(value));
        }
    }
    void begin() {
        for(auto& value:values) {
            bool playerInitiated=false;void* args[]={&playerInitiated};
            Obj scope=nullptr;
            try{scope=invoke(value->begin,value->group.get(),args);}
            catch(...) {
                // Original BeginSuspend sets IsSuspended in its finally even
                // if OnBeginSuspension throws. Its rooted helper still needs
                // exactly one Dispose; a pre-entry reflection failure does not.
                value->begun=ba::read<bool>(value->helper.get(),0x10);throw;
            }
            // Mark ownership before validating the result; a failed check must
            // still Dispose the already-started original suspension exactly once.
            value->begun=true;
            require(scope==value->helper.get(),"original group suspension did not return its rooted helper");
        }
    }
    void close() {
        if(closed)return;
        std::exception_ptr error;
        for(auto& value:values)if(value->begun && !value->disposed) {
            if(mutated)try {
                Obj tracked=ba::read<Obj>(value->group.get(),0x10);
                for(auto id:retiredIds)removeId(tracked,id);
                invoke(value->clear,value->group.get());
                ba::log("Prediction actor control group cleared: group=%u changedIds=%zu originalScopeAcrossRecreation=1 automaticRulesPreserved=1 unaffectedGroupsRetained=1",
                    ba::read<uint32_t>(value->group.get(),0x38),retiredIds.size());
            }catch(...){if(!error)error=std::current_exception();}
            value->disposed=true;
            try{invoke(value->dispose,value->helper.get());}
            catch(...){if(!error)error=std::current_exception();}
        }
        closed=true;if(error)std::rethrow_exception(error);
    }
    ~GroupChanges(){try{close();}catch(...){ba::log("Prediction actor group scope cleanup failed: retry=0");}}
};
static bool selectionReferences(Obj selection,const std::set<uint32_t>& retired) {
    classIs(selection,"Uncapped.Collections","UnitSelectionSet");
    field(selection,"_allUnits",0x18);field(selection,"_subsetsByType",0x20);
    Root all(ba::read<Obj>(selection,0x18)),subsets(ba::read<Obj>(selection,0x20));
    require(all.get() && subsets.get(),"held gesture selection storage missing");
    const auto ledClass=ba::klass(all.get());
    auto references=[&](Obj led,size_t& total) {
        require(led && ba::klass(led)==ledClass,"held gesture typed selection class differs");
        field(led,"<Entities>k__BackingField",0x10);
        const auto values=ids(ba::read<Obj>(led,0x10));
        require(values.size()<=maximumActors-total,"held gesture cached selection ID budget exceeded");
        total+=values.size();
        return std::any_of(values.begin(),values.end(),[&](uint32_t id){return retired.count(id)!=0;});
    };
    size_t mainCount=0;if(references(all.get(),mainCount))return true;
    const Obj countMethod=method(subsets.get(),"get_Count",0,0x06002dcc);
    require(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
        ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(countMethod))==type("System","Int32"),
        "held gesture dictionary count signature differs");
    Root boxedCount(invoke(countMethod,subsets.get()));const int count=unbox<int>(boxedCount.get());
    require(count>=0 && static_cast<size_t>(count)<=maximumActors,"held gesture cached selection count exceeds bound");
    Root values(invoke(method(subsets.get(),"get_Values",0,0x06002dd0),subsets.get()));
    field(values.get(),"_dictionary",0x10);
    require(ba::read<Obj>(values.get(),0x10)==subsets.get(),"held gesture cached selection owner differs");
    Root iterator(invoke(method(values.get(),"GetEnumerator",0,0x06002e18),values.get()));
    require(iterator.get() && ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(ba::klass(iterator.get())),
        "held gesture selection enumerator is not a value type");
    const Obj move=method(iterator.get(),"MoveNext",0,0x06002e27);
    const Obj current=method(iterator.get(),"get_Current",0,0x06002e28);
    const Obj dispose=method(iterator.get(),"Dispose",0,0x06002e26);
    require(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
        ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(move))==type("System","Boolean"),
        "held gesture selection enumerator signature differs");
    // RuntimeInvoke expects the UNBOXED receiver for these original struct
    // methods. Retain the box and obtain its payload anew for each invocation.
    auto receiver=[&](){return ba::api<Obj(*)(Obj)>("il2cpp_object_unbox")(iterator.get());};
    bool disposed=false,found=false;size_t groups=0,total=0;
    auto close=[&](){if(!disposed){disposed=true;invoke(dispose,receiver());}};
    try {
        for(;;) {
            Root more(invoke(move,receiver()));if(!unbox<bool>(more.get()))break;
            require(++groups<=static_cast<size_t>(count),"held gesture cached selection enumeration exceeds count");
            Root led(invoke(current,receiver()));found=references(led.get(),total)||found;
        }
        require(groups==static_cast<size_t>(count),"held gesture cached selection count changed");
        close();return found;
    } catch(...) {try{close();}catch(...){ba::log("Held gesture readonly enumerator cleanup failed; retry=0");}throw;}
}
// Validate both original representations before retaining or purging an ID.
// Remove's absent-Type fallback removes only the first cached typed subset; a
// duplicate/ghost therefore refuses instead of becoming a partial repair.
static bool groupCacheMembership(Obj selection,uint32_t id) {
    classIs(selection,"Uncapped.Collections","UnitSelectionSet");
    field(selection,"_allUnits",0x18);field(selection,"_subsetsByType",0x20);
    Root all(ba::read<Obj>(selection,0x18)),subsets(ba::read<Obj>(selection,0x20));
    require(all.get() && subsets.get(),"group intent typed storage missing");
    const auto ledClass=ba::klass(all.get());size_t total=0;
    auto occurrences=[&](Obj led) {
        require(led && ba::klass(led)==ledClass,"group intent typed Led class differs");
        field(led,"<Entities>k__BackingField",0x10);
        const auto values=ids(ba::read<Obj>(led,0x10));
        require(values.size()<=maximumActors-total,"group intent typed ID budget exceeded");total+=values.size();
        const std::set<uint32_t> distinct(values.begin(),values.end());
        require(distinct.size()==values.size(),"group intent duplicate IDs in original Led set");
        return distinct.count(id);
    };
    const bool present=occurrences(all.get())!=0;total=0;
    const Obj countMethod=method(subsets.get(),"get_Count",0,0x06002dcc);
    require(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
        ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(countMethod))==type("System","Int32"),
        "group intent typed count signature differs");
    Root countValue(invoke(countMethod,subsets.get()));const int count=unbox<int>(countValue.get());
    require(count>=0 && static_cast<size_t>(count)<=maximumActors,"group intent typed count bound");
    Root values(invoke(method(subsets.get(),"get_Values",0,0x06002dd0),subsets.get()));
    field(values.get(),"_dictionary",0x10);
    require(ba::read<Obj>(values.get(),0x10)==subsets.get(),"group intent typed dictionary owner differs");
    Root iterator(invoke(method(values.get(),"GetEnumerator",0,0x06002e18),values.get()));
    require(iterator.get() && ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(ba::klass(iterator.get())),
        "group intent typed enumerator is not a value type");
    const Obj move=method(iterator.get(),"MoveNext",0,0x06002e27);
    const Obj current=method(iterator.get(),"get_Current",0,0x06002e28);
    const Obj dispose=method(iterator.get(),"Dispose",0,0x06002e26);
    require(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
        ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(move))==type("System","Boolean"),
        "group intent typed enumerator signature differs");
    auto receiver=[&](){return ba::api<Obj(*)(Obj)>("il2cpp_object_unbox")(iterator.get());};
    bool disposed=false;size_t groups=0,hits=0;
    auto close=[&](){if(!disposed){disposed=true;invoke(dispose,receiver());}};
    try {
        for(;;) {
            Root more(invoke(move,receiver()));if(!unbox<bool>(more.get()))break;
            require(++groups<=static_cast<size_t>(count),"group intent typed enumeration grew");
            Root led(invoke(current,receiver()));hits+=occurrences(led.get());
        }
        require(groups==static_cast<size_t>(count),"group intent typed enumeration changed");close();
    } catch(...) {try{close();}catch(...){ba::log("Group intent readonly enumeration cleanup failed; retry=0");}throw;}
    require(hits==(present?1u:0u),"group intent all/typed membership is inconsistent");return present;
}
static void requireOwned(const State& s);
static void groupOwner(const State& s) {
    requireOwned(s);
    require(ba::initialThread && GetCurrentThreadId()==ba::initialThread &&
        GetCurrentThreadId()==ba_local::updateThread && s.manager && s.simulation &&
        ba_prediction_movement::ownsPresentation(s.simulation->get()) &&
        s.groupIntent.generation()==s.groupGeneration,"group intent presentation owner differs");
}
struct IntentGroup {
    Root group,helper,selected;
    uint32_t id;
    static Obj reference(Obj value,const char* name,size_t offset) {
        classIs(value,"Uncapped","ControlGroup");field(value,name,offset);return ba::read<Obj>(value,offset);
    }
    IntentGroup(const State& s,Obj value,uint32_t index)
        :group(value),helper(reference(value,"_controlGroupChangeHelper",0x40)),selected(reference(value,"_unitIDs",0x20)),id(index) {
        classIs(group.get(),"Uncapped","ControlGroup");
        field(group.get(),"<ID>k__BackingField",0x38);field(group.get(),"_controlGroupChangeHelper",0x40);
        field(group.get(),"_unitIDs",0x20);field(group.get(),"_unitManager",0x60);field(group.get(),"_simulation",0x48);
        require(ba::read<uint32_t>(group.get(),0x38)==id &&
            ba::read<Obj>(group.get(),0x60)==s.manager->get() && ba::read<Obj>(group.get(),0x48)==s.simulation->get(),
            "group intent original group owner differs");
        require(helper.get() && selected.get(),"group intent original helper/set missing");
        field(helper.get(),"_controlGroup",0x18);field(helper.get(),"<IsSuspended>k__BackingField",0x10);
        require(ba::read<Obj>(helper.get(),0x18)==group.get(),"group intent helper owner differs");
        classIs(selected.get(),"Uncapped.Collections","UnitSelectionSet");field(selected.get(),"_simFrames",0x48);
        require(ba::read<Obj>(selected.get(),0x48)==ba::read<Obj>(s.simulation->get(),0x148),
            "group intent typed set frame owner differs");
    }
    void validate(const State& s) const {
        groupOwner(s);
        require(ba::read<uint32_t>(group.get(),0x38)==id &&
            ba::read<Obj>(group.get(),0x40)==helper.get() && ba::read<Obj>(group.get(),0x20)==selected.get() &&
            ba::read<Obj>(group.get(),0x60)==s.manager->get() && ba::read<Obj>(group.get(),0x48)==s.simulation->get() &&
            ba::read<Obj>(helper.get(),0x18)==group.get() &&
            ba::read<Obj>(selected.get(),0x48)==ba::read<Obj>(s.simulation->get(),0x148),
            "group intent original roots changed during callback");
    }
};
static Obj intentGroups(const State& s) {
    groupOwner(s);
    Root selector(ba::get<Obj>(ba::owner,"<UnitSelector>k__BackingField"));classIs(selector.get(),"Uncapped","UnitSelector");
    field(selector.get(),"_unitManager",0x40);field(selector.get(),"_controlGroupPanel",0x38);
    require(ba::read<Obj>(selector.get(),0x40)==s.manager->get(),"group intent selector owner differs");
    Root panel(ba::read<Obj>(selector.get(),0x38));classIs(panel.get(),"Uncapped","ControlGroupPanel");
    field(panel.get(),"_controlGroups",0x38);Obj array=ba::read<Obj>(panel.get(),0x38);
    require(array && ba::read<uintptr_t>(array,0x18)>0 && ba::read<uintptr_t>(array,0x18)<=16,
        "group intent original group array bound");return array;
}
static void instanceSignature(Obj info,const char* result,const char* parameter=nullptr) {
    uint32_t implementation=0;
    require(!(ba::api<uint32_t(*)(Obj,uint32_t*)>("il2cpp_method_get_flags")(info,&implementation)&0x10u) &&
        ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(info))==type("System",result),
        "group intent original instance/return signature differs");
    if(parameter)require(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
        ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(info,0))==type("System",parameter),
        "group intent original parameter signature differs");
}
static bool preserveReleasedGroupMember(State& s,Obj selected,uint32_t id) {
    groupOwner(s);Root array(intentGroups(s));const auto count=ba::read<uintptr_t>(array.get(),0x18);
    Obj found=nullptr;uint32_t groupId=0;
    for(uintptr_t i=0;i<count;++i) {
        Obj candidate=ba::read<Obj>(array.get(),0x20+i*sizeof(Obj));classIs(candidate,"Uncapped","ControlGroup");
        field(candidate,"_unitIDs",0x20);
        if(ba::read<Obj>(candidate,0x20)==selected) {
            require(!found,"group intent set is shared between original groups");found=candidate;groupId=static_cast<uint32_t>(i);
        }
    }
    if(!found)return false;
    IntentGroup group(s,found,groupId);
    const Resident* observed=nullptr;
    for(const auto& entry:s.identities)if(entry.second.identity.entityId==id) {
        require(!observed,"group intent released resident ID is ambiguous");observed=&entry.second;
    }
    if(!observed || !observed->incarnation || observed->identity.unitType==3 ||
        confirmedToken(s,observed->identity)!=observed->incarnation)return false;
    field(s.simulation->get(),"_localPlayer",0x90);Root player(ba::read<Obj>(s.simulation->get(),0x90));
    classIs(player.get(),"Uncapped","SimPlayer");field(player.get(),"ArmyID",0x38);
    if(observed->identity.armyId!=ba::read<uint32_t>(player.get(),0x38))return false;
    Current current(ba::read<Obj>(s.simulation->get(),0x148));
    const int frame=ba::read<int>(current.frame.get(),0x40);
    if(!confirmedInterval(s,frame) || frame<=s.admission.frame || current.identity(id))return false;
    // Original UnitsReleased visits every group and calls Remove even if this
    // particular group never contained the released ID. Preserve that no-op.
    if(!groupCacheMembership(group.selected.get(),id))return false;
    const Obj remove=method(group.selected.get(),"Remove",1,0x060025ab,0x3c66610);
    instanceSignature(remove,"Boolean","UInt32");group.validate(s);
    s.groupIntent.remember(s.groupGeneration,{groupId,id},
        {observed->identity.unitType,observed->identity.armyId,observed->incarnation});
    ba::log("Prediction group intent retained: world=%llu match=%s group=%u entity=%u token=%llu originalMemberUnchanged=1 readd=0",
        static_cast<unsigned long long>(s.world),s.match.c_str(),groupId,id,static_cast<unsigned long long>(observed->incarnation));
    return true;
}
static void reconcileGroupIntent(State& s) {
    if(s.groupIntent.entries().empty())return;
    namespace intent=ba_prediction_group_intent;
    Root array(intentGroups(s));const auto count=ba::read<uintptr_t>(array.get(),0x18);
    Current current(ba::read<Obj>(s.simulation->get(),0x148));
    const auto pending=s.groupIntent.entries();
    for(const auto& entry:pending) {
        groupOwner(s);require(entry.first.group<count,"pending group intent ID escaped original array");
        IntentGroup group(s,ba::read<Obj>(array.get(),0x20+entry.first.group*sizeof(Obj)),entry.first.group);
        const bool present=groupCacheMembership(group.selected.get(),entry.first.entity);
        std::optional<intent::Identity> canonical;const auto known=s.admission.entities.find(entry.first.entity);
        if(known!=s.admission.entities.end())canonical=intent::Identity{known->second.type,known->second.army,known->second.incarnation};
        bool admitted=false;
        for(Obj actor:units(ba::read<Obj>(s.manager->get(),0x10))) {
            const auto observed=s.identities.find(actor);
            if(observed==s.identities.end() || observed->second.identity.entityId!=entry.first.entity)continue;
            const auto& identity=observed->second;
            field(actor,"_componentData",0x158);field(actor,"<DeadToTheSim>k__BackingField",0x160);
            const auto native=current.identity(entry.first.entity);
            admitted=identity.incarnation==entry.second.token && identity.identity.unitType==entry.second.type &&
                identity.identity.armyId==entry.second.army && confirmedToken(s,identity.identity)==identity.incarnation &&
                native && native->unitType==entry.second.type && native->armyId==entry.second.army &&
                ba::read<Obj>(actor,0x158) && !ba::read<bool>(actor,0x160) &&
                confirmedInterval(s,ba::read<int>(current.frame.get(),0x40)) && current.retainedAlive(entry.first.entity);
        }
        const auto decision=s.groupIntent.classify(s.groupGeneration,entry.first,present,canonical,admitted);
        if(decision==intent::Decision::Keep)continue;
        if(decision==intent::Decision::Purge) {
            require(!ba::read<bool>(group.helper.get(),0x10),"group intent purge found an active original scope");
            const Obj begin=method(group.group.get(),"BeginControlGroupChange",1,0x06001645,0x3ea5790);
            const Obj remove=method(group.selected.get(),"Remove",1,0x060025ab,0x3c66610);
            const Obj mark=method(group.helper.get(),"MarkForFire",0,0x060000ce,0x3b02170);
            const Obj dispose=method(group.helper.get(),"Dispose",0,0x060000cd,0x3b02160);
            instanceSignature(begin,"IDisposable","Boolean");instanceSignature(remove,"Boolean","UInt32");
            instanceSignature(mark,"Void");instanceSignature(dispose,"Void");group.validate(s);
            bool begun=false,disposed=false;
            auto close=[&](){if(begun && !disposed){disposed=true;invoke(dispose,group.helper.get());}};
            try {
                bool playerInitiated=false;void* beginArgs[]={&playerInitiated};Obj scope=nullptr;
                try{scope=invoke(begin,group.group.get(),beginArgs);}
                catch(...){begun=ba::read<bool>(group.helper.get(),0x10);throw;}
                begun=true;require(scope==group.helper.get() && ba::read<bool>(group.helper.get(),0x10),
                    "group intent purge original scope owner differs");group.validate(s);
                uint32_t id=entry.first.entity;void* args[]={&id};Root removed(invoke(remove,group.selected.get(),args));
                require(unbox<bool>(removed.get()),"group intent purge original member removal failed");group.validate(s);
                require(!groupCacheMembership(group.selected.get(),id),"group intent purge left original cached membership");
                invoke(mark,group.helper.get());group.validate(s);close();group.validate(s);
            } catch(...) {try{close();}catch(...){ba::log("Group intent original scope cleanup failed; retry=0");}throw;}
            ba::log("Prediction group intent purged: world=%llu match=%s group=%u entity=%u originalAPI=1 readd=0",
                static_cast<unsigned long long>(s.world),s.match.c_str(),entry.first.group,entry.first.entity);
        }
        s.groupIntent.erase(s.groupGeneration,entry.first);
    }
}
static void clickScalarSize(Obj value,int32_t expected) {
    uint32_t alignment=0;
    require(value && ba::api<int32_t(*)(Obj,uint32_t*)>("il2cpp_class_value_size")(value,&alignment)==expected,
            "click history original scalar size differs");
}
static Obj clickField(Obj selector,const char* name,size_t offset,Obj expected,int32_t size) {
    Obj member=ba::field(selector,name);
    require(member && ba::api<Obj(*)(Obj)>("il2cpp_field_get_parent")(member)==ba::klass(selector) &&
        ba::api<size_t(*)(Obj)>("il2cpp_field_get_offset")(member)==offset &&
        !(ba::api<uint32_t(*)(Obj)>("il2cpp_field_get_flags")(member)&0x10u) &&
        ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(member))==expected,
        "click history original closed field differs");
    clickScalarSize(expected,size);return member;
}
static Obj clickMode(Obj selector) {
    Obj member=ba::field(selector,"_deferredClickMode");
    Obj mode=ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
        ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(member));
    const char* name=mode?ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(mode):nullptr;
    require(mode && ba::api<bool(*)(Obj)>("il2cpp_class_is_enum")(mode) &&
        ba::api<Obj(*)(Obj)>("il2cpp_class_get_declaring_type")(mode)==ba::klass(selector) &&
        name && !strcmp(name,"DeferredClickMode") &&
        ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj)>("il2cpp_class_enum_basetype")(mode))==type("System","Int32"),
        "click history original nested mode enum differs");
    clickScalarSize(type("System","Int32"),4);
    clickField(selector,"_deferredClickMode",0x170,mode,4);
    const char* names[]={"None","SingleClickOnMouseUp","DoubleClickOnMouseUp"};
    for(int32_t value=0;value<3;++value) {
        Obj literal=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(mode,names[value]);
        require(literal && ba::api<Obj(*)(Obj)>("il2cpp_field_get_parent")(literal)==mode &&
            (ba::api<uint32_t(*)(Obj)>("il2cpp_field_get_flags")(literal)&0x50u)==0x50u &&
            ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
                ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(literal))==mode,
            "click history original mode literal differs");
        int32_t actual=-1;ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(literal,&actual);
        require(actual==value,"click history original mode values differ");
    }
    return mode;
}
static float clickNow() {
    // Time is a CLASS here, not an object receiver for actors::method(). The
    // original static getter returns Single. runtime_invoke preserves its real
    // MethodInfo and exposes a managed exception without guessing exception data.
    Obj time=type("UnityEngine","Time"),single=type("System","Single"),found=nullptr;
    void* iterator=nullptr;
    while(Obj info=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(time,&iterator)) {
        const char* name=ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(info);
        if(!name || strcmp(name,"get_realtimeSinceStartup") ||
           ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_token")(info)!=0x06001040 ||
           ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(info)!=0)continue;
        uint32_t implementation=0;
        require(!found && (ba::api<uint32_t(*)(Obj,uint32_t*)>("il2cpp_method_get_flags")(info,&implementation)&0x10u) &&
            ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
                ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(info))==single &&
            ba::read<Obj>(info,0)==ba::native<Obj>(0x8656b0),
            "click history original static clock method differs");
        found=info;
    }
    require(found!=nullptr,"click history original static clock unavailable");clickScalarSize(single,4);
    guard(0x8656b0,"\x48\x83\xec\x28\x48\x8b\x05\x0d\xf8\x5f\x06\x48\x85\xc0\x75\x18",16);
    Root result(invoke(found,nullptr));
    require(result.get() && ba::klass(result.get())==single,"click history clock boxed result differs");
    float* value=ba::api<float*(*)(Obj)>("il2cpp_object_unbox")(result.get());
    require(value!=nullptr,"click history clock unbox missing");return *value;
}
static bool affectedLiveClick(Obj selector,const std::set<uint32_t>& affected) {
    namespace click=ba_prediction_click_policy;
    // Preserve the old unmatched fast path: no new field reflection or time call.
    const bool matches=affected.count(ba::read<uint32_t>(selector,0x128))!=0;
    const auto decision=click::classify(matches,[&](){
        classIs(selector,"Uncapped","UnitSelector");
        Obj single=type("System","Single"),boolean=type("System","Boolean");
        clickField(selector,"_doubleClickFirstClickReferenceUnitEntityId",0x128,type("System","UInt32"),4);
        clickField(selector,"_doubleClickTime",0x28,single,4);
        clickField(selector,"_lastPointerUpTime",0x154,single,4);
        clickField(selector,"_isPointerDown",0x16c,boolean,1);
        clickField(selector,"_isContextPointerDown",0x16d,boolean,1);
        clickField(selector,"_isDragging",0x119,boolean,1);clickMode(selector);
        click::State value;value.mode=ba::read<int32_t>(selector,0x170);
        value.primaryDown=ba::read<uint8_t>(selector,0x16c);value.contextDown=ba::read<uint8_t>(selector,0x16d);
        value.dragging=ba::read<uint8_t>(selector,0x119);
        require(value.primaryDown<=1 && value.contextDown<=1 && value.dragging<=1,
            "click history original Boolean value differs");
        value.lastUp=ba::read<float>(selector,0x154);value.window=ba::read<float>(selector,0x28);return value;
    },[](){return clickNow();});
    return decision==click::Classification::LiveOrUnknown;
}
static void guardRetiringInteractions(Obj selector,const std::vector<Retire>& retire,bool clearingCasting=false) {
    std::set<uint32_t> retired;for(const auto& actor:retire)retired.insert(actor.resident.entityId);
    for(const auto& actor:retire) {
        Obj casting=ba::read<Obj>(selector,0x98);
        uint32_t id=actor.resident.entityId;void* args[]={&id};
        if(!clearingCasting) {
            Root has(invoke(method(casting,"Contains",1,0x060025b7),casting,args));
            require(!unbox<bool>(has.get()),"retiring actor remains in an active casting set");
        }
    }
    require(!affectedLiveClick(selector,retired),"retiring identity remains in live or unresolved click intent");
    if(!ba::read<bool>(selector,0x16c) && !ba::read<bool>(selector,0x16d))return;
    field(selector,"_activeAbilityCaster",0x100);
    require(!ba::read<Obj>(selector,0x100),"held gesture with an active ability caster is not qualified");
    for(const auto& entry:std::initializer_list<std::pair<const char*,size_t>>{
            {"_previewSelectionSet",0x88},{"_selectionSet",0x90},{"_castingSet",0x98}}) {
        field(selector,entry.first,entry.second);
        if(clearingCasting && entry.second==0x98)continue;
        require(!selectionReferences(ba::read<Obj>(selector,entry.second),retired),
                "retiring identity remains in held gesture selection or cached type subset");
    }
    // This preflight never changes button/selection/caster/queue state. A
    // separate positively prepared queue-empty plan may clear casting scratch.
}
struct CastingCleanupAccess {
    State& state;
    Root selector,casting,server,commands;
    std::set<uint32_t> retired;
    uint64_t world=0;
    std::string match;
    Obj clearMethod=nullptr;
    static Obj castingReference(Obj owner) {
        field(owner,"_castingSet",0x98);field(owner,"_activeAbilityCaster",0x100);
        return ba::read<Obj>(owner,0x98);
    }
    static Obj commandReference(Obj owner) {
        field(owner,"_queuedInputCommands",0x180);return ba::read<Obj>(owner,0x180);
    }
    CastingCleanupAccess(State& owner,Obj value,const std::vector<Retire>& retire)
        :state(owner),selector(value),casting(castingReference(value)),server(ba_local::server()),
         commands(commandReference(server.get())),world(owner.world),match(owner.match) {
        for(const auto& actor:retire)retired.insert(actor.resident.entityId);
    }
    void validate() {
        require(GetCurrentThreadId()==ba::initialThread && GetCurrentThreadId()==ba_local::updateThread &&
                state.thread==GetCurrentThreadId() && state.inUpdate && !state.failed &&
                world && world==state.world && match.size()==32 && match==state.match &&
                world==ba_prediction_worker::movementWorldId() && match==ba_prediction_worker::movementMatchId(),
                "casting cleanup lost its Unity owner/world/match");
        require(server.get() && server.get()==ba_local::server() && ba_local::isTarget(server.get()) &&
                state.simulation && state.manager && selector.get() && casting.get() && commands.get() &&
                ba::read<Obj>(server.get(),0x140)==state.simulation->get() &&
                ba::read<Obj>(selector.get(),0x40)==state.manager->get() &&
                ba_prediction_movement::ownsPresentation(state.simulation->get()),
                "casting cleanup lost its presentation generation/roots");
        require(castingReference(selector.get())==casting.get() && commandReference(server.get())==commands.get(),
                "casting cleanup storage owner changed");
        classIs(casting.get(),"Uncapped.Collections","UnitSelectionSet");
        namespace cleanup=ba_prediction_casting_cleanup;
        clearMethod=method(casting.get(),"Clear",0,cleanup::clearToken,cleanup::clearRva);
        require(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
                    ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(clearMethod))==type("System","Void"),
                "casting cleanup original Clear signature differs");
        guard(cleanup::clearRva,reinterpret_cast<const char*>(cleanup::clearEntry.data()),cleanup::clearEntry.size());
    }
    bool hasActiveCaster(){return ba::read<Obj>(selector.get(),0x100)!=nullptr;}
    bool hasAffectedLiveClick(){return affectedLiveClick(selector.get(),retired);}
    struct Lock {ba_local::QueueLock lock;explicit Lock(CastingCleanupAccess&) {}};
    size_t commandCount() {
        const int count=ba_local::count(commands.get());
        require(count>=0 && static_cast<size_t>(count)<=maximumActors,"casting cleanup pending command count bound");
        return static_cast<size_t>(count);
    }
    void clearCasting(){invoke(clearMethod,casting.get());}
};
using CastingCleanup=ba_prediction_casting_cleanup::Plan<CastingCleanupAccess>;
// Prepare without changing original focus. All other interaction, method and
// group-scope checks must finish before cancel() enters the original API.
struct FocusCancellation {
    Root selector,focused;
    int32_t group=-1;
    Obj cancelMethod=nullptr;
    bool attempted=false;
    static Obj focusReference(Obj owner) {
        field(owner,"_repeatFocusUnit",0xa8);field(owner,"_focusChaseControlGroup",0xa0);
        return ba::read<Obj>(owner,0xa8);
    }
    FocusCancellation(Obj owner,const std::vector<Retire>& retire)
        :selector(owner),focused(focusReference(owner)) {
        require(selector.get()==owner,"actor focus selector root missing");
        require(focused.get()==ba::read<Obj>(selector.get(),0xa8),"actor focus root missing");
        group=ba::read<int32_t>(selector.get(),0xa0);
        const bool affected=focused.get() && std::any_of(retire.begin(),retire.end(),
            [&](const Retire& actor){return actor.actor==focused.get();});
        if(!affected)return;
        cancelMethod=method(selector.get(),"FocusControlGroupCancel",1,0x06002220,0x3bf2fa0);
        require(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
                    ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(cancelMethod,0))==type("System","Int32") &&
                ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
                    ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(cancelMethod))==type("System","Void"),
                "actor focus cancellation signature differs");
        guard(0x3bf2fa0,"\x3b\x91\xa0\x00\x00\x00\x75\x59\x83\x3d\x99\x34\x25\x03\x00\x48\x8d\x91\xa8\x00\x00\x00\x48\xc7\x02\x00\x00\x00\x00\xc7\x81\xa0\x00\x00\x00\xff\xff\xff\xff",39);
    }
    void cancel() {
        require(!attempted,"actor focus cancellation attempted twice");
        // Original suspension callbacks must not redirect this prepared plan
        // onto unrelated focus or introduce a new retiring reference.
        require(ba::read<Obj>(selector.get(),0xa8)==focused.get() &&
                ba::read<int32_t>(selector.get(),0xa0)==group,
                "actor focus changed after retirement preflight");
        attempted=true;
        if(!cancelMethod)return;
        void* args[]={&group};invoke(cancelMethod,selector.get(),args);
        require(!ba::read<Obj>(selector.get(),0xa8) && ba::read<int32_t>(selector.get(),0xa0)==-1,
                "original focus cancellation did not release retiring actor");
        ba::log("Prediction actor focus cancelled: group=%d affectedActorOnly=1 originalAPI=1",group);
    }
};
static void beginRetirement(GroupChanges& changes,FocusCancellation& focus) {
    // A throwing original Begin still owns its ordinary Dispose, but neither
    // focus nor actor ownership is changed until every scope has begun.
    changes.begin();focus.cancel();changes.mutated=true;
}
static void beginRetiringInteractions(State& s,Obj selector,const std::vector<Retire>& retire,
        const std::vector<Obj>& groups,GroupChanges& changes) {
    std::set<uint32_t> retiredIds;for(const auto& actor:retire)retiredIds.insert(actor.resident.entityId);
    field(selector,"_castingSet",0x98);
    const bool affectedCasting=selectionReferences(ba::read<Obj>(selector,0x98),retiredIds);
    std::unique_ptr<CastingCleanupAccess> castingAccess;
    std::unique_ptr<CastingCleanup> casting;
    if(affectedCasting) {
        castingAccess=std::make_unique<CastingCleanupAccess>(s,selector,retire);
        casting=std::make_unique<CastingCleanup>(*castingAccess,true);casting->prepare();
    }
    FocusCancellation focus(selector,retire);
    guardRetiringInteractions(selector,retire,casting && casting->willClear());
    changes.prepare(groups,retire);
    // This is the first mutation. Its SAME producer SRW checks queue180 again;
    // a new ICommand refuses before scratch/focus/selection/pool can change.
    if(casting && casting->commit())ba::log("Prediction actor casting scratch cleared: pendingCommands=0 originalAPI=1 serializedActionsUntouched=1");
    beginRetirement(changes,focus);
}
static void requireOwned(const State& s) {
    require(!s.failed && s.inUpdate && s.thread==GetCurrentThreadId() && s.world &&
        ba_prediction_worker::movementWorldId()==s.world && ba_prediction_worker::movementMatchId()==s.match,
        "actor callback stopped or changed its owned prediction generation");
}
struct DeferredSelection {
    std::unique_ptr<Root> selector,batch,manager,simulation,frames;
    std::vector<uint32_t> frozenIds;
    policy::ActorIdentity expected;
    Obj remove=nullptr;
    int preparedFrame=-1;
    bool attempted=false;
    bool prepare(State& s,Obj owner,Obj values,Obj original,Obj currentFrames,const std::vector<Retire>& retire) {
        if(std::none_of(retire.begin(),retire.end(),[](const Retire& actor){return actor.alreadyReleased;}))return false;
        // Normal HQ death has already released this actor from the simulation.
        // Its old ID is absent from the live manager until original recreation.
        // SelectionChanged listeners may dereference that ID, so retain the
        // entire ORIGINAL RemoveSelection operation until the manager is whole.
        // Keep mixed retirements/active abilities refused until separately proven.
        require(retire.size()==1 && retire.front().alreadyReleased,
            "mixed retained HQ selection retirement is not qualified");
        const auto& actor=retire.front();
        require(actor.resident.unitType==3 && actor.current.unitType==3 &&
            actor.resident.entityId==actor.current.entityId && actor.resident.armyId==actor.current.armyId,
            "retained HQ selection identity change is not qualified");
        expected=actor.current;
        field(owner,"_activeAbilityCaster",0x100);
        require(!ba::read<Obj>(owner,0x100),"retained HQ selection with active ability is not qualified");
        classIs(values,"Uncapped.Collections","UnitSet");field(values,"_entityIds",0x18);
        frozenIds=ids(ba::read<Obj>(values,0x18));
        require(frozenIds==std::vector<uint32_t>{retire.front().resident.entityId},
            "retained HQ original selection batch IDs differ");
        manager=std::make_unique<Root>(s.manager->get());simulation=std::make_unique<Root>(s.simulation->get());
        frames=std::make_unique<Root>(currentFrames);Current current(frames->get());
        preparedFrame=ba::read<int>(current.frame.get(),0x40);
        selector=std::make_unique<Root>(owner);batch=std::make_unique<Root>(values);remove=original;
        return true;
    }
    void commit(State& s) {
        if(!batch)return;
        require(!attempted,"retained HQ selection removal attempted twice");requireOwned(s);
        Current current(frames->get());
        require(selector->get()==ba::get<Obj>(ba::owner,"<UnitSelector>k__BackingField") &&
            s.manager->get()==manager->get() && s.simulation->get()==simulation->get() &&
            ba::read<Obj>(selector->get(),0x40)==manager->get() &&
            ba::read<int>(current.frame.get(),0x40)==preparedFrame &&
            ba_prediction_movement::ownsPresentation(simulation->get()) &&
            !ba::read<Obj>(selector->get(),0x100),"retained HQ selection owner/ability changed");
        // A pooled Unit object can be reused. Only the independent immutable ID
        // snapshot chooses removals; never derive them from its mutable actors.
        require(ids(ba::read<Obj>(batch->get(),0x18))==frozenIds,
            "retained HQ selection batch changed during original recreation");
        bool recreated=false;
        for(Obj actor:units(ba::read<Obj>(s.manager->get(),0x10))) {
            const auto identity=resident(actor);if(identity.entityId!=frozenIds.front())continue;
            const auto observed=s.identities.find(actor);
            require(identity.unitType==expected.unitType && identity.armyId==expected.armyId &&
                observed!=s.identities.end() && observed->second.incarnation &&
                confirmedToken(s,identity)==observed->second.incarnation,
                "retained HQ selection notification precedes confirmed recreation");recreated=true;
        }
        require(recreated,"retained HQ selection notification lacks its recreated actor");
        attempted=true;void* args[]={batch->get()};invoke(remove,selector->get(),args);requireOwned(s);
        ba::log("Prediction retained HQ selection applied: world=%llu match=%s entity=%u originalRemoval=1 frozenIds=1 postRecreation=1",
            static_cast<unsigned long long>(s.world),s.match.c_str(),frozenIds.front());
    }
};
static void repair(State& s,Obj manager,Obj frames,GroupChanges& changes,DeferredSelection& selection) {
    Current current(frames);
    Root active(ba::read<Obj>(manager,0x10)),retained(ba::read<Obj>(manager,0xa0)),pending(ba::read<Obj>(manager,0x18));
    const auto activeActors=units(active.get()),retainedActors=units(retained.get());
    std::set<Obj> firstObserved;
    for(Obj actor:activeActors)if(!s.identities.count(actor))firstObserved.insert(actor);
    std::set<Obj> live;remember(s,activeActors,live);remember(s,retainedActors,live);
    std::vector<Retire> retire;
    for(Obj actor:activeActors) {
        auto& observed=s.identities.at(actor);const auto old=observed.identity;
        const auto token=confirmedToken(s,old);
        // Only an actually confirmed displayed frame may seed a previously
        // unseen resident. Numeric coincidence at a predicted head does not
        // promote an old speculative actor into an authoritative incarnation.
        if(!observed.incarnation && token && firstObserved.count(actor) &&
           ba::read<int>(current.frame.get(),0x40)==s.admission.frame)
            observed.incarnation=token;
        if(auto next=current.identity(old.entityId)) {
            const auto nextToken=confirmedToken(s,*next);
            if(policy::actorDecision(old,next)==policy::ActorDecision::Reload ||
               (nextToken && observed.incarnation!=nextToken)) {
                retire.push_back({actor,old,*next});
                if(nextToken)s.confirmedRecreation.insert(old.entityId);
            }
        }
    }
    // Original UnitsReleased completed BEFORE ReleaseFromSim inserted this
    // dead HQ into presentationOnly and returned its component data. Retire
    // that old retained lifetime without broadcasting UnitsReleased again.
    for(Obj actor:retainedActors) {
        const auto old=s.identities.at(actor).identity;
        if(auto next=current.identity(old.entityId)) {
            if(!current.retainedAlive(old.entityId))continue;
            field(actor,"<DeadToTheSim>k__BackingField",0x160);field(actor,"_componentData",0x158);
            Obj config=ba::read<Obj>(actor,0x168);field(config,"IsHQ",0x2c);
            require(ba::read<bool>(config,0x2c) && ba::read<bool>(actor,0x160) && !ba::read<Obj>(actor,0x158),
                    "retained actor lacks original released HQ ownership state");
            for(Obj activeActor:activeActors)require(resident(activeActor).entityId!=old.entityId,
                    "retained HQ cleanup would remove an already-created same-ID actor");
            retire.push_back({actor,old,*next,true});
            if(confirmedToken(s,*next))s.confirmedRecreation.insert(old.entityId);
        }
    }
    std::vector<uint32_t> invalidPending;
    for(uint32_t id:ids(pending.get())) {
        auto previous=s.pending.find(id);auto next=current.identity(id);
        if(previous!=s.pending.end() && next &&
           policy::actorDecision(previous->second,next)==policy::ActorDecision::Reload)invalidPending.push_back(id);
    }
    if(retire.empty()) {
        for(uint32_t id:invalidPending)removeId(pending.get(),id);
        return;
    }
    Root selector(ba::get<Obj>(ba::owner,"<UnitSelector>k__BackingField"));classIs(selector.get(),"Uncapped","UnitSelector");
    field(selector.get(),"_unitManager",0x40);
    require(ba::read<Obj>(selector.get(),0x40)==manager,"actor repair selector owner differs");
    const auto groups=affectedGroups(selector.get(),s.simulation->get(),retire);
    Root batch(ba::make("Uncapped.Collections","UnitSet"));
    Root released(ba::make("Uncapped.Collections","UnitSet"));
    Obj add=method(batch.get(),"Add",1,0x0600261b,0x3c6c280);
    for(const auto& actor:retire){void* args[]={actor.actor};invoke(add,batch.get(),args);
        if(!actor.alreadyReleased)invoke(add,released.get(),args);}
    // Resolve every non-generic method and required owner before the first
    // selection/pool mutation. An exception after this point fails the owner;
    // no partial repair is retried and no replacement is manually installed.
    Obj removeSelection=method(selector.get(),"RemoveSelection",1,0x0600220a,0x3bf0cf0);
    const bool deferredSelection=selection.prepare(s,selector.get(),batch.get(),removeSelection,frames,retire);
    Root factory(ba::read<Obj>(manager,0x50));require(factory.get(),"actor repair factory missing");
    Root pools(ba::read<Obj>(factory.get(),0x10));require(pools.get(),"actor repair pool manager missing");
    Obj poolRelease=method(pools.get(),"Release",1,0x060021b1,0x3be9770);
    // The original dispatcher deliberately returns if the old-type pool is
    // missing. Do not mistake that return for a completed ownership release.
    Root poolMap(ba::read<Obj>(pools.get(),0x18));require(poolMap.get(),"actor repair old pool map missing");
    for(const auto& actor:retire) {
        uint32_t key=actor.resident.unitType;void* args[]={&key};
        Root has(ba::call(poolMap.get(),"ContainsKey",1,args));
        require(unbox<bool>(has.get()),"actor repair old instantiated pool is unavailable");
    }
    method(active.get(),"Remove",1,0x06002622,0x3c6c660);
    method(retained.get(),"Remove",1,0x06002622,0x3c6c660);
    method(pending.get(),"Remove",1,0x060000ad,0x3782570);
    method(ba::read<Obj>(manager,0x30),"Remove",1,0x060000ad,0x3782570);
    method(ba::read<Obj>(manager,0x28),"Remove",1,0x060000ad,0x3782570);
    for(const auto& actor:retire)method(actor.actor,"ReleaseFromSim",0,0x060022a1,0x3bfc570);
    ReleaseEvent releaseEvent(manager);
    // Original RemoveSelection handles ordinary preview/current selection and
    // ability compatibility. Resolve supported affected-focus cancellation
    // separately; casting/click/ability refusals must happen before it runs.
    beginRetiringInteractions(s,selector.get(),retire,groups,changes);
    requireOwned(s);
    for(const auto& actor:retire)
        ba::log("Prediction actor retirement begin: world=%llu match=%s frame=%d entity=%u actor=%p oldType=%u oldArmy=%u correctedType=%u correctedArmy=%u affectedGroups=%zu",
            static_cast<unsigned long long>(s.world),s.match.c_str(),ba::read<int>(current.frame.get(),0x40),
            actor.resident.entityId,actor.actor,actor.resident.unitType,actor.resident.armyId,
            actor.current.unitType,actor.current.armyId,groups.size());
    // Original released observers complete interpolation jobs and remove
    // TransformAccessArray/turret registrations before the pool owns actors.
    if(!deferredSelection) {
        void* selectionArgs[]={batch.get()};invoke(removeSelection,selector.get(),selectionArgs);requireOwned(s);
    }
    if(std::any_of(retire.begin(),retire.end(),[](const Retire& value){return !value.alreadyReleased;}))
        releaseEvent.fire(manager,released.get(),current.frame.get());
    requireOwned(s);
    for(const auto& actor:retire) {
        // Invoke the original UnitPoolManager dispatcher even for an active HQ.
        // Its old instantiated type selects the old pool and normal release
        // lifecycle. Never toggle shared IsHQ, destroy Unity objects or fake
        // state6/UnitsDying. Keep batch roots until ALL old-ID removals finish.
        void* args[]={actor.actor};invoke(poolRelease,pools.get(),args);requireOwned(s);
        require(ba::read<uint32_t>(actor.actor,0x14c)==actor.resident.entityId,
                "old pool lifecycle changed the entity ID before exact membership removal");
        if(!actor.alreadyReleased) {
            removeId(ba::read<Obj>(manager,0x30),actor.resident.entityId);
            removeId(ba::read<Obj>(manager,0x28),actor.resident.entityId);
            invoke(method(actor.actor,"ReleaseFromSim",0,0x060022a1,0x3bfc570),actor.actor);
        }
        removeUnit(actor.alreadyReleased?retained.get():active.get(),actor.actor);
        removeId(pending.get(),actor.resident.entityId);
        s.identities.erase(actor.actor);
        ba::log("Prediction actor retired: world=%llu match=%s entity=%u actor=%p oldType=%u oldArmy=%u correctedType=%u correctedArmy=%u selectionBatch=1 releasedMulticast=%d originalPool=1 oldMembershipRemoved=1 retainedHQ=%d",
            static_cast<unsigned long long>(s.world),s.match.c_str(),actor.resident.entityId,actor.actor,
            actor.resident.unitType,actor.resident.armyId,actor.current.unitType,actor.current.armyId,
            actor.alreadyReleased?0:1,actor.alreadyReleased?1:0);
    }
    for(uint32_t id:invalidPending)removeId(pending.get(),id);
}
static void after(State& s,Obj manager,Obj frames) {
    Current current(frames);
    // Ordinary original removal may return an actor to its pool and reuse its
    // address for another ID during this same update. Retire that cache entry
    // only when its old ID is absent; it is a new creation, not identity repair.
    const auto active=units(ba::read<Obj>(manager,0x10));
    const auto retained=units(ba::read<Obj>(manager,0xa0));
    std::set<Obj> freshLifetimes;
    for(const auto* list:{&active,&retained})for(Obj actor:*list) {
        auto found=s.identities.find(actor);
        if(found!=s.identities.end() && found->second.identity.entityId!=resident(actor).entityId) {
            require(!current.identity(found->second.identity.entityId),
                    "old actor ID remains present during ordinary pool-address reuse");
            s.identities.erase(found);
        }
        if(!s.identities.count(actor))freshLifetimes.insert(actor);
    }
    std::set<Obj> live;
    remember(s,active,live);remember(s,retained,live);
    for(Obj actor:active) {
        auto& observed=s.identities.at(actor);const auto token=confirmedToken(s,observed.identity);
        const int frame=ba::read<int>(current.frame.get(),0x40);
        if(!observed.incarnation && token && confirmedInterval(s,frame) &&
           (frame<=s.admission.frame || freshLifetimes.count(actor) ||
            s.confirmedRecreation.count(observed.identity.entityId)))observed.incarnation=token;
    }
    s.confirmedRecreation.clear();
    for(auto it=s.identities.begin();it!=s.identities.end();)
        if(!live.count(it->first))it=s.identities.erase(it);else ++it;
    rememberPending(s,ba::read<Obj>(manager,0x18),current);
}
}

extern "C" __declspec(dllexport) void OfflinePredictionActorUpdate(void* manager,void* frames,void* methodInfo) {
    ba::init();
    const auto original=ba::native<void(*)(void*,void*,void*)>(0x3c08010);
    auto& s=ba_prediction_actors::state();
    ba_prediction_actors::GroupChanges changes;
    ba_prediction_actors::DeferredSelection selection;
    bool entered=false;
    try {
        // movementEnabled means requested, including startup before BEGIN and
        // offline fallback. A transport world alone is not an active movement
        // generation; the match ID and opaque world ID must both be assigned.
        if(!ba_prediction_actors::flag() || !ba_prediction_worker::movementEnabled() ||
           !ba_prediction_worker::movementWorldId() || ba_prediction_worker::movementMatchId().empty()) {
            ba_prediction_actors::clearInactive(s);original(manager,frames,methodInfo);return;
        }
        ba_prediction_actors::require(!s.inUpdate,"actor repair reentered");s.inUpdate=true;entered=true;
        ba_prediction_actors::checkContext(s,manager,frames);
        ba_prediction_actors::reconcileGroupIntent(s);
        ba_prediction_actors::repair(s,manager,frames,changes,selection);
        original(manager,frames,methodInfo);
        ba_prediction_actors::requireOwned(s);
        changes.close();
        ba_prediction_actors::requireOwned(s);
        ba_prediction_actors::after(s,manager,frames);
        ba_prediction_actors::reconcileGroupIntent(s);
        selection.commit(s);
        s.inUpdate=false;
    } catch(const std::exception& error) {
        try{changes.close();}catch(const std::exception& cleanup){ba::log("Prediction actor group cleanup failed: reason=%s retry=0",cleanup.what());}
        if(entered)s.inUpdate=false;
        s.failed=true;
        ba::log("Prediction actor repair failed: world=%llu match=%s reason=%s retry=0",
            static_cast<unsigned long long>(s.world),s.match.c_str(),error.what());
        ba_prediction_worker::movementFail(error.what());
    }
}

// One exact call in ORIGINAL ControlGroup.UnitsReleased's physical-absence
// branch. The surrounding tracked.Remove/count/notification operations remain
// original. Clear, replace, explicit Remove and initialization use other calls.
extern "C" __declspec(dllexport) bool OfflinePredictionGroupReleaseRemove(void* selected,uint32_t entity,void* methodInfo) {
    ba::init();using namespace ba_prediction_actors;
    const auto original=ba::native<bool(*)(Obj,uint32_t,Obj)>(0x3c66610);
    auto& s=state();
    if(!flag() || !ba_prediction_worker::movementEnabled() || !s.inUpdate ||
       !ba_prediction_worker::movementWorldId() || ba_prediction_worker::movementMatchId().empty())
        return original(selected,entity,methodInfo);
    try {
        require(!methodInfo,"group intent release call MethodInfo differs");
        if(preserveReleasedGroupMember(s,selected,entity))return false;
        return original(selected,entity,methodInfo);
    } catch(const std::exception& error) {
        s.failed=true;ba::log("Prediction group intent failed: entity=%u reason=%s retry=0",entity,error.what());
        ba_prediction_worker::movementFail(error.what());
    } catch(...) {
        s.failed=true;ba::log("Prediction group intent failed: entity=%u reason=unknown exception retry=0",entity);
        ba_prediction_worker::movementFail("unknown group intent exception");
    }
    return false;
}
