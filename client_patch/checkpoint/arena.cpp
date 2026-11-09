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
#include "thread_state.hpp"
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
// Diagnostic ABI1. All storage stays outside the rewound native arena. Each
// frame has its raw PC plus module base/RVA; UINT64_MAX RVA means unresolved.
// Free/Size use size0 because those APIs have no requested-size argument. Do
// not inspect the foreign pointer or call a heap API while recording failure.
constexpr size_t kForeignCapacity = 8, kForeignFrames = 16;
struct ForeignEvent {
    uint64_t version = 1, operation = 0, size = 0, pointer = 0;
    uint64_t threadId = 0, ownerThreadId = 0, nativeBase = 0, heap = 0;
    uint64_t caller = 0, tick = 0, frameCount = 0;
    std::array<uint64_t,kForeignFrames> addresses{}, moduleBases{}, rvas{};
};
static_assert(sizeof(ForeignEvent) == 472, "foreign event ABI must remain explicit");
std::array<ForeignEvent,kForeignCapacity> foreignEvents{};
std::array<volatile LONG,kForeignCapacity> foreignPublished{};
volatile LONG foreignClaims = 0;
using CaptureStack = USHORT (WINAPI*)(ULONG,ULONG,PVOID*,PULONG);
using PcToImage = PVOID (WINAPI*)(PVOID,PVOID*);
CaptureStack captureStack = nullptr;
PcToImage pcToImage = nullptr;
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
// Complete original function guards, read offline from SHA107bb83d...;
// private provenance/bytes: worker-root-guards01.json. No guarded bytes execute
// in authored unit tests. Primers are never reached by capture/restore/read.
constexpr char kVcrRead[] =
    "\x48\x89\x5c\x24\x08\x57\x48\x83\xec\x20\x83\x3d\x23\xe9\x0e\x00\xff\x75\x04\x33\xc0\xeb\x2b\xff"
    "\x15\xb7\x16\x04\x00\x8b\x0d\x11\xe9\x0e\x00\x8b\xd8\xe8\x3a\xb0\x00\x00\x8b\xcb\x48\x8b\xf8\xff"
    "\x15\xef\x16\x04\x00\x33\xc0\x48\x83\xff\xff\x48\x0f\x44\xf8\x48\x8b\xc7\x48\x8b\x5c\x24\x30\x48"
    "\x83\xc4\x20\x5f\xc3";
constexpr char kVcrPrime[] =
    "\x48\x89\x5c\x24\x08\x48\x89\x74\x24\x10\x57\x48\x83\xec\x20\x83\x3d\xde\xe9\x0e\x00\xff\x75\x07"
    "\x33\xc0\xe9\x90\x00\x00\x00\xff\x15\x6f\x17\x04\x00\x8b\x0d\xc9\xe9\x0e\x00\x8b\xf8\xe8\xf2\xb0"
    "\x00\x00\x48\x83\xca\xff\x33\xf6\x48\x3b\xc2\x74\x67\x48\x85\xc0\x74\x05\x48\x8b\xf0\xeb\x5d\x8b"
    "\x0d\xa7\xe9\x0e\x00\xe8\x1a\xb1\x00\x00\x85\xc0\x74\x4e\xba\x80\x00\x00\x00\x8d\x4a\x81\xe8\x45"
    "\xb8\x00\x00\x8b\x0d\x8b\xe9\x0e\x00\x48\x8b\xd8\x48\x85\xc0\x74\x24\x48\x8b\xd0\xe8\xf3\xb0\x00"
    "\x00\x85\xc0\x74\x12\x48\x8b\xc3\xc7\x43\x78\xfe\xff\xff\xff\x48\x8b\xde\x48\x8b\xf0\xeb\x0d\x8b"
    "\x0d\x5f\xe9\x0e\x00\x33\xd2\xe8\xd0\xb0\x00\x00\x48\x8b\xcb\xe8\x0c\xb8\x00\x00\x8b\xcf\xff\x15"
    "\x38\x17\x04\x00\x48\x8b\xc6\x48\x8b\x5c\x24\x30\x48\x8b\x74\x24\x38\x48\x83\xc4\x20\x5f\xc3";
