#pragma once
// Correlated publication ownership shared by background updates and Custom start.
#include <cstdint>
#include <map>
#include <stdexcept>
#include "community_wire.hpp"
namespace ba_loadout_publication {
struct State {
    bool accepted=false,pending=false;
    uint32_t latest=0;
    std::map<uint32_t,unsigned char> requests;
    void submit(uint32_t id,unsigned char kind) {
        if(!id || id<=latest || requests.size()>=32 || (kind!=ba_community_wire::SetDeck && kind!=ba_community_wire::SetLoadout))throw std::runtime_error("invalid loadout publication ownership");
        requests.emplace(id,kind);latest=id;accepted=false;pending=true;
    }
    bool acknowledge(uint32_t id,unsigned char kind,bool success) {
        const auto found=requests.find(id);if(found==requests.end())return false;
        if(found->second!=kind)throw std::runtime_error("loadout acknowledgement kind mismatch");
        requests.erase(found);if(id==latest){accepted=success;pending=false;}return true;
    }
    void reset(){accepted=false;pending=false;latest=0;requests.clear();}
};
}
