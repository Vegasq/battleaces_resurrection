// Include inside ba_prediction_actors. Retain original numeric sets ONLY when
// the observed original release left the exact same logical click intact.
// The natural-removal/empty-preview case remains refused by this adapter.
class HeldSelection {
    using Eligibility=ba_prediction_held_selection_policy::Retirement;
    State& state_;
    Eligibility retirement_;
    Obj selector_=nullptr,frames_=nullptr;
    int frame_=-1;
    bool prepared_=false,completed_=false;
    ba_prediction_input_observer::Owner currentOwner()const {
        return {state_.groupGeneration,state_.world,reinterpret_cast<uintptr_t>(selector_),
            reinterpret_cast<uintptr_t>(state_.manager?state_.manager->get():nullptr),state_.thread};
    }
    bool current(Obj selector)const {
        if(!prepared_ || completed_ || selector!=selector_ || state_.failed || !state_.inUpdate ||
           state_.originalManagerUpdate || !state_.clickSelector || state_.clickSelector->get()!=selector_ ||
           state_.clickSnapshot.graph[4]!=frames_)return false;
        auto value=retirement_;
        value.canonicalIncarnation=confirmedToken(state_,{value.currentIdentity.entity,value.currentIdentity.type,value.currentIdentity.army});
        if(!ba_prediction_held_selection_policy::eligible(state_.inputIntent,state_.clickProvenance,currentOwner(),value) ||
           !clickSameSample(state_,selector_,false))return false;
        Current currentFrame(frames_);
        return ba::read<int>(currentFrame.frame.get(),0x40)==frame_ &&
            clickSelectionShape(state_.clickSnapshot.graph[1],5,3,true) &&
            clickSelectionShape(state_.clickSnapshot.graph[2],5,3,true) &&
            clickSelectionShape(state_.clickSnapshot.graph[3],5,3,false);
    }
public:
    explicit HeldSelection(State& state):state_(state){}
    bool prepared()const noexcept{return prepared_;}
    bool prepare(Obj selector,const std::vector<Retire>& retire) {
        require(!prepared_ && !completed_,"held selection preservation prepared twice");
        if(retire.size()!=1 || !clickCurrent(state_))return false;
        const auto& actor=retire.front();
        retirement_={retire.size(),actor.alreadyReleased,
            {actor.resident.entityId,actor.resident.unitType,actor.resident.armyId},
            {actor.current.entityId,actor.current.unitType,actor.current.armyId},
            actor.incarnation,confirmedToken(state_,actor.current)};
        selector_=selector;frames_=state_.clickSnapshot.graph[4];
        if(!frames_ || !ba_prediction_held_selection_policy::eligible(
                state_.inputIntent,state_.clickProvenance,currentOwner(),retirement_))return false;
        Current currentFrame(frames_);frame_=ba::read<int>(currentFrame.frame.get(),0x40);
        prepared_=true;
        if(!current(selector)){prepared_=false;return false;}
        ba::log("Prediction held selection prepared: world=%llu frame=%d entity=5 token=%llu serial=%llu retainedNumericSets=1 originalActorMutationStarted=0",
            static_cast<unsigned long long>(state_.world),frame_,
            static_cast<unsigned long long>(retirement_.residentIncarnation),
            static_cast<unsigned long long>(state_.inputIntent.serial()));return true;
    }
    bool allows(Obj selector)const{return current(selector);}
    void complete(Obj selector) {
        require(current(selector),"held selection changed during original actor recreation");
        unsigned found=0;
        for(Obj actor:units(ba::read<Obj>(state_.manager->get(),0x10))) {
            const auto identity=resident(actor);if(identity.entityId!=5)continue;
            const auto observed=state_.identities.find(actor);
            require(++found==1 && identity.unitType==3 && identity.armyId==1 &&
                observed!=state_.identities.end() && observed->second.identity.entityId==5 &&
                observed->second.identity.unitType==3 && observed->second.identity.armyId==1 &&
                observed->second.incarnation==retirement_.residentIncarnation &&
                confirmedToken(state_,identity)==retirement_.residentIncarnation,
                "held selection replacement is not the same admitted logical actor");
            field(actor,"<DeadToTheSim>k__BackingField",0x160);field(actor,"_componentData",0x158);
            require(!ba::read<bool>(actor,0x160) && ba::read<Obj>(actor,0x158),
                "held selection replacement lacks its original live presentation");
        }
        require(found==1,"held selection replacement is missing");
        require(current(selector),"held selection changed after replacement validation");
        completed_=true;
        ba::log("Prediction held selection preserved: world=%llu frame=%d entity=5 token=%llu serial=%llu originalRemovalSkipped=1 previewWrites=0 currentWrites=0 postRecreationAdmitted=1 originalUpStillPending=1",
            static_cast<unsigned long long>(state_.world),frame_,
            static_cast<unsigned long long>(retirement_.residentIncarnation),
            static_cast<unsigned long long>(state_.inputIntent.serial()));
    }
};
