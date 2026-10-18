// Offline bootstrap for the exact preserved Battle Aces build 37822.
// Loaded through a normal PE import. No process injection or Steam emulation.
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <bcrypt.h>
#include <vector>
#include <deque>
#include <array>
#include <string>
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <stdexcept>
#include <share.h>
#include "command_line.h"
#include "match_loading.h"

namespace ba_catalog { static void exportOnce();static std::string utf8(void*); }
namespace ba_dedicated_results { static void receive(const std::string&); }
namespace ba_audit { static void beginMatch(const std::string&);static void practiceAIView(void*,int); }
namespace ba_telemetry_audit { static void startup();static void update(); }
namespace ba_practice_settings_ui { static void update(void* front);static bool smokeComplete(); }
namespace ba_dedicated_session {
static void update(void* front);
static bool retryFromPlay(void* front,int mode);
}
namespace ba_community_native { static void update(void* front);static void reset(); }
namespace ba_community_roster { static void reset();static void changed();static void update();static void smoke(void* front); }
namespace ba_community_wire {struct Ack;struct Invitation;struct Aborted;}
namespace ba_practice {
static bool active();static void start(void*,void*);static void consume(void*,void*,void*);
static void offlineUpdate(void*);
static bool assetsReady(void*);static void worldReady(void*);static bool gameUpdate(void*,void*);static bool frontUpdate(void*);
static bool acknowledge(void*,const ba_community_wire::Ack&);static void smoke(void*);
static void input(void*,void*);static bool signalReady(void*);static void fail(const char*,const std::exception&);
}
namespace ba_community_invites {
static void reset(void*);static void enqueue(void*,void*,int);static bool acknowledge(void*,const ba_community_wire::Ack&);
static void receive(void*,const ba_community_wire::Invitation&);static void flush(void*);static void dispatch(void*);
static bool retain(const std::string&);static bool pending(const std::string&);static bool canInvite(const std::string&);
static void reconcileParty(void*);static void anchorClock(void*);static void smoke(void*);
}
namespace ba_community_popup {static void reset();static void update();}
namespace ba_community_match {
static void reset();static void enqueue(void*,void*,void*);
static bool acknowledge(void*,const ba_community_wire::Ack&);
static void aborted(void*,const ba_community_wire::Aborted&);
static void snapshot(void*);static void update(void*);static void returned(void*,void*);static void smoke(void*);
}
namespace ba_export {
static void poll(void* front);
static void consume(void* gameData,void* encoded);
static void failed(const char* reason);
}

