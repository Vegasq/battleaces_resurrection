#pragma once
// Owned diagnostic only: the original InputSystem callback creates and queues
// the fresh command. Observe its normal ToProto result; never serialize twice.
namespace context_move {
namespace vm=virtual_mouse;
namespace utility=expired_click;
namespace base=mobile;
namespace input=ba_prediction_input;
using Vec3=base::original::Vec3;
static bool enabled(){return ba::flag(L"-prediction-mobile-context-move-smoke");}
struct State {
    uint64_t world=0,sequence=0,callbackSequence=0,update=0,queuedUpdate=0,pressUpdate=0;
    uint64_t callbackStart=0,callbackEnd=0,originSampled=0,downSerial=0;
    std::string match,capturedClass;
    unsigned stage=0,session=0;
    float x=0,y=0;
    bool inputOpened=false,closed=true,complete=false,failed=false,hasPosition=false;
    bool downReturned=false,serialized=false,ground=false,commandQueued=false;
    int queueBefore=-1,queueAfter=-1,downFrame=-1;
    int32_t perspective=0;
    Vec3 origin{},requested{},target{};
    std::optional<base::MapPerspective> perspectiveProof;
    std::unique_ptr<Root> command;
    vm::Snapshot primary{},primaryPressed{};
    vm::ContextSnapshot context{},contextPressed{};
};
static State& state(){static State* value=new State;return *value;}
static uint64_t& ordinal(){static uint64_t value=0;return value;}
static void frontendUpdate(){require(ordinal()!=UINT64_MAX,"context Move frontend ordinal exhausted");++ordinal();}
static void markFailed(){state().failed=true;input::contextProbe=nullptr;}
static std::string pointer(Obj object){return object?"\""+utility::pointer(object)+"\"":"null";}
static std::string bits(const Vec3& point) {
    uint32_t value[3]{};std::memcpy(value,&point,sizeof(point));
    return "["+std::to_string(value[0])+","+std::to_string(value[1])+","+std::to_string(value[2])+"]";
}
static void sample() {
    auto& s=state();if(s.closed||!s.session)return;
    if(s.session==1)s.primary=vm::observe();else s.context=vm::observeContext();
}
static std::optional<input::ReturnedInput> returned(const std::optional<input::ReturnedInput>& value,
                                                   actors::State& owner,Obj selector) {
    if(value&&value->ticket.owner.world==owner.world&&value->ticket.owner.generation==owner.groupGeneration&&
        value->ticket.owner.selector==reinterpret_cast<uintptr_t>(selector)&&
        value->ticket.owner.manager==reinterpret_cast<uintptr_t>(owner.manager->get())&&
        value->ticket.owner.thread==GetCurrentThreadId())return value;
    return std::nullopt;
}
static void record(actors::State& owner,Obj selector,int frame,const char* event) {
    auto& s=state();auto& m=base::state();base::owned(owner);sample();
    base::View view(owner,selector);const auto h=utility::history(selector);
    const auto primary=returned(input::contextPrimaryReturnedInput,owner,selector);
    const auto context=returned(input::contextReturnedInput,owner,selector);
    Obj action=nullptr,control=nullptr,device=nullptr;uint64_t sequence=0;
    if(s.session==1){action=s.primary.action;control=s.primary.control;device=s.primary.device;sequence=s.primary.queuedSequence;}
    if(s.session==2){action=s.context.action;control=s.context.control;device=s.context.device;sequence=s.context.queuedSequence;}
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::boolalpha<<std::setprecision(9);
    out<<"{\"schema\":1,\"event\":\""<<event<<"\",\"sequence\":"<<++s.sequence
       <<",\"world\":"<<s.world<<",\"match\":\""<<s.match<<"\",\"frame\":"<<frame<<",\"ordinal\":"<<s.update
       <<",\"tick_ms\":"<<GetTickCount64()<<",\"sampled_us\":"<<base::stamp()
       <<",\"slot\":1,\"entity\":11,\"unit_type\":1,\"army\":1,\"original_token\":"<<m.originalToken
       <<",\"session\":"<<s.session<<",\"input_sequence\":"<<sequence<<",\"input_closed\":"<<s.closed
       <<",\"selector\":"<<pointer(selector)<<",\"action\":"<<pointer(action)<<",\"control\":"<<pointer(control)<<",\"device\":"<<pointer(device)
       <<",\"primary\":"<<h.primary<<",\"context\":"<<h.context<<",\"drag\":"<<h.drag<<",\"owned_primary\":";
    if(s.closed||!s.session)out<<"null";else out<<(s.session==1?s.primary.ownedButtonPressed:s.context.ownedPrimaryPressed);
    out<<",\"owned_context\":";
    if(s.closed||!s.session)out<<"null";
    else if(s.session==2)out<<s.context.ownedContextPressed;
    else out<<vm::originalBoolean(vm::api().isPressed,vm::session().controls[2]->get());
    out<<",\"current_ids\":"<<base::idsJson(selection::selectionIds(ba::read<Obj>(selector,0x90)))
       <<",\"preview_ids\":"<<base::idsJson(selection::selectionIds(ba::read<Obj>(selector,0x88)))
       <<",\"casting_ids\":"<<base::idsJson(selection::selectionIds(ba::read<Obj>(selector,0x98)))
       <<",\"active_caster\":"<<pointer(ba::read<Obj>(selector,0x100))
       <<",\"current_token\":"<<base::token(view.context,view.current)<<",\"canonical_token\":"<<actors::confirmedToken(owner,{11,1,1})
       <<",\"native_present\":"<<view.nativePresent<<",\"native_state\":";
    if(view.nativeValue)out<<*view.nativeValue;else out<<"null";
    out<<",\"current_admitted\":"<<view.context.admitted(view.current)<<",\"last_click_id\":"<<h.id<<",\"click_mode\":"<<h.mode
       <<",\"primary_return_serial\":"<<(primary?primary->ticket.serial:0)
       <<",\"primary_return_down\":"<<(primary&&primary->ticket.kind==input::Kind::Down)
       <<",\"primary_return_up\":"<<(primary&&primary->ticket.kind==input::Kind::Up)
       <<",\"context_return_serial\":"<<(context?context->ticket.serial:0)
       <<",\"context_return_down\":"<<(context&&context->ticket.kind==input::Kind::ContextDown)
       <<",\"context_return_up\":"<<(context&&context->ticket.kind==input::Kind::ContextUp)
       <<",\"pending_commands\":"<<base::pending(owner)<<",\"screen_position\":["<<ba::read<float>(selector,0x14c)<<','<<ba::read<float>(selector,0x150)
       <<"],\"queued_screen_position\":";
    if(s.hasPosition)out<<'['<<s.x<<','<<s.y<<']';else out<<"null";
    out<<",\"selection_writes\":0,\"history_writes\":0,\"physicalUI\":false}";
    ba::log("CONTEXT INPUT %s",out.str().c_str());
}
static void capture(actors::State& owner,Obj selector) {
    auto& s=state();if(s.queueBefore!=0||s.queueAfter!=1)return;
    {
        ba_local::QueueLock lock;Obj queue=ba::read<Obj>(ba_local::server(),0x180);
        require(ba_local::count(queue)==1,"context callback command queue changed before read-only Peek");
        s.command=std::make_unique<Root>(ba::call(queue,"Peek"));
    }
    require(s.command->get(),"context callback queued a null ICommand");
    const auto klass=ba::klass(s.command->get());
    const char* space=ba::api<const char*(*)(Obj)>("il2cpp_class_get_namespace")(klass);
    const char* name=ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(klass);
    require(space&&name&&strlen(space)<256&&strlen(name)<256,"context command class name differs");
    s.capturedClass=std::string(space)+"."+name;
    s.ground=klass==actors::type("Uncapped","ExecuteTargetGroundCommand");if(!s.ground)return;
    Obj command=s.command->get();actors::field(command,"<Position>k__BackingField",0x18);
    actors::field(command,"<Queued>k__BackingField",0x24);actors::field(command,"_mapPerspective",0x28);
    actors::clickField(command,"<Position>k__BackingField",0x18,actors::type("UnityEngine","Vector3"),12);
    actors::clickField(command,"<Queued>k__BackingField",0x24,actors::type("System","Boolean"),1);
    s.target=ba::read<Vec3>(command,0x18);base::original::finite(s.target);
    const auto queued=ba::read<uint8_t>(command,0x24);require(queued<=1,"context command queued Boolean differs");s.commandQueued=queued!=0;
    s.perspective=ba::read<int32_t>(command,0x28);
    // Metadata only: never allocate/invoke this constructor or enumerate its
    // lazy groups. Normal ToProto owns the single enumeration/serialization.
    Obj constructor=actors::method(command,".ctor",4,0x060000e6,0x37ae080);
    s.perspectiveProof=base::currentPerspective(owner,selector,constructor);
}
static void order() {
    auto& s=state();if(!s.ground)return;
    const auto text=base::common("original_context_move",s.downFrame,11,1,base::state().currentToken)+
        ",\"slot\":1,\"sampled_us\":"+std::to_string(s.callbackStart)+",\"origin_sampled_us\":"+std::to_string(s.originSampled)+
        ",\"enqueue_sampled_us\":"+std::to_string(s.callbackEnd)+",\"origin\":"+base::original::pointJson(s.origin)+
        ",\"target\":"+base::original::pointJson(s.target)+",\"target_bits\":"+bits(s.target)+
        ",\"requested_target\":"+base::original::pointJson(s.requested)+",\"command\":"+pointer(s.command->get())+
        ",\"command_class\":\"Uncapped.ExecuteTargetGroundCommand\",\"queued\":"+(s.commandQueued?"true":"false")+
        ",\"originalCtor\":false,\"original_callback\":\"Uncapped.UnitSelector.OnPlayerPointerContextDown\",\"queue_before\":"+
        std::to_string(s.queueBefore)+",\"queue_after\":"+std::to_string(s.queueAfter)+",\"queueDelta\":"+
        std::to_string(s.queueAfter-s.queueBefore)+s.perspectiveProof->json()+",\"physicalUI\":false}";
    ba::log("CONTEXT ORDER %s",text.c_str());
}
static void probe(bool before,const ba_prediction_input_observer::Ticket& ticket,Obj selector,bool completed,uint64_t ledgerSerial) {
    auto& s=state();auto& owner=actors::state();base::owned(owner);
    require(!s.failed&&!s.complete&&s.session==2&&!s.closed&&ticket.owner==input::owner(selector),
        "context callback lost its borrowed session owner");
    const bool down=ticket.kind==input::Kind::ContextDown;
    require(down||ticket.kind==input::Kind::ContextUp,"context probe saw another callback kind");
    require(s.callbackSequence==(down?(before?0u:1u):(before?2u:3u)),"context callback order differs");
    const int frame=ba::read<int>(owner.simulation->get(),0xac);
    if(before&&down) {
        require(frame>=186&&frame<=187,"context original Down frame differs");
        base::View view(owner,selector);require(base::state().currentActor&&view.current==base::state().currentActor->get()&&
            view.context.admitted(view.current)&&base::token(view.context,view.current)==base::state().currentToken,
            "context original Down lost its admitted current actor");
        s.origin=base::original::actualPosition(owner,base::state().currentActor->get());base::pose(owner,s.origin,frame,true);
        s.originSampled=base::state().lastPoseUs;s.queueBefore=base::pending(owner);s.downFrame=frame;s.downSerial=ticket.serial;
    }
    const auto sampled=base::stamp();
    if(down&&before)s.callbackStart=sampled;
    if(down&&!before){s.callbackEnd=sampled;s.queueAfter=base::pending(owner);capture(owner,selector);s.downReturned=true;
        base::state().freshQueued=true;base::state().freshFrame=frame;}
    sample();const auto h=utility::history(selector);
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::boolalpha;
    out<<"{\"schema\":1,\"event\":\""<<(before?"before":"returned")<<"\",\"sequence\":"<<++s.callbackSequence
       <<",\"world\":"<<s.world<<",\"match\":\""<<s.match<<"\",\"generation\":"<<owner.groupGeneration
       <<",\"selector\":"<<pointer(selector)<<",\"manager\":"<<pointer(owner.manager->get())<<",\"server\":"<<pointer(ba_local::server())
       <<",\"simulation\":"<<pointer(owner.simulation->get())<<",\"thread\":"<<GetCurrentThreadId()
       <<",\"kind\":\""<<(down?"ContextDown":"ContextUp")<<"\",\"ticket_serial\":"<<ticket.serial
       <<",\"frame\":"<<frame<<",\"tick_ms\":"<<GetTickCount64()<<",\"sampled_us\":"<<sampled<<",\"ledger_completed\":";
    if(before)out<<"null";else out<<completed;
    out<<",\"ledger_serial\":"<<ledgerSerial<<",\"primary\":"<<h.primary<<",\"context\":"<<h.context<<",\"drag\":"<<h.drag
       <<",\"owned_primary\":"<<s.context.ownedPrimaryPressed<<",\"owned_context\":"<<s.context.ownedContextPressed
       <<",\"pending_commands\":"<<base::pending(owner)<<",\"captured_command\":"<<pointer(s.command?s.command->get():nullptr)<<",\"captured_class\":";
    if(s.command)out<<std::quoted(s.capturedClass);else out<<"null";
    out<<",\"target\":"<<(s.ground?base::original::pointJson(s.target):"null")<<",\"target_bits\":"<<(s.ground?bits(s.target):"null")<<",\"queued\":";
    if(s.ground)out<<s.commandQueued;else out<<"null";
    out<<",\"map_perspective\":";if(s.ground)out<<s.perspective;else out<<"null";
    out<<",\"physicalUI\":false}";ba::log("CONTEXT CALLBACK %s",out.str().c_str());
    if(down&&!before)order();
}
static void serialized(Obj command,Obj action,uint64_t sequence,int sourceNextFrame) {
    auto& s=state();if(!s.command||s.command->get()!=command)return;
    auto& owner=actors::state();base::owned(owner);
    require(!s.failed&&s.downReturned&&!s.serialized&&action&&s.downSerial&&base::stamp()>s.callbackEnd,
        "context normal ToProto witness is duplicated, early or lacks a returned callback");
    Obj selector=selectorFor(owner);require(input::owner(selector).world==s.world,"context serializer owner changed");
    std::ostringstream out;out<<"{\"schema\":1,\"world\":"<<s.world<<",\"match\":\""<<s.match
       <<"\",\"generation\":"<<owner.groupGeneration<<",\"selector\":"<<pointer(selector)<<",\"manager\":"<<pointer(owner.manager->get())
       <<",\"thread\":"<<GetCurrentThreadId()<<",\"callback_serial\":"<<s.downSerial
       <<",\"frame\":"<<ba::read<int>(owner.simulation->get(),0xac)<<",\"source_next_frame\":"<<sourceNextFrame<<",\"sequence\":"<<sequence
       <<",\"command\":"<<pointer(command)<<",\"action\":"<<pointer(action)<<",\"tick_ms\":"<<GetTickCount64()
       <<",\"sampled_us\":"<<base::stamp()<<",\"physicalUI\":false}";
    ba::log("CONTEXT SERIALIZED %s",out.str().c_str());s.serialized=true;
}
static void queue(actors::State& owner,Obj selector,int frame,bool held,const char* event) {
    auto& s=state();if(s.session==1)vm::queuePositionButton(s.x,s.y,held);else vm::queueContextPositionButton(s.x,s.y,held);
    s.queuedUpdate=s.update;record(owner,selector,frame,event);
}
static bool observed(Obj selector,bool held) {
    auto& s=state();sample();const auto h=utility::history(selector);
    if(s.update<=s.queuedUpdate||h.drag)return false;
    return s.session==1?(s.primary.ownedButtonPressed==held&&h.primary==held&&!h.context):
        (!s.context.ownedPrimaryPressed&&!h.primary&&s.context.ownedContextPressed==held&&h.context==held);
}
static bool positionObserved(Obj selector) {
    auto& s=state();return observed(selector,false)&&utility::bits(ba::read<float>(selector,0x14c))==utility::bits(s.x)&&
        utility::bits(ba::read<float>(selector,0x150))==utility::bits(s.y);
}
static void tick() {
    auto& s=state();const auto world=worker::movementWorldId();const auto match=worker::movementMatchId();
    if(s.failed)return;
    if(!worker::movementEnabled()||!world||match.empty()) {
        if(s.world){require(!s.inputOpened||(s.complete&&s.closed),"context Move retired an unfinished input session");
            input::contextProbe=nullptr;s=State{};base::state()=base::State{};}return;
    }
    if(s.world!=world||s.match!=match) {
        require(!s.world||!s.inputOpened||(s.complete&&s.closed),"context Move changed world before real release");
        input::contextProbe=nullptr;s=State{};s.world=world;s.match=match;
        base::state()=base::State{};base::state().world=world;base::state().match=match;
    }
    if(s.complete)return;
    auto& owner=actors::state();if(owner.world!=world||owner.match!=match||!owner.manager||!owner.simulation)return;
    base::owned(owner);if(ba_lan::matchEnded)return;
    require(ba::flag(L"-prediction-mobile-correction-smoke")&&!held_click::enabled()&&!utility::enabled()&&!mobile_held::enabled()&&
        !ba::flag(L"-prediction-actor-correction-smoke")&&!fixture_roles::mirrored()&&!base::groupIntentEnabled()&&
        !base::groupUserEditsEnabled()&&!base::recallEnabled()&&!base::focusEnabled()&&!base::focusNoStartEnabled()&&
        !base::focusRestartEnabled()&&!base::casterSurveyEnabled()&&!base::casterLifetimeEnabled()&&!base::uiCastEnabled()&&
        !base::recoveryStallEnabled(),"context Move fixture scope differs");
    const int frame=ba::read<int>(owner.simulation->get(),0xac);auto& m=base::state();
    if(ba::lanSlot()==0) {
        if(!m.escapeQueued&&frame>=150){require(frame==150,"context Move missed independent escape150");
            base::move(owner,selectorFor(owner),frame,10,Vec3{-32.f,0.f,0.f},false);}return;
    }
    require(ba::lanSlot()==1,"context Move victim seat differs");if(frame<130)return;
    Obj selector=selectorFor(owner);s.update=ordinal();require(s.update,"context Move frontend ordinal missing");
    if(!s.stage) {
        require(frame==130,"context Move missed setup130");base::setup(owner,selector,frame,mobile_held::releasedIdle);
        int group=4;void* args[]={&group};actors::invoke(actors::method(selector,"FocusControlGroupCancel",1,0x06002220,0x3bf2fa0),selector,args);
        require(ba::read<int>(selector,0xa0)==-1&&!ba::read<Obj>(selector,0xa8),"context Move original focus cancellation failed");
        utility::validateHistory(selector);const auto vector=actors::type("UnityEngine","Vector2");
        actors::clickField(selector,"_currentPointerPosition",0x14c,vector,8);actors::clickField(selector,"_pointerDownPosition",0x164,vector,8);
        input::contextPrimaryReturnedInput.reset();input::contextReturnedInput.reset();
        record(owner,selector,frame,"setup");s.stage=1;return;
    }
    base::View view(owner,selector);
    if(m.firstRestored>=0&&!m.freshQueued&&frame>=168&&GetTickCount64()-m.lastPoseTick>=15) {
        require(m.currentActor&&view.current==m.currentActor->get()&&view.context.admitted(view.current)&&
            base::token(view.context,view.current)==m.currentToken,"context Move baseline lost current admission");
        base::pose(owner,base::original::actualPosition(owner,m.currentActor->get()),frame,true);
    }
    // Keep observing while right input is held/releasing. Waiting until the
    // session closed would hide the first response behind several native ticks.
    if(m.freshQueued&&s.stage<=14&&GetTickCount64()-m.lastPoseTick>=15) {
        require(m.currentActor&&view.current==m.currentActor->get()&&view.context.admitted(view.current)&&
            base::token(view.context,view.current)==m.currentToken,"context Move response lost current admission");
        base::pose(owner,base::original::actualPosition(owner,m.currentActor->get()),frame,false);
    }
    if(s.stage==1) {
        require(frame<=153,"context Move missed native death153");if(!view.nativeValue||*view.nativeValue!=6)return;
        require(frame==153,"context Move native death frame differs");m.firstDead=frame;
        base::snapshot(owner,selector,frame,"native_dead_observed");record(owner,selector,frame,"native_dead");s.stage=2;return;
    }
    if(s.stage==2) {
        require(frame<=154,"context Move missed physical release154");if(view.nativePresent||view.oldActive||view.oldRetained||view.oldComponent)return;
        m.firstReleased=frame;base::snapshot(owner,selector,frame,"original_mobile_release_observed");
        record(owner,selector,frame,"natural_release");s.stage=3;return;
    }
    if(s.stage==3) {
        require(frame<=164,"context Move missed restoration164");
        if(!view.nativePresent||!view.nativeValue||*view.nativeValue==6||!view.current||!view.context.admitted(view.current))return;
        require(base::token(view.context,view.current)==m.originalToken,"context Move restored incarnation differs");
        m.currentActor=std::make_unique<Root>(view.current);m.currentToken=m.originalToken;m.firstRestored=frame;
        base::snapshot(owner,selector,frame,"original_mobile_restored_and_admitted");record(owner,selector,frame,"restored");s.stage=4;return;
    }
    if(s.stage==4) {
        if(frame<178)return;require(frame==178,"context Move missed primary position178");
        mobile_held::releasedIdle(owner,selector,11);mobile_held::focus(owner,selector,m.currentActor->get());
        const auto point=utility::project(owner,selector,m.currentActor->get(),11,1,1);s.x=point.first;s.y=point.second;s.hasPosition=true;
        vm::preflight(owner,selector);vm::begin(owner,selector);s.inputOpened=true;s.closed=false;s.session=1;
        queue(owner,selector,frame,false,"primary_position_queued");s.stage=5;return;
    }
    if(s.stage==5) {
        if(frame<180)return;require(frame==180,"context Move missed primary Down180");if(!positionObserved(selector))return;
        record(owner,selector,frame,"primary_position_observed");
        base::snapshot(owner,selector,frame,"before_fresh_reselection");queue(owner,selector,frame,true,"primary_down_queued");s.stage=6;return;
    }
    if(s.stage==6) {
        require(frame<=181,"context Move primary Down not consumed");if(!observed(selector,true))return;
        const auto h=utility::history(selector);require(h.id==11&&h.mode==1,"context Move primary Down did not establish Single11");
        require(utility::bits(ba::read<float>(selector,0x164))==utility::bits(s.x)&&
            utility::bits(ba::read<float>(selector,0x168))==utility::bits(s.y),"context Move original primary Down hit position differs");
        s.primaryPressed=s.primary;s.pressUpdate=s.update;record(owner,selector,frame,"primary_down_observed");s.stage=7;return;
    }
    if(s.stage==7) {
        if(frame<182)return;require(frame==182,"context Move missed primary Up182");queue(owner,selector,frame,false,"primary_up_queued");s.stage=8;return;
    }
    if(s.stage==8) {
        require(frame<=183,"context Move primary Up not consumed");if(!observed(selector,false))return;
        require(selection::selectionIds(ba::read<Obj>(selector,0x90))==std::vector<uint32_t>{11},"context Move original primary did not reselect11");
        base::snapshot(owner,selector,frame,"original_fresh_reselection_established");record(owner,selector,frame,"primary_up_observed");
        vm::ReleaseObservation release{s.primaryPressed,s.primary,s.pressUpdate,s.update};vm::close(release);s.closed=true;
        record(owner,selector,frame,"primary_closed");s.stage=9;return;
    }
    if(s.stage==9) {
        if(frame<184)return;require(frame==184,"context Move missed context position184");mobile_held::releasedIdle(owner,selector,11);
        require(mobile_held::resolvableCount(ba::read<Obj>(selector,0x90))==1,"context Move selection is not resolvable11");
        const auto origin=base::original::actualPosition(owner,m.currentActor->get());s.requested={origin.x+16.f,origin.y,origin.z};
        const float point[]={s.requested.x,s.requested.y,s.requested.z};const auto screen=utility::project(owner,selector,m.currentActor->get(),11,1,1,point);
        s.x=screen.first;s.y=screen.second;vm::preflight(owner,selector);vm::beginContext(owner,selector);s.session=2;s.closed=false;
        input::contextProbe=&probe;queue(owner,selector,frame,false,"context_position_queued");s.stage=10;return;
    }
    if(s.stage==10) {
        if(frame<186)return;require(frame==186,"context Move missed context Down186");if(!positionObserved(selector))return;
        require(!ba::read<Obj>(selector,0x100),"context Move begins with an active ability caster");
        record(owner,selector,frame,"context_position_observed");queue(owner,selector,frame,true,"context_down_queued");s.stage=11;return;
    }
    if(s.stage==11) {
        require(frame<=187,"context Move original right Down not consumed");if(!observed(selector,true))return;
        s.contextPressed=s.context;s.pressUpdate=s.update;record(owner,selector,frame,"context_down_observed");s.stage=12;return;
    }
    if(s.stage==12) {
        require(frame<=189,"context Move missed later original right Up");if(s.update<=s.pressUpdate)return;
        queue(owner,selector,frame,false,"context_up_queued");s.stage=13;return;
    }
    if(s.stage==13) {
        require(frame<=190,"context Move original right Up not consumed");if(!observed(selector,false))return;
        record(owner,selector,frame,"context_up_observed");
        vm::ContextReleaseObservation release{s.contextPressed,s.context,s.pressUpdate,s.update};vm::closeContext(release);s.closed=true;
        record(owner,selector,frame,"context_closed");input::contextProbe=nullptr;s.stage=14;return;
    }
    if(s.stage==14) {
        if(frame>=260){require(frame<=261&&s.closed,"context Move completion lacks balanced real input");
            base::snapshot(owner,selector,frame,"mobile_observation_complete");record(owner,selector,frame,"complete");
            m.passed=true;s.complete=true;s.stage=15;}
    }
}
}
