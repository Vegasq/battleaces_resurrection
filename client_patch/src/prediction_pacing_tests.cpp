#include "prediction_pacing.hpp"
#include "original_command_scheduling.hpp"
#include <cassert>
#include <iostream>
#include <string>
#include <vector>
#include <deque>
#include <queue>
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
static void steadyCadenceGatesAndReset() {
    p::Policy s;s.authorityReceived(0,0);queue(s,0,-1,-1,0,1);s.published(0,2000);
    // One-microsecond RTT isolates the exact initial acquisition transition.
    s.authorityReceived(1,1000000);
    auto first=s.decide(1,0,0,1000000,1);
    assert(first.allowed && !first.acquiring && first.nextDeadline==1050000);
    s.queued(first);s.published(1,1002000);
    assert(s.decide(2,1,1,1025000,475000).wait==p::Wait::Spacing);
    auto second=s.decide(2,1,1,1050000,475000);
    assert(second.allowed && !second.acquiring && second.frame==2 && second.nextDeadline==1095000);
    s.queued(second);
    assert(refused([&]{s.queued(second);}));assert(s.observedQueued()==2);++cases;
    // A due deadline cannot override the sole original output. A real long
    // native stall rebases only the following deadline, with no stale burst.
    assert(s.decide(3,1,1,1400000,475000).wait==p::Wait::NativeOutput);
    s.published(2,1400000);
    auto third=s.decide(3,2,1,1400000,475000);
    assert(third.allowed && third.nextDeadline==1445000);
    assert(s.decide(3,2,1,1400000,475000).nextDeadline==third.nextDeadline);
    s.queued(third);s.published(3,1425000);
    assert(s.decide(4,3,1,1425000,475000).wait==p::Wait::Spacing);
    assert(s.decide(4,3,1,1445000,std::nullopt).wait==p::Wait::RoundTrip);
    assert(s.observedQueued()==3);++cases;
    assert(refused([&]{s.decide(4,3,1,1399999,475000);}));
    assert(refused([&]{s.decide(4,3,4,1445000,475000);}));
    s.reset();assert(refused([&]{s.queued(third);}));
    assert(s.received()==-1 && s.observedQueued()==-1 && s.observedPresented()==-1);
    s.authorityReceived(0,0);queue(s,0,-1,-1,0,130000);s.published(0,2000);
    assert(s.decide(1,0,0,1000000,130000).wait==p::Wait::SteadyFrameOne);++cases;
    p::RoundTrips r;r.reset(20);assert(r.observe(20,0,130000));
    assert(!r.estimate(4130001));r.reset(21);
    assert(!r.observe(20,5000000,5130000) && !r.estimate());++cases;
    p::Policy exhausted;exhausted.authorityReceived(0,0);
    queue(exhausted,0,-1,-1,0,1);exhausted.published(0,2000);
    const Tick end=(std::numeric_limits<Tick>::max)()-10000;
    exhausted.authorityReceived(1,end);
    assert(refused([&]{exhausted.decide(1,0,0,end,1);}));
    assert(exhausted.observedQueued()==0);++cases;
}
struct PhasePoint {Tick at=0;Frame error=0;};
struct Run {std::vector<Tick> feeds,publications;std::vector<PhasePoint> phases;Frame head=-1,received=-1;Tick acquired=0;};
// Authored loopback time model, NOT a native/client acceptance test. Every input
// spends a real numbered slot and every sole output must be observed/published.
static Run simulate(Tick rtt,unsigned refresh,Tick end,bool pause,bool changing=false) {
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
        const Tick currentRtt=changing && now>=5000000 && now<12000000?475000:rtt;
        auto d=policy.decide(next,static_cast<int>(presented),projected,now,currentRtt);
        if(d.allowed) {
            assert(pending==-1 && next-projected<=p::maximumAhead);
            if(next)out.phases.push_back(PhasePoint{now,d.target.assigned-next});
            policy.queued(d);pending=next++;readyAt=now+nativeWork;out.feeds.push_back(now);
            if(!d.acquiring && d.frame>0 && !out.acquired)out.acquired=now;
        }
    }
    out.head=next-1;out.received=arrived;return out;
}
static void changingPathContinuity() {
    for(unsigned refresh:{32u,60u,64u,144u,1000u}) {
        const auto run=simulate(130000,refresh,20000000,false,true);
        Tick maximumFallGap=0,minimumRiseGap=(std::numeric_limits<Tick>::max)();
        for(size_t i=1;i<run.publications.size();++i) {
            const Tick now=run.publications[i],gap=now-run.publications[i-1];
            if(now>=12000000 && now<14000000)maximumFallGap=(std::max)(maximumFallGap,gap);
            if(now>=5000000 && now<7000000)minimumRiseGap=(std::min)(minimumRiseGap,gap);
        }
        std::cout<<"transition model refresh="<<refresh<<" fall_max_gap_us="<<maximumFallGap
                 <<" rise_min_gap_us="<<minimumRiseGap<<std::endl;
        // Regression for the real changing-path RED. This is an authored
        // source-level gate, not a claim about Unity interpolation or inputs.
        assert(maximumFallGap<100000 && minimumRiseGap>=p::minimumSpacingUs);
        for(Tick begin:{3500000ull,10000000ull,18000000ull}) {
            unsigned frames=0;for(auto t:run.feeds)if(t>=begin && t<begin+1000000)++frames;
            assert(frames>=19 && frames<=21);
            for(const auto& phase:run.phases)if(phase.at>=begin&&phase.at<begin+1000000)
                assert(phase.error>=-1&&phase.error<=1);
        }
    }
    ++cases;
}
static void phaseAcquisitionAndSteady() {
    for(Tick rtt:{130000ull,475000ull}) {
        for(unsigned refresh:{32u,60u,64u,144u,1000u}) {
            auto run=simulate(rtt,refresh,10000000,false);
            assert(run.acquired>=1000000 && run.acquired<=2200000);
            for(size_t i=2;i<run.feeds.size();++i)assert(run.feeds[i]-run.feeds[i-1]>=25000);
            for(size_t i=2;i<run.publications.size();++i)assert(run.publications[i]-run.publications[i-1]>=25000);
            unsigned steady=0;for(auto t:run.feeds)if(t>=4000000 && t<9000000)++steady;
            assert(steady>=99 && steady<=101); // Real20Hz average, including32Hz polls.
            const Frame maximumLead=static_cast<Frame>((rtt+p::stepUs-1)/p::stepUs);
            assert(run.head-run.received>=maximumLead-2 && run.head-run.received<=maximumLead);
            Frame low=p::maximumFrame,high=-p::maximumFrame;unsigned behind=0;
            for(const auto& phase:run.phases)if(phase.at>=4000000&&phase.at<9000000) {
                low=(std::min)(low,phase.error);high=(std::max)(high,phase.error);if(phase.error>1)++behind;
            }
            std::cout<<"model rtt_us="<<rtt<<" refresh="<<refresh<<" acquired_us="<<run.acquired
                     <<" steady5s_frames="<<steady<<" head_minus_received="<<run.head-run.received
                     <<" assigned_minus_next_min="<<low<<" max="<<high<<" queues_late_by2plus="<<behind<<'\n';
            assert(low>=-1&&high<=1);
        }
    }
    ++cases;
}
static void pauseAndLateBurst() {
    for(Tick rtt:{130000ull,475000ull}) {
        auto run=simulate(rtt,1000,15000000,true);
        for(size_t i=2;i<run.feeds.size();++i)assert(run.feeds[i]-run.feeds[i-1]>=25000);
        // The pause loses twelve physical slots. Bounded5ms phase slew can
        // need six seconds; recovery is intentionally no longer a40Hz burst.
        unsigned steady=0;for(auto t:run.feeds)if(t>=12000000 && t<15000000)++steady;
        std::cout<<"pause model rtt_us="<<rtt<<" recovered3s_frames="<<steady<<std::endl;
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
static void cursorPhaseRegression() {
    p::Policy s;s.authorityReceived(0,0);queue(s,0,-1,-1,0,1);s.published(0,2000);
    s.authorityReceived(1,1000000);queue(s,1,0,0,1000000,1);s.published(1,1002000);
    const auto behind=s.decide(2,1,1,1050000,50001);
    assert(behind.allowed&&behind.target.assigned==4&&behind.frame==2);
    std::cout<<"cursor regression next="<<behind.frame<<" targetAssigned="<<behind.target.assigned
             <<" following_deadline_us="<<behind.nextDeadline<<std::endl;
    // Own immutable67 is assigned NEXT=2 before this physical queue. Desired
    // assignment4 is TWO frames ahead, outside the one-frame neutral band.
    assert(behind.nextDeadline==1095000);++cases;

    p::Policy ahead;ahead.authorityReceived(0,0);queue(ahead,0,-1,-1,0,475000);ahead.published(0,2000);
    ahead.authorityReceived(1,1000000);
    for(Frame f=1;f<=12;++f) {
        const Tick t=2000000+static_cast<Tick>(f)*25000;
        queue(ahead,f,static_cast<int>(f-1),0,t,475000);ahead.published(f,t+1);
    }
    for(Frame f=2;f<=11;++f)ahead.authorityReceived(f,3000000);
    const auto neutral=ahead.decide(13,12,11,3000000,1);
    assert(neutral.allowed&&neutral.target.assigned==12&&neutral.frame==13);
    // The former integer deadband kept this at50ms (preserved in the old
    // source/RED control). Continuous clamped lead is50ms, so NEXT13 is a full
    //50ms ahead of received11+lead1 and must slow at55ms, including rebase.
    assert(neutral.nextDeadline==3055000);++cases;
}
static void fractionalBounds() {
    assert(p::fractionalPeriod(10,12,0,104000)==49500);
    assert(p::fractionalPeriod(10,12,0,100000)==50000);
    assert(p::fractionalPeriod(10,12,0,96000)==50500);++cases;
    // Same ceil assignment, different subframe phase: the old deadband lost it.
    assert(p::assignmentTarget(10,0,0,100001).assigned==13);
    assert(p::assignmentTarget(10,0,0,149999).assigned==13);
    assert(p::fractionalPeriod(10,13,0,100001)==55000);
    assert(p::fractionalPeriod(10,13,0,149999)==50000);++cases;
    assert(p::fractionalPeriod(10,11,0,0)==50000);
    assert(p::fractionalPeriod(10,11,49999,0)==50000);
    assert(p::fractionalPeriod(10,22,0,600000)==50000);
    assert(p::fractionalPeriod(10,22,(std::numeric_limits<Tick>::max)(),0)==50000);++cases;
    assert(p::fractionalPeriod(10,12,20000,80000)==50000);
    assert(p::fractionalPeriod(10,12,99999,1)==50000);++cases;
    assert(p::fractionalPeriod(1,p::maximumFrame,0,0)==55000);
    assert(p::fractionalPeriod(p::maximumFrame,1,0,600000)==45000);++cases;
    assert(refused([]{p::fractionalPeriod(0,1,0,0);}));
    assert(refused([]{p::fractionalPeriod(1,-1,0,0);}));
    assert(refused([]{p::fractionalPeriod(p::maximumFrame+1,1,0,0);}));
    assert(refused([]{p::fractionalPeriod(1,(std::numeric_limits<Frame>::min)(),0,0);}));++cases;
    assert(refused([]{p::fractionalPeriod(1,1,1,(std::numeric_limits<Tick>::max)());}));
    assert(refused([]{p::fractionalPeriod(1,1,(std::numeric_limits<Tick>::max)(),1);}));++cases;
    p::Policy s;s.authorityReceived(0,0);queue(s,0,-1,-1,0,1);s.published(0,2000);
    s.authorityReceived(1,1000000);queue(s,1,0,0,1000000,1);s.published(1,1002000);
    assert(refused([&]{s.decide(2,1,1,1050000,(std::numeric_limits<Tick>::max)());}));
    assert(s.observedQueued()==1 && s.observedPresented()==1 && s.received()==1);
    assert(s.decide(2,1,1,1050000,50001).nextDeadline==1095000);++cases;
}

// Independent server seal and actual LOCAL_BATCH cursor oracles. These authored
// models do not assert the policy formula: each hypothetical gesture is compared
// with the next unsealed authority frame at its independently delayed arrival.
// Fixed and dynamic kernels retain the bounded private comparison grids. They
// model worker prepare/Step at1/2ms, not original native/Unity/renderer behavior.
namespace fixed_seal_oracle {
namespace p=ba_prediction_pacing;
using p::Tick;using p::Frame;
constexpr Tick serverEpoch=1000000,step=50000,endAt=20000000;
// Independent authority: frame1 seals at epoch, then every50ms. An accept
// delivered at/after that synchronous seal must enter the NEXT frame. Server
// ArrivalScheduler.next_frame advances BEFORE the worker await, so native work
// delays broadcast but NEVER widens the already sealed frame's input window.
static Frame canonicalAt(Tick send,Tick upstream){
    const Tick arrival=send+upstream;
    return arrival<serverEpoch?1:static_cast<Frame>((arrival-serverEpoch)/step)+2;
}
struct Stats {Frame low=100,high=-100;unsigned samples=0,bad=0;};
static void probe(Stats& out,Tick at,Frame head,Frame pending,Tick queuedAt,Tick upstream){
    // Mirror actual LOCAL_BATCH ABI, not the policy's target: queued but not
    // ProcessMsg-prepared remains H+1; prepared or Step-completed gives H+2.
    const bool queued=pending>=0;
    const bool prepared=queued&&at>=queuedAt+1000&&at<queuedAt+2000;
    if(queued&&at>=queuedAt+2000)head=pending;
    const Frame assigned=head+1+static_cast<int>(prepared);
    const Frame error=assigned-canonicalAt(at,upstream);
    out.low=(std::min)(out.low,error);out.high=(std::max)(out.high,error);++out.samples;
    if(error<-1||error>1)++out.bad;
}
struct Result {std::array<Stats,4> phases;unsigned steady=0;Frame lead=0;};
static Result run(Tick rtt,unsigned hz,Tick phase,Tick work,Tick controlPoll){
    p::Policy policy;Result out;Frame received=0,next=1,presented=0,head=0,pending=-1;
    Tick queuedAt=0;uint32_t random=0x8af91u;
    policy.authorityReceived(0,0);auto boot=policy.decide(0,-1,-1,0,rtt+controlPoll);policy.queued(boot);policy.published(0,2000);
    const Tick upstream=rtt/2,downstream=rtt-upstream;
    for(Tick poll=0;;++poll){
        const Tick now=phase+poll*1000000/hz;if(now>endAt)break;
        while(now>=serverEpoch+static_cast<Tick>(received)*step+work+downstream){
            ++received;policy.authorityReceived(received,now);
        }
        if(pending>=0&&now>=queuedAt+2000)head=pending;
        const bool scored=now>=8000000&&now<18000000;
        if(scored)probe(out.phases[0],now,head,pending,queuedAt,upstream); // Before originalInput/Push.
        if(pending>=0&&now>=queuedAt+2000&&policy.canPublish(pending,now)){
            policy.published(pending,now);presented=pending;pending=-1;
        }
        const Frame projected=(std::min)(received,head);
        auto d=policy.decide(next,static_cast<int>(presented),projected,now,rtt+controlPoll);
        if(d.allowed){
            p::require(pending<0&&next==head+1&&next-projected<=12,"model ownership/budget mismatch");
            policy.queued(d);pending=next++;queuedAt=now;out.lead=(std::max)(out.lead,next-1-projected);
            if(now>=10000000&&now<15000000)++out.steady;
            if(scored){
                probe(out.phases[1],now+1,head,pending,queuedAt,upstream); // Queued, unprepared.
                probe(out.phases[2],now+1000,head,pending,queuedAt,upstream); // ProcessMsg prepared.
                probe(out.phases[2],now+2000,head,pending,queuedAt,upstream); // Original Step complete.
            }
        }
        // A seeded one-shot originalInput invocation between pacing callbacks
        // samples arbitrary input phase before its own possible next Push.
        random=random*1664525u+1013904223u;
        const Tick following=phase+(poll+1)*1000000/hz;
        const Tick offset=following>now+1?1+random%(following-now-1):0;
        if(scored&&offset)probe(out.phases[3],now+offset,head,pending,queuedAt,upstream);
    }
    return out;
}
static unsigned verify(){
    unsigned failures=0,totalBad=0,totalCases=0;
    for(Tick rtt:{130000ull,475000ull})for(unsigned hz:{32u,60u,64u,144u,1000u})
        for(Tick work:{0ull,6000ull})for(Tick controlPoll:{0ull,10000ull})
            for(Tick phase:{0ull,7000ull,23000ull,49000ull}){
                const auto r=run(rtt,hz,phase,work,controlPoll);++totalCases;
                bool failed=r.steady!=100||r.lead>p::maximumAhead;
                for(const auto& s:r.phases){totalBad+=s.bad;failed=failed||!s.samples||s.bad||s.low<-1||s.high>1;}
                if(failed){++failures;std::cout<<"fixed failure rtt="<<rtt<<" hz="<<hz<<" phase="<<phase
                    <<" work="<<work<<" control="<<controlPoll<<" steady="<<r.steady<<'\n';}
            }
    assert(totalCases==160);cases+=totalCases;
    std::cout<<"independent fixed-seal cases="<<totalCases<<" failed="<<failures<<" bad_probes="<<totalBad<<'\n';
    return failures;
}

}
namespace queued_chunk_oracle {
namespace p=ba_prediction_pacing;using p::Tick;using p::Frame;
constexpr Tick epoch=1000000,step=50000,endAt=39000000;
enum Kind{FrameRead,HeartbeatRead,AckRead,FrameDelivery,AckDelivery};
struct Event{Tick at=0;uint64_t serial=0;Kind kind=FrameRead;Frame value=0;Tick sent=0;};
struct Later{bool operator()(const Event&a,const Event&b)const{return a.at>b.at||(a.at==b.at&&a.serial>b.serial);}};
struct Net{
    std::priority_queue<Event,std::vector<Event>,Later> events;
    std::vector<Event> frames,acks;
    uint64_t serial=0;Tick upDue=0,downDue=0,rise=0,fall=0,work=0,control=0,jitter=0;
    unsigned frozenChunks=0;
    void add(Tick at,Kind kind,Frame value=0,Tick sent=0){events.push({at,++serial,kind,value,sent});}
    Tick configured(Tick at)const{return rise&&at>=rise&&(!fall||at<fall)?475000:130000;}
    int64_t noise(Tick at,uint64_t salt)const{
        if(!jitter)return 0;
        uint64_t x=(at+0x9e3779b97f4a7c15ull*salt);x^=x>>30;x*=0xbf58476d1ce4e5b9ull;x^=x>>27;
        return static_cast<int64_t>(x%(2*jitter+1))-static_cast<int64_t>(jitter);
    }
    Tick duration(Tick at,uint64_t salt)const{return static_cast<Tick>(static_cast<int64_t>(configured(at)/2)+noise(at,salt));}
    Tick upstream(Tick at,uint64_t salt){const Tick desired=at+duration(at,salt);upDue=(std::max)(upDue,desired);return upDue;}
    void downstream(Tick at,Kind kind,Frame value,Tick sent){
        const Tick desired=at+duration(at,static_cast<uint64_t>(value)+53);if(desired<downDue)++frozenChunks;
        downDue=(std::max)(downDue,desired);add(downDue,kind,value,sent);
    }
    void advance(Tick until){
        while(!events.empty()&&events.top().at<=until){
            const auto e=events.top();events.pop();
            switch(e.kind){
            case FrameRead:downstream(e.at,FrameDelivery,e.value,0);break;
            case HeartbeatRead:upstream(e.at,999);break;
            case AckRead:downstream(e.at,AckDelivery,e.value,e.sent);break;
            case FrameDelivery:frames.push_back(e);break;
            case AckDelivery:acks.push_back(e);break;
            }
        }
    }
    Tick probeArrival(Tick at)const{return (std::max)(upDue,at+duration(at,997));}
};
static Frame canonicalAt(Tick arrival){return arrival<epoch?1:static_cast<Frame>((arrival-epoch)/step)+2;}
struct Stats{int low=100,high=-100;unsigned bad=0,total=0;};
static void probe(Stats& s,const Net& n,Tick at,Frame head,Frame pending,Tick queued){
    bool prepared=pending>=0&&at>=queued+1000&&at<queued+2000;
    if(pending>=0&&at>=queued+2000)head=pending;
    const Frame assigned=head+1+static_cast<int>(prepared);
    const int error=static_cast<int>(assigned-canonicalAt(n.probeArrival(at)));
    s.low=(std::min)(s.low,error);s.high=(std::max)(s.high,error);++s.total;if(error<-1||error>1)++s.bad;
}
struct Result{
    Stats baseline,afterLow,settled;Tick rise=0,fall=0,highEstimate=0,lowEstimate=0,gate=0;
    int gateError=100;unsigned frozen=0,missingRtt=0;Frame lead=0;Tick maxGap=0,lastPub=0;
    std::vector<Event> ackRows;
};
static Result run(unsigned hz,Tick phase,Tick work,Tick control,Tick jitter){
    Net net;net.work=work;net.control=control;net.jitter=jitter;
    for(Frame f=1;f<800;++f)net.add(epoch+static_cast<Tick>(f-1)*step+work,FrameRead,f);
    for(Tick at=0;at<endAt;at+=1000000)net.add(at,HeartbeatRead);
    p::Policy policy;p::RoundTrips rtts;p::RefreshRequests refresh;rtts.reset(1);refresh.reset(1);
    Result out;Frame head=0,pending=-1,received=0,next=1,presented=0;Tick queued=0,controllerAt=0,lastDense=0;
    Tick firstEligible=0,lastHighAck=0,gestureAt=0;unsigned highSamples=0;uint32_t random=0x7582a;
    uint32_t request=0;Tick pendingSent=0;bool pendingRefresh=false;
    policy.authorityReceived(0,0);auto boot=policy.decide(0,-1,-1,0,130000);policy.queued(boot);policy.published(0,2000);
    for(Tick poll=0;;++poll){
        const Tick now=phase+poll*1000000/hz;if(now>endAt)break;
        net.advance(now);
        for(const auto& frame:net.frames){p::require(frame.value==received+1,"network frame FIFO changed");policy.authorityReceived(++received,now);}net.frames.clear();
        for(const auto& ack:net.acks){
            p::require(pendingRefresh&&static_cast<uint32_t>(ack.value)==request&&ack.sent==pendingSent,"ACK identity changed");
            refresh.complete(1,request,now);pendingRefresh=false;rtts.observe(1,pendingSent,now);
            const auto estimate=rtts.estimate(now);out.ackRows.push_back({now,0,AckDelivery,static_cast<Frame>(estimate.value_or(0)),pendingSent});
            if(net.rise&&pendingSent>net.rise&&now-pendingSent>=430000){++highSamples;lastHighAck=now;}
            if(net.fall&&!out.lowEstimate&&pendingSent>net.fall&&now-pendingSent<=200000&&estimate&&*estimate<=200000)out.lowEstimate=now;
        }net.acks.clear();
        if(refresh.due(1,now,true,std::nullopt)){
            refresh.sent(1,++request,now);pendingRefresh=true;pendingSent=now;
            const Tick at=net.upstream(now,request)+control;net.add(at,AckRead,request,now);
        }
        const auto estimate=rtts.estimate(now);
        if(now>=controllerAt){
            controllerAt=now+150000;
            if(!net.rise&&presented>=450)net.rise=out.rise=now;
            else if(net.rise&&!net.fall&&now-net.rise>=4000000&&highSamples>=2&&lastHighAck&&estimate&&*estimate>=430000){
                net.fall=out.fall=now;out.highEstimate=lastHighAck;
            }
        }
        if(pending>=0&&now>=queued+2000)head=pending;
        auto score=[&](Tick at){
            if(at>=6000000&&at<10000000)probe(out.baseline,net,at,head,pending,queued);
            if(out.lowEstimate&&at>=out.lowEstimate+500000)probe(out.afterLow,net,at,head,pending,queued);
            if(net.fall&&at>=net.fall+8000000)probe(out.settled,net,at,head,pending,queued);
        };
        score(now); // Real originalInput drain precedes this callback's Push.
        if(gestureAt&&now>=gestureAt&&out.gateError==100){
            Frame h=head;const bool prep=pending>=0&&now>=queued+1000&&now<queued+2000;if(pending>=0&&now>=queued+2000)h=pending;
            out.gateError=static_cast<int>(h+1+static_cast<int>(prep)-canonicalAt(net.probeArrival(now)));
        }
        if(pending>=0&&now>=queued+2000&&policy.canPublish(pending,now)){
            policy.published(pending,now);presented=pending;pending=-1;
            if(net.rise&&out.lastPub)out.maxGap=(std::max)(out.maxGap,now-out.lastPub);out.lastPub=now;
        }
        auto d=policy.decide(next,static_cast<int>(presented),(std::min)(head,received),now,estimate);
        if(!estimate)++out.missingRtt;
        if(d.target.assigned>=1&&now>=lastDense+10000){
            lastDense=now;
            if(out.lowEstimate&&now>=out.lowEstimate&&d.frame>=400&&d.frame<650){
                const Frame error=d.target.assigned-next;
                if(error>=-1&&error<=1){
                    if(!firstEligible)firstEligible=now;
                    if(!out.gate&&now-firstEligible>=500000){out.gate=now;gestureAt=now+20000;}
                }
            }
        }
        if(d.allowed){
            p::require(pending<0&&next==head+1&&next-(std::min)(head,received)<=12,"native/budget changed");
            policy.queued(d);pending=next++;queued=now;out.lead=(std::max)(out.lead,next-1-(std::min)(head,received));
        }
        const Tick following=phase+(poll+1)*1000000/hz;
        random=random*1664525u+1013904223u;
        std::vector<Tick> probes={now+1,now+1000,now+2000};
        if(following>now+1)probes.push_back(now+1+random%(following-now-1));
        std::sort(probes.begin(),probes.end());
        for(Tick at:probes)if(at<following){net.advance(at);score(at);}
    }
    out.frozen=net.frozenChunks;return out;
}
static unsigned verify(){
    unsigned failures=0,totalCases=0;uint64_t totalBad=0,totalProbes=0;Tick maximumGap=0;
    for(unsigned hz:{32u,60u,144u,1000u})for(Tick phase:{0ull,17000ull,47000ull})
        for(Tick work:{0ull,6000ull})for(Tick control:{0ull,10000ull})for(Tick jitter:{0ull,8000ull}){
            const auto r=run(hz,phase,work,control,jitter);++totalCases;
            bool failed=!r.rise||!r.fall||!r.highEstimate||!r.lowEstimate||!r.gate||r.frozen<1||
                r.gateError<-1||r.gateError>1||r.maxGap>=100000||r.lead>p::maximumAhead;
            maximumGap=(std::max)(maximumGap,r.maxGap);
            for(const auto* s:{&r.baseline,&r.afterLow,&r.settled}){
                totalBad+=s->bad;totalProbes+=s->total;failed=failed||!s->total||s->bad||s->low<-1||s->high>1;
            }
            if(failed){++failures;std::cout<<"dynamic failure hz="<<hz<<" phase="<<phase<<" work="<<work
                <<" control="<<control<<" jitter="<<jitter<<" gate_error="<<r.gateError<<'\n';}
        }
    assert(totalCases==96);cases+=totalCases;
    std::cout<<"independent queued-chunk cases="<<totalCases<<" failed="<<failures<<" bad_probes="<<totalBad
        <<" probes="<<totalProbes<<" max_gap_us="<<maximumGap<<'\n';
    return failures;
}

}

int main() {
    targetExamples();roundTripsAndRealAck();realCommunityCorrelation();barrierAndOneOutput();receiptAtomicityAndReset();
    steadyCadenceGatesAndReset();
    phaseAcquisitionAndSteady();pauseAndLateBurst();changingPathContinuity();
    cursorPhaseRegression();fractionalBounds();
    const auto failures=fixed_seal_oracle::verify()+queued_chunk_oracle::verify();
    if(failures){std::cout<<"FAIL independent phase cases="<<failures<<std::endl;return 1;}
    std::cout<<"PASS "<<cases<<" authored pacing cases; no Simulation.dll/Unity/runtime executed\n";
}
