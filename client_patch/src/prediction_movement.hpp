#pragma once
#include <cstdint>
#include <string>
#include <vector>
#include <map>
#include "prediction_visual_correction_wire.hpp"
#include "prediction_visual_lifetime.hpp"

// Shared declarations only. The worker bridge serializes these controls with
// its original native API gate; the Unity-side pipeline never calls a raw DLL.
namespace ba_prediction_worker {
using MovementBytes=std::vector<uint8_t>;
struct MovementMetrics {int confirmed=-1,predicted=-1,received=-1;uint32_t flags=0;};
struct MovementIdentity {uint32_t army=0,type=0;uint64_t incarnation=0;};
struct MovementAdmission {int frame=-1;std::map<uint32_t,MovementIdentity> entities;};
bool movementEnabled();
void movementBegin(const std::string& match,unsigned slot,bool serverAi=false);
void movementAuthority(const MovementBytes& canonical,const std::string& wireSha);
MovementMetrics movementMetrics();
MovementAdmission movementAdmission();
ba_prediction_correction_wire::Frame movementCorrections(int publishedFrame);
bool visualCorrectionsEnabled();
void movementBatch(uint64_t sequence,const MovementBytes& originalPlayerBody);
void movementEnd(int finalInputFrame);
uint64_t movementWorldId();
const std::string& movementMatchId();
void movementFail(const char* reason) noexcept;
}
namespace ba_prediction_movement {
void beforeReady();
void started();
void authorityReceived(int frame,uint64_t receivedUs);
bool ownsPresentation(void* simulation);
bool activeForRefresh();
bool canPublish(void* simulation,uint64_t nowUs);
void published(void* simulation,uint64_t nowUs);
void tick(void* server);
void flushEarlyPhaseDiagnostics() noexcept;
void reset() noexcept;
ba_prediction_visual_lifetime::Snapshot presentationLifetime();
}
namespace ba_prediction_visual {
void published(void* simulation);
void clearInactive(const char* trigger="frontend");
}
