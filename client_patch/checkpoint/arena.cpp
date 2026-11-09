// Isolated original-build checkpoint experiment. Not linked into the client.
// Call only at native API boundaries, on the installing thread, with no workers.
// A private derived import table routes native heap calls here from the first
// DLL initializer. This captures intercepted heap storage, writable image data
// and static TLS; FLS and operating-system state need separate qualification.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <intrin.h>
#include <cstdint>
#include <cstring>
#include <memory>
#include <vector>
#include <array>
#include <algorithm>
#include "page_checkpoint.hpp"
#pragma comment(linker, "/EXPORT:HeapAlloc=BAHeapAlloc")
#pragma comment(linker, "/EXPORT:HeapFree=BAHeapFree")
#pragma comment(linker, "/EXPORT:HeapReAlloc=BAHeapReAlloc")
#pragma comment(linker, "/EXPORT:HeapSize=BAHeapSize")

namespace {
constexpr size_t kReserve = size_t(512) << 20;
constexpr size_t kDataRva = 0x427000, kDataSize = 0x39744;
constexpr size_t kTlsIndexRva = 0x45f300, kTlsSize = 133;
constexpr uint64_t kMagic = 0x424143484b424c4b;
struct alignas(16) Block { uint64_t magic, capacity, requested, next; };
static_assert(sizeof(Block) == 32);
struct State {
    uint64_t high = 16, live = 0, liveBytes = 0;
    std::array<uint64_t, 32> free{};
};
struct Stats {
    uint64_t version = 2, error = 0, allocations = 0, frees = 0, reallocations = 0;
    uint64_t unknown = 0, foreignThreads = 0, high = 0, live = 0, liveBytes = 0;
    uint64_t captures = 0, restores = 0, committed = 0;
    uint64_t captureBytes = 0, restoreBytes = 0, captureMicros = 0, restoreMicros = 0, savedBytes = 0;
};
struct Unknown { uint64_t operation, pointer, size, caller, heap; };
std::array<Unknown, 32> unknowns{};
size_t unknownCount = 0;
bool sealed = false;
struct Checkpoint {
    uint64_t id;
    uint64_t pageId;
    State state;
    std::vector<uint8_t> data, tls;
};
HMODULE image = nullptr;
DWORD owner = 0;
HANDLE nativeHeap = nullptr;
uint8_t* arena = nullptr;
size_t committed = 0;
State state;
Stats stats;
std::vector<std::unique_ptr<Checkpoint>> saved;
std::unique_ptr<ba_page_checkpoint::Store> pages;
uint64_t nextId = 1;
using Alloc = LPVOID (WINAPI*)(HANDLE,DWORD,SIZE_T);
using Free = BOOL (WINAPI*)(HANDLE,DWORD,LPVOID);
using Realloc = LPVOID (WINAPI*)(HANDLE,DWORD,LPVOID,SIZE_T);
using Size = SIZE_T (WINAPI*)(HANDLE,DWORD,LPCVOID);
Alloc originalAlloc = nullptr;
Free originalFree = nullptr;
Realloc originalRealloc = nullptr;
Size originalSize = nullptr;

bool fail(uint64_t code) { if (!stats.error) stats.error = code; return false; }
bool thread() {
    if (GetCurrentThreadId() == owner) return true;
    InterlockedIncrement64(reinterpret_cast<volatile LONG64*>(&stats.foreignThreads));
    return fail(1);
}
bool flags(DWORD value, DWORD allowed) { return !(value & ~allowed) || fail(2); }
unsigned bin(size_t requested, size_t& capacity) {
    unsigned result = 0; capacity = 16;
    while (capacity < requested && result < 31) { capacity *= 2; ++result; }
    return result;
}
bool commit(size_t end) {
    if (end > kReserve) return fail(3);
    if (end <= committed) return true;
    size_t amount = (end + 0xffff) & ~size_t(0xffff);
    if (!VirtualAlloc(arena + committed, amount - committed, MEM_COMMIT, PAGE_READWRITE)) return fail(4);
    committed = amount; return true;
}
Block* block(const void* pointer) {
    auto p = reinterpret_cast<uintptr_t>(pointer), a = reinterpret_cast<uintptr_t>(arena);
    if (!pointer || p < a + 16 + sizeof(Block) || p >= a + state.high) return nullptr;
    auto b = reinterpret_cast<Block*>(p - sizeof(Block));
    if ((p & 15) || b->magic != kMagic || !b->requested ||
        b->capacity < 16 || (b->capacity & (b->capacity-1)) ||
        b->requested > b->capacity || b->capacity > state.high - (p-a)) return nullptr;
    return b;
}
void* allocate(size_t bytes, DWORD options) {
    if (!bytes) bytes = 1;
    if (bytes > kReserve / 2) { fail(3); return nullptr; }
    size_t capacity; unsigned index = bin(bytes, capacity);
    Block* b = nullptr;
    if (state.free[index]) {
        if ((state.free[index] & 15) || state.free[index] < 16 ||
            state.free[index] > state.high - sizeof(Block)) { fail(5); return nullptr; }
        b = reinterpret_cast<Block*>(arena + state.free[index]);
        if (b->magic != kMagic || b->requested || b->capacity != capacity) { fail(5); return nullptr; }
        state.free[index] = b->next;
    } else {
        const size_t end = state.high + sizeof(Block) + capacity;
        if (!commit(end)) return nullptr;
        b = reinterpret_cast<Block*>(arena + state.high);
        b->magic = kMagic; b->capacity = capacity;
        state.high = end;
    }
    b->requested = bytes; b->next = 0;
    ++state.live; state.liveBytes += bytes; ++stats.allocations;
    void* result = b + 1;
    if (options & HEAP_ZERO_MEMORY) memset(result, 0, bytes);
    return result;
}
bool release(Block* b) {
    size_t capacity; unsigned index = bin(b->capacity, capacity);
    if (capacity != b->capacity) return fail(5);
    if (!state.live || state.liveBytes < b->requested) return fail(5);
    --state.live; state.liveBytes -= b->requested;
    b->requested = 0; b->next = state.free[index];
    state.free[index] = reinterpret_cast<uint8_t*>(b) - arena;
    ++stats.frees; return true;
}
bool inside(const void* pointer) {
    auto p = reinterpret_cast<uintptr_t>(pointer), a = reinterpret_cast<uintptr_t>(arena);
    return p >= a && p < a + kReserve;
}
void unknown(uint64_t operation, HANDLE heap, const void* pointer, size_t size, void* caller) {
    ++stats.unknown;
    if (unknownCount < unknowns.size()) unknowns[unknownCount++] = {
        operation, reinterpret_cast<uint64_t>(pointer), size,
        reinterpret_cast<uint64_t>(caller) - reinterpret_cast<uint64_t>(image),
        reinterpret_cast<uint64_t>(heap)};
    fail(6);
}
LPVOID WINAPI heapAlloc(HANDLE heap, DWORD options, SIZE_T bytes) {
    if (!thread() || !flags(options, HEAP_ZERO_MEMORY)) return nullptr;
    if (heap != nativeHeap) { unknown(1,heap,nullptr,bytes,_ReturnAddress()); return originalAlloc(heap, options, bytes); }
    return allocate(bytes, options);
}
BOOL WINAPI heapFree(HANDLE heap, DWORD options, LPVOID pointer) {
    if (!thread() || !flags(options, 0)) return FALSE;
    if (!pointer) return TRUE;
    auto b = block(pointer);
    if (heap != nativeHeap || !b) {
        if (inside(pointer)) { fail(5); return FALSE; }
        unknown(2,heap,pointer,originalSize(heap,0,pointer),_ReturnAddress());
        return originalFree(heap, options, pointer);
    }
    return release(b);
}
LPVOID WINAPI heapRealloc(HANDLE heap, DWORD options, LPVOID pointer, SIZE_T bytes) {
    if (!thread() || !flags(options, HEAP_ZERO_MEMORY | HEAP_REALLOC_IN_PLACE_ONLY)) return nullptr;
    auto b = block(pointer);
    if (heap != nativeHeap || !b) {
        if (inside(pointer)) { fail(5); return nullptr; }
        unknown(3,heap,pointer,bytes,_ReturnAddress()); return originalRealloc(heap, options, pointer, bytes);
    }
    ++stats.reallocations;
    if (!bytes) bytes = 1;
    if (bytes <= b->capacity) {
        if ((options & HEAP_ZERO_MEMORY) && bytes > b->requested)
            memset(reinterpret_cast<uint8_t*>(pointer) + b->requested, 0, bytes - b->requested);
        state.liveBytes = state.liveBytes - b->requested + bytes;
        b->requested = bytes; return pointer;
    }
    if (options & HEAP_REALLOC_IN_PLACE_ONLY) return nullptr;
    auto replacement = allocate(bytes, options);
    if (!replacement) return nullptr;
    memcpy(replacement, pointer, b->requested); release(b); return replacement;
}
SIZE_T WINAPI heapSize(HANDLE heap, DWORD options, LPCVOID pointer) {
    if (!thread() || !flags(options, 0)) return SIZE_T(-1);
    auto b = block(pointer);
    if (heap != nativeHeap || !b) {
        if (inside(pointer)) { fail(5); return SIZE_T(-1); }
        unknown(4,heap,pointer,0,_ReturnAddress()); return originalSize(heap, options, pointer);
    }
    return b->requested;
}
uint8_t* tls() {
    auto slots = reinterpret_cast<uint8_t**>(__readgsqword(0x58));
    const DWORD index = *reinterpret_cast<DWORD*>(reinterpret_cast<uint8_t*>(image) + kTlsIndexRva);
    if (!slots || index > 4095 || !slots[index]) { fail(7); return nullptr; }
    return slots[index];
}
}