constexpr char kVcrRawRead[] =
    "\x40\x53\x48\x83\xec\x20\x8b\xd9\x4c\x8d\x0d\x89\x34\x07\x00\xb9\x02\x00\x00\x00\x4c\x8d\x05\x75"
    "\x34\x07\x00\x48\x8d\x15\xb6\x17\x07\x00\xe8\xf9\xfd\xff\xff\x8b\xcb\x48\x85\xc0\x74\x0c\x48\x83"
    "\xc4\x20\x5b\x48\xff\x25\x16\x6a\x03\x00\x48\x83\xc4\x20\x5b\x48\xff\x25\x6a\x68\x03\x00";
constexpr char kUcrtPrime[] =
    "\x48\x89\x5c\x24\x08\x48\x89\x74\x24\x10\x57\x48\x83\xec\x20\xff\x15\x4b\x1d\x02\x00\x8b\x0d\x95"
    "\xf2\x0c\x00\x33\xf6\x8b\xd8\x83\xf9\xff\x74\x1d\xe8\x03\x45\x00\x00\x48\x8b\xf8\x48\x85\xc0\x74"
    "\x0a\x48\x83\xf8\xff\x48\x0f\x44\xfe\xeb\x72\x8b\x0d\x6f\xf2\x0c\x00\x48\x83\xca\xff\xe8\xea\x44"
    "\x00\x00\x85\xc0\x75\x05\x48\x8b\xfe\xeb\x5a\xba\xc8\x03\x00\x00\xb9\x01\x00\x00\x00\xe8\x06\x25"
    "\x00\x00\x8b\x0d\x48\xf2\x0c\x00\x48\x8b\xf8\x48\x85\xc0\x75\x10\x33\xd2\xe8\xbd\x44\x00\x00\x33"
    "\xc9\xe8\x62\x25\x00\x00\xeb\xce\x48\x8b\xd7\xe8\xac\x44\x00\x00\x85\xc0\x75\x12\x8b\x0d\x1e\xf2"
    "\x0c\x00\x33\xd2\xe8\x9b\x44\x00\x00\x48\x8b\xcf\xeb\xdb\x48\x8b\xcf\xe8\x4e\xfb\xff\xff\x33\xc9"
    "\xe8\x33\x25\x00\x00\x8b\xcb\xff\x15\xfb\x1c\x02\x00\x48\x8b\x5c\x24\x30\x48\x8b\xc7\x48\x8b\x74"
    "\x24\x38\x48\x83\xc4\x20\x5f\xc3";
constexpr char kUcrtReadThunk[] =
    "\x48\xff\x25\xb5\xd9\x01\x00";
