// Owned local-worker transport probe. Prediction is not enabled by this file.
// Its sole optional GameAssembly CALL hook is excluded from the normal recipe.
#include <memory>
#include <mutex>
#include <set>
#include "../checkpoint/native_api_proxy.hpp"
#include "../checkpoint/native_rpc_backend.hpp"
#include "../checkpoint/native_worker_channel.hpp"

namespace ba_prediction_worker {
namespace proxy=ba_native_api_proxy;
namespace backend=ba_native_rpc_backend;
namespace wire=ba_native_worker_wire;
namespace channel=ba_native_worker_channel;
using Obj=void*;

static bool enabled(){return ba::flag(L"-prediction-native-worker-probe");}
struct State {
    std::recursive_mutex gate;
    std::unique_ptr<channel::Process> process;
    HMODULE selected=nullptr;
    bool failed=false,firstRequest=true,destroyed=false;
    unsigned depth=0;
    std::set<DWORD> threads;
    std::set<std::string> calls,lookups;
    uint64_t entered=0,left=0;
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
        if(s.failed){s.gate.unlock();return -1;}
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
    s.process=std::make_unique<channel::Process>(python,args,data,data+L"\\worker-stderr.log");
    if(backend::initialize(selected,request,&s)!=0 ||
       proxy::bind(selected,backend::resolver,{&s,enter,leave})!=0)
        throw std::runtime_error("native worker proxy binding failed");
    s.selected=selected;
    const auto stats=s.process->stats();
    ba::log("Native worker transport probe active: pid=%lu assignedBeforeResume=%d BA_RESURRECTION_NATIVE_WORKER_PROXY_V1; movement prediction is not enabled",
        stats.pid,stats.assignedBeforeResume?1:0);
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