extern "C" __declspec(dllexport) LPVOID WINAPI BAHeapAlloc(HANDLE heap,DWORD options,SIZE_T bytes) {
    return heapAlloc(heap,options,bytes);
}
extern "C" __declspec(dllexport) BOOL WINAPI BAHeapFree(HANDLE heap,DWORD options,LPVOID pointer) {
    return heapFree(heap,options,pointer);
}
extern "C" __declspec(dllexport) LPVOID WINAPI BAHeapReAlloc(HANDLE heap,DWORD options,LPVOID pointer,SIZE_T bytes) {
    return heapRealloc(heap,options,pointer,bytes);
}
extern "C" __declspec(dllexport) SIZE_T WINAPI BAHeapSize(HANDLE heap,DWORD options,LPCVOID pointer) {
    return heapSize(heap,options,pointer);
}
extern "C" __declspec(dllexport) int BAInitialize() {
    if (arena || image) return -1;
    owner = GetCurrentThreadId(); nativeHeap = GetProcessHeap();
    auto kernel = GetModuleHandleW(L"kernel32.dll");
    originalAlloc = reinterpret_cast<Alloc>(GetProcAddress(kernel,"HeapAlloc"));
    originalFree = reinterpret_cast<Free>(GetProcAddress(kernel,"HeapFree"));
    originalRealloc = reinterpret_cast<Realloc>(GetProcAddress(kernel,"HeapReAlloc"));
    originalSize = reinterpret_cast<Size>(GetProcAddress(kernel,"HeapSize"));
    arena = static_cast<uint8_t*>(VirtualAlloc(nullptr, kReserve, MEM_RESERVE|MEM_WRITE_WATCH, PAGE_NOACCESS));
    if (!arena) return -3;
    try {
        saved.reserve(16);
        pages = std::make_unique<ba_page_checkpoint::Store>(arena,kReserve,size_t(384)*1024*1024);
    } catch (...) { fail(9); return -4; }
    return 0;
}
extern "C" __declspec(dllexport) int BAInstall(HMODULE target) {
    if (!arena || image || !target || !thread() || stats.error) return -1;
    auto base = reinterpret_cast<uint8_t*>(target);
    auto dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    auto pe = reinterpret_cast<IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || pe->Signature != IMAGE_NT_SIGNATURE ||
        pe->OptionalHeader.SizeOfImage < kDataRva + kDataSize ||
        memcmp(base + 0x331b4, "\x8d\x56\x00", 3)) return -2;
    // The loader must already have routed every native initializer's allocation
    // through this helper; accepting post-load IAT replacement would miss them.
    if (*reinterpret_cast<void**>(base+0x3852d8) != reinterpret_cast<void*>(BAHeapAlloc) ||
        *reinterpret_cast<void**>(base+0x3852e0) != reinterpret_cast<void*>(BAHeapFree) ||
        *reinterpret_cast<void**>(base+0x385360) != reinterpret_cast<void*>(BAHeapReAlloc) ||
        *reinterpret_cast<void**>(base+0x3853b8) != reinterpret_cast<void*>(BAHeapSize)) return -4;
    auto sections = IMAGE_FIRST_SECTION(pe);
    bool dataVerified = false;
    for (WORD i=0;i<pe->FileHeader.NumberOfSections;++i) {
        if (sections[i].VirtualAddress == kDataRva && sections[i].Misc.VirtualSize == kDataSize &&
            (sections[i].Characteristics & IMAGE_SCN_MEM_WRITE)) dataVerified = true;
        else if (sections[i].Characteristics & IMAGE_SCN_MEM_WRITE) return -5;
    }
    auto directory = pe->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_TLS];
    if (!dataVerified || directory.Size != sizeof(IMAGE_TLS_DIRECTORY64)) return -5;
    auto tlsDirectory = reinterpret_cast<IMAGE_TLS_DIRECTORY64*>(base+directory.VirtualAddress);
    if (tlsDirectory->EndAddressOfRawData-tlsDirectory->StartAddressOfRawData != kTlsSize ||
        tlsDirectory->SizeOfZeroFill || tlsDirectory->AddressOfIndex != reinterpret_cast<uint64_t>(base+kTlsIndexRva)) return -5;
    image = target; return 0;
}

