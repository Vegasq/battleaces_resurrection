#pragma once
// Native Start/Ready requests are not wire transactions: callbacks carry only
// Error and may synchronously enqueue another request. Retain exact ownership.
namespace ba_community_match {
using ba::Obj;using ba_local::Root;
namespace wire=ba_community_wire;
namespace native=ba_community_native;
struct Operation {
    Root message,manager;std::string lobby;uint32_t epoch=0,request=0;
    ba_match_loading::Ticket loadingTicket=0;
    unsigned kind=0,wireKind=0;bool valid=true,cancelled=false;
    bool selectionValid=false;
    wire::Loadout selection;
    ba_cosmetics::FrozenLoadout appearance;
    std::unique_ptr<Root> deckSnapshot;
    Operation(Obj value,Obj owner):message(value),manager(owner){}
};
static auto& operations=*new std::deque<std::unique_ptr<Operation>>();
static std::string acceptedLobby,activeLobby,activeMatch;
static std::unique_ptr<Root> acceptedDeck;
static ba_cosmetics::FrozenLoadout acceptedAppearance;
static wire::Loadout acceptedSelection;
static uint32_t startEpoch=0,readyEpoch=0,activeEpoch=0,returnRequest=0;
static std::string sentReadyLobby;
static uint32_t sentReadyEpoch=0,probeReadyEpoch=0;
static bool awaitingReturn=false,returnAccepted=false,capturing=false,captured=false;
struct AbortRecovery {
    std::string lobby,match,reason;uint32_t epoch=0;
    bool confirmed=false,failedSignal=false,cleanup=false;
    ULONGLONG began=0,lastLog=0;
};
static std::unique_ptr<AbortRecovery> abortRecovery;
static auto& returnedMatches=*new std::deque<std::string>();
static bool returnWasCompleted=false;
static unsigned recoveredAborts=0;
static Obj expectedConnection=nullptr;
static unsigned probeStage=0,probeMatches=0,probeAborts=0;
static ULONGLONG probeAt=0;
static std::unique_ptr<Root> probeButton;
struct LoadingAttempt {
    ba_match_loading::Ticket ticket=0;
    std::string lobby;uint32_t epoch=0;unsigned kind=0;
    bool pending=false,accepted=false,seenStarting=false,cancelRequested=false;
};
static LoadingAttempt loading;
static bool loadingOwns(const Operation& op) {
    return loading.pending && op.loadingTicket && op.loadingTicket==loading.ticket &&
        op.lobby==loading.lobby && op.epoch==loading.epoch;
}
static void loadingCancel(const char* reason) {
    ba_match_loading::cancel(loading.ticket,reason);loading.pending=false;
}
static void loadingError(const char* message) {
    ba_match_loading::error(loading.ticket,message);loading.pending=false;
}
static void loadingFailure() {loadingError("Connection lost while starting the match.");}
static void loadingQueued(Operation& op) {
    if(!op.valid)return;
    const auto& lobby=native::authority;
    const bool same=loading.lobby==op.lobby && loading.epoch==op.epoch;
    const bool readySent=op.kind==16 && sentReadyLobby==op.lobby && sentReadyEpoch==op.epoch;
    if(same && (loading.pending || loading.accepted || readySent)) {
        op.loadingTicket=loading.ticket;return;
    }
    // Enqueue precedes the native manager's pending-pointer assignment. Do not
    // call back here; qualify the click/automatic Ready against current authority.
    if(op.lobby.empty() || awaitingReturn || !activeMatch.empty() || abortRecovery || readySent)return;
    const bool valid=op.kind==15?(lobby.phase==wire::Open && lobby.host==ba_community::welcome.profile &&
        lobby.members.size()==2 && op.epoch==lobby.epoch+1):
        (lobby.phase==wire::Starting && lobby.host!=ba_community::welcome.profile && op.epoch==lobby.epoch);
    if(!valid)return;
    loading=LoadingAttempt{};loading.lobby=op.lobby;loading.epoch=op.epoch;loading.kind=op.kind;loading.pending=true;
    loading.ticket=ba_match_loading::begin(ba_match_loading::Source::Custom,
        "custom:"+op.lobby+":"+std::to_string(op.epoch),ba_match_loading::Stage::Preparing);
    op.loadingTicket=loading.ticket;
}
static void loadingUpdate() {
    if(!loading.pending)return;
    const auto& lobby=native::authority;
    if(lobby.phase==wire::None || lobby.id!=loading.lobby) {loadingCancel("left custom lobby");return;}
    if(lobby.epoch>loading.epoch || (lobby.epoch==loading.epoch && lobby.phase==wire::Open && loading.seenStarting)) {
        if(loading.cancelRequested && lobby.phase==wire::Open && lobby.reason=="player cancelled start")
            loadingCancel("native Ready cancelled after deck change");
        else loadingError("Match start was cancelled. Please try again.");
        return;
    }
    // Initial Open at epoch-1 is the host's legitimate deck/Start preparation.
    if(lobby.epoch!=loading.epoch)return;
    if(lobby.phase==wire::Starting) {
        loading.seenStarting=true;
        if(loading.kind==15)loading.accepted=true;
        ba_match_loading::advance(loading.ticket,ba_match_loading::Stage::Waiting);
    } else if(lobby.phase==wire::Loading || lobby.phase==wire::Running) {
        loading.seenStarting=true;loading.accepted=true;
        if(activeLobby==loading.lobby && activeEpoch==loading.epoch && !activeMatch.empty() &&
           activeMatch==ba_lan::dedicatedMatchId && ba_dedicated_session::joined && ba_lan::running &&
           ba_lan::worldReady && ba_dedicated::loadingInGame()) {
            ba::log("Match loading readiness: source=custom ticket=%llu nativeInGame=1 running=1 localReady=1 worldReady=1 lobby=%s epoch=%u match=%s",
                static_cast<unsigned long long>(loading.ticket),loading.lobby.c_str(),loading.epoch,activeMatch.c_str());
            ba_match_loading::success(loading.ticket);loading.pending=false;return;
        }
        ba_match_loading::advance(loading.ticket,!ba_lan::worldReady?ba_match_loading::Stage::Loading:
            !ba_lan::running?ba_match_loading::Stage::Waiting:ba_match_loading::Stage::Starting);
    } else if(lobby.phase==wire::Results)loadingError("The match could not start.");
}
static void reset() {
    loadingCancel("community session reset");loading=LoadingAttempt{};
    operations.clear();acceptedLobby.clear();activeLobby.clear();activeMatch.clear();
    acceptedDeck.reset();acceptedAppearance={};acceptedSelection={};
    startEpoch=readyEpoch=activeEpoch=returnRequest=0;awaitingReturn=returnAccepted=capturing=captured=false;
    sentReadyLobby.clear();sentReadyEpoch=probeReadyEpoch=0;
    expectedConnection=nullptr;probeStage=probeMatches=probeAborts=0;probeAt=0;probeButton.reset();
    abortRecovery.reset();returnedMatches.clear();returnWasCompleted=false;recoveredAborts=0;
}
static wire::Loadout selectedLoadout(Obj front) {
    Root deck(ba_dedicated_deck::selectedProto(front));return ba_cosmetics::wireLoadout(deck.get(),ba_cosmetics::currentSelection(front));
}
static wire::Loadout memberLoadout(const wire::Member& member) {
    wire::Loadout value;value.deck=member.deck;value.full=member.full;value.cosmetics=member.cosmetics;return value;
}
static const wire::Member* member() {
    for(const auto& row:native::authority.members)if(row.profile==ba_community::welcome.profile)return &row;
    return nullptr;
}
static void enqueue(Obj front,Obj message,Obj owner) {
    wire::require(operations.size()<32,"native community start queue capacity");
    auto op=std::make_unique<Operation>(message,owner);op->lobby=native::authority.id;
    Obj actions=ba::get<Obj>(message,"updateActions_");const int count=ba_local::count(actions);
    wire::require(count>0 && count<=32,"native community start action capacity");
    for(int index=0;index<count;++index) {
        void* args[]={&index};Root action(ba::call(actions,"get_Item",1,args));
        const auto kind=static_cast<unsigned>(ba::get<int>(action.get(),"updateActionsCase_"));
        if(!op->kind)op->kind=kind;
        op->valid&=(kind==15 || kind==16) && kind==op->kind;
    }
    op->epoch=native::authority.epoch+(op->kind==15 && native::authority.phase==wire::Open?1:0);
    if(op->valid) {
        op->selectionValid=ba_dedicated_deck::canReady(front);
        if(op->selectionValid) {
            op->deckSnapshot=std::make_unique<Root>(ba_dedicated_deck::selectedProto(front));
            op->appearance=ba_cosmetics::freezeHuman(front,op->deckSnapshot->get());
            op->selection=ba_cosmetics::wireLoadout(op->deckSnapshot->get(),op->appearance);
        }
    }
    loadingQueued(*op);
    ba::log("Community native start queued: kind=%u actions=%d epoch=%u native=%p; deferred callback",op->kind,count,op->epoch,message);
    operations.push_back(std::move(op));
}
static bool owned(const Operation& op) {
    return op.manager.get() && ba::get<Obj>(op.manager.get(),"_frontServer")==ba_dedicated_session::observedFront &&
        ba::get<Obj>(op.manager.get(),"_pendingLobbyUpdateRequest")==op.message.get();
}
static void complete(Obj front,std::unique_ptr<Operation> op,bool success,const char* rejection=nullptr) {
    if(!owned(*op)) {
        ba::log("Community native start completion discarded after manager release: kind=%u epoch=%u",op->kind,op->epoch);return;
    }
    wire::require(native::authority.id==op->lobby && native::authority.phase!=wire::None &&
        ba::get<Obj>(front,"_party"),"native community update lost active lobby");
    Root response(ba::make("FrontPb","UpdateLobbyStateResponse")),state(native::notification());
    ba::set<Obj>(response.get(),"currentState_",state.get());
    // Settle this ticket before the native callback: it may enqueue a new
    // attempt, including a valid retry at the same not-yet-accepted epoch.
    if(!success && rejection && loadingOwns(*op) && !loading.accepted)loadingError(rejection);
    ba::native<void(*)(Obj,Obj,int,Obj)>(0x3e485f0)(front,response.get(),success?0:2,nullptr);
    // SendUpdateActions may replace this pointer reentrantly with a NEW request.
    wire::require(!owned(*op),"native start response retained old pending request");
    ba::log("Community native start completed: kind=%u epoch=%u success=%d oldPendingReleased=1 next=%p",
        op->kind,op->epoch,success?1:0,ba::get<Obj>(op->manager.get(),"_pendingLobbyUpdateRequest"));
}
static bool acknowledge(Obj front,const wire::Ack& ack) {
    if(ack.request==returnRequest && returnRequest) {
        wire::require(ack.kind==wire::Return && ack.success,"community match return rejected");
        returnRequest=0;returnAccepted=true;return true;
    }
    for(auto it=operations.begin();it!=operations.end();++it) {
        auto& op=**it;if(!op.request || op.request!=ack.request)continue;
        wire::require(ack.kind==op.wireKind,"community start acknowledgement kind mismatch");
        if((op.wireKind==wire::SetDeck || op.wireKind==wire::SetLoadout) && ack.success){op.request=0;op.wireKind=0;return true;}
        // A successful wire ACK describes the decision then. A later rollback,
        // departure or new epoch may already have superseded it in ordered
        // authority. Never replay that old success into the current prediction.
        bool success=ack.success && !op.cancelled && owned(op) && native::authority.id==op.lobby &&
            native::authority.epoch==op.epoch && native::authority.phase>=wire::Starting &&
            native::authority.phase<=wire::Running && !abortRecovery;
        if(success) {
            if(ack.kind==wire::Start)wire::require(ack.object==op.lobby,"community Start ACK changed lobby identity");
            acceptedLobby=op.lobby;
            wire::require(op.selectionValid && op.deckSnapshot,"custom acceptance has no frozen human intent");
            acceptedDeck=std::move(op.deckSnapshot);acceptedAppearance=op.appearance;acceptedSelection=op.selection;
            (op.kind==15?startEpoch:readyEpoch)=op.epoch;
            if(loadingOwns(op))loading.accepted=true;
        }
        if(ack.success && op.cancelled && loadingOwns(op))loadingCancel("native Ready cancellation accepted");
        const bool duplicateProbe=success && op.kind==16 && ba::flag(L"-community-match-duplicate-smoke") && probeReadyEpoch!=op.epoch;
        if(duplicateProbe)probeReadyEpoch=op.epoch;
        auto done=std::move(*it);operations.erase(it);
        complete(front,std::move(done),success,ack.success?nullptr:"The server could not start this match. Please try again.");
        if(duplicateProbe) {
            Root state(native::notification());ba::native<void(*)(Obj,Obj,Obj)>(0x3e48820)(front,state.get(),nullptr);
            ba::log("COMMUNITY MATCH SMOKE replayed native Starting after Ready ACK; duplicate must not reach wire");
        }
        return true;
    }
    return false;
}
static void aborted(Obj front,const wire::Aborted& message) {
    // A result already validated for this exact match owns its normal Continue
    // flow. A delayed duplicate from the previous returned match owns nothing.
    bool returnedBefore=false;for(const auto& match:returnedMatches)returnedBefore|=message.match==match;
    if(returnedBefore || (awaitingReturn && message.match==activeMatch) ||
       (message.match==ba_dedicated_results::matchId && ba_lan::matchEnded)) {
        ba::log("Community stale abort ignored: match=%s; validated result/return retained",message.match.c_str());
        if(!abortRecovery)ba_community::abortPending=false;
        return;
    }
    if(abortRecovery) {
        wire::require(abortRecovery->match==message.match,"conflicting community abort");ba_community::abortPending=true;return;
    }
    const auto& lobby=native::authority;
    wire::require(!awaitingReturn && ba_lan::welcomed && !lobby.id.empty() && lobby.epoch &&
        (lobby.phase==wire::Loading || lobby.phase==wire::Running) &&
        (lobby.match.empty() || lobby.match==message.match) &&
        (ba_lan::dedicatedMatchId.empty() || ba_lan::dedicatedMatchId==message.match) &&
        (activeMatch.empty() || activeMatch==message.match),"community abort does not own active attempt");
    abortRecovery=std::make_unique<AbortRecovery>();auto& abort=*abortRecovery;
    ba_community::abortPending=true;
    abort.lobby=lobby.id;abort.match=message.match;abort.reason=message.reason;abort.epoch=lobby.epoch;
    abort.began=GetTickCount64();
    if(loading.pending && loading.lobby==abort.lobby && loading.epoch==abort.epoch)
        loadingError("The match could not start.");
    ba::log("Community abort pending Results: lobby=%s match=%s epoch=%u joined=%d mapLoading=%d reason=%s",
        abort.lobby.c_str(),abort.match.c_str(),abort.epoch,ba_dedicated_session::joined?1:0,
        ba::read<bool>(ba::read<Obj>(front,0xd8),0xd8)?1:0,abort.reason.c_str());
}
static void snapshot(Obj front) {
    loadingUpdate();
    if(abortRecovery && !abortRecovery->confirmed) {
        auto& abort=*abortRecovery;const auto& lobby=native::authority;
        wire::require(lobby.id==abort.lobby && lobby.epoch==abort.epoch && lobby.phase==wire::Results &&
            lobby.match==abort.match,"community abort Results identity mismatch");
        abort.confirmed=true;activeLobby=abort.lobby;activeMatch=abort.match;activeEpoch=abort.epoch;
        ba_lan::running=false;ba_lan::frames.clear();ba_local::ready.store(false);
        ba::log("Community abort validated: match=%s epoch=%u; control connection retained",activeMatch.c_str(),activeEpoch);
    }
    if(awaitingReturn && native::authority.phase==wire::Open && native::authority.id==activeLobby) {
        wire::require(ba_dedicated_session::inMenu() && !ba_dedicated_session::joined && ba::lanSlot()==-1,
            "community reopened before local world teardown");
        native::restoreIdentity(front);native::installedLobby=activeLobby;
        // No synthetic Create/Invite response: the existing LobbyStateUpdated
        // subscription initializes a new prediction from this authoritative state.
        ba_community_invites::reconcileParty(front);
        Obj party=ba::get<Obj>(front,"_party");if(party && returnWasCompleted)ba::set<bool>(party,"HasPlayedMatch",true);
        ba::log("Community native lobby restored: lobby=%s epoch=%u members=%llu canonicalAlias=%llu seat=-1",
            activeLobby.c_str(),activeEpoch,static_cast<unsigned long long>(native::authority.members.size()),
            static_cast<unsigned long long>(ba_community::alias(ba_community::welcome.profile)));
        if(abortRecovery) {
            ++recoveredAborts;
            ba::log("Community aborted match recovered: match=%s epoch=%u; same lobby/presence, seat=-1, no result fabricated",
                activeMatch.c_str(),activeEpoch);
        }
        if(returnedMatches.size()==16)returnedMatches.pop_front();returnedMatches.push_back(activeMatch);
        abortRecovery.reset();ba_community::abortPending=false;
        awaitingReturn=false;activeLobby.clear();activeMatch.clear();activeEpoch=0;
    }
}
static void dispatch(Obj front) {
    for(unsigned completed=0;!operations.empty() && completed<32;++completed) {
        auto& op=*operations.front();if(op.request)return;
        if(!owned(op)) {operations.pop_front();continue;}
        const auto& lobby=native::authority;
        bool valid=op.valid && op.lobby==lobby.id && !op.lobby.empty() && !awaitingReturn && activeMatch.empty() && !abortRecovery;
        const bool duplicate=valid && acceptedLobby==op.lobby && lobby.epoch==op.epoch && lobby.phase>=wire::Starting &&
            (op.kind==15?startEpoch:readyEpoch)==op.epoch;
        if(duplicate) {
            auto done=std::move(operations.front());operations.pop_front();
            ba::log("Community duplicate native start settled without wire replay: kind=%u epoch=%u",done->kind,done->epoch);
            complete(front,std::move(done),true);continue;
        }
        // A definitive rejected Ready is not retried for the same attempt.
        // A newer epoch can still need Ready after an old request's late ACK.
        const bool duplicateReady=valid && op.kind==16 && sentReadyLobby==op.lobby && sentReadyEpoch==op.epoch;
        if(duplicateReady)valid=false;
        valid&=op.kind==15?(lobby.phase==wire::Open && lobby.host==ba_community::welcome.profile &&
            lobby.members.size()==2 && op.epoch==lobby.epoch+1):
            (lobby.phase==wire::Starting && lobby.host!=ba_community::welcome.profile && op.epoch==lobby.epoch);
        if(!valid) {
            const bool rejected=!duplicateReady && op.lobby==lobby.id &&
                (op.kind==15?(lobby.phase==wire::Open && op.epoch==lobby.epoch+1):
                    (lobby.phase==wire::Starting && op.epoch==lobby.epoch));
            auto done=std::move(operations.front());operations.pop_front();
            complete(front,std::move(done),false,rejected?"Unable to start this match. Please try again.":nullptr);continue;
        }
        // Finish earlier native deck edits first. Poll's ordered ACK events are
        // drained before this dispatch, so authority now includes their revision.
        bool pendingDeck=false;for(const auto& item:ba_community::pending)pendingDeck|=item.second.kind==wire::SetDeck || item.second.kind==wire::SetLoadout;
        if(pendingDeck)return;
        const auto* local=member();wire::require(local!=nullptr,"community local member missing");
        const bool canReady=op.selectionValid && ba_dedicated_deck::canReady(front);
        if(op.kind==15 && !canReady) {
            auto done=std::move(operations.front());operations.pop_front();
            complete(front,std::move(done),false,"Choose a valid deck before starting the match.");continue;
        }
        const auto current=selectedLoadout(front);
        const bool changed=!canReady || current!=op.selection;
        if(op.kind==15 && changed) {
            auto done=std::move(operations.front());operations.pop_front();
            complete(front,std::move(done),false,"Your loadout changed. Please start again.");continue;
        }
        const auto id=ba_community::nextRequest();
        if(op.kind==15 && op.selection!=memberLoadout(*local)) {
            op.wireKind=op.selection.full?wire::SetLoadout:wire::SetDeck;
            op.request=ba_community::send(op.selection.full?wire::setLoadout(id,op.selection):wire::setDeck(id,op.selection.deck));
            ba_client::deckSubmitted(op.request,op.selection);
        } else if(op.kind==15) {
            op.wireKind=wire::Start;op.request=ba_community::send(wire::start(id,lobby));
        } else {
            // A deck edit racing the remote host must cancel the attempt instead
            // of silently loading a different frozen deck.
            op.cancelled=changed || op.selection!=memberLoadout(*local);
            sentReadyLobby=op.lobby;sentReadyEpoch=op.epoch;
            op.wireKind=wire::Ready;op.request=ba_community::send(wire::ready(id,lobby,!op.cancelled));
        }
        if(loadingOwns(op)) {
            loading.cancelRequested=op.cancelled;
            ba_match_loading::advance(op.loadingTicket,(op.wireKind==wire::SetDeck || op.wireKind==wire::SetLoadout)?
                ba_match_loading::Stage::Preparing:ba_match_loading::Stage::Waiting);
        }
        ba::log("Community start transaction dispatched: nativeKind=%u wireKind=%u request=%u epoch=%u cancel=%d",
            op.kind,op.wireKind,op.request,op.epoch,op.cancelled?1:0);return;
    }
}
static void captureJoin(Obj server,Obj connection,bool spectator) {
    wire::require(capturing && !captured && !spectator && connection==expectedConnection &&
        native::owns(ba_dedicated_session::observedFront) && server==ba::read<Obj>(ba_dedicated_session::observedFront,0xd8),
        "unowned community custom join");
    captured=true;
}
static void begin(Obj front) {
    const auto& lobby=native::authority;
    if(ba_community::abortPending || abortRecovery || ba_dedicated_session::joined || awaitingReturn || !activeMatch.empty() || lobby.phase!=wire::Loading ||
        lobby.match.empty() || ba_lan::bootstrap.empty() || !operations.empty())return;
    const bool host=lobby.host==ba_community::welcome.profile;
    if(acceptedLobby!=lobby.id || (host?startEpoch:readyEpoch)!=lobby.epoch)return;
    Root owner(native::manager(front));
    wire::require(ba_lan::welcomed && lobby.match==ba_lan::dedicatedMatchId && native::installedLobby==lobby.id &&
        native::requests.empty() && owner.get() && !ba::get<Obj>(owner.get(),"_pendingLobbyUpdateRequest") &&
        !ba::get<Obj>(owner.get(),"_pendingCreateLobbyRequest"),"community bootstrap ownership mismatch");
    const int slot=ba::lanSlot();wire::require(slot>=0 && slot<static_cast<int>(lobby.members.size()) &&
        lobby.members[slot].profile==ba_community::welcome.profile && ba_lan::dedicatedDeck.size()==32,
        "community frozen seat mismatch");
    for(size_t i=0;i<8;++i)wire::require(ba_lan::u32(ba_lan::dedicatedDeck,4*i)==lobby.members[slot].deck[i],"community frozen deck mismatch");
    wire::require(acceptedDeck && acceptedSelection==memberLoadout(lobby.members[slot]),"custom full intent differs from authoritative selection");
    if(acceptedSelection.full) {
        Root encoded(ba_lan::byteString(ba_lan::bootstrap)),data(ba_lan_bootstrap::decodeGameDataLan(encoded.get()));
        Obj config=ba::get<Obj>(data.get(),"gameConfig_"),armies=ba::get<Obj>(config,"armies_");
        wire::require(ba_local::count(armies)==2,"custom cosmetic bootstrap army count");
        Obj army=ba_lan_bootstrap::at(armies,slot),deck=ba::get<Obj>(army,"deck_");
        Obj units=ba::get<Obj>(deck,"units_");wire::require(ba_local::count(units)==8,"custom cosmetic bootstrap units missing");
        for(int i=0;i<8;++i)wire::require(ba_lan_bootstrap::uintAt(units,i)==acceptedSelection.deck[i],"custom cosmetic bootstrap units differ");
        ba_cosmetics::validateHumanDeck(deck,acceptedAppearance);
        wire::require(ba::get<uint32_t>(army,"armyId_")==static_cast<uint32_t>(slot) &&
            ba::get<uint32_t>(army,"portraitId_")==acceptedAppearance.portrait &&
            ba::get<uint32_t>(army,"bannerId_")==acceptedAppearance.banner,"custom cosmetic bootstrap roles differ");
    }
    Root message(ba::make("FrontPb","CustomGameCreatedNotification")),connection(ba::make("CommonPb","GameConnectionInfo")),handle(ba::make("CommonPb","GameHandle"));
    ba::set<Obj>(handle.get(),"gameName_",ba::str(lobby.match.c_str()));
    ba::set<Obj>(connection.get(),"gameHandle_",handle.get());
    ba::set<Obj>(connection.get(),"address_",ba::str(ba::argument(L"-dedicated-server=").c_str()));
    ba::set<bool>(connection.get(),"isSpectator_",false);
    ba::set<Obj>(message.get(),"createdGame_",connection.get());ba::set<Obj>(message.get(),"playerHandle_",native::localRaw());
    wire::require(ba::get<int>(front,"_lastCustomGameMode")==1,"community custom mode changed");
    if(ba::unified())ba_client::acquireRemote(front,lobby.match);
    activeLobby=lobby.id;activeMatch=lobby.match;activeEpoch=lobby.epoch;
    if(loading.pending && loading.lobby==activeLobby && loading.epoch==activeEpoch)
        ba_match_loading::advance(loading.ticket,ba_match_loading::Stage::Loading);
    capturing=true;captured=false;expectedConnection=connection.get();
    try {ba::native<void(*)(Obj,Obj,int,Obj)>(0x3e40410)(front,message.get(),0,nullptr);}
    catch(...){capturing=false;expectedConnection=nullptr;throw;}
    capturing=false;expectedConnection=nullptr;
    wire::require(captured && !ba_lan::stopped,"native CustomGameCreated did not consume owned join");
    native::closeLobbyWithReason(front,3);
    ba_dedicated_session::joined=true;++ba_dedicated_session::startedSessions;
    Root encoded(ba_lan::byteString(ba_lan::bootstrap));
    Root identity(ba_lan_bootstrap::identityLan(front,slot));
    Obj profile=ba::get<Obj>(ba::get<Obj>(front,"_accountService"),"<ProfileCache>k__BackingField");
    ba::set<uint64_t>(profile,"steamId_",static_cast<uint64_t>(slot+1));
    ba_bootstrap::beginJoined(front,encoded.get(),identity.get(),true);
    ba::log("Community native custom match joined: lobby=%s match=%s epoch=%u seat=%d session=%u BA_RESURRECTION_COMMUNITY_MATCH_V1",
        activeLobby.c_str(),activeMatch.c_str(),activeEpoch,slot,ba_dedicated_session::startedSessions);
}
static void normalizeJoin(Obj action) {
    wire::require(!activeMatch.empty() && acceptedDeck,"custom JoinArmy has no owned frozen intent");
    ba_cosmetics::applyFrozenJoin(action,acceptedDeck->get(),acceptedAppearance);
}
static void returned(Obj front,Obj server) {
    wire::require(!activeMatch.empty() && activeMatch==ba_lan::dedicatedMatchId && !awaitingReturn &&
        ba_dedicated_results::delivered && !ba_lan::stopped && ba_community::online,"community return before valid result/teardown");
    awaitingReturn=true;returnAccepted=false;returnWasCompleted=true;
    loadingCancel("native custom match returned to menu");
    ba_dedicated_session::resetAtMenu(front,server,true,true);
    native::restoreIdentity(front);
    returnRequest=ba_community::send(wire::returned(ba_community::nextRequest(),activeMatch));
    ba::log("Community native match return: match=%s lobby=%s epoch=%u request=%u; native world idle, presence retained",
        activeMatch.c_str(),activeLobby.c_str(),activeEpoch,returnRequest);
}
static void recoverAbort(Obj front) {
    if(!abortRecovery || awaitingReturn || ba::read<bool>(ba::owner,0x280))return;
    auto& abort=*abortRecovery;
    if(!abort.confirmed) {
        wire::require(GetTickCount64()-abort.began<15000,"community abort missing authoritative Results");return;
    }
    Obj server=ba::read<Obj>(front,0xd8),sim=ba::read<Obj>(server,0x140);
    if(ba_dedicated_session::joined) {
        // Wait for the original async map callback; do not cancel or clear its
        // flags. Cleanup owns simulation shutdown and the native menu signal.
        if(!abort.cleanup && !ba::read<bool>(server,0xd8) && ba::read<bool>(sim,0x1a0) && ba::read<uint64_t>(sim,0x1a8)) {
            abort.cleanup=true;ba_bootstrap::awaitingWorld=false;
            int reason=1;bool stay=false;void* args[]={&reason,&stay};
            ba::log("Community abort native CleanupGameState: match=%s mapLoading=0 active=1",abort.match.c_str());
            ba::call(server,"CleanupGameState",2,args);
        }
    } else if(!abort.failedSignal && operations.empty()) {
        Obj fsm=ba::read<Obj>(ba::owner,0x2b0),predict=ba::read<Obj>(ba::owner,0x2c8);
        if(predict && fsm && ba::get<Obj>(fsm,"_currentState")==predict &&
           // Predict uses UI GameMode7 (custom1v1), not CommonPb.GameMode1.
           ba::read<Obj>(predict,0x18)==ba::owner && ba::read<int>(predict,0x20)==7 && !ba::read<bool>(predict,0x28)) {
            Root owner(native::manager(front));
            wire::require(native::installedLobby==abort.lobby && owner.get() &&
                ba::call(owner.get(),"get_PredictedCustomGameLobby") && ba::get<Obj>(front,"_party") &&
                !ba::get<Obj>(owner.get(),"_pendingLobbyUpdateRequest") && !ba::get<Obj>(owner.get(),"_pendingCreateLobbyRequest"),
                "community setup failure lost native lobby ownership");
            abort.failedSignal=true;
            // MainMenu does not listen; wait for the actual Predict state.
            // Retain its existing lobby/party so native ReturnToCustomGameLobby
            // can navigate back without creating a new server lobby.
            ba::native<void(*)(Obj,Obj,int,Obj)>(0x3e40410)(front,nullptr,2,nullptr);
            wire::require(ba::read<bool>(predict,0x24),"native Predict did not consume setup failure");
            ba::log("Community setup failure delivered to native Predict: match=%s; existing lobby retained",abort.match.c_str());
        }
    }
    Obj menu=ba::read<Obj>(ba::owner,0x2c0);
    if((abort.cleanup || abort.failedSignal) && operations.empty() &&
       ba_dedicated_session::inMenu() && ba_dedicated_session::worldIdle(server) &&
       !ba::read<bool>(menu,0x21) && !ba::read<bool>(menu,0x24) && !ba::read<bool>(menu,0x2c)) {
        awaitingReturn=true;returnAccepted=false;returnWasCompleted=false;
        ba_dedicated_session::resetAtMenu(front,server,false,true);
        native::restoreIdentity(front);
        returnRequest=ba_community::send(wire::returned(ba_community::nextRequest(),activeMatch));
        ba::log("Community aborted match return: match=%s lobby=%s epoch=%u request=%u; native world idle, presence retained",
            activeMatch.c_str(),activeLobby.c_str(),activeEpoch,returnRequest);
        return;
    }
    const auto now=GetTickCount64();
    if(now-abort.lastLog>10000) {
        abort.lastLog=now;
        ba::log("Community abort waiting for native teardown: match=%s elapsed=%llu menu=%d active=%d mapLoading=%d failedSignal=%d cleanup=%d operations=%llu",
            abort.match.c_str(),static_cast<unsigned long long>(now-abort.began),ba_dedicated_session::inMenu()?1:0,
            ba::read<bool>(sim,0x1a0)?1:0,ba::read<bool>(server,0xd8)?1:0,abort.failedSignal?1:0,abort.cleanup?1:0,
            static_cast<unsigned long long>(operations.size()));
    }
}
static void update(Obj front) {
    dispatch(front);
    if(abortRecovery){recoverAbort(front);return;}
    Obj server=ba::read<Obj>(front,0xd8);
    if(ba_dedicated_session::joined && ba_dedicated_session::sawWorld &&
       ba_dedicated_session::inMenu() && ba_dedicated_session::worldIdle(server)) {
        returned(front,server);return;
    }
    const auto& lobby=native::authority;
    if(lobby.phase==wire::Starting && lobby.id==native::installedLobby && lobby.host!=ba_community::welcome.profile &&
        (sentReadyLobby!=lobby.id || sentReadyEpoch!=lobby.epoch) && operations.empty()) {
        Root owner(native::manager(front));
        if(owner.get() && !ba::get<Obj>(owner.get(),"_pendingLobbyUpdateRequest") &&
            ba::call(owner.get(),"get_PredictedCustomGameLobby")) {
            Root state(native::notification());ba::native<void(*)(Obj,Obj,Obj)>(0x3e48820)(front,state.get(),nullptr);
        }
    }
    begin(front);
    loadingUpdate();
}
static void smoke(Obj front); // Original UI actions below, opt-in only.
}