struct RootCodeGuard { size_t rva; const char* bytes; size_t size; };
constexpr std::array<RootCodeGuard,5> kRootGuards{{
    {0x34392c,kVcrRead,sizeof(kVcrRead)-1},
    {0x34386c,kVcrPrime,sizeof(kVcrPrime)-1},
    {0x34e990,kVcrRawRead,sizeof(kVcrRawRead)-1},
    {0x3632a0,kUcrtPrime,sizeof(kUcrtPrime)-1},
    {0x3677cc,kUcrtReadThunk,sizeof(kUcrtReadThunk)-1},
}};
std::unique_ptr<ba_thread_state::NativeReader> rootReader;
bool rootPrimeAttempted=false,rootPrimed=false;
bool rootCodeGuards(const uint8_t* base) {
    for(const auto& guard:kRootGuards)
        if(std::memcmp(base+guard.rva,guard.bytes,guard.size))return false;
    return true;
}
std::array<uint64_t,7> checkedRootValues(const ba_thread_state::CurrentState& current) {
    ba_thread_state::LastError preserve;
    ba_thread_state::require(current.threadId==owner && current.threadId==GetCurrentThreadId(),"root reader owner changed");
    ba_thread_state::require(current.tlsIndex!=TLS_OUT_OF_INDEXES && current.tlsIndex<4096 &&
        current.vcrIndex!=FLS_OUT_OF_INDEXES && current.ucrtIndex!=FLS_OUT_OF_INDEXES,"native root index unavailable");
    ba_thread_state::require(current.vcrRoot && current.ucrtRoot &&
        current.vcrRoot!=reinterpret_cast<void*>(~uintptr_t(0)) &&
        current.ucrtRoot!=reinterpret_cast<void*>(~uintptr_t(0)),"native roots are null/initializing");
    ba_thread_state::writableTls(current.tls);
    return {{current.threadId,current.tlsIndex,current.vcrIndex,current.ucrtIndex,
        reinterpret_cast<uint64_t>(current.tls),reinterpret_cast<uint64_t>(current.vcrRoot),
        reinterpret_cast<uint64_t>(current.ucrtRoot)}};
}
template<class Read,class PrimeVcr,class PrimeUcrt>
std::array<uint64_t,7> primeRootFunctions(Read read,PrimeVcr vcr,PrimeUcrt ucrt) {
    ba_thread_state::LastError preserve;
    const auto first=vcr();
    ba_thread_state::require(first && first!=reinterpret_cast<void*>(~uintptr_t(0)),"VCR root priming failed");
    const auto second=ucrt();
    ba_thread_state::require(second && second!=reinterpret_cast<void*>(~uintptr_t(0)),"UCRT root priming failed");
    const auto current=read();const auto result=checkedRootValues(current);
    ba_thread_state::require(current.vcrRoot==first && current.ucrtRoot==second,"primed roots disagree with nonallocating reader");
    return result;
}

