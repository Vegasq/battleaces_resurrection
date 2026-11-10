// Authored fake-host tests of the ACTUAL actor source's binding/retirement flow.
// No original IL2CPP, Unity, Simulation DLL, game or worker is loaded.
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include <array>
#include <vector>
#include <string>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <iostream>
#include <map>
#include <memory>
#include <set>
#include <limits>
#ifndef BA_MOVEMENT_HEADER
#define BA_MOVEMENT_HEADER "../src/prediction_movement.hpp"
#endif
#include BA_MOVEMENT_HEADER

namespace host {
using Obj=void*;
struct Class;
struct Method {Obj function=nullptr;const char* name=nullptr;uint32_t token=0;Class* result=nullptr;uint32_t parameters=1;};
struct Class {std::string space,name;std::vector<Method*> methods;};
struct Field {size_t offset=0;};
struct Node {
    Class* klass=nullptr;
    std::array<unsigned char,0x220> bytes{};
    std::vector<uint32_t> values;
    std::map<uint32_t,uint32_t> components;
    std::map<std::string,Obj> calls;
    std::vector<Obj> objects;
    size_t cursor=0;
    unsigned disposed=0;
    bool unboxedReceiver=false;
};
static std::map<std::pair<std::string,std::string>,std::unique_ptr<Class>> classes;
static std::map<std::string,Field> fields;
static std::set<Obj> methodObjects;
static unsigned retirementPreflights=0;
static void check(bool ok,const char* reason){if(!ok)throw std::runtime_error(reason);}
static Class* type(const char* space,const char* name){
    const auto key=std::make_pair(std::string(space),std::string(name));
    auto& entry=classes[key];if(!entry)entry=std::make_unique<Class>(Class{space,name,{}});return entry.get();
}
template<class T>static void put(Node& node,size_t offset,T value){
    check(offset+sizeof(T)<=node.bytes.size(),"authored write bounds");
    memcpy(node.bytes.data()+offset,&value,sizeof(T));
}
template<class T>static T read(Obj object,size_t offset){
    check(object!=nullptr,"authored null read");
    if(methodObjects.count(object)){
        check(!offset && sizeof(T)==sizeof(Obj),"authored method pointer read");
        T result{};memcpy(&result,&static_cast<Method*>(object)->function,sizeof(T));return result;
    }
    auto& node=*static_cast<Node*>(object);T result{};
    check(offset+sizeof(T)<=node.bytes.size(),"authored read bounds");
    memcpy(&result,node.bytes.data()+offset,sizeof(T));return result;
}
static bool contains(Obj node,uint32_t id,Obj){return static_cast<Node*>(node)->components.count(id)!=0;}
static uint32_t item(Obj node,uint32_t id,Obj){return static_cast<Node*>(node)->components.at(id);}
static Method containsMethod,itemMethod,selectionContainsMethod,countMethod,valuesMethod,enumeratorMethod,moveNextMethod,currentMethod,disposeMethod;
static Node boxedBool,boxedInt;
static bool failEnumeration=false;
static void metadata(){
    auto uintType=type("System","UInt32");auto boolType=type("System","Boolean");
    containsMethod={reinterpret_cast<Obj>(&contains),"Contains",0x0600013c,boolType};
    itemMethod={reinterpret_cast<Obj>(&item),"get_Item",0x0600013d,uintType};
    methodObjects={&containsMethod,&itemMethod};
    type("Authored","ComponentBuffer")->methods={&containsMethod,&itemMethod};
    selectionContainsMethod={reinterpret_cast<Obj>(&contains),"Contains",0x060025b7,boolType};
    countMethod={reinterpret_cast<Obj>(&contains),"get_Count",0x06002dcc,type("System","Int32"),0};
    valuesMethod={reinterpret_cast<Obj>(&contains),"get_Values",0x06002dd0,nullptr,0};
    enumeratorMethod={reinterpret_cast<Obj>(&contains),"GetEnumerator",0x06002e18,nullptr,0};
    moveNextMethod={reinterpret_cast<Obj>(&contains),"MoveNext",0x06002e27,boolType,0};
    currentMethod={reinterpret_cast<Obj>(&contains),"get_Current",0x06002e28,nullptr,0};
    disposeMethod={reinterpret_cast<Obj>(&contains),"Dispose",0x06002e26,nullptr,0};
    for(auto* method:{&selectionContainsMethod,&countMethod,&valuesMethod,&enumeratorMethod,&moveNextMethod,&currentMethod,&disposeMethod})methodObjects.insert(method);
    type("Uncapped.Collections","UnitSelectionSet")->methods={&selectionContainsMethod};
    type("Authored","TypedSubsets")->methods={&countMethod,&valuesMethod};
    type("Authored","ValueCollection")->methods={&enumeratorMethod};
    type("Authored","ValueEnumerator")->methods={&moveNextMethod,&currentMethod,&disposeMethod};
    fields={{"_units",{0x10}},{"_entityIds",{0x18}},{"<EntityId>k__BackingField",{0x14c}},
            {"_fallbackArmyId",{0x150}},{"_entityConfig",{0x168}},{"UnitType",{0x10}},
            {"_allUnits",{0x18}},{"_subsetsByType",{0x20}},{"<Entities>k__BackingField",{0x10}},
            {"_dictionary",{0x10}},{"_previewSelectionSet",{0x88}},{"_selectionSet",{0x90}},
            {"_castingSet",{0x98}},{"_activeAbilityCaster",{0x100}}};
}
static Obj methods(Obj klass,void** iterator){
    const auto index=reinterpret_cast<uintptr_t>(*iterator);
    const auto& values=static_cast<Class*>(klass)->methods;
    if(index>=values.size())return nullptr;
    *iterator=reinterpret_cast<void*>(index+1);return values[index];
}
static Obj parent(Obj){return nullptr;}
static const char* methodName(Obj value){return static_cast<Method*>(value)->name;}
static uint32_t parameterCount(Obj value){return static_cast<Method*>(value)->parameters;}
static uint32_t methodToken(Obj value){return static_cast<Method*>(value)->token;}
static Obj parameter(Obj,uint32_t){return type("System","UInt32");}
static Obj resultType(Obj value){return static_cast<Method*>(value)->result;}
static Obj fromType(Obj value){return value;}
static size_t fieldOffset(Obj value){return static_cast<Field*>(value)->offset;}
static bool isValueType(Obj klass){return klass==type("Authored","ValueEnumerator");}
static void* unbox(Obj value){
    auto* node=static_cast<Node*>(value);
    if(isValueType(node->klass)){node->unboxedReceiver=true;return node;}
    return node->bytes.data();
}
static Obj boolean(bool value){put(boxedBool,0,value);return &boxedBool;}
static Obj integer(int value){put(boxedInt,0,value);return &boxedInt;}
struct Span {const uint32_t* values=nullptr;int count=0,padding=0;};
static Span* ids(Span* result,Obj receiver,Obj){
    const auto& values=static_cast<Node*>(receiver)->values;
    *result={values.data(),static_cast<int>(values.size()),0};return result;
}
}
namespace ba {
using Obj=void*;static DWORD initialThread=1;static Obj owner=nullptr;
template<class T>T api(const char* name){
    if(!strcmp(name,"il2cpp_class_get_methods"))return reinterpret_cast<T>(&host::methods);
    if(!strcmp(name,"il2cpp_class_get_parent"))return reinterpret_cast<T>(&host::parent);
    if(!strcmp(name,"il2cpp_method_get_name"))return reinterpret_cast<T>(&host::methodName);
    if(!strcmp(name,"il2cpp_method_get_param_count"))return reinterpret_cast<T>(&host::parameterCount);
    if(!strcmp(name,"il2cpp_method_get_token"))return reinterpret_cast<T>(&host::methodToken);
    if(!strcmp(name,"il2cpp_method_get_param"))return reinterpret_cast<T>(&host::parameter);
    if(!strcmp(name,"il2cpp_method_get_return_type"))return reinterpret_cast<T>(&host::resultType);
    if(!strcmp(name,"il2cpp_class_from_type"))return reinterpret_cast<T>(&host::fromType);
    if(!strcmp(name,"il2cpp_field_get_offset"))return reinterpret_cast<T>(&host::fieldOffset);
    if(!strcmp(name,"il2cpp_object_unbox"))return reinterpret_cast<T>(&host::unbox);
    if(!strcmp(name,"il2cpp_class_is_valuetype"))return reinterpret_cast<T>(&host::isValueType);
    throw std::runtime_error("unexpected authored metadata API");
}
template<class T>T native(uintptr_t rva){
    if(rva==0x3787d20)return reinterpret_cast<T>(&host::ids);
    throw std::runtime_error("unexpected original native call");
}
template<class T>T read(Obj object,size_t offset){return host::read<T>(object,offset);}
static bool flag(const wchar_t*){return false;}
static void init(){}static void log(const char*,...){}
static Obj klass(Obj object){return static_cast<host::Node*>(object)->klass;}
static Obj find_class(const char* space,const char* name){return host::type(space,name);}
static Obj field(Obj,const char* name){return &host::fields.at(name);}
static Obj call(Obj receiver,const char* name,int=0,void** =nullptr){return static_cast<host::Node*>(receiver)->calls.at(name);}
static Obj make(const char*,const char*){throw std::runtime_error("unexpected managed creation");}
template<class T>T get(Obj,const char*){
    ++host::retirementPreflights;
    throw std::runtime_error("authored stop: real retirement preflight reached");
}
}
namespace ba_local {
struct Root {void* value;explicit Root(void* pointer):value(pointer){}void* get()const{return value;}};
static int count(void* value){return static_cast<int>(static_cast<host::Node*>(value)->values.size());}
static void* invokeMethod(void* method,void* object,void** args){
    auto& node=*static_cast<host::Node*>(object);const auto token=static_cast<host::Method*>(method)->token;
    if(token==0x060025b7)return host::boolean(node.components.count(*static_cast<uint32_t*>(args[0]))!=0);
    if(token==0x06002dcc)return host::integer(static_cast<int>(node.objects.size()));
    if(token==0x06002dd0)return node.calls.at("values");
    if(token==0x06002e18){auto* result=static_cast<host::Node*>(node.calls.at("enumerator"));result->cursor=0;return result;}
    if(token==0x06002e27 || token==0x06002e28 || token==0x06002e26){
        host::check(node.unboxedReceiver,"boxed enumerator passed to original struct invocation");node.unboxedReceiver=false;
    }
    if(token==0x06002e27){if(host::failEnumeration)throw std::runtime_error("authored enumeration failure");return host::boolean(node.cursor<node.objects.size() && (++node.cursor,true));}
    if(token==0x06002e28)return node.objects.at(node.cursor-1);
    if(token==0x06002e26){++node.disposed;return nullptr;}
    throw std::runtime_error("unexpected original managed invocation");
}
}
namespace ba_prediction_worker {
bool movementEnabled(){return false;}uint64_t movementWorldId(){return 0;}
const std::string& movementMatchId(){static std::string empty;return empty;}
MovementAdmission movementAdmission(){return {};}
void movementFail(const char*)noexcept{}
}
#ifndef BA_ACTOR_SOURCE
#define BA_ACTOR_SOURCE "../src/prediction_actor_repair.cpp"
#endif
#include BA_ACTOR_SOURCE

