// Include after prediction_selection.cpp. These optional movement hooks observe
// original callbacks; they do not synthesize input or waive retirement guards.
namespace ba_prediction_input {
namespace actors=ba_prediction_actors;
namespace selection=ba_prediction_selection;
namespace observer=ba_prediction_input_observer;
using ba::Obj;
using Kind=observer::Kind;
struct Route {Kind kind;const char* name;uint32_t token;uintptr_t rva,slot;};
static constexpr Route routes[]={
    {Kind::FocusCancel0,"FocusControlGroupCancel0",0x0600225d,0x3bf7760,0x6d4db50},
    {Kind::FocusCancel1,"FocusControlGroupCancel1",0x0600225e,0x3bf77d0,0x6d4db58},
    {Kind::FocusCancel2,"FocusControlGroupCancel2",0x0600225f,0x3bf7840,0x6d4db60},
    {Kind::FocusCancel3,"FocusControlGroupCancel3",0x06002260,0x3bf78b0,0x6d4db68},
    {Kind::FocusCancel4,"FocusControlGroupCancel4",0x06002261,0x3bf7920,0x6d4db70},
    {Kind::CancelAbility,"OnCancelActiveAbility",0x06002262,0x3bf7990,0x6d4db78},
    {Kind::QueueModifier,"OnQueueCommands",0x06002263,0x3bf79a0,0x6d4db80},
    {Kind::ForceModifier,"OnForceSelectAllUnitsOfSameType",0x06002264,0x3bf7a70,0x6d4db88},
    {Kind::Position,"OnPlayerPointerPosition",0x06002265,0x3bf7ad0,0x6d4db90},
    {Kind::Down,"OnPlayerPointerDown",0x06002266,0x3bf7d20,0x6d4db98},
    {Kind::Up,"OnPlayerPointerUp",0x06002267,0x3bf7f60,0x6d4dba0},
    {Kind::ContextDown,"OnPlayerPointerContextDown",0x06002268,0x3bf80f0,0x6d4dba8},
    {Kind::ContextUp,"OnPlayerPointerContextUp",0x06002269,0x3bf8290,0x6d4dbb0}
};
using Callback=void(*)(Obj,const void*,Obj);
static observer::Owner owner(Obj selector) {
    auto& s=actors::state();
    actors::require(ba::initialThread && GetCurrentThreadId()==ba::initialThread &&
        s.thread==GetCurrentThreadId() && !s.failed && s.world && s.groupGeneration &&
        s.world==ba_prediction_worker::movementWorldId() &&
        s.match==ba_prediction_worker::movementMatchId() && s.match.size()==32,
        "input observer lost its retained Unity owner/world/match");
    actors::classIs(selector,"Uncapped","UnitSelector");
    actors::field(selector,"_unitManager",0x40);
    actors::require(selector==selection::currentSelector() && s.manager && s.simulation &&
        ba::read<Obj>(selector,0x40)==s.manager->get() &&
        ba_prediction_movement::ownsPresentation(s.simulation->get()),
        "input observer belongs to another presentation generation");
    return {s.groupGeneration,s.world,reinterpret_cast<uintptr_t>(selector),
        reinterpret_cast<uintptr_t>(s.manager->get()),GetCurrentThreadId()};
}
static void signature(const Route& route,Obj selector,const void* context,Obj info) {
    actors::require(context && info && info==actors::method(selector,route.name,1,route.token),
        "input observer original callback MethodInfo/context differs");
    uint32_t implementation=0;
    const auto flags=ba::api<uint32_t(*)(Obj,uint32_t*)>("il2cpp_method_get_flags")(info,&implementation);
    actors::require(!(flags&0x10u) && ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
        ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(info))==actors::type("System","Void"),
        "input observer callback instance/void signature differs");
    Obj parameter=ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
        ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(info,0));
    const char* name=parameter?ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(parameter):nullptr;
    uint32_t alignment=0;
    actors::require(name && !strcmp(name,"CallbackContext") &&
        ba::api<Obj(*)(Obj)>("il2cpp_class_get_declaring_type")(parameter)==
            actors::type("UnityEngine.InputSystem","InputAction") &&
        ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(parameter) &&
        ba::api<int32_t(*)(Obj,uint32_t*)>("il2cpp_class_value_size")(parameter,&alignment)==16,
        "input observer original CallbackContext value ABI differs");
    // The pinned ORIGINAL delegate constructor reads MethodInfo+8. Prove that
    // both native dispatch pointers resolve to the installed codegen thunk;
    // a slot patch without this runtime witness cannot arm an episode.
    Obj thunk=ba::read<Obj>(ba::native<Obj>(route.slot),0);
    actors::require(thunk && ba::read<Obj>(info,0)==thunk && ba::read<Obj>(info,8)==thunk,
        "input observer callback dispatch does not match its loaded method slot");
}
struct Dispatch;
static Dispatch* currentDispatch=nullptr; // Retained Unity owner thread only.
struct Dispatch {
    const Route& route;
    Obj selector;
    const void* context;
    Obj info;
    observer::Ledger* ledger=nullptr;
    observer::Ticket ticket;
    Dispatch* previous=nullptr;
    bool entered=false;
    explicit Dispatch(const Route& value,Obj instance,const void* input,Obj method)
        :route(value),selector(instance),context(input),info(method){}
    ~Dispatch(){leave();}
    void leave() noexcept {
        if(entered && currentDispatch==this)currentDispatch=previous;
        entered=false;
    }
    bool prepare() {
        if(!selection::active())return false;
        actors::require(ba::initialThread && GetCurrentThreadId()==ba::initialThread,
            "input observer callback is outside the retained Unity thread");
        auto& state=actors::state();
        // Input may arrive before the first original presentation update has
        // established actor ownership. Forward it without arming an episode.
        if(!state.world || !state.groupGeneration || !state.manager || !state.simulation ||
           state.world!=ba_prediction_worker::movementWorldId() ||
           state.match!=ba_prediction_worker::movementMatchId() ||
           selector!=selection::currentSelector())return false;
        const auto current=owner(selector);ledger=&actors::state().inputIntent;
        signature(route,selector,context,info);
        ticket=ledger->begin(current,route.kind);
        previous=currentDispatch;currentDispatch=this;entered=true;return true;
    }
    void original(){ba::native<Callback>(route.rva)(selector,context,info);}
    void complete() {
        // The positive marker can already have failed and abandoned this
        // observer while the original callback unwound normally. Do not turn
        // its one recorded failure into a second stack/completion error.
        if(!entered)return;
        actors::require(currentDispatch==this,"input observer callback stack differs");
        if(!selection::active()){abandon();return;}
        actors::require(owner(selector)==ticket.owner,"input observer owner changed during original callback");
        const bool completed=ledger->complete(ticket);
        if(completed && ledger->accepted()) {
            actors::clickCapture(actors::state(),selector,ticket);
            ba::log("Prediction input Single observed: world=%llu generation=%llu serial=%llu entity=%u originalDown=1 originalProcess=1 completedCallback=1 dispatchVerified=1 repairAuthorized=0",
                static_cast<unsigned long long>(ticket.owner.world),
                static_cast<unsigned long long>(ticket.owner.generation),
                static_cast<unsigned long long>(ticket.serial),ba::read<uint32_t>(selector,0x128));
        }
        leave();
    }
    void abandon() noexcept {if(ledger)ledger->abandon(ticket);leave();}
    void failed(const char* reason) noexcept {
        if(ledger)ledger->discard();leave();selection::failed("input-observer",reason);
    }
    void singleDown(Obj instance,Obj method) {
        actors::require(currentDispatch==this && entered && route.kind==Kind::Down &&
            selector==instance && !method && owner(selector)==ticket.owner,
            "input observer positive Down marker has another callback owner");
        Obj boolean=actors::type("System","Boolean");
        actors::clickField(selector,"_doubleClickFirstClickReferenceUnitEntityId",0x128,actors::type("System","UInt32"),4);
        actors::clickField(selector,"_isPointerDown",0x16c,boolean,1);
        actors::clickField(selector,"_isContextPointerDown",0x16d,boolean,1);
        actors::clickField(selector,"_isDragging",0x119,boolean,1);actors::clickMode(selector);
        const auto primary=ba::read<uint8_t>(selector,0x16c),secondary=ba::read<uint8_t>(selector,0x16d);
        const auto dragging=ba::read<uint8_t>(selector,0x119);
        actors::require(primary<=1 && secondary<=1 && dragging<=1,"input observer original Boolean value differs");
        if(primary==1 && !secondary && !dragging && ba::read<int32_t>(selector,0x170)==1 &&
           ba::read<uint32_t>(selector,0x128)!=UINT32_MAX)ledger->markSingleDown(ticket);
    }
};
static void callback(Kind kind,Obj selector,const void* context,Obj info) {
    ba::init();
    Dispatch access(routes[static_cast<unsigned>(kind)],selector,context,info);
    observer::forward(access);
}
}

