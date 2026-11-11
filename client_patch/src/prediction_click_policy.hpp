#pragma once
#include <cmath>
#include <cstdint>

// Readonly classification of an affected first-click identity. These are the
// original System.Single clock values, not wall time or a replacement timer.
namespace ba_prediction_click_policy {
enum class Classification { Unmatched, Expired, LiveOrUnknown };
struct State {
    int32_t mode=0;
    uint8_t primaryDown=0,contextDown=0,dragging=0;
    float lastUp=0,window=0;
};

// The adapter validates the original closed field/method ABI. Unmatched IDs do
// not read any additional state, metadata or clock. Nothing resets click history.
template<class StateReader,class NowReader>
Classification classify(bool affected,StateReader readState,NowReader readNow) {
    if(!affected)return Classification::Unmatched;
    const State state=readState();
    if(state.mode!=0 || state.primaryDown!=0 || state.contextDown!=0 || state.dragging!=0 ||
       !std::isfinite(state.lastUp) || state.lastUp<0 ||
       !std::isfinite(state.window) || state.window<0)return Classification::LiveOrUnknown;
    const float now=readNow();
    if(!std::isfinite(now) || now<0 || now<state.lastUp)return Classification::LiveOrUnknown;
    const float elapsed=now-state.lastUp;
    return std::isfinite(elapsed) && elapsed>state.window?
        Classification::Expired:Classification::LiveOrUnknown;
}
}
