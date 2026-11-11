#pragma once
// Include inside ba_prediction_actor_smoke after regular HQ setup/escape helpers.
// Explicit owned diagnostic. The original InputSystem delivers the borrowed
// Mouse events on later ordinary frontend updates. No selector writes/reselects.
namespace held_click {
namespace vm=virtual_mouse;
namespace utility=expired_click;
static bool enabled(){return ba::flag(L"-prediction-held-click-smoke");}
struct State {
    uint64_t world=0,sequence=0,update=0,inputSequence=0,positionUpdate=0,pressUpdate=0,releaseUpdate=0;
    uint64_t originalToken=0,currentToken=0;
    std::string match;
    std::unique_ptr<Root> selector,originalActor,restoredActor;
    unsigned stage=0;
    ULONGLONG focusedAt=0;
    float x=0,y=0;
    uint32_t lastUpBits=0,windowBits=0;
    std::array<uint32_t,2> currentPosition{},downPosition{},referencePosition{};
    vm::Snapshot last{},pressed{},released{};
    bool closed=false,complete=false,failed=false,deathSelectionPreserved=false;
};
static State& state(){static State* value=new State;return *value;}
static uint64_t& frontendOrdinal(){static uint64_t value=0;return value;}
static void frontendUpdate(){require(frontendOrdinal()!=UINT64_MAX,"held click frontend ordinal overflow");++frontendOrdinal();}
static std::array<uint32_t,2> position(Obj selector,size_t offset) {
    return {utility::bits(ba::read<float>(selector,offset)),utility::bits(ba::read<float>(selector,offset+4))};
}
static std::string positionJson(const std::array<uint32_t,2>& value) {
    return "["+std::to_string(value[0])+","+std::to_string(value[1])+"]";
}
static std::string idsJson(const std::vector<uint32_t>& value) {
    std::ostringstream out;out<<'[';bool first=true;for(auto id:value){if(!first)out<<',';first=false;out<<id;}out<<']';return out.str();
}
static std::string pointer(Obj value) {
    std::ostringstream out;out<<std::hex<<reinterpret_cast<uintptr_t>(value);return out.str();
}
static uint64_t token(actors::State& owner,Obj actor) {
    const auto found=owner.identities.find(actor);return found==owner.identities.end()?0:found->second.incarnation;
}
static void owned(actors::State& owner,Obj selector) {
    utility::owned(owner,selector);auto& s=state();
    require(!s.failed&&s.world==owner.world&&s.match==owner.match&&s.selector&&s.selector->get()==selector&&
        !utility::enabled()&&!ba::flag(L"-prediction-mobile-correction-smoke")&&
        ba::flag(L"-prediction-actor-correction-smoke"),"held click fixture owner/flag scope differs");
    require(ba::read<int32_t>(selector,0xa0)==-1&&!ba::read<Obj>(selector,0xa8)&&
        !ba::read<Obj>(selector,0x100),"held click fixture focus/caster became active");
    actors::field(selector,"_castingSet",0x98);
    require(actors::clickSelectionShape(ba::read<Obj>(selector,0x98),5,3,false),"held click fixture casting scratch is not raw empty");
}
static void validatePositions(Obj selector) {
    Obj vector=actors::type("UnityEngine","Vector2");
    actors::clickField(selector,"_currentPointerPosition",0x14c,vector,8);
    actors::clickField(selector,"_pointerDownPosition",0x164,vector,8);
    actors::clickField(selector,"_doubleClickFirstClickReferencePosition",0x12c,vector,8);
}
static void held(actors::State& owner,Obj selector) {
    owned(owner,selector);auto& s=state();s.last=vm::observe();const auto h=utility::history(selector);
    require(h.id==5&&h.mode==1&&h.primary&&!h.context&&!h.drag&&s.last.ownedButtonPressed&&
        s.last.selectorPrimaryHeld&&!s.last.selectorContextHeld&&s.last.queuedSequence==2&&
        utility::bits(h.lastUp)==s.lastUpBits&&utility::bits(h.window)==s.windowBits&&
        position(selector,0x14c)==s.currentPosition&&position(selector,0x164)==s.downPosition&&
        position(selector,0x12c)==s.referencePosition,"held click fixture changed its original live history/positions");
}
static void record(actors::State& owner,Obj selector,int frame,const char* event) {
    owned(owner,selector);auto& s=state();const auto h=utility::history(selector);
    const float now=actors::clickNow();require(std::isfinite(now)&&now>=h.lastUp,"held click fixture original clock differs");
    if(!s.closed)require(s.last.selector==selector&&s.last.world==s.world&&s.last.match==s.match&&
        s.last.queuedSequence==s.inputSequence&&s.last.selectorPrimaryHeld==h.primary&&
        s.last.selectorContextHeld==h.context,"held click fixture actual input snapshot differs");
    const Obj currentSet=ba::read<Obj>(selector,0x90),previewSet=ba::read<Obj>(selector,0x88);
    Obj current=coreFor(owner);const uint64_t currentToken=current?token(owner,current):0;
    const auto boolean=[](bool value){return value?"true":"false";};
    const auto accepted=owner.inputIntent.accepted();
    std::ostringstream out;
    out<<"{\"schema\":1,\"event\":\""<<event<<"\",\"sequence\":"<<++s.sequence
       <<",\"world\":"<<s.world<<",\"match\":\""<<s.match<<"\",\"slot\":1,\"entity\":5,\"unit_type\":3,\"frame\":"<<frame
       <<",\"update\":"<<s.update<<",\"update_scope\":\"original_frontend_callback\",\"input_sequence\":"<<s.inputSequence
       <<",\"selector\":\""<<pointer(s.last.selector)<<"\",\"action\":\""<<pointer(s.last.action)
       <<"\",\"control\":\""<<pointer(s.last.control)<<"\",\"device\":\""<<pointer(s.last.device)
       <<"\",\"input_source\":\"bound_existing_mouse\",\"ownership_scope\":\""<<(s.closed?"retained_scalar":"borrowed_current")<<"\",\"owned_button\":";
    if(s.closed)out<<"null";else out<<boolean(s.last.ownedButtonPressed);
    out<<",\"input_closed\":"<<boolean(s.closed)<<",\"click_id\":"<<h.id<<",\"mode\":"<<h.mode
       <<",\"primary\":"<<boolean(h.primary)<<",\"context\":"<<boolean(h.context)<<",\"drag\":"<<boolean(h.drag)
       <<",\"now_bits\":"<<utility::bits(now)<<",\"last_up_bits\":"<<utility::bits(h.lastUp)<<",\"window_bits\":"<<utility::bits(h.window)
       <<",\"target_position_bits\":"<<positionJson({utility::bits(s.x),utility::bits(s.y)})
       <<",\"current_position_bits\":"<<positionJson(position(selector,0x14c))
       <<",\"down_position_bits\":"<<positionJson(position(selector,0x164))
       <<",\"reference_position_bits\":"<<positionJson(position(selector,0x12c))
       <<",\"current_ids\":"<<idsJson(selection::selectionIds(currentSet))<<",\"preview_ids\":"<<idsJson(selection::selectionIds(previewSet))
       <<",\"current_exact5\":"<<boolean(actors::clickSelectionShape(currentSet,5,3,true))
       <<",\"current_empty\":"<<boolean(actors::clickSelectionShape(currentSet,5,3,false))
       <<",\"preview_exact5\":"<<boolean(actors::clickSelectionShape(previewSet,5,3,true))
       <<",\"preview_empty\":"<<boolean(actors::clickSelectionShape(previewSet,5,3,false))
       <<",\"original_actor\":\""<<pointer(s.originalActor->get())<<"\",\"current_actor\":\""<<pointer(current)
       <<"\",\"original_token\":"<<s.originalToken<<",\"current_token\":"<<currentToken
       <<",\"original_dead\":"<<boolean(ba::read<bool>(s.originalActor->get(),0x160))
       <<",\"original_component\":"<<boolean(ba::read<Obj>(s.originalActor->get(),0x158)!=nullptr)
       <<",\"focus_group\":"<<ba::read<int32_t>(selector,0xa0)<<",\"focus_actor\":\""<<pointer(ba::read<Obj>(selector,0xa8))
       <<"\",\"active_caster\":\""<<pointer(ba::read<Obj>(selector,0x100))<<"\",\"input_serial\":"<<owner.inputIntent.serial()
       <<",\"accepted_down_serial\":"<<(accepted?accepted->serial:0)
       <<",\"provenance_phase\":"<<static_cast<unsigned>(owner.clickProvenance.phase())
       <<",\"originalClockSingle\":true,\"selectionWritesAfterPress\":0,\"physicalUI\":false}";
    ba::log("HELD CLICK %s",out.str().c_str());
}
static void clear() {
    auto& s=state();if(s.failed)return;
    require(!s.world||(s.closed&&s.complete),"held click fixture ended with a held/unfinished original input session");s=State{};
}
static void markFailed(){state().failed=true;}
static void tick() {
    if(state().failed)return; // Retain the failed borrowed session; never fabricate cleanup input.
    const auto world=worker::movementWorldId();const auto match=worker::movementMatchId();
    if(!worker::movementEnabled()||!world||match.empty()){clear();ba_prediction_actor_smoke::state()=ba_prediction_actor_smoke::State{};return;}
    auto& fixture=ba_prediction_actor_smoke::state();
    if(fixture.world!=world||fixture.match!=match) {
        clear();fixture=ba_prediction_actor_smoke::State{};fixture.world=world;fixture.match=match;
    }
    auto& s=state();if(s.failed||s.complete||fixture.failed)return;
    auto& owner=actors::state();
    if(owner.world!=world||owner.match!=match||!owner.manager||!owner.simulation)return;
    require(!owner.failed&&owner.thread==GetCurrentThreadId(),"held click fixture actor owner failed/changed");
    if(ba_lan::matchEnded)return;
    require(ba::unified()&&ba::community()&&ba::dedicated()&&ba::lan()&&ba_lan::originalCommandScheduling()&&
        ba_lan::running&&!ba_lan::publicMatch,"held click fixture requires negotiated prediction Custom");
    const int frame=ba::read<int>(owner.simulation->get(),0xac);
    if(ba::lanSlot()==0) {
        if(fixture.escapeQueued||frame<152)return;
        require(frame==152,"held click attacker missed original escape152");escape(owner,selectorFor(owner),frame);return;
    }
    require(ba::lanSlot()==1,"held click fixture requires exactly two human seats");if(frame<130)return;
    Obj selector=selectorFor(owner);s.update=frontendOrdinal();require(s.update,"held click frontend ordinal missing");
    if(!fixture.setup) {
        require(frame==130,"held click fixture missed regular original setup130");setup(owner,selector,frame);
        s.world=world;s.match=match;s.selector=std::make_unique<Root>(selector);
        s.originalActor=std::make_unique<Root>(fixture.originalCore->get());s.originalToken=token(owner,s.originalActor->get());
        require(s.originalToken,"held click original actor lacks immutable token");
        utility::validateHistory(selector);validatePositions(selector);owned(owner,selector);
        const auto h=utility::history(selector);require(!h.primary&&!h.context&&!h.drag&&h.mode==0,
            "held click fixture starts with a live gesture");
        const Obj currentSet=ba::read<Obj>(selector,0x90),previewSet=ba::read<Obj>(selector,0x88);
        const bool currentExact=actors::clickSelectionShape(currentSet,5,3,true);
        const bool previewEmpty=actors::clickSelectionShape(previewSet,5,3,false);
        const bool previewExact=actors::clickSelectionShape(previewSet,5,3,true);
        ba::log("Held setup precheck: world=%llu frame=%d currentExact5=%u previewEmpty=%u previewExact5=%u currentIds=%s previewIds=%s",
            static_cast<unsigned long long>(world),frame,currentExact?1u:0u,previewEmpty?1u:0u,previewExact?1u:0u,
            idsJson(selection::selectionIds(currentSet)).c_str(),idsJson(selection::selectionIds(previewSet)).c_str());
        // The borrowed Mouse survives rematch at its last position. Original
        // hover may already preview this HQ before this episode queues a Down.
        // Keep both raw typed shapes exact; never clear/reseed that preview.
        require(currentExact&&(previewEmpty||previewExact),"held click setup raw current/preview differs");
        vm::preflight(owner,selector);vm::begin(owner,selector);s.last=vm::observe();
        require(!s.last.ownedButtonPressed&&!s.last.selectorPrimaryHeld&&!s.last.selectorContextHeld&&s.last.queuedSequence==0,
            "held click borrowed Mouse was not initially released");record(owner,selector,frame,"setup");
        utility::focus(selector);s.focusedAt=GetTickCount64();s.last=vm::observe();record(owner,selector,frame,"focused");s.stage=1;return;
    }
    owned(owner,selector);
    if(s.stage==1) {
        if(frame<148)return;require(frame<=149&&GetTickCount64()-s.focusedAt>=200,"held click missed settled position148/149");
        // Original FocusOnPosition writes the camera transform synchronously,
        // but later original pan updates may supersede the focus at setup130.
        // Refocus before projecting, while no press or held history exists.
        Root controller(utility::reference(selector,"_cameraController",0x20,actors::type("Uncapped","CameraController")));
        Obj canMove=actors::method(controller.get(),"get_CanUserMoveCamera",0,0x060015cf,0x3e9b8a0);
        utility::signature(canMove,false,actors::type("System","Boolean"));
        Root allowed(actors::invoke(canMove,controller.get()));actors::classIs(allowed.get(),"System","Boolean");
        const bool originalAllowed=actors::unbox<bool>(allowed.get());
        ba::log("Held camera projection focus: world=%llu frame=%d originalCanUserMove=%u originalFocusOnHQ=1 beforePress=1",
            static_cast<unsigned long long>(world),frame,originalAllowed?1u:0u);
        require(originalAllowed,"held click camera refuses original user focus before projection");
        utility::focus(selector);
        const auto point=utility::project(owner,selector,coreFor(owner));s.x=point.first;s.y=point.second;
        const auto receipt=vm::queuePositionButton(s.x,s.y,false);require(receipt.sequence==1&&!receipt.held,"held click position queue differs");
        s.inputSequence=receipt.sequence;s.positionUpdate=s.update;s.last=vm::observe();record(owner,selector,frame,"position_queued");s.stage=2;return;
    }
    if(s.stage==2) {
        s.last=vm::observe();if(s.update<=s.positionUpdate)return;
        require(frame<=151,"held click position callback missed press window");
        const std::array<uint32_t,2> target{utility::bits(s.x),utility::bits(s.y)};
        if(position(selector,0x14c)!=target)return;
        if(frame<150)return;
        require(!s.last.ownedButtonPressed&&!s.last.selectorPrimaryHeld&&!s.last.selectorContextHeld,"held click position phase has a held button");
        record(owner,selector,frame,"position_observed");
        const auto receipt=vm::queuePositionButton(s.x,s.y,true);require(receipt.sequence==2&&receipt.held,"held click press queue differs");
        s.inputSequence=receipt.sequence;s.last=vm::observe();record(owner,selector,frame,"press_queued");s.stage=3;return;
    }
    if(s.stage==3) {
        s.last=vm::observe();require(frame<=154,"held click original Down missed consume154");
        if(!s.last.selectorPrimaryHeld||!s.last.ownedButtonPressed)return;
        const auto h=utility::history(selector);require(h.id==5&&h.mode==1&&h.primary&&!h.context&&!h.drag,
            "held click original Down did not establish Single/id5");
        s.lastUpBits=utility::bits(h.lastUp);s.windowBits=utility::bits(h.window);
        s.currentPosition=position(selector,0x14c);s.downPosition=position(selector,0x164);s.referencePosition=position(selector,0x12c);
        const std::array<uint32_t,2> target{utility::bits(s.x),utility::bits(s.y)};
        require(s.currentPosition==target&&s.downPosition==target&&s.referencePosition==target,
            "held click original press/reference position differs");
        require(owner.inputIntent.accepted()&&owner.inputIntent.accepted()->kind==ba_prediction_input_observer::Kind::Down,
            "held click lacks actual original accepted Down provenance");
        s.pressed=s.last;s.pressUpdate=s.update;held(owner,selector);record(owner,selector,frame,"pressed");s.stage=4;
    }
    if(s.stage==4) {
        held(owner,selector);if(frame<154)return;require(frame==154,"held click missed hold checkpoint154");
        require(actors::clickSelectionShape(ba::read<Obj>(selector,0x90),5,3,true)&&
            actors::clickSelectionShape(ba::read<Obj>(selector,0x88),5,3,true),"held click pre-death raw selection differs");
        record(owner,selector,frame,"held_checkpoint");s.stage=5;return;
    }
    if(s.stage==5) {
        held(owner,selector);require(frame<=156,"held click missed original death156");
        Obj old=s.originalActor->get();if(!ba::read<bool>(old,0x160)||ba::read<Obj>(old,0x158))return;
        require(frame>=155,"held click original death precedes fixture boundary");
        const auto retained=actors::units(ba::read<Obj>(owner.manager->get(),0xa0));
        const bool oldRetained=std::find(retained.begin(),retained.end(),old)!=retained.end();
        const Obj currentSet=ba::read<Obj>(selector,0x90),previewSet=ba::read<Obj>(selector,0x88);
        const bool currentEmpty=actors::clickSelectionShape(currentSet,5,3,false);
        const bool previewEmpty=actors::clickSelectionShape(previewSet,5,3,false);
        const bool currentExact=actors::clickSelectionShape(currentSet,5,3,true);
        const bool previewExact=actors::clickSelectionShape(previewSet,5,3,true);
        ba::log("Held death precheck: world=%llu frame=%d retained=%u retainedCount=%zu currentEmpty=%u previewEmpty=%u currentExact5=%u previewExact5=%u currentIds=%s previewIds=%s inputSerial=%llu provenancePhase=%u",
            static_cast<unsigned long long>(world),frame,oldRetained?1u:0u,retained.size(),currentEmpty?1u:0u,
            previewEmpty?1u:0u,currentExact?1u:0u,previewExact?1u:0u,
            idsJson(selection::selectionIds(currentSet)).c_str(),idsJson(selection::selectionIds(previewSet)).c_str(),
            static_cast<unsigned long long>(owner.inputIntent.serial()),static_cast<unsigned>(owner.clickProvenance.phase()));
        const bool sameInput=owner.clickProvenance.current(owner.inputIntent);
        const bool preserved=sameInput&&currentExact&&previewExact&&
            owner.clickProvenance.phase()==ba_prediction_click_provenance::Phase::Held;
        const bool removed=sameInput&&currentEmpty&&previewEmpty&&
            owner.clickProvenance.phase()==ba_prediction_click_provenance::Phase::Removed;
        require(oldRetained&&(preserved||removed),"held click original release selection/provenance differs");
        s.deathSelectionPreserved=preserved;
        fixture.firstDead=frame;event("original_dead_hq_retained",frame,old);record(owner,selector,frame,"dead_hq_retained");s.stage=6;return;
    }
    if(s.stage==6) {
        held(owner,selector);require(frame<=164,"held click restored actor missed164");
        Obj core=coreFor(owner);if(!core)return;
        selection::Context admission(selector);if(!admission.admitted(core))return;
        require(frame>=158&&actors::resident(core).entityId==5,"held click restored HQ frame/identity differs");
        // Resident.incarnation is the canonical logical entity token. A false
        // death recreates presentation while preserving that same identity;
        // pool/recreation evidence, rather than pointer/token inequality, owns
        // the physical-lifecycle proof.
        s.currentToken=token(owner,core);require(s.currentToken&&s.currentToken==s.originalToken,
            "held click restored HQ changed its immutable canonical identity");
        s.restoredActor=std::make_unique<Root>(core);fixture.firstRestored=frame;
        event("original_hq_restored_and_admitted",frame,core);record(owner,selector,frame,"hq_restored");s.stage=7;
    }
    if(s.stage==7) {
        held(owner,selector);require(frame<=164,"held click restored preview missed164");
        require(actors::clickSelectionShape(ba::read<Obj>(selector,0x90),5,3,s.deathSelectionPreserved),
            "held click current changed its original retained/removal intent before Up");
        if(!actors::clickSelectionShape(ba::read<Obj>(selector,0x88),5,3,true))return;
        record(owner,selector,frame,"preview_ready");s.stage=8;return;
    }
    if(s.stage==8) {
        held(owner,selector);if(frame<(std::max)(165,fixture.firstRestored+2))return;
        require(frame<=166,"held click missed real Up queue165/166");
        require(coreFor(owner)==s.restoredActor->get()&&token(owner,s.restoredActor->get())==s.currentToken&&
            actors::clickSelectionShape(ba::read<Obj>(selector,0x90),5,3,s.deathSelectionPreserved)&&
            actors::clickSelectionShape(ba::read<Obj>(selector,0x88),5,3,true),"held click lost restored preview before real Up");
        const auto receipt=vm::queuePositionButton(s.x,s.y,false);require(receipt.sequence==3&&!receipt.held,"held click release queue differs");
        s.inputSequence=receipt.sequence;s.last=vm::observe();record(owner,selector,frame,"release_queued");s.stage=9;return;
    }
    require(s.stage==9,"held click fixture stage differs");s.last=vm::observe();require(frame<=167,"held click actual Up missed167");
    if(s.last.selectorPrimaryHeld||s.last.ownedButtonPressed)return;
    const auto h=utility::history(selector);require(s.update>s.pressUpdate&&!h.primary&&!h.context&&!h.drag&&h.mode==0&&h.id==5&&
        actors::clickSelectionShape(ba::read<Obj>(selector,0x90),5,3,true)&&
        actors::clickSelectionShape(ba::read<Obj>(selector,0x88),5,3,false),"held click real Up did not confirm restored HQ");
    s.released=s.last;s.releaseUpdate=s.update;record(owner,selector,frame,"released");
    vm::ReleaseObservation release;release.pressedSnapshot=s.pressed;release.releasedSnapshot=s.released;
    release.pressUpdate=s.pressUpdate;release.releaseUpdate=s.releaseUpdate;vm::close(release);s.closed=true;
    record(owner,selector,frame,"input_closed");
    require(frame>=fixture.firstRestored+2&&s.sequence==13,"held click final actor/input sequence differs");
    fixture.passed=true;event("hq_selection_correction_passed",frame,s.restoredActor->get());record(owner,selector,frame,"complete");s.complete=true;
}
}
