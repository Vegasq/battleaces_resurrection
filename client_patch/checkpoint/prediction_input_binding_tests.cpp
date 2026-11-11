// Authored fake host for the ACTUAL input observer adapter. No game/DLL loads.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <array>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <functional>
#include <iostream>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
#include "../src/prediction_input_observer.hpp"

namespace host {
using Obj=void*;
using Callback=void(*)(Obj,const void*,Obj);
using Memory=std::array<unsigned char,0x200>;
struct Class;
struct Field {size_t offset=0,size=0;Class* type=nullptr;};
struct Method {
    Memory bytes{};const char* name=nullptr;uint32_t token=0,flags=0;
    Class* result=nullptr;Class* parameter=nullptr;uint32_t count=1;
};
struct Class {
    std::string name;Class* declaring=nullptr;bool value=false;int32_t size=0;
    std::map<std::string,Field> fields;std::vector<Method*> methods;
};
struct Node {Memory bytes{};Class* klass=nullptr;};
struct Call {size_t route=0;Obj selector=nullptr;const void* context=nullptr;Obj info=nullptr;};
struct OriginalError {int tag=0;}; // Deliberately not derived from std::exception.
struct Root {Obj value=nullptr;explicit Root(Obj p):value(p){}Obj get()const{return value;}};
struct alignas(8) Context {std::array<unsigned char,16> bytes{};};
static_assert(sizeof(Context)==16 && alignof(Context)==8,"authored context ABI");
static std::map<std::pair<std::string,std::string>,std::unique_ptr<Class>> classes;
static std::map<Obj,Memory*> memories;
static std::array<Method,13> methods;
static std::array<Node,13> slots;
static Node selector,otherSelector,manager,simulation;
static Context context;
static std::array<unsigned,13> originals{};
static std::vector<Call> calls;
static std::vector<std::string> logs;
static std::function<void(size_t)> originalBody;
static std::function<void(Obj,Obj)> processBody;
static Obj selected=nullptr;
static bool active=true,stopped=false,presentationOwned=true;
static uint64_t world=91;
static std::string match(32,'a'),lastFailure;
static unsigned failures=0,processCalls=0;
static Obj processSelector=nullptr,processInfo=nullptr;
static constexpr std::array<uintptr_t,13> originalRvas{{
    0x3bf7760,0x3bf77d0,0x3bf7840,0x3bf78b0,0x3bf7920,0x3bf7990,
    0x3bf79a0,0x3bf7a70,0x3bf7ad0,0x3bf7d20,0x3bf7f60,0x3bf80f0,0x3bf8290}};
static constexpr std::array<const char*,13> names{{
    "FocusControlGroupCancel0","FocusControlGroupCancel1","FocusControlGroupCancel2",
    "FocusControlGroupCancel3","FocusControlGroupCancel4","OnCancelActiveAbility",
    "OnQueueCommands","OnForceSelectAllUnitsOfSameType","OnPlayerPointerPosition",
    "OnPlayerPointerDown","OnPlayerPointerUp","OnPlayerPointerContextDown","OnPlayerPointerContextUp"}};
static void check(bool value,const char* reason){if(!value)throw std::runtime_error(reason);}
static Class* type(const char* space,const char* name) {
    auto& p=classes[{space,name}];if(!p){p=std::make_unique<Class>();p->name=name;}return p.get();
}
template<class T>static void put(Obj object,size_t offset,T value) {
    auto* memory=memories.at(object);check(offset+sizeof(T)<=memory->size(),"authored write bound");
    memcpy(memory->data()+offset,&value,sizeof(T));
}
template<class T>static T read(Obj object,size_t offset) {
    auto* memory=memories.at(object);check(offset+sizeof(T)<=memory->size(),"authored read bound");
    T value{};memcpy(&value,memory->data()+offset,sizeof(T));return value;
}
template<size_t Index>static void original(Obj instance,const void* input,Obj info) {
    ++originals[Index];calls.push_back({Index,instance,input,info});if(originalBody)originalBody(Index);
}
static const std::array<Callback,13> originalCallbacks{{
    &original<0>,&original<1>,&original<2>,&original<3>,&original<4>,&original<5>,
    &original<6>,&original<7>,&original<8>,&original<9>,&original<10>,&original<11>,&original<12>}};
static void process(Obj instance,Obj info) {
    ++processCalls;processSelector=instance;processInfo=info;
    if(processBody)processBody(instance,info);
}
static uint32_t flags(Obj info,uint32_t* implementation) {
    *implementation=0;return static_cast<Method*>(info)->flags;
}
static Obj result(Obj info){return static_cast<Method*>(info)->result;}
static Obj parameter(Obj info,uint32_t index) {
    check(index==0,"authored parameter index");return static_cast<Method*>(info)->parameter;
}
static Obj fromType(Obj value){return value;}
static const char* className(Obj value){return static_cast<Class*>(value)->name.c_str();}
static Obj declaring(Obj value){return static_cast<Class*>(value)->declaring;}
static bool isValue(Obj value){return static_cast<Class*>(value)->value;}
static int32_t valueSize(Obj value,uint32_t* alignment){*alignment=8;return static_cast<Class*>(value)->size;}
}
namespace ba {
using Obj=void*;
static DWORD initialThread=0;
static void init(){}
template<class T>T read(Obj value,size_t offset){return host::read<T>(value,offset);}
static void log(const char* format,...) {
    char text[2048];va_list args;va_start(args,format);vsnprintf(text,sizeof(text),format,args);va_end(args);
    host::logs.emplace_back(text);
}
template<class T>T api(const char* name) {
    if(!strcmp(name,"il2cpp_method_get_flags"))return reinterpret_cast<T>(&host::flags);
    if(!strcmp(name,"il2cpp_method_get_return_type"))return reinterpret_cast<T>(&host::result);
    if(!strcmp(name,"il2cpp_method_get_param"))return reinterpret_cast<T>(&host::parameter);
    if(!strcmp(name,"il2cpp_class_from_type"))return reinterpret_cast<T>(&host::fromType);
    if(!strcmp(name,"il2cpp_class_get_name"))return reinterpret_cast<T>(&host::className);
    if(!strcmp(name,"il2cpp_class_get_declaring_type"))return reinterpret_cast<T>(&host::declaring);
    if(!strcmp(name,"il2cpp_class_is_valuetype"))return reinterpret_cast<T>(&host::isValue);
    if(!strcmp(name,"il2cpp_class_value_size"))return reinterpret_cast<T>(&host::valueSize);
    throw std::runtime_error("unexpected authored input metadata API");
}
template<class T>T native(uintptr_t rva) {
    if(rva==0x3bf4a60)return reinterpret_cast<T>(&host::process);
    for(size_t i=0;i<host::originalRvas.size();++i) {
        if(rva==host::originalRvas[i])return reinterpret_cast<T>(host::originalCallbacks[i]);
        if(rva==0x6d4db50+i*8)return reinterpret_cast<T>(&host::slots[i]);
    }
    throw std::runtime_error("unexpected authored input native RVA");
}
}
namespace ba_prediction_worker {
static uint64_t movementWorldId(){return host::world;}
static const std::string& movementMatchId(){return host::match;}
}
namespace ba_prediction_movement {
static bool ownsPresentation(void* value){return host::presentationOwned && value==&host::simulation;}
}
namespace ba_prediction_actors {
using ba::Obj;
struct State {
    DWORD thread=0;bool failed=false;uint64_t world=0,groupGeneration=0;
    std::string match;std::unique_ptr<host::Root> manager,simulation;
    ba_prediction_input_observer::Ledger inputIntent;
};
static State& state(){static State value;return value;}
static void require(bool value,const char* reason){host::check(value,reason);}
static Obj type(const char* space,const char* name){return host::type(space,name);}
static void classIs(Obj value,const char* space,const char* name) {
    require(value && static_cast<host::Node*>(value)->klass==type(space,name),"authored input owner class differs");
}
static void field(Obj value,const char* name,size_t offset) {
    const auto& fields=static_cast<host::Node*>(value)->klass->fields;
    auto found=fields.find(name);require(found!=fields.end() && found->second.offset==offset,"authored input field differs");
}
static Obj method(Obj value,const char* name,int count,uint32_t token) {
    for(auto* info:static_cast<host::Node*>(value)->klass->methods)
        if(!strcmp(info->name,name) && info->token==token && info->count==static_cast<uint32_t>(count))return info;
    throw std::runtime_error("authored input original method missing");
}
static void clickField(Obj value,const char* name,size_t offset,Obj klass,size_t size) {
    field(value,name,offset);const auto& actual=static_cast<host::Node*>(value)->klass->fields.at(name);
    require(actual.type==klass && actual.size==size,"authored input click field ABI differs");
}
static void clickMode(Obj value) {field(value,"_deferredClickMode",0x170);}
static void clickCapture(State&,Obj,const ba_prediction_input_observer::Ticket&) {
    // Full capture/typed-cache adapter has its own source tests. This host
    // qualifies unchanged callback routing and forwarding only.
}
}
namespace ba_prediction_selection {
static bool active(){return host::active && !host::stopped;}
static void* currentSelector(){return host::selected;}
static void failed(const char* where,const char* reason) noexcept {
    ++host::failures;host::stopped=true;host::lastFailure=std::string(where)+":"+reason;
}
}

