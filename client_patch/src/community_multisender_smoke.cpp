#pragma once
// Included inside ba_community_invites after verifyParty. Explicit owned
// loopback diagnostics only; original picker/popup callbacks remain unchanged.
struct MultiInviteProbe {
    unsigned stage=0,status=0;
    ULONGLONG started=GetTickCount64(),at=0;
    std::string role,target,id,sender,lobby;
    std::unique_ptr<Root> button,party;
};
static void multisenderSmoke(Obj front) {
    wire::require(!ba::flag(L"-community-invite-host-smoke") && !ba::flag(L"-community-invite-guest-smoke"),
        "multisender diagnostic cannot overlap another invitation probe");
    const auto endpoint=ba::argument(L"-dedicated-server=");
    const auto profile=ba::argument(L"-local-profile=");
    wire::require(endpoint.rfind("127.0.0.1:",0)==0 && profile.rfind("nativeprobe_",0)==0,
        "multisender diagnostic requires owned loopback/nativeprobe arguments");
    // Never destroy managed roots from CRT/DllMain shutdown after IL2CPP stops.
    // No allocation occurs for an ordinary client, which never calls this path.
    static auto& probe=*new std::unique_ptr<MultiInviteProbe>();
    if(!probe) {
        probe=std::make_unique<MultiInviteProbe>();
        probe->role=ba::argument(L"-community-multisender-role=");
        probe->target=ba::argument(L"-community-multisender-target=");
        wire::require((probe->role=="first" || probe->role=="second" || probe->role=="target") &&
            probe->target.rfind("multi_target_",0)==0 && probe->target.size()<=64,
            "multisender diagnostic role/target invalid");
    }
    auto& p=*probe;const auto now=GetTickCount64();
    wire::require(p.stage==9 || now-p.started<120000,"multisender native diagnostic deadline");
    if(!native::installed || !ba_community::online || native::directory.players.size()!=3)return;
    wire::require(native::owns(front) && !ba_lan::welcomed && ba_lan::bootstrap.empty() &&
        ba_lan::dedicatedMatchId.empty() && ba_dedicated_session::inMenu(),
        "multisender probe acquired a match or lost its owned menu");
    Root owner(native::manager(front));
    const bool target=p.role=="target";
    wire::require((ba_community::welcome.profile==p.target)==target,"multisender target identity mismatch");
    if(p.stage==0 && now-p.started<2500)return; // Same original-menu settling interval as the invitation probe.
    if(p.stage==9) {
        verifyParty(front,target || p.status==1?2:1,!target);
        wire::require(operations.empty() && !completing && invitations.empty() &&
            ba_local::count(ba::get<Obj>(front,"_partyInvites"))==0,"multisender settled state retained invites/credits");
        if(!target && p.status==5)wire::require(ba::get<Obj>(front,"_party")==p.party->get() &&
            native::installedLobby==p.lobby,"unselected inviter moved to another Party/lobby");
        return;
    }
    if(target) {
        if(p.stage==0) {
            Root panel(ba_community_popup::ready());
            if(!panel.get() || ba_community_popup::owned->paint || ba::get<int>(panel.get(),"_receivedInviteCount")!=2)return;
            wire::require(!ba::get<Obj>(front,"_party") && ba_local::count(ba::get<Obj>(front,"_partyInvites"))==2,
                "multisender target requires two independent native invitations");
            Root first(ba::call(front,"get_FirstPartyInvite"));auto* chosen=incomingFor(first.get());
            wire::require(chosen && chosen->value.status==0 && chosen->value.target==p.target,
                "multisender original popup has no current invitation");
            ba_community_roster::verifyRenderedName(ba_community_popup::owned->inviteChild.get(),
                ba_community_roster::literalName(ba_catalog::utf8(ba::get<Obj>(chosen->sender.get(),"playerName_"))));
            p.id=chosen->value.id;p.sender=chosen->value.sender;p.lobby=chosen->value.lobby;p.stage=1;
            const int before=ba::get<int>(front,"_pendingInviteResponseRequests");
            ba::native<void(*)(Obj,Obj)>(0x3d24700)(panel.get(),nullptr);
            wire::require(ba::get<int>(front,"_pendingInviteResponseRequests")==before+1,
                "multisender Accept did not retain its deferred native reply");
            ba::log("MULTI INVITE target accepted original popup: invite=%s sender=%s lobby=%s received=2 pendingDelta=1",
                p.id.c_str(),p.sender.c_str(),p.lobby.c_str());
        } else if(p.stage==1 && operations.empty() && !completing && invitations.empty() &&
                  !ba_community_popup::owned && ba::get<int>(front,"_pendingInviteResponseRequests")==0) {
            verifyParty(front,2,false);
            wire::require(native::authority.host==p.sender && native::authority.id==p.lobby &&
                native::installedLobby==p.lobby && ba_community_roster::mainScreen()!=nullptr,
                "multisender accepted target entered the wrong lobby");
            p.status=1;p.stage=9;
            ba::log("MULTI INVITE target settled: sender=%s lobby=%s members=2 replyCounter=0 incoming=0 popup=0 world=0",
                p.sender.c_str(),p.lobby.c_str());
        }
        return;
    }
    if(p.stage==0) {
        wire::require(native::installedLobby.empty() && native::authority.phase==wire::None && !ba::get<Obj>(front,"_party"),
            "multisender inviter already owns a lobby");
        Root controller(ba::get<Obj>(owner.get(),"_menuFlowController")),link(ba::make("Uncapped.UI","UILink"));
        ba::set<int>(link.get(),"PrefabKey",97);p.stage=1;
        ba::native<void(*)(Obj,Obj,Obj)>(0x3d52440)(controller.get(),link.get(),nullptr);
    } else if(p.stage==1 && !native::installedLobby.empty() && native::requests.empty()) {
        Root main(ba_community_roster::mainScreen());if(!main.get())return;
        verifyParty(front,1,true);p.lobby=native::installedLobby;p.party=std::make_unique<Root>(ba::get<Obj>(front,"_party"));
        p.button=std::make_unique<Root>(ba_community_roster::pickerButton(main.get()));
        if(!ba_community_roster::screen)ba::native<void(*)(Obj,Obj)>(0x3d62c40)(p.button->get(),nullptr);
        p.stage=2;p.at=now+500;
    } else if(p.stage==2 && now>=p.at) {
        if(!ba_community_roster::screen || ba_community_roster::rows.size()!=3)return;
        ba_community_roster::Row* chosen=nullptr;
        for(const auto& row:ba_community_roster::rows)if(row->profile==p.target)chosen=row.get();
        wire::require(chosen && canInvite(p.target) && ba::get<bool>(chosen->row.get(),"_canInvite"),
            "multisender target row is not eligible");
        ba_community_roster::verifyRenderedName(chosen->child.get(),
            ba_community_roster::literalName(native::player(p.target)->name));
        p.stage=3;ba::native<void(*)(Obj,Obj)>(0x3ca8f20)(chosen->row.get(),nullptr);
        wire::require(!operations.empty() && ba::get<Obj>(front,"_party")==p.party->get() &&
            ba_local::count(ba::get<Obj>(owner.get(),"_pendingLobbyPlayerInvites"))==1,
            "multisender original Invite lost deferred request bookkeeping");
        ba::log("MULTI INVITE host sent original picker: role=%s target=%s lobby=%s members=1",
            p.role.c_str(),p.target.c_str(),p.lobby.c_str());
    } else if(p.stage==3) {
        if(p.id.empty()) {
            for(const auto& item:invitations)if(item.second->value.sender==ba_community::welcome.profile &&
                item.second->value.target==p.target)p.id=item.first;
            if(p.id.empty())for(const auto& item:finished)if(item.sender==ba_community::welcome.profile && item.target==p.target)p.id=item.id;
            if(p.id.empty())return;
        }
        const unsigned status=terminal(p.id);
        if(!status || !operations.empty() || completing || !invitations.empty())return;
        wire::require(status==1 || status==5,"multisender invitation was not accepted or superseded as busy");
        verifyParty(front,status==1?2:1,true);
        wire::require(native::installedLobby==p.lobby && native::authority.id==p.lobby &&
            (status==1 || ba::get<Obj>(front,"_party")==p.party->get()),"unselected inviter Party/lobby changed");
        p.status=status;p.stage=9;
        ba::log("MULTI INVITE host settled: role=%s invite=%s lobby=%s status=%u members=%u replyCounter=0 sent=0 world=0 partyUnchanged=%d",
            p.role.c_str(),p.id.c_str(),p.lobby.c_str(),status,status==1?2:1,ba::get<Obj>(front,"_party")==p.party->get()?1:0);
    }
}
