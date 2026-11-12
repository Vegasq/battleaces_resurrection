#include "prediction_visual_correction.hpp"
#include <cassert>
#include <algorithm>
#include <cmath>
#include <iostream>
#include <limits>

using namespace ba_prediction_visual_correction;
namespace {
constexpr uint64_t duration=900000;
static_assert(Policy::DurationUs==duration,"finite correction duration contract changed");
Identity owner() {
    Identity result;result.world=1;result.match=std::string(32,'a');
    result.entity=74;result.unitType=1;result.army=0;result.incarnation=75;return result;
}
void near(double actual,double expected) { assert(std::fabs(actual-expected)<1e-12); }
void zero(const Sample& value) {
    assert(value.status==SampleStatus::Ok);
    assert(value.offset.x==0&&value.offset.y==0&&value.offset.z==0);
}
void ordinary_motion_and_original_alpha() {
    const auto id=owner();Policy p;
    assert(p.sample(id,10,.5,0).status==SampleStatus::Unbound);
    assert(p.reset(id));zero(p.sample(id,10,.75,0));
    assert(p.admit(id,1,11,0,{-2,0,0})==Admission::Accepted);
    zero(p.sample(id,10,.9,0)); // A future published segment contributes nothing.
    zero(p.sample(id,11,0,0)); // Full correction is NOT injected at publication.
    near(p.sample(id,11,.25,0).offset.x,.5);
    near(p.sample(id,11,.75,0).offset.x,1.5);
    const auto midpoint=p.sample(id,12,0,(duration/2));near(midpoint.offset.x,1);
    // A new ordinary input changes position immediately: this component never
    // accepts a position or target to smooth, and its additive offset cancels.
    const double oldPosition=10+midpoint.offset.x,newPosition=13+midpoint.offset.x;
    near(newPosition-oldPosition,3);
    zero(p.sample(id,12,1,duration));assert(p.activePulses()==0&&p.retainedDistance()==0);
    zero(p.sample(id,20,.1,(duration+300000)));
    assert(p.admit(id,2,21,(duration+300000),{0,0,0})==Admission::NoCorrection);
    assert(p.activePulses()==0);zero(p.sample(id,21,.5,(duration+300000)));
}
void elapsed_time_stalls_and_no_sample_rate_dependence() {
    const auto id=owner();Policy frequent,sparse;
    assert(frequent.reset(id)&&sparse.reset(id));
    for(Policy* p:{&frequent,&sparse})assert(p->admit(id,1,10,1000,{-4,0,0})==Admission::Accepted);
    for(uint64_t t=1000;t<(duration/2+1000);t+=1000)frequent.sample(id,10,1,t);
    near(frequent.sample(id,10,1,(duration/2+1000)).offset.x,2);
    near(sparse.sample(id,10,1,(duration/2+1000)).offset.x,2);
    // Native frame and alpha may remain fixed throughout the whole stall.
    assert(sparse.sample(id,10,1,(duration+999)).offset.x>0);
    zero(sparse.sample(id,10,1,(duration+1000)));
    zero(frequent.sample(id,10,1,9001000)); // No capped-dt recovery tail.
    Policy curve;assert(curve.reset(id));
    assert(curve.admit(id,1,0,0,{-4,0,0})==Admission::Accepted);
    // Quarter-point anchors distinguish the chosen ease from a linear ramp.
    near(curve.sample(id,0,1,(duration/4)).offset.x,3.375);
    near(curve.sample(id,0,1,(3*duration/4)).offset.x,.625);
    zero(curve.sample(id,0,1,duration));
}
void repeated_noncollinear_corrections_keep_independent_deadlines() {
    const auto id=owner();Policy both,first,second;
    for(Policy* p:{&both,&first,&second})assert(p->reset(id));
    assert(both.admit(id,1,10,0,{-2,0,0})==Admission::Accepted);
    assert(first.admit(id,1,10,0,{-2,0,0})==Admission::Accepted);
    assert(both.admit(id,2,11,100000,{0,0,-1})==Admission::Accepted);
    assert(second.admit(id,2,11,100000,{0,0,-1})==Admission::Accepted);
    const auto combined=both.sample(id,12,1,(duration/2));
    const auto a=first.sample(id,12,1,(duration/2)),b=second.sample(id,12,1,(duration/2));
    near(combined.offset.x,a.offset.x+b.offset.x);near(combined.offset.z,a.offset.z+b.offset.z);
    const auto tail=both.sample(id,12,1,duration);
    assert(tail.offset.x==0&&tail.offset.z>0&&tail.activePulses==1);
    zero(both.sample(id,12,1,(duration+100000)));
    Policy shared;assert(shared.reset(id));
    assert(shared.admit(id,1,10,0,{-1,0,0})==Admission::Accepted);
    assert(shared.admit(id,2,10,0,{0,0,-2})==Admission::Accepted);
    const auto half=shared.sample(id,10,.5,0);near(half.offset.x,.5);near(half.offset.z,1);
}
void duplicate_conflict_and_expired_revision_are_distinct() {
    const auto id=owner();Policy p;assert(p.reset(id));
    assert(p.admit(id,1,10,0,{-2,0,0})==Admission::Accepted);
    assert(p.admit(id,2,11,100000,{0,0,-1})==Admission::Accepted);
    assert(p.admit(id,1,10,0,{-2,0,0})==Admission::Duplicate);
    assert(p.admit(id,1,10,0,{-3,0,0})==Admission::ConflictingRevision);
    assert(p.admit(id,2,11,100001,{0,0,-1})==Admission::ConflictingRevision);
    near(p.sample(id,12,1,(duration/2)).offset.x,1);
    assert(p.admit(id,2,11,100000,{0,0,-1})==Admission::Duplicate);
    const auto tail=p.sample(id,12,1,duration);assert(tail.offset.x==0&&tail.activePulses==1);
    assert(p.admit(id,1,10,0,{-2,0,0})==Admission::StaleRevision);
    zero(p.sample(id,12,1,(duration+100000)));
    assert(p.admit(id,2,11,100000,{0,0,-1})==Admission::Duplicate);
    assert(p.admit(id,2,12,100000,{0,0,-1})==Admission::ConflictingRevision);
    zero(p.sample(id,12,1,(duration+200000)));
}
void distance_refusal_does_not_clamp_or_later_apply() {
    const auto id=owner();Policy p;assert(p.reset(id));
    assert(p.admit(id,1,10,0,{-4.5,0,0})==Admission::Accepted);
    // Opposite direction does not evade the summed retained-distance budget.
    assert(p.admit(id,2,10,0,{4.5,0,0})==Admission::UncompensatedDistance);
    assert(p.admit(id,3,10,0,{-3.5,0,0})==Admission::Accepted);
    near(p.retainedDistance(),8);near(p.sample(id,10,1,0).offset.x,8);
    zero(p.sample(id,10,1,duration));
    assert(p.admit(id,2,10,0,{4.5,0,0})==Admission::StaleRevision);
    assert(p.admit(id,4,11,duration,{-8.1,0,0})==Admission::UncompensatedDistance);
    assert(p.admit(id,4,11,duration,{-8.1,0,0})==Admission::Duplicate);
    assert(p.admit(id,4,11,duration,{-1,0,0})==Admission::ConflictingRevision);
    zero(p.sample(id,11,1,duration));
    const double huge=std::numeric_limits<double>::max();
    assert(p.admit(id,5,12,duration,{huge,huge,huge})==Admission::UncompensatedDistance);
    assert(p.activePulses()==0);
}
void capacity_refusal_and_expiry_recovery() {
    const auto id=owner();Policy p;assert(p.reset(id));
    for(uint64_t revision=1;revision<=Policy::MaxPulses;++revision)
        assert(p.admit(id,revision,static_cast<int32_t>(revision),0,{-.125,0,0})==Admission::Accepted);
    assert(p.admit(id,17,17,0,{-.125,0,0})==Admission::UncompensatedCapacity);
    assert(p.activePulses()==16);near(p.sample(id,17,1,0).offset.x,2);
    zero(p.sample(id,17,1,duration));
    assert(p.admit(id,17,17,0,{-.125,0,0})==Admission::Duplicate);
    assert(p.admit(id,18,18,duration,{-.125,0,0})==Admission::Accepted);
    near(p.sample(id,18,1,duration).offset.x,.125);
}
void identity_and_lifetime_reset() {
    const auto id=owner();Policy p;assert(p.reset(id));
    assert(p.admit(id,1,10,0,{-2,0,0})==Admission::Accepted);
    for(unsigned field=0;field<6;++field) {
        auto wrong=id;
        if(field==0)++wrong.world;
        if(field==1)wrong.match[0]='b';
        if(field==2)++wrong.entity;
        if(field==3)++wrong.unitType;
        if(field==4)++wrong.army;
        if(field==5)++wrong.incarnation;
        assert(p.sample(wrong,10,1,0).status==SampleStatus::IdentityMismatch);
        assert(p.admit(wrong,2,11,0,{-1,0,0})==Admission::IdentityMismatch);
        assert(p.activePulses()==1);
    }
    assert(p.reset(id));zero(p.sample(id,10,1,0)); // Same identity, new actor/interpolator lifetime.
    assert(p.admit(id,1,11,0,{-1,0,0})==Admission::Accepted);
    auto replacement=id;++replacement.incarnation;assert(p.reset(replacement));
    zero(p.sample(replacement,0,0,0));
    auto nativeZero=id;nativeZero.entity=0;nativeZero.unitType=0;
    assert(p.reset(nativeZero));
    assert(p.admit(nativeZero,1,0,0,{-1,0,0})==Admission::Accepted);
    near(p.sample(nativeZero,0,1,0).offset.x,1);
    auto invalid=id;invalid.match="not-a-match";assert(!p.reset(invalid)&&!p.bound());
    assert(p.admit(id,1,1,0,{-1,0,0})==Admission::Unbound);
    assert(p.reset(id));p.clear();assert(!p.bound()&&p.activePulses()==0);
}
void malformed_inputs_and_chronology_do_not_mutate_policy() {
    const auto id=owner();Policy p;assert(p.reset(id));
    const double nan=std::numeric_limits<double>::quiet_NaN(),inf=std::numeric_limits<double>::infinity();
    for(double bad:{nan,inf,-inf})assert(p.admit(id,1,10,1000,{bad,0,0})==Admission::InvalidInput);
    assert(p.admit(id,0,10,1000,{-1,0,0})==Admission::InvalidInput);
    assert(p.admit(id,1,-1,1000,{-1,0,0})==Admission::InvalidInput);
    assert(p.admit(id,1,10,std::numeric_limits<uint64_t>::max(),{-1,0,0})==Admission::InvalidInput);
    assert(p.admit(id,1,10,1000,{-1,0,0})==Admission::Accepted);
    for(double bad:{nan,inf,-inf,-.001,1.001})assert(p.sample(id,10,bad,1000).status==SampleStatus::InvalidAlpha);
    assert(p.sample(id,-1,1,1000).status==SampleStatus::InvalidFrame);
    assert(p.sample(id,10,1,999).status==SampleStatus::ClockRegression);
    assert(p.admit(id,2,11,999,{-1,0,0})==Admission::ClockRegression);
    assert(p.admit(id,2,9,1000,{-1,0,0})==Admission::InvalidOrder);
    assert(p.admit(id,2,10,1001,{-1,0,0})==Admission::InvalidOrder);
    near(p.sample(id,10,1,1000).offset.x,1);
    assert(p.admit(id,2,10,1000,{-1,0,0})==Admission::InvalidOrder); // Late first admission.
    assert(p.sample(id,9,1,1000).status==SampleStatus::InvalidFrame);
    assert(p.activePulses()==1);near(p.retainedDistance(),1);
    zero(p.sample(id,10,1,(duration+1000)));
    Policy end;assert(end.reset(id));
    const auto start=std::numeric_limits<uint64_t>::max()-Policy::DurationUs;
    assert(end.admit(id,1,0,start,{-1,0,0})==Admission::Accepted);
    zero(end.sample(id,0,1,std::numeric_limits<uint64_t>::max()));
}
bool correction_decay_preserves_continuing_motion() {
    // Actual78 exposed cancellation: a 3.15-unit correction opposed a unit
    // moving at6.3units/s. Exercise both one coalesced repair and overlapping
    // repairs, independently of the runtime renderer and its sampling cadence.
    // This is a scoped regression, not a claim for every8-unit accepted offset.
    const auto id=owner();
    for(bool staggered:{false,true}) {
        Policy p;assert(p.reset(id));
        if(staggered) {
            assert(p.admit(id,1,10,0,{-1.89,0,0})==Admission::Accepted);
            assert(p.admit(id,2,11,50000,{-.63,0,0})==Admission::Accepted);
            assert(p.admit(id,3,12,100000,{-.63,0,0})==Admission::Accepted);
        } else assert(p.admit(id,1,10,0,{-3.15,0,0})==Admission::Accepted);
        double previous=0,anchor=0,minimumSpeed=1000;
        uint64_t previousUs=0,anchorUs=0,maximumHold=0;
        for(uint64_t us=150000;us<=Policy::DurationUs+250000;us+=5000) {
            const auto sampled=p.sample(id,20+static_cast<int32_t>(us/50000),1,us);
            assert(sampled.status==SampleStatus::Ok);
            const double raw=6.3*static_cast<double>(us)/1000000.0-3.15;
            const double shown=raw+sampled.offset.x;
            if(previousUs) {
                minimumSpeed=(std::min)(minimumSpeed,(shown-previous)*1000000.0/static_cast<double>(us-previousUs));
                maximumHold=(std::max)(maximumHold,us-anchorUs);
                if(std::fabs(shown-anchor)>.025){anchor=shown;anchorUs=us;}
            } else {anchor=shown;anchorUs=us;}
            previous=shown;previousUs=us;
        }
        if(minimumSpeed<1.0 || maximumHold>100000 || p.activePulses()!=0) {
            std::cerr<<"FAIL continuing-motion correction regression: staggered="<<staggered
                <<" minimumSpeed="<<minimumSpeed<<" maximumHoldUs="<<maximumHold
                <<" remainingPulses="<<p.activePulses()<<"\n";
            return false;
        }
    }
    return true;
}
}
int main() {
    ordinary_motion_and_original_alpha();
    elapsed_time_stalls_and_no_sample_rate_dependence();
    repeated_noncollinear_corrections_keep_independent_deadlines();
    duplicate_conflict_and_expired_revision_are_distinct();
    distance_refusal_does_not_clamp_or_later_apply();
    capacity_refusal_and_expiry_recovery();
    identity_and_lifetime_reset();
    malformed_inputs_and_chronology_do_not_mutate_policy();
    if(!correction_decay_preserves_continuing_motion())return 2;
    std::cout<<"Prediction visual correction policy tests passed\n";
}
