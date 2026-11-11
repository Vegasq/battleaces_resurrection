// Authored fake-host tests of the ACTUAL actor source's binding/retirement flow.
// No original IL2CPP, Unity, Simulation DLL, game or worker is loaded.
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include <array>
#include <algorithm>
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
#include <functional>
#include <cmath>
#ifndef BA_MOVEMENT_HEADER
#define BA_MOVEMENT_HEADER "../src/prediction_movement.hpp"
#endif
#include BA_MOVEMENT_HEADER

namespace host {
using Obj=void*;
struct Class;
struct Method {Obj function=nullptr;const char* name=nullptr;uint32_t token=0;Class* result=nullptr;uint32_t parameters=1;uint32_t flags=0;Class* owner=nullptr;};
struct Class {std::string space,name;std::vector<Method*> methods;Class* declaring=nullptr;};
struct Field {size_t offset=0;Class* type=nullptr;Class* parent=nullptr;uint32_t flags=0;int32_t literal=0;};
struct Node {
    Class* klass=nullptr;
    std::array<unsigned char,0x220> bytes{};
    std::vector<uint32_t> values;
    std::map<uint32_t,uint32_t> components;
    std::map<uint32_t,Obj> typedBuckets;
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
static std::vector<std::string> interactionEvents;
static unsigned focusCalls=0;
static bool failFocusBefore=false,failFocusAfter=false,focusNoOp=false,failScopeBegin=false;
static Obj failedRoot=nullptr;
static Obj castingServer=nullptr,castingQueue=nullptr,expectedCasting=nullptr;
static unsigned queueLocks=0,castingClears=0;
static bool presentationOwned=false,failCastingClear=false;
static float clickNow=10.0f;
static unsigned clickClockCalls=0;static bool failClickClock=false,wrongClickBox=false;
static int32_t clickSingleSize=4,clickModeSize=4;
static std::map<std::string,Field> clickLiterals;
static uint64_t movementWorld=0;
static std::string movementMatch;
static std::function<void()> focusParameterHook;
static Obj currentSelector=nullptr;
static unsigned selectionRemovals=0;
static std::vector<uint32_t> removedSelectionIds;
static bool failSelectionRemoval=false,stopOnSelectionRemoval=false;
static unsigned groupRemovals=0,groupMarks=0,groupNotifications=0;
static bool failGroupRemove=false,leaveGroupTyped=false,failGroupMark=false,stopAfterGroupRemove=false;
static Obj expectedGroupHelper=nullptr;
static unsigned char groupRemoveCode[32]{},groupBeginCode[32]{},groupDisposeCode[8]{},groupMarkCode[32]{};
static unsigned char focusCode[]={0x3b,0x91,0xa0,0,0,0,0x75,0x59,0x83,0x3d,0x99,0x34,0x25,0x03,0,0x48,0x8d,0x91,0xa8,0,0,0,0x48,0xc7,0x02,0,0,0,0,0xc7,0x81,0xa0,0,0,0,0xff,0xff,0xff,0xff};
static unsigned char clearCode[]={0x48,0x89,0x5c,0x24,0x08,0x57,0x48,0x83,0xec,0x70,0x48,0x8b,0xd9,0x80,0x3d,0xb4};
static unsigned char clickClockCode[]={0x48,0x83,0xec,0x28,0x48,0x8b,0x05,0x0d,0xf8,0x5f,0x06,0x48,0x85,0xc0,0x75,0x18,0x48};
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
static Method containsMethod,itemMethod,selectionContainsMethod,countMethod,valuesMethod,enumeratorMethod,moveNextMethod,currentMethod,disposeMethod,focusMethod,scopeBeginMethod,scopeDisposeMethod,clearMethod,removeSelectionMethod,groupRemoveMethod,groupMarkMethod,clickTimeMethod,getTypedMethod,typedLookupMethod;
static unsigned char getTypedCode[16]{};
static Class* focusParameter=nullptr;
static Node boxedBool,boxedInt,boxedSingle;
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
    focusMethod={focusCode,"FocusControlGroupCancel",0x06002220,type("System","Void"),1};
    focusParameter=type("System","Int32");
    scopeBeginMethod={groupBeginCode,"BeginControlGroupChange",0x06001645,type("System","IDisposable"),1};
    scopeDisposeMethod={groupDisposeCode,"Dispose",0x060000cd,type("System","Void"),0};
    groupRemoveMethod={groupRemoveCode,"Remove",0x060025ab,boolType,1};
    groupMarkMethod={groupMarkCode,"MarkForFire",0x060000ce,type("System","Void"),0};
    clearMethod={clearCode,"Clear",0x060025ac,type("System","Void"),0};
    removeSelectionMethod={reinterpret_cast<Obj>(&contains),"RemoveSelection",0x0600220a,type("System","Void"),1};
    clickTimeMethod={clickClockCode,"get_realtimeSinceStartup",0x06001040,type("System","Single"),0,0x10};
    for(auto* method:{&selectionContainsMethod,&countMethod,&valuesMethod,&enumeratorMethod,&moveNextMethod,&currentMethod,&disposeMethod,&focusMethod,&scopeBeginMethod,&scopeDisposeMethod,&clearMethod})methodObjects.insert(method);
    type("Uncapped","UnitSelector")->methods={&focusMethod};
    methodObjects.insert(&removeSelectionMethod);
    methodObjects.insert(&groupRemoveMethod);methodObjects.insert(&groupMarkMethod);
    methodObjects.insert(&clickTimeMethod);type("UnityEngine","Time")->methods={&clickTimeMethod};
    methodObjects.insert(&scopeBeginMethod);methodObjects.insert(&scopeDisposeMethod);
    type("Uncapped.Collections","UnitSelectionSet")->methods={&selectionContainsMethod,&clearMethod,&groupRemoveMethod};
    type("Uncapped","ControlGroup")->methods={&scopeBeginMethod};
    type("Authored","GroupHelper")->methods={&scopeDisposeMethod,&groupMarkMethod};
    type("Authored","TypedSubsets")->methods={&countMethod,&valuesMethod};
    type("Authored","ValueCollection")->methods={&enumeratorMethod};
    type("Authored","ValueEnumerator")->methods={&moveNextMethod,&currentMethod,&disposeMethod};
    fields={{"_units",{0x10}},{"_entityIds",{0x18}},{"<EntityId>k__BackingField",{0x14c}},
            {"_fallbackArmyId",{0x150}},{"_entityConfig",{0x168}},{"UnitType",{0x10}},
            {"_allUnits",{0x18}},{"_subsetsByType",{0x20}},{"<Entities>k__BackingField",{0x10}},
            {"_dictionary",{0x10}},{"_previewSelectionSet",{0x88}},{"_selectionSet",{0x90}},
            {"_castingSet",{0x98}},{"_activeAbilityCaster",{0x100}},
            {"_repeatFocusUnit",{0xa8}},{"_focusChaseControlGroup",{0xa0}},
            {"_controlGroupChangeHelper",{0x40}},{"_queuedInputCommands",{0x180}},
            {"_unitManager",{0x40}},{"_controlGroupPanel",{0x38}},{"_controlGroups",{0x38}},
            {"_unitIDs",{0x20}},{"<ID>k__BackingField",{0x38}},{"_controlGroup",{0x18}},
            {"<IsSuspended>k__BackingField",{0x10}},{"_simFrames",{0x48}},
            {"_componentData",{0x158}},{"<DeadToTheSim>k__BackingField",{0x160}},
            {"_localPlayer",{0x90}},{"ArmyID",{0x38}},{"_simulation",{0x48}}};
    auto* selectorType=type("Uncapped","UnitSelector");auto* modeType=type("","DeferredClickMode");modeType->declaring=selectorType;
    fields["_doubleClickTime"]={0x28,type("System","Single"),selectorType};
    fields["_lastPointerUpTime"]={0x154,type("System","Single"),selectorType};
    fields["_doubleClickFirstClickReferenceUnitEntityId"]={0x128,uintType,selectorType};
    fields["_deferredClickMode"]={0x170,modeType,selectorType};
    fields["_isPointerDown"]={0x16c,boolType,selectorType};fields["_isContextPointerDown"]={0x16d,boolType,selectorType};
    fields["_isDragging"]={0x119,boolType,selectorType};
    clickLiterals={{"None",{0,modeType,modeType,0x56,0}},{"SingleClickOnMouseUp",{0,modeType,modeType,0x56,1}},
        {"DoubleClickOnMouseUp",{0,modeType,modeType,0x56,2}}};
    boxedSingle.klass=type("System","Single");
}
static Obj methods(Obj klass,void** iterator){
    const auto index=reinterpret_cast<uintptr_t>(*iterator);
    const auto& values=static_cast<Class*>(klass)->methods;
    if(index>=values.size())return nullptr;
    *iterator=reinterpret_cast<void*>(index+1);return values[index];
}
static Obj parent(Obj){return nullptr;}
static const char* className(Obj value){return static_cast<Class*>(value)->name.c_str();}
static const char* methodName(Obj value){return static_cast<Method*>(value)->name;}
static uint32_t parameterCount(Obj value){return static_cast<Method*>(value)->parameters;}
static uint32_t methodToken(Obj value){return static_cast<Method*>(value)->token;}
static uint32_t methodFlags(Obj value,uint32_t* implementation){*implementation=0;return static_cast<Method*>(value)->flags;}
static Obj parameter(Obj method,uint32_t index){
    if(method==&getTypedMethod){check(index==0,"authored typed view parameter index");return type("Uncapped","IntKey`1");}
    if(method==&typedLookupMethod){check(index<2,"authored typed lookup parameter index");return index?type("Authored","LedByRefType"):type("Uncapped","IntKey`1");}
    if(method==&focusMethod){if(focusParameterHook){auto hook=std::move(focusParameterHook);focusParameterHook={};hook();}return focusParameter;}
    return type("System",method==&scopeBeginMethod?"Boolean":"UInt32");
}
static Obj resultType(Obj value){return static_cast<Method*>(value)->result;}
static Obj fromType(Obj value){return value==type("Authored","LedByRefType")?type("","LedUnitSet"):value;}
static size_t fieldOffset(Obj value){return static_cast<Field*>(value)->offset;}
static Obj fieldType(Obj value){return static_cast<Field*>(value)->type;}
static Obj fieldParent(Obj value){return static_cast<Field*>(value)->parent;}
static uint32_t fieldFlags(Obj value){return static_cast<Field*>(value)->flags;}
static void staticFieldValue(Obj value,void* result){check(result!=nullptr,"authored literal output missing");memcpy(result,&static_cast<Field*>(value)->literal,4);}
static Obj declaringType(Obj value){return static_cast<Class*>(value)->declaring;}
static Obj classField(Obj value,const char* name){
    if(value!=type("","DeferredClickMode"))throw std::runtime_error("unexpected authored class field lookup");
    const auto found=clickLiterals.find(name);return found==clickLiterals.end()?nullptr:&found->second;
}
static bool isEnum(Obj value){return value==type("","DeferredClickMode");}
static Obj enumBase(Obj value){check(isEnum(value),"authored enum base lookup on another type");return type("System","Int32");}
static bool isValueType(Obj klass){return klass==type("Uncapped","IntKey`1")||klass==type("","SelectedEntitiesOfType")||klass==type("Authored","ValueEnumerator")||isEnum(klass)||
    klass==type("System","Single")||klass==type("System","Int32")||klass==type("System","UInt32")||klass==type("System","Boolean");}
static int32_t valueSize(Obj klass,uint32_t* alignment){
    if(klass==type("System","Boolean")){*alignment=1;return 1;}
    if(klass==type("System","Single")){*alignment=4;return clickSingleSize;}
    if(isEnum(klass)){*alignment=4;return clickModeSize;}
    check(klass==type("Uncapped","IntKey`1")||klass==type("System","UInt32")||klass==type("System","Int32")||klass==type("System","Single")||isEnum(klass),
        "unexpected authored scalar type");*alignment=4;return 4;
}
static void* unbox(Obj value){
    auto* node=static_cast<Node*>(value);
    if(node->klass==type("Authored","ValueEnumerator")){node->unboxedReceiver=true;return node;}
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
namespace host {
static unsigned controlGroupClears=0,trackedRemoves=0;
static unsigned char controlClearCode[16]{},suspendedCode[8]{},trackedRemoveCode[8]{};
static Method controlClearMethod{controlClearCode,"Clear",0x06001644,nullptr,0};
static Method suspendedMethod{suspendedCode,"get_IsSuspended",0x060000c7,nullptr,0};
static Method trackedRemoveMethod{trackedRemoveCode,"Remove",0x060000ad,nullptr,1};
}
namespace host {
static unsigned char ledCode[16]{},dirtyCode[16]{};
static Method ledMethod{ledCode,"Remove",0x060025c8,nullptr,1};
static Method dirtyMethod{dirtyCode,"MarkCountAsDirty",0x0600259a,nullptr,0};
static Method automaticMethod{reinterpret_cast<Obj>(&contains),"Add",0x060025aa,nullptr,1};
static unsigned dirtyCalls=0,ledCalls=0,automaticCalls=0;
static unsigned removeCurrentTypeRoutes=0,removeAbsentTypeRoutes=0;
static uint32_t lastRemoveType=UINT32_MAX;
static Obj failLed=nullptr,failLedAfter=nullptr,failDispose=nullptr;
static std::map<Obj,unsigned> dirtyBySet,ledByObject,disposeByHelper;
static std::function<void(Obj)> disposeHook,markHook,beginHook,lookupHook;
static bool removeLed(Node* led,uint32_t id){
    auto& values=read<Node*>(led,0x10)->values;auto found=std::find(values.begin(),values.end(),id);
    if(found==values.end())return false;
    *found=values.back();values.pop_back();
    if(read<uint32_t>(led,0x18)==id)put(*led,0x18,values.empty()?UINT32_MAX:values.front());
    return true;
}
static void addLed(Node* led,uint32_t id){
    auto& values=read<Node*>(led,0x10)->values;
    if(std::find(values.begin(),values.end(),id)==values.end())values.push_back(id);
    if(read<uint32_t>(led,0x18)==UINT32_MAX||read<uint32_t>(led,0x1c)==id)put(*led,0x18,id);
}
static const char* classNamespace(Obj value){return static_cast<Class*>(value)->space.c_str();}
static Obj methodOwner(Obj value){return static_cast<Method*>(value)->owner;}
// This separate authored type carrier maps to LedUnitSet under class_from_type
// while retaining the closed lookup's real out-byref metadata distinction.
static bool byref(Obj value){return value==type("Authored","LedByRefType");}
}
namespace ba {
static int lanSlot(){return 1;}
using Obj=void*;static DWORD initialThread=1;static Obj owner=nullptr;
template<class T>T api(const char* name){
    if(!strcmp(name,"il2cpp_class_get_namespace"))return reinterpret_cast<T>(&host::classNamespace);
    if(!strcmp(name,"il2cpp_method_get_declaring_type"))return reinterpret_cast<T>(&host::methodOwner);
    if(!strcmp(name,"il2cpp_type_is_byref"))return reinterpret_cast<T>(&host::byref);
    if(!strcmp(name,"il2cpp_class_get_methods"))return reinterpret_cast<T>(&host::methods);
    if(!strcmp(name,"il2cpp_class_get_parent"))return reinterpret_cast<T>(&host::parent);
    if(!strcmp(name,"il2cpp_class_get_name"))return reinterpret_cast<T>(&host::className);
    if(!strcmp(name,"il2cpp_method_get_name"))return reinterpret_cast<T>(&host::methodName);
    if(!strcmp(name,"il2cpp_method_get_param_count"))return reinterpret_cast<T>(&host::parameterCount);
    if(!strcmp(name,"il2cpp_method_get_token"))return reinterpret_cast<T>(&host::methodToken);
    if(!strcmp(name,"il2cpp_method_get_flags"))return reinterpret_cast<T>(&host::methodFlags);
    if(!strcmp(name,"il2cpp_method_get_param"))return reinterpret_cast<T>(&host::parameter);
    if(!strcmp(name,"il2cpp_method_get_return_type"))return reinterpret_cast<T>(&host::resultType);
    if(!strcmp(name,"il2cpp_class_from_type"))return reinterpret_cast<T>(&host::fromType);
    if(!strcmp(name,"il2cpp_field_get_offset"))return reinterpret_cast<T>(&host::fieldOffset);
    if(!strcmp(name,"il2cpp_field_get_type"))return reinterpret_cast<T>(&host::fieldType);
    if(!strcmp(name,"il2cpp_field_get_parent"))return reinterpret_cast<T>(&host::fieldParent);
    if(!strcmp(name,"il2cpp_field_get_flags"))return reinterpret_cast<T>(&host::fieldFlags);
    if(!strcmp(name,"il2cpp_field_static_get_value"))return reinterpret_cast<T>(&host::staticFieldValue);
    if(!strcmp(name,"il2cpp_class_get_declaring_type"))return reinterpret_cast<T>(&host::declaringType);
    if(!strcmp(name,"il2cpp_class_get_field_from_name"))return reinterpret_cast<T>(&host::classField);
    if(!strcmp(name,"il2cpp_class_enum_basetype"))return reinterpret_cast<T>(&host::enumBase);
    if(!strcmp(name,"il2cpp_object_unbox"))return reinterpret_cast<T>(&host::unbox);
    if(!strcmp(name,"il2cpp_class_is_valuetype"))return reinterpret_cast<T>(&host::isValueType);
    if(!strcmp(name,"il2cpp_class_is_enum"))return reinterpret_cast<T>(&host::isEnum);
    if(!strcmp(name,"il2cpp_class_value_size"))return reinterpret_cast<T>(&host::valueSize);
    throw std::runtime_error(std::string("unexpected authored metadata API: ")+name);
}
template<class T>T native(uintptr_t rva){
    if(rva==0x3c65810)return reinterpret_cast<T>(&host::getTypedCode[0]);
    if(rva==0x3c699b0)return reinterpret_cast<T>(&host::ledCode[0]);
    if(rva==0x3c63de0)return reinterpret_cast<T>(&host::dirtyCode[0]);
    if(rva==0x3ea5740)return reinterpret_cast<T>(&host::controlClearCode[0]);
    if(rva==0x90fd60)return reinterpret_cast<T>(&host::suspendedCode[0]);
    if(rva==0x3782570)return reinterpret_cast<T>(&host::trackedRemoveCode[0]);

    if(rva==0x3787d20)return reinterpret_cast<T>(&host::ids);
    if(rva==0x3bf2fa0)return reinterpret_cast<T>(&host::focusCode[0]);
    if(rva==0x3c66c50)return reinterpret_cast<T>(&host::clearCode[0]);
    if(rva==0x3c66610)return reinterpret_cast<T>(&host::groupRemoveCode[0]);
    if(rva==0x3ea5790)return reinterpret_cast<T>(&host::groupBeginCode[0]);
    if(rva==0x3b02160)return reinterpret_cast<T>(&host::groupDisposeCode[0]);
    if(rva==0x3b02170)return reinterpret_cast<T>(&host::groupMarkCode[0]);
    if(rva==0x8656b0)return reinterpret_cast<T>(&host::clickClockCode[0]);
    throw std::runtime_error("unexpected original native call");
}
template<class T>T read(Obj object,size_t offset){return host::read<T>(object,offset);}
static bool flag(const wchar_t*){return false;}
static void init(){}static void log(const char*,...){}
static Obj klass(Obj object){return static_cast<host::Node*>(object)->klass;}
static Obj find_class(const char* space,const char* name){return host::type(space,name);}
static Obj field(Obj receiver,const char* name){
    static host::Field groupManager{0x60};
    if(!strcmp(name,"_dictionary")){
        static std::map<Obj,host::Field> dictionaries;
        auto& member=dictionaries[klass(receiver)];member={0x10,host::type("System.Collections.Generic","Dictionary`2"),static_cast<host::Class*>(klass(receiver))};return &member;
    }

    if(!strcmp(name,"_unitManager") && klass(receiver)==host::type("Uncapped","ControlGroup"))return &groupManager;
    return &host::fields.at(name);
}
static Obj call(Obj receiver,const char* name,int=0,void** =nullptr){return static_cast<host::Node*>(receiver)->calls.at(name);}
static Obj make(const char*,const char*){throw std::runtime_error("unexpected managed creation");}
template<class T>T get(Obj,const char*){
    if(host::currentSelector)return static_cast<T>(host::currentSelector);
    ++host::retirementPreflights;
    throw std::runtime_error("authored stop: real retirement preflight reached");
}
}
namespace ba_local {
struct Root {void* value;explicit Root(void* pointer):value(pointer){}void* get()const{return value==host::failedRoot?nullptr:value;}};
static DWORD updateThread=1;
inline void* server(){return host::castingServer;}
inline bool isTarget(void* value){return value && value==host::castingServer;}
struct QueueLock {
    QueueLock(){host::check(!host::queueLocks,"recursive queue lock");++host::queueLocks;host::interactionEvents.push_back("lock");}
    ~QueueLock(){--host::queueLocks;host::interactionEvents.push_back("unlock");}
};
static int count(void* value){
    if(value==host::castingQueue)host::check(host::queueLocks==1,"pending command count read outside producer lock");
    return static_cast<int>(static_cast<host::Node*>(value)->values.size());
}
static void* invokeMethod(void* method,void* object,void** args){
    const auto token=static_cast<host::Method*>(method)->token;
    if(token==0x060025a1)throw std::runtime_error("filtered GetUnitsOfType must never be invoked by raw ownership query");
    if(token==0x06002de7){
        host::check(object&&ba::klass(object)==host::type("System.Collections.Generic","Dictionary`2")&&args&&args[0]&&args[1],
            "authored closed typed lookup owner/key/out ABI");
        if(host::lookupHook)host::lookupHook(object);
        const auto& entries=static_cast<host::Node*>(object)->typedBuckets;const auto found=entries.find(*static_cast<uint32_t*>(args[0]));
        *static_cast<host::Obj*>(args[1])=found==entries.end()?nullptr:found->second;return host::boolean(found!=entries.end());
    }
    if(token==0x0600259a){++host::dirtyCalls;++host::dirtyBySet[object];host::interactionEvents.push_back("dirty");host::put(*static_cast<host::Node*>(object),0x54,int32_t{-1});return nullptr;}
    if(token==0x060025c8){
        ++host::ledCalls;++host::ledByObject[object];host::interactionEvents.push_back("ledRemove");
        if(object==host::failLed)throw std::runtime_error("injected original Led.Remove failure");
        const bool removed=host::removeLed(static_cast<host::Node*>(object),*static_cast<uint32_t*>(args[0]));
        if(object==host::failLedAfter)throw std::runtime_error("injected original Led.Remove failure after mutation");
        return host::boolean(removed);
    }
    if(token==0x060025aa){
        ++host::automaticCalls;host::interactionEvents.push_back("originalAutomaticAdd");
        auto* selected=static_cast<host::Node*>(object);const auto id=*static_cast<uint32_t*>(args[0]);
        auto* all=host::read<host::Node*>(selected,0x18);auto& ids=host::read<host::Node*>(all,0x10)->values;
        if(std::find(ids.begin(),ids.end(),id)!=ids.end())return host::boolean(false);
        host::addLed(all,id);auto* bucket=static_cast<host::Node*>(selected->calls.at("newTypeBucket"));
        auto* dictionary=host::read<host::Node*>(selected,0x20);
        if(std::find(dictionary->objects.begin(),dictionary->objects.end(),bucket)==dictionary->objects.end())dictionary->objects.push_back(bucket);
        dictionary->typedBuckets[76]=bucket;
        host::addLed(bucket,id);selected->components[id]=1;host::put(*selected,0x54,int32_t{-1});host::put(*selected,0x10,true);return host::boolean(true);
    }

    // Original API stubs from pinned original3ea5740: clear WHOLE selected set,
    // then MarkForFire. This does not implement the GroupChanges policy/oracle.
    if(token==0x060000c7)return host::boolean(host::read<bool>(object,0x10));
    if(token==0x060000ad){
        ++host::trackedRemoves;host::interactionEvents.push_back("trackedRemove");
        auto& values=static_cast<host::Node*>(object)->values;const auto id=*static_cast<uint32_t*>(args[0]);
        const auto before=values.size();values.erase(std::remove(values.begin(),values.end(),id),values.end());
        return host::boolean(values.size()!=before);
    }
    if(token==0x06001644){throw std::runtime_error("unexpected whole ControlGroup.Clear");
        ++host::controlGroupClears;host::interactionEvents.push_back("controlGroupClear");
        host::check(host::expectedGroupHelper&&host::read<bool>(host::expectedGroupHelper,0x10),"ControlGroup.Clear outside original scope");
        auto* selected=host::read<host::Node*>(object,0x20);
        auto clearLed=[](host::Node* led){host::read<host::Node*>(led,0x10)->values.clear();};
        clearLed(host::read<host::Node*>(selected,0x18));selected->components.clear();
        for(auto value:host::read<host::Node*>(selected,0x20)->objects)clearLed(static_cast<host::Node*>(value));
        ++host::groupMarks;host::put(*static_cast<host::Node*>(host::expectedGroupHelper),0x12,true);return nullptr;
    }

    if(token==0x06001040){
        host::check(!object&&!args&&!host::queueLocks,"authored Single clock invocation ABI/lock differs");++host::clickClockCalls;
        if(host::failClickClock)throw std::runtime_error("authored original clock failure");
        host::boxedSingle.klass=host::type("System",host::wrongClickBox?"Int32":"Single");host::put(host::boxedSingle,0,host::clickNow);return &host::boxedSingle;
    }
    auto& node=*static_cast<host::Node*>(object);
    if(token==0x0600220a){
        host::check(object==host::currentSelector && args && args[0],"original removal owner/batch missing");
        ++host::selectionRemovals;host::interactionEvents.push_back("removeSelection");
        host::removedSelectionIds=host::read<host::Node*>(args[0],0x18)->values;
        if(host::stopOnSelectionRemoval)host::movementWorld=0;
        if(host::failSelectionRemoval)throw std::runtime_error("authored original selection callback failure");
        return nullptr;
    }
    if(token==0x06002220){
        host::check(!host::queueLocks,"focus callback entered with producer SRW held");
        ++host::focusCalls;host::interactionEvents.push_back("focus");
        if(host::failFocusBefore)throw std::runtime_error("authored original focus failure before clear");
        host::check(args && args[0],"focus group argument missing");
        const auto group=*static_cast<int32_t*>(args[0]);
        if(!host::focusNoOp && group==host::read<int32_t>(object,0xa0)){
            host::put(node,0xa8,static_cast<void*>(nullptr));host::put(node,0xa0,int32_t{-1});
        }
        if(host::failFocusAfter)throw std::runtime_error("authored original focus failure after clear");
        return nullptr;
    }
    if(token==0x06001645){
        host::check(!host::queueLocks,"group callback entered with producer SRW held");
        host::interactionEvents.push_back("begin");
        host::check(args && !*static_cast<bool*>(args[0]),"group scope incorrectly player initiated");
        auto* helper=host::read<host::Node*>(object,0x40);host::put(*helper,0x10,true);
        host::put(*helper,0x12,false);
        if(host::beginHook)host::beginHook(object);
        if(host::failScopeBegin)throw std::runtime_error("authored original group begin failure");
        return helper;
    }
    if(token==0x060000cd){
        ++host::disposeByHelper[object];host::interactionEvents.push_back("dispose");
        host::check(host::read<bool>(object,0x10),"scope disposed without begin");
        if(host::read<bool>(object,0x12)){++host::groupNotifications;host::put(node,0x12,false);}
        host::put(node,0x10,false);++node.disposed;if(host::disposeHook)host::disposeHook(object);
        if(object==host::failDispose)throw std::runtime_error("injected original Dispose failure");return nullptr;
    }
    if(token==0x060025ab){
        host::check(args && args[0],"original UnitSelectionSet.Remove argument missing");
        ++host::groupRemovals;host::interactionEvents.push_back("groupRemove");
        if(host::failGroupRemove)throw std::runtime_error("authored original group Remove failure");
        const auto id=*static_cast<uint32_t*>(args[0]);
        auto erase=[&](host::Node* led){return host::removeLed(led,id);};
        const bool removed=erase(host::read<host::Node*>(object,0x18));node.components.erase(id);
        if(removed) {
            // Faithful external original3c66610 routing: after all-Led removal,
            // invalidate count, then use ONLY the current-type bucket if type
            // resolves. The absent-type fallback stops at its first success.
            host::put(node,0x54,int32_t{-1});
            auto* dictionary=host::read<host::Node*>(object,0x20);
            auto* frames=host::read<host::Node*>(object,0x48);host::Node* types=nullptr;
            if(frames){auto* frame=static_cast<host::Node*>(frames->calls.at("get_Current"));types=static_cast<host::Node*>(frame->calls.at("get_TypeBuffer"));}
            const auto currentType=types?types->components.find(id):std::map<uint32_t,uint32_t>::const_iterator{};
            if(types && currentType!=types->components.end()) {
                ++host::removeCurrentTypeRoutes;host::lastRemoveType=currentType->second;
                const auto bucket=dictionary->typedBuckets.find(currentType->second);
                if(!host::leaveGroupTyped && bucket!=dictionary->typedBuckets.end())erase(static_cast<host::Node*>(bucket->second));
            } else {
                ++host::removeAbsentTypeRoutes;
                if(!host::leaveGroupTyped)for(auto value:dictionary->objects)if(erase(static_cast<host::Node*>(value)))break;
            }
        }
        if(host::stopAfterGroupRemove)host::movementWorld=0;
        return host::boolean(removed);
    }
    if(token==0x060000ce){
        host::check(host::read<bool>(object,0x10),"group MarkForFire outside original scope");
        ++host::groupMarks;host::interactionEvents.push_back("mark");
        if(host::markHook)host::markHook(object);
        if(host::failGroupMark)throw std::runtime_error("authored original group notification failure");
        host::put(node,0x12,true);return nullptr;
    }
    if(token==0x060025ac){
        host::check(object==host::expectedCasting && host::queueLocks==1,"Clear used wrong set or producer lock");
        host::check(static_cast<host::Node*>(host::castingQueue)->values.empty(),"Clear changed a set with queued aliases");
        ++host::castingClears;host::interactionEvents.push_back("clear");
        if(host::failCastingClear)throw std::runtime_error("authored original casting Clear failure");
        auto clearLed=[](host::Node* led){host::read<host::Node*>(led,0x10)->values.clear();};
        clearLed(host::read<host::Node*>(object,0x18));node.components.clear();
        for(auto value:host::read<host::Node*>(object,0x20)->objects)clearLed(static_cast<host::Node*>(value));
        return nullptr;
    }
    if(token==0x0600013d)return host::integer(static_cast<int>(node.components.at(*static_cast<uint32_t*>(args[0]))));
    if(token==0x060025b7)return host::boolean(node.components.count(*static_cast<uint32_t*>(args[0]))!=0);
    if(token==0x06002dcc)return host::integer(static_cast<int>(node.objects.size()));
    if(token==0x06002dd0)return node.calls.at("values");
    if(token==0x06002e18){auto* result=static_cast<host::Node*>(node.calls.at("enumerator"));result->cursor=0;result->objects=host::read<host::Node*>(object,0x10)->objects;return result;}
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
bool movementEnabled(){return false;}uint64_t movementWorldId(){return host::movementWorld;}
const std::string& movementMatchId(){return host::movementMatch;}
MovementAdmission movementAdmission(){return {};}
void movementFail(const char*)noexcept{}
}
namespace ba_prediction_movement {bool ownsPresentation(void*){return host::presentationOwned;}}
#ifndef BA_ACTOR_SOURCE
#define BA_ACTOR_SOURCE "../src/prediction_actor_repair.cpp"
#endif
#include BA_ACTOR_SOURCE

namespace scope_test {
using host::Node;using host::put;using host::check;namespace actors=ba_prediction_actors;
static void metadata(){
    host::metadata();auto* selection=host::type("Uncapped.Collections","UnitSelectionSet");
    auto* led=host::type("","LedUnitSet");led->declaring=selection;
    auto* dictionary=host::type("System.Collections.Generic","Dictionary`2");dictionary->methods={&host::countMethod,&host::valuesMethod,&host::typedLookupMethod};
    auto* boolean=host::type("System","Boolean");auto* integer=host::type("System","Int32");auto* uint=host::type("System","UInt32");auto* nothing=host::type("System","Void");
    auto* values=host::type("Authored","ValueCollection");auto* iterator=host::type("Authored","ValueEnumerator");
    host::ledMethod.result=boolean;host::ledMethod.owner=led;led->methods={&host::ledMethod};
    host::dirtyMethod.result=nothing;host::dirtyMethod.owner=selection;
    host::automaticMethod.result=boolean;host::automaticMethod.owner=selection;
    auto* typedView=host::type("","SelectedEntitiesOfType");typedView->declaring=selection;
    host::getTypedMethod={host::getTypedCode,"GetUnitsOfType",0x060025a1,typedView,1,0,selection};
    host::typedLookupMethod={reinterpret_cast<void*>(&host::contains),"TryGetValue",0x06002de7,boolean,2,0,dictionary};
    selection->methods.push_back(&host::getTypedMethod);
    selection->methods.push_back(&host::dirtyMethod);selection->methods.push_back(&host::automaticMethod);
    host::valuesMethod.result=values;host::enumeratorMethod.result=iterator;host::currentMethod.result=led;host::disposeMethod.result=nothing;
    host::controlClearMethod.result=nothing;host::suspendedMethod.result=boolean;host::trackedRemoveMethod.result=boolean;
    host::type("Uncapped","ControlGroup")->methods.push_back(&host::controlClearMethod);
    host::type("Authored","GroupHelper")->methods.push_back(&host::suspendedMethod);
    host::type("Uncapped.Collections","EntityIdSet")->methods={&host::trackedRemoveMethod};
    for(auto* method:{&host::ledMethod,&host::dirtyMethod,&host::automaticMethod,&host::controlClearMethod,&host::suspendedMethod,&host::trackedRemoveMethod,&host::getTypedMethod,&host::typedLookupMethod})host::methodObjects.insert(method);
    host::fields["_allUnits"]={0x18,led,selection};host::fields["_subsetsByType"]={0x20,dictionary,selection};
    host::fields["<Entities>k__BackingField"]={0x10,host::type("Uncapped.Collections","EntityIdSet"),led};
    host::fields["<Leader>k__BackingField"]={0x18,uint,led};host::fields["_lastKnownLeaderId"]={0x1c,uint,led};
    host::fields["<OnlyHQSelected>k__BackingField"]={0x58,boolean,selection};host::fields["_recomputeOverallLeader"]={0x10,boolean,selection};
    host::fields["_lastFrameCountRecalculated"]={0x54,integer,selection};
    host::fields["_trackedReleasedUnits"]={0x10};host::fields["_autoAssignments"]={0x30};
    host::boxedBool.klass=boolean;host::boxedInt.klass=integer;
    host::dirtyCalls=host::ledCalls=host::automaticCalls=host::controlGroupClears=host::trackedRemoves=0;
    host::removeCurrentTypeRoutes=host::removeAbsentTypeRoutes=0;host::lastRemoveType=UINT32_MAX;
    host::groupRemovals=host::groupMarks=host::groupNotifications=0;host::failGroupRemove=host::leaveGroupTyped=host::stopAfterGroupRemove=false;host::dirtyBySet.clear();host::ledByObject.clear();host::disposeByHelper.clear();
    host::failLed=host::failLedAfter=host::failDispose=nullptr;host::disposeHook={};host::markHook={};host::beginHook={};host::lookupHook={};host::failGroupMark=false;host::failScopeBegin=false;
    host::interactionEvents.clear();host::failedRoot=nullptr;host::failEnumeration=false;
}
struct Selection {
    Node set,all,allIds,dictionary,values,iterator,oldType,oldIds,newType,newIds;
    Selection(uint32_t unaffected){
        set.klass=host::type("Uncapped.Collections","UnitSelectionSet");all.klass=oldType.klass=newType.klass=host::type("","LedUnitSet");
        allIds.klass=oldIds.klass=newIds.klass=host::type("Uncapped.Collections","EntityIdSet");
        dictionary.klass=host::type("System.Collections.Generic","Dictionary`2");values.klass=host::type("Authored","ValueCollection");iterator.klass=host::type("Authored","ValueEnumerator");
        put(set,0x18,static_cast<void*>(&all));put(set,0x20,static_cast<void*>(&dictionary));
        put(all,0x10,static_cast<void*>(&allIds));put(oldType,0x10,static_cast<void*>(&oldIds));put(newType,0x10,static_cast<void*>(&newIds));
        allIds.values=oldIds.values={7,unaffected};set.components={{7,1},{unaffected,1}};
        for(auto* value:{&all,&oldType,&newType}){put(*value,0x18,value==&newType?UINT32_MAX:uint32_t{7});put(*value,0x1c,UINT32_MAX);}
        put(values,0x10,static_cast<void*>(&dictionary));put(iterator,0x10,static_cast<void*>(&dictionary));
        dictionary.calls["values"]=&values;dictionary.objects={&oldType};dictionary.typedBuckets[75]=&oldType;
        values.calls["enumerator"]=&iterator;set.calls["newTypeBucket"]=&newType;
    }
};
struct Fixture {
    actors::State state;Node manager,simulation,frames,frame,position,type,army,selector,panel,array;
    Node group0,group1,helper0,helper1,tracked0,tracked1,rules0,rules1,actor,config;
    Selection first{99},second{100};std::vector<actors::Retire> retired;
    Fixture(){
        metadata(); // Class addresses are stable across fixture construction.
        // Selection members were constructed before metadata; refresh methods/fields only.
        manager.klass=host::type("Uncapped","UnitManager");simulation.klass=host::type("Uncapped","Simulation");
        selector.klass=host::type("Uncapped","UnitSelector");panel.klass=host::type("Uncapped","ControlGroupPanel");
        frame.klass=host::type("Uncapped.Collections.ComponentBuffers","SimFrameComponentBuffers");
        position.klass=type.klass=army.klass=host::type("Authored","ComponentBuffer");
        group0.klass=group1.klass=host::type("Uncapped","ControlGroup");helper0.klass=helper1.klass=host::type("Authored","GroupHelper");
        tracked0.klass=tracked1.klass=host::type("Uncapped.Collections","EntityIdSet");tracked0.values={7,99};tracked1.values={7,100};
        rules0.values=rules1.values={75};actor.klass=host::type("Uncapped","Unit");config.klass=host::type("Uncapped","EntityConfig");
        put(actor,0x14c,uint32_t{7});put(actor,0x150,uint32_t{0});put(actor,0x168,static_cast<void*>(&config));put(config,0x10,uint32_t{75});
        put(simulation,0x148,static_cast<void*>(&frames));put(simulation,0x70,static_cast<void*>(&manager));put(manager,0x40,static_cast<void*>(&simulation));
        frames.calls["get_Current"]=&frame;frame.calls["get_PositionBuffer"]=&position;frame.calls["get_TypeBuffer"]=&type;frame.calls["get_ArmyBuffer"]=&army;put(frame,0x40,int32_t{110});
        put(selector,0x40,static_cast<void*>(&manager));put(selector,0x38,static_cast<void*>(&panel));put(selector,0x138,static_cast<void*>(&simulation));
        put(panel,0x38,static_cast<void*>(&array));put(array,0x18,uintptr_t{2});put(array,0x20,static_cast<void*>(&group0));put(array,0x28,static_cast<void*>(&group1));
        setup(group0,helper0,tracked0,rules0,first,0);setup(group1,helper1,tracked1,rules1,second,1);
        ba::initialThread=ba_local::updateThread=GetCurrentThreadId();state.thread=GetCurrentThreadId();state.world=93;state.match=std::string(32,'g');state.inUpdate=true;
        state.manager=std::make_unique<ba_local::Root>(&manager);state.simulation=std::make_unique<ba_local::Root>(&simulation);state.groupGeneration=1;state.groupIntent.reset(1);
        host::movementWorld=state.world;host::movementMatch=state.match;host::presentationOwned=true;host::currentSelector=&selector;
        retired={{&actor,{7,75,0},{7,76,0},false,900}};
    }
    void setup(Node& group,Node& helper,Node& tracked,Node& rules,Selection& selected,uint32_t id){
        put(group,0x10,static_cast<void*>(&tracked));put(group,0x20,static_cast<void*>(&selected.set));put(group,0x30,static_cast<void*>(&rules));put(group,0x38,id);
        put(group,0x40,static_cast<void*>(&helper));put(group,0x48,static_cast<void*>(&simulation));put(group,0x60,static_cast<void*>(&manager));put(helper,0x18,static_cast<void*>(&group));put(selected.set,0x48,static_cast<void*>(&frames));
    }
    void prepare(actors::GroupChanges& changes,bool both=false){changes.prepare(both?std::vector<void*>{&group0,&group1}:std::vector<void*>{&group0},retired,&state);changes.begin();changes.mutated=true;}
    void automatic(){check(!host::read<bool>(&helper0,0x10),"ControlGroup.eventSuspender is suspended in ControlGroup.UnitManager_UnitsInitialized and shouldn't be!");uint32_t id=7;void* args[]={&id};actors::invoke(&host::automaticMethod,&first.set,args);}
    void manual(uint32_t id){void* args[]={&id};actors::invoke(&host::groupRemoveMethod,&first.set,args);}
};
struct CanonicalGroup {
    Selection empty2{101},empty3{102},selected{99};
    Node group2,group3,group,helper2,helper3,helper,tracked2,tracked3,tracked,rules2,rules3,rules;
    explicit CanonicalGroup(Fixture& f) {
        for(auto* value:{&group2,&group3,&group})value->klass=host::type("Uncapped","ControlGroup");
        for(auto* value:{&helper2,&helper3,&helper})value->klass=host::type("Authored","GroupHelper");
        for(auto* value:{&tracked2,&tracked3,&tracked})value->klass=host::type("Uncapped.Collections","EntityIdSet");
        for(auto* value:{&empty2,&empty3}) {
            value->allIds.values.clear();value->oldIds.values.clear();
            put(value->all,0x18,UINT32_MAX);put(value->oldType,0x18,UINT32_MAX);
        }
        tracked.values={7,99};
        f.setup(group2,helper2,tracked2,rules2,empty2,2);f.setup(group3,helper3,tracked3,rules3,empty3,3);
        f.setup(group,helper,tracked,rules,selected,4);put(group,0x30,static_cast<void*>(nullptr));
        put(f.array,0x18,uintptr_t{5});put(f.array,0x30,static_cast<void*>(&group2));
        put(f.array,0x38,static_cast<void*>(&group3));put(f.array,0x40,static_cast<void*>(&group));
        f.position.components[7]=1;f.type.components[7]=75;f.army.components[7]=0;
        f.state.admission.frame=110;f.state.admission.entities[7]={0,75,900};
        f.state.groupIntent.remember(1,{4,7},{75,0,900});
        put(f.config,0x10,uint32_t{76});f.state.identities[&f.actor]={{7,76,0},0};
        f.retired={{&f.actor,{7,76,0},{7,75,0},false,0}};
    }
    void prepare(Fixture& f,actors::GroupChanges& changes,bool both=false) {
        changes.prepare(both?std::vector<void*>{&group,&f.group1}:std::vector<void*>{&group},f.retired,&f.state);
        changes.begin();changes.mutated=true;
    }
};
struct CanonicalLoss:CanonicalGroup {
    Node units,unitArray,unitIds;
    explicit CanonicalLoss(Fixture& f):CanonicalGroup(f) {
        units.klass=host::type("Uncapped.Collections","UnitSet");unitIds.klass=host::type("Uncapped.Collections","EntityIdSet");
        put(units,0x10,static_cast<void*>(&unitArray));put(units,0x18,static_cast<void*>(&unitIds));
        put(unitIds,0x10,int32_t{0});put(unitArray,0x18,uintptr_t{0});put(f.manager,0x10,static_cast<void*>(&units));
        f.type.components[7]=76;f.state.admission.entities[7]={0,76,901};
        selected.dictionary.objects.push_back(&selected.newType);selected.dictionary.typedBuckets[76]=&selected.newType;
    }
};
static void exact(Node& values,std::vector<uint32_t> expected){auto actual=values.values;std::sort(actual.begin(),actual.end());std::sort(expected.begin(),expected.end());check(actual==expected,"scope raw membership differs");}
static void refused(const std::function<void()>& operation){bool rejected=false;try{operation();}catch(const std::exception&){rejected=true;}check(rejected,"actual scope refused contract was accepted");}
static unsigned cases=0;
static void run(const char* name,const std::function<void(Fixture&)>& body){Fixture f;try{body(f);++cases;}catch(...){std::cerr<<"FAIL "<<name<<'\n';throw;}}
}
int main(){using namespace scope_test;try{
    run("pending member and close idempotence",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes);changes.prune();
        exact(f.first.allIds,{99});exact(f.first.oldIds,{99});exact(f.tracked0,{99});
        check(changes.pruned&&host::dirtyCalls==1&&host::ledCalls==2,"actual prune not exercised");
        changes.close();changes.close();check(f.helper0.disposed==1&&!host::read<bool>(&f.helper0,0x10),"close did not dispose once");
        check(host::dirtyCalls==1&&host::ledCalls==2&&!host::controlGroupClears,"close adapted original membership");
        check(f.rules0.values==std::vector<uint32_t>{75},"automatic rule changed");
    });
    run("original initializer after close retains new assignment",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes);changes.prune();changes.close();f.automatic();
        exact(f.first.allIds,{7,99});exact(f.first.oldIds,{99});exact(f.first.newIds,{7});
        check(f.first.dictionary.objects.size()==2&&host::automaticCalls==1,"new original typed bucket not exercised");
        changes.close();exact(f.first.allIds,{7,99});exact(f.first.newIds,{7});
        check(host::ledCalls==2&&f.helper0.disposed==1,"later close re-pruned/re-disposed original assignment");
    });
    run("original initializer suspension diagnostic",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes);std::string failure;
        try{f.automatic();}catch(const std::exception& e){failure=e.what();}
        check(failure.find("eventSuspender is suspended")!=std::string::npos&&failure.find("UnitsInitialized")!=std::string::npos,"original wrapper diagnostic missing");
        check(!host::automaticCalls,"raw Add ran despite forbidden initializer suspension");
        exact(f.first.allIds,{7,99});changes.close(true);check(f.helper0.disposed==1,"negative wrapper leaked scope");
    });
    run("Dispose callback manual removal is not resurrected",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes);changes.prune();
        host::disposeHook=[&](void* helper){if(helper==&f.helper0)f.manual(99);};
        changes.close();exact(f.first.allIds,{});exact(f.first.oldIds,{});f.automatic();
        exact(f.first.allIds,{7});exact(f.first.newIds,{7});changes.close();exact(f.first.allIds,{7});
        check(host::groupRemovals==1&&host::ledCalls==2,"manual callback/purge provenance differs");
    });
    run("manual new assignment removal stays absent",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes);changes.prune();changes.close();f.automatic();f.manual(7);changes.close();
        exact(f.first.allIds,{99});exact(f.first.newIds,{});check(host::groupRemovals==1,"manual removal not exercised");
    });
    run("both groups prune pending IDs only",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);changes.prune();changes.close();
        exact(f.first.allIds,{99});exact(f.second.allIds,{100});exact(f.tracked0,{99});exact(f.tracked1,{100});
        check(f.helper0.disposed==1&&f.helper1.disposed==1&&host::dirtyCalls==2&&host::ledCalls==4,"two-group scope counts differ");
    });
    for(bool typed:{false,true})run(typed?"partial first-group purge failure":"first-group purge failure",[&](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);host::failLed=typed?&f.first.oldType:&f.first.all;
        refused([&]{changes.prune();});const auto calls=host::ledCalls;refused([&]{changes.prune();});changes.close(true);
        check(host::dirtyBySet[&f.second.set]==0&&host::ledByObject[&f.second.all]==0&&host::ledCalls==calls,"purge failure reached/retried later group");
        exact(f.second.allIds,{7,100});check(f.helper0.disposed==1&&f.helper1.disposed==1,"purge failure leaked begun scopes");
        check(host::read<int32_t>(&f.first.set,0x54)==-1,"partial failure left count valid");
    });
    run("first mark failure stops later group",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);
        host::markHook=[&](void* helper){if(helper==&f.helper0)throw std::runtime_error("injected original Mark failure");};
        refused([&]{changes.prune();});changes.close(true);exact(f.first.allIds,{99});exact(f.second.allIds,{7,100});
        check(!host::dirtyBySet[&f.second.set]&&f.helper0.disposed==1&&f.helper1.disposed==1,"mark failure mutated later group or leaked cleanup");
    });
    run("missing prune rejected after all cleanup",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);refused([&]{changes.close();});changes.close(true);
        check(f.helper0.disposed==1&&f.helper1.disposed==1&&!host::ledCalls,"missing-prune close mutated/retried");
        exact(f.first.allIds,{7,99});exact(f.second.allIds,{7,100});
    });
    run("cancelled pre-mutation cleanup never purges",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);changes.mutated=false;changes.close();
        check(!host::ledCalls&&!host::dirtyCalls&&f.helper0.disposed==1&&f.helper1.disposed==1,"pre-mutation cleanup pruned");
    });
    run("prune cannot repeat",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes);changes.prune();refused([&]{changes.prune();});changes.close();f.automatic();
        refused([&]{changes.prune();});changes.close();exact(f.first.allIds,{7,99});check(host::dirtyCalls==1,"repeat prune mutated new assignment");
    });
    run("prune cannot precede Begin",[](Fixture& f){
        actors::GroupChanges changes;changes.prepare({&f.group0},f.retired,&f.state);changes.mutated=true;
        refused([&]{changes.prune();});changes.close(true);check(!host::ledCalls&&!f.helper0.disposed,"unbegun scope mutated/disposed");
    });
    run("helper replacement before Begin",[](Fixture& f){
        actors::GroupChanges changes;changes.prepare({&f.group0},f.retired,&f.state);put(f.group0,0x40,static_cast<void*>(&f.helper1));
        refused([&]{changes.begin();});changes.close(true);check(!f.helper0.disposed&&!f.helper1.disposed&&!host::ledCalls,"receiver replacement entered original Begin");
    });
    run("selected replacement after Begin",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);put(f.group0,0x20,static_cast<void*>(&f.second.set));
        refused([&]{changes.prune();});refused([&]{changes.close(true);});
        check(f.helper0.disposed==1&&f.helper1.disposed==1&&!host::ledCalls,"root loss mutated or leaked cleanup");
    });
    run("owner loss before prune",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);host::movementWorld=0;
        refused([&]{changes.prune();});refused([&]{changes.close(true);});
        check(!host::ledCalls&&f.helper0.disposed==1&&f.helper1.disposed==1,"owner loss adapted or leaked cleanup");
    });
    run("Dispose callback owner loss blocks pool continuation",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);changes.prune();
        host::disposeHook=[&](void* helper){if(helper==&f.helper0)host::movementWorld=0;};
        bool poolContinuation=false;refused([&]{changes.close();actors::requireOwned(f.state);poolContinuation=true;});
        check(!poolContinuation&&f.helper0.disposed==1&&f.helper1.disposed==1&&host::ledCalls==4,"Dispose owner loss continued adaptation");
    });
    run("Dispose callback selected-root loss",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);changes.prune();
        host::disposeHook=[&](void* helper){if(helper==&f.helper0)put(f.group1,0x20,static_cast<void*>(&f.first.set));};
        refused([&]{changes.close();});check(f.helper0.disposed==1&&f.helper1.disposed==1&&host::ledCalls==4,"Dispose replacement retried adaptation/cleanup");
        exact(f.first.allIds,{99});exact(f.second.allIds,{100});
    });
    run("first Dispose failure still closes later scope",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);changes.prune();host::failDispose=&f.helper0;
        refused([&]{changes.close();});changes.close(true);
        check(host::disposeByHelper[&f.helper0]==1&&host::disposeByHelper[&f.helper1]==1&&host::ledCalls==4,"Dispose failure lost once-only cleanup");
    });
    run("frame epoch change rejected",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);put(f.frame,0x40,int32_t{111});
        refused([&]{changes.prune();});refused([&]{changes.close(true);});check(!host::ledCalls&&f.helper0.disposed==1&&f.helper1.disposed==1,"changed frame mutated/escaped cleanup");
    });
    for(int mode=0;mode<3;++mode)run(("missing or invalid original frame "+std::to_string(mode)).c_str(),[&](Fixture& f){
        if(mode==0)put(f.simulation,0x148,static_cast<void*>(nullptr));
        if(mode==1)f.frames.calls["get_Current"]=nullptr;
        if(mode==2)f.frame.klass=host::type("Authored","WrongFrame");
        actors::GroupChanges changes;refused([&]{f.prepare(changes);});changes.close(true);
        check(host::interactionEvents.empty()&&!host::dirtyCalls&&!host::ledCalls&&
            !f.helper0.disposed&&!f.helper1.disposed,"missing frame reached original group mutation/cleanup");
        exact(f.first.allIds,{7,99});exact(f.first.oldIds,{7,99});
    });
    run("tracked root change rejected",[](Fixture& f){
        actors::GroupChanges changes;f.prepare(changes,true);put(f.group0,0x10,static_cast<void*>(&f.tracked1));
        refused([&]{changes.prune();});refused([&]{changes.close(true);});check(!host::ledCalls&&f.helper0.disposed==1&&f.helper1.disposed==1,"tracked replacement adapted");
    });
    run("null original automatic rules retained",[](Fixture& f){
        put(f.group0,0x30,static_cast<void*>(nullptr));actors::GroupChanges changes;f.prepare(changes);changes.prune();changes.close();f.automatic();
        check(!host::read<void*>(&f.group0,0x30),"null rule set replaced");exact(f.first.allIds,{7,99});
    });
    run("canonical manual membership survives speculative presentation retirement",[](Fixture& f){
        // Original group4 still owns canonical75/0/token900 at numeric7.
        // The physical presentation being retired is speculative76/token0;
        // it never owned this group's logical membership. Pending99 is absent.
        Selection empty2{101},empty3{102},manual{99};
        Node group2,group3,group4,helper2,helper3,helper4,tracked2,tracked3,tracked4,rules2,rules3,rules4;
        for(auto* group:{&group2,&group3,&group4})group->klass=host::type("Uncapped","ControlGroup");
        for(auto* helper:{&helper2,&helper3,&helper4})helper->klass=host::type("Authored","GroupHelper");
        for(auto* tracked:{&tracked2,&tracked3,&tracked4})tracked->klass=host::type("Uncapped.Collections","EntityIdSet");
        for(auto* selected:{&empty2,&empty3}) {
            selected->allIds.values.clear();selected->oldIds.values.clear();
            put(selected->all,0x18,UINT32_MAX);put(selected->oldType,0x18,UINT32_MAX);
        }
        tracked4.values={7,99};
        f.setup(group2,helper2,tracked2,rules2,empty2,2);f.setup(group3,helper3,tracked3,rules3,empty3,3);
        f.setup(group4,helper4,tracked4,rules4,manual,4);put(group4,0x30,static_cast<void*>(nullptr));
        put(f.array,0x18,uintptr_t{5});put(f.array,0x30,static_cast<void*>(&group2));
        put(f.array,0x38,static_cast<void*>(&group3));put(f.array,0x40,static_cast<void*>(&group4));
        check(manual.dictionary.typedBuckets.at(75)==&manual.oldType,"canonical typed bucket key differs");
        f.position.components[7]=1;f.type.components[7]=75;f.army.components[7]=0;
        f.state.admission.frame=110;f.state.admission.entities[7]={0,75,900};
        f.state.groupIntent.remember(1,{4,7},{75,0,900});
        put(f.config,0x10,uint32_t{76});f.state.identities[&f.actor]={{7,76,0},0};
        f.retired={{&f.actor,{7,76,0},{7,75,0},false,0}};
        actors::Current current(&f.frames);const auto canonical=current.identity(7);
        check(canonical&&canonical->unitType==75&&canonical->armyId==0&&!current.identity(99)&&
            actors::confirmedToken(f.state,*canonical)==900&&actors::resident(&f.actor).unitType==76&&
            f.state.identities.at(&f.actor).incarnation==0,"ownership RED setup differs");
        check(f.state.groupIntent.classify(1,{4,7},true,ba_prediction_group_intent::Identity{75,0,900},false)==
            ba_prediction_group_intent::Decision::Keep,"original canonical intent does not own membership");
        exact(manual.allIds,{7,99});exact(manual.oldIds,{7,99});
        actors::GroupChanges changes;changes.prepare({&group4},f.retired,&f.state);changes.begin();changes.mutated=true;
        changes.prune();changes.close();
        check(helper4.disposed==1&&!host::read<bool>(&helper4,0x10)&&!host::controlGroupClears&&
            !host::automaticCalls&&!host::groupRemovals,"ownership case used Clear/re-add or leaked original scope");
        const auto remembered=f.state.groupIntent.entries().find({4,7});
        check(remembered!=f.state.groupIntent.entries().end()&&remembered->second==ba_prediction_group_intent::Identity{75,0,900},
            "canonical intent metadata vanished before same-lease admission");
        auto allIds=manual.allIds.values,typedIds=manual.oldIds.values;
        std::sort(allIds.begin(),allIds.end());std::sort(typedIds.begin(),typedIds.end());
        check(std::binary_search(allIds.begin(),allIds.end(),uint32_t{99})&&std::binary_search(typedIds.begin(),typedIds.end(),uint32_t{99}),
            "ownership case lost unrelated pending99");
        std::cout<<"OWNERSHIP CHECK priorCases="<<cases<<" allCount="<<manual.allIds.values.size()
            <<" allFirst="<<allIds.front()<<" typedCount="<<manual.oldIds.values.size()<<" typedFirst="<<typedIds.front()
            <<" ledgerToken="<<remembered->second.token
            <<" physicalType=76 physicalToken=0 canonicalType=75 canonicalToken=900"
            <<" originalAddCalls="<<host::automaticCalls<<" wholeClearCalls="<<host::controlGroupClears<<'\n';
        check(allIds==std::vector<uint32_t>({7,99})&&typedIds==std::vector<uint32_t>({7,99}),
            "RED: actual physical-ID prune drops canonical logical member7 while pending99 and canonical intent900 survive");
    });
    run("protected-only count dirty once and tracked lease retained",[](Fixture& f){
        CanonicalGroup g(f);actors::GroupChanges changes;g.prepare(f,changes);changes.prune();changes.close();
        exact(g.selected.allIds,{7,99});exact(g.selected.oldIds,{7,99});exact(g.tracked,{7,99});
        check(host::dirtyCalls==1&&!host::ledCalls&&!host::trackedRemoves&&!host::automaticCalls&&
            changes.values.front()->retainedIntents.size()==1&&f.state.groupIntent.entries().count({4,7})==1&&
            host::read<int32_t>(&g.selected.set,0x54)==-1&&g.helper.disposed==1,
            "protected logical membership/count/tracked state differs");
    });
    for(int mode=0;mode<5;++mode)run(("canonical absence or identity mismatch "+std::to_string(mode)).c_str(),[&](Fixture& f){
        CanonicalGroup g(f);
        if(mode==0)f.state.admission.entities.erase(7);
        if(mode==1){f.state.admission.entities[7].type=76;f.type.components[7]=76;f.retired[0].current.unitType=76;}
        if(mode==2){f.state.admission.entities[7].army=1;f.army.components[7]=1;f.retired[0].current.armyId=1;}
        if(mode==3)f.state.admission.entities[7].incarnation=901;if(mode==4)f.state.admission.entities[7].incarnation=0;
        actors::GroupChanges changes;g.prepare(f,changes);changes.prune();changes.close();
        exact(g.selected.allIds,{99});exact(g.selected.oldIds,{99});exact(g.tracked,{99});
        check(host::dirtyCalls==1&&host::ledCalls==2&&changes.values.front()->retainedIntents.empty()&&!host::automaticCalls,
            "noncanonical logical lease was protected or double-dirtied");
    });
    run("missing logical record does not protect speculative presentation",[](Fixture& f){
        CanonicalGroup g(f);f.state.groupIntent.erase(1,{4,7});actors::GroupChanges changes;g.prepare(f,changes);changes.prune();changes.close();
        exact(g.selected.allIds,{99});exact(g.selected.oldIds,{99});exact(g.tracked,{99});check(host::dirtyCalls==1&&host::ledCalls==2,"unrecorded ID protected");
    });
    for(bool ghost:{false,true})run(ghost?"original user removal wins and typed ghost purged":"original user removal stays absent",[&](Fixture& f){
        CanonicalGroup g(f);g.selected.allIds.values={99};put(g.selected.all,0x18,uint32_t{99});
        if(!ghost){g.selected.oldIds.values={99};put(g.selected.oldType,0x18,uint32_t{99});}
        actors::GroupChanges changes;g.prepare(f,changes);changes.prune();changes.close();
        exact(g.selected.allIds,{99});exact(g.selected.oldIds,{99});exact(g.tracked,{99});
        check(host::dirtyCalls==1&&host::ledCalls==(ghost?1u:0u)&&!host::automaticCalls&&!host::controlGroupClears&&
            changes.values.front()->retainedIntents.empty(),"user removal resurrected/protected stale membership");
    });
    for(bool multiple:{false,true})run(multiple?"canonical ownership multiple ghosts refuses before mutation":"canonical ownership wrong key refuses before mutation",[&](Fixture& f){
        CanonicalGroup g(f);
        if(multiple){g.selected.newIds.values={7};put(g.selected.newType,0x18,uint32_t{7});g.selected.dictionary.objects.push_back(&g.selected.newType);g.selected.dictionary.typedBuckets[76]=&g.selected.newType;}
        else {g.selected.dictionary.typedBuckets.erase(75);g.selected.dictionary.typedBuckets[76]=&g.selected.oldType;}
        actors::GroupChanges changes;g.prepare(f,changes,true);refused([&]{changes.prune();});changes.close(true);
        exact(g.selected.allIds,{7,99});exact(g.selected.oldIds,{7,99});exact(f.second.allIds,{7,100});
        check(!host::dirtyCalls&&!host::ledCalls&&!host::trackedRemoves&&g.helper.disposed==1&&f.helper1.disposed==1,
            "unproven typed ownership mutated a group or leaked cleanup");
    });
    run("mixed canonical protected and invalidated IDs",[](Fixture& f){
        CanonicalGroup g(f);Node actor8,config8;actor8.klass=host::type("Uncapped","Unit");config8.klass=host::type("Uncapped","EntityConfig");
        put(actor8,0x14c,uint32_t{8});put(actor8,0x150,uint32_t{0});put(actor8,0x168,static_cast<void*>(&config8));put(config8,0x10,uint32_t{77});
        f.state.identities[&actor8]={{8,77,0},0};f.position.components[8]=1;f.type.components[8]=78;f.army.components[8]=0;
        f.state.admission.entities[8]={0,78,901};f.retired.push_back({&actor8,{8,77,0},{8,78,0},false,0});
        g.selected.allIds.values={7,8,99};g.selected.newIds.values={8};put(g.selected.newType,0x18,uint32_t{8});
        g.selected.dictionary.objects.push_back(&g.selected.newType);g.selected.dictionary.typedBuckets[77]=&g.selected.newType;g.tracked.values={7,8,99};
        actors::GroupChanges changes;g.prepare(f,changes);changes.prune();changes.close();
        exact(g.selected.allIds,{7,99});exact(g.selected.oldIds,{7,99});exact(g.selected.newIds,{});exact(g.tracked,{7,99});
        check(host::dirtyCalls==1&&host::ledCalls==2&&host::trackedRemoves==1&&changes.values.front()->retainedIntents.size()==1&&
            f.state.groupIntent.entries().at({4,7}).token==900&&!host::automaticCalls,"mixed purge deleted canonical intent or rewrote pending members");
    });
    for(int mode=0;mode<5;++mode)run(("canonical owner drift during raw lookup "+std::to_string(mode)).c_str(),[&](Fixture& f){
        CanonicalGroup g(f);actors::GroupChanges changes;g.prepare(f,changes,true);
        host::lookupHook=[&](void*){
            if(mode==0)host::movementWorld=0;if(mode==1)f.state.admission.entities[7].type=76;
            if(mode==2)f.state.admission.entities[7].army=1;if(mode==3)f.state.admission.entities[7].incarnation=901;
            if(mode==4)f.state.groupIntent.erase(1,{4,7});
        };
        refused([&]{changes.prune();});try{changes.close(true);}catch(const std::exception&){}changes.close(true);
        exact(g.selected.allIds,{7,99});exact(g.selected.oldIds,{7,99});exact(f.second.allIds,{7,100});
        check(!host::dirtyCalls&&!host::ledCalls&&!host::trackedRemoves&&g.helper.disposed==1&&f.helper1.disposed==1,
            "lookup drift adapted a later group or retried cleanup");
    });
    run("canonical drift during Mark stops later groups",[](Fixture& f){
        CanonicalGroup g(f);actors::GroupChanges changes;g.prepare(f,changes,true);
        host::markHook=[&](void* helper){if(helper==&g.helper)f.state.admission.entities[7].incarnation=901;};
        refused([&]{changes.prune();});try{changes.close(true);}catch(const std::exception&){}changes.close(true);
        exact(g.selected.allIds,{7,99});exact(g.tracked,{7,99});exact(f.second.allIds,{7,100});
        check(host::dirtyCalls==1&&!host::ledCalls&&!host::dirtyBySet[&f.second.set]&&g.helper.disposed==1&&f.helper1.disposed==1,
            "post-query canonical drift continued adaptation/cleanup");
    });
    run("canonical token loss current-type route acknowledges only after Dispose",[](Fixture& f){
        CanonicalLoss g(f);f.type.components[7]=75;f.state.admission.entities[7]={0,75,901};
        bool markedPending=false,disposedPending=false;
        host::markHook=[&](void* helper){if(helper==&g.helper)markedPending=f.state.groupIntent.entries().count({4,7})==1;};
        host::disposeHook=[&](void* helper){if(helper==&g.helper)disposedPending=f.state.groupIntent.entries().count({4,7})==1;};
        actors::reconcileGroupIntent(f.state);
        exact(g.selected.allIds,{99});exact(g.selected.oldIds,{99});exact(g.selected.newIds,{});
        check(markedPending&&disposedPending&&f.state.groupIntent.entries().empty()&&g.helper.disposed==1&&
            host::groupMarks==1&&host::groupNotifications==1&&!host::automaticCalls&&!host::controlGroupClears,
            "canonical loss acknowledged before successful original scope/notification");
    });
    run("canonical loss original user Clear wins",[](Fixture& f){
        CanonicalLoss g(f);g.selected.allIds.values.clear();g.selected.oldIds.values.clear();g.selected.set.components.clear();
        put(g.selected.all,0x18,UINT32_MAX);put(g.selected.oldType,0x18,UINT32_MAX);
        actors::reconcileGroupIntent(f.state);exact(g.selected.allIds,{});exact(g.selected.oldIds,{});
        check(f.state.groupIntent.entries().empty()&&!host::groupRemovals&&!host::ledCalls&&!host::dirtyCalls&&
            !host::groupMarks&&!host::groupNotifications&&!g.helper.disposed&&!host::automaticCalls,
            "original Clear was resurrected or unnecessarily purged");
    });
    run("canonical loss original mutation exception keeps metadata and closes once",[](Fixture& f){
        CanonicalLoss g(f);host::failLed=&g.selected.all;
        refused([&]{actors::reconcileGroupIntent(f.state);});exact(g.selected.allIds,{7,99});exact(g.selected.oldIds,{7,99});
        check(f.state.groupIntent.entries().at({4,7}).token==900&&g.helper.disposed==1&&!host::read<bool>(&g.helper,0x10)&&
            !host::groupMarks&&!host::groupNotifications&&!host::groupRemovals&&host::ledCalls==1,
            "failed original mutation acknowledged metadata or retried/leaked scope");
    });
    for(int mode=0;mode<4;++mode)run(("canonical loss exact current owner refusal "+std::to_string(mode)).c_str(),[&](Fixture& f){
        CanonicalLoss g(f);
        if(mode==0)host::movementWorld=0;if(mode==1)put(f.simulation,0x148,static_cast<void*>(nullptr));
        if(mode==2)f.frame.klass=host::type("Authored","WrongFrame");if(mode==3)put(g.helper,0x18,static_cast<void*>(&f.group1));
        refused([&]{actors::reconcileGroupIntent(f.state);});exact(g.selected.allIds,{7,99});exact(g.selected.oldIds,{7,99});
        check(f.state.groupIntent.entries().size()==1&&!host::groupRemovals&&!host::ledCalls&&!host::dirtyCalls&&
            !host::groupMarks&&!g.helper.disposed,"invalid current owner reached canonical-loss mutation");
    });
    run("canonical loss Begin owner drift refuses and closes once",[](Fixture& f){
        CanonicalLoss g(f);host::beginHook=[&](void* group){if(group==&g.group)host::movementWorld=0;};
        refused([&]{actors::reconcileGroupIntent(f.state);});exact(g.selected.allIds,{7,99});exact(g.selected.oldIds,{7,99});
        check(f.state.groupIntent.entries().size()==1&&g.helper.disposed==1&&!host::read<bool>(&g.helper,0x10)&&
            !host::groupRemovals&&!host::ledCalls&&!host::dirtyCalls&&!host::groupMarks,
            "Begin owner drift continued mutation or failed once-only cleanup");
    });
    run("canonical loss Dispose owner drift keeps unacknowledged metadata",[](Fixture& f){
        CanonicalLoss g(f);f.type.components[7]=75;f.state.admission.entities[7]={0,75,901};
        host::disposeHook=[&](void* helper){if(helper==&g.helper)host::movementWorld=0;};
        refused([&]{actors::reconcileGroupIntent(f.state);});exact(g.selected.allIds,{99});exact(g.selected.oldIds,{99});
        check(f.state.groupIntent.entries().at({4,7}).token==900&&g.helper.disposed==1&&host::groupMarks==1&&host::groupNotifications==1,
            "Dispose owner drift acknowledged metadata or retried cleanup");
    });
    run("canonical loss current-type change needs every raw cached bucket purged",[](Fixture& f){
        CanonicalLoss g(f);check(!host::leaveGroupTyped,"canonical-loss RED must not inject a skipped typed removal");
        std::string failure;try{actors::reconcileGroupIntent(f.state);}catch(const std::exception& e){failure=e.what();}
        std::cout<<"CANONICAL LOSS CHECK priorCases="<<cases<<" currentTypeRoutes="<<host::removeCurrentTypeRoutes
            <<" resolvedType="<<host::lastRemoveType<<" allCount="<<g.selected.allIds.values.size()
            <<" oldTypedCount="<<g.selected.oldIds.values.size()<<" currentTypedCount="<<g.selected.newIds.values.size()
            <<" metadataEntries="<<f.state.groupIntent.entries().size()<<" disposed="<<g.helper.disposed
            <<" marks="<<host::groupMarks<<" notifications="<<host::groupNotifications
            <<" originalRemove="<<host::groupRemovals<<" rawLedRemove="<<host::ledCalls<<" skipTypedInjected="<<host::leaveGroupTyped
            <<" originalFailure="<<failure<<'\n';
        check(failure.empty(),"RED: actual canonical-loss reconciliation resolves only current type76 and leaves old typed75 ghost7");
        exact(g.selected.allIds,{99});exact(g.selected.oldIds,{99});exact(g.selected.newIds,{});
        check(f.state.groupIntent.entries().empty()&&g.helper.disposed==1&&host::groupMarks==1&&host::groupNotifications==1&&
            !host::controlGroupClears&&!host::automaticCalls&&!host::groupRemovals&&host::ledCalls==2,
            "canonical-loss cleanup did not surgically purge all original raw buckets before acknowledgment");
    });
    for(int stage=0;stage<3;++stage)for(int mode=0;mode<9;++mode)
        run(("canonical loss callback current snapshot "+std::to_string(stage)+":"+std::to_string(mode)).c_str(),[&](Fixture& f){
            CanonicalLoss g(f);Node otherFrames,otherFrame,otherBuffer;
            otherFrames.calls["get_Current"]=&f.frame;otherFrame.klass=f.frame.klass;otherFrame.calls=f.frame.calls;
            put(otherFrame,0x40,int32_t{110});otherBuffer.klass=host::type("Authored","ComponentBuffer");
            auto drift=[&](){
                if(mode==0)f.frames.calls["get_Current"]=&otherFrame; // Same collection/index, different current node.
                if(mode==1)put(f.frame,0x40,int32_t{111});
                if(mode==2)f.frame.calls["get_PositionBuffer"]=&otherBuffer;
                if(mode==3)f.frame.calls["get_TypeBuffer"]=&otherBuffer;
                if(mode==4)f.frame.calls["get_ArmyBuffer"]=&otherBuffer;
                if(mode==5)put(f.simulation,0x148,static_cast<void*>(&otherFrames));
                if(mode==6)f.state.admission.frame=111;
                if(mode==7)put(f.array,0x40,static_cast<void*>(&f.group1));
                if(mode==8)put(f.array,0x18,uintptr_t{4});
            };
            if(stage==0)host::beginHook=[&](void* group){if(group==&g.group)drift();};
            if(stage==1)host::markHook=[&](void* helper){if(helper==&g.helper)drift();};
            if(stage==2)host::disposeHook=[&](void* helper){if(helper==&g.helper)drift();};
            refused([&]{actors::reconcileGroupIntent(f.state);});
            exact(g.selected.allIds,stage==0?std::vector<uint32_t>{7,99}:std::vector<uint32_t>{99});
            exact(g.selected.oldIds,stage==0?std::vector<uint32_t>{7,99}:std::vector<uint32_t>{99});
            check(f.state.groupIntent.entries().at({4,7}).token==900&&g.helper.disposed==1&&
                host::disposeByHelper[&g.helper]==1&&!host::read<bool>(&g.helper,0x10)&&!host::groupRemovals&&
                host::dirtyCalls==(stage==0?0u:1u)&&host::ledCalls==(stage==0?0u:2u)&&
                host::groupMarks==(stage==0?0u:1u)&&host::groupNotifications==(stage==0?0u:1u),
                "current snapshot drift acknowledged metadata, continued mutation or retried cleanup");
        });
    for(int stage=0;stage<3;++stage)for(int mode=0;mode<6;++mode)
        run(("canonical loss callback identity snapshot "+std::to_string(stage)+":"+std::to_string(mode)).c_str(),[&](Fixture& f){
            CanonicalLoss g(f);
            auto drift=[&](){
                if(mode==0)f.state.admission.entities.erase(7);
                if(mode==1)f.state.admission.entities[7].type=75;
                if(mode==2)f.state.admission.entities[7].army=1;
                if(mode==3)f.state.admission.entities[7].incarnation=902;
                if(mode>=4)f.state.groupIntent.erase(1,{4,7});
                if(mode==5)f.state.groupIntent.remember(1,{4,7},{75,0,902});
            };
            if(stage==0)host::beginHook=[&](void* group){if(group==&g.group)drift();};
            if(stage==1)host::markHook=[&](void* helper){if(helper==&g.helper)drift();};
            if(stage==2)host::disposeHook=[&](void* helper){if(helper==&g.helper)drift();};
            refused([&]{actors::reconcileGroupIntent(f.state);});
            exact(g.selected.allIds,stage==0?std::vector<uint32_t>{7,99}:std::vector<uint32_t>{99});
            exact(g.selected.oldIds,stage==0?std::vector<uint32_t>{7,99}:std::vector<uint32_t>{99});
            if(mode==4)check(f.state.groupIntent.entries().empty(),"callback-removed metadata was resurrected");
            else check(f.state.groupIntent.entries().at({4,7}).token==(mode==5?902u:900u),"drifted callback metadata was erased or overwritten");
            check(g.helper.disposed==1&&host::disposeByHelper[&g.helper]==1&&!host::read<bool>(&g.helper,0x10)&&
                !host::groupRemovals&&host::dirtyCalls==(stage==0?0u:1u)&&host::ledCalls==(stage==0?0u:2u)&&
                host::groupMarks==(stage==0?0u:1u)&&host::groupNotifications==(stage==0?0u:1u),
                "identity drift continued adaptation or retried original cleanup");
        });
    run("canonical loss partial old-typed Led failure retains metadata",[](Fixture& f){
        CanonicalLoss g(f);host::failLed=&g.selected.oldType;
        refused([&]{actors::reconcileGroupIntent(f.state);});exact(g.selected.allIds,{99});exact(g.selected.oldIds,{7,99});
        check(f.state.groupIntent.entries().at({4,7}).token==900&&host::dirtyCalls==1&&host::ledCalls==2&&
            !host::groupRemovals&&!host::groupMarks&&!host::groupNotifications&&g.helper.disposed==1&&
            host::read<int32_t>(&g.selected.set,0x54)==-1,"partial Led failure acknowledged metadata or left count valid");
    });
    for(bool typed:{false,true})run(typed?"canonical loss typed Led throws after mutation":"canonical loss all Led throws after mutation",[&](Fixture& f){
        CanonicalLoss g(f);host::failLedAfter=typed?&g.selected.oldType:&g.selected.all;
        refused([&]{actors::reconcileGroupIntent(f.state);});exact(g.selected.allIds,{99});
        exact(g.selected.oldIds,typed?std::vector<uint32_t>{99}:std::vector<uint32_t>{7,99});
        check(f.state.groupIntent.entries().at({4,7}).token==900&&host::dirtyCalls==1&&host::ledCalls==(typed?2u:1u)&&
            !host::groupMarks&&!host::groupNotifications&&g.helper.disposed==1&&!host::groupRemovals,
            "after-mutation Led exception acknowledged metadata or continued mutation");
    });
    run("canonical loss original Dispose failure keeps completed purge unacknowledged",[](Fixture& f){
        CanonicalLoss g(f);host::failDispose=&g.helper;refused([&]{actors::reconcileGroupIntent(f.state);});
        exact(g.selected.allIds,{99});exact(g.selected.oldIds,{99});
        check(f.state.groupIntent.entries().at({4,7}).token==900&&host::dirtyCalls==1&&host::ledCalls==2&&
            host::groupMarks==1&&host::groupNotifications==1&&g.helper.disposed==1&&host::disposeByHelper[&g.helper]==1,
            "failed original Dispose acknowledged metadata or was retried");
    });
    run("canonical loss primary Led exception survives Dispose failure",[](Fixture& f){
        CanonicalLoss g(f);host::failLed=&g.selected.oldType;host::failDispose=&g.helper;
        std::string error;try{actors::reconcileGroupIntent(f.state);}catch(const std::exception& e){error=e.what();}
        check(error=="injected original Led.Remove failure","cleanup replaced the original Led exception");
        exact(g.selected.allIds,{99});exact(g.selected.oldIds,{7,99});
        check(f.state.groupIntent.entries().at({4,7}).token==900&&host::ledCalls==2&&!host::groupMarks&&
            !host::groupNotifications&&g.helper.disposed==1&&host::disposeByHelper[&g.helper]==1,"double failure lost metadata or retried cleanup");
    });
    run("canonical loss first partial failure stops later pending group",[](Fixture& f){
        CanonicalLoss g(f);Selection selected5{100};Node group5,helper5,tracked5,rules5;
        group5.klass=host::type("Uncapped","ControlGroup");helper5.klass=host::type("Authored","GroupHelper");
        tracked5.klass=host::type("Uncapped.Collections","EntityIdSet");f.setup(group5,helper5,tracked5,rules5,selected5,5);
        put(group5,0x30,static_cast<void*>(nullptr));put(f.array,0x18,uintptr_t{6});put(f.array,0x48,static_cast<void*>(&group5));
        f.state.groupIntent.remember(1,{5,7},{75,0,900});host::failLed=&g.selected.oldType;
        refused([&]{actors::reconcileGroupIntent(f.state);});exact(g.selected.allIds,{99});exact(g.selected.oldIds,{7,99});
        exact(selected5.allIds,{7,100});exact(selected5.oldIds,{7,100});
        check(f.state.groupIntent.entries().size()==2&&host::ledCalls==2&&host::dirtyCalls==1&&!host::dirtyBySet[&selected5.set]&&
            g.helper.disposed==1&&!helper5.disposed&&!host::groupMarks,"first failure adapted/acknowledged a later pending group");
    });
    run("canonical loss original removal during Begin uses no resurrection and one dirty",[](Fixture& f){
        CanonicalLoss g(f);host::beginHook=[&](void* group){if(group==&g.group){
            g.selected.allIds.values={99};g.selected.oldIds.values={99};g.selected.set.components.erase(7);
            put(g.selected.all,0x18,uint32_t{99});put(g.selected.oldType,0x18,uint32_t{99});
        }};
        actors::reconcileGroupIntent(f.state);exact(g.selected.allIds,{99});exact(g.selected.oldIds,{99});
        check(f.state.groupIntent.entries().empty()&&!host::ledCalls&&!host::groupRemovals&&host::dirtyCalls==1&&
            host::groupMarks==1&&host::groupNotifications==1&&g.helper.disposed==1&&!host::automaticCalls,
            "original removal during Begin was re-added or double-dirtied");
    });
    std::cout<<"PASS "<<cases<<" actual-source pre-pool group-scope cases; original initializer suspension diagnostic exercised; no Unity/IL2CPP/game/DLL loads\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
