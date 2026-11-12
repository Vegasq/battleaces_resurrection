#pragma once
#include <cmath>
#include <cstdint>
#include <stdexcept>

// Explicit movement-smoke readiness only. The caller supplies the SAME nearest
// sample at least100ms old; this policy never searches for an older direction.
namespace ba_prediction_movement_readiness {
enum class Result {Pending,Ready};
inline Result evaluate(uint64_t ageUs,float displacement,float remainingSquared) {
    if(ageUs<100000 || ageUs>500000)
        throw std::invalid_argument("movement turn lacks recent100ms actual motion");
    if(!std::isfinite(displacement) || displacement<0 ||
       !std::isfinite(remainingSquared) || remainingSquared<=.0625f)
        throw std::invalid_argument("movement turn requires actual ongoing unfinished travel");
    // A stalled latest pose does not supply a usable direction yet. Retain
    // the gate until real movement resumes; the unchanged650 cutoff and full
    // captured hold/position tests still reject an unfinished or laggy run.
    return displacement>.05f?Result::Ready:Result::Pending;
}
}
