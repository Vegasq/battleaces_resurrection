// Disposable instrumentation control. An owned local file releases its original
// main-thread exception; the observer never calls native functions in the target.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdio>
#include <cstring>

static HANDLE journal = INVALID_HANDLE_VALUE;
static DWORD mainThread = 0;
static void record(const char* kind, DWORD code = 0) {
    char row[192]{};
    const int size = std::snprintf(row, sizeof(row),
        "%s pid=%lu thread=%lu mainThread=%lu code=%lu errorMode=%lu\n",
        kind, GetCurrentProcessId(), GetCurrentThreadId(), mainThread, code, GetErrorMode());
    DWORD written = 0;
    if(size <= 0 || size >= static_cast<int>(sizeof(row)) || journal == INVALID_HANDLE_VALUE ||
       !WriteFile(journal, row, static_cast<DWORD>(size), &written, nullptr) || written != static_cast<DWORD>(size) ||
       !FlushFileBuffers(journal)) ExitProcess(81);
}
static LONG WINAPI unhandled(EXCEPTION_POINTERS* exception) {
    record("original-filter", exception->ExceptionRecord->ExceptionCode);
    return EXCEPTION_CONTINUE_SEARCH;
}
extern "C" __declspec(dllexport) __declspec(noinline) void CrashControlTick() {
    Sleep(10);
}
extern "C" __declspec(dllexport) __declspec(noinline) void CrashControlInvoke() {
    record("native-invoke");
    RaiseException(0xc0000005, 0, 0, nullptr);
    record("unexpected-return");
}
int main(int argc, char** argv) {
    if(argc != 2) return 80;
    const bool noWer = !std::strcmp(argv[1], "--owned-native-crash-control-no-wer");
    if(!noWer && std::strcmp(argv[1], "--owned-native-crash-control")) return 80;
    journal = CreateFileW(L"native-control.log", GENERIC_WRITE, FILE_SHARE_READ, nullptr,
                          CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
    if(journal == INVALID_HANDLE_VALUE) return 81;
    mainThread = GetCurrentThreadId();
    SetUnhandledExceptionFilter(unhandled);
    record("before-mode");
    if(noWer) SetErrorMode(GetErrorMode() | SEM_NOGPFAULTERRORBOX);
    record("ready");
    for(unsigned i = 0; i < 3000; ++i) {
        CrashControlTick();
        if(GetFileAttributesW(L"invoke-native-crash.flag") != INVALID_FILE_ATTRIBUTES)
            CrashControlInvoke();
    }
    record("no-probe-timeout");
    CloseHandle(journal);
    return 82;
}
