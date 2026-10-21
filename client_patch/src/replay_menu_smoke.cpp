#pragma once
// Explicit healthy original replay API/lifecycle control. No ReplayFiles batch,
// manual FSM transition, helper ticks, or new UI route. The separate button
// mode invokes the existing input binding/confirmation, never the exit API for success.
namespace ba_replay_menu {
using ba::Obj;using ba_local::Root;using ba_native_settings::require;
namespace codec=ba_native_replay_reader;
namespace ui=ba_practice_settings_ui;
struct Probe {
    Root owner,front,replay,simulation;
    ba_native_settings::Handle file;
    std::unique_ptr<Root> controller,button,show,model,modal,modalOwner;
    bool optionsDispatched=false,buttonClicked=false;
    bool cancelSent=false,cancelSettled=false;
    unsigned leaveCalls=0;int cancelFrame=0;Obj gameData=nullptr;
    ULONGLONG optionsDeadline=0;
    uint64_t world=0;int frames=0;
    Probe(Obj a,Obj b,Obj c,Obj d):owner(a),front(b),replay(c),simulation(d){}
};
static auto& probe=*new std::unique_ptr<Probe>();
static unsigned stage=0;static ULONGLONG due=0,deadline=0;
static std::string lastState;
static bool canInspect(){return probe && (stage==1 || stage==2);}
static bool buttonMode(){return ba::flag(L"-native-replay-menu-button-smoke");}
static bool cancelMode(){return ba::flag(L"-native-replay-menu-cancel-smoke");}
static void componentInventory(Obj button) {
    Root type(ui::reflectedType("UnityEngine","Component"));
    auto transform=std::make_unique<Root>(ba::call(button,"get_transform"));
    for(unsigned depth=0;transform->get() && depth<4;++depth) {
        void* args[]={type.get()};
        Root values(codec::invoke(codec::method(codec::type("UnityEngine","Component"),"GetComponents",1,
            0x5085bc0,0x06000e1d),transform->get(),args));
        const auto count=ui::arrayCount(values.get(),64);
        for(size_t i=0;i<count;++i) {
            Root value(ui::arrayItem(values.get(),i));if(!value.get())continue;
            const auto before=ba_replay_binding::graphEvents(value.get());
            require(before==ba_replay_binding::graphEvents(value.get()),"replay component event inventory changed");
            ba::log("NATIVE REPLAY BUTTON component inventory: {\"depth\":%u,\"component\":%s,\"events\":%s}",
                depth,ba_replay_binding::reference(value.get()).c_str(),before.c_str());
        }
        Root parent(ba::call(transform->get(),"get_parent"));transform=std::make_unique<Root>(parent.get());
    }
}
static bool clickExit(Probe& value,Obj controller) {
    if(value.cancelSent && !value.cancelSettled) {
        require(value.show && value.modalOwner && GetTickCount64()<value.optionsDeadline &&
            ba::read<uint64_t>(value.simulation.get(),0x1a8)==value.world &&
            ba::read<bool>(value.simulation.get(),0x1a0) &&
            ba::get<Obj>(value.replay.get(),"_gameData")==value.gameData,
            "replay Cancel changed the replay/world or exceeded its deadline");
        Root navigation(ba::get<Obj>(ba::owner,"<NavigationStack>k__BackingField"));
        Root entries(ba::get<Obj>(navigation.get(),"_navigationStack"));
        if(ba_local::count(entries.get()) || ba::get<Obj>(value.show->get(),"_uiObject") ||
            ba_catalog::unbox<bool>(ba::call(value.show->get(),"get_IsShown")) ||
            ba::get<bool>(value.modalOwner->get(),"<IsInitialized>k__BackingField"))return false;
        const int frame=ba::read<int>(value.simulation.get(),0xac);
        if(frame<value.cancelFrame+3)return false;
        if(ui::active(value.button->get()))return false;
        Root view(ba::get<Obj>(controller,"_optionsConcedeView"));
        require(!ba::native<bool(*)(Obj,Obj)>(0x88a350)(view.get(),nullptr),"replay Cancel unexpectedly reopened options");
        ba::log("NATIVE REPLAY BUTTON cancel settled: world=%llu presentedBefore=%d presentedAfter=%d sameReplay=1 nativeRelease=1 navigationCount=0 optionsHidden=1 fsmWrites=0 helperTicks=0",
            static_cast<unsigned long long>(value.world),value.cancelFrame,frame);
        value.cancelSettled=true;value.buttonClicked=false;value.optionsDispatched=false;
        value.modal.reset();value.modalOwner.reset();value.model.reset();value.show.reset();return false;
    }
    if(!value.optionsDispatched) {
        value.controller=std::make_unique<Root>(controller);
        value.button=std::make_unique<Root>(ba::get<Obj>(controller,"_leaveReplayButton"));
        require(ui::exact(value.button->get(),"Doozy.Runtime.UIManager.Components","UIButton") &&
            !ui::active(value.button->get()),"replay button must start under the closed options view");
        value.optionsDispatched=true;value.optionsDeadline=GetTickCount64()+10000;
        ba::log("NATIVE REPLAY BUTTON options dispatch: originalTryShowOptionsConcedeView=1 buttonInitiallyHidden=1 fsmWrites=0");
        codec::invoke(codec::method(ba::klass(controller),"TryShowOptionsConcedeView",0,0x3b44490,0x0600171b),controller);
        return false;
    }
    require(value.controller && value.controller->get()==controller && value.button &&
        ba::get<Obj>(controller,"_leaveReplayButton")==value.button->get() &&
        GetTickCount64()<value.optionsDeadline,"replay button owner/visibility deadline differs");
    if(value.buttonClicked) {
        require(value.show && value.model,"replay authored modal source missing");
        Root modal(ba::get<Obj>(value.show->get(),"_uiObject"));
        if(!modal.get() || !ba::get<bool>(modal.get(),"_isInitialized") || !ui::active(modal.get()))return false;
        require(ui::exact(modal.get(),"Uncapped.UI","ModalConfirmVM") &&
            ba::get<Obj>(modal.get(),"_model")==value.model->get(),"replay acquired wrong confirmation model");
        Root owner(ba::get<Obj>(modal.get(),"<Owner>k__BackingField"));
        Root navigation(ba::get<Obj>(ba::owner,"<NavigationStack>k__BackingField"));
        Root entries(ba::get<Obj>(navigation.get(),"_navigationStack"));
        require(owner.get() && ba::get<bool>(owner.get(),"<IsInitialized>k__BackingField") &&
            ba::get<Obj>(owner.get(),"<Root>k__BackingField")==modal.get() &&
            ba::get<Obj>(owner.get(),"_pool")==ba::get<Obj>(value.show->get(),"_pool") &&
            ba::get<int>(owner.get(),"<PrefabType>k__BackingField")==52 &&
            ba::get<Obj>(modal.get(),"_navigationStack")==navigation.get() &&
            ba_local::count(entries.get())==1 && ui::item(entries.get(),0)==modal.get(),
            "replay confirmation is not the current owned modal");
        const bool cancel=cancelMode() && !value.cancelSent;
        Root child(ui::findChild(modal.get(),cancel?"ModalContainer/Buttons/CancelButton":"ModalContainer/Buttons/ConfirmButton"));
        Root button(ui::component(child.get(),"Doozy.Runtime.UIManager.Components","UIButton"));
        if(!ui::selectable(button.get()))return false;
        Root container(ba::get<Obj>(button.get(),"Behaviours"));
        ba_replay_binding::List behaviours(ba::get<Obj>(container.get(),"Behaviours"));unsigned found=0;
        for(int i=0;i<behaviours.size;++i) {
            Root item(behaviours.at(i));if(ba::get<int>(item.get(),"BehaviourName")!=7)continue;
            require(++found==1 && ba::get<Obj>(item.get(),"Selectable")==button.get(),"replay confirm button owner differs");
            ui::persistentTarget(ba::get<Obj>(item.get(),"Event"),modal.get(),cancel?"OnCancel":"OnConfirm");
        }
        behaviours.unchanged();require(found==1,"replay original confirm callback missing");
        value.modal=std::make_unique<Root>(modal.get());value.modalOwner=std::make_unique<Root>(owner.get());
        if(cancel) {
            require(ba::get<bool>(value.model->get(),"CloseOnCancel"),"replay Cancel model must close the modal");
            Root meta(ba::get<Obj>(value.model->get(),"Meta")),event(ba::get<Obj>(meta.get(),"CancelEvent"));
            Root group(ba::get<Obj>(event.get(),"m_PersistentCalls")),invoked(ba::get<Obj>(event.get(),"m_Calls"));
            ba_replay_binding::List persistent(ba::get<Obj>(group.get(),"m_Calls"));
            ba_replay_binding::List runtime(ba::get<Obj>(invoked.get(),"m_RuntimeCalls"));
            require(persistent.size==0 && runtime.size==0,"replay Cancel has unqualified side effects");
            persistent.unchanged();runtime.unchanged();
            value.cancelFrame=ba::read<int>(value.simulation.get(),0xac);value.cancelSent=true;
            value.optionsDeadline=GetTickCount64()+10000;
            ba::log("NATIVE REPLAY BUTTON cancel dispatch: originalModalOnCancel=1 currentNavigation=1 emptyCancelEvent=1 closeOnCancel=1 world=%llu presented=%d originalExitApi=0 fsmWrites=0 helperTicks=0",
                static_cast<unsigned long long>(value.world),value.cancelFrame);
            ba::call(modal.get(),"OnCancel");
            ba::log("NATIVE REPLAY BUTTON cancel returned: originalCallbackReturned=1");return false;
        }
        ba::log("NATIVE REPLAY BUTTON confirmation dispatch: originalModalOnConfirm=1 currentNavigation=1 nativeModel=1 persistentReplayEndGame=1 originalExitApi=0 fsmWrites=0 helperTicks=0");
        ba::call(modal.get(),"OnConfirm");
        ba::log("NATIVE REPLAY BUTTON authored returned: originalCallbackReturned=1");return true;
    }
    if(!ui::selectable(value.button->get()))return false;
    Root view(ba::get<Obj>(controller,"_optionsConcedeView"));
    if(!view.get() || !ba::native<bool(*)(Obj,Obj)>(0x88a350)(view.get(),nullptr))return false;
    Root id(ba::get<Obj>(value.button->get(),"Id"));
    require(id.get() && !ba::get<bool>(id.get(),"Custom") &&
        ba_catalog::utf8(ba::get<Obj>(id.get(),"Category"))=="Game" &&
        ba_catalog::utf8(ba::get<Obj>(id.get(),"Name"))=="Quit","replay visible button ID differs");
    const auto before=ba_replay_binding::snapshot(controller,value.button->get());
    require(before==ba_replay_binding::snapshot(controller,value.button->get()) &&
        ba::read<uint64_t>(value.simulation.get(),0x1a8)==value.world,
        "replay visible button bindings/world changed during inventory");
    ba::log("NATIVE REPLAY BUTTON visible inventory: %s",before.c_str());
    componentInventory(value.button->get());
    Root binder(ui::component(value.button->get(),"Uncapped","BindUISelectableToInputAction"));
    Root show(ui::component(value.button->get(),"Uncapped.UI","ShowUIObjectComponent"));
    require(ui::exact(binder.get(),"Uncapped","BindUISelectableToInputAction") && ui::active(binder.get()) &&
        ba::get<Obj>(binder.get(),"_button")==value.button->get() && show.get() &&
        ui::gameObject(binder.get())==ui::gameObject(value.button->get()),"replay authored input binding owner differs");
    Root event(ba::get<Obj>(binder.get(),"ClickEvent"));
    Root group(ba::get<Obj>(event.get(),"m_PersistentCalls"));
    ba_replay_binding::List calls(ba::get<Obj>(group.get(),"m_Calls"));require(calls.size==2,"replay authored click callback count differs");
    for(int i=0;i<2;++i) {
        Root call(calls.at(i));
        require(ba::get<Obj>(call.get(),"m_Target")==(!i?show.get():view.get()) &&
            ba_catalog::utf8(ba::get<Obj>(call.get(),"m_MethodName"))==(!i?"Show":"Hide") &&
            ba::get<int>(call.get(),"m_Mode")==1 && ba::get<int>(call.get(),"m_CallState")==2,
            "replay authored click target differs");
    }
    calls.unchanged();Root descriptor(ba::get<Obj>(show.get(),"_showUIObject"));
    Root model(ba::get<Obj>(descriptor.get(),"_model"));
    require(ui::exact(model.get(),"Uncapped.UI","ModalConfirmModel"),"replay authored confirmation model differs");
    Root meta(ba::get<Obj>(model.get(),"Meta")),confirm(ba::get<Obj>(meta.get(),"ConfirmEvent"));
    ui::persistentTarget(confirm.get(),controller,"ReplayEndGame");
    Root confirmGroup(ba::get<Obj>(confirm.get(),"m_PersistentCalls"));
    ba_replay_binding::List confirmCalls(ba::get<Obj>(confirmGroup.get(),"m_Calls"));
    Root confirmCall(confirmCalls.at(0));
    require(ba::get<int>(confirmCall.get(),"m_Mode")==1 && ba::get<int>(confirmCall.get(),"m_CallState")==2,
        "replay authored confirmation mode/state differs");
    for(Obj action:{event.get(),confirm.get()}) {
        Root invoked(ba::get<Obj>(action,"m_Calls"));
        ba_replay_binding::List runtime(ba::get<Obj>(invoked.get(),"m_RuntimeCalls"));
        require(runtime.size==0,"replay authored event has unqualified runtime listeners");runtime.unchanged();
    }
    const auto clickBefore=ba_replay_binding::event(event.get()),confirmBefore=ba_replay_binding::event(confirm.get());
    require(clickBefore==ba_replay_binding::event(event.get()) && confirmBefore==ba_replay_binding::event(confirm.get()),
        "replay authored event inventory changed");
    ba::log("NATIVE REPLAY BUTTON authored binding: {\"binder\":%s,\"same_game_object\":true,\"show\":%s,\"view\":%s,\"click_event\":%s,\"confirm_event\":%s}",
        ba_replay_binding::reference(binder.get()).c_str(),ba_replay_binding::reference(show.get()).c_str(),
        ba_replay_binding::reference(view.get()).c_str(),clickBefore.c_str(),confirmBefore.c_str());
    value.show=std::make_unique<Root>(show.get());value.model=std::make_unique<Root>(model.get());
    value.buttonClicked=true;++value.leaveCalls;
    ba::log("NATIVE REPLAY BUTTON authored dispatch: originalBindClickButton=1 active=1 interactable=1 originalExitApi=0 buttonClicks=1 fsmWrites=0 helperTicks=0");
    codec::invoke(codec::method(ba::klass(binder.get()),"ClickButton",0,0x3e9b630,0x060015bc),binder.get());
    return false;
}
static void update(Obj front) {
    if(!ba::flag(L"-native-replay-menu-smoke") || stage>=4 || GetTickCount64()<due)return;
    due=GetTickCount64()+50;
    try {
        require(ui::unityThread() && ba::offlinePractice() && ba_native_settings::session &&
            ba::flag(L"-native-quit-smoke") && ba::flag(L"-native-quit-gate-smoke") &&
            ba::flag(L"-replay-binding-inventory") && ba::flag(L"-replay-signal-inventory") &&
            ba::flag(L"-replay-nody-inventory") && !ba::flag(L"-practice-ai-smoke") &&
            !ba::flag(L"-native-replay-playback-smoke"),"replay menu control requires one owned diagnostic API sequence");
        require(!cancelMode() || buttonMode(),"replay Cancel control requires the original authored leave route");
        const auto& profile=ba_native_settings::session->profile();const std::string prefix="nativestest_replayui_";
        require(profile.size()==prefix.size()+12 && profile.rfind(prefix,0)==0 &&
            profile.find_first_not_of("0123456789abcdef",prefix.size())==std::string::npos,
            "replay menu requires a fresh owned profile");
        Root fsm(ba::get<Obj>(ba::owner,"_mainFSM")),current(ba::get<Obj>(fsm.get(),"_currentState"));
        const auto state=ba_replay_binding::className(current.get());
        if(state!=lastState){lastState=state;ba::log("NATIVE REPLAY MENU state: stage=%u state=%s",stage,state.c_str());}
        const auto now=GetTickCount64();
        if(stage==0) {
            if(!ba_local_menu::ready(front) || !ba_dedicated_session::inMenu() || !ba_client::nativeIdle(front))return;
            if(!deadline){deadline=now+60000;due=now+2500;return;}
            require(now<deadline,"replay menu entry deadline");
            require(!ba_practice::active() && !ba_local::server() && ba_client::worldOwner==ba_client::Owner::None &&
                ba::read<Obj>(current.get(),0x18)==ba::owner && current.get()==ba::read<Obj>(ba::owner,0x2c0),
                "replay menu requires the original idle main-menu owner");
            Root replay(ba::get<Obj>(ba::owner,"<Replay>k__BackingField")),simulation(ba::get<Obj>(replay.get(),"_simulation"));
            require(replay.get() && codec::type("Uncapped","Replay","RGame.dll")==ba::klass(replay.get()) &&
                simulation.get() && !ba::read<uint64_t>(simulation.get(),0x1a8) &&
                !ba::get<Obj>(replay.get(),"_gameData"),"replay menu refuses preexisting replay/world data");
            probe=std::make_unique<Probe>(ba::owner,front,replay.get(),simulation.get());
            auto& directory=ba_native_storage::destination(ba_native_storage::Kind::Replays);
            const auto selected=directory.directory.apiPath()+L"\\native-menu-replay.rep";
            probe->file.value=CreateFileW(selected.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,
                FILE_FLAG_OPEN_REPARSE_POINT,nullptr);ba_native_settings::ordinary(probe->file.value);
            LARGE_INTEGER size{};require(GetFileSizeEx(probe->file.value,&size) && size.QuadPart>0 &&
                size.QuadPart<=4*1024*1024,"replay menu selected file bound");
            wchar_t final[32768];const auto count=GetFinalPathNameByHandleW(probe->file.value,final,32768,FILE_NAME_NORMALIZED|VOLUME_NAME_DOS);
            require(count && count<32768 && !_wcsicmp(final,selected.c_str()),"replay menu file escapes the pinned owned directory");
            Root path(ba::api<Obj(*)(const wchar_t*,int32_t)>("il2cpp_string_new_utf16")(selected.data(),static_cast<int32_t>(selected.size())));
            ba::log("NATIVE REPLAY MENU load dispatch: profile=%s mainMenu=1 worldIdle=1 originalLoadReplayFromFile=1 extraPlayCalls=0 fsmWrites=0 helperTicks=0",profile.c_str());
            stage=1;deadline=now+60000;void* args[]={path.get()};
            Root loaded(codec::invoke(codec::method(ba::klass(replay.get()),"LoadReplayFromFile",1,0x3dddab0,0x06000952),replay.get(),args));
            require(loaded.get() && ba_catalog::unbox<bool>(loaded.get()),"original replay file load returned false");
            Root frames(codec::get(replay.get(),"get_FrameCount",0x3ddb470,0x0600092a)),data(ba::get<Obj>(replay.get(),"_gameData"));
            probe->frames=ba_catalog::unbox<int>(frames.get());require(data.get() && probe->frames>30 && probe->frames<=65536,
                "replay menu decoded data/frame bound");
            probe->gameData=data.get();
            const auto digest=ba_lan::sha(ba_lan::serialize(data.get()));std::string hash;char byte[3];
            for(unsigned char value:digest){sprintf_s(byte,"%02x",value);hash+=byte;}
            ba::log("NATIVE REPLAY MENU loaded: frames=%d gameDataSha256=%s loadReturned=1 originalPlayInternal=1",probe->frames,hash.c_str());
            return;
        }
        require(now<deadline && probe && probe->owner.get()==ba::owner && probe->front.get()==front &&
            ba::get<Obj>(probe->replay.get(),"_simulation")==probe->simulation.get(),"replay menu owner/deadline differs");
        if(stage==1) {
            if(state!=".RGameInGameState" || !ba::read<bool>(probe->simulation.get(),0x1a0) ||
                ba::read<int>(probe->simulation.get(),0xac)<30)return;
            probe->world=ba::read<uint64_t>(probe->simulation.get(),0x1a8);
            require(probe->world && ba::read<Obj>(current.get(),0x18)==ba::owner && !ba_practice::active(),
                "replay menu original in-game world/owner unavailable");
            ba::log("NATIVE REPLAY MENU in-game: world=%llu presented=%d originalMainFsm=1 practiceActive=0 frames=%d",
                static_cast<unsigned long long>(probe->world),ba::read<int>(probe->simulation.get(),0xac),probe->frames);
            stage=2;
        }
        if(stage==2) {
            if(!ba_replay_binding::finished)return;
            require(ba_replay_binding::passed && state==".RGameInGameState" &&
                ba::read<uint64_t>(probe->simulation.get(),0x1a8)==probe->world,"replay menu requires the unchanged passive replay inventory");
            Root type(ui::reflectedType("Uncapped","ConcedeFlowUIController"));void* args[]={type.get()};
            Root values(ba::invoke(ba::find_class("UnityEngine","Resources"),nullptr,"FindObjectsOfTypeAll",1,args));
            std::unique_ptr<Root> controller;
            for(size_t i=0;i<ui::arrayCount(values.get(),64);++i) {
                Obj candidate=ui::arrayItem(values.get(),i);
                if(ba::get<Obj>(candidate,"_simulation")!=probe->simulation.get() || !ui::active(candidate))continue;
                require(!controller,"replay menu cleanup controller ambiguous");controller=std::make_unique<Root>(candidate);
            }
            require(controller && ba::get<Obj>(controller->get(),"_signalRouter")==ba::read<Obj>(ba::owner,0x238),
                "replay menu cleanup requires the current original controller");
            if(buttonMode()) {
                if(!clickExit(*probe,controller->get()))return;
                stage=3;deadline=now+10000;return;
            }
            stage=3;
            ba::log("NATIVE REPLAY MENU exit API dispatch: originalReplayEndGame=1 buttonClicks=0 fsmWrites=0 helperTicks=0");
            codec::invoke(codec::method(ba::klass(controller->get()),"ReplayEndGame",0,0x3b443b0,0x06001718),controller->get());
            ba::log("NATIVE REPLAY MENU exit API returned: originalCallbackReturned=1");return;
        }
        if(stage==3) {
            if(!ba_dedicated_session::inMenu() || !ba_local_menu::ready(front) || !ba_client::nativeIdle(front))return;
            require(!ba::read<uint64_t>(probe->simulation.get(),0x1a8) &&
                !ba::read<bool>(probe->simulation.get(),0x1a0) && !ba_practice::active() &&
                ba_client::worldOwner==ba_client::Owner::None,"replay menu exit did not release the original world");
            if(cancelMode())require(probe->cancelSettled && probe->leaveCalls==2,"replay Cancel/reopen sequence incomplete");
            probe.reset();stage=4;
            if(cancelMode())ba::log("NATIVE REPLAY MENU CANCEL control passed: mainMenu=1 worldIdle=1 originalExitApi=0 probeRootsReleased=1 filePinReleased=1 buttonClicks=2 cancelCallbacks=1 fsmWrites=0 helperTicks=0 BA_RESURRECTION_REPLAY_MENU_CANCEL_V1");
            else if(buttonMode())ba::log("NATIVE REPLAY MENU BUTTON control passed: mainMenu=1 worldIdle=1 originalExitApi=0 probeRootsReleased=1 filePinReleased=1 buttonClicks=1 fsmWrites=0 helperTicks=0 BA_RESURRECTION_REPLAY_MENU_BUTTON_V2");
            else ba::log("NATIVE REPLAY MENU API control passed: mainMenu=1 worldIdle=1 originalExitApi=1 probeRootsReleased=1 filePinReleased=1 buttonClicks=0 fsmWrites=0 helperTicks=0 BA_RESURRECTION_REPLAY_MENU_V1");
        }
    } catch(const std::exception& error) {
        stage=5;ba::log("Native replay menu control failed: %s",error.what());
        if(buttonMode())try {
            // Failure-only original API cleanup never qualifies the UI route.
            if(probe && probe->controller && ba::owner==probe->owner.get() &&
                ba::get<Obj>(probe->controller->get(),"_simulation")==probe->simulation.get() &&
                ba::read<uint64_t>(probe->simulation.get(),0x1a8)==probe->world &&
                ba::read<bool>(probe->simulation.get(),0x1a0)) {
                Root fsm(ba::get<Obj>(ba::owner,"_mainFSM")),current(ba::get<Obj>(fsm.get(),"_currentState"));
                require(ba_replay_binding::className(current.get())==".RGameInGameState" &&
                    ba::read<Obj>(current.get(),0x18)==ba::owner,"replay failure cleanup requires the same in-game owner");
                codec::invoke(codec::method(ba::klass(probe->controller->get()),"ReplayEndGame",0,0x3b443b0,0x06001718),probe->controller->get());
                ba::log("NATIVE REPLAY BUTTON failure cleanup: originalExitApiReturned=1 successUnclaimed=1");
            } else if(ba_dedicated_session::inMenu() && ba_client::nativeIdle(front))
                ba::log("NATIVE REPLAY BUTTON failure cleanup: alreadyIdle=1 successUnclaimed=1");
        }catch(const std::exception& cleanup){ba::log("Native replay button failure cleanup failed: %s",cleanup.what());}
        probe.reset();
    }
}
}
