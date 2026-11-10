// Authored host for the ACTUAL focus adapter header. No original DLL/game loads.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <array>
#include <algorithm>
#include <cstdarg>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <functional>
#include <iostream>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

extern "C" __declspec(dllexport) bool OfflinePredictionRepeatFocusNext(void*,void*);
extern "C" __declspec(dllexport) bool OfflinePredictionFocusActuate(void*,int32_t,bool);
extern "C" __declspec(dllexport) uint32_t OfflinePredictionStartRepeatFocus(void*,void*);
extern "C" __declspec(dllexport) void OfflinePredictionControlGroupCamera(void*,void*,void*);

namespace host {
using Obj=void*;
struct Class;
struct Field{size_t offset=0;Class* type=nullptr;};
struct Method{Obj function=nullptr;const char* name=nullptr;uint32_t token=0,flags=0;Class* result=nullptr;std::vector<Class*> parameters;};
struct Class{std::string space,name;int32_t size=0;std::vector<Method*> methods;std::vector<Class*> nested;std::map<std::string,Field> fields;};
struct Identity{uint32_t entityId=0,unitType=0,armyId=0;};
struct Node{Class* klass=nullptr;std::array<unsigned char,0x220> bytes{};std::vector<uint32_t> ids;std::vector<Obj> objects;
    Identity resident{};std::map<uint32_t,Identity> native;std::map<uint32_t,uint32_t> states;bool truth=true,enabled=true;};
std::map<std::pair<std::string,std::string>,std::unique_ptr<Class>> classes;
std::set<Obj> methods;
std::vector<std::unique_ptr<Node>> boxes;
bool active=true,diagnostic=false,accepted=true,throwNext=false,throwCamera=false,originalResult=true,cameraOnNext=true,codeGuardOkay=true,fallbackOnNext=false,deferStart=false;
uint64_t world=1,now=1;std::string match(32,'a'),lastFailure;
Obj selector=nullptr,lastIterator=nullptr,lastInfo=nullptr,lastCamera=nullptr,lastActor=nullptr;
unsigned originalNextCalls=0,originalActuateCalls=0,originalStartCalls=0,originalCameraCalls=0,chooserCalls=0,failures=0,barriers=0,roots=0;
uint32_t choice=11,handle=77;std::vector<std::string> logs;
std::map<uint32_t,Obj> weakTargets;uint32_t nextWeak=1;unsigned weakAllocated=0,weakFreed=0;
Node slot;
Method nextMethod,startMethod,actuateMethod,cameraMethod,truthMethod,activityMethod,targetMethod,positionMethod;
void check(bool value,const char* why){if(!value)throw std::runtime_error(why);}
Class* type(const char* space,const char* name){auto& p=classes[{space,name}];if(!p){p=std::make_unique<Class>();p->space=space;p->name=name;}return p.get();}
template<class T>void put(Node& n,size_t offset,T value){check(offset+sizeof(T)<=n.bytes.size(),"authored write bound");memcpy(n.bytes.data()+offset,&value,sizeof(T));}
template<class T>T read(Obj object,size_t offset){check(object!=nullptr,"authored null read");T value{};
    if(methods.count(object)){check(!offset&&sizeof(T)==sizeof(Obj),"authored method read bound");memcpy(&value,&static_cast<Method*>(object)->function,sizeof(T));}
    else{auto& n=*static_cast<Node*>(object);check(offset+sizeof(T)<=n.bytes.size(),"authored read bound");memcpy(&value,n.bytes.data()+offset,sizeof(T));}return value;}
template<class T>Obj box(Class* klass,T value){auto n=std::make_unique<Node>();n->klass=klass;put(*n,0,value);auto p=n.get();boxes.push_back(std::move(n));return p;}
bool originalNext(Obj iterator,Obj info);
bool originalActuate(Obj selector,int32_t group,Obj info);
uint32_t originalStart(Obj iterator,Obj info);
void originalCamera(Obj camera,Obj actor,Obj info);
Obj originalTarget(Obj value,Obj){return value;}
bool originalTruth(Obj value,Obj){return static_cast<Node*>(value)->truth;}
bool originalActivity(Obj value,Obj){return static_cast<Node*>(value)->enabled;}
uint32_t originalChoose(Obj,const void*,Obj){++chooserCalls;return choice;}
Obj methodIter(Obj klass,void** cursor){const auto i=reinterpret_cast<uintptr_t>(*cursor);auto& v=static_cast<Class*>(klass)->methods;
    if(i>=v.size())return nullptr;*cursor=reinterpret_cast<void*>(i+1);return v[i];}
Obj nestedIter(Obj klass,void** cursor){const auto i=reinterpret_cast<uintptr_t>(*cursor);auto& v=static_cast<Class*>(klass)->nested;
    if(i>=v.size())return nullptr;*cursor=reinterpret_cast<void*>(i+1);return v[i];}
const char* className(Obj c){return static_cast<Class*>(c)->name.c_str();}
const char* methodName(Obj m){return static_cast<Method*>(m)->name;}
uint32_t methodToken(Obj m){return static_cast<Method*>(m)->token;}
uint32_t paramCount(Obj m){return static_cast<uint32_t>(static_cast<Method*>(m)->parameters.size());}
uint32_t methodFlags(Obj m,uint32_t* implementation){*implementation=0;return static_cast<Method*>(m)->flags;}
Obj resultType(Obj m){return static_cast<Method*>(m)->result;}
Obj param(Obj m,uint32_t i){return static_cast<Method*>(m)->parameters.at(i);}
Obj fromType(Obj c){return c;}
Obj fieldType(Obj f){return static_cast<Field*>(f)->type;}
int32_t valueSize(Obj c,uint32_t* alignment){*alignment=4;return static_cast<Class*>(c)->size;}
bool assignable(Obj target,Obj source){return target==source;}
uint32_t newWeak(Obj object,bool trackResurrection){check(object&&!trackResurrection,"authored weak handle contract differs");
    check(nextWeak!=UINT32_MAX,"authored weak handle space exhausted");const auto result=nextWeak++;
    check(weakTargets.emplace(result,object).second,"authored weak handle reused");++weakAllocated;return result;}
Obj weakTarget(uint32_t handleValue){auto found=weakTargets.find(handleValue);check(found!=weakTargets.end(),"authored unknown weak handle read");return found->second;}
void freeWeak(uint32_t handleValue){check(weakTargets.erase(handleValue)==1,"authored weak handle double free");++weakFreed;}
void collect(Obj object){for(auto& entry:weakTargets)if(entry.second==object)entry.second=nullptr;}
}
namespace ba {
using Obj=void*;
DWORD initialThread=0;
template<class T>T read(Obj p,size_t o){return host::read<T>(p,o);}
Obj klass(Obj p){return static_cast<host::Node*>(p)->klass;}
Obj field(Obj p,const char* n){return &static_cast<host::Class*>(klass(p))->fields.at(n);}
template<class T>void set(Obj p,const char* n,T v){++host::barriers;host::put(*static_cast<host::Node*>(p),static_cast<host::Field*>(field(p,n))->offset,v);}
bool flag(const wchar_t*){return host::diagnostic;}
int lanSlot(){return 1;}
void init(){}
void log(const char* format,...){char text[8192];va_list args;va_start(args,format);vsnprintf(text,sizeof(text),format,args);va_end(args);host::logs.emplace_back(text);}
template<class T>T api(const char* name){
    if(!strcmp(name,"il2cpp_class_get_nested_types"))return reinterpret_cast<T>(&host::nestedIter);
    if(!strcmp(name,"il2cpp_class_get_methods"))return reinterpret_cast<T>(&host::methodIter);
    if(!strcmp(name,"il2cpp_class_get_name"))return reinterpret_cast<T>(&host::className);
    if(!strcmp(name,"il2cpp_method_get_name"))return reinterpret_cast<T>(&host::methodName);
    if(!strcmp(name,"il2cpp_method_get_token"))return reinterpret_cast<T>(&host::methodToken);
    if(!strcmp(name,"il2cpp_method_get_param_count"))return reinterpret_cast<T>(&host::paramCount);
    if(!strcmp(name,"il2cpp_method_get_flags"))return reinterpret_cast<T>(&host::methodFlags);
    if(!strcmp(name,"il2cpp_method_get_return_type"))return reinterpret_cast<T>(&host::resultType);
    if(!strcmp(name,"il2cpp_method_get_param"))return reinterpret_cast<T>(&host::param);
    if(!strcmp(name,"il2cpp_class_from_type"))return reinterpret_cast<T>(&host::fromType);
    if(!strcmp(name,"il2cpp_field_get_type"))return reinterpret_cast<T>(&host::fieldType);
    if(!strcmp(name,"il2cpp_class_value_size"))return reinterpret_cast<T>(&host::valueSize);
    if(!strcmp(name,"il2cpp_class_is_assignable_from"))return reinterpret_cast<T>(&host::assignable);
    if(!strcmp(name,"il2cpp_gchandle_new_weakref"))return reinterpret_cast<T>(&host::newWeak);
    if(!strcmp(name,"il2cpp_gchandle_get_target"))return reinterpret_cast<T>(&host::weakTarget);
    if(!strcmp(name,"il2cpp_gchandle_free"))return reinterpret_cast<T>(&host::freeWeak);
    throw std::runtime_error("unexpected authored focus metadata API");
}
template<class T>T native(uintptr_t rva){
    if(rva==0x6d4dc48)return reinterpret_cast<T>(&host::slot);
    if(rva==0x3bf9de0)return reinterpret_cast<T>(&host::originalNext);
    if(rva==0x3bf1650)return reinterpret_cast<T>(&host::originalActuate);
    if(rva==0x32f97f0)return reinterpret_cast<T>(&host::originalStart);
    if(rva==0x3e9e310)return reinterpret_cast<T>(&host::originalCamera);
    if(rva==0x3c646a0)return reinterpret_cast<T>(&host::originalChoose);
    if(rva==0x3e9b7a0)return reinterpret_cast<T>(&host::originalTarget);
    if(rva==0x508fda0)return reinterpret_cast<T>(&host::originalTruth);
    if(rva==0x5084710)return reinterpret_cast<T>(&host::originalActivity);
    throw std::runtime_error("unexpected authored focus native RVA");
}
}
namespace ba_local {
DWORD updateThread=0;
struct Root{void* value;explicit Root(void* p):value(p){++host::roots;}~Root(){--host::roots;}void* get()const{return value;}
    Root(const Root&)=delete;Root& operator=(const Root&)=delete;};
}
namespace ba_prediction_worker {
uint64_t movementWorldId(){return host::world;}
const std::string& movementMatchId(){return host::match;}
}
namespace ba_prediction_movement {bool ownsPresentation(void*){return host::active;}}
namespace ba_frame_timing {bool timestampMicros(uint64_t& out){out=++host::now;return true;}}
namespace ba_prediction_actors {
using ba::Obj;using ba_local::Root;
namespace policy{using ActorIdentity=host::Identity;}
struct Resident{policy::ActorIdentity identity{};uint64_t incarnation=0;};
struct Canonical{uint32_t type=0,army=0;uint64_t incarnation=0;};
struct State{uint64_t world=0;std::string match;std::unique_ptr<Root> simulation,manager;std::map<Obj,Resident> identities;
    struct Admission{int frame=100;std::map<uint32_t,Canonical> entities;}admission;};
State& state(){static State value;return value;}
void require(bool v,const char* why){host::check(v,why);}
void guard(uintptr_t,const char*,size_t){require(host::codeGuardOkay,"authored original-code guard failed");}
Obj type(const char* space,const char* name){return host::type(space,name);}
void classIs(Obj p,const char* space,const char* name){require(p&&ba::klass(p)==type(space,name),"authored focus class differs");}
void field(Obj p,const char* name,size_t offset){require(p&&static_cast<host::Field*>(ba::field(p,name))->offset==offset,"authored focus field differs");}
Obj method(Obj object,const char* name,int count,uint32_t token,uintptr_t rva=0){
    require(object!=nullptr,"authored method owner missing");for(auto* m:static_cast<host::Class*>(ba::klass(object))->methods)
        if(!strcmp(m->name,name)&&m->parameters.size()==static_cast<size_t>(count)&&m->token==token){
            if(rva)require(m->function==ba::native<Obj>(rva),"authored original method target differs");return m;}
    throw std::runtime_error("authored focus method missing");
}
void instanceSignature(Obj info,const char* result,const char* parameter=nullptr){auto* m=static_cast<host::Method*>(info);
    require(!(m->flags&0x10)&&m->result==type("System",result),"authored focus signature differs");
    if(parameter)require(m->parameters.size()==1&&m->parameters[0]==type("System",parameter),"authored focus parameter differs");}
template<class T>T unbox(Obj p){require(p&&static_cast<host::Class*>(ba::klass(p))->size==sizeof(T),"authored boxed size differs");return host::read<T>(p,0);}
policy::ActorIdentity resident(Obj p){return static_cast<host::Node*>(p)->resident;}
bool confirmedInterval(const State& s,int frame){return frame>=s.admission.frame&&frame-s.admission.frame<=12;}
struct Current{Root frame;explicit Current(Obj frames):frame(host::read<Obj>(frames,0x10)){}
    std::optional<policy::ActorIdentity> identity(uint32_t id)const{const auto& map=static_cast<host::Node*>(frame.get())->native;auto p=map.find(id);return p==map.end()?std::nullopt:std::optional<policy::ActorIdentity>(p->second);}
    bool retainedAlive(uint32_t id)const{auto& v=static_cast<host::Node*>(frame.get())->states;require(v.count(id)!=0,"authored native state missing");return v.at(id)!=6;}};
struct IntentGroup{Root selected;IntentGroup(const State& s,Obj group,uint32_t index):selected(host::read<Obj>(group,0x20)){
    require(host::read<uint32_t>(group,0x38)==index&&host::read<Obj>(group,0x48)==s.simulation->get()&&
        host::read<Obj>(group,0x60)==s.manager->get(),"authored logical group owner differs");}};
Obj invoke(Obj info,Obj object,void** args=nullptr){auto* m=static_cast<host::Method*>(info);
    if(m==&host::nextMethod)return host::box(host::type("System","Boolean"),OfflinePredictionRepeatFocusNext(object,info));
    if(m==&host::actuateMethod)return host::box(host::type("System","Boolean"),host::originalActuate(object,*static_cast<int32_t*>(args[0]),nullptr));
    if(m==&host::startMethod)return host::box(host::type("MEC","CoroutineHandle"),host::originalStart(args[0],info));
    if(m==&host::cameraMethod){host::originalCamera(object,args[0],info);return nullptr;}
    if(m==&host::truthMethod)return host::box(host::type("System","Boolean"),static_cast<host::Node*>(args[0])->truth);
    if(m==&host::activityMethod)return host::box(host::type("System","Boolean"),static_cast<host::Node*>(object)->enabled);
    if(m==&host::targetMethod)return object;
    if(m==&host::positionMethod){struct Vec3{float x,y,z;};return host::box(host::type("UnityEngine","Vector3"),Vec3{});}
    throw std::runtime_error("unexpected authored focus invocation");
}
}
namespace ba_prediction_selection {
namespace actors=ba_prediction_actors;using ba::Obj;using ba_local::Root;
bool active(){return host::active&&host::world!=0;}
Obj currentSelector(){return host::selector;}
void failed(const char*,const char* why){++host::failures;host::lastFailure=why;host::world=0;}
std::vector<uint32_t> selectionIds(Obj set){return static_cast<host::Node*>(set)->ids;}
struct Context{actors::State& state;Obj selector;std::map<uint32_t,Obj> live;
    explicit Context(Obj p):state(actors::state()),selector(p){actors::require(p==host::selector&&state.world==host::world&&state.match==host::match,"authored focus context differs");
        for(auto unit:static_cast<host::Node*>(state.manager->get())->objects)actors::require(live.emplace(actors::resident(unit).entityId,unit).second,"duplicate authored live unit");}
    bool admitted(Obj actor)const{if(!actor)return false;auto p=state.identities.find(actor);if(p==state.identities.end())return false;const auto& id=p->second.identity;
        auto liveOne=live.find(id.entityId);auto c=state.admission.entities.find(id.entityId);
        return liveOne!=live.end()&&liveOne->second==actor&&c!=state.admission.entities.end()&&id.armyId==1&&
            c->second.type==id.unitType&&c->second.army==id.armyId&&c->second.incarnation==p->second.incarnation&&p->second.incarnation;}
};
}
#ifndef BA_FOCUS_HEADER
#define BA_FOCUS_HEADER "../src/prediction_focus.hpp"
#endif
#include BA_FOCUS_HEADER