extern "C" __declspec(dllexport) uint64_t BACapture() {
    if (!image || !sealed || !thread() || stats.error || saved.size() >= 16) return 0;
    auto storage = tls(); if (!storage) return 0;
    try {
        auto p = std::make_unique<Checkpoint>();
        p->id = nextId++; p->state = state;
        auto data = reinterpret_cast<uint8_t*>(image) + kDataRva;
        p->data.assign(data, data + kDataSize);
        p->tls.assign(storage, storage + kTlsSize);
        p->pageId = pages->capture(state.high,(state.high+0xffff)&~size_t(0xffff));
        const auto id = p->id; saved.push_back(std::move(p)); ++stats.captures; return id;
    } catch (...) { fail(9); return 0; }
}
extern "C" __declspec(dllexport) int BAGetUnknown(Unknown* output, uint32_t count) {
    if (!thread() || count != unknownCount || (count && !output)) return -1;
    if (count) memcpy(output,unknowns.data(),count*sizeof(Unknown));
    return static_cast<int>(unknownCount);
}
// Early interception must have zero unknown allocations, including startup.
extern "C" __declspec(dllexport) int BASeal() {
    if (!image || !thread() || sealed || stats.captures || stats.foreignThreads ||
        stats.error || unknownCount || stats.unknown) return -1;
    sealed = true; return 0;
}
extern "C" __declspec(dllexport) int BARestore(uint64_t id) {
    if (!image || !thread() || stats.error) return -1;
    auto storage = tls(); if (!storage) return -2;
    for (auto& p : saved) if (p->id == id) {
        try {
            auto position = pages->restore(p->pageId,committed);
            if (position.high != p->state.high) { fail(10); return -4; }
        } catch (...) { fail(9); return -4; }
        memcpy(reinterpret_cast<uint8_t*>(image) + kDataRva, p->data.data(), p->data.size());
        memcpy(storage, p->tls.data(), p->tls.size());
        state = p->state; ++stats.restores; return 0;
    }
    return -3;
}
extern "C" __declspec(dllexport) int BADrop(uint64_t id) {
    if (!thread()) return -1;
    for (auto i = saved.begin(); i != saved.end(); ++i) if ((*i)->id == id) {
        try { pages->drop((*i)->pageId); } catch (...) { fail(9); return -3; }
        saved.erase(i); return 0;
    }
    return -2;
}
extern "C" __declspec(dllexport) int BAGetStats(Stats* output, uint32_t size) {
    if (!output || size != sizeof(Stats) || !thread()) return -1;
    stats.high = state.high; stats.live = state.live; stats.liveBytes = state.liveBytes;
    if (pages) {
        const auto p = pages->stats();
        stats.captureBytes=p.lastCaptureCopiedBytes;stats.restoreBytes=p.lastRestoreCopiedBytes;
        stats.captureMicros=p.lastCaptureMicros;stats.restoreMicros=p.lastRestoreMicros;
        stats.savedBytes=p.uniqueSavedBytes;
    }
    stats.committed = committed; *output = stats; return 0;
}
// Hooks deliberately remain until process exit: CRT detach may still free blocks.
// Do not unload this helper or release its arena while the native DLL is loaded.
