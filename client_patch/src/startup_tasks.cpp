#pragma once
// Owned opt-in diagnostic. Never complete/cancel/wait tasks or drive a new pump.
// Original calls stay OUTSIDE observer catch blocks, including Unity Exec.
namespace ba_startup_tasks {
using ba::Obj;
static constexpr size_t taskCount=50, rootCount=53;
static constexpr ULONGLONG windowMs=240000;
static std::atomic<DWORD> ownerThread{0};
static std::atomic<bool> foreignThread{false};
static std::array<uint32_t,rootCount> roots{};
static std::array<bool,taskCount> captured{};
static uint32_t (*newRoot)(Obj,bool)=nullptr;
static Obj (*target)(uint32_t)=nullptr;
static void (*freeRoot)(uint32_t)=nullptr;
static bool active=false, taskLayoutChecked=false, inPump=false;
static unsigned phase=0, events=0, pumps=0, tableReturns=0;
static ULONGLONG started=0, nextSample=0;
static const char* labels[]={"PlayerInputActionTable","InputActionPanelMappingTable",
    "OptionSettingTable","CursorTable","UIButtonAudioTable","UIContainerAudioTable",
    "UIDragAndDropAudioTable","UIAnimatorAudioTable","PlaySoundNodeAudioTable",
    "UIPrefabTable","MenuUIStateTable","IngameMusicTrackTable"};

static bool enabled() noexcept {
    // Disabled hot path performs no engine lookup, inspection, handles or I/O.
    static const bool value=[]() noexcept {
        try {
            if(!ba::flag(L"-startup-tasks-audit") || !ba::localMenu())return false;
            const auto key=ba::argument(L"-local-profile=");
            if(key.size()<13 || key.size()>46 || key.compare(0,12,"nativestest_")!=0)return false;
            for(char c:key)if(!((c>='a'&&c<='z') || (c>='0'&&c<='9') || c=='_' || c=='-'))return false;
            return true;
        } catch(...) {return false;}
    }();
    return value;
}
template<class F> static F original(uintptr_t rva) {
    // Imported by this exact loaded image; no diagnostic API/error can replace
    // an original call or its native/managed exception propagation.
    static const auto image=reinterpret_cast<uintptr_t>(GetModuleHandleW(L"GameAssembly.dll"));
    return reinterpret_cast<F>(image+rva);
}
static unsigned liveRoots() {
    unsigned count=0;for(auto h:roots)if(h)++count;return count;
}
static void release() {
    // Disable reads first. Only invoked on the established original thread.
    active=false;
    for(auto& h:roots)if(h){const auto old=h;h=0;freeRoot(old);}
}
static void event(const char* kind,ULONGLONG tick,int index=-1,ULONGLONG entry=0,
                  Obj object=nullptr,Obj method=nullptr) {
    if(++events>1600)throw std::runtime_error("startup observer event budget");
    ba::log("STARTUP TASKS {\"event\":\"%s\",\"tick\":%llu,\"entry\":%llu,\"seq\":%u,\"thread\":%lu,\"phase\":%u,\"index\":%d,\"object\":\"%p\",\"method\":\"%p\",\"roots\":%u,\"pump\":%u}",
        kind,tick,entry,events,GetCurrentThreadId(),phase,index,object,method,liveRoots(),pumps);
}
static void root(size_t index,Obj value) {
    if(index>=roots.size() || roots[index] || !value)throw std::runtime_error("startup observer root contract");
    const auto h=newRoot(value,false);
    if(!h)throw std::runtime_error("startup observer root unavailable");
    roots[index]=h;
}
static Obj rooted(size_t index) {
    Obj value=roots[index]?target(roots[index]):nullptr;
    if(!value)throw std::runtime_error("startup observer target missing");
    return value;
}
static void checkTask(Obj task) {
    if(taskLayoutChecked)return;
    auto f=ba::field(task,"m_stateFlags");
    if(ba::api<size_t(*)(Obj)>("il2cpp_field_get_offset")(f)!=0x38)
        throw std::runtime_error("startup Task flags layout mismatch");
    taskLayoutChecked=true;
}
static void snapshot(ULONGLONG tick) {
    // Each original get_Status is a separate memory-barriered observation,
    // not one atomic snapshot. No Exception/Result/IsCompleted accessors.
    char states[256]{};size_t length=0;
    for(size_t i=0;i<taskCount;++i) {
        int status=-1;
        if(captured[i]) {
            Obj task=rooted(i);checkTask(task);
            status=original<int(*)(Obj,Obj)>(0x3636750)(task,nullptr);
            if(status<0 || status>7)throw std::runtime_error("startup Task status mismatch");
        }
        const int n=_snprintf_s(states+length,sizeof(states)-length,_TRUNCATE,"%s%d",i?",":"",status);
        if(n<=0)throw std::runtime_error("startup status buffer exhausted");length+=static_cast<size_t>(n);
    }
    if(++events>1600)throw std::runtime_error("startup observer event budget");
    ba::log("STARTUP TASKS {\"event\":\"snapshot\",\"tick\":%llu,\"seq\":%u,\"thread\":%lu,\"phase\":%u,\"roots\":%u,\"pump\":%u,\"status\":[%s]}",
        tick,events,GetCurrentThreadId(),phase,liveRoots(),pumps,states);
}
static void end(const char* reason,ULONGLONG tick) {
    release();
    ba::log("STARTUP TASKS {\"event\":\"end\",\"tick\":%llu,\"seq\":%u,\"thread\":%lu,\"phase\":%u,\"roots\":%u,\"pump\":%u,\"reason\":\"%s\",\"table_returns\":%u}",
        tick,++events,GetCurrentThreadId(),phase,liveRoots(),pumps,reason,tableReturns);
}
static void failed() noexcept {
    try {end("observer_error",GetTickCount64());}catch(...) {active=false;}
}
static bool owned() noexcept {
    if(!enabled())return false;
    const auto owner=ownerThread.load();
    if(!owner)return false;
    if(owner!=GetCurrentThreadId()){foreignThread=true;return false;}
    if(!active)return false;
    try {
        if(foreignThread.load())throw std::runtime_error("startup observer thread changed");
        if(GetTickCount64()-started>=windowMs){end("deadline",GetTickCount64());return false;}
        return true;
    }catch(...){failed();return false;}
}
static void begin(Obj tables,ULONGLONG tick) noexcept {
    if(!enabled())return;
    DWORD empty=0;
    if(!ownerThread.compare_exchange_strong(empty,GetCurrentThreadId())) {
        if(owned())failed();return;
    }
    try {
        ba::init();
        newRoot=ba::api<uint32_t(*)(Obj,bool)>("il2cpp_gchandle_new");
        target=ba::api<Obj(*)(uint32_t)>("il2cpp_gchandle_get_target");
        freeRoot=ba::api<void(*)(uint32_t)>("il2cpp_gchandle_free");
        started=tick;phase=1;active=true;root(52,tables);
        event("premenu_enter",tick,-1,0,tables);
        ba::log("STARTUP TASKS contract=BA_RESURRECTION_STARTUP_TASKS_V1 rootsMax=53 windowMs=240000 tables=12 other=37 aggregate=1");
    }catch(...){failed();}
}
static void tableEnter(size_t index,ULONGLONG tick,Obj asset,Obj method) noexcept {
    if(!owned())return;
    try {
        if(phase!=1 || index>=12 || captured[index])throw std::runtime_error("startup dispatch order mismatch");
        event("table_enter",tick,static_cast<int>(index),0,asset,method);
    }catch(...){failed();}
}
static void tableReturn(size_t index,Obj task,ULONGLONG entry,ULONGLONG returned,Obj method) noexcept {
    if(!owned())return;
    try {
        root(index,task);captured[index]=true;++tableReturns;
        event("table_return",returned,static_cast<int>(index),entry,task,method);
        ba::log("STARTUP TASKS table=%zu label=%s",index,labels[index]);
    }catch(...){failed();}
}
static void batchReturn(bool other,Obj list,ULONGLONG entry,ULONGLONG returned) noexcept {
    if(!owned())return;
    try {
        const size_t listIndex=other?51:50;root(listIndex,list);list=rooted(listIndex);
        if(ba::api<size_t(*)(Obj)>("il2cpp_field_get_offset")(ba::field(list,"_items"))!=0x10 ||
           ba::api<size_t(*)(Obj)>("il2cpp_field_get_offset")(ba::field(list,"_size"))!=0x18)
            throw std::runtime_error("startup Task list layout mismatch");
        const int expected=other?37:12;
        if(ba::read<int>(list,0x18)!=expected)throw std::runtime_error("startup Task list count mismatch");
        Obj items=ba::read<Obj>(list,0x10);
        if(!items || ba::read<uintptr_t>(items,0x18)<static_cast<uintptr_t>(expected) ||
           ba::read<uintptr_t>(items,0x18)>64)throw std::runtime_error("startup Task array bound mismatch");
        for(int i=0;i<expected;++i) {
            Obj task=ba::read<Obj>(items,0x20+sizeof(Obj)*i);
            if(other){root(12+i,task);captured[12+i]=true;}
            else if(!captured[i] || rooted(i)!=task)throw std::runtime_error("startup premenu Task identity mismatch");
        }
        phase=other?4:2;event(other?"other_return":"premenu_return",returned,-1,entry,list);
        snapshot(GetTickCount64());
    }catch(...){failed();}
}
static void stage(bool aggregate,Obj argument,ULONGLONG tick) noexcept {
    if(!owned())return;
    try {
        if(phase!=(aggregate?4u:2u) || argument!=rooted(aggregate?50:52))
            throw std::runtime_error("startup original batch input identity mismatch");
        phase=aggregate?5:3;event(aggregate?"whenall_enter":"other_enter",tick,-1,0,argument);
    }catch(...){failed();}
}
static void aggregateReturn(Obj task,ULONGLONG entry,ULONGLONG returned) noexcept {
    if(!owned())return;
    try {root(49,task);captured[49]=true;phase=6;event("whenall_return",returned,-1,entry,task);snapshot(GetTickCount64());}
    catch(...){failed();}
}
static bool pumpBefore(Obj context,ULONGLONG tick) noexcept {
    if(!owned())return false;
    try {
        if(inPump)throw std::runtime_error("startup observer nested pump");
        inPump=true;++pumps;
        if(tick<nextSample)return false;
        nextSample=tick+1000;event("pump_enter",tick,-1,0,context);snapshot(GetTickCount64());return true;
    }catch(...){failed();return false;}
}
static void pumpAfter(bool sampled,ULONGLONG entry,ULONGLONG returned) noexcept {
    if(!enabled() || ownerThread.load()!=GetCurrentThreadId())return;
    if(!active && !sampled)return;
    try {
        inPump=false;
        // Startup-ready can run INSIDE original Exec. Still pair its entry after
        // root release; no ended-object reads are allowed.
        if(sampled)event("pump_return",returned,-1,entry);
        if(active && sampled)snapshot(GetTickCount64());
    }catch(...){failed();}
}
static void ready() noexcept {
    if(!owned())return;
    try {phase=7;snapshot(GetTickCount64());end("startup_ready",GetTickCount64());}
    catch(...){failed();}
}
static Obj table(size_t index,Obj asset,Obj method) {
    const auto entry=GetTickCount64();tableEnter(index,entry,asset,method);
    Obj result=original<Obj(*)(Obj,Obj)>(0x121d0d0)(asset,method);
    const auto returned=GetTickCount64();tableReturn(index,result,entry,returned,method);return result;
}
}
#define STARTUP_TABLE(N) extern "C" __declspec(dllexport) void* OfflineStartupTable##N(void* asset,void* method) {return ba_startup_tasks::table(N,asset,method);}
STARTUP_TABLE(0) STARTUP_TABLE(1) STARTUP_TABLE(2) STARTUP_TABLE(3)
STARTUP_TABLE(4) STARTUP_TABLE(5) STARTUP_TABLE(6) STARTUP_TABLE(7)
STARTUP_TABLE(8) STARTUP_TABLE(9) STARTUP_TABLE(10) STARTUP_TABLE(11)
#undef STARTUP_TABLE
extern "C" __declspec(dllexport) void* OfflineStartupPreMenu(void* tables,void* method) {
    const auto entry=GetTickCount64();ba_startup_tasks::begin(tables,entry);
    auto result=ba_startup_tasks::original<void*(*)(void*,void*)>(0x3e19cd0)(tables,method);
    const auto returned=GetTickCount64();ba_startup_tasks::batchReturn(false,result,entry,returned);return result;
}
extern "C" __declspec(dllexport) void* OfflineStartupOther(void* tables,void* method) {
    const auto entry=GetTickCount64();ba_startup_tasks::stage(false,tables,entry);
    auto result=ba_startup_tasks::original<void*(*)(void*,void*)>(0x3e1a340)(tables,method);
    const auto returned=GetTickCount64();ba_startup_tasks::batchReturn(true,result,entry,returned);return result;
}
extern "C" __declspec(dllexport) void* OfflineStartupWhenAll(void* list,void* method) {
    const auto entry=GetTickCount64();ba_startup_tasks::stage(true,list,entry);
    auto result=ba_startup_tasks::original<void*(*)(void*,void*)>(0x363e2f0)(list,method);
    const auto returned=GetTickCount64();ba_startup_tasks::aggregateReturn(result,entry,returned);return result;
}
extern "C" __declspec(dllexport) void OfflineStartupPump(void* context,void* method) {
    const auto entry=GetTickCount64();const bool sampled=ba_startup_tasks::pumpBefore(context,entry);
    ba_startup_tasks::original<void(*)(void*,void*)>(0x5093060)(context,method);
    const auto returned=GetTickCount64();ba_startup_tasks::pumpAfter(sampled,entry,returned);
}
