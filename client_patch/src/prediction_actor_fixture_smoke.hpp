#pragma once
// Explicit owned diagnostic roles. Ordinary clients never enable this fixture.
// Legacy Core5 timings/schema remain unchanged without the mirror flag.
namespace ba_prediction_actor_fixture_smoke {
static bool mirrored(){return ba::flag(L"-prediction-actor-mirror-smoke");}
static bool validScope(){return !mirrored()||(
    ba::flag(L"-prediction-actor-correction-smoke")&&ba::flag(L"-prediction-held-click-smoke")&&
    !ba::flag(L"-prediction-expired-click-smoke")&&!ba::flag(L"-prediction-mobile-correction-smoke"));}
static int victimSlot(){return mirrored()?0:1;}
static int attackerSlot(){return mirrored()?1:0;}
static uint32_t coreId(){return mirrored()?0u:5u;}
static int escapeFrame(){return mirrored()?150:152;}
static int consumedBy(){return mirrored()?152:154;}
static int heldCheckpoint(){return mirrored()?152:154;}
static int deathFrame(){return mirrored()?153:155;}
}
