#pragma once
#include <iomanip>
#include <sstream>

// Passive, bounded owned-process diagnostic. Both originals run exactly once;
// original exceptions propagate. No extra event-owner lookup, timeline track
// enumeration, selection write or lifetime repair is performed here.
namespace ba_prediction_timeline_smoke {
namespace actors=ba_prediction_actors;
using ba::Obj;
using ba_local::Root;
struct Call {
    uint64_t sequence=0,world=0,update=0;
    unsigned ownerLookups=0;
    std::string match;
    Obj config=nullptr,context=nullptr;
    int frame=-1,presented=-1,completed=-1;
};
static Call*& active(){static Call* value=nullptr;return value;}
static uint64_t& sequence(){static uint64_t value=0;return value;}
static std::string pointer(Obj object){std::ostringstream out;out<<std::hex<<reinterpret_cast<uintptr_t>(object);return out.str();}
static std::string name(Obj object) {
    if(!object)return "";
    const auto klass=ba::klass(object);
    return std::string(ba::api<const char*(*)(Obj)>("il2cpp_class_get_namespace")(klass))+"."+
        ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(klass);
}
static std::string prefix(const Call& call,const char* event) {
    std::ostringstream out;
    out<<"{\"schema\":1,\"event\":"<<std::quoted(event)<<",\"sequence\":"<<call.sequence
       <<",\"world\":"<<call.world<<",\"match\":"<<std::quoted(call.match)<<",\"frame\":"<<call.frame
       <<",\"presented\":"<<call.presented<<",\"completed\":"<<call.completed<<",\"manager_update\":"<<call.update
       <<",\"tick_ms\":"<<GetTickCount64()<<",\"config\":"<<std::quoted(pointer(call.config))
       <<",\"context\":"<<std::quoted(pointer(call.context));return out.str();
}
static void emit(const Call& call,const char* event,const std::string& fields="") {
    ba::log("TIMELINE TRACE %s",(prefix(call,event)+fields+"}").c_str());
}
static void fieldType(Obj object,const char* fieldName,size_t offset,Obj expected) {
    actors::field(object,fieldName,offset);
    Obj info=ba::field(object,fieldName);
    actors::require(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
        ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(info))==expected,
        "timeline observer field type differs");
}
static uint32_t ownerId(Obj object,const char* fieldName,size_t offset) {
    Obj id=actors::type("Uncapped","Id");uint32_t alignment=0;
    actors::require(ba::api<int32_t(*)(Obj,uint32_t*)>("il2cpp_class_value_size")(id,&alignment)==4,
        "timeline observer registry Id ABI differs");
    fieldType(object,fieldName,offset,id);return ba::read<uint32_t>(object,offset);
}
static std::string unityPointer(Obj object) {
    if(!object)return "0";
    actors::require(ba::api<bool(*)(Obj,Obj)>("il2cpp_class_is_assignable_from")(
        actors::type("UnityEngine","Object"),ba::klass(object)),"timeline observer Unity object type differs");
    actors::field(object,"m_CachedPtr",0x10);return pointer(ba::read<Obj>(object,0x10));
}
static void raw(const Call& call) {
    // ENTER precedes every inspection, so a refused layout is retained rather
    // than being mistaken for proof of a particular null original input.
    emit(call,"enter");
    Obj timeline=nullptr,deps=nullptr;std::optional<uint32_t> id;
    if(call.config) {
        actors::classIs(call.config,"Uncapped","TimelineEventConfig");
        fieldType(call.config,"Timeline",0x18,actors::type("UnityEngine.Timeline","TimelineAsset"));
        timeline=ba::read<Obj>(call.config,0x18);
    }
    if(call.context) {
        actors::classIs(call.context,"Uncapped","EventContext");
        id=ownerId(call.context,"EventOwnerId",0x18);
        fieldType(call.context,"Dependencies",0x20,actors::type("Uncapped","IGameDependenciesProvider"));
        deps=ba::read<Obj>(call.context,0x20);
    }
    std::ostringstream out;
    out<<",\"config_class\":"<<std::quoted(name(call.config))<<",\"context_class\":"<<std::quoted(name(call.context))
       <<",\"timeline\":"<<std::quoted(pointer(timeline))<<",\"timeline_class\":"<<std::quoted(name(timeline))
       <<",\"dependencies\":"<<std::quoted(pointer(deps))<<",\"dependencies_class\":"<<std::quoted(name(deps))
       <<",\"registry_owner_id\":";
    if(id)out<<*id;else out<<"null";
    emit(call,"inputs",out.str());
    emit(call,"timeline_unity",",\"timeline_cached_ptr\":\""+unityPointer(timeline)+"\"");
}
static std::optional<Call> begin(Obj config,Obj context) {
    if(GetCurrentThreadId()!=ba::initialThread||!ba::flag(L"-prediction-terminal-timeline-smoke"))return std::nullopt;
    auto& owner=actors::state();
    if(!ba::flag(L"-prediction-actor-mirror-smoke")||!ba::flag(L"-prediction-held-click-smoke")||
        !owner.inUpdate||!owner.originalManagerUpdate||owner.failed||!owner.simulation||
        owner.thread!=GetCurrentThreadId()||!owner.world||owner.match.size()!=32)return std::nullopt;
    const int presented=ba::read<int>(owner.simulation->get(),0xac);
    if(presented<680||presented>750)return std::nullopt;
    actors::require(sequence()<2048,"timeline observer bounded event count exceeded");
    Call call;call.sequence=++sequence();call.world=owner.world;call.match=owner.match;
    call.update=owner.managerUpdateSerial;call.config=config;call.context=context;call.presented=presented;
    call.completed=ba::read<int>(owner.simulation->get(),0xa8);
    actors::Current current(ba::read<Obj>(owner.simulation->get(),0x148));
    call.frame=ba::read<int>(current.frame.get(),0x40);return call;
}
struct Scope {
    Call* previous;
    explicit Scope(Call& call):previous(active()){active()=&call;}
    ~Scope(){active()=previous;}
};
static void ownerReturned(const Call& call,Obj owner) {
    std::ostringstream out;
    out<<",\"owner\":"<<std::quoted(pointer(owner))<<",\"owner_class\":"<<std::quoted(name(owner));
    emit(call,"owner_lookup_return",out.str());
    if(!owner||!ba::api<bool(*)(Obj,Obj)>("il2cpp_class_is_assignable_from")(
        actors::type("Uncapped","AbstractEventOwnerComponent"),ba::klass(owner)))return;
    const auto id=ownerId(owner,"<EventOwnerId>k__BackingField",0x30);
    fieldType(owner,"_playableDirector",0x48,actors::type("UnityEngine.Playables","PlayableDirector"));
    Obj director=ba::read<Obj>(owner,0x48);
    std::ostringstream details;
    details<<",\"registry_owner_id\":"<<id<<",\"director\":"<<std::quoted(pointer(director));
    emit(call,"owner_fields",details.str());
    if(ba::klass(owner)==actors::type("Uncapped","Unit")) {
        std::ostringstream unit;
        const auto resident=actors::resident(owner);
        actors::field(owner,"_componentData",0x158);actors::field(owner,"<DeadToTheSim>k__BackingField",0x160);
        unit<<",\"entity\":"<<resident.entityId<<",\"unit_type\":"<<resident.unitType<<",\"army\":"<<resident.armyId
            <<",\"component\":"<<std::quoted(pointer(ba::read<Obj>(owner,0x158)))
            <<",\"dead\":"<<(ba::read<bool>(owner,0x160)?"true":"false");
        const auto& state=actors::state();const auto found=state.identities.find(owner);
        unit<<",\"cached_token\":"<<(found==state.identities.end()?0:found->second.incarnation);
        emit(call,"unit_fields",unit.str());
    }
    emit(call,"director_unity",",\"director_cached_ptr\":\""+unityPointer(director)+"\"");
}
static void refusal(const Call* call,const char* reason) noexcept {
    try {
        if(call){std::ostringstream out;out<<",\"reason\":"<<std::quoted(reason);emit(*call,"observer_refused",out.str());}
        else ba::log("Timeline observer refused before ENTER: reason=%s originalUnchanged=1",reason);
    } catch(...) {} // Observation must never replace the original outcome.
}
static void missingAnimator(const Call& call,Obj director) {
    // Diagnostic only: distinguish an inactive child from an absent component.
    // The actual original active-only result is still returned unchanged.
    Root animatorType(ba::api<Obj(*)(Obj)>("il2cpp_type_get_object")(
        ba::api<Obj(*)(Obj)>("il2cpp_class_get_type")(actors::type("UnityEngine","Animator"))));
    actors::require(animatorType.get(),"timeline observer Animator reflection type missing");
    Root includingInactive(ba::native<Obj(*)(Obj,Obj,bool,Obj)>(0x5085850)(director,animatorType.get(),true,nullptr));
    emit(call,"animator_including_inactive",",\"animator\":\""+pointer(includingInactive.get())+"\",\"include_inactive\":true,\"original_result_unchanged\":true");
    if(!includingInactive.get())return;
    actors::classIs(includingInactive.get(),"UnityEngine","Animator");
    Root object(ba::call(includingInactive.get(),"get_gameObject"));actors::classIs(object.get(),"UnityEngine","GameObject");
    Root self(ba::call(object.get(),"get_activeSelf")),hierarchy(ba::call(object.get(),"get_activeInHierarchy"));
    actors::classIs(self.get(),"System","Boolean");actors::classIs(hierarchy.get(),"System","Boolean");
    emit(call,"inactive_animator_object",",\"game_object\":\""+pointer(object.get())+"\",\"active_self\":"+
        (actors::unbox<bool>(self.get())?"true":"false")+",\"active_in_hierarchy\":"+
        (actors::unbox<bool>(hierarchy.get())?"true":"false"));
}
template<class Observe> static void observe(const Call* call,Observe&& action) noexcept {
    try{action();}
    catch(const std::exception& error){refusal(call,error.what());}
    catch(...){refusal(call,"unknown observation exception");}
}
}

