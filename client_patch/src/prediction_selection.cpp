// Optional movement recipe CALL shims. Include after prediction_actor_repair.
// Original scoped mutations and notification ordering remain the owners.
namespace ba_prediction_selection {
namespace actors=ba_prediction_actors;
using ba::Obj;
using ba_local::Root;
static bool active() {
    return ba_prediction_worker::movementEnabled() && ba_prediction_worker::movementWorldId() &&
        !ba_prediction_worker::movementMatchId().empty();
}
static void notice() {
    static ULONGLONG previous=0;const auto now=GetTickCount64();
    if(!previous || now-previous>=2500) {
        previous=now;ba_match_loading::hint("Unit awaiting server confirmation. Select it again shortly.");
    }
}
static std::vector<uint32_t> selectionIds(Obj selection) {
    actors::classIs(selection,"Uncapped.Collections","UnitSelectionSet");
    actors::field(selection,"_allUnits",0x18);
    Obj led=ba::read<Obj>(selection,0x18);actors::require(led,"selection all-unit set missing");
    actors::field(led,"<Entities>k__BackingField",0x10);
    return actors::ids(ba::read<Obj>(led,0x10));
}
struct Context {
    actors::State& state;
    Obj selector;
    std::map<uint32_t,Obj> live;
    explicit Context(Obj value):state(actors::state()),selector(value) {
        actors::require(ba::initialThread && GetCurrentThreadId()==ba::initialThread,
            "selection admission requires the retained Unity main thread");
        actors::classIs(selector,"Uncapped","UnitSelector");
        actors::field(selector,"_unitManager",0x40);
        actors::require(!state.failed && state.world && state.world==ba_prediction_worker::movementWorldId() &&
            state.match==ba_prediction_worker::movementMatchId() && state.thread==GetCurrentThreadId() &&
            state.manager && state.simulation && state.manager->get()==ba::read<Obj>(selector,0x40),
            "selection admission owner/generation unavailable");
        state.admission=ba_prediction_worker::movementAdmission();
        for(Obj unit:actors::units(ba::read<Obj>(state.manager->get(),0x10))) {
            const auto identity=actors::resident(unit);
            actors::require(live.emplace(identity.entityId,unit).second,"duplicate active actor ID during selection");
        }
    }
    bool admitted(Obj unit)const {
        if(!unit)return false;
        const auto observed=state.identities.find(unit);
        if(observed==state.identities.end() || !observed->second.incarnation)return false;
        const auto& identity=observed->second.identity;
        const auto found=live.find(identity.entityId);
        return found!=live.end() && found->second==unit &&
            identity.armyId==static_cast<uint32_t>(ba::lanSlot()) &&
            actors::confirmedToken(state,identity)==observed->second.incarnation;
    }
    bool admitted(uint32_t id)const {
        const auto found=live.find(id);return found!=live.end() && admitted(found->second);
    }
};
static Obj currentSelector() {
    return ba::get<Obj>(ba::owner,"<UnitSelector>k__BackingField");
}
static Obj helperSelector(Obj helper) {
    actors::field(helper,"_unitSelector",0x20);
    actors::field(helper,"_unitManager",0x28);
    Obj selector=ba::read<Obj>(helper,0x20);
    actors::classIs(selector,"Uncapped","UnitSelector");
    actors::field(selector,"_selectionChangeHelper",0x80);
    actors::require(selector==currentSelector() && ba::read<Obj>(selector,0x80)==helper &&
        ba::read<Obj>(selector,0x40)==ba::read<Obj>(helper,0x28),"selection helper belongs to another owner");
    return selector;
}
static void declineCasters(Obj set) noexcept {
    // The original caller forwards this IEnumerable to its command builder.
    // Cancel through original set removals instead of introducing a null set
    // on an error path that originally returned a concrete casting set.
    try {
        Obj remove=actors::method(set,"Remove",1,0x060025ab,0x3c66610);
        for(uint32_t id:selectionIds(set)){void* args[]={&id};actors::invoke(remove,set,args);}
    } catch(...) {ba::log("Prediction failed caster cleanup unavailable; transport already stopped");}
}
static void failed(const char* where,const char* reason) noexcept {
    ba::log("Prediction selection admission failed: where=%s reason=%s",where,reason);
    ba_prediction_worker::movementFail(reason);
}
}