extern "C" __declspec(dllexport) void OfflineCommunityJoinGame(void* server,void* connection,bool spectator,void* methodInfo) {
    ba::init();
    if(!ba::community()){ba::native<void(*)(ba::Obj,ba::Obj,bool,ba::Obj)>(0x3e53940)(server,connection,spectator,methodInfo);return;}
    try{ba_community_match::captureJoin(server,connection,spectator);}
    catch(const std::exception& e){ba_lan::fail("community custom join",e);}
}

namespace ba_community_match {
static void smoke(Obj front) {
    const bool host=ba::flag(L"-community-match-host-smoke"),guest=ba::flag(L"-community-match-guest-smoke");
    if(!host && !guest)return;
    const auto now=GetTickCount64();if(!probeAt){probeAt=now+2500;return;}if(now<probeAt)return;
    Root owner(native::manager(front));wire::require(owner.get()!=nullptr,"community match smoke manager missing");
    if(probeStage==4 && recoveredAborts>probeAborts && !awaitingReturn && returnAccepted &&
       native::authority.phase==wire::Open && !ba_dedicated_session::joined) {
        ba_community_invites::verifyParty(front,2,host);
        wire::require(ba::lanSlot()==-1 && !ba::get<Obj>(owner.get(),"_pendingLobbyUpdateRequest"),"abort retained seat/request");
        probeAborts=recoveredAborts;probeStage=3;
        probeAt=now+(guest && ba::flag(L"-community-match-late-guest-smoke")?4000:1500);
        ba::log("COMMUNITY MATCH SMOKE recovered abort; starting two successful native matches on the same lobby");return;
    }
    // The host may start while the guest's diagnostic delay is still active.
    // Accepting the actual next match is stronger evidence than observing a
    // transient Open lobby. Never leave the result observer waiting for Open
    // after this process has already joined that match.
    if(guest && probeStage==3 && ba_dedicated_session::joined && !activeLobby.empty() && activeEpoch &&
       !activeMatch.empty() && activeMatch==ba_lan::dedicatedMatchId) {
        probeStage=4;
        ba::log("COMMUNITY MATCH SMOKE guest result observer armed from accepted match: match=%s epoch=%u",activeMatch.c_str(),activeEpoch);
    }
    if(probeStage==0 && native::directory.players.size()>=2) {
        if(host) {
            Root controller(ba::get<Obj>(owner.get(),"_menuFlowController")),link(ba::make("Uncapped.UI","UILink"));
            ba::set<int>(link.get(),"PrefabKey",97);probeStage=1;
            ba::native<void(*)(Obj,Obj,Obj)>(0x3d52440)(controller.get(),link.get(),nullptr);
        } else {
            Root panel(ba_community_popup::ready());if(!panel.get() || ba_community_popup::owned->paint)return;
            probeStage=3;ba::native<void(*)(Obj,Obj)>(0x3d24700)(panel.get(),nullptr);
            ba::log("COMMUNITY MATCH SMOKE guest native Accept (NOT manual UI input)");
        }
    } else if(probeStage==1 && !native::installedLobby.empty() && native::requests.empty()) {
        Root main(ba_community_roster::mainScreen());if(!main.get())return;
        probeButton=std::make_unique<Root>(ba_community_roster::pickerButton(main.get()));
        ba::native<void(*)(Obj,Obj)>(0x3d62c40)(probeButton->get(),nullptr);probeStage=2;probeAt=now+500;
    } else if(probeStage==2) {
        for(const auto& row:ba_community_roster::rows)if(row->profile!=ba_community::welcome.profile && ba_community_invites::canInvite(row->profile)) {
            probeStage=3;ba::native<void(*)(Obj,Obj)>(0x3ca8f20)(row->row.get(),nullptr);
            ba::call(probeButton->get(),"Hide");probeButton.reset();
            ba::log("COMMUNITY MATCH SMOKE host native picker Invite (NOT manual UI input)");break;
        }
    } else if(probeStage==3 && native::authority.phase==wire::Open && native::authority.members.size()==2 &&
        native::requests.empty() && ba_community_invites::operations.empty() && !native::installedLobby.empty()) {
        ba_community_invites::verifyParty(front,2,host);
        if(host) {
            Root main(ba_community_roster::mainScreen());if(!main.get())return;
            if(probeMatches==1 && ba::flag(L"-community-cosmetics-smoke"))ba_cosmetics::practiceRematchSmoke(front);
            probeStage=4;ba::native<void(*)(Obj,Obj)>(0x3cb1080)(main.get(),nullptr);
            wire::require(ba::get<Obj>(owner.get(),"_pendingLobbyUpdateRequest") && !operations.empty(),"native Start did not retain pending request");
            if(ba::flag(L"-community-match-duplicate-smoke")) {
                ba::native<void(*)(Obj,Obj)>(0x3cb1080)(main.get(),nullptr);
                wire::require(ba_local::count(ba::get<Obj>(owner.get(),"_deferredLobbyUpdateActions"))>0,"duplicate Start did not defer action");
            }
            ba::log("COMMUNITY MATCH SMOKE host native Start returned pending; round=%u (NOT manual UI input)",probeMatches);
        } else probeStage=4;
    } else if(probeStage==4 && host && !ba_dedicated_session::joined && activeMatch.empty() &&
        native::authority.phase==wire::Open && operations.empty() && !ba::get<Obj>(owner.get(),"_pendingLobbyUpdateRequest")) {
        Root predicted(ba::call(owner.get(),"get_PredictedCustomGameLobby"));
        wire::require(predicted.get() && ba::get<int>(ba::call(predicted.get(),"get_CurrentState"),"lobbyStatus_")==2,
            "rejected Start did not restore full native lobby prediction");
        probeStage=3;probeAt=now+250;
        ba::log("COMMUNITY MATCH SMOKE rejected/timed-out Start rolled back to full native lobby; retry deferred");
    } else if(probeStage==4 && ba_dedicated_session::joined && ba_dedicated_results::delivered &&
        ba_dedicated_session::worldIdle(ba::read<Obj>(front,0xd8))) {
        Obj controller=ba::get<Obj>(ba::owner,"<UIPostGameController>k__BackingField");if(!controller)return;
        Obj state=ba::get<Obj>(controller,"_matchResultState"),fsm=ba::get<Obj>(controller,"_fsm");
        if(!state || !fsm || ba::get<Obj>(fsm,"_currentState")!=state)return;
        Obj view=ba::get<Obj>(state,"_matchResultVM");if(!view)return;
        Obj navigation=ba::get<Obj>(view,"_navigationStack"),stack=navigation?ba::get<Obj>(navigation,"_navigationStack"):nullptr;
        if(!stack || ba_local::count(stack))return;
        probeStage=5;probeAt=now+1000;
        ba::log("COMMUNITY MATCH SMOKE native result ready; round=%u match=%s",probeMatches,activeMatch.c_str());
    } else if(probeStage==5) {
        Obj controller=ba::get<Obj>(ba::owner,"<UIPostGameController>k__BackingField");
        Obj view=ba::get<Obj>(ba::get<Obj>(controller,"_matchResultState"),"_matchResultVM");
        probeStage=6;ba::call(view,"OnContinue");
        ba::log("COMMUNITY MATCH SMOKE native Continue (NOT manual UI input)");
    } else if(probeStage==6 && !awaitingReturn && returnAccepted && native::authority.phase==wire::Open &&
        !native::installedLobby.empty() && !ba_dedicated_session::joined) {
        ba_community_invites::verifyParty(front,2,host);
        wire::require(ba::lanSlot()==-1 && !ba::get<Obj>(owner.get(),"_pendingLobbyUpdateRequest"),"community returned seat/request retained");
        ++probeMatches;
        if(probeMatches<2) {
            if(host && ba::flag(L"-community-match-deck-smoke"))ba_dedicated_deck::rematchSmokeSelection(front);
            probeStage=3;probeAt=now+1500;
        }
        else {probeStage=7;ba::log("COMMUNITY MATCH SMOKE passed: two native Start/result/Continue cycles; same lobby, presence retained, seat=-1");}
    }
}
}
