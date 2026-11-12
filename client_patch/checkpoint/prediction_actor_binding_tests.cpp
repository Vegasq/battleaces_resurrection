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
static unsigned groupDirtyCalls=0,groupLedCalls=0;
static Obj failedGroupLed=nullptr;
static bool failGroupRemove=false,leaveGroupTyped=false,failGroupMark=false,stopAfterGroupRemove=false;
static Obj expectedGroupHelper=nullptr;
static unsigned char groupRemoveCode[32]{},groupBeginCode[32]{},groupDisposeCode[8]{},groupMarkCode[32]{};
static unsigned char groupLedCode[16]{},groupDirtyCode[8]{};
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
static Method containsMethod,itemMethod,selectionContainsMethod,countMethod,valuesMethod,enumeratorMethod,moveNextMethod,currentMethod,disposeMethod,focusMethod,scopeBeginMethod,scopeDisposeMethod,clearMethod,removeSelectionMethod,groupRemoveMethod,groupMarkMethod,clickTimeMethod;
static Method groupLedMethod,groupDirtyMethod;
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
    boxedBool.klass=boolType;boxedInt.klass=type("System","Int32");
    auto* selection=type("Uncapped.Collections","UnitSelectionSet");
    auto* led=type("","LedUnitSet");led->declaring=selection;
    auto* dictionary=type("System.Collections.Generic","Dictionary`2");
    auto* valueCollection=type("Authored","ValueCollection");
    auto* iterator=type("Authored","ValueEnumerator");
    groupLedMethod={groupLedCode,"Remove",0x060025c8,boolType,1,0,led};
    groupDirtyMethod={groupDirtyCode,"MarkCountAsDirty",0x0600259a,type("System","Void"),0,0,selection};
    methodObjects.insert(&groupLedMethod);methodObjects.insert(&groupDirtyMethod);
    led->methods={&groupLedMethod};selection->methods.push_back(&groupDirtyMethod);
    dictionary->methods={&countMethod,&valuesMethod};
    valuesMethod.result=valueCollection;enumeratorMethod.result=iterator;
    currentMethod.result=led;disposeMethod.result=type("System","Void");
    fields["_allUnits"]={0x18,led,selection};fields["_subsetsByType"]={0x20,dictionary,selection};
    fields["<Entities>k__BackingField"]={0x10,type("Uncapped.Collections","EntityIdSet"),led};
    fields["<Leader>k__BackingField"]={0x18,uintType,led};fields["_lastKnownLeaderId"]={0x1c,uintType,led};
    fields["<OnlyHQSelected>k__BackingField"]={0x58,boolType,selection};
    fields["_recomputeOverallLeader"]={0x10,boolType,selection};
    fields["_lastFrameCountRecalculated"]={0x54,type("System","Int32"),selection};
}
static Obj methods(Obj klass,void** iterator){
    const auto index=reinterpret_cast<uintptr_t>(*iterator);
    const auto& values=static_cast<Class*>(klass)->methods;
    if(index>=values.size())return nullptr;
    *iterator=reinterpret_cast<void*>(index+1);return values[index];
}
static Obj parent(Obj){return nullptr;}
static const char* className(Obj value){return static_cast<Class*>(value)->name.c_str();}
static const char* classNamespace(Obj value){return static_cast<Class*>(value)->space.c_str();}
static Obj methodOwner(Obj value){return static_cast<Method*>(value)->owner;}
static bool byref(Obj){return false;}
static const char* methodName(Obj value){return static_cast<Method*>(value)->name;}
static uint32_t parameterCount(Obj value){return static_cast<Method*>(value)->parameters;}
static uint32_t methodToken(Obj value){return static_cast<Method*>(value)->token;}
static uint32_t methodFlags(Obj value,uint32_t* implementation){*implementation=0;return static_cast<Method*>(value)->flags;}
static Obj parameter(Obj method,uint32_t){
    if(method==&focusMethod){if(focusParameterHook){auto hook=std::move(focusParameterHook);focusParameterHook={};hook();}return focusParameter;}
    return type("System",method==&scopeBeginMethod?"Boolean":"UInt32");
}
static Obj resultType(Obj value){return static_cast<Method*>(value)->result;}
static Obj fromType(Obj value){return value;}
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
static bool isValueType(Obj klass){return klass==type("Authored","ValueEnumerator")||isEnum(klass)||
    klass==type("System","Single")||klass==type("System","Int32")||klass==type("System","UInt32")||klass==type("System","Boolean");}
