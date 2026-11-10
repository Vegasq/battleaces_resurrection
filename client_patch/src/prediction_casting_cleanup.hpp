#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <stdexcept>

// Narrow ownership gate for an AFFECTED, inactive UnitSelector casting scratch.
// This does not cancel gestures, serialize/drain commands, or own actor pooling.
namespace ba_prediction_casting_cleanup {
inline constexpr uint32_t clearToken=0x060025ac;
inline constexpr uintptr_t clearRva=0x3c66c50;
inline constexpr std::array<uint8_t,16> clearEntry{{
    0x48,0x89,0x5c,0x24,0x08,0x57,0x48,0x83,0xec,0x70,0x48,0x8b,0xd9,0x80,0x3d,0xb4}};
inline constexpr size_t castingOffset=0x98,activeCasterOffset=0x100,commandQueueOffset=0x180;

// Access contract (adapter remains responsible for original IL2CPP ABI/rooting):
// validate(): readonly check of matching movement world/generation, owned human
// server and Unity update thread, same rooted selector/casting/queue180, exact
// declared fields and Clear token/RVA/entry/void/no-parameter method signature.
// hasActiveCaster()/hasAffectedLiveClick(): readonly current owner predicates.
// Lock(Access&): the CURRENT ba_local::QueueLock/SRW, shared by all owned enqueue
// and dequeue routes. Original server+40 Mutex or a queue Monitor is NOT this lock.
// commandCount(): actual Queue<ICommand>180 Count, only under Lock.
// clearCasting(): ONLY original UnitSelectionSet.Clear; no actor/selection/focus
// callbacks, no 188 mutation, no command serialization or network side effects.
// All preflight callbacks must be readonly and must not reenter a queue route.
template<class Access> class Plan final {
    Access& access_;
    bool affected_,prepared_=false,committed_=false;
    static void require(bool value,const char* why){if(!value)throw std::runtime_error(why);}
    void owners() {
        access_.validate();
        require(!access_.hasActiveCaster(),"affected casting scratch has an active ability owner");
        require(!access_.hasAffectedLiveClick(),"affected casting scratch has live click intent");
    }
public:
    Plan(Access& access,bool affected):access_(access),affected_(affected){}
    Plan(const Plan&)=delete;
    Plan& operator=(const Plan&)=delete;
    void prepare() {
        require(!prepared_&&!committed_,"casting cleanup preparation repeated");
        if(affected_) {
            owners();
            typename Access::Lock lock(access_);
            require(access_.commandCount()==0,"affected casting scratch aliases pending ICommand queue");
        }
        prepared_=true;
    }
    bool willClear()const noexcept{return prepared_&&affected_&&!committed_;}
    bool commit() {
        require(prepared_&&!committed_,"casting cleanup commit is unprepared/repeated");
        if(affected_) {
            // Prepare does not hold SRW across the other readonly plans. Recheck
            // immediately before the FIRST mutation; a new producer must refuse.
            owners();
            typename Access::Lock lock(access_);
            require(access_.commandCount()==0,"affected casting scratch gained a pending ICommand");
            access_.clearCasting();
        }
        committed_=true;
        return affected_;
    }
};
}
