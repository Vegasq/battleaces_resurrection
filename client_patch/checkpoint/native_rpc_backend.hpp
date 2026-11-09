#pragma once
#include "native_api_proxy.hpp"
#include "native_worker_wire.hpp"
#include <atomic>
#include <cstring>
#include <map>
#include <mutex>
#include <string>
#include <tuple>
#include <type_traits>
#include <utility>

// Isolated remote implementations of the24 recovered native ABIs. Compose
// resolver with native_api_proxy::bind; the caller owns module routing, the
// recursive API gate, ordered/terminal transport, framing and process lifetime.
// No original native function or process-local pointer crosses this boundary.
// Get has no capacity argument in its original ABI: caller storage MUST cover
// the advertised size. Copies here never exceed the verified response count.
namespace ba_native_rpc_backend {
namespace wire=ba_native_worker_wire;
using Bytes=wire::Bytes;using Response=wire::Response;using Result=std::int32_t;
using LogCallback=ba_native_api_proxy::LogCallback;
using Request=bool(__cdecl*)(void*,std::uint8_t,const Bytes&,Response&);
inline constexpr std::size_t maxBuffer=16U*1024U*1024U,maxSystems=2048,systemRecordBytes=128;
struct Limits {std::size_t max_cached_pairs=128,max_cached_bytes=32U*1024U*1024U;};
struct CacheStats {std::size_t pairs=0,bytes=0;};
namespace detail {
inline void require(bool value,const char* message){if(!value)throw wire::ProtocolError(message);}
struct Config {void* module=nullptr;Request request=nullptr;void* context=nullptr;Limits limits;};
inline Config storage;
inline std::atomic<const Config*> config{nullptr};
inline std::mutex configuration_mutex;
inline std::atomic<LogCallback> callback{nullptr};
enum class Kind:std::uint8_t {Frame,Labels,Players,Map,Debug};
struct Key {
    std::uint64_t thread,world;Kind kind;std::uint32_t selector;
    bool operator<(const Key& other)const{return std::tie(thread,world,kind,selector)<std::tie(other.thread,other.world,other.kind,other.selector);}
};
struct Cached {std::int64_t size;Result get_result;Bytes bytes;};
inline std::map<Key,Cached> cache;
inline std::size_t cached_bytes=0;
inline std::mutex cache_mutex;
inline std::atomic<std::uint64_t> next_thread{1};
inline Key key(std::uint64_t world,Kind kind,std::uint32_t selector=0) {
    // OS/thread IDs may be reused after a rematch. Tokens never make another
    // thread's abandoned pair eligible; successful world/session close prunes it.
    static thread_local const auto token=next_thread.fetch_add(1,std::memory_order_relaxed);
    require(token!=0,"RPC caller token exhausted");return {token,world,kind,selector};
}
inline Result signed32(std::uint32_t value){Result result;std::memcpy(&result,&value,4);return result;}
inline void validate_logs(const std::vector<wire::Log>& logs,std::size_t data_bytes=0) {
    require(logs.size()<=wire::maxLogs && data_bytes<=wire::maxPayload-8,"RPC response/log cap");
    std::size_t total=8+data_bytes;
    for(const auto& log:logs) {
        require(log.text.size()<=wire::maxLogBytes && wire::utf8(log.text),"RPC log UTF8/length");
        require(total<=wire::maxPayload-8-log.text.size(),"RPC response envelope exceeds cap");total+=8+log.text.size();
    }
}
inline int deliver_logs(const std::vector<wire::Log>& logs)noexcept {
    try {
        validate_logs(logs);
        for(const auto& log:logs)if(const auto target=callback.load(std::memory_order_acquire)) {
            const std::string text(log.text.begin(),log.text.end());target(log.kind,text.c_str());
        }
        return 0;
    }catch(...){return -1;}
}
inline Response transact(const Config& selected,std::uint8_t opcode,const Bytes& body) {
    require(body.size()<=wire::maxPayload,"RPC request exceeds cap");Response out;
    require(selected.request(selected.context,opcode,body,out),"RPC transport failed");
    validate_logs(out.logs,out.data.size());return out;
}
inline Result finish(const Response& out)noexcept{return deliver_logs(out.logs)==0?out.result:-1;}
template<class Call>inline Result invoke(Call&& call)noexcept {
    const auto* selected=config.load(std::memory_order_acquire);if(!selected)return -1;
    try{return call(*selected);}catch(...){return -1;}
}
inline void append_raw(Bytes& out,const void* source,std::size_t count) {
    require(out.size()<=wire::maxPayload && count<=wire::maxPayload-out.size(),"RPC request byte cap");
    require(!count || source,"RPC null source");
    if(count){const auto* first=static_cast<const std::uint8_t*>(source);out.insert(out.end(),first,first+count);}
}
inline Bytes world_body(std::uint64_t world){Bytes out;wire::append64(out,world);return out;}
inline void exact(const Response& out,std::size_t count){require(out.data.size()==count,"RPC response byte count differs");}
inline void prepare_pair(const Key& selected,const Limits& limits) {
    std::lock_guard<std::mutex> lock(cache_mutex);const auto found=cache.find(selected);
    if(found!=cache.end()){cached_bytes-=found->second.bytes.size();cache.erase(found);}
    require(cache.size()<limits.max_cached_pairs,"RPC pair capacity reached");
}
inline void stash(const Key& selected,Cached value,const Limits& limits) {
    std::lock_guard<std::mutex> lock(cache_mutex);
    // A nested callback may have completed a same-key Make. The completing
    // outer Make replaces that pair, matching its own eventual advertised size.
    const auto found=cache.find(selected);
    const auto old=found==cache.end()?0:found->second.bytes.size();
    require(found!=cache.end() || cache.size()<limits.max_cached_pairs,"RPC pair capacity reached");
    require(cached_bytes>=old && cached_bytes-old<=limits.max_cached_bytes &&
            value.bytes.size()<=limits.max_cached_bytes-(cached_bytes-old),"RPC cache byte capacity reached");
    if(found!=cache.end()){found->second=std::move(value);cached_bytes=cached_bytes-old+found->second.bytes.size();}
    else {const auto bytes=value.bytes.size();cache.emplace(selected,std::move(value));cached_bytes+=bytes;}
}
inline void clear_world(std::uint64_t world) {
    std::lock_guard<std::mutex> lock(cache_mutex);
    for(auto found=cache.begin();found!=cache.end();) {
        if(found->first.world==world) {
            cached_bytes-=found->second.bytes.size();found=cache.erase(found);
        }else ++found;
    }
}
inline void clear_all(){std::lock_guard<std::mutex> lock(cache_mutex);cache.clear();cached_bytes=0;}
inline Result get(std::uint64_t world,Kind kind,void* destination,std::uint32_t selector=0) {
    const auto selected=key(world,kind,selector);std::lock_guard<std::mutex> lock(cache_mutex);
    const auto found=cache.find(selected);if(found==cache.end())return -1;const auto& value=found->second;
    if(value.get_result==0) {
        require(value.size>=0 && static_cast<std::uint64_t>(value.size)<=maxBuffer &&
                value.bytes.size()==static_cast<std::size_t>(value.size),"RPC cached byte count differs");
        if(!value.bytes.empty() && !destination)return -1; // No successful read yet; retain for a valid destination.
        if(!value.bytes.empty())std::memcpy(destination,value.bytes.data(),value.bytes.size());
    }else require(value.bytes.empty(),"RPC failed Get contains bytes");
    const Result result=value.get_result;cached_bytes-=value.bytes.size();cache.erase(found);return result;
}
template<class Size>inline Result paired(const Config& selected,std::uint8_t opcode,Bytes body,
                                       std::uint64_t world,Kind kind,Size* size,std::uint32_t selector=0,
                                       std::int32_t* version=nullptr) {
    require(size,"RPC null size output");const Size seed=*size;const auto selected_key=key(world,kind,selector);
    if(kind!=Kind::Debug)prepare_pair(selected_key,selected.limits);
    auto out=transact(selected,opcode,body);std::size_t at=0;
    const auto bits=wire::read32(out.data,at);Size new_size;
    if constexpr(std::is_same_v<Size,std::int32_t>)new_size=signed32(bits);else new_size=bits;
    std::int32_t new_version=0;if(version)new_version=signed32(wire::read32(out.data,at));
    const Result get_result=signed32(wire::read32(out.data,at));const auto length=wire::read32(out.data,at);
    require(length<=maxBuffer && length==out.data.size()-at,"RPC pair payload length differs");
    const auto size64=static_cast<std::int64_t>(new_size);
    if(kind==Kind::Debug) {
        // Exact-build debug exports alias the verified no-write stub. Never
        // allocate/fabricate sizeSeed bytes or change a caller destination.
        require(out.result==8 && get_result==8 && new_size==seed && length==0,"RPC debug no-write contract differs");
        return finish(out); // No output write or cache pressure for this stub.
    }else if(out.result!=0)require(get_result==-1 && length==0,"failed RPC Make executed Get");
    else {
        require(size64>=0 && static_cast<std::uint64_t>(size64)<=maxBuffer,"successful RPC size exceeds cap");
        require(get_result==0?length==static_cast<std::uint64_t>(size64):length==0,"RPC Get result/size differs");
    }
    Cached value{size64,get_result,Bytes(out.data.begin()+at,out.data.end())};
    // Reentrant log queries may Make/Get their own pair. Publish this outer
    // pair only after callbacks finish so its advertised byte count cannot be
    // replaced between writing size and returning to its allocating caller.
    if(deliver_logs(out.logs)!=0)return -1;
    stash(selected_key,std::move(value),selected.limits);*size=new_size;if(version)*version=new_version;return out.result;
}
inline Result plain(const Config& selected,std::uint8_t opcode,const Bytes& body) {
    const auto out=transact(selected,opcode,body);exact(out,0);return finish(out);
}
inline Result unsigned_count(const Config& selected,std::uint8_t opcode,std::uint64_t world,std::uint32_t* count,bool systems) {
    require(count,"RPC null count output");const auto seed=*count;auto body=world_body(world);wire::append32(body,seed);
    const auto out=transact(selected,opcode,body);exact(out,4);std::size_t at=0;const auto value=wire::read32(out.data,at);
    if(opcode==18){require(out.result==8 && value==seed,"RPC debug count no-write contract differs");return finish(out);}
    require(!systems || out.result!=0 || value<=maxSystems,"RPC successful system count exceeds cap");*count=value;return finish(out);
}
}

inline int initialize(void* native_module,Request request,void* context,Limits limits={})noexcept {
    if(!native_module || !request || limits.max_cached_pairs<1 || limits.max_cached_pairs>256 ||
       limits.max_cached_bytes<1 || limits.max_cached_bytes>32U*1024U*1024U)return -1;
    try {
        std::lock_guard<std::mutex> lock(detail::configuration_mutex);
        if(detail::config.load(std::memory_order_relaxed))return -1;
        detail::storage={native_module,request,context,limits};detail::config.store(&detail::storage,std::memory_order_release);return 0;
    }catch(...){return -1;}
}
inline LogCallback retained_callback()noexcept{return detail::callback.load(std::memory_order_acquire);}
// Ordinary shims ALREADY dispatch each response's logs exactly once. This
// helper is for an explicit external decoded-log source, never duplicate replay.
inline int dispatch_logs(const std::vector<wire::Log>& logs)noexcept{return detail::deliver_logs(logs);}
inline CacheStats cache_stats(){std::lock_guard<std::mutex> lock(detail::cache_mutex);return {detail::cache.size(),detail::cached_bytes};}

extern "C" inline Result __cdecl BARpcSimInit(bool enabled)noexcept {
    return detail::invoke([&](const detail::Config& c){return detail::plain(c,1,Bytes{static_cast<std::uint8_t>(enabled)});});
}
extern "C" inline Result __cdecl BARpcSimDestroy()noexcept {
    return detail::invoke([](const detail::Config& c){const auto out=detail::transact(c,2,{});detail::exact(out,0);
        if(out.result==0)detail::clear_all();const Result result=detail::finish(out);
        if(out.result==0)detail::callback.store(nullptr,std::memory_order_release);return result;});
}
extern "C" inline Result __cdecl BARpcSimSetLogCallBack(LogCallback callback)noexcept {
    return detail::invoke([&](const detail::Config& c){const auto out=detail::transact(c,3,Bytes{static_cast<std::uint8_t>(callback!=nullptr)});
        detail::exact(out,0);if(out.result==0)detail::callback.store(callback,std::memory_order_release);return detail::finish(out);});
}
extern "C" inline Result __cdecl BARpcSimSetLogFlags(std::uint32_t flags)noexcept {
    return detail::invoke([&](const detail::Config& c){Bytes body;wire::append32(body,flags);return detail::plain(c,4,body);});
}
extern "C" inline Result __cdecl BARpcSimCreateWorld(const std::uint8_t* data,std::uint32_t size,std::uint64_t* world)noexcept {
    return detail::invoke([&](const detail::Config& c){detail::require(world,"RPC null world output");Bytes body;detail::append_raw(body,data,size);
        const auto out=detail::transact(c,5,body);detail::exact(out,8);std::size_t at=0;const auto value=wire::read64(out.data,at);
        if(out.result==0)detail::clear_world(value);*world=value;return detail::finish(out);});
}
extern "C" inline Result __cdecl BARpcSimDestroyWorld(std::uint64_t world)noexcept {
    return detail::invoke([&](const detail::Config& c){const auto out=detail::transact(c,6,detail::world_body(world));detail::exact(out,0);
        if(out.result==0)detail::clear_world(world);return detail::finish(out);});
}
extern "C" inline Result __cdecl BARpcSimProcessMsg(std::uint64_t world,const std::uint8_t* data,std::uint32_t size)noexcept {
    return detail::invoke([&](const detail::Config& c){auto body=detail::world_body(world);detail::append_raw(body,data,size);return detail::plain(c,7,body);});
}
extern "C" inline Result __cdecl BARpcSimStep(std::uint64_t world,std::uint32_t dt,std::int32_t* time)noexcept {
    return detail::invoke([&](const detail::Config& c){detail::require(time,"RPC null time output");auto body=detail::world_body(world);
        wire::append32(body,dt);wire::append32(body,static_cast<std::uint32_t>(*time));const auto out=detail::transact(c,8,body);detail::exact(out,4);
        std::size_t at=0;*time=detail::signed32(wire::read32(out.data,at));return detail::finish(out);});
}
extern "C" inline Result __cdecl BARpcSimMakeSimFrame(std::uint64_t world,std::uint32_t viewer,std::uint32_t* size)noexcept {
    return detail::invoke([&](const detail::Config& c){detail::require(size,"RPC null size output");auto body=detail::world_body(world);wire::append32(body,viewer);wire::append32(body,*size);
        return detail::paired(c,9,std::move(body),world,detail::Kind::Frame,size);});
}
extern "C" inline Result __cdecl BARpcSimGetSimFrameBuffer(std::uint64_t world,void* buffer)noexcept {
    return detail::invoke([&](const detail::Config&){return detail::get(world,detail::Kind::Frame,buffer);});
}
extern "C" inline Result __cdecl BARpcSimGetLabelsFrameBufferSize(std::uint64_t world,std::uint32_t registry,std::uint32_t* size)noexcept {
    return detail::invoke([&](const detail::Config& c){detail::require(size,"RPC null size output");auto body=detail::world_body(world);wire::append32(body,registry);wire::append32(body,*size);
        return detail::paired(c,11,std::move(body),world,detail::Kind::Labels,size,registry);});
}
extern "C" inline Result __cdecl BARpcSimGetLabelsFrameBuffer(std::uint64_t world,std::uint32_t registry,void* buffer)noexcept {
    return detail::invoke([&](const detail::Config&){return detail::get(world,detail::Kind::Labels,buffer,registry);});
}
extern "C" inline Result __cdecl BARpcSimGetConnectedPlayersSizeAndVersion(std::uint64_t world,std::int32_t* size,std::int32_t* version)noexcept {
    return detail::invoke([&](const detail::Config& c){detail::require(size && version,"RPC null player output");auto body=detail::world_body(world);
        wire::append32(body,static_cast<std::uint32_t>(*size));wire::append32(body,static_cast<std::uint32_t>(*version));
        return detail::paired(c,13,std::move(body),world,detail::Kind::Players,size,0,version);});
}
extern "C" inline Result __cdecl BARpcSimGetConnectedPlayers(std::uint64_t world,void* buffer)noexcept {
    return detail::invoke([&](const detail::Config&){return detail::get(world,detail::Kind::Players,buffer);});
}
extern "C" inline Result __cdecl BARpcSimGetMapFrameSize(std::uint64_t world,std::int32_t* size)noexcept {
    return detail::invoke([&](const detail::Config& c){detail::require(size,"RPC null map size");auto body=detail::world_body(world);wire::append32(body,static_cast<std::uint32_t>(*size));
        return detail::paired(c,15,std::move(body),world,detail::Kind::Map,size);});
}
extern "C" inline Result __cdecl BARpcSimGetMapFrame(std::uint64_t world,void* buffer)noexcept {
    return detail::invoke([&](const detail::Config&){return detail::get(world,detail::Kind::Map,buffer);});
}
extern "C" inline Result __cdecl BARpcSimCrashOnCommand()noexcept {
    return detail::invoke([](const detail::Config& c){return detail::plain(c,17,{});});
}
extern "C" inline Result __cdecl BARpcSimGetDebugDrawCommandBufferCount(std::uint64_t world,std::uint32_t* count)noexcept {
    return detail::invoke([&](const detail::Config& c){return detail::unsigned_count(c,18,world,count,false);});
}
extern "C" inline Result __cdecl BARpcSimGetDebugDrawCommandBufferSize(std::uint64_t world,std::uint32_t* size,std::uint32_t index)noexcept {
    return detail::invoke([&](const detail::Config& c){detail::require(size,"RPC null debug size");auto body=detail::world_body(world);wire::append32(body,*size);wire::append32(body,index);
        return detail::paired(c,19,std::move(body),world,detail::Kind::Debug,size,index);});
}
extern "C" inline Result __cdecl BARpcSimGetDebugDrawCommandBuffer(std::uint64_t world,void* buffer,std::uint32_t index)noexcept {
    (void)world;(void)buffer;(void)index;
    // Exact-build mov eax,8;ret. No request/cache/destination access, even if no
    // preceding Size exists or the destination is not a valid pointer.
    return detail::invoke([](const detail::Config&)->Result{return 8;});
}
extern "C" inline Result __cdecl BARpcSimClearAllDebugDrawCommandBuffers(std::uint64_t world)noexcept {
    return detail::invoke([&](const detail::Config& c){return detail::plain(c,21,detail::world_body(world));});
}
extern "C" inline Result __cdecl BARpcSimSetDebugDrawCommandListsActive(std::uint64_t world,std::uint32_t count,const std::int32_t* active)noexcept {
    return detail::invoke([&](const detail::Config& c){detail::require(count<=(wire::maxPayload-12)/4 && (!count || active),"RPC active array cap/pointer");
        auto body=detail::world_body(world);wire::append32(body,count);for(std::uint32_t i=0;i<count;++i)wire::append32(body,static_cast<std::uint32_t>(active[i]));return detail::plain(c,22,body);});
}
extern "C" inline Result __cdecl BARpcSimGetSystemCount(std::uint64_t world,std::uint32_t* count)noexcept {
    return detail::invoke([&](const detail::Config& c){return detail::unsigned_count(c,23,world,count,true);});
}
extern "C" inline Result __cdecl BARpcSimGetSystemIDAttributes(std::uint64_t world,void* attributes,std::uint32_t count)noexcept {
    return detail::invoke([&](const detail::Config& c){detail::require(count<=maxSystems,"RPC system record count cap");
        const auto bytes=static_cast<std::size_t>(count)*systemRecordBytes;auto body=detail::world_body(world);wire::append32(body,count);detail::append_raw(body,attributes,bytes);
        const auto out=detail::transact(c,24,body);detail::exact(out,bytes);if(bytes)std::memcpy(attributes,out.data.data(),bytes);return detail::finish(out);});
}
inline std::uintptr_t __cdecl resolver(void* native_module,const char* exact_name)noexcept {
    const auto* selected=detail::config.load(std::memory_order_acquire);
    if(!selected || native_module!=selected->module || reinterpret_cast<std::uintptr_t>(exact_name)<=0xffff)return 0;
#define BA_RPC_NAME(Name) if(std::strcmp(exact_name,#Name)==0)return reinterpret_cast<std::uintptr_t>(&BARpc##Name);
    BA_RPC_NAME(SimInit) BA_RPC_NAME(SimDestroy) BA_RPC_NAME(SimSetLogCallBack) BA_RPC_NAME(SimSetLogFlags)
    BA_RPC_NAME(SimCreateWorld) BA_RPC_NAME(SimDestroyWorld) BA_RPC_NAME(SimProcessMsg) BA_RPC_NAME(SimStep)
    BA_RPC_NAME(SimMakeSimFrame) BA_RPC_NAME(SimGetSimFrameBuffer) BA_RPC_NAME(SimGetLabelsFrameBufferSize) BA_RPC_NAME(SimGetLabelsFrameBuffer)
    BA_RPC_NAME(SimGetConnectedPlayersSizeAndVersion) BA_RPC_NAME(SimGetConnectedPlayers) BA_RPC_NAME(SimGetMapFrameSize) BA_RPC_NAME(SimGetMapFrame)
    BA_RPC_NAME(SimCrashOnCommand) BA_RPC_NAME(SimGetDebugDrawCommandBufferCount) BA_RPC_NAME(SimGetDebugDrawCommandBufferSize) BA_RPC_NAME(SimGetDebugDrawCommandBuffer)
    BA_RPC_NAME(SimClearAllDebugDrawCommandBuffers) BA_RPC_NAME(SimSetDebugDrawCommandListsActive) BA_RPC_NAME(SimGetSystemCount) BA_RPC_NAME(SimGetSystemIDAttributes)
#undef BA_RPC_NAME
    return 0;
}
}
