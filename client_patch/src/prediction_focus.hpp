#pragma once
// Movement-only, original repeat-focus coroutine prelude. Include after selection.
// Original MoveNext owns state/current/yields and every camera invocation.
#include <limits>
#include <sstream>

namespace ba_prediction_selection {
struct FocusCandidate {
    Obj actor=nullptr;
    actors::policy::ActorIdentity identity{};
    uint64_t token=0;
};
struct FocusRequest {
    uint64_t epoch=0;
    uint32_t requestedGroup=0,effectiveGroup=0;
    bool repeat=false;
    std::vector<uint32_t> sourceIds,logicalIds;
};
struct FocusSession {
    uint64_t world=0,epoch=0,iteration=0,eventSequence=0,pendingIteration=0,lastSampled=0;
    std::string match;
    std::unique_ptr<Root> selector,iterator;
    uint32_t handle=0,group=0;
    bool scheduling=false,handleReady=false,ending=false;
    std::vector<uint32_t> sourceIds,logicalIds;
    std::map<uint32_t,actors::Resident> pending;
    FocusRequest request;
};
static FocusSession& focusSession(){static auto* value=new FocusSession;return *value;}
static uint64_t& focusEpochCounter(){static uint64_t value=0;return value;}
static bool& focusStopped(){static bool value=false;return value;}
struct FocusWeakStore {std::vector<uint32_t> handles;bool failed=false;};
static FocusWeakStore& focusWeakStore(){static auto* value=new FocusWeakStore;return *value;}
static constexpr size_t maximumRetiredFocusIterators=8192; // Concurrent live weak targets, never a lifetime counter.
static void focusPruneRetired() {
    auto& store=focusWeakStore();if(store.handles.empty())return;
    actors::require(ba::initialThread && GetCurrentThreadId()==ba::initialThread,
        "focus weak retirement requires the retained Unity owner");
    auto at=store.handles.begin();
    while(at!=store.handles.end()) {
        if(ba::api<Obj(*)(uint32_t)>("il2cpp_gchandle_get_target")(*at)){++at;continue;}
        ba::api<void(*)(uint32_t)>("il2cpp_gchandle_free")(*at);at=store.handles.erase(at);
    }
}
static bool focusWasRetired(Obj iterator) {
    focusPruneRetired();
    for(auto handle:focusWeakStore().handles)
        if(ba::api<Obj(*)(uint32_t)>("il2cpp_gchandle_get_target")(handle)==iterator)return true;
    return false;
}
static void focusRememberRetired(Obj iterator) {
    actors::require(ba::initialThread && GetCurrentThreadId()==ba::initialThread,
        "focus weak identity requires the retained Unity owner");
    if(!iterator || focusWasRetired(iterator))return;
    auto& store=focusWeakStore();actors::require(store.handles.size()<maximumRetiredFocusIterators,
        "retired focus iterator weak budget exhausted");
    const auto handle=ba::api<uint32_t(*)(Obj,bool)>("il2cpp_gchandle_new_weakref")(iterator,false);
    actors::require(handle!=0,"retired focus weak identity allocation failed; restart required");
    try {
        actors::require(ba::api<Obj(*)(uint32_t)>("il2cpp_gchandle_get_target")(handle)==iterator,
            "retired focus weak identity did not retain the live target");store.handles.push_back(handle);
    } catch(...) {ba::api<void(*)(uint32_t)>("il2cpp_gchandle_free")(handle);throw;}
}
static bool focusDiagnostic(){return ba::flag(L"-prediction-mobile-focus-smoke");}
struct FocusForward {Obj iterator=nullptr,info=nullptr;};
static thread_local FocusForward* focusForward=nullptr;
struct FocusCameraContext {Obj iterator=nullptr;uint64_t epoch=0,iteration=0;bool allowChooser=true;};
static thread_local FocusCameraContext* focusCameraContext=nullptr;
static bool focusSameWorld(const FocusSession& s) {
    return active() && s.world && s.world==ba_prediction_worker::movementWorldId() &&
        s.match==ba_prediction_worker::movementMatchId();
}
static bool focusHas(const std::vector<uint32_t>& ids,uint32_t id) {
    return std::find(ids.begin(),ids.end(),id)!=ids.end();
}
static void focusGuards() {
    actors::guard(0x3bf9de0,"\x40\x53\x57\x48\x83\xec\x58\x80\x3d\x64\xf1\x25\x03\x00\x48\x8b",16);
    actors::guard(0x3bf1650,"\x48\x89\x5c\x24\x10\x48\x89\x74\x24\x18\x57\x48\x83\xec\x40\x48",16);
    actors::guard(0x32f97f0,"\x40\x57\x48\x83\xec\x50\x80\x3d\xe3\xa8\xb5\x03\x00\x48\x8b\xf9",16);
    actors::guard(0x3e9e310,"\x48\x89\x5c\x24\x08\x57\x48\x83\xec\x40\x80\x3d\x50\xc0\xfb\x02",16);
}
static void focusReference(Obj object,const char* name,size_t offset,Obj expected) {
    actors::field(object,name,offset);
    actors::require(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
        ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(ba::field(object,name)))==expected,
        "focus reference field type differs");
}
static void focusSetCache(Obj selector,Obj unit) {
    focusReference(selector,"_repeatFocusUnit",0xa8,actors::type("Uncapped","Unit"));
    ba::set<Obj>(selector,"_repeatFocusUnit",unit); // IL2CPP GC barrier, never a raw store.
}
static void focusSelectorFields(Obj selector) {
    focusReference(selector,"_focusChaseControlGroup",0xa0,actors::type("System","Int32"));
    focusReference(selector,"_repeatControlGroupFocusHandle",0xb0,actors::type("MEC","CoroutineHandle"));
    uint32_t alignment=0;actors::require(ba::api<int32_t(*)(Obj,uint32_t*)>("il2cpp_class_value_size")(
        actors::type("MEC","CoroutineHandle"),&alignment)==4,"focus handle scalar ABI differs");
}
static Obj focusIteratorClass() {
    static Obj found=nullptr;if(found)return found;
    void* cursor=nullptr;Obj owner=actors::type("Uncapped","UnitSelector");
    while(Obj nested=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_nested_types")(owner,&cursor))
        if(!strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(nested),"<FocusControlGroupRepeat>d__119")) {
            actors::require(!found,"duplicate original focus iterator class");found=nested;
        }
    actors::require(found,"original focus iterator class missing");return found;
}
static Obj focusIteratorOwner(Obj iterator) {
    actors::require(ba::initialThread && GetCurrentThreadId()==ba::initialThread &&
        GetCurrentThreadId()==ba_local::updateThread,"focus iterator requires the retained Unity owner");
    actors::require(iterator && ba::klass(iterator)==focusIteratorClass(),"focus iterator class differs");
    focusReference(iterator,"<>4__this",0x18,actors::type("Uncapped","UnitSelector"));
    actors::field(iterator,"<>1__state",0x10);actors::field(iterator,"<>2__current",0x14);
    for(const auto& field:std::vector<std::pair<const char*,const char*>>{{"<>1__state","Int32"},{"<>2__current","Single"}})
        actors::require(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(ba::field(iterator,field.first)))==actors::type("System",field.second),
            "focus iterator scalar type differs");
    Obj selector=ba::read<Obj>(iterator,0x18);actors::classIs(selector,"Uncapped","UnitSelector");
    focusGuards();focusSelectorFields(selector);return selector;
}
static Obj focusMoveInfo(Obj iterator) {
    Obj info=actors::method(iterator,"MoveNext",0,0x0600227c);
    actors::instanceSignature(info,"Boolean");
    actors::require(ba::read<Obj>(info,0)==ba::read<Obj>(ba::native<Obj>(0x6d4dc48),0),
        "focus iterator MethodInfo is not its admitted codegen hook");return info;
}
static void focusClearPending(FocusSession& s){s.pending.clear();s.pendingIteration=0;}
static void focusEvent(const char* event,const char* stage,const FocusCandidate* candidate=nullptr,
                       int originalResult=-1,const char* route="repeat");
