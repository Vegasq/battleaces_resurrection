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
// This is a rolling minimum of eight genuine local elapsed round trips. It
// resists positive UI/flush/load outliers, but cannot distinguish a consistently
// inflated path from genuine high RTT, or promptly discover a rising RTT when
// no new correlated request is sent. Those are explicit integration limits.
class RoundTrips {
    struct Sample {Tick duration=0,received=0;};
    std::array<Sample,8> samples_{};
    size_t count_=0,next_=0;
    uint64_t generation_=0;
public:
    static constexpr Tick maximumSampleUs=2000000;
    void reset(uint64_t generation) {
        require(generation!=0,"RTT connection generation must be nonzero");
        samples_={};count_=next_=0;generation_=generation;
    }
    bool observe(uint64_t generation,Tick sent,Tick received) {
        if(!generation_ || generation!=generation_ || received<sent ||
           received-sent>maximumSampleUs)return false;
        samples_[next_]=Sample{(std::max)(Tick(1),received-sent),received};
        next_=(next_+1)%samples_.size();count_=(std::min)(count_+1,samples_.size());return true;
    }
    size_t count() const{return count_;}
    std::optional<Tick> estimate() const {
        if(!count_)return std::nullopt;
        Tick best=(std::numeric_limits<Tick>::max)();
        for(size_t i=0;i<count_;++i)best=(std::min)(best,samples_[i].duration);
        return best;
    }
};

enum class Wait {None,NativeOutput,SteadyFrameOne,RoundTrip,TargetPhase,Budget,Spacing};
struct Decision {
    bool allowed=false,acquiring=false;
    Wait wait=Wait::None;
    Frame frame=-1;
    Tick now=0;
    Target target{};
};
class Policy {
    Frame received_=-1,lastQueued_=-1,lastPresented_=-1;
    Tick receivedAt_=0,lastQueueAt_=0,lastPublicationAt_=0;
    bool haveQueue_=false,havePublication_=false;
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
        d.acquiring=next<d.target.head;
        if(next>d.target.head){d.wait=Wait::TargetPhase;return d;}
        if(next-projected>maximumAhead){d.wait=Wait::Budget;return d;}
        if(haveQueue_ && now-lastQueueAt_<minimumSpacingUs){d.wait=Wait::Spacing;return d;}
        d.allowed=true;return d;
    }
    // Call only AFTER successful ORIGINAL PushSimMessage. These are audit
    // observations, never writes to native a8/ac or original server+198.
    void queued(const Decision& d) {
        require(d.allowed && d.wait==Wait::None && d.frame==lastQueued_+1 &&
                (!haveQueue_ || d.now>=lastQueueAt_),"invalid/stale pacing queue receipt");
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
