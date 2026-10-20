#include "native_quit_gate.hpp"
#include <cassert>
#include <iostream>
using namespace ba_native_quit_gate;
int main() {
    Wait absent;
    assert(absent.failed(2,0)==Result::Missing);
    assert(absent.failed(2,1000000)==Result::Missing && !absent.active);
    assert(absent.ready(1000000));
    Wait transient;
    assert(transient.failed(32,10)==Result::Sharing && transient.active && transient.attempts==1);
    assert(transient.failed(32,1009)==Result::Sharing && transient.attempts==2);
    assert(transient.ready(1009) && transient.elapsed(1009)==999);
    assert(!transient.ready(1010) && transient.failed(32,1010)==Result::Expired);
    transient.clear();assert(!transient.active && transient.attempts==0 && transient.ready(1010));
    Wait disappeared;
    assert(disappeared.failed(32,20)==Result::Sharing);
    assert(disappeared.failed(2,1019)==Result::Missing);
    assert(disappeared.failed(2,1020)==Result::Expired); // Missing cannot reset the busy budget.
    Wait regressed;
    assert(regressed.failed(32,100)==Result::Sharing);
    assert(regressed.failed(32,99)==Result::Expired);
    for(const uint32_t code:{0u,3u,5u,87u,123u}) {
        Wait rejected;
        assert(rejected.failed(code,10)==Result::Unexpected && !rejected.active);
    }
    std::cout<<"Native diagnostic gate wait tests passed\n";
}