extern "C" __declspec(dllexport) void OfflinePredictionTimelineTrigger(void* config,void* context,void* methodInfo) {
    ba::init();namespace trace=ba_prediction_timeline_smoke;
    const auto original=ba::native<void(*)(void*,void*,void*)>(0x3be4290);
    std::optional<trace::Call> call;
    try{call=trace::begin(config,context);if(call)trace::raw(*call);}
    catch(const std::exception& error){trace::refusal(call?&*call:nullptr,error.what());}
    catch(...){trace::refusal(call?&*call:nullptr,"unknown pre-call observation exception");}
    if(!call){original(config,context,methodInfo);return;}
    trace::Scope scope(*call);
    // Do not catch the original managed exception or manufacture a RETURN.
    original(config,context,methodInfo);
    trace::observe(&*call,[&](){trace::emit(*call,"return");});
}
extern "C" __declspec(dllexport) void* OfflinePredictionTimelineEventOwner(void* context,void* methodInfo) {
    ba::init();namespace trace=ba_prediction_timeline_smoke;
    const auto original=ba::native<void*(*)(void*,void*)>(0x3bd1880);
    auto* call=GetCurrentThreadId()==ba::initialThread?trace::active():nullptr;
    if(call)trace::observe(call,[&](){++call->ownerLookups;trace::emit(*call,"owner_lookup_enter",",\"lookup_ordinal\":"+
        std::to_string(call->ownerLookups)+",\"lookup_context\":\""+trace::pointer(context)+"\",\"method_info\":\""+trace::pointer(methodInfo)+"\"");});
    void* result=original(context,methodInfo);
    if(call)trace::observe(call,[&](){trace::ownerReturned(*call,result);});
    return result;
}
extern "C" __declspec(dllexport) void* OfflinePredictionTimelineAnimator(void* director,void* methodInfo) {
    ba::init();namespace trace=ba_prediction_timeline_smoke;using ba::Obj;
    const auto original=ba::native<void*(*)(void*,void*)>(0x13bee10);
    auto* call=GetCurrentThreadId()==ba::initialThread?trace::active():nullptr;
    if(call)trace::observe(call,[&](){trace::emit(*call,"animator_lookup_enter",",\"director\":\""+trace::pointer(director)+
        "\",\"method_info\":\""+trace::pointer(methodInfo)+"\"");});
    if(call&&methodInfo)trace::observe(call,[&](){std::ostringstream fields;
        fields<<",\"method_name\":"<<std::quoted(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(methodInfo));
        Obj type=ba::api<Obj(*)(Obj)>("il2cpp_method_get_declaring_type")(methodInfo);
        fields<<",\"declaring_type\":"<<std::quoted(type?ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(type):"<unresolved>");
        Obj returned=ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(methodInfo));
        fields<<",\"return_type\":"<<std::quoted(returned?ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(returned):"<unresolved>");
        trace::emit(*call,"animator_method",fields.str());});
    void* result=original(director,methodInfo); // Actual closed generic MI, once.
    if(call)trace::observe(call,[&](){trace::emit(*call,"animator_lookup_return",",\"animator\":\""+trace::pointer(result)+"\"");});
    if(call)trace::observe(call,[&](){std::ostringstream fields;fields<<",\"animator_class\":"<<std::quoted(trace::name(result));
        trace::emit(*call,"animator_class",fields.str());});
    if(call&&!result)trace::observe(call,[&](){trace::missingAnimator(*call,director);});
    return result;
}
extern "C" __declspec(dllexport) void OfflinePredictionTimelineBinding(void* director,void* key,void* target,void* methodInfo) {
    ba::init();namespace trace=ba_prediction_timeline_smoke;
    const auto original=ba::native<void(*)(void*,void*,void*,void*)>(0x50ddbe0);
    auto* call=GetCurrentThreadId()==ba::initialThread?trace::active():nullptr;
    if(call)trace::observe(call,[&](){std::ostringstream fields;fields<<",\"director\":"<<std::quoted(trace::pointer(director))
        <<",\"key\":"<<std::quoted(trace::pointer(key))<<",\"target\":"<<std::quoted(trace::pointer(target))
        <<",\"method_info\":"<<std::quoted(trace::pointer(methodInfo));
        trace::emit(*call,"binding_enter",fields.str());});
    if(call)trace::observe(call,[&](){std::ostringstream fields;fields<<",\"target_class\":"<<std::quoted(trace::name(target));
        trace::emit(*call,"binding_classes",fields.str());});
    original(director,key,target,methodInfo);
    if(call)trace::observe(call,[&](){trace::emit(*call,"binding_return");});
}
extern "C" __declspec(dllexport) void OfflinePredictionTimelinePlay(void* director,void* asset,void* methodInfo) {
    ba::init();namespace trace=ba_prediction_timeline_smoke;
    const auto original=ba::native<void(*)(void*,void*,void*)>(0x50dd870);
    auto* call=GetCurrentThreadId()==ba::initialThread?trace::active():nullptr;
    if(call)trace::observe(call,[&](){trace::emit(*call,"play_enter",",\"director\":\""+trace::pointer(director)+
        "\",\"asset\":\""+trace::pointer(asset)+"\",\"method_info\":\""+trace::pointer(methodInfo)+"\"");});
    original(director,asset,methodInfo);
    if(call)trace::observe(call,[&](){trace::emit(*call,"play_return");});
}
