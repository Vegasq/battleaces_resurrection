#include "prediction_movement_readiness.hpp"
#include <cassert>
#include <cmath>
#include <iostream>
#include <limits>

namespace readiness=ba_prediction_movement_readiness;
template<class F> static bool refused(F action) {
    try {action();return false;}catch(const std::invalid_argument&){return true;}
}
int main() {
    // Retained Actual83 RED: actor still19.21units from its original target,
    // but its nearest >=100ms sample spans a337.566ms frontend pause and only
    // .0157units of travel. This must wait without manufacturing a direction.
    const float dx=76.2035599f-76.2159805f,dz=59.1412849f-59.1509209f;
    const float displacement=std::sqrt(dx*dx+dz*dz);
    assert(displacement>.015f && displacement<.016f);
    const float remainingX=61.0256119f-76.2035599f,remainingZ=47.3617401f-59.1412849f;
    const float remaining=remainingX*remainingX+remainingZ*remainingZ;
    assert(readiness::evaluate(935318447402ULL-935318109836ULL,displacement,remaining)==readiness::Result::Pending);

    // A genuinely new moving sample may later supply the direction. Merely
    // waiting longer or reaching the target must never grant readiness.
    assert(readiness::evaluate(110000,.2f,remaining)==readiness::Result::Ready);
    assert(readiness::evaluate(500000,0,remaining)==readiness::Result::Pending);
    assert(refused([&]{readiness::evaluate(500001,displacement,remaining);}));
    assert(refused([&]{readiness::evaluate(99999,.2f,remaining);}));
    assert(readiness::evaluate(100000,.2f,remaining)==readiness::Result::Ready);
    assert(readiness::evaluate(500000,.2f,remaining)==readiness::Result::Ready);
    assert(readiness::evaluate(100000,.05f,remaining)==readiness::Result::Pending);
    assert(readiness::evaluate(100000,std::nextafter(.05f,1.0f),remaining)==readiness::Result::Ready);
    assert(refused([]{readiness::evaluate(100000,.2f,.0625f);}));
    assert(refused([]{readiness::evaluate(100000,0,.0625f);}));
    assert(refused([]{readiness::evaluate(100000,.2f,0);}));
    assert(refused([&]{readiness::evaluate(100000,-1,remaining);}));
    assert(refused([&]{readiness::evaluate(100000,std::numeric_limits<float>::quiet_NaN(),remaining);}));
    assert(refused([&]{readiness::evaluate(100000,std::numeric_limits<float>::infinity(),remaining);}));
    assert(refused([]{readiness::evaluate(100000,.2f,std::numeric_limits<float>::quiet_NaN());}));
    std::cout<<"movement turn readiness: captured83 pending and strict bounds PASS (17 checks)\n";
}
