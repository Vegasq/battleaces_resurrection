#pragma once
// Owned C/local4/C/public1/C diagnostic. Never clears live production owners.
namespace ba_custom_transition {
using ba::Obj;using ba_local::Root;
namespace native=ba_community_native;
namespace custom=ba_community_match;
namespace wire=ba_community_wire;
static unsigned phase=0;
static bool armed=false,prepared=false,startReleased=false,customReturned=false,leaveIssued=false,connectIssued=false,edited=false;
static ULONGLONG gateBegan=0;
static bool isCustom(){return phase==0 || phase==2 || phase==4;}
static bool enabled() {
    if(!ba::flag(L"-custom-transition-smoke"))return false;
    const bool host=ba::flag(L"-community-match-host-smoke"),guest=ba::flag(L"-community-match-guest-smoke");
    const auto key=ba::argument(L"-custom-transition-gate=");
    wire::require(ba::unified() && host!=guest && ba::flag(L"-public-queue-experimental") &&
        ba::flag(L"-public-queue-smoke") && ba::flag(L"-practice-ai-smoke") &&
        ba::flag(L"-community-cosmetics-smoke") && !ba::flag(L"-dedicated-rematch-smoke") &&
        ba::argument(L"-local-profile=").rfind("cosmeticstest_",0)==0 && key.size()==32 &&
        std::all_of(key.begin(),key.end(),[](char c){return (c>='0' && c<='9') || (c>='a' && c<='f');}),
        "Custom transitions require an owned gated full-loadout diagnostic");
    return true;
}
static bool allowCustom(){return enabled() && isCustom() && armed && prepared && startReleased && !customReturned;}
static bool allowPractice(){return enabled() && phase==1 && armed;}
static bool allowPublic(){return enabled() && phase==3 && armed;}
static bool gate(const std::wstring& suffix) {
    wchar_t module[32768];const DWORD length=GetModuleFileNameW(ba::module,module,32768);
    wire::require(length && length<32768,"Custom transition installation path unavailable");
    wchar_t* slash=wcsrchr(module,L'\\');wire::require(slash!=nullptr,"Custom transition installation path invalid");*(slash+1)=0;
    const auto key=ba::argument(L"-custom-transition-gate=");
    const std::wstring path=std::wstring(module)+L"investigation\\runtime\\custom-transition-"+
        std::wstring(key.begin(),key.end())+suffix+L".ready";
    const DWORD attributes=GetFileAttributesW(path.c_str());
    if(attributes==INVALID_FILE_ATTRIBUTES) {
        const DWORD error=GetLastError();wire::require(error==ERROR_FILE_NOT_FOUND || error==ERROR_PATH_NOT_FOUND,
            "Custom transition gate unreadable");return false;
    }
    wire::require(!(attributes&(FILE_ATTRIBUTE_DIRECTORY|FILE_ATTRIBUTE_REPARSE_POINT)),"Custom transition gate must be an ordinary file");
    return true;
}
static void noParty(Obj front,Obj owner) {
    wire::require(native::authority.phase==wire::None && native::installedLobby.empty() && native::requests.empty() &&
        !ba::get<Obj>(front,"_party") && !ba::call(owner,"get_PredictedCustomGameLobby") &&
        !ba::get<Obj>(owner,"_pendingCreateLobbyRequest") && !ba::get<Obj>(owner,"_pendingLobbyUpdateRequest") &&
        ba_local::count(ba::get<Obj>(owner,"_pendingLobbyPlayerInvites"))==0 &&
        ba::get<int>(front,"_pendingInviteResponseRequests")==0 && ba_community_invites::operations.empty() &&
        !ba_community_invites::completing && !ba_community_popup::owned && custom::operations.empty() &&
        custom::activeMatch.empty() && !custom::awaitingReturn && !ba_public::active() && !ba_dedicated_session::joined &&
        ba_client::nativeIdle(front),"Custom transition retained native party/prediction/request/world");
}
static void advance() {
    ++phase;armed=prepared=startReleased=customReturned=leaveIssued=connectIssued=false;gateBegan=0;
}
static void update(Obj front) {
    if(!enabled() || phase>=5 || ba_client::worldOwner!=ba_client::Owner::None || ba_practice::active() ||
        !ba_dedicated_session::inMenu() || !ba_client::nativeIdle(front))return;
    const bool host=ba::flag(L"-community-match-host-smoke");
    const char* role=host?"host":"guest";
    Root owner(native::manager(front));wire::require(owner.get()!=nullptr,"Custom transition manager missing");
    if(!armed) {
        noParty(front,owner.get());
        if(!gateBegan){gateBegan=GetTickCount64();ba::log("CUSTOM TRANSITION waiting for gate: stage=%u role=%s nativeIdle=1 party=0 BA_RESURRECTION_CUSTOM_TRANSITION_V1",phase+1,role);}
        wire::require(GetTickCount64()-gateBegan<180000,"Custom transition gate timed out");
        if(!gate(L"-stage-"+std::to_wstring(phase+1)))return;
        armed=true;ba::log("CUSTOM TRANSITION stage released: stage=%u role=%s",phase+1,role);
    }
    if(isCustom()) {
        if(!prepared) {
            if(!connectIssued){connectIssued=true;ba_client::requestConnect();}
            if(!ba_community::online || !native::installed || !ba_client::deckReady())return;
            if(!host && !edited) {
                edited=true;ba_dedicated_deck::rematchSmokeSelection(front);
                ba::log("CUSTOM TRANSITION initial guest deck edited through native selection");return;
            }
            noParty(front,owner.get());
            custom::probeStage=0;custom::probeMatches=0;custom::probeAt=0;custom::probeButton.reset();
            prepared=true;
            ba::log("CUSTOM TRANSITION original invitation flow armed: stage=%u role=%s",phase+1,role);
        }
        // Both native profiles/deck ACKs must be ready before the host may open
        // the picker. Do not rely on the older probe's scheduling delay to keep
        // an incoming popup from racing the guest's preparation checks.
        if(!startReleased) {
            if(!gate(L"-custom-start-"+std::to_wstring(phase+1)))return;
            startReleased=true;
            ba::log("CUSTOM TRANSITION invitation gate released: stage=%u role=%s",phase+1,role);
        }
        if(custom::probeStage!=10)return;
        if(!customReturned) {
            wire::require(native::authority.phase==wire::Open && native::authority.members.size()==2 &&
                custom::returnAccepted && custom::operations.empty() && !custom::awaitingReturn,
                "Custom transition result did not restore its two-human lobby");
            customReturned=true;
            ba::log("CUSTOM TRANSITION Custom returned: stage=%u role=%s lobby=%s party=2 nativeIdle=1",phase+1,role,native::authority.id.c_str());
        }
        if(!leaveIssued) {
            if(!gate(L"-leave-"+std::to_wstring(phase+1)+(host?L"-host":L"-guest")))return;
            wire::require(native::authority.phase==wire::Open && !native::installedLobby.empty() && native::requests.empty(),
                "Custom transition Leave requires its original open lobby");
            leaveIssued=true;
            ba::native<void(*)(Obj,bool,Obj)>(0x3cab820)(owner.get(),false,nullptr);
            ba::log("CUSTOM TRANSITION original Leave dispatched: stage=%u role=%s",phase+1,role);return;
        }
        if(native::authority.phase!=wire::None || !native::installedLobby.empty() || !native::requests.empty())return;
        noParty(front,owner.get());
        ba::log("CUSTOM TRANSITION departed: stage=%u role=%s party=0 prediction=0 pending=0 nativeIdle=1",phase+1,role);
        advance();
        if(phase==5)ba::log("CUSTOM TRANSITION complete: stages=C,local4,C,public1,C role=%s worlds=5 BA_RESURRECTION_CUSTOM_TRANSITION_V1",role);
    } else if(phase==1 && ba_practice::completed==1) {
        noParty(front,owner.get());
        ba::log("CUSTOM TRANSITION local returned: stage=2 role=%s practiceCompleted=1 nativeIdle=1",role);advance();
    } else if(phase==3 && ba_public::completed==1 && !ba_public::active()) {
        noParty(front,owner.get());
        ba::log("CUSTOM TRANSITION public returned: stage=4 role=%s publicCompleted=1 nativeIdle=1",role);advance();
    }
}
}
