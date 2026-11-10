// Authored allocations/headers only. Never load Simulation.dll or call native
// simulation code. Including the implementation exercises the real owned-range
// checks, including MSVC's manually aligned vector allocation convention.
#include "arena.cpp"
#include <cstdio>
#include <stdexcept>

namespace entity_guard_arena_test {
void require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
using Error=ba_entity_guard::Error;
void run() {
    require(BAInitialize()==0,"authored arena initialization");
    image=reinterpret_cast<HMODULE>(uintptr_t(0x180000000)); // Comparison value only; never dereferenced.
    auto world=static_cast<uint8_t*>(allocate(0x22c68,HEAP_ZERO_MEMORY));
    require(world!=nullptr,"owned authored world allocation");
    *reinterpret_cast<uint64_t*>(world)=reinterpret_cast<uint64_t>(image)+0x387860;
    auto registry=world+0x22a08;
    const auto header=[registry](uintptr_t begin,uintptr_t end,uintptr_t capacity,uint32_t head) {
        auto fields=reinterpret_cast<uintptr_t*>(registry+0xa8);
        fields[0]=begin;fields[1]=end;fields[2]=capacity;
        *reinterpret_cast<uint32_t*>(registry+0xc0)=head;
    };
    header(0,0,0,0xffffffff);require(entityStorageError(registry)==Error::None,"empty owned world");
    auto direct=static_cast<uint8_t*>(allocate(64,0));require(direct!=nullptr,"direct allocation");
    const auto begin=reinterpret_cast<uintptr_t>(direct);
    header(begin,begin+16,begin+64,0xffffffff);
    require(entityStorageError(registry)==Error::None,"direct owned vector refused");
    header(begin,begin+16,begin+68,0xffffffff);
    require(entityStorageError(registry)==Error::Storage,"vector crossed requested allocation");
    header(1,5,9,0xffffffff);require(entityStorageError(registry)==Error::Storage,"foreign low pointer");
    const auto uncommitted=reinterpret_cast<uintptr_t>(arena)+committed+4096;
    header(uncommitted,uncommitted+4,uncommitted+4,0xffffffff);
    require(entityStorageError(registry)==Error::Storage,"uncommitted pointer dereferenced/admitted");
    auto alignedRaw=static_cast<uint8_t*>(allocate(8192+39,0));require(alignedRaw!=nullptr,"aligned allocation");
    const auto raw=reinterpret_cast<uintptr_t>(alignedRaw),aligned=(raw+39)&~uintptr_t(31);
    *reinterpret_cast<uintptr_t*>(aligned-8)=raw;
    header(aligned,aligned+16,aligned+8192,0xffffffff);
    require(entityStorageError(registry)==Error::None,"owned manually aligned vector refused");
    *reinterpret_cast<uintptr_t*>(aligned-8)=1;
    require(entityStorageError(registry)==Error::Storage,"foreign alignment backup admitted");
    *reinterpret_cast<uintptr_t*>(aligned-8)=raw;
    header(aligned,aligned+16,aligned+8192+40,0xffffffff);
    require(entityStorageError(registry)==Error::Storage,"aligned vector crossed allocation");
    require(release(block(alignedRaw)),"release aligned fixture");
    header(aligned,aligned+16,aligned+8192,0xffffffff);
    require(entityStorageError(registry)==Error::Storage,"freed aligned vector admitted");
    constexpr uint64_t limit=0xfffff;
    auto large=static_cast<uint8_t*>(allocate(4*limit+39,0));require(large!=nullptr,"index-limit fixture allocation");
    const auto largeRaw=reinterpret_cast<uintptr_t>(large),largeBegin=(largeRaw+39)&~uintptr_t(31);
    *reinterpret_cast<uintptr_t*>(largeBegin-8)=largeRaw;
    header(largeBegin,largeBegin+4*(limit-1),largeBegin+4*limit,0xffffffff);
    require(entityStorageError(registry)==Error::None,"last valid actual owned index refused");
    header(largeBegin,largeBegin+4*limit,largeBegin+4*limit,0xffffffff);
    require(entityStorageError(registry)==Error::IndexLimit,"actual owned reserved index admitted");
    header(largeBegin,largeBegin+4*limit,largeBegin+4*limit,0xfff00001);
    require(entityStorageError(registry)==Error::None,"actual owned slot reuse at ceiling refused");
    *reinterpret_cast<uint64_t*>(world)=0;
    require(entityStorageError(registry)==Error::Storage,"wrong world vtable admitted");
    *reinterpret_cast<uint64_t*>(world)=reinterpret_cast<uint64_t>(image)+0x387860;
    require(entityStorageError(registry+1)==Error::Storage,"interior non-world pointer admitted");
    auto shortWorld=static_cast<uint8_t*>(allocate(64,HEAP_ZERO_MEMORY));
    require(shortWorld && entityStorageError(shortWorld+0x22a08)==Error::Storage,"short world header read/admitted");
    image=nullptr;pages.reset();require(VirtualFree(arena,0,MEM_RELEASE)!=0,"owned arena release");arena=nullptr;
}
}
int main() {
    try{entity_guard_arena_test::run();std::puts("PASS:15 authored owned-arena storage/cap/world/alignment controls;no original DLL loaded");return 0;}
    catch(const std::exception& error){std::fprintf(stderr,"FAIL:%s\n",error.what());return 1;}
}
