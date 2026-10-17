#pragma once
// The game's notification owns the panel and its buttons/countdown. We replace
// only this panel's friend lookup and child presentation, never Steam's table.
namespace ba_community_popup {
using ba::Obj;using ba_local::Root;
namespace wire=ba_community_wire;
namespace native=ba_community_native;
namespace roster=ba_community_roster;
struct Panel {
    Root object,owner,inviteChild,partyChild;
    std::unique_ptr<Root> model;
    std::string profile;
    uint64_t serial,marked=0;
    bool lookup=false,paint=false;
    Panel(Obj p,uint64_t generation):object(p),owner(ba::get<Obj>(p,"<Owner>k__BackingField")),
        inviteChild(ba::get<Obj>(p,"_playerInviteFriendVM")),partyChild(ba::get<Obj>(p,"_partyMemberFriendVM")),serial(generation){}
};
static auto& owned=*new std::unique_ptr<Panel>();
static uint64_t serial=0;
static bool exact(Obj object,const char* ns,const char* name) {
    return object && ba::klass(object)==ba::find_class(ns,name);
}
static bool live(Obj object) {return roster::initialized(object) && ba::read<uintptr_t>(object,0x10)!=0;}
static bool bindingsReady(Obj child) {
    if(!live(child))return false;
    Root bindings(ba::get<Obj>(child,"_bindings"));
    return bindings.get() && ba::get<bool>(bindings.get(),"_initialized");
}
static void validate(Obj panel) {
    Obj front=ba_dedicated_session::observedFront;
    wire::require(native::owns(front) && native::installed && exact(panel,"Uncapped.UI","MatchmakingStatusPanelVM") &&
        live(panel) && ba::read<bool>(panel,0x50) && ba::get<Obj>(panel,"_frontServerIntegration")==front,
        "community popup panel ownership");
    Root router(ba::get<Obj>(front,"_signalRouter")),services(ba::get<Obj>(panel,"_serverManager"));
    Root model(ba::get<Obj>(panel,"_model")),owner(ba::get<Obj>(panel,"<Owner>k__BackingField"));
    wire::require(router.get() && services.get() && owner.get() && ba::get<Obj>(services.get(),"_frontServerIntegration")==front &&
        ba::get<Obj>(panel,"_signalRouter")==router.get() && exact(model.get(),"Uncapped.UI","MatchmakingStateModel") &&
        ba::get<Obj>(model.get(),"_matchmakingFrontEnd")==front && ba::get<Obj>(model.get(),"_signalRouter")==router.get(),
        "community popup model/router ownership");
    for(const char* name:{"_playerInviteFriendVM","_partyMemberFriendVM"}) {
        Root child(ba::get<Obj>(panel,name));
        wire::require(exact(child.get(),"Uncapped.UI","FriendVM") &&
            ba::get<Obj>(child.get(),"<Owner>k__BackingField")==owner.get(),"community popup child ownership");
    }
}
static Obj resolve() {
    Obj front=ba_dedicated_session::observedFront;
    if(!native::owns(front) || !native::installed)return nullptr;
    Root event(ba::get<Obj>(front,"MatchmakingStateChange"));if(!event.get())return nullptr;
    Root listeners(ba::call(event.get(),"GetInvocationList"));
    const auto count=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(listeners.get());
    wire::require(count<=128,"community popup observer capacity");Obj result=nullptr;
    for(size_t i=0;i<count;++i) {
        Root target(ba::call(ba::read<Obj>(listeners.get(),0x20+i*sizeof(Obj)),"get_Target"));
        if(!exact(target.get(),"Uncapped.UI","MatchmakingStatusPanelVM"))continue;
        validate(target.get());
        wire::require(!result || result==target.get(),"multiple community matchmaking panels");result=target.get();
    }
    return result;
}
static Obj notification() {
    Obj front=ba_dedicated_session::observedFront;
    Root router(ba::get<Obj>(front,"_signalRouter")),lookup(ba::get<Obj>(router.get(),"_typeLookup"));
    Root type(roster::reflectedType("Uncapped","MatchmakingStatusSignal"));
    int index=-1;void* args[]={type.get(),&index};Root found(ba::call(lookup.get(),"TryGetValue",2,args));
    if(!*ba::api<bool*(*)(Obj)>("il2cpp_object_unbox")(found.get()))return nullptr;
    Root collections(ba::get<Obj>(router.get(),"_handlerCollections"));const int count=ba_local::count(collections.get());
    wire::require(count<=4096 && index>=0 && index<count,"community notification collection index");
    void* itemArgs[]={&index};Root collection(ba::call(collections.get(),"get_Item",1,itemArgs));
    wire::require(!strcmp(ba_dedicated_session::className(collection.get()),"HandlerCollection`1") &&
        ba::api<Obj(*)(Obj)>("il2cpp_class_get_declaring_type")(ba::klass(collection.get()))==ba::find_class("Uncapped","SignalRouter"),
        "community notification collection class");
    Root closedType(ba::api<Obj(*)(Obj)>("il2cpp_type_get_object")(ba::api<Obj(*)(Obj)>("il2cpp_class_get_type")(ba::klass(collection.get()))));
    Root genericArgs(ba::call(closedType.get(),"GetGenericArguments"));
    wire::require(ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(genericArgs.get())==1 &&
        ba::read<Obj>(genericArgs.get(),0x20)==type.get(),"community notification signal type");
    Root changes(ba::get<Obj>(collection.get(),"_pendingCollectionChanges"));
    if(ba::get<int>(collection.get(),"_handlingCount") || (changes.get() && ba_local::count(changes.get())))return nullptr;
    Root handlers(ba::get<Obj>(collection.get(),"_handlers"));const int handlerCount=ba_local::count(handlers.get());
    wire::require(handlerCount<=128,"community notification handler capacity");Obj result=nullptr;unsigned visited=0;
    for(int i=0;i<handlerCount;++i) {
        void* at[]={&i};Root action(ba::call(handlers.get(),"get_Item",1,at)),entries(ba::call(action.get(),"GetInvocationList"));
        const auto entriesCount=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(entries.get());
        wire::require(entriesCount<=64 && visited+entriesCount<=256,"community notification delegate capacity");
        visited+=static_cast<unsigned>(entriesCount);
        for(size_t j=0;j<entriesCount;++j) {
            Root target(ba::call(ba::read<Obj>(entries.get(),0x20+j*sizeof(Obj)),"get_Target"));
            if(!exact(target.get(),"Uncapped.UI","MatchmakingNotification"))continue;
            wire::require(ba::get<Obj>(target.get(),"_signalRouter")==router.get() && (!result || result==target.get()),
                "community notification ownership/uniqueness");result=target.get();
        }
    }
    return result;
}
static void clear() {
    if(!owned)return;
    for(Obj child:{owned->inviteChild.get(),owned->partyChild.get()})if(live(child))roster::present(child,nullptr);
    owned->profile.clear();owned->model.reset();owned->paint=false;
}
static void reset() {
    if(owned && live(owned->object.get()))clear();
    owned.reset();
}
static wire::Player playerFor(const std::string& profile) {
    if(const auto* player=native::player(profile))return *player;
    // A terminal event may precede its sender's directory departure. The rooted
    // canonical name remains valid until the exact invitation is completed.
    return {profile,ba_catalog::utf8(ba::get<Obj>(native::named(profile),"playerName_")),0,false};
}
static std::string candidate(Obj panel,uint64_t key) {
    Obj front=ba_dedicated_session::observedFront;
    wire::require(!ba::get<bool>(panel,"_inQueue"),"community invitation popup unexpectedly in queue");
    Root party(ba::get<Obj>(front,"_party"));
    if(!party.get()) {
        Root incoming(ba::call(front,"get_FirstPartyInvite"));
        auto* record=ba_community_invites::incomingFor(incoming.get());
        if(record && ba_community::alias(record->value.sender)==key)return record->value.sender;
        return {};
    }
    wire::require(ba::get<int>(party.get(),"PartyType")==3,"community popup unsupported Party");
    Root members(ba::get<Obj>(party.get(),"Members"));const int count=ba_local::count(members.get());
    wire::require(count>=1 && count<=2,"community popup party capacity");
    for(int i=0;i<count;++i) {
        void* at[]={&i};Root member(ba::call(members.get(),"get_Item",1,at));
        for(const auto& allowed:native::authority.members)if(allowed.profile!=ba_community::welcome.profile &&
            ba_community::alias(allowed.profile)==key && member.get()==native::named(allowed.profile))return allowed.profile;
    }
    return {};
}
static bool lookup(Obj dictionary,uint64_t key,Obj* output) {
    wire::require(output!=nullptr,"community popup lookup output missing");*output=nullptr;
    Root panel(resolve());wire::require(panel.get()!=nullptr,"community popup lookup has no owner");
    Root friends(ba::get<Obj>(panel.get(),"_uncappedSteamFriends"));
    wire::require(friends.get() && ba::get<Obj>(friends.get(),"_lookupFriends")==dictionary,"community popup dictionary ownership");
    wire::require(!owned || owned->object.get()==panel.get() || !live(owned->object.get()),"community popup pooled generation overlap");
    if(!owned || owned->object.get()!=panel.get())owned=std::make_unique<Panel>(panel.get(),++serial);
    const auto profile=candidate(panel.get(),key);owned->lookup=true;
    if(profile.empty()){clear();return false;}
    if(owned->profile!=profile || !owned->model) {
        owned->profile=profile;owned->model=std::make_unique<Root>(roster::modelFor(playerFor(profile)));
    }
    *output=owned->model->get();return true;
}
static void child(Obj object,Obj model) {
    wire::require(owned && (owned->inviteChild.get()==object || owned->partyChild.get()==object) &&
        owned->model && owned->model->get()==model,"community popup child/model outside ownership");
    validate(owned->object.get());
    // Parent Initialize can arrive before the child's bindings. The completed
    // native Refresh schedules one full repaint on the next Unity update.
}
static void refreshed(Obj panel) {
    if(!owned || owned->object.get()!=panel)return;
    validate(panel);
    if(!owned->lookup)clear();
    owned->lookup=false;owned->paint=!owned->profile.empty();owned->marked=ba_dedicated_session::updateSequence;
}
static Obj ready() {
    if(!owned || !live(owned->object.get()))return nullptr;
    Root panel(resolve());if(!panel.get() || panel.get()!=owned->object.get())return nullptr;
    Root notice(notification());
    if(!notice.get() || ba::get<Obj>(notice.get(),"_viewModel")!=panel.get())return nullptr;
    if(!ba::get<bool>(owned->owner.get(),"<IsInitialized>k__BackingField") ||
        !bindingsReady(owned->inviteChild.get()) || !bindingsReady(owned->partyChild.get()))return nullptr;
    return panel.get();
}
static void update() {
    if(!owned)return;
    if(!live(owned->object.get())){owned.reset();return;}
    Root panel(resolve());if(!panel.get() || panel.get()!=owned->object.get()){owned.reset();return;}
    if(!owned->paint || ba_dedicated_session::updateSequence<=owned->marked || !ready())return;
    const auto player=playerFor(owned->profile);
    roster::present(owned->inviteChild.get(),&player);roster::present(owned->partyChild.get(),&player);owned->paint=false;
    ba::log("Community popup painted: generation=%llu profile=%s childrenUnbound=1 BA_RESURRECTION_COMMUNITY_INVITES_V1",
        static_cast<unsigned long long>(owned->serial),owned->profile.c_str());
}
}