static void focusForget() {
    actors::require(ba::initialThread && GetCurrentThreadId()==ba::initialThread,
        "focus observer roots require retained Unity owner retirement");
    auto& s=focusSession();std::exception_ptr failure;
    try{if(s.iterator)focusRememberRetired(s.iterator->get());}
    catch(...){focusWeakStore().failed=true;failure=std::current_exception();}
    focusClearPending(s);s.iterator.reset();s.selector.reset();
    s.world=0;s.match.clear();s.handleReady=false;s.scheduling=false;
    s.ending=false;
    s.sourceIds.clear();s.logicalIds.clear();
    s.request=FocusRequest{};
    if(failure)std::rethrow_exception(failure);
}
static void focusBeginWorld(Obj selector) {
    Context context(selector);focusGuards();focusSelectorFields(selector);auto& s=focusSession();
    if(!focusSameWorld(s)) {
        focusForget();s.world=context.state.world;s.match=context.state.match;
        s.iteration=0;s.epoch=0;s.selector=std::make_unique<Root>(selector);
        focusStopped()=false;
    }
    actors::require(s.selector && s.selector->get()==selector,"focus request selector differs");
}
struct FocusView {
    Context context;
    Root source,camera;
    std::unique_ptr<Root> logical;
    actors::Current current;
    std::vector<uint32_t> sourceIds,logicalIds;
    FocusView(Obj selector,uint32_t group)
        :context(selector),source(ba::read<Obj>(selector,0x90)),
         camera(ba::read<Obj>(selector,0x20)),current(ba::read<Obj>(context.state.simulation->get(),0x148)) {
        actors::require(context.state.simulation && context.state.manager &&
            GetCurrentThreadId()==ba_local::updateThread &&
            ba_prediction_movement::ownsPresentation(context.state.simulation->get()),"focus presentation owner differs");
        actors::field(selector,"_selectionSet",0x90);actors::field(selector,"_controlGroupPanel",0x38);
        Root panel(ba::read<Obj>(selector,0x38));actors::classIs(panel.get(),"Uncapped","ControlGroupPanel");
        actors::field(panel.get(),"_controlGroups",0x38);Root array(ba::read<Obj>(panel.get(),0x38));
        const auto count=array.get()?ba::read<uintptr_t>(array.get(),0x18):0;
        actors::require(count && count<=16 && group<count,"focus logical group index differs");
        actors::IntentGroup original(context.state,ba::read<Obj>(array.get(),0x20+group*sizeof(Obj)),group);
        logical=std::make_unique<Root>(original.selected.get());
        actors::field(source.get(),"_simFrames",0x48);
        actors::require(ba::read<Obj>(source.get(),0x48)==ba::read<Obj>(context.state.simulation->get(),0x148),
            "focus source frame owner differs");
        sourceIds=selectionIds(source.get());logicalIds=selectionIds(logical->get());
        focusReference(selector,"_cameraController",0x20,actors::type("Uncapped","CameraController"));
        actors::classIs(camera.get(),"Uncapped","CameraController");
    }
    bool member(uint32_t id)const{return focusHas(sourceIds,id)&&focusHas(logicalIds,id);}
    std::map<uint32_t,actors::Resident> canonical()const {
        std::map<uint32_t,actors::Resident> result;
        for(uint32_t id:sourceIds)if(member(id)) {
            const auto known=context.state.admission.entities.find(id);
            if(known!=context.state.admission.entities.end() && known->second.incarnation &&
               known->second.army==static_cast<uint32_t>(ba::lanSlot()))
                result.emplace(id,actors::Resident{{id,known->second.type,known->second.army},known->second.incarnation});
        }
        return result;
    }
    std::optional<FocusCandidate> positive(Obj actor)const {
        if(!actor || !context.admitted(actor))return std::nullopt;
        const auto& observed=context.state.identities.at(actor);const auto& id=observed.identity;
        if(!member(id.entityId))return std::nullopt;
        actors::field(actor,"_componentData",0x158);actors::field(actor,"<DeadToTheSim>k__BackingField",0x160);
        if(!ba::read<Obj>(actor,0x158) || ba::read<bool>(actor,0x160))return std::nullopt;
        const auto resident=actors::resident(actor);const auto native=current.identity(id.entityId);
        if(resident.entityId!=id.entityId || resident.unitType!=id.unitType || resident.armyId!=id.armyId ||
           !native || native->unitType!=id.unitType || native->armyId!=id.armyId ||
           !actors::confirmedInterval(context.state,ba::read<int>(current.frame.get(),0x40)) ||
           !current.retainedAlive(id.entityId))return std::nullopt;
        Obj truth=actors::method(actor,"op_Implicit",1,0x06000f04,0x508fda0);
        uint32_t implementation=0;
        actors::require(ba::api<uint32_t(*)(Obj,uint32_t*)>("il2cpp_method_get_flags")(truth,&implementation)&0x10u,
            "focus Unity truth getter is not static");
        actors::require(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(truth,0))==actors::type("UnityEngine","Object"),
            "focus Unity truth parameter differs");
        actors::require(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(truth))==actors::type("System","Boolean"),
            "focus Unity truth return type differs");
        void* args[]={actor};Root trueBox(actors::invoke(truth,nullptr,args));
        if(!actors::unbox<bool>(trueBox.get()))return std::nullopt;
        Obj activity=actors::method(actor,"get_isActiveAndEnabled",0,0x06000df6,0x5084710);
        actors::instanceSignature(activity,"Boolean");Root activeBox(actors::invoke(activity,actor));
        if(!actors::unbox<bool>(activeBox.get()))return std::nullopt;
        return FocusCandidate{actor,id,observed.incarnation};
    }
    std::optional<FocusCandidate> byId(uint32_t id)const {
        if(!member(id))return std::nullopt;
        const auto found=context.live.find(id);return found==context.live.end()?std::nullopt:positive(found->second);
    }
    std::optional<FocusCandidate> choose(const void* suppliedPosition=nullptr,Obj info=nullptr)const {
        struct Vec3 {float x,y,z;};Vec3 position{};
        if(!suppliedPosition) {
            Root transform(actors::invoke(actors::method(camera.get(),"get_CameraTarget",0,0x060015c8,0x3e9b7a0),camera.get()));
            Obj get=actors::method(transform.get(),"get_position",0,0x0600109a);
            Root boxed(actors::invoke(get,transform.get()));uint32_t alignment=0;
            actors::require(boxed.get() && ba::klass(boxed.get())==actors::type("UnityEngine","Vector3") &&
                ba::api<int32_t(*)(Obj,uint32_t*)>("il2cpp_class_value_size")(ba::klass(boxed.get()),&alignment)==12,
                "focus camera position ABI differs");
            position=actors::unbox<Vec3>(boxed.get());suppliedPosition=&position;
        }
        const auto id=ba::native<uint32_t(*)(Obj,const void*,Obj)>(0x3c646a0)(source.get(),suppliedPosition,info);
        return id==UINT32_MAX?std::nullopt:byId(id);
    }
};
static bool focusSameMembers(const std::map<uint32_t,actors::Resident>& a,const std::map<uint32_t,actors::Resident>& b) {
    if(a.size()!=b.size())return false;
    for(const auto& entry:a) {
        const auto found=b.find(entry.first);
        if(found==b.end() || found->second.incarnation!=entry.second.incarnation ||
           found->second.identity.unitType!=entry.second.identity.unitType ||
           found->second.identity.armyId!=entry.second.identity.armyId)return false;
    }
    return true;
}
static void focusSnapshot(FocusView& view,bool initial=false) {
    auto& s=focusSession();
    if(initial){s.request.sourceIds=view.sourceIds;s.request.logicalIds=view.logicalIds;}
    else {s.sourceIds=view.sourceIds;s.logicalIds=view.logicalIds;}
}
static void focusEvent(const char* event,const char* stage,const FocusCandidate* candidate,
                       int originalResult,const char* route) {
    if(!focusDiagnostic())return;
    auto& s=focusSession();uint64_t sampled=0;
    actors::require(ba_frame_timing::timestampMicros(sampled),"focus diagnostic QPC unavailable");
    actors::require(sampled>=s.lastSampled,"focus diagnostic QPC moved backwards");s.lastSampled=sampled;
    actors::require(s.eventSequence!=UINT64_MAX,"focus event sequence exhausted");++s.eventSequence;
    const bool initial=!strcmp(event,"request") || !strcmp(route,"initial");
    const bool extended=ba::flag(L"-prediction-mobile-focus-no-start-smoke");
    // Retain the qualified base receipt shape. Its first accepted request had
    // no iterator and used the repeat route; the new explicit scope separates
    // initial requests from an already running repeat iterator.
    const char* recordedRoute=initial && !strcmp(event,"request") && !extended?"repeat":route;
    const auto& sourceIds=initial?s.request.sourceIds:s.sourceIds;
    const auto& logicalIds=initial?s.request.logicalIds:s.logicalIds;
    std::ostringstream out;out<<"MOVEMENT FOCUS {\"schema\":1,\"event_sequence\":"<<s.eventSequence
        <<",\"event\":\""<<event<<"\",\"stage\":\""<<stage<<"\",\"route\":\""<<recordedRoute
        <<"\",\"world\":"<<s.world<<",\"match\":\""<<s.match<<"\",\"selector\":\""<<(s.selector?s.selector->get():nullptr)
        <<"\",\"iterator\":";
    Obj iterator=(initial?nullptr:(s.iterator?s.iterator->get():nullptr));
    if(iterator)out<<'"'<<iterator<<'"';else out<<"null";
    out<<",\"request_epoch\":"<<(initial?s.request.epoch:s.epoch)<<",\"iteration\":"<<(iterator?s.iteration:0);
    if(extended) {
        out<<",\"requested_group\":"<<(initial?s.request.requestedGroup:s.group)
            <<",\"active_epoch\":"<<(s.iterator?s.epoch:0)<<",\"active_iterator\":";
        if(s.iterator)out<<'"'<<s.iterator->get()<<'"';else out<<"null";
        out<<",\"active_handle\":";if(s.iterator && s.handleReady)out<<s.handle;else out<<"null";
    }
    out<<",\"group\":"<<(initial?s.request.effectiveGroup:s.group)<<",\"held_group\":"<<(s.selector?ba::read<int>(s.selector->get(),0xa0):-1)
        <<",\"tick_ms\":"<<GetTickCount64()<<",\"sampled_us\":"<<sampled<<",\"original_state\":";
    if(iterator)out<<ba::read<int>(iterator,0x10);else out<<"null";
    out<<",\"yield_bits\":";if(iterator)out<<ba::read<uint32_t>(iterator,0x14);else out<<"null";
    out<<",\"original_result\":";if(originalResult<0)out<<"null";else out<<(originalResult?"true":"false");
    out<<",\"source_ids\":[";bool comma=false;for(auto id:sourceIds){if(comma)out<<',';out<<id;comma=true;}
    out<<"],\"logical_ids\":[";comma=false;for(auto id:logicalIds){if(comma)out<<',';out<<id;comma=true;}
    out<<"],\"actor\":";if(candidate)out<<'"'<<candidate->actor<<'"';else out<<"null";
    out<<",\"entity\":";if(candidate)out<<candidate->identity.entityId;else out<<"null";
    out<<",\"unit_type\":";if(candidate)out<<candidate->identity.unitType;else out<<"null";
    out<<",\"army\":";if(candidate)out<<candidate->identity.armyId;else out<<"null";
    out<<",\"incarnation\":";if(candidate)out<<candidate->token;else out<<"null";
    out<<",\"member\":"<<(candidate?"true":"false")<<",\"initialized\":"<<(candidate?"true":"false")
        <<",\"current_lease\":"<<(candidate?"true":"false")<<'}';
    ba::log("%s",out.str().c_str());
}
static uint32_t focusCandidate(Obj set,const void* position,Obj info) {
    if(!active())return ba::native<uint32_t(*)(Obj,const void*,Obj)>(0x3c646a0)(set,position,info);
    if(focusCameraContext && (!focusCameraContext->allowChooser || focusSession().ending))return UINT32_MAX;
    try {
        auto& s=focusSession();Obj selector=currentSelector();
        actors::require(focusSameWorld(s) && s.selector && s.selector->get()==selector,
            "focus chooser has no accepted request epoch");
        const bool initial=!focusCameraContext;
        actors::require(!initial || s.request.epoch,"focus initial chooser has no accepted request");
        FocusView view(selector,initial?s.request.effectiveGroup:s.group);actors::require(view.source.get()==set,"focus chooser passed set owner differs");
        focusSnapshot(view,initial);const auto candidate=view.choose(position,info);
        return candidate?candidate->identity.entityId:UINT32_MAX;
    } catch(const std::exception& error){failed("focus",error.what());}
    catch(...){failed("focus","unknown focus chooser exception");}
    return UINT32_MAX;
}
static bool focusBinding(Obj selector) {
    auto& s=focusSession();
    return ba::initialThread && GetCurrentThreadId()==ba::initialThread && GetCurrentThreadId()==ba_local::updateThread &&
        focusSameWorld(s) && s.selector && s.selector->get()==selector && s.iterator &&
        s.epoch && (s.scheduling || (s.handleReady && ba::read<uint32_t>(selector,0xb0)==s.handle));
}
static uint64_t focusPendingIteration(Obj selector) {
    auto& s=focusSession();return focusBinding(selector) && ba::read<int>(selector,0xa0)>=0?s.pendingIteration:0;
}
static uint64_t focusPendingEpoch(Obj selector){return focusPendingIteration(selector)?focusSession().epoch:0;}
static Obj focusPendingIterator(Obj selector){return focusPendingIteration(selector)?focusSession().iterator->get():nullptr;}
static void focusClearInactive() {
    focusPruneRetired();auto& s=focusSession();if(!s.world || focusSameWorld(s))return;
    actors::require(ba::initialThread && GetCurrentThreadId()==ba::initialThread,
        "focus root retirement requires the retained Unity owner");
    try{focusEvent("terminal","world_retired");}catch(...){/* no diagnostic retry */}
    focusForget();
}
static bool focusOriginalNext(Obj iterator) {
    Obj info=focusMoveInfo(iterator);FocusForward forwarding{iterator,info};
    actors::require(!focusForward,"recursive focus original delegation");focusForward=&forwarding;
    try {
        Root boxed(actors::invoke(info,iterator));focusForward=nullptr;
        actors::require(boxed.get() && ba::klass(boxed.get())==actors::type("System","Boolean"),
            "focus original MoveNext return ABI differs");return actors::unbox<bool>(boxed.get());
    } catch(...) {focusForward=nullptr;throw;}
}
static Obj focusStartInfo() {
    static Obj found=nullptr;if(found)return found;
    Obj klass=actors::type("MEC","Timing");void* cursor=nullptr;
    while(Obj info=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(klass,&cursor)) {
        if(ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_token")(info)!=0x060000a8 ||
           strcmp(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(info),"RunCoroutine") ||
           ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(info)!=1)continue;
        actors::require(!found && ba::read<Obj>(info,0)==ba::native<Obj>(0x32f97f0),"original focus scheduler overload differs");
        uint32_t flags=0;actors::require(ba::api<uint32_t(*)(Obj,uint32_t*)>("il2cpp_method_get_flags")(info,&flags)&0x10u,
            "original focus scheduler is not static");
        actors::require(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(info))==actors::type("MEC","CoroutineHandle"),
            "original focus scheduler return type differs");
        Obj parameter=ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(info,0));
        actors::require(parameter && ba::api<bool(*)(Obj,Obj)>("il2cpp_class_is_assignable_from")(parameter,focusIteratorClass()),
            "original focus scheduler iterator parameter differs");found=info;
    }
    actors::require(found,"original focus scheduler unavailable");return found;
}
static void focusFailed(const char* where,const char* reason) noexcept {
    if(!ba::initialThread || GetCurrentThreadId()!=ba::initialThread) {
        focusForward=nullptr;focusCameraContext=nullptr;failed(where,reason);return;
    }
    focusStopped()=true;
    try{focusEvent("terminal","failed");}catch(...){/* failed clock must not cause a diagnostic retry */}
    try{focusForget();}catch(...){ba::log("Focus weak lifetime retirement failed; adaptation cannot resume");}
    focusForward=nullptr;focusCameraContext=nullptr;failed(where,reason);
}
}