static int32_t valueSize(Obj klass,uint32_t* alignment){
    if(klass==type("System","Boolean")){*alignment=1;return 1;}
    if(klass==type("System","Single")){*alignment=4;return clickSingleSize;}
    if(isEnum(klass)){*alignment=4;return clickModeSize;}
    check(klass==type("System","UInt32")||klass==type("System","Int32")||klass==type("System","Single")||isEnum(klass),
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
    throw std::runtime_error("unexpected authored metadata API");
}
template<class T>T native(uintptr_t rva){
    if(rva==0x3787d20)return reinterpret_cast<T>(&host::ids);
    if(rva==0x3c699b0)return reinterpret_cast<T>(&host::groupLedCode[0]);
    if(rva==0x3c63de0)return reinterpret_cast<T>(&host::groupDirtyCode[0]);
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
    if(!strcmp(name,"_unitManager") && klass(receiver)==host::type("Uncapped","ControlGroup"))return &groupManager;
    if(!strcmp(name,"_dictionary")) {
        static host::Field valuesOwner{0x10,host::type("System.Collections.Generic","Dictionary`2"),host::type("Authored","ValueCollection")};
        static host::Field iteratorOwner{0x10,host::type("System.Collections.Generic","Dictionary`2"),host::type("Authored","ValueEnumerator")};
        if(klass(receiver)==valuesOwner.parent)return &valuesOwner;
        if(klass(receiver)==iteratorOwner.parent)return &iteratorOwner;
    }
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
    if(token==0x06001040){
        host::check(!object&&!args&&!host::queueLocks,"authored Single clock invocation ABI/lock differs");++host::clickClockCalls;
        if(host::failClickClock)throw std::runtime_error("authored original clock failure");
        host::boxedSingle.klass=host::type("System",host::wrongClickBox?"Int32":"Single");host::put(host::boxedSingle,0,host::clickNow);return &host::boxedSingle;
    }
    auto& node=*static_cast<host::Node*>(object);
    if(token==0x0600259a){
        host::check(host::expectedGroupHelper && host::read<bool>(host::expectedGroupHelper,0x10),"group dirty outside original scope");
        ++host::groupDirtyCalls;host::interactionEvents.push_back("dirty");host::put(node,0x54,int32_t{-1});return nullptr;
    }
    if(token==0x060025c8){
        host::check(host::expectedGroupHelper && host::read<bool>(host::expectedGroupHelper,0x10) && args && args[0],"group Led removal ABI/scope differs");
        ++host::groupLedCalls;host::interactionEvents.push_back("ledRemove");
        if(object==host::failedGroupLed)throw std::runtime_error("authored original Led removal failure");
        const auto id=*static_cast<uint32_t*>(args[0]);auto& values=host::read<host::Node*>(object,0x10)->values;
        const auto found=std::find(values.begin(),values.end(),id);
        if(found==values.end())return host::boolean(false);
        *found=values.back();values.pop_back();
        if(host::read<uint32_t>(object,0x18)==id)host::put(node,0x18,values.empty()?UINT32_MAX:values.front());
        return host::boolean(true);
    }
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
        if(host::failScopeBegin)throw std::runtime_error("authored original group begin failure");
        return helper;
    }
    if(token==0x060000cd){
        host::interactionEvents.push_back("dispose");
        host::check(host::read<bool>(object,0x10),"scope disposed without begin");
        if(host::read<bool>(object,0x12)){++host::groupNotifications;host::put(node,0x12,false);}
        host::put(node,0x10,false);++node.disposed;return nullptr;
    }
    if(token==0x060025ab){
        host::check(host::expectedGroupHelper && host::read<bool>(host::expectedGroupHelper,0x10),"group Remove outside original scope");
        ++host::groupRemovals;host::interactionEvents.push_back("groupRemove");
        if(host::failGroupRemove)throw std::runtime_error("authored original group Remove failure");
        const auto id=*static_cast<uint32_t*>(args[0]);
        auto erase=[&](host::Node* led){auto& values=host::read<host::Node*>(led,0x10)->values;
            const auto before=values.size();values.erase(std::remove(values.begin(),values.end(),id),values.end());return before!=values.size();};
        const bool removed=erase(host::read<host::Node*>(object,0x18));node.components.erase(id);
        if(!host::leaveGroupTyped)for(auto value:host::read<host::Node*>(object,0x20)->objects)erase(static_cast<host::Node*>(value));
        if(host::stopAfterGroupRemove)host::movementWorld=0;
        return host::boolean(removed);
    }
    if(token==0x060000ce){
        host::check(object==host::expectedGroupHelper && host::read<bool>(object,0x10),"group MarkForFire outside original scope");
        ++host::groupMarks;host::interactionEvents.push_back("mark");
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
bool movementEnabled(){return false;}uint64_t movementWorldId(){return host::movementWorld;}
const std::string& movementMatchId(){return host::movementMatch;}
MovementAdmission movementAdmission(){return {};}
void movementFail(const char*)noexcept{}
}
namespace ba_prediction_movement {bool ownsPresentation(void*){return host::presentationOwned;}}
namespace ba_prediction_stages {static void mark(const char*,void*){}}
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
        host::currentSelector=nullptr;
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
    void repair(){actors::GroupChanges scopes;actors::DeferredSelection selection;actors::repair(state,&manager,&frames,scopes,selection);}
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
    Fixture same(105,100);same.after();
    const auto firstLease=same.state.identities.at(&same.actor).presentationLease;
    check(firstLease && same.token()==900,"first observed actor did not acquire a presentation lease");
    same.after();
    check(same.state.identities.at(&same.actor).presentationLease==firstLease,"ordinary actor observation replaced its presentation lease");
    // The repair's erase can be followed by reuse of the exact same Unit,
    // native ID and canonical incarnation. Only this local lease must change.
    same.state.identities.erase(&same.actor);same.state.confirmedRecreation.insert(7);same.after();
    const auto recreatedLease=same.state.identities.at(&same.actor).presentationLease;
    check(same.token()==900 && recreatedLease>firstLease && same.state.confirmedRecreation.empty(),
          "same-pointer/token recreation reused the retired presentation lease");
    same.state.identities.clear();same.after();
    check(same.state.identities.at(&same.actor).presentationLease>recreatedLease,
          "observer cache clear recycled a presentation lease");
    Fixture exhausted;exhausted.state.nextPresentationLease=UINT64_MAX;bool refused=false;
    try{exhausted.after();}catch(const std::exception& error){refused=std::string(error.what())=="actor presentation lease exhausted";}
    check(refused && exhausted.state.identities.empty() && exhausted.state.nextPresentationLease==UINT64_MAX,
          "presentation lease exhaustion wrapped or inserted an unleased actor");
}
static void cachedZeroCannotPromoteEvenWithKnownMapBeforeOriginal(){
    Fixture f(105,100);f.cache();f.retirement();check(!f.token(),"old speculative actor rebound to a known numeric ID");
}
struct Selection {
    Node set,all,allIDs,subsets,values,enumerator,typed,typedIDs;
    Selection(){
        set.klass=host::type("Uncapped.Collections","UnitSelectionSet");
        all.klass=typed.klass=host::type("","LedUnitSet");
        allIDs.klass=typedIDs.klass=host::type("Uncapped.Collections","EntityIdSet");
        subsets.klass=host::type("System.Collections.Generic","Dictionary`2");values.klass=host::type("Authored","ValueCollection");
        enumerator.klass=host::type("Authored","ValueEnumerator");
        put(set,0x18,static_cast<void*>(&all));put(set,0x20,static_cast<void*>(&subsets));
        put(all,0x10,static_cast<void*>(&allIDs));put(typed,0x10,static_cast<void*>(&typedIDs));
        put(values,0x10,static_cast<void*>(&subsets));subsets.calls["values"]=&values;values.calls["enumerator"]=&enumerator;
        put(enumerator,0x10,static_cast<void*>(&subsets));
        subsets.objects={&typed};enumerator.objects={&typed};setIDs({100},{100});
    }
    void setIDs(std::vector<uint32_t> main,std::vector<uint32_t> cached){
        allIDs.values=std::move(main);typedIDs.values=std::move(cached);set.components.clear();
        put(all,0x18,allIDs.values.empty()?UINT32_MAX:allIDs.values.front());
        put(typed,0x18,typedIDs.values.empty()?UINT32_MAX:typedIDs.values.front());
        put(all,0x1c,UINT32_MAX);put(typed,0x1c,UINT32_MAX);
        for(auto id:allIDs.values)set.components[id]=1;
    }
};
struct Interaction {
    Selection preview,current,casting;
    Node selector,oldActor,ability;
    std::vector<actors::Retire> retire;
    Interaction(){
        ba::initialThread=ba_local::updateThread=GetCurrentThreadId();
        host::failEnumeration=false;selector.klass=host::type("Uncapped","UnitSelector");
        host::focusCalls=0;host::interactionEvents.clear();host::failedRoot=nullptr;
        host::failFocusBefore=host::failFocusAfter=host::focusNoOp=host::failScopeBegin=false;
        host::focusParameterHook={};host::queueLocks=host::castingClears=0;host::failCastingClear=false;
        host::clickNow=10.0f;host::clickClockCalls=0;host::failClickClock=host::wrongClickBox=false;host::clickSingleSize=host::clickModeSize=4;
        put(selector,0x88,static_cast<void*>(&preview.set));put(selector,0x90,static_cast<void*>(&current.set));
        put(selector,0x98,static_cast<void*>(&casting.set));put(selector,0x128,uint32_t{UINT32_MAX});
        put(selector,0x170,int32_t{0});put(selector,0x119,false);put(selector,0x154,host::clickNow);put(selector,0x28,0.25f);
        put(selector,0xa0,int32_t{-1});
        retire.push_back({&oldActor,{7,75,0},{7,75,0},false});
    }
    void held(bool left,bool right){put(selector,0x16c,left);put(selector,0x16d,right);}
    void guard(){actors::guardRetiringInteractions(&selector,retire);}
    void focus(int32_t group=3){put(selector,0xa8,static_cast<void*>(&oldActor));put(selector,0xa0,group);}
    void begin(actors::GroupChanges& changes){
        actors::FocusCancellation focusPlan(&selector,retire);guard();
        changes.prepare({},retire);actors::beginRetirement(changes,focusPlan);
    }
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
static void affectedFocusPreflightIsReadOnlyAndRawClickRemainsRefused(){
    Interaction focus;focus.held(false,true);put(focus.selector,0xa8,static_cast<void*>(&focus.oldActor));focus.guard();
    check(ba::read<void*>(&focus.selector,0xa8)==&focus.oldActor,"focus preflight mutated original focus");
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
template<class F>static void rejected(F action){bool denied=false;try{action();}catch(const std::exception&){denied=true;}check(denied,"expected original focus/preflight refusal");}
static void affectedFocusCancelsOnlyThroughOriginalCurrentGroup(){
    for(int32_t group:{3,-1}){
        Interaction f;f.focus(group);f.held(true,true);actors::GroupChanges changes;f.begin(changes);
        check(host::focusCalls==1 && !ba::read<void*>(&f.selector,0xa8) && ba::read<int32_t>(&f.selector,0xa0)==-1,"affected focus not cancelled exactly once");
        check(changes.mutated,"successful original cancellation did not admit retirement");f.unchanged();
        check(ba::read<bool>(&f.selector,0x16c) && ba::read<bool>(&f.selector,0x16d),"focus cancellation cleared pointer flags");
    }
}
static void unrelatedFocusAndSameNumericIDArePreserved(){
    Interaction f;Node unrelated;put(unrelated,0x14c,uint32_t{7});
    put(f.selector,0xa8,static_cast<void*>(&unrelated));put(f.selector,0xa0,int32_t{4});f.held(false,true);
    actors::GroupChanges changes;f.begin(changes);
    check(!host::focusCalls && ba::read<void*>(&f.selector,0xa8)==&unrelated && ba::read<int32_t>(&f.selector,0xa0)==4,"unrelated actor focus was cancelled by numeric ID");f.unchanged();
}
static void allInteractionRefusalsPrecedeFocusMutation(){
    for(int mode=0;mode<5;++mode){
        Interaction f;f.focus();f.held(true,false);actors::GroupChanges changes;
        if(mode==0)f.casting.setIDs({7},{7});
        if(mode==1)put(f.selector,0x128,uint32_t{7});
        if(mode==2)put(f.selector,0x100,static_cast<void*>(&f.ability));
        if(mode==3)f.current.setIDs({100},{7});
        if(mode==4)host::failEnumeration=true;
        rejected([&]{f.begin(changes);});host::failEnumeration=false;
        check(!host::focusCalls && host::interactionEvents.empty() && !changes.mutated,"later refusal happened after focus/scope mutation");
        check(ba::read<void*>(&f.selector,0xa8)==&f.oldActor && ba::read<int32_t>(&f.selector,0xa0)==3,"refusal changed focus");
    }
}
static void metadataRootsAndCodeAreCheckedBeforeCancellation(){
    for(int mode=0;mode<6;++mode){
        Interaction f;f.focus();actors::GroupChanges changes;
        const auto oldParameter=host::focusParameter;const auto oldResult=host::focusMethod.result;
        const auto oldFunction=host::focusMethod.function;const auto oldCode=host::focusCode[0];
        if(mode==0)host::focusParameter=host::type("System","UInt32");
        if(mode==1)host::focusMethod.result=host::type("System","Int32");
        if(mode==2)host::focusMethod.function=reinterpret_cast<void*>(&host::contains);
        if(mode==3)host::focusCode[0]^=1;
        if(mode==4)host::failedRoot=&f.selector;
        if(mode==5)host::failedRoot=&f.oldActor;
        rejected([&]{f.begin(changes);});
        host::focusParameter=oldParameter;host::focusMethod.result=oldResult;
        host::focusMethod.function=oldFunction;host::focusCode[0]=oldCode;host::failedRoot=nullptr;
        check(!host::focusCalls && host::interactionEvents.empty() && !changes.mutated,"invalid metadata/root/code allowed mutation");f.unchanged();
    }
}
static void groupPreparationFailurePrecedesFocusCancellation(){
    Interaction f;f.focus();actors::FocusCancellation focus(&f.selector,f.retire);f.guard();
    Node missingHelper;actors::GroupChanges changes;
    rejected([&]{changes.prepare({&missingHelper},f.retire);actors::beginRetirement(changes,focus);});
    check(!host::focusCalls && host::interactionEvents.empty() && !changes.mutated,"missing later group owner cancelled focus");
}
struct Scope {
    Node group,helper;
    void add(actors::GroupChanges& changes){
        put(group,0x40,static_cast<void*>(&helper));
        auto value=std::make_unique<actors::GroupChanges::Change>(&group);
        value->begin=&host::scopeBeginMethod;value->dispose=&host::scopeDisposeMethod;
        changes.values.push_back(std::move(value));
    }
};
static void throwingOriginalBeginLeavesFocusAndPoolUntouched(){
    Interaction f;f.focus();actors::FocusCancellation focus(&f.selector,f.retire);f.guard();
    actors::GroupChanges changes;Scope scope;scope.add(changes);host::failScopeBegin=true;
    rejected([&]{actors::beginRetirement(changes,focus);});changes.close();
    check(!host::focusCalls && !changes.mutated && scope.helper.disposed==1,"throwing original Begin reached focus/pool or leaked scope");
    check(host::interactionEvents==std::vector<std::string>({"begin","dispose"}) && ba::read<void*>(&f.selector,0xa8)==&f.oldActor,"Begin exception ordering changed focus");
}
static void focusFailureDoesNotAdmitPoolMutationOrRetry(){
    for(int mode=0;mode<3;++mode){
        Interaction f;f.focus();actors::FocusCancellation focus(&f.selector,f.retire);f.guard();
        actors::GroupChanges changes;Scope scope;scope.add(changes);
        host::failFocusBefore=mode==0;host::failFocusAfter=mode==1;host::focusNoOp=mode==2;
        rejected([&]{actors::beginRetirement(changes,focus);});changes.close();
        check(host::focusCalls==1 && !changes.mutated && scope.helper.disposed==1,"focus exception admitted pool mutation or leaked scope");
        check(host::interactionEvents==std::vector<std::string>({"begin","focus","dispose"}),"focus exception ordering changed");
        rejected([&]{focus.cancel();});check(host::focusCalls==1,"failed original cancellation retried side effects");f.unchanged();
    }
}
static void changedFocusAfterPreflightIsNeverCancelled(){
    for(bool originallyAffected:{false,true}){
        Interaction f;if(originallyAffected)f.focus();Node unrelated;
        actors::FocusCancellation focus(&f.selector,f.retire);f.guard();
        put(f.selector,0xa8,static_cast<void*>(originallyAffected?&unrelated:&f.oldActor));put(f.selector,0xa0,int32_t{5});
        actors::GroupChanges changes;rejected([&]{actors::beginRetirement(changes,focus);});
        check(!host::focusCalls && !changes.mutated && ba::read<int32_t>(&f.selector,0xa0)==5,"prepared plan cancelled changed focus");
    }
}
struct CastingInteraction:Interaction {
    Node server,queue,serialized,simulation,manager;
    actors::State state;
    CastingInteraction(){
        const DWORD thread=GetCurrentThreadId();ba::initialThread=ba_local::updateThread=thread;
        state.thread=thread;state.inUpdate=true;state.world=91;state.match=std::string(32,'b');
        state.simulation=std::make_unique<ba_local::Root>(&simulation);state.manager=std::make_unique<ba_local::Root>(&manager);
        put(server,0x140,static_cast<void*>(&simulation));put(server,0x180,static_cast<void*>(&queue));
        put(server,0x188,static_cast<void*>(&serialized));put(selector,0x40,static_cast<void*>(&manager));
        serialized.values={777,888};host::castingServer=&server;host::castingQueue=&queue;host::expectedCasting=&casting.set;
        host::movementWorld=state.world;host::movementMatch=state.match;host::presentationOwned=true;
        casting.setIDs({7,100},{7,100});focus();
    }
    void run(actors::GroupChanges& changes,const std::vector<void*>& groups={}){
        actors::beginRetiringInteractions(state,&selector,retire,groups,changes);
    }
    void untouched(){
        check(!host::castingClears && !host::focusCalls && !host::queueLocks,"refused preflight reached mutation or leaked queue lock");
        check(casting.allIDs.values==std::vector<uint32_t>({7,100}) && casting.typedIDs.values==std::vector<uint32_t>({7,100}),"refusal altered aliased casting IDs");
        check(serialized.values==std::vector<uint32_t>({777,888}),"serialized queue188 changed");
    }
};
static void staleCastingClearsBeforeFocusAndPreservesQueuesAndSelection(){
    CastingInteraction f;f.held(true,true);actors::GroupChanges changes;f.run(changes);
    check(changes.mutated && host::castingClears==1 && host::focusCalls==1 && !host::queueLocks,"stale casting/focus mutation missing");
    check(f.casting.allIDs.values.empty() && f.casting.typedIDs.values.empty(),"original whole Clear did not remove cached casting memberships");
    check(f.preview.allIDs.values==std::vector<uint32_t>{100} && f.current.allIDs.values==std::vector<uint32_t>{100},"stale cleanup cleared actual selection");
    check(f.queue.values.empty() && f.serialized.values==std::vector<uint32_t>({777,888}),"cleanup altered pending/serialized queues");
    const auto clear=std::find(host::interactionEvents.begin(),host::interactionEvents.end(),"clear");
    const auto focus=std::find(host::interactionEvents.begin(),host::interactionEvents.end(),"focus");
    check(clear<focus && clear+1!=host::interactionEvents.end() && *(clear+1)=="unlock","casting producer lock crossed focus callback");
    check(ba::read<bool>(&f.selector,0x16c) && ba::read<bool>(&f.selector,0x16d),"casting cleanup modified button state");
}
static void actualQueuedAliasAndActiveIntentStillRefuse(){
    for(int mode=0;mode<4;++mode){
        CastingInteraction f;actors::GroupChanges changes;
        if(mode==0)f.queue.values={1};
        if(mode==1)put(f.selector,0x100,static_cast<void*>(&f.ability));
        if(mode==2)put(f.selector,0x128,uint32_t{7});
        if(mode==3){f.held(true,false);f.current.setIDs({100},{7});}
        rejected([&]{f.run(changes);});f.untouched();check(!changes.mutated,"active interaction reached pool admission");
    }
}
static void pendingCommandRaceRechecksBeforeAnyMutation(){
    CastingInteraction f;actors::GroupChanges changes;
    host::focusParameterHook=[&]{f.queue.values={123};};
    rejected([&]{f.run(changes);});f.untouched();
    check(f.queue.values==std::vector<uint32_t>{123} && !changes.mutated,"race drained/ignored new command alias");
}
static void castingOwnersAndOriginalClearAreStrict(){
    for(int mode=0;mode<9;++mode){
        CastingInteraction f;actors::GroupChanges changes;
        auto result=host::clearMethod.result;auto function=host::clearMethod.function;const auto code=host::clearCode[0];
        if(mode==0)host::movementWorld=92;
        if(mode==1)host::movementMatch=std::string(32,'c');
        if(mode==2)host::presentationOwned=false;
        if(mode==3)++ba_local::updateThread;
        if(mode==4)put(f.server,0x140,static_cast<void*>(&f.oldActor));
        if(mode==5)host::failedRoot=&f.queue;
        if(mode==6)host::clearMethod.result=host::type("System","Int32");
        if(mode==7)host::clearMethod.function=reinterpret_cast<void*>(&host::contains);
        if(mode==8)host::clearCode[0]^=1;
        rejected([&]{f.run(changes);});
        host::clearMethod.result=result;host::clearMethod.function=function;host::clearCode[0]=code;host::failedRoot=nullptr;
        f.untouched();check(!changes.mutated,"invalid casting owner/ABI reached pool admission");
    }
}
static void laterGroupOrFocusFailurePreventsStaleClear(){
    for(bool badFocus:{false,true}){
        CastingInteraction f;actors::GroupChanges changes;Node missingHelper;
        auto result=host::focusMethod.result;if(badFocus)host::focusMethod.result=host::type("System","Int32");
        rejected([&]{f.run(changes,badFocus?std::vector<void*>{}:std::vector<void*>{&missingHelper});});
        host::focusMethod.result=result;f.untouched();check(!changes.mutated,"later preflight happened after stale Clear");
    }
}
static void originalClearFailureUnlocksBeforeFocusOrPool(){
    CastingInteraction f;actors::GroupChanges changes;host::failCastingClear=true;
    rejected([&]{f.run(changes);});host::failCastingClear=false;
    check(host::castingClears==1 && !host::focusCalls && !host::queueLocks && !changes.mutated,"throwing original Clear leaked lock/reached focus/pool");
    check(f.casting.allIDs.values==std::vector<uint32_t>({7,100}) && f.serialized.values==std::vector<uint32_t>({777,888}),"throwing Clear lost commands");
}
static void ghostCastingIsClearedButUnaffectedScratchIsPreserved(){
    CastingInteraction ghost;ghost.casting.setIDs({100},{7});actors::GroupChanges changed;ghost.run(changed);
    check(host::castingClears==1 && ghost.casting.typedIDs.values.empty(),"ghost cached casting ID escaped original Clear");
    CastingInteraction unaffected;unaffected.casting.setIDs({100},{100});unaffected.queue.values={1};
    host::presentationOwned=false;actors::GroupChanges preserved;unaffected.run(preserved);
    check(!host::castingClears && !host::queueLocks && unaffected.casting.allIDs.values==std::vector<uint32_t>{100} && unaffected.queue.values==std::vector<uint32_t>{1},"unaffected scratch unnecessarily touched commands/owner path");
}
struct DeferredHQ:Fixture {
    Node selector,batch,batchIDs,simulation,recreated,recreatedConfig;
    std::vector<actors::Retire> retired;
    DeferredHQ():Fixture(163,153){
        host::selectionRemovals=0;host::removedSelectionIds.clear();host::interactionEvents.clear();
        host::failSelectionRemoval=host::stopOnSelectionRemoval=false;host::failedRoot=nullptr;
        state.thread=GetCurrentThreadId();state.inUpdate=true;state.world=91;state.match=std::string(32,'d');
        state.manager=std::make_unique<ba_local::Root>(&manager);state.simulation=std::make_unique<ba_local::Root>(&simulation);
        host::movementWorld=state.world;host::movementMatch=state.match;host::presentationOwned=true;
        selector.klass=host::type("Uncapped","UnitSelector");put(selector,0x40,static_cast<void*>(&manager));
        host::currentSelector=&selector;
        batch.klass=host::type("Uncapped.Collections","UnitSet");batchIDs.klass=host::type("Uncapped.Collections","EntityIdSet");
        batchIDs.values={5};put(batch,0x18,static_cast<void*>(&batchIDs));
        identity(5,3,1);current(5,3,1);state.admission.entities.clear();admit(5,3,1,700);cache(5,3,1,700);setActive(false);
        recreated.klass=host::type("Uncapped","Unit");recreatedConfig.klass=host::type("Uncapped","EntityConfig");
        put(recreated,0x14c,uint32_t{5});put(recreated,0x150,uint32_t{1});
        put(recreated,0x168,static_cast<void*>(&recreatedConfig));put(recreatedConfig,0x10,uint32_t{3});
        retired.push_back({&actor,{5,3,1},{5,3,1},true});
    }
    ~DeferredHQ(){host::currentSelector=nullptr;host::failSelectionRemoval=host::stopOnSelectionRemoval=false;}
    bool prepare(actors::DeferredSelection& selection){
        return selection.prepare(state,&selector,&batch,&host::removeSelectionMethod,&frames,retired);
    }
    void recreate(bool promote=true){
        put(activeIDs,0x10,1);put(activeArray,0x20,static_cast<void*>(&recreated));
        if(promote)after();
    }
    void noRemoval(){check(!host::selectionRemovals && host::removedSelectionIds.empty(),"selection notified before coherent recreation");}
};
static void deferredHQPreflightRejectsUnsupportedBatchesAndAbility(){
    for(int mode=0;mode<8;++mode){
        DeferredHQ f;actors::DeferredSelection pending;
        if(mode==0)f.retired.push_back({&f.recreated,{6,3,1},{6,3,1},false});
        if(mode==1)f.retired.push_back({&f.recreated,{6,3,1},{6,3,1},true});
        if(mode==2)put(f.selector,0x100,static_cast<void*>(&f.recreated));
        if(mode==3)f.retired[0].current.unitType=75;
        if(mode==4)f.retired[0].current.armyId=0;
        if(mode==5)f.retired[0].current.entityId=6;
        if(mode==6)f.retired[0].resident.unitType=75;
        if(mode==7)f.batchIDs.values={6};
        rejected([&]{f.prepare(pending);});f.noRemoval();
    }
    DeferredHQ active;active.retired[0].alreadyReleased=false;actors::DeferredSelection ordinary;
    check(!active.prepare(ordinary) && !ordinary.batch,"ordinary active retirement was newly deferred");active.noRemoval();
}
static void deferredHQWaitsForActualAfterAdmission(){
    for(int mode=0;mode<4;++mode){
        DeferredHQ f;actors::DeferredSelection pending;check(f.prepare(pending),"retained HQ was not deferred");f.noRemoval();
        if(mode>=1)f.recreate(mode>=2);
        if(mode==2)f.state.identities[&f.recreated].incarnation=701;
        if(mode<3){rejected([&]{pending.commit(f.state);});f.noRemoval();}
        else {
            check(f.state.identities.at(&f.recreated).incarnation==700,"actual after() did not admit new HQ lifetime");
            pending.commit(f.state);check(host::selectionRemovals==1 && host::removedSelectionIds==std::vector<uint32_t>{5},"original post-recreation removal missing");
            rejected([&]{pending.commit(f.state);});check(host::selectionRemovals==1,"original removal was retried");
        }
    }
}
static void deferredSnapshotSurvivesPooledObjectReuse(){
    DeferredHQ f;actors::DeferredSelection pending;check(f.prepare(pending),"snapshot preparation missing");
    put(f.actor,0x14c,uint32_t{99});f.recreate();pending.commit(f.state);
    check(pending.frozenIds==std::vector<uint32_t>{5} && host::removedSelectionIds==std::vector<uint32_t>{5},"pooled actor's changed ID rebound removal");
}
static void deferredBatchMutationAndWrongReplacementRefuse(){
    for(int mode=0;mode<4;++mode){
        DeferredHQ f;actors::DeferredSelection pending;f.prepare(pending);f.recreate();
        if(mode==0)f.batchIDs.values={5,99};
        if(mode==1)put(f.recreatedConfig,0x10,uint32_t{75});
        if(mode==2)put(f.recreated,0x150,uint32_t{0});
        if(mode==3)put(f.recreated,0x14c,uint32_t{6});
        rejected([&]{pending.commit(f.state);});f.noRemoval();
        check(pending.frozenIds==std::vector<uint32_t>{5},"caller mutation changed independent ID snapshot");
    }
}
static void deferredFrameOwnerAndAbilityChangesRefuse(){
    for(int mode=0;mode<6;++mode){
        DeferredHQ f;actors::DeferredSelection pending;f.prepare(pending);f.recreate();Node changed;
        if(mode==0)put(f.frame,0x40,164);
        if(mode==1)host::currentSelector=&changed;
        if(mode==2)host::presentationOwned=false;
        if(mode==3)put(f.selector,0x100,static_cast<void*>(&changed));
        if(mode==4)f.state.simulation=std::make_unique<ba_local::Root>(&changed);
        if(mode==5)f.state.manager=std::make_unique<ba_local::Root>(&changed);
        rejected([&]{pending.commit(f.state);});f.noRemoval();
    }
}
static void failedGenerationNeverFlushesOnDestruction(){
    for(bool recreate:{false,true}){
        DeferredHQ f;
        {actors::DeferredSelection pending;f.prepare(pending);if(recreate)f.recreate();}
        f.noRemoval(); // Aborted owner never implicitly flushes even a ready plan.
    }
    for(int mode=0;mode<4;++mode){
        DeferredHQ f;
        {actors::DeferredSelection pending;f.prepare(pending);f.recreate();
            if(mode==0)host::movementWorld=0;
            if(mode==1)host::movementMatch=std::string(32,'x');
            if(mode==2)f.state.failed=true;
            if(mode==3)f.state.inUpdate=false;
            rejected([&]{pending.commit(f.state);});f.noRemoval();
        }
        f.noRemoval();
    }
}
static void throwingOrStoppingCallbackCannotFlushTwice(){
    for(bool stop:{false,true}){
        DeferredHQ f;
        {actors::DeferredSelection pending;f.prepare(pending);f.recreate();
            host::failSelectionRemoval=!stop;host::stopOnSelectionRemoval=stop;
            rejected([&]{pending.commit(f.state);});
            check(pending.attempted && host::selectionRemovals==1,"original failing callback was not exactly once");
            rejected([&]{pending.commit(f.state);});check(host::selectionRemovals==1,"callback failure retried removal");
            if(stop)rejected([&]{actors::requireOwned(f.state);});
        }
        check(host::selectionRemovals==1,"destructor retried a failed callback");
    }
}
static void ownershipGuardRejectsContinuationAfterCallbackStop(){
    for(int mode=0;mode<4;++mode){
        DeferredHQ f;actors::requireOwned(f.state);
        if(mode==0)host::movementWorld=0;
        if(mode==1)host::movementMatch=std::string(32,'z');
        if(mode==2)f.state.failed=true;
        if(mode==3)f.state.thread=GetCurrentThreadId()+1;
        rejected([&]{actors::requireOwned(f.state);});f.noRemoval();
    }
}
struct GroupIntent:Fixture {
    Node selector,panel,array,simulation,player,nativeStates;
    std::array<Node,8> groups,helpers;
    std::array<Selection,8> sets;
    uint32_t group;
    explicit GroupIntent(uint32_t index=4):Fixture(110,100),group(index) {
        check(index<groups.size(),"authored group index bound");
        host::interactionEvents.clear();host::failedRoot=nullptr;host::failEnumeration=false;
        host::groupRemovals=host::groupMarks=host::groupNotifications=0;
        host::groupDirtyCalls=host::groupLedCalls=0;host::failedGroupLed=nullptr;
        host::failGroupRemove=host::leaveGroupTyped=host::failGroupMark=host::stopAfterGroupRemove=false;
        host::failScopeBegin=false;host::scopeBeginMethod.flags=host::groupRemoveMethod.flags=host::groupMarkMethod.flags=0;
        ba::initialThread=ba_local::updateThread=GetCurrentThreadId();
        state.thread=GetCurrentThreadId();state.inUpdate=true;state.world=93;state.match=std::string(32,'g');
        state.manager=std::make_unique<ba_local::Root>(&manager);state.simulation=std::make_unique<ba_local::Root>(&simulation);
        state.groupGeneration=1;state.groupIntent.reset(1);cache(7,75,0,900);
        host::movementWorld=state.world;host::movementMatch=state.match;host::presentationOwned=true;
        selector.klass=host::type("Uncapped","UnitSelector");panel.klass=host::type("Uncapped","ControlGroupPanel");
        simulation.klass=host::type("Uncapped","Simulation");player.klass=host::type("Uncapped","SimPlayer");
        nativeStates.klass=host::type("Authored","ComponentBuffer");nativeStates.components={{7,0}};
        frame.calls["get_StateBuffer"]=&nativeStates;put(actor,0x158,static_cast<void*>(&nativeStates));put(actor,0x160,false);
        put(selector,0x40,static_cast<void*>(&manager));put(selector,0x38,static_cast<void*>(&panel));
        put(panel,0x38,static_cast<void*>(&array));put(array,0x18,uintptr_t{8});
        put(simulation,0x148,static_cast<void*>(&frames));put(simulation,0x90,static_cast<void*>(&player));put(player,0x38,uint32_t{0});
        for(uint32_t i=0;i<8;++i) {
            groups[i].klass=host::type("Uncapped","ControlGroup");helpers[i].klass=host::type("Authored","GroupHelper");
            put(array,0x20+i*sizeof(void*),static_cast<void*>(&groups[i]));
            put(groups[i],0x38,i);put(groups[i],0x60,static_cast<void*>(&manager));
            put(groups[i],0x48,static_cast<void*>(&simulation));put(groups[i],0x40,static_cast<void*>(&helpers[i]));
            put(groups[i],0x20,static_cast<void*>(&sets[i].set));put(helpers[i],0x18,static_cast<void*>(&groups[i]));
            put(sets[i].set,0x48,static_cast<void*>(&frames));sets[i].setIDs({},{});
        }
        sets[group].setIDs({7,99},{7,99});host::expectedGroupHelper=&helpers[group];host::currentSelector=&selector;
        setActive(false);position.components.clear();type.components.clear();army.components.clear();
    }
    ~GroupIntent(){
        host::currentSelector=nullptr;host::expectedGroupHelper=nullptr;host::failedRoot=nullptr;
        host::scopeBeginMethod.flags=host::groupRemoveMethod.flags=host::groupMarkMethod.flags=0;
        host::failGroupRemove=host::leaveGroupTyped=host::failGroupMark=host::stopAfterGroupRemove=host::failScopeBegin=false;
    }
    bool preserve(uint32_t id=7){return actors::preserveReleasedGroupMember(state,&sets[group].set,id);}
    void reconcile(){actors::reconcileGroupIntent(state);}
    void unchanged(){
        check(sets[group].allIDs.values==std::vector<uint32_t>({7,99})&&
            sets[group].typedIDs.values==std::vector<uint32_t>({7,99})&&
            !host::groupRemovals&&!host::groupMarks&&!host::groupNotifications&&
            !host::groupDirtyCalls&&!host::groupLedCalls,
            "group intent preflight changed original membership/notification");
    }
};
static void groupIntentHostModelsOriginalSurgicalCacheAPIs(){
    GroupIntent f;check(f.preserve(),"authored preservation failed");f.admit(7,76,0,901);f.current(7,76,0);
    actors::GroupSelectionPurge purge(&f.sets[f.group].set);
    bool playerInitiated=false;void* args[]={&playerInitiated};
    const auto begin=actors::method(&f.groups[f.group],"BeginControlGroupChange",1,0x06001645,0x3ea5790);
    const auto dispose=actors::method(&f.helpers[f.group],"Dispose",0,0x060000cd,0x3b02160);
    check(actors::invoke(begin,&f.groups[f.group],args)==&f.helpers[f.group],"original helper host scope differs");
    check(purge.erase({7}),"original raw helper did not remove the invalidated member");
    actors::invoke(dispose,&f.helpers[f.group]);
    check(f.sets[f.group].allIDs.values==std::vector<uint32_t>{99}&&f.sets[f.group].typedIDs.values==std::vector<uint32_t>{99}&&
        host::read<uint32_t>(&f.sets[f.group].all,0x18)==99&&host::read<uint32_t>(&f.sets[f.group].typed,0x18)==99&&
        host::groupDirtyCalls==1&&host::groupLedCalls==2&&!host::groupRemovals&&f.helpers[f.group].disposed==1&&
        f.state.groupIntent.entries().at({f.group,7}).token==900,"surgical host changed unrelated members or caller-owned acknowledgement");
}
static void groupIntentPreservesActualTypedMembershipIncludingGroupZero(){
    for(uint32_t index:{0u,4u}){
        GroupIntent f(index);check(f.preserve(),"same confirmed actor absence was not preserved");
        check(f.preserve()&&f.state.groupIntent.entries().size()==1,"repeat release consumed metadata twice");
        f.reconcile();f.unchanged();
        check(f.state.groupIntent.entries().at({index,7}).token==900,"group intent recorded wrong incarnation");
    }
}
static void groupIntentNonmemberAndIneligibleReleaseForwardsWithoutMetadata(){
    for(int mode=0;mode<7;++mode){
        GroupIntent f;
        if(mode==0)f.sets[f.group].setIDs({99},{99});
        if(mode==1)f.state.identities.clear();
        if(mode==2)f.state.identities[&f.actor].incarnation=0;
        if(mode==3)f.state.admission.entities.clear();
        if(mode==4)f.state.identities[&f.actor].identity.unitType=3;
        if(mode==5)put(f.player,0x38,uint32_t{1});
        if(mode==6)f.current(7,75,0);
        check(!f.preserve()&&f.state.groupIntent.entries().empty(),"nonmember/ineligible release kept hidden intent");
        check(!host::groupRemovals&&!host::groupMarks,"forward decision invoked an original mutation");
    }
}
static void groupIntentVisibleUserClearReplaceAndNoopAreNeverReadded(){
    for(int mode=0;mode<3;++mode){
        GroupIntent f;check(f.preserve(),"authored preservation failed");
        const std::vector<uint32_t> accepted=mode==1?std::vector<uint32_t>{88}:std::vector<uint32_t>{};
        f.sets[f.group].setIDs(accepted,accepted); // Accepted original external edit.
        if(mode==2)f.sets[f.group].setIDs({},{}); // Repeated empty/no-op clear.
        f.reconcile();
        check(f.state.groupIntent.entries().empty()&&f.sets[f.group].allIDs.values==accepted&&
            f.sets[f.group].typedIDs.values==accepted&&!host::groupRemovals&&!host::groupMarks,
            "original accepted clear/replace was undone by pending metadata");
        f.setActive(true);f.current(7,75,0);f.reconcile();
        check(f.sets[f.group].allIDs.values==accepted,"recreation re-added explicitly removed membership");
    }
}
static void groupIntentSameRecreatedLeaseForgetsMetadataWithoutMutation(){
    GroupIntent f;check(f.preserve(),"authored preservation failed");f.setActive(true);f.current(7,75,0);f.reconcile();
    check(f.state.groupIntent.entries().empty(),"recreated same lease retained provisional metadata");f.unchanged();
}
static void groupIntentUninitializedOrStillDeadActorCannotForgetObligation(){
    for(int mode=0;mode<6;++mode){
        GroupIntent f;check(f.preserve(),"authored preservation failed");f.setActive(true);f.current(7,75,0);
        if(mode==0)put(f.actor,0x158,static_cast<void*>(nullptr));
        if(mode==1)put(f.actor,0x160,true);
        if(mode==2)f.nativeStates.components[7]=6;
        if(mode==3)put(f.frame,0x40,113);
        if(mode==4)f.current(7,76,0);
        if(mode==5)f.state.identities[&f.actor].incarnation=0;
        f.reconcile();check(f.state.groupIntent.entries().size()==1,"transient old actor retired pending canonical obligation");f.unchanged();
    }
    GroupIntent missing;check(missing.preserve(),"authored preservation failed");missing.setActive(true);missing.current(7,75,0);
    missing.nativeStates.components.clear();rejected([&]{missing.reconcile();});
    check(missing.state.groupIntent.entries().size()==1,"missing native state silently forgot obligation");missing.unchanged();
}
static void groupIntentCanonicalLossPurgesThroughOriginalScopeAndNotification(){
    for(int mode=0;mode<4;++mode){
        GroupIntent f;check(f.preserve(),"authored preservation failed");
        if(mode==0)f.state.admission.entities.clear();
        if(mode==1)f.admit(7,75,0,901);
        if(mode==2)f.admit(7,76,0,900);
        if(mode==3)f.admit(7,75,1,900);
        f.reconcile();
        check(f.state.groupIntent.entries().empty()&&f.sets[f.group].allIDs.values==std::vector<uint32_t>{99}&&
            f.sets[f.group].typedIDs.values==std::vector<uint32_t>{99},"canonical loss left all/type membership or removed another unit");
        check(!host::groupRemovals&&host::groupLedCalls==2&&host::groupDirtyCalls==1&&
            host::groupMarks==1&&host::groupNotifications==1&&f.helpers[f.group].disposed==1&&
            !host::read<bool>(&f.helpers[f.group],0x10)&&
            host::interactionEvents==std::vector<std::string>({"begin","dirty","ledRemove","ledRemove","mark","dispose"}),
            "original canonical purge scope/notification ordering differs");
        f.reconcile();check(host::groupLedCalls==2&&host::groupDirtyCalls==1,"finished purge was repeated");
    }
}
static void groupIntentTypedInconsistencyRefusesBeforeDecliningOriginalRemove(){
    for(int mode=0;mode<4;++mode){
        GroupIntent f;Node extra,extraIDs;
        if(mode==0)f.sets[f.group].setIDs({7,99},{99});
        if(mode==1)f.sets[f.group].setIDs({99},{7,99});
        if(mode==2)f.sets[f.group].setIDs({7,7},{7});
        if(mode==3){extra.klass=f.sets[f.group].typed.klass;extraIDs.klass=f.sets[f.group].typedIDs.klass;extraIDs.values={7};
            put(extra,0x10,static_cast<void*>(&extraIDs));f.sets[f.group].subsets.objects.push_back(&extra);f.sets[f.group].enumerator.objects.push_back(&extra);}
        rejected([&]{f.preserve();});check(f.state.groupIntent.entries().empty()&&!host::groupRemovals,
            "inconsistent typed cache entered preservation metadata");
    }
}
static void groupIntentOwnerMetadataAndSignatureRefuseBeforeMutation(){
    for(int mode=0;mode<7;++mode){
        GroupIntent f;
        if(mode==0)host::movementWorld=0;
        if(mode==1)host::presentationOwned=false;
        if(mode==2)put(f.groups[f.group],0x60,static_cast<void*>(&f.simulation));
        if(mode==3)put(f.helpers[f.group],0x18,static_cast<void*>(&f.groups[0]));
        if(mode==4)put(f.sets[f.group].set,0x48,static_cast<void*>(&f.simulation));
        if(mode==5)host::groupRemoveMethod.flags=0x10;
        if(mode==6)f.state.groupGeneration=2;
        rejected([&]{f.preserve();});check(f.state.groupIntent.entries().empty(),"invalid owner recorded group intent");f.unchanged();
    }
}
static void groupIntentPurgePreflightAndOriginalFailuresRetainMetadata(){
    for(int mode=0;mode<5;++mode){
        GroupIntent f;check(f.preserve(),"authored preservation failed");f.state.admission.entities.clear();
        if(mode==0)host::groupMarkMethod.flags=0x10;
        if(mode==1)host::failScopeBegin=true;
        if(mode==2)host::failedGroupLed=&f.sets[f.group].all;
        if(mode==3)host::failedGroupLed=&f.sets[f.group].typed;
        if(mode==4)host::failGroupMark=true;
        rejected([&]{f.reconcile();});check(f.state.groupIntent.entries().size()==1,
            "failed original purge discarded its acknowledgement metadata");
        check(!host::read<bool>(&f.helpers[f.group],0x10),"failed original purge leaked scope");
        check(f.helpers[f.group].disposed==(mode==0?0u:1u),"failed original purge retried Dispose");
        if(mode<3)check(f.sets[f.group].allIDs.values==std::vector<uint32_t>({7,99}),"pre-mutation refusal changed visible group");
        if(mode==3)check(!host::groupMarks,"incomplete typed removal emitted original success notification");
        check(!host::groupRemovals&&host::groupLedCalls==(mode<2?0u:(mode==2?1u:2u))&&
            host::groupDirtyCalls==(mode<2?0u:1u),"failure control did not reach the expected original raw API stage");
    }
}
static void expiredClick(CastingInteraction& f){
    f.held(false,false);
    put(f.selector,0x128,uint32_t{7});put(f.selector,0x170,int32_t{0});put(f.selector,0x119,false);
    put(f.selector,0x154,9.0f);put(f.selector,0x28,0.25f);host::clickNow=10.0f;
}
static void clickPredicatesPreserveHistory(CastingInteraction& f,const std::array<unsigned char,0x220>& history){
    check(f.selector.bytes==history,"click-history predicates changed selector fields");
    check(f.preview.allIDs.values==std::vector<uint32_t>{100}&&f.current.allIDs.values==std::vector<uint32_t>{100},
        "click-history predicates changed selection");f.untouched();
    check(host::interactionEvents.empty(),"click-history predicates entered original mutation callbacks");
}
static void expiredIdleClickHistoryDoesNotOwnRetiringActor(){
    CastingInteraction f;expiredClick(f);
    // Authored values use the ORIGINAL Single arithmetic. No QPC/Double clock
    // or fabricated pointer callback is part of this isolated source regression.
    check(host::clickNow-host::read<float>(&f.selector,0x154)>host::read<float>(&f.selector,0x28),
        "authored idle history is not actually expired");
    const auto history=f.selector.bytes;bool guardAllowed=true;std::string refusal;
    try{actors::guardRetiringInteractions(&f.selector,f.retire,true);}
    catch(const std::exception& error){guardAllowed=false;refusal=error.what();}
    actors::CastingCleanupAccess access(f.state,&f.selector,f.retire);access.validate();
    const bool cleanupReportsLive=access.hasAffectedLiveClick();
    clickPredicatesPreserveHistory(f,history);
    std::cout<<"expired idle click: affected ID7, mode0, buttons up, drag false, Single now10-last9 > window0.25; actor_allowed="
        <<guardAllowed<<", casting_reports_live="<<cleanupReportsLive<<", history unchanged; actor refusal="<<refusal<<'\n';
    check(guardAllowed&&!cleanupReportsLive,
        "expired idle click history is still treated as live ownership by actor/casting guards");
    check(host::clickClockCalls==2,"both actual click entrypoints did not read the original Single clock exactly once");
}
static void clickRefusesThroughBothActualEntryPoints(CastingInteraction& f,const char* name){
    const auto history=f.selector.bytes;bool actorRefused=false,cleanupRefused=false;
    try{actors::guardRetiringInteractions(&f.selector,f.retire,true);}catch(const std::exception&){actorRefused=true;}
    try{actors::CastingCleanupAccess access(f.state,&f.selector,f.retire);access.validate();cleanupRefused=access.hasAffectedLiveClick();}
    catch(const std::exception&){cleanupRefused=true;}
    check(actorRefused&&cleanupRefused,(std::string("actual click entrypoints accepted live/unknown history: ")+name).c_str());
    clickPredicatesPreserveHistory(f,history);
}
static void liveDeferredHeldAndMalformedHistoryRefuse(){
    const char* cases[]={"equality","recent","deferred-single","deferred-double","primary-held","context-held","dragging",
        "negative-now","negative-last","negative-window","clock-backwards","NaN-now","NaN-last","NaN-window",
        "infinite-now","infinite-last","infinite-window","unknown-mode","invalid-primary-byte","invalid-context-byte","invalid-drag-byte"};
    for(int mode=0;mode<21;++mode){CastingInteraction f;expiredClick(f);
        const auto nan=std::numeric_limits<float>::quiet_NaN(),inf=std::numeric_limits<float>::infinity();
        if(mode==0)host::clickNow=9.25f;if(mode==1)host::clickNow=9.125f;
        if(mode==2)put(f.selector,0x170,int32_t{1});if(mode==3)put(f.selector,0x170,int32_t{2});
        if(mode==4)f.held(true,false);if(mode==5)f.held(false,true);if(mode==6)put(f.selector,0x119,true);
        if(mode==7)host::clickNow=-1.f;if(mode==8)put(f.selector,0x154,-1.f);if(mode==9)put(f.selector,0x28,-0.25f);
        if(mode==10)host::clickNow=8.f;if(mode==11)host::clickNow=nan;if(mode==12)put(f.selector,0x154,nan);
        if(mode==13)put(f.selector,0x28,nan);if(mode==14)host::clickNow=inf;if(mode==15)put(f.selector,0x154,inf);
        if(mode==16)put(f.selector,0x28,inf);if(mode==17)put(f.selector,0x170,int32_t{3});
        if(mode==18)put(f.selector,0x16c,uint8_t{2});if(mode==19)put(f.selector,0x16d,uint8_t{2});
        if(mode==20)put(f.selector,0x119,uint8_t{2});clickRefusesThroughBothActualEntryPoints(f,cases[mode]);
    }
}
static void originalClickFieldEnumClockAndBoxABIFailClosed(){
    const char* cases[]={"Single-field-type","Single-field-offset","Single-field-static","Single-size","enum-parent","enum-literal",
        "clock-static","clock-return-Double","clock-arity","clock-target","clock-entry","clock-box","clock-exception","enum-size"};
    for(int mode=0;mode<14;++mode){CastingInteraction f;expiredClick(f);
        const auto oldField=host::fields.at("_doubleClickTime"),oldLiteral=host::clickLiterals.at("None");
        const auto oldMethod=host::clickTimeMethod;auto* const modeType=host::type("","DeferredClickMode");
        auto* const oldDeclaring=modeType->declaring;const auto code=host::clickClockCode[0];
        if(mode==0)host::fields.at("_doubleClickTime").type=host::type("System","Double");
        if(mode==1)host::fields.at("_doubleClickTime").offset=0x2c;
        if(mode==2)host::fields.at("_doubleClickTime").flags=0x10;if(mode==3)host::clickSingleSize=8;
        if(mode==4)modeType->declaring=host::type("Uncapped","ControlGroup");if(mode==5)host::clickLiterals.at("None").literal=7;
        if(mode==6)host::clickTimeMethod.flags=0;if(mode==7)host::clickTimeMethod.result=host::type("System","Double");
        if(mode==8)host::clickTimeMethod.parameters=1;if(mode==9)host::clickTimeMethod.function=reinterpret_cast<void*>(&host::contains);
        if(mode==10)host::clickClockCode[0]^=1;if(mode==11)host::wrongClickBox=true;if(mode==12)host::failClickClock=true;
        if(mode==13)host::clickModeSize=8;
        try{clickRefusesThroughBothActualEntryPoints(f,cases[mode]);}
        catch(...){host::fields.at("_doubleClickTime")=oldField;host::clickLiterals.at("None")=oldLiteral;
            host::clickTimeMethod=oldMethod;modeType->declaring=oldDeclaring;host::clickClockCode[0]=code;throw;}
        host::fields.at("_doubleClickTime")=oldField;host::clickLiterals.at("None")=oldLiteral;
        host::clickTimeMethod=oldMethod;modeType->declaring=oldDeclaring;host::clickClockCode[0]=code;
    }
}
static void unmatchedClickDoesNotReadClockOrHistoryMetadata(){
    CastingInteraction f;expiredClick(f);put(f.selector,0x128,uint32_t{99});host::failClickClock=true;
    const auto oldField=host::fields.at("_doubleClickTime");host::fields.at("_doubleClickTime").type=nullptr;
    const auto history=f.selector.bytes;
    try{actors::guardRetiringInteractions(&f.selector,f.retire,true);
        actors::CastingCleanupAccess access(f.state,&f.selector,f.retire);access.validate();
        check(!access.hasAffectedLiveClick()&&!host::clickClockCalls,"unmatched history entered the original clock path");
        clickPredicatesPreserveHistory(f,history);
    }catch(...){host::fields.at("_doubleClickTime")=oldField;throw;}
    host::fields.at("_doubleClickTime")=oldField;
}
static void expiredPreparationCannotClearAfterClickBecomesLive(){
    for(bool held:{false,true}){CastingInteraction f;expiredClick(f);
        actors::CastingCleanupAccess access(f.state,&f.selector,f.retire);actors::CastingCleanup plan(access,true);plan.prepare();
        if(held)f.held(true,false);else put(f.selector,0x154,host::clickNow);
        const auto history=f.selector.bytes;rejected([&]{plan.commit();});f.untouched();
        check(f.selector.bytes==history&&host::interactionEvents==std::vector<std::string>({"lock","unlock"}),
            "live click at commit cleared scratch, changed history, or entered another mutation callback");
    }
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
    test::affectedFocusPreflightIsReadOnlyAndRawClickRemainsRefused();test::unresolvedActiveCasterRefusesHeldOnly();
    test::boundsAndEnumeratorOwnerRefuse();test::exceptionDisposesEnumeratorWithoutClearing();
    test::cachedSubsetValuesRequireExactLedClass();test::noButtonPathKeepsOriginalSelectedGuard();test::allSubsetsAreInspectedAndBounded();
    test::affectedFocusCancelsOnlyThroughOriginalCurrentGroup();test::unrelatedFocusAndSameNumericIDArePreserved();
    test::allInteractionRefusalsPrecedeFocusMutation();test::metadataRootsAndCodeAreCheckedBeforeCancellation();
    test::groupPreparationFailurePrecedesFocusCancellation();test::throwingOriginalBeginLeavesFocusAndPoolUntouched();
    test::focusFailureDoesNotAdmitPoolMutationOrRetry();test::changedFocusAfterPreflightIsNeverCancelled();
    test::staleCastingClearsBeforeFocusAndPreservesQueuesAndSelection();test::actualQueuedAliasAndActiveIntentStillRefuse();
    test::pendingCommandRaceRechecksBeforeAnyMutation();test::castingOwnersAndOriginalClearAreStrict();
    test::laterGroupOrFocusFailurePreventsStaleClear();test::originalClearFailureUnlocksBeforeFocusOrPool();
    test::ghostCastingIsClearedButUnaffectedScratchIsPreserved();
    test::deferredHQPreflightRejectsUnsupportedBatchesAndAbility();test::deferredHQWaitsForActualAfterAdmission();
    test::deferredSnapshotSurvivesPooledObjectReuse();test::deferredBatchMutationAndWrongReplacementRefuse();
    test::deferredFrameOwnerAndAbilityChangesRefuse();test::failedGenerationNeverFlushesOnDestruction();
    test::throwingOrStoppingCallbackCannotFlushTwice();test::ownershipGuardRejectsContinuationAfterCallbackStop();
    test::groupIntentPreservesActualTypedMembershipIncludingGroupZero();test::groupIntentNonmemberAndIneligibleReleaseForwardsWithoutMetadata();
    test::groupIntentVisibleUserClearReplaceAndNoopAreNeverReadded();test::groupIntentSameRecreatedLeaseForgetsMetadataWithoutMutation();
    test::groupIntentUninitializedOrStillDeadActorCannotForgetObligation();
    test::groupIntentCanonicalLossPurgesThroughOriginalScopeAndNotification();test::groupIntentTypedInconsistencyRefusesBeforeDecliningOriginalRemove();
    test::groupIntentOwnerMetadataAndSignatureRefuseBeforeMutation();test::groupIntentPurgePreflightAndOriginalFailuresRetainMetadata();
    std::cout<<"prior53 actual-source authored flow groups PASS; testing expired click history\n";
    test::expiredIdleClickHistoryDoesNotOwnRetiringActor();
    test::liveDeferredHeldAndMalformedHistoryRefuse();test::originalClickFieldEnumClockAndBoxABIFailClosed();
    test::unmatchedClickDoesNotReadClockOrHistoryMetadata();test::expiredPreparationCannotClearAfterClickBecomesLive();
    test::groupIntentHostModelsOriginalSurgicalCacheAPIs();
    std::cout<<"actor binding/held gesture/focus/casting/deferred/group-intent/click:59 actual-source authored flow groups PASS; no Unity/IL2CPP/native engine execution\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