namespace ba {
using Obj = void*;
static HMODULE module;
static FILE* logfile;
static Obj owner;
static uint32_t owner_root;
static DWORD initialThread=0;
static const std::vector<std::wstring>& arguments() {
    static const auto values=ba_command_line::parse(GetCommandLineW());return values;
}
static bool flag(const wchar_t* name){return ba_command_line::has(arguments(),name);}
static bool exportServerAssets() {return flag(L"-export-server-assets");}
static bool offlinePractice() {return !exportServerAssets() && flag(L"-offline-practice");}
static bool dedicated() {std::wstring value;return !offlinePractice() && !exportServerAssets() && ba_command_line::value(arguments(),L"-dedicated-server=",value);}
static bool community() {return dedicated() && flag(L"-dedicated-community");}
static bool lan() { return !offlinePractice() && !exportServerAssets() && (dedicated() || flag(L"-offline-lan")); }
static int dedicatedAssignedSlot=-1;
static int requestedLanSlot() {
    std::wstring value;
    if(ba_command_line::value(arguments(),L"-lan-slot=",value)) {
        if(value==L"1")return 1;
        if(value==L"0")return 0;
    }
    return dedicated()?255:0;
}
// A dedicated army identity does not exist until S_WELCOME assigns its seat.
static int lanSlot() { return offlinePractice()?-1:dedicated()?dedicatedAssignedSlot:requestedLanSlot(); }
static std::string argument(const wchar_t* key,const char* fallback="") {
    std::wstring value;if(!ba_command_line::value(arguments(),key,value))return fallback;
    int count=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,value.data(),static_cast<int>(value.size()),nullptr,0,nullptr,nullptr);
    if(!value.empty() && !count)throw std::runtime_error("command-line value has invalid Unicode");
    std::string out(count,'\0');if(count)WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,value.data(),static_cast<int>(value.size()),&out[0],count,nullptr,nullptr);return out;
}
void lanFrontUpdate(Obj front);
template<class F> F api(const char* name) {
    F f=reinterpret_cast<F>(GetProcAddress(module,name));
    if(!f) throw std::runtime_error(name);
    return f;
}
template<class F> F native(uintptr_t rva) { return reinterpret_cast<F>(reinterpret_cast<uintptr_t>(module)+rva); }
template<class T> T read(Obj p, size_t off) { return p ? *reinterpret_cast<T*>(static_cast<char*>(p)+off) : T{}; }
void log(const char* format, ...) {
    if(!logfile) {
        wchar_t path[32768]; GetModuleFileNameW(module,path,32768);
        wchar_t* slash=wcsrchr(path,L'\\'); if(slash) *(slash+1)=0;
        if(offlinePractice() || (dedicated() && requestedLanSlot()==255)) {
            wchar_t suffix[128];swprintf_s(suffix,L"investigation\\runtime\\dedicated-native-%lu.log",GetCurrentProcessId());wcscat_s(path,suffix);
        } else wcscat_s(path,lan() ? (requestedLanSlot()==1 ? L"investigation\\runtime\\lan-native-1.log" : L"investigation\\runtime\\lan-native-0.log") : L"investigation\\runtime\\offline-native.log");
        logfile=_wfsopen(path,L"a",_SH_DENYNO);
    }
    if(logfile) { fprintf(logfile,"[%llu] ",GetTickCount64()); va_list args;va_start(args,format);vfprintf(logfile,format,args);va_end(args);fputc('\n',logfile);fflush(logfile); }
}
LONG CALLBACK trace_exception(EXCEPTION_POINTERS* info) {
    if(info->ExceptionRecord->ExceptionCode!=0xe06d7363)return EXCEPTION_CONTINUE_SEARCH;
    static thread_local bool tracing=false;static LONG recorded=0;
    if(tracing || InterlockedIncrement(&recorded)>32)return EXCEPTION_CONTINUE_SEARCH;
    tracing=true;
    void* frames[48];USHORT count=CaptureStackBackTrace(0,48,frames,nullptr);
    log("Native first-chance C++ exception trace:");
    for(USHORT i=0;i<count;++i) {
        uintptr_t address=reinterpret_cast<uintptr_t>(frames[i]);
        uintptr_t base=reinterpret_cast<uintptr_t>(module);
        if(address>=base && address<base+0x8000000)log("  GameAssembly RVA 0x%llx",static_cast<unsigned long long>(address-base));
    }
    tracing=false;return EXCEPTION_CONTINUE_SEARCH;
}
void init() {
    if(!module) {
        module=GetModuleHandleW(L"GameAssembly.dll");
        if(module && wcsstr(GetCommandLineW(),L"-offline-trace"))AddVectoredExceptionHandler(0,trace_exception);
    }
    if(!module) throw std::runtime_error("GameAssembly unavailable");
}
Obj klass(Obj obj) { return api<Obj(*)(Obj)>("il2cpp_object_get_class")(obj); }
Obj find_class(const char* ns, const char* name) {
    Obj domain=api<Obj(*)()>("il2cpp_domain_get")();size_t count=0;
    const Obj* assemblies=api<const Obj*(*)(Obj,size_t*)>("il2cpp_domain_get_assemblies")(domain,&count);
    for(size_t i=0;i<count;i++) {
        Obj img=api<Obj(*)(Obj)>("il2cpp_assembly_get_image")(assemblies[i]);
        Obj k=api<Obj(*)(Obj,const char*,const char*)>("il2cpp_class_from_name")(img,ns,name);if(k)return k;
    }
    throw std::runtime_error(name);
}
Obj field(Obj obj,const char* name) {
    if(!obj)throw std::runtime_error("field on null object");
    Obj f=api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(klass(obj),name);
    if(!f)throw std::runtime_error(name);return f;
}
template<class T> T get(Obj obj,const char* name) {
    T value{};api<void(*)(Obj,Obj,void*)>("il2cpp_field_get_value")(obj,field(obj,name),&value);return value;
}
template<class T> void set(Obj obj,const char* name,T value) {
    api<void(*)(Obj,Obj,void*)>("il2cpp_field_set_value")(obj,field(obj,name),&value);
}
template<> void set<Obj>(Obj obj,const char* name,Obj value) {
    api<void(*)(Obj,Obj,Obj)>("il2cpp_field_set_value_object")(obj,field(obj,name),value);
    if(get<Obj>(obj,name)!=value)throw std::runtime_error("managed reference field verification failed");
}
Obj invoke(Obj k,Obj instance,const char* name,int argc,void** args=nullptr) {
    Obj m=api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(k,name,argc);
    if(!m)throw std::runtime_error(name);
    Obj exception=nullptr;
    Obj result=api<Obj(*)(Obj,Obj,void**,Obj*)>("il2cpp_runtime_invoke")(m,instance,args,&exception);
    if(exception) {
        char message[8192]={};api<void(*)(Obj,char*,int)>("il2cpp_format_exception")(exception,message,sizeof(message));
        log("Exception in %s: %s",name,message);
        char stack[16384]={};api<void(*)(Obj,char*,int)>("il2cpp_format_stack_trace")(exception,stack,sizeof(stack));
        log("Managed stack: %s",stack);throw std::runtime_error(name);
    }
    return result;
}
Obj call(Obj obj,const char* name,int argc=0,void** args=nullptr) { return invoke(klass(obj),obj,name,argc,args); }
Obj make(const char* ns,const char* name) {
    Obj k=find_class(ns,name);api<void(*)(Obj)>("il2cpp_runtime_class_init")(k);
    Obj o=api<Obj(*)(Obj)>("il2cpp_object_new")(k);invoke(k,o,".ctor",0);return o;
}
Obj str(const char* s) { return api<Obj(*)(const char*)>("il2cpp_string_new")(s); }
void local_profile(Obj account) {
    if(get<Obj>(account,"<ProfileCache>k__BackingField"))return;
    Obj p=make("CommonPb","ProfileData");
    Obj id=make("CommonPb","ProfileId");
    set(id,"profileId_",str("offline-0000000000000001"));
    set(p,"id_",id);set(p,"name_",str("Offline Player"));
    set(p,"profileLocks_",make("CommonPb","ProfileLocks"));
    set(p,"progression_",make("CommonPb","PlayerProgression"));
    set(p,"accountData_",make("CommonPb","AccountData"));
    set(p,"cosmeticLoadout_",make("CommonPb","CosmeticLoadout"));
    set(p,"selectedDeck_",make("CommonPb","Deck"));
    set(account,"<ProfileCache>k__BackingField",p);
    log("Created local profile and empty local progression state.");
}
void local_version(Obj front) {
    Obj version=make("CommonPb","VersionResponse");
    set(version,"apiVersionOk_",true);set(version,"buildVersionOk_",true);
    set(front,"_frontVersionResponse",version);
    set(front,"_clientVersionOk",true);set(front,"_gameVersionAvailable",true);
    set(front,"_isLoggedIn",true);
}
void dump(Obj obj,const char* label) {
    if(!obj){log("%s = null",label);return;}
    Obj k=klass(obj);log("%s = %p (%s)",label,obj,api<const char*(*)(Obj)>("il2cpp_class_get_name")(k));
    void* iter=nullptr;Obj f;int shown=0;
    while((f=api<Obj(*)(Obj,void**)>("il2cpp_class_get_fields")(k,&iter)) && shown++<80) {
        unsigned flags=api<unsigned(*)(Obj)>("il2cpp_field_get_flags")(f);if(flags&0x10)continue;
        const char* n=api<const char*(*)(Obj)>("il2cpp_field_get_name")(f);
        size_t off=api<size_t(*)(Obj)>("il2cpp_field_get_offset")(f);
        log("  +%zx %s = %p",off,n,read<Obj>(obj,off));
    }
}
}

