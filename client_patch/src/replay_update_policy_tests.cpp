#include "replay_update_policy.hpp"
#include <cassert>
#include <iostream>
using namespace ba_replay_update;
int main() {
    Context replay{true,true,true,true,false,false,false,false};
    assert(ownsReplay(replay));
    assert(replacementEligible(replay,0x100,0x200));
    assert(!replacementEligible(replay,0x100,0x100));
    assert(!replacementEligible(replay,0,0x200));
    assert(!replacementEligible(replay,0x100,0));
    // A valid loaded recording must not let an AI integration or a match owner
    // advance the shared replay runner. Each independent conflict rejects it.
    for(auto member:{&Context::primary,&Context::sameReplay,&Context::sameSimulation,&Context::loaded}) {
        auto conflict=replay;conflict.*member=false;assert(!ownsReplay(conflict));
        assert(!replacementEligible(conflict,0x100,0x200));
    }
    for(auto member:{&Context::localMatch,&Context::remoteMatch,&Context::bootstrap,&Context::batchDiagnostic}) {
        auto conflict=replay;conflict.*member=true;assert(!ownsReplay(conflict));
        assert(!replacementEligible(conflict,0x100,0x200));
    }
    assert(!ownsReplay(Context{}));
    for(int state:{0,1,2,3,4}) {
        assert(originalEligibility(false,false,state)); // Offline normal-menu replay.
        assert(originalEligibility(true,true,state)); // Original spectator branch.
        assert(originalEligibility(true,false,state));
        assert(originalEligibility(false,true,state)==(state==3));
    }
    std::cout << "Replay ownership exclusions, decoded-data replacement and original update eligibility passed\n";
}
