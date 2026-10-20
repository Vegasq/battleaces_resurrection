#pragma once
#include <cstdint>

// Explicit diagnostic only. Closed-file rename can still briefly conflict with
// a strict FILE_SHARE_READ consumer while Windows finishes the rename handle.
namespace ba_native_quit_gate {
enum class Result { Missing,Sharing,Expired,Unexpected };
struct Wait {
    static constexpr uint32_t MaxWaitMs=1000;
    bool active=false;
    uint64_t began=0;
    uint32_t attempts=0;
    uint64_t elapsed(uint64_t now) const {return active?now-began:0;}
    bool ready(uint64_t now) const {return !active || elapsed(now)<MaxWaitMs;}
    Result failed(uint32_t error,uint64_t now) {
        if(error!=2 && error!=32)return Result::Unexpected;
        if(!ready(now))return Result::Expired;
        if(error==2)return Result::Missing; // Parent has not published the gate.
        if(!active){active=true;began=now;}
        ++attempts;return Result::Sharing;
    }
    void clear(){active=false;began=0;attempts=0;}
};
}
