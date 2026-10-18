#pragma once
#include "public_attempt.hpp"
// Unity-thread public matchmaking adapter. Custom lobby ownership stays separate.
namespace ba_public {
using ba::Obj;using ba_local::Root;
namespace q=ba_public_wire;
namespace c=ba_community_wire;
using q::require;
struct Current {
    ba_public_attempt::Attempt intent;Root front,controller;
    uint32_t enterRequest=0,readyRequest=0,cancelRequest=0,returnRequest=0;
    bool lost=false,cancelAck=false,cancelRejected=false,returnAck=false,joining=false,aborting=false,cleanup=false;
    bool found=false,returning=false;std::string failure;
    Current(uint64_t ticket,int mode,const q::Deck& deck,Obj f,Obj owner):
        intent(ticket,mode,deck,GetTickCount64()),front(f),controller(owner){}
};
static auto& current=*new std::unique_ptr<Current>();
static uint64_t lastTicket=0;
static ba_match_loading::Ticket errorNotice=0;
static unsigned completed=0,smokeStarted=0;
static bool smokeCancelled=false;
static uint64_t smokeRetryAt=0;
static auto& oldMatches=*new std::deque<std::string>();
static bool active(){return static_cast<bool>(current);}
static bool deckLocked(){return current && current->intent.entered && !current->intent.retired;}
static bool ignoreMatchData(){return current && (current->intent.cancelled || current->aborting);}
static void controlReset(){if(current){current->lost=true;current->failure="community connection retired";}}
static void connectionFailed(const char* reason){if(current){current->lost=true;current->failure=reason;}}
static void forget() {
    if(current && !current->intent.match.empty()) {
        if(oldMatches.size()==16)oldMatches.pop_front();oldMatches.push_back(current->intent.match);
    }
    current.reset();
}
static void closeControl(Obj front,const char* reason) {
    ba_client::connectRequested=false;
    ba_client::retireControl(front,reason);
}
static void finishMenu(Obj front,const char* reason,bool disconnect,bool error=false) {
    require(current && !current->joining && ba_client::worldOwner==ba_client::Owner::None &&
        ba_client::nativeIdle(front) && ba_dedicated_session::inMenu(),"public retirement before idle menu");
    const auto ticket=current->intent.ticket;
    ba_match_search::release(ticket,reason);
    if(disconnect)closeControl(front,reason);
    else ba_community_native::restoreIdentity(front);
    ba::log("Public intent retired: ticket=%llu reason=%s nativeIdle=1 disconnect=%d",
        static_cast<unsigned long long>(ticket),reason,disconnect?1:0);
    if(ba::flag(L"-public-queue-smoke-retry") && smokeStarted==1)smokeRetryAt=GetTickCount64()+1000;
    forget();
    if(error) {
        errorNotice=ba_match_loading::begin(ba_match_loading::Source::Dedicated,"public-error:"+std::to_string(ticket),ba_match_loading::Stage::Preparing);
        ba_match_loading::error(errorNotice,"Match could not start. Please try again.");
    }
}
static void fallback(Obj front) {
    require(current && current->intent.mayFallback() && !current->joining,"ambiguous public fallback after READY");
    const auto ticket=current->intent.ticket;const int mode=static_cast<int>(current->intent.mode);
    Root controller(current->controller.get());
    ba::log("Public fallback accepted: ticket=%llu mode=%d beforeAmbiguousCommit=1 elapsedMs=%llu reason=%s",
        static_cast<unsigned long long>(ticket),mode,static_cast<unsigned long long>(GetTickCount64()-current->intent.started),current->failure.c_str());
    forget(); // Transfer the native search ticket to the local match producer.
    try {ba_practice::startMode(front,controller.get(),mode,ticket);}
    catch(...) {ba_match_search::release(ticket,"local fallback failed");throw;}
}
static void start(Obj front,Obj controller,int mode) {
    require(ba::unified() && ba::flag(L"-public-queue-experimental"),"public queue adapter not enabled");
    q::participants(mode);
    if(active() || ba_practice::active()){ba::log("Public Play duplicate ignored while an intent/world is active");return;}
    require(ba_local_menu::ready(front) && ba_dedicated_session::inMenu() && ba_client::nativeIdle(front) &&
        ba_client::worldOwner==ba_client::Owner::None && !ba_dedicated_session::joined &&
        ba_community_native::authority.phase==c::None && ba_community_native::requests.empty() &&
        ba_community_invites::operations.empty() && !ba::get<Obj>(front,"_party") && ba_lan::bootstrap.empty(),
        "public search requires an idle menu outside Custom");
    require(ba_dedicated_deck::canReady(front),"public selected deck invalid");
    const auto deck=ba_community_match::selected(front);
    const auto ticket=ba_match_search::begin(front,mode);
    try {current=std::make_unique<Current>(ticket,mode,deck,front,controller);lastTicket=ticket;ba_client::requestConnect();}
    catch(...) {ba_match_search::release(ticket,"public start failed");current.reset();throw;}
    // Only the retired public attempt's error may be dismissed. A stale notice
    // handle must never hide another producer's current loading/error state.
    ba_match_loading::dismissNotice(errorNotice,"public search restarted");errorNotice=0;
    ba::log("Public search intent: ticket=%llu mode=%d originalSearch=1 deadlineMs=30000 BA_RESURRECTION_PUBLIC_QUEUE_V1",
        static_cast<unsigned long long>(ticket),mode);
}
static bool cancel(Obj front) {
    if(!current || current->front.get()!=front)return false;
    if(!current->joining && ba_match_search::requestCancel(front))current->intent.cancelled=true;
    return true;
}
static bool receive(unsigned char kind,const q::Bytes& bytes) {
    require(ba_community::online,"public event before community welcome");
    if(kind==q::StateKind) {
        const auto value=q::state(bytes);
        if(!current){require(value.ticket<=lastTicket,"unsolicited public state");return false;}
        if(!current->intent.state(ba_community::generation,value))return false;
        ba::log("Public authoritative state: ticket=%llu phase=%u mode=%u match=%s elapsedMs=%u",
            static_cast<unsigned long long>(value.ticket),value.phase,value.mode,value.match.c_str(),value.elapsedMs);
        return true;
    }
    require(kind==q::MatchKind,"unknown public assignment event");
    const auto value=q::assignment(bytes);
    if(!current){require(value.ticket<=lastTicket,"unsolicited public assignment");return false;}
    if(!current->intent.assignment(ba_community::generation,value))return false;
    require(!ba_lan::welcomed && ba_lan::bootstrap.empty() && ba_lan::dedicatedMatchId.empty(),"public assignment overlaps existing match");
    ba_lan::dedicatedMatchId=value.match;ba_lan::inputWindow=value.inputWindow;ba::dedicatedAssignedSlot=value.slot;
    ba_lan::dedicatedDeck.clear();for(auto unit:value.deck)ba_lan::append32(ba_lan::dedicatedDeck,unit);
    ba_lan::welcomed=true;ba_lan::publicMatch=true;
    ba::log("Public match assignment: ticket=%llu match=%s mode=%u count=%u seat=%u humans=%u inputWindow=%u",
        static_cast<unsigned long long>(value.ticket),value.match.c_str(),value.mode,value.count,value.slot,value.humanMask,value.inputWindow);
    return true;
}
static bool acknowledge(Obj,const c::Ack& ack) {
    if(ack.kind<q::Enter || ack.kind>q::Return)return false;
    if(!current)return true;
    auto& s=*current;
    if(ack.request==s.cancelRequest){s.cancelAck=ack.success;s.cancelRejected=!ack.success;}
    else if(ack.request==s.returnRequest){require(ack.success,"public RETURN rejected");s.returnAck=true;}
    else if(ack.request==s.enterRequest && !ack.success){s.lost=true;s.failure=ack.reason;}
    else if(ack.request==s.readyRequest && !ack.success && s.intent.readySent && !s.intent.retired && !s.intent.cancelled) {
        // WAITING may already have replaced this proposal before its delayed
        // negative ACK. Until the new READY is sent, readySent stays false.
        s.lost=true;s.failure=ack.reason;
    }
    ba::log("Public ACK: ticket=%llu kind=%u request=%u success=%d reason=%s",
        static_cast<unsigned long long>(s.intent.ticket),ack.kind,ack.request,ack.success?1:0,ack.reason.c_str());
    return true;
}
static bool aborted(const c::Aborted& message) {
    for(const auto& match:oldMatches)if(match==message.match){ba_community::abortPending=false;return true;}
    if(!current || current->intent.match!=message.match)return false;
    if(ba_lan::matchEnded){ba_community::abortPending=false;return true;}
    current->aborting=true;current->failure=message.reason;return true;
}
static Obj validateBootstrap(Obj front) {
    const auto& s=current->intent;const auto& seat=s.seat;
    Root encoded(ba_lan::byteString(ba_lan::bootstrap)),data(ba_lan_bootstrap::decodeGameDataLan(encoded.get()));
    Obj config=ba_lan_bootstrap::required(ba::get<Obj>(data.get(),"gameConfig_"),"public GameConfig missing");
    require(ba::get<int>(config,"gameMode_")==static_cast<int>(s.mode),"public bootstrap mode differs from assignment");
    Obj armies=ba::get<Obj>(config,"armies_");require(ba_local::count(armies)==seat.count,"public bootstrap participant count differs");
    ba_lan::publicIdentities.clear();std::unique_ptr<Root> local;
    for(int slot=0;slot<seat.count;++slot) {
        Obj army=ba_lan_bootstrap::at(armies,slot);
        require(ba::get<uint32_t>(army,"armyId_")==static_cast<uint32_t>(slot) &&
            ba::get<uint32_t>(army,"allianceId_")==static_cast<uint32_t>(slot%2),"public army/alliance changed");
        Obj players=ba::get<Obj>(army,"players_");require(ba_local::count(players)==1,"public army identity count");
        Obj identity=ba_lan_bootstrap::at(players,0);
        Obj named=ba::get<Obj>(identity,"playerHandleWithName_"),id=ba::get<Obj>(named,"playerHandle_");
        require(ba::get<uint64_t>(id,"steamId_")==static_cast<uint64_t>(slot+1) && ba::get<bool>(id,"isAliased_"),"public aliased seat identity");
        const bool human=(seat.humanMask&(1u<<slot))!=0;
        require((ba::get<uint32_t>(identity,"aiProfileId_")==0)==human,"public bot ownership differs from human mask");
        ba_lan::publicIdentities.push_back(ba_lan::serialize(identity));
        if(slot==seat.slot) {
            Obj deck=ba::get<Obj>(army,"deck_"),units=ba::get<Obj>(deck,"units_");
            require(ba_local::count(units)==8,"public human deck size");
            for(int i=0;i<8;++i)require(ba_lan_bootstrap::uintAt(units,i)==s.deck[i],"public human bootstrap deck changed");
            local=std::make_unique<Root>(ba::call(identity,"Clone"));
        }
    }
    require(local && local->get() && ba_community_match::selected(front)==s.deck,"public local identity/selected deck changed");
    return local->get();
}
static void begin(Obj front) {
    auto& s=*current;
    if(s.joining || !s.intent.assigned || ba_lan::bootstrap.empty() || s.aborting || s.intent.cancelled)return;
    require(s.intent.committed && s.intent.match==ba_lan::dedicatedMatchId && ba_client::nativeIdle(front),"public begin ownership");
    Root local(validateBootstrap(front));
    if(!s.found){require(ba_match_search::found(s.intent.ticket),"public accepted after Cancel");s.found=true;}
    ba_client::acquireRemote(front,s.intent.match);s.joining=true;
    ba::set<Obj>(front,"_playerGameHandle",local.get());
    ba::set<Obj>(front,"_currentPlayerName",ba::get<Obj>(ba::get<Obj>(local.get(),"playerHandleWithName_"),"playerName_"));
    Obj profile=ba::get<Obj>(ba::get<Obj>(front,"_accountService"),"<ProfileCache>k__BackingField");
    ba::set<uint64_t>(profile,"steamId_",static_cast<uint64_t>(s.intent.seat.slot+1));
    ba_dedicated_session::joined=true;++ba_dedicated_session::startedSessions;
    Root encoded(ba_lan::byteString(ba_lan::bootstrap));ba_bootstrap::beginJoined(front,encoded.get(),local.get(),true);
    ba::log("Public native match joined: ticket=%llu match=%s mode=%u participants=%u seat=%u remoteWorld=1",
        static_cast<unsigned long long>(s.intent.ticket),s.intent.match.c_str(),s.intent.mode,s.intent.seat.count,s.intent.seat.slot);
}
static void returnFromMatch(Obj front,Obj server) {
    auto& s=*current;require(s.intent.phase==q::Results && !s.returnRequest,"public return before authoritative results");
    ba_match_search::release(s.intent.ticket,"public match returned");
    ba_dedicated_session::resetAtMenu(front,server,!s.aborting,true);s.joining=false;s.returning=true;
    ba_community::abortPending=false;ba_community_native::restoreIdentity(front);
    s.returnRequest=ba_community::send(q::returned(ba_community::nextRequest(),s.intent.ticket,s.intent.match));
    ba::log("Public native return: ticket=%llu match=%s aborted=%d nativeIdle=1",
        static_cast<unsigned long long>(s.intent.ticket),s.intent.match.c_str(),s.aborting?1:0);
}
static void smokeCancel(Obj) {
    if(!ba::flag(L"-public-queue-smoke") || !current || smokeStarted!=1 || smokeCancelled)return;
    const auto point=ba::argument(L"-public-queue-smoke-cancel=","");if(point.empty())return;
    const auto& intent=current->intent;
    const bool reached=(point=="before-enter" && !intent.entered) ||
        (point=="waiting" && intent.phase==q::Waiting && GetTickCount64()-intent.started>=3000) ||
        (point=="offered" && intent.phase==q::Offered && !intent.readySent) ||
        (point=="after-ready" && intent.readySent && !intent.committed);
    if(!reached)return;
    ba_match_search::clickCancel(intent.ticket);smokeCancelled=true;
    require(current->intent.cancelled,"native public Cancel did not reach its intent");
    ba::log("PUBLIC QUEUE SMOKE cancellation: ticket=%llu point=%s noWorld=%d",
        static_cast<unsigned long long>(intent.ticket),point.c_str(),ba_client::worldOwner==ba_client::Owner::None?1:0);
}
static void update(Obj front) {
    if(!current)return;
    try {
        auto& s=*current;auto& intent=s.intent;
        require(s.front.get()==front,"public attempt belongs to another front");
        const auto now=GetTickCount64();Obj server=ba::read<Obj>(front,0xd8);
        if(s.lost) {
            // A valid result and native Continue already finished this match.
            // Losing only its final control ACK must not report a start failure.
            if(s.returning && !s.aborting){finishMenu(front,"connection lost after return",true);return;}
            if(s.joining) {
                if(!ba_client::nativeIdle(front) || !ba_dedicated_session::inMenu() || ba_client::remoteWorld())return;
                s.joining=false;finishMenu(front,"connection lost after match acceptance",true,true);return;
            }
            if(intent.mayFallback()){fallback(front);return;}
            finishMenu(front,"connection lost after READY",true,!intent.cancelled);return;
        }
        if(s.returnRequest) {
            if(intent.retired && s.returnAck){++completed;ba::log("PUBLIC QUEUE completed return: match=%s completed=%u seatReleased=1",intent.match.c_str(),completed);finishMenu(front,"returned",false);}
            return;
        }
        smokeCancel(front);
        if(intent.cancelled && !s.joining) {
            ba_match_search::release(intent.ticket,"cancel requested");
            if(!intent.entered){finishMenu(front,"cancelled before ENTER",true);return;}
            if((intent.retired && s.cancelAck) || s.cancelRejected){finishMenu(front,"cancelled",s.cancelRejected);return;}
            if(!s.cancelRequest)s.cancelRequest=ba_community::send(q::cancel(ba_community::nextRequest(),intent.ticket));
            return;
        }
        if(intent.retired) {if(intent.mayFallback()){fallback(front);return;}finishMenu(front,"server retired public ticket",false,true);return;}
        if(s.aborting || (intent.phase==q::Results && !ba_lan::matchEnded)) {
            s.aborting=true;ba_lan::running=false;ba_lan::frames.clear();ba_local::ready.store(false);
            if(intent.phase!=q::Results)return; // Wait for authoritative abort identity/state.
            if(s.joining && !s.cleanup) {
                Obj sim=ba::read<Obj>(server,0x140);
                if(!ba::read<bool>(server,0xd8) && ba::read<bool>(sim,0x1a0) && ba::read<uint64_t>(sim,0x1a8)) {
                    s.cleanup=true;ba_bootstrap::awaitingWorld=false;int reason=1;bool stay=false;void* args[]={&reason,&stay};
                    ba::call(server,"CleanupGameState",2,args);
                }
            }
            if(ba_client::nativeIdle(front) && ba_dedicated_session::inMenu())returnFromMatch(front,server);
            return;
        }
        if(s.joining) {
            if(ba_lan::worldReady && ba_lan::running && ba_dedicated::loadingInGame())ba_match_search::release(intent.ticket,"public native world ready");
            if(ba_dedicated_session::sawWorld && ba_client::nativeIdle(front) && ba_dedicated_session::inMenu() && ba_dedicated_results::delivered)
                returnFromMatch(front,server);
            return;
        }
        if(intent.committed) {
            if(!s.found){require(ba_match_search::found(intent.ticket),"public commit after local cancellation");s.found=true;}
            begin(front);return;
        }
        if(!intent.entered && ba_community::online && ba_community_native::installed && ba_client::deckReady()) {
            require(ba_community_match::selected(front)==intent.deck,"public deck changed while connecting");
            intent.enter(ba_community::generation);
            s.enterRequest=ba_community::send(q::enter(ba_community::nextRequest(),intent.ticket,intent.mode,intent.remaining(now),intent.deck));
        }
        if(intent.phase==q::Offered && !intent.readySent) {
            intent.ready();s.readyRequest=ba_community::send(q::ready(ba_community::nextRequest(),intent.ticket,intent.match));
            ba::log("Public READY sent: ticket=%llu proposal=%s automaticFallbackLocked=1",static_cast<unsigned long long>(intent.ticket),intent.match.c_str());
            smokeCancel(front);
        }
        if(now-intent.started>=35000 && intent.mayFallback()) {s.failure="server queue deadline response unavailable";fallback(front);}
    } catch(const std::exception& error) {
        ba::log("Public client failure: %s",error.what());
        if(current && current->joining){ba_lan::fail("public match",error);return;}
        if(current){current->lost=true;current->failure=error.what();current->intent.cancelled=true;}
    }
}
static void smoke(Obj front) {
    const unsigned attempts=ba::flag(L"-public-queue-smoke-retry")?2:1;
    if(!ba::flag(L"-public-queue-smoke") || !ba::flag(L"-public-queue-experimental") || active() || ba_practice::active() || smokeStarted>=attempts ||
        GetTickCount64()<smokeRetryAt || !ba_dedicated_session::inMenu() || !ba_client::nativeIdle(front))return;
    const int mode=std::stoi(ba::argument(L"-public-queue-smoke-mode=","1"));
    Root type(ba_tables::reflectedType("MatchmakingButtonVM","Uncapped.UI"));void* args[]={type.get()};
    Root buttons(ba::invoke(ba::find_class("UnityEngine","Resources"),nullptr,"FindObjectsOfTypeAll",1,args));
    if(!buttons.get())return;const auto count=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(buttons.get());require(count<=1024,"public smoke button capacity");
    for(size_t i=0;i<count;++i) {
        Obj button=ba::read<Obj>(buttons.get(),0x20+i*sizeof(Obj));
        if(!button || !ba::get<bool>(button,"_isInitialized") || !ba::native<bool(*)(Obj,Obj)>(0x5084710)(button,nullptr))continue;
        Root go(ba::native<Obj(*)(Obj,Obj)>(0x6ec1a0)(button,nullptr));
        if(!go.get() || !ba::native<bool(*)(Obj,Obj)>(0x508a650)(go.get(),nullptr))continue;
        Root model(ba::call(button,"get_Model"));if(!model.get() || ba::get<int>(model.get(),"<GameMode>k__BackingField")!=mode)continue;
        if(ba::get<bool>(button,"_isMatching") || ba::get<int>(button,"_lockedReason")!=0)continue;
        Root enabled(ba::call(button,"get_Interactable"));if(!ba_practice::boolean(enabled.get()))continue;
        ++smokeStarted;ba::native<void(*)(Obj,Obj)>(0x3d23220)(button,nullptr);
        require(active(),"original public button did not enter server queue");ba_match_search::observeButton(button);
        if(ba::flag(L"-public-queue-smoke-practice-overlap")) {
            const auto ticket=current->intent.ticket,connection=ba_community::generation;
            ba_practice::start(front,current->controller.get());
            require(current && current->intent.ticket==ticket && !ba_practice::active() &&
                ba_match_search::owns(ticket) && ba_community::generation==connection &&
                ba_client::worldOwner==ba_client::Owner::None,"Try Deck preempted pending public search");
            ba::log("PUBLIC QUEUE SMOKE practice overlap rejected: ticket=%llu searchAndConnectionRetained=1",
                static_cast<unsigned long long>(ticket));
        }
        ba::log("PUBLIC QUEUE SMOKE original OnMapSelected: mode=%d visible=1 automatedCallback=1",mode);return;
    }
}
}
