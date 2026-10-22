#pragma once
#include "cosmetics_state.hpp"
#include "community_wire.hpp"
namespace ba_cosmetics {
// Immutable by convention once a match owns it. Never use the observer cache
// as the source: a Play callback may follow an equip in the same frame.
struct FrozenLoadout {
    bool active=false;
    std::string catalog;
    ba_cosmetics_state::Pairs slots;
    uint32_t portrait=0,banner=0;
};
static FrozenLoadout freezeHuman(void* front,void* freshDeck);
static FrozenLoadout currentSelection(void* front=nullptr);
static bool readyForLoadout(void* front);
static ba_community_wire::Loadout wireLoadout(void* deck,const FrozenLoadout& frozen);
static void applyFrozenJoin(void* action,void* deck,const FrozenLoadout& frozen);
static void validateHumanDeck(void* deck,const FrozenLoadout& frozen);
static void applyHumanRoles(void* message,const FrozenLoadout& frozen);
static void practiceHumanProof(void* server,const FrozenLoadout& frozen,void* deck);
static void remoteProof(void* front);
static void practiceRematchSmoke(void* front);
static void captureHumanProfile(const std::string& match,bool result);
static uint32_t communityPortrait(uint32_t requested,const std::array<unsigned char,32>& catalog);
}
