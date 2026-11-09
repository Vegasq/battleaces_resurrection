#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "native_rpc_backend.hpp"
#include <condition_variable>
#include <deque>
#include <exception>
#include <functional>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>

namespace b=ba_native_rpc_backend;
namespace p=ba_native_api_proxy;
namespace w=ba_native_worker_wire;
static void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
static constexpr std::uint64_t world=0xfedcba9876543210ULL,other=0x123456789abcdef0ULL;
static void* const module=reinterpret_cast<void*>(std::uintptr_t(0x12340000));
static w::Bytes u32(std::uint32_t value){w::Bytes bytes;w::append32(bytes,value);return bytes;}
static w::Bytes u64(std::uint64_t value){w::Bytes bytes;w::append64(bytes,value);return bytes;}
static w::Bytes fields(std::uint64_t value,std::initializer_list<std::uint32_t> values) {
    auto bytes=u64(value);for(auto item:values)w::append32(bytes,item);return bytes;
}
static w::Bytes joined(w::Bytes prefix,const w::Bytes& bytes){prefix.insert(prefix.end(),bytes.begin(),bytes.end());return prefix;}
static w::Response response(std::int32_t result,w::Bytes data={},std::vector<w::Log> logs={}) {
    return {result,std::move(logs),std::move(data)};
}
static w::Bytes pair(std::uint32_t size,std::int32_t get,const w::Bytes& bytes) {
    auto data=u32(size);w::append32(data,static_cast<std::uint32_t>(get));w::append32(data,static_cast<std::uint32_t>(bytes.size()));return joined(std::move(data),bytes);
}
static w::Bytes players(std::int32_t size,std::int32_t version,std::int32_t get,const w::Bytes& bytes) {
    auto data=u32(static_cast<std::uint32_t>(size));w::append32(data,static_cast<std::uint32_t>(version));
    w::append32(data,static_cast<std::uint32_t>(get));w::append32(data,static_cast<std::uint32_t>(bytes.size()));return joined(std::move(data),bytes);
}
struct Packet {std::uint8_t opcode;w::Bytes payload;w::Response reply;bool transport=true,throws=false;};
struct Script {std::deque<Packet> packets;std::size_t calls=0,unexpected=0;};
struct Gate {std::recursive_mutex mutex;int depth=0,peak=0,enters=0,leaves=0;};
static Script script;static Gate gate;
static std::vector<std::string> logs;
static bool throwLog=false;
template<class Function>static Function api(const char* name) {
    const auto address=p::lookup(name);check(address!=0,"missing remote proxy export");return reinterpret_cast<Function>(address);
}
static int __cdecl enter(void* context,const char*) {
    check(context==&gate,"gate context changed");gate.mutex.lock();++gate.depth;++gate.enters;
    if(gate.depth>gate.peak)gate.peak=gate.depth;return 0;
}
static void __cdecl leave(void* context,const char*) {
    check(context==&gate && gate.depth>0,"unbalanced remote gate");--gate.depth;++gate.leaves;gate.mutex.unlock();
}
static bool __cdecl request(void* context,std::uint8_t opcode,const w::Bytes& payload,w::Response& out) {
    check(context==&script && gate.depth>0,"request bypassed supplied context/gate");
    ++script.calls;
    if(script.packets.empty()){++script.unexpected;throw std::runtime_error("unexpected worker request (possibly local Get)");}
    auto expected=std::move(script.packets.front());script.packets.pop_front();
    if(opcode!=expected.opcode || payload!=expected.payload){++script.unexpected;throw std::runtime_error("remote ABI payload/opcode differs");}
    if(expected.throws)throw std::runtime_error("authored request exception");
    out=std::move(expected.reply);return expected.transport;
}
static void expect(std::uint8_t opcode,w::Bytes payload,w::Response reply) {
    script.packets.push_back({opcode,std::move(payload),std::move(reply),true,false});
}
static void emptyScript(){check(script.packets.empty() && script.unexpected==0,"omitted/mismatched/unexpected worker request");}
static void __cdecl callbackA(std::int32_t kind,const char* text) {
    check(gate.depth>0,"log callback escaped recursive gate");logs.push_back("A"+std::to_string(kind)+":"+text);
    if(throwLog)throw std::runtime_error("authored managed callback failure");
    if(std::string(text)=="reenter")check(api<p::types::SimSetLogFlags>("SimSetLogFlags")(999)==0,"reentrant RPC failed");
    if(std::string(text)=="nested-pair" || std::string(text)=="nested-pair-unread") {
        std::uint32_t size=0;
        check(api<p::types::SimMakeSimFrame>("SimMakeSimFrame")(world,99,&size)==0 && size==2,"nested pair Make failed");
        if(std::string(text)=="nested-pair") {
            std::uint8_t bytes[2]{};
            check(api<p::types::SimGetSimFrameBuffer>("SimGetSimFrameBuffer")(world,bytes)==0 &&
                  bytes[0]==8 && bytes[1]==9,"nested pair Get lost immutable response");
        }
    }
}
static void __cdecl callbackB(std::int32_t kind,const char* text){logs.push_back("B"+std::to_string(kind)+":"+text);}
static w::Log log(std::int32_t kind,const char* text){const std::string value(text);return {kind,w::Bytes(value.begin(),value.end())};}
static void configurationAndLookup() {
    check(b::resolver(module,"SimInit")==0 && b::BARpcSimInit(true)==-1,"uninitialized backend executed");
    check(b::initialize(nullptr,request,&script)==-1 && b::initialize(module,nullptr,&script)==-1,"invalid backend configured");
    b::Limits bad;bad.max_cached_pairs=0;check(b::initialize(module,request,&script,bad)==-1,"zero pair cap accepted");
    bad={};bad.max_cached_bytes=0;check(b::initialize(module,request,&script,bad)==-1,"zero byte cap accepted");
    b::Limits limits;limits.max_cached_pairs=8;limits.max_cached_bytes=64;
    check(b::initialize(module,request,&script,limits)==0 && b::initialize(module,request,&script)==-1,"immutable backend binding failed");
    for(const char* name:{"SimMakeSimDebugInfoFrame","SimGetSimDebugInfoFrameBuffer","siminit","Init","SimInit ","unknown"})
        check(b::resolver(module,name)==0,"unreviewed remote alias accepted");
    check(b::resolver(nullptr,"SimInit")==0 && b::resolver(reinterpret_cast<void*>(1),"SimInit")==0 &&
          b::resolver(module,nullptr)==0 && b::resolver(module,reinterpret_cast<const char*>(1))==0,"wrong module/ordinal accepted");
    check(p::bind(module,b::resolver,{&gate,enter,leave})==0,"typed proxy could not bind remote shims");
    check(b::retained_callback()==nullptr,"callback enabled by default");
}
static void typedRequestsAndSeeds() {
    expect(1,{1},response(11));check(api<p::types::SimInit>("SimInit")(true)==11,"bool/result changed");
    expect(1,{0},response(0));check(api<p::types::SimInit>("SimInit")(false)==0,"false bool changed");
    expect(4,u32(0xfedcba98),response(14));check(api<p::types::SimSetLogFlags>("SimSetLogFlags")(0xfedcba98)==14,"flags/result changed");
    const w::Bytes game{9,8,7,6};std::uint64_t created=123;
    expect(5,game,response(0,u64(world)));
    check(api<p::types::SimCreateWorld>("SimCreateWorld")(game.data(),static_cast<std::uint32_t>(game.size()),&created)==0 && created==world,"world/rawGameData changed");
    expect(5,game,response(7,u64(0)));created=999;
    check(api<p::types::SimCreateWorld>("SimCreateWorld")(game.data(),static_cast<std::uint32_t>(game.size()),&created)==7 && created==0,"create worker seed0 contract changed");
    const w::Bytes actions{1,3,5};expect(7,joined(u64(world),actions),response(-17));
    check(api<p::types::SimProcessMsg>("SimProcessMsg")(world,actions.data(),static_cast<std::uint32_t>(actions.size()))==-17,"input actions/world changed");
    std::int32_t time=-123;expect(8,fields(world,{50,static_cast<std::uint32_t>(time)}),response(8,u32(static_cast<std::uint32_t>(-456))));
    check(api<p::types::SimStep>("SimStep")(world,50,&time)==8 && time==-456,"signed time seed/result changed");
    std::uint32_t size=0xfedcba98;expect(9,fields(world,{31,size}),response(0,pair(3,0,{1,2,3})));
    check(api<p::types::SimMakeSimFrame>("SimMakeSimFrame")(world,31,&size)==0 && size==3,"viewer/uint size seed changed");
    std::uint8_t output[5]={0xaa,0xaa,0xaa,0xaa,0xaa};const auto calls=script.calls;
    check(api<p::types::SimGetSimFrameBuffer>("SimGetSimFrameBuffer")(world,output+1)==0 &&
          w::Bytes(output,output+5)==w::Bytes({0xaa,1,2,3,0xaa}) && script.calls==calls,"frame Get wrote outside verified count or used wire");
    check(api<p::types::SimGetSimFrameBuffer>("SimGetSimFrameBuffer")(world,output)==-1,"duplicate frame Get accepted");
    size=77;expect(11,fields(world,{4,size}),response(0,pair(2,0,{4,5})));
    check(api<p::types::SimGetLabelsFrameBufferSize>("SimGetLabelsFrameBufferSize")(world,4,&size)==0 && size==2,"labels seed/registry changed");
    check(api<p::types::SimGetLabelsFrameBuffer>("SimGetLabelsFrameBuffer")(world,5,output)==-1,"wrong labels registry consumed cache");
    check(api<p::types::SimGetLabelsFrameBuffer>("SimGetLabelsFrameBuffer")(world,4,output)==0 && output[0]==4 && output[1]==5,"labels Get changed");
    std::int32_t signedSize=-55,version=-66;
    expect(13,fields(world,{static_cast<std::uint32_t>(signedSize),static_cast<std::uint32_t>(version)}),response(0,players(2,-7,0,{6,7})));
    check(api<p::types::SimGetConnectedPlayersSizeAndVersion>("SimGetConnectedPlayersSizeAndVersion")(world,&signedSize,&version)==0 &&
          signedSize==2 && version==-7,"player signed seeds/version changed");
    check(api<p::types::SimGetConnectedPlayers>("SimGetConnectedPlayers")(world,output)==0 && output[0]==6,"players Get changed");
    signedSize=-88;expect(15,fields(world,{static_cast<std::uint32_t>(signedSize)}),response(0,pair(2,0,{8,9})));
    check(api<p::types::SimGetMapFrameSize>("SimGetMapFrameSize")(world,&signedSize)==0 && signedSize==2,"map signed seed changed");
    check(api<p::types::SimGetMapFrame>("SimGetMapFrame")(world,output)==0 && output[0]==8,"map Get changed");
    expect(17,{},response(17));check(api<p::types::SimCrashOnCommand>("SimCrashOnCommand")()==17,"crash opcode changed");
    size=99;expect(18,fields(world,{size}),response(8,u32(size)));
    check(api<p::types::SimGetDebugDrawCommandBufferCount>("SimGetDebugDrawCommandBufferCount")(world,&size)==8 && size==99,"debug no-write count seed changed");
    size=101;expect(19,fields(world,{size,17}),response(8,pair(size,8,{})));output[0]=0xab;
    check(api<p::types::SimGetDebugDrawCommandBufferSize>("SimGetDebugDrawCommandBufferSize")(world,&size,17)==8 && size==101,"debug no-write size/index order changed");
    check(api<p::types::SimGetDebugDrawCommandBuffer>("SimGetDebugDrawCommandBuffer")(world,output,18)==8 && b::cache_stats().pairs==0,"debug stub retained cache bookkeeping");
    check(api<p::types::SimGetDebugDrawCommandBuffer>("SimGetDebugDrawCommandBuffer")(world,output,17)==8 && output[0]==0xab,"debug no-write Get fabricated bytes");
    check(api<p::types::SimGetDebugDrawCommandBuffer>("SimGetDebugDrawCommandBuffer")(world,reinterpret_cast<void*>(1),17)==8,"uncached debug stub dereferenced destination");
    size=0xffffffff;expect(19,fields(world,{size,99}),response(8,pair(size,8,{})));
    check(api<p::types::SimGetDebugDrawCommandBufferSize>("SimGetDebugDrawCommandBufferSize")(world,&size,99)==8 && size==0xffffffff &&
          api<p::types::SimGetDebugDrawCommandBuffer>("SimGetDebugDrawCommandBuffer")(world,output,99)==8 && output[0]==0xab,
          "large debug seed allocated/fabricated destination bytes");
    expect(21,u64(world),response(8));check(api<p::types::SimClearAllDebugDrawCommandBuffers>("SimClearAllDebugDrawCommandBuffers")(world)==8,"debug clear changed");
    const std::int32_t active[]={-1,42,(-2147483647-1)};
    expect(22,fields(world,{3,0xffffffff,42,0x80000000}),response(8));
    check(api<p::types::SimSetDebugDrawCommandListsActive>("SimSetDebugDrawCommandListsActive")(world,3,active)==8,"active raw int32 array changed");
    size=37;expect(23,fields(world,{size}),response(0,u32(2)));
    check(api<p::types::SimGetSystemCount>("SimGetSystemCount")(world,&size)==0 && size==2,"system count seed changed");
    w::Bytes attributes(256,0xa1),changed(256,0xb2);expect(24,joined(fields(world,{2}),attributes),response(24,changed));
    check(api<p::types::SimGetSystemIDAttributes>("SimGetSystemIDAttributes")(world,attributes.data(),2)==24 && attributes==changed,"128-byte inline attrs/seeds changed");
    check(b::cache_stats().pairs==0 && b::cache_stats().bytes==0,"consumed pairs retained payloads");emptyScript();
}
static void pairErrorsAndMalformedResponses() {
    const auto make=api<p::types::SimMakeSimFrame>("SimMakeSimFrame");const auto get=api<p::types::SimGetSimFrameBuffer>("SimGetSimFrameBuffer");
    std::uint32_t size=123;std::uint8_t out[4]={0xaa,0xaa,0xaa,0xaa};
    expect(9,fields(world,{0,size}),response(5,pair(0xffffffff,-1,{})));
    check(make(world,0,&size)==5 && size==0xffffffff && get(world,out)==-1 && out[0]==0xaa,"Make failure/Get omission changed");
    size=123;expect(9,fields(world,{0,size}),response(0,pair(3,19,{})));
    check(make(world,0,&size)==0 && size==3 && get(world,out)==19 && get(world,out)==-1 && out[0]==0xaa,"separate Get failure lost or wrote output");
    size=123;expect(9,fields(world,{0,size}),response(0,pair(0,0,{})));
    check(make(world,0,&size)==0 && size==0 && get(world,nullptr)==0,"zero-byte Get rejected");
    size=123;expect(9,fields(world,{0,size}),response(0,pair(3,0,{1,2,3})));
    check(make(world,0,&size)==0 && get(world,nullptr)==-1 && get(world,out)==0,"invalid destination consumed valid cache");
    for(const auto& invalid:std::vector<w::Response>{response(0,pair(3,0,{1,2})),response(0,pair(16U*1024U*1024U+1U,0,{})),
            response(7,pair(3,0,{1,2,3})),response(0,pair(3,9,{1})),response(0,{1,2,3})}) {
        size=123;expect(9,fields(world,{0,size}),invalid);
        check(make(world,0,&size)==-1 && size==123 && get(world,out)==-1 && out[3]==0xaa,"malformed pair changed output/retained stale cache");
    }
    std::int32_t mapSize=-2;expect(15,fields(world,{static_cast<std::uint32_t>(mapSize)}),response(0,pair(0xffffffff,0,{})));
    check(api<p::types::SimGetMapFrameSize>("SimGetMapFrameSize")(world,&mapSize)==-1 && mapSize==-2,"negative successful map size written");
    size=123;expect(9,fields(world,{0,size}),response(0,pair(1,0,{7})));check(make(world,0,&size)==0,"stale-cache setup failed");
    size=123;script.packets.push_back({9,fields(world,{0,size}),response(0,pair(1,0,{8})),false,false});
    check(make(world,0,&size)==-1 && size==123 && get(world,out)==-1,"transport failure preserved old pair/wrote out seed");
    size=123;script.packets.push_back({9,fields(world,{0,size}),{},true,true});
    check(make(world,0,&size)==-1 && size==123,"request exception crossed ABI/wrote seed");
    size=123;expect(19,fields(world,{size,7}),response(8,pair(124,8,{})));
    check(api<p::types::SimGetDebugDrawCommandBufferSize>("SimGetDebugDrawCommandBufferSize")(world,&size,7)==-1 && size==123,"debug stub changed size seed");
    expect(18,fields(world,{size}),response(8,u32(124)));
    check(api<p::types::SimGetDebugDrawCommandBufferCount>("SimGetDebugDrawCommandBufferCount")(world,&size)==-1 && size==123,"debug stub changed count seed");emptyScript();
}
static void requestAndResponseBounds() {
    const auto calls=script.calls;const std::uint8_t tiny=1;std::uint64_t created=77;
    check(api<p::types::SimCreateWorld>("SimCreateWorld")(&tiny,32U*1024U*1024U+1U,&created)==-1 && created==77,"oversized raw GameData accessed/written");
    check(api<p::types::SimProcessMsg>("SimProcessMsg")(world,&tiny,32U*1024U*1024U)==-1,"input prefix omitted from payload cap");
    check(api<p::types::SimSetDebugDrawCommandListsActive>("SimSetDebugDrawCommandListsActive")(world,0xffffffff,reinterpret_cast<const std::int32_t*>(&tiny))==-1,"oversized active array accessed");
    w::Bytes attributes(128,0xcc);check(api<p::types::SimGetSystemIDAttributes>("SimGetSystemIDAttributes")(world,attributes.data(),2049)==-1,"system record count cap bypassed");
    check(api<p::types::SimStep>("SimStep")(world,50,nullptr)==-1 && script.calls==calls,"invalid out pointer issued request");
    expect(24,joined(fields(world,{1}),attributes),response(0,w::Bytes(129,0xdd)));
    check(api<p::types::SimGetSystemIDAttributes>("SimGetSystemIDAttributes")(world,attributes.data(),1)==-1 && attributes==w::Bytes(128,0xcc),"attrs length mismatch wrote caller array");
    std::uint32_t count=77;expect(23,fields(world,{count}),response(0,u32(2049)));
    check(api<p::types::SimGetSystemCount>("SimGetSystemCount")(world,&count)==-1 && count==77,"oversized successful system count written");
    expect(23,fields(world,{count}),response(7,u32(0xffffffff)));
    check(api<p::types::SimGetSystemCount>("SimGetSystemCount")(world,&count)==7 && count==0xffffffff,"failed native seed was clamped");
    std::int32_t time=77;expect(8,fields(world,{50,77}),response(0,{1,2,3,4,5}));
    check(api<p::types::SimStep>("SimStep")(world,50,&time)==-1 && time==77,"trailing step bytes wrote output");
    auto oversized=response(0,u32(1));oversized.logs.resize(257);
    expect(8,fields(world,{50,77}),std::move(oversized));
    check(api<p::types::SimStep>("SimStep")(world,50,&time)==-1 && time==77,"log cap validated after out write");emptyScript();
    expect(22,fields(world,{0}),response(8));
    check(api<p::types::SimSetDebugDrawCommandListsActive>("SimSetDebugDrawCommandListsActive")(world,0,nullptr)==8,"zero-count active array rejected");
    expect(24,fields(world,{0}),response(0));
    check(api<p::types::SimGetSystemIDAttributes>("SimGetSystemIDAttributes")(world,nullptr,0)==0,"zero-count system array rejected");
    w::Bytes bounded(2048U*128U+2U,0xcc);const w::Bytes initial(bounded.begin()+1,bounded.end()-1);
    expect(24,joined(fields(world,{2048}),initial),response(0,w::Bytes(2048U*128U,0xdd)));
    check(api<p::types::SimGetSystemIDAttributes>("SimGetSystemIDAttributes")(world,bounded.data()+1,2048)==0 &&
          bounded.front()==0xcc && bounded.back()==0xcc && bounded[1]==0xdd && bounded[bounded.size()-2]==0xdd,
          "maximum inline system count copied outside caller array");emptyScript();
}
static void cacheWorldKindAndCapacity() {
    const auto make=api<p::types::SimMakeSimFrame>("SimMakeSimFrame");const auto get=api<p::types::SimGetSimFrameBuffer>("SimGetSimFrameBuffer");
    std::uint32_t size=0;std::uint8_t out[64]{};
    expect(9,fields(world,{1,0}),response(0,pair(2,0,{1,2})));check(make(world,1,&size)==0,"world cache setup failed");
    size=0;expect(9,fields(other,{2,0}),response(0,pair(2,0,{3,4})));check(make(other,2,&size)==0,"other world cache setup failed");
    check(api<p::types::SimGetMapFrame>("SimGetMapFrame")(world,out)==-1 && get(world,out)==0 && out[0]==1 &&
          get(other,out)==0 && out[0]==3,"world/kind cache keys collided");
    size=0;expect(9,fields(world,{0,0}),response(0,pair(40,0,w::Bytes(40,1))));check(make(world,0,&size)==0,"byte-cap first pair failed");
    size=0;expect(9,fields(other,{0,0}),response(0,pair(24,0,w::Bytes(24,2))));check(make(other,0,&size)==0,"exact byte cap rejected");
    size=77;expect(9,fields(other+1,{0,77}),response(0,pair(1,0,{3})));
    check(make(other+1,0,&size)==-1 && size==77 && b::cache_stats().bytes==64,"byte cap overwrote out size/evicted another pair");
    check(get(world,out)==0 && get(other,out)==0,"byte-cap rejection destroyed unrelated pair");
    for(std::uint64_t item=1;item<=8;++item) {
        size=0;expect(9,fields(item,{0,0}),response(0,pair(1,0,{static_cast<std::uint8_t>(item)})));check(make(item,0,&size)==0,"pair-count setup failed");
    }
    const auto before=script.calls;size=77;
    check(make(9,0,&size)==-1 && size==77 && script.calls==before && b::cache_stats().pairs==8,"pair cap issued request or evicted input");
    std::uint32_t debugSeed=0xffffffff;expect(19,fields(world,{debugSeed,99}),response(8,pair(debugSeed,8,{})));
    check(api<p::types::SimGetDebugDrawCommandBufferSize>("SimGetDebugDrawCommandBufferSize")(world,&debugSeed,99)==8 &&
          debugSeed==0xffffffff && b::cache_stats().pairs==8 &&
          api<p::types::SimGetDebugDrawCommandBuffer>("SimGetDebugDrawCommandBuffer")(world,reinterpret_cast<void*>(1),99)==8,
          "full normal cache changed known no-write debug behavior");
    for(std::uint64_t item=1;item<=8;++item)check(get(item,out)==0 && out[0]==item,"pair capacity lost a cached response");
    check(b::cache_stats().pairs==0,"pair consumption did not release capacity");emptyScript();
}
static void interleavedThreads() {
    expect(9,fields(world,{1,0}),response(0,pair(1,0,{11})));
    expect(9,fields(world,{2,0}),response(0,pair(1,0,{22})));
    std::mutex mutex;std::condition_variable changed;int phase=0;std::exception_ptr failureA,failureB;
    std::thread first([&]{try {
        std::uint32_t size=0;check(api<p::types::SimMakeSimFrame>("SimMakeSimFrame")(world,1,&size)==0,"thread A Make failed");
        {std::lock_guard<std::mutex> lock(mutex);phase=1;}changed.notify_all();
        {std::unique_lock<std::mutex> lock(mutex);changed.wait(lock,[&]{return phase>=2;});}
        std::uint8_t out=0;check(api<p::types::SimGetSimFrameBuffer>("SimGetSimFrameBuffer")(world,&out)==0 && out==11,"thread B overwrote A pair");
    }catch(...){failureA=std::current_exception();{std::lock_guard<std::mutex> lock(mutex);phase=3;}changed.notify_all();}});
    std::thread second([&]{try {
        {std::unique_lock<std::mutex> lock(mutex);changed.wait(lock,[&]{return phase>=1;});}
        std::uint8_t out=0;check(api<p::types::SimGetSimFrameBuffer>("SimGetSimFrameBuffer")(world,&out)==-1,"thread B consumed A pair");
        std::uint32_t size=0;check(api<p::types::SimMakeSimFrame>("SimMakeSimFrame")(world,2,&size)==0,"thread B Make failed");
        check(api<p::types::SimGetSimFrameBuffer>("SimGetSimFrameBuffer")(world,&out)==0 && out==22,"thread B consumed wrong pair");
        {std::lock_guard<std::mutex> lock(mutex);phase=2;}changed.notify_all();
    }catch(...){failureB=std::current_exception();{std::lock_guard<std::mutex> lock(mutex);phase=3;}changed.notify_all();}});
    first.join();second.join();if(failureA)std::rethrow_exception(failureA);if(failureB)std::rethrow_exception(failureB);
    check(b::cache_stats().pairs==0,"thread pair consumption leaked cache");
    expect(9,fields(world,{3,0}),response(0,pair(1,0,{33})));
    std::thread orphan([&]{try{std::uint32_t size=0;check(api<p::types::SimMakeSimFrame>("SimMakeSimFrame")(world,3,&size)==0,"orphan Make failed");}
        catch(...){failureA=std::current_exception();}});orphan.join();if(failureA)std::rethrow_exception(failureA);
    std::thread later([&]{try{std::uint8_t out=0;check(api<p::types::SimGetSimFrameBuffer>("SimGetSimFrameBuffer")(world,&out)==-1,"new thread reused abandoned pair");}
        catch(...){failureB=std::current_exception();}});later.join();if(failureB)std::rethrow_exception(failureB);
    check(b::cache_stats().pairs==1,"unrelated thread consumed orphan cache");expect(6,u64(world),response(0));
    check(api<p::types::SimDestroyWorld>("SimDestroyWorld")(world)==0 && b::cache_stats().pairs==0,"world close failed to prune other-thread cache");emptyScript();
}
static void callbackOrderingReentrancyAndLifetime() {
    const auto set=api<p::types::SimSetLogCallBack>("SimSetLogCallBack");
    expect(3,{1},response(0,{}, {log(-1,"new")}));check(set(callbackA)==0 && b::retained_callback()==callbackA &&
          logs.back()=="A-1:new","op3 callback was not committed before log delivery");
    expect(3,{1},response(7,{}, {log(2,"old")}));check(set(callbackB)==7 && b::retained_callback()==callbackA &&
          logs.back()=="A2:old","failed op3 replaced callback");
    std::int32_t time=0;expect(8,fields(world,{50,0}),response(0,u32(50),{log(3,"reenter")}));expect(4,u32(999),response(0));
    check(api<p::types::SimStep>("SimStep")(world,50,&time)==0 && time==50 && gate.peak==2,"response log reentrancy failed");
    for(const char* text:{"nested-pair","nested-pair-unread"}) {
        std::uint32_t outerSize=77;
        expect(9,fields(world,{11,77}),response(0,pair(3,0,{1,2,3}),{log(7,text)}));
        expect(9,fields(world,{99,0}),response(0,pair(2,0,{8,9})));
        std::uint8_t outerBytes[5]={0xaa,0xaa,0xaa,0xaa,0xaa};
        check(api<p::types::SimMakeSimFrame>("SimMakeSimFrame")(world,11,&outerSize)==0 && outerSize==3 &&
              api<p::types::SimGetSimFrameBuffer>("SimGetSimFrameBuffer")(world,outerBytes+1)==0 &&
              w::Bytes(outerBytes,outerBytes+5)==w::Bytes({0xaa,1,2,3,0xaa}),"nested log query replaced outer advertised-size pair");
    }
    throwLog=true;expect(4,u32(7),response(0,{}, {log(4,"throws")}));
    check(api<p::types::SimSetLogFlags>("SimSetLogFlags")(7)==-1,"callback C++ exception escaped");throwLog=false;
    expect(3,{0},response(0,{}, {log(5,"disabled")}));const auto count=logs.size();
    check(set(nullptr)==0 && b::retained_callback()==nullptr && logs.size()==count,"disabled callback still dispatched");
    expect(3,{1},response(0));check(set(callbackA)==0,"callback reenable failed");
    std::uint32_t size=0;expect(9,fields(world,{0,0}),response(0,pair(1,0,{1})));
    check(api<p::types::SimMakeSimFrame>("SimMakeSimFrame")(world,0,&size)==0,"lifetime cache setup failed");
    expect(6,u64(world),response(0));check(api<p::types::SimDestroyWorld>("SimDestroyWorld")(world)==0 &&
          b::cache_stats().pairs==0 && b::retained_callback()==callbackA,"world close retained cache or cleared session callback");
    expect(2,{},response(0,{}, {log(6,"destroy")}));check(api<p::types::SimDestroy>("SimDestroy")()==0 &&
          logs.back()=="A6:destroy" && b::retained_callback()==nullptr && b::cache_stats().bytes==0,"session cleanup callback/cache ordering failed");emptyScript();
}
int main() {
    try {
        configurationAndLookup();typedRequestsAndSeeds();pairErrorsAndMalformedResponses();requestAndResponseBounds();
        cacheWorldKindAndCapacity();interleavedThreads();callbackOrderingReentrancyAndLifetime();
        check(gate.depth==0 && gate.enters==gate.leaves,"remote gate left acquired");
        std::cout<<"native RPC backend: 24 ABI shims PASS; 7 packet/cache/thread/callback scenario groups PASS\n";return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