bool fail(uint64_t code) {
    InterlockedCompareExchange64(reinterpret_cast<volatile LONG64*>(&stats.error),static_cast<LONG64>(code),0);
    return false;
}
void foreign(uint64_t operation,const void* pointer,size_t size,HANDLE heap,void* caller) noexcept {
    const DWORD error = GetLastError();
    LONG index = InterlockedCompareExchange(&foreignClaims,0,0);
    for (;;) {
        if (index >= static_cast<LONG>(kForeignCapacity)) { SetLastError(error); return; }
        const LONG observed = InterlockedCompareExchange(&foreignClaims,index+1,index);
        if (observed == index) break;
        index = observed;
    }
    ForeignEvent event;
    event.operation = operation; event.size = size;
    event.pointer = reinterpret_cast<uint64_t>(pointer);
    event.threadId = GetCurrentThreadId(); event.ownerThreadId = owner;
    event.nativeBase = reinterpret_cast<uint64_t>(image);
    event.heap = reinterpret_cast<uint64_t>(heap); event.caller = reinterpret_cast<uint64_t>(caller);
    event.tick = GetTickCount64();
    // No formatting, filesystem, dynamic container, module enumeration, or
    // native heap call here. APIs were resolved before the derived DLL loaded.
    std::array<void*,kForeignFrames> frames{};
    if (captureStack && pcToImage) {
        event.frameCount = (std::min)(size_t(captureStack(0,static_cast<ULONG>(kForeignFrames),frames.data(),nullptr)),kForeignFrames);
        for (size_t frame=0;frame<event.frameCount;++frame) {
            void* base = nullptr;
            pcToImage(frames[frame],&base);
            const auto address = reinterpret_cast<uint64_t>(frames[frame]);
            const auto module = reinterpret_cast<uint64_t>(base);
            event.addresses[frame] = address; event.moduleBases[frame] = module;
            event.rvas[frame] = module && address >= module ? address-module : UINT64_MAX;
        }
    }
    foreignEvents[static_cast<size_t>(index)] = event;
    InterlockedExchange(&foreignPublished[static_cast<size_t>(index)],1);
    SetLastError(error);
}
bool thread(uint64_t operation=0,const void* pointer=nullptr,size_t size=0,HANDLE heap=nullptr,void* caller=nullptr) {
    if (GetCurrentThreadId() == owner) return true;
    InterlockedIncrement64(reinterpret_cast<volatile LONG64*>(&stats.foreignThreads));
    fail(1);foreign(operation,pointer,size,heap,caller);return false;
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
LPVOID WINAPI heapAlloc(HANDLE heap, DWORD options, SIZE_T bytes,void* caller) {
    if (!thread(1,nullptr,bytes,heap,caller) || !flags(options, HEAP_ZERO_MEMORY)) return nullptr;
    if (heap != nativeHeap) { unknown(1,heap,nullptr,bytes,_ReturnAddress()); return originalAlloc(heap, options, bytes); }
    return allocate(bytes, options);
}
BOOL WINAPI heapFree(HANDLE heap, DWORD options, LPVOID pointer,void* caller) {
    if (!thread(2,pointer,0,heap,caller) || !flags(options, 0)) return FALSE;
    if (!pointer) return TRUE;
    auto b = block(pointer);
    if (heap != nativeHeap || !b) {
        if (inside(pointer)) { fail(5); return FALSE; }
        unknown(2,heap,pointer,originalSize(heap,0,pointer),_ReturnAddress());
        return originalFree(heap, options, pointer);
    }
    return release(b);
}
LPVOID WINAPI heapRealloc(HANDLE heap, DWORD options, LPVOID pointer, SIZE_T bytes,void* caller) {
    if (!thread(3,pointer,bytes,heap,caller) || !flags(options, HEAP_ZERO_MEMORY | HEAP_REALLOC_IN_PLACE_ONLY)) return nullptr;
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
SIZE_T WINAPI heapSize(HANDLE heap, DWORD options, LPCVOID pointer,void* caller) {
    if (!thread(4,pointer,0,heap,caller) || !flags(options, 0)) return SIZE_T(-1);
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
    return heapAlloc(heap,options,bytes,_ReturnAddress());
}
extern "C" __declspec(dllexport) BOOL WINAPI BAHeapFree(HANDLE heap,DWORD options,LPVOID pointer) {
    return heapFree(heap,options,pointer,_ReturnAddress());
}
extern "C" __declspec(dllexport) LPVOID WINAPI BAHeapReAlloc(HANDLE heap,DWORD options,LPVOID pointer,SIZE_T bytes) {
    return heapRealloc(heap,options,pointer,bytes,_ReturnAddress());
}
extern "C" __declspec(dllexport) SIZE_T WINAPI BAHeapSize(HANDLE heap,DWORD options,LPCVOID pointer) {
    return heapSize(heap,options,pointer,_ReturnAddress());
}
extern "C" __declspec(dllexport) int BAInitialize() {
    if (arena || image) return -1;
    owner = GetCurrentThreadId(); nativeHeap = GetProcessHeap();
    auto kernel = GetModuleHandleW(L"kernel32.dll");
    originalAlloc = reinterpret_cast<Alloc>(GetProcAddress(kernel,"HeapAlloc"));
    originalFree = reinterpret_cast<Free>(GetProcAddress(kernel,"HeapFree"));
    originalRealloc = reinterpret_cast<Realloc>(GetProcAddress(kernel,"HeapReAlloc"));
    originalSize = reinterpret_cast<Size>(GetProcAddress(kernel,"HeapSize"));
    const auto ntdll = GetModuleHandleW(L"ntdll.dll");
    captureStack = reinterpret_cast<CaptureStack>(GetProcAddress(ntdll,"RtlCaptureStackBackTrace"));
    pcToImage = reinterpret_cast<PcToImage>(GetProcAddress(ntdll,"RtlPcToFileHeader"));
    if (!captureStack || !pcToImage) return -5;
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
    try {
        if(!rootCodeGuards(base))return -6;
        rootReader=std::make_unique<ba_thread_state::NativeReader>(target);
    }catch(...){fail(11);return -6;}
    image = target; return 0;
}

// Explicit pre-checkpoint setup only. The safe original lazy getters are
// called once here; capture/restore and the readonly getter never call them.
extern "C" __declspec(dllexport) int BAPrimeRootBindings() noexcept {
    ba_thread_state::LastError preserve;
    if(!image || !rootReader || !thread() || stats.error || rootPrimeAttempted ||
       stats.captures || !saved.empty())return -1;
    rootPrimeAttempted=true;
    try {
        if(!rootCodeGuards(reinterpret_cast<const uint8_t*>(image))){fail(11);return -2;}
        using Prime=void*(*)();const auto base=reinterpret_cast<uint8_t*>(image);
        primeRootFunctions([]{return (*rootReader)();},reinterpret_cast<Prime>(base+0x34386c),
                           reinterpret_cast<Prime>(base+0x3632a0));
        if(stats.error)return -3;
        rootPrimed=true;return 0;
    }catch(...){fail(11);return -3;}
}
// ABI1/count7: thread,tlsIndex,vcrIndex,ucrtIndex,tls,vcrRoot,ucrtRoot, all u64.
// Python owns the immutable checkpoint binding/revision and checks it BEFORE
// BARestore. No partial output, FLS SetValue, TLS copy or native-world mutation.
extern "C" __declspec(dllexport) int BAGetRootBindings(uint64_t* output,uint32_t count) noexcept {
    ba_thread_state::LastError preserve;
    if(!output || count!=7 || !image || !rootReader || !rootPrimed || !thread() || stats.error)return -1;
    try {
        if(!rootCodeGuards(reinterpret_cast<const uint8_t*>(image))){fail(11);return -2;}
        const auto values=checkedRootValues((*rootReader)());
        std::memcpy(output,values.data(),sizeof(values));return 0;
    }catch(...){fail(11);return -3;}
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
// ABI1. Explicit match-retirement cleanup only; unlike restore, this touches
// no native/arena/TLS/image bytes. Dropping IDs alone intentionally retains the
// incremental baseline, so release it before a new world's first full capture.
extern "C" __declspec(dllexport) int BAForgetCheckpointBaseline() noexcept {
    ba_thread_state::LastError preserve;
    if(!pages || !thread() || !saved.empty())return -1;
    try {pages->forgetBaseline();return 0;}
    catch(...){fail(9);return -2;}
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
extern "C" __declspec(dllexport) uint32_t BASizeOfForeignEvent() {
    return static_cast<uint32_t>(sizeof(ForeignEvent));
}
extern "C" __declspec(dllexport) uint32_t BAGetForeignEventCount() {
    if (!thread()) return UINT32_MAX;
    return static_cast<uint32_t>(InterlockedCompareExchange(&foreignClaims,0,0));
}
extern "C" __declspec(dllexport) int BAGetForeignEvents(ForeignEvent* output,uint32_t count,uint32_t eventSize) {
    if (!thread() || eventSize != sizeof(ForeignEvent) || count > kForeignCapacity ||
        count > static_cast<uint32_t>(InterlockedCompareExchange(&foreignClaims,0,0)) || (count && !output)) return -1;
    // Claims are bounded, but an exiting thread may still be capturing. The
    // caller may retry a finite number of times; no partial output is copied.
    for (uint32_t index=0;index<count;++index)
        if (InterlockedCompareExchange(&foreignPublished[index],0,0) != 1) return -2;
    if (count) memcpy(output,foreignEvents.data(),count*sizeof(ForeignEvent));
    return static_cast<int>(count);
}
// Hooks deliberately remain until process exit: CRT detach may still free blocks.
// Do not unload this helper or release its arena while the native DLL is loaded.
