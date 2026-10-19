#pragma once
#include "native_backup_store.hpp"
#include "native_settings_atomic.hpp"
namespace ba_native_backup {
using ba::Obj;using ba_local::Root;
static constexpr wchar_t fileId[]=L"A3079428-5DC5-4617-AF2D-0C8656DA760B";
struct State {
    Root owner,accessor;
    Input input;
    State(Obj file):owner(file),accessor(ba::read<Obj>(file,0x10)),
        input(ba_native_storage::destination(ba_native_storage::Kind::Backup).directory.path()+L"\\"+fileId) {
        require(accessor.get() && ba::klass(accessor.get())==ba::find_class("Uncapped","TailoredUXTracking") &&
            ba_native_settings::wide(ba::read<Obj>(owner.get(),0x28))==fileId,"native backup owner identity mismatch");
    }
};
static auto& state=*new std::unique_ptr<State>();
static std::atomic<unsigned long long> readFailures{0},saveFailures{0},saveAttempts{0};
static ba_native_settings::SaveOutcome lastSaveSucceeded;
static Obj method(Obj klass,const char* name,int count,uintptr_t rva) {
    auto m=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(klass,name,count);
    require(m && ba::read<Obj>(m,0)==ba::native<Obj>(rva),"native backup method identity mismatch");return m;
}
static Obj invoke(Obj m,Obj owner,void** args=nullptr) {
    Obj exception=nullptr;
    auto result=ba::api<Obj(*)(Obj,Obj,void**,Obj*)>("il2cpp_runtime_invoke")(m,owner,args,&exception);
    require(!exception,"native backup original managed operation failed");return result;
}
static void defaults() {
    // Reset is incomplete (quest lists survive). Use the ORIGINAL complete data
    // constructor/builder/setter, retaining the live accessor/account/listeners.
    auto klass=ba::find_class("Uncapped","TailoredUXTracking");
    ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(klass);
    Root fresh(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(klass));require(fresh.get()!=nullptr,"native backup defaults allocation failed");
    invoke(method(klass,".ctor",0,0x3e7d520),fresh.get());
    const char* prefix="Uncapped.UncappedSteamRemoteStorageSync.ISteamRemoteFileDataAccessor.";
    const auto build=std::string(prefix)+"BuildSerializedData",set=std::string(prefix)+"SetFromSerializedData";
    Root data(invoke(method(klass,build.c_str(),0,0x3e7b5a0),fresh.get()));
    require(data.get()!=nullptr,"native backup defaults builder failed");
    const auto account=ba::read<Obj>(state->accessor.get(),0x10),listeners=ba::read<Obj>(state->accessor.get(),0x70);
    void* args[]={data.get()};invoke(method(klass,set.c_str(),1,0x3e7af10),state->accessor.get(),args);
    require(ba::read<Obj>(state->accessor.get(),0x10)==account && ba::read<Obj>(state->accessor.get(),0x70)==listeners,
        "native backup defaults changed live dependencies");
    Root applied(invoke(method(klass,build.c_str(),0,0x3e7b5a0),state->accessor.get()));
    void* freshArgs[]={data.get()};void* appliedArgs[]={applied.get()};
    Root expected(ba::invoke(ba::find_class("UnityEngine","JsonUtility"),nullptr,"ToJson",1,freshArgs));
    Root actual(ba::invoke(ba::find_class("UnityEngine","JsonUtility"),nullptr,"ToJson",1,appliedArgs));
    require(expected.get() && actual.get() && ba_native_settings::wide(expected.get())==ba_native_settings::wide(actual.get()),
        "native backup complete defaults readback differs");
    ba::log("NATIVE BACKUP temporary defaults: originalCtorBuilderSetter=1 liveAccessorRetained=1 inputPreserved=1 completeNativeReadbackEqual=1");
}
static void writeProbe() {
    static bool done=false;if(done || !ba::flag(L"-native-backup-write-smoke"))return;
    require(state && ba_native_settings::session && ba_native_settings::session->profile().rfind("nativestest_",0)==0,
        "native backup writer probe requires an owned profile");
    bool dirtyOnly=false;void* args[]={&dirtyOnly};const auto before=saveAttempts.load();
    Root result(invoke(method(ba::klass(state->owner.get()),"Write",1,0x26313c0),state->owner.get(),args));
    require(result.get()!=nullptr && saveAttempts.load()==before+1,"native backup writer probe did not exercise one text write");
    const bool okay=*ba::api<bool*(*)(Obj)>("il2cpp_object_unbox")(result.get());
    require(okay==lastSaveSucceeded.load(),"original native backup Write Boolean differs from publication result");
    done=true;ba::log("NATIVE BACKUP writer probe: originalWriteBoolean=%d managedExceptionOut=0 agreesWithPublication=1 automated=1",okay);
}
// Do not declare noexcept: the original Write catches Il2CppExceptionWrapper.
// Raise only outside authored catch blocks; std::exception must not cross thunk.
[[noreturn]] static void raise(Obj original) {
    Obj exception=original;
    try {
        if(!exception)exception=ba::api<Obj(*)(Obj,const char*,const char*,const char*)>("il2cpp_exception_from_name_msg")(
            ba::api<Obj(*)()>("il2cpp_get_corlib")(),"System.IO","IOException","Local menu data could not be saved; existing data was preserved.");
        require(exception!=nullptr,"native backup managed exception allocation failed");
    }catch(const std::exception& error){ba_native_storage::fatal(error.what());}
    Root rooted(exception);ba::api<void(*)(Obj)>("il2cpp_raise_exception")(rooted.get());
    ba_native_storage::fatal("native backup managed raise returned");
}
}
extern "C" __declspec(dllexport) bool OfflineBackupInitialRead(void* receiver,bool onlyIfNewer,void* originalMethod) {
    using namespace ba_native_backup;
    try {
        ba::init();require(!state && !onlyIfNewer && originalMethod &&
            ba::read<Obj>(originalMethod,0)==ba::native<Obj>(0x2630f00),"native backup initial read ABI mismatch");
        state=std::make_unique<State>(receiver);bool readable=false;
        try {readable=state->input.prepare();}
        catch(const std::exception& error){ba::log("NATIVE BACKUP input preflight refused: %s",error.what());}
        bool accepted=false;
        if(readable) {
            void* args[]={&onlyIfNewer};Root result(invoke(originalMethod,state->owner.get(),args));
            require(result.get()!=nullptr,"native backup read Boolean unavailable");
            accepted=*ba::api<bool*(*)(Obj)>("il2cpp_object_unbox")(result.get());state->input.finish(accepted);
        }
        if(!state->input.writable()) {
            state->input.refuse();defaults();++readFailures;
            ba::log("NATIVE BACKUP input refused: nativeAccepted=%d temporaryDefaults=1 writesRefused=1 inputPreserved=1",accepted);
        }
        ba::log("NATIVE BACKUP initial read: nativeAccepted=%d writable=%d originalDeserializer=%d BA_RESURRECTION_NATIVE_BACKUP_GUARD_V1",accepted,state->input.writable(),readable);
        return accepted;
    }catch(const std::exception& error){ba_native_storage::fatal(error.what());}
    catch(...){ba_native_storage::fatal("unknown native backup read boundary failure");}
}
extern "C" __declspec(dllexport) void OfflineBackupWriteText(void* path,void* contents,void*) {
    using namespace ba_native_backup;
    const auto sequence=++saveAttempts;std::unique_ptr<Root> originalException;
    bool published=false;
    {
        static auto& gate=*new ba_native_settings::SaveGate();ba_native_settings::SaveGate::Lease lease(gate);
        try {
            require(lease.acquired(),"native backup concurrent/reentrant save refused");
            require(sequence && sequence<=(~0ull>>1) && !lastSaveSucceeded.newerThan(sequence),"native backup save superseded");
            Root pathRoot(path),textRoot(contents);
            require(state && state->input.writable(),"native backup save before input admission or after rejection");
            require(ba_native_settings::wide(pathRoot.get())==state->input.path(),"native backup write destination mismatch");
            require(textRoot.get()!=nullptr,"native backup serialized text unavailable");
            ba_native_settings::WriteTransaction transaction(state->input.path());
            Root temporary(ba::api<Obj(*)(const wchar_t*,int32_t)>("il2cpp_string_new_utf16")(
                transaction.path().data(),static_cast<int32_t>(transaction.path().size())));
            require(temporary.get()!=nullptr,"native backup temporary managed path allocation failed");
            void* args[]={temporary.get(),textRoot.get()};Obj exception=nullptr;
            auto m=method(ba::find_class("System.IO","File"),"WriteAllText",2,0x35482a0);
            ba::api<Obj(*)(Obj,Obj,void**,Obj*)>("il2cpp_runtime_invoke")(m,nullptr,args,&exception);
            if(exception)originalException=std::make_unique<Root>(exception);
            require(!exception,"native backup original text writer failed");
            require(!lastSaveSucceeded.newerThan(sequence),"native backup save superseded during serialization");
            transaction.commit();published=true;
            ba::log("NATIVE BACKUP save published: originalJsonAndWriter=1 flushed=1 inPlaceFallback=0");
        }catch(const std::exception& error){ba::log("NATIVE BACKUP save refused: %s; published=0 inPlaceFallback=0 originalCatchExpected=1",error.what());}
        lastSaveSucceeded.record(sequence,published);if(!published)++saveFailures;
    }
    if(!published)raise(originalException?originalException->get():nullptr);
}