#define BA_INPUT_OBSERVER_EXPORT(Name,KindName) \
extern "C" __declspec(dllexport) void OfflinePredictionInput##Name(void* selector,const void* context,void* info) { \
    ba_prediction_input::callback(ba_prediction_input::Kind::KindName,selector,context,info); \
}
BA_INPUT_OBSERVER_EXPORT(FocusCancel0,FocusCancel0)
BA_INPUT_OBSERVER_EXPORT(FocusCancel1,FocusCancel1)
BA_INPUT_OBSERVER_EXPORT(FocusCancel2,FocusCancel2)
BA_INPUT_OBSERVER_EXPORT(FocusCancel3,FocusCancel3)
BA_INPUT_OBSERVER_EXPORT(FocusCancel4,FocusCancel4)
BA_INPUT_OBSERVER_EXPORT(CancelAbility,CancelAbility)
BA_INPUT_OBSERVER_EXPORT(QueueModifier,QueueModifier)
BA_INPUT_OBSERVER_EXPORT(ForceModifier,ForceModifier)
BA_INPUT_OBSERVER_EXPORT(Position,Position)
BA_INPUT_OBSERVER_EXPORT(Down,Down)
BA_INPUT_OBSERVER_EXPORT(Up,Up)
BA_INPUT_OBSERVER_EXPORT(ContextDown,ContextDown)
BA_INPUT_OBSERVER_EXPORT(ContextUp,ContextUp)
#undef BA_INPUT_OBSERVER_EXPORT

extern "C" __declspec(dllexport) void OfflinePredictionClickDownAccepted(void* selector,void* info) {
    ba::init();
    ba::native<void(*)(ba::Obj,ba::Obj)>(0x3bf4a60)(selector,info); // Exactly once, even without an observer.
    if(!ba_prediction_selection::active() || !ba::initialThread || GetCurrentThreadId()!=ba::initialThread)return;
    auto* dispatch=ba_prediction_input::currentDispatch;
    if(!dispatch || dispatch->selector!=selector || dispatch->route.kind!=ba_prediction_input::Kind::Down)return;
    try {dispatch->singleDown(selector,info);}
    catch(const std::exception& error){dispatch->failed(error.what());}
    catch(...){dispatch->failed("unknown input Single observer exception");}
}
