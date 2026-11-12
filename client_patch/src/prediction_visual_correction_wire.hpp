#pragma once
#include "../checkpoint/native_worker_wire.hpp"
#include <cmath>
#include <cstring>
#include <set>

// Separate presentation metadata. Never appended to the original MAKE/GET
// buffer, and never used as authoritative native state or an input action.
namespace ba_prediction_correction_wire {
struct Delta {
    uint32_t entity=0,type=0,army=0;
    uint64_t incarnation=0;
    float x=0,y=0,z=0;
};
struct Frame {
    uint64_t world=0,revision=0;
    int32_t frame=-1,head=-1;
    std::vector<Delta> deltas;
};
constexpr uint8_t Opcode=77;
constexpr uint32_t Version=1,MaximumEntities=65536;
inline float scalar(const ba_native_worker_wire::Bytes& bytes,size_t& at) {
    const auto bits=ba_native_worker_wire::read32(bytes,at);
    float result=0;static_assert(sizeof(result)==sizeof(bits),"correction Single ABI differs");
    std::memcpy(&result,&bits,sizeof(result));
    ba_native_worker_wire::require(std::isfinite(result),"nonfinite presentation correction");
    return result;
}
inline Frame decode(const ba_native_worker_wire::Bytes& bytes,uint64_t expectedWorld,int32_t expectedFrame) {
    namespace wire=ba_native_worker_wire;
    wire::require(expectedWorld && expectedFrame>=0 && bytes.size()>=32,
        "presentation correction request/header bounds differ");
    size_t at=0;Frame result;
    wire::require(wire::read32(bytes,at)==Version,"presentation correction version differs");
    result.world=wire::read64(bytes,at);
    result.frame=static_cast<int32_t>(wire::read32(bytes,at));
    result.head=static_cast<int32_t>(wire::read32(bytes,at));
    result.revision=wire::read64(bytes,at);
    const auto count=wire::read32(bytes,at);
    wire::require(result.world==expectedWorld && result.frame==expectedFrame && count<=MaximumEntities &&
        bytes.size()==32u+32u*static_cast<size_t>(count),"presentation correction frame/size differs");
    wire::require(count?(result.frame>0 && result.head==result.frame-1 && result.revision>0):result.head==-1,
        "presentation correction native-head binding differs");
    result.deltas.reserve(count);std::set<uint64_t> tokens;uint32_t previous=0;
    for(uint32_t index=0;index<count;++index) {
        Delta delta;
        delta.entity=wire::read32(bytes,at);delta.type=wire::read32(bytes,at);delta.army=wire::read32(bytes,at);
        delta.incarnation=wire::read64(bytes,at);
        delta.x=scalar(bytes,at);delta.y=scalar(bytes,at);delta.z=scalar(bytes,at);
        wire::require((!index || delta.entity>previous) && delta.incarnation && tokens.insert(delta.incarnation).second,
            "presentation correction identity order/token differs");
        result.deltas.push_back(delta);previous=delta.entity;
    }
    wire::require(at==bytes.size(),"presentation correction trailing bytes");return result;
}
}