extern "C" __declspec(dllexport) void OfflinePredictionSelectionCommit(void* helper,void* actualClass) {
    ba::init();using namespace ba_prediction_selection;
    // The patched window precedes the MethodInfo load. RDX is the real class,
    // not MethodInfo; recover BOTH original vtable fields before helper work.
    const auto original=reinterpret_cast<void(*)(Obj,Obj)>(ba::read<Obj>(actualClass,0x188));
    Obj info=ba::read<Obj>(actualClass,0x190);
    if(!active() || reinterpret_cast<void*>(original)!=ba::native<void*>(0x3bf95f0)) {
        original(helper,info);return;
    }
    try {
        actors::require(actualClass==ba::klass(helper),"selection virtual dispatch class differs");
        Obj selector=helperSelector(helper);Context context(selector);
        actors::require(ba::read<bool>(helper,0x10),"selection commit is outside its original suspension");
        actors::field(selector,"_selectionSet",0x90);
        Obj remove=actors::method(selector,"RemoveFromSelection",1,0x06002215,0x3bf25a0);
        unsigned denied=0;
        for(uint32_t id:selectionIds(ba::read<Obj>(selector,0x90)))if(!context.admitted(id)) {
            void* args[]={&id};actors::invoke(remove,selector,args);++denied;
        }
        if(denied) {
            ba::log("Prediction selection filtered: denied=%u confirmedFrame=%d originalScope=1 deferredIntent=0",denied,context.state.admission.frame);
            notice();
        }
        // Invoke the exact original callback through IL2CPP's managed boundary.
        // A direct C++ call can throw its private exception wrapper, leaving
        // only an "unknown selection exception" at this exported shim. The
        // runtime boundary retains the original exception/stack diagnostic.
        // This is OnRaiseEvent, not the surrounding EndSuspend call site;
        // EndSuspend still owns its ordinary reset/finally after we return.
        actors::require(info==actors::method(helper,"OnRaiseEvent",0,0x06002274,0x3bf95f0),
            "selection callback MethodInfo differs from original virtual target");
        uint32_t implementationFlags=0;
        const auto flags=ba::api<uint32_t(*)(Obj,uint32_t*)>("il2cpp_method_get_flags")(info,&implementationFlags);
        actors::require(!(flags&0x10u) && ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(info))==actors::type("System","Void"),
            "selection callback instance/void signature differs");
        actors::invoke(info,helper); // Exactly once; never retry a throwing callback.
    } catch(const std::exception& error) {failed("commit",error.what());}
    catch(...) {failed("commit","unknown selection exception");}
}

extern "C" __declspec(dllexport) void* OfflinePredictionSelectionConfirmer(void* helper,void* info) {
    ba::init();using namespace ba_prediction_selection;
    Obj result=ba::native<Obj(*)(Obj,Obj)>(0x3bf9810)(helper,info);
    if(!active() || !result)return result;
    try {
        Context context(helperSelector(helper));
        if(context.admitted(result))return result;
        ba::log("Prediction selection confirmer declined: actor=%p confirmedFrame=%d",result,context.state.admission.frame);
        notice();return nullptr;
    } catch(const std::exception& error) {failed("confirmer",error.what());}
    catch(...) {failed("confirmer","unknown confirmer exception");}
    return nullptr;
}

extern "C" __declspec(dllexport) void* OfflinePredictionCastingSet(void* selector,const void* position,void* source,bool append,void* info) {
    ba::init();using namespace ba_prediction_selection;
    Obj result=ba::native<Obj(*)(Obj,const void*,Obj,bool,Obj)>(0x3bf35f0)(selector,position,source,append,info);
    if(!active() || !result)return result;
    try {
        Context context(selector);actors::field(selector,"_castingSet",0x98);
        actors::require(result==ba::read<Obj>(selector,0x98),"original casting set owner differs");
        Obj remove=actors::method(result,"Remove",1,0x060025ab,0x3c66610);
        unsigned denied=0;
        for(uint32_t id:selectionIds(result))if(!context.admitted(id)) {
            void* args[]={&id};actors::invoke(remove,result,args);++denied;
        }
        if(denied) {
            ba::log("Prediction casters filtered before command creation: denied=%u confirmedFrame=%d deferredIntent=0",denied,context.state.admission.frame);
            notice();
        }
        return result;
    } catch(const std::exception& error) {failed("casters",error.what());}
    catch(...) {failed("casters","unknown caster exception");}
    declineCasters(result);return result;
}

extern "C" __declspec(dllexport) uint32_t OfflinePredictionControlGroupFocus(void* set,const void* position,void* info) {
    ba::init();using namespace ba_prediction_selection;
    const auto id=ba::native<uint32_t(*)(Obj,const void*,Obj)>(0x3c646a0)(set,position,info);
    if(!active() || id==UINT32_MAX)return id;
    try {
        Context context(currentSelector());if(context.admitted(id))return id;
        notice();return UINT32_MAX;
    } catch(const std::exception& error) {failed("focus",error.what());}
    catch(...) {failed("focus","unknown focus exception");}
    return UINT32_MAX;
}
