// Asset-free scheduling tests: no game, helper DLL, native objects or network.
#include "telemetry_sampling.hpp"
#include <cassert>
#include <iostream>
using namespace ba_telemetry_sampling;

int main() {
    Schedule schedule;
    unsigned snapshots=1; // Startup is included in the process-wide limit.
    auto sample=[&](Stage stage,uint64_t now) {
        const bool take=schedule.due(stage,now,snapshots);
        if(take)++snapshots;
        return take;
    };
    assert(!sample(Stage::Other,100));
    assert(sample(Stage::Menu,101));
    assert(!sample(Stage::Menu,102));
    assert(!sample(Stage::Menu,10100));
    assert(sample(Stage::Menu,10101));
    assert(!sample(Stage::Menu,999999)); // At most two in a sustained entry.

    // Both result transitions and the intervening menu are observed, even when
    // all occur between the old ten-second status calls. Adjacent updates can
    // share a millisecond timestamp, so entry sampling has no time throttle.
    Schedule rematch;
    assert(rematch.due(Stage::InGame,1000,1));
    assert(rematch.due(Stage::PostGame,1001,2));
    assert(rematch.due(Stage::Menu,1001,3));
    assert(rematch.due(Stage::InGame,1002,4));
    assert(rematch.due(Stage::PostGame,1003,5));
    assert(!rematch.due(Stage::PostGame,1004,6));

    // Intermediate states re-arm the same state's next entry without sampling
    // unknown layouts, and the already-established tutorial target is eligible.
    Schedule other;
    assert(other.due(Stage::Menu,2000,1));
    assert(!other.due(Stage::Other,2001,2));
    assert(other.due(Stage::Menu,2002,2));
    assert(other.due(Stage::Tutorial,2003,3));
    assert(!other.due(Stage::Tutorial,2004,4));
    assert(other.due(Stage::Tutorial,12003,4));
    assert(!other.due(Stage::Tutorial,22003,5));

    Schedule clock;
    assert(clock.due(Stage::Menu,20000,1));
    assert(!clock.due(Stage::Menu,19999,2)); // No unsigned-underflow sample.
    assert(!clock.due(Stage::Menu,29999,2));
    assert(clock.due(Stage::Menu,30000,2));

    Schedule bounded;
    unsigned total=1;
    for(unsigned i=0;i<1000;++i) {
        const auto stage=i%2?Stage::PostGame:Stage::Menu;
        if(bounded.due(stage,i,total))++total;
    }
    assert(total==maxRegularSnapshots);
    assert(total+1==maxSnapshots); // Original Quit has one reserved slot.
    assert(!bounded.due(Stage::Other,50000,total));
    assert(!bounded.due(Stage::Tutorial,50001,total));
    assert(!bounded.due(Stage::InGame,60001,total));
    assert(!bounded.due(Stage::Menu,70001,maxSnapshots+1));

    std::cout << "Telemetry transition timing, rematch, tutorial and sample-budget checks passed\n";
}
