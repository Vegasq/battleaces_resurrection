#pragma once
#include "online_frame_clock.hpp"
#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <optional>
#include <stdexcept>

// Opt-in owned movement pacing. Times are one process's
// monotonic MICROSECONDS, never Unix time or a mix of QPC/GetTickCount epochs.
namespace ba_prediction_pacing {
using Tick=uint64_t;
using Frame=int64_t;
constexpr Tick stepUs=50000,minimumSpacingUs=25000;
constexpr Tick shortestPeriodUs=45000,longestPeriodUs=55000;
constexpr Frame maximumAhead=12,maximumFrame=0x7fffffff;
inline void require(bool value,const char* reason) {
    if(!value)throw std::invalid_argument(reason);
}
struct Target {
    Frame assigned=-1,head=-1;
    uint64_t rawLead=0;
    bool capped=false;
};
inline Target assignmentTarget(Frame received,Tick receivedAt,Tick now,Tick rtt) {
    require(received>=1 && received<=maximumFrame,"target needs a real steady authority frame");
    require(now>=receivedAt,"authority receipt timestamp is in the future");
    const Tick age=now-receivedAt;
    require(rtt<=(std::numeric_limits<Tick>::max)()-age,"target time overflow");
    const Tick total=age+rtt;
    // Exact requested ceil convention. At an exact server seal boundary a
    // packet may instead enter the following frame: that uncertainty is NOT
    // removed by this arithmetic, and must be measured against real commits.
    const uint64_t raw=(std::max)(uint64_t(1),total/stepUs+(total%stepUs?1u:0u));
    const Frame lead=static_cast<Frame>((std::min)(raw,static_cast<uint64_t>(maximumAhead)));
    require(received<=maximumFrame-lead,"prediction target frame exhausted");
    return Target{received+lead,received+lead-1,raw,raw>static_cast<uint64_t>(maximumAhead)};
}

// Only call observe AFTER the EXISTING own request/ACK validator accepts the
// current connection generation, request ID, kind, and payload. No heartbeat,
// remote player's request, server timestamp, or fabricated RTT is admissible.
// Keep at most eight samples from four seconds of genuine own elapsed round
// trips. Two independently timed fresh replies support an increase; one larger
// UI/flush outlier cannot replace a still-qualified lower estimate. A first
// sample after complete expiry starts acquisition again. These are apparent
// application RTTs, not pure transport latency or a proof of future path delay.
class RoundTrips {
    struct Sample {Tick duration=0,received=0;};
    std::array<Sample,8> samples_{};
    size_t count_=0,next_=0;
    uint64_t generation_=0;
    std::optional<Tick> estimate_;
    Tick lastClock_=0;
    bool haveClock_=false;
    void expire(Tick now) {
        require(!haveClock_ || now>=lastClock_,"RTT measurement clock regressed");
        lastClock_=now;haveClock_=true;
        for(auto& sample:samples_)if(sample.duration && now-sample.received>sampleLifetimeUs) {
            sample={};--count_;
        }
        if(!count_)estimate_.reset();
    }
    void update() {
        Tick best=(std::numeric_limits<Tick>::max)(),first=best,last=0;
        for(const auto& sample:samples_)if(sample.duration) {
            best=(std::min)(best,sample.duration);first=(std::min)(first,sample.received);
            last=(std::max)(last,sample.received);
        }
        if(count_ && (!estimate_ || best<=*estimate_ ||
                     (count_>=2 && last-first>=riseSupportUs)))estimate_=best;
    }
public:
    static constexpr Tick maximumSampleUs=2000000;
    static constexpr Tick sampleLifetimeUs=4000000,riseSupportUs=500000;
    void reset(uint64_t generation) {
        require(generation!=0,"RTT connection generation must be nonzero");
        *this=RoundTrips{};generation_=generation;
    }
    bool observe(uint64_t generation,Tick sent,Tick received) {
        if(!generation_ || generation!=generation_ || received<sent ||
           received-sent>maximumSampleUs || (haveClock_ && received<lastClock_))return false;
        expire(received);
        if(samples_[next_].duration)--count_;
        samples_[next_]=Sample{(std::max)(Tick(1),received-sent),received};
        next_=(next_+1)%samples_.size();++count_;update();return true;
    }
    size_t count() const{return count_;}
    std::optional<Tick> estimate() const {return estimate_;}
    std::optional<Tick> estimate(Tick now) {expire(now);update();return estimate_;}
};

// A sparse use of existing REFRESH55, never a new heartbeat/wire protocol.
// Exact pending request/kind/generation checks remain in the community decoder.
// Ordinary or inactive/public paths never call sent(). No retries are created
// while one request is outstanding; the normal15s control timeout still owns it.
class RefreshRequests {
    uint64_t generation_=0;
    uint32_t pending_=0;
    Tick lastSend_=0,lastClock_=0,directoryBytes_=0;
    bool haveSend_=false,haveClock_=false;
    void clock(Tick now) {
        require(!haveClock_ || now>=lastClock_,"RTT refresh clock regressed");
        lastClock_=now;haveClock_=true;
    }
public:
    static constexpr Tick intervalUs=2000000;
    void reset(uint64_t generation) {
        require(generation!=0,"RTT refresh generation must be nonzero");
        *this=RefreshRequests{};generation_=generation;
    }
    bool due(uint64_t generation,Tick now,bool capacity,std::optional<Tick> lastOtherReply) {
        require(generation_ && generation==generation_,"RTT refresh generation differs");clock(now);
        if(pending_ || !capacity || (haveSend_ && now-lastSend_<intervalUs))return false;
        if(lastOtherReply) {
            require(now>=*lastOtherReply,"RTT control reply timestamp is in the future");
            if(now-*lastOtherReply<intervalUs)return false;
        }
        return true;
    }
    void sent(uint64_t generation,uint32_t request,Tick now) {
        require(generation_ && generation==generation_ && request && !pending_ &&
                (!haveSend_ || (now>=lastSend_ && now-lastSend_>=intervalUs)),"RTT refresh send scope/cadence");
        clock(now);pending_=request;lastSend_=now;haveSend_=true;directoryBytes_=0;
    }
    bool tracks(uint64_t generation,uint32_t request) const {
        return generation_ && generation==generation_ && request && pending_==request;
    }
    bool complete(uint64_t generation,uint32_t request,Tick now) {
        if(!tracks(generation,request))return false;
        clock(now);pending_=0;return true;
    }
    void directoryBytes(uint64_t bytes) {
        if(!pending_)return;
        const auto maximum=(std::numeric_limits<Tick>::max)();
        directoryBytes_=bytes>maximum-directoryBytes_?maximum:directoryBytes_+bytes;
    }
    uint32_t pending() const{return pending_;}
    Tick directoryBytes() const{return directoryBytes_;}
};

enum class Wait {None,NativeOutput,SteadyFrameOne,RoundTrip,TargetPhase,Budget,Spacing};
struct Decision {
    bool allowed=false,acquiring=false;
    Wait wait=Wait::None;
    Frame frame=-1;
    Tick now=0,nextDeadline=0;
    Target target{};
};
class Policy {
    Frame received_=-1,lastQueued_=-1,lastPresented_=-1;
    Tick receivedAt_=0,lastQueueAt_=0,lastPublicationAt_=0,nextDeadline_=0;
    bool haveQueue_=false,havePublication_=false,acquired_=false;
public:
    void reset(){*this=Policy{};}
    Frame received() const{return received_;}
    Frame observedQueued() const{return lastQueued_;}
    Frame observedPresented() const{return lastPresented_;}
    void authorityReceived(Frame frame,Tick now) {
        require(frame>=0 && frame<=maximumFrame && frame==received_+1,
                "pacing authority receipts must be contiguous");
        require(received_<0 || now>=receivedAt_,"pacing receipt clock regressed");
        received_=frame;receivedAt_=now;
    }
    Decision decide(Frame next,int presented,Frame projected,Tick now,std::optional<Tick> rtt) const {
        require(next>=0 && next<=maximumFrame && next==lastQueued_+1,
                "pacing requires the real next physical frame");
        require(projected>=-1 && projected<=lastQueued_,"projected confirmation escaped physical head");
        require(!haveQueue_ || now>=lastQueueAt_,"pacing clock regressed");
        Decision d{};d.frame=next;d.now=now;
        if(!ba_online_frame_clock::canFeed(static_cast<int>(next),presented)) {
            d.wait=Wait::NativeOutput;return d;
        }
        require(presented==lastPresented_,"pacing publication observation differs from original counter");
        if(next==0) {
            d.allowed=received_>=0;d.wait=d.allowed?Wait::None:Wait::SteadyFrameOne;return d;
        }
        // Canonical0/bootstrap is NOT the server's steady epoch. The server
        // can still be waiting for the other peer's actual publication READY.
        if(received_<1){d.wait=Wait::SteadyFrameOne;return d;}
        if(!rtt){d.wait=Wait::RoundTrip;return d;}
        d.target=assignmentTarget(received_,receivedAt_,now,*rtt);
        d.acquiring=!acquired_ && next<d.target.head;
        if(!acquired_ && next>d.target.head){d.wait=Wait::TargetPhase;return d;}
        if(next-projected>maximumAhead){d.wait=Wait::Budget;return d;}
        if(haveQueue_ && now-lastQueueAt_<minimumSpacingUs){d.wait=Wait::Spacing;return d;}
        if(acquired_ && now<nextDeadline_){d.wait=Wait::Spacing;return d;}
        if(acquired_ || !d.acquiring) {
            // Only initial acquisition follows the raw target at25ms. Once
            // acquired, changing RTT must not hard-hold a monotonically growing
            // physical head or switch back to initial acquisition. Slew its absolute deadline,
            // with a one-frame deadband for receipt/ceil quantization. This
            // trades temporary phase error for continuity, not input-phase or
            // visual-interpolation acceptance. Native dt stays exactly50ms.
            const Frame error=d.target.head-next;
            const Tick period=error>1?shortestPeriodUs:error<-1?longestPeriodUs:stepUs;
            const Tick base=acquired_?nextDeadline_:now;
            const Tick maximum=(std::numeric_limits<Tick>::max)();
            require(base<=maximum-period,"pacing deadline exhausted");
            d.nextDeadline=base+period;
            // Preserve phase through coarse polls. After a genuine long
            // native/budget stall, discard obsolete catch-up deadlines rather
            // than retaining a long burst. Up to one nominal interval of
            // overdue debt remains, still bounded by minimumSpacingUs.
            // No clock/native-counter/command writes occur.
            if(now>d.nextDeadline && now-d.nextDeadline>stepUs) {
                require(now<=maximum-period,"pacing deadline exhausted");
                d.nextDeadline=now+period;
            }
        }
        d.allowed=true;return d;
    }
    // Call only AFTER successful ORIGINAL PushSimMessage. These are audit
    // observations, never writes to native a8/ac or original server+198.
    void queued(const Decision& d) {
        require(d.allowed && d.wait==Wait::None && d.frame==lastQueued_+1 &&
                (!haveQueue_ || d.now>=lastQueueAt_),"invalid/stale pacing queue receipt");
        if(d.nextDeadline){nextDeadline_=d.nextDeadline;acquired_=true;}
        lastQueued_=d.frame;lastQueueAt_=d.now;haveQueue_=true;
    }
    bool canPublish(Frame frame,Tick now) const {
        require(frame==lastQueued_ && frame==lastPresented_+1,"publication is not the sole queued output");
        require(now>=lastQueueAt_,"publication precedes native enqueue");
        return !havePublication_ || (now>=lastPublicationAt_ && now-lastPublicationAt_>=minimumSpacingUs);
    }
    // Call only AFTER the ORIGINAL PresentAvailableSimFrame actually advances
    // its presented counter. The original still owns buffers, locking/jobs.
    void published(Frame frame,Tick now) {
        require(canPublish(frame,now),"publication spacing/ownership failed");
        lastPresented_=frame;lastPublicationAt_=now;havePublication_=true;
    }
};
}
