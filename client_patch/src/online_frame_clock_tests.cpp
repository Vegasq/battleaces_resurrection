#include "online_frame_clock.hpp"
#include <cassert>
#include <cstdint>
#include <iostream>
#include <limits>
#include <vector>

// Compile with BA_ONLINE_FRAME_CLOCK_LEGACY to run these same acceptance
// checks against the former lan_transport.cpp deadline algorithm. The burst
// regression must fail; this switch never changes the product clock.
#ifdef BA_ONLINE_FRAME_CLOCK_LEGACY
struct TestClock {
    bool active=false;uint64_t next=0;
    void reset(){active=false;next=0;}
    bool started()const{return active;}
    void start(uint64_t now){if(!active){active=true;next=now;}}
    bool ready(uint64_t now)const{return active && now>=next;}
    void pushed(uint64_t now){next+=50;if(now>next+50)next=now+50;}
};
#else
using TestClock=ba_online_frame_clock::Clock;
#endif

static void spacing(const std::vector<uint64_t>& pushed) {
    for(size_t i=1;i<pushed.size();++i)assert(pushed[i]-pushed[i-1]>=25);
}
static void steady(unsigned refreshHz) {
    TestClock clock;clock.start(0);std::vector<uint64_t> pushed;
    for(uint64_t update=0;update<=static_cast<uint64_t>(refreshHz)*60;++update) {
        const uint64_t now=update*1000/refreshHz;
        if(clock.ready(now)){clock.pushed(now);pushed.push_back(now);}
        assert(!clock.ready(now)); // A second callback in the same OS timestamp.
    }
    // At least20Hz main-thread updates must sustain the50ms simulation clock,
    // including32Hz,where blindly using now+50 would drop to16Hz.
    assert(pushed.size()>=1200 && pushed.size()<=1201);
    assert(pushed.back()>=59950 && pushed.back()<=60000);spacing(pushed);
}
static void overdueBurst() {
    TestClock clock;clock.start(950);assert(clock.ready(950));clock.pushed(950);
    assert(!clock.ready(999));assert(clock.ready(1000));
    // No packet is available at deadline1000. A batch arrives90ms late.
    assert(clock.ready(1090));clock.pushed(1090);
    assert(!clock.ready(1090));assert(!clock.ready(1091));assert(!clock.ready(1114));
    assert(clock.ready(1115));clock.pushed(1115);
    assert(!clock.ready(1116));assert(clock.ready(1140));clock.pushed(1140);
    assert(!clock.ready(1141));
    std::vector<uint64_t> pushed{950,1090,1115,1140};
    for(uint64_t now=1141;now<=2000;++now)
        if(clock.ready(now)){clock.pushed(now);pushed.push_back(now);}
    spacing(pushed);
    // The short deficit is recovered;the clock resumes its original phase.
    assert(pushed.back()==2000);
}
static void longUnderrun() {
    for(uint64_t stalled:{100u,150u,5000u}) {
        TestClock clock;clock.start(1000);clock.pushed(1000);
        const uint64_t resumed=1050+stalled;
        std::vector<uint64_t> pushed;
        for(uint64_t now=resumed;now<=resumed+1000;++now)
            if(clock.ready(now)){clock.pushed(now);pushed.push_back(now);}
        spacing(pushed);
        // Replaying a huge elapsed wall-time debt must never fast-forward the
        // entire backlog. At most two extra recovery ticks are allowed here.
        assert(pushed.size()>=20 && pushed.size()<=23);
        unsigned recoveryGaps=0;
        for(size_t i=1;i<pushed.size();++i)if(pushed[i]-pushed[i-1]<50)++recoveryGaps;
        assert(recoveryGaps<=4);
    }
}
static void traceInspiredBatches() {
    // Real rc1.10 capture had batches531..534 after a110ms pause and563..565
    // after141ms. Reproduce the same interrupted steady stream at small IDs.
    TestClock clock;clock.start(0);std::vector<uint64_t> pushed;
    unsigned arrived=0,applied=0;
    std::vector<uint64_t> arrivals;
    for(unsigned frame=0;frame<90;++frame) {
        uint64_t time=frame*50;
        if(frame>=20 && frame<=22)time=1090;
        if(frame>=52 && frame<=54)time=2741;
        arrivals.push_back(time);
    }
    for(uint64_t now=0;now<=5000;++now) {
        while(arrived<arrivals.size() && arrivals[arrived]<=now)++arrived;
        if(applied<arrived && clock.ready(now)) {
            clock.pushed(now);pushed.push_back(now);++applied;
        }
    }
    assert(applied==arrivals.size());spacing(pushed);
}
static void lifecycleAndBounds() {
    TestClock clock;assert(!clock.started() && !clock.ready(1000));
    clock.start(0);assert(clock.ready(0));clock.pushed(0);
    clock.start(1);assert(!clock.ready(25)); // Starting again cannot pull phase.
    assert(clock.ready(50));clock.pushed(50);assert(!clock.ready(49));
    clock.reset();assert(!clock.started() && !clock.ready(10000));
    clock.start(10000);assert(clock.ready(10000));
#ifndef BA_ONLINE_FRAME_CLOCK_LEGACY
    const auto maximum=(std::numeric_limits<uint64_t>::max)();
    clock.reset();clock.start(maximum-100);clock.pushed(maximum-100);
    assert(!clock.ready(maximum-51));assert(clock.ready(maximum-50));
    clock.pushed(maximum-50);assert(!clock.ready(maximum-1));assert(clock.ready(maximum));
    clock.pushed(maximum);assert(!clock.ready(maximum));
#endif
}
static void microsecondPublicationClock() {
    ba_online_frame_clock::MicrosecondClock clock;
    clock.start(1000000);assert(clock.ready(1000000));clock.pushed(1000000);
    assert(!clock.ready(1049999));assert(clock.ready(1050000));
    clock.pushed(1090000);
    assert(!clock.ready(1114999));assert(clock.ready(1115000));
    clock.pushed(1115000);assert(!clock.ready(1149999));assert(clock.ready(1150000));
}
static void replaceableNativeOutputSlot() {
    // Inputs are available in a burst, but the native output buffer can hold
    // only one result. Running the worker ahead would overwrite those results.
    ba_online_frame_clock::Clock clock;clock.start(0);
    int next=0,presented=-1,pending=-1,lastPublished=-1;unsigned consumed=0;
    for(uint64_t now=0;now<=10000;++now) {
        if(next<160 && ba_online_frame_clock::canFeed(next,presented)) {
            assert(pending==-1);pending=next++;
        }
        if(pending>=0 && clock.ready(now)) {
            assert(pending==presented+1);presented=pending;pending=-1;
            if(lastPublished>=0)assert(now-static_cast<uint64_t>(lastPublished)>=25);
            lastPublished=static_cast<int>(now);clock.pushed(now);++consumed;
        }
    }
    assert(consumed==160 && presented==159 && next==160);
    assert(!ba_online_frame_clock::canFeed(0,0));
    assert(!ba_online_frame_clock::canFeed(2,0));
    assert(!ba_online_frame_clock::canFeed(-1,-2));
}
int main() {
    microsecondPublicationClock();
    replaceableNativeOutputSlot();
    overdueBurst();longUnderrun();traceInspiredBatches();lifecycleAndBounds();
    for(unsigned refresh:{20u,25u,30u,32u,60u,64u})steady(refresh);
    std::cout<<"Online clock preserves20Hz phase and bounds starvation recovery to spaced native pushes\n";
}
