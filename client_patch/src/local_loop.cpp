#pragma once
// Include after offline_client.cpp's ba helpers. This file performs no patching.
// Static evidence: ../metadata/local-runtime-notes.txt and local-loop-hooks.json.
// Startup sequence on Unity's main thread:
//   OfflinePrepareLocalGame(server);  // before CreateGame queues JoinArmyCommand
//   ... create world / synthesize joined game, set state Simulating ...
//   OfflineSetLocalReady(true);       // caller explicitly authorizes ticking
// The update hook never contacts a server, including before preparation.
#include <atomic>

namespace ba_local {
using ba::Obj;
static uint32_t serverRoot = 0;
// Up to three local AI integrations share the human world. Only the local
// match coordinator may register them, before ticking, and release after shutdown.
static std::array<uint32_t,3> peerRoots{};
static size_t peerCount=0;
static std::atomic<bool> accepting{false}, ready{false}, failed{false};
static DWORD updateThread = 0;
static ULONGLONG previousTime = 0;
static uint64_t submittedTicks = 0;
static int lastSubmittedFrame = -1;
static unsigned accumulatedMs = 0;
static SRWLOCK queueLock = SRWLOCK_INIT;

struct QueueLock {
    QueueLock() { AcquireSRWLockExclusive(&queueLock); }
    ~QueueLock() { ReleaseSRWLockExclusive(&queueLock); }
    QueueLock(const QueueLock&) = delete;
    QueueLock& operator=(const QueueLock&) = delete;
};
struct Root {
    uint32_t handle;
    explicit Root(Obj value) : handle(value ? ba::api<uint32_t(*)(Obj,bool)>("il2cpp_gchandle_new")(value,false) : 0) {}
    ~Root() { if(handle) ba::api<void(*)(uint32_t)>("il2cpp_gchandle_free")(handle); }
    Obj get() const { return handle ? ba::api<Obj(*)(uint32_t)>("il2cpp_gchandle_get_target")(handle) : nullptr; }
    Root(const Root&) = delete;
    Root& operator=(const Root&) = delete;
};
static Obj server() {
    return serverRoot ? ba::api<Obj(*)(uint32_t)>("il2cpp_gchandle_get_target")(serverRoot) : nullptr;
}
static bool isTarget(Obj candidate) {
    return accepting.load() && !failed.load() && candidate && candidate == server();
}
static Obj peer(size_t index) {
    return index<peerCount ? ba::api<Obj(*)(uint32_t)>("il2cpp_gchandle_get_target")(peerRoots[index]) : nullptr;
}
static bool isPeer(Obj candidate) {
    if(!candidate)return false;
    for(size_t i=0;i<peerCount;++i)if(candidate==peer(i))return true;
    return false;
}
static bool isProducer(Obj candidate) {
    return accepting.load() && !failed.load() && candidate && (candidate==server() || isPeer(candidate));
}
static void attachPeer(Obj candidate) {
    if(GetCurrentThreadId()!=updateThread || !isTarget(server()) || ready.load() || peerCount>=peerRoots.size() || isPeer(candidate) ||
       !candidate || candidate==server() || ba::read<Obj>(candidate,0x140) ||
       !ba::read<Obj>(candidate,0x180) || !ba::read<Obj>(candidate,0x188))
        throw std::runtime_error("local AI input ownership mismatch");
    const auto handle=ba::api<uint32_t(*)(Obj,bool)>("il2cpp_gchandle_new")(candidate,false);
    if(!handle)throw std::runtime_error("local AI root allocation failed");
    peerRoots[peerCount++]=handle;
}
static void detachPeers() {
    if(GetCurrentThreadId()!=updateThread || accepting.load() || ready.load())
        throw std::runtime_error("local AI input still active during release");
    for(size_t i=0;i<peerCount;++i){ba::api<void(*)(uint32_t)>("il2cpp_gchandle_free")(peerRoots[i]);peerRoots[i]=0;}
    peerCount=0;
}
static void fail(const char* where,const std::exception& exception) {
    ready.store(false); accepting.store(false); failed.store(true);
    ba::log("Offline loop stopped in %s: %s",where,exception.what());
}
static Obj invokeMethod(Obj method,Obj instance,void** args) {
    if(!method) throw std::runtime_error("local loop method resolution failed");
    Obj exception=nullptr;
    Obj result=ba::api<Obj(*)(Obj,Obj,void**,Obj*)>("il2cpp_runtime_invoke")(method,instance,args,&exception);
    if(exception) {
        char text[8192]={};
        ba::api<void(*)(Obj,char*,int)>("il2cpp_format_exception")(exception,text,sizeof(text));
        ba::log("Offline loop managed exception: %s",text);
        char stack[16384]={};ba::api<void(*)(Obj,char*,int)>("il2cpp_format_stack_trace")(exception,stack,sizeof(stack));
        ba::log("Managed stack: %s",stack);
        throw std::runtime_error("local loop managed invocation");
    }
    return result;
}
static int count(Obj queue) {
    if(!queue) throw std::runtime_error("offline input queue missing");
    Root boxed(ba::call(queue,"get_Count"));
    if(!boxed.get()) throw std::runtime_error("queue count returned null");
    return *ba::api<int*(*)(Obj)>("il2cpp_object_unbox")(boxed.get());
}
static void enqueue(Obj queue,Obj value) {
    if(!queue || !value) throw std::runtime_error("null offline input queue/value");
    QueueLock lock;
    void* args[]={value}; // reference args are objects; value-type args are addresses
    ba::call(queue,"Enqueue",1,args);
}
static Obj dequeue(Obj queue) {
    QueueLock lock;
    return count(queue) ? ba::call(queue,"Dequeue") : nullptr;
}
static void addItem(Obj repeated,Obj item) {
    if(!repeated || !item) throw std::runtime_error("null repeated-field item");
    // RepeatedField<T> has both Add(T) and Add(IEnumerable<T>) with one argument.
    // Name + parameter-count lookup alone may select the wrong overload.
    Obj itemClass=ba::klass(item), selected=nullptr;
    void* iter=nullptr;
    while(Obj method=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(ba::klass(repeated),&iter)) {
        if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(method),"Add") != 0) continue;
        if(ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(method) != 1) continue;
        Obj paramType=ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(method,0);
        Obj paramClass=ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(paramType);
        if(paramClass && ba::api<bool(*)(Obj,Obj)>("il2cpp_class_is_assignable_from")(paramClass,itemClass)) {
            if(selected) throw std::runtime_error("ambiguous RepeatedField.Add overload");
            selected=method;
        }
    }
    if(!selected) throw std::runtime_error("RepeatedField.Add(T) unavailable");
    void* args[]={item}; invokeMethod(selected,repeated,args);
}
static Obj toProto(Obj command) {
    // Resolve the interface dispatch, including explicit implementation names.
    Obj contract=ba::find_class("Uncapped","ICommand");
    Obj method=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(contract,"ToProto",0);
    method=ba::api<Obj(*)(Obj,Obj)>("il2cpp_object_get_virtual_method")(command,method);
    return invokeMethod(method,command,nullptr);
}
static int collect(Obj gameServer,Obj message) {
    Root player(ba::make("GamePb","InputActionsByPlayer"));
    Obj identity=ba::read<Obj>(gameServer,0x1a8);
    if(!identity) throw std::runtime_error("offline PlayerGameHandle missing");
    ba::set<Obj>(player.get(),"playerHandle_",identity);
    Obj commands=ba::read<Obj>(gameServer,0x180), actions=ba::read<Obj>(gameServer,0x188);
    Obj playerActions=ba::get<Obj>(player.get(),"actions_");
    int actionCount=0;
    // Keep draining bounded if another producer floods a queue. Preserve the
    // original order: commands first, then already-serialized InputActions.
    while(actionCount < 256) {
        Root command(dequeue(commands)); if(!command.get()) break;
        Root action(toProto(command.get()));
        if(!action.get()) throw std::runtime_error("ICommand.ToProto returned null");
        if(ba_practice::active())ba_practice::input(gameServer,action.get());
        addItem(playerActions,action.get()); ++actionCount;
    }
    while(actionCount < 256) {
        Root action(dequeue(actions)); if(!action.get()) break;
        if(ba_practice::active())ba_practice::input(gameServer,action.get());
        if(isPeer(gameServer) && ba::flag(L"-practice-ai-smoke")) {
            Obj payload=ba::get<Obj>(action.get(),"action_");
            ba::log("Practice AI action: case=%d type=%s",ba::get<int>(action.get(),"actionCase_"),
                payload?ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(ba::klass(payload)):"null");
            if(payload && ba::klass(payload)==ba::find_class("GamePb","ExecuteCommand")) {
                Obj data=ba::get<Obj>(payload,"commandData_");Obj command=data?ba::get<Obj>(data,"commandData_"):nullptr;
                ba::log("Practice AI command: case=%d type=%s",data?ba::get<int>(data,"commandDataCase_"):-1,
                    command?ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(ba::klass(command)):"null");
            }
            const auto json=ba_catalog::utf8(ba::call(action.get(),"ToString"));
            const auto id=ba::get<uint64_t>(ba::get<Obj>(ba::get<Obj>(identity,"playerHandleWithName_"),"playerHandle_"),"steamId_");
            ba::log("Practice AI protobuf: %s",json.substr(0,8192).c_str());
            ba::log("Local AI owned action: identity=%llu frame=%d protobuf=%s",static_cast<unsigned long long>(id),ba::get<int>(message,"gameFrame_"),json.substr(0,8192).c_str());
        }
        addItem(playerActions,action.get()); ++actionCount;
    }
    if(actionCount) addItem(ba::get<Obj>(message,"playerInputActions_"),player.get());
    return actionCount;
}
static void tick(Obj gameServer,Obj simulation) {
    if(lastSubmittedFrame == 0x7fffffff) throw std::runtime_error("offline frame counter exhausted");
    const int nextFrame=lastSubmittedFrame+1;
    Root message(ba::make("GamePb","InputActions"));
    ba::set<int>(message.get(),"gameFrame_",nextFrame);
    ba::set<int>(message.get(),"debugFramesPerSecond_",20);
    ba::set<int>(message.get(),"debugGameTimeStepMs_",50);
    ba::set<float>(message.get(),"debugGameSpeed_",1.0f);
    ba::set<int>(message.get(),"spectatorCount_",0);
    const int humanActions=collect(gameServer,message.get());
    int aiActions=0;
    for(size_t i=0;i<peerCount;++i)aiActions+=collect(peer(i),message.get());
    const int actionCount=humanActions+aiActions;
    bool catchingUp=false;
    void* processArgs[]={message.get(),&catchingUp};
    ba::call(gameServer,"ProcessInputActions",2,processArgs);
    for(size_t i=0;i<peerCount;++i)ba::call(peer(i),"ProcessInputActions",2,processArgs);
    void* pushArgs[]={message.get()};
    ba::call(simulation,"PushSimMessage",1,pushArgs);
    lastSubmittedFrame=nextFrame;
    ++submittedTicks;
    if(submittedTicks==1 || submittedTicks%200==0 || actionCount)
        ba::log("Offline frame %d submitted; sim=%d actions=%d",nextFrame,ba::read<int>(simulation,0xa8),actionCount);
    if(aiActions)ba::log("Practice AI input frame=%d actions=%d separateIdentity=1",nextFrame,aiActions);
}
}

