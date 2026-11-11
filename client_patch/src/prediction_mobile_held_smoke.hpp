#pragma once
// Explicit owned diagnostic. Original InputSystem delivers both Mouse sessions;
// no selector/history writes or synthetic callback/cleanup input are permitted.
namespace mobile_held {
namespace vm=virtual_mouse;
namespace utility=expired_click;
namespace base=mobile;
static bool enabled(){return ba::flag(L"-prediction-mobile-held-click-smoke");}
struct State {
    uint64_t world=0,sequence=0,update=0,queuedUpdate=0,pressUpdate=0;
    std::string match;
    unsigned stage=0,session=1;
    float x=0,y=0;
    bool inputOpened=false,closed=false,releaseQueued=false,complete=false,failed=false;
    vm::Snapshot last{},pressed{};
};
static State& state(){static State* value=new State;return *value;}
static uint64_t& ordinal(){static uint64_t value=0;return value;}
static void frontendUpdate(){require(ordinal()!=UINT64_MAX,"mobile held frontend ordinal exhausted");++ordinal();}
static void markFailed(){state().failed=true;}
static void releasedIdle(actors::State& owner,Obj selector,uint32_t entity) {
    base::owned(owner);utility::validateHistory(selector);const auto h=utility::history(selector);
    require(entity==11&&!h.primary&&!h.context&&!h.drag&&h.mode==0&&
        !ba::read<Obj>(selector,0x100)&&base::pending(owner)==0,
        "mobile held released input is not idle");
    Obj casting=ba::read<Obj>(selector,0x98);
    require(selection::selectionIds(casting).empty()&&!actors::selectionReferences(casting,{entity}),
        "mobile held released casting scratch is not empty");
    // The original last-click ID legitimately remains11 after actual Up.
    // This test guard does not clear it or treat it as an active gesture.
}
static void focus(actors::State& owner,Obj selector,Obj actor) {
    selection::Context context(selector);require(context.admitted(actor),"mobile held camera source is not admitted");
    Root camera(utility::reference(selector,"_cameraController",0x20,actors::type("Uncapped","CameraController")));
    Obj method=actors::method(camera.get(),"FocusOnUnit",1,0x060015ec,0x3e9e310);
    utility::signature(method,false,actors::type("System","Void"));
    require(base::original::parameterClass(method,0)==actors::type("Uncapped","Unit"),"mobile held camera Unit ABI differs");
    void* args[]={actor};actors::invoke(method,camera.get(),args);base::owned(owner);
}
static int resolvableCount(Obj set) {
    actors::classIs(set,"Uncapped.Collections","UnitSelectionSet");
    Obj method=actors::method(set,"get_Count",0,0x060025b5,0x3c68f00);
    utility::signature(method,false,actors::type("System","Int32"));
    Root boxed(actors::invoke(method,set));const int value=actors::unbox<int32_t>(boxed.get());
    require(value>=0&&value<=1,"mobile held original resolvable count exceeds its single member");return value;
}
static void record(actors::State& owner,Obj selector,int frame,const char* event) {
    auto& s=state();auto& m=base::state();base::View view(owner,selector);const auto h=utility::history(selector);
    if(!s.closed)s.last=vm::observe();
    require(s.last.world==s.world&&s.last.match==s.match&&s.last.selector==selector,
        "mobile held retained input tuple changed");
    const auto observed=ba_prediction_input::mobileReturnedInput;
    const auto returned=observed&&observed->ticket.owner.world==s.world&&observed->ticket.owner.generation==owner.groupGeneration&&
        observed->ticket.owner.selector==reinterpret_cast<uintptr_t>(selector)&&
        observed->ticket.owner.manager==reinterpret_cast<uintptr_t>(owner.manager->get())&&observed->ticket.owner.thread==GetCurrentThreadId()?observed:std::nullopt;
    const bool down=returned&&returned->ticket.kind==ba_prediction_input_observer::Kind::Down;
    const bool up=returned&&returned->ticket.kind==ba_prediction_input_observer::Kind::Up;
    Obj currentSet=ba::read<Obj>(selector,0x90),previewSet=ba::read<Obj>(selector,0x88);
    const auto currentIds=selection::selectionIds(currentSet),previewIds=selection::selectionIds(previewSet);
    const int currentCount=resolvableCount(currentSet),previewCount=resolvableCount(previewSet);
    require(currentIds==selection::selectionIds(currentSet)&&previewIds==selection::selectionIds(previewSet),
        "mobile held original Count query changed numeric membership");
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::boolalpha;
    out<<"{\"schema\":3,\"event\":\""<<event<<"\",\"sequence\":"<<++s.sequence
       <<",\"world\":"<<s.world<<",\"match\":\""<<s.match<<"\",\"slot\":1,\"entity\":11,\"unit_type\":1,\"army\":1"
       <<",\"frame\":"<<frame<<",\"tick_ms\":"<<GetTickCount64()<<",\"sampled_us\":"<<base::stamp()
       <<",\"session\":"<<s.session<<",\"input_sequence\":"<<s.last.queuedSequence
       <<",\"selector\":\""<<utility::pointer(s.last.selector)<<"\",\"action\":\""<<utility::pointer(s.last.action)
       <<"\",\"control\":\""<<utility::pointer(s.last.control)<<"\",\"device\":\""<<utility::pointer(s.last.device)
       <<"\",\"input_closed\":"<<s.closed<<",\"owned_button\":";
    if(s.closed)out<<"null";else out<<s.last.ownedButtonPressed;
    out<<",\"click_id\":"<<h.id<<",\"mode\":"<<h.mode<<",\"primary\":"<<h.primary
       <<",\"context\":"<<h.context<<",\"drag\":"<<h.drag<<",\"original_token\":"<<m.originalToken
       <<",\"current_token\":"<<base::token(view.context,view.current)
       <<",\"canonical_token\":"<<actors::confirmedToken(owner,{11,1,1})
       <<",\"current_ids\":"<<base::idsJson(currentIds)<<",\"preview_ids\":"<<base::idsJson(previewIds)
       <<",\"current_count\":"<<currentCount<<",\"preview_count\":"<<previewCount
       <<",\"casting_ids\":"<<base::idsJson(selection::selectionIds(ba::read<Obj>(selector,0x98)))
       <<",\"native_present\":"<<view.nativePresent<<",\"native_state\":";
    if(view.nativeValue)out<<*view.nativeValue;else out<<"null";
    out<<",\"current_admitted\":"<<view.context.admitted(view.current)<<",\"returned_serial\":"<<(returned?returned->ticket.serial:0)
       <<",\"returned_down\":"<<down<<",\"returned_up\":"<<up
       <<",\"ledger_completed\":"<<(returned&&returned->ledgerCompleted)
       <<",\"ledger_serial\":"<<(returned?returned->ledgerSerial:0)<<",\"pending_commands\":"<<base::pending(owner)
       <<",\"selection_writes\":0,\"history_writes\":0,\"physicalUI\":false}";
    ba::log("MOBILE HELD CLICK %s",out.str().c_str());
}
static void queue(actors::State& owner,Obj selector,int frame,bool held,const char* event) {
    auto& s=state();vm::queuePositionButton(s.x,s.y,held);s.queuedUpdate=s.update;record(owner,selector,frame,event);
}
static bool observed(Obj selector,bool held) {
    auto& s=state();s.last=vm::observe();const auto h=utility::history(selector);
    return s.update>s.queuedUpdate&&s.last.ownedButtonPressed==held&&h.primary==held&&!h.context&&!h.drag;
}
static void close(actors::State& owner,Obj selector,int frame,bool fresh) {
    auto& s=state();vm::ReleaseObservation release;release.pressedSnapshot=s.pressed;release.releasedSnapshot=s.last;
    release.pressUpdate=s.pressUpdate;release.releaseUpdate=s.update;vm::close(release);s.closed=true;
    record(owner,selector,frame,fresh?"fresh_input_closed":"input_closed");
}
static void beginPosition(actors::State& owner,Obj selector,int frame,bool fresh) {
    auto& s=state();base::View view(owner,selector);require(view.current&&view.context.admitted(view.current),"mobile held position source missing");
    releasedIdle(owner,selector,11);focus(owner,selector,view.current);
    const auto point=utility::project(owner,selector,view.current,11,1,1);s.x=point.first;s.y=point.second;
    if(fresh){vm::preflight(owner,selector);vm::begin(owner,selector);s.session=2;s.closed=false;}
    queue(owner,selector,frame,false,fresh?"fresh_position_queued":"position_queued");
}
static void tick() {
    auto& s=state();const auto world=worker::movementWorldId();const auto match=worker::movementMatchId();
    // A failed borrowed session remains failed. Teardown must not manufacture
    // an Up or obscure the first failure with repeated retirement errors.
    if(s.failed)return;
    if(!worker::movementEnabled()||!world||match.empty()) {
        if(s.world){require(!s.inputOpened||(s.complete&&s.closed),"mobile held retired an unfinished input episode");s=State{};base::state()=base::State{};}
        return;
    }
    if(s.world!=world||s.match!=match) {
        require(!s.world||!s.inputOpened||(s.complete&&s.closed),"mobile held world changed before real release");s=State{};s.world=world;s.match=match;
        base::state()=base::State{};base::state().world=world;base::state().match=match;
    }
    if(s.failed||s.complete)return;
    auto& owner=actors::state();if(owner.world!=world||owner.match!=match||!owner.manager||!owner.simulation)return;
    base::owned(owner);if(ba_lan::matchEnded)return;
    require(ba::flag(L"-prediction-mobile-correction-smoke")&&!held_click::enabled()&&!utility::enabled()&&
        !ba::flag(L"-prediction-actor-correction-smoke")&&
        !fixture_roles::mirrored()&&!base::groupIntentEnabled()&&!base::groupUserEditsEnabled()&&!base::recallEnabled()&&
        !base::focusEnabled()&&!base::focusNoStartEnabled()&&!base::focusRestartEnabled()&&
        !base::casterSurveyEnabled()&&!base::casterLifetimeEnabled()&&!base::uiCastEnabled()&&
        !base::recoveryStallEnabled(),"mobile held fixture scope differs");
    const int frame=ba::read<int>(owner.simulation->get(),0xac);auto& m=base::state();
    if(ba::lanSlot()==0) {
        if(!m.escapeQueued&&frame>=150){require(frame==150,"mobile held missed escape150");base::move(owner,selectorFor(owner),frame,10,base::original::Vec3{-32.f,0.f,0.f},false);}
        return;
    }
    require(ba::lanSlot()==1,"mobile held requires victim seat1");if(frame<130)return;
    Obj selector=selectorFor(owner);s.update=ordinal();require(s.update,"mobile held frontend ordinal missing");
    if(!s.stage) {
        require(frame==130,"mobile held missed setup130");base::setup(owner,selector,frame,releasedIdle);
        int group=4;void* args[]={&group};actors::invoke(actors::method(selector,"FocusControlGroupCancel",1,0x06002220,0x3bf2fa0),selector,args);
        require(ba::read<int>(selector,0xa0)==-1&&!ba::read<Obj>(selector,0xa8),"mobile held original focus cancel failed");
        utility::validateHistory(selector);const auto vector=actors::type("UnityEngine","Vector2");
        actors::clickField(selector,"_currentPointerPosition",0x14c,vector,8);actors::clickField(selector,"_pointerDownPosition",0x164,vector,8);
        vm::preflight(owner,selector);vm::begin(owner,selector);s.inputOpened=true;record(owner,selector,frame,"setup");s.stage=1;return;
    }
    if(s.stage==1){if(frame<148)return;require(frame==148,"mobile held missed position148");beginPosition(owner,selector,frame,false);s.stage=2;return;}
    if(s.stage==2||s.stage==9) {
        const bool fresh=s.stage==9;const int wanted=fresh?180:150;
        if(frame<wanted||s.update<=s.queuedUpdate)return;require(frame==wanted,"mobile held missed original Down queue frame");
        if(!observed(selector,false))return;
        if(utility::bits(ba::read<float>(selector,0x14c))!=utility::bits(s.x)||
           utility::bits(ba::read<float>(selector,0x150))!=utility::bits(s.y))return;
        if(fresh)base::snapshot(owner,selector,frame,"before_fresh_reselection");
        record(owner,selector,frame,fresh?"fresh_position_observed":"position_observed");
        queue(owner,selector,frame,true,fresh?"fresh_press_queued":"press_queued");s.stage=fresh?10:3;return;
    }
    if(s.stage==3||s.stage==10) {
        const bool fresh=s.stage==10;require(frame<=(fresh?181:151),"mobile held original Down was not consumed");
        if(!observed(selector,true))return;const auto h=utility::history(selector);
        require(h.id==11&&h.mode==1,"mobile held original Down did not establish Single11");
        require(utility::bits(ba::read<float>(selector,0x164))==utility::bits(s.x)&&
            utility::bits(ba::read<float>(selector,0x168))==utility::bits(s.y),"mobile held original Down position differs");
        s.pressed=s.last;s.pressUpdate=s.update;record(owner,selector,frame,fresh?"fresh_pressed":"pressed");s.stage=fresh?11:4;
    }
    if(s.stage==4){if(frame<152)return;require(frame==152,"mobile held missed checkpoint152");record(owner,selector,frame,"held_checkpoint");s.stage=5;return;}
    base::View view(owner,selector);
    if(m.firstRestored>=0&&!m.freshQueued&&frame>=168&&GetTickCount64()-m.lastPoseTick>=15) {
        require(m.currentActor&&view.current==m.currentActor->get()&&view.context.admitted(view.current)&&
            base::token(view.context,view.current)==m.currentToken,"mobile held baseline lost its admitted actor");
        base::pose(owner,base::original::actualPosition(owner,m.currentActor->get()),frame,true);
    }
    if(s.stage==5&&view.nativeValue&&*view.nativeValue==6) {
        require(frame==153,"mobile held native death boundary differs");m.firstDead=frame;
        base::snapshot(owner,selector,frame,"native_dead_observed");record(owner,selector,frame,"native_dead");s.stage=6;return;
    }
    if(s.stage==5){require(frame<=153,"mobile held missed native death153");return;}
    if(s.stage==6) {
        require(frame<=154,"mobile held missed original mobile release154");
        if(view.nativePresent||view.oldActive||view.oldRetained||view.oldComponent)return;
        m.firstReleased=frame;base::snapshot(owner,selector,frame,"original_mobile_release_observed");record(owner,selector,frame,"natural_release");
        // Native60 observed retained numeric IDs after physical removal. Do not
        // clear the original sets to manufacture a different input episode.
        // The strict file-only evaluator checks these observations and the
        // later original Up outcome after the natural lifecycle completes.
        if(s.world==2){queue(owner,selector,frame,false,"release_queued");s.releaseQueued=true;}s.stage=7;return;
    }
    if(s.stage==7) {
        if(m.firstRestored<0&&view.nativePresent&&view.nativeValue&&*view.nativeValue!=6&&view.current&&view.context.admitted(view.current)) {
            require(frame<=164&&base::token(view.context,view.current)==m.originalToken,"mobile held restored identity/token differs");
            m.currentActor=std::make_unique<Root>(view.current);m.currentToken=m.originalToken;m.firstRestored=frame;
            base::snapshot(owner,selector,frame,"original_mobile_restored_and_admitted");record(owner,selector,frame,"restored");
        }
        require(m.firstRestored>=0||frame<=164,"mobile held missed restoration164");
        if(s.world==1&&!s.releaseQueued&&frame>=165) {
            require(frame<=166&&m.firstRestored>=0,"mobile held late Up lacks restored actor");queue(owner,selector,frame,false,"release_queued");s.releaseQueued=true;return;
        }
        if(s.releaseQueued&&!s.closed&&observed(selector,false)) {
            require(frame<=(s.world==2?155:167),"mobile held original Up consumed late");
            require(s.world!=2||(!view.nativePresent&&!view.current),"mobile held absence Up arrived after restoration");
            record(owner,selector,frame,"released");close(owner,selector,frame,false);
        }
        if(s.closed&&m.firstRestored>=0)s.stage=8;return;
    }
    if(s.stage==8){if(frame<178)return;require(frame==178,"mobile held missed fresh position178");beginPosition(owner,selector,frame,true);s.stage=9;return;}
    if(s.stage==11){if(frame<182)return;require(frame==182,"mobile held missed fresh Up182");queue(owner,selector,frame,false,"fresh_release_queued");s.stage=12;return;}
    if(s.stage==12) {
        require(frame<=183,"mobile held fresh Up consumed late");if(!observed(selector,false))return;
        require(selection::selectionIds(ba::read<Obj>(selector,0x90))==std::vector<uint32_t>{11},"mobile held fresh input did not select restored11");
        base::snapshot(owner,selector,frame,"original_fresh_reselection_established");record(owner,selector,frame,"fresh_released");
        close(owner,selector,frame,true);s.stage=13;return;
    }
    if(s.stage==13) {
        if(frame<184)return;require(frame==184,"mobile held missed fresh Move184");const auto origin=base::original::actualPosition(owner,m.currentActor->get());
        base::pose(owner,origin,frame,true);base::move(owner,selector,frame,11,{origin.x+16.f,origin.y,origin.z},true,&origin,m.lastPoseUs,releasedIdle);
        record(owner,selector,frame,"fresh_move_queued");s.stage=14;return;
    }
    if(s.stage==14) {
        if(GetTickCount64()-m.lastPoseTick>=15)base::pose(owner,base::original::actualPosition(owner,m.currentActor->get()),frame,false);
        if(frame>=260){require(frame<=261&&s.closed,"mobile held completion lacks balanced input");base::snapshot(owner,selector,frame,"mobile_observation_complete");record(owner,selector,frame,"complete");m.passed=true;s.complete=true;s.stage=15;}
    }
}
}
