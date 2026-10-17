#pragma once
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace ba_wire {
constexpr unsigned protocol=3,minimumInputWindow=2,maximumInputWindow=12;
struct Welcome { unsigned slot,inputWindow; };
inline Welcome parseWelcome(const std::vector<unsigned char>& payload,int requestedSlot) {
    if(payload.size()!=34 || payload[0]>1 ||
       (requestedSlot!=255 && payload[0]!=requestedSlot) ||
       payload[1]<minimumInputWindow || payload[1]>maximumInputWindow)
        throw std::runtime_error("Invalid protocol3 welcome; update client and server together");
    return {payload[0],payload[1]};
}
}
