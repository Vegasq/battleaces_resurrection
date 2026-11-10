#pragma once
#include <cstddef>
#include <cstdint>
#include <limits>
#include <map>
#include <optional>
#include <stdexcept>

// Metadata for membership which STILL EXISTS in the original control group.
// This policy never owns a Unit/Unity pointer, mutates membership, or re-adds an
// ID. The adapter must validate the current world/match, original group roots,
// exact typed membership and canonical ACTIVE observation before recording.
namespace ba_prediction_group_intent {
struct Key {
    uint32_t group=0,entity=0;
};
inline bool operator<(const Key& left,const Key& right) noexcept {
    return left.group<right.group || (left.group==right.group && left.entity<right.entity);
}
inline bool operator==(const Key& left,const Key& right) noexcept {
    return left.group==right.group && left.entity==right.entity;
}
struct Identity {
    uint32_t type=0,army=0;
    uint64_t token=0;
};
inline bool operator==(const Identity& left,const Identity& right) noexcept {
    return left.type==right.type && left.army==right.army && left.token==right.token;
}
enum class Decision {Keep,Forget,Purge};

class Ledger {
public:
    using Entries=std::map<Key,Identity>;
    static constexpr size_t maximumEntries=65536;
    explicit Ledger(size_t limit=maximumEntries):limit_(limit) {
        require(limit>0 && limit<=maximumEntries,"group intent entry limit differs");
    }
    // Opaque worker world IDs must advance on rematch. Resetting the SAME live
    // generation is harmless; a retired generation can never be reactivated.
    void reset(uint64_t generation) {
        require(generation && (generation>generation_ || (active_ && generation==generation_)),
                "group intent generation must advance");
        if(active_ && generation==generation_)return;
        entries_.clear();generation_=generation;active_=true;
    }
    void clear() noexcept {entries_.clear();active_=false;}
    uint64_t generation()const noexcept {return active_?generation_:0;}
    const Entries& entries()const noexcept {return entries_;}

    void remember(uint64_t generation,Key key,Identity identity) {
        current(generation);valid(key);valid(identity);
        const auto prior=entries_.find(key);
        if(prior!=entries_.end()) {
            require(prior->second==identity,"group intent identity changed before retirement");
            return;
        }
        require(entries_.size()<limit_,"group intent entry budget reached");
        entries_.emplace(key,identity);
    }
    Decision classify(uint64_t generation,Key key,bool membershipPresent,
                      std::optional<Identity> canonical,bool currentAdmittedSameLease)const {
        current(generation);valid(key);
        const auto prior=entries_.find(key);
        require(prior!=entries_.end(),"group intent entry is not recorded");
        if(canonical)valid(*canonical);
        // The adapter supplies ACTUAL visible membership, never the old saved
        // intent. An original Clear/replace/remove wins even when it emitted
        // no notification. Forgetting metadata does not restore membership.
        if(!membershipPresent)return Decision::Forget;
        // Includes canonical DEAD6 (absent from the ACTIVE packet), complete
        // disappearance, type/army change and a renewed incarnation token.
        if(!canonical || !(prior->second==*canonical))return Decision::Purge;
        if(currentAdmittedSameLease)return Decision::Forget;
        return Decision::Keep;
    }
    // Call after Forget, or ONLY AFTER the original purge and notification
    // succeeded. A failed original mutation must retain metadata/fail the owner.
    void erase(uint64_t generation,Key key) {
        current(generation);valid(key);entries_.erase(key);
    }
private:
    static void require(bool value,const char* message) {
        if(!value)throw std::invalid_argument(message);
    }
    static void valid(Key key) {
        require(key.group<16 && key.entity!=(std::numeric_limits<uint32_t>::max)(),
                "group intent key differs");
    }
    static void valid(Identity identity) {
        require(identity.type!=(std::numeric_limits<uint32_t>::max)() &&
                identity.army!=(std::numeric_limits<uint32_t>::max)() && identity.token,
                "group intent identity differs");
    }
    void current(uint64_t generation)const {
        require(active_ && generation && generation==generation_,"group intent owner generation differs");
    }
    size_t limit_;
    uint64_t generation_=0;
    bool active_=false;
    Entries entries_;
};
}
