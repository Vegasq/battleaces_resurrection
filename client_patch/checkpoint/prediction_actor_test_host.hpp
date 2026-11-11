#pragma once
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
#include <type_traits>
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
// Opt-in held-identity fixtures; defaults preserve the group-scope host.
static bool heldMovementEnabled=false;static int heldSlot=1,vector2Bytes=8;
static std::map<std::pair<Class*,std::string>,Field> heldFields;
// Opt-in exact original-API fixtures. Empty defaults retain the old host's
// refusals; each fixture must match receiver, method/token and arguments.
static std::map<uintptr_t,Obj> nativeOverrides;
static std::map<Obj,std::vector<Obj>> parameterOverrides;
static std::map<Obj,Obj> classParents,enumClasses;
static std::map<Obj,std::pair<int32_t,uint32_t>> valueSizes;
static std::map<std::pair<Obj,std::string>,Field> extraLiterals;
static std::function<Obj(const char*,const char*)> makeHook;
static std::function<bool(Obj,const char*,int,void**,Obj&)> callHook;
static std::function<bool(Obj,const char*,uintptr_t&)> getHook;
static std::function<bool(Obj,Obj,void**,Obj&)> invokeHook;
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
static Obj parent(Obj value){const auto found=classParents.find(value);return found==classParents.end()?nullptr:found->second;}
static bool assignableFrom(Obj expected,Obj value){
    for(unsigned count=0;value&&count<64;++count,value=parent(value))if(value==expected)return true;
    return false;
}
static uintptr_t arrayLength(Obj value){return read<uintptr_t>(value,0x18);}
static Obj classMethod(Obj value,const char* name,int count){
    for(Obj current=value;current;current=parent(current))for(auto* method:static_cast<Class*>(current)->methods)
        if(method->name&&!strcmp(method->name,name)&&method->parameters==static_cast<uint32_t>(count))return method;
    return nullptr;
}
static const char* className(Obj value){return static_cast<Class*>(value)->name.c_str();}
static const char* methodName(Obj value){return static_cast<Method*>(value)->name;}
static uint32_t parameterCount(Obj value){return static_cast<Method*>(value)->parameters;}
static uint32_t methodToken(Obj value){return static_cast<Method*>(value)->token;}
static uint32_t methodFlags(Obj value,uint32_t* implementation){*implementation=0;return static_cast<Method*>(value)->flags;}
static Obj parameter(Obj method,uint32_t index){
    const auto extra=parameterOverrides.find(method);
    if(extra!=parameterOverrides.end()){check(index<extra->second.size(),"authored exact parameter index");return extra->second[index];}
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
    const auto extra=extraLiterals.find({value,name});if(extra!=extraLiterals.end())return const_cast<Field*>(&extra->second);
    if(value!=type("","DeferredClickMode"))throw std::runtime_error("unexpected authored class field lookup");
    const auto found=clickLiterals.find(name);return found==clickLiterals.end()?nullptr:&found->second;
}
static bool isEnum(Obj value){return value==type("","DeferredClickMode")||enumClasses.count(value)!=0;}
static Obj enumBase(Obj value){check(isEnum(value),"authored enum base lookup on another type");const auto extra=enumClasses.find(value);return extra==enumClasses.end()?type("System","Int32"):extra->second;}
static bool isValueType(Obj klass){if(valueSizes.count(klass))return true;if(klass==type("UnityEngine","Vector2"))return true;return klass==type("Uncapped","IntKey`1")||klass==type("","SelectedEntitiesOfType")||klass==type("Authored","ValueEnumerator")||isEnum(klass)||
    klass==type("System","Single")||klass==type("System","Int32")||klass==type("System","UInt32")||klass==type("System","Boolean");}
static int32_t valueSize(Obj klass,uint32_t* alignment){
    const auto extra=valueSizes.find(klass);if(extra!=valueSizes.end()){*alignment=extra->second.second;return extra->second.first;}
    if(klass==type("UnityEngine","Vector2")){*alignment=4;return vector2Bytes;}
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
static int lanSlot(){return host::heldSlot;}
using Obj=void*;static DWORD initialThread=1;static Obj owner=nullptr;
template<class T>T api(const char* name){
    if(!strcmp(name,"il2cpp_class_get_namespace"))return reinterpret_cast<T>(&host::classNamespace);
    if(!strcmp(name,"il2cpp_method_get_declaring_type"))return reinterpret_cast<T>(&host::methodOwner);
    if(!strcmp(name,"il2cpp_type_is_byref"))return reinterpret_cast<T>(&host::byref);
    if(!strcmp(name,"il2cpp_class_get_methods"))return reinterpret_cast<T>(&host::methods);
    if(!strcmp(name,"il2cpp_class_get_method_from_name"))return reinterpret_cast<T>(&host::classMethod);
    if(!strcmp(name,"il2cpp_class_is_assignable_from"))return reinterpret_cast<T>(&host::assignableFrom);
    if(!strcmp(name,"il2cpp_array_length"))return reinterpret_cast<T>(&host::arrayLength);
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
    const auto extra=host::nativeOverrides.find(rva);if(extra!=host::nativeOverrides.end())return reinterpret_cast<T>(extra->second);
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
    const auto declared=host::heldFields.find({static_cast<host::Class*>(klass(receiver)),name});
    if(declared!=host::heldFields.end())return const_cast<host::Field*>(&declared->second);
    static host::Field groupManager{0x60};
    if(!strcmp(name,"_dictionary")){
        static std::map<Obj,host::Field> dictionaries;
        auto& member=dictionaries[klass(receiver)];member={0x10,host::type("System.Collections.Generic","Dictionary`2"),static_cast<host::Class*>(klass(receiver))};return &member;
    }

    if(!strcmp(name,"_unitManager") && klass(receiver)==host::type("Uncapped","ControlGroup"))return &groupManager;
    return &host::fields.at(name);
}
static Obj call(Obj receiver,const char* name,int count=0,void** args=nullptr){Obj result=nullptr;if(host::callHook&&host::callHook(receiver,name,count,args,result))return result;return static_cast<host::Node*>(receiver)->calls.at(name);}
inline Obj method(Obj receiver,const char* name,int count){return host::classMethod(klass(receiver),name,count);}
static Obj make(const char* space,const char* name){if(host::makeHook)return host::makeHook(space,name);throw std::runtime_error("unexpected managed creation");}
template<class T>T get(Obj receiver,const char* name){
    uintptr_t raw=0;if(host::getHook&&host::getHook(receiver,name,raw)){
        if constexpr(std::is_pointer_v<T>)return reinterpret_cast<T>(raw);else return static_cast<T>(raw);
    }
    if(receiver==owner&&!strcmp(name,"<UnitSelector>k__BackingField")&&host::currentSelector){
        if constexpr(std::is_pointer_v<T>)return static_cast<T>(host::currentSelector);
        else throw std::runtime_error("authored selector field is not a scalar");
    }
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
    host::Obj hookResult=nullptr;if(host::invokeHook&&host::invokeHook(method,object,args,hookResult))return hookResult;
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
bool movementEnabled(){return host::heldMovementEnabled;}uint64_t movementWorldId(){return host::movementWorld;}
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
    host::nativeOverrides.clear();host::parameterOverrides.clear();host::classParents.clear();host::enumClasses.clear();host::valueSizes.clear();host::extraLiterals.clear();
    host::makeHook={};host::callHook={};host::getHook={};host::invokeHook={};
    host::heldMovementEnabled=false;host::heldSlot=1;host::vector2Bytes=8;host::heldFields.clear();
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
}
