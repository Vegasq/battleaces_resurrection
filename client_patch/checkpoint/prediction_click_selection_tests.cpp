// Authored host for the ACTUAL raw selection reader. No Unity/IL2CPP/DLL loads.
#include <algorithm>
#include <array>
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

namespace host {
using Obj=void*;
struct Class;
struct Type {Class* klass=nullptr;bool byref=false;};
struct Field {Class* parent=nullptr;Type* type=nullptr;size_t offset=0;uint32_t flags=0;};
struct Method {const char* name=nullptr;uint32_t token=0,flags=0;uintptr_t rva=0;Type* result=nullptr;std::vector<Type*> params;};
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
    Class booleanClass,integerClass,voidClass;
    std::vector<std::unique_ptr<Type>> types;
    std::vector<std::unique_ptr<Node>> nodes;
    Node* selection=nullptr;Node* all=nullptr;Node* dictionary=nullptr;Node* values=nullptr;Node* iterator=nullptr;
    Node* boxBool=nullptr;Node* boxInt=nullptr;
    Method getTyped,lookup,count,getValues,enumerate,move,current,dispose;
    std::map<uint32_t,Node*> entries;std::vector<Node*> iterated;
    std::vector<int32_t> counts;
    size_t cursor=0;unsigned countCalls=0,lookupCalls=0,enumerateCalls=0,moveCalls=0,currentCalls=0,disposeCalls=0,unboxes=0,logs=0;
    bool failMove=false,failCurrent=false,failDispose=false,failLookup=false;
    bool falseWithOut=false,trueWithoutOut=false;
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
        put(result,0x10,entityIds);return result;
    }
    Node* raw(Node* ledNode) {
        Node* result=nullptr;memcpy(&result,ledNode->bytes.data()+0x10,sizeof(result));return result;
    }
    void event(const char* name){if(hook)hook(name);}
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
    auto field=[&](Class& owner,const char* name,size_t offset,Class& value) {
        owner.fields[name]=Field{&owner,makeType(&value),offset,0};
    };
    field(selectionClass,"_allUnits",0x18,ledClass);field(selectionClass,"_subsetsByType",0x20,dictionaryClass);
    field(ledClass,"<Entities>k__BackingField",0x10,idClass);
    field(valuesClass,"_dictionary",0x10,dictionaryClass);field(iteratorClass,"_dictionary",0x10,dictionaryClass);
    auto method=[&](Method& value,Class& owner,const char* name,uint32_t token,Class& result,std::vector<Type*> params,uintptr_t rva=0) {
        value.name=name;value.token=token;value.rva=rva;value.result=makeType(&result);value.params=std::move(params);
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
    selection=node(&selectionClass);all=led({5});dictionary=node(&dictionaryClass);
    values=node(&valuesClass);iterator=node(&iteratorClass);
    boxBool=node(&booleanClass);boxInt=node(&integerClass);
    put(selection,0x18,all);put(selection,0x20,dictionary);
    put(values,0x10,dictionary);put(iterator,0x10,dictionary);entries[3]=led({5});
}
static Obj klass(Obj object){check(object,"authored missing object");return static_cast<Node*>(object)->klass;}
template<class T>static T read(Obj object,size_t offset) {
    check(object,"authored null read");
    for(auto* method:{&active->getTyped,&active->lookup,&active->count,&active->getValues,&active->enumerate,&active->move,&active->current,&active->dispose}) {
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
            &active->booleanClass,&active->integerClass,&active->voidClass}) {
        if(!strcmp(value->space,space) && !strcmp(value->name,name))return value;
    }
    throw std::runtime_error("authored missing class");
}
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
        *static_cast<Obj*>(args[1])=f.trueWithoutOut?nullptr:(exists?found->second:nullptr);
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
        if(f.failDispose)throw OriginalError{3};return nullptr;
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
    HOST_API("il2cpp_object_unbox",unbox);
