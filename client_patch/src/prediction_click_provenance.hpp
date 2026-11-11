#pragma once
#include "prediction_input_observer.hpp"
#include <cstdint>
#include <optional>
#include <stdexcept>

// A positive original-operation witness, not an actor-repair permission. The
// adapter supplies exact rooted graph, raw typed-set and immutable identity
// observations. Input always wins over an in-flight original removal.
namespace ba_prediction_click_provenance {
namespace input=ba_prediction_input_observer;
struct Identity {uint32_t entity=0,type=0,army=0;uint64_t token=0;};
inline bool operator==(const Identity& a,const Identity& b)noexcept {
    return a.entity==b.entity && a.type==b.type && a.army==b.army && a.token==b.token;
}
inline bool same(const input::Ticket& a,const input::Ticket& b)noexcept {
    return a.owner==b.owner && a.serial==b.serial && a.kind==b.kind;
}
struct Press {
    input::Ticket ticket;
    Identity identity;
    uintptr_t helper=0;
    int32_t frame=-1;
};
enum class Phase {Empty,Held,Removing,Removed};
enum class RemovalPart {Preview,Current,Commit};
struct Removal {
    uint64_t nonce=0,managerUpdate=0;
    input::Ticket ticket;
    uintptr_t helper=0;
    Identity identity;
    int32_t frame=-1;
};
class Ledger {
public:
    void capture(const input::Ledger& source,Press value) {
        require(value.ticket.kind==input::Kind::Down && value.ticket.serial &&
            source.accepted() && same(value.ticket,*source.accepted()) &&
            value.identity.entity!=UINT32_MAX && value.identity.type!=UINT32_MAX &&
            value.identity.army!=UINT32_MAX && value.identity.token && value.helper && value.frame>=0,
            "click provenance lacks a completed accepted Down/identity");
        clear();press_=value;phase_=Phase::Held;
    }
    bool current(const input::Ledger& source)const noexcept {
        return press_ && source.accepted() && same(press_->ticket,*source.accepted());
    }
    Removal beginRemoval(const input::Ledger& source,uint64_t managerUpdate,
                         uintptr_t helper,Identity identity,int32_t frame) {
        require(current(source) && phase_==Phase::Held && !operation_ && managerUpdate &&
            managerUpdate>lastManagerUpdate_ && helper==press_->helper && identity==press_->identity &&
            frame>=press_->frame,"click natural removal has another episode/origin");
        if(operationSerial_==UINT64_MAX)throw std::overflow_error("click removal nonce exhausted");
        operation_=Removal{++operationSerial_,managerUpdate,press_->ticket,helper,identity,frame};
        phase_=Phase::Removing;parts_=0;return *operation_;
    }
    bool observe(const input::Ledger& source,const Removal& operation,RemovalPart part,
                 uintptr_t helper,uint32_t entity)noexcept {
        if(!matches(source,operation) || helper!=press_->helper || entity!=press_->identity.entity ||
           static_cast<unsigned>(part)!=parts_)return false;
        ++parts_;return true;
    }
    bool finishRemoval(const input::Ledger& source,const Removal& operation)noexcept {
        if(!matches(source,operation) || parts_!=3)return false;
        lastManagerUpdate_=operation.managerUpdate;phase_=Phase::Removed;operation_.reset();return true;
    }
    void clear()noexcept {press_.reset();operation_.reset();phase_=Phase::Empty;parts_=0;}
    void invalidate(input::Ledger& source) {clear();source.invalidate();}
    const std::optional<Press>& press()const noexcept {return press_;}
    const std::optional<Removal>& operation()const noexcept {return operation_;}
    Phase phase()const noexcept {return phase_;}
private:
    static void require(bool value,const char* reason){if(!value)throw std::invalid_argument(reason);}
    bool matches(const input::Ledger& source,const Removal& value)const noexcept {
        return current(source) && phase_==Phase::Removing && operation_ &&
            value.nonce==operation_->nonce && value.managerUpdate==operation_->managerUpdate &&
            same(value.ticket,operation_->ticket) && value.helper==operation_->helper &&
            value.identity==operation_->identity && value.frame==operation_->frame;
    }
    Phase phase_=Phase::Empty;
    unsigned parts_=0;
    uint64_t operationSerial_=0,lastManagerUpdate_=0;
    std::optional<Press> press_;
    std::optional<Removal> operation_;
};
}
