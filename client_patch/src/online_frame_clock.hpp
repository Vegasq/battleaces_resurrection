#pragma once
#include <cstdint>
#include <limits>

// Main-thread admission clock; receiving authoritative frames remains separate.
namespace ba_online_frame_clock {
template<uint64_t UnitsPerMs=1> struct BasicClock {
    static constexpr uint64_t stepMs=50;
    static constexpr uint64_t minimumSpacingMs=25;
    static_assert(UnitsPerMs>0 && UnitsPerMs<=(std::numeric_limits<uint64_t>::max)()/stepMs,
                  "clock units must fit the simulation step");
    static constexpr uint64_t step=stepMs*UnitsPerMs;
    static constexpr uint64_t minimumSpacing=minimumSpacingMs*UnitsPerMs;

    void reset() {started_=false;hasPush_=false;deadline_=lastPush_=0;}
    bool started() const {return started_;}
    void start(uint64_t now) {
        if(started_)return;
        started_=true;deadline_=now;
    }
    bool ready(uint64_t now) const {
        if(!started_ || now<deadline_)return false;
        return !hasPush_ || (now>=lastPush_ && now-lastPush_>=minimumSpacing);
    }
    // Call only after ready(now) and a successful native push. Preserve the
    // absolute phase during ordinary coarse polls; now+50 on every push would
    // reduce a31.25ms update cadence to16Hz. The independent spacing floor
    // prevents overdue frames from bursting across adjacent front updates.
    void pushed(uint64_t now) {
        const auto maximum=(std::numeric_limits<uint64_t>::max)();
        deadline_=deadline_>maximum-step?maximum:deadline_+step;
        // A long suspension must not accumulate unbounded fast-forward debt.
        // Rebase to now with at most one tick left to recover, always subject
        // to minimumSpacingMs. Frame numbers and simulation steps stay external.
        if(now>deadline_ && now-deadline_>step)deadline_=now;
        lastPush_=now;hasPush_=true;
    }
private:
    bool started_=false,hasPush_=false;
    uint64_t deadline_=0,lastPush_=0;
};
using Clock=BasicClock<1>;
using MicrosecondClock=BasicClock<1000>;
// The native worker replaces its sole output slot. A second input is safe
// only after the previous input's output has been consumed by presentation.
inline bool canFeed(int nextFrame,int presentedFrame) {
    return nextFrame>=0 && static_cast<int64_t>(nextFrame)==static_cast<int64_t>(presentedFrame)+1;
}
}