extern "C" __declspec(dllexport) int OfflineInitialUpdate(void* state,void*) {
    using namespace ba;
    static bool failed=false;
    if(failed)return 0;
    try {
        init();
        if(initialThread && initialThread!=GetCurrentThreadId())throw std::runtime_error("initial state changed Unity thread");
        initialThread=GetCurrentThreadId();owner=read<Obj>(state,0x18);
        if(!owner_root)owner_root=api<uint32_t(*)(Obj,bool)>("il2cpp_gchandle_new")(owner,false);
        log("Offline initial state reached after game initialization. PID=%lu",GetCurrentProcessId());
        ba_telemetry_audit::startup();
        Obj services=read<Obj>(owner,0x38);
        local_profile(read<Obj>(services,0x40));
        local_version(read<Obj>(services,0x10));
        if(lan()) {
            Obj background=invoke(find_class("UnityEngine","Application"),nullptr,"get_runInBackground",0);
            log("LAN Unity runInBackground=%d",*api<bool*(*)(Obj)>("il2cpp_object_unbox")(background));
        }
        bool tutorial=!exportServerAssets() && wcsstr(GetCommandLineW(),L"-offline-tutorial")!=nullptr;
        Obj target=read<Obj>(owner,tutorial ? 0x2f8 : 0x2c0);
        if(!target)throw std::runtime_error("startup target state missing");
        log("Entering existing %s state %p",tutorial ? "tutorial01" : "main menu",target);
        return native<int(*)(Obj,Obj)>(0x4dd1d0)(state,target);
    } catch(const std::exception& e) { log("Offline initialization failed: %s",e.what());failed=true;return 0; }
}

