#pragma once
#include <cstdint>
#include <limits>
#include <optional>
#include <stdexcept>

// Observer-owned input provenance only. A completed, positively observed Down
// is a prerequisite for a held-click repair, never permission to perform one.
// No CallbackContext, Unit pointer, selection snapshot or original state is owned
// here. The adapter must still prove identity, natural removal and current state.
namespace ba_prediction_input_observer {
enum class Kind : uint8_t {
    FocusCancel0,FocusCancel1,FocusCancel2,FocusCancel3,FocusCancel4,
    CancelAbility,QueueModifier,ForceModifier,Position,Down,Up,ContextDown,ContextUp
};
struct Owner {
    uint64_t generation=0,world=0;
    uintptr_t selector=0,manager=0;
    uint32_t thread=0;
};
inline bool operator==(const Owner& a,const Owner& b) noexcept {
    return a.generation==b.generation && a.world==b.world &&
        a.selector==b.selector && a.manager==b.manager && a.thread==b.thread;
}
struct Ticket {
    Owner owner;
    uint64_t serial=0;
    Kind kind=Kind::Position;
};
class Ledger {
public:
    Ticket begin(Owner owner,Kind kind) {
        require(owner.generation && owner.world && owner.selector && owner.manager && owner.thread,
            "input observer owner is incomplete");
        require(static_cast<unsigned>(kind)<=static_cast<unsigned>(Kind::ContextUp),
            "input observer callback kind differs");
        if(!(owner==owner_)) {
            require(owner.generation>owner_.generation,"input observer owner generation must advance");
            discard();owner_=owner;
        }
        advance();open_=true;kind_=kind;marked_=false;
        return {owner_,serial_,kind};
    }
    bool markSingleDown(const Ticket& ticket) noexcept {
        if(!current(ticket) || !open_ || ticket.kind!=Kind::Down || marked_)return false;
        marked_=true;return true;
    }
    bool complete(const Ticket& ticket) noexcept {
        if(!current(ticket) || !open_)return false;
        open_=false;
        if(marked_ && ticket.kind==Kind::Down)accepted_=ticket;
        marked_=false;return true;
    }
    // Includes no-op edits. Set equality and selection-change notifications are
    // not evidence that the player left the original input episode untouched.
    void invalidate() {advance();}
    void abandon(const Ticket& ticket) noexcept {if(current(ticket))discard();}
    void discard() noexcept {open_=false;marked_=false;accepted_.reset();}
    const std::optional<Ticket>& accepted()const noexcept {return accepted_;}
    uint64_t serial()const noexcept {return serial_;}
    const Owner& owner()const noexcept {return owner_;}
private:
    static void require(bool value,const char* reason) {
        if(!value)throw std::invalid_argument(reason);
    }
    bool current(const Ticket& ticket)const noexcept {
        return ticket.serial && ticket.serial==serial_ && ticket.owner==owner_ && ticket.kind==kind_;
    }
    void advance() {
        discard();
        if(serial_==(std::numeric_limits<uint64_t>::max)())
            throw std::overflow_error("input observer serial exhausted");
        ++serial_;
    }
    Owner owner_;
    uint64_t serial_=0;
    Kind kind_=Kind::Position;
    bool open_=false,marked_=false;
    std::optional<Ticket> accepted_;
};

// The original callback runs exactly once even when observer preparation or
// completion fails. Its own exception propagates unchanged; it is never retried.
// failed()/abandon() are adapter-owned noexcept cleanup, not original callbacks.
template<class Access> void forward(Access& access) {
    bool prepared=false;
    try {prepared=access.prepare();}
    catch(const std::exception& error){access.failed(error.what());}
    catch(...){access.failed("unknown input observer preparation exception");}
    try {access.original();}
    catch(...){if(prepared)access.abandon();throw;}
    if(prepared) {
        try {access.complete();}
        catch(const std::exception& error){access.failed(error.what());}
        catch(...){access.failed("unknown input observer completion exception");}
    }
}
}