extern "C" __declspec(dllexport) bool OfflinePredictionFocusActuate(void* selector,int32_t group,bool repeat) {
    ba::init();using namespace ba_prediction_selection;
    // The original CALL's third argument was null MethodInfo, not an additive flag.
    if(!active())return ba::native<bool(*)(Obj,int32_t,Obj)>(0x3bf1650)(selector,group,nullptr);
    try {
        Context context(selector);actors::require(group>=0,"negative focus request group");
        Obj method=actors::method(selector,"ActuateControlGroup",1,0x0600220f,0x3bf1650);
        actors::instanceSignature(method,"Boolean","Int32");void* args[]={&group};Root result(actors::invoke(method,selector,args));
        const bool accepted=actors::unbox<bool>(result.get());if(!accepted)return false;
        focusBeginWorld(selector);auto& s=focusSession();
        const int held=ba::read<int>(selector,0xa0);actors::require(held>=-1,"focus held group differs");
        // Original Actuate can return true without a selection scope while a
        // group is already held. Original Focus then skips RunCoroutine. Keep
        // this initial request separate from the still-owned repeat iterator.
        FocusRequest request;request.requestedGroup=static_cast<uint32_t>(group);
        request.effectiveGroup=held<0?request.requestedGroup:static_cast<uint32_t>(held);request.repeat=repeat;
        FocusView view(selector,request.effectiveGroup);
        request.sourceIds=view.sourceIds;request.logicalIds=view.logicalIds;
        auto& next=focusEpochCounter();actors::require(next!=UINT64_MAX,"focus request epoch exhausted");
        request.epoch=++next;s.request=std::move(request);
        if(repeat || ba::flag(L"-prediction-mobile-focus-no-start-smoke"))
            focusEvent("request",repeat?"accepted_repeat":"accepted_once",nullptr,-1,"initial");
        return true;
    } catch(const std::exception& error){focusFailed("focus_actuate",error.what());}
    catch(...){focusFailed("focus_actuate","unknown focus request exception");}
    return false;
}

