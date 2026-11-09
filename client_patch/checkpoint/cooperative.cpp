// Isolated original-build experiment: zero-pool dependency waits pump queued work.
// Not linked into ordinary launchers. One owned process/thread/pool per lifetime.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <cstdint>
#include <cstring>
#include <array>
#include <vector>
#include <limits>

namespace {
struct Stats {
    uint64_t version = 1, error = 0, waitEntries = 0, pumps = 0, emptyPumps = 0;
    uint64_t maxDepth = 0, depth = 0, consumerWaits = 0, producerWaits = 0;
    uint64_t foreignThreads = 0, poolChanges = 0, exceptions = 0;
    uint64_t pool = 0, owner = 0, codeBase = 0;
};
struct Patch {
    uint8_t* address = nullptr;
    size_t size = 0;
    std::array<uint8_t, 14> original{};
    bool installed = false;
};
constexpr size_t kCodeSize = 65536, kMaximumDepth = 64, kMaximumPumps = 1000000;
constexpr uintptr_t kWaitCall = 0xf7f22, kWait = 0xa15f0, kTryRun = 0x291c00;
constexpr uintptr_t kConsumer = 0x9fbe0, kProducer = 0x9fd7d;
constexpr std::array<uint8_t, 5> kWaitBytes{{0xe8,0xc9,0x96,0xfa,0xff}};
constexpr std::array<uint8_t, 14> kConsumerBytes{{0x48,0x8b,0x0f,0x48,0x8b,0x89,0xe0,0,0,0,0x90,0x48,0x85,0xc9}};
constexpr std::array<uint8_t, 14> kProducerBytes{{0x48,0x8b,0x03,0x48,0x8b,0x80,0xf0,0,0,0,0x90,0x48,0x3b,0xc8}};
HMODULE image = nullptr;
DWORD owner = 0;
void* pool = nullptr;
uint8_t* code = nullptr;
std::array<Patch,3> patches{};
std::array<RUNTIME_FUNCTION,7> functions{};
bool registered = false;
Stats stats;
using Wait = void (__fastcall*)(void*,void*);
using TryRun = bool (__fastcall*)(void*);

void fail(uint64_t value) {
    InterlockedCompareExchange64(reinterpret_cast<volatile LONG64*>(&stats.error), static_cast<LONG64>(value), 0);
}
bool owned() {
    if (GetCurrentThreadId() == owner) return true;
    InterlockedIncrement64(reinterpret_cast<volatile LONG64*>(&stats.foreignThreads));
    fail(1); return false;
}
void __fastcall boundWait(void* service, void* suppliedPool) {
    if (!owned() || !suppliedPool) { fail(2); throw 2; }
    if (pool && pool != suppliedPool) { ++stats.poolChanges; fail(3); throw 3; }
    pool = suppliedPool;
    stats.pool = reinterpret_cast<uintptr_t>(pool);
    ++stats.waitEntries;
    reinterpret_cast<Wait>(reinterpret_cast<uintptr_t>(image)+kWait)(service,suppliedPool);
}

void __fastcall pump(uint64_t index, const void* capture, uint64_t producer) noexcept {
    if (!owned() || stats.error) return;
    if (!pool || !capture) { fail(4); return; }
    const auto service = *reinterpret_cast<const uint8_t* const*>(capture);
    if (!service) { fail(5); return; }
    const auto published = *reinterpret_cast<const volatile uint64_t*>(service+(producer ? 0xf0 : 0x1f8));
    const bool active = producer ? (*reinterpret_cast<const volatile uint8_t*>(service+0xd8) != 0)
                                : (*reinterpret_cast<const volatile uint64_t*>(service+0xe0) != 0);
    // Never pause a producer/consumer which can itself make progress. Only a
    // genuine dependency wait may execute another queued task recursively.
    if (!active || index < published) return;
    if (producer) ++stats.producerWaits; else ++stats.consumerWaits;
    if (stats.depth >= kMaximumDepth || stats.pumps >= kMaximumPumps) { fail(6); return; }
    ++stats.depth;
    if (stats.depth > stats.maxDepth) stats.maxDepth = stats.depth;
    ++stats.pumps;
    try {
        if (!reinterpret_cast<TryRun>(reinterpret_cast<uintptr_t>(image)+kTryRun)(pool)) ++stats.emptyPumps;
    } catch (...) {
        ++stats.exceptions; fail(7); // No C++ exception crosses a generated gateway.
    }
    --stats.depth;
}

void byte(std::vector<uint8_t>& bytes, uint8_t value) { bytes.push_back(value); }
void append(std::vector<uint8_t>& bytes, std::initializer_list<uint8_t> value) { bytes.insert(bytes.end(),value); }
void address(std::vector<uint8_t>& bytes, uintptr_t value) {
    const auto first = reinterpret_cast<const uint8_t*>(&value);
    bytes.insert(bytes.end(),first,first+sizeof(value));
}
bool displacement(uintptr_t from, uintptr_t to, int32_t& result) {
    const auto difference = static_cast<int64_t>(to)-static_cast<int64_t>(from+5);
    if (difference < std::numeric_limits<int32_t>::min() || difference > std::numeric_limits<int32_t>::max()) return false;
    result = static_cast<int32_t>(difference); return true;
}
uint8_t* allocateNear(uintptr_t target) {
    SYSTEM_INFO info{}; GetSystemInfo(&info);
    const uintptr_t granularity = info.dwAllocationGranularity;
    const uintptr_t aligned = target & ~(granularity-1);
    for (uintptr_t distance=0; distance<0x70000000; distance+=granularity) {
        for (unsigned direction=0; direction<2; ++direction) {
            if (direction && aligned < distance+granularity) continue;
            const uintptr_t candidate = direction ? aligned-distance : aligned+distance;
            auto memory = static_cast<uint8_t*>(VirtualAlloc(reinterpret_cast<void*>(candidate),kCodeSize,
                MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE));
            if (memory) return memory;
        }
    }
    return nullptr;
}

// Loop gateway entry has a real CALL return address. Both replaced native
// instruction spans use no RSP operands. All volatile registers/flags are
// restored before those copied instructions compute fresh native TEST/CMP flags.
struct Gateway { std::vector<uint8_t> bytes; uint32_t flagsOffset=0, leafOffset=0; };
Gateway loopGateway(bool producer, const std::array<uint8_t,14>& copied) {
    Gateway gateway;
    auto& result=gateway.bytes;
    append(result,{0x9c,0x50,0x51,0x52,0x41,0x50,0x41,0x51,0x41,0x52,0x41,0x53});
    append(result,{0x48,0x81,0xec,0x88,0,0,0});
    for (uint8_t index=0; index<6; ++index)
        append(result,{0xf3,0x0f,0x7f,static_cast<uint8_t>(0x44+8*index),0x24,static_cast<uint8_t>(0x20+16*index)});
    append(result,{0x0f,0xae,0x9c,0x24,0x80,0,0,0}); // stmxcsr [rsp+80]
    append(result,{0x48,0x8b,0x8c,0x24,static_cast<uint8_t>(producer?0xb0:0xb8),0,0,0});
    if (producer) append(result,{0x48,0x8b,0xd3}); // RDX=original RBX capture.
    else append(result,{0x48,0x8b,0xd7});           // RDX=original RDI capture.
    append(result,{0x41,0xb8,static_cast<uint8_t>(producer?1:0),0,0,0});
    append(result,{0x48,0xb8}); address(result,reinterpret_cast<uintptr_t>(&pump));
    append(result,{0xff,0xd0});
    append(result,{0x0f,0xae,0x94,0x24,0x80,0,0,0}); // ldmxcsr [rsp+80]
    for (uint8_t index=0; index<6; ++index)
        append(result,{0xf3,0x0f,0x6f,static_cast<uint8_t>(0x44+8*index),0x24,static_cast<uint8_t>(0x20+16*index)});
    append(result,{0x4c,0x8b,0x9c,0x24,0x88,0,0,0}); // saved R11
    append(result,{0x4c,0x8b,0x94,0x24,0x90,0,0,0}); // saved R10
    append(result,{0x4c,0x8b,0x8c,0x24,0x98,0,0,0}); // saved R9
    append(result,{0x4c,0x8b,0x84,0x24,0xa0,0,0,0}); // saved R8
    append(result,{0x48,0x8b,0x94,0x24,0xa8,0,0,0}); // saved RDX
    append(result,{0x48,0x8b,0x8c,0x24,0xb0,0,0,0}); // saved RCX
    append(result,{0x48,0x8b,0x84,0x24,0xb8,0,0,0}); // saved RAX
    append(result,{0x48,0x8d,0xa4,0x24,0xc0,0,0,0}); // RSP points at saved flags.
    gateway.flagsOffset=static_cast<uint32_t>(result.size());
    byte(result,0x9d);
    gateway.leafOffset=static_cast<uint32_t>(result.size());
    result.insert(result.end(),copied.begin(),copied.end());
    byte(result,0xc3);
    return gateway;
}

void writeUnwind(uint32_t offset, unsigned kind) {
    // Version1, no handler, no frame register. Volatile PUSHes consume stack
    // without saving nonvolatile register state; each is an8-byte allocation.
    uint8_t* out=code+offset;
    if (kind==0) { const uint8_t empty[]{1,0,0,0}; std::memcpy(out,empty,sizeof(empty)); return; }
    if (kind==8) { const uint8_t flags[]{1,0,1,0,0,2,0,0};std::memcpy(out,flags,sizeof(flags));return; }
    const uint8_t info[]{1,19,10,0, 19,1,17,0, // UWOP_ALLOC_LARGE136 at prologue end19.
        12,2,10,2,8,2,6,2,4,2,3,2,2,2,1,2}; // eight UWOP_ALLOC_SMALL8 push slots.
    std::memcpy(out,info,sizeof(info));
}
bool modify(Patch& patch, const uint8_t* bytes) {
    DWORD prior=0,ignored=0;
    if (!VirtualProtect(patch.address,patch.size,PAGE_EXECUTE_READWRITE,&prior)) return false;
    std::memcpy(patch.address,bytes,patch.size);
    const bool restored=VirtualProtect(patch.address,patch.size,prior,&ignored)!=0;
    return FlushInstructionCache(GetCurrentProcess(),patch.address,patch.size)!=0 && restored;
}
bool callPatch(Patch& patch, uintptr_t destination) {
    int32_t relative=0;
    if (!displacement(reinterpret_cast<uintptr_t>(patch.address),destination,relative)) return false;
    std::array<uint8_t,14> replacement{}; replacement.fill(0x90);
    replacement[0]=0xe8; std::memcpy(replacement.data()+1,&relative,sizeof(relative));
    patch.installed=true; // Retain restoration ownership even if cache/protection fails.
    return modify(patch,replacement.data());
}
bool restore() {
    bool ok=true;
    for (auto& patch:patches) if (patch.installed) {
        if (modify(patch,patch.original.data())) patch.installed=false; else ok=false;
    }
    return ok;
}
}

