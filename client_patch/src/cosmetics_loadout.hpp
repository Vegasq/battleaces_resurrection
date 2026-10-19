#pragma once
#include "cosmetics_state.hpp"
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
static void validateHumanDeck(void* deck,const FrozenLoadout& frozen);
static void applyHumanRoles(void* message,const FrozenLoadout& frozen);
static void practiceHumanProof(void* server,const FrozenLoadout& frozen);
static void practiceRematchSmoke(void* front);
static void captureHumanProfile(const std::string& match,bool result);
}