extern "C" __declspec(dllexport) void OfflinePrepareLocalGame(void* gameServer) {
    using namespace ba_local;
    try {
        ba::init(); accepting.store(false); ready.store(false);
        if(!gameServer) throw std::runtime_error("offline server missing");
        if(peerCount)throw std::runtime_error("previous local AI services have not shut down");
        // Invoke only while the prior local game/input producers are stopped.
        if(serverRoot) ba::api<void(*)(uint32_t)>("il2cpp_gchandle_free")(serverRoot);
        serverRoot=0;
        serverRoot=ba::api<uint32_t(*)(Obj,bool)>("il2cpp_gchandle_new")(gameServer,false);
        if(!ba::read<Obj>(gameServer,0x180) || !ba::read<Obj>(gameServer,0x188))
            throw std::runtime_error("game server input queues not initialized");
        { QueueLock lock; ba::call(ba::read<Obj>(gameServer,0x180),"Clear"); ba::call(ba::read<Obj>(gameServer,0x188),"Clear"); }
        updateThread=GetCurrentThreadId(); previousTime=GetTickCount64(); accumulatedMs=0;
        submittedTicks=0; lastSubmittedFrame=-1; failed.store(false); accepting.store(true);
        ba::log("Offline local input prepared for %p; ticking remains disabled",gameServer);
    } catch(const std::exception& e) { fail("prepare",e); }
}

