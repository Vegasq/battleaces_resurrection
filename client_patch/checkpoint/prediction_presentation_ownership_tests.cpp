// Regression host for the actual production presentation ownership function.
// No game, worker, native world or DLL is loaded.
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
namespace ba_prediction_movement {
struct State {
    bool prepared=true,pacingStarted=true,drained=false;
    uint64_t world=2;
    std::string match=std::string(32,'a');
    void* simulation=reinterpret_cast<void*>(uintptr_t{0x1000});
    void* server=reinterpret_cast<void*>(uintptr_t{0x2000});
};
static State state;
static bool requested=true,bindingMismatch=false;
static unsigned boundCalls=0;
namespace worker {
static uint64_t world=2;
static std::string match(32,'a');
static bool movementEnabled(){return requested;}
static uint64_t movementWorldId(){return world;}
static const std::string& movementMatchId(){return match;}
}
static void bound(void* server) {
    ++boundCalls;
    if(state.drained||bindingMismatch||server!=state.server)
        throw std::logic_error("movement prediction generation/match changed");
}
#include "../src/prediction_presentation_ownership.hpp"
static void check(bool value,const char* reason){if(!value)throw std::runtime_error(reason);}
static void reset() {
    state=State{};requested=true;bindingMismatch=false;boundCalls=0;
    worker::world=2;worker::match.assign(32,'a');
}
static void inactiveDoesNotConsultActiveBinding() {
    for(unsigned variant=0;variant<9;++variant) {
        reset();void* simulation=state.simulation;
        if(variant==0)requested=false;
        if(variant==1)state.prepared=false;
        if(variant==2)state.pacingStarted=false;
        if(variant==3)state.world=0;
        if(variant==4)state.match.clear();
        if(variant==5)simulation=nullptr;
        if(variant==6)worker::world=0;
        if(variant==7)worker::match.clear();
        if(variant==8)state.drained=true; // Actual65: key survives terminal drain.
        check(!ownsPresentation(simulation)&&boundCalls==0,"inactive presentation was rebound");
    }
}
static void activeOwnershipRemainsStrict() {
    reset();check(ownsPresentation(state.simulation)&&boundCalls==1,"active owner refused");
    reset();bindingMismatch=true;bool rejected=false;
    try{(void)ownsPresentation(state.simulation);}catch(const std::logic_error&){rejected=true;}
    check(rejected&&boundCalls==1,"active generation mismatch was silently bypassed");
}
static void nextWorldCanOwnAfterDrainedWorldRetires() {
    reset();state.drained=true;
    check(!ownsPresentation(state.simulation)&&boundCalls==0,"drained world still owns presentation");
    state=State{};state.world=3;worker::world=3;
    check(ownsPresentation(state.simulation)&&boundCalls==1,"fresh world inherited retired ownership");
}
}
int main(){try {
    ba_prediction_movement::inactiveDoesNotConsultActiveBinding();
    ba_prediction_movement::activeOwnershipRemainsStrict();
    ba_prediction_movement::nextWorldCanOwnAfterDrainedWorldRetires();
    std::cout<<"presentation ownership:3 actual-source groups PASS; no native runtime loaded\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
