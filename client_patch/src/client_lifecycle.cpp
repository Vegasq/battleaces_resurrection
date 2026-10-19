#pragma once
#include "loadout_publication.hpp"
// One application owns its local menu; optional presence never owns a local world.
namespace ba_client {
using ba::Obj;using ba_local::Root;
namespace wire=ba_community_wire;
enum class Owner {None,Practice,Remote};
static Owner worldOwner=Owner::None;
static uint64_t generation=0,worldLease=0;
static std::string worldMatch;
static bool connectRequested=true,controlFailed=false,failed=false;
static ba_loadout_publication::State publication;
static auto& selectedDeckAccepted=publication.accepted;
static auto& selectedDeckPending=publication.pending;
static ba_community_wire::Loadout selectedSubmitted;
static void controlReset(){publication.reset();selectedSubmitted={};}
static void queueLoadoutAccepted(const wire::Loadout& selection) {
    if(!ba::unified())return;
    wire::require(!selectedDeckPending,"queue accepted before prior loadout publication completed");
    selectedSubmitted=selection;selectedDeckAccepted=true;
}
static unsigned smokeStage=0;
static void require(bool condition,const char* message) {if(!condition)throw std::runtime_error(message);}
static bool remoteWorld() {return ba::unified() && worldOwner==Owner::Remote;}
static bool nativeIdle(Obj front) {
    return ba_dedicated_session::worldIdle(ba::read<Obj>(front,0xd8)) &&
        !ba_bootstrap::creating && !ba_bootstrap::awaitingWorld;
}
static uint64_t acquire(Obj front,Owner owner,const std::string& match) {
    require(ba_local_menu::ready(front) && worldOwner==Owner::None && nativeIdle(front) &&
        !ba_dedicated_session::joined && generation!=UINT64_MAX,"client world is already owned or still loading");
    worldOwner=owner;worldLease=++generation;worldMatch=match;
    ba::log("Client world acquired: generation=%llu owner=%s match=%s",
        static_cast<unsigned long long>(worldLease),owner==Owner::Practice?"local-practice":"remote",match.c_str());
    return worldLease;
}
static void retireControl(Obj front,const char* reason) {
    require(worldOwner==Owner::None && nativeIdle(front) && ba_dedicated_session::inMenu(),
        "control retirement requires an idle menu without a world owner");
    // This existing boundary finishes retained native requests before clearing
    // their identity. Unified resets retain the application-owned deck cache.
    ba_dedicated_session::resetAtMenu(front,ba::read<Obj>(front,0xd8),false);
    ba_dedicated::initialized=false;
    publication.reset();selectedSubmitted={};controlFailed=false;
    ba_local_menu::restoreIdentity(front);
    ba::log("Client control retired: reason=%s localMenu=1 nativeDeckRetained=1",reason);
}
static void prepareLocal(Obj front) {
    require(ba::unified() && worldOwner==Owner::None && !ba_public::active() && ba_local_menu::ready(front),
        "local match application ownership");
    connectRequested=false;
    retireControl(front,"local practice requested");
}
static uint64_t acquireLocal(Obj front) {return acquire(front,Owner::Practice,"");}
static void releaseLocal(Obj front,uint64_t lease) {
    require(worldOwner==Owner::Practice && lease && lease==worldLease && nativeIdle(front),"stale local world release");
    ba::log("Client world released: generation=%llu owner=local-practice nativeIdle=1",static_cast<unsigned long long>(lease));
    worldOwner=Owner::None;worldLease=0;worldMatch.clear();ba_local_menu::restoreIdentity(front);
}
static void acquireRemote(Obj front,const std::string& match) {
    require(!match.empty() && selectedDeckAccepted && ba_community_native::installed,"remote match before accepted presence/deck");
    acquire(front,Owner::Remote,match);
}
static void releaseRemote(Obj front,const std::string& match) {
    require(worldOwner==Owner::Remote && !match.empty() && match==worldMatch && nativeIdle(front),"stale remote world release");
    ba::log("Client world released: generation=%llu owner=remote nativeIdle=1",static_cast<unsigned long long>(worldLease));
    worldOwner=Owner::None;worldLease=0;worldMatch.clear();
}
static bool optionalFailure(const char* where,const std::exception& error) {
    if(!ba::unified() || worldOwner==Owner::Remote)return false;
    ba_public::connectionFailed(error.what());
    if(!controlFailed)ba::log("Client optional connection unavailable in %s: %s; localWorldUnaffected=1",where,error.what());
    connectRequested=false;controlFailed=true;selectedDeckAccepted=false;
    ba_lan::closeSocket();return true;
}
static void requestConnect() {
    if(!ba::unified())return;
    require(worldOwner==Owner::None,"finish the active match before connecting");
    connectRequested=true;
}
static bool deckReady() {return !ba::unified() || selectedDeckAccepted;}
static bool deckPending() {return ba::unified() && selectedDeckPending;}
static void deckSubmitted(uint32_t id,const wire::Loadout& selected) {
    if(!ba::unified())return;
    publication.submit(id,selected.full?wire::SetLoadout:wire::SetDeck);selectedSubmitted=selected;
}
static bool acknowledge(const wire::Ack& ack) {
    if(!ba::unified() || (ack.kind!=wire::SetDeck && ack.kind!=wire::SetLoadout))return false;
    const bool owned=publication.acknowledge(ack.request,ack.kind,ack.success);
    if(owned && ack.request==publication.latest) {
        ba::log("Client local deck acknowledgement: request=%u accepted=%d",ack.request,ack.success?1:0);
        if(!ack.success)ba_public::connectionFailed(ack.reason.c_str());
    }
    return owned;
}
static void synchronizeLoadout(Obj front) {
    static ULONGLONG next=0;const auto now=GetTickCount64();
    if(now<next || worldOwner!=Owner::None || ba_public::active() || !ba_community::online || !ba_dedicated::initialized ||
       !ba_dedicated_session::inMenu() || !nativeIdle(front) || selectedDeckPending ||
       (ba_community_native::authority.phase!=wire::None && ba_community_native::authority.phase!=wire::Open) ||
       !ba_cosmetics::readyForLoadout(front))return;
    next=now+500;Root deck(ba_dedicated_deck::selectedProto(front));
    const auto selection=ba_cosmetics::wireLoadout(deck.get(),ba_cosmetics::currentSelection(front));
    if(selection!=selectedSubmitted)ba_dedicated::submitDeck(deck.get());
}
static bool allowPracticeSmoke() {
    return !ba::flag(L"-unified-smoke") || ba_practice::completed==0 || smokeStage>=2;
}
static bool allowCustomSmoke() {
    return !ba::flag(L"-unified-smoke") || (smokeStage==1 && selectedDeckAccepted);
}
static void smoke() {
    if(!ba::flag(L"-unified-smoke") || worldOwner!=Owner::None)return;
    if(smokeStage==0 && ba_practice::completed==1) {
        smokeStage=1;requestConnect();
        ba::log("UNIFIED SMOKE first local practice returned; requesting authenticated Custom presence");
    } else if(smokeStage==1 && ba_community_native::smokeStage==8 &&
        ba_community_native::requests.empty() && ba_community_native::authority.phase==wire::None) {
        smokeStage=2;ba::log("UNIFIED SMOKE native Custom Create/Leave complete; second local practice allowed");
    } else if(smokeStage==2 && ba_practice::completed==2) {
        smokeStage=3;ba::log("UNIFIED SMOKE local-practice -> authenticated-Custom -> local-practice complete; same PID and native deck storage");
    }
}
static void update(Obj front) {
    if(!ba::unified() || failed || !ba_local_menu::ensure(front))return;
    try {
        static bool logged=false;
        if(!logged) {
            require(!ba::offlinePractice() && ba_lan::secureMode() && ba_lan::secureVersion()==2,
                "unified client requires private bridge ABI2 without an offline-only launch flag");
            logged=true;ba::log("Unified client ready: local menu independent of server BA_RESURRECTION_UNIFIED_CLIENT_V1");
        }
        if(worldOwner==Owner::Practice || ba_practice::active()) {ba_practice::frontUpdate(front);return;}
        if(controlFailed && worldOwner==Owner::None) {
            if(!nativeIdle(front) || !ba_dedicated_session::inMenu())return;
            retireControl(front,"optional connection failed");
        }
        smoke();
        if(worldOwner==Owner::Remote || connectRequested)ba_dedicated_session::update(front);
        ba_cosmetics::remoteProof(front);
        synchronizeLoadout(front);
        ba_public::update(front);
        if(worldOwner==Owner::None && !ba_practice::active()) {
            ba_practice::releaseOfflineIdleDisconnect(front);
            ba_practice_settings_ui::update(front);
            if(!ba::flag(L"-practice-settings-smoke") || ba_practice_settings_ui::smokeComplete())ba_practice::smoke(front);
            ba_public::smoke(front);
        }
    } catch(const std::exception& error) {
        failed=true;ba::log("Client lifecycle invariant failed: %s; retaining native owners",error.what());
    }
}
}
