#pragma once
#include "native_storage.hpp"
namespace ba_native_storage {
using ba_native_settings::require;
struct Destination {
    Directory directory;
    ba_local::Root text;
    explicit Destination(Kind kind):directory(ba_native_settings::prepareSession(),kind),
        text(ba::api<ba::Obj(*)(const wchar_t*,int32_t)>("il2cpp_string_new_utf16")(
            directory.path().data(),static_cast<int32_t>(directory.path().size()))) {
        require(text.get()!=nullptr,"native storage managed path root unavailable");
    }
};
// Deliberately retain directories and managed roots through native teardown.
static auto& replay=*new std::unique_ptr<Destination>();
static auto& backup=*new std::unique_ptr<Destination>();
struct ReplayFault {
    ba_native_settings::Handle blocker;
    std::unique_ptr<ba_local::Root> text;
    ReplayFault() {
        const auto& session=ba_native_settings::prepareSession();const auto& key=session.profile();
        const std::string prefix="nativestest_storage_";
        require(key.size()==prefix.size()+12 && key.compare(0,prefix.size(),prefix)==0 &&
            key.find_first_not_of("0123456789abcdef",prefix.size())==std::string::npos,"storage fault requires an owned diagnostic profile");
        const auto path=session.path().substr(0,session.path().find_last_of(L'\\')+1)+L"native-replay-directory-blocker";
        blocker.value=CreateFileW(path.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL|FILE_FLAG_OPEN_REPARSE_POINT,nullptr);ba_native_settings::ordinary(blocker.value);
        constexpr char expected[]="authored native replay directory fault\n";char data[sizeof(expected)];DWORD count=0;LARGE_INTEGER size{};
        require(GetFileSizeEx(blocker.value,&size) && size.QuadPart==sizeof(expected)-1 &&
            ReadFile(blocker.value,data,sizeof(data),&count,nullptr) && count==sizeof(expected)-1 &&
            memcmp(data,expected,sizeof(expected)-1)==0,"storage fault blocker must be the exact authored fixture");
        text=std::make_unique<ba_local::Root>(ba::api<ba::Obj(*)(const wchar_t*,int32_t)>("il2cpp_string_new_utf16")(
            path.data(),static_cast<int32_t>(path.size())));require(text->get()!=nullptr,"storage fault managed path root unavailable");
        ba::log("NATIVE STORAGE explicit directory fault armed: ownedProfile=1 fixturePinned=1 sharedPathUnused=1 BA_RESURRECTION_NATIVE_STORAGE_FAULT_V1");
    }
};
static auto& fault=*new std::unique_ptr<ReplayFault>();
static Destination& destination(Kind kind) {
    static auto& mutex=*new std::mutex();std::lock_guard<std::mutex> lock(mutex);
    auto& chosen=kind==Kind::Replays?replay:backup;
    if(!chosen) {
        chosen=std::make_unique<Destination>(kind);
        ba::log("NATIVE STORAGE path selected: kind=%s profile=%s path=%s isolated=1 rooted=1 BA_RESURRECTION_NATIVE_STORAGE_V1",
            kind==Kind::Replays?"replay":"backup",ba_native_settings::session->profile().c_str(),
            ba_native_settings::utf8(chosen->directory.path()).c_str());
    }
    return *chosen;
}
[[noreturn]] static void fatal(const char* reason) {
    ba::log("Native storage initialization refused: %s; sharedFallback=0",reason);
    TerminateProcess(GetCurrentProcess(),ERROR_BAD_CONFIGURATION);ExitProcess(ERROR_BAD_CONFIGURATION);
}
static void verify() {
    static bool verified=false;if(verified)return;
    require(backup!=nullptr,"early native backup isolation was not installed");
    auto type=ba::find_class("Uncapped","UncappedSteamRemoteStorageSync");
    auto field=ba::api<ba::Obj(*)(ba::Obj,const char*)>("il2cpp_class_get_field_from_name")(type,"BackupRemoteSyncRoot");
    require(field!=nullptr,"native backup static root field missing");ba::Obj actual=nullptr;
    ba::api<void(*)(ba::Obj,void*)>("il2cpp_field_static_get_value")(field,&actual);
    require(ba_native_settings::wide(actual)==backup->directory.path(),"native backup static root differs from isolated destination");
    verified=true;ba::log("NATIVE STORAGE backup verified: staticField=1 getterCalled=0 localOnlyPolicy=1 isolated=1");
}
}
extern "C" __declspec(dllexport) void* OfflineBackupStoragePath(void*,void* name,void*) {
    try {
        ba::init();ba_native_storage::require(ba_native_settings::wide(name)==L"StorageSyncBackup","native backup callsite ABI mismatch");
        // Caller immediately stores this strongly rooted string in its cctor.
        return ba_native_storage::destination(ba_native_storage::Kind::Backup).text.get();
    }catch(const std::exception& error){ba_native_storage::fatal(error.what());}
    catch(...){ba_native_storage::fatal("unknown backup path error");}
}
extern "C" __declspec(dllexport) void* OfflineReplayStoragePath(void*,void*,void* name,void*) {
    // Outer autosave boundary prepares the destination before native managed
    // invocation. No path allocation, original getter fallback or UI here.
    try {
        ba_native_storage::require(ba_native_storage::replay!=nullptr &&
            ba_native_settings::wide(name)==L"AutoSaveReplays","native replay callsite ABI mismatch");
        return ba_native_storage::fault?ba_native_storage::fault->text->get():ba_native_storage::replay->text.get();
    }catch(const std::exception& error){ba_native_storage::fatal(error.what());}
    catch(...){ba_native_storage::fatal("unknown replay path error");}
}
extern "C" __declspec(dllexport) void OfflineCleanupAutoSaveReplay(void* receiver,void*) {
    try {
        ba::init();ba_local::Root owner(receiver);ba_native_storage::require(owner.get()!=nullptr,"native autosave owner unavailable");
        ba_native_storage::destination(ba_native_storage::Kind::Replays);
        // Explicit owned diagnostics only: let ORIGINAL Directory.CreateDirectory
        // raise against an authored file, outside its inner SaveReplayFile catch.
        if(ba::flag(L"-native-storage-directory-failure-smoke") && !ba_native_storage::fault)
            ba_native_storage::fault=std::make_unique<ba_native_storage::ReplayFault>();
        auto method=ba::api<void*(*)(void*,const char*,int)>("il2cpp_class_get_method_from_name")(
            ba::find_class("Uncapped","GameServerIntegration"),"AutoSaveReplay",0);
        ba_native_storage::require(method && ba::read<void*>(method,0)==ba::native<void*>(0x3e4fe70),"native autosave method identity mismatch");
        ba::Obj exception=nullptr;
        ba::api<ba::Obj(*)(ba::Obj,ba::Obj,void**,ba::Obj*)>("il2cpp_runtime_invoke")(method,owner.get(),nullptr,&exception);
        // Void return is not proof of a written replay: original code may skip
        // or return false internally. Do not retry after its autoSave flag clears.
        ba::log("NATIVE STORAGE autosave boundary: invoked=1 managedException=%d cleanupContinues=1 saved=unclaimed",exception!=nullptr);
    }catch(const std::exception& error) {
        ba::log("NATIVE STORAGE autosave refused: %s; sharedFallback=0 cleanupContinues=1 saved=0",error.what());
    }catch(...) {ba::log("NATIVE STORAGE autosave refused: unknown error; sharedFallback=0 cleanupContinues=1 saved=0");}
}
