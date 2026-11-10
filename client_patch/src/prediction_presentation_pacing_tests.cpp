// Actual presentation wrapper with an authored native host, not a game/DLL.
#include "prediction_pacing.hpp"
#include <cassert>
#include <cstring>
#include <deque>
#include <iostream>
namespace p=ba_prediction_pacing;
static uint64_t nowUs=0;
static bool active=true,requested=false,matchActive=false,failed=false;
static unsigned originals=0,movementPublications=0,timingPublications=0;
struct FakeSim {unsigned char bytes[0x118]{};};
static FakeSim primary,foreign;
static void* expected=nullptr;
static p::Policy policy;
template<class T> static void put(void* object,size_t offset,T value) {
    std::memcpy(static_cast<unsigned char*>(object)+offset,&value,sizeof(value));
}
template<class T> static T get(void* object,size_t offset) {
    T value{};std::memcpy(&value,static_cast<unsigned char*>(object)+offset,sizeof(value));return value;
}
static void original(void* simulation,void* method) {
    assert(method==reinterpret_cast<void*>(0x1234));++originals;
    if(!get<void*>(simulation,0x110))return;
    const int frame=get<int>(simulation,0xac)+1;
    put(simulation,0xac,frame);put<void*>(simulation,0x110,nullptr);
}
namespace ba {
using Obj=void*;
static void init(){}
static void log(const char*,...){}
template<class Function> static Function native(uint64_t rva) {
    assert(rva==0x3e65c70);return reinterpret_cast<Function>(&original);
}
template<class T> static T read(Obj object,size_t offset){return get<T>(object,offset);}
}
namespace ba_lan {
static ba_online_frame_clock::MicrosecondClock presentationClock;
static std::deque<int> frames;
static bool presentationActive(void*){return active;}
static uint64_t presentationNowUs(){return nowUs;}
static uint64_t movementPacingNowUs(){return nowUs;}
static void fail(const char*,const std::exception&){failed=true;}
}
namespace ba_prediction_movement {
static bool ownsPresentation(void* simulation){return requested && matchActive && simulation==expected;}
static bool canPublish(void* simulation,uint64_t now){
    assert(simulation==expected);return policy.canPublish(policy.observedQueued(),now);
}
static void published(void* simulation,uint64_t now){
    ++movementPublications;policy.published(get<int>(simulation,0xac),now);
}
}
namespace ba_frame_timing {
static void published(void*,size_t){++timingPublications;}
}
#include "online_presentation.cpp"
static void reset() {
    primary=FakeSim{};foreign=FakeSim{};put(&primary,0xac,-1);put(&foreign,0xac,-1);
    active=true;requested=matchActive=failed=false;originals=movementPublications=timingPublications=0;
    nowUs=0;expected=&primary;policy.reset();ba_lan::presentationClock.reset();
}
static void available(void* simulation){put<void*>(simulation,0x110,reinterpret_cast<void*>(1));}
static void present(void* simulation){OfflinePresentAvailableSimFrame(simulation,reinterpret_cast<void*>(0x1234));}
static void queued(int frame,uint64_t at) {
    const auto d=policy.decide(frame,get<int>(&primary,0xac),(std::min)(policy.received(),static_cast<p::Frame>(frame-1)),at,130000);
    assert(d.allowed);policy.queued(d);available(&primary);
}
int main() {
    reset();available(&primary);present(&primary);
    assert(originals==1 && get<int>(&primary,0xac)==0 && movementPublications==0);
    available(&primary);nowUs=10000;present(&primary);assert(originals==1);
    nowUs=50000;present(&primary);assert(originals==2 && get<int>(&primary,0xac)==1);
    assert(ba_lan::presentationClock.started() && !failed); // Ordinary phase unchanged.

    reset();requested=true;matchActive=false;available(&primary);present(&primary);
    assert(originals==1 && movementPublications==0 && ba_lan::presentationClock.started());

    reset();requested=matchActive=true;available(&foreign);present(&foreign);
    assert(originals==1 && movementPublications==0 && ba_lan::presentationClock.started());

    reset();requested=matchActive=true;policy.authorityReceived(0,0);queued(0,0);
    nowUs=100000;present(&primary);
    assert(originals==1 && movementPublications==1 && policy.observedPresented()==0);
    assert(!ba_lan::presentationClock.started()); // NO second independent clock.
    policy.authorityReceived(1,1000000);queued(1,1000000);nowUs=1001000;present(&primary);
    assert(policy.observedPresented()==1 && movementPublications==2);
    queued(2,1025000);nowUs=1025000;present(&primary);
    assert(get<int>(&primary,0xac)==1 && originals==2); // Actual publication gap24ms.
    nowUs=1026000;present(&primary);
    assert(get<int>(&primary,0xac)==2 && policy.observedPresented()==2 && originals==3);
    assert(timingPublications==3 && !ba_lan::presentationClock.started() && !failed);

    reset();requested=matchActive=true;available(&primary);present(&primary);
    assert(failed && originals==0 && get<int>(&primary,0xac)==-1);
    std::cout<<"PASS 5 actual-wrapper pacing/inactive/foreign/spacing/failure cases; authored host only\n";
}
