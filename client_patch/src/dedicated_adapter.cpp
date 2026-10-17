#pragma once
// Include after local_bootstrap.cpp. All entry points run on the Unity thread.
// Native evidence and the protocol/lifetime contract are documented in
// docs/client-session-lifecycle.txt. No native world or UI object is freed here.
namespace ba_dedicated_session {
using ba::Obj;using ba_local::Root;
static bool lobbyInstalled=false,joined=false,sawWorld=false,abortRequested=false;
static bool deferredPlay=false,blocked=false;
static int appliedReady=-1;
static unsigned startedSessions=0,retryAttempts=0;
static DWORD unityThread=0;
static ULONGLONG retryAt=0,failedAt=0,lastWaitLog=0;
static bool smokeContinueIssued=false,smokeDeckEdited=false,smokeFinished=false;
static ULONGLONG smokePostgameAt=0;
static ULONGLONG diagnosticAt=0;
static unsigned diagnosticCount=0;

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
static void rematchSmoke(Obj server) {
    if(!ba::flag(L"-dedicated-rematch-smoke") || !joined || !sawWorld ||
       !ba_dedicated_results::delivered || !worldIdle(server))return;
    Obj fsm=ba::read<Obj>(ba::owner,0x2b0);
    if(ba::get<Obj>(fsm,"_currentState")!=ba::read<Obj>(ba::owner,0x2f0))return;
    if(startedSessions>=2) {
        if(!smokeFinished){smokeFinished=true;ba::log("DEDICATED REMATCH SMOKE automated two-match flow finished; leaving second native result screen open");}
        return;
    }
    if(startedSessions!=1 || smokeContinueIssued)return;
    Obj controller=ba::get<Obj>(ba::owner,"<UIPostGameController>k__BackingField");
    if(!controller)return;
    Obj resultState=ba::get<Obj>(controller,"_matchResultState"),postFsm=ba::get<Obj>(controller,"_fsm");
    if(!resultState || !postFsm || ba::get<Obj>(postFsm,"_currentState")!=resultState)return;
    Obj view=ba::get<Obj>(resultState,"_matchResultVM");if(!view)return;
    Obj navigation=ba::get<Obj>(view,"_navigationStack");if(!navigation)return;
    Obj stack=ba::get<Obj>(navigation,"_navigationStack");if(!stack || ba_local::count(stack))return;
    if(!smokePostgameAt){smokePostgameAt=GetTickCount64();return;}
    if(GetTickCount64()-smokePostgameAt<2000)return;
    smokeContinueIssued=true;
    ba::log("DEDICATED REMATCH SMOKE automated original MatchResultVM.OnContinue; match=%s active=0 world=0 navigation=empty (NOT manual UI input)",ba_lan::dedicatedMatchId.c_str());
    ba::call(view,"OnContinue");
}
static void releaseRoot(uint32_t& root) {
    if(root){ba::api<void(*)(uint32_t)>("il2cpp_gchandle_free")(root);root=0;}
}
static void resetAtMenu(Obj front,Obj server,bool completed) {
    if(!inMenu() || !worldIdle(server) || ba_dedicated_results::updating)
        throw std::runtime_error("dedicated reset requires idle native world and main menu");
    ba::log("Dedicated session reset: match=%s sessions=%u completed=%d nextFrame=%d; native world inactive/zero",
        ba_lan::dedicatedMatchId.c_str(),startedSessions,completed?1:0,ba_lan::nextFrame);
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
    ba_lan::closeSocket();
    ba_lan::closeReceipts();
    ba_lan::rx.clear();ba_lan::tx.clear();ba_lan::txPosition=0;ba_lan::frames.clear();
    ba_lan::bootstrap.clear();ba_lan::dedicatedDeck.clear();ba_lan::dedicatedMatchId.clear();
    ba_lan::welcomed=false;ba_lan::stopped=false;ba_lan::worldReady=false;ba_lan::running=false;
    ba_lan::peerClosed=false;ba_lan::submittedFirst=false;ba_lan::matchEnded=false;ba_lan::lobbyReady=false;
    ba_lan::nextFrame=0;ba_lan::bootstrapHash=0;ba_lan::connectStarted=0;ba_lan::failureReason.clear();
    ba_dedicated::installing=false;ba_dedicated::initialized=false;
    ba_dedicated_deck::initialized=false;ba_dedicated_deck::suppress=false;
    releaseRoot(ba_dedicated_deck::accountRoot);
    ba_dedicated_results::pending=false;ba_dedicated_results::delivered=false;
    ba_dedicated_results::gameOverFrame=-1;ba_dedicated_results::winningAlliance=31;
    ba_dedicated_results::concededMask=0;ba_dedicated_results::checksum=0;
    ba_dedicated_results::receivedAt=0;ba_dedicated_results::lastWaitLog=0;ba_dedicated_results::matchId.clear();
    ba_lan_smoke::plan=ba_lan_smoke::Plan{};
    ba::set<Obj>(front,"_playerGameHandle",nullptr);ba::set<Obj>(server,"_playerGameHandle",nullptr);
    ba::dedicatedAssignedSlot=-1;
    lobbyInstalled=false;joined=false;sawWorld=false;abortRequested=false;appliedReady=-1;
    failedAt=0;lastWaitLog=0;blocked=false;
    diagnosticAt=0;diagnosticCount=0;
    if(completed){retryAttempts=0;deferredPlay=false;}
}
static bool retryFromPlay(Obj front,int) {
    if(!ba::dedicated() || !ba_lan::stopped)return false;
    Obj server=ba::read<Obj>(front,0xd8);
    if(joined || !inMenu() || !worldIdle(server)) {
        ba::log("Dedicated Play waits for the old match's native teardown");return true;
    }
    resetAtMenu(front,server,false);
    retryAttempts=0;retryAt=GetTickCount64();deferredPlay=true;
    ba::log("Dedicated connection retry requested from native Play");return true;
}
static void recover(Obj front,Obj server) {
    const ULONGLONG now=GetTickCount64();
    if(!failedAt){failedAt=now;ba_dedicated_deck::updateLobby(front,false);}
    Obj sim=ba::read<Obj>(server,0x140);
    // Do not race the async map callback. Once it finishes, reuse the original
    // reason-1 cleanup, which joins the sim thread and emits native menu flow.
    if(joined && !abortRequested && sim && !ba::read<bool>(server,0xd8) &&
       ba::read<bool>(sim,0x1a0) && ba::read<uint64_t>(sim,0x1a8)) {
        abortRequested=true;ba_bootstrap::awaitingWorld=false;
        int reason=1;bool skipShutdown=false;void* args[]={&reason,&skipShutdown};
        ba::log("Dedicated aborted match: requesting original CleanupGameState(reason=1)");
        try{ba::call(server,"CleanupGameState",2,args);}
        catch(const std::exception& e){ba::log("Dedicated native cleanup reported: %s",e.what());}
        // No direct field-clearing or alternate native destruction on failure.
    }
    if(inMenu() && worldIdle(server) && (!joined || sawWorld || abortRequested)) {
        const std::string reason=ba_lan::failureReason;
        resetAtMenu(front,server,false);
        if(++retryAttempts<=3) {
            retryAt=now+(1000u<<(retryAttempts-1));
            ba::log("Dedicated connection retry %u/3 after: %s",retryAttempts,reason.c_str());
        } else {
            blocked=true;ba_lan::stopped=true;
            ba::log("Dedicated connection unavailable; native Play retries. Last error: %s",reason.c_str());
        }
        return;
    }
    // A stalled native map load cannot safely be reset by clearing our flags.
    // Keep the old roots and prohibit a new world; report a bounded diagnostic.
    if(now-failedAt>120000 && !blocked) {
        blocked=true;ba::log("Dedicated cleanup exceeded 120s; retaining native state, process restart required");
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
    const bool autoReady=smokeMayReady && ba::flag(L"-dedicated-auto-ready") &&
        (!startedSessions || ba::flag(L"-dedicated-auto-rematch"));
    if(deferredPlay || autoReady) {
        deferredPlay=false;
        ba::native<void(*)(Obj,Obj,int,Obj)>(0x3e3c0d0)(front,ba::owner,1,nullptr);
    }
}
static void update(Obj front) {
    if(!ba::dedicated())return;
    try {
        if(!unityThread)unityThread=GetCurrentThreadId();
        if(unityThread!=GetCurrentThreadId())throw std::runtime_error("dedicated lifecycle called off Unity thread");
        Obj server=ba::read<Obj>(front,0xd8),sim=ba::read<Obj>(server,0x140);
        if(!server || !sim)return;
        if(joined && ba::read<bool>(sim,0x1a0) && ba::read<uint64_t>(sim,0x1a8))sawWorld=true;
        postgameDiagnostics(server);
        rematchSmoke(server);
        // User Continue (or native non-result exit), never a synthetic UI click.
        if(joined && sawWorld && inMenu() && worldIdle(server)) {
            const bool completed=ba_dedicated_results::delivered;
            resetAtMenu(front,server,completed);retryAt=GetTickCount64()+500;return;
        }
        if(ba_lan::stopped){if(!blocked)recover(front,server);return;}
        if(joined && ba_local::failed.load())throw std::runtime_error("dedicated local input capture failed");
        if(GetTickCount64()<retryAt)return;
        ba_lan::poll();
        if(ba_lan::welcomed && !lobbyInstalled && inMenu())installLobby(front);
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
    } catch(const std::exception& e){ba_lan::fail("dedicated session update",e);}
}
}