extern "C" __declspec(dllexport) bool OfflineCommunityPopupLookup(void* dictionary,uint64_t key,void** output) {
    ba::init();
    if(!ba::community())return ba::native<bool(*)(ba::Obj,uint64_t,ba::Obj*)>(0x4ef130)(dictionary,key,output);
    try{return ba_community_popup::lookup(dictionary,key,output);}
    catch(const std::exception& e){if(output)*output=nullptr;ba_lan::fail("community popup lookup",e);return false;}
}
extern "C" __declspec(dllexport) void OfflineCommunityPopupChild(void* child,void* model,void* method) {
    ba::init();
    if(!ba::community()){ba_community_roster::virtualBind(child,model,method);return;}
    try{ba_community_popup::child(child,model);}
    catch(const std::exception& e){ba_lan::fail("community popup child",e);}
}
extern "C" __declspec(dllexport) bool OfflineCommunityPopupRefreshed(void* panel,int* backing,int value,void* property,void* alsoUpdate,void* method) {
    ba::init();
    const bool changed=ba::native<bool(*)(ba::Obj,int*,int,ba::Obj,ba::Obj,ba::Obj)>(0x236780)(panel,backing,value,property,alsoUpdate,method);
    if(ba::community())try {
        ba_community_wire::require(backing==reinterpret_cast<int*>(static_cast<char*>(panel)+0xbc),"community popup Refresh backing");
        ba_community_popup::refreshed(panel);
    }catch(const std::exception& e){ba_lan::fail("community popup refresh",e);}
    return changed;
}
extern "C" __declspec(dllexport) void OfflineCommunityPopupRelease(uint16_t slot,void* interfaceClass,void* pool,void* object) {
    ba::init();
    if(ba::community())try {
        using namespace ba_community_popup;
        if(owned && owned->object.get()==object) {
            validate(object);wire::require(slot==4 && ba::get<Obj>(owned->owner.get(),"_pool")==pool,"community popup release pool");
            clear();owned.reset();ba::log("Community popup released: ownedModels=0");
        }
    }catch(const std::exception& e){ba_lan::fail("community popup release",e);}
    ba::native<void(*)(uint16_t,ba::Obj,ba::Obj,ba::Obj)>(0x13e00)(slot,interfaceClass,pool,object);
}

