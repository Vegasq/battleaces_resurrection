#pragma once
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <string>

// Pure presentation-offset policy. No actor pointers, native state, ordinary
// movement, or interpolation-clock reconstruction belong here. The caller must
// supply the ORIGINAL clamped interpolation alpha and corrected publication.
namespace ba_prediction_visual_correction {
struct Vec3 { double x=0,y=0,z=0; };
struct Identity {
    uint64_t world=0;
    std::string match;
    uint32_t entity=0,unitType=0,army=0;
    uint64_t incarnation=0;
};
inline bool sameIdentity(const Identity& a,const Identity& b) {
    return a.world==b.world&&a.match==b.match&&a.entity==b.entity&&
        a.unitType==b.unitType&&a.army==b.army&&a.incarnation==b.incarnation;
}
inline bool validIdentity(const Identity& value) {
    // Entity/type zero are legal native identities; consumer eligibility is
    // separate from this generic ownership binding.
    if(!value.world||!value.incarnation||value.match.size()!=32)return false;
    return value.match.find_first_not_of("0123456789abcdef")==std::string::npos;
}
enum class Admission {
    Accepted,NoCorrection,Duplicate,StaleRevision,ConflictingRevision,
    UncompensatedDistance,UncompensatedCapacity,
    Unbound,IdentityMismatch,InvalidInput,InvalidOrder,ClockRegression
};
enum class SampleStatus { Ok,Unbound,IdentityMismatch,InvalidFrame,InvalidAlpha,ClockRegression };
struct Sample {
    SampleStatus status=SampleStatus::Unbound;
    Vec3 offset{};
    size_t activePulses=0;
};

class Policy {
public:
    // At600ms a coalesced3.15-unit repair can oppose6.3units/s movement
    // strongly enough to pause/reverse it.900ms leaves correction-rate margin
    // in that reproduced case while keeping an absolute finite deadline.
    static constexpr uint64_t DurationUs=900000;
    static constexpr size_t MaxPulses=16;
    static constexpr double MaxDistance=8.0;

    // A changed actor/interpolator lifetime MUST reset even when this canonical
    // identity is unchanged. An invalid reset also discards the former owner.
    void clear() { *this=Policy{}; }
    bool reset(const Identity& owner) {
        clear();
        if(!validIdentity(owner))return false;
        owner_=owner;bound_=true;return true;
    }
    bool bound() const { return bound_; }
    size_t activePulses() const { return count_; } // As of the last valid time observation.
    double retainedDistance() const { return distance_; }

    // delta is corrected(H)-old(H), first exposed by publishedFrame H+1.
    // Same-publication deltas may compose, but all must arrive before that
    // frame's first sample. publicationUs is immutable, NOT the retry time.
    Admission admit(const Identity& owner,uint64_t revision,int32_t publishedFrame,
                    uint64_t publicationUs,const Vec3& delta) {
        if(!bound_)return Admission::Unbound;
        if(!sameIdentity(owner_,owner))return Admission::IdentityMismatch;
        if(!revision||publishedFrame<0||!finite(delta)||
           publicationUs>(std::numeric_limits<uint64_t>::max)()-DurationUs)return Admission::InvalidInput;
        const Metadata incoming{revision,publishedFrame,publicationUs,delta};
        // Retained signatures authenticate older duplicates. Only the newest
        // signature survives expiry; older unretained revisions are stale,
        // never silently authenticated or admitted again.
        if(haveRevision_&&revision<=newest_.revision) {
            if(revision==newest_.revision)return duplicate(newest_,incoming);
            for(size_t i=0;i<count_;++i)
                if(pulses_[i].metadata.revision==revision)return duplicate(pulses_[i].metadata,incoming);
            return Admission::StaleRevision;
        }
        if(haveClock_&&publicationUs<lastUs_)return Admission::ClockRegression;
        if((haveRevision_&&(publishedFrame<newest_.frame||
            (publishedFrame==newest_.frame&&publicationUs!=newest_.publicationUs)))||
           (haveSample_&&publishedFrame<=lastSampleFrame_))return Admission::InvalidOrder;
        advance(publicationUs);
        newest_=incoming;haveRevision_=true;
        const double magnitude=std::hypot(std::hypot(delta.x,delta.y),delta.z);
        if(magnitude==0)return Admission::NoCorrection;
        // A refused revision is consumed. Retrying it after capacity frees may
        // not introduce a previously uncompensated correction retroactively.
        if(magnitude>MaxDistance-distance_)return Admission::UncompensatedDistance;
        if(count_==MaxPulses)return Admission::UncompensatedCapacity;
        pulses_[count_++]={incoming,magnitude};distance_+=magnitude;
        return Admission::Accepted;
    }

