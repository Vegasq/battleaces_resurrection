#pragma once
#include <atomic>
#include <cstdint>
#include <cstring>
#include <mutex>

// Unintegrated, exact-build Windows x64 API proxy. No loading/patching, module
// selection, allocator lock, TLS registry or frame inference lives here. The
// integration owner routes ONLY its selected native module to lookup(), keeps
// module/callback contexts alive, and prevents every raw-export bypass.
// ABI source: client-checkpoint-activation.txt, exact wrapper ABI checklist.
// C++ exceptions are contained; SEH/native memory corruption is not suppressed.
namespace ba_native_api_proxy {
static_assert(sizeof(void*)==8 && sizeof(int)==4,"proxy requires Windows x64 ABI");
using Result=std::int32_t;
using LogCallback=void(__cdecl*)(std::int32_t,const char*);
using Resolver=std::uintptr_t(__cdecl*)(void* native_module,const char* exact_name);
struct Callbacks {
    void* context=nullptr;
    int(__cdecl* enter)(void*,const char*)=nullptr;
    void(__cdecl* leave)(void*,const char*)=nullptr;
};
struct Hooks {
    void* context=nullptr;
    int(__cdecl* before_process_msg)(void*,std::uint64_t,const std::uint8_t*,std::uint32_t)=nullptr;
    int(__cdecl* after_step)(void*,std::uint64_t,std::uint32_t,std::int32_t*,Result)=nullptr;
};

// Parameter order and pointer signedness are explicit even where original PE
// exports alias the same stub. ProcessMsg/Step have optional typed hooks below.
#define BA_NATIVE_API_PLAIN(X) \
 X(SimInit,(bool enabled),(enabled)) \
 X(SimDestroy,(),()) \
 X(SimSetLogCallBack,(LogCallback callback),(callback)) \
 X(SimSetLogFlags,(std::uint32_t flags),(flags)) \
 X(SimCreateWorld,(const std::uint8_t* data,std::uint32_t size,std::uint64_t* world),(data,size,world)) \
 X(SimDestroyWorld,(std::uint64_t world),(world)) \
 X(SimMakeSimFrame,(std::uint64_t world,std::uint32_t viewer,std::uint32_t* size),(world,viewer,size)) \
 X(SimGetSimFrameBuffer,(std::uint64_t world,void* buffer),(world,buffer)) \
 X(SimGetLabelsFrameBufferSize,(std::uint64_t world,std::uint32_t registry,std::uint32_t* size),(world,registry,size)) \
 X(SimGetLabelsFrameBuffer,(std::uint64_t world,std::uint32_t registry,void* buffer),(world,registry,buffer)) \
 X(SimGetConnectedPlayersSizeAndVersion,(std::uint64_t world,std::int32_t* size,std::int32_t* version),(world,size,version)) \
 X(SimGetConnectedPlayers,(std::uint64_t world,void* buffer),(world,buffer)) \
 X(SimGetMapFrameSize,(std::uint64_t world,std::int32_t* size),(world,size)) \
 X(SimGetMapFrame,(std::uint64_t world,void* buffer),(world,buffer)) \
 X(SimCrashOnCommand,(),()) \
 X(SimGetDebugDrawCommandBufferCount,(std::uint64_t world,std::uint32_t* count),(world,count)) \
 X(SimGetDebugDrawCommandBufferSize,(std::uint64_t world,std::uint32_t* size,std::uint32_t index),(world,size,index)) \
 X(SimGetDebugDrawCommandBuffer,(std::uint64_t world,void* buffer,std::uint32_t index),(world,buffer,index)) \
 X(SimClearAllDebugDrawCommandBuffers,(std::uint64_t world),(world)) \
 X(SimSetDebugDrawCommandListsActive,(std::uint64_t world,std::uint32_t count,const std::int32_t* lists),(world,count,lists)) \
 X(SimGetSystemCount,(std::uint64_t world,std::uint32_t* count),(world,count)) \
 X(SimGetSystemIDAttributes,(std::uint64_t world,void* array,std::uint32_t count),(world,array,count))

namespace types {
#define BA_NATIVE_API_TYPE(Name,Args,Call) using Name=Result(__cdecl*)Args;
BA_NATIVE_API_PLAIN(BA_NATIVE_API_TYPE)
#undef BA_NATIVE_API_TYPE
using SimProcessMsg=Result(__cdecl*)(std::uint64_t,const std::uint8_t*,std::uint32_t);
using SimStep=Result(__cdecl*)(std::uint64_t,std::uint32_t,std::int32_t*);
}
namespace detail {
struct Originals {
#define BA_NATIVE_API_FIELD(Name,Args,Call) types::Name Name=nullptr;
BA_NATIVE_API_PLAIN(BA_NATIVE_API_FIELD)
#undef BA_NATIVE_API_FIELD
    types::SimProcessMsg SimProcessMsg=nullptr;
    types::SimStep SimStep=nullptr;
};
struct Binding {void* module=nullptr;Originals originals;Callbacks callbacks;Hooks hooks;};
inline Binding storage;
inline std::atomic<const Binding*> binding{nullptr};
inline std::mutex binding_mutex;

class Scope {
public:
    Scope(const Binding& selected,const char* name):callbacks_(selected.callbacks),name_(name) {
        // Failed/thrown enter MUST undo its own partial acquisition. Only an
        // enter returning0 owns a matching leave, including nested callbacks.
        entered_=callbacks_.enter(callbacks_.context,name_)==0;
    }
    Scope(const Scope&)=delete;Scope& operator=(const Scope&)=delete;
    ~Scope()noexcept{finish();}
    bool entered()const noexcept{return entered_;}
    bool finish()noexcept {
        if(entered_) {
            entered_=false; // Disarm before callback; exceptions cannot double-leave.
            try{callbacks_.leave(callbacks_.context,name_);}catch(...){failed_=true;}
        }
        return !failed_;
    }
private:
    Callbacks callbacks_;
    const char* name_;
    bool entered_=false,failed_=false;
};
template<class Call>inline Result invoke(const char* name,Call&& call)noexcept {
    const auto* selected=binding.load(std::memory_order_acquire);
    if(!selected)return -1;
    try {
        Scope scope(*selected,name);
        if(!scope.entered())return -1;
        const Result result=call(*selected);
        return scope.finish()?result:-1;
    }catch(...){return -1;} // Scope leaves once before exceptions reach here.
}
}

// One immutable successful binding per process/module lifetime. Missing exports
// or resolver exceptions publish nothing. Binding itself runs no native API.
// Contexts and native module must outlive every returned function pointer.
inline int bind(void* native_module,Resolver resolver,Callbacks callbacks,Hooks hooks={})noexcept {
    if(!native_module || !resolver || !callbacks.enter || !callbacks.leave)return -1;
    try {
        std::lock_guard<std::mutex> lock(detail::binding_mutex);
        if(detail::binding.load(std::memory_order_relaxed))return -1;
        detail::Binding candidate;candidate.module=native_module;candidate.callbacks=callbacks;candidate.hooks=hooks;
#define BA_NATIVE_API_RESOLVE(Name,Args,Call) \
        {const auto address=resolver(native_module,#Name);if(!address)return -1; \
         candidate.originals.Name=reinterpret_cast<types::Name>(address);}
        BA_NATIVE_API_PLAIN(BA_NATIVE_API_RESOLVE)
        BA_NATIVE_API_RESOLVE(SimProcessMsg,(),())
        BA_NATIVE_API_RESOLVE(SimStep,(),())
#undef BA_NATIVE_API_RESOLVE
        detail::storage=candidate;
        detail::binding.store(&detail::storage,std::memory_order_release);return 0;
    }catch(...){return -1;}
}
inline void* module()noexcept {
    const auto* selected=detail::binding.load(std::memory_order_acquire);return selected?selected->module:nullptr;
}

#define BA_NATIVE_API_WRAPPER(Name,Args,Call) \
extern "C" inline Result __cdecl BAProxy##Name Args noexcept { \
    return detail::invoke(#Name,[&](const detail::Binding& selected){return selected.originals.Name Call;}); \
}
BA_NATIVE_API_PLAIN(BA_NATIVE_API_WRAPPER)
#undef BA_NATIVE_API_WRAPPER
extern "C" inline Result __cdecl BAProxySimProcessMsg(std::uint64_t world,const std::uint8_t* data,std::uint32_t size)noexcept {
    return detail::invoke("SimProcessMsg",[&](const detail::Binding& selected)->Result {
        if(selected.hooks.before_process_msg &&
           selected.hooks.before_process_msg(selected.hooks.context,world,data,size)!=0)return -1;
        return selected.originals.SimProcessMsg(world,data,size);
    });
}
extern "C" inline Result __cdecl BAProxySimStep(std::uint64_t world,std::uint32_t dt,std::int32_t* current)noexcept {
    return detail::invoke("SimStep",[&](const detail::Binding& selected)->Result {
        const Result result=selected.originals.SimStep(world,dt,current);
        // Raw native output pointer/result are forwarded without dereference or
        // frame inference, even for a native error. A hook decides its policy.
        if(selected.hooks.after_step &&
           selected.hooks.after_step(selected.hooks.context,world,dt,current,result)!=0)return -1;
        return result;
    });
}
// Exact raw PE export names only. Unrecovered SimMakeSimDebugInfoFrame and
// SimGetSimDebugInfoFrameBuffer intentionally return0 despite shared stub RVAs.
// No ordinal/alias/case/whitespace fallback is provided for the selected module.
inline std::uintptr_t lookup(const char* exact_name)noexcept {
    // Windows GetProcAddress encodes ordinals in pointer values1..65535; do
    // not dereference them as text even if a caller accidentally forwards one.
    if(reinterpret_cast<std::uintptr_t>(exact_name)<=0xffff ||
       !detail::binding.load(std::memory_order_acquire))return 0;
#define BA_NATIVE_API_LOOKUP(Name,Args,Call) \
    if(std::strcmp(exact_name,#Name)==0)return reinterpret_cast<std::uintptr_t>(&BAProxy##Name);
    BA_NATIVE_API_PLAIN(BA_NATIVE_API_LOOKUP)
    BA_NATIVE_API_LOOKUP(SimProcessMsg,(),())
    BA_NATIVE_API_LOOKUP(SimStep,(),())
#undef BA_NATIVE_API_LOOKUP
    return 0;
}
#undef BA_NATIVE_API_PLAIN
}
