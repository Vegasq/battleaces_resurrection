#pragma once
// Included in the movement owner namespace. Keep the active ownership check
// strict; a flag or lingering worker key alone does not establish presentation.
bool ownsPresentation(void* simulation) {
    if(!worker::movementEnabled() || !state.prepared || !state.pacingStarted || state.drained || !state.world ||
       state.match.empty() || state.simulation!=simulation)return false;
    // Terminal drain ends prediction presentation before the worker world key
    // retires. Later original input/publication is no longer ours to observe.
    // Teardown/local-AI fallback may also have no worker movement key.
    if(!worker::movementWorldId() || worker::movementMatchId().empty())return false;
    bound(state.server);return true;
}