namespace ba_community_invites {
static unsigned probeStage=0,probeRound=0;
static ULONGLONG probeAt=0;
static std::string probeId;
static auto& probeButton=*new std::unique_ptr<Root>();
static void resetSmoke() {probeButton.reset();probeStage=0;probeRound=0;probeAt=0;probeId.clear();}
static unsigned terminal(const std::string& id) {
    auto current=invitations.find(id);if(current!=invitations.end())return current->second->value.status;
    for(const auto& value:finished)if(value.id==id)return value.status;
    return 0;
}
static void verifyParty(Obj front,unsigned count,bool creator) {
    Root party(ba::get<Obj>(front,"_party")),owner(native::manager(front));
    wire::require(party.get() && ba::get<int>(party.get(),"PartyType")==3 && ba::get<bool>(party.get(),"IsCreator")==creator &&
        ba_local::count(ba::get<Obj>(party.get(),"Members"))==static_cast<int>(count),"community invite smoke Party mismatch");
    Root predicted(ba::call(owner.get(),"get_PredictedCustomGameLobby"));
    Root state(predicted.get()?ba::call(predicted.get(),"get_CurrentState"):nullptr);
    wire::require(state.get() && ba_local::count(ba::get<Obj>(state.get(),"members_"))==static_cast<int>(count),
        "community invite smoke native lobby mismatch");
    wire::require(ba::get<int>(front,"_pendingInviteResponseRequests")==0 &&
        ba_local::count(ba::get<Obj>(owner.get(),"_pendingLobbyPlayerInvites"))==0,"community invitation bookkeeping retained");
}
static void smoke(Obj front) {
    const bool host=ba::flag(L"-community-invite-host-smoke"),guest=ba::flag(L"-community-invite-guest-smoke");
    if(!host && !guest)return;
    wire::require(host!=guest,"ambiguous community invitation smoke role");
    const bool recovery=ba::flag(L"-community-invite-recovery-smoke");
    const bool earlyLeave=ba::flag(L"-community-leave-accepted-smoke");
    if(guest && recovery && ba_dedicated_session::recoverySmokeStage==1 && native::installed && ba_community::online) {
        if(probeStage==9)return;
        Root owner(native::manager(front));
        wire::require(native::installedLobby.empty() && native::authority.phase==wire::None &&
            !ba::get<Obj>(front,"_party") && !ba::call(owner.get(),"get_PredictedCustomGameLobby") &&
            ba::get<int>(front,"_pendingInviteResponseRequests")==0 && operations.empty() && !completing &&
            invitations.empty() && !ba_community_popup::owned,"community invitation retry retained native state");
        probeStage=9;ba::log("COMMUNITY INVITE RECOVERY guest passed: fresh presence, party=0 prediction=0 replyCounter=0 ownedInvites=0");return;
    }
    const auto now=GetTickCount64();if(!probeAt){probeAt=now+2500;return;}if(now<probeAt)return;
    Root owner(native::manager(front));
    if(host) {
        if(probeStage==0 && native::directory.players.size()==2) {
            Root controller(ba::get<Obj>(owner.get(),"_menuFlowController")),link(ba::make("Uncapped.UI","UILink"));
            ba::set<int>(link.get(),"PrefabKey",97);probeStage=1;
            ba::native<void(*)(Obj,Obj,Obj)>(0x3d52440)(controller.get(),link.get(),nullptr);
        } else if(probeStage==1 && !native::installedLobby.empty() && native::requests.empty()) {
            Root main(ba_community_roster::mainScreen());if(!main.get())return;
            if(!probeButton)probeButton=std::make_unique<Root>(ba_community_roster::pickerButton(main.get()));
            if(!ba_community_roster::screen)ba::native<void(*)(Obj,Obj)>(0x3d62c40)(probeButton->get(),nullptr);
            probeStage=2;probeAt=now+500;
        } else if(probeStage==2) {
            wire::require(ba_community_roster::screen && ba_community_roster::rows.size()==2,"community invite smoke picker missing");
            ba_community_roster::Row* chosen=nullptr;
            for(const auto& row:ba_community_roster::rows)if(row->profile!=ba_community::welcome.profile)chosen=row.get();
            wire::require(chosen && canInvite(chosen->profile) && ba::get<bool>(chosen->row.get(),"_canInvite"),"community invite smoke row unavailable");
            ba_community_roster::verifyRenderedName(chosen->child.get(),ba_community_roster::literalName(native::player(chosen->profile)->name));
            Root row(chosen->row.get()),party(ba::get<Obj>(front,"_party"));probeStage=3;probeId.clear();probeAt=now+2000;
            ba::native<void(*)(Obj,Obj)>(0x3ca8f20)(row.get(),nullptr);
            wire::require(!operations.empty() && ba::get<Obj>(front,"_party")==party.get() &&
                ba_local::count(ba::get<Obj>(owner.get(),"_pendingLobbyPlayerInvites"))==1,"native invite enqueue bookkeeping");
            ba::log("COMMUNITY INVITE SMOKE host sent round=%u through native picker action; callback deferred",probeRound);
        } else if(probeStage==3) {
            if(probeId.empty()) {
                for(const auto& item:invitations)if(item.second->value.sender==ba_community::welcome.profile)probeId=item.first;
                if(probeId.empty() && !finished.empty())probeId=finished.back().id;
                if(probeId.empty())return;
            }
            if(probeRound==1 && !terminal(probeId)) {
                auto found=invitations.find(probeId);wire::require(found!=invitations.end(),"community cancel smoke lost invitation");
                Obj raw=ba::get<Obj>(found->second->target.get(),"playerHandle_");void* args[]={raw};
                ba::call(front,"CancelInviteToPartyRequest",1,args);probeStage=4;
                ba::log("COMMUNITY INVITE SMOKE host native Cancel requested");return;
            }
            probeStage=4;
        } else if(probeStage==4) {
            const unsigned status=terminal(probeId);if(!status || !operations.empty())return;
            const unsigned expected[]={2,3,4,1};wire::require(status==expected[probeRound],"community invitation terminal state mismatch");
            if(earlyLeave && probeRound==3) {
                if(!native::installedLobby.empty() || !native::requests.empty())return;
                wire::require(!ba::get<Obj>(front,"_party") && !ba::call(owner.get(),"get_PredictedCustomGameLobby"),"late acceptance smoke retained departing lobby");
                probeStage=7;ba::log("COMMUNITY INVITE SMOKE host passed: late acceptance after native Leave; no lobby revival");return;
            }
            ba::log("COMMUNITY INVITE SMOKE host terminal round=%u status=%u",probeRound,status);
            if(probeRound<3){verifyParty(front,1,true);++probeRound;probeStage=1;probeAt=now+750;}
            else {verifyParty(front,recovery?static_cast<unsigned>(native::authority.members.size()):2,true);probeStage=5;ba::call(probeButton->get(),"Hide");}
        } else if(probeStage==5 && native::authority.members.size()==1) {
            verifyParty(front,1,true);probeStage=6;
            ba::native<void(*)(Obj,bool,Obj)>(0x3cab820)(owner.get(),false,nullptr);
        } else if(probeStage==6 && native::installedLobby.empty() && native::requests.empty()) {
            wire::require(!ba::get<Obj>(front,"_party") && operations.empty() && invitations.empty(),"community host final cleanup");
            probeStage=7;ba::log("COMMUNITY INVITE SMOKE host passed: decline cancel expiry accept guest-leave host-leave; presence retained");
        }
    } else {
        if(probeStage==0) {
            Root panel(ba_community_popup::ready());if(!panel.get() || ba_community_popup::owned->paint)return;
            Root current(ba::call(front,"get_FirstPartyInvite"));auto* invite=incomingFor(current.get());
            if(!invite || invite->value.status)return;
            wire::require(invite->value.id!=probeId && !ba::get<Obj>(front,"_party") && !ba::get<bool>(panel.get(),"_inQueue"),
                "community guest smoke requires current simple invite");
            const int seconds=ba::get<int>(panel.get(),"_inviteExpirationTime");if(seconds<=0)return;
            wire::require(seconds<=30 && ba::get<int>(panel.get(),"_receivedInviteCount")==1,"community popup countdown/count mismatch");
            ba_community_roster::verifyRenderedName(ba_community_popup::owned->inviteChild.get(),
                ba_community_roster::literalName(ba_catalog::utf8(ba::get<Obj>(invite->sender.get(),"playerName_"))));
            wire::require(!ba::read<bool>(ba_community_popup::owned->inviteChild.get(),0x50) &&
                !ba::read<bool>(ba_community_popup::owned->partyChild.get(),0x50),"community popup child unexpectedly observes Steam model");
            probeId=invite->value.id;probeStage=1;
            ba::log("COMMUNITY INVITE SMOKE guest popup round=%u TMP text active and countdown=%d verified",probeRound,seconds);
            if(probeRound==0 || probeRound==3) {
                const int before=ba::get<int>(front,"_pendingInviteResponseRequests");
                ba::native<void(*)(Obj,Obj)>(probeRound==0?0x3d24910:0x3d24700)(panel.get(),nullptr);
                wire::require(ba::get<int>(front,"_pendingInviteResponseRequests")==before+1,"native popup reply was completed too early");
                ba::log("COMMUNITY INVITE SMOKE guest native %s returned with one pending reply",probeRound==0?"Decline":"Accept");
                if(probeRound==3) {
                    ba::native<void(*)(Obj,Obj)>(0x3d24700)(panel.get(),nullptr);
                    wire::require(ba::get<int>(front,"_pendingInviteResponseRequests")==before+2,"duplicate native Accept bookkeeping");
                    ba::log("COMMUNITY INVITE SMOKE duplicate native Accept retained two replies; only first may reach server");
                }
            }
        } else if(probeStage==1) {
            const unsigned status=terminal(probeId);if(!status || !operations.empty())return;
            const unsigned expected[]={2,3,4,1};wire::require(status==expected[probeRound],"community guest terminal mismatch");
            wire::require(ba::get<int>(front,"_pendingInviteResponseRequests")==0 && !ba_community_popup::owned &&
                ba_local::count(ba::get<Obj>(front,"_partyInvites"))==0,"community guest invitation/popup retained");
            ba::log("COMMUNITY INVITE SMOKE guest terminal round=%u status=%u counter=0 popupReleased=1",probeRound,status);
            if(probeRound<3){++probeRound;probeStage=0;}
            else {
                verifyParty(front,earlyLeave?static_cast<unsigned>(native::authority.members.size()):2,
                    earlyLeave && native::authority.host==ba_community::welcome.profile);
                wire::require(ba_community_roster::mainScreen()!=nullptr,"accepted guest did not enter native custom screen");
                probeStage=2;probeAt=now+5000;
            }
        } else if(probeStage==2) {
            if(earlyLeave)verifyParty(front,1,true);
            probeStage=3;ba::native<void(*)(Obj,bool,Obj)>(0x3cab820)(owner.get(),false,nullptr);
        } else if(probeStage==3 && native::installedLobby.empty() && native::requests.empty()) {
            wire::require(!ba::get<Obj>(front,"_party") && operations.empty() && invitations.empty(),"community guest final cleanup");
            probeStage=4;ba::log("COMMUNITY INVITE SMOKE guest passed: four native popups and native Decline/Accept; presence retained");
        }
    }
}
}