    // Check status before using the offset. Refused samples leave policy state
    // unchanged; their zero placeholder is not a successful recovery result.
    Sample sample(const Identity& owner,int32_t presentedFrame,double originalAlpha,uint64_t nowUs) {
        if(!bound_)return failure(SampleStatus::Unbound);
        if(!sameIdentity(owner_,owner))return failure(SampleStatus::IdentityMismatch);
        if(presentedFrame<0||(haveSample_&&presentedFrame<lastSampleFrame_))return failure(SampleStatus::InvalidFrame);
        if(!std::isfinite(originalAlpha)||originalAlpha<0||originalAlpha>1)return failure(SampleStatus::InvalidAlpha);
        if(haveClock_&&nowUs<lastUs_)return failure(SampleStatus::ClockRegression);
        advance(nowUs);haveSample_=true;lastSampleFrame_=presentedFrame;
        Vec3 offset{};
        for(size_t i=0;i<count_;++i) {
            const auto& pulse=pulses_[i].metadata;
            const double weight=presentedFrame<pulse.frame?0:(presentedFrame==pulse.frame?originalAlpha:1);
            const double age=static_cast<double>(nowUs-pulse.publicationUs)/static_cast<double>(DurationUs);
            // Finite-support cubic: value 1->0, zero endpoint derivatives.
            // Expired pulses were removed, so age is in [0,1).
            const double remaining=1-age;
            const double scale=weight*remaining*remaining*(1+2*age);
            offset.x-=pulse.delta.x*scale;
            offset.y-=pulse.delta.y*scale;
            offset.z-=pulse.delta.z*scale;
        }
        return {SampleStatus::Ok,offset,count_};
    }

private:
    struct Metadata {
        uint64_t revision=0;
        int32_t frame=0;
        uint64_t publicationUs=0;
        Vec3 delta{};
    };
    struct Pulse { Metadata metadata{};double magnitude=0; };
    static bool finite(const Vec3& value) {
        return std::isfinite(value.x)&&std::isfinite(value.y)&&std::isfinite(value.z);
    }
    static Admission duplicate(const Metadata& old,const Metadata& incoming) {
        return old.frame==incoming.frame&&old.publicationUs==incoming.publicationUs&&
            old.delta.x==incoming.delta.x&&old.delta.y==incoming.delta.y&&old.delta.z==incoming.delta.z?
            Admission::Duplicate:Admission::ConflictingRevision;
    }
    Sample failure(SampleStatus status) const { return {status,{},count_}; }
    void advance(uint64_t nowUs) {
        size_t keep=0;distance_=0;
        for(size_t i=0;i<count_;++i) {
            if(nowUs-pulses_[i].metadata.publicationUs>=DurationUs)continue;
            pulses_[keep]=pulses_[i];distance_+=pulses_[keep].magnitude;++keep;
        }
        for(size_t i=keep;i<count_;++i)pulses_[i]=Pulse{};
        count_=keep;lastUs_=nowUs;haveClock_=true;
    }
    Identity owner_{};
    std::array<Pulse,MaxPulses> pulses_{};
    Metadata newest_{};
    size_t count_=0;
    double distance_=0;
    uint64_t lastUs_=0;
    int32_t lastSampleFrame_=0;
    bool bound_=false,haveRevision_=false,haveClock_=false,haveSample_=false;
};
}