extern "C" __declspec(dllexport) int BAEnableCooperative(HMODULE native) {
    if (image || !native) return 1;
    image=native; owner=GetCurrentThreadId(); stats=Stats{}; stats.owner=owner;
    auto base=reinterpret_cast<uint8_t*>(native);
    const uint8_t serial[]{0x8d,0x56,0};
    if (std::memcmp(base+0x331b4,serial,sizeof(serial)) ||
        std::memcmp(base+kWaitCall,kWaitBytes.data(),kWaitBytes.size()) ||
        std::memcmp(base+kConsumer,kConsumerBytes.data(),kConsumerBytes.size()) ||
        std::memcmp(base+kProducer,kProducerBytes.data(),kProducerBytes.size())) {
        image=nullptr; fail(10); return 2;
    }
    patches[0].address=base+kWaitCall;patches[0].size=kWaitBytes.size();
    patches[1].address=base+kConsumer;patches[1].size=kConsumerBytes.size();
    patches[2].address=base+kProducer;patches[2].size=kProducerBytes.size();
    for (auto& patch:patches) std::memcpy(patch.original.data(),patch.address,patch.size);
    code=allocateNear(reinterpret_cast<uintptr_t>(base));
    if (!code) { image=nullptr;fail(11);return 3; }
    stats.codeBase=reinterpret_cast<uintptr_t>(code);
    std::vector<uint8_t> binding{0x48,0xb8};address(binding,reinterpret_cast<uintptr_t>(&boundWait));append(binding,{0xff,0xe0});
    const std::array<Gateway,3> gateways{{{binding,0,0},loopGateway(false,kConsumerBytes),loopGateway(true,kProducerBytes)}};
    const std::array<uint32_t,3> starts{{0,0x200,0x400}};
    size_t functionIndex=0;
    for (size_t index=0;index<gateways.size();++index) {
        const auto start=starts[index],unwind=static_cast<uint32_t>(0x2000+index*0x100);
        const auto& gateway=gateways[index];
        std::memcpy(code+start,gateway.bytes.data(),gateway.bytes.size());
        if (index==0) {
            writeUnwind(unwind,0);
            functions[functionIndex++]={start,static_cast<DWORD>(start+gateway.bytes.size()),unwind};
        } else {
            // Separate ranges describe exact RSP state rather than relying on
            // epilogue recognition across POPFQ and the copied native head.
            writeUnwind(unwind,200);writeUnwind(unwind+0x40,8);writeUnwind(unwind+0x80,0);
            functions[functionIndex++]={start,start+gateway.flagsOffset,unwind};
            functions[functionIndex++]={start+gateway.flagsOffset,start+gateway.leafOffset,unwind+0x40};
            functions[functionIndex++]={start+gateway.leafOffset,static_cast<DWORD>(start+gateway.bytes.size()),unwind+0x80};
        }
    }
    DWORD ignored=0;
    if (!VirtualProtect(code,kCodeSize,PAGE_EXECUTE_READ,&ignored) ||
        !FlushInstructionCache(GetCurrentProcess(),code,kCodeSize) ||
        !RtlAddFunctionTable(functions.data(),static_cast<DWORD>(functions.size()),reinterpret_cast<DWORD64>(code))) {
        VirtualFree(code,0,MEM_RELEASE);code=nullptr;image=nullptr;fail(12);return 4;
    }
    registered=true;
    for (size_t index=0;index<patches.size();++index)
        if (!callPatch(patches[index],reinterpret_cast<uintptr_t>(code+starts[index]))) {
            fail(13);
            if (restore()) { RtlDeleteFunctionTable(functions.data());registered=false;VirtualFree(code,0,MEM_RELEASE);code=nullptr;image=nullptr; }
            return 5;
        }
    return 0;
}

extern "C" __declspec(dllexport) unsigned BASizeOfCooperativeStats() { return static_cast<unsigned>(sizeof(Stats)); }
extern "C" __declspec(dllexport) int BAGetCooperativeStats(void* output) {
    if (!output) return 1;
    std::memcpy(output,&stats,sizeof(stats));return 0;
}
extern "C" __declspec(dllexport) int BADisableCooperative() {
    if (!image) return 0;
    if (!owned() || stats.depth) return 1;
    if (!restore()) {fail(14);return 2;}
    if (registered && !RtlDeleteFunctionTable(functions.data())) {fail(15);return 3;}
    registered=false;
    if (code && !VirtualFree(code,0,MEM_RELEASE)) {fail(16);return 4;}
    code=nullptr;pool=nullptr;image=nullptr;return 0;
}
