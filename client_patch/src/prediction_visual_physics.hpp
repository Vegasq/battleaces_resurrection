#pragma once
// Exact shipped UnityPlayer registration: Physics::SyncTransforms ->1771f0
// ->6d8c80. No MethodInfo, autoSync policy setter, or simulation advance.
// Include after actor repair. Both production batches and the opt-in causal
// diagnostic use this same guarded original void() icall binding.
namespace ba_prediction_visual_physics {
static void require(bool value,const char* why){ba_prediction_actors::require(value,why);}
struct Module {
    uintptr_t base=0;
    void (*sync)()=nullptr;
};
static Module resolve() {
    Module result;result.base=reinterpret_cast<uintptr_t>(GetModuleHandleW(L"UnityPlayer.dll"));
    require(result.base!=0,"visual sync loaded UnityPlayer is missing");
    const auto* dos=reinterpret_cast<const IMAGE_DOS_HEADER*>(result.base);
    require(dos->e_magic==IMAGE_DOS_SIGNATURE&&dos->e_lfanew==0x148,"visual sync loaded UnityPlayer DOS identity differs");
    const auto* nt=reinterpret_cast<const IMAGE_NT_HEADERS64*>(result.base+0x148);
    require(nt->Signature==IMAGE_NT_SIGNATURE&&nt->FileHeader.Machine==IMAGE_FILE_MACHINE_AMD64&&
        nt->FileHeader.NumberOfSections==8&&nt->FileHeader.TimeDateStamp==0x66a03c5f&&
        nt->OptionalHeader.Magic==IMAGE_NT_OPTIONAL_HDR64_MAGIC&&nt->OptionalHeader.SizeOfImage==0x1e58000,
        "visual sync loaded UnityPlayer PE identity differs");
    const auto target=ba::api<void*(*)(const char*)>("il2cpp_resolve_icall")("UnityEngine.Physics::SyncTransforms");
    require(reinterpret_cast<uintptr_t>(target)==result.base+0x1771f0,"visual sync registered engine icall target differs");
    MEMORY_BASIC_INFORMATION memory{};
    require(VirtualQuery(target,&memory,sizeof(memory))==sizeof(memory)&&memory.AllocationBase==reinterpret_cast<void*>(result.base)&&
        memory.State==MEM_COMMIT&&!(memory.Protect&(PAGE_GUARD|PAGE_NOACCESS))&&
        (memory.Protect&(PAGE_EXECUTE|PAGE_EXECUTE_READ|PAGE_EXECUTE_READWRITE|PAGE_EXECUTE_WRITECOPY)),
        "visual sync registered engine target is not executable in UnityPlayer");
    require(std::memcmp(target,"\xe9\x8b\x1a\x56\x00",5)==0&&
        std::memcmp(reinterpret_cast<const void*>(result.base+0x6d8c80),
            "\x4c\x8b\xdc\x53\x55\x56\x57\x48\x83\xec\x78\x8b\x0d\x6f\xd0\x53",16)==0&&
        std::memcmp(reinterpret_cast<const void*>(result.base+0x6d8f9d),"\x48\x83\xc4\x78\x5f\x5e\x5d\x5b\xc3",9)==0,
        "visual sync registered engine instructions differ");
    result.sync=reinterpret_cast<void(*)()>(target);return result;
}
inline Module checked() {
    // UnityPlayer is a process-lifetime engine module. Cache resolution but
    // refuse a module replacement or changed target bytes before each batch.
    static const Module value=resolve();
    require(reinterpret_cast<uintptr_t>(GetModuleHandleW(L"UnityPlayer.dll"))==value.base&&
        std::memcmp(reinterpret_cast<const void*>(value.base+0x1771f0),"\xe9\x8b\x1a\x56\x00",5)==0&&
        std::memcmp(reinterpret_cast<const void*>(value.base+0x6d8c80),
            "\x4c\x8b\xdc\x53\x55\x56\x57\x48\x83\xec\x78\x8b\x0d\x6f\xd0\x53",16)==0&&
        std::memcmp(reinterpret_cast<const void*>(value.base+0x6d8f9d),"\x48\x83\xc4\x78\x5f\x5e\x5d\x5b\xc3",9)==0,
        "visual physics loaded engine binding changed");
    return value;
}
}
