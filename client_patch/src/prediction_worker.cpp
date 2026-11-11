// Explicit local-worker route and private movement controller bridge.
// Its sole optional GameAssembly CALL hook is excluded from the normal recipe.
#include <memory>
#include <mutex>
#include <set>
#include "../checkpoint/native_api_proxy.hpp"
#include "../checkpoint/native_rpc_backend.hpp"
#include "../checkpoint/native_worker_channel.hpp"
#include "prediction_movement.hpp"

namespace ba_prediction_worker {
namespace proxy=ba_native_api_proxy;
namespace backend=ba_native_rpc_backend;
namespace wire=ba_native_worker_wire;
namespace channel=ba_native_worker_channel;
using Obj=void*;

bool movementEnabled(){return ba::flag(L"-prediction-movement-experimental");}
static bool enabled(){return ba::flag(L"-prediction-native-worker-probe") || movementEnabled();}
struct State {
    std::recursive_mutex gate;
    std::unique_ptr<channel::Process> process;
    HMODULE selected=nullptr;
    bool failed=false,firstRequest=true,destroyed=false;
    unsigned depth=0;
    std::set<DWORD> threads;
    std::set<std::string> calls,lookups;
    uint64_t entered=0,left=0;
    uint64_t world=0,movementWorld=0;
    DWORD movementOwner=0;
    unsigned movementSlot=0;
    std::string movementMatch;
    bool movementStopped=false,movementEnding=false;
};
static State& state() {
    // Explicit SimDestroy shutdown runs outside the loader lock. At abnormal
    // process exit the retained Job handle closes with the process. A static
    // destructor must never join an I/O thread while DLL detach owns that lock.
    static State* lifetime=new State;return *lifetime;
}
static std::wstring option(const wchar_t* key) {
    std::wstring result;
    if(!ba_command_line::value(ba::arguments(),key,result) || result.empty())
        throw std::runtime_error("native worker probe path argument missing");
    return result;
}
static std::wstring modulePath(HMODULE module) {
    wchar_t path[32768];const DWORD length=GetModuleFileNameW(module,path,32768);
    if(!length || length>=32768)throw std::runtime_error("native module path unavailable");
    return std::wstring(path,length);
}
static bool simulation(HMODULE module) {
    const auto path=modulePath(module);const auto slash=path.find_last_of(L"\\/");
    return _wcsicmp(path.c_str()+(slash==std::wstring::npos?0:slash+1),L"Simulation.dll")==0;
}
static std::string exportName(Obj name) {
    if(!name)throw std::runtime_error("native export string missing");
    const int length=ba::read<int>(name,0x10);
    if(length<=0 || length>128)throw std::runtime_error("native export string length invalid");
    const auto chars=reinterpret_cast<const wchar_t*>(static_cast<const char*>(name)+0x14);
    std::string result;result.reserve(static_cast<size_t>(length));
    for(int i=0;i<length;++i) {
        if(chars[i]<0x21 || chars[i]>0x7e)throw std::runtime_error("native export name is not ASCII");
        result.push_back(static_cast<char>(chars[i]));
    }
    return result;
}
static int __cdecl enter(void* context,const char* name) {
    auto& s=*static_cast<State*>(context);s.gate.lock();
    try {
        const bool cleanup=strcmp(name,"SimDestroyWorld")==0 || strcmp(name,"SimDestroy")==0 ||
            strcmp(name,"SimSetLogCallBack")==0;
        if(s.failed && !cleanup){s.gate.unlock();return -1;}
        ++s.depth;++s.entered;
        const bool newThread=s.threads.insert(GetCurrentThreadId()).second;
        const bool newCall=s.calls.insert(name).second;
        if(newThread || newCall)
            ba::log("Native worker API observed: name=%s thread=%lu depth=%u calls=%llu",
                name,GetCurrentThreadId(),s.depth,static_cast<unsigned long long>(s.entered));
        return 0;
    } catch(...) {s.failed=true;--s.depth;s.gate.unlock();throw;}
}
static void logClosed(State& s) {
    const auto stats=s.process->stats();
    ba::log("Native worker closed: pid=%lu exit=%lu natural=%d reaped=%d ioJoined=%d abandoned=%llu requests=%llu responses=%llu",
        stats.pid,stats.exitCode,stats.naturalShutdown?1:0,stats.processReaped?1:0,stats.ioJoined?1:0,
        static_cast<unsigned long long>(stats.ioAbandoned),static_cast<unsigned long long>(stats.requests),
        static_cast<unsigned long long>(stats.responses));
}
static void __cdecl leave(void* context,const char* name) {
    auto& s=*static_cast<State*>(context);
    std::unique_lock<std::recursive_mutex> release(s.gate,std::adopt_lock);
    ++s.left;--s.depth;
    try {
        if(strcmp(name,"SimDestroy")==0 && s.destroyed && s.process) {
            s.process->shutdown(5000);logClosed(s);
        }
    } catch(const std::exception& error) {
        s.failed=true;ba::log("Native worker shutdown failed: %s",error.what());
    } catch(...) {
        s.failed=true;ba::log("Native worker shutdown failed with an unknown exception");
    }
}
static bool __cdecl request(void* context,uint8_t opcode,const wire::Bytes& bytes,wire::Response& response) {
    auto& s=*static_cast<State*>(context);
    try {
        const DWORD timeout=(s.firstRequest || opcode==5)?30000:5000;
        s.firstRequest=false;response=s.process->request(opcode,bytes,timeout);
        if(opcode==5 && response.result==0) {
            size_t at=0;const auto world=wire::read64(response.data,at);
            if(!world || at!=response.data.size() || s.world)throw std::runtime_error("worker created-world response differs");
            s.world=world;
        }
        if(opcode==6 && response.result==0)s.world=0;
        if(opcode==2 && response.result==0)s.destroyed=true;
        return true;
    } catch(const std::exception& error) {
        s.failed=true;ba::log("Native worker request failed: op=%u error=%s",unsigned(opcode),error.what());
        return false;
    }
}
static void setup(HMODULE selected) {
    auto& s=state();
    if(s.failed)throw std::runtime_error("native worker probe previously failed");
    if(s.selected) {
        if(s.selected!=selected)throw std::runtime_error("native worker module changed");
        return;
    }
    const auto python=option(L"-prediction-worker-python=");
    const auto root=option(L"-prediction-worker-module-root=");
    const auto heap=option(L"-prediction-worker-heap-helper=");
    const auto cooperative=option(L"-prediction-worker-cooperative=");
    const auto data=option(L"-prediction-worker-data-dir=");
    const DWORD attributes=GetFileAttributesW(data.c_str());
    if(attributes==INVALID_FILE_ATTRIBUTES || !(attributes&FILE_ATTRIBUTE_DIRECTORY))
        throw std::runtime_error("native worker probe requires a prepared private data directory");
    std::vector<std::wstring> args{L"-I",L"-S",L"-B",L"-u",L"-c",
        L"import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('client_patch.prediction_worker',run_name='__main__')",
        root,L"--original-dll",modulePath(selected),L"--heap-helper",heap,
        L"--cooperative",cooperative,L"--data-dir",data};
    const bool movementSmoke=ba::flag(L"-prediction-movement-smoke");
    const bool mobileSmoke=ba::flag(L"-prediction-mobile-correction-smoke");
    const bool serverAiObserve=ba::flag(L"-prediction-server-ai-observe");
    const bool serverAiMove=ba::flag(L"-prediction-server-ai-move-smoke");
    const bool closeFormation=ba_prediction_close_formation::enabled();
    if(ba_prediction_cohort::enabled())ba_prediction_cohort::requireFlags();
    if(ba_prediction_survivor::enabled()||ba_prediction_survivor::canonicalDeath())ba_prediction_survivor::requireFlags();
    if(closeFormation)ba_prediction_close_formation::requireFlags();
    if(serverAiMove && !serverAiObserve)
        throw std::runtime_error("server AI Move fixture requires its explicit state observer");
    if(serverAiObserve && (!movementEnabled() || movementSmoke || mobileSmoke ||
        !ba::flag(L"-original-command-scheduling-experimental") ||
        !ba::flag(L"-public-queue-smoke") || ba::argument(L"-public-queue-smoke-mode=","")!="1" ||
        ba::argument(L"-solo-ai-host=","")!="server"))
        throw std::runtime_error("server AI state observation requires its explicit owned public mode1 fixture");
    if(movementSmoke || mobileSmoke || serverAiObserve || closeFormation)args.push_back(L"--movement-observe");
    if(serverAiObserve)ba::log("Server AI native state observation enabled: BA_RESURRECTION_SERVER_AI_PREDICTION_OBSERVE_V1");
    if(serverAiMove)ba::log("Server AI original Move fixture enabled: BA_RESURRECTION_SERVER_AI_MOVEMENT_SMOKE_V1");
    if(closeFormation)ba::log("Close formation diagnostic enabled: BA_RESURRECTION_PREDICTION_CLOSE_FORMATION_V1");
    std::wstring cohortTrace;
    if(ba_command_line::value(ba::arguments(),L"-prediction-movement-observe-cohort=",cohortTrace)) {
        if((!ba_prediction_cohort::enabled()&&!ba_prediction_survivor::enabled()&&!closeFormation)||cohortTrace.empty()||cohortTrace.size()>64)
            throw std::runtime_error("native cohort observation requires its explicit cohort fixture");
        for(const auto ch:cohortTrace)if((ch<L'0'||ch>L'9')&&ch!=L':')
            throw std::runtime_error("native cohort diagnostic is not canonical ASCII decimal");
        args.push_back(L"--movement-observe-cohort");args.push_back(cohortTrace);
    }
    std::wstring positionTrace;
    if(ba_command_line::value(ba::arguments(),L"-prediction-movement-observe-position=",positionTrace)) {
        if(!movementSmoke || positionTrace.empty() || positionTrace.size()>64)
            throw std::runtime_error("selected native position diagnostic requires the owned movement fixture");
        for(const auto ch:positionTrace)if((ch<L'0' || ch>L'9') && ch!=L':')
            throw std::runtime_error("selected native position diagnostic is not ASCII decimal");
        // The Python entry point validates all five identity/window fields
        // before stdout isolation or NativeSession.open. No shell is used.
        args.push_back(L"--movement-observe-position");args.push_back(positionTrace);
    }
    s.process=std::make_unique<channel::Process>(python,args,data,data+L"\\worker-stderr.log");
    if(backend::initialize(selected,request,&s)!=0 ||
       proxy::bind(selected,backend::resolver,{&s,enter,leave})!=0)
        throw std::runtime_error("native worker proxy binding failed");
    s.selected=selected;
    const auto stats=s.process->stats();
    if(movementEnabled())
        ba::log("Native worker movement route active: pid=%lu assignedBeforeResume=%d BA_RESURRECTION_NATIVE_WORKER_PROXY_V1; movementRequested=1",
            stats.pid,stats.assignedBeforeResume?1:0);
    else
        ba::log("Native worker transport probe active: pid=%lu assignedBeforeResume=%d BA_RESURRECTION_NATIVE_WORKER_PROXY_V1; movement prediction is not enabled",
            stats.pid,stats.assignedBeforeResume?1:0);
}
static void movementOwner(State& s,bool bound=true) {
    if(!movementEnabled() || s.failed || s.movementStopped || !s.process || !s.process->healthy() || !s.world)
        throw std::runtime_error("movement worker is unavailable");
    if(bound && (!s.movementWorld || s.movementWorld!=s.world || s.movementMatch.size()!=32 ||
                 s.movementOwner!=GetCurrentThreadId()))
        throw std::runtime_error("movement worker owner/generation differs");
}
static wire::Response control(State& s,uint8_t opcode,const wire::Bytes& bytes,DWORD timeout=5000) {
    auto response=s.process->request(opcode,bytes,timeout);
    if(response.result!=0 || backend::dispatch_logs(response.logs)!=0)
        throw std::runtime_error("movement worker control failed");
    return response;
}
static void requireMovementHook(int64_t site,const char* exportName,uint8_t opcode=0xe8) {
    const auto module=GetModuleHandleW(L"GameAssembly.dll");
    if(!module)throw std::runtime_error("movement actor module is unavailable");
    const auto image=reinterpret_cast<const uint8_t*>(module);
    const auto dos=reinterpret_cast<const IMAGE_DOS_HEADER*>(image);
    if(dos->e_magic!=IMAGE_DOS_SIGNATURE || dos->e_lfanew<=0 || dos->e_lfanew>=4096)
        throw std::runtime_error("movement actor image header differs");
    const auto pe=reinterpret_cast<const IMAGE_NT_HEADERS64*>(image+dos->e_lfanew);
    const int64_t size=pe->OptionalHeader.SizeOfImage;
    if(pe->Signature!=IMAGE_NT_SIGNATURE || pe->FileHeader.Machine!=IMAGE_FILE_MACHINE_AMD64 || size<site+5)
        throw std::runtime_error("movement actor image layout differs");
    int32_t displacement=0;memcpy(&displacement,image+site+1,4);
    const int64_t thunk=site+5+displacement;
    if(image[site]!=opcode || thunk<0 || thunk>size-6 || image[thunk]!=0xff || image[thunk+1]!=0x25)
        throw std::runtime_error("movement requires its optional actor call/tail hook");
    memcpy(&displacement,image+thunk+2,4);const int64_t iat=thunk+6+displacement;
    if(iat<0 || iat>size-8)throw std::runtime_error("movement actor import lies outside image");
    uintptr_t target=0;memcpy(&target,image+iat,8);
    // ba::module is GameAssembly, whose IL2CPP APIs the ordinary helper uses.
    // The imported movement wrappers are exports of our separate helper DLL.
    const auto helper=GetModuleHandleW(L"BattleAcesOffline.dll");
    const auto expected=reinterpret_cast<uintptr_t>(helper?GetProcAddress(helper,exportName):nullptr);
    if(!expected || target!=expected)
        throw std::runtime_error(std::string("movement actor import target differs: ")+exportName);
}
static void requireMovementTailHook(int64_t site,const char* exportName) {requireMovementHook(site,exportName,0xe9);}
static void requireMovementPointerHook(int64_t site,const char* exportName) {
    const auto module=GetModuleHandleW(L"GameAssembly.dll");
    if(!module)throw std::runtime_error("movement pointer module is unavailable");
    const auto image=reinterpret_cast<const uint8_t*>(module);
    const auto dos=reinterpret_cast<const IMAGE_DOS_HEADER*>(image);
    if(dos->e_magic!=IMAGE_DOS_SIGNATURE || dos->e_lfanew<=0 || dos->e_lfanew>=4096)
        throw std::runtime_error("movement pointer image header differs");
    const auto pe=reinterpret_cast<const IMAGE_NT_HEADERS64*>(image+dos->e_lfanew);
    const int64_t size=pe->OptionalHeader.SizeOfImage;
    if(pe->Signature!=IMAGE_NT_SIGNATURE || pe->FileHeader.Machine!=IMAGE_FILE_MACHINE_AMD64 ||
       pe->OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR64_MAGIC || site<0 || size<8 || site>size-8)
        throw std::runtime_error("movement pointer image layout differs");
    uintptr_t target=0;memcpy(&target,image+site,8);
    const auto base=reinterpret_cast<uintptr_t>(module);
    // The existing DIR64 fixup makes the slot an ACTUAL loaded-image address.
    // It points to our RX import thunk, never directly to the helper export.
    if(target<base || target-base>static_cast<uintptr_t>(size-6))
        throw std::runtime_error("movement method pointer lies outside image");
    const int64_t thunk=static_cast<int64_t>(target-base);
    if(image[thunk]!=0xff || image[thunk+1]!=0x25)
        throw std::runtime_error("movement requires its optional method-pointer hook");
    int32_t displacement=0;memcpy(&displacement,image+thunk+2,4);
    const int64_t iat=thunk+6+displacement;
    if(iat<0 || iat>size-8)throw std::runtime_error("movement pointer import lies outside image");
    uintptr_t imported=0;memcpy(&imported,image+iat,8);
    const auto helper=GetModuleHandleW(L"BattleAcesOffline.dll");
    const auto expected=reinterpret_cast<uintptr_t>(helper?GetProcAddress(helper,exportName):nullptr);
    if(!expected || imported!=expected)
        throw std::runtime_error(std::string("movement pointer import target differs: ")+exportName);
}
static void requireMovementBytes(int64_t site,const char* bytes,size_t count) {
    const auto module=GetModuleHandleW(L"GameAssembly.dll");
    if(!module)throw std::runtime_error("movement byte-patch module is unavailable");
    const auto image=reinterpret_cast<const uint8_t*>(module);
    const auto dos=reinterpret_cast<const IMAGE_DOS_HEADER*>(image);
    if(dos->e_magic!=IMAGE_DOS_SIGNATURE || dos->e_lfanew<=0 || dos->e_lfanew>=4096)
        throw std::runtime_error("movement byte-patch image header differs");
    const auto pe=reinterpret_cast<const IMAGE_NT_HEADERS64*>(image+dos->e_lfanew);
    const uint64_t size=pe->OptionalHeader.SizeOfImage;
    if(pe->Signature!=IMAGE_NT_SIGNATURE || pe->FileHeader.Machine!=IMAGE_FILE_MACHINE_AMD64 ||
       pe->OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR64_MAGIC || site<0 || !count ||
       count>size || static_cast<uint64_t>(site)>size-count || memcmp(image+site,bytes,count))
        throw std::runtime_error("movement requires its scoped focus argument patch");
}
static void requireActorHook() {
    requireMovementHook(0x3be43be,"OfflinePredictionTimelineEventOwner");
    requireMovementHook(0x3be4661,"OfflinePredictionTimelineEventOwner");
    requireMovementHook(0x3be47b5,"OfflinePredictionTimelineEventOwner");
    requireMovementHook(0x3be46a9,"OfflinePredictionTimelineAnimator");
    requireMovementHook(0x3be468c,"OfflinePredictionTimelineBinding");
    requireMovementHook(0x3be46bd,"OfflinePredictionTimelineBinding");
    requireMovementHook(0x3be478a,"OfflinePredictionTimelinePlay");
    requireMovementTailHook(0x3bf3316,"OfflinePredictionNaturalSelectionRemove");
    requireMovementTailHook(0x3bf24f7,"OfflinePredictionPreviewAdd");
    requireMovementTailHook(0x3bf2666,"OfflinePredictionPreviewClear");
    requireMovementTailHook(0x3bf25f0,"OfflinePredictionSelectionRemoveCurrent");
    requireMovementTailHook(0x3bf26a8,"OfflinePredictionSelectionClear");
    requireMovementHook(0x3bf1375,"OfflinePredictionPreviewClear");
    requireMovementHook(0x3bf2856,"OfflinePredictionPreviewClear");
    requireMovementHook(0x3bf253a,"OfflinePredictionSelectionAdd");
    requireMovementHook(0x3bf25d0,"OfflinePredictionSelectionRemovePreview");
    requireMovementHook(0x3bf2739,"OfflinePredictionSelectionClear");
    requireMovementHook(0x3e6608b,"OfflinePredictionActorUpdate");
    requireMovementHook(0x3ea625a,"OfflinePredictionGroupReleaseRemove");
    requireMovementHook(0x3b02322,"OfflinePredictionSelectionCommit");
    requireMovementHook(0x3bf9657,"OfflinePredictionSelectionConfirmer");
    requireMovementHook(0x3bf416d,"OfflinePredictionCastingSet");
    requireMovementHook(0x3bf42e9,"OfflinePredictionCastingSet");
    requireMovementHook(0x3bf310f,"OfflinePredictionControlGroupFocus");
    requireMovementHook(0x3bfa10b,"OfflinePredictionControlGroupFocus");
    requireMovementHook(0x3bf306c,"OfflinePredictionFocusActuate");
    requireMovementHook(0x3bf322b,"OfflinePredictionStartRepeatFocus");
    requireMovementHook(0x3bf315d,"OfflinePredictionControlGroupCamera");
    requireMovementHook(0x3bfa027,"OfflinePredictionControlGroupCamera");
    requireMovementPointerHook(0x6d4dc48,"OfflinePredictionRepeatFocusNext");
    requireMovementHook(0x3bf7e64,"OfflinePredictionClickDownAccepted");
    requireMovementPointerHook(0x6d4db50,"OfflinePredictionInputFocusCancel0");
    requireMovementPointerHook(0x6d4db58,"OfflinePredictionInputFocusCancel1");
    requireMovementPointerHook(0x6d4db60,"OfflinePredictionInputFocusCancel2");
    requireMovementPointerHook(0x6d4db68,"OfflinePredictionInputFocusCancel3");
    requireMovementPointerHook(0x6d4db70,"OfflinePredictionInputFocusCancel4");
    requireMovementPointerHook(0x6d4db78,"OfflinePredictionInputCancelAbility");
    requireMovementPointerHook(0x6d4db80,"OfflinePredictionInputQueueModifier");
    requireMovementPointerHook(0x6d4db88,"OfflinePredictionInputForceModifier");
    requireMovementPointerHook(0x6d4db90,"OfflinePredictionInputPosition");
    requireMovementPointerHook(0x6d4db98,"OfflinePredictionInputDown");
    requireMovementPointerHook(0x6d4dba0,"OfflinePredictionInputUp");
    requireMovementPointerHook(0x6d4dba8,"OfflinePredictionInputContextDown");
    requireMovementPointerHook(0x6d4dbb0,"OfflinePredictionInputContextUp");
    requireMovementPointerHook(0x6d4ced0,"OfflinePredictionTimelineTrigger");
    requireMovementBytes(0x3bf305b,"\x45\x88\xf0",3);
}
uint64_t movementWorldId() {
    auto& s=state();std::lock_guard<std::recursive_mutex> hold(s.gate);
    return s.failed || s.movementStopped?0:s.world;
}
const std::string& movementMatchId() {
    static const std::string empty;
    auto& s=state();std::lock_guard<std::recursive_mutex> hold(s.gate);
    // This string changes only on the Unity owner during BEGIN. Native world
    // destruction only changes the integer key;it never invalidates this ref.
    return !s.failed && !s.movementStopped && s.world && s.world==s.movementWorld?s.movementMatch:empty;
}
void movementBegin(const std::string& match,unsigned slot,bool serverAi) {
    auto& s=state();std::lock_guard<std::recursive_mutex> hold(s.gate);movementOwner(s,false);
    if(slot>1 || (serverAi && slot!=0) || match.size()!=32 || match.find_first_not_of("0123456789abcdef")!=std::string::npos ||
       !ba::flag(L"-original-command-scheduling-experimental") || s.movementWorld==s.world)
        throw std::runtime_error("invalid movement BEGIN context");
    requireActorHook();
    if(ba::flag(L"-prediction-server-ai-observe") && !serverAi)
        throw std::runtime_error("server AI state observation requires actual public assignment");
    if(serverAi) {
        wire::Bytes roster;wire::append64(roster,s.world);wire::append32(roster,slot);
        if(!control(s,76,roster).data.empty())throw std::runtime_error("movement canonical roster response differs");
    }
    wire::Bytes bytes;wire::append64(bytes,s.world);wire::append32(bytes,12);wire::append32(bytes,16u*1024u*1024u);
    const auto response=control(s,64,bytes,30000);
    if(!response.data.empty())throw std::runtime_error("movement BEGIN response differs");
    wire::Bytes proof;wire::append64(proof,s.world);const auto guard=control(s,71,proof);
    size_t at=0;
    if(wire::read32(guard.data,at)!=1 || at!=guard.data.size())
        throw std::runtime_error("movement needs the guarded native entity incarnation observer");
    s.movementWorld=s.world;s.movementMatch=match;s.movementOwner=GetCurrentThreadId();
    s.movementSlot=slot;s.movementEnding=false;
}
void movementAuthority(const MovementBytes& canonical,const std::string& wireSha) {
    auto& s=state();std::lock_guard<std::recursive_mutex> hold(s.gate);movementOwner(s);
    if(canonical.empty() || canonical.size()>2u*1024u*1024u || s.movementEnding)
        throw std::runtime_error("movement authority outside match bounds");
    wire::Bytes bytes;wire::append64(bytes,s.world);bytes.insert(bytes.end(),canonical.begin(),canonical.end());
    if(!control(s,65,bytes).data.empty())throw std::runtime_error("movement authority response differs");
    ba_prediction_cohort::authoritative(canonical,wireSha);
    ba_prediction_survivor::authoritative(canonical,wireSha);
    ba_prediction_close_formation::authoritative(canonical,wireSha);
    ba_prediction_movement_smoke::authoritative(canonical,wireSha);
}
MovementMetrics movementMetrics() {
    auto& s=state();std::lock_guard<std::recursive_mutex> hold(s.gate);movementOwner(s);
    wire::Bytes bytes;wire::append64(bytes,s.world);const auto response=control(s,66,bytes);
    if(response.data.size()!=80)throw std::runtime_error("movement metrics response differs");
    size_t at=0;MovementMetrics result;
    result.confirmed=static_cast<int32_t>(wire::read32(response.data,at));
    result.predicted=static_cast<int32_t>(wire::read32(response.data,at));
    result.received=static_cast<int32_t>(wire::read32(response.data,at));
    result.flags=wire::read32(response.data,at);
    for(unsigned i=0;i<8;++i)wire::read64(response.data,at);
    if(result.flags&~15u)throw std::runtime_error("movement metrics flags differ");
    return result;
}
MovementAdmission movementAdmission() {
    auto& s=state();std::lock_guard<std::recursive_mutex> hold(s.gate);movementOwner(s);
    wire::Bytes bytes;wire::append64(bytes,s.world);const auto response=control(s,70,bytes);
    if(response.data.size()<8)throw std::runtime_error("movement admission response is truncated");
    size_t at=0;MovementAdmission result;
    result.frame=static_cast<int32_t>(wire::read32(response.data,at));
    const uint32_t count=wire::read32(response.data,at);
    if(result.frame<-1 || count>65536 || response.data.size()!=8u+20u*static_cast<size_t>(count))
        throw std::runtime_error("movement admission response bounds differ");
    uint32_t previous=0;std::set<uint64_t> tokens;
    for(uint32_t index=0;index<count;++index) {
        const uint32_t id=wire::read32(response.data,at);
        MovementIdentity identity;identity.army=wire::read32(response.data,at);
        identity.type=wire::read32(response.data,at);identity.incarnation=wire::read64(response.data,at);
        if((index && id<=previous) || !identity.incarnation || !tokens.insert(identity.incarnation).second)
            throw std::runtime_error("movement admission identity order/token differs");
        result.entities.emplace(id,identity);previous=id;
    }
    return result;
}
void movementBatch(uint64_t sequence,const MovementBytes& body) {
    auto& s=state();std::lock_guard<std::recursive_mutex> hold(s.gate);movementOwner(s);
    if(!sequence || body.empty() || body.size()>65536 || s.movementEnding)
        throw std::runtime_error("movement local batch outside match bounds");
    wire::Bytes bytes;wire::append64(bytes,s.world);wire::append64(bytes,sequence);
    bytes.insert(bytes.end(),body.begin(),body.end());const auto response=control(s,67,bytes);
    size_t at=0;const auto echoed=wire::read64(response.data,at);
    const auto assigned=static_cast<int32_t>(wire::read32(response.data,at));
    if(echoed!=sequence || assigned<0 || at!=response.data.size())
        throw std::runtime_error("movement local batch response differs");
    ba::log("Movement local batch registered: sequence=%llu speculativeFrame=%d tick=%llu match=%s",
        static_cast<unsigned long long>(sequence),assigned,static_cast<unsigned long long>(GetTickCount64()),s.movementMatch.c_str());
    ba_prediction_movement_smoke::registered(sequence,assigned,body);
    ba_prediction_cohort::registered(sequence,assigned,body);
    ba_prediction_survivor::registered(sequence,assigned,body);
    ba_prediction_close_formation::registered(sequence,assigned,body);
}
void movementEnd(int finalInputFrame) {
    auto& s=state();std::lock_guard<std::recursive_mutex> hold(s.gate);movementOwner(s);
    if(finalInputFrame<0 || s.movementEnding)throw std::runtime_error("movement END outside match bounds");
    wire::Bytes bytes;wire::append64(bytes,s.world);wire::append32(bytes,static_cast<uint32_t>(finalInputFrame));
    const auto response=control(s,69,bytes);size_t at=0;const auto cancelled=wire::read32(response.data,at);
    if(at!=response.data.size())throw std::runtime_error("movement END response differs");
    s.movementEnding=true;
    ba::log("Movement authoritative end queued: frame=%d uncommittedActionsCancelled=%u match=%s",
        finalInputFrame,cancelled,s.movementMatch.c_str());
}
void movementFail(const char* reason) noexcept {
    try {auto& s=state();std::lock_guard<std::recursive_mutex> hold(s.gate);s.movementStopped=true;s.failed=true;}
    catch(...) {}
    // Preserve the already-buffered producer/arrival QPC rows after an owned
    // mirror diagnostic fails. This does no trace I/O during a successful
    // measured prefix and never flushes a worker thread's main-thread buffer.
    try {
        const bool heldTimeline=ba::flag(L"-prediction-terminal-timeline-smoke")&&
            ba::flag(L"-prediction-actor-mirror-smoke")&&ba::flag(L"-prediction-held-click-smoke");
        const bool mobileHeld=ba::flag(L"-prediction-mobile-held-click-smoke")&&ba::flag(L"-prediction-mobile-correction-smoke");
        if(ba::initialThread&&GetCurrentThreadId()==ba::initialThread&&(heldTimeline||mobileHeld)) {
            ba_prediction_movement::flushEarlyPhaseDiagnostics();
            ba_frame_timing::flush();
        }
    } catch(...) {}
    try {const std::runtime_error error(reason?reason:"unknown movement failure");ba_lan::fail("movement prediction",error);}
    catch(...) {ba::log("Movement prediction stopped; normal Quit remains available");}
}
static uintptr_t lookup(HMODULE module,const char* name) {
    if(!enabled())return reinterpret_cast<uintptr_t>(GetProcAddress(module,name));
    auto& s=state();
    if(!s.selected || s.selected!=module || s.failed)return 0;
    return proxy::lookup(name);
}
static void shutdown() noexcept {
    if(!enabled())return;
    auto& s=state();
    try {
        std::lock_guard<std::recursive_mutex> lock(s.gate);
        if(s.process && s.process->healthy()) {s.process->shutdown(5000);logClosed(s);}
    } catch(const std::exception& error) {s.failed=true;ba::log("Native worker cleanup failed: %s",error.what());}
    catch(...) {s.failed=true;}
}
}

extern "C" __declspec(dllexport) uintptr_t OfflinePredictionGetProcAddress(void* module,void* name,void* method) {
    ba::init();
    const auto original=ba::native<uintptr_t(*)(void*,void*,void*)>(0x379bd20);
    if(!ba_prediction_worker::enabled())return original(module,name,method);
    try {
        const auto selected=static_cast<HMODULE>(module);
        if(!ba_prediction_worker::simulation(selected))return original(module,name,method);
        ba_prediction_worker::setup(selected);
        const auto symbol=ba_prediction_worker::exportName(name);
        const auto result=ba_prediction_worker::lookup(selected,symbol.c_str());
        if(!result)throw std::runtime_error("unsupported native worker export lookup");
        auto& s=ba_prediction_worker::state();
        s.lookups.insert(symbol);
        ba::log("Native worker export lookup: name=%s count=%zu thread=%lu",symbol.c_str(),s.lookups.size(),GetCurrentThreadId());
        return result;
    } catch(const std::exception& error) {
        ba_prediction_worker::state().failed=true;
        ba_prediction_worker::shutdown();
        ba::log("Native worker startup refused: %s",error.what());return 0;
    }
}
