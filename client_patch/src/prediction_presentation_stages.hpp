#pragma once
#include <cstdint>
#include <limits>
// Opt-in attribution of work between native availability and presentation.
// These rows use the existing buffered QPC trace; no file writes occur here.
// For stage.* events ONLY, queued contains this thread's cumulative kernel+
// user CPU microseconds (SIZE_MAX means GetThreadTimes failed). CPU accounting
// can be coarse; it cannot resolve small intervals or identify an OS scheduler.
namespace ba_prediction_stages {
static void mark(const char* event,void* simulation) {
    static const bool requested=ba::flag(L"-prediction-presentation-stages");
    if(!requested || !ba_frame_timing::captureTarget() || !ba_frame_timing::enabled())return;
    FILETIME created{},exited{},kernel{},user{};
    size_t cpu=(std::numeric_limits<size_t>::max)();
    if(GetThreadTimes(GetCurrentThread(),&created,&exited,&kernel,&user)) {
        const uint64_t kernel100=(static_cast<uint64_t>(kernel.dwHighDateTime)<<32)|kernel.dwLowDateTime;
        const uint64_t user100=(static_cast<uint64_t>(user.dwHighDateTime)<<32)|user.dwLowDateTime;
        cpu=static_cast<size_t>((kernel100+user100)/10);
    }
    const int sim=simulation?ba::read<int>(simulation,0xa8):-1;
    const int presented=simulation?ba::read<int>(simulation,0xac):-1;
    ba_frame_timing::write(event,presented,sim,presented,cpu);
}
}