extern "C" __declspec(dllexport) void OfflineSetLocalReady(bool enabled) {
    using namespace ba_local;
    try {
        ba::init(); ready.store(false); previousTime=GetTickCount64(); accumulatedMs=0;
        if(!enabled) return;
        Obj gameServer=server();
        if(!accepting.load() || failed.load() || !gameServer) throw std::runtime_error("offline game not prepared");
        if(GetCurrentThreadId()!=updateThread) throw std::runtime_error("offline readiness must be set on preparation thread");
        Obj simulation=ba::read<Obj>(gameServer,0x140);
        if(!simulation) throw std::runtime_error("offline simulation missing");
        int frame=ba::read<int>(gameServer,0x198), simFrame=ba::read<int>(simulation,0xa8);
        if(simFrame>frame) frame=simFrame;
        if(frame>lastSubmittedFrame) lastSubmittedFrame=frame;
        ready.store(true);
        ba::log("Offline ticking explicitly enabled at frame %d",lastSubmittedFrame);
    } catch(const std::exception& e) { fail("set ready",e); }
}

extern "C" __declspec(dllexport) void OfflineGameUpdate(void* gameServer,void*) {
    using namespace ba_local;
    try {
        ba::init();
        if(!isTarget(gameServer) || !ready.load()) return;
        if(GetCurrentThreadId()!=updateThread) throw std::runtime_error("offline update on unexpected thread");
        ULONGLONG now=GetTickCount64(), elapsed=now-previousTime; previousTime=now;
        Obj simulation=ba::read<Obj>(gameServer,0x140);
        if(!simulation || !ba::read<bool>(simulation,0x1a0) || !ba::read<Obj>(simulation,0x1a8)
            || ba::read<bool>(gameServer,0xd8) || ba::read<int>(gameServer,0x19c)!=1) {
            accumulatedMs=0; return;
        }
        unsigned delta=elapsed>200 ? 200 : static_cast<unsigned>(elapsed);
        accumulatedMs=accumulatedMs+delta>200 ? 200 : accumulatedMs+delta;
        for(unsigned emitted=0; accumulatedMs>=50 && emitted<4; ++emitted) {
            int simFrame=ba::read<int>(simulation,0xa8);
            // At most four outstanding messages: no unbounded worker backlog.
            if(static_cast<int64_t>(lastSubmittedFrame)-simFrame>=4) { accumulatedMs=50; break; }
            tick(gameServer,simulation); accumulatedMs-=50;
        }
    } catch(const std::exception& e) { fail("update",e); }
}

extern "C" __declspec(dllexport) void OfflineEnqueueCommand(void* gameServer,void* command,void*) {
    using namespace ba_local;
    try { ba::init(); if(isProducer(gameServer)) enqueue(ba::read<Obj>(gameServer,0x180),command); }
    catch(const std::exception& e) { fail("enqueue command",e); }
}

extern "C" __declspec(dllexport) void OfflineEnqueueAction(void* gameServer,void* action,void*) {
    using namespace ba_local;
    try { ba::init(); if(isProducer(gameServer)) enqueue(ba::read<Obj>(gameServer,0x188),action); }
    catch(const std::exception& e) { fail("enqueue action",e); }
}
