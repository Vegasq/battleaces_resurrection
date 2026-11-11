#pragma once
#include "prediction_click_provenance.hpp"
#include <cstddef>
#include <cstdint>

// First qualified held case: one already-released HQ retains BOTH original
// numeric selection sets. This predicate never creates an intent or mutates a
// ledger/set. The native adapter separately proves raw typed membership, exact
// snapshot/graph/scope/frame, no queued commands/caster/modifiers, and repeats
// every check before pooling and after confirmed presentation recreation.
namespace ba_prediction_held_selection_policy {
namespace input=ba_prediction_input_observer;
namespace provenance=ba_prediction_click_provenance;
struct Identity {uint32_t entity=0,type=0,army=0;};
inline bool operator==(const Identity& a,const Identity& b)noexcept {
    return a.entity==b.entity && a.type==b.type && a.army==b.army;
}
struct Retirement {
    std::size_t count=0;
    bool alreadyReleased=false;
    Identity residentIdentity,currentIdentity;
    uint64_t residentIncarnation=0,canonicalIncarnation=0;
};
inline bool eligible(const input::Ledger& source,const provenance::Ledger& proof,
                     const input::Owner& expectedOwner,const Retirement& retirement)noexcept {
    if(retirement.count!=1 || !retirement.alreadyReleased ||
       proof.phase()!=provenance::Phase::Held || proof.operation() ||
       !proof.current(source) || !proof.press() || !source.accepted())return false;
    const auto& press=*proof.press();const auto& accepted=*source.accepted();
    // The producer proves the current local HQ. Bind to its captured identity
    // and lifetime; numeric IDs/armies do not select the qualified player side.
    const auto& qualified=retirement.currentIdentity;
    return expectedOwner.generation && expectedOwner.world && expectedOwner.selector &&
        expectedOwner.manager && expectedOwner.thread && source.owner()==expectedOwner &&
        press.ticket.owner==expectedOwner && press.ticket.kind==input::Kind::Down &&
        accepted.kind==input::Kind::Down && accepted.serial==source.serial() &&
        provenance::same(press.ticket,accepted) && press.helper && press.frame>=0 &&
        qualified.type==3 && retirement.residentIdentity==qualified &&
        press.identity.entity==qualified.entity && press.identity.type==qualified.type &&
        press.identity.army==qualified.army && retirement.residentIncarnation &&
        retirement.residentIncarnation==press.identity.token &&
        retirement.canonicalIncarnation==retirement.residentIncarnation;
}
}