namespace host {
bool originalNext(Obj iterator,Obj info){++originalNextCalls;lastIterator=iterator;lastInfo=info;
    if(throwNext)throw std::runtime_error("authored original MoveNext failure");
    Obj owner=read<Obj>(iterator,0x18);if(read<int>(owner,0xa0)<0)return false;
    // Source-relevant original state1 fallback and state2 exit. These writes
    // belong to the AUTHORED original callback, never the adapter under test.
    if(fallbackOnNext&&read<int>(iterator,0x10)==2){put(*static_cast<Node*>(owner),0xa0,int32_t{-1});return false;}
    if(fallbackOnNext&&!read<Obj>(owner,0xa8)) {
        struct Vec3{float x,y,z;};Vec3 point{};
        const auto selected=ba_prediction_selection::focusCandidate(read<Obj>(owner,0x90),&point,nullptr);
        Obj found=nullptr;
        for(auto actor:static_cast<Node*>(ba_prediction_actors::state().manager->get())->objects)
            if(static_cast<Node*>(actor)->resident.entityId==selected)found=actor;
        if(!found){put(*static_cast<Node*>(iterator),0x10,int32_t{2});put(*static_cast<Node*>(iterator),0x14,uint32_t{0});return true;}
        ba::set<Obj>(owner,"_repeatFocusUnit",found);
    }
    if(cameraOnNext&&read<Obj>(owner,0xa8))OfflinePredictionControlGroupCamera(read<Obj>(owner,0x20),read<Obj>(owner,0xa8),nullptr);
    if(!world&&active)return false;
    put(*static_cast<Node*>(iterator),0x10,1);put(*static_cast<Node*>(iterator),0x14,uint32_t{0xff800000});return originalResult;
}
bool originalActuate(Obj owner,int32_t group,Obj info){++originalActuateCalls;lastIterator=owner;lastInfo=info;check(group>=0&&group<16,"authored Actuate group bound");return accepted;}
uint32_t originalStart(Obj iterator,Obj info){++originalStartCalls;lastIterator=iterator;lastInfo=info;
    if(active&&!deferStart)OfflinePredictionRepeatFocusNext(iterator,&nextMethod);return handle;}
void originalCamera(Obj camera,Obj actor,Obj info){++originalCameraCalls;lastCamera=camera;lastActor=actor;lastInfo=info;
    if(throwCamera)throw std::runtime_error("authored original camera failure");}
void metadata(){
    type("System","Boolean")->size=1;type("System","Int32")->size=4;type("System","UInt32")->size=4;
    type("UnityEngine","Vector3")->size=12;type("MEC","CoroutineHandle")->size=4;
    auto unit=type("Uncapped","Unit"),selectorClass=type("Uncapped","UnitSelector"),iter=type("Uncapped","<FocusControlGroupRepeat>d__119");
    auto camera=type("Uncapped","CameraController"),set=type("Uncapped.Collections","UnitSelectionSet");
    selectorClass->nested={iter};selectorClass->fields={{"_repeatFocusUnit",{0xa8,unit}},{"_cameraController",{0x20,camera}},
        {"_selectionSet",{0x90,set}},{"_controlGroupPanel",{0x38,type("Uncapped","ControlGroupPanel")}},
        {"_focusChaseControlGroup",{0xa0,type("System","Int32")}},{"_repeatControlGroupFocusHandle",{0xb0,type("MEC","CoroutineHandle")}}};
    iter->fields={{"<>4__this",{0x18,selectorClass}},{"<>1__state",{0x10,type("System","Int32")}},{"<>2__current",{0x14,type("System","Single")}}};
    unit->fields={{"_componentData",{0x158,type("Authored","Components")}},{"<DeadToTheSim>k__BackingField",{0x160,type("System","Boolean")}}};
    type("Uncapped","ControlGroupPanel")->fields={{"_controlGroups",{0x38,type("Authored","Array")}}};set->fields={{"_simFrames",{0x48,type("Authored","Frames")}}};
    nextMethod={reinterpret_cast<Obj>(&OfflinePredictionRepeatFocusNext),"MoveNext",0x0600227c,0,type("System","Boolean"),{}};
    startMethod={reinterpret_cast<Obj>(&originalStart),"RunCoroutine",0x060000a8,0x10,type("MEC","CoroutineHandle"),{iter}};
    actuateMethod={reinterpret_cast<Obj>(&originalActuate),"ActuateControlGroup",0x0600220f,0,type("System","Boolean"),{type("System","Int32")}};
    cameraMethod={reinterpret_cast<Obj>(&originalCamera),"FocusOnUnit",0x060015ec,0,type("System","Void"),{unit}};
    truthMethod={reinterpret_cast<Obj>(&originalTruth),"op_Implicit",0x06000f04,0x10,type("System","Boolean"),{type("UnityEngine","Object")}};
    activityMethod={reinterpret_cast<Obj>(&originalActivity),"get_isActiveAndEnabled",0x06000df6,0,type("System","Boolean"),{}};
    targetMethod={reinterpret_cast<Obj>(&originalTarget),"get_CameraTarget",0x060015c8,0,nullptr,{}};positionMethod={nullptr,"get_position",0x0600109a,0,type("UnityEngine","Vector3"),{}};
    iter->methods={&nextMethod};selectorClass->methods={&actuateMethod};type("MEC","Timing")->methods={&startMethod};
    camera->methods={&cameraMethod,&targetMethod,&positionMethod};unit->methods={&truthMethod,&activityMethod};
    for(auto* m:{&nextMethod,&startMethod,&actuateMethod,&cameraMethod,&truthMethod,&activityMethod,&targetMethod,&positionMethod})methods.insert(m);
    put(slot,0,nextMethod.function);
}
}
namespace test {
namespace focus=ba_prediction_selection;namespace actors=ba_prediction_actors;using host::Node;using host::put;using host::check;
unsigned cases=0;
struct Fixture{
    Node selector,iterator,otherIterator,simulation,manager,frames,frame,source,logical,panel,array,group,camera,unit,replacement,hq;
    Fixture(){ba::initialThread=ba_local::updateThread=GetCurrentThreadId();
        focus::focusForget();focus::focusPruneRetired();focus::focusStopped()=false;host::boxes.clear();host::active=true;host::diagnostic=false;host::codeGuardOkay=true;host::world=1;host::match=std::string(32,'a');
        host::accepted=true;host::throwNext=host::throwCamera=host::fallbackOnNext=host::deferStart=false;host::originalResult=host::cameraOnNext=true;host::choice=11;
        host::originalNextCalls=host::originalActuateCalls=host::originalStartCalls=host::originalCameraCalls=host::chooserCalls=host::failures=host::barriers=0;host::logs.clear();host::lastFailure.clear();
        auto& s=actors::state();s.identities.clear();s.admission.entities.clear();s.simulation.reset();s.manager.reset();s.world=host::world;s.match=host::match;s.admission.frame=100;
        host::selector=&selector;
        selector.klass=host::type("Uncapped","UnitSelector");iterator.klass=otherIterator.klass=host::type("Uncapped","<FocusControlGroupRepeat>d__119");
        camera.klass=host::type("Uncapped","CameraController");source.klass=logical.klass=host::type("Uncapped.Collections","UnitSelectionSet");
        panel.klass=host::type("Uncapped","ControlGroupPanel");unit.klass=replacement.klass=hq.klass=host::type("Uncapped","Unit");
        put(selector,0x90,static_cast<void*>(&source));put(selector,0x38,static_cast<void*>(&panel));put(selector,0x20,static_cast<void*>(&camera));
        put(selector,0xa8,static_cast<void*>(&unit));put(selector,0xa0,int32_t{4});put(selector,0xb0,host::handle);
        put(iterator,0x18,static_cast<void*>(&selector));put(otherIterator,0x18,static_cast<void*>(&selector));
        put(iterator,0x10,int32_t{0});put(iterator,0x14,uint32_t{0});
        put(simulation,0x148,static_cast<void*>(&frames));put(frames,0x10,static_cast<void*>(&frame));put(frame,0x40,int32_t{105});
        put(source,0x48,static_cast<void*>(&frames));source.ids=logical.ids={11};put(panel,0x38,static_cast<void*>(&array));put(array,0x18,uintptr_t{5});put(array,0x20+4*sizeof(void*),static_cast<void*>(&group));
        put(group,0x20,static_cast<void*>(&logical));put(group,0x38,uint32_t{4});put(group,0x48,static_cast<void*>(&simulation));put(group,0x60,static_cast<void*>(&manager));
        s.simulation=std::make_unique<ba_local::Root>(&simulation);s.manager=std::make_unique<ba_local::Root>(&manager);
        unit.resident=replacement.resident={11,1,1};hq.resident={0,3,1};
        for(auto* actor:{&unit,&replacement,&hq}){put(*actor,0x158,static_cast<void*>(&frame));put(*actor,0x160,false);}
        manager.objects={&unit};s.identities[&unit]={{11,1,1},11};s.identities[&replacement]={{11,1,1},11};s.identities[&hq]={{0,3,1},1};
        s.admission.entities[11]={1,1,11};s.admission.entities[0]={3,1,1};frame.native[11]={11,1,1};frame.states[11]=0;frame.native[0]={0,3,1};frame.states[0]=0;
    }
    ~Fixture(){focus::focusForget();actors::state().simulation.reset();actors::state().manager.reset();
        host::collect(&iterator);host::collect(&otherIterator);focus::focusPruneRetired();}
    void start(){check(OfflinePredictionFocusActuate(&selector,4,true),"authored accepted repeat rejected");
        const auto h=OfflinePredictionStartRepeatFocus(&iterator,nullptr);check(h==host::handle,"authored coroutine handle changed");put(selector,0xb0,h);
        check(!host::failures,"authored positive startup failed");}
    void absent(){manager.objects.clear();frame.native.erase(11);frame.states.erase(11);}
    void restored(){manager.objects={&replacement};frame.native[11]={11,1,1};frame.states[11]=0;}
    void wait(){absent();const auto calls=host::originalNextCalls;const auto state=host::read<int32_t>(&iterator,0x10);const auto yield=host::read<uint32_t>(&iterator,0x14);
        check(OfflinePredictionRepeatFocusNext(&iterator,&host::nextMethod),"canonical absence did not remain pending");
        check(host::originalNextCalls==calls&&host::read<int32_t>(&iterator,0x10)==state&&host::read<uint32_t>(&iterator,0x14)==yield,"pending altered original step/state/yield");}
};
void pendingAndRefind(){Fixture f;f.start();f.wait();check(!host::read<void*>(&f.selector,0xa8)&&host::barriers==1,"pending did not clear cache through GC setter");
    check(focus::focusPendingIteration(&f.selector)&&focus::focusPendingEpoch(&f.selector)&&focus::focusPendingIterator(&f.selector)==&f.iterator,"pending receipt lost epoch/iterator");
    const auto calls=host::originalNextCalls;f.restored();check(OfflinePredictionRepeatFocusNext(&f.iterator,&host::nextMethod),"restored original iterator failed");
    check(host::originalNextCalls==calls+1&&host::lastActor==&f.replacement&&host::read<void*>(&f.selector,0xa8)==&f.replacement&&host::barriers==2,"refind did not GC-bind/call exact new admitted actor");
    check(!focus::focusPendingIteration(&f.selector),"refind left pending intent");++cases;}
void cancelAndSupersede(){Fixture f;f.start();f.wait();put(f.selector,0xa0,int32_t{-1});auto n=host::originalNextCalls;
    check(!OfflinePredictionRepeatFocusNext(&f.iterator,&host::nextMethod)&&host::originalNextCalls==n+1&&!focus::focusPendingIteration(&f.selector),"cancel did not delegate original once");++cases;
    put(f.selector,0xa0,int32_t{4});f.restored();check(OfflinePredictionFocusActuate(&f.selector,4,true),"new accepted epoch failed");put(f.otherIterator,0x10,int32_t{0});
    check(OfflinePredictionStartRepeatFocus(&f.otherIterator,nullptr)==host::handle,"new iterator failed");n=host::originalNextCalls;
    check(!OfflinePredictionRepeatFocusNext(&f.iterator,&host::nextMethod)&&host::originalNextCalls==n,"superseded iterator adopted new epoch");++cases;}
void worldAndMembershipRetirement(){
    {Fixture f;f.start();f.wait();host::world=0;auto n=host::originalNextCalls;
        check(!OfflinePredictionRepeatFocusNext(&f.iterator,&host::nextMethod)&&host::originalNextCalls==n,"retired owned iterator forwarded into old world");++cases;}
    {Fixture f;f.start();f.wait();f.source.ids.clear();f.logical.ids.clear();host::cameraOnNext=false;host::originalResult=false;
        auto n=host::originalNextCalls;check(!OfflinePredictionRepeatFocusNext(&f.iterator,&host::nextMethod)&&host::originalNextCalls==n+1&&
            !focus::focusPendingIteration(&f.selector),"changed logical group retained hidden pending intent");++cases;}}
void chooserAndPeriodicRetirement(){Fixture f;f.start();struct Vec3{float x,y,z;};Vec3 position{};
    check(focus::focusCandidate(&f.source,&position,nullptr)==11,"original chooser rejected current member");
    host::choice=0;f.manager.objects.push_back(&f.hq);
    check(focus::focusCandidate(&f.source,&position,nullptr)==UINT32_MAX&&!host::failures,"chooser selected own nonmember HQ");++cases;
    f.wait();const auto before=host::roots;focus::focusClearInactive();check(host::roots==before,"same-world cleanup released active roots");
    host::world=0;focus::focusClearInactive();check(host::roots+2==before&&focus::focusSession().pending.empty()&&
        !focus::focusSession().selector&&!focus::focusSession().iterator,"periodic retirement leaked focus roots without another iterator callback");
    const auto after=host::roots;focus::focusClearInactive();check(host::roots==after,"repeated periodic cleanup changed roots");++cases;}
void ownHQCannotBecomeFallback(){Fixture f;f.start();f.absent();f.manager.objects={&f.hq};put(f.selector,0xa8,static_cast<void*>(&f.hq));host::choice=0;
    auto n=host::originalNextCalls;check(OfflinePredictionRepeatFocusNext(&f.iterator,&host::nextMethod)&&host::originalNextCalls==n&&
        !host::read<void*>(&f.selector,0xa8)&&!host::failures,"own nonmember HQ was accepted as fallback");++cases;}
void positiveGuards(){for(int mode=0;mode<7;++mode){Fixture f;f.start();
    if(mode==0)put(f.unit,0x158,static_cast<void*>(nullptr));if(mode==1)put(f.unit,0x160,true);
    if(mode==2)f.frame.states[11]=6;if(mode==3)f.frame.native[11]={11,2,1};if(mode==4)put(f.frame,0x40,int32_t{113});
    if(mode==5)f.unit.truth=false;if(mode==6)f.unit.enabled=false;
    const auto cameras=host::originalCameraCalls;check(OfflinePredictionRepeatFocusNext(&f.iterator,&host::nextMethod)&&host::originalCameraCalls==cameras,"invalid physical/Unity actor reached camera");++cases;}}
void originalFailuresNoRetry(){Fixture f;f.start();f.wait();f.restored();host::throwNext=true;const auto n=host::originalNextCalls;
    check(!OfflinePredictionRepeatFocusNext(&f.iterator,&host::nextMethod)&&host::originalNextCalls==n+1&&host::failures==1&&
        !focus::focusForward&&!focus::focusCameraContext&&focus::focusSession().pending.empty(),"MoveNext failure retried/leaked forwarding context");++cases;
    check(!OfflinePredictionRepeatFocusNext(&f.iterator,&host::nextMethod)&&host::originalNextCalls==n+1,"failed owned iterator restarted");++cases;}
void changedCanonicalCannotAdoptNewToken(){Fixture f;f.start();f.wait();f.restored();host::fallbackOnNext=true;
    actors::state().identities[&f.replacement].incarnation=22;actors::state().admission.entities[11].incarnation=22;
    const auto calls=host::originalNextCalls,cameras=host::originalCameraCalls;
    check(OfflinePredictionRepeatFocusNext(&f.iterator,&host::nextMethod)&&host::originalNextCalls==calls+1&&
        host::originalCameraCalls==cameras&&!host::read<void*>(&f.selector,0xa8)&&host::read<int>(&f.iterator,0x10)==2,
        "changed canonical token was adopted by original fallback instead of ending old request");
    check(!OfflinePredictionRepeatFocusNext(&f.iterator,&host::nextMethod)&&host::originalNextCalls==calls+2&&
        host::originalCameraCalls==cameras&&host::read<int>(&f.selector,0xa0)==-1&&!focus::focusPendingIteration(&f.selector),
        "changed canonical request did not reach original eventual cancel");++cases;}
void deferredIteratorCannotReviveRetiredWorld(){Fixture f;host::deferStart=true;f.start();
    check(host::originalNextCalls==0&&host::read<int>(&f.iterator,0x10)==0,"authored deferred coroutine unexpectedly stepped");
    const auto rooted=host::roots;host::world=0;focus::focusClearInactive();const auto calls=host::originalNextCalls,cameras=host::originalCameraCalls;
    check(host::roots+2==rooted&&focus::focusWasRetired(&f.iterator),"retired weak identity retained strong scene roots or lost live iterator");
    check(!OfflinePredictionRepeatFocusNext(&f.iterator,&host::nextMethod)&&host::originalNextCalls==calls&&host::originalCameraCalls==cameras,
        "registered state0 iterator revived an already retired world through inactive forwarding");++cases;
    // Authored collection ends the old object's lifetime. Reusing this exact
    // address is a distinct object; no raw-pointer/state0 tombstone may block it.
    const auto freed=host::weakFreed;host::collect(&f.iterator);focus::focusPruneRetired();
    check(!focus::focusWasRetired(&f.iterator)&&host::weakFreed==freed+1&&focus::focusWeakStore().handles.empty(),
        "collected retired iterator did not release its weak identity");
    host::active=false;host::cameraOnNext=false;void* info=reinterpret_cast<void*>(uintptr_t{4321});
    check(OfflinePredictionRepeatFocusNext(&f.iterator,info)&&host::originalNextCalls==calls+1&&host::lastInfo==info&&
        host::lastIterator==&f.iterator&&host::roots+2==rooted,"collected address reuse did not delegate ordinary original exactly once");++cases;}
void inactiveForwarding(){Fixture f;host::active=false;host::cameraOnNext=false;void* info=reinterpret_cast<void*>(uintptr_t{1234});
    check(OfflinePredictionRepeatFocusNext(&f.otherIterator,info)&&host::originalNextCalls==1&&host::lastIterator==&f.otherIterator&&host::lastInfo==info,"inactive MoveNext arguments changed");
    check(OfflinePredictionFocusActuate(&f.selector,4,false)&&host::originalActuateCalls==1&&!host::lastInfo,"inactive Actuate did not preserve null MethodInfo");
    check(OfflinePredictionStartRepeatFocus(&f.otherIterator,info)==host::handle&&host::lastInfo==info,"inactive scheduler forwarding differs");
    OfflinePredictionControlGroupCamera(&f.camera,&f.unit,info);check(host::lastCamera==&f.camera&&host::lastActor==&f.unit&&host::lastInfo==info,"inactive camera forwarding differs");++cases;}
}
int main(){try{host::metadata();test::pendingAndRefind();test::cancelAndSupersede();test::worldAndMembershipRetirement();test::chooserAndPeriodicRetirement();test::ownHQCannotBecomeFallback();
    test::positiveGuards();test::originalFailuresNoRetry();test::changedCanonicalCannotAdoptNewToken();test::deferredIteratorCannotReviveRetiredWorld();test::inactiveForwarding();
    host::check(!host::roots,"authored focus roots leaked");host::check(host::weakTargets.empty()&&host::weakAllocated==host::weakFreed,"authored weak identity handles leaked");
    std::cout<<"focus adapter: "<<test::cases<<" actual-header authored cases PASS; no original DLL/game loaded\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
