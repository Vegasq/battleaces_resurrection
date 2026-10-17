#pragma once
#include <memory>
// Opt-in native lobby and invitation integration. The normal launcher remains
// on the independently qualified two-player path. Start/AI are not enabled here.
namespace ba_community_native {
using ba::Obj;using ba_local::Root;
namespace wire=ba_community_wire;
static bool installed=false;
static std::string installedLobby;
static wire::Lobby authority;
static wire::Directory directory{};
// Release managed roots only during an owned Unity-thread reset, never during
// CRT/DllMain shutdown after IL2CPP may already have stopped.
static auto& identities=*new std::map<std::string,std::unique_ptr<Root>>();
struct Pending {
    unsigned kind;uint32_t request=0;bool cancelled=false;Root message,manager;
    Pending(unsigned k,Obj m,Obj owner):kind(k),message(m),manager(owner){}
};
static auto& requests=*new std::deque<std::unique_ptr<Pending>>();
static unsigned smokeStage=0;
static unsigned smokeRound=0;
static ULONGLONG smokeAt=0;
static bool owns(Obj front) {
    return ba::community() && front && front==ba_dedicated_session::observedFront &&
        GetCurrentThreadId()==ba_dedicated_session::unityThread;
}
static void closeLobby(Obj front);
static Obj manager(Obj front);
static void reset() {
    Obj front=ba_dedicated_session::observedFront;
    ba_community_invites::reset(front);
    // Finish only the actual retained Create. A Leave may already have released
    // that manager and cleared its pointer, in which case there is no callback.
    while(!requests.empty()) {
        auto pending=std::move(requests.front());requests.pop_front();
        if(pending->kind==33 && ba::get<Obj>(pending->manager.get(),"_pendingCreateLobbyRequest")==pending->message.get())
            ba::native<void(*)(Obj,Obj,int,Obj)>(0x3e48360)(front,nullptr,2,nullptr);
    }
    if(installed) {
        Root party(ba::get<Obj>(front,"_party"));
        if(!installedLobby.empty() || (party.get() && ba::get<int>(party.get(),"PartyType")==3))closeLobby(front);
        Root owner(manager(front));
        wire::require(!ba::get<Obj>(front,"_party") && (!owner.get() ||
            (!ba::get<Obj>(owner.get(),"_pendingCreateLobbyRequest") && !ba::call(owner.get(),"get_PredictedCustomGameLobby"))),
            "community reset retained native lobby state");
        ba::log("Community native reset: party=0 prediction=0 pendingCreate=0 replyCounter=0");
    }
    ba_community_popup::reset();
    ba_community_roster::reset();
    requests.clear();identities.clear();installed=false;installedLobby.clear();authority={};directory={};smokeStage=0;smokeRound=0;smokeAt=0;
}
static const wire::Player* player(const std::string& profile) {
    for(const auto& row:directory.players)if(row.profile==profile)return &row;
    return directory.revision?nullptr:ba_community::player(profile);
}
static Obj named(const std::string& profile) {
    auto found=identities.find(profile);if(found!=identities.end())return found->second->get();
    const auto* player=ba_community_native::player(profile);
    wire::require(player && identities.size()<wire::maxPlayers+64,"community named identity unavailable/capacity");
    Root handle(ba::make("CommonPb","PlayerHandle")),name(ba::make("CommonPb","PlayerHandleWithName"));
    ba::set<uint64_t>(handle.get(),"steamId_",ba_community::alias(profile));ba::set<bool>(handle.get(),"isAliased_",true);
    ba::set<Obj>(name.get(),"playerHandle_",handle.get());
    ba::set<Obj>(name.get(),"playerName_",ba::str(player->name.c_str()));
    ba::set<Obj>(name.get(),"filteredName_",ba::str(player->name.c_str()));
    Obj result=name.get();identities.emplace(profile,std::make_unique<Root>(result));return result;
}
static Obj localRaw() {return ba::get<Obj>(named(ba_community::welcome.profile),"playerHandle_");}
static void pruneIdentities() {
    for(auto it=identities.begin();it!=identities.end();) {
        bool keep=it->first==ba_community::welcome.profile || player(it->first) || ba_community_invites::retain(it->first);
        for(const auto& member:authority.members)keep|=it->first==member.profile;
        if(keep)++it;else it=identities.erase(it);
    }
}
static Obj manager(Obj front) {
    Root event(ba::get<Obj>(front,"LobbyStateUpdated"));if(!event.get())return nullptr;
    Root list(ba::call(event.get(),"GetInvocationList"));const auto count=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(list.get());
    wire::require(count<=128,"community native listener capacity");
    for(size_t i=0;i<count;++i) {
        Root target(ba::call(ba::read<Obj>(list.get(),0x20+sizeof(Obj)*i),"get_Target"));
        if(target.get() && !strcmp(ba_dedicated_session::className(target.get()),"CustomGameLobbyManager") &&
           ba::get<Obj>(target.get(),"_frontServer")==front)return target.get();
    }
    return nullptr;
}
static void installPresence(Obj front) {
    Root gameHandle(ba::make("CommonPb","PlayerGameHandle"));
    ba::set<Obj>(gameHandle.get(),"playerHandleWithName_",named(ba_community::welcome.profile));
    ba::set<Obj>(front,"_playerGameHandle",gameHandle.get());
    ba::set<Obj>(front,"_currentPlayerName",ba::get<Obj>(named(ba_community::welcome.profile),"playerName_"));
    ba_lan::Bytes ids;for(auto id:ba_community::welcome.deck)ba_lan::append32(ids,id);
    Root deck(ba_dedicated::deckFromIds(ids));ba_dedicated::installing=true;
    try{ba_dedicated_deck::initialize(front,deck.get());}
    catch(...){ba_dedicated::installing=false;throw;}
    ba_dedicated::installing=false;ba_dedicated::initialized=true;
    Obj account=ba::get<Obj>(front,"_accountService"),profile=ba::get<Obj>(account,"<ProfileCache>k__BackingField");
    ba::set<uint64_t>(profile,"steamId_",ba_community::alias(ba_community::welcome.profile));
    ba::set<bool>(profile,"isAlias_",true);
    ba::set<Obj>(profile,"name_",ba::get<Obj>(named(ba_community::welcome.profile),"playerName_"));
    ba_community_invites::anchorClock(front);
    ba_dedicated_session::lobbyInstalled=true;installed=true;
    ba::log("Community presence installed: profile=%s alias=%llu assignedSeat=%d BA_RESURRECTION_COMMUNITY_V1",
        ba_community::welcome.profile.c_str(),static_cast<unsigned long long>(ba_community::alias(ba_community::welcome.profile)),ba::lanSlot());
}
static Obj notification() {
    const auto& lobby=authority;
    wire::require(lobby.phase==wire::Open && !lobby.members.empty(),"native community slice requires open lobby");
    Root message(ba::make("FrontPb","LobbyStateNotification")),state(ba::make("CommonPb","LobbyState"));
    ba::set<int>(state.get(),"lobbyStatus_",lobby.members.size()==1?1:2);
    ba::set<int>(state.get(),"gameMode_",1);ba::set<Obj>(state.get(),"hostHandle_",named(lobby.host));
    for(size_t i=0;i<lobby.members.size();++i) {
        const auto& profile=lobby.members[i].profile;
        Root member(ba::make("CommonPb","LobbyMember")),service(ba::make("CommonPb","ServiceHandle"));
        ba::set<Obj>(service.get(),"handle_",ba::str(profile.c_str()));
        ba::set<Obj>(member.get(),"playerHandle_",named(profile));
        ba::set<Obj>(member.get(),"playerFrontHandle_",service.get());
        ba::set<bool>(member.get(),"isHost_",profile==lobby.host);
        ba::set<int>(member.get(),"lobbyRole_",1);ba::set<int>(member.get(),"roleSlot_",static_cast<int>(i));
        ba_local::addItem(ba::get<Obj>(state.get(),"members_"),member.get());
    }
    ba::set<Obj>(message.get(),"lobbyState_",state.get());ba::set<Obj>(message.get(),"frontReceiver_",localRaw());
    return message.get();
}
static void closeLobby(Obj front) {
    Root message(ba::make("FrontPb","LobbyClosedNotification"));
    ba::set<Obj>(message.get(),"frontReceiver_",localRaw());ba::set<int>(message.get(),"closureType_",1);
    ba::native<void(*)(Obj,Obj,Obj)>(0x3e48ad0)(front,message.get(),nullptr);installedLobby.clear();
    ba::log("Community native lobby closure delivered; party=%p",ba::get<Obj>(front,"_party"));
}
static void acknowledge(Obj front,const wire::Ack& ack) {
    for(auto it=requests.begin();it!=requests.end();++it) {
        Pending& pending=**it;if(pending.request!=ack.request || !ack.request)continue;
        const unsigned kind=pending.kind;
        // LeaveLobby releases its manager immediately and ignores the returned
        // native request. Its NONE snapshot owns closure; no update response.
        if(kind==14) {
            wire::require(ack.success,"community leave rejected after native release");
            requests.erase(it);return;
        }
        wire::require(kind==33,"unexpected community native response kind");
        if(pending.cancelled) {
            if(ack.success) {
                wire::require(authority.id==ack.object && authority.host==ba_community::welcome.profile,
                    "cancelled community create disagrees with authority");
                installedLobby=ack.object;
            }
            requests.erase(it);
            ba::log("Community cancelled create acknowledged without stale native callback; queued Leave reclaims lobby");return;
        }
        const Obj retained=ba::get<Obj>(pending.manager.get(),"_pendingCreateLobbyRequest");
        wire::require(retained==pending.message.get(),"community create acknowledgement lost native request ownership");
        std::unique_ptr<Root> response;
        if(ack.success) {
            wire::require(authority.id==ack.object && authority.host==ba_community::welcome.profile,
                "community create acknowledgement disagrees with authority");
            Root state(notification());response=std::make_unique<Root>(ba::make("FrontPb","CreateLobbyResponse"));
            ba::set<Obj>(response->get(),"lobbyState_",state.get());installedLobby=ack.object;
        }
        // Remove our pending entry before native events can enqueue another.
        Root owner(pending.manager.get());requests.erase(it);
        ba::native<void(*)(Obj,Obj,int,Obj)>(0x3e48360)(front,response?response->get():nullptr,ack.success?0:2,nullptr);
        wire::require(!ba::get<Obj>(owner.get(),"_pendingCreateLobbyRequest"),"native create callback did not clear pending request");
        ba::log("Community native create response: success=%d pending=0 party=%p lobby=%s",ack.success?1:0,
            ba::get<Obj>(front,"_party"),installedLobby.c_str());return;
    }
    ba::log("Community control ACK: request=%u kind=%u success=%d reason=%s",ack.request,ack.kind,ack.success?1:0,ack.reason.c_str());
}
static void enqueue(Obj front,Obj consumer) {
    wire::require(owns(front) && installed,"community request outside owned session");
    const int kind=ba::get<int>(consumer,"frontServerMessagesCase_");
    // A click already inside the original Reply caller will increment its
    // counter even after connection failure. Retain that credit for reset.
    if(kind==23 || kind==24 || kind==25){ba_community_invites::enqueue(front,consumer,kind);return;}
    wire::require(ba_community::online && !ba_lan::stopped && requests.size()<16,"community control request unavailable/capacity");
    Obj message=ba::get<Obj>(consumer,"frontServerMessages_");Root owner(manager(front));
    wire::require(message && owner.get(),"community request/manager unavailable");
    unsigned operation=static_cast<unsigned>(kind);
    if(kind==33) {
        wire::require(ba::get<int>(message,"gameMode_")==1,"only community custom1v1 is supported");
        for(const auto& pending:requests)wire::require(pending->kind!=33 || pending->cancelled,"duplicate pending native create");
    } else if(kind==34) {
        Obj actions=ba::get<Obj>(message,"updateActions_");
        wire::require(ba_local::count(actions)==1,"community prototype needs one lobby action");
        int index=0;void* args[]={&index};Root action(ba::call(actions,"get_Item",1,args));
        operation=static_cast<unsigned>(ba::get<int>(action.get(),"updateActionsCase_"));
        wire::require(operation==14,"community native Invite/Start/update adapters are not installed yet");
        // Native Leave immediately releases the manager, including its pending
        // Create pointer. Finish server admission/departure in order and never
        // deliver that now-cancelled Create callback into the released manager.
        for(auto& pending:requests)if(pending->kind==33)pending->cancelled=true;
    } else throw std::runtime_error("unsupported community native request");
    requests.push_back(std::make_unique<Pending>(operation,message,owner.get()));
    ba::log("Community native request queued: operation=%u native=%p; send and callback deferred",operation,message);
}
static void dispatch(Obj front) {
    // At most one native lobby transaction is in flight. A rapid new Create
    // waits for Leave/NONE, even if all wire replies fit into a single poll.
    while(!requests.empty() && !requests.front()->request) {
        Pending& pending=*requests.front();
        if(pending.kind==33 && pending.cancelled){requests.pop_front();continue;}
        if(pending.kind==14 && authority.phase==wire::None) {
            if(!installedLobby.empty())closeLobby(front);
            requests.pop_front();continue;
        }
        const auto id=ba_community::nextRequest();
        if(pending.kind==33) {
            wire::require(authority.phase==wire::None,"native Create dispatched before previous departure");
            pending.request=ba_community::send(wire::create(id));
        } else pending.request=ba_community::send(wire::leave(id,authority.id));
        ba::log("Community native transaction dispatched: operation=%u request=%u",pending.kind,pending.request);
    }
}
static void project(Obj front) {
    if(installedLobby.empty())return;
    if(authority.phase==wire::None){closeLobby(front);return;}
    for(const auto& pending:requests)if(pending->kind==14)return;
    wire::require(authority.id==installedLobby,"community native lobby changed unexpectedly");
    ba_community_invites::reconcileParty(front);
    Root state(notification());ba::native<void(*)(Obj,Obj,Obj)>(0x3e48820)(front,state.get(),nullptr);
    ba::log("Community native lobby state: revision=%llu members=%llu",static_cast<unsigned long long>(authority.revision),static_cast<unsigned long long>(authority.members.size()));
}
static void smoke(Obj front) {
    if(!ba::flag(L"-community-create-smoke"))return;
    const ULONGLONG now=GetTickCount64();if(!smokeAt){smokeAt=now+2500;return;}if(now<smokeAt)return;
    Root owner(manager(front));wire::require(owner.get()!=nullptr,"community smoke manager unavailable");
    if(smokeStage==0) {
        wire::require(!ba::get<Obj>(owner.get(),"_pendingCreateLobbyRequest") && installedLobby.empty(),"community smoke starts in occupied lobby");
        smokeStage=1;
        ba::log("COMMUNITY SMOKE native EnterLobbyScreen (NOT manual UI input)");
        ba::native<void(*)(Obj,Obj)>(0x3cab7b0)(owner.get(),nullptr);
        wire::require(ba::get<Obj>(owner.get(),"_pendingCreateLobbyRequest") && !requests.empty(),"native create did not retain request after enqueue");
        ba::log("COMMUNITY SMOKE create returned with native pending request; no early response");
    } else if(smokeStage==1 && !installedLobby.empty() && requests.empty()) {
        smokeStage=2;smokeAt=now+2500;
        wire::require(ba::get<Obj>(front,"_party") && !ba::get<Obj>(owner.get(),"_pendingCreateLobbyRequest"),"native lobby/party not accepted");
        ba::log("COMMUNITY SMOKE confirmed native lobby and party; waiting before leave");
    } else if(smokeStage==2) {
        smokeStage=3;
        ba::log("COMMUNITY SMOKE native LeaveLobby (NOT manual UI input)");
        ba::native<void(*)(Obj,bool,Obj)>(0x3cab820)(owner.get(),false,nullptr);
    } else if(smokeStage==3 && requests.empty() && installedLobby.empty() && authority.phase==wire::None) {
        wire::require(!ba::get<Obj>(front,"_party") && !ba::get<Obj>(owner.get(),"_pendingCreateLobbyRequest") &&
            !ba::get<Obj>(owner.get(),"_pendingLobbyUpdateRequest"),"native leave retained party/request");
        ++smokeRound;smokeStage=smokeRound<2?0:4;smokeAt=now+750;
        ba::log("COMMUNITY SMOKE Create/Leave round=%u: party=0 pending=0 seat=-1 connection retained",smokeRound);
    } else if(smokeStage==4) {
        smokeStage=5;
        ba::log("COMMUNITY SMOKE testing Leave and re-enter while Create ACK is pending (NOT manual UI input)");
        ba::native<void(*)(Obj,Obj)>(0x3cab7b0)(owner.get(),nullptr);
    } else if(smokeStage==5 && !requests.empty() && requests.front()->request && installedLobby.empty()) {
        // Probe deliberately delays CREATE ACK; native request has been sent.
        smokeStage=6;
        ba::native<void(*)(Obj,bool,Obj)>(0x3cab820)(owner.get(),false,nullptr);
        ba::native<void(*)(Obj,Obj)>(0x3cab7b0)(owner.get(),nullptr);
        ba::log("COMMUNITY SMOKE early Leave/re-enter queued behind original Create");
    } else if(smokeStage==6 && requests.empty() && !installedLobby.empty()) {
        smokeStage=7;
        wire::require(!ba::get<Obj>(owner.get(),"_pendingCreateLobbyRequest"),"rapid re-enter retained native create");
        ba::native<void(*)(Obj,bool,Obj)>(0x3cab820)(owner.get(),false,nullptr);
    } else if(smokeStage==7 && requests.empty() && installedLobby.empty() && authority.phase==wire::None) {
        wire::require(!ba::get<Obj>(front,"_party") && !ba::get<Obj>(owner.get(),"_pendingCreateLobbyRequest") &&
            !ba::get<Obj>(owner.get(),"_pendingLobbyUpdateRequest"),"rapid leave/re-enter retained native state");
        smokeStage=8;ba::log("COMMUNITY SMOKE Create/Leave passed: two normal rounds and pending-ACK Leave/re-enter; party=0 pending=0 seat=-1 connection retained");
    }
}
static void update(Obj front) {
    wire::require(owns(front),"community native update ownership");ba_community::checkTimeouts();
    if(!installed && ba_community::online && ba_community::player(ba_community::welcome.profile) && ba_dedicated_session::inMenu())installPresence(front);
    if(!installed)return;
    while(!ba_community::events.empty()) {
        auto event=std::move(ba_community::events.front());ba_community::events.pop_front();
        if(const auto* ack=std::get_if<wire::Ack>(&event)) {
            if(!ba_community_invites::acknowledge(front,*ack))acknowledge(front,*ack);
            ba_community_invites::flush(front);project(front);
        }
        else if(const auto* snapshot=std::get_if<wire::Lobby>(&event)){authority=*snapshot;ba_community_invites::flush(front);project(front);}
        else if(const auto* listing=std::get_if<wire::Directory>(&event)) {
            directory=*listing;pruneIdentities();
            for(const auto& row:directory.players)named(row.profile);
            ba::log("Community directory: revision=%llu players=%llu",static_cast<unsigned long long>(directory.revision),static_cast<unsigned long long>(directory.players.size()));
            ba_community_roster::changed();
        }
        else if(const auto* invite=std::get_if<wire::Invitation>(&event))ba_community_invites::receive(front,*invite);
        else if(std::holds_alternative<wire::Aborted>(event))throw std::runtime_error("community match aborted");
    }
    smoke(front);
    dispatch(front);
    ba_community_invites::dispatch(front);ba_community_invites::flush(front);
    ba_community_roster::update();
    ba_community_popup::update();
    ba_community_roster::smoke(front);
    ba_community_invites::smoke(front);
}
}
extern "C" __declspec(dllexport) void OfflineCommunityEnqueue(void* front,void* consumer,void* methodInfo) {
    ba::init();
    if(!ba::community()){ba::native<void(*)(ba::Obj,ba::Obj,ba::Obj)>(0x256df90)(front,consumer,methodInfo);return;}
    try{ba_community_native::enqueue(front,consumer);}
    catch(const std::exception& e){ba_lan::fail("community native request",e);}
}
