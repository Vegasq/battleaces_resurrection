#pragma once
// Application-lifetime local profile/deck ownership. It has no network dependency.
namespace ba_local_menu {
using ba::Obj;using ba_local::Root;
static auto& frontRoot=*new std::unique_ptr<Root>();
static auto& identityRoot=*new std::unique_ptr<Root>();
static bool initialized=false,baseInitialized=false,failed=false;
static void require(bool condition,const char* message) {if(!condition)throw std::runtime_error(message);}
static bool ready(Obj front) {return initialized && !failed && frontRoot && frontRoot->get()==front;}
static void restoreIdentity(Obj front) {
    require(frontRoot && frontRoot->get()==front && identityRoot,"local menu identity ownership");
    require(ba_dedicated_session::worldIdle(ba::read<Obj>(front,0xd8)) &&
        !ba_bootstrap::creating && !ba_bootstrap::awaitingWorld,"local identity requires an idle native world");
    Obj named=ba::get<Obj>(identityRoot->get(),"playerHandleWithName_");
    Obj name=ba::get<Obj>(named,"playerName_");
    ba::set<Obj>(front,"_playerGameHandle",identityRoot->get());
    ba::set<Obj>(front,"_currentPlayerName",name);
    Obj account=ba::get<Obj>(front,"_accountService");
    Obj profile=ba::get<Obj>(account,"<ProfileCache>k__BackingField");
    require(profile!=nullptr,"local menu profile missing");
    ba::set<uint64_t>(profile,"steamId_",1);ba::set<bool>(profile,"isAlias_",true);
    ba::set<Obj>(profile,"name_",name);
}
static bool ensure(Obj front) {
    if(failed)return false;
    try {
        Obj services=ba::get<Obj>(ba::owner,"<ServiceManager>k__BackingField");
        require(services && ba::read<Obj>(services,0x10)==front &&
            ba::read<Obj>(services,0x18)==ba::read<Obj>(front,0xd8),"local menu service ownership");
        if(!ba_dedicated_session::unityThread)ba_dedicated_session::unityThread=GetCurrentThreadId();
        require(ba_dedicated_session::unityThread==GetCurrentThreadId(),"local menu called off Unity thread");
        ba_dedicated_session::observedFront=front;
        if(initialized) {require(ready(front),"local menu front changed");return true;}
        if(!ba_dedicated_session::inMenu() || !ba_dedicated_session::worldIdle(ba::read<Obj>(front,0xd8)))return false;
        if(!baseInitialized) {
        frontRoot=std::make_unique<Root>(front);
        identityRoot=std::make_unique<Root>(ba_lan_bootstrap::identityLan(front,0));
        Root name(ba::str(ba::argument(L"-player-name=","Offline Player").c_str()));
        Obj named=ba::get<Obj>(identityRoot->get(),"playerHandleWithName_");
        ba::set<Obj>(named,"playerName_",name.get());ba::set<Obj>(named,"filteredName_",name.get());
        Obj account=ba::get<Obj>(front,"_accountService");ba::local_profile(account);
        Obj selector=ba::get<Obj>(front,"_deckSelector"),storage=ba::read<Obj>(ba::owner,0x110);
        require(selector && storage && selector==ba::read<Obj>(ba::owner,0x108) &&
            selector==ba::get<Obj>(account,"_deckSelector") && storage==ba::read<Obj>(selector,0x10) &&
            storage==ba::get<Obj>(account,"_localDeckStorage"),"local menu native deck storage ownership");
        restoreIdentity(front);
        ba_dedicated_deck::initializeLocal(front);ba_practice_settings::selection();
        baseInitialized=true;
        }
        require(frontRoot && frontRoot->get()==front,"local menu initialization owner changed");
        if(!ba_cosmetics::prepare(front))return false;
        // Search can begin before optional presence. One application clock keeps
        // its DateTime epoch stable across authentication and reconnection.
        ba_community_invites::anchorClock(front);initialized=true;
        ba::log("Local menu ready: native local deck storage; configured name; transportIndependent=1 BA_RESURRECTION_LOCAL_MENU_V1");
        return true;
    } catch(const std::exception& error) {
        failed=true;ba::log("Local menu initialization failed: %s",error.what());return false;
    }
}
}
