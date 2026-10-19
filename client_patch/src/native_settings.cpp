#pragma once
#include <memory>
#include <atomic>
#include "native_settings.hpp"
namespace ba_native_settings {
static void observe(ba::Obj);
static void inspectDeckTable(ba::Obj);
static bool saveIsolated(ba::Obj,ba::Obj,ba::Obj,void*,unsigned long long);
// Held through engine teardown. OS process exit releases the handles; CRT
// destruction must not unlock a profile while native shutdown can still save.
static auto& session=*new std::unique_ptr<Session>();
static std::atomic<unsigned long long> loads{0},saves{0},saveFailures{0};
static std::atomic<unsigned long long> validationSaveRefusals{0};
static SaveOutcome lastSaveSucceeded;
static bool matches(ba::Obj path) noexcept {
    // Exact known System.String ABI; no getter, managed allocation or cctor.
    // Other config writers use this same base. Leave their results unchanged.
    return session && path && ba::read<int32_t>(path,0x10)==static_cast<int32_t>(session->path().size()) &&
        memcmp(static_cast<const char*>(path)+0x14,session->path().data(),session->path().size()*sizeof(wchar_t))==0;
}
static std::wstring wide(ba::Obj text) {
    require(text!=nullptr,"native settings hook string missing");
    const int count=ba::api<int(*)(ba::Obj)>("il2cpp_string_length")(text);
    require(count>=0 && count<32768,"native settings hook string length");
    return std::wstring(ba::api<const wchar_t*(*)(ba::Obj)>("il2cpp_string_chars")(text),count);
}
static std::string utf8(const std::wstring& text) {
    const int count=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,text.data(),static_cast<int>(text.size()),nullptr,0,nullptr,nullptr);
    require(count>0,"native settings path Unicode invalid");std::string result(count,'\0');
    require(WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,text.data(),static_cast<int>(text.size()),result.data(),count,nullptr,nullptr)==count,
        "native settings path Unicode conversion failed");return result;
}
static void verify() {
    static bool verified=false;if(verified)return;
    require(session!=nullptr,"early native settings isolation was not installed");
    // Read directly after startup. The getter can reset settings/create files.
    auto type=ba::find_class("Uncapped","RGameLocalUserConfigTomlLoader");
    auto field=ba::api<ba::Obj(*)(ba::Obj,const char*)>("il2cpp_class_get_field_from_name")(type,"ConfigFileLocation");
    require(field!=nullptr,"native settings static field missing");ba::Obj actual=nullptr;
    ba::api<void(*)(ba::Obj,void*)>("il2cpp_field_static_get_value")(field,&actual);
    require(wide(actual)==session->path(),"native settings initialized path differs from isolated destination");
    verified=true;ba::log("NATIVE SETTINGS path verified: profile=%s staticField=1 getterCalled=0 isolated=1",session->profile().c_str());
}
}
extern "C" __declspec(dllexport) void* OfflineLocalUserLoadTable(void* loader,void* path,void* method) {
    ba::init();const bool isolated=ba_native_settings::matches(path);
    // No managed allocation after this return: RAX is not yet rooted by caller.
    auto table=ba::native<void*(*)(void*,void*,void*)>(0x3797f80)(loader,path,method);
    if(isolated) {
        const auto sequence=++ba_native_settings::loads;
        ba::log("NATIVE SETTINGS load result: profile=%s sequence=%llu parsed=%d BA_RESURRECTION_NATIVE_SETTINGS_ERRORS_V1",
            ba_native_settings::session->profile().c_str(),sequence,table!=nullptr);
        if(!table) {
            // Original outer Load falsely reports success here,then may save
            // defaults over the input. Preserve it by stopping before fallback.
            ba::log("NATIVE SETTINGS load refused: parsedTable=0 inputPreserved=1 sharedPathUnused=1");
            TerminateProcess(GetCurrentProcess(),ERROR_BAD_CONFIGURATION);ExitProcess(ERROR_BAD_CONFIGURATION);
        }
        try {ba_native_settings::inspectDeckTable(table);}
        catch(const std::exception& error) {
            ba::log("Native persisted deck load refused: %s; inputPreserved=1 selectorUnused=1",error.what());
            TerminateProcess(GetCurrentProcess(),ERROR_BAD_CONFIGURATION);ExitProcess(ERROR_BAD_CONFIGURATION);
        }
    }
    return table;
}
extern "C" __declspec(dllexport) bool OfflineLocalUserSaveTable(void* loader,void* path,void* table,void* method) {
    ba::init();const bool isolated=ba_native_settings::matches(path);
    const auto sequence=isolated?++ba_native_settings::saves:0;
    // Unrelated/protected startup saves keep their original target/result.
    // After input acceptance,serialize unchanged to a sibling and report success
    // only after publication. No UI or retry inside writer/teardown callbacks.
    const bool protectedInput=isolated && ba_native_settings::session->inputProtected();
    const bool okay=isolated && !protectedInput ? ba_native_settings::saveIsolated(loader,path,table,method,sequence) :
        ba::native<bool(*)(void*,void*,void*,void*)>(0x3796060)(loader,path,table,method);
    if(isolated) {
        if(protectedInput) {if(!okay)++ba_native_settings::validationSaveRefusals;}
        else {
            if(!okay)++ba_native_settings::saveFailures;
        }
        ba::log("NATIVE SETTINGS save result: profile=%s sequence=%llu succeeded=%d failures=%llu validationProtected=%d validationRefusals=%llu BA_RESURRECTION_NATIVE_SETTINGS_ERRORS_V1",
            ba_native_settings::session->profile().c_str(),sequence,okay,ba_native_settings::saveFailures.load(),
            protectedInput,ba_native_settings::validationSaveRefusals.load());
    }
    return okay;
}
extern "C" __declspec(dllexport) void* OfflineLocalUserConfigPath(void*,void*,void* filename,void*) {
    try {
        ba::init();ba_native_settings::require(!ba_native_settings::session,"native settings cctor repeated unexpectedly");
        ba_native_settings::require(ba_native_settings::wide(filename)==L"gameconfig-localuser.toml","native settings callsite ABI mismatch");
        wchar_t module[32768];const DWORD length=GetModuleFileNameW(ba::module,module,32768);
        ba_native_settings::require(length && length<32768,"native settings installation path unavailable");
        auto slash=wcsrchr(module,L'\\');ba_native_settings::require(slash!=nullptr,"native settings installation path invalid");*(slash+1)=0;
        ba_native_settings::session=std::make_unique<ba_native_settings::Session>(module,ba_native_settings::profile(ba::arguments()));
        const auto& selected=*ba_native_settings::session;
        ba::log("NATIVE SETTINGS path selected: {\"profile\":%s,\"path\":%s,\"beforeNativeLoad\":true,\"isolated\":true,\"writerLock\":true} BA_RESURRECTION_NATIVE_SETTINGS_V1",
            ba_catalog::quote(selected.profile()).c_str(),ba_catalog::quote(ba_native_settings::utf8(selected.path())).c_str());
        // Last managed operation: original code immediately stores/root-barriers
        // the string. Do not reenter its loader cctor here.
        auto result=ba::api<void*(*)(const wchar_t*,int32_t)>("il2cpp_string_new_utf16")(selected.path().data(),static_cast<int32_t>(selected.path().size()));
        ba_native_settings::require(result!=nullptr,"native settings path allocation failed");return result;
    }catch(const std::exception& error) {
        ba::log("Native local-user settings isolation failed: %s; originalPathUnused=1",error.what());
    }catch(...) {ba::log("Native local-user settings isolation failed: unknown error; originalPathUnused=1");}
    TerminateProcess(GetCurrentProcess(),ERROR_BAD_CONFIGURATION);ExitProcess(ERROR_BAD_CONFIGURATION);
}