extern "C" __declspec(dllexport) uint32_t OfflinePredictionStartRepeatFocus(void* iterator,void* info) {
    ba::init();using namespace ba_prediction_selection;
    if(!active())return ba::native<uint32_t(*)(Obj,Obj)>(0x32f97f0)(iterator,info);
    try {
        Obj selector=focusIteratorOwner(iterator);auto& s=focusSession();
        actors::require(focusSameWorld(s) && s.selector && s.selector->get()==selector && s.request.epoch && s.request.repeat,
            "focus scheduler has no accepted repeat epoch");
        actors::require(ba::read<int>(selector,0xa0)>=0 &&
            static_cast<uint32_t>(ba::read<int>(selector,0xa0))==s.request.requestedGroup,
            "focus scheduler did not observe the original requested held group");
        actors::require(ba::read<int>(iterator,0x10)==0,"focus scheduler received an already started iterator");
        actors::require(!focusWeakStore().failed,"focus weak lifetime guard failed; restart required");
        if(s.iterator && s.iterator->get()!=iterator) {
            focusEvent("terminal","superseded");focusRememberRetired(s.iterator->get());
        }
        focusPruneRetired();actors::require(focusWeakStore().handles.size()<maximumRetiredFocusIterators,
            "retired focus iterator weak budget exhausted before registration");
        s.iterator=std::make_unique<Root>(iterator);s.iteration=0;focusClearPending(s);
        s.epoch=s.request.epoch;s.group=s.request.requestedGroup;
        s.sourceIds=s.request.sourceIds;s.logicalIds=s.request.logicalIds;
        s.request=FocusRequest{}; // Only an actual Start consumes this request.
        actors::require(s.iterator->get()==iterator,"focus iterator GC root allocation failed");
        actors::require(!focusWasRetired(iterator),"a live retired focus iterator cannot be registered again");
        s.scheduling=true;s.handleReady=false;s.ending=false;
        focusEvent("start","scheduling");void* args[]={iterator};Root boxed(actors::invoke(focusStartInfo(),nullptr,args));
        uint32_t alignment=0;
        actors::require(focusSameWorld(s) && boxed.get() && ba::klass(boxed.get())==actors::type("MEC","CoroutineHandle") &&
            ba::api<int32_t(*)(Obj,uint32_t*)>("il2cpp_class_value_size")(ba::klass(boxed.get()),&alignment)==4,
            "focus scheduler handle/world ABI differs");
        s.handle=actors::unbox<uint32_t>(boxed.get());s.scheduling=false;s.handleReady=true;
        focusEvent("scheduled","returned");return s.handle;
    } catch(const std::exception& error){focusFailed("focus_start",error.what());}
    catch(...){focusFailed("focus_start","unknown focus scheduler exception");}
    return 0;
}

