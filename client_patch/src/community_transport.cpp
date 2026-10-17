#pragma once
#include "community_wire.hpp"
#include <map>
// Session control is separate from a match seat. No managed objects are created
// in the decoder; the native adapter consumes events after poll() returns.
namespace ba_lan { static void send(unsigned char,const std::vector<unsigned char>&); }
namespace ba_community {
namespace wire=ba_community_wire;
static bool online=false;
// Pause only match traffic as soon as ABORTED is decoded, even when its ordered
// RESULTS snapshot arrives in a later socket read. Native ownership is checked
// by the Unity-thread adapter before any world cleanup or RETURN.
static bool abortPending=false;
static wire::Welcome welcome;
static wire::Directory directory{};
static wire::Lobby lobby;
static std::deque<wire::Event> events;
struct Pending {unsigned char kind;ULONGLONG deadline;};
static std::map<uint32_t,Pending> pending;
static uint32_t requestId=0;
static uint64_t alias(const std::string& profile) {
    // A stable lobby-only identifier. Simulation seat handles1/2 stay separate.
    uint64_t value=14695981039346656037ull;
    for(unsigned char byte:profile){value^=byte;value*=1099511628211ull;}
    return value|0x8000000000000000ull;
}
static const wire::Player* player(const std::string& profile) {
    for(const auto& row:directory.players)if(row.profile==profile)return &row;
    return nullptr;
}
static void reset() {
    online=false;abortPending=false;welcome={};directory={};lobby={};events.clear();pending.clear();requestId=0;
}
static uint32_t nextRequest() {
    wire::require(online && pending.size()<32 && requestId<UINT32_MAX,"community request capacity/state");
    return ++requestId;
}
static uint32_t send(wire::Packet packet) {
    wire::Reader r(packet.payload);const auto id=r.u32();
    wire::require(online && id==requestId && !pending.count(id) && packet.payload.size()<=256,
        "invalid outgoing community request");
    pending.emplace(id,Pending{packet.kind,GetTickCount64()+15000});
    ba_lan::send(packet.kind,packet.payload);return id;
}
static void receive(unsigned char kind,const wire::Bytes& payload) {
    wire::require(events.size()<256,"community event queue capacity");
    auto event=wire::decode(kind,payload);
    if(const auto* greeting=std::get_if<wire::Welcome>(&event)) {
        wire::require(!online && greeting->profile==ba::argument(L"-player-id="),"unexpected community identity/welcome");
        welcome=*greeting;online=true;
    } else {
        wire::require(online,"community event before welcome");
        if(const auto* listing=std::get_if<wire::Directory>(&event)) {
            wire::require(listing->revision>=directory.revision,"community directory revision regressed");
            bool self=false;std::map<uint64_t,std::string> aliases;
            for(const auto& row:listing->players) {
                self|=row.profile==welcome.profile;
                wire::require(aliases.emplace(alias(row.profile),row.profile).second,"community identity alias collision");
            }
            wire::require(self,"community directory omits local identity");directory=*listing;
        } else if(const auto* snapshot=std::get_if<wire::Lobby>(&event)) {
            if(snapshot->phase!=wire::None) {
                bool self=false;for(const auto& row:snapshot->members)self|=row.profile==welcome.profile;
                wire::require(self,"community lobby does not belong to local player");
                if(snapshot->id==lobby.id)wire::require(snapshot->revision>=lobby.revision,"community lobby revision regressed");
            }
            lobby=*snapshot;
        } else if(const auto* reply=std::get_if<wire::Ack>(&event)) {
            const auto found=pending.find(reply->request);
            wire::require(found!=pending.end() && found->second.kind==reply->kind,"uncorrelated community acknowledgement");
            pending.erase(found);
        } else if(const auto* invitation=std::get_if<wire::Invitation>(&event)) {
            wire::require(invitation->sender==welcome.profile || invitation->target==welcome.profile,"foreign community invitation");
        } else if(std::holds_alternative<wire::Aborted>(event)) {
            abortPending=true;
        }
    }
    events.push_back(std::move(event));
}
static void checkTimeouts() {
    for(const auto& item:pending)wire::require(GetTickCount64()<item.second.deadline,"community acknowledgement timed out");
}
}
