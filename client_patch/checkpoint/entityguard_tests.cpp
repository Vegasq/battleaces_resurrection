#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <stdexcept>
#include "entityguard.hpp"
#include "entityguard_hooks.hpp"

namespace {
void require(bool value,const char* text){if(!value)throw std::runtime_error(text);}
using ba_entity_guard::State;
using ba_entity_guard::Stats;
using ba_entity_guard::Kind;
using ba_entity_guard::Error;
using ba_entity_guard::Hooks;
constexpr uint64_t own=1,world=0x1000,master=0x2000,other=0x3000;
void observe(State& state,Kind kind,uint64_t registry,uint64_t caller=own) {
    if(state.enter(kind,registry,caller))state.leave();
}
Stats read(State& state,uint64_t caller=own) {
    Stats result;require(state.read(result,caller),"read refused");return result;
}
void policyTests() {
    { State state(own);observe(state,Kind::Create,master,2);
      require(read(state).error==0 && read(state).foreign==0,"inactive call changed default"); }
    { State state(own);require(state.bind(world,master,own) && state.reset(own),"bind/reset");
      observe(state,Kind::Create,master);observe(state,Kind::Create,other);observe(state,Kind::Hint,other);
      const auto before=read(state);require(before.creates==1 && before.otherCreates==1 && before.otherHints==1 && !before.hints,"registry identity counts");
      require(state.reset(own),"second epoch reset");const auto after=read(state);
      require(after.epoch==2 && after.creates==0 && after.otherHints==0,"epoch reset not per-frame");
      require(state.unbind(world,own),"unbind");observe(state,Kind::Create,master);
      require(!read(state).error && !read(state).master,"retired call changed binding");
      require(state.bind(world+1,master+1,own) && state.reset(own),"rematch bind"); }
    { State state(own);require(state.bind(world,master,own),"bind");observe(state,Kind::Create,master);
      require(read(state).error==static_cast<uint64_t>(Error::MissingReset),"missing reset admitted");
      require(state.unbind(world,own),"failed world cannot retire"); }
    { State state(own);require(state.bind(world,master,own) && state.reset(own),"bind");
      observe(state,Kind::Hint,master);const auto value=read(state);
      require(value.error==static_cast<uint64_t>(Error::DirectMasterHint) && value.hints==1,"direct master hint admitted");
      require(!state.reset(own),"failure reset away");require(state.unbind(world,own),"failure retirement"); }
    { State state(own);require(state.bind(world,master,own) && state.reset(own),"bind");
      for(uint64_t i=0;i<4094;++i)observe(state,Kind::Create,master);
      require(!read(state).error && read(state).creates==4094,"4094 refused");
      observe(state,Kind::Create,master);require(read(state).error==static_cast<uint64_t>(Error::CreationLimit),"4095 admitted"); }
    { State state(own);require(state.bind(world,master,own) && state.reset(own),"bind");
      observe(state,Kind::Create,master,2);const auto value=read(state);
      require(value.error==static_cast<uint64_t>(Error::ForeignThread) && value.foreign==1 && value.creates==0,"foreign mutation counted as owned"); }
    { State state(own);require(state.bind(world,master,own) && state.reset(own),"bind");
      require(state.enter(Kind::Hint,other,own),"outer callback");
      require(state.enter(Kind::Create,master,own),"nested callback");state.leave();state.leave();
      require(!read(state).error && read(state).depth==0 && read(state).creates==1,"nested depth/count"); }
    { State state(own);require(state.bind(world,master,own) && state.reset(own),"bind");
      require(state.enter(Kind::Create,master,own),"entry");Stats untouched;untouched.version=99;
      require(!state.read(untouched,own) && untouched.version==99,"partial in-flight output");
      require(!state.reset(own),"in-flight reset admitted");state.leave();
      require(state.unbind(world,own),"post-flight failure retirement"); }
    { State state(own);require(state.bind(world,master,own),"bind");
      require(!state.bind(world+1,master+1,own) && !state.unbind(world+1,own),"identity changed");
      require(state.unbind(world,own),"exact old identity not retained"); }
}
void storageTests() {
    using ba_entity_guard::storageError;
    constexpr uint64_t begin=0x10000,limit=0xfffff;
    require(storageError(0,0,0,0,0xffffffff)==Error::None,"initial empty registry refused");
    require(storageError(0,0,0,0,0)==Error::Storage,"empty freehead accepted");
    require(storageError(begin,begin+4*(limit-1),begin+4*limit,4*limit,0xffffffff)==Error::None,"last valid fresh index refused");
    require(storageError(begin,begin+4*limit,begin+4*limit,4*limit,0xffffffff)==Error::IndexLimit,"fresh null index admitted");
    require(storageError(begin,begin+4*(limit+1),begin+4*(limit+1),4*(limit+1),0xffffffff)==Error::IndexLimit,"fresh index wrap admitted");
    require(storageError(begin,begin+4*limit,begin+4*limit,4*limit,0xfff00001)==Error::None,"existing index reuse at ceiling refused");
    require(storageError(begin,begin+8,begin+8,8,0xfff00002)==Error::Storage,"freehead outside vector admitted");
    require(storageError(begin,begin+8,begin+8,4,0xffffffff)==Error::Storage,"vector crosses owned allocation");
    require(storageError(begin,begin-4,begin+8,8,0xffffffff)==Error::Storage,"reversed end admitted");
    require(storageError(begin,begin+8,begin+4,8,0xffffffff)==Error::Storage,"end exceeds capacity admitted");
    require(storageError(begin+1,begin+9,begin+9,8,0xffffffff)==Error::Storage,"unaligned header admitted");
    require(storageError(begin,begin+7,begin+8,8,0xffffffff)==Error::Storage,"fractional uint32 count admitted");
    require(storageError(begin,begin+8,begin+9,9,0xffffffff)==Error::Storage,"fractional uint32 capacity admitted");
    require(storageError(0,begin,begin,begin,0xffffffff)==Error::Storage,"partial null header admitted");
    require(storageError(begin,begin+8,begin+8,0,0xffffffff)==Error::Storage,"unowned range admitted");
    State state(own);state.unsupported(Error::IndexLimit);state.unsupported(Error::Storage);
    require(read(state).error==static_cast<uint64_t>(Error::IndexLimit),"storage failure not sticky");
}

// Completely authored functions: only ordinary x64 prologues match the native
// guard; their bodies return a fixture constant/hint or throw a fixture error.
// No Simulation.dll, game assets, process, or world is loaded by these tests.
struct Fixture {
    uint8_t* base=nullptr;
    std::array<RUNTIME_FUNCTION,2> functions_{};
    bool registered=false;
    explicit Fixture(bool throwing=false,bool badGuard=false) {
        base=static_cast<uint8_t*>(VirtualAlloc(nullptr,0x40000,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE));
        require(base!=nullptr,"fixture allocation");
        std::memcpy(base+Hooks::createRva,Hooks::createPrefix.data(),Hooks::createPrefix.size());
        auto cursor=base+Hooks::createRva+Hooks::createPrefix.size();
        if(throwing) {
            const uint8_t mov[]{0x48,0xb8};std::memcpy(cursor,mov,2);cursor+=2;
            const auto target=reinterpret_cast<uintptr_t>(&throwFixture);std::memcpy(cursor,&target,8);cursor+=8;
            const uint8_t call[]{0xff,0xd0};std::memcpy(cursor,call,2);cursor+=2;
        }else {const uint8_t value[]{0xb8,0x78,0x56,0x34,0x12};std::memcpy(cursor,value,5);cursor+=5;}
        const uint8_t finish[]{0x48,0x83,0xc4,0x28,0xc3};std::memcpy(cursor,finish,sizeof(finish));cursor+=sizeof(finish);
        const auto createEnd=static_cast<DWORD>(cursor-base);
        std::memcpy(base+Hooks::hintRva,Hooks::hintPrefix.data(),Hooks::hintPrefix.size());
        const uint8_t hintBody[]{0x8b,0xc2,0x48,0x83,0xc4,0x20,0x41,0x5f,0x41,0x5e,0x41,0x5c,0x5f,0x5e,0xc3};
        std::memcpy(base+Hooks::hintRva+Hooks::hintPrefix.size(),hintBody,sizeof(hintBody));
        if(badGuard)base[Hooks::createRva]^=1;
        const uint8_t createInfo[]{1,4,1,0,4,0x42,0,0};std::memcpy(base+0x3f000,createInfo,sizeof(createInfo));
        const uint8_t hintInfo[]{1,13,6,0,13,0x32,9,0xf0,7,0xe0,5,0xc0,3,0x70,2,0x60};
        std::memcpy(base+0x3f020,hintInfo,sizeof(hintInfo));
        functions_={{{static_cast<DWORD>(Hooks::createRva),createEnd,0x3f000},
                      {static_cast<DWORD>(Hooks::hintRva),static_cast<DWORD>(Hooks::hintRva+Hooks::hintPrefix.size()+sizeof(hintBody)),0x3f020}}};
        DWORD old=0;require(VirtualProtect(base,0x40000,PAGE_EXECUTE_READ,&old)!=0,"fixture executable");
        require(FlushInstructionCache(GetCurrentProcess(),base,0x40000)!=0,"fixture flush");
        require(RtlAddFunctionTable(functions_.data(),2,reinterpret_cast<DWORD64>(base))!=0,"fixture unwind register");registered=true;
    }
    ~Fixture(){if(registered)RtlDeleteFunctionTable(functions_.data());if(base)VirtualFree(base,0,MEM_RELEASE);}
    Fixture(const Fixture&)=delete;Fixture& operator=(const Fixture&)=delete;
    static void throwFixture(){throw std::runtime_error("owned fixture throw");}
};
Hooks* activeHooks=nullptr;
State* activeState=nullptr;
struct Scope {
    bool entered;
    Scope(Kind kind,void* registry):entered(activeState->enter(kind,reinterpret_cast<uint64_t>(registry),GetCurrentThreadId())){}
    ~Scope(){if(entered)activeState->leave();}
};
uint32_t __fastcall createShim(void* registry) {
    Scope scope(Kind::Create,registry);
    return reinterpret_cast<uint32_t (__fastcall*)(void*)>(activeHooks->createOriginal())(registry);
}
uint32_t __fastcall hintShim(void* registry,uint32_t value) {
    Scope scope(Kind::Hint,registry);
    return reinterpret_cast<uint32_t (__fastcall*)(void*,uint32_t)>(activeHooks->hintOriginal())(registry,value);
}
void unwindTests(Hooks& hooks) {
    const auto code=hooks.codeBase();
    for(const auto offset:{0u,4u,11u,21u}) {
        alignas(16) std::array<uint64_t,64> stack{};auto original=stack.data()+32;
        *original=0x123456789abcdef0;
        CONTEXT context{};context.Rip=code+0x100+offset;
        context.Rsp=reinterpret_cast<DWORD64>(original)-(offset>=4?40:0);
        DWORD64 imageBase=0;auto function=RtlLookupFunctionEntry(context.Rip,&imageBase,nullptr);
        require(function && imageBase==code,"create trampoline lookup");
        void* handler=nullptr;DWORD64 establisher=0;
        RtlVirtualUnwind(UNW_FLAG_NHANDLER,imageBase,context.Rip,function,&context,&handler,&establisher,nullptr);
        require(context.Rsp==reinterpret_cast<DWORD64>(original+1) && context.Rip==*original,"create trampoline stack unwind");
    }
    for(const auto offset:{0u,2u,3u,5u,15u}) {
        alignas(16) std::array<uint64_t,64> stack{};auto original=stack.data()+32;
        *original=0x123456789abcdef0;original[-1]=0x6161;original[-2]=0x7171;original[-3]=0x1212;
        CONTEXT context{};context.Rip=code+0x300+offset;
        const uint64_t pushed=offset>=5?3:offset>=3?2:offset>=2?1:0;
        context.Rsp=reinterpret_cast<DWORD64>(original-pushed);
        context.Rsi=offset>=2?0:0x6161;context.Rdi=offset>=3?0:0x7171;context.R12=offset>=5?0:0x1212;
        DWORD64 imageBase=0;auto function=RtlLookupFunctionEntry(context.Rip,&imageBase,nullptr);
        require(function && imageBase==code,"hint trampoline lookup");
        void* handler=nullptr;DWORD64 establisher=0;
        RtlVirtualUnwind(UNW_FLAG_NHANDLER,imageBase,context.Rip,function,&context,&handler,&establisher,nullptr);
        require(context.Rsp==reinterpret_cast<DWORD64>(original+1) && context.Rip==*original &&
                context.Rsi==0x6161 && context.Rdi==0x7171 && context.R12==0x1212,"hint trampoline nonvolatile unwind");
    }
}
void hookTests() {
    { Fixture fixture(false,true);Hooks hooks;
      require(!hooks.install(fixture.base,0x40000,reinterpret_cast<void*>(&createShim),reinterpret_cast<void*>(&hintShim)),"bad guard installed");
      require(!hooks.codeBase() && hooks.disable(),"bad guard allocated/left code"); }
    for(const bool throwing:{false,true}) {
        Fixture fixture(throwing);Hooks hooks;State state(GetCurrentThreadId());
        activeHooks=&hooks;activeState=&state;
        require(hooks.install(fixture.base,0x40000,reinterpret_cast<void*>(&createShim),reinterpret_cast<void*>(&hintShim)),"hook install");
        unwindTests(hooks);
        alignas(16) std::array<uint8_t,256> registry{};
        require(state.bind(0x8888,reinterpret_cast<uint64_t>(registry.data()),GetCurrentThreadId()) && state.reset(GetCurrentThreadId()),"fixture bind");
        using Create=uint32_t (__fastcall*)(void*);using Hint=uint32_t (__fastcall*)(void*,uint32_t);
        const auto create=reinterpret_cast<Create>(fixture.base+Hooks::createRva);
        if(throwing) {
            bool caught=false;try{create(registry.data());}catch(const std::runtime_error& error){caught=std::strcmp(error.what(),"owned fixture throw")==0;}
            require(caught,"real native exception lost across trampoline/shim");
        }else require(create(registry.data())==0x12345678,"real RAX result changed");
        auto value=read(state,GetCurrentThreadId());require(value.creates==1 && value.depth==0 && !value.error,"compiled shim observation/depth");
        require(reinterpret_cast<Hint>(fixture.base+Hooks::hintRva)(registry.data(),0xfedcba98)==0xfedcba98,"hint RAX changed");
        require(read(state,GetCurrentThreadId()).error==static_cast<uint64_t>(Error::DirectMasterHint),"actual direct hint not flagged");
        require(state.unbind(0x8888,GetCurrentThreadId()) && hooks.disable(),"owned hook cleanup");
        require(std::memcmp(fixture.base+Hooks::createRva,Hooks::createPrefix.data(),Hooks::createPrefix.size())==0 &&
                std::memcmp(fixture.base+Hooks::hintRva,Hooks::hintPrefix.data(),Hooks::hintPrefix.size())==0,"original bytes not restored");
    }
    activeHooks=nullptr;activeState=nullptr;
}
}
int main() {
    try{policyTests();storageTests();hookTests();std::puts("PASS:9 policy cases,16 storage controls,authored hook/RAX/exception/restore controls,18 trampoline unwind states");return 0;}
    catch(const std::exception& error){std::fprintf(stderr,"FAIL:%s\n",error.what());return 1;}
}
