#pragma once
// Load installed data through the game's original asynchronous table registry.
namespace ba_tables {
using ba::Obj;using ba_local::Root;
static void require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
static Obj reflectedType(const char* name,const char* ns="Uncapped") {
    return ba::api<Obj(*)(Obj)>("il2cpp_type_get_object")(
        ba::api<Obj(*)(Obj)>("il2cpp_class_get_type")(ba::find_class(ns,name)));
}
static void arraySet(Obj array,size_t index,Obj value) {
    ba::api<void(*)(Obj,void**,Obj)>("il2cpp_gc_wbarrier_set_field")(
        array,reinterpret_cast<void**>(static_cast<char*>(array)+0x20+index*sizeof(Obj)),value);
}
static bool boolean(Obj value) {
    require(value!=nullptr,"native table boolean missing");
    return *ba::api<bool*(*)(Obj)>("il2cpp_object_unbox")(value);
}
// Retain both the reference and operation for application lifetime. The game's
// generic System.Object instantiation already exists in the supported AOT image.
struct Asset {
    const char* type;
    const char* guid;
    std::unique_ptr<Root> reference,operation,value;
    ULONGLONG began=0;
    Asset(const char* name,const char* address):type(name),guid(address){}
    Obj get() const {return value?value->get():nullptr;}
    bool ready() {
        if(value)return true;
        if(!reference) {
            Obj cls=ba::find_class("UnityEngine.AddressableAssets","AssetReference");
            ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(cls);
            reference=std::make_unique<Root>(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(cls));
            Root address(ba::str(guid));void* ctorArgs[]={address.get()};
            ba::invoke(cls,reference->get(),".ctor",1,ctorArgs);
            Obj method=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(cls,"LoadAssetAsync",0);
            require(method!=nullptr,"native asset loader missing");
            Root reflected(ba::api<Obj(*)(Obj,Obj)>("il2cpp_method_get_object")(method,cls));
            Root types(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(ba::find_class("System","Type"),1));
            Root objectType(reflectedType("Object","System"));arraySet(types.get(),0,objectType.get());
            void* genericArgs[]={types.get()};Root closed(ba::call(reflected.get(),"MakeGenericMethod",1,genericArgs));
            Root parameters(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(ba::find_class("System","Object"),0));
            void* args[]={reference->get(),parameters.get()};
            operation=std::make_unique<Root>(ba::call(closed.get(),"Invoke",2,args));
            require(operation->get()!=nullptr,"native asset operation missing");began=GetTickCount64();
            ba::log("Native asset load requested: %s",type);
        }
        Root done(ba::call(reference->get(),"get_IsDone"));
        require(GetTickCount64()-began<30000,"native asset load deadline");
        if(!boolean(done.get()))return false;
        Root loaded(ba::call(reference->get(),"get_Asset"));
        require(loaded.get() && ba::klass(loaded.get())==ba::find_class("Uncapped",type),"native asset load failed or type mismatch");
        value=std::make_unique<Root>(loaded.get());
        ba::log("Native asset load completed: %s",type);return true;
    }
};
struct Table {
    const char* element;
    const char* type;
    const char* guid;
    std::unique_ptr<Root> reference,task;
    ULONGLONG began=0;
    bool loaded=false;
    Table(const char* item,const char* name,const char* address):element(item),type(name),guid(address){}
    Obj get() const {
        Root reflected(reflectedType(type));void* args[]={reflected.get()};
        return ba::invoke(ba::find_class("Uncapped","StaticTables"),nullptr,"GetTable",1,args);
    }
    bool ready() {
        if(loaded)return true;
        if(!task && get()){loaded=true;return true;}
        if(!task) {
            Obj cls=ba::find_class("Uncapped","StaticTables");
            Obj method=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(cls,"LoadTableAsync",1);
            require(method!=nullptr,"native async table loader missing");
            Root reflected(ba::api<Obj(*)(Obj,Obj)>("il2cpp_method_get_object")(method,cls));
            Root types(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(ba::find_class("System","Type"),2));
            Root item(reflectedType(element)),tableType(reflectedType(type));
            arraySet(types.get(),0,item.get());arraySet(types.get(),1,tableType.get());
            void* genericArgs[]={types.get()};Root closed(ba::call(reflected.get(),"MakeGenericMethod",1,genericArgs));
            Obj referenceClass=ba::find_class("UnityEngine.AddressableAssets","AssetReference");
            ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(referenceClass);
            reference=std::make_unique<Root>(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(referenceClass));
            Root address(ba::str(guid));void* ctorArgs[]={address.get()};
            ba::invoke(referenceClass,reference->get(),".ctor",1,ctorArgs);
            Root parameters(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(ba::find_class("System","Object"),1));
            arraySet(parameters.get(),0,reference->get());void* args[]={nullptr,parameters.get()};
            task=std::make_unique<Root>(ba::call(closed.get(),"Invoke",2,args));
            require(task->get()!=nullptr,"native table loader returned no task");began=GetTickCount64();
            ba::log("Native table load requested: %s",type);
        }
        Root done(ba::call(task->get(),"get_IsCompleted"));
        require(GetTickCount64()-began<30000,"native table load deadline");
        if(!boolean(done.get()))return false;
        Root faulted(ba::call(task->get(),"get_IsFaulted")),cancelled(ba::call(task->get(),"get_IsCanceled"));
        require(!boolean(faulted.get()) && !boolean(cancelled.get()) && get(),"native table load did not succeed");
        Root elementType(reflectedType(element));void* args[]={elementType.get()};
        Root mapped(ba::invoke(ba::find_class("Uncapped","StaticTables"),nullptr,"GetElementTableType",1,args));
        require(mapped.get() && ba_catalog::utf8(ba::call(mapped.get(),"get_Name"))==type,"native table mapping mismatch");
        loaded=true;ba::log("Native table load registered: %s",type);return true;
    }
    Obj at(uint32_t id) const {
        Root table(get());require(table.get()!=nullptr,"native table is not loaded");
        Obj method=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(
            ba::find_class("Uncapped","IIntTable"),"GetElementByID",1);
        method=ba::api<Obj(*)(Obj,Obj)>("il2cpp_object_get_virtual_method")(table.get(),method);
        void* args[]={&id};return ba_local::invokeMethod(method,table.get(),args);
    }
};
}
