// Authored independent API host for the ACTUAL group-retirement header.
// Infrastructure follows the existing raw-reader host; no Unity/IL2CPP/DLL loads.
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <functional>
#include <iostream>
#include <map>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace host {
using Obj=void*;
struct Class;
struct Type {Class* klass=nullptr;bool byref=false;};
struct Field {Class* parent=nullptr;Type* type=nullptr;size_t offset=0;uint32_t flags=0;};
struct Method {const char* name=nullptr;uint32_t token=0,flags=0;uintptr_t rva=0;Type* result=nullptr;std::vector<Type*> params;Class* owner=nullptr;};
struct Class {
    const char* space="";const char* name="";Class* declaring=nullptr;
    bool value=false;int32_t size=0;uint32_t alignment=4;
    std::map<std::string,Field> fields;std::vector<Method*> methods;
};
struct Node {
    Class* klass=nullptr;std::array<unsigned char,128> bytes{};
    std::array<unsigned char,8> box{};std::vector<uint32_t> ids;
};
struct OriginalError {int tag=0;};
static void check(bool value,const char* reason){if(!value)throw std::runtime_error(reason);}
struct Fixture {
    Class selectionClass,ledClass,dictionaryClass,idClass,keyClass,wrongClass,viewClass,valuesClass,iteratorClass;
    Class booleanClass,integerClass,voidClass,unsignedClass;
    std::vector<std::unique_ptr<Type>> types;
    std::vector<std::unique_ptr<Node>> nodes;
    Node* selection=nullptr;Node* all=nullptr;Node* dictionary=nullptr;Node* values=nullptr;Node* iterator=nullptr;
    Node* boxBool=nullptr;Node* boxInt=nullptr;
    Method getTyped,lookup,count,getValues,enumerate,move,current,dispose,remove,dirty;
    unsigned dirtyCalls=0,removeCalls=0,failRemoveOn=0,failDisposeOn=0;
    bool failDirty=false,noDirty=false,failAfterRemove=false,falseRemove=false,dropUnrelated=false,badLeader=false,badMemory=false;
    std::vector<std::string> events;
    std::map<uint32_t,Node*> entries;std::vector<Node*> iterated;
    std::vector<int32_t> counts;
    size_t cursor=0;unsigned countCalls=0,lookupCalls=0,enumerateCalls=0,moveCalls=0,currentCalls=0,disposeCalls=0,unboxes=0,logs=0;
    bool failMove=false,failCurrent=false,failDispose=false,failLookup=false;
    bool falseWithOut=false,trueWithoutOut=false,invalidLookupBool=false;
    Node* overrideLookupOut=nullptr;
    Node* failIds=nullptr;bool failIteratorCreation=false;
    std::function<void(const char*)> hook;
    Fixture();
    Type* makeType(Class* klass,bool byref=false) {
        types.push_back(std::make_unique<Type>(Type{klass,byref}));return types.back().get();
    }
    Node* node(Class* klass) {
        nodes.push_back(std::make_unique<Node>());nodes.back()->klass=klass;return nodes.back().get();
    }
    template<class T>void put(Node* target,size_t offset,T value) {
        check(offset+sizeof(T)<=target->bytes.size(),"authored write bounds");
        memcpy(target->bytes.data()+offset,&value,sizeof(T));
    }
    Node* led(std::initializer_list<uint32_t> entriesIds) {
        Node* result=node(&ledClass);Node* entityIds=node(&idClass);entityIds->ids=entriesIds;
        put(result,0x10,entityIds);put(result,0x18,entriesIds.size()?*entriesIds.begin():UINT32_MAX);put(result,0x1c,UINT32_MAX);return result;
    }
    Node* raw(Node* ledNode) {
        Node* result=nullptr;memcpy(&result,ledNode->bytes.data()+0x10,sizeof(result));return result;
    }
    void event(const char* name){events.push_back(name);if(hook)hook(name);}
};
static Fixture* active=nullptr;
Fixture::Fixture() {
    selectionClass.space="Uncapped.Collections";selectionClass.name="UnitSelectionSet";
    ledClass.name="LedUnitSet";ledClass.declaring=&selectionClass;
    dictionaryClass.space="System.Collections.Generic";dictionaryClass.name="Dictionary`2";
    idClass.space="Uncapped.Collections";idClass.name="EntityIdSet";
    keyClass.space="Uncapped";keyClass.name="IntKey`1";keyClass.value=true;keyClass.size=4;
    wrongClass.space="Authored";wrongClass.name="Other";
    viewClass.name="SelectedEntitiesOfType";viewClass.value=true;viewClass.size=16;viewClass.declaring=&selectionClass;
    valuesClass.name="ValueCollection";valuesClass.declaring=&dictionaryClass;
    iteratorClass.name="Enumerator";iteratorClass.value=true;iteratorClass.size=24;iteratorClass.alignment=8;
    booleanClass.space="System";booleanClass.name="Boolean";booleanClass.value=true;booleanClass.size=1;
    integerClass.space="System";integerClass.name="Int32";integerClass.value=true;integerClass.size=4;
    voidClass.space="System";voidClass.name="Void";
    unsignedClass.space="System";unsignedClass.name="UInt32";unsignedClass.value=true;unsignedClass.size=4;
    auto field=[&](Class& owner,const char* name,size_t offset,Class& value) {
        owner.fields[name]=Field{&owner,makeType(&value),offset,0};
    };
    field(selectionClass,"_allUnits",0x18,ledClass);field(selectionClass,"_subsetsByType",0x20,dictionaryClass);
    field(ledClass,"<Entities>k__BackingField",0x10,idClass);
    field(ledClass,"<Leader>k__BackingField",0x18,unsignedClass);field(ledClass,"_lastKnownLeaderId",0x1c,unsignedClass);
    field(selectionClass,"<OnlyHQSelected>k__BackingField",0x58,booleanClass);
    field(selectionClass,"_recomputeOverallLeader",0x10,booleanClass);
    field(selectionClass,"_lastFrameCountRecalculated",0x54,integerClass);
    field(valuesClass,"_dictionary",0x10,dictionaryClass);field(iteratorClass,"_dictionary",0x10,dictionaryClass);
    auto method=[&](Method& value,Class& owner,const char* name,uint32_t token,Class& result,std::vector<Type*> params,uintptr_t rva=0) {
        value.owner=&owner;value.name=name;value.token=token;value.rva=rva;value.result=makeType(&result);value.params=std::move(params);
        owner.methods.push_back(&value);
    };
    method(getTyped,selectionClass,"GetUnitsOfType",0x060025a1,viewClass,{makeType(&keyClass)},0x3c65810);
    method(lookup,dictionaryClass,"TryGetValue",0x06002de7,booleanClass,{makeType(&keyClass),makeType(&ledClass,true)});
    method(count,dictionaryClass,"get_Count",0x06002dcc,integerClass,{});
    method(getValues,dictionaryClass,"get_Values",0x06002dd0,valuesClass,{});
    method(enumerate,valuesClass,"GetEnumerator",0x06002e18,iteratorClass,{});
    method(move,iteratorClass,"MoveNext",0x06002e27,booleanClass,{});
    method(current,iteratorClass,"get_Current",0x06002e28,ledClass,{});
    method(dispose,iteratorClass,"Dispose",0x06002e26,voidClass,{});
    method(remove,ledClass,"Remove",0x060025c8,booleanClass,{makeType(&unsignedClass)},0x3c699b0);
    method(dirty,selectionClass,"MarkCountAsDirty",0x0600259a,voidClass,{},0x3c63de0);
    selection=node(&selectionClass);all=led({5});dictionary=node(&dictionaryClass);
    values=node(&valuesClass);iterator=node(&iteratorClass);
    boxBool=node(&booleanClass);boxInt=node(&integerClass);
    put(selection,0x18,all);put(selection,0x20,dictionary);
    put(values,0x10,dictionary);put(iterator,0x10,dictionary);entries[3]=led({5});
}
static Obj klass(Obj object){check(object,"authored missing object");return static_cast<Node*>(object)->klass;}
template<class T>static T read(Obj object,size_t offset) {
    check(object,"authored null read");
    for(auto* method:{&active->getTyped,&active->lookup,&active->count,&active->getValues,&active->enumerate,&active->move,&active->current,&active->dispose,&active->remove,&active->dirty}) {
        if(object==method) {
            check(!offset && sizeof(T)==sizeof(Obj),"authored method read");
            T result{};memcpy(&result,&object,sizeof(T));return result;
        }
    }
    auto* node=static_cast<Node*>(object);check(offset+sizeof(T)<=node->bytes.size(),"authored read bounds");
    T result{};memcpy(&result,node->bytes.data()+offset,sizeof(T));return result;
}
static Obj field(Obj object,const char* name) {
    auto* value=static_cast<Class*>(klass(object));const auto found=value->fields.find(name);
    check(found!=value->fields.end(),"authored missing field");return &found->second;
}
static Obj type(const char* space,const char* name) {
    for(auto* value:{&active->selectionClass,&active->ledClass,&active->dictionaryClass,&active->idClass,&active->keyClass,
            &active->wrongClass,&active->viewClass,&active->valuesClass,&active->iteratorClass,
            &active->booleanClass,&active->integerClass,&active->voidClass,&active->unsignedClass}) {
        if(!strcmp(value->space,space) && !strcmp(value->name,name))return value;
    }
    throw std::runtime_error("authored missing class");
}
static Obj methodOwner(Obj value){return static_cast<Method*>(value)->owner;}
static Obj classFromType(Obj value){check(value,"authored missing type");return static_cast<Type*>(value)->klass;}
static bool byref(Obj value){check(value,"authored missing byref type");return static_cast<Type*>(value)->byref;}
static Obj returnType(Obj value){return static_cast<Method*>(value)->result;}
static Obj parameter(Obj value,uint32_t index){return static_cast<Method*>(value)->params.at(index);}
static uint32_t flags(Obj value,uint32_t* implementation){*implementation=0;return static_cast<Method*>(value)->flags;}
static Obj fieldParent(Obj value){return static_cast<Field*>(value)->parent;}
static Obj fieldType(Obj value){return static_cast<Field*>(value)->type;}
static uint32_t fieldFlags(Obj value){return static_cast<Field*>(value)->flags;}
static size_t fieldOffset(Obj value){return static_cast<Field*>(value)->offset;}
static const char* className(Obj value){return static_cast<Class*>(value)->name;}
static const char* classSpace(Obj value){return static_cast<Class*>(value)->space;}
static Obj declaring(Obj value){return static_cast<Class*>(value)->declaring;}
static bool isValue(Obj value){return static_cast<Class*>(value)->value;}
static int32_t valueSize(Obj value,uint32_t* alignment) {
    auto* klass=static_cast<Class*>(value);*alignment=klass->alignment;return klass->size;
}
static Obj methods(Obj value,void** iterator) {
    auto& methods=static_cast<Class*>(value)->methods;const auto index=reinterpret_cast<uintptr_t>(*iterator);
    if(index>=methods.size())return nullptr;
    *iterator=reinterpret_cast<void*>(index+1);return methods[index];
}
static const char* methodName(Obj value){return static_cast<Method*>(value)->name;}
static uint32_t methodToken(Obj value){return static_cast<Method*>(value)->token;}
static uint32_t paramCount(Obj value){return static_cast<uint32_t>(static_cast<Method*>(value)->params.size());}
static Obj unbox(Obj value) {
    auto* node=static_cast<Node*>(value);++active->unboxes;
    if(node->klass==&active->iteratorClass)return value;
    return node->box.data();
}
template<class T>static Obj box(Node* node,T value){memcpy(node->box.data(),&value,sizeof(value));return node;}
static Obj invoke(Obj info,Obj object,void** args=nullptr) {
    auto& f=*active;auto* method=static_cast<Method*>(info);f.event(method->name);
    if(method==&f.dirty){
        ++f.dirtyCalls;check(object==f.selection && !args,"authored dirty owner/arity");
        check(f.enumerateCalls==f.disposeCalls,"count invalidation preceded census cleanup");
        if(f.failDirty)throw OriginalError{8};if(!f.noDirty)f.put(f.selection,0x54,int32_t{-1});return nullptr;
    }
    if(method==&f.remove){
        ++f.removeCalls;check(object && args && args[0],"authored Led Remove ABI");
        int32_t invalidated=0;memcpy(&invalidated,f.selection->bytes.data()+0x54,4);
        check(invalidated==-1 && f.disposeCalls>0 && f.enumerateCalls==f.disposeCalls,"removal before dirty/census cleanup");
        if(f.failRemoveOn==f.removeCalls&&!f.failAfterRemove)throw OriginalError{7};
        auto* led=static_cast<Node*>(object);auto& values=f.raw(led)->ids;const auto id=*static_cast<uint32_t*>(args[0]);
        const auto found=std::find(values.begin(),values.end(),id);const bool removed=found!=values.end();
        if(removed){*found=values.back();values.pop_back();uint32_t leader=0;memcpy(&leader,led->bytes.data()+0x18,4);
            if(leader==id)f.put(led,0x18,values.empty()?UINT32_MAX:values.front());}
        if(f.dropUnrelated)values.clear();if(f.badLeader)f.put(led,0x18,id);if(f.badMemory)f.put(led,0x1c,uint32_t{42});
        if(f.failRemoveOn==f.removeCalls&&f.failAfterRemove)throw OriginalError{7};
        return box(f.boxBool,f.falseRemove?false:removed);
    }
    if(method==&f.count) {
        check(object==f.dictionary,"authored count owner");const auto index=f.countCalls++;
        const int32_t value=index<f.counts.size()?f.counts[index]:static_cast<int32_t>(f.entries.size());
        return box(f.boxInt,value);
    }
    if(method==&f.lookup) {
        ++f.lookupCalls;check(object==f.dictionary && args,"authored lookup owner/args");
        if(f.failLookup)throw OriginalError{4};
        const uint32_t key=*static_cast<uint32_t*>(args[0]);
        const auto found=f.entries.find(key);const bool exists=found!=f.entries.end();
        *static_cast<Obj*>(args[1])=f.overrideLookupOut?f.overrideLookupOut:(f.trueWithoutOut?nullptr:(exists?found->second:nullptr));
        if(f.invalidLookupBool)return box(f.boxBool,uint8_t{2});
        return box(f.boxBool,f.falseWithOut?false:(f.trueWithoutOut?true:exists));
    }
    if(method==&f.getValues){check(object==f.dictionary,"authored Values owner");return f.values;}
    if(method==&f.enumerate) {
        ++f.enumerateCalls;check(object==f.values,"authored enumeration owner");
        if(f.failIteratorCreation)throw OriginalError{5};
        f.cursor=0;f.iterated.clear();for(const auto& pair:f.entries)f.iterated.push_back(pair.second);return f.iterator;
    }
    if(method==&f.move) {
        ++f.moveCalls;check(object==f.iterator,"authored iterator must use unboxed receiver");
        if(f.failMove)throw OriginalError{1};
        const bool more=f.cursor<f.iterated.size();if(more)++f.cursor;return box(f.boxBool,more);
    }
    if(method==&f.current) {
        ++f.currentCalls;check(object==f.iterator && f.cursor,"authored Current receiver");
        if(f.failCurrent)throw OriginalError{2};return f.iterated.at(f.cursor-1);
    }
    if(method==&f.dispose) {
        ++f.disposeCalls;check(object==f.iterator,"authored Dispose receiver");
        if(f.failDispose || f.failDisposeOn==f.disposeCalls)throw OriginalError{3};return nullptr;
    }
    throw std::runtime_error("authored unexpected original invocation");
}
}
namespace ba {
using host::Obj;
static Obj klass(Obj object){return host::klass(object);}
template<class T>static T read(Obj object,size_t offset){return host::read<T>(object,offset);}
static Obj field(Obj object,const char* name){return host::field(object,name);}
static void log(const char*,...){++host::active->logs;}
template<class T>static T api(const char* name) {
#define HOST_API(Name,Function) if(!strcmp(name,Name))return reinterpret_cast<T>(&host::Function)
    HOST_API("il2cpp_class_from_type",classFromType);HOST_API("il2cpp_type_is_byref",byref);
    HOST_API("il2cpp_method_get_return_type",returnType);HOST_API("il2cpp_method_get_param",parameter);
    HOST_API("il2cpp_method_get_flags",flags);HOST_API("il2cpp_field_get_parent",fieldParent);
    HOST_API("il2cpp_field_get_type",fieldType);HOST_API("il2cpp_field_get_flags",fieldFlags);
    HOST_API("il2cpp_field_get_offset",fieldOffset);HOST_API("il2cpp_class_get_name",className);
    HOST_API("il2cpp_class_get_namespace",classSpace);HOST_API("il2cpp_class_get_declaring_type",declaring);
    HOST_API("il2cpp_class_is_valuetype",isValue);HOST_API("il2cpp_class_value_size",valueSize);
    HOST_API("il2cpp_class_get_methods",methods);HOST_API("il2cpp_method_get_name",methodName);
    HOST_API("il2cpp_method_get_token",methodToken);HOST_API("il2cpp_method_get_param_count",paramCount);
    HOST_API("il2cpp_object_unbox",unbox);HOST_API("il2cpp_method_get_declaring_type",methodOwner);
#undef HOST_API
    throw std::runtime_error(std::string("authored unknown API: ")+name);
}
}
namespace ba_prediction_actors {
using host::Obj;
constexpr size_t maximumActors=8192;
struct Root {Obj value=nullptr;explicit Root(Obj object):value(object){}Root(const Root&)=delete;Root& operator=(const Root&)=delete;Obj get()const{return value;}};
static void require(bool value,const char* reason){host::check(value,reason);}
static Obj type(const char* space,const char* name){return host::type(space,name);}
static void classIs(Obj object,const char* space,const char* name) {
    require(object && ba::klass(object)==type(space,name),"authored concrete class differs");
}
static void field(Obj object,const char* name,size_t offset) {
    require(host::fieldOffset(ba::field(object,name))==offset,"authored field offset differs");
}
static Obj method(Obj object,const char* name,unsigned count,uint32_t token,uintptr_t rva=0) {
    for(auto* value:static_cast<host::Class*>(ba::klass(object))->methods) {
        if(!strcmp(value->name,name) && value->token==token && value->params.size()==count) {
            require(!rva || value->rva==rva,"authored original RVA differs");return value;
        }
    }
    throw std::runtime_error("authored original method missing");
}
static Obj invoke(Obj info,Obj object,void** args=nullptr){return host::invoke(info,object,args);}
template<class T>static T unbox(Obj object) {
    require(object,"authored null box");return *static_cast<T*>(host::unbox(object));
}
static std::vector<uint32_t> ids(Obj object) {
    require(object && ba::klass(object)==&host::active->idClass,"authored EntityIdSet class differs");
    if(object==host::active->failIds)throw host::OriginalError{6};
    return static_cast<host::Node*>(object)->ids;
}
static void clickScalarSize(Obj value,int32_t expected) {
    uint32_t alignment=0;require(host::valueSize(value,&alignment)==expected,"authored scalar size differs");
}
#include "../src/prediction_click_selection.hpp"
#include "../src/prediction_group_retirement.hpp"
}
namespace host {
using Purge=ba_prediction_actors::GroupSelectionPurge;
static unsigned cases=0;
static uint32_t scalar(Node* node,size_t offset){return read<uint32_t>(node,offset);}
static void set(Fixture& f,Node* led,std::initializer_list<uint32_t> values,uint32_t leader=UINT32_MAX) {
    f.raw(led)->ids=values;
    f.put(led,0x18,values.size()?(leader==UINT32_MAX?*values.begin():leader):UINT32_MAX);
}
static void exact(Fixture& f,Node* led,std::vector<uint32_t> expected) {
    auto actual=f.raw(led)->ids;std::sort(actual.begin(),actual.end());std::sort(expected.begin(),expected.end());
    check(actual==expected,"unrelated raw membership changed");
    const auto leader=scalar(led,0x18);
    check(leader==UINT32_MAX || (!actual.empty() && std::binary_search(actual.begin(),actual.end(),leader)),"raw leader invalid");
}
static void run(const char* name,const std::function<void(Fixture&)>& body) {
    Fixture f;active=&f;try{body(f);++cases;}
    catch(...){std::cerr<<"FAIL "<<name<<'\n';throw;}
}
static void refused(const std::function<void()>& body) {
    bool threw=false;try{body();}catch(const std::exception&){threw=true;}
    check(threw,"ABI/owner/corruption was accepted");
}
static void originalError(const std::function<void()>& body,int expected) {
    int found=0;try{body();}catch(const OriginalError& error){found=error.tag;}
    check(found==expected,"original exception changed or disappeared");
}
static void noMutation(Fixture& f){check(!f.dirtyCalls&&!f.removeCalls,"prevalidation mutated selection");}
}
int main(){using namespace host;try{
    run("pending unaffected ID survives",[](Fixture& f){
        set(f,f.all,{5,99});set(f,f.entries[3],{5,99});Purge plan(f.selection);plan.erase({5});
        exact(f,f.all,{99});exact(f,f.entries[3],{99});
        check(f.dirtyCalls==1&&f.removeCalls==2&&f.disposeCalls==2,"original API/cleanup count differs");
        check(!f.lookupCalls,"purge consulted a live typed lookup");
    });
    run("unresolved pending leader preserved without removal",[](Fixture& f){
        set(f,f.all,{99});set(f,f.entries[3],{99});
        f.put(f.all,0x18,UINT32_MAX);f.put(f.entries[3],0x18,UINT32_MAX);
        f.put(f.selection,0x10,uint8_t{0});f.put(f.selection,0x38,uint32_t{5});
        Purge plan(f.selection);plan.validate();plan.erase({5});
        exact(f,f.all,{99});exact(f,f.entries[3],{99});noMutation(f);
        check(scalar(f.all,0x18)==UINT32_MAX&&scalar(f.entries[3],0x18)==UINT32_MAX&&
            scalar(f.selection,0x38)==5&&!read<uint8_t>(f.selection,0x10)&&!f.lookupCalls,
            "unresolved pending leader/derived cache was rewritten");
    });
    for(uint8_t recompute:{uint8_t{0},uint8_t{1}})run(recompute?"unresolved partial removal with recompute":"unresolved partial removal without recompute",[&](Fixture& f){
        set(f,f.all,{5,99});set(f,f.entries[3],{5,99});
        for(auto* led:{f.all,f.entries[3]}){f.put(led,0x18,UINT32_MAX);f.put(led,0x1c,uint32_t{5});}
        f.put(f.selection,0x10,recompute);f.put(f.selection,0x38,uint32_t{5});
        Purge(f.selection).erase({5});exact(f,f.all,{99});exact(f,f.entries[3],{99});
        check(f.removeCalls==2&&f.dirtyCalls==1&&!f.lookupCalls&&
            scalar(f.all,0x18)==UINT32_MAX&&scalar(f.entries[3],0x18)==UINT32_MAX&&
            scalar(f.all,0x1c)==5&&scalar(f.entries[3],0x1c)==5&&
            read<uint8_t>(f.selection,0x10)==recompute&&scalar(f.selection,0x38)==5,
            "unresolved removal changed original leader/derived semantics");
    });
    run("unresolved final member removal",[](Fixture& f){
        f.put(f.all,0x18,UINT32_MAX);f.put(f.entries[3],0x18,UINT32_MAX);
        Purge(f.selection).erase({5});exact(f,f.all,{});exact(f,f.entries[3],{});
        check(f.removeCalls==2&&scalar(f.all,0x18)==UINT32_MAX&&scalar(f.entries[3],0x18)==UINT32_MAX,
            "unresolved final removal lost sentinel semantics");
    });
    run("empty all non-sentinel leader refused",[](Fixture& f){
        set(f,f.all,{});f.put(f.all,0x18,uint32_t{5});refused([&]{Purge plan(f.selection);});noMutation(f);
    });
    run("empty typed non-sentinel leader refused",[](Fixture& f){
        set(f,f.entries[3],{});f.put(f.entries[3],0x18,uint32_t{5});Purge plan(f.selection);
        refused([&]{plan.erase({5});});noMutation(f);check(f.disposeCalls==1,"invalid empty typed leader leaked iterator");
    });
    run("stale old type and new type ghosts",[](Fixture& f){
        set(f,f.all,{5,99,7});set(f,f.entries[3],{5,99});f.entries[8]=f.led({5,7});f.entries[12]=f.led({5});
        Purge plan(f.selection);plan.erase({5});exact(f,f.all,{7,99});exact(f,f.entries[3],{99});
        exact(f,f.entries[8],{7});exact(f,f.entries[12],{});check(f.removeCalls==4,"not every raw cache purged");
    });
    run("typed ghost when all lacks ID",[](Fixture& f){
        set(f,f.all,{99});set(f,f.entries[3],{5,99});Purge(f.selection).erase({5});
        exact(f,f.all,{99});exact(f,f.entries[3],{99});check(f.removeCalls==1&&f.dirtyCalls==1,"typed-only ghost not purged");
    });
    run("fresh bucket after construction",[](Fixture& f){
        Purge plan(f.selection);f.entries[8]=f.led({5,99});plan.erase({5});exact(f,f.entries[8],{99});
        check(f.removeCalls==3,"new genuine bucket omitted");
    });
    run("remove leader swap order",[](Fixture& f){
        set(f,f.all,{5,99,7});set(f,f.entries[3],{5,99,7});f.put(f.selection,0x10,uint8_t{1});
        Purge(f.selection).erase({5});exact(f,f.all,{7,99});exact(f,f.entries[3],{7,99});
        check(scalar(f.all,0x18)!=5&&read<uint8_t>(f.selection,0x10)==1,"original overall-leader flag changed");
    });
    run("nonleader remains leader",[](Fixture& f){
        set(f,f.all,{5,99},99);set(f,f.entries[3],{5,99},99);Purge(f.selection).erase({5});
        check(scalar(f.all,0x18)==99&&scalar(f.entries[3],0x18)==99,"nonleader removal replaced leader");
    });
    run("final member leaders sentinel",[](Fixture& f){
        Purge(f.selection).erase({5});exact(f,f.all,{});exact(f,f.entries[3],{});
        check(ba_prediction_actors::clickSelectionShape(f.selection,5,3,false),"raw reader disagrees after purge");
    });
    run("preserve preferred leader memory",[](Fixture& f){
        f.put(f.all,0x1c,uint32_t{5});f.put(f.entries[3],0x1c,uint32_t{5});Purge(f.selection).erase({5});
        check(scalar(f.all,0x1c)==5&&scalar(f.entries[3],0x1c)==5,"last-known leader overwritten");
    });
    run("deduplicate targets",[](Fixture& f){Purge(f.selection).erase({5,5});check(f.removeCalls==2,"duplicate target repeated mutation");});
    run("empty target no API mutation",[](Fixture& f){Purge(f.selection).erase({});noMutation(f);check(!f.disposeCalls,"empty target enumerated");});
    run("absent target no API mutation",[](Fixture& f){Purge(f.selection).erase({77});noMutation(f);check(f.disposeCalls==1,"absent census cleanup");});
    run("empty cached buckets retained",[](Fixture& f){f.entries[8]=f.led({});Purge(f.selection).erase({5});exact(f,f.entries[8],{});check(f.entries.size()==2,"dictionary bucket removed");});
    run("sentinel rejected",[](Fixture& f){Purge plan(f.selection);refused([&]{plan.erase({UINT32_MAX});});noMutation(f);});
    run("target budget",[](Fixture& f){Purge plan(f.selection);refused([&]{plan.erase(std::vector<uint32_t>(8193,5));});noMutation(f);});
    run("OnlyHQ before constructor",[](Fixture& f){f.put(f.selection,0x58,uint8_t{1});refused([&]{Purge plan(f.selection);});noMutation(f);});
    run("OnlyHQ before erase",[](Fixture& f){Purge plan(f.selection);f.put(f.selection,0x58,uint8_t{1});refused([&]{plan.erase({5});});noMutation(f);});
    run("bad all leader refused",[](Fixture& f){f.put(f.all,0x18,uint32_t{99});refused([&]{Purge plan(f.selection);});noMutation(f);});
    run("bad later bucket prevalidated",[](Fixture& f){f.entries[8]=f.led({99});f.put(f.entries[8],0x18,uint32_t{5});Purge plan(f.selection);refused([&]{plan.erase({5});});noMutation(f);check(f.disposeCalls==1,"late refusal leaked iterator");});
    run("duplicate raw IDs",[](Fixture& f){set(f,f.entries[3],{5,5});Purge plan(f.selection);refused([&]{plan.erase({5});});noMutation(f);});
    run("aliased Led",[](Fixture& f){f.entries[8]=f.entries[3];Purge plan(f.selection);refused([&]{plan.erase({5});});noMutation(f);});
    run("aliased Entities",[](Fixture& f){f.entries[8]=f.led({5});f.put(f.entries[8],0x10,f.raw(f.entries[3]));Purge plan(f.selection);refused([&]{plan.erase({5});});noMutation(f);});
    run("owner all replaced",[](Fixture& f){Purge plan(f.selection);f.put(f.selection,0x18,f.entries[3]);refused([&]{plan.validate();});noMutation(f);});
    run("owner dictionary replaced",[](Fixture& f){Purge plan(f.selection);f.put(f.selection,0x20,f.values);refused([&]{plan.erase({5});});noMutation(f);});
    run("all Entity owner replaced before erase",[](Fixture& f){Purge plan(f.selection);f.put(f.all,0x10,f.raw(f.entries[3]));refused([&]{plan.erase({5});});noMutation(f);check(!f.enumerateCalls,"changed prepared storage acquired iterator");});
    run("UInt32 not value type",[](Fixture& f){f.unsignedClass.value=false;refused([&]{Purge plan(f.selection);});noMutation(f);});
    run("UInt32 wrong alignment",[](Fixture& f){f.unsignedClass.alignment=8;refused([&]{Purge plan(f.selection);});noMutation(f);});
    run("invalid OnlyHQ byte",[](Fixture& f){f.put(f.selection,0x58,uint8_t{2});refused([&]{Purge plan(f.selection);});noMutation(f);});
    run("Entity storage replaced during census",[](Fixture& f){Purge plan(f.selection);f.hook=[&](const char* n){if(!strcmp(n,"Dispose"))f.put(f.all,0x10,f.raw(f.entries[3]));};refused([&]{plan.erase({5});});noMutation(f);});
    for(int mode=0;mode<16;++mode)run(("mutator/derived ABI "+std::to_string(mode)).c_str(),[&](Fixture& f){
        if(mode==0)f.remove.flags=0x10;if(mode==1)f.remove.result=f.makeType(&f.integerClass);
        if(mode==2)f.remove.result->byref=true;if(mode==3)f.remove.params[0]->byref=true;
        if(mode==4)f.remove.params[0]=f.makeType(&f.integerClass);if(mode==5)f.remove.params.clear();
        if(mode==6)++f.remove.rva;if(mode==7)f.remove.owner=&f.wrongClass;
        if(mode==8)f.dirty.flags=0x10;if(mode==9)f.dirty.result=f.makeType(&f.integerClass);
        if(mode==10)f.dirty.params.push_back(f.makeType(&f.unsignedClass));if(mode==11)++f.dirty.rva;
        if(mode==12)f.dirty.owner=&f.wrongClass;
        if(mode==13)f.selectionClass.fields["<OnlyHQSelected>k__BackingField"].type=f.makeType(&f.integerClass);
        if(mode==14)f.selectionClass.fields["_lastFrameCountRecalculated"].flags=0x10;
        if(mode==15)f.ledClass.fields["<Leader>k__BackingField"].offset=0x1c;
        refused([&]{Purge plan(f.selection);});noMutation(f);
    });
    run("count negative",[](Fixture& f){f.counts={-1};Purge plan(f.selection);refused([&]{plan.erase({5});});noMutation(f);});
    run("count bound",[](Fixture& f){f.counts={8193};Purge plan(f.selection);refused([&]{plan.erase({5});});noMutation(f);});
    run("typed census ID budget",[](Fixture& f){f.raw(f.entries[3])->ids.clear();for(uint32_t i=0;i<8192;++i)f.raw(f.entries[3])->ids.push_back(i);f.put(f.entries[3],0x18,uint32_t{0});f.entries[8]=f.led({9999});Purge plan(f.selection);refused([&]{plan.erase({5});});noMutation(f);check(f.disposeCalls==1,"budget leaked iterator");});
    run("missing iterator cleanup metadata",[](Fixture& f){f.iteratorClass.methods.pop_back();Purge plan(f.selection);refused([&]{plan.erase({5});});noMutation(f);check(!f.enumerateCalls,"bad cleanup acquired iterator");});
    run("wrong iterator owner",[](Fixture& f){f.put(f.iterator,0x10,f.all);Purge plan(f.selection);refused([&]{plan.erase({5});});noMutation(f);check(f.disposeCalls==1,"wrong owner cleanup missing");});
    run("Move failure cleanup",[](Fixture& f){f.failMove=true;Purge plan(f.selection);originalError([&]{plan.erase({5});},1);noMutation(f);check(f.disposeCalls==1,"Move failure cleanup");});
    run("Current failure cleanup",[](Fixture& f){f.failCurrent=true;Purge plan(f.selection);originalError([&]{plan.erase({5});},2);noMutation(f);check(f.disposeCalls==1,"Current failure cleanup");});
    run("Dispose failure before writes",[](Fixture& f){f.failDispose=true;Purge plan(f.selection);originalError([&]{plan.erase({5});},3);noMutation(f);check(f.disposeCalls==1,"Dispose retried");});
    run("primary exception survives cleanup failure",[](Fixture& f){f.failMove=f.failDispose=true;Purge plan(f.selection);originalError([&]{plan.erase({5});},1);noMutation(f);check(f.disposeCalls==1&&f.logs==1,"original exception/cleanup contract");});
    run("dirty exception stops removals",[](Fixture& f){f.failDirty=true;Purge plan(f.selection);originalError([&]{plan.erase({5});},8);check(f.dirtyCalls==1&&!f.removeCalls&&f.disposeCalls==1,"dirty failure continued");});
    run("dirty effect validated",[](Fixture& f){f.noDirty=true;Purge plan(f.selection);refused([&]{plan.erase({5});});check(!f.removeCalls,"removal before invalidation");});
    for(bool after:{false,true})run(after?"Remove throws after mutation":"Remove throws before mutation",[&](Fixture& f){
        f.failRemoveOn=1;f.failAfterRemove=after;Purge plan(f.selection);originalError([&]{plan.erase({5});},7);
        check(f.removeCalls==1&&f.dirtyCalls==1&&read<int32_t>(f.selection,0x54)==-1&&f.disposeCalls==1,"partial failure continued or left count valid");
        exact(f,f.entries[3],{5});exact(f,f.all,after?std::vector<uint32_t>{}:std::vector<uint32_t>{5});
    });
    run("second removal stops following buckets",[](Fixture& f){set(f,f.all,{5,7,99});set(f,f.entries[3],{5,7,99});f.failRemoveOn=2;Purge plan(f.selection);originalError([&]{plan.erase({5,7});},7);check(f.removeCalls==2&&read<int32_t>(f.selection,0x54)==-1,"partial loop continued");exact(f,f.entries[3],{5,7,99});});
    for(int mode=0;mode<4;++mode)run(("corrupt original mutation "+std::to_string(mode)).c_str(),[&](Fixture& f){
        set(f,f.all,{5,99});set(f,f.entries[3],{5,99});
        if(mode==0)f.falseRemove=true;if(mode==1)f.dropUnrelated=true;if(mode==2)f.badLeader=true;if(mode==3)f.badMemory=true;
        Purge plan(f.selection);refused([&]{plan.erase({5});});check(f.removeCalls==1&&f.dirtyCalls==1,"bad mutation reached another bucket");
    });
    run("owner replaced by original mutation",[](Fixture& f){Purge plan(f.selection);f.hook=[&](const char* n){if(!strcmp(n,"Remove"))f.put(f.selection,0x20,f.values);};refused([&]{plan.erase({5});});check(f.removeCalls==1,"owner failure continued");});
    run("postverification cleanup exactly once",[](Fixture& f){f.failDisposeOn=2;Purge plan(f.selection);originalError([&]{plan.erase({5});},3);check(f.disposeCalls==2&&f.removeCalls==2&&read<int32_t>(f.selection,0x54)==-1,"post cleanup retried or lost invalidation");});
    run("raw typed pending multi-member ownership",[](Fixture& f){
        set(f,f.all,{5,99,7});set(f,f.entries[3],{5,99});f.entries[8]=f.led({7});
        Purge plan(f.selection);check(plan.hasTypedMember(5,3)&&plan.hasTypedMember(99,3)&&plan.hasTypedMember(7,8),"raw typed ownership unavailable");
        exact(f,f.all,{5,7,99});exact(f,f.entries[3],{5,99});noMutation(f);
        check(f.lookupCalls==3&&f.disposeCalls==6&&f.enumerateCalls==6&&
            std::find(f.events.begin(),f.events.end(),"GetUnitsOfType")==f.events.end(),"query used filtered view or leaked census");
    });
    run("raw typed unresolved leader ownership",[](Fixture& f){
        set(f,f.all,{5,99});set(f,f.entries[3],{5,99});f.put(f.all,0x18,UINT32_MAX);f.put(f.entries[3],0x18,UINT32_MAX);
        check(Purge(f.selection).hasTypedMember(99,3),"sentinel pending leader refused");noMutation(f);
        check(scalar(f.all,0x18)==UINT32_MAX&&scalar(f.entries[3],0x18)==UINT32_MAX,"query rewrote leader");
    });
    run("raw typed absent all wins over multiple ghosts",[](Fixture& f){
        set(f,f.all,{});f.entries[8]=f.led({5});check(!Purge(f.selection).hasTypedMember(5,3),"removed raw membership was protected");
        noMutation(f);check(!f.lookupCalls&&f.disposeCalls==1,"absent query changed/looked up ghosts");exact(f,f.entries[3],{5});exact(f,f.entries[8],{5});
    });
    run("raw typed empty cache absence",[](Fixture& f){set(f,f.all,{});f.entries.clear();check(!Purge(f.selection).hasTypedMember(5,3),"empty set became present");noMutation(f);check(f.disposeCalls==1,"empty census cleanup");});
    run("raw typed fresh original removal wins",[](Fixture& f){
        Purge plan(f.selection);check(plan.hasTypedMember(5,3),"initial raw membership missing");set(f,f.all,{});
        check(!plan.hasTypedMember(5,3),"query reused stale raw all-set");noMutation(f);check(f.lookupCalls==1&&f.disposeCalls==3,"fresh query cleanup differs");
    });
    run("raw typed missing expected key refuses",[](Fixture& f){f.entries[8]=f.entries[3];f.entries.erase(3);Purge plan(f.selection);refused([&]{plan.hasTypedMember(5,3);});noMutation(f);check(f.disposeCalls==1,"missing lookup leaked census");});
    run("raw typed wrong expected bucket refuses",[](Fixture& f){f.entries[8]=f.entries[3];f.entries[3]=f.led({99});Purge plan(f.selection);refused([&]{plan.hasTypedMember(5,3);});noMutation(f);check(f.disposeCalls==2,"wrong-key cleanup differs");});
    run("raw typed multiple ghosts refuse",[](Fixture& f){f.entries[8]=f.led({5});Purge plan(f.selection);refused([&]{plan.hasTypedMember(5,3);});noMutation(f);check(f.disposeCalls==2,"multiple ghost cleanup differs");});
    run("raw typed present without any bucket refuses",[](Fixture& f){f.entries.clear();Purge plan(f.selection);refused([&]{plan.hasTypedMember(5,3);});noMutation(f);});
    run("raw typed lookup out not enumerated refuses",[](Fixture& f){f.overrideLookupOut=f.led({5});Purge plan(f.selection);refused([&]{plan.hasTypedMember(5,3);});noMutation(f);check(f.disposeCalls==2,"out-of-cache lookup cleanup differs");});
    run("raw typed wrong out class refuses",[](Fixture& f){f.overrideLookupOut=f.node(&f.wrongClass);Purge plan(f.selection);refused([&]{plan.hasTypedMember(5,3);});noMutation(f);check(f.disposeCalls==1,"wrong out class leaked first census");});
    for(int mode=0;mode<3;++mode)run(("raw typed Boolean/out refusal "+std::to_string(mode)).c_str(),[&](Fixture& f){
        if(mode==0)f.falseWithOut=true;if(mode==1)f.trueWithoutOut=true;if(mode==2)f.invalidLookupBool=true;
        Purge plan(f.selection);refused([&]{plan.hasTypedMember(5,3);});noMutation(f);check(f.disposeCalls==1,"Boolean/out failure leaked census");
    });
    for(int mode=0;mode<21;++mode)run(("raw typed closed ABI "+std::to_string(mode)).c_str(),[&](Fixture& f){
        Purge plan(f.selection);
        if(mode==0)f.getTyped.flags=0x10;if(mode==1)f.getTyped.result=f.makeType(&f.wrongClass);
        if(mode==2)f.getTyped.result->byref=true;if(mode==3)f.getTyped.params[0]->byref=true;
        if(mode==4)f.keyClass.value=false;if(mode==5)f.keyClass.size=8;if(mode==6)f.keyClass.alignment=8;
        if(mode==7)f.keyClass.name="OtherKey";if(mode==8)f.lookup.flags=0x10;
        if(mode==9)f.lookup.result=f.makeType(&f.integerClass);if(mode==10)f.lookup.result->byref=true;
        if(mode==11)f.lookup.params[0]->byref=true;if(mode==12)f.lookup.params[0]=f.makeType(&f.unsignedClass);
        if(mode==13)f.lookup.params[1]->byref=false;if(mode==14)f.lookup.params[1]=f.makeType(&f.wrongClass,true);
        if(mode==15)f.lookup.owner=&f.wrongClass;if(mode==16)f.getTyped.owner=&f.wrongClass;
        if(mode==17)++f.getTyped.rva;if(mode==18)f.getTyped.params.clear();
        if(mode==19)f.lookup.params.push_back(f.makeType(&f.unsignedClass));if(mode==20)f.lookup.params[1]=nullptr;
        refused([&]{plan.hasTypedMember(5,3);});noMutation(f);check(!f.lookupCalls&&!f.enumerateCalls,"bad lookup ABI acquired original census/lookup");
    });
    run("raw typed lookup Boolean box refuses",[](Fixture& f){
        Purge plan(f.selection);f.hook=[&](const char* n){if(!strcmp(n,"TryGetValue"))f.boxBool->klass=&f.integerClass;};
        refused([&]{plan.hasTypedMember(5,3);});noMutation(f);check(f.disposeCalls==1,"wrong Boolean box leaked census");
    });
    run("raw typed lookup exception preserves original",[](Fixture& f){f.failLookup=true;Purge plan(f.selection);originalError([&]{plan.hasTypedMember(5,3);},4);noMutation(f);check(f.disposeCalls==1,"lookup exception leaked census");});
    run("raw typed owner changes during lookup",[](Fixture& f){Purge plan(f.selection);f.hook=[&](const char* n){if(!strcmp(n,"TryGetValue"))f.put(f.selection,0x20,f.values);};refused([&]{plan.hasTypedMember(5,3);});noMutation(f);check(f.disposeCalls==1,"lookup owner replacement leaked census");});
    run("raw typed same-count topology replacement",[](Fixture& f){Purge plan(f.selection);f.hook=[&](const char* n){if(!strcmp(n,"TryGetValue"))f.entries[3]=f.led({5});};refused([&]{plan.hasTypedMember(5,3);});noMutation(f);check(f.disposeCalls==2,"topology replacement leaked census");});
    run("raw typed content changes during lookup",[](Fixture& f){Purge plan(f.selection);f.hook=[&](const char* n){if(!strcmp(n,"TryGetValue"))set(f,f.entries[3],{5,99});};refused([&]{plan.hasTypedMember(5,3);});noMutation(f);check(f.disposeCalls==2,"lookup content drift leaked census");});
    run("raw typed absent becomes present in Dispose refuses",[](Fixture& f){set(f,f.all,{});Purge plan(f.selection);f.hook=[&](const char* n){if(!strcmp(n,"Dispose"))set(f,f.all,{5});};refused([&]{plan.hasTypedMember(5,3);});noMutation(f);check(f.disposeCalls==1,"absent snapshot change retried cleanup");});
    for(unsigned at:{1u,2u})run(at==1?"raw typed first Dispose failure":"raw typed second Dispose failure",[&](Fixture& f){
        f.failDisposeOn=at;Purge plan(f.selection);originalError([&]{plan.hasTypedMember(5,3);},3);noMutation(f);check(f.disposeCalls==at,"query Dispose retried");
    });
    run("raw typed primary and cleanup exceptions",[](Fixture& f){f.failMove=f.failDispose=true;Purge plan(f.selection);originalError([&]{plan.hasTypedMember(5,3);},1);noMutation(f);check(f.disposeCalls==1&&f.logs==1,"query exception/cleanup contract differs");});
    for(uint8_t recompute:{uint8_t{0},uint8_t{1}})run(recompute?"explicit count invalidation preserves recompute1":"explicit count invalidation preserves recompute0",[&](Fixture& f){
        f.put(f.selection,0x10,recompute);f.put(f.selection,0x38,uint32_t{99});Purge(f.selection).invalidateCount();
        check(f.dirtyCalls==1&&!f.removeCalls&&!f.enumerateCalls&&read<int32_t>(f.selection,0x54)==-1&&
            read<uint8_t>(f.selection,0x10)==recompute&&scalar(f.selection,0x38)==99,"explicit invalidation changed membership/leader cache");exact(f,f.all,{5});
    });
    run("empty erase result then one explicit dirty",[](Fixture& f){Purge plan(f.selection);check(!plan.erase({}),"empty erase reported change");noMutation(f);plan.invalidateCount();check(f.dirtyCalls==1&&!f.removeCalls&&!f.disposeCalls,"protected-only caller invalidation differs");});
    run("no-match erase result then one explicit dirty",[](Fixture& f){Purge plan(f.selection);check(!plan.erase({99}),"absent erase reported change");noMutation(f);plan.invalidateCount();check(f.dirtyCalls==1&&!f.removeCalls&&f.disposeCalls==1,"absent caller invalidation differs");});
    run("real erase result avoids double dirty",[](Fixture& f){Purge plan(f.selection);if(!plan.erase({5}))plan.invalidateCount();check(f.dirtyCalls==1&&f.removeCalls==2,"real prune dirty count differs");exact(f,f.all,{});});
    run("explicit invalidation original exception",[](Fixture& f){f.failDirty=true;Purge plan(f.selection);originalError([&]{plan.invalidateCount();},8);check(f.dirtyCalls==1&&!f.removeCalls,"invalidation failure mutated membership");});
    run("explicit invalidation effect validated",[](Fixture& f){f.noDirty=true;Purge plan(f.selection);refused([&]{plan.invalidateCount();});check(f.dirtyCalls==1&&!f.removeCalls,"missing dirty side effect accepted");});
    run("explicit invalidation recompute drift refuses",[](Fixture& f){Purge plan(f.selection);f.hook=[&](const char* n){if(!strcmp(n,"MarkCountAsDirty"))f.put(f.selection,0x10,uint8_t{1});};refused([&]{plan.invalidateCount();});check(f.dirtyCalls==1&&!f.removeCalls,"dirty callback recompute drift accepted");});
    std::cout<<"PASS "<<cases<<" actual-header group purge cases; no Unity/IL2CPP/game/DLL loads\n";return 0;
}catch(const OriginalError& error){std::cerr<<"Unexpected original error "<<error.tag<<'\n';}
catch(const std::exception& error){std::cerr<<error.what()<<'\n';}return 1;}
