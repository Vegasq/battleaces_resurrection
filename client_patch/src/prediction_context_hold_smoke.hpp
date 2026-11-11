#pragma once
// Owned original UI-button diagnostic; it is not physical keyboard input.
// The original instant caster creates the command; normal ToProto runs once.
namespace context_hold {
namespace base=mobile;
namespace survey=mobile::caster_survey;
namespace life=mobile::caster_lifetime;
namespace utility=expired_click;
static bool originalOnly(){return ba::flag(L"-prediction-mobile-original-hold-smoke");}
static bool enabled(){return ba::flag(L"-prediction-mobile-context-hold-smoke")||originalOnly();}
static void originalScope() {
    require(originalOnly()&&ba::flag(L"-prediction-mobile-correction-smoke")&&!context_move::enabled()&&
        !ba::flag(L"-prediction-mobile-context-hold-smoke")&&!mobile_held::enabled()&&!held_click::enabled()&&
        !utility::enabled()&&!ba::flag(L"-prediction-actor-correction-smoke")&&!fixture_roles::mirrored()&&
        !base::groupIntentEnabled()&&!base::groupUserEditsEnabled()&&!base::recallEnabled()&&!base::focusEnabled()&&
        !base::focusNoStartEnabled()&&!base::focusRestartEnabled()&&!base::casterSurveyEnabled()&&
        !base::casterLifetimeEnabled()&&!base::uiCastEnabled()&&!base::recoveryStallEnabled(),
        "original Hold requires its separate base mobile fixture");
}
struct State {
    uint64_t world=0,serial=0,sequence=0;
    std::string match,commandClass;
    std::unique_ptr<life::Mapping> mapping;
    std::unique_ptr<Root> activation,source,mapped,group,command;
    int activationType=0,activationCount=0;
    unsigned performCalls=0;
    bool fromHotkey=false,held=false,instant=false,queued=false,serialized=false,complete=false,failed=false;
};
static State& state(){static State* value=new State;return *value;}
static uint64_t& activationSerial(){static uint64_t value=0;return value;}
static void markFailed(){state().failed=true;}
static void guard(actors::State& owner,Obj selector) {
    base::owned(owner);auto& s=state();auto& m=base::state();base::View view(owner,selector);
    require(s.world==owner.world&&s.match==owner.match&&s.mapping&&s.source&&s.mapped&&s.group&&
        ba::read<Obj>(selector,0x90)==s.source->get()&&ba::read<Obj>(selector,0xc8)==s.mapping->panel->get()&&
        ba::read<Obj>(s.mapping->button->get(),0xb0)==s.mapped->get()&&
        ba::read<Obj>(s.mapping->button->get(),0xb8)==s.group->get()&&m.currentActor&&view.current==m.currentActor->get()&&
        view.context.admitted(view.current)&&base::token(view.context,view.current)==m.currentToken&&
        actors::confirmedToken(owner,{11,1,1})==m.currentToken&&view.nativePresent&&view.nativeValue&&
        *view.nativeValue!=6&&*view.nativeValue!=9&&ba::read<Obj>(view.current,0x158)&&!ba::read<bool>(view.current,0x160),
        "context Hold lost its original mapping/current admitted actor");
    if(originalOnly()) {
        originalScope();require(m.freshQueued&&m.freshFrame>=180&&m.freshFrame<198,
            "original Hold lacks its separately proven scripted Move setup");
    } else require(context_move::state().world==s.world&&context_move::state().session==2&&context_move::state().closed&&
        context_move::state().callbackSequence==4&&context_move::state().serialized,
        "context Hold lacks the actual completed right-click Move session");
}
static void record(actors::State& owner,Obj selector,int frame,const char* event) {
    guard(owner,selector);auto& s=state();auto& m=base::state();
    const auto position=base::original::actualPosition(owner,m.currentActor->get());base::pose(owner,position,frame,false);
    const auto positionUs=m.lastPoseUs;const auto h=utility::history(selector);
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::boolalpha;
    out<<"{\"schema\":1,\"event\":\""<<event<<"\",\"sequence\":"<<++s.sequence
       <<",\"world\":"<<s.world<<",\"match\":\""<<s.match<<"\",\"generation\":"<<owner.groupGeneration
       <<",\"selector\":"<<context_move::pointer(selector)<<",\"manager\":"<<context_move::pointer(owner.manager->get())
       <<",\"simulation\":"<<context_move::pointer(owner.simulation->get())<<",\"server\":"<<context_move::pointer(ba_local::server())
       <<",\"thread\":"<<GetCurrentThreadId()<<",\"frame\":"<<frame<<",\"tick_ms\":"<<GetTickCount64()
       <<",\"sampled_us\":"<<base::stamp()<<",\"slot\":1,\"entity\":11,\"unit_type\":1,\"army\":1"
       <<",\"incarnation\":"<<m.currentToken<<",\"current_token\":"<<m.currentToken<<",\"canonical_token\":"<<actors::confirmedToken(owner,{11,1,1})
       <<",\"actor\":"<<context_move::pointer(m.currentActor->get())<<",\"button\":"<<context_move::pointer(s.mapping->button->get())
       <<",\"panel\":"<<context_move::pointer(s.mapping->panel->get())<<",\"source_set\":"<<context_move::pointer(s.source->get())
       <<",\"mapped_set\":"<<context_move::pointer(s.mapped->get())<<",\"group\":"<<context_move::pointer(s.group->get())
       <<",\"activation\":"<<context_move::pointer(s.activation->get())<<",\"activation_serial\":"<<s.serial<<",\"mapping\":";
    s.mapping->row.json(out);
    out<<",\"activation_type\":"<<s.activationType<<",\"activation_count\":"<<s.activationCount<<",\"from_hotkey\":"<<s.fromHotkey
       <<",\"held\":"<<s.held<<",\"perform_calls\":"<<s.performCalls<<",\"pending_commands\":"<<base::pending(owner)
       <<",\"command\":"<<context_move::pointer(s.command?s.command->get():nullptr)<<",\"command_class\":";
    if(s.command)out<<ba_catalog::quote(s.commandClass);else out<<"null";
    out<<",\"queued\":";if(s.instant)out<<s.queued;else out<<"null";
    out<<",\"primary\":"<<h.primary<<",\"context\":"<<h.context<<",\"drag\":"<<h.drag
       <<",\"active_caster\":"<<context_move::pointer(ba::read<Obj>(selector,0x100))
       <<",\"casting_ids\":"<<base::idsJson(selection::selectionIds(ba::read<Obj>(selector,0x98)))
       <<",\"current_ids\":"<<base::idsJson(selection::selectionIds(s.source->get()))
       <<",\"preview_ids\":"<<base::idsJson(selection::selectionIds(ba::read<Obj>(selector,0x88)))
       <<",\"current_count\":"<<survey::count(owner,s.source->get())<<",\"position\":"<<base::original::pointJson(position)
       <<",\"position_sampled_us\":"<<positionUs<<",\"context_input_closed\":";
    if(originalOnly())out<<"null";else out<<context_move::state().closed;
    out<<",\"move_command\":"<<(originalOnly()?"null":context_move::pointer(context_move::state().command?context_move::state().command->get():nullptr))
       <<",\"originalCtor\":false,\"original_callback\":\"Uncapped.AbilityButtonAction.PerformButtonAction\""
       <<",\"selection_writes\":0,\"history_writes\":0,\"physicalUI\":false}";
    ba::log("CONTEXT HOLD %s",out.str().c_str());
}
static void activate(actors::State& owner,Obj selector,int frame) {
    auto& s=state();require(frame==198&&!s.performCalls&&!s.mapping,"context Hold activation must be once at198");
    mobile_held::releasedIdle(owner,selector,11);
    s.mapping=std::make_unique<life::Mapping>(life::findMapping(owner,selector,5,14,2,0));
    s.source=std::make_unique<Root>(ba::read<Obj>(selector,0x90));
    s.mapped=std::make_unique<Root>(ba::read<Obj>(s.mapping->button->get(),0xb0));
    s.group=std::make_unique<Root>(ba::read<Obj>(s.mapping->button->get(),0xb8));
    Obj klass=actors::type("Uncapped","ButtonActivationInfo");
    Obj hotkey=virtual_mouse::exact(klass,"get_HotkeyActivation",0x060015c2,0,0x3e9b750);
    base::FocusObservation::signature(hotkey,true,klass);
    actors::guard(0x3e9b750,"\x48\x83\xec\x28\x80\x3d\x05\xec\xfb\x02\x00\x75\x18\x48\x8d\x0d",16);
    s.activation=std::make_unique<Root>(actors::invoke(hotkey,nullptr));actors::classIs(s.activation->get(),"Uncapped","ButtonActivationInfo");
    Obj activationType=survey::fieldType(s.activation->get(),"<Type>k__BackingField",0x10,actors::type("Uncapped","ButtonActivationType"));
    require(ba::api<bool(*)(Obj)>("il2cpp_class_is_enum")(activationType),"context Hold activation type is not original enum");
    base::original::checkValue(activationType,4,"context Hold activation enum ABI differs");
    survey::reference(s.activation->get(),"<Count>k__BackingField",0x14,"System","Int32");
    Obj from=life::method(s.activation->get(),"get_IsFromHotKey",0,0x060015bf,0x3624090,actors::type("System","Boolean"),
        "\x0f\xb6\x41\x10\x24\x01\xc3\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc");
    Obj held=life::method(s.activation->get(),"get_IsHeld",0,0x060015c0,0x3e9b6f0,actors::type("System","Boolean"),
        "\x8b\x41\x10\xd1\xe8\x24\x01\xc3\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc");
    s.activationType=ba::read<int32_t>(s.activation->get(),0x10);s.activationCount=ba::read<int32_t>(s.activation->get(),0x14);
    auto fromValue=survey::read(owner,from,s.activation->get());auto heldValue=survey::read(owner,held,s.activation->get());
    s.fromHotkey=survey::scalar<bool>(fromValue.get(),actors::type("System","Boolean"));
    s.held=survey::scalar<bool>(heldValue.get(),actors::type("System","Boolean"));
    require(s.activationType==1&&s.activationCount==1&&s.fromHotkey&&!s.held,"context Hold original activation values differ");
    require(activationSerial()!=UINT64_MAX,"context Hold activation serial exhausted");s.serial=++activationSerial();
    guard(owner,selector);record(owner,selector,frame,"before");
    Obj perform=life::method(s.mapping->button->get(),"PerformButtonAction",1,0x060016ac,0x3eb0c00,actors::type("System","Void"),
        "\x48\x89\x5c\x24\x08\x57\x48\x83\xec\x30\x80\x3d\x0b\x98\xfa\x02");
    require(base::original::parameterClass(perform,0)==klass,"context Hold original Perform parameter differs");
    void* args[]={s.activation->get()};++s.performCalls;actors::invoke(perform,s.mapping->button->get(),args);guard(owner,selector);
    if(base::pending(owner)==1) {
        {ba_local::QueueLock lock;Obj queue=ba::read<Obj>(ba_local::server(),0x180);
            require(ba_local::count(queue)==1,"context Hold queue changed before original Peek");s.command=std::make_unique<Root>(ba::call(queue,"Peek"));}
        require(s.command->get(),"context Hold original command is null");s.commandClass=survey::className(s.command->get());
        s.instant=ba::klass(s.command->get())==actors::type("Uncapped","ExecuteInstantCommand");
        if(s.instant) {
            Obj queued=actors::method(s.command->get(),"get_Queued",0,0x060000e0,0x981980);
            base::FocusObservation::signature(queued,false,actors::type("System","Boolean"));
            auto value=survey::read(owner,queued,s.command->get());s.queued=survey::scalar<bool>(value.get(),actors::type("System","Boolean"));
        }
    }
    // A normal no-command/wrong-command branch is retained for the final gate;
    // never construct a replacement command or fabricate another activation.
    record(owner,selector,frame,"returned");
}
static void serialized(Obj command,Obj action,uint64_t sequence,int sourceNextFrame) {
    auto& s=state();if(!s.command||s.command->get()!=command)return;
    auto& owner=actors::state();Obj selector=selectorFor(owner);guard(owner,selector);
    require(!s.failed&&s.performCalls==1&&s.sequence>=2&&!s.serialized&&action,"context Hold normal serialization duplicated or early");
    std::ostringstream out;out<<"{\"schema\":1,\"world\":"<<s.world<<",\"match\":\""<<s.match
       <<"\",\"generation\":"<<owner.groupGeneration<<",\"selector\":"<<context_move::pointer(selector)
       <<",\"manager\":"<<context_move::pointer(owner.manager->get())<<",\"thread\":"<<GetCurrentThreadId()
       <<",\"activation_serial\":"<<s.serial<<",\"frame\":"<<ba::read<int>(owner.simulation->get(),0xac)
       <<",\"source_next_frame\":"<<sourceNextFrame<<",\"sequence\":"<<sequence<<",\"command\":"<<context_move::pointer(command)
       <<",\"action\":"<<context_move::pointer(action)<<",\"tick_ms\":"<<GetTickCount64()<<",\"sampled_us\":"<<base::stamp()<<",\"physicalUI\":false}";
    ba::log("CONTEXT HOLD SERIALIZED %s",out.str().c_str());s.serialized=true;
}
static void tick() {
    auto& s=state();if(s.failed)return;
    if(originalOnly())originalScope();
    else require(context_move::enabled()&&ba::flag(L"-prediction-mobile-correction-smoke"),"context Hold requires original context Move fixture");
    const auto world=worker::movementWorldId();const auto match=worker::movementMatchId();
    if(!worker::movementEnabled()||!world||match.empty()) {
        if(s.world){require(!s.performCalls||s.complete,"context Hold retired unfinished");s=State{};}return;
    }
    if(s.world!=world||s.match!=match) {
        require(!s.world||!s.performCalls||s.complete,"context Hold changed world unfinished");s=State{};s.world=world;s.match=match;
    }
    if(s.complete||ba::lanSlot()!=1)return;
    auto& owner=actors::state();if(owner.world!=world||owner.match!=match||!owner.manager||!owner.simulation)return;
    base::owned(owner);if(ba_lan::matchEnded)return;
    const int frame=ba::read<int>(owner.simulation->get(),0xac);if(frame<198)return;Obj selector=selectorFor(owner);
    if(!s.performCalls){activate(owner,selector,frame);return;}
    if(frame>=260){require(frame<=261&&(originalOnly()?base::state().passed:context_move::state().complete),"original Hold lacks complete parent mobile episode");
        record(owner,selector,frame,"complete");s.complete=true;}
}
}