#undef HOST_API
    throw std::runtime_error(std::string("authored unknown API: ")+name);
}
}
namespace ba_prediction_actors {
using host::Obj;
constexpr size_t maximumActors=8192;
struct Root {Obj value=nullptr;explicit Root(Obj object):value(object){}Obj get()const{return value;}};
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
}
namespace host {
static unsigned cases=0;
static void run(const char* name,const std::function<void(Fixture&)>& body) {
    Fixture f;active=&f;
    try {body(f);++cases;std::cout<<"PASS "<<name<<'\n';}
    catch(...) {std::cerr<<"FAIL "<<name<<'\n';throw;}
}
static bool shape(Fixture& f,bool present=true){return ba_prediction_actors::clickSelectionShape(f.selection,5,3,present);}
static void rejected(Fixture& f,unsigned disposals=0) {
    bool failed=false;try{(void)shape(f);}catch(const std::exception&){failed=true;}
    check(failed,"authored ABI/owner refusal missing");check(f.disposeCalls==disposals,"authored refusal disposal count");
}
static void error(Fixture& f,int tag,unsigned disposals) {
    int actual=0;try{(void)shape(f);}catch(const OriginalError& failure){actual=failure.tag;}
    check(actual==tag,"authored original exception changed");check(f.disposeCalls==disposals,"authored exception disposal count");
}
}
int main() {
    using namespace host;
    try {
        run("exact raw all and type3",[](Fixture& f){check(shape(f),"positive shape");check(f.lookupCalls==1 && f.disposeCalls==1,"positive exact calls");});
        run("empty cached extras",[](Fixture& f){f.entries[1]=f.led({});f.entries[7]=f.led({});check(shape(f),"empty cached extras");check(f.disposeCalls==1,"empty extras disposal");});
        run("absent cache",[](Fixture& f){f.raw(f.all)->ids.clear();f.entries.clear();check(shape(f,false),"absent cache");check(f.disposeCalls==1,"absent disposal");});
        run("absent retained empty values",[](Fixture& f){f.raw(f.all)->ids.clear();f.raw(f.entries[3])->ids.clear();check(shape(f,false),"empty retained value");});
        run("wrong typed key",[](Fixture& f){auto* value=f.entries[3];f.entries.clear();f.entries[4]=value;check(!shape(f),"wrong typed key accepted");});
        run("all extra ID",[](Fixture& f){f.raw(f.all)->ids.push_back(9);check(!shape(f),"all extra accepted");});
        run("typed extra ID",[](Fixture& f){f.raw(f.entries[3])->ids.push_back(9);check(!shape(f),"typed extra accepted");});
        run("all duplicate ID",[](Fixture& f){f.raw(f.all)->ids.push_back(5);check(!shape(f),"all duplicate accepted");});
        run("typed duplicate ID",[](Fixture& f){f.raw(f.entries[3])->ids.push_back(5);check(!shape(f),"typed duplicate accepted");});
        run("ghost other typed ID",[](Fixture& f){f.entries[4]=f.led({9});check(!shape(f),"typed ghost accepted");});
        run("same ID in two typed sets",[](Fixture& f){f.entries[4]=f.led({5});check(!shape(f),"typed repeated ID accepted");});
        run("aliased typed sets",[](Fixture& f){f.entries[4]=f.entries[3];check(!shape(f),"aliased typed values accepted");});
        run("absent all but typed residue",[](Fixture& f){f.raw(f.all)->ids.clear();check(!shape(f,false),"absent residue accepted");});
        run("present all but typed empty",[](Fixture& f){f.raw(f.entries[3])->ids.clear();check(!shape(f),"typed empty accepted");});
        run("wrong selection class",[](Fixture& f){f.selection->klass=&f.wrongClass;rejected(f);});
        run("wrong all class",[](Fixture& f){f.all->klass=&f.wrongClass;rejected(f);});
        run("wrong dictionary actual class",[](Fixture& f){f.dictionary->klass=&f.wrongClass;rejected(f);});
        run("wrong dictionary declared class",[](Fixture& f){f.selectionClass.fields["_subsetsByType"].type=f.makeType(&f.wrongClass);rejected(f);});
        run("wrong field parent",[](Fixture& f){f.selectionClass.fields["_allUnits"].parent=&f.wrongClass;rejected(f);});
        run("static storage field",[](Fixture& f){f.selectionClass.fields["_subsetsByType"].flags=0x10;rejected(f);});
        run("wrong Led declaring class",[](Fixture& f){f.ledClass.declaring=&f.wrongClass;rejected(f);});
        run("wrong typed view declaring class",[](Fixture& f){f.viewClass.declaring=&f.wrongClass;rejected(f);});
        run("wrong GetUnitsOfType original RVA",[](Fixture& f){++f.getTyped.rva;rejected(f);});
        run("wrong GetUnitsOfType key",[](Fixture& f){f.getTyped.params[0]=f.makeType(&f.wrongClass);rejected(f);});
        run("wrong key class",[](Fixture& f){f.lookup.params[0]=f.makeType(&f.wrongClass);rejected(f);check(!f.lookupCalls,"bad key invoked");});
        run("byref key",[](Fixture& f){f.lookup.params[0]->byref=true;rejected(f);});
        run("key not value type",[](Fixture& f){f.keyClass.value=false;rejected(f);});
        run("wrong key size",[](Fixture& f){f.keyClass.size=8;rejected(f);});
        run("wrong key alignment",[](Fixture& f){f.keyClass.alignment=8;rejected(f);});
        run("lookup out not byref",[](Fixture& f){f.lookup.params[1]->byref=false;rejected(f);check(!f.lookupCalls,"bad out invoked");});
        run("lookup out wrong class",[](Fixture& f){f.lookup.params[1]=f.makeType(&f.wrongClass,true);rejected(f);});
        run("lookup wrong Boolean",[](Fixture& f){f.lookup.result=f.makeType(&f.integerClass);rejected(f);});
        run("lookup byref Boolean",[](Fixture& f){f.lookup.result->byref=true;rejected(f);});
        run("lookup wrong Boolean box",[](Fixture& f){f.boxBool->klass=&f.wrongClass;rejected(f);});
        run("lookup static",[](Fixture& f){f.lookup.flags=0x10;rejected(f);});
        run("lookup inconsistent false out",[](Fixture& f){f.falseWithOut=true;rejected(f);});
        run("lookup inconsistent true null",[](Fixture& f){f.trueWithoutOut=true;rejected(f);});
        run("lookup original exception",[](Fixture& f){f.failLookup=true;error(f,4,0);});
        run("negative count",[](Fixture& f){f.counts={-1};rejected(f);});
        run("count bound",[](Fixture& f){f.counts={8193};rejected(f);});
        run("count wrong return",[](Fixture& f){f.count.result=f.makeType(&f.booleanClass);rejected(f);});
        run("count wrong box",[](Fixture& f){f.boxInt->klass=&f.wrongClass;rejected(f);});
        run("enumeration exceeds count",[](Fixture& f){f.counts={0};rejected(f,1);});
        run("enumeration fewer than count",[](Fixture& f){f.counts={2};rejected(f,1);});
        run("count changed",[](Fixture& f){f.counts={1,2};rejected(f,1);});
        run("Values wrong owner",[](Fixture& f){f.put(f.values,0x10,f.all);rejected(f);});
        run("Values wrong class",[](Fixture& f){f.values->klass=&f.wrongClass;rejected(f);});
        run("iterator wrong owner",[](Fixture& f){f.put(f.iterator,0x10,f.all);rejected(f,1);});
        run("iterator wrong dictionary field type",[](Fixture& f){f.iteratorClass.fields["_dictionary"].type=f.makeType(&f.wrongClass);rejected(f,1);});
        run("iterator not value type",[](Fixture& f){f.iteratorClass.value=false;rejected(f);check(!f.enumerateCalls,"invalid iterator acquired");});
        run("iterator bad MoveNext signature",[](Fixture& f){f.move.result=f.makeType(&f.integerClass);rejected(f);check(!f.enumerateCalls,"bad MoveNext acquired iterator");});
        run("iterator bad Current signature",[](Fixture& f){f.current.result=f.makeType(&f.wrongClass);rejected(f);check(!f.enumerateCalls,"bad Current acquired iterator");});
        run("iterator bad Dispose signature",[](Fixture& f){f.dispose.result=f.makeType(&f.integerClass);rejected(f);check(!f.enumerateCalls,"bad Dispose acquired iterator");});
        run("iterator missing Dispose",[](Fixture& f){f.iteratorClass.methods.pop_back();rejected(f);check(!f.enumerateCalls,"missing Dispose acquired iterator");});
        run("iterator duplicate Dispose",[](Fixture& f){f.iteratorClass.methods.push_back(&f.dispose);rejected(f);check(!f.enumerateCalls,"duplicate Dispose acquired iterator");});
        run("iterator creation exception",[](Fixture& f){f.failIteratorCreation=true;error(f,5,0);});
        run("MoveNext exception disposed",[](Fixture& f){f.failMove=true;error(f,1,1);});
        run("Current exception disposed",[](Fixture& f){f.failCurrent=true;error(f,2,1);});
        run("raw ID exception disposed",[](Fixture& f){f.failIds=f.raw(f.entries[3]);error(f,6,1);});
        run("typed wrong Led class disposed",[](Fixture& f){f.entries[4]=f.led({});f.entries[4]->klass=&f.wrongClass;rejected(f,1);});
        run("MoveNext wrong Boolean box disposed",[](Fixture& f){f.hook=[&](const char* name){if(!strcmp(name,"MoveNext"))f.boxBool->klass=&f.wrongClass;};rejected(f,1);});
        run("Dispose exception not retried",[](Fixture& f){f.failDispose=true;error(f,3,1);});
        run("cleanup exception preserves original",[](Fixture& f){f.failMove=true;f.failDispose=true;error(f,1,1);check(f.logs==1,"cleanup failure log missing");});
        run("typed budget bound disposed",[](Fixture& f){f.raw(f.entries[3])->ids.assign(8192,5);f.entries[4]=f.led({9});rejected(f,1);});
        run("all budget bound",[](Fixture& f){f.raw(f.all)->ids.assign(8193,5);rejected(f);});
        run("storage owner changes disposed",[](Fixture& f){f.hook=[&](const char* name){if(!strcmp(name,"MoveNext"))f.put(f.selection,0x18,f.entries[3]);};rejected(f,1);});
        run("all raw IDs changed during read",[](Fixture& f){f.hook=[&](const char* name){if(!strcmp(name,"MoveNext"))f.raw(f.all)->ids={9};};check(!shape(f),"changed raw all accepted");check(f.disposeCalls==1,"changed all disposal");});
        std::cout<<"PASS "<<cases<<" actual-header raw selection cases; no game/DLL loaded\n";return 0;
    } catch(const OriginalError& value){std::cerr<<"Unexpected original error "<<value.tag<<'\n';}
    catch(const std::exception& error){std::cerr<<error.what()<<'\n';}
    return 1;
}
