// Authored watchpoint control. Does not load game files or contact a network.
#include <windows.h>
#include <cstdint>
#include <cstdio>

alignas(8) static volatile uint64_t watchSlot = 0;

static bool waitFile(const wchar_t* name) {
    const auto started = GetTickCount64();
    while (GetTickCount64() - started < 180000) {
        if (GetFileAttributesW(name) != INVALID_FILE_ATTRIBUTES) return true;
        Sleep(20);
    }
    return false;
}

int wmain() {
    FILE* out = nullptr;
    if (_wfopen_s(&out, L"ready.json", L"wx") || !out) return 2;
    fprintf(out, "{\"pid\":%lu,\"tid\":%lu,\"address\":\"%p\",\"initial\":0}\n",
            GetCurrentProcessId(), GetCurrentThreadId(), (const void*)&watchSlot);
    fclose(out);
    if (!waitFile(L"write.flag")) return 3;
    watchSlot = 0x315977471ULL;
    if (_wfopen_s(&out, L"wrote.json", L"wx") || !out) return 4;
    fprintf(out, "{\"value\":%llu,\"tid\":%lu}\n", watchSlot, GetCurrentThreadId());
    fclose(out);
    if (!waitFile(L"finish.flag")) return 5;
    watchSlot = 0x315977472ULL;
    if (_wfopen_s(&out, L"finished.json", L"wx") || !out) return 6;
    fprintf(out, "{\"value\":%llu,\"tid\":%lu}\n", watchSlot, GetCurrentThreadId());
    fclose(out);
    return watchSlot == 0x315977472ULL ? 0 : 7;
}
