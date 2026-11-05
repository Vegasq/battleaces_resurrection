// Authored native control only. Does not load any game files.
#include <windows.h>
#include <cstdio>
#include <cstdint>
#include <cstring>

using Callback = uint64_t(*)(uint64_t, uint64_t);
static Callback callback = nullptr;
static DWORD workerTid = 0;
extern "C" __declspec(dllexport) __declspec(noinline)
int AuthoredCaller(Callback fn, int count) {
    int total = 0;
    for (int i = 0; i < count; ++i) {
        const auto value = fn(i, 42-i);
        if (value != 42) return -1000;
        total += static_cast<int>(value);
    }
    return total;
}
static bool waitFile(const wchar_t* name) {
    const auto start = GetTickCount64();
    while (GetTickCount64()-start < 180000) {
        if (GetFileAttributesW(name) != INVALID_FILE_ATTRIBUTES) return true;
        Sleep(20);
    }
    return false;
}
static DWORD WINAPI work(void*) {
    workerTid = GetCurrentThreadId();
    return AuthoredCaller(callback, 7) == 294 ? 0 : 4;
}
int wmain() {
    wchar_t dll[MAX_PATH];
    if (!GetFullPathNameW(L"UnityPlayer.dll", MAX_PATH, dll, nullptr)) return 2;
    auto module = LoadLibraryW(dll);
    if (!module) return 3;
    callback = reinterpret_cast<Callback>(GetProcAddress(module, "Fixture"));
    if (!callback || reinterpret_cast<uintptr_t>(callback)-reinterpret_cast<uintptr_t>(module) != 0xc307c0) return 4;
    if (!waitFile(L"invoke.flag")) return 5;
    const int mainResult = AuthoredCaller(callback, 6);
    auto thread = CreateThread(nullptr, 0, work, nullptr, 0, nullptr);
    if (!thread || WaitForSingleObject(thread, 10000) != WAIT_OBJECT_0) return 6;
    DWORD workerResult = 1;
    GetExitCodeThread(thread, &workerResult); CloseHandle(thread);
    FILE* output = nullptr;
    if (_wfopen_s(&output, L"calls.json", L"wx") || !output) return 7;
    fprintf(output, "{\"mainTid\":%lu,\"workerTid\":%lu,\"mainCalls\":6,\"workerCalls\":7,\"mainResult\":%d,\"workerExit\":%lu}\n",
        GetCurrentThreadId(), workerTid, mainResult, workerResult);
    fclose(output);
    if (!waitFile(L"finish.flag")) return 8;
    const int after = AuthoredCaller(callback, 2);
    bool restored = true;
    auto bytes = reinterpret_cast<const unsigned char*>(callback);
    for (int i=0;i<16;++i) restored = restored && bytes[i] == 0x90;
    for (int i=0x78;i<0x7d;++i) restored = restored && bytes[i] == 0x90;
    if (_wfopen_s(&output, L"finished.json", L"wx") || !output) return 9;
    fprintf(output,"{\"afterDetachCalls\":2,\"afterDetachResult\":%d,\"entryAndGuardRestored\":%s}\n",after,restored?"true":"false");
    fclose(output);
    FreeLibrary(module);
    return mainResult == 252 && workerResult == 0 && after == 84 && restored ? 0 : 10;
}