namespace test {
namespace actors=ba_prediction_actors;
using host::check;using host::put;using host::Node;
struct Fixture {
    actors::State state;
    Node manager,frames,frame,position,type,army,active,activeArray,activeIDs,retained,retainedArray,retainedIDs,pending,actor,config;
    Fixture(int head=100,int confirmed=100){
        host::retirementPreflights=0;
        manager.klass=host::type("Uncapped","UnitManager");
        frame.klass=host::type("Uncapped.Collections.ComponentBuffers","SimFrameComponentBuffers");
        for(auto* set:{&active,&retained})set->klass=host::type("Uncapped.Collections","UnitSet");
        for(auto* ids:{&activeIDs,&retainedIDs,&pending})ids->klass=host::type("Uncapped.Collections","EntityIdSet");
        for(auto* component:{&position,&type,&army})component->klass=host::type("Authored","ComponentBuffer");
        actor.klass=host::type("Uncapped","Unit");config.klass=host::type("Uncapped","EntityConfig");
        put(active,0x10,static_cast<void*>(&activeArray));put(active,0x18,static_cast<void*>(&activeIDs));
        put(retained,0x10,static_cast<void*>(&retainedArray));put(retained,0x18,static_cast<void*>(&retainedIDs));
        put(manager,0x10,static_cast<void*>(&active));put(manager,0x18,static_cast<void*>(&pending));put(manager,0xa0,static_cast<void*>(&retained));
        frames.calls["get_Current"]=&frame;frame.calls["get_PositionBuffer"]=&position;
        frame.calls["get_TypeBuffer"]=&type;frame.calls["get_ArmyBuffer"]=&army;put(frame,0x40,head);
        state.admission.frame=confirmed;
        identity(7,75,0);current(7,75,0);admit(7,75,0,900);setActive(true);
    }
    void identity(uint32_t id,uint32_t kind,uint32_t side){
        put(actor,0x14c,id);put(actor,0x150,side);put(actor,0x168,static_cast<void*>(&config));put(config,0x10,kind);
    }
    void current(uint32_t id,uint32_t kind,uint32_t side){
        position.components={{id,1}};type.components={{id,kind}};army.components={{id,side}};
    }
    void admit(uint32_t id,uint32_t kind,uint32_t side,uint64_t token){state.admission.entities[id]={side,kind,token};}
    void setActive(bool present){
        put(activeIDs,0x10,present?1:0);put(activeArray,0x18,uintptr_t{1});put(activeArray,0x20,static_cast<void*>(&actor));
    }
    void cache(uint32_t id=7,uint32_t kind=75,uint32_t side=0,uint64_t token=0){state.identities[&actor]={{id,kind,side},token};}
    uint64_t token(){return state.identities.at(&actor).incarnation;}
    void repair(){actors::GroupChanges scopes;actors::repair(state,&manager,&frames,scopes);}
    void after(){actors::after(state,&manager,&frames);}
    void retirement(){
        bool stopped=false;try{repair();}catch(const std::exception& error){
            stopped=std::string(error.what())=="authored stop: real retirement preflight reached";
        }
        check(stopped && host::retirementPreflights==1,"cached/unqualified actor bypassed real retirement preflight");
    }
};
static void bootstrapOnlySeedsNewObservation(){
    for(int frame:{-1,100}){Fixture f(frame,frame);f.repair();f.after();
        check(f.token()==900 && !host::retirementPreflights,"first actually confirmed observation did not bind");}
}
static void cachedZeroAtSameFrameRetires(){
    Fixture f;f.cache();f.retirement();
    check(!f.token() && f.state.confirmedRecreation.count(7),"cached token0 silently promoted instead of scheduled recreation");
}
static void firstSeenAheadBeforeOriginalIsNotFresh(){
    Fixture f(101,100);f.retirement();check(!f.token(),"preexisting predicted actor was treated as original recreation");
}
static void newAfterOriginalBindsBoundedInterval(){
    for(int lead:{0,1,12}){Fixture f(100,100-lead);f.setActive(false);f.repair();
        f.setActive(true);f.after();check(f.token()==900,"new original actor did not bind qualified known identity");}
}
static void unqualifiedIntervalsDoNotBind(){
    for(const auto pair:{std::pair<int,int>{100,87},{100,101},{-2,-2},{100,-2},
                         {(std::numeric_limits<int>::max)(),-1}}){
        Fixture f(pair.first,pair.second);f.setActive(false);f.repair();f.setActive(true);f.after();
        check(!f.token(),"new original actor bound outside qualified confirmation interval");
    }
}
static void speculativeBirthThenConfirmationStillRetires(){
    Fixture f(105,100);f.state.admission.entities.clear();f.setActive(false);f.repair();f.setActive(true);f.after();
    check(!f.token(),"unknown speculative birth acquired an incarnation");
    f.state.admission.frame=105;f.admit(7,75,0,901);f.retirement();
    check(!f.token(),"later confirmation silently promoted cached speculative lifetime");
}
static void exactTypeArmyRequired(){
    for(const auto pair:{std::pair<uint32_t,uint32_t>{76,0},{75,1}}){
        Fixture f(105,100);f.state.admission.entities.clear();f.admit(7,pair.first,pair.second,900);
        f.setActive(false);f.repair();f.setActive(true);f.after();check(!f.token(),"fresh actor bound wrong type/army");
    }
}
static void poolAddressReuseNeedsAbsentOldID(){
    Fixture f(105,100);f.cache();f.identity(8,75,0);f.current(8,75,0);f.state.admission.entities.clear();f.admit(8,75,0,901);
    f.after();check(f.token()==901 && f.state.identities.at(&f.actor).identity.entityId==8,"validated new pool lifetime did not bind");
    Fixture bad(105,100);bad.cache();bad.identity(8,75,0);bad.current(8,75,0);
    bad.position.components[7]=1;bad.type.components[7]=75;bad.army.components[7]=0;
    bad.state.admission.entities.clear();bad.admit(8,75,0,901);bool refused=false;
    try{bad.after();}catch(const std::exception& error){refused=std::string(error.what())=="old actor ID remains present during ordinary pool-address reuse";}
    check(refused && bad.state.identities.at(&bad.actor).identity.entityId==7,"unsafe pool-address reuse mutated observer identity");
}
static void changedConfirmedTokenRetires(){Fixture f;f.cache(7,75,0,899);f.retirement();check(f.token()==899,"old nonzero incarnation was overwritten");}
static void absentUnchangedAndBoundActorsAreStable(){
    Fixture f(105,100);f.cache(7,75,0,900);f.repair();f.after();check(f.token()==900,"matching cached lifetime changed");
    f.setActive(false);f.current(8,75,0);f.after();check(f.state.identities.empty(),"absent actor cache was not pruned");
}
static void explicitRecreationCanReuseSamePointer(){
    Fixture f(105,100);f.cache();f.state.identities.erase(&f.actor);f.state.confirmedRecreation.insert(7);
    f.after();check(f.token()==900 && f.state.confirmedRecreation.empty(),"explicitly retired same-address new lifetime failed to bind");
}
static void cachedZeroCannotPromoteEvenWithKnownMapBeforeOriginal(){
    Fixture f(105,100);f.cache();f.retirement();check(!f.token(),"old speculative actor rebound to a known numeric ID");
}
struct Selection {
    Node set,all,allIDs,subsets,values,enumerator,typed,typedIDs;
    Selection(){
        set.klass=host::type("Uncapped.Collections","UnitSelectionSet");
        all.klass=typed.klass=host::type("Authored","LedUnitSet");
        allIDs.klass=typedIDs.klass=host::type("Uncapped.Collections","EntityIdSet");
        subsets.klass=host::type("Authored","TypedSubsets");values.klass=host::type("Authored","ValueCollection");
        enumerator.klass=host::type("Authored","ValueEnumerator");
        put(set,0x18,static_cast<void*>(&all));put(set,0x20,static_cast<void*>(&subsets));
        put(all,0x10,static_cast<void*>(&allIDs));put(typed,0x10,static_cast<void*>(&typedIDs));
        put(values,0x10,static_cast<void*>(&subsets));subsets.calls["values"]=&values;values.calls["enumerator"]=&enumerator;
        subsets.objects={&typed};enumerator.objects={&typed};setIDs({100},{100});
    }
    void setIDs(std::vector<uint32_t> main,std::vector<uint32_t> cached){
        allIDs.values=std::move(main);typedIDs.values=std::move(cached);set.components.clear();
        for(auto id:allIDs.values)set.components[id]=1;
    }
};
struct Interaction {
    Selection preview,current,casting;
    Node selector,oldActor,ability;
    std::vector<actors::Retire> retire;
    Interaction(){
        host::failEnumeration=false;selector.klass=host::type("Uncapped","UnitSelector");
        put(selector,0x88,static_cast<void*>(&preview.set));put(selector,0x90,static_cast<void*>(&current.set));
        put(selector,0x98,static_cast<void*>(&casting.set));put(selector,0x128,uint32_t{UINT32_MAX});
        retire.push_back({&oldActor,{7,75,0},{7,75,0},false});
    }
    void held(bool left,bool right){put(selector,0x16c,left);put(selector,0x16d,right);}
    void guard(){actors::guardRetiringInteractions(&selector,retire);}
    void refused(){bool denied=false;try{guard();}catch(const std::exception&){denied=true;}check(denied,"affected/unproven held gesture was allowed");}
    void unchanged(){for(auto* value:{&preview,&current,&casting}){
        check(value->allIDs.values==std::vector<uint32_t>{100} && value->typedIDs.values==std::vector<uint32_t>{100},"guard mutated an aliased selection");}}
};
static void unrelatedHeldButtonsPreserveSelectedUnits(){
    for(const auto pair:{std::pair<bool,bool>{true,false},{false,true},{true,true}}){
        Interaction f;f.held(pair.first,pair.second);f.guard();f.unchanged();
        check(ba::read<bool>(&f.selector,0x16c)==pair.first && ba::read<bool>(&f.selector,0x16d)==pair.second,"guard altered button state");
    }
}
static void affectedSelectionAndGhostSubsetsRefuse(){
    for(int set=0;set<3;++set)for(bool ghost:{false,true}){
        Interaction f;f.held(true,false);auto* selected=set==0?&f.preview:set==1?&f.current:&f.casting;
        selected->setIDs(ghost?std::vector<uint32_t>{100}:std::vector<uint32_t>{7},{7});f.refused();
        check(selected->typedIDs.values==std::vector<uint32_t>{7},"refusal cleared an aliased typed subset");
    }
}
static void affectedFocusAndRawClickRemainRefused(){
    Interaction focus;focus.held(false,true);put(focus.selector,0xa8,static_cast<void*>(&focus.oldActor));focus.refused();
    Interaction click;click.held(true,false);put(click.selector,0x128,uint32_t{7});click.refused();
}
static void unresolvedActiveCasterRefusesHeldOnly(){
    Interaction held;held.held(true,false);put(held.selector,0x100,static_cast<void*>(&held.ability));held.refused();
    Interaction idle;put(idle.selector,0x100,static_cast<void*>(&idle.ability));idle.guard();idle.unchanged();
}
static void boundsAndEnumeratorOwnerRefuse(){
    Interaction excessive;excessive.held(true,false);excessive.preview.subsets.objects.resize(8193,&excessive.preview.typed);excessive.refused();
    Interaction owner;owner.held(true,false);put(owner.preview.values,0x10,static_cast<void*>(&owner.current.subsets));owner.refused();
}
static void exceptionDisposesEnumeratorWithoutClearing(){
    Interaction f;f.held(true,false);host::failEnumeration=true;f.refused();host::failEnumeration=false;
    check(f.preview.enumerator.disposed==1,"failed readonly enumeration leaked/retried its scope");f.unchanged();
}
static void cachedSubsetValuesRequireExactLedClass(){
    Interaction f;f.held(false,true);f.preview.typed.klass=host::type("Authored","WrongSet");f.refused();
}
static void noButtonPathKeepsOriginalSelectedGuard(){
    Interaction f;f.preview.setIDs({7},{7});f.current.setIDs({7},{7});f.guard();
    check(!f.preview.enumerator.disposed && !f.current.enumerator.disposed,"idle path newly enumerated unrelated input");
}
static void allSubsetsAreInspectedAndBounded(){
    Interaction f;f.held(true,false);Node second,secondIDs;
    second.klass=f.preview.typed.klass;secondIDs.klass=f.preview.typedIDs.klass;secondIDs.values={7};put(second,0x10,static_cast<void*>(&secondIDs));
    f.preview.subsets.objects.push_back(&second);f.preview.enumerator.objects.push_back(&second);f.refused();
    check(secondIDs.values==std::vector<uint32_t>{7},"second ghost subset was mutated");
}
}
int main(){try{
    host::metadata();
    test::bootstrapOnlySeedsNewObservation();test::cachedZeroAtSameFrameRetires();
    test::firstSeenAheadBeforeOriginalIsNotFresh();test::newAfterOriginalBindsBoundedInterval();
    test::unqualifiedIntervalsDoNotBind();test::speculativeBirthThenConfirmationStillRetires();
    test::exactTypeArmyRequired();test::poolAddressReuseNeedsAbsentOldID();test::changedConfirmedTokenRetires();
    test::absentUnchangedAndBoundActorsAreStable();test::explicitRecreationCanReuseSamePointer();
    test::cachedZeroCannotPromoteEvenWithKnownMapBeforeOriginal();
    test::unrelatedHeldButtonsPreserveSelectedUnits();test::affectedSelectionAndGhostSubsetsRefuse();
    test::affectedFocusAndRawClickRemainRefused();test::unresolvedActiveCasterRefusesHeldOnly();
    test::boundsAndEnumeratorOwnerRefuse();test::exceptionDisposesEnumeratorWithoutClearing();
    test::cachedSubsetValuesRequireExactLedClass();test::noButtonPathKeepsOriginalSelectedGuard();test::allSubsetsAreInspectedAndBounded();
    std::cout<<"actor binding/held gesture:21 actual-source authored flow groups PASS; no Unity/IL2CPP/native engine execution\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
