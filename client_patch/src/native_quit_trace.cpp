#pragma once
// Opt-in owned diagnostic only. The original Dispose always runs unchanged.
namespace ba_native_quit {
static void update(ba::Obj);
static std::atomic<HANDLE> trace{INVALID_HANDLE_VALUE};
static std::atomic<bool> ioFailed{false};
static void mark(const char* event) noexcept {
    const auto handle=trace.load();if(handle==INVALID_HANDLE_VALUE)return;
    char line[192];const int length=_snprintf_s(line,sizeof(line),_TRUNCATE,
        "{\"tick\":%llu,\"pid\":%lu,\"thread\":%lu,\"event\":\"%s\"}\n",
        GetTickCount64(),GetCurrentProcessId(),GetCurrentThreadId(),event);
    if(length<=0)return;
    DWORD written=0;if(!WriteFile(handle,line,static_cast<DWORD>(length),&written,nullptr) || written!=static_cast<DWORD>(length) || !FlushFileBuffers(handle))ioFailed=true;
}
static void arm() {
    ba_native_settings::require(ba::flag(L"-native-quit-smoke") && ba_native_settings::session &&
        ba_native_settings::session->profile().compare(0,12,"nativestest_")==0,
        "native Quit trace requires an explicit owned test profile");
    ba_native_settings::require(trace.load()==INVALID_HANDLE_VALUE,"native Quit trace already armed");
    const auto& target=ba_native_settings::session->path();
    const auto path=target.substr(0,target.find_last_of(L'\\')+1)+L"quit-trace.jsonl";
    const auto handle=CreateFileW(path.c_str(),GENERIC_WRITE,FILE_SHARE_READ,nullptr,CREATE_NEW,
        FILE_ATTRIBUTE_NORMAL|FILE_FLAG_WRITE_THROUGH,nullptr);
    ba_native_settings::require(handle!=INVALID_HANDLE_VALUE,"owned native Quit trace destination unavailable");
    // No CRT/managed destructor: the OS closes this after native shutdown.
    trace=handle;mark("armed");
    ba_native_settings::require(!ioFailed.load(),"owned native Quit trace initial write failed");
    ba::log("NATIVE QUIT trace armed: BA_RESURRECTION_NATIVE_QUIT_TRACE_V1 profile=%s",
        ba_native_settings::session->profile().c_str());
}
}
extern "C" __declspec(dllexport) void OfflineNativeQuitDispose(void* instance,void* method) {
    ba::init();ba_native_quit::mark("RGameInstance.Dispose.enter");
    ba::native<void(*)(void*,void*)>(0x3de2a30)(instance,method);
    ba_native_quit::mark("RGameInstance.Dispose.return");
}
extern "C" __declspec(dllexport) void OfflineNativeQuitAIDispose(void* instance,void* method) {
    ba::init();ba_native_quit::mark("AIManager.Dispose.enter");
    ba::native<void(*)(void*,void*)>(0x3b983b0)(instance,method);
    ba_native_quit::mark("AIManager.Dispose.return");
}
extern "C" __declspec(dllexport) void OfflineNativeQuitOnDestroy(void* instance,void* method) {
    ba::init();ba_native_quit::mark("RGameSingleton.OnDestroy.enter");
    // Only the codegen registration pointer is redirected. The original body
    // is untouched,so forwarding directly cannot recurse through this wrapper.
    ba::native<void(*)(void*,void*)>(0x3de4820)(instance,method);
    ba_native_quit::mark("RGameSingleton.OnDestroy.return");
}
