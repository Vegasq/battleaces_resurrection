#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "native_api_proxy.hpp"
#include <algorithm>
#include <array>
#include <cstring>
#include <functional>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

namespace p=ba_native_api_proxy;
static void check(bool result,const char* message){if(!result)throw std::runtime_error(message);}
static constexpr std::uint64_t world=0xfedcba9876543210ULL;
static constexpr std::uint32_t count=0xfedcba98U,index=0x98765432U;
static const std::uint8_t input[]={1,2,3,4,5};
static std::uint8_t output[64]{};
static const std::int32_t lists[]={-7,0,19};
static std::uint64_t worldResult=0;
static std::uint32_t unsignedResult=0;
static std::int32_t signedResult=0,versionResult=0;
static void* const module=reinterpret_cast<void*>(std::uintptr_t(0x12340000));
static bool throwOriginal=false,reenterOriginal=false,expectedInit=true;
static std::vector<std::string> originals,trace,resolved;
static const char* missing=nullptr;
static bool throwResolver=false;
struct Gate {
    std::recursive_mutex mutex;
    int enters=0,leaves=0,depth=0,peak=0;
    std::array<const char*,8> names{};
    bool deny=false,throwEnter=false,throwLeave=false;
};
static Gate* gate=nullptr;
struct HookState {int before=0,after=0;bool denyBefore=false,throwBefore=false,denyAfter=false,throwAfter=false;};
static HookState* hooks=nullptr;
static void called(const char* name) {
    check(gate && gate->depth>0 && std::strcmp(gate->names[gate->depth-1],name)==0,"native call bypassed/misnamed API gate");
    originals.emplace_back(name);trace.emplace_back(std::string("original:")+name);
}
static void __cdecl logCallback(std::int32_t kind,const char* text) {
    check(kind==-37 && text==reinterpret_cast<const char*>(input),"callback raw arguments changed");
    const auto nested=reinterpret_cast<p::types::SimGetSystemCount>(p::lookup("SimGetSystemCount"));
    check(nested(world,&unsignedResult)==123,"nested log callback export failed");
}
static std::int32_t __cdecl fakeSimInit(bool enabled) {
    called("SimInit");check(enabled==expectedInit,"bool argument changed");
    if(reenterOriginal) {
        const auto nested=reinterpret_cast<p::types::SimSetLogFlags>(p::lookup("SimSetLogFlags"));
        check(nested(count)==104,"reentrant original export failed");
    }
    return 101;
}
static std::int32_t __cdecl fakeSimDestroy(){called("SimDestroy");if(throwOriginal)throw std::runtime_error("native fake failure");return 102;}
static std::int32_t __cdecl fakeSimSetLogCallBack(p::LogCallback callback) {
    called("SimSetLogCallBack");check(callback==logCallback,"callback address changed");
    callback(-37,reinterpret_cast<const char*>(input));return 103;
}
static std::int32_t __cdecl fakeSimSetLogFlags(std::uint32_t flags){called("SimSetLogFlags");check(flags==count,"flags width changed");return 104;}
static std::int32_t __cdecl fakeSimCreateWorld(const std::uint8_t* data,std::uint32_t size,std::uint64_t* result) {
    called("SimCreateWorld");check(data==input && size==count && result==&worldResult,"create pointer/count/byref changed");*result=world;return 105;
}
static std::int32_t __cdecl fakeSimDestroyWorld(std::uint64_t value){called("SimDestroyWorld");check(value==world,"world narrowed");return 106;}
static std::int32_t __cdecl fakeSimProcessMsg(std::uint64_t value,const std::uint8_t* data,std::uint32_t size) {
    called("SimProcessMsg");check(value==world && data==input && size==count,"message raw arguments changed");return 107;
}
static std::int32_t __cdecl fakeSimStep(std::uint64_t value,std::uint32_t dt,std::int32_t* result) {
    called("SimStep");check(value==world && dt==count && result==&signedResult,"step pointer/timing changed");*result=-1234567;return -108;
}
static std::int32_t __cdecl fakeSimMakeSimFrame(std::uint64_t value,std::uint32_t viewer,std::uint32_t* size) {
    called("SimMakeSimFrame");check(value==world && viewer==count && size==&unsignedResult,"frame arguments changed");*size=0xabcdef01;return 109;
}
static std::int32_t __cdecl fakeSimGetSimFrameBuffer(std::uint64_t value,void* buffer) {
    called("SimGetSimFrameBuffer");check(value==world && buffer==output,"frame buffer changed");output[0]=10;return 110;
}
static std::int32_t __cdecl fakeSimGetLabelsFrameBufferSize(std::uint64_t value,std::uint32_t registry,std::uint32_t* size) {
    called("SimGetLabelsFrameBufferSize");check(value==world && registry==count && size==&unsignedResult,"label size arguments changed");*size=11;return 111;
}
static std::int32_t __cdecl fakeSimGetLabelsFrameBuffer(std::uint64_t value,std::uint32_t registry,void* buffer) {
    called("SimGetLabelsFrameBuffer");check(value==world && registry==count && buffer==output,"label buffer changed");output[0]=12;return 112;
}
static std::int32_t __cdecl fakeSimGetConnectedPlayersSizeAndVersion(std::uint64_t value,std::int32_t* size,std::int32_t* version) {
    called("SimGetConnectedPlayersSizeAndVersion");check(value==world && size==&signedResult && version==&versionResult,"player byrefs changed");*size=-13;*version=-1313;return 113;
}
static std::int32_t __cdecl fakeSimGetConnectedPlayers(std::uint64_t value,void* buffer) {
    called("SimGetConnectedPlayers");check(value==world && buffer==output,"players buffer changed");output[0]=14;return 114;
}
static std::int32_t __cdecl fakeSimGetMapFrameSize(std::uint64_t value,std::int32_t* size) {
    called("SimGetMapFrameSize");check(value==world && size==&signedResult,"map size byref changed");*size=-15;return 115;
}
static std::int32_t __cdecl fakeSimGetMapFrame(std::uint64_t value,void* buffer) {
    called("SimGetMapFrame");check(value==world && buffer==output,"map buffer changed");output[0]=16;return 116;
}
static std::int32_t __cdecl fakeSimCrashOnCommand(){called("SimCrashOnCommand");return 117;}
static std::int32_t __cdecl fakeSimGetDebugDrawCommandBufferCount(std::uint64_t value,std::uint32_t* size) {
    called("SimGetDebugDrawCommandBufferCount");check(value==world && size==&unsignedResult,"debug count changed");*size=18;return 118;
}
static std::int32_t __cdecl fakeSimGetDebugDrawCommandBufferSize(std::uint64_t value,std::uint32_t* size,std::uint32_t item) {
    called("SimGetDebugDrawCommandBufferSize");check(value==world && size==&unsignedResult && item==index,"debug size pointer/index order changed");*size=19;return 119;
}
static std::int32_t __cdecl fakeSimGetDebugDrawCommandBuffer(std::uint64_t value,void* buffer,std::uint32_t item) {
    called("SimGetDebugDrawCommandBuffer");check(value==world && buffer==output && item==index,"debug buffer pointer/index order changed");output[0]=20;return 120;
}
static std::int32_t __cdecl fakeSimClearAllDebugDrawCommandBuffers(std::uint64_t value) {
    called("SimClearAllDebugDrawCommandBuffers");check(value==world,"debug clear world changed");return 121;
}
static std::int32_t __cdecl fakeSimSetDebugDrawCommandListsActive(std::uint64_t value,std::uint32_t size,const std::int32_t* active) {
    called("SimSetDebugDrawCommandListsActive");check(value==world && size==count && active==lists,"debug list array marshaling changed");return 122;
}
static std::int32_t __cdecl fakeSimGetSystemCount(std::uint64_t value,std::uint32_t* size) {
    called("SimGetSystemCount");check(value==world && size==&unsignedResult,"system count changed");*size=23;return 123;
}
static std::int32_t __cdecl fakeSimGetSystemIDAttributes(std::uint64_t value,void* array,std::uint32_t size) {
    called("SimGetSystemIDAttributes");check(value==world && array==output && size==count,"system raw array/count changed");output[0]=24;return 124;
}
#define FAKE_EXPORTS(X) \
 X(SimInit) X(SimDestroy) X(SimSetLogCallBack) X(SimSetLogFlags) X(SimCreateWorld) X(SimDestroyWorld) \
 X(SimProcessMsg) X(SimStep) X(SimMakeSimFrame) X(SimGetSimFrameBuffer) X(SimGetLabelsFrameBufferSize) \
 X(SimGetLabelsFrameBuffer) X(SimGetConnectedPlayersSizeAndVersion) X(SimGetConnectedPlayers) \
 X(SimGetMapFrameSize) X(SimGetMapFrame) X(SimCrashOnCommand) X(SimGetDebugDrawCommandBufferCount) \
 X(SimGetDebugDrawCommandBufferSize) X(SimGetDebugDrawCommandBuffer) X(SimClearAllDebugDrawCommandBuffers) \
 X(SimSetDebugDrawCommandListsActive) X(SimGetSystemCount) X(SimGetSystemIDAttributes)
