#pragma once
namespace ba_replay_update {
struct Context {
    bool primary=false, sameReplay=false, sameSimulation=false, loaded=false;
    bool localMatch=false, remoteMatch=false, bootstrap=false, batchDiagnostic=false;
};
inline bool ownsReplay(const Context& value) {
    return value.primary && value.sameReplay && value.sameSimulation && value.loaded &&
        !value.localMatch && !value.remoteMatch && !value.bootstrap && !value.batchDiagnostic;
}
// Original GameServerIntegration.ProcessUpdate eligibility, build37822.
inline bool originalEligibility(bool spectator,bool connected,int gameState) {
    return spectator || !connected || gameState==3;
}
}
