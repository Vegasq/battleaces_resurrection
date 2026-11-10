#pragma once
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <array>
#include <cstdint>
#include <cstring>
#include <limits>

// Exact-build entry detours into ordinary compiled C++ shims. The caller owns
// serialization, image/provenance, owner thread and original module lifetime.
// Like cooperative.cpp, generated code has registered Win64 unwind metadata.
// No destructor unpatches/frees code: DLL detach/loader lock is not a safe native
// teardown boundary. Explicit disable() is only for a known quiescent owner.
namespace ba_entity_guard {
class Hooks {
public:
    static constexpr size_t createRva=0x37b70,hintRva=0x379b0,codeSize=0x10000;
    inline static constexpr std::array<uint8_t,11> createPrefix{{
        0x48,0x83,0xec,0x28,0x44,0x8b,0x81,0xc0,0,0,0}};
    inline static constexpr std::array<uint8_t,13> hintPrefix{{
        0x40,0x56,0x57,0x41,0x54,0x41,0x56,0x41,0x57,0x48,0x83,0xec,0x20}};
    Hooks()=default;
    Hooks(const Hooks&)=delete;Hooks& operator=(const Hooks&)=delete;
    ~Hooks()=default;
    bool install(uint8_t* image,size_t imageBytes,void* createShim,void* hintShim) noexcept {
        if(code_ || !image || !createShim || !hintShim || imageBytes<hintRva+hintPrefix.size())return false;
        if(std::memcmp(image+createRva,createPrefix.data(),createPrefix.size()) ||
           std::memcmp(image+hintRva,hintPrefix.data(),hintPrefix.size()))return false;
        patches_[0].address=image+createRva;patches_[0].size=createPrefix.size();
        patches_[1].address=image+hintRva;patches_[1].size=5;
        for(auto& p:patches_)std::memcpy(p.original.data(),p.address,p.size);
        code_=allocateNear(reinterpret_cast<uintptr_t>(image));if(!code_)return false;
        // Leaf absolute indirect jumps preserve all registers, including RAX.
        jump(code_,createShim);jump(code_+0x200,hintShim);
        std::memcpy(code_+0x100,createPrefix.data(),createPrefix.size());
        continuation(code_+0x100+createPrefix.size(),image+createRva+createPrefix.size());
        std::memcpy(code_+0x300,hintPrefix.data(),5);
        continuation(code_+0x305,image+hintRva+5);
        const uint8_t leaf[]{1,0,0,0};
        const uint8_t createUnwind[]{1,4,1,0,4,0x42,0,0}; // ALLOC_SMALL40, subrsp28 endsat4.
        const uint8_t hintUnwind[]{1,5,3,0,5,0xc0,3,0x70,2,0x60,0,0}; // R12/RDI/RSI.
        std::memcpy(code_+0x2000,leaf,sizeof(leaf));
        std::memcpy(code_+0x2010,createUnwind,sizeof(createUnwind));
        std::memcpy(code_+0x2020,hintUnwind,sizeof(hintUnwind));
        functions_={{{0,14,0x2000},{0x100,0x118,0x2010},
                     {0x200,0x20e,0x2000},{0x300,0x312,0x2020}}};
        DWORD prior=0;
        if(!VirtualProtect(code_,codeSize,PAGE_EXECUTE_READ,&prior) ||
           !FlushInstructionCache(GetCurrentProcess(),code_,codeSize))return false;
        if(!RtlAddFunctionTable(functions_.data(),static_cast<DWORD>(functions_.size()),
                                reinterpret_cast<DWORD64>(code_)))return false;
        registered_=true;
        // Publish original trampolines before either entry can call its shim.
        for(size_t index=0;index<patches_.size();++index) {
            auto& p=patches_[index];
            const auto destination=reinterpret_cast<uintptr_t>(code_+(index?0x200:0));
            const auto delta=static_cast<int64_t>(destination)-
                static_cast<int64_t>(reinterpret_cast<uintptr_t>(p.address)+5);
            if(delta<(std::numeric_limits<int32_t>::min)() || delta>(std::numeric_limits<int32_t>::max)())return false;
            std::array<uint8_t,11> replacement{};replacement.fill(0x90);replacement[0]=0xe9;
            const auto relative=static_cast<int32_t>(delta);std::memcpy(replacement.data()+1,&relative,4);
            p.installed=true; // Retain restoration ownership even if protection/cache fails.
            if(!modify(p,replacement.data()))return false;
        }
        installed_=true;return true;
    }
    bool disable() noexcept {
        bool ok=true;
        for(auto& p:patches_)if(p.installed) {
            if(modify(p,p.original.data()))p.installed=false;else ok=false;
        }
        if(!ok)return false;
        installed_=false;
        if(registered_) {
            if(!RtlDeleteFunctionTable(functions_.data()))return false;
            registered_=false;
        }
        if(code_) {if(!VirtualFree(code_,0,MEM_RELEASE))return false;code_=nullptr;}
        return true;
    }
    void* createOriginal()const noexcept{return code_?code_+0x100:nullptr;}
    void* hintOriginal()const noexcept{return code_?code_+0x300:nullptr;}
    uintptr_t codeBase()const noexcept{return reinterpret_cast<uintptr_t>(code_);}
    bool installed()const noexcept{return installed_;}
private:
    struct Patch {uint8_t* address=nullptr;size_t size=0;std::array<uint8_t,11> original{};bool installed=false;};
    static void jump(uint8_t* out,const void* target) noexcept {
        const uint8_t instruction[]{0xff,0x25,0,0,0,0};std::memcpy(out,instruction,6);
        const auto address=reinterpret_cast<uintptr_t>(target);std::memcpy(out+6,&address,8);
    }
    static void continuation(uint8_t* out,const void* target) noexcept {
        // FF25 would be recognized as an epilogue even though the copied
        // prologue still owns its stack/nonvolatile saves. JMP R11 (ModRM11)
        // is outside that Win64 epilogue form. R11 is volatile, is not a
        // parameter in either guarded native signature, and RAX stays intact.
        out[0]=0x49;out[1]=0xbb;
        const auto address=reinterpret_cast<uintptr_t>(target);std::memcpy(out+2,&address,8);
        out[10]=0x41;out[11]=0xff;out[12]=0xe3;
    }
    static bool modify(Patch& p,const uint8_t* bytes) noexcept {
        DWORD prior=0,ignored=0;
        if(!VirtualProtect(p.address,p.size,PAGE_EXECUTE_READWRITE,&prior))return false;
        std::memcpy(p.address,bytes,p.size);
        const bool restored=VirtualProtect(p.address,p.size,prior,&ignored)!=0;
        return FlushInstructionCache(GetCurrentProcess(),p.address,p.size)!=0 && restored;
    }
    static uint8_t* allocateNear(uintptr_t target) noexcept {
        SYSTEM_INFO info{};GetSystemInfo(&info);
        const auto granularity=static_cast<uintptr_t>(info.dwAllocationGranularity);
        const auto aligned=target&~(granularity-1);
        for(uintptr_t distance=0;distance<0x70000000;distance+=granularity) {
            for(unsigned direction=0;direction<2;++direction) {
                if(direction && aligned<distance+granularity)continue;
                if(!direction && aligned>(std::numeric_limits<uintptr_t>::max)()-distance)continue;
                const auto candidate=direction?aligned-distance:aligned+distance;
                auto memory=static_cast<uint8_t*>(VirtualAlloc(reinterpret_cast<void*>(candidate),codeSize,
                    MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE));
                if(memory)return memory;
            }
        }
        return nullptr;
    }
    uint8_t* code_=nullptr;
    bool registered_=false,installed_=false;
    std::array<Patch,2> patches_{};
    std::array<RUNTIME_FUNCTION,4> functions_{};
};
}
