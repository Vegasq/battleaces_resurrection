#pragma once
// Include after local_bootstrap.cpp. All entry points run on the Unity thread.
// Native evidence and the protocol/lifetime contract are documented in
// docs/client-session-lifecycle.txt. No native world or UI object is freed here.
namespace ba_community_match { static void loadingFailure(); }
namespace ba_dedicated_session {
using ba::Obj;using ba_local::Root;
static bool lobbyInstalled=false,joined=false,sawWorld=false,abortRequested=false;
static bool deferredPlay=false,blocked=false;
static int appliedReady=-1;
static unsigned startedSessions=0;
static DWORD unityThread=0;
static ULONGLONG retryAt=0,failedAt=0,lastWaitLog=0;
static Obj observedFront=nullptr;
static bool reconnectRequested=false,reconnectThenPlay=false,retryNeedsPlay=false;
static bool failureNoticeShown=false,retryReleaseAttempted=false,retryModalReleased=false,retryContinueIssued=false;
static uint64_t updateSequence=0,reconnectAfterUpdate=0;
static ULONGLONG failureNoticeCheckAt=0,recoverySmokeAt=0;
static unsigned failureNoticeChecks=0,recoverySmokeStage=0;
static bool smokeContinueIssued=false,smokeDeckEdited=false,smokeFinished=false;
static ULONGLONG smokePostgameAt=0;
static ULONGLONG diagnosticAt=0;
static unsigned diagnosticCount=0;
static bool legacyDisconnectReleaseAttempted=false;
static ULONGLONG legacyDisconnectCheckAt=0;
static unsigned legacyDisconnectChecks=0;
static bool lobbyDisconnectReleaseAttempted=false;
static ULONGLONG lobbyDisconnectCheckAt=0,lobbyObservationAt=0;
static unsigned lobbyDisconnectChecks=0,lobbyObservations=0;

static bool inMenu() {
    Obj fsm=ba::read<Obj>(ba::owner,0x2b0);
    return fsm && ba::get<Obj>(fsm,"_currentState")==ba::read<Obj>(ba::owner,0x2c0);
}
static bool worldIdle(Obj server) {
    Obj sim=ba::read<Obj>(server,0x140);
    return server && sim && !ba::read<bool>(server,0xd8) &&
        !ba::read<bool>(sim,0x1a0) && !ba::read<uint64_t>(sim,0x1a8);
}
static const char* className(Obj object) {
    return object?ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(ba::klass(object)):"null";
}
static Obj loginController(Obj front,Obj server) {
    Root event(ba::get<Obj>(server,"GameStateCleanedUp"));if(!event.get())return nullptr;
    Root listeners(ba::call(event.get(),"GetInvocationList"));
    const size_t count=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(listeners.get());
    if(count>128)throw std::runtime_error("unexpected native cleanup listener count");
    Obj expected=ba::find_class("Uncapped.UI","UILoginFlowController");
    for(size_t i=0;i<count;++i) {
        Obj entry=ba::read<Obj>(listeners.get(),0x20+i*sizeof(Obj));
        Root controller(ba::call(entry,"get_Target"));
        if(controller.get() && ba::klass(controller.get())==expected &&
           ba::get<Obj>(controller.get(),"_frontServer")==front &&
           ba::get<Obj>(controller.get(),"_gameServer")==server)return controller.get();
    }
    return nullptr;
}
static void queueReconnect(Obj front,bool thenPlay=false) {
    // The original RetryLogin tail arrives on the UI thread, still inside the
    // modal's UnityEvent callback. Do not release the invoking VM here.
    if(!unityThread || GetCurrentThreadId()!=unityThread || front!=observedFront) {
        ba::log("Dedicated Reconnect ignored outside the observed Unity/front session");return;
    }
    if(!ba_lan::stopped || reconnectRequested)return;
    ba::log("Dedicated recovery ABI BA_RESURRECTION_RECOVERY_V1");
    reconnectRequested=true;reconnectThenPlay=thenPlay;reconnectAfterUpdate=updateSequence;
    ba::log("Dedicated Reconnect callback queued: update=%llu originalChannel=%p pendingClosure=%d thenPlay=%d",
        static_cast<unsigned long long>(updateSequence),ba::read<Obj>(front,0x20),ba::read<bool>(front,0x38)?1:0,thenPlay?1:0);
}
static void showFailureNotice(Obj front,Obj server) {
    if(failureNoticeShown || failureNoticeChecks>=120 || ba::read<bool>(ba::owner,0x280))return;
    const ULONGLONG now=GetTickCount64();if(now<failureNoticeCheckAt)return;
    failureNoticeCheckAt=now+250;++failureNoticeChecks;
    try {
        Root controller(loginController(front,server));if(!controller.get())return;
        Obj descriptor=ba::get<Obj>(controller.get(),"_disconnectedModal");
        Obj active=ba::get<Obj>(controller.get(),"_activeModal");
        if(!descriptor || (active && ba::get<Obj>(controller.get(),"_activeShowUIObject")!=descriptor))return;
        if(!active){void* args[]={descriptor};ba::call(controller.get(),"ShowModal",1,args);}
        if(ba::get<Obj>(controller.get(),"_activeShowUIObject")!=descriptor ||
           !ba::get<Obj>(controller.get(),"_activeModal"))return;
        failureNoticeShown=true;
        ba::log("Dedicated failure dialog ready: menu=%d worldIdle=%d originalChannel=%p pendingClosure=%d; Reconnect opens a new lobby, Quit remains native. Reason: %s",
            inMenu()?1:0,worldIdle(server)?1:0,ba::read<Obj>(front,0x20),ba::read<bool>(front,0x38)?1:0,ba_lan::failureReason.c_str());
    } catch(const std::exception& e) {
        failureNoticeChecks=120;
        ba::log("Dedicated failure dialog unavailable; retaining stopped session: %s",e.what());
    }
}
static bool releaseRetryModal(Obj front,Obj server) {
    if(retryModalReleased)return true;
    if(retryReleaseAttempted)return false;
    Root controller(loginController(front,server));if(!controller.get())return false;
    Obj descriptor=ba::get<Obj>(controller.get(),"_disconnectedModal");
    Obj active=ba::get<Obj>(controller.get(),"_activeModal");
    if(active && (!descriptor || ba::get<Obj>(controller.get(),"_activeShowUIObject")!=descriptor))return false;
    retryReleaseAttempted=true; // A release failure is never retried in a loop.
    // Also cancel the controller's delayed disconnect coroutine when its modal
    // has not appeared yet. HideReconnectUI's empty-modal path is native-owned.
    ba::call(controller.get(),"HideReconnectUI");
    if(ba::get<Obj>(controller.get(),"_activeModal"))return false;
    retryModalReleased=true;
    ba::log("Dedicated retry modal released on later update: requested=%llu current=%llu nativeRelease=1 hadModal=%d menu=%d worldIdle=%d",
        static_cast<unsigned long long>(reconnectAfterUpdate),static_cast<unsigned long long>(updateSequence),active?1:0,inMenu()?1:0,worldIdle(server)?1:0);
    return true;
}
static void recoverySmokeConfirm(Obj front,Obj server) {
    const bool quit=ba::flag(L"-dedicated-quit-smoke");
    if((!quit && !ba::flag(L"-dedicated-recovery-smoke")) || recoverySmokeStage || !failureNoticeShown)return;
    if(!recoverySmokeAt){recoverySmokeAt=GetTickCount64();return;}
    if(GetTickCount64()-recoverySmokeAt<1500)return;
    Root controller(loginController(front,server));if(!controller.get())return;
    Obj descriptor=ba::get<Obj>(controller.get(),"_disconnectedModal");
    Root modal(ba::get<Obj>(controller.get(),"_activeModal"));
    if(!descriptor || ba::get<Obj>(controller.get(),"_activeShowUIObject")!=descriptor ||
       strcmp(className(modal.get()),"ModalConfirmVM"))return;
    recoverySmokeStage=quit?3:1;recoverySmokeAt=0;
    if(quit) {
        ba::log("QUIT SMOKE invoking original disconnected modal OnCancel (NOT manual UI input)");
        ba::call(modal.get(),"OnCancel");
        return;
    }
    ba::log("RECOVERY SMOKE invoking original disconnected modal OnConfirm (NOT manual UI input)");
    ba::call(modal.get(),"OnConfirm");
    ba::log("RECOVERY SMOKE original OnConfirm returned; modalStillOwned=%d queued=%d",
        ba::get<Obj>(controller.get(),"_activeModal")==modal.get()?1:0,reconnectRequested?1:0);
}
static void releaseCompletedLegacyDisconnect(Obj front,Obj server) {
    // The shipped login controller rechecks the retired front service during
    // GameStateCleanedUp, even after a verified dedicated victory/defeat. Its
    // exact disconnected descriptor is obsolete here; other dialogs and all
    // unsuccessful coordinator paths keep their native behavior.
    if(legacyDisconnectReleaseAttempted || legacyDisconnectChecks>=120 ||
       ba_lan::stopped || !ba_lan::failureReason.empty() || ba_local::failed.load() ||
       !joined || !sawWorld || !ba_lan::matchEnded || !ba_dedicated_results::delivered ||
       ba_dedicated_results::updating || ba_dedicated_results::matchId!=ba_lan::dedicatedMatchId ||
       !worldIdle(server))return;
    Obj fsm=ba::read<Obj>(ba::owner,0x2b0);
    if(!fsm || ba::get<Obj>(fsm,"_currentState")!=ba::read<Obj>(ba::owner,0x2f0))return;
    const ULONGLONG now=GetTickCount64();if(now<legacyDisconnectCheckAt)return;
    legacyDisconnectCheckAt=now+250;++legacyDisconnectChecks;
    try {
        Root event(ba::get<Obj>(server,"GameStateCleanedUp"));if(!event.get())return;
        Root listeners(ba::call(event.get(),"GetInvocationList"));
        const size_t count=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(listeners.get());
        if(count>128)throw std::runtime_error("unexpected native cleanup listener count");
        Obj loginClass=ba::find_class("Uncapped.UI","UILoginFlowController");
        for(size_t i=0;i<count;++i) {
            Obj entry=ba::read<Obj>(listeners.get(),0x20+i*sizeof(Obj));
            Root controller(ba::call(entry,"get_Target"));
            if(!controller.get() || ba::klass(controller.get())!=loginClass)continue;
            if(ba::get<Obj>(controller.get(),"_frontServer")!=front ||
               ba::get<Obj>(controller.get(),"_gameServer")!=server ||
               ba::get<bool>(controller.get(),"_isTrackingGameConnection") ||
               ba::read<int>(front,0x118)!=0)return;
            Obj descriptor=ba::get<Obj>(controller.get(),"_disconnectedModal");
            Obj activeDescriptor=ba::get<Obj>(controller.get(),"_activeShowUIObject");
            Obj modal=ba::get<Obj>(controller.get(),"_activeModal");
            if(!descriptor || activeDescriptor!=descriptor || !modal)return;
            Obj navigation=ba::get<Obj>(ba::owner,"<NavigationStack>k__BackingField");
            Obj stack=navigation?ba::get<Obj>(navigation,"_navigationStack"):nullptr;
            const int before=stack?ba_local::count(stack):-1;
            // Mark BEFORE invoking native release. A failed release must never
            // become an endless popup-dismissal loop or suppress later errors.
            legacyDisconnectReleaseAttempted=true;
            ba::log("Dedicated completed legacy disconnect: match=%s controller=%s source=OnGameStateCleanedUp/UpdateView frontStatus=0 tracking=0 activeShow=%p disconnected=%p modal=%s navigationBefore=%d; one original HideReconnectUI call",
                ba_lan::dedicatedMatchId.c_str(),className(controller.get()),activeDescriptor,descriptor,className(modal),before);
            ba::call(controller.get(),"HideReconnectUI");
            ba::log("Dedicated completed legacy disconnect released: match=%s activeShowAfter=%p modalAfter=%p navigationAfter=%d; native pool/navigation ownership retained",
                ba_lan::dedicatedMatchId.c_str(),ba::get<Obj>(controller.get(),"_activeShowUIObject"),
                ba::get<Obj>(controller.get(),"_activeModal"),stack?ba_local::count(stack):-1);
            return;
        }
    } catch(const std::exception& e) {
        legacyDisconnectReleaseAttempted=true;
        ba::log("Dedicated completed legacy disconnect inspection/release failed; no retry: %s",e.what());
    }
}
static void releaseHealthyLobbyLegacyDisconnect(Obj front,Obj server) {
    // Startup also lets the shipped login controller inspect the deliberately
    // disconnected original front service. A successful replacement WELCOME
    // must not leave that unrelated modal blocking the ordinary Play button.
    // Poll the replacement transport first; real errors enter recover() instead.
    if(!lobbyInstalled || joined || sawWorld || !inMenu() || !worldIdle(server) ||
       !(ba::community()?ba_community::online:ba_lan::welcomed) || ba_lan::stopped || ba_lan::peerClosed ||
       !ba_lan::failureReason.empty() || ba_local::failed.load() ||
       !ba_lan::bootstrap.empty() || ba::read<bool>(ba::owner,0x280))return;
    const ULONGLONG now=GetTickCount64();
    if(lobbyDisconnectReleaseAttempted) {
        // A few read-only observations establish that release stays effective
        // while idle. Never repeatedly dismiss a modal that reappears.
        if(!lobbyObservationAt || now<lobbyObservationAt || lobbyObservations>=6)return;
        lobbyObservationAt=now+5000;++lobbyObservations;
        try {
            Root controller(loginController(front,server));if(!controller.get())return;
            Obj navigation=ba::get<Obj>(ba::owner,"<NavigationStack>k__BackingField");
            Obj stack=navigation?ba::get<Obj>(navigation,"_navigationStack"):nullptr;
            ba::log("Dedicated idle lobby observation: sample=%u activeShow=%p modal=%p navigation=%d welcome=1 stopped=0 worldIdle=1",
                lobbyObservations,ba::get<Obj>(controller.get(),"_activeShowUIObject"),
                ba::get<Obj>(controller.get(),"_activeModal"),stack?ba_local::count(stack):-1);
        } catch(const std::exception& e) {
            lobbyObservations=6;
            ba::log("Dedicated idle lobby observation unavailable: %s",e.what());
        }
        return;
    }
    if(lobbyDisconnectChecks>=120 || now<lobbyDisconnectCheckAt)return;
    lobbyDisconnectCheckAt=now+250;++lobbyDisconnectChecks;
    try {
        Root controller(loginController(front,server));if(!controller.get())return;
        if(ba::get<bool>(controller.get(),"_isTrackingGameConnection") ||
           ba::read<int>(front,0x118)!=0 || ba::read<Obj>(front,0x20) || ba::read<bool>(front,0x38))return;
        Obj descriptor=ba::get<Obj>(controller.get(),"_disconnectedModal");
        Obj activeDescriptor=ba::get<Obj>(controller.get(),"_activeShowUIObject");
        Obj modal=ba::get<Obj>(controller.get(),"_activeModal");
        if(!descriptor || activeDescriptor!=descriptor || !modal)return;
        Obj navigation=ba::get<Obj>(ba::owner,"<NavigationStack>k__BackingField");
        Obj stack=navigation?ba::get<Obj>(navigation,"_navigationStack"):nullptr;
        lobbyDisconnectReleaseAttempted=true;
        ba::log("Dedicated healthy lobby legacy disconnect: controller=%s frontStatus=0 originalChannel=null tracking=0 activeShow=%p disconnected=%p modal=%s navigationBefore=%d; one original HideReconnectUI call",
            className(controller.get()),activeDescriptor,descriptor,className(modal),stack?ba_local::count(stack):-1);
        ba::call(controller.get(),"HideReconnectUI");
        ba::log("Dedicated healthy lobby legacy disconnect released: activeShowAfter=%p modalAfter=%p navigationAfter=%d welcome=1 worldIdle=1; native pool/navigation ownership retained",
            ba::get<Obj>(controller.get(),"_activeShowUIObject"),ba::get<Obj>(controller.get(),"_activeModal"),
            stack?ba_local::count(stack):-1);
        lobbyObservationAt=now+5000;
    } catch(const std::exception& e) {
        lobbyDisconnectReleaseAttempted=true;
        ba::log("Dedicated healthy lobby legacy disconnect inspection/release failed; no retry: %s",e.what());
    }
}
static void postgameDiagnostics(Obj server) {
    // Also enabled in manual runs. Diagnostics never alter the UI or weaken a
    // lifecycle gate, and stop after24 samples rather than logging indefinitely.
    if((!ba_dedicated_results::delivered && !ba_lan::matchEnded) || diagnosticCount>=24)return;
    const ULONGLONG now=GetTickCount64();if(now<diagnosticAt)return;
    diagnosticAt=now+5000;++diagnosticCount;
    try {
        Obj sim=ba::read<Obj>(server,0x140),fsm=ba::read<Obj>(ba::owner,0x2b0);
        Obj outer=fsm?ba::get<Obj>(fsm,"_currentState"):nullptr;
        Obj controller=ba::get<Obj>(ba::owner,"<UIPostGameController>k__BackingField");
        Obj resultState=controller?ba::get<Obj>(controller,"_matchResultState"):nullptr;
        Obj postFsm=controller?ba::get<Obj>(controller,"_fsm"):nullptr;
        Obj inner=postFsm?ba::get<Obj>(postFsm,"_currentState"):nullptr;
        Obj view=resultState?ba::get<Obj>(resultState,"_matchResultVM"):nullptr;
        Obj navigation=view?ba::get<Obj>(view,"_navigationStack"):nullptr;
        Obj stack=navigation?ba::get<Obj>(navigation,"_navigationStack"):nullptr;
        const int navigationCount=stack?ba_local::count(stack):-1;
        Obj matchData=ba::get<Obj>(ba::owner,"<MatchDataManager>k__BackingField");
        Obj info=matchData?ba::get<Obj>(matchData,"_matchInfo"):nullptr;
        const int rewardScreen=info?ba::get<int>(info,"ProvingGroundsRewardScreen"):-1;
        const char* gate=!joined?"not-joined":!sawWorld?"world-never-observed":
            !ba_dedicated_results::delivered?"result-not-delivered":!worldIdle(server)?"world-not-idle":
            outer!=ba::read<Obj>(ba::owner,0x2f0)?"not-postgame":!controller?"controller-null":
            !resultState||!postFsm||inner!=resultState?"inner-not-match-result":!view?"result-view-null":
            !navigation||!stack?"navigation-null":navigationCount?"navigation-not-empty":"continue-handler-ready";
        ba::log("Dedicated postgame gates %u/24: match=%s gate=%s sessions=%u joined=%d sawWorld=%d delivered=%d active=%d world=%016llx mapLoading=%d outer=%s postgameEqual=%d menu=%d inner=%s resultEqual=%d view=%p navigationCount=%d rewardScreen=%d smokeFlag=%d continueIssued=%d stopped=%d",
            diagnosticCount,ba_lan::dedicatedMatchId.c_str(),gate,startedSessions,joined?1:0,sawWorld?1:0,ba_dedicated_results::delivered?1:0,
            ba::read<bool>(sim,0x1a0)?1:0,static_cast<unsigned long long>(ba::read<uint64_t>(sim,0x1a8)),ba::read<bool>(server,0xd8)?1:0,
            className(outer),outer==ba::read<Obj>(ba::owner,0x2f0)?1:0,inMenu()?1:0,className(inner),inner==resultState?1:0,view,navigationCount,rewardScreen,
            ba::flag(L"-dedicated-rematch-smoke")?1:0,smokeContinueIssued?1:0,ba_lan::stopped?1:0);
    } catch(const std::exception& e){ba::log("Dedicated postgame diagnostics unavailable: %s",e.what());}
}
static bool returnRetrySmoke() {
    if(!ba::flag(L"-public-return-retry-smoke"))return false;
    const auto profile=ba::argument(L"-local-profile=");
    if(!ba::unified() || !ba::flag(L"-public-queue-experimental") || !ba::flag(L"-public-queue-smoke") ||
       !ba::flag(L"-public-queue-smoke-retry") || !ba::flag(L"-dedicated-rematch-smoke") ||
       profile.rfind("cosmeticstest_",0)!=0)
        throw std::runtime_error("public RETURN retry requires an owned full-loadout diagnostic");
    return true;
}
static void rematchSmoke(Obj server) {
    if(!ba::flag(L"-dedicated-rematch-smoke") || !joined || !sawWorld ||
       !ba_dedicated_results::delivered || !worldIdle(server))return;
    Obj fsm=ba::read<Obj>(ba::owner,0x2b0);
    if(ba::get<Obj>(fsm,"_currentState")!=ba::read<Obj>(ba::owner,0x2f0))return;
    // The public recovery probe aborts its first joined world before any result.
    // Continue the second session's first valid result only under explicit test
    // flags and an observed native Reconnect. A team retry probe also includes
    // survivors that returned through an authoritative abort without Reconnect.
    // Both diagnostic paths are bounded to the second session's result.
    // RETURN-ACK retry separately rearms Continue after its completed first result.
    const bool publicRecovery=startedSessions==2 &&
        ba::flag(L"-public-queue-smoke") && ba::flag(L"-public-queue-smoke-retry") &&
        ((recoverySmokeStage==1 && ba::flag(L"-dedicated-recovery-smoke")) ||
         (ba::unified() && ba::flag(L"-public-queue-experimental") && ba::flag(L"-public-team-retry-smoke")) ||
         returnRetrySmoke());
    if(startedSessions>=2 && !publicRecovery) {
        if(!smokeFinished){smokeFinished=true;ba::log("DEDICATED REMATCH SMOKE automated two-match flow finished; leaving second native result screen open");}
        return;
    }
    if((startedSessions!=1 && !publicRecovery) || smokeContinueIssued)return;
    Obj controller=ba::get<Obj>(ba::owner,"<UIPostGameController>k__BackingField");
    if(!controller)return;
    Obj resultState=ba::get<Obj>(controller,"_matchResultState"),postFsm=ba::get<Obj>(controller,"_fsm");
    if(!resultState || !postFsm || ba::get<Obj>(postFsm,"_currentState")!=resultState)return;
    Obj view=ba::get<Obj>(resultState,"_matchResultVM");if(!view)return;
    Obj navigation=ba::get<Obj>(view,"_navigationStack");if(!navigation)return;
    Obj stack=ba::get<Obj>(navigation,"_navigationStack");if(!stack || ba_local::count(stack))return;
    if(!smokePostgameAt){smokePostgameAt=GetTickCount64();return;}
    if(GetTickCount64()-smokePostgameAt<2000)return;
    if(!ba_remote_profiles::resultReady(ba_lan::dedicatedMatchId))return;
    smokeContinueIssued=true;
    ba::log("DEDICATED REMATCH SMOKE automated original MatchResultVM.OnContinue; match=%s active=0 world=0 navigation=empty (NOT manual UI input)",ba_lan::dedicatedMatchId.c_str());
    ba::call(view,"OnContinue");
}
static void releaseRoot(uint32_t& root) {
    if(root){ba::api<void(*)(uint32_t)>("il2cpp_gchandle_free")(root);root=0;}
}
static void resetAtMenu(Obj front,Obj server,bool completed,bool keepCommunity=false) {
    if(!inMenu() || !worldIdle(server) || ba_dedicated_results::updating)
        throw std::runtime_error("dedicated reset requires idle native world and main menu");
    const std::string releaseMatch=ba_lan::dedicatedMatchId;
    ba::log("Dedicated session reset: match=%s sessions=%u completed=%d nextFrame=%d; native world inactive/zero",
        ba_lan::dedicatedMatchId.c_str(),startedSessions,completed?1:0,ba_lan::nextFrame);
    ba_dedicated::loadingCancel("native match returned to menu");
    // Native Shutdown has already stopped/joined the simulation thread. Disable
    // helper command capture before dropping its roots and clearing its queues.
    ba_local::accepting.store(false);ba_local::ready.store(false);
    {
        ba_local::QueueLock lock;
        for(size_t offset:{size_t(0x180),size_t(0x188)}) {
            Obj queue=ba::read<Obj>(server,offset);if(queue)ba::call(queue,"Clear");
        }
    }
    releaseRoot(ba_local::serverRoot);
    ba_local::failed.store(false);ba_local::updateThread=0;ba_local::previousTime=0;
    ba_local::submittedTicks=0;ba_local::lastSubmittedFrame=-1;ba_local::accumulatedMs=0;
    ba_bootstrap::awaitingWorld=false;ba_bootstrap::creating=false;
    releaseRoot(ba_bootstrap::frontRoot);ba_bootstrap::bootstrapThread=0;
    if(!keepCommunity) {
        ba_lan::closeSocket();
        if(ba::community()){ba_community_native::reset();ba_community::reset();}
        ba_lan::rx.clear();ba_lan::tx.clear();ba_lan::txPosition=0;
    }
    ba_lan::closeReceipts();
    ba_lan::frames.clear();
    ba_lan::publicMatch=false;ba_lan::publicIdentities.clear();
    ba_lan::bootstrap.clear();ba_lan::dedicatedDeck.clear();ba_lan::dedicatedMatchId.clear();
    ba_lan::welcomed=false;ba_lan::stopped=false;ba_lan::worldReady=false;ba_lan::running=false;
    ba_lan::peerClosed=false;ba_lan::submittedFirst=false;ba_lan::matchEnded=false;ba_lan::lobbyReady=false;
    ba_lan::nextFrame=0;ba_lan::inputWindow=0;ba_lan::bootstrapHash=0;ba_lan::connectStarted=0;ba_lan::failureReason.clear();
    if(!keepCommunity) {
        ba_dedicated::installing=false;ba_dedicated::initialized=false;
        if(!ba::unified()) {
            ba_dedicated_deck::initialized=false;ba_dedicated_deck::suppress=false;
            releaseRoot(ba_dedicated_deck::accountRoot);
        }
    }
    ba_dedicated_results::pending=false;ba_dedicated_results::delivered=false;
    ba_dedicated_results::gameOverFrame=-1;ba_dedicated_results::winningAlliance=31;
    ba_dedicated_results::concededMask=0;ba_dedicated_results::checksum=0;
    ba_dedicated_results::receivedAt=0;ba_dedicated_results::lastWaitLog=0;ba_dedicated_results::matchId.clear();
    ba_lan_smoke::plan=ba_lan_smoke::Plan{};
    ba::set<Obj>(front,"_playerGameHandle",nullptr);ba::set<Obj>(server,"_playerGameHandle",nullptr);
    ba::dedicatedAssignedSlot=-1;
    lobbyInstalled=keepCommunity;joined=false;sawWorld=false;abortRequested=false;appliedReady=-1;
    failedAt=0;lastWaitLog=0;blocked=false;
    diagnosticAt=0;diagnosticCount=0;
    legacyDisconnectReleaseAttempted=false;legacyDisconnectCheckAt=0;legacyDisconnectChecks=0;
    lobbyDisconnectReleaseAttempted=false;lobbyDisconnectCheckAt=0;lobbyDisconnectChecks=0;
    lobbyObservationAt=0;lobbyObservations=0;
    reconnectRequested=false;reconnectThenPlay=false;reconnectAfterUpdate=0;
    failureNoticeShown=false;failureNoticeCheckAt=0;failureNoticeChecks=0;
    retryReleaseAttempted=false;retryModalReleased=false;retryContinueIssued=false;
    if(completed){deferredPlay=false;retryNeedsPlay=false;}
    if(completed && startedSessions==1 && ba::flag(L"-public-practice-transition-smoke") &&
       ba::flag(L"-public-queue-smoke") && ba::flag(L"-public-queue-smoke-retry-gate") &&
       ba::flag(L"-public-team-retry-smoke")) {
        smokeContinueIssued=false;
        ba::log("PUBLIC PRACTICE TRANSITION SMOKE first remote result retired; second Continue armed");
    }
    if(completed && startedSessions==1 && returnRetrySmoke()) {
        smokeContinueIssued=false;smokePostgameAt=0;
        ba::log("PUBLIC RETURN RETRY SMOKE first native result retired; second Continue armed BA_RESURRECTION_RETURN_RETRY_V1");
    }
    if(ba_client::remoteWorld())ba_client::releaseRemote(front,releaseMatch);
}
static bool retryFromPlay(Obj front,int) {
    if(!ba::dedicated() || !ba_lan::stopped)return false;
    Obj server=ba::read<Obj>(front,0xd8);
    if(!inMenu() || !worldIdle(server) || (joined && !sawWorld && !abortRequested)) {
        ba::log("Dedicated Play waits for the old match's native teardown");return true;
    }
    queueReconnect(front,true);
    ba::log("Dedicated connection retry requested from native Play");return true;
}
static bool recoverCompletedPostgame(Obj front,Obj server) {
    // A genuine failure can arrive after a valid result and native teardown,
    // while the player is still reading results. Reconnect must first use the
    // original Continue path; waiting for menu behind our modal would deadlock.
    if(!joined || !sawWorld || !worldIdle(server) || ba_dedicated_results::updating ||
       !ba_dedicated_results::delivered || ba_dedicated_results::pending ||
       !ba_lan::matchEnded || ba_dedicated_results::matchId.empty() ||
       ba_dedicated_results::matchId!=ba_lan::dedicatedMatchId || ba::read<bool>(ba::owner,0x280))return false;
    Obj fsm=ba::read<Obj>(ba::owner,0x2b0);
    if(!fsm || ba::get<Obj>(fsm,"_currentState")!=ba::read<Obj>(ba::owner,0x2f0))return false;
    if(!reconnectRequested)showFailureNotice(front,server);
    recoverySmokeConfirm(front,server);
    if(!reconnectRequested || updateSequence<=reconnectAfterUpdate ||
       !releaseRetryModal(front,server) || retryContinueIssued)return true;
    Root controller(ba::get<Obj>(ba::owner,"<UIPostGameController>k__BackingField"));
    if(!controller.get())return true;
    Root state(ba::get<Obj>(controller.get(),"_matchResultState"));
    Root postFsm(ba::get<Obj>(controller.get(),"_fsm"));
    if(!state.get() || !postFsm.get() || ba::get<Obj>(postFsm.get(),"_currentState")!=state.get())return true;
    Root view(ba::get<Obj>(state.get(),"_matchResultVM"));if(!view.get())return true;
    Root navigation(ba::get<Obj>(view.get(),"_navigationStack"));if(!navigation.get())return true;
    Root stack(ba::get<Obj>(navigation.get(),"_navigationStack"));
    if(!stack.get() || ba_local::count(stack.get()))return true;
    retryContinueIssued=true;
    ba::log("Dedicated postgame Reconnect invokes original OnContinue: match=%s menu=0 worldIdle=1 navigation=0; waiting for native menu",
        ba_lan::dedicatedMatchId.c_str());
    ba::call(view.get(),"OnContinue");
    return true;
}
static void recover(Obj front,Obj server) {
    const ULONGLONG now=GetTickCount64();
    if(!failedAt){
        failedAt=now;deferredPlay=false;retryNeedsPlay=true;
        ba_dedicated::loadingFailure();
        if(ba::community())ba_community_match::loadingFailure();
        ba_dedicated_deck::updateLobby(front,false);
        ba::log("Dedicated failed session retained until native cleanup and explicit Reconnect; match=%s",ba_lan::dedicatedMatchId.c_str());
    }
    Obj sim=ba::read<Obj>(server,0x140);
    // Do not race the async map callback. Once it finishes, reuse the original
    // reason-1 cleanup, which joins the sim thread and emits native menu flow.
    if(joined && !abortRequested && sim && !ba::read<bool>(server,0xd8) &&
       ba::read<bool>(sim,0x1a0) && ba::read<uint64_t>(sim,0x1a8)) {
        abortRequested=true;ba_bootstrap::awaitingWorld=false;
        int reason=1;bool stayInGame=false;void* args[]={&reason,&stayInGame};
        ba::log("Dedicated aborted match: requesting original CleanupGameState(reason=1)");
        try{ba::call(server,"CleanupGameState",2,args);}
        catch(const std::exception& e){ba::log("Dedicated native cleanup reported: %s",e.what());}
        // No direct field-clearing or alternate native destruction on failure.
    }
    if(recoverCompletedPostgame(front,server))return;
    if(inMenu() && worldIdle(server) && (!joined || sawWorld || abortRequested)) {
        if(!reconnectRequested)showFailureNotice(front,server);
        recoverySmokeConfirm(front,server);
        if(!reconnectRequested || updateSequence<=reconnectAfterUpdate || !releaseRetryModal(front,server))return;
        const bool thenPlay=reconnectThenPlay;
        resetAtMenu(front,server,false);
        retryAt=now+250;deferredPlay=thenPlay;retryNeedsPlay=!thenPlay;
        ba::log("Dedicated explicit retry opening fresh lobby; readyIntent=%d",thenPlay?1:0);
        return;
    }
    // A stalled native map load cannot safely be reset by clearing our flags.
    // Keep the old roots and prohibit a new world; report a bounded diagnostic.
    if(now-failedAt>120000 && !blocked) {
        blocked=true;ba::log("Dedicated cleanup exceeded 120s; retaining native state, process restart required");
        showFailureNotice(front,server);
    }
    if(!blocked && now-lastWaitLog>10000) {
        lastWaitLog=now;ba::log("Dedicated recovery waiting for native teardown: menu=%d active=%d mapLoading=%d",
            inMenu()?1:0,ba::read<bool>(sim,0x1a0)?1:0,ba::read<bool>(server,0xd8)?1:0);
    }
}
static void installLobby(Obj front) {
    if(ba::lanSlot()<0 || ba::lanSlot()>1)throw std::runtime_error("dedicated seat not assigned");
    ba_lan_bootstrap::identityLan(front,ba::lanSlot());
    Root deck(ba_dedicated::deckFromIds(ba_lan::dedicatedDeck));
    ba_dedicated::installing=true;
    try{ba_dedicated_deck::initialize(front,deck.get());}
    catch(...){ba_dedicated::installing=false;throw;}
    ba_dedicated::installing=false;ba_dedicated::initialized=true;lobbyInstalled=true;
    // The native profile persists across matches; its temporary simulation ID
    // follows this connection's seat, not the authenticated/profile identifier.
    Obj account=ba::get<Obj>(front,"_accountService");
    Obj profile=ba::get<Obj>(account,"<ProfileCache>k__BackingField");
    ba::set<uint64_t>(profile,"steamId_",static_cast<uint64_t>(ba::lanSlot()+1));
    ba::set<bool>(profile,"isAlias_",true);
    if(!ba_dedicated_deck::smokeSelection(front))throw std::runtime_error("dedicated deck smoke failed");
    if(ba::flag(L"-dedicated-rematch-smoke") && smokeContinueIssued && startedSessions==1 && !smokeDeckEdited) {
        ba_dedicated_deck::rematchSmokeSelection(front);smokeDeckEdited=true;
    }
    ba::log("Dedicated lobby ready: assigned seat %d, completed/started sessions=%u; choose deck then Play",ba::lanSlot(),startedSessions);
    const bool smokeMayReady=!ba::flag(L"-dedicated-rematch-smoke") || startedSessions<2;
    const bool autoReady=!retryNeedsPlay && smokeMayReady && ba::flag(L"-dedicated-auto-ready") &&
        (!startedSessions || ba::flag(L"-dedicated-auto-rematch"));
    if(deferredPlay || autoReady) {
        deferredPlay=false;
        ba::native<void(*)(Obj,Obj,int,Obj)>(0x3e3c0d0)(front,ba::owner,1,nullptr);
    }
}
static void recoverySmokePlay(Obj front,Obj server) {
    if(!ba::flag(L"-dedicated-recovery-smoke") || recoverySmokeStage!=1 ||
       !retryNeedsPlay || !lobbyInstalled || joined || !inMenu() || !worldIdle(server) || appliedReady!=0)return;
    if(ba_lan::lobbyReady)throw std::runtime_error("Reconnect must not automatically ready a player");
    if(!recoverySmokeAt){recoverySmokeAt=GetTickCount64();return;}
    if(GetTickCount64()-recoverySmokeAt<2000)return;
    recoverySmokeStage=2;
    ba::log("RECOVERY SMOKE fresh lobby is not ready; invoking native Play (NOT manual UI input)");
    ba::native<void(*)(Obj,Obj,int,Obj)>(0x3e3c0d0)(front,ba::owner,1,nullptr);
}
static void update(Obj front) {
    if(!ba::dedicated())return;
    try {
        if(!unityThread)unityThread=GetCurrentThreadId();
        if(unityThread!=GetCurrentThreadId())throw std::runtime_error("dedicated lifecycle called off Unity thread");
        observedFront=front;++updateSequence;
        Obj server=ba::read<Obj>(front,0xd8),sim=ba::read<Obj>(server,0x140);
        if(!server || !sim)return;
        if(ba_practice::frontUpdate(front))return;
        if(joined && ba::read<bool>(sim,0x1a0) && ba::read<uint64_t>(sim,0x1a8))sawWorld=true;
        // Handle failures before the ordinary menu reset, which would otherwise
        // erase the failure and reconnect behind the still-owned native modal.
        if(ba_lan::stopped){recover(front,server);return;}
        postgameDiagnostics(server);
        // Postgame failure qualification leaves the first result open until the
        // harness sends a real ERROR packet. Only Reconnect may advance it.
        if(!ba::flag(L"-dedicated-postgame-recovery-smoke"))rematchSmoke(server);
        // Community return runs after ordered control events, so an abort cannot
        // enter completed-only return before its notice has been consumed.
        if(!ba::community() && joined && sawWorld && inMenu() && worldIdle(server)) {
            const bool completed=ba_dedicated_results::delivered;
            resetAtMenu(front,server,completed);retryAt=GetTickCount64()+500;return;
        }
        if(joined && ba_local::failed.load())throw std::runtime_error("dedicated local input capture failed");
        if(GetTickCount64()<retryAt)return;
        ba_lan::poll();
        if(ba::community()) {
            ba_community_native::update(front);
            releaseCompletedLegacyDisconnect(front,server);
            releaseHealthyLobbyLegacyDisconnect(front,server);
            ba_practice::smoke(front);
            return;
        }
        // Poll first: a real coordinator ERROR/invalid packet must be observed
        // before considering the obsolete original-front success-path modal.
        releaseCompletedLegacyDisconnect(front,server);
        if(ba_lan::welcomed && !lobbyInstalled && inMenu())installLobby(front);
        releaseHealthyLobbyLegacyDisconnect(front,server);
        if(lobbyInstalled && !joined && !ba_lan::bootstrap.empty()) {
            if(ba_lan::dedicatedMatchId.empty())throw std::runtime_error("dedicated bootstrap precedes match ID");
            ba_dedicated_deck::updateLobby(front,false);joined=true;++startedSessions;
            Root encoded(ba_lan::byteString(ba_lan::bootstrap));
            ba_bootstrap::beginJoined(front,encoded.get(),ba_lan_bootstrap::identityLan(front,ba::lanSlot()),true);
            ba::log("Dedicated session %u joined match=%s assignedSeat=%d",startedSessions,ba_lan::dedicatedMatchId.c_str(),ba::lanSlot());
        }
        if(lobbyInstalled && !joined) {
            const int ready=ba_lan::lobbyReady?1:0;
            if(appliedReady!=ready){appliedReady=ready;ba_dedicated_deck::updateLobby(front,ready!=0);}
        }
        recoverySmokePlay(front,server);
        ba_dedicated::loadingUpdate();
    } catch(const std::exception& e){
        ba_lan::fail("dedicated session update",e);
        ba_dedicated::loadingFailure();
        if(ba::community())ba_community_match::loadingFailure();
    }
}
}

// Only RetryLogin's original tail jump is redirected. Its native stack/RBX
// restoration and original generic MethodInfo remain intact. Shared Quit and
// the generic connection routine itself are not patched.
extern "C" __declspec(dllexport) void OfflineDedicatedRetryLogin(void* front,void* methodInfo) {
    ba::init();
    if(ba::unified() && !ba_client::remoteWorld()) {
        try{ba_client::requestConnect();}catch(const std::exception& e){ba::log("Client connection retry: %s",e.what());}
        return;
    }
    if(ba::offlinePractice()){ba::log("Offline practice ignores obsolete service reconnect");return;}
    if(!ba::dedicated()) {
        ba::native<void(*)(ba::Obj,ba::Obj)>(0x256da30)(front,methodInfo);return;
    }
    try{ba_dedicated_session::queueReconnect(front);}
    catch(const std::exception& e){ba::log("Dedicated Reconnect callback failed: %s",e.what());}
}
