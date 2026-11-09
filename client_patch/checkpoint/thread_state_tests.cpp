#include "thread_state.hpp"
#include <condition_variable>
#include <exception>
#include <iostream>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>

namespace t=ba_thread_state;
static void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
template<class F> static void rejects(F action) {
    bool refused=false;try{action();}catch(const std::runtime_error&){refused=true;}
    check(refused,"expected thread-state refusal missing");
}
struct TestState {
    std::array<uint8_t,t::nativeTlsBytes> bytes{};
    uint8_t* overrideTls=nullptr;
};
static thread_local TestState currentTest;
struct Fixture {
    DWORD vcr=FlsAlloc(nullptr),ucrt=FlsAlloc(nullptr),tlsIndex=17;
    std::array<int,20> roots{};
    Fixture(){check(vcr!=FLS_OUT_OF_INDEXES && ucrt!=FLS_OUT_OF_INDEXES,"test FLS allocation failed");}
    ~Fixture(){if(vcr!=FLS_OUT_OF_INDEXES)FlsFree(vcr);if(ucrt!=FLS_OUT_OF_INDEXES)FlsFree(ucrt);}
    t::CurrentState read()const {
        t::LastError preserve;
        t::CurrentState result;result.threadId=GetCurrentThreadId();result.tlsIndex=tlsIndex;
        result.vcrIndex=vcr;result.ucrtIndex=ucrt;
        result.tls=currentTest.overrideTls ? currentTest.overrideTls : currentTest.bytes.data();
        result.vcrRoot=FlsGetValue(vcr);result.ucrtRoot=FlsGetValue(ucrt);return result;
    }
    void initialize(uint8_t value,size_t root=0,bool empty=false) {
        currentTest.overrideTls=nullptr;currentTest.bytes.fill(value);
        check(FlsSetValue(vcr,empty ? nullptr : &roots[root])!=FALSE,"test VCR FLS setup failed");
        check(FlsSetValue(ucrt,empty ? nullptr : &roots[root+1])!=FALSE,"test UCRT FLS setup failed");
    }
};
// Only owned test threads, parked between bounded synchronous calls. Registry
// access is sequential; this harness provides the external gate/lifetime rule.
class Worker {
public:
    Worker():thread_([this]{run();}){}
    ~Worker(){stop();}
    Worker(const Worker&)=delete;Worker& operator=(const Worker&)=delete;
    void call(std::function<void()> action) {
        {
            std::lock_guard<std::mutex> lock(mutex_);check(!stop_,"test worker already stopped");
            action_=std::move(action);done_=false;error_=nullptr;
        }
        request_.notify_one();
        std::unique_lock<std::mutex> lock(mutex_);
        check(completed_.wait_for(lock,std::chrono::seconds(10),[this]{return done_;}),"owned test worker timed out");
        if(error_)std::rethrow_exception(error_);
    }
    void stop() {
        if(!thread_.joinable())return;
        {std::lock_guard<std::mutex> lock(mutex_);stop_=true;}
        request_.notify_one();thread_.join();
    }
private:
    void run() {
        for(;;) {
            std::function<void()> action;
            {
                std::unique_lock<std::mutex> lock(mutex_);
                request_.wait(lock,[this]{return stop_ || static_cast<bool>(action_);});
                if(stop_)return;action=std::move(action_);action_=nullptr;
            }
            std::exception_ptr error;try{action();}catch(...){error=std::current_exception();}
            {std::lock_guard<std::mutex> lock(mutex_);error_=error;done_=true;}
            completed_.notify_one();
        }
    }
    std::mutex mutex_;std::condition_variable request_,completed_;
    bool stop_=false,done_=false;
    std::function<void()> action_;std::exception_ptr error_;
    std::thread thread_;
};
static void bytes(const uint8_t* data,uint8_t expected) {
    for(size_t i=0;i<t::nativeTlsBytes;++i)check(data[i]==expected,"TLS bytes mismatch");
}
static void handoffAndRestore() {
    Fixture f;Worker worker;t::ThreadRegistry registry([&]{return f.read();});
    f.initialize(0x11);registry.observe();registry.observe();
    worker.call([&]{f.initialize(0x22,2);registry.observe();registry.observe();});
    SetLastError(0x1234);const auto saved=registry.capture();
    check(GetLastError()==0x1234 && saved.threadCount()==2,"capture thread/error state mismatch");
    currentTest.bytes.fill(0x55);registry.observe();
    worker.call([&]{registry.observe();currentTest.bytes.fill(0x66);registry.observe();});
    SetLastError(0x5678);registry.validate(saved);registry.restore(saved);
    check(GetLastError()==0x5678,"restore lost Win32 last error");bytes(currentTest.bytes.data(),0x11);
    worker.call([&]{registry.observe();bytes(currentTest.bytes.data(),0x22);registry.observe();});
    registry.restore(saved);bytes(currentTest.bytes.data(),0x11);
    check(registry.threadCount()==2,"main-to-worker handoff lost registration");
}
static void currentActualRootsAndRevisions() {
    Fixture f;f.initialize(0x10,0,true);t::ThreadRegistry registry([&]{return f.read();});registry.observe();
    const auto saved=registry.capture();currentTest.bytes.fill(0x70);
    check(FlsSetValue(f.ucrt,&f.roots[4])!=FALSE,"test late root set failed");
    rejects([&]{registry.restore(saved);});bytes(currentTest.bytes.data(),0x70);
    registry.observe();rejects([&]{registry.restore(saved);});bytes(currentTest.bytes.data(),0x70);
    // Returning to the same address must not hide an observed intermediate
    // future binding (ABA); the per-thread binding revision retains it.
    check(FlsSetValue(f.ucrt,nullptr)!=FALSE,"test late root clear failed");registry.observe();
    rejects([&]{registry.restore(saved);});bytes(currentTest.bytes.data(),0x70);
    const auto stable=registry.capture();currentTest.bytes.fill(0x80);registry.restore(stable);
    bytes(currentTest.bytes.data(),0x70);
    check(FlsSetValue(f.vcr,&f.roots[5])!=FALSE,"test late VCR set failed");
    rejects([&]{registry.validate(stable);});bytes(currentTest.bytes.data(),0x70);
}
static void otherThreadRootsAreObserved() {
    Fixture f;Worker worker;t::ThreadRegistry registry([&]{return f.read();});f.initialize(1);registry.observe();
    worker.call([&]{f.initialize(2,2,true);registry.observe();registry.observe();});
    const auto saved=registry.capture();currentTest.bytes.fill(3);
    worker.call([&]{registry.observe();check(FlsSetValue(f.vcr,&f.roots[4])!=FALSE,"test root change failed");
                    currentTest.bytes.fill(4);registry.observe();});
    rejects([&]{registry.restore(saved);});bytes(currentTest.bytes.data(),3);
    worker.call([&]{bytes(currentTest.bytes.data(),4);});
    const auto newer=registry.capture();currentTest.bytes.fill(5);
    worker.call([&]{registry.observe();currentTest.bytes.fill(6);registry.observe();});
    registry.restore(newer);bytes(currentTest.bytes.data(),3);
    worker.call([&]{bytes(currentTest.bytes.data(),4);});
}
static void newThreadAndExitedThread() {
    Fixture f;f.initialize(0x11);t::ThreadRegistry registry([&]{return f.read();});registry.observe();
    const auto one=registry.capture();Worker worker;
    worker.call([&]{f.initialize(0x22,2);registry.observe();registry.observe();});
    currentTest.bytes.fill(0x33);rejects([&]{registry.restore(one);});bytes(currentTest.bytes.data(),0x33);
    const auto both=registry.capture();currentTest.bytes.fill(0x44);worker.stop();
    rejects([&]{registry.restore(both);});bytes(currentTest.bytes.data(),0x44);
    rejects([&]{registry.capture();});
}
struct Page {
    uint8_t* data=static_cast<uint8_t*>(VirtualAlloc(nullptr,4096,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE));
    Page(){check(data!=nullptr,"test TLS page allocation failed");}
    ~Page(){if(data)VirtualFree(data,0,MEM_RELEASE);}
};
static void fullValidationBeforeAnyCopy() {
    Fixture f;Page page;Worker worker;t::ThreadRegistry registry([&]{return f.read();});
    f.initialize(0x11);registry.observe();
    worker.call([&]{f.initialize(0x22,2);currentTest.overrideTls=page.data;
                    std::memset(page.data,0x22,t::nativeTlsBytes);registry.observe();});
    const auto saved=registry.capture();currentTest.bytes.fill(0x33);std::memset(page.data,0x44,t::nativeTlsBytes);
    DWORD old=0;check(VirtualProtect(page.data,4096,PAGE_READONLY,&old)!=FALSE,"test protect failed");
    rejects([&]{registry.restore(saved);});bytes(currentTest.bytes.data(),0x33);bytes(page.data,0x44);
    check(VirtualProtect(page.data,4096,PAGE_READWRITE,&old)!=FALSE,"test unprotect failed");
    registry.restore(saved);bytes(currentTest.bytes.data(),0x11);bytes(page.data,0x22);
    // A TLS-pointer change is independent from the FLS roots and is refused.
    worker.call([&]{registry.observe();currentTest.overrideTls=nullptr;registry.observe();});
    currentTest.bytes.fill(0x77);rejects([&]{registry.restore(saved);});bytes(currentTest.bytes.data(),0x77);
}
static void identitiesIndicesAndUnobservedCaller() {
    Fixture f;f.initialize(7);t::ThreadRegistry a([&]{return f.read();}),b([&]{return f.read();});
    rejects([&]{a.capture();});a.observe();b.observe();const auto saved=a.capture();currentTest.bytes.fill(8);
    rejects([&]{b.restore(saved);});rejects([&]{a.restore(t::ThreadRegistry::Snapshot{});});
    ++f.tlsIndex;rejects([&]{a.restore(saved);});bytes(currentTest.bytes.data(),8);--f.tlsIndex;
    a.restore(saved);bytes(currentTest.bytes.data(),7);
    t::ThreadRegistry foreign([&]{auto r=f.read();r.threadId^=1;return r;});rejects([&]{foreign.observe();});
    check(FlsSetValue(f.ucrt,reinterpret_cast<void*>(~uintptr_t(0)))!=FALSE,"test sentinel set failed");
    rejects([&]{a.observe();});check(FlsSetValue(f.ucrt,&f.roots[1])!=FALSE,"test sentinel clear failed");
    const DWORD index=f.ucrt;f.ucrt=FLS_OUT_OF_INDEXES;rejects([&]{a.observe();});f.ucrt=index;
}
static void threadLimitAndHandles() {
    Fixture f;f.initialize(1);std::vector<std::unique_ptr<Worker>> workers;
    for(size_t i=0;i<8;++i)workers.push_back(std::make_unique<Worker>());
    DWORD before=0,during=0,after=0;check(GetProcessHandleCount(GetCurrentProcess(),&before)!=FALSE,"handle baseline failed");
    {
        t::ThreadRegistry registry([&]{return f.read();});registry.observe();
        for(size_t i=0;i<7;++i)workers[i]->call([&,i]{f.initialize(2,2*i+2);registry.observe();});
        check(registry.threadCount()==8,"eight threads were not retained");
        check(GetProcessHandleCount(GetCurrentProcess(),&during)!=FALSE && during==before+8,"retained handle count mismatch");
        workers[7]->call([&]{f.initialize(3,18);rejects([&]{registry.observe();});});
        check(registry.threadCount()==8,"thread limit failure changed registry");const auto saved=registry.capture();
        currentTest.bytes.fill(4);registry.restore(saved);bytes(currentTest.bytes.data(),1);
    }
    check(GetProcessHandleCount(GetCurrentProcess(),&after)!=FALSE && after==before,"registry thread handles leaked");
}
// Compile the actual GS/CRT reader path without executing any native game DLL.
t::CurrentState nativeReaderCompileCheck(HMODULE module){return t::NativeReader(module)();}
int main() {
    try {
        handoffAndRestore();currentActualRootsAndRevisions();otherThreadRootsAreObserved();
        newThreadAndExitedThread();fullValidationBeforeAnyCopy();identitiesIndicesAndUnobservedCaller();
        threadLimitAndHandles();rejects([]{t::NativeReader reader(nullptr);});
        std::cout<<"thread state: 8 owned Windows TLS/FLS scenario groups PASS\n";return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
