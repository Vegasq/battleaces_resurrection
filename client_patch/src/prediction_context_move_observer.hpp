#pragma once
#include <cstdint>

// Passive diagnostic on the one normal ToProto result, never extra serialization.
namespace ba_prediction_context_move {
void serialized(void* command,void* action,uint64_t sequence,int sourceNextFrame) noexcept;
}