extern "C" __declspec(dllexport) void OfflineFrontUpdate(void* front,void*) {
    // Offline mode owns no connection to the discontinued front service.
    using namespace ba;
    static ULONGLONG last=0;
    if(!owner)return;
    try {
        if(!get<Obj>(front,"_frontVersionResponse")) {
            local_version(front);log("Restored local version state after frontend reset.");
        }
        if(!get<bool>(front,"_isLoggedIn"))set(front,"_isLoggedIn",true);
        if(exportServerAssets()){ba_export::poll(front);return;}
        // Observe before opt-in automation can continue out of a result/menu and
        // before the normal ten-second status throttle. Disabled audit is a cached
        // flag check and performs no FSM, UnityPlayer or native-object reads.
        ba_telemetry_audit::update();
        ba_catalog::exportOnce();
        if(offlinePractice())ba_practice::offlineUpdate(front);
        else if(lan())lanFrontUpdate(front);
        ba_match_loading::update(front);
        ba_match_loading_smoke::update(front);
        if(GetTickCount64()-last<10000)return;
        last=GetTickCount64();
        Obj fsm=read<Obj>(owner,0x2b0), state=get<Obj>(fsm,"_currentState");
        log("Offline state: %s",state ? api<const char*(*)(Obj)>("il2cpp_class_get_name")(klass(state)) : "none");
        Obj services=read<Obj>(owner,0x38), server=read<Obj>(services,0x18);
        Obj sim=read<Obj>(server,0x140), player=read<Obj>(sim,0x90);
        if(sim)log("Offline world: active=%d simFrame=%d presentedFrame=%d playerArmy=%d",
            read<bool>(sim,0x1a0),read<int>(sim,0xa8),read<int>(sim,0xac),player ? read<int>(player,0x38) : -1);
    }
    catch(const std::exception& e) { log("Offline status: %s",e.what()); }
}

#include "local_loop.cpp"
#include "catalog_export.cpp"
#include "lan_smoke.cpp"
#include "community_transport.cpp"
#include "lan_transport.cpp"
#include "dedicated_transport.cpp"
#include "dedicated_deck.cpp"
#include "dedicated_results.cpp"
#include "local_bootstrap.cpp"
#include "dedicated_adapter.cpp"
#include "community_native.cpp"
#include "community_roster.cpp"
#include "community_invites.cpp"
#include "community_popup.cpp"
#include "community_match.cpp"
#include "practice_settings.cpp"
#include "practice_ai.cpp"
#include "practice_settings_ui.cpp"
#include "match_loading.cpp"
#include "match_loading_smoke.cpp"
#include "server_assets_export.cpp"
#include "lan_audit.cpp"
#include "telemetry_audit.cpp"

extern "C" __declspec(dllexport) void OfflineStartupReady(void* context,void* freshThreshold,void* reusedThreshold,void* initializer) {
    // Exact RGameInit.Start completion callsite, after _loadingFinish=true.
    // Windows x64 passes the two 16-byte Nullable<double> values by pointer.
    // Keep the original startup stopwatch/logging and its original null
    // MethodInfo before opening the intro gate, which still waits for assets.
    ba::init();
    ba_local::Root owner(initializer);
    ba::native<void(*)(void*,void*,void*,void*)>(0x3dfd180)(context,freshThreshold,reusedThreshold,nullptr);
    ba::log("Offline startup assets ready; original Start timing retained; releasing native intro gate");
    ba::native<void(*)(void*,void*)>(0x3dfced0)(owner.get(),nullptr);
}
