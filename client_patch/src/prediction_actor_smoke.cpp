// Explicit owned correction fixture. Original selection/control-group/focus APIs
// only; no simulated callbacks, native state writes or observer-token changes.
namespace ba_prediction_actor_smoke {
namespace actors=ba_prediction_actors;
namespace selection=ba_prediction_selection;
namespace worker=ba_prediction_worker;
using ba::Obj;
using ba_local::Root;
struct State {
    uint64_t world=0;
    std::string match;
    std::unique_ptr<Root> originalCore,group;
    uint32_t entity=0;
    int firstDead=-1,firstRestored=-1;
    bool setup=false,passed=false,failed=false,escapeQueued=false,focusRetainedAtDeath=false;
};
static State& state(){static State* value=new State;return *value;}
static void require(bool ok,const char* why){actors::require(ok,why);}
static void event(const char* name,int frame,Obj current=nullptr) {
    const auto& s=state();
    ba::log("ACTOR CORRECTION {\"schema\":1,\"event\":\"%s\",\"world\":%llu,\"match\":\"%s\",\"entity\":%u,\"army\":%d,\"unit_type\":3,\"frame\":%d,\"tick_ms\":%llu,\"original_actor\":\"%p\",\"current_actor\":\"%p\",\"original_focus_supported\":false,\"original_group_supported\":false,\"focus_retained_at_death\":%s,\"physicalUI\":false}",
        name,static_cast<unsigned long long>(s.world),s.match.c_str(),s.entity,ba::lanSlot(),frame,
        static_cast<unsigned long long>(GetTickCount64()),
        s.originalCore?s.originalCore->get():nullptr,current,s.focusRetainedAtDeath?"true":"false");
}
static Obj selectorFor(actors::State& owner) {
    Obj selector=selection::currentSelector();actors::classIs(selector,"Uncapped","UnitSelector");
    actors::field(selector,"_unitManager",0x40);
    require(owner.manager&&ba::read<Obj>(selector,0x40)==owner.manager->get(),"actor fixture selector owner differs");
    return selector;
}
static Obj coreFor(actors::State& owner) {
    Obj found=nullptr;
    for(Obj actor:actors::units(ba::read<Obj>(owner.manager->get(),0x10))) {
        const auto identity=actors::resident(actor);
        if(identity.armyId!=static_cast<uint32_t>(ba::lanSlot())||identity.unitType!=3)continue;
        actors::field(actor,"_componentData",0x158);
        actors::field(actor,"<DeadToTheSim>k__BackingField",0x160);
        if(ba::read<bool>(actor,0x160)||!ba::read<Obj>(actor,0x158))continue;
        require(!found,"actor fixture requires exactly one live owned Core3");found=actor;
    }
    return found;
}
static void setup(actors::State& owner,Obj selector,int frame) {
    auto& s=state();Obj core=coreFor(owner);require(core,"actor fixture own Core missing");
    selection::Context admission(selector);require(admission.admitted(core),"actor fixture Core is not confirmed");
    const auto identity=actors::resident(core);require(identity.entityId==5,"actor fixture victim Core ID differs");
    s.entity=identity.entityId;s.originalCore=std::make_unique<Root>(core);
    actors::field(core,"_entityConfig",0x168);
    Obj config=ba::read<Obj>(core,0x168);actors::field(config,"IsHQ",0x2c);
    require(ba::read<bool>(config,0x2c),"actor fixture Core is not original HQ presentation type");
    // These exact original non-callback methods are also used by real input.
    Obj clear=actors::method(selector,"ClearSelection",0,0x06002217,0x3bf2680);
    Obj add=actors::method(selector,"AddToSelection",1,0x06002214,0x3bf2510);
    Obj assign=actors::method(selector,"AssignSelectionToControlGroup",2,0x0600220e,0x3bf14e0);
    Obj focus=actors::method(selector,"FocusControlGroup",2,0x06002221,0x3bf3010);
    Obj begin=actors::method(selector,"BeginSelectionChange",1,0x06002237,0x3bf5af0);
    actors::field(selector,"_selectionChangeHelper",0x80);
    Root helper(ba::read<Obj>(selector,0x80));require(helper.get(),"actor fixture selection helper missing");
    actors::field(helper.get(),"<IsSuspended>k__BackingField",0x10);
    require(!ba::read<bool>(helper.get(),0x10),"actor fixture selection already suspended");
    Obj dispose=actors::method(helper.get(),"Dispose",0,0x060000cd,0x3b02160);
    bool disposed=false;
    auto close=[&](){if(!disposed&&ba::read<bool>(helper.get(),0x10)) {
        disposed=true;actors::invoke(dispose,helper.get());
    }};
    try {
        bool playerInitiated=true;void* beginArgs[]={&playerInitiated};
        require(actors::invoke(begin,selector,beginArgs)==helper.get(),"actor fixture original scope owner differs");
        ba::log("Actor fixture original selection scope begun: entity=%u",s.entity);
        actors::invoke(clear,selector);void* addArgs[]={&s.entity};actors::invoke(add,selector,addArgs);
        close();require(disposed&&!ba::read<bool>(helper.get(),0x10),"actor fixture original scope did not close");
    } catch(...) {try{close();}catch(...){ba::log("Actor fixture original selection cleanup failed; retry=0");}throw;}
    require(selection::selectionIds(ba::read<Obj>(selector,0x90))==std::vector<uint32_t>{s.entity},
        "actor fixture original selection did not retain exactly its Core");
    ba::log("Actor fixture original selection committed: entity=%u",s.entity);
    int groupId=4;bool replace=true;void* assignArgs[]={&groupId,&replace};actors::invoke(assign,selector,assignArgs);
    bool repeat=true;void* focusArgs[]={&groupId,&repeat};actors::invoke(focus,selector,focusArgs);
    actors::field(selector,"_repeatFocusUnit",0xa8);actors::field(selector,"_focusChaseControlGroup",0xa0);
    // Original HasAssignableUnit deliberately excludes IsHQ. The sole Core
    // selection cannot populate a control group or begin persistent focus.
    // Exercise that ordinary refusal without bypassing it through lower APIs.
    require(!ba::read<Obj>(selector,0xa8)&&ba::read<int>(selector,0xa0)==-1,
        "actor fixture sole HQ unexpectedly entered persistent focus");
    Obj panel=ba::read<Obj>(selector,0x38);actors::classIs(panel,"Uncapped","ControlGroupPanel");
    actors::field(panel,"_controlGroups",0x38);Obj groups=ba::read<Obj>(panel,0x38);
    require(groups&&ba::read<uintptr_t>(groups,0x18)>4,"actor fixture group4 unavailable");
    s.group=std::make_unique<Root>(ba::read<Obj>(groups,0x20+4*sizeof(Obj)));
    actors::classIs(s.group->get(),"Uncapped","ControlGroup");actors::field(s.group->get(),"<ID>k__BackingField",0x38);
    require(ba::read<int>(s.group->get(),0x38)==groupId,"actor fixture group index/ID differ");
    Obj selected=ba::read<Obj>(s.group->get(),0x20);void* idArgs[]={&s.entity};
    Root contains(actors::invoke(actors::method(selected,"Contains",1,0x060025b7),selected,idArgs));
    require(!actors::unbox<bool>(contains.get()),"actor fixture original group admitted excluded HQ");
    s.setup=true;event("original_hq_selection_established",frame,core);
}
static void escape(actors::State& owner,Obj selector,int frame) {
    namespace original=ba_prediction_movement_smoke;
    auto& s=state();selection::Context admission(selector);
    auto found=admission.live.find(10);require(found!=admission.live.end(),"actor fixture initial Gunbot10 missing");
    Obj actor=found->second;const auto identity=actors::resident(actor);
    require(identity.armyId==0&&identity.unitType==1&&admission.admitted(actor),"actor fixture escape source is not confirmed Gunbot1");
    uint32_t id=identity.entityId,ability=12,unitType=identity.unitType;
    original::Vec3 target{-69.77999877929688f,0.f,-80.8499984741211f};original::finite(target);
    Root ids(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(actors::type("System","UInt32"),1));
    require(ids.get(),"actor fixture escape ID array missing");
    std::memcpy(static_cast<unsigned char*>(ids.get())+0x20,&id,sizeof(id));
    Root group(original::allocate("ExecuteCommandEntityTypeData"));
    Obj groupCtor=actors::method(group.get(),".ctor",3,0x060000f3,0x34b3080);
    void* groupArgs[]={ids.get(),&ability,&unitType};
    actors::invoke(groupCtor,group.get(),groupArgs);
    require(ba::read<Obj>(group.get(),0x10)==ids.get()&&ba::read<uint32_t>(group.get(),0x18)==ability&&
        ba::read<uint32_t>(group.get(),0x1c)==unitType,"actor fixture original escape group differs");
    Root groups(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(ba::klass(group.get()),1));
    require(groups.get(),"actor fixture escape group array missing");
    auto* slot=reinterpret_cast<Obj*>(static_cast<unsigned char*>(groups.get())+0x20);
    ba::api<void(*)(Obj,Obj*,Obj)>("il2cpp_gc_wbarrier_set_field")(groups.get(),slot,group.get());
    require(*slot==group.get(),"actor fixture escape group reference not published");
    Root command(original::allocate("ExecuteTargetGroundCommand"));
    Obj ctor=actors::method(command.get(),".ctor",4,0x060000e6,0x37ae080);
    require(original::parameterClass(ctor,1)==actors::type("UnityEngine","Vector3"),
        "actor fixture escape target ABI differs");
    int32_t perspective=original::normalPerspective(ctor);bool queued=false;
    void* args[]={groups.get(),&target,&perspective,&queued};actors::invoke(ctor,command.get(),args);
    const auto hash=original::actionHash(command.get());
    require(admission.admitted(actor),"actor fixture escape source changed before enqueue");
    Obj server=ba_local::server();actors::classIs(server,"Uncapped","GameServerIntegration");
    require(ba::read<Obj>(server,0x140)==owner.simulation->get(),"actor fixture escape server changed");
    Obj queue=ba::read<Obj>(server,0x180);const int before=ba_local::count(queue);
    Obj enqueue=actors::method(server,"EnqueueInputCommand",1,0x06001115,0x3e53530);
    void* commandArgs[]={command.get()};actors::invoke(enqueue,server,commandArgs);
    require(ba_local::count(queue)==before+1,"actor fixture original escape enqueue delta differs");s.escapeQueued=true;
    ba::log("ACTOR ORDER {\"schema\":1,\"event\":\"original_escape_move\",\"world\":%llu,\"match\":\"%s\",\"army\":0,\"entity\":10,\"unit_type\":1,\"ability\":12,\"frame\":%d,\"tick_ms\":%llu,\"action_sha256\":\"%s\",\"originalCtor\":true,\"physicalUI\":false}",
        static_cast<unsigned long long>(s.world),s.match.c_str(),frame,static_cast<unsigned long long>(GetTickCount64()),hash.c_str());
}
// Separate first-slice mobile fixture. Empty casting scratch/no active caster is
// an explicit diagnostic precondition, not a production input policy.
namespace mobile {
namespace original=ba_prediction_movement_smoke;
struct State {
    uint64_t world=0,originalToken=0,currentToken=0,lastPoseUs=0;
    std::string match;
    std::unique_ptr<Root> oldActor,currentActor,group,attackerGroup;
    uint64_t attackerToken=0;
    int firstDead=-1,firstReleased=-1,firstRestored=-1,lastSnapshot=-1,freshFrame=-1;
    ULONGLONG lastPoseTick=0;
    unsigned samples=0;
    bool setup=false,escapeQueued=false,freshQueued=false,passed=false,failed=false;
    bool groupHoldObserved=false,groupEdits=false,groupRestored=false,attackerSetup=false,attackerAbsent=false,attackerPurged=false;
    bool recoveryStalled=false,recallAbsent=false,recallRestored=false;
};
static State& state(){static State* value=new State;return *value;}
static uint64_t stamp(){uint64_t value=0;require(ba_frame_timing::timestampMicros(value),"mobile fixture QPC unavailable");return value;}
static void owned(actors::State& owner) {
    const auto& s=state();
    require(ba::initialThread&&GetCurrentThreadId()==ba::initialThread&&owner.thread==GetCurrentThreadId()&&
        !owner.failed&&s.world&&owner.world==s.world&&owner.match==s.match&&owner.manager&&owner.simulation&&
        s.world==worker::movementWorldId()&&s.match==worker::movementMatchId(),"mobile fixture lost its presentation owner");
}
static int pending(actors::State& owner) {
    Obj server=ba_local::server();actors::classIs(server,"Uncapped","GameServerIntegration");
    actors::field(server,"_queuedInputCommands",0x180);
    require(ba_local::isTarget(server)&&ba::read<Obj>(server,0x140)==owner.simulation->get(),"mobile fixture command owner changed");
    ba_local::QueueLock lock;const int count=ba_local::count(ba::read<Obj>(server,0x180));
    require(count>=0&&count<=256,"mobile fixture pending-command bound");return count;
}
static void idle(actors::State& owner,Obj selector,uint32_t entity) {
    owned(owner);
    for(const auto& entry:std::initializer_list<std::pair<const char*,size_t>>{
        {"_previewSelectionSet",0x88},{"_selectionSet",0x90},{"_castingSet",0x98},{"_activeAbilityCaster",0x100},
        {"_repeatFocusUnit",0xa8},{"_focusChaseControlGroup",0xa0},{"_doubleClickFirstClickReferenceUnitEntityId",0x128},
        {"_isPointerDown",0x16c},{"_isContextPointerDown",0x16d}})actors::field(selector,entry.first,entry.second);
    require(!ba::read<Obj>(selector,0x100),"mobile fixture active caster is outside this slice");
    require(selection::selectionIds(ba::read<Obj>(selector,0x98)).empty()&&
        !actors::selectionReferences(ba::read<Obj>(selector,0x98),std::set<uint32_t>{entity}),
        "mobile fixture requires empty casting scratch; inactive scratch is a separate slice");
    require(!ba::read<bool>(selector,0x16c)&&!ba::read<bool>(selector,0x16d)&&
        ba::read<uint32_t>(selector,0x128)!=entity,"mobile fixture physical gesture/live click is outside this slice");
    require(pending(owner)==0,"mobile fixture pending ICommand is outside this slice");
}
static Obj groupFor(Obj selector,int index=4) {
    actors::field(selector,"_controlGroupPanel",0x38);Obj panel=ba::read<Obj>(selector,0x38);
    actors::classIs(panel,"Uncapped","ControlGroupPanel");actors::field(panel,"_controlGroups",0x38);
    Obj groups=ba::read<Obj>(panel,0x38);require(groups,"mobile fixture control groups missing");
    const auto count=ba::read<uintptr_t>(groups,0x18);require(index>=0&&static_cast<uintptr_t>(index)<count&&count<=16,"mobile fixture group array bound");
    Obj group=ba::read<Obj>(groups,0x20+static_cast<size_t>(index)*sizeof(Obj));actors::classIs(group,"Uncapped","ControlGroup");
    actors::field(group,"<ID>k__BackingField",0x38);actors::field(group,"_unitIDs",0x20);
    actors::field(group,"_trackedReleasedUnits",0x10);actors::field(group,"_autoAssignments",0x30);
    require(ba::read<int>(group,0x38)==index,"mobile fixture group index/ID differs");return group;
}
static std::string idsJson(const std::vector<uint32_t>& ids) {
    std::ostringstream out;out<<'[';bool first=true;for(auto id:ids){if(!first)out<<',';first=false;out<<id;}out<<']';return out.str();
}
static uint64_t token(const selection::Context& context,Obj actor) {
    const auto found=context.state.identities.find(actor);return found==context.state.identities.end()?0:found->second.incarnation;
}
static std::optional<uint32_t> nativeState(const actors::Current& current) {
    Root states(ba::call(current.frame.get(),"get_StateBuffer"));if(!actors::contains(states.get(),11))return std::nullopt;
    Obj get=actors::method(states.get(),"get_Item",1,0x0600013d);
    Obj valueType=ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
        ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(get));uint32_t alignment=0;
    require((valueType==actors::type("System","UInt32")||ba::api<bool(*)(Obj)>("il2cpp_class_is_enum")(valueType))&&
        ba::api<int32_t(*)(Obj,uint32_t*)>("il2cpp_class_value_size")(valueType,&alignment)==4,
        "mobile fixture original native state scalar ABI differs");
    uint32_t id=11;void* args[]={&id};Root boxed(actors::invoke(get,states.get(),args));
    const auto value=actors::unbox<uint32_t>(boxed.get());require(value!=0xffffffff,"mobile fixture native state sentinel");return value;
}
struct View {
    selection::Context context;
    actors::Current native;
    Obj current=nullptr;
    std::optional<uint32_t> nativeValue;
    bool nativePresent=false,oldActive=false,oldRetained=false,oldDead=false,oldComponent=false;
    View(actors::State& owner,Obj selector):context(selector),native(ba::read<Obj>(owner.simulation->get(),0x148)) {
        owned(owner);const auto found=context.live.find(11);if(found!=context.live.end())current=found->second;
        nativePresent=native.identity(11).has_value();nativeValue=nativeState(native);
        if(auto old=state().oldActor?state().oldActor->get():nullptr) {
            actors::field(old,"<DeadToTheSim>k__BackingField",0x160);actors::field(old,"_componentData",0x158);
            const auto active=actors::units(ba::read<Obj>(owner.manager->get(),0x10));
            const auto retained=actors::units(ba::read<Obj>(owner.manager->get(),0xa0));
            oldActive=std::find(active.begin(),active.end(),old)!=active.end();
            oldRetained=std::find(retained.begin(),retained.end(),old)!=retained.end();
            oldDead=ba::read<bool>(old,0x160);oldComponent=ba::read<Obj>(old,0x158)!=nullptr;
        }
        actors::field(selector,"_repeatFocusUnit",0xa8);actors::field(selector,"_focusChaseControlGroup",0xa0);
        // The original keeps an inactive repeat-focus cache when group==-1.
        // This FrontUpdate snapshot can also precede later selector cleanup.
        // Record the raw pointer/group truth without dereferencing or judging
        // a transient cache; the evaluator checks stable post-restore ownership.
    }
};
// Observe the rooted cache independently of whether the original coroutine is
// actually chasing it. A pooled inactive Unit can remain in this field.
struct FocusObservation {
    Root object;
    int group=-1;
    bool isUnit=false;
    std::string name,space,unityError;
    std::optional<uint32_t> entity,unitType,army;
    std::optional<bool> dead,component,active,retained,admitted,unityTruth,enabled;
    std::optional<uint64_t> observedToken,confirmedToken,cachedPtr;
    std::optional<bool> lookupPresent;
    Obj lookupActor=nullptr;
    std::string lookupError;
    static Obj returns(Obj info) {
        return ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(info));
    }
    static void signature(Obj info,bool isStatic,Obj result) {
        uint32_t implementation=0;const auto flags=ba::api<uint32_t(*)(Obj,uint32_t*)>("il2cpp_method_get_flags")(info,&implementation);
        require(((flags&0x10u)!=0)==isStatic&&returns(info)==result,"mobile focus original getter signature differs");
    }
    FocusObservation(actors::State& owner,Obj selector,const selection::Context& context)
        :object(ba::read<Obj>(selector,0xa8)),group(ba::read<int>(selector,0xa0)) {
        if(!object.get())return;
        Obj klass=ba::klass(object.get());require(klass,"mobile focus runtime class missing");
        const char* className=ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(klass);
        const char* classSpace=ba::api<const char*(*)(Obj)>("il2cpp_class_get_namespace")(klass);
        require(className&&classSpace&&strlen(className)<512&&strlen(classSpace)<512,"mobile focus runtime class text invalid");
        name=className;space=classSpace;isUnit=klass==actors::type("Uncapped","Unit");
        if(isUnit) {
            actors::field(object.get(),"<EntityId>k__BackingField",0x14c);actors::field(object.get(),"_fallbackArmyId",0x150);
            actors::field(object.get(),"_componentData",0x158);actors::field(object.get(),"<DeadToTheSim>k__BackingField",0x160);
            actors::field(object.get(),"_entityConfig",0x168);
            entity=ba::read<uint32_t>(object.get(),0x14c);army=ba::read<uint32_t>(object.get(),0x150);
            dead=ba::read<bool>(object.get(),0x160);component=ba::read<Obj>(object.get(),0x158)!=nullptr;
            const auto live=actors::units(ba::read<Obj>(owner.manager->get(),0x10));
            const auto kept=actors::units(ba::read<Obj>(owner.manager->get(),0xa0));
            active=std::find(live.begin(),live.end(),object.get())!=live.end();
            retained=std::find(kept.begin(),kept.end(),object.get())!=kept.end();
            admitted=context.admitted(object.get());
            // Original coroutine TryGet uses manager._units and cached.EntityId,
            // not selection/group membership. Observe its ID predicate through
            // the existing validated UnitSet/EntityIdSet span, without invoking
            // an unqualified generic/shared TryGet thunk.
            try {
                Root activeSet(ba::read<Obj>(owner.manager->get(),0x10));
                actors::classIs(activeSet.get(),"Uncapped.Collections","UnitSet");actors::field(activeSet.get(),"_entityIds",0x18);
                auto numeric=actors::ids(ba::read<Obj>(activeSet.get(),0x18));std::sort(numeric.begin(),numeric.end());
                std::vector<uint32_t> observed;observed.reserve(context.live.size());
                for(const auto& entry:context.live)observed.push_back(entry.first);
                const auto found=context.live.find(*entity);if(found!=context.live.end())lookupActor=found->second;
                if(numeric!=observed)lookupError="manager active ID span and observed actor-ID map disagree";
                else lookupPresent=std::binary_search(numeric.begin(),numeric.end(),*entity);
            } catch(const std::exception& error){lookupError=error.what();}
            catch(...){lookupError="unknown manager active ID observation failure";}
            const auto resident=owner.identities.find(object.get());
            if(resident!=owner.identities.end())observedToken=resident->second.incarnation;
            if(Obj config=ba::read<Obj>(object.get(),0x168)) {
                actors::classIs(config,"Uncapped","EntityConfig");actors::field(config,"UnitType",0x10);
                unitType=ba::read<uint32_t>(config,0x10);
                confirmedToken=actors::confirmedToken(owner,actors::policy::ActorIdentity{*entity,*unitType,*army});
            }
        }
        try {
            // Exact original metadata/RVA/signature guards; no invented entry
            // bytes or raw cached-pointer offset. Invoke each getter once.
            Obj cached=actors::method(object.get(),"GetCachedPtr",0,0x06000f08,0x17b7cf0);
            Obj truth=actors::method(object.get(),"op_Implicit",1,0x06000f04,0x508fda0);
            signature(cached,false,actors::type("System","IntPtr"));
            signature(truth,true,actors::type("System","Boolean"));
            require(original::parameterClass(truth,0)==actors::type("UnityEngine","Object"),"mobile focus Unity truth parameter differs");
            original::checkValue(returns(cached),8,"mobile focus cached pointer value size differs");
            original::checkValue(returns(truth),1,"mobile focus Unity truth value size differs");
            Root pointer(actors::invoke(cached,object.get()));cachedPtr=actors::unbox<uint64_t>(pointer.get());
            void* args[]={object.get()};Root alive(actors::invoke(truth,nullptr,args));unityTruth=actors::unbox<bool>(alive.get());
            if(*unityTruth) {
                Obj activity=actors::method(object.get(),"get_isActiveAndEnabled",0,0x06000df6,0x5084710);
                signature(activity,false,actors::type("System","Boolean"));
                original::checkValue(returns(activity),1,"mobile focus activity value size differs");
                Root result(actors::invoke(activity,object.get()));enabled=actors::unbox<bool>(result.get());
            }
        } catch(const std::exception& error){unityError=error.what();}
        catch(...){unityError="unknown original Unity focus observation failure";}
    }
    void json(std::ostringstream& out)const {
        const auto nullable=[&](const auto& value){if(value.has_value())out<<*value;else out<<"null";};
        out<<",\"focus_class_name\":"<<(object.get()?ba_catalog::quote(name):"null")
           <<",\"focus_class_namespace\":"<<(object.get()?ba_catalog::quote(space):"null")<<",\"focus_is_unit\":";
        if(object.get())out<<isUnit;else out<<"null";
        out<<",\"focus_actual_entity\":";nullable(entity);out<<",\"focus_actual_type\":";nullable(unitType);out<<",\"focus_actual_army\":";nullable(army);
        out<<",\"focus_dead_to_sim\":";nullable(dead);out<<",\"focus_component_present\":";nullable(component);
        out<<",\"focus_in_active\":";nullable(active);out<<",\"focus_in_retained\":";nullable(retained);out<<",\"focus_current_admitted\":";nullable(admitted);
        out<<",\"focus_observed_incarnation\":";nullable(observedToken);out<<",\"focus_confirmed_incarnation\":";nullable(confirmedToken);
        out<<",\"focus_lookup_id_present\":";nullable(lookupPresent);
        out<<",\"focus_lookup_actor\":";if(lookupActor)out<<'"'<<lookupActor<<'"';else out<<"null";
        out<<",\"focus_lookup_source\":\"manager-active-UnitSet-id-enumeration\",\"focus_lookup_proof_error\":"
           <<(lookupError.empty()?"null":ba_catalog::quote(lookupError));
        out<<",\"focus_cached_ptr\":";nullable(cachedPtr);out<<",\"focus_unity_truth\":";nullable(unityTruth);
        out<<",\"focus_is_active_and_enabled\":";nullable(enabled);
        out<<",\"focus_unity_proof_error\":"<<(unityError.empty()?"null":ba_catalog::quote(unityError));
    }
};
static void snapshot(actors::State& owner,Obj selector,int frame,const char* event,std::optional<bool> scope=std::nullopt) {
    auto& s=state();View view(owner,selector);FocusObservation focus(owner,selector,view.context);Obj group=s.group?s.group->get():groupFor(selector);
    require(group==groupFor(selector),"mobile fixture group root changed");
    const auto selected=selection::selectionIds(ba::read<Obj>(selector,0x90));
    const auto preview=selection::selectionIds(ba::read<Obj>(selector,0x88));
    const auto casting=selection::selectionIds(ba::read<Obj>(selector,0x98));
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::boolalpha;
    out<<"{\"schema\":1,\"event\":\""<<event<<"\",\"world\":"<<s.world<<",\"match\":\""<<s.match
       <<"\",\"entity\":11,\"army\":1,\"unit_type\":1,\"frame\":"<<frame
       <<",\"completed_frame\":"<<ba::read<int>(owner.simulation->get(),0xa8)<<",\"tick_ms\":"<<GetTickCount64()<<",\"sampled_us\":"<<stamp()
       <<",\"original_actor\":\""<<(s.oldActor?s.oldActor->get():nullptr)<<"\",\"current_actor\":\""<<view.current
       <<"\",\"original_incarnation\":"<<s.originalToken<<",\"current_incarnation\":"<<token(view.context,view.current)
       <<",\"original_actual_entity\":"<<(s.oldActor?ba::read<uint32_t>(s.oldActor->get(),0x14c):0)
       <<",\"old_dead_to_sim\":"<<view.oldDead<<",\"old_component_present\":"<<view.oldComponent
       <<",\"old_in_active\":"<<view.oldActive<<",\"old_in_retained\":"<<view.oldRetained
       <<",\"current_in_active\":"<<(view.current!=nullptr)<<",\"current_admitted\":"<<view.context.admitted(view.current)
       <<",\"native_identity_present\":"<<view.nativePresent<<",\"native_state_present\":"<<view.nativeValue.has_value()<<",\"native_state\":";
    if(view.nativeValue)out<<*view.nativeValue;else out<<"null";
    out<<",\"current_actual_entity\":";
    if(view.current){const auto identity=actors::resident(view.current);out<<identity.entityId<<",\"current_actual_type\":"<<identity.unitType<<",\"current_actual_army\":"<<identity.armyId;}
    else out<<"null,\"current_actual_type\":null,\"current_actual_army\":null";
    const auto nativeIdentity=view.native.identity(11);out<<",\"native_identity_type\":";
    if(nativeIdentity)out<<nativeIdentity->unitType<<",\"native_identity_army\":"<<nativeIdentity->armyId;
    else out<<"null,\"native_identity_army\":null";
    out<<",\"selected_ids\":"<<idsJson(selected)<<",\"preview_ids\":"<<idsJson(preview)<<",\"casting_ids\":"<<idsJson(casting)
       <<",\"casting_references_victim\":"<<actors::selectionReferences(ba::read<Obj>(selector,0x98),std::set<uint32_t>{11})
       <<",\"active_caster\":\""<<ba::read<Obj>(selector,0x100)<<"\",\"focus_actor\":\""<<focus.object.get()
       <<"\",\"focus_group\":"<<focus.group<<",\"group_ids\":"<<idsJson(selection::selectionIds(ba::read<Obj>(group,0x20)))
       <<",\"tracked_released_ids\":"<<idsJson(actors::ids(ba::read<Obj>(group,0x10)))
       <<",\"auto_type1\":"<<actors::automaticType(ba::read<Obj>(group,0x30),1)<<",\"pending_commands\":"<<pending(owner)
       <<",\"left_held\":"<<ba::read<bool>(selector,0x16c)<<",\"right_held\":"<<ba::read<bool>(selector,0x16d)
       <<",\"live_click_id\":"<<ba::read<uint32_t>(selector,0x128)<<",\"pool_callback_observed\":false,\"physicalUI\":false";
    out<<",\"selection_scope_player_initiated\":";if(scope.has_value())out<<*scope;else out<<"null";
    focus.json(out);out<<'}';
    ba::log("MOBILE CORRECTION %s",out.str().c_str());
}
static void selectCurrent(actors::State& owner,Obj selector,Obj actor,bool playerInitiated=true,uint32_t entity=11,uint32_t army=1) {
    idle(owner,selector,entity);selection::Context context(selector);
    require(context.live.count(entity)&&context.live.at(entity)==actor&&context.admitted(actor),"mobile fixture reselect source is not current confirmed unit");
    const auto identity=actors::resident(actor);require(identity.entityId==entity&&identity.unitType==1&&identity.armyId==army,"mobile fixture selection identity differs");
    Obj clear=actors::method(selector,"ClearSelection",0,0x06002217,0x3bf2680);
    Obj add=actors::method(selector,"AddToSelection",1,0x06002214,0x3bf2510);
    Obj begin=actors::method(selector,"BeginSelectionChange",1,0x06002237,0x3bf5af0);
    actors::field(selector,"_selectionChangeHelper",0x80);Root helper(ba::read<Obj>(selector,0x80));require(helper.get(),"mobile fixture selection helper missing");
    actors::field(helper.get(),"<IsSuspended>k__BackingField",0x10);require(!ba::read<bool>(helper.get(),0x10),"mobile fixture selection is already suspended");
    Obj dispose=actors::method(helper.get(),"Dispose",0,0x060000cd,0x3b02160);bool disposed=false;
    auto close=[&](){if(!disposed&&ba::read<bool>(helper.get(),0x10)){disposed=true;actors::invoke(dispose,helper.get());}};
    try {
        bool player=playerInitiated;void* args[]={&player};
        require(actors::invoke(begin,selector,args)==helper.get()&&ba::read<bool>(helper.get(),0x10),
            "mobile fixture selection scope owner/suspension differs");owned(owner);
        actors::invoke(clear,selector);owned(owner);uint32_t id=entity;void* ids[]={&id};actors::invoke(add,selector,ids);owned(owner);
        close();owned(owner);require(disposed&&!ba::read<bool>(helper.get(),0x10),"mobile fixture selection scope did not close");
    } catch(...) {try{close();}catch(...){ba::log("Mobile fixture selection cleanup failed; retry=0");}throw;}
    require(selection::selectionIds(ba::read<Obj>(selector,0x90))==std::vector<uint32_t>{entity},"mobile fixture original selection did not retain exactly its unit");
}
static bool groupIntentEnabled(){return ba::flag(L"-prediction-mobile-group-intent-smoke");}
static bool groupUserEditsEnabled(){return ba::flag(L"-prediction-mobile-group-user-edits-smoke");}
static bool recoveryStallEnabled(){return ba::flag(L"-prediction-mobile-recovery-stall-smoke");}
static bool recallEnabled(){return ba::flag(L"-prediction-mobile-recall-smoke");}
static std::vector<uint32_t> groupIds(Obj group){return selection::selectionIds(ba::read<Obj>(group,0x20));}
static void assignSelected(actors::State& owner,Obj selector,int index) {
    Obj group=groupFor(selector,index);require(!actors::automaticType(ba::read<Obj>(group,0x30),1),"group intent fixture needs manual type1 membership");
    Obj assign=actors::method(selector,"AssignSelectionToControlGroup",2,0x0600220e,0x3bf14e0);
    bool replace=true;void* args[]={&index,&replace};actors::invoke(assign,selector,args);owned(owner);
}
static void groupEvidence(actors::State& owner,Obj selector,int frame,const char* event,const char* operation=nullptr) {
    auto& s=state();owned(owner);selection::Context context(selector);const bool attacker=ba::lanSlot()==0;
    const uint32_t entity=attacker?10u:11u,army=attacker?0u:1u;
    const uint64_t observed=attacker?s.attackerToken:s.originalToken;
    Obj retained=attacker?s.attackerGroup->get():s.group->get();
    require(retained==groupFor(selector,4),"group intent fixture retained group owner changed");
    actors::Current current(ba::read<Obj>(owner.simulation->get(),0x148));
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::boolalpha;
    out<<"{\"schema\":1,\"event\":\""<<event<<"\",\"world\":"<<s.world<<",\"match\":\""<<s.match
       <<"\",\"slot\":"<<ba::lanSlot()<<",\"frame\":"<<frame<<",\"tick_ms\":"<<GetTickCount64()<<",\"sampled_us\":"<<stamp()
       <<",\"entity\":"<<entity<<",\"unit_type\":1,\"army\":"<<army<<",\"incarnation\":"<<observed
       <<",\"confirmed_incarnation\":"<<actors::confirmedToken(owner,{entity,1,army})
       <<",\"native_identity_present\":"<<current.identity(entity).has_value()<<",\"current_admitted\":"<<context.admitted(entity)
       <<",\"retained_group\":4,\"retained_ids\":"<<idsJson(groupIds(retained))
       <<",\"retained_tracked_ids\":"<<idsJson(actors::ids(ba::read<Obj>(retained,0x10)))
       <<",\"operation\":"<<(operation?ba_catalog::quote(operation):"null")
       <<",\"original_scope_player_initiated\":";
    if(operation)out<<"true";else out<<"null";
    const bool clear=operation&&!strcmp(operation,"clear"),replace=operation&&!strcmp(operation,"replace");
    out<<",\"clear_callback\":"<<(clear?"\"Uncapped.ControlGroup.Clear\"":"null")
       <<",\"replace_callback\":"<<(replace?"\"Uncapped.ControlGroupPanel.AssignToControlGroup\"":"null")
       <<",\"replace_source_count\":"<<(replace?"0":"null")<<",\"replace_existing\":"<<(replace?"true":"null")
       <<",\"physicalUI\":false}";
    ba::log("MOBILE GROUP INTENT %s",out.str().c_str());
}
static void clearOriginalGroup(actors::State& owner,Obj group) {
    actors::field(group,"_controlGroupChangeHelper",0x40);Root helper(ba::read<Obj>(group,0x40));require(helper.get(),"group intent clear helper missing");
    actors::field(helper.get(),"<IsSuspended>k__BackingField",0x10);require(!ba::read<bool>(helper.get(),0x10),"group intent clear already suspended");
    Obj begin=actors::method(group,"BeginControlGroupChange",1,0x06001645,0x3ea5790);
    Obj clear=actors::method(group,"Clear",0,0x06001644,0x3ea5740);
    Obj dispose=actors::method(helper.get(),"Dispose",0,0x060000cd,0x3b02160);bool disposed=false;
    auto close=[&](){if(!disposed&&ba::read<bool>(helper.get(),0x10)){disposed=true;actors::invoke(dispose,helper.get());}};
    try {
        bool player=true;void* args[]={&player};
        require(actors::invoke(begin,group,args)==helper.get()&&ba::read<bool>(helper.get(),0x10),"group intent clear scope differs");owned(owner);
        actors::invoke(clear,group);owned(owner);close();owned(owner);
        require(disposed&&!ba::read<bool>(helper.get(),0x10)&&groupIds(group).empty(),"group intent original clear did not close/clear");
    } catch(...){try{close();}catch(...){ba::log("Group intent clear scope cleanup failed; retry=0");}throw;}
}
static void replaceOriginalGroupWithEmpty(actors::State& owner,Obj selector,int index) {
    actors::field(selector,"_controlGroupPanel",0x38);Root panel(ba::read<Obj>(selector,0x38));actors::classIs(panel.get(),"Uncapped","ControlGroupPanel");
    Obj assign=actors::method(panel.get(),"AssignToControlGroup",3,0x06001742,0x3b471f0);
    FocusObservation::signature(assign,false,actors::type("System","Void"));
    require(original::parameterClass(assign,1)==actors::type("System","Int32")&&
        original::parameterClass(assign,2)==actors::type("System","Boolean"),"group intent original replace signature differs");
    // Original AssignSelectionToControlGroup passes its UnitSelectionSet
    // directly as ISet<uint>. Use the same original concrete set class from
    // this selector's empty preview, without altering ordinary selection.
    actors::field(selector,"_previewSelectionSet",0x88);actors::field(selector,"_selectionSet",0x90);
    Root empty(ba::read<Obj>(selector,0x88));actors::classIs(empty.get(),"Uncapped.Collections","UnitSelectionSet");
    actors::field(empty.get(),"_simFrames",0x48);
    require(ba::klass(empty.get())==ba::klass(ba::read<Obj>(selector,0x90))&&
        ba::read<Obj>(empty.get(),0x48)==ba::read<Obj>(owner.simulation->get(),0x148)&&
        selection::selectionIds(empty.get()).empty()&&!actors::selectionReferences(empty.get(),std::set<uint32_t>{11})&&
        ba::api<bool(*)(Obj,Obj)>("il2cpp_class_is_assignable_from")(original::parameterClass(assign,0),ba::klass(empty.get())),
        "group intent original replace source is not an owned assignable empty numeric set");
    bool replace=true;void* args[]={empty.get(),&index,&replace};actors::invoke(assign,panel.get(),args);owned(owner);
    require(groupIds(groupFor(selector,index)).empty(),"group intent original empty replacement did not clear");
}
static void editGroupsDuringAbsence(actors::State& owner,Obj selector,int frame) {
    auto& s=state();require(!s.groupHoldObserved&&s.group,"group intent hold state differs");
    require(groupIds(s.group->get())==std::vector<uint32_t>{11},"group intent preservation failed before provisional hold");
    require(actors::confirmedToken(owner,{11,1,1})==s.originalToken,"group intent user edit lacks unchanged confirmed token");
    s.groupHoldObserved=true;
    if(!groupUserEditsEnabled()){groupEvidence(owner,selector,frame,"before_provisional_hold");return;}
    require(s.world==1||s.world==2,"group intent edit fixture needs actual owned worlds1/2");
    groupEvidence(owner,selector,frame,"before_user_edits");
    if(s.world==1)clearOriginalGroup(owner,s.group->get());else replaceOriginalGroupWithEmpty(owner,selector,4);
    require(groupIds(s.group->get()).empty(),"group intent original user edit did not remove its visible member");
    s.groupEdits=true;groupEvidence(owner,selector,frame,"after_user_edits",s.world==1?"clear":"replace");
}
// Original recall owns its true player-initiated selection scope, including all
// original notifications. No direct selection/group mutation or callback retry.
struct RecallMethods {
    Root selector,helper;
    Obj cancel=nullptr,actuate=nullptr;
    static Obj helperReference(Obj value) {
        actors::field(value,"_selectionChangeHelper",0x80);return ba::read<Obj>(value,0x80);
    }
    explicit RecallMethods(Obj value):selector(value),helper(helperReference(value)) {
        require(helper.get()&&selection::helperSelector(helper.get())==value,"group recall selection helper owner differs");
        actors::field(helper.get(),"<IsSuspended>k__BackingField",0x10);
        require(!ba::read<bool>(helper.get(),0x10),"group recall selection scope already suspended");
        cancel=actors::method(value,"FocusControlGroupCancel",1,0x06002220,0x3bf2fa0);
        actuate=actors::method(value,"ActuateControlGroup",1,0x0600220f,0x3bf1650);
        FocusObservation::signature(cancel,false,actors::type("System","Void"));
        FocusObservation::signature(actuate,false,actors::type("System","Boolean"));
        require(original::parameterClass(cancel,0)==actors::type("System","Int32")&&
            original::parameterClass(actuate,0)==actors::type("System","Int32"),"group recall original argument ABI differs");
        actors::guard(0x3bf2fa0,"\x3b\x91\xa0\x00\x00\x00\x75\x59\x83\x3d\x99\x34\x25\x03\x00\x48\x8d\x91\xa8\x00\x00\x00\x48\xc7\x02\x00\x00\x00\x00\xc7\x81\xa0\x00\x00\x00\xff\xff\xff\xff",39);
        actors::guard(0x3bf1650,"\x48\x89\x5c\x24\x10\x48\x89\x74\x24\x18\x57\x48\x83\xec\x40\x48\x63\xf2\x48\x8b\xd9\x80\x3d\xb1",24);
    }
    void validate()const {
        require(!ba_lan::stopped&&!ba_community::abortPending&&ba_lan::running,
            "group recall original callback stopped its active owner");
        require(ba::read<Obj>(selector.get(),0x80)==helper.get()&&
            selection::helperSelector(helper.get())==selector.get()&&!ba::read<bool>(helper.get(),0x10),
            "group recall original selection scope did not close on its owner");
    }
    bool recall(actors::State& owner) {
        validate();require(ba::read<int>(selector.get(),0xa0)==-1,"group recall still has active repeat focus");
        int index=4;void* args[]={&index};Root result(actors::invoke(actuate,selector.get(),args));owned(owner);validate();
        return actors::unbox<bool>(result.get());
    }
};
static int recallSourceCount(Obj selector) {
    Root source(ba::read<Obj>(groupFor(selector),0x20));actors::classIs(source.get(),"Uncapped.Collections","UnitSelectionSet");
    Obj count=actors::method(source.get(),"get_Count",0,0x060025b5,0x3c68f00);
    FocusObservation::signature(count,false,actors::type("System","Int32"));
    Root boxed(actors::invoke(count,source.get()));const int value=actors::unbox<int32_t>(boxed.get());
    // This original getter counts IDs resolvable through the physical TypeBuffer,
    // not the numeric membership deliberately preserved by the group shim.
    require(value>=0&&value<=1,"group recall original resolvable count exceeds its single member");return value;
}
static void recallEvidence(actors::State& owner,Obj selector,int frame,const char* event,
                           bool cancelled=false,std::optional<bool> result=std::nullopt) {
    const auto& s=state();owned(owner);View view(owner,selector);
    require(s.group&&s.group->get()==groupFor(selector)&&groupIds(s.group->get())==std::vector<uint32_t>{11}&&
        actors::groupCacheMembership(ba::read<Obj>(s.group->get(),0x20),11)&&
        actors::confirmedToken(owner,{11,1,1})==s.originalToken,"group recall lost its unchanged original group identity");
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::boolalpha;
    out<<"{\"schema\":1,\"event\":\""<<event<<"\",\"world\":"<<s.world<<",\"match\":\""<<s.match
       <<"\",\"slot\":1,\"entity\":11,\"unit_type\":1,\"army\":1,\"frame\":"<<frame
       <<",\"completed_frame\":"<<ba::read<int>(owner.simulation->get(),0xa8)<<",\"tick_ms\":"<<GetTickCount64()<<",\"sampled_us\":"<<stamp()
       <<",\"incarnation\":"<<s.originalToken<<",\"confirmed_incarnation\":"<<actors::confirmedToken(owner,{11,1,1})
       <<",\"current_incarnation\":"<<token(view.context,view.current)<<",\"retained_group\":4,\"group_ids\":"<<idsJson(groupIds(s.group->get()))
       <<",\"selected_ids\":"<<idsJson(selection::selectionIds(ba::read<Obj>(selector,0x90)))
       <<",\"preview_ids\":"<<idsJson(selection::selectionIds(ba::read<Obj>(selector,0x88)))
       <<",\"casting_ids\":"<<idsJson(selection::selectionIds(ba::read<Obj>(selector,0x98)))
       <<",\"native_identity_present\":"<<view.nativePresent<<",\"current_admitted\":"<<view.context.admitted(view.current)
       <<",\"source_resolvable_count\":"<<recallSourceCount(selector)
       <<",\"current_actor\":\""<<view.current<<"\",\"current_actual_entity\":";
    if(view.current){const auto id=actors::resident(view.current);out<<id.entityId<<",\"current_actual_type\":"<<id.unitType<<",\"current_actual_army\":"<<id.armyId;}
    else out<<"null,\"current_actual_type\":null,\"current_actual_army\":null";
    out<<",\"focus_group\":"<<ba::read<int>(selector,0xa0)<<",\"pending_commands\":"<<pending(owner)
       <<",\"cancel_callback\":"<<(cancelled?"\"Uncapped.UnitSelector.FocusControlGroupCancel\"":"null")
       <<",\"cancel_token\":"<<(cancelled?"\"06002220\"":"null")
       <<",\"actuate_callback\":"<<(result?"\"Uncapped.UnitSelector.ActuateControlGroup\"":"null")
       <<",\"actuate_token\":"<<(result?"\"0600220f\"":"null")<<",\"actuate_result\":";
    if(result)out<<*result;else out<<"null";
    out<<",\"physicalUI\":false}";ba::log("MOBILE GROUP RECALL %s",out.str().c_str());
}
static void recallAbsentGroup(actors::State& owner,Obj selector,int frame) {
    auto& s=state();idle(owner,selector,11);View view(owner,selector);RecallMethods methods(selector);
    require(!s.recallAbsent&&s.firstReleased>=0&&!view.nativePresent&&!view.current&&s.groupHoldObserved,
        "group recall needs the actual absent unit and its retained group");
    const int focus=ba::read<int>(selector,0xa0);require(focus==-1||focus==4,"group recall belongs to another held focus");
    recallEvidence(owner,selector,frame,"before_absent_recall");
    int index=4;void* args[]={&index};actors::invoke(methods.cancel,selector,args);owned(owner);methods.validate();
    require(ba::read<int>(selector,0xa0)==-1,"original group recall key release did not leave active focus");
    recallEvidence(owner,selector,frame,"focus_cancelled",true);
    const auto selected=selection::selectionIds(ba::read<Obj>(selector,0x90));
    const auto preview=selection::selectionIds(ba::read<Obj>(selector,0x88));
    const auto casting=selection::selectionIds(ba::read<Obj>(selector,0x98));
    const int count=recallSourceCount(selector);
    const bool result=methods.recall(owner);
    if(count==0) {
        require(!result&&selection::selectionIds(ba::read<Obj>(selector,0x90))==selected&&
            selection::selectionIds(ba::read<Obj>(selector,0x88))==preview&&
            selection::selectionIds(ba::read<Obj>(selector,0x98))==casting,
            "original absent recall did not preserve its legitimate empty-resolvable-source refusal");
    } else require(result&&selection::selectionIds(ba::read<Obj>(selector,0x90)).empty()&&
            !actors::selectionReferences(ba::read<Obj>(selector,0x90),std::set<uint32_t>{11})&&
            selection::selectionIds(ba::read<Obj>(selector,0x88)).empty(),"original absent recall did not complete admission filtering");
    s.recallAbsent=true;recallEvidence(owner,selector,frame,"after_absent_recall",false,result);
}
static void recallRestoredGroup(actors::State& owner,Obj selector,int frame) {
    auto& s=state();idle(owner,selector,11);View view(owner,selector);RecallMethods methods(selector);
    require(s.recallAbsent&&!s.recallRestored&&s.firstRestored>=0&&view.nativePresent&&view.current&&
        view.context.admitted(view.current)&&token(view.context,view.current)==s.originalToken,
        "group recall needs the current restored admitted unit");
    recallEvidence(owner,selector,frame,"before_restored_recall");
    require(recallSourceCount(selector)==1,"original restored group member is not physically type-resolvable");
    const bool result=methods.recall(owner);
    selection::Context current(selector);
    require(result&&current.admitted(11)&&current.live.at(11)==view.current&&token(current,view.current)==s.originalToken&&
        selection::selectionIds(ba::read<Obj>(selector,0x90))==std::vector<uint32_t>{11},
        "original restored recall did not select the current admitted unit");
    s.recallRestored=true;recallEvidence(owner,selector,frame,"after_restored_recall",false,result);
}
static void setup(actors::State& owner,Obj selector,int frame) {
    auto& s=state();selection::Context context(selector);const auto found=context.live.find(11);
    require(found!=context.live.end()&&context.admitted(found->second),"mobile fixture confirmed victim11 missing");Obj actor=found->second;
    const auto identity=actors::resident(actor);require(identity.entityId==11&&identity.unitType==1&&identity.armyId==1,"mobile fixture victim identity differs");
    actors::field(actor,"_entityConfig",0x168);Obj config=ba::read<Obj>(actor,0x168);actors::field(config,"IsHQ",0x2c);
    require(!ba::read<bool>(config,0x2c),"mobile fixture cannot bypass original HQ group exclusion");
    s.oldActor=std::make_unique<Root>(actor);s.originalToken=token(context,actor);require(s.originalToken,"mobile fixture original admission token missing");
    s.group=std::make_unique<Root>(groupFor(selector));selectCurrent(owner,selector,actor);
    Obj assign=actors::method(selector,"AssignSelectionToControlGroup",2,0x0600220e,0x3bf14e0);
    Obj focus=actors::method(selector,"FocusControlGroup",2,0x06002221,0x3bf3010);
    int group=4;bool replace=true;void* assignArgs[]={&group,&replace};actors::invoke(assign,selector,assignArgs);owned(owner);
    bool repeat=true;void* focusArgs[]={&group,&repeat};actors::invoke(focus,selector,focusArgs);owned(owner);
    const auto ids=selection::selectionIds(ba::read<Obj>(s.group->get(),0x20));
    require(std::find(ids.begin(),ids.end(),11)!=ids.end()&&ba::read<Obj>(selector,0xa8)==actor&&ba::read<int>(selector,0xa0)==4,
        "mobile fixture original group/repeat focus was not positively established");
    s.setup=true;snapshot(owner,selector,frame,"original_mobile_selection_established",true);
    if(groupIntentEnabled())groupEvidence(owner,selector,frame,"setup");
}
static std::string common(const char* event,int frame,uint32_t entity,uint32_t army,uint64_t incarnation) {
    std::ostringstream out;const auto& s=state();out<<"{\"schema\":1,\"event\":\""<<event<<"\",\"world\":"<<s.world<<",\"match\":\""<<s.match
      <<"\",\"entity\":"<<entity<<",\"unit_type\":1,\"army\":"<<army<<",\"incarnation\":"<<incarnation<<",\"frame\":"<<frame<<",\"tick_ms\":"<<GetTickCount64();return out.str();
}
static void pose(actors::State& owner,const original::Vec3& point,int frame,bool baseline) {
    auto& s=state();owned(owner);const auto now=stamp();require(now>s.lastPoseUs&&s.samples<1024,"mobile fixture pose clock/sample bound");
    s.lastPoseUs=now;s.lastPoseTick=GetTickCount64();++s.samples;
    const auto text=common("transform",frame,11,1,s.currentToken)+",\"move_id\":1,\"position\":"+original::pointJson(point)+
        ",\"sampled_us\":"+std::to_string(now)+",\"presented_frame\":"+std::to_string(frame)+",\"completed_frame\":"+
        std::to_string(ba::read<int>(owner.simulation->get(),0xa8))+",\"baseline\":"+(baseline?"true":"false")+
        ",\"source\":\"UnityEngine.Transform.get_position\",\"jobsJoined\":true,\"physicalUI\":false}";
    ba::log("MOBILE FEEL %s",text.c_str());
}
struct MapPerspective {
    uint32_t alliance=0;
    int32_t value=0,normal=0,flipped=0;
    std::string json()const {
        return ",\"local_alliance\":"+std::to_string(alliance)+",\"map_perspective\":"+std::to_string(value)+
            ",\"map_perspective_source\":\"Uncapped.Map.GetAlliancePerspective\",\"map_perspective_enum\":\"Uncapped.Map.Perspective\","+
            "\"map_perspective_enum_matches_ctor\":true,\"map_perspective_normal\":"+std::to_string(normal)+
            ",\"map_perspective_flipped\":"+std::to_string(flipped)+",\"map_perspective_value_name\":\""+(value==normal?"Normal":"Flipped")+"\"";
    }
};
static MapPerspective currentPerspective(actors::State& owner,Obj selector,Obj constructor) {
    owned(owner);actors::field(selector,"_mapManager",0x50);actors::field(selector,"_simulation",0x138);
    require(ba::read<Obj>(selector,0x138)==owner.simulation->get(),"mobile perspective selector/simulation differs");
    Root manager(ba::read<Obj>(selector,0x50));actors::classIs(manager.get(),"Uncapped","MapManager");
    Obj getMap=actors::method(manager.get(),"get_CurrentMap",0,0x0600077e,0x845d70);
    FocusObservation::signature(getMap,false,actors::type("Uncapped","Map"));
    Root map(actors::invoke(getMap,manager.get()));owned(owner);actors::classIs(map.get(),"Uncapped","Map");
    actors::field(owner.simulation->get(),"_localPlayer",0x90);Root player(ba::read<Obj>(owner.simulation->get(),0x90));
    actors::classIs(player.get(),"Uncapped","SimPlayer");actors::field(player.get(),"AllianceID",0x3c);
    Obj allianceType=ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
        ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(ba::field(player.get(),"AllianceID")));
    require(allianceType==actors::type("System","UInt32"),"mobile perspective AllianceID is not UInt32");
    MapPerspective proof;proof.alliance=ba::read<uint32_t>(player.get(),0x3c);
    Obj getPerspective=actors::method(map.get(),"GetAlliancePerspective",1,0x0600075b,0x3db8f80);
    Obj perspectiveType=original::parameterClass(constructor,2);
    FocusObservation::signature(getPerspective,false,perspectiveType);
    require(original::parameterClass(getPerspective,0)==actors::type("System","UInt32"),"mobile perspective getter parameter differs");
    original::checkValue(perspectiveType,4,"mobile perspective getter enum value size differs");
    proof.normal=original::normalPerspective(constructor);
    Obj flipped=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(perspectiveType,"Flipped");require(flipped,"mobile perspective Flipped literal missing");
    require((ba::api<uint32_t(*)(Obj)>("il2cpp_field_get_flags")(flipped)&0x50u)==0x50u,"mobile perspective Flipped is not a static literal");
    ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(flipped,&proof.flipped);
    require(proof.normal==0&&proof.flipped==1,"mobile perspective original Normal/Flipped values differ");
    void* args[]={&proof.alliance};Root value(actors::invoke(getPerspective,map.get(),args));owned(owner);
    require(value.get()&&ba::klass(value.get())==perspectiveType,"mobile perspective boxed enum differs from constructor parameter");
    proof.value=actors::unbox<int32_t>(value.get());require(proof.value==proof.normal||proof.value==proof.flipped,"mobile perspective returned unknown enum");
    // Original ProtocolUtil.ToProto3dc7430 maps Normal0 identically and
    // Flipped by negating X/Z before Q32.32. Keep the Unity target unchanged;
    // the original command's ToProto owns that conversion, never this fixture.
    return proof;
}
static void move(actors::State& owner,Obj selector,int frame,uint32_t id,const original::Vec3& target,bool fresh,
                 const original::Vec3* observedOrigin=nullptr,uint64_t observedOriginUs=0) {
    owned(owner);idle(owner,selector,id);selection::Context context(selector);const auto found=context.live.find(id);
    require(found!=context.live.end()&&context.admitted(found->second),"mobile fixture command source is not current admitted");Obj actor=found->second;
    const auto identity=actors::resident(actor);const uint32_t army=fresh?1u:0u;
    require(identity.entityId==id&&identity.unitType==1&&identity.armyId==army,"mobile fixture command identity differs");
    const auto incarnation=token(context,actor);require(incarnation,"mobile fixture command admission token missing");
    require(!fresh||(observedOrigin&&observedOriginUs&&observedOriginUs==state().lastPoseUs),
        "mobile fixture fresh Move needs its exact observed baseline sample");
    const auto origin=fresh?*observedOrigin:original::actualPosition(owner,actor);
    const auto originSampled=fresh?observedOriginUs:stamp();original::finite(origin);original::finite(target);
    if(fresh)require(state().currentActor&&state().currentActor->get()==actor&&state().currentToken==incarnation,
        "mobile fixture fresh command cannot use an old actor lease/token");
    uint32_t ability=12,unitType=1;
    Root ids(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(actors::type("System","UInt32"),1));require(ids.get(),"mobile fixture ID array allocation failed");
    std::memcpy(static_cast<unsigned char*>(ids.get())+0x20,&id,sizeof(id));
    Root group(original::allocate("ExecuteCommandEntityTypeData"));Obj groupCtor=actors::method(group.get(),".ctor",3,0x060000f3,0x34b3080);
    void* groupArgs[]={ids.get(),&ability,&unitType};actors::invoke(groupCtor,group.get(),groupArgs);owned(owner);
    require(ba::read<Obj>(group.get(),0x10)==ids.get()&&ba::read<uint32_t>(group.get(),0x18)==ability&&ba::read<uint32_t>(group.get(),0x1c)==unitType,
        "mobile fixture typed original group readback differs");
    Root groups(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(ba::klass(group.get()),1));require(groups.get(),"mobile fixture group array allocation failed");
    auto* slot=reinterpret_cast<Obj*>(static_cast<unsigned char*>(groups.get())+0x20);
    ba::api<void(*)(Obj,Obj*,Obj)>("il2cpp_gc_wbarrier_set_field")(groups.get(),slot,group.get());require(*slot==group.get(),"mobile fixture group reference differs");
    Root command(original::allocate("ExecuteTargetGroundCommand"));Obj ctor=actors::method(command.get(),".ctor",4,0x060000e6,0x37ae080);
    require(original::parameterClass(ctor,1)==actors::type("UnityEngine","Vector3"),"mobile fixture original Vector3 ABI differs");
    std::optional<MapPerspective> perspectiveProof;
    int32_t perspective=original::normalPerspective(ctor);
    if(fresh){perspectiveProof=currentPerspective(owner,selector,ctor);perspective=perspectiveProof->value;}
    bool queued=false;auto mutableTarget=target;
    void* args[]={groups.get(),&mutableTarget,&perspective,&queued};actors::invoke(ctor,command.get(),args);owned(owner);
    actors::field(command.get(),"<Position>k__BackingField",0x18);actors::field(command.get(),"<Queued>k__BackingField",0x24);actors::field(command.get(),"_mapPerspective",0x28);
    const auto stored=ba::read<original::Vec3>(command.get(),0x18);
    require(ba::read<Obj>(command.get(),0x10)==groups.get()&&!ba::read<bool>(command.get(),0x24)&&ba::read<int32_t>(command.get(),0x28)==perspective&&
        !memcmp(&stored,&target,sizeof(target)),"mobile fixture original ground constructor readback differs");
    const auto hash=original::actionHash(command.get());selection::Context recheck(selector);
    require(recheck.live.count(id)&&recheck.live.at(id)==actor&&recheck.admitted(actor)&&token(recheck,actor)==incarnation,"mobile fixture source changed before enqueue");
    idle(owner,selector,id);Obj server=ba_local::server();Obj enqueue=actors::method(server,"EnqueueInputCommand",1,0x06001115,0x3e53530);
    const auto sampled=stamp();void* commandArgs[]={command.get()};actors::invoke(enqueue,server,commandArgs);owned(owner);const auto enqueued=stamp();
    require(pending(owner)==1,"mobile fixture original enqueue did not add exactly one ICommand");
    uint32_t bits[3]{};std::memcpy(bits,&target,sizeof(target));
    const auto text=common(fresh?"original_fresh_move":"original_escape_move",frame,id,army,incarnation)+
        ",\"ability\":12,\"origin\":"+original::pointJson(origin)+",\"target\":"+original::pointJson(target)+",\"target_bits\":["+
        std::to_string(bits[0])+","+std::to_string(bits[1])+","+std::to_string(bits[2])+"],\"sampled_us\":"+std::to_string(sampled)+
        ",\"origin_sampled_us\":"+std::to_string(originSampled)+",\"enqueue_sampled_us\":"+std::to_string(enqueued)+",\"action_sha256\":\""+hash+"\",\"originalCtor\":true,\"physicalUI\":false,"+
        "\"original_callback\":\"Uncapped.ExecuteTargetGroundCommand..ctor\",\"queueDelta\":1,\"reselected_current\":"+(fresh?"true":"false")+
        (perspectiveProof?perspectiveProof->json():std::string{})+"}";
    ba::log("MOBILE ORDER %s",text.c_str());if(fresh){state().freshQueued=true;state().freshFrame=frame;}else state().escapeQueued=true;
}
static void attackerGroupTick(actors::State& owner,Obj selector,int frame) {
    auto& s=state();if(frame<130)return;
    if(!s.attackerSetup) {
        require(frame==130,"group intent fixture missed attacker selection130");selection::Context context(selector);
        const auto found=context.live.find(10);require(found!=context.live.end()&&context.admitted(found->second),"group intent confirmed attacker10 missing");
        s.attackerToken=token(context,found->second);require(s.attackerToken,"group intent attacker incarnation missing");
        // Each client owns a different selector/panel. Use the available
        // group4 in each process rather than inventing extra group slots.
        s.attackerGroup=std::make_unique<Root>(groupFor(selector,4));
        selectCurrent(owner,selector,found->second,true,10,0);assignSelected(owner,selector,4);
        require(groupIds(s.attackerGroup->get())==std::vector<uint32_t>{10},"group intent original attacker group was not established");
        s.attackerSetup=true;groupEvidence(owner,selector,frame,"attacker_setup");
    }
    if(!s.escapeQueued&&frame>=150) {
        require(frame==150,"mobile fixture missed physical escape150");move(owner,selector,frame,10,original::Vec3{-32.f,0.f,0.f},false);
    }
    if(s.escapeQueued&&!s.attackerPurged) {
        selection::Context context(selector);actors::Current current(ba::read<Obj>(owner.simulation->get(),0x148));
        const auto confirmed=actors::confirmedToken(owner,{10,1,0});
        if(!s.attackerAbsent&&!current.identity(10)&&!context.live.count(10)&&confirmed==s.attackerToken) {
            require(groupIds(s.attackerGroup->get())==std::vector<uint32_t>{10},"group intent attacker lost provisional numeric membership");
            s.attackerAbsent=true;groupEvidence(owner,selector,frame,"attacker_speculative_absence");
        }
        // A Context may observe authority newer than the preceding original
        // actor update. Wait for completed original purge;220 remains bounded.
        if(s.attackerAbsent&&!confirmed&&groupIds(s.attackerGroup->get()).empty()) {
            s.attackerPurged=true;groupEvidence(owner,selector,frame,"attacker_confirmed_purge");
        }
    }
    if(frame>=220) {
        require(s.attackerAbsent&&s.attackerPurged,"group intent attacker lacks speculative-preserve/confirmed-purge evidence");
        require(groupIds(s.attackerGroup->get()).empty(),"group intent attacker membership returned after confirmed death");
        groupEvidence(owner,selector,frame,"attacker_complete");s.passed=true;
    }
}
static void tick() {
    try {
        require(!ba::flag(L"-prediction-actor-correction-smoke"),"mobile/HQ fixture flags must be separate");
        const auto world=worker::movementWorldId();const auto match=worker::movementMatchId();
        if(!worker::movementEnabled()||!world||match.empty()){state()=State{};return;}
        auto& s=state();if(s.world!=world||s.match!=match){s=State{};s.world=world;s.match=match;}
        if(s.failed||s.passed)return;auto& owner=actors::state();
        if(owner.world!=world||owner.match!=match||!owner.manager||!owner.simulation)return;
        owned(owner);if(ba_lan::matchEnded)return;
        require(!recoveryStallEnabled()||(groupIntentEnabled()&&groupUserEditsEnabled()),
            "mobile recovery stall requires the explicit group user-edit fixture");
        require(!recallEnabled()||(groupIntentEnabled()&&!groupUserEditsEnabled()&&!recoveryStallEnabled()),
            "mobile recall requires preserve-only group intent without an injected stall");
        require(ba::unified()&&ba::community()&&ba::dedicated()&&ba::lan()&&ba_lan::originalCommandScheduling()&&ba_lan::running&&!ba_lan::publicMatch,
            "mobile fixture requires negotiated prediction Custom");
        const int frame=ba::read<int>(owner.simulation->get(),0xac);
        if(ba::lanSlot()==0){
            if(groupIntentEnabled()){attackerGroupTick(owner,selectorFor(owner),frame);return;}
            if(s.escapeQueued||frame<150)return;require(frame==150,"mobile fixture missed physical escape150");move(owner,selectorFor(owner),frame,10,original::Vec3{-32.f,0.f,0.f},false);return;
        }
        require(ba::lanSlot()==1,"mobile fixture requires two human seats");if(frame<130)return;
        Obj selector=selectorFor(owner);
        if(!s.setup){require(frame==130,"mobile fixture missed victim setup130");setup(owner,selector,frame);return;}
        if(!s.freshQueued)idle(owner,selector,11);
        View view(owner,selector);
        if(frame!=s.lastSnapshot){s.lastSnapshot=frame;snapshot(owner,selector,frame,"snapshot");}
        if(recoveryStallEnabled()&&s.world==2&&!s.recoveryStalled&&frame>=152) {
            require(frame==152&&s.lastSnapshot==152&&ba::read<int>(owner.simulation->get(),0xac)==152,
                "mobile recovery stall missed its owned publication152");
            const int completedBefore=ba::read<int>(owner.simulation->get(),0xa8);
            s.recoveryStalled=true;
            // Explicit owned diagnostic only. The measured bracket contains
            // Sleep itself, not logging or owner revalidation. No frame,
            // command, packet or original collection is changed by this probe.
            const auto begin=stamp();Sleep(250);const auto end=stamp();owned(owner);
            const int presentedAfter=ba::read<int>(owner.simulation->get(),0xac);
            const int completedAfter=ba::read<int>(owner.simulation->get(),0xa8);
            const auto text=std::string("{\"schema\":1,\"event\":\"main_thread_stall\",\"world\":")+
                std::to_string(s.world)+",\"match\":\""+s.match+"\",\"slot\":1,\"frame\":152,\"requested_ms\":250,"+
                "\"begin_us\":"+std::to_string(begin)+",\"end_us\":"+std::to_string(end)+
                ",\"presented_before\":152,\"presented_after\":"+std::to_string(presentedAfter)+
                ",\"completed_before\":"+std::to_string(completedBefore)+",\"completed_after\":"+std::to_string(completedAfter)+
                ",\"qpc_scope\":\"Sleep(250) only\",\"physicalUI\":false}";
            ba::log("MOBILE RECOVERY STALL %s",text.c_str());
            return; // Reacquire a fresh view after the ordinary owner resumes.
        }
        if(s.firstDead<0&&view.nativeValue&&*view.nativeValue==6){s.firstDead=frame;snapshot(owner,selector,frame,"native_dead_observed");}
        if(s.firstReleased<0&&s.firstDead>=0&&!view.nativePresent&&!view.oldActive&&!view.oldRetained&&!view.oldComponent){
            s.firstReleased=frame;snapshot(owner,selector,frame,"original_mobile_release_observed");}
        if(groupIntentEnabled()&&s.firstReleased>=0&&!s.groupHoldObserved&&!view.nativePresent&&!view.current)
            editGroupsDuringAbsence(owner,selector,frame);
        if(recallEnabled()&&s.firstReleased>=0&&!s.recallAbsent&&!view.nativePresent&&!view.current) {
            recallAbsentGroup(owner,selector,frame);return; // Reacquire after the original callback scope.
        }
        if(s.firstReleased>=0&&s.firstRestored<0&&view.nativePresent&&view.nativeValue&&*view.nativeValue!=6&&view.current&&view.context.admitted(view.current)){
            const auto identity=actors::resident(view.current);require(identity.entityId==11&&identity.unitType==1&&identity.armyId==1,"mobile fixture restored identity differs");
            require(ba::read<Obj>(view.current,0x158)&&!ba::read<bool>(view.current,0x160),"mobile fixture restored actor is not initialized");
            s.currentActor=std::make_unique<Root>(view.current);s.currentToken=token(view.context,view.current);require(s.currentToken,"mobile fixture restored admission token missing");
            s.firstRestored=frame;snapshot(owner,selector,frame,"original_mobile_restored_and_admitted");
            if(groupIntentEnabled()) {
                const auto expected=groupUserEditsEnabled()?std::vector<uint32_t>{}:std::vector<uint32_t>{11};
                require(s.groupHoldObserved&&s.groupEdits==groupUserEditsEnabled()&&groupIds(s.group->get())==expected,
                    "group intent restoration changed visible manual membership");
                s.groupRestored=true;groupEvidence(owner,selector,frame,"restored");
            }
        }
        if(recallEnabled()&&s.firstRestored>=0&&!s.recallRestored) {
            recallRestoredGroup(owner,selector,frame);return;
        }
        // Retain actual pre-command motion after restoration. A quiet baseline
        // is a verifier gate, never an assumption about native auto-chase.
        if(s.firstRestored>=0&&!s.freshQueued&&frame<180&&GetTickCount64()-s.lastPoseTick>=15){
            require(s.currentActor&&view.context.admitted(s.currentActor->get())&&token(view.context,s.currentActor->get())==s.currentToken,
                "mobile fixture restored baseline lost its current admitted lease");
            pose(owner,original::actualPosition(owner,s.currentActor->get()),frame,true);
        }
        if(!s.freshQueued&&frame>=180){
            require(!recallEnabled()||(s.recallAbsent&&s.recallRestored),"mobile fresh move lacks original absent/restored recall");
            require(frame<200&&s.firstDead>=0&&s.firstReleased>=0&&s.firstRestored>=0,"mobile fixture lacks a bounded real death/release/restore");
            selection::Context current(selector);const auto found=current.live.find(11);require(found!=current.live.end()&&current.admitted(found->second),"mobile fixture fresh admitted11 missing");
            const auto incarnation=token(current,found->second);require(incarnation==s.currentToken,"mobile fixture restored token changed before fresh selection");
            s.currentActor=std::make_unique<Root>(found->second);snapshot(owner,selector,frame,"before_fresh_reselection");
            selectCurrent(owner,selector,found->second,false);snapshot(owner,selector,frame,"original_fresh_reselection_established",false);
            const auto origin=original::actualPosition(owner,found->second);pose(owner,origin,frame,true);
            move(owner,selector,frame,11,original::Vec3{origin.x+16.f,origin.y,origin.z},true,&origin,s.lastPoseUs);
        }
        if(s.freshQueued&&GetTickCount64()-s.lastPoseTick>=15){
            selection::Context current(selector);require(s.currentActor&&current.admitted(s.currentActor->get())&&token(current,s.currentActor->get())==s.currentToken,
                "mobile fixture fresh observed actor lost its admitted lease");
            pose(owner,original::actualPosition(owner,s.currentActor->get()),frame,false);
        }
        if(frame>=260){
            require(s.freshQueued,"mobile fixture fresh Move missing");
            if(groupIntentEnabled()) {
                const auto expected=groupUserEditsEnabled()?std::vector<uint32_t>{}:std::vector<uint32_t>{11};
                require(s.groupHoldObserved&&s.groupEdits==groupUserEditsEnabled()&&s.groupRestored&&groupIds(s.group->get())==expected,
                    "group intent completion lost preservation/cancellation");
                groupEvidence(owner,selector,frame,"complete");
            }
            if(recallEnabled()) {
                require(s.recallAbsent&&s.recallRestored,"mobile recall completion lacks both original calls");
                recallEvidence(owner,selector,frame,"complete");
            }
            snapshot(owner,selector,frame,"mobile_observation_complete");s.passed=true;
        }
    } catch(const std::exception& error){state().failed=true;ba::log("Mobile correction smoke failed: reason=%s physicalUI=0",error.what());worker::movementFail(error.what());}
    catch(...){state().failed=true;ba::log("Mobile correction smoke failed: reason=unknown fixture exception physicalUI=0");worker::movementFail("unknown mobile fixture exception");}
}
}
static void tick() {
    if(ba::flag(L"-prediction-mobile-correction-smoke")){mobile::tick();return;}
    if(!ba::flag(L"-prediction-actor-correction-smoke"))return;
    try {
        const auto world=worker::movementWorldId();const auto match=worker::movementMatchId();
        if(!worker::movementEnabled()||!world||match.empty()){state()=State{};return;}
        auto& s=state();if(s.world!=world||s.match!=match){s=State{};s.world=world;s.match=match;}
        if(s.failed||s.passed)return;
        auto& owner=actors::state();
        if(owner.world!=world||owner.match!=match||!owner.manager||!owner.simulation)return;
        require(!owner.failed&&owner.thread==GetCurrentThreadId(),"actor fixture owner failed/changed");
        if(ba_lan::matchEnded)return;
        require(ba::unified()&&ba::community()&&ba::dedicated()&&ba::lan()&&ba_lan::originalCommandScheduling()&&
            ba_lan::running&&!ba_lan::publicMatch,"actor fixture requires negotiated prediction Custom");
        const int frame=ba::read<int>(owner.simulation->get(),0xac);
        if(ba::lanSlot()==0) {
            if(s.escapeQueued||frame<152)return;
            require(frame==152,"actor fixture missed its physical escape frame152");
            escape(owner,selectorFor(owner),frame);return;
        }
        require(ba::lanSlot()==1,"actor fixture requires exactly two human seats");
        if(frame<130)return;
        Obj selector=selectorFor(owner);
        if(!s.setup){require(frame<145,"actor fixture missed pre-death selection window");setup(owner,selector,frame);return;}
        if(s.firstDead<0) {
            Obj old=s.originalCore->get();
            if(!ba::read<bool>(old,0x160)||ba::read<Obj>(old,0x158))return;
            const auto retained=actors::units(ba::read<Obj>(owner.manager->get(),0xa0));
            require(std::find(retained.begin(),retained.end(),old)!=retained.end(),"actor fixture dead HQ was not retained by original manager");
            s.focusRetainedAtDeath=ba::read<Obj>(selector,0xa8)==old&&ba::read<int>(selector,0xa0)==4;
            s.firstDead=frame;event("original_dead_hq_retained",frame,old);return;
        }
        Obj core=coreFor(owner);if(!core)return;
        require(actors::resident(core).entityId==s.entity,"actor fixture resurrected Core identity differs");
        selection::Context admission(selector);require(admission.admitted(core),"actor fixture restored Core not admitted");
        require(!ba::read<Obj>(selector,0xa8)&&ba::read<int>(selector,0xa0)==-1,
            "actor fixture restored Core retains old focus");
        Obj selected=ba::read<Obj>(s.group->get(),0x20);void* idArgs[]={&s.entity};
        Root contains(actors::invoke(actors::method(selected,"Contains",1,0x060025b7),selected,idArgs));
        require(!actors::unbox<bool>(contains.get()),"actor fixture group retains retired HQ membership");
        actors::field(s.group->get(),"_trackedReleasedUnits",0x10);
        Obj tracked=ba::read<Obj>(s.group->get(),0x10);
        Root remembered(actors::invoke(actors::method(tracked,"Contains",1,0x060000ac,0x3782540),tracked,idArgs));
        require(!actors::unbox<bool>(remembered.get()),"actor fixture group retains released HQ identity");
        if(s.firstRestored<0){s.firstRestored=frame;event("original_hq_restored_and_admitted",frame,core);}
        if(frame>=s.firstRestored+2){s.passed=true;event("hq_selection_correction_passed",frame,core);}
    } catch(const std::exception& error) {
        state().failed=true;ba::log("Actor correction smoke failed: reason=%s physicalUI=0",error.what());
        worker::movementFail(error.what());
    }
}
}
