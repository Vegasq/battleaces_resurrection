#pragma once
#include <cstdint>
#include <string>

// Scalar owner-lifetime decision only. No Unity pointers, GC handles, worker
// calls or engine ownership checks. END/matchEnded alone preserve drain.
namespace ba_prediction_visual_lifetime {
struct Snapshot {
    uint64_t movementWorld=0,workerWorld=0;
    std::string movementMatch,workerMatch;
    uint32_t ownerThread=0;
    bool prepared=false,pacingStarted=false,failed=false,endSent=false,drained=false;
    bool matchEnded=false,abortPending=false,connected=false;
};
enum class Reason {Keep,Drained,Failed,Aborted,Disconnected,MovementInactive,MovementChanged,WorkerRetired,WorkerChanged};
inline Reason retirement(uint64_t world,const std::string& match,bool visualFailed,const Snapshot& state) {
    if(visualFailed || state.failed)return Reason::Failed;
    if(state.drained)return Reason::Drained;
    if(state.abortPending)return Reason::Aborted;
    if(!state.connected)return Reason::Disconnected;
    if(!state.prepared || !state.pacingStarted)return Reason::MovementInactive;
    if(!world || match.empty() || state.movementWorld!=world || state.movementMatch!=match)return Reason::MovementChanged;
    if(!state.workerWorld || state.workerMatch.empty())return Reason::WorkerRetired;
    if(state.workerWorld!=world || state.workerMatch!=match)return Reason::WorkerChanged;
    return Reason::Keep;
}
inline const char* name(Reason value) {
    switch(value) {
    case Reason::Keep:return "keep";
    case Reason::Drained:return "drained";
    case Reason::Failed:return "failed";
    case Reason::Aborted:return "aborted";
    case Reason::Disconnected:return "disconnected";
    case Reason::MovementInactive:return "movement_inactive";
    case Reason::MovementChanged:return "movement_changed";
    case Reason::WorkerRetired:return "worker_retired";
    case Reason::WorkerChanged:return "worker_changed";
    }
    return "invalid";
}
}
