#pragma once
// Native request counters and identity-only callbacks require invitation-ID
// correlation outside the game's protobufs. All entry points run on Unity's
// observed thread, and every response follows the originating enqueue return.
namespace ba_community_invites {
using ba::Obj;using ba_local::Root;
namespace wire=ba_community_wire;
namespace native=ba_community_native;
struct Invitation {
    wire::Invitation value;ULONGLONG deadline;Root sender,target;
    std::unique_ptr<Root> incoming,sent,manager;
    bool acknowledged=false,applied=false;unsigned replies=0;
    explicit Invitation(const wire::Invitation& v):value(v),deadline(GetTickCount64()+v.milliseconds),
        sender(native::named(v.sender)),target(native::named(v.target)){}
};
struct Operation {
    int kind;uint32_t request=0;bool accepted=false,rejected=false;
    bool replySettled=false;int counterBefore=-1;
    std::string profile,invitation,lobby;Root message,manager,other;
    Operation(int k,Obj m,Obj owner,std::string p,Obj identity):kind(k),profile(std::move(p)),
        message(m),manager(owner),other(identity){}
};
static auto& invitations=*new std::map<std::string,std::unique_ptr<Invitation>>();
static auto& operations=*new std::deque<std::unique_ptr<Operation>>();
static auto& completing=*new std::unique_ptr<Operation>();
static std::deque<wire::Invitation> finished;
static bool resetting=false;
static Invitation* delivering=nullptr;
static bool completionFailureInjected=false;
static void resetSmoke();
static std::string profileForRaw(Obj raw) {
    wire::require(raw && ba::get<bool>(raw,"isAliased_"),"native community invitation identity is not aliased");
    const auto key=ba::get<uint64_t>(raw,"steamId_");
    for(const auto& item:native::identities)if(ba_community::alias(item.first)==key)return item.first;
    throw std::runtime_error("native community invitation identity unavailable");
}
static bool retain(const std::string& profile) {
    for(const auto& item:invitations)if(item.second->value.sender==profile || item.second->value.target==profile)return true;
    for(const auto& op:operations)if(op->profile==profile)return true;
    if(completing && completing->profile==profile)return true;
    return false;
}
static bool pending(const std::string& profile) {
    for(const auto& item:invitations)if(item.second->value.sender==ba_community::welcome.profile &&
        item.second->value.target==profile && item.second->value.status==0)return true;
    for(const auto& op:operations)if(op->kind==23 && op->profile==profile && !op->rejected)return true;
    return false;
}
static bool canInvite(const std::string& profile) {
    const auto* player=native::player(profile);const auto& lobby=native::authority;
    if(!native::installed || ba_lan::stopped || profile==ba_community::welcome.profile || !player || !player->invitable ||
       lobby.phase!=wire::Open || lobby.host!=ba_community::welcome.profile || lobby.members.size()!=1 ||
       native::installedLobby!=lobby.id || pending(profile))return false;
    for(const auto& op:native::requests)if(op->kind==14 || !op->cancelled)return false;
    return true;
}
static bool same(const wire::Invitation& a,const wire::Invitation& b) {
    return a.id==b.id && a.lobby==b.lobby && a.sender==b.sender && a.target==b.target;
}
static bool leaving(const std::string& lobby) {
    if(native::installedLobby!=lobby)return true;
    for(const auto& request:native::requests)if(request->kind==14)return true;
    return false;
}
static Invitation* incomingFor(Obj nativeInvite) {
    for(auto& item:invitations)if(item.second->incoming && item.second->incoming->get()==nativeInvite)return item.second.get();
    // ProcessIncoming synchronously initializes the popup before returning its
    // retained PartyInvite. Only that exact in-progress delivery may use this
    // early path; ordinary refreshes require the retained object identity.
    if(delivering && nativeInvite && ba::get<Obj>(nativeInvite,"Sender")==delivering->sender.get() &&
        ba::get<int>(nativeInvite,"PartyType")==3 && ba::get<int>(nativeInvite,"GameMode")==1)return delivering;
    return nullptr;
}
static bool containsIncoming(Obj front,Obj invite) {
    Root list(ba::get<Obj>(front,"_partyInvites"));wire::require(list.get()!=nullptr,"native invitation list not initialized");
    wire::require(ba_local::count(list.get())<=16,"native incoming invitation capacity");
    Root first(ba::call(list.get(),"get_First"));Obj node=first.get();unsigned count=0;
    while(node) {
        wire::require(++count<=16,"native invitation list cycle/capacity");
        if(ba::call(node,"get_Value")==invite)return true;
        node=ba::call(node,"get_Next");
    }
    return false;
}
static void refreshRows(Obj manager) {
    if(manager && ba::get<Obj>(manager,"_frontServer")==ba_dedicated_session::observedFront) {
        Root event(ba::get<Obj>(manager,"InvitesChanged"));if(event.get())ba::call(event.get(),"Invoke");
    }
}
static void removeSent(Obj owner,Obj message) {
    if(!owner || !message || ba::get<Obj>(owner,"_frontServer")!=ba_dedicated_session::observedFront)return;
    Root list(ba::get<Obj>(owner,"_pendingLobbyPlayerInvites"));
    const int count=ba_local::count(list.get());wire::require(count<=64,"native sent invitation capacity");
    for(int i=0;i<count;++i) {
        void* args[]={&i};Root item(ba::call(list.get(),"get_Item",1,args));
        if(item.get()==message){ba::call(list.get(),"RemoveAt",1,args);refreshRows(owner);return;}
    }
}
static void anchorClock(Obj front) {
    Root utc(ba::invoke(ba::find_class("System","DateTime"),nullptr,"get_UtcNow",0));
    Root realtime(ba::invoke(ba::find_class("UnityEngine","Time"),nullptr,"get_realtimeSinceStartup",0));
    ba::set<uint64_t>(front,"_serverTimeAtLogin",*ba::api<uint64_t*(*)(Obj)>("il2cpp_object_unbox")(utc.get()));
    ba::set<float>(front,"_realtimeAtServerLogin",*ba::api<float*(*)(Obj)>("il2cpp_object_unbox")(realtime.get()));
}
static int64_t expiry(Obj front,ULONGLONG deadline) {
    Root date(ba::call(front,"GetCurrentServerTime"));
    Obj value=ba::api<Obj(*)(Obj)>("il2cpp_object_unbox")(date.get());
    Root ticks(ba::invoke(ba::klass(date.get()),value,"get_Ticks",0));
    const auto now=GetTickCount64();
    return *ba::api<int64_t*(*)(Obj)>("il2cpp_object_unbox")(ticks.get())/10000-62135596800000ll+
        static_cast<int64_t>(deadline>now?deadline-now:0);
}
static void nativeUpdate(Obj front,Invitation& invite,int state,bool hostAccepted) {
    Root message(ba::make("FrontPb","PartyInviteUpdateNotification"));
    ba::set<Obj>(message.get(),"playerHandle_",hostAccepted?invite.target.get():invite.sender.get());
    ba::set<int>(message.get(),"inviteState_",state);ba::set<Obj>(message.get(),"frontReceiver_",native::localRaw());
    ba::set<Obj>(message.get(),"partyLeader_",invite.sender.get());
    ba::set<int>(message.get(),"partyType_",3);ba::set<int>(message.get(),"gameMode_",1);
    ba::native<void(*)(Obj,Obj,Obj)>(0x3e47c40)(front,message.get(),nullptr);
}
static void reconcileParty(Obj front) {
    const auto& lobby=native::authority;
    if(lobby.phase!=wire::Open || native::installedLobby!=lobby.id)return;
    Root party(ba::get<Obj>(front,"_party"));bool sameMembers=party.get() && ba::get<int>(party.get(),"PartyType")==3 &&
        ba::get<bool>(party.get(),"IsCreator")== (lobby.host==ba_community::welcome.profile);
    if(sameMembers) {
        Root members(ba::get<Obj>(party.get(),"Members"));sameMembers=ba_local::count(members.get())==static_cast<int>(lobby.members.size());
        for(int i=0;sameMembers && i<static_cast<int>(lobby.members.size());++i) {
            void* args[]={&i};Root member(ba::call(members.get(),"get_Item",1,args));
            sameMembers=member.get()==native::named(lobby.members[i].profile);
        }
    }
    if(sameMembers)return;
    Root response(ba::make("FrontPb","PartyInviteReplyResponse")),members(ba::get<Obj>(response.get(),"members_"));
    for(const auto& member:lobby.members)ba_local::addItem(members.get(),native::named(member.profile));
    Obj klass=ba::find_class("Uncapped","Party");ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(klass);
    Root replacement(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(klass));
    ba::native<void(*)(Obj,bool,Obj,int,Obj)>(0x3e4c470)(replacement.get(),lobby.host==ba_community::welcome.profile,members.get(),3,nullptr);
    if(party.get())ba::set<bool>(replacement.get(),"HasPlayedMatch",ba::get<bool>(party.get(),"HasPlayedMatch"));
    ba::set<Obj>(front,"_party",replacement.get());
    ba::log("Community Party reconciled: members=%llu creator=%d",static_cast<unsigned long long>(lobby.members.size()),lobby.host==ba_community::welcome.profile?1:0);
}
static void deliverIncoming(Obj front,Invitation& invite) {
    if(invite.incoming || invite.value.status!=0 || invite.value.target!=ba_community::welcome.profile)return;
    // Keep a terminal invite until its real pending reply captures GameMode.
    // A newer invitation by the same sender waits; native removal is by sender.
    for(const auto& item:invitations)if(item.second.get()!=&invite && (item.second->incoming || item.second->replies) &&
        item.second->value.sender==invite.value.sender)return;
    Root message(ba::make("FrontPb","PartyInviteRequestNotification"));
    ba::set<Obj>(message.get(),"playerHandle_",invite.sender.get());
    ba::set<int64_t>(message.get(),"expiryTimeUnixMilliseconds_",expiry(front,invite.deadline));
    ba::set<Obj>(message.get(),"frontReceiver_",native::localRaw());
    ba::set<int>(message.get(),"partyType_",3);ba::set<int>(message.get(),"gameMode_",1);
    wire::require(!delivering,"nested native invitation delivery");delivering=&invite;
    try{ba::native<void(*)(Obj,Obj,Obj)>(0x3e47f60)(front,message.get(),nullptr);}
    catch(...){delivering=nullptr;throw;}
    delivering=nullptr;
    void* args[]={invite.sender.get()};Root received(ba::call(front,"FindExistingPartyInvite",1,args));
    wire::require(received.get()!=nullptr,"native incoming invite was not retained");
    invite.incoming=std::make_unique<Root>(received.get());
    ba::log("Community native incoming invitation: id=%s sender=%s remainingMs=%u",invite.value.id.c_str(),invite.value.sender.c_str(),invite.value.milliseconds);
}
static void flush(Obj front) {
    for(auto& item:invitations) {
        auto& invite=*item.second;
        if(!invite.value.status){deliverIncoming(front,invite);continue;}
        if(invite.value.sender==ba_community::welcome.profile) {
            if(invite.sent)removeSent(invite.manager?invite.manager->get():nullptr,invite.sent->get());
            if(invite.value.status==1 && !invite.applied) {
                // Leave releases manager prediction immediately; Party itself
                // survives until LobbyClosed. Do not append or raise callbacks
                // into that departing lobby even if its last snapshot matches.
                if(leaving(invite.value.lobby)) {
                    invite.applied=true;
                    ba::log("Community accepted invitation ignored after native Leave: id=%s",invite.value.id.c_str());
                    continue;
                }
                const auto& lobby=native::authority;
                bool member=false;for(const auto& row:lobby.members)member|=row.profile==invite.value.target;
                if(lobby.id!=invite.value.lobby || lobby.host!=invite.value.sender || !member)continue;
                wire::require(ba::get<Obj>(front,"_party")!=nullptr,"accepted invitation lost host Party");
                nativeUpdate(front,invite,0,true);invite.applied=true;
                ba::log("Community host accepted invitation: id=%s; native member appended once",invite.value.id.c_str());
            } else if(invite.value.status!=1)invite.applied=true;
        } else if(!invite.replies) {
            if(invite.incoming && containsIncoming(front,invite.incoming->get()))nativeUpdate(front,invite,invite.value.status==2?1:2,false);
            invite.incoming.reset();invite.applied=true;
        }
    }
    for(auto it=invitations.begin();it!=invitations.end();) {
        const auto& invite=*it->second;bool referenced=false;
        for(const auto& op:operations)referenced|=op->invitation==it->first;
        if(invite.value.status && invite.applied && !referenced && !invite.replies) {
            finished.push_back(invite.value);if(finished.size()>256)finished.pop_front();it=invitations.erase(it);
        } else ++it;
    }
}
static void receive(Obj front,const wire::Invitation& value) {
    auto found=invitations.find(value.id);
    if(found==invitations.end()) {
        for(const auto& old:finished)if(old.id==value.id) {
            wire::require(same(old,value) && value.status==old.status,"community invitation replay changed identity/state");return;
        }
        wire::require(value.status==0 && invitations.size()<32,"unknown terminal invitation/capacity");
        auto record=std::make_unique<Invitation>(value);
        if(value.sender==ba_community::welcome.profile) {
            Operation* original=nullptr;
            for(auto& op:operations)if(op->kind==23 && op->request && op->profile==value.target && op->invitation.empty()) {
                wire::require(!original,"ambiguous outgoing native invitation");original=op.get();
            }
            wire::require(original && original->lobby==value.lobby,"unsolicited outgoing community invitation");
            original->invitation=value.id;record->sent=std::make_unique<Root>(original->message.get());
            record->manager=std::make_unique<Root>(original->manager.get());
        }
        invitations.emplace(value.id,std::move(record));
    } else {
        wire::require(same(found->second->value,value),"community invitation changed identity");
        wire::require(!found->second->value.status || found->second->value.status==value.status,"community invitation terminal state changed");
        found->second->value=value;
    }
    std::unique_ptr<Root> departedParty;
    if(value.status==1 && value.sender==ba_community::welcome.profile && ba::flag(L"-community-leave-accepted-smoke")) {
        Root owner(native::manager(front));departedParty=std::make_unique<Root>(ba::get<Obj>(front,"_party"));
        ba::native<void(*)(Obj,bool,Obj)>(0x3cab820)(owner.get(),false,nullptr);
        wire::require(!ba::call(owner.get(),"get_PredictedCustomGameLobby"),"late acceptance smoke manager not released");
    }
    flush(front);
    if(departedParty) {
        wire::require(ba::get<Obj>(front,"_party")==departedParty->get() &&
            ba_local::count(ba::get<Obj>(departedParty->get(),"Members"))==1,"late acceptance mutated departing Party");
        ba::log("COMMUNITY INVITE SMOKE late acceptance after native Leave: released prediction retained, departing Party unchanged");
    }
    Root owner(native::manager(front));refreshRows(owner.get());
}
static void enqueue(Obj front,Obj consumer,int kind) {
    wire::require(!resetting && native::owns(front) && operations.size()<32,"community invitation request ownership/capacity");
    Root message(ba::get<Obj>(consumer,"frontServerMessages_")),owner(native::manager(front));
    wire::require(message.get() && owner.get(),"community invitation request/manager missing");
    const char* handle=kind==25?"partyLeaderHandle_":"playerHandle_";
    const auto profile=profileForRaw(ba::get<Obj>(message.get(),handle));
    auto op=std::make_unique<Operation>(kind,message.get(),owner.get(),profile,native::named(profile));
    if(kind==23) {
        wire::require(ba::get<int>(message.get(),"partyType_")==3 && ba::get<int>(message.get(),"gameMode_")==1,
            "unsupported native community invitation mode");
        op->rejected=!canInvite(profile);op->lobby=native::authority.id;
    } else {
        Invitation* selected=nullptr;
        for(auto& item:invitations) {
            auto& candidate=*item.second;
            const bool matches=kind==25?candidate.value.sender==profile && candidate.value.target==ba_community::welcome.profile && candidate.incoming:
                candidate.value.target==profile && candidate.value.sender==ba_community::welcome.profile;
            if(matches && (!candidate.value.status || (kind==25 && candidate.incoming))) {
                wire::require(!selected,"ambiguous native invitation action");selected=&candidate;
            }
        }
        if(selected) {
            op->invitation=selected->value.id;op->lobby=selected->value.lobby;
            if(kind==25){op->accepted=ba::get<bool>(message.get(),"accepted_");op->rejected=selected->replies!=0;++selected->replies;}
        } else {
            op->rejected=true;
            // A real Cancel can follow Invite in the same UI update, before
            // the server has assigned an invitation ID. Wait for that exact
            // outstanding send rather than accidentally canceling a re-invite.
            if(kind==24)for(const auto& prior:operations)if(prior->kind==23 && prior->profile==profile && !prior->rejected) {
                op->rejected=false;op->lobby=prior->lobby;break;
            }
        }
        if(kind==25)wire::require(ba::get<int>(message.get(),"partyType_")==3,"unsupported native party reply");
    }
    if(ba_lan::stopped || !ba_community::online)op->rejected=true;
    operations.push_back(std::move(op));
    ba::log("Community native invitation operation queued: kind=%d target=%s; callback deferred",kind,profile.c_str());
}
static void completeOne(Obj front,Operation* op,bool success,const std::string& object,const std::string& reason) {
    auto found=invitations.find(op->invitation);Invitation* invite=found==invitations.end()?nullptr:found->second.get();
    if(op->kind==23) {
        if(success) {
            wire::require(invite && object==invite->value.id,"community invite ACK correlation lost");
            invite->acknowledged=true;
            if(!leaving(op->lobby)) {
                Root before(ba::get<Obj>(front,"_party")),response(ba::make("FrontPb","InvitePlayerToPartyResponse"));
                ba::set<Obj>(response.get(),"playerHandle_",op->other.get());ba::set<int>(response.get(),"partyType_",3);
                ba::set<bool>(response.get(),"automatedAcceptance_",true);
                ba::set<int64_t>(response.get(),"expiryTimeUnixMilliseconds_",expiry(front,invite->deadline));
                ba::native<void(*)(Obj,Obj,int,Obj)>(0x3e477f0)(front,response.get(),0,nullptr);
                wire::require(ba::get<Obj>(front,"_party")==before.get(),"native invite ACK replaced host Party");
            }
        } else {
            // Original error callback RemoveAll(target) can erase a newer valid
            // re-invite. Complete only this exact failed sent request instead.
            removeSent(op->manager.get(),op->message.get());
        }
    } else if(op->kind==25) {
        const bool accepted=success && op->accepted;
        if(accepted) {
            wire::require(invite && invite->value.status==1 && object==invite->value.lobby && native::authority.id==object &&
                native::authority.members.size()==2 && native::authority.host==invite->value.sender,
                "accepted native reply disagrees with lobby authority");
            wire::require(invite->incoming && containsIncoming(front,invite->incoming->get()),"accepted native reply lost original invitation");
        }
        if(accepted && !completionFailureInjected && ba::flag(L"-community-completion-failure-before")) {
            completionFailureInjected=true;throw std::runtime_error("injected community completion failure before native reply");
        }
        Root response(ba::make("FrontPb","PartyInviteReplyResponse"));
        ba::set<bool>(response.get(),"inParty_",accepted);ba::set<Obj>(response.get(),"inviter_",op->other.get());
        ba::set<int>(response.get(),"partyType_",3);
        if(accepted)for(const auto& member:native::authority.members)
            ba_local::addItem(ba::get<Obj>(response.get(),"members_"),native::named(member.profile));
        const int counter=ba::get<int>(front,"_pendingInviteResponseRequests");
        wire::require(counter>0,"native reply callback preceded request bookkeeping");
        op->counterBefore=counter;
        try{ba::native<void(*)(Obj,Obj,Obj)>(0x3e48050)(front,response.get(),nullptr);}
        catch(...) {
            op->replySettled=ba::get<int>(front,"_pendingInviteResponseRequests")==counter-1;throw;
        }
        op->replySettled=ba::get<int>(front,"_pendingInviteResponseRequests")==counter-1;
        wire::require(op->replySettled,"native reply counter mismatch");
        if(accepted && !completionFailureInjected && ba::flag(L"-community-completion-failure-after")) {
            completionFailureInjected=true;throw std::runtime_error("injected community completion failure after native reply");
        }
        if(invite){wire::require(invite->replies>0,"community reply accounting underflow");--invite->replies;invite->incoming.reset();}
        if(accepted)native::installedLobby=object;
        ba::log("Community native reply completed: accepted=%d counter=%d lobby=%s",accepted?1:0,counter-1,native::installedLobby.c_str());
    } else {
        Root response(ba::make("FrontPb","CancelInviteToPartyResponse"));
        ba::set<Obj>(response.get(),"playerHandle_",ba::get<Obj>(op->other.get(),"playerHandle_"));
        ba::native<void(*)(Obj,Obj,int,Obj)>(0x3e47b40)(front,response.get(),success?0:2,nullptr);
    }
    refreshRows(op->manager.get());
    ba::log("Community native invitation completion: kind=%d success=%d reason=%s",op->kind,success?1:0,reason.c_str());
}
static void complete(Obj front,std::unique_ptr<Operation> op,bool success,const std::string& object,const std::string& reason) {
    wire::require(!completing,"nested community invitation completion");
    // The native reply decrements early, before allocating Party/raising UI
    // events. Preserve both the request root and observed credit settlement
    // through any exception so explicit reconnect can finish the exact debt.
    completing=std::move(op);
    completeOne(front,completing.get(),success,object,reason);
    completing.reset();
}
static bool acknowledge(Obj front,const wire::Ack& ack) {
    for(auto it=operations.begin();it!=operations.end();++it)if((*it)->request==ack.request && ack.request) {
        auto op=std::move(*it);operations.erase(it);complete(front,std::move(op),ack.success,ack.object,ack.reason);return true;
    }
    return false;
}
static void dispatch(Obj front) {
    unsigned sent=0,completed=0;
    while(completed<32) {
        auto it=std::find_if(operations.begin(),operations.end(),[](const auto& op){return !op->request;});
        if(it==operations.end())break;
        auto& op=**it;
        if(op.kind==23 && native::authority.id!=op.lobby)op.rejected=true;
        if(op.kind==24 && op.invitation.empty() && !op.rejected) {
            for(const auto& item:invitations)if(item.second->value.sender==ba_community::welcome.profile &&
                item.second->value.target==op.profile && item.second->value.lobby==op.lobby && !item.second->value.status)
                op.invitation=item.first;
            if(op.invitation.empty()) {
                bool outstanding=false;
                for(const auto& prior:operations)outstanding|=prior->kind==23 && prior->profile==op.profile && !prior->rejected;
                if(outstanding)break;
                op.rejected=true;
            }
        }
        if(op.kind!=23) {
            const auto invite=invitations.find(op.invitation);
            if(invite==invitations.end() || invite->second->value.status)op.rejected=true;
        }
        if(op.rejected) {
            // Every native click increments the counter after enqueue. A
            // duplicate must still receive one callback, but the original
            // false response removes the incoming invite too. Let the first
            // reply capture GameMode before completing any later duplicate.
            bool earlierReply=false;
            if(op.kind==25)for(auto prior=operations.begin();prior!=it;++prior)
                earlierReply|=(*prior)->kind==25 && (*prior)->invitation==op.invitation;
            if(earlierReply)break;
            auto rejected=std::move(*it);operations.erase(it);++completed;
            // Native completion raises UI events which may enqueue another
            // operation. Never retain a deque iterator across that callback.
            complete(front,std::move(rejected),false,"","invitation no longer available");continue;
        }
        if(sent++>=4)break;
        const auto id=ba_community::nextRequest();
        op.request=ba_community::send(op.kind==23?wire::invite(id,op.profile):op.kind==25?wire::reply(id,op.invitation,op.accepted):wire::cancel(id,op.invitation));
    }
}
static void reset(Obj front) {
    resetting=true;
    struct Guard {~Guard(){resetting=false;delivering=nullptr;}} guard;
    if(completing) {
        auto op=std::move(completing);
        if(op->kind!=25 || !op->replySettled)complete(front,std::move(op),false,"","community completion interrupted");
        else ba::log("Community interrupted native reply already settled: no duplicate counter decrement");
    }
    while(!operations.empty()) {
        auto op=std::move(operations.front());operations.pop_front();
        complete(front,std::move(op),false,"","community session ended");
    }
    for(auto& item:invitations) {
        auto& invite=*item.second;
        if(invite.sent)removeSent(invite.manager?invite.manager->get():nullptr,invite.sent->get());
        if(invite.incoming && containsIncoming(front,invite.incoming->get()))nativeUpdate(front,invite,2,false);
    }
    invitations.clear();finished.clear();resetSmoke();
    if(front)wire::require(ba::get<int>(front,"_pendingInviteResponseRequests")==0,"community reset retained native reply counter");
}
static void smoke(Obj); // Defined after the popup adapter's ownership resolver.
}