extern "C" __declspec(dllexport) bool OfflinePredictionRepeatFocusNext(void* iterator,void* info) {
    using namespace ba_prediction_selection;
    // Only this exact runtime_invoke pair may enter the untouched original body.
    // Its managed exception unwinds directly into IL2CPP's invocation boundary.
    if(focusForward && focusForward->iterator==iterator && focusForward->info==info)
        return ba::native<bool(*)(Obj,Obj)>(0x3bf9de0)(iterator,info);
    ba::init();auto& s=focusSession();
    try {
        if(focusWeakStore().failed)return false; // Lost lifetime proof cannot authorize an old actor callback.
        if(focusWasRetired(iterator))return false;
        if(s.iterator && s.iterator->get()==iterator && s.world && !focusSameWorld(s)) {
            actors::require(ba::initialThread && GetCurrentThreadId()==ba::initialThread,
                "focus retirement callback has another owner thread");
            focusClearPending(s);try{focusEvent("terminal","world_retired");}catch(...){/* no diagnostic retry */}
            focusForget();return false;
        }
    } catch(const std::exception& error){focusFailed("focus_lifetime",error.what());return false;}
    catch(...){focusFailed("focus_lifetime","unknown focus lifetime guard failure");return false;}
    if(!active()) {
        return ba::native<bool(*)(Obj,Obj)>(0x3bf9de0)(iterator,info);
    }
    try {
        Obj selector=focusIteratorOwner(iterator);
        // A superseded/retired iterator must never adopt a later handle/epoch.
        if(!s.iterator || s.iterator->get()!=iterator)return false;
        if(!focusBinding(selector)) {
            focusClearPending(s);focusEvent("terminal","superseded");focusForget();return false;
        }
        actors::require(s.iteration!=UINT64_MAX,"focus iteration ordinal exhausted");++s.iteration;
        actors::require(!focusCameraContext,"recursive focus coroutine callback");
        FocusCameraContext cameraContext{iterator,s.epoch,s.iteration};focusCameraContext=&cameraContext;
        const int held=ba::read<int>(selector,0xa0);const char* stage="delegate";
        std::optional<FocusCandidate> candidate;
        if(held<0 || s.ending) {
            s.ending=true;cameraContext.allowChooser=false;focusClearPending(s);
            if(held<0){focusEvent("cancel_observed","cancel_delegate");stage="cancel_delegate";}
            else {focusEvent("ending_observed","ending_delegate");stage="ending_delegate";}
        }
        else {
            FocusView view(selector,s.group);focusSnapshot(view);const auto members=view.canonical();
            const bool changed=!s.pending.empty() && !focusSameMembers(s.pending,members);
            if(!changed)candidate=view.positive(ba::read<Obj>(selector,0xa8));
            if(!candidate && !changed)candidate=view.choose();
            if(candidate) {
                if(ba::read<Obj>(selector,0xa8)!=candidate->actor) {
                    focusSetCache(selector,candidate->actor);stage="refind";
                }
                focusClearPending(s);
            } else {
                focusSetCache(selector,nullptr);
                const int originalState=ba::read<int>(iterator,0x10);
                const uint32_t yield=ba::read<uint32_t>(iterator,0x14);
                if(!changed && !members.empty() && (originalState==1 || originalState==2) && yield==0xff800000u) {
                    s.pending=members;s.pendingIteration=s.iteration;
                    focusEvent("iteration","waiting_absent");focusCameraContext=nullptr;return true;
                }
                s.ending=true;cameraContext.allowChooser=false;
                focusClearPending(s); // Original owns its ordinary eventual false exit.
            }
        }
        const bool result=focusOriginalNext(iterator);focusCameraContext=nullptr;
        actors::require(focusSameWorld(s) && s.epoch==cameraContext.epoch && s.iterator && s.iterator->get()==iterator,
            "focus original callback retired or superseded the owned epoch");
        focusEvent("iteration",stage,candidate?&*candidate:nullptr,result?1:0);
        if(!result){focusClearPending(s);focusEvent("terminal","original_false",nullptr,0);focusForget();}
        return result;
    } catch(const std::exception& error){focusFailed("focus_next",error.what());}
    catch(...){focusFailed("focus_next","unknown focus coroutine exception");}
    return false;
}