// Compile the production adapter itself. The facades above replace only its
// external host; its routing, signatures, RAII, marker and forwarding are real.
#include "../src/prediction_input_observer.cpp"

namespace host {
static const std::array<Callback,13> exports{{
    &OfflinePredictionInputFocusCancel0,&OfflinePredictionInputFocusCancel1,&OfflinePredictionInputFocusCancel2,
    &OfflinePredictionInputFocusCancel3,&OfflinePredictionInputFocusCancel4,&OfflinePredictionInputCancelAbility,
    &OfflinePredictionInputQueueModifier,&OfflinePredictionInputForceModifier,&OfflinePredictionInputPosition,
    &OfflinePredictionInputDown,&OfflinePredictionInputUp,&OfflinePredictionInputContextDown,&OfflinePredictionInputContextUp}};
static void single(Obj instance,Obj info) {
    check(!info,"original ProcessClick null MethodInfo changed");
    put<uint32_t>(instance,0x128,5);put<uint8_t>(instance,0x16c,1);
    put<uint8_t>(instance,0x16d,0);put<uint8_t>(instance,0x119,0);put<int32_t>(instance,0x170,1);
}
static void reset() {
    check(!ba_prediction_input::currentDispatch,"previous authored callback leaked its dispatch frame");
    originals.fill(0);calls.clear();logs.clear();originalBody={};processBody=&single;
    failures=0;processCalls=0;processSelector=nullptr;processInfo=nullptr;lastFailure.clear();
    active=true;stopped=false;presentationOwned=true;world=91;match.assign(32,'a');
    memories.clear();selector=Node{};otherSelector=Node{};manager=Node{};simulation=Node{};
    for(auto* node:{&selector,&otherSelector,&manager,&simulation})memories.emplace(node,&node->bytes);
    auto* selectorType=type("Uncapped","UnitSelector");auto* contextType=type("Authored","CallbackContext");
    contextType->name="CallbackContext";contextType->declaring=type("UnityEngine.InputSystem","InputAction");
    contextType->value=true;contextType->size=16;
    selectorType->methods.clear();selectorType->fields={
        {"_unitManager",{0x40,8,type("Uncapped","UnitManager")}},
        {"_doubleClickFirstClickReferenceUnitEntityId",{0x128,4,type("System","UInt32")}},
        {"_isPointerDown",{0x16c,1,type("System","Boolean")}},
        {"_isContextPointerDown",{0x16d,1,type("System","Boolean")}},
        {"_isDragging",{0x119,1,type("System","Boolean")}},
        {"_deferredClickMode",{0x170,4,type("Authored","DeferredClickMode")}}};
    selector.klass=selectorType;otherSelector.klass=selectorType;selected=&selector;
    put<Obj>(&selector,0x40,&manager);put<Obj>(&otherSelector,0x40,&manager);
    for(size_t i=0;i<methods.size();++i) {
        methods[i]=Method{};methods[i].name=names[i];methods[i].token=0x0600225d+static_cast<uint32_t>(i);
        methods[i].result=type("System","Void");methods[i].parameter=contextType;
        memories.emplace(&methods[i],&methods[i].bytes);memories.emplace(&slots[i],&slots[i].bytes);
        const auto thunk=reinterpret_cast<Obj>(exports[i]);
        put<Obj>(&methods[i],0,thunk);put<Obj>(&methods[i],8,thunk);put<Obj>(&slots[i],0,thunk);
        selectorType->methods.push_back(&methods[i]);
    }
    for(size_t i=0;i<context.bytes.size();++i)context.bytes[i]=static_cast<unsigned char>(i*13+7);
    ba::initialThread=GetCurrentThreadId();auto& state=ba_prediction_actors::state();
    state.thread=ba::initialThread;state.failed=false;state.world=world;state.groupGeneration=1;state.match=match;
    state.manager=std::make_unique<Root>(&manager);state.simulation=std::make_unique<Root>(&simulation);
    state.inputIntent=ba_prediction_input_observer::Ledger{};
}
static void invoke(size_t index,Obj instance=nullptr,const void* input=nullptr,Obj info=nullptr) {
    exports[index](instance?instance:&selector,input?input:&context,info?info:&methods[index]);
}
static void exact(size_t index,Obj instance,const void* input,Obj info) {
    check(calls.size()==1 && calls[0].route==index && calls[0].selector==instance &&
        calls[0].context==input && calls[0].info==info && originals[index]==1,
        "actual exported route changed original arguments or callback count");
    check(!ba_prediction_input::currentDispatch,"actual callback left a dispatch frame");
}
static void allRoutesPreserveActualOriginalArgumentsAndContext() {
    for(size_t i=0;i<exports.size();++i) {
        reset();const auto before=context.bytes;const auto selectorBefore=selector.bytes;
        invoke(i);exact(i,&selector,&context,&methods[i]);
        check(context.bytes==before && selector.bytes==selectorBefore,"observer mutated original context or selector bytes");
        check(!failures && !ba_prediction_actors::state().inputIntent.accepted(),"unmarked callback invented an episode");
        check(ba_prediction_actors::state().inputIntent.serial()==1,"actual callback did not enter the ledger");
    }
}
static void inactiveUninitializedAndStaleSelectorsPassThrough() {
    for(int mode=0;mode<9;++mode) {
        reset();auto& state=ba_prediction_actors::state();Obj instance=&selector;
        if(mode==0)active=false;if(mode==1)state.world=0;if(mode==2)state.groupGeneration=0;
        if(mode==3)state.manager.reset();if(mode==4)state.simulation.reset();
        if(mode==5)instance=&otherSelector;if(mode==6)state.world=world+1;
        if(mode==7)state.match.assign(32,'b');if(mode==8){active=false;ba::initialThread=0;}
        invoke(9,instance);exact(9,instance,&context,&methods[9]);
        check(!failures && !state.inputIntent.serial() && !state.inputIntent.accepted(),"passthrough armed or failed observer");
    }
}
static void onlyACompletedMarkedDownArms() {
    reset();single(&selector,nullptr);invoke(9);
    check(!ba_prediction_actors::state().inputIntent.accepted(),"scalar Single without marker armed");
    reset();OfflinePredictionClickDownAccepted(&selector,nullptr);
    check(processCalls==1 && !ba_prediction_actors::state().inputIntent.accepted(),"out-of-callback marker armed");
    reset();originalBody=[](size_t){OfflinePredictionClickDownAccepted(&selector,nullptr);};invoke(10);
    check(processCalls==1 && !failures && !ba_prediction_actors::state().inputIntent.accepted(),"Up marker armed Down");
    reset();const auto before=context.bytes;
    originalBody=[](size_t){
        auto& ledger=ba_prediction_actors::state().inputIntent;
        check(!ledger.accepted(),"episode armed before original marker");
        OfflinePredictionClickDownAccepted(&selector,nullptr);
        check(!ledger.accepted(),"episode armed before original Down completed");
    };
    invoke(9);exact(9,&selector,&context,&methods[9]);
    check(processCalls==1 && processSelector==&selector && !processInfo && !failures &&
        ba_prediction_actors::state().inputIntent.accepted() && logs.size()==1,
        "actual completed original Down marker failed to arm exactly once");
    check(context.bytes==before,"positive Down changed original CallbackContext bytes");
}
static void metadataAndLoadedDispatchFailuresStillForwardExactlyOnce() {
    for(int mode=0;mode<12;++mode) {
        reset();auto* ctx=methods[9].parameter;Obj supplied=&methods[9];
        if(mode==0)put<Obj>(&methods[9],0,reinterpret_cast<Obj>(exports[8]));
        if(mode==1)put<Obj>(&methods[9],8,reinterpret_cast<Obj>(exports[8]));
        if(mode==2)put<Obj>(&slots[9],0,reinterpret_cast<Obj>(exports[8]));
        if(mode==3)put<Obj>(&slots[9],0,nullptr);if(mode==4)supplied=&methods[8];
        if(mode==5)methods[9].flags=0x10;if(mode==6)methods[9].result=type("System","Int32");
        if(mode==7)ctx->name="WrongContext";if(mode==8)ctx->declaring=type("Authored","OtherAction");
        if(mode==9)ctx->value=false;if(mode==10)ctx->size=8;if(mode==11)methods[9].parameter=nullptr;
        originalBody=[](size_t){OfflinePredictionClickDownAccepted(&selector,nullptr);};
        invoke(9,&selector,&context,supplied);exact(9,&selector,&context,supplied);
        check(failures==1 && stopped && processCalls==1 && !ba_prediction_actors::state().inputIntent.accepted() &&
            !ba_prediction_actors::state().inputIntent.serial(),"metadata/slot failure armed or skipped original");
    }
}
static void failedCompletionAndChangedOwnershipDoNotArm() {
    for(int mode=0;mode<3;++mode) {
        reset();originalBody=[mode](size_t){
            OfflinePredictionClickDownAccepted(&selector,nullptr);
            if(mode==0)++ba_prediction_actors::state().groupGeneration;
            if(mode==1)active=false;if(mode==2)presentationOwned=false;
        };
        invoke(9);exact(9,&selector,&context,&methods[9]);
        check(processCalls==1 && !ba_prediction_actors::state().inputIntent.accepted(),"changed callback owner completed an episode");
        check(failures==(mode==1?0u:1u),"completion failure handling differs");
    }
}
static void nonstandardOriginalExceptionsPropagateWithoutRetry() {
    for(bool observe:{false,true})for(bool processThrows:{false,true}) {
        reset();active=observe;const auto before=context.bytes;
        originalBody=[processThrows](size_t){
            OfflinePredictionClickDownAccepted(&selector,nullptr);
            if(!processThrows)throw OriginalError{17};
        };
        if(processThrows)processBody=[](Obj,Obj){throw OriginalError{23};};
        bool exactException=false;
        try{invoke(9);}catch(const OriginalError& error){exactException=error.tag==(processThrows?23:17);}
        exact(9,&selector,&context,&methods[9]);
        check(exactException && processCalls==1 && !failures && !logs.size() &&
            !ba_prediction_actors::state().inputIntent.accepted(),"original nonstd exception was changed, retried or completed");
        check(context.bytes==before,"throwing callback changed original context bytes");
    }
}
static void nestedCallbacksCannotRearmTheirParent() {
    reset();Context child;child.bytes.fill(0xb7);const auto childBefore=child.bytes;
    originalBody=[&child](size_t index){
        if(index!=9)return;
        OfflinePredictionClickDownAccepted(&selector,nullptr);
        if(originals[9]==1) {
            invoke(8);invoke(9,&selector,&child,&methods[9]);
            check(ba_prediction_actors::state().inputIntent.accepted()->serial==3,"nested Down serial differs");
            OfflinePredictionClickDownAccepted(&selector,nullptr); // Old parent marker cannot win.
        }
    };
    invoke(9);
    check(originals[9]==2 && originals[8]==1 && processCalls==3 && !failures &&
        ba_prediction_actors::state().inputIntent.accepted() &&
        ba_prediction_actors::state().inputIntent.accepted()->serial==3,
        "parent rearmed over the newest completed nested Down");
    check(calls.size()==3 && calls[0].context==&context && calls[1].context==&context &&
        calls[2].context==&child && child.bytes==childBefore && !ba_prediction_input::currentDispatch,
        "nested callback changed context or leaked its owning dispatch");
}
static void invalidatedDownAndWrongMarkerArgumentsCannotArm() {
    for(int mode=0;mode<3;++mode) {
        reset();originalBody=[mode](size_t){
            if(mode==0){OfflinePredictionClickDownAccepted(&selector,nullptr);ba_prediction_actors::state().inputIntent.invalidate();}
            if(mode==1)OfflinePredictionClickDownAccepted(&otherSelector,nullptr);
            if(mode==2)OfflinePredictionClickDownAccepted(&selector,&methods[9]);
        };
        // A nonnull marker MI must still reach its original unchanged.
        if(mode==2)processBody=[](Obj,Obj){};
        invoke(9);exact(9,&selector,&context,&methods[9]);
        check(processCalls==1 && !ba_prediction_actors::state().inputIntent.accepted(),"invalidated or foreign marker armed");
        check(failures==(mode==2?1u:0u),"marker argument failure classification differs");
    }
}
}
int main(){try{
    host::allRoutesPreserveActualOriginalArgumentsAndContext();
    host::inactiveUninitializedAndStaleSelectorsPassThrough();
    host::onlyACompletedMarkedDownArms();host::metadataAndLoadedDispatchFailuresStillForwardExactlyOnce();
    host::failedCompletionAndChangedOwnershipDoNotArm();host::nonstandardOriginalExceptionsPropagateWithoutRetry();
    host::nestedCallbacksCannotRearmTheirParent();host::invalidatedDownAndWrongMarkerArgumentsCannotArm();
    std::cout<<"input binding:8 authored actual-source groups PASS; real delegate dispatch and held-click repair remain unqualified\n";
    return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
catch(...){std::cerr<<"unexpected authored input exception\n";return 1;}}
