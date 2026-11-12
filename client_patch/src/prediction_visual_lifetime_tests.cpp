#include "prediction_visual_lifetime.hpp"
#include <cassert>
#include <iostream>
#include <initializer_list>
#include <string>

using namespace ba_prediction_visual_lifetime;
namespace {
const std::string matchA(32,'a'),matchB(32,'b');
Snapshot active(uint64_t world=1,const std::string& match=matchA) {
    Snapshot value;value.movementWorld=value.workerWorld=world;
    value.movementMatch=value.workerMatch=match;value.ownerThread=7;
    value.prepared=value.pacingStarted=value.connected=true;return value;
}
Reason decide(const Snapshot& value,bool visualFailed=false) {return retirement(1,matchA,visualFailed,value);}
void end_is_not_drain_completion() {
    // END acknowledgement and terminal result can precede the final original
    // presentation/job completion. Neither may release presentation owners.
    for(bool ended:{false,true})for(bool sent:{false,true}) {
        auto value=active();value.matchEnded=ended;value.endSent=sent;
        assert(decide(value)==Reason::Keep);
    }
    auto value=active();value.matchEnded=value.endSent=true;
    assert(decide(value)==Reason::Keep);
    value.drained=true;assert(decide(value)==Reason::Drained);
    // Normal terminal retirement still identifies drain after transport closes.
    value.connected=false;value.workerWorld=0;value.workerMatch.clear();
    assert(decide(value)==Reason::Drained);
}
void failures_and_abort_do_not_wait_for_another_match() {
    auto value=active();assert(decide(value,true)==Reason::Failed);
    value.failed=true;assert(decide(value)==Reason::Failed);
    value=active();value.endSent=value.matchEnded=value.abortPending=true;
    assert(decide(value)==Reason::Aborted);
    value=active();value.connected=false;assert(decide(value)==Reason::Disconnected);
    value.matchEnded=true;assert(decide(value)==Reason::Disconnected);
}
void retired_worker_keys_are_sufficient_without_engine_objects() {
    auto value=active();value.workerWorld=0;assert(decide(value)==Reason::WorkerRetired);
    value=active();value.workerMatch.clear();assert(decide(value)==Reason::WorkerRetired);
    value=active();value.workerWorld=2;assert(decide(value)==Reason::WorkerChanged);
    value=active();value.workerMatch=matchB;assert(decide(value)==Reason::WorkerChanged);
}
void movement_reset_retires_the_previous_owner() {
    auto value=active();value.prepared=false;assert(decide(value)==Reason::MovementInactive);
    value=active();value.pacingStarted=false;assert(decide(value)==Reason::MovementInactive);
    value=active();value.movementWorld=2;assert(decide(value)==Reason::MovementChanged);
    value=active();value.movementMatch=matchB;assert(decide(value)==Reason::MovementChanged);
    value=active();assert(retirement(0,matchA,false,value)==Reason::MovementChanged);
    assert(retirement(1,"",false,value)==Reason::MovementChanged);
}
void replacement_world_is_not_retired_by_previous_terminal_flags() {
    auto old=active();old.endSent=old.matchEnded=old.drained=true;
    assert(decide(old)==Reason::Drained);
    const auto current=active(2,matchB);
    assert(decide(current)==Reason::MovementChanged); // Old retained roots.
    assert(retirement(2,matchB,false,current)==Reason::Keep); // Fresh owner.
    // Late original joins supply no authority to change these current keys;
    // the consumer re-reads this snapshot instead of the callback's old world.
    auto ending=current;ending.endSent=ending.matchEnded=true;
    assert(retirement(2,matchB,false,ending)==Reason::Keep);
}
void diagnostic_reason_contract() {
    assert(std::string(name(Reason::Keep))=="keep");
    assert(std::string(name(Reason::Drained))=="drained");
    assert(std::string(name(Reason::Failed))=="failed");
    assert(std::string(name(Reason::Aborted))=="aborted");
    assert(std::string(name(Reason::Disconnected))=="disconnected");
    assert(std::string(name(Reason::MovementInactive))=="movement_inactive");
    assert(std::string(name(Reason::MovementChanged))=="movement_changed");
    assert(std::string(name(Reason::WorkerRetired))=="worker_retired");
    assert(std::string(name(Reason::WorkerChanged))=="worker_changed");
}
}
int main() {
    end_is_not_drain_completion();failures_and_abort_do_not_wait_for_another_match();
    retired_worker_keys_are_sufficient_without_engine_objects();movement_reset_retires_the_previous_owner();
    replacement_world_is_not_retired_by_previous_terminal_flags();diagnostic_reason_contract();
    std::cout<<"visual lifetime policy: 6 groups PASS\n";
}