static std::uintptr_t __cdecl resolve(void* selected,const char* name) {
    check(selected==module,"resolver module identity changed");resolved.emplace_back(name);
    if(throwResolver)throw std::runtime_error("resolver failure");
    if(missing && std::strcmp(name,missing)==0)return 0;
#define FIND_FAKE(Name) if(std::strcmp(name,#Name)==0){p::types::Name typed=&fake##Name;return reinterpret_cast<std::uintptr_t>(typed);}
    FAKE_EXPORTS(FIND_FAKE)
#undef FIND_FAKE
    throw std::runtime_error("resolver received unreviewed export");
}
static int __cdecl enter(void* context,const char* name) {
    check(context==gate,"gate context changed");++gate->enters;trace.emplace_back(std::string("enter:")+name);
    if(gate->throwEnter)throw std::runtime_error("enter failure before acquisition");
    if(gate->deny)return 7;
    gate->mutex.lock();
    if(gate->depth==static_cast<int>(gate->names.size())){gate->mutex.unlock();return 9;}
    gate->names[gate->depth]=name;++gate->depth;if(gate->depth>gate->peak)gate->peak=gate->depth;return 0;
}
static void __cdecl leave(void* context,const char* name) {
    check(context==gate && gate->depth>0 && std::strcmp(gate->names[gate->depth-1],name)==0,"leave without matching successful enter");
    ++gate->leaves;--gate->depth;gate->mutex.unlock();trace.emplace_back(std::string("leave:")+name);
    if(gate->throwLeave)throw std::runtime_error("leave failure after release");
}
static int __cdecl before(void* context,std::uint64_t value,const std::uint8_t* data,std::uint32_t size) {
    check(context==hooks && gate->depth==1 && value==world && data==input && size==count,"before hook args/gate changed");
    ++hooks->before;trace.emplace_back("before");
    if(hooks->throwBefore)throw std::runtime_error("before failure");return hooks->denyBefore?1:0;
}
static int __cdecl after(void* context,std::uint64_t value,std::uint32_t dt,std::int32_t* result,std::int32_t code) {
    check(context==hooks && gate->depth==1 && value==world && dt==count && result==&signedResult &&
          *result==-1234567 && code==-108,"after hook guessed frame or changed raw arguments");
    ++hooks->after;trace.emplace_back("after");
    if(hooks->throwAfter)throw std::runtime_error("after failure");return hooks->denyAfter?1:0;
}
template<class Function>static Function api(const char* name) {
    const auto address=p::lookup(name);check(address!=0,"reviewed wrapper missing");return reinterpret_cast<Function>(address);
}
static void bindingAndNames(bool withHooks) {
    check(p::lookup("SimInit")==0 && p::module()==nullptr && p::BAProxySimInit(true)==-1,"unbound proxy executed native call");
    const p::Callbacks callbacks{gate,enter,leave};
    check(p::bind(nullptr,resolve,callbacks)==-1 && p::bind(module,nullptr,callbacks)==-1 &&
          p::bind(module,resolve,{gate,nullptr,leave})==-1 && p::bind(module,resolve,{gate,enter,nullptr})==-1,
          "incomplete binding accepted");
    check(resolved.empty(),"invalid binding resolved native functions");
    missing="SimGetSystemIDAttributes";
    check(p::bind(module,resolve,callbacks)==-1 && p::lookup("SimInit")==0,"partial binding was published");
    missing=nullptr;throwResolver=true;
    check(p::bind(module,resolve,callbacks)==-1 && p::lookup("SimInit")==0,"resolver exception escaped/published binding");
    throwResolver=false;resolved.clear();
    const p::Hooks optional=withHooks?p::Hooks{hooks,before,after}:p::Hooks{};
    check(p::bind(module,resolve,callbacks,optional)==0 && resolved.size()==24 && p::module()==module,"exact binding failed");
    auto sorted=resolved;std::sort(sorted.begin(),sorted.end());
    check(std::adjacent_find(sorted.begin(),sorted.end())==sorted.end(),"export resolved more than once");
    check(p::bind(module,resolve,callbacks)==-1 && resolved.size()==24,"binding changed after publication");
    for(const char* name:{"SimMakeSimDebugInfoFrame","SimGetSimDebugInfoFrameBuffer","Init","siminit","SimInit ","", "SimUnknown"})
        check(p::lookup(name)==0,"unknown/unrecovered alias accepted");
    check(p::lookup(nullptr)==0,"null name accepted");
    check(p::lookup(reinterpret_cast<const char*>(std::uintptr_t(1)))==0 &&
          p::lookup(reinterpret_cast<const char*>(std::uintptr_t(65535)))==0,"ordinal treated as export-name pointer");
    std::vector<std::uintptr_t> wrappers;
#define CHECK_WRAPPER(Name) wrappers.push_back(p::lookup(#Name));
    FAKE_EXPORTS(CHECK_WRAPPER)
#undef CHECK_WRAPPER
    std::sort(wrappers.begin(),wrappers.end());
    check(wrappers.front()!=0 && std::adjacent_find(wrappers.begin(),wrappers.end())==wrappers.end(),
          "distinct native signatures shared a wrapper address");
}
static void allTypedForwarding() {
    check(api<p::types::SimInit>("SimInit")(true)==101,"init result changed");
    expectedInit=false;check(api<p::types::SimInit>("SimInit")(false)==101,"false bool changed");expectedInit=true;
    check(api<p::types::SimDestroy>("SimDestroy")()==102,"destroy result changed");
    check(api<p::types::SimSetLogCallBack>("SimSetLogCallBack")(logCallback)==103,"callback result changed");
    check(api<p::types::SimSetLogFlags>("SimSetLogFlags")(count)==104,"flags result changed");
    check(api<p::types::SimCreateWorld>("SimCreateWorld")(input,count,&worldResult)==105 && worldResult==world,"create result changed");
    check(api<p::types::SimDestroyWorld>("SimDestroyWorld")(world)==106,"destroy world result changed");
    check(api<p::types::SimProcessMsg>("SimProcessMsg")(world,input,count)==107,"process result changed");
    check(api<p::types::SimStep>("SimStep")(world,count,&signedResult)==-108 && signedResult==-1234567,"step signed byref/result changed");
    check(api<p::types::SimMakeSimFrame>("SimMakeSimFrame")(world,count,&unsignedResult)==109 && unsignedResult==0xabcdef01,"frame uint byref changed");
    check(api<p::types::SimGetSimFrameBuffer>("SimGetSimFrameBuffer")(world,output)==110 && output[0]==10,"frame buffer result changed");
    check(api<p::types::SimGetLabelsFrameBufferSize>("SimGetLabelsFrameBufferSize")(world,count,&unsignedResult)==111 && unsignedResult==11,"label size result changed");
    check(api<p::types::SimGetLabelsFrameBuffer>("SimGetLabelsFrameBuffer")(world,count,output)==112 && output[0]==12,"label buffer result changed");
    check(api<p::types::SimGetConnectedPlayersSizeAndVersion>("SimGetConnectedPlayersSizeAndVersion")(world,&signedResult,&versionResult)==113 &&
          signedResult==-13 && versionResult==-1313,"player size/version signed byrefs changed");
    check(api<p::types::SimGetConnectedPlayers>("SimGetConnectedPlayers")(world,output)==114 && output[0]==14,"players result changed");
    check(api<p::types::SimGetMapFrameSize>("SimGetMapFrameSize")(world,&signedResult)==115 && signedResult==-15,"map signed size changed");
    check(api<p::types::SimGetMapFrame>("SimGetMapFrame")(world,output)==116 && output[0]==16,"map result changed");
    check(api<p::types::SimCrashOnCommand>("SimCrashOnCommand")()==117,"crash command fake result changed");
    check(api<p::types::SimGetDebugDrawCommandBufferCount>("SimGetDebugDrawCommandBufferCount")(world,&unsignedResult)==118 && unsignedResult==18,"debug count result changed");
    check(api<p::types::SimGetDebugDrawCommandBufferSize>("SimGetDebugDrawCommandBufferSize")(world,&unsignedResult,index)==119 && unsignedResult==19,"debug size result changed");
    check(api<p::types::SimGetDebugDrawCommandBuffer>("SimGetDebugDrawCommandBuffer")(world,output,index)==120 && output[0]==20,"debug buffer result changed");
    check(api<p::types::SimClearAllDebugDrawCommandBuffers>("SimClearAllDebugDrawCommandBuffers")(world)==121,"debug clear result changed");
    check(api<p::types::SimSetDebugDrawCommandListsActive>("SimSetDebugDrawCommandListsActive")(world,count,lists)==122,"debug list result changed");
    check(api<p::types::SimGetSystemCount>("SimGetSystemCount")(world,&unsignedResult)==123 && unsignedResult==23,"system count result changed");
    check(api<p::types::SimGetSystemIDAttributes>("SimGetSystemIDAttributes")(world,output,count)==124 && output[0]==24,"system attributes result changed");
    check(gate->depth==0 && gate->enters==26 && gate->leaves==26 && originals.size()==26,"forwarding call/gate conservation failed");
}
static void deniedAndExceptions() {
    const auto init=api<p::types::SimInit>("SimInit");const auto destroy=api<p::types::SimDestroy>("SimDestroy");
    const auto baseOriginals=originals.size();const auto baseLeaves=gate->leaves;
    gate->deny=true;check(init(true)==-1,"denied gate entered native");gate->deny=false;
    check(originals.size()==baseOriginals && gate->leaves==baseLeaves && gate->depth==0,"denial called original/leave");
    gate->throwEnter=true;check(init(true)==-1,"enter exception crossed native ABI");gate->throwEnter=false;
    check(originals.size()==baseOriginals && gate->leaves==baseLeaves && gate->depth==0,"failed enter called original/leave");
    throwOriginal=true;check(destroy()==-1,"original C++ exception crossed native ABI");throwOriginal=false;
    check(gate->leaves==baseLeaves+1 && gate->depth==0,"original exception did not leave once");
    gate->throwLeave=true;check(init(true)==-1,"leave exception crossed native ABI");gate->throwLeave=false;
    check(gate->leaves==baseLeaves+2 && gate->depth==0,"throwing leave ran twice or retained gate");
    reenterOriginal=true;check(init(true)==101,"reentrant wrapper failed");reenterOriginal=false;
    check(gate->depth==0 && gate->peak==2,"proxy imposed nonrecursive execution gate");
}
static void optionalHooks(bool enabled) {
    const auto process=api<p::types::SimProcessMsg>("SimProcessMsg");const auto step=api<p::types::SimStep>("SimStep");
    if(!enabled){check(hooks->before==0 && hooks->after==0,"default binding invoked hooks");return;}
    trace.clear();check(process(world,input,count)==107,"before hook skipped original");
    check(trace==std::vector<std::string>{"enter:SimProcessMsg","before","original:SimProcessMsg","leave:SimProcessMsg"},"before hook order changed");
    trace.clear();check(step(world,count,&signedResult)==-108,"after hook changed original status");
    check(trace==std::vector<std::string>{"enter:SimStep","original:SimStep","after","leave:SimStep"},"after hook order changed");
    const auto originalCount=originals.size();const auto leaves=gate->leaves;
    hooks->denyBefore=true;check(process(world,input,count)==-1,"before denial accepted");hooks->denyBefore=false;
    hooks->throwBefore=true;check(process(world,input,count)==-1,"before exception escaped");hooks->throwBefore=false;
    check(originals.size()==originalCount && gate->leaves==leaves+2 && gate->depth==0,"before failure called native/failed leave");
    hooks->denyAfter=true;check(step(world,count,&signedResult)==-1,"after denial accepted");hooks->denyAfter=false;
    hooks->throwAfter=true;check(step(world,count,&signedResult)==-1,"after exception escaped");hooks->throwAfter=false;
    check(originals.size()==originalCount+2 && gate->leaves==leaves+4 && gate->depth==0,"after failure duplicated/skipped step or leave");
}
int main(int argc,char** argv) {
    try {
        const bool enabled=argc==2 && std::strcmp(argv[1],"--hooks")==0;
        check(argc==1 || enabled,"unsupported test option");Gate owner;HookState hookState;gate=&owner;hooks=&hookState;
        bindingAndNames(enabled);allTypedForwarding();deniedAndExceptions();optionalHooks(enabled);
        check(gate->depth==0 && gate->enters==gate->leaves+2,"final gate conservation failed");
        std::cout<<"native API proxy: 24 typed exports PASS; gates/exceptions/reentrancy/names PASS; hooks="
                 <<(enabled?"enabled":"default-off")<<'\n';return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
