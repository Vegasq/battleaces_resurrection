#include "prediction_pacing.hpp"
#include "original_command_scheduling.hpp"
#include <cassert>
#include <iostream>
#include <string>
#include <vector>
#include <deque>
#include "community_wire.hpp"
using ULONGLONG=unsigned long long;
static ULONGLONG controlNow=100;
static ULONGLONG GetTickCount64(){return controlNow;}
namespace ba_public {static void controlReset(){}}
namespace ba_client {static void controlReset(){}}
namespace ba_lan {
static ba_community_wire::Packet sentControl{};
static ba_prediction_pacing::RoundTrips capturedRoundTrips;
static uint64_t capturedGeneration=0;
static bool movementPacingRequested(){return true;}
static uint64_t movementPacingNowUs(){return controlNow*1000;}
static bool movementRefreshActive(){return false;}
static bool movementRefreshDue(uint64_t,uint64_t,bool){return false;}
static void movementRefreshSent(uint64_t,uint32_t,uint64_t){}
static void movementDirectoryReceived(uint64_t){}
static void resetMovementRoundTrips(){capturedRoundTrips=ba_prediction_pacing::RoundTrips{};capturedGeneration=0;}
static void movementRoundTrip(uint64_t generation,unsigned char kind,uint32_t request,uint64_t sentUs,uint64_t receivedUs){
    assert(kind==ba_community_wire::Refresh && request);
    if(generation!=capturedGeneration){capturedRoundTrips.reset(generation);capturedGeneration=generation;}
    assert(capturedRoundTrips.observe(generation,sentUs,receivedUs));
}
static std::string authenticatedProfile(){return "pacing_test";}
static void send(unsigned char kind,const std::vector<unsigned char>& data){sentControl={kind,data};}
}
#include "community_transport.cpp"
namespace p=ba_prediction_pacing;
using p::Frame;using p::Tick;
static unsigned cases=0;
template<class Fn> static bool refused(Fn fn) {try{fn();return false;}catch(const std::exception&){return true;}}
static void targetExamples() {
    auto a=p::assignmentTarget(299,1000000,1000000,130000);
    assert(a.assigned==302 && a.head==301 && a.rawLead==3 && !a.capped);++cases;
    auto b=p::assignmentTarget(399,1000000,1000000,475000);
    assert(b.assigned==409 && b.head==408 && b.rawLead==10 && !b.capped);++cases;
    assert(p::assignmentTarget(299,1000000,1020000,130000).assigned==302);
    assert(p::assignmentTarget(299,1000000,1020001,130000).assigned==303);++cases;
    auto cap=p::assignmentTarget(99,1000000,2000000,475000);
    assert(cap.assigned==111 && cap.head==110 && cap.rawLead==30 && cap.capped);++cases;
    assert(refused([]{p::assignmentTarget(0,0,0,130000);}));
    assert(refused([]{p::assignmentTarget(99,20,19,130000);}));
    assert(refused([]{p::assignmentTarget(p::maximumFrame,0,0,130000);}));
    assert(refused([]{p::assignmentTarget(99,0,1,(std::numeric_limits<Tick>::max)());}));++cases;
}
static void roundTripsAndRealAck() {
    p::RoundTrips r;r.reset(7);
    assert(!r.estimate());assert(!r.observe(6,0,130000));assert(!r.observe(7,10,9));
    assert(!r.observe(7,0,2000001));assert(!r.estimate());++cases;
    // Real existing protocol ACK validation, not a permissive authored copy.
    ba_original_commands::State s;s.request();
    assert(refused([&]{s.acknowledge({2});}));assert(s.pending());
    s.acknowledge({1});assert(r.observe(7,0,475000));assert(*r.estimate()==475000);
    assert(refused([&]{s.acknowledge({1});}));++cases;
    assert(r.observe(7,1000000,2400000)); // UI/server-load positive outlier.
    assert(*r.estimate()==475000);
    assert(r.observe(7,3000000,3130000));assert(*r.estimate()==130000);++cases;
    r.reset(8);assert(!r.estimate() && !r.observe(7,0,130000));
    for(unsigned i=0;i<16;++i)assert(r.observe(8,i*1000000ull,i*1000000ull+475000));
    assert(r.count()>0 && r.count()<=8 && *r.estimate()==475000);++cases;
}
static void realCommunityCorrelation() {
    namespace c=ba_community;namespace w=ba_community_wire;
    c::reset();c::pollMovementRefresh();controlNow=100;assert(c::player("absent")==nullptr);
    w::Writer greeting;greeting.number(1,2);greeting.number(3,2);greeting.id("pacing_test");
    greeting.deck({1,2,3,4,5,6,7,8});c::receive(w::WelcomeKind,greeting.bytes);
    const auto request=c::send(w::refresh(c::nextRequest()));
    assert(ba_lan::sentControl.kind==w::Refresh && c::pending.size()==1);
    const auto sentAt=c::pending.at(request).deadline-15000;
    p::RoundTrips r;r.reset(c::generation);
    const auto accept=[&](const w::Bytes& bytes) {
        const auto generation=c::generation;
        c::receive(w::AckKind,bytes); // Existing exact ID/kind guard MUST run first.
        assert(r.observe(generation,sentAt*1000,controlNow*1000));
    };
    w::Writer ack;ack.number(request,4);ack.number(w::Refresh,1);ack.number(1,1);ack.text("");ack.text("");
    auto wrong=ack.bytes;wrong[4]=w::Leave;controlNow=230;
    assert(refused([&]{accept(wrong);}));assert(!r.estimate() && c::pending.size()==1);
    accept(ack.bytes);assert(*r.estimate()==130000 && c::pending.empty());
    assert(ba_lan::capturedRoundTrips.count()==1 && *ba_lan::capturedRoundTrips.estimate()==130000);
    assert(ba_lan::capturedGeneration==c::generation);
    assert(refused([&]{accept(ack.bytes);}));assert(r.count()==1);
    c::checkTimeouts();c::reset();++cases;
}
static void queue(p::Policy& s,Frame frame,int presented,Frame projected,Tick now,Tick rtt) {
    auto d=s.decide(frame,presented,projected,now,rtt);assert(d.allowed);s.queued(d);
}
static void barrierAndOneOutput() {
    p::Policy s;s.authorityReceived(0,1000000);
    queue(s,0,-1,-1,1000000,130000);
    // The REAL source one-output predicate refuses a second native input.
    assert(s.decide(1,-1,0,1100000,130000).wait==p::Wait::NativeOutput);
    s.published(0,1200000);
    for(Tick now=1200000;now<9000000;now+=50000)
        assert(s.decide(1,0,0,now,130000).wait==p::Wait::SteadyFrameOne);
    assert(s.observedQueued()==0 && s.observedPresented()==0);++cases;
    s.authorityReceived(1,9000000);
    assert(s.decide(1,0,0,9000000,std::nullopt).wait==p::Wait::RoundTrip);
    auto d=s.decide(1,0,0,9000000,130000);assert(d.allowed && d.acquiring);s.queued(d);
    assert(refused([&]{s.queued(d);}));++cases;
    assert(s.canPublish(1,9000001));s.published(1,9000001);
    auto before=s.observedQueued();
    assert(s.decide(2,1,0,9024999,130000).wait==p::Wait::Spacing);
    assert(s.observedQueued()==before);
    queue(s,2,1,0,9025000,130000);
    assert(!s.canPublish(2,9025000));assert(s.canPublish(2,9025001));++cases;
}
static void receiptAtomicityAndReset() {
    p::Policy s;
    assert(refused([&]{s.authorityReceived(1,50);}));assert(s.received()==-1);
    s.authorityReceived(0,100);
    assert(refused([&]{s.authorityReceived(0,101);}));
    assert(refused([&]{s.authorityReceived(1,99);}));assert(s.received()==0);
    s.reset();assert(s.received()==-1 && s.observedQueued()==-1 && s.observedPresented()==-1);++cases;
}
struct Run {std::vector<Tick> feeds,publications;Frame head=-1,received=-1;Tick acquired=0;};
// Authored loopback time model, NOT a native/client acceptance test. Every input
// spends a real numbered slot and every sole output must be observed/published.
static Run simulate(Tick rtt,unsigned refresh,Tick end,bool pause) {
    p::Policy policy;Run out;
    constexpr Tick steadyAt=1000000,nativeWork=2000;
    policy.authorityReceived(0,0);queue(policy,0,-1,-1,0,rtt);policy.published(0,nativeWork);
    out.feeds.push_back(0);out.publications.push_back(nativeWork);
    Frame next=1,presented=0,pending=-1,arrived=0;Tick readyAt=0;
    for(Tick poll=0;;++poll) {
        const Tick now=poll*1000000/refresh;if(now>end)break;
        if(pause && now>=3000000 && now<3600000)continue;
        while(now>=steadyAt+static_cast<Tick>(arrived)*p::stepUs) {
            ++arrived;policy.authorityReceived(arrived,now);
        }
        if(pending>=0 && now>=readyAt && policy.canPublish(pending,now)) {
            policy.published(pending,now);presented=pending;pending=-1;out.publications.push_back(now);
        }
        const Frame projected=(std::min)(arrived,next-1);
        auto d=policy.decide(next,static_cast<int>(presented),projected,now,rtt);
        if(d.allowed) {
            assert(pending==-1);policy.queued(d);pending=next++;readyAt=now+nativeWork;out.feeds.push_back(now);
            if(!d.acquiring && d.frame>0 && !out.acquired)out.acquired=now;
        }
    }
    out.head=next-1;out.received=arrived;return out;
}
static void phaseAcquisitionAndSteady() {
    for(Tick rtt:{130000ull,475000ull}) {
        for(unsigned refresh:{32u,60u,144u,1000u}) {
            auto run=simulate(rtt,refresh,10000000,false);
            assert(run.acquired>=1000000 && run.acquired<=2200000);
            for(size_t i=2;i<run.feeds.size();++i)assert(run.feeds[i]-run.feeds[i-1]>=25000);
            for(size_t i=2;i<run.publications.size();++i)assert(run.publications[i]-run.publications[i-1]>=25000);
            unsigned steady=0;for(auto t:run.feeds)if(t>=4000000 && t<9000000)++steady;
            assert(steady>=99 && steady<=101); // Real20Hz average, including32Hz polls.
            const Frame maximumLead=static_cast<Frame>((rtt+p::stepUs-1)/p::stepUs);
            assert(run.head-run.received>=maximumLead-2 && run.head-run.received<=maximumLead);
            std::cout<<"model rtt_us="<<rtt<<" refresh="<<refresh<<" acquired_us="<<run.acquired
                     <<" steady5s_frames="<<steady<<" head_minus_received="<<run.head-run.received<<'\n';
        }
    }
    ++cases;
}
static void pauseAndLateBurst() {
    for(Tick rtt:{130000ull,475000ull}) {
        auto run=simulate(rtt,1000,10000000,true);
        for(size_t i=2;i<run.feeds.size();++i)assert(run.feeds[i]-run.feeds[i-1]>=25000);
        unsigned steady=0;for(auto t:run.feeds)if(t>=6000000 && t<9000000)++steady;
        assert(steady>=59 && steady<=61);
        assert(run.head-run.received<=12);
    }
    ++cases;
    p::Policy s;s.authorityReceived(0,0);queue(s,0,-1,-1,0,475000);s.published(0,2000);
    s.authorityReceived(1,1000000);
    for(Frame f=1;f<=12;++f) {
        const Tick t=2000000+static_cast<Tick>(f)*25000;
        queue(s,f,static_cast<int>(f-1),0,t,475000);s.published(f,t+1);
    }
    // Receipt2 permits target head13 while actual projected confirmation is
    // deliberately still0. This reaches the distinct worker safety ceiling.
    s.authorityReceived(2,3000000);
    const auto blocked=s.decide(13,12,0,4000000,475000);
    assert(!blocked.allowed && blocked.wait==p::Wait::Budget && s.observedQueued()==12);++cases;
}
int main() {
    targetExamples();roundTripsAndRealAck();realCommunityCorrelation();barrierAndOneOutput();receiptAtomicityAndReset();
    phaseAcquisitionAndSteady();pauseAndLateBurst();
    std::cout<<"PASS "<<cases<<" authored pacing cases; no Simulation.dll/Unity/runtime executed\n";
}