extern "C" __declspec(dllexport) void OfflinePredictionControlGroupCamera(void* camera,void* actor,void* info) {
    ba::init();using namespace ba_prediction_selection;
    if(!active()){ba::native<void(*)(Obj,Obj,Obj)>(0x3e9e310)(camera,actor,info);return;}
    try {
        auto& s=focusSession();actors::require(focusSameWorld(s) && s.selector,"focus camera request has no epoch");
        Root actorRoot(actor);
        const bool repeat=focusCameraContext!=nullptr;
        if(repeat)actors::require(!s.ending && focusCameraContext->allowChooser && focusBinding(s.selector->get()) &&
            focusCameraContext->iterator==s.iterator->get() && focusCameraContext->epoch==s.epoch &&
            focusCameraContext->iteration==s.iteration && ba::read<int>(s.selector->get(),0xa0)>=0,
            "focus camera iterator/epoch was cancelled or superseded");
        actors::require(repeat || s.request.epoch,"focus initial camera has no accepted request");
        FocusView view(s.selector->get(),repeat?s.group:s.request.effectiveGroup);focusSnapshot(view,!repeat);
        actors::require(camera==view.camera.get(),"focus camera belongs to another selector");
        const auto candidate=view.positive(actor);actors::require(candidate.has_value(),"focus camera target is not a current admitted logical member");
        const uint64_t epoch=repeat?s.epoch:s.request.epoch;Obj selector=s.selector->get();
        const char* route=repeat?"repeat":"initial";
        focusEvent("camera","requested",&*candidate,-1,route);
        Obj method=actors::method(camera,"FocusOnUnit",1,0x060015ec,0x3e9e310);
        actors::instanceSignature(method,"Void");
        actors::require(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(method,0))==actors::type("Uncapped","Unit"),
            "focus camera Unit parameter differs");
        void* args[]={actor};actors::invoke(method,camera,args);
        actors::require(focusSameWorld(s) && (repeat?s.epoch:s.request.epoch)==epoch && s.selector && s.selector->get()==selector,
            "focus camera callback retired or superseded the owned epoch");
        focusEvent("camera","returned",&*candidate,-1,route);
    } catch(const std::exception& error){focusFailed("focus_camera",error.what());}
    catch(...){focusFailed("focus_camera","unknown focus camera exception");}
}
