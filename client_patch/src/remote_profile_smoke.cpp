#pragma once
// Explicit owned diagnostic only. Read original models/getters; never bind or
// refresh a UI model to manufacture a passing observation.
namespace ba_remote_profiles {
using ba::Obj;using ba_local::Root;
using ba_tables::require;
struct Expected {
    uint32_t army=0,profile=0,portrait=0,banner=0;
    uint64_t player=0;
    std::string name;
    std::array<uint32_t,8> units{};
};
struct State {
    std::unique_ptr<Root> front;
    std::string match;
    int mode=0;
    std::vector<Expected> players;
    bool loadingSeen=false,nativeRosterSeen=false;
    uint32_t resultMask=0;
    ULONGLONG resultStarted=0,resultPollAt=0,loadingPollAt=0;
};
static auto& state=*new State();
static bool enabled() {
    if(!ba::flag(L"-remote-profile-smoke"))return false;
    require(ba::unified() && ba::flag(L"-public-queue-experimental") && ba::flag(L"-public-queue-smoke") &&
        ba::flag(L"-community-cosmetics-smoke") && ba::argument(L"-local-profile=").rfind("cosmeticstest_",0)==0,
        "remote profile proof requires an owned full-loadout diagnostic");
    return true;
}
static std::string unitsJson(const std::array<uint32_t,8>& units) {
    std::string out="[";
    for(size_t i=0;i<units.size();++i){if(i)out+=",";out+=std::to_string(units[i]);}
    return out+"]";
}
static void freeze(Obj front,Obj config,const std::string& match,int mode) {
    if(!enabled())return;
    require(!state.front && !match.empty() && (mode==1 || mode==2 || mode==5),"remote profile diagnostic already owns a match");
    state=State{};state.front=std::make_unique<Root>(front);state.match=match;state.mode=mode;
    Root armies(ba::get<Obj>(config,"armies_"));const auto count=ba_local::count(armies.get());
    require(count==(mode==1?2:4),"remote profile roster count changed");
    for(int seat=0;seat<count;++seat) {
        Root army(ba_bootstrap::item(armies.get(),seat)),players(ba::get<Obj>(army.get(),"players_"));
        require(ba_local::count(players.get())==1,"remote profile army player count changed");
        Root identity(ba_bootstrap::item(players.get(),0));
        Root named(ba::get<Obj>(identity.get(),"playerHandleWithName_")),handle(ba::get<Obj>(named.get(),"playerHandle_"));
        Expected value;value.army=ba::get<uint32_t>(army.get(),"armyId_");
        value.profile=ba::get<uint32_t>(identity.get(),"aiProfileId_");value.player=ba::get<uint64_t>(handle.get(),"steamId_");
        value.name=ba_catalog::utf8(ba::get<Obj>(named.get(),"playerName_"));
        value.portrait=ba::get<uint32_t>(army.get(),"portraitId_");value.banner=ba::get<uint32_t>(army.get(),"bannerId_");
        require(value.army==static_cast<uint32_t>(seat) && value.player==static_cast<uint64_t>(seat+1) &&
            !value.name.empty() && value.portrait && value.banner,"remote profile frozen identity is incomplete");
        Root deck(ba::get<Obj>(army.get(),"deck_")),units(ba::get<Obj>(deck.get(),"units_"));
        require(ba_local::count(units.get())==8,"remote profile frozen deck count changed");
        for(int i=0;i<8;++i)value.units[i]=ba_lan_bootstrap::uintAt(units.get(),i);
        ba::log("REMOTE PROFILE expected: {\"match\":%s,\"mode\":%d,\"army\":%u,\"player\":%llu,\"profile\":%u,\"name\":%s,\"portrait\":%u,\"banner\":%u,\"units\":%s}",
            ba_catalog::quote(match).c_str(),mode,value.army,static_cast<unsigned long long>(value.player),value.profile,
            ba_catalog::quote(value.name).c_str(),value.portrait,value.banner,unitsJson(value.units).c_str());
        state.players.push_back(std::move(value));
    }
    ba::log("REMOTE PROFILE proof armed: match=%s players=%zu BA_RESURRECTION_REMOTE_PROFILE_V1",match.c_str(),state.players.size());
}
static uint32_t child(Obj vm,uint32_t expected) {
    if(!ba_practice::visibleProfile(vm))return 0;
    Root set(ba::call(vm,"get_IsModelSet"));if(!ba_tables::boolean(set.get()))return 0;
    Root model(ba::call(vm,"get_Model"));
    require(model.get() && ba::get<uint32_t>(model.get(),"Item")==expected,"remote profile live cosmetic child differs from frozen identity");
    return 1;
}
static bool loadingActive(bool record) {
    Root type(ba_tables::reflectedType("UILoadingScreen","Uncapped.UI"));void* args[]={type.get()};
    Root views(ba::invoke(ba::find_class("UnityEngine","Resources"),nullptr,"FindObjectsOfTypeAll",1,args));
    const auto count=ba_catalog::length(views.get());require(count<=128,"remote loading screen capacity exceeded");
    for(size_t i=0;i<count;++i) {
        Obj vm=ba_catalog::arrayAt(views.get(),i);
        if(!ba_practice::visibleProfile(vm) || ba::get<Obj>(vm,"_frontServer")!=state.front->get())continue;
        Root set(ba::call(vm,"get_IsModelSet"));if(!ba_tables::boolean(set.get()))continue;
        Root model(ba::call(vm,"get_Model"));if(!model.get())continue;
        require(ba::klass(model.get())==ba::find_class("Uncapped.UI","LoadingScreenModel"),"remote loading model class changed");
        // LoadingScreenModel.Signal is an INLINE ShowLoadingScreenSignal value
        // whose only field is a four-byte UILoadingScreen.GameMode enum. Copy the
        // field bytes, as original Refresh does; never reinterpret them as Obj.
        // Public1/2/5 map to the same values; the original view can present an
        // all-AI-opponent1v1 as internal Game_1vAI4 without changing match mode.
        const auto signalMode=ba::get<int>(model.get(),"Signal");
        if(signalMode!=state.mode)continue;
        const auto viewMode=ba::get<int>(vm,"_gameMode");
        require(viewMode==state.mode || (state.mode==1 && viewMode==4),"original loading presentation has unexpected mode");
        if(record)ba::log("REMOTE PROFILE loading: {\"match\":%s,\"mode\":%d,\"signal_mode\":%d,\"view_mode\":%d,\"front_owned\":true,\"live\":true,\"original_screen\":true,\"profile_roster_present\":false}",
            ba_catalog::quote(state.match).c_str(),state.mode,signalMode,viewMode);
        return true;
    }
    return false;
}
static void observeNativeRoster(Obj front) {
    if(state.nativeRosterSeen || !ba_lan::worldReady || ba_lan::nextFrame<2 || !ba_dedicated::loadingInGame())return;
    Obj server=ba::read<Obj>(front,0xd8);
    Root data(ba::get<Obj>(ba::owner,"<MatchDataManager>k__BackingField")),simulation(ba::read<Obj>(server,0x140));
    if(!data.get() || ba::get<Obj>(data.get(),"_simulation")!=simulation.get())return;
    Root info(ba::get<Obj>(data.get(),"_matchInfo")),entries(ba::get<Obj>(data.get(),"_players"));
    if(!info.get() || ba::get<uint32_t>(info.get(),"PlayerCount")!=static_cast<uint32_t>(state.players.size()))return;
    require(state.loadingSeen && ba::get<int>(info.get(),"GameMode")==state.mode &&
        !ba::get<bool>(info.get(),"MatchCompleted") && ba::get<Obj>(data.get(),"_serviceManager")==
        ba::get<Obj>(ba::owner,"<ServiceManager>k__BackingField"),"original native roster has stale match ownership");
    const auto capacity=ba_catalog::length(entries.get());require(capacity>=state.players.size() && capacity<=4,"original native roster capacity changed");
    uint32_t seen=0;const bool stillLoading=loadingActive(false);
    for(size_t i=0;i<state.players.size();++i) {
        Root entry(ba_catalog::arrayAt(entries.get(),i)),player(ba::get<Obj>(entry.get(),"Player"));
        if(!player.get())return;
        const auto army=ba::get<uint32_t>(player.get(),"ArmyID");
        require(army<state.players.size() && !(seen&(1u<<army)),"original native roster army duplicate/outside match");seen|=1u<<army;
        const auto& value=state.players[army];
        // SimPlayer.Handle is an inline value type, not an object reference.
        // PlayerName is another field INSIDE inline Handle, not a SimPlayer field.
        Root playerName(ba::read<Obj>(player.get(),0x30));
        require(ba::read<uint64_t>(player.get(),0x10)==value.player && ba::read<uint32_t>(player.get(),0x1c)==value.profile &&
            ba::get<uint32_t>(player.get(),"AllianceID")==army%2 && playerName.get() && ba_catalog::utf8(playerName.get())==value.name &&
            ba::get<uint32_t>(player.get(),"Portrait")==value.portrait && ba::get<uint32_t>(player.get(),"Banner")==value.banner,
            "original native SimPlayer identity differs from frozen remote match");
        Root deck(ba::get<Obj>(player.get(),"Deck")),units(ba::get<Obj>(deck.get(),"UnitIDs"));
        require(ba_catalog::length(units.get())==8,"original native SimDeck unit count changed");
        for(size_t j=0;j<8;++j)require(ba::read<uint32_t>(units.get(),0x20+4*j)==value.units[j],"original native SimDeck differs from frozen remote match");
    }
    for(const auto& value:state.players)ba::log("REMOTE PROFILE native: {\"match\":%s,\"mode\":%d,\"army\":%u,\"player\":%llu,\"profile\":%u,\"name\":%s,\"portrait\":%u,\"banner\":%u,\"units\":%s,\"loading_active\":%s,\"simulation_owned\":true,\"match_data_owned\":true}",
        ba_catalog::quote(state.match).c_str(),state.mode,value.army,static_cast<unsigned long long>(value.player),value.profile,
        ba_catalog::quote(value.name).c_str(),value.portrait,value.banner,unitsJson(value.units).c_str(),stillLoading?"true":"false");
    state.nativeRosterSeen=true;
}
static void observeResults() {
    Root controller(ba::get<Obj>(ba::owner,"<UIPostGameController>k__BackingField"));if(!controller.get())return;
    Root resultState(ba::get<Obj>(controller.get(),"_matchResultState")),fsm(ba::get<Obj>(controller.get(),"_fsm"));
    if(!resultState.get() || !fsm.get() || ba::get<Obj>(fsm.get(),"_currentState")!=resultState.get())return;
    Root parent(ba::get<Obj>(resultState.get(),"_matchResultVM"));if(!ba_practice::visibleProfile(parent.get()))return;
    Root views(ba::get<Obj>(parent.get(),"_players"));const auto count=ba_catalog::length(views.get());
    require(count>=state.players.size() && count<=4,"remote result profile capacity exceeded");
    for(size_t i=0;i<count;++i) {
        Obj vm=ba_catalog::arrayAt(views.get(),i);if(!ba_practice::visibleProfile(vm))continue;
        Root set(ba::call(vm,"get_IsModelSet"));if(!ba_tables::boolean(set.get()))continue;
        if(ba::get<Obj>(vm,"_frontServer")!=state.front->get())continue;
        Root model(ba::call(vm,"get_Model"));if(!model.get())continue;
        const auto id=ba::get<uint64_t>(model.get(),"SteamId");
        const auto found=std::find_if(state.players.begin(),state.players.end(),[&](const Expected& value){return value.player==id;});
        if(found==state.players.end())continue;
        const auto& value=*found;const auto bit=1u<<value.army;if(state.resultMask&bit)continue;
        require(ba::get<int>(model.get(),"GameMode")==state.mode && ba::get<uint32_t>(model.get(),"AllianceId")==value.army%2,
            "remote result profile mode/alliance differs from frozen match");
        const auto name=ba_catalog::utf8(ba::get<Obj>(model.get(),"PlayerName"));
        const auto displayed=ba_catalog::utf8(ba::call(vm,"get_PlayerName"));
        const auto expected=value.name+(ba::get<bool>(model.get(),"IsAlias")?" (Alias)":"");
        Root getterAi(ba::call(vm,"get_IsAI"));const bool isAi=value.profile!=0;
        const bool namesMatch=name==value.name && displayed==expected && ba::get<bool>(model.get(),"IsAi")==isAi && ba_tables::boolean(getterAi.get())==isAi;
        if(!namesMatch)ba::log("REMOTE PROFILE name mismatch: army=%u expected=%s actual=%s displayed=%s expectedAi=%d modelAi=%d getterAi=%d",
            value.army,ba_catalog::quote(value.name).c_str(),ba_catalog::quote(name).c_str(),ba_catalog::quote(displayed).c_str(),
            isAi?1:0,ba::get<bool>(model.get(),"IsAi")?1:0,ba_tables::boolean(getterAi.get())?1:0);
        require(namesMatch,"remote original result name/AI getter mismatch");
        require(ba::get<uint32_t>(model.get(),"Portrait")==value.portrait && ba::get<uint32_t>(model.get(),"Banner")==value.banner,
            "remote result avatar differs from frozen match");
        Root deck(ba::get<Obj>(model.get(),"PlayerDeck")),units(ba::get<Obj>(deck.get(),"_units"));
        require(ba_catalog::length(units.get())==8,"remote result deck has wrong count");
        for(size_t j=0;j<8;++j)require(ba::read<uint32_t>(units.get(),0x20+4*j)==value.units[j],"remote result deck differs from frozen match");
        uint32_t portraits=0,banners=0;
        for(const char* field:{"_portraits","_banners"}) {
            Root children(ba::get<Obj>(vm,field));const auto n=ba_catalog::length(children.get());
            require(n<=32,"remote result cosmetic child capacity exceeded");
            for(size_t j=0;j<n;++j)if(field[1]=='p')portraits+=child(ba_catalog::arrayAt(children.get(),j),value.portrait);
                else banners+=child(ba_catalog::arrayAt(children.get(),j),value.banner);
        }
        if(!portraits || !banners)continue;
        state.resultMask|=bit;
        ba::log("REMOTE PROFILE result: {\"match\":%s,\"mode\":%d,\"army\":%u,\"player\":%llu,\"name\":%s,\"displayed\":%s,\"is_ai\":%s,\"portrait\":%u,\"banner\":%u,\"units\":%s,\"portrait_children\":%u,\"banner_children\":%u,\"front_owned\":true,\"live\":true}",
            ba_catalog::quote(state.match).c_str(),state.mode,value.army,static_cast<unsigned long long>(id),
            ba_catalog::quote(name).c_str(),ba_catalog::quote(displayed).c_str(),isAi?"true":"false",
            value.portrait,value.banner,unitsJson(value.units).c_str(),portraits,banners);
    }
}
static bool resultReady(const std::string& match) {
    if(!enabled())return true;
    return state.front && state.match==match && state.loadingSeen && state.nativeRosterSeen && state.resultMask==((1u<<state.players.size())-1);
}
static void update(Obj front) {
    if(!enabled() || !state.front)return;
    // Continue legitimately clears the transport/world before its RETURN ACK.
    // Finished observations must not touch those retired native owners again.
    if(resultReady(state.match))return;
    require(state.front->get()==front && state.match==ba_lan::dedicatedMatchId,"remote profile observer changed native owner");
    const auto now=GetTickCount64();
    if(!state.loadingSeen && now>=state.loadingPollAt){state.loadingPollAt=now+100;state.loadingSeen=loadingActive(true);}
    observeNativeRoster(front);
    if(!ba_dedicated_results::delivered || resultReady(state.match))return;
    require(state.nativeRosterSeen,"remote result arrived before original native roster proof");
    if(!state.resultStarted)state.resultStarted=now;
    require(now-state.resultStarted<10000,"remote original result profile observation deadline");
    if(now<state.resultPollAt)return;state.resultPollAt=now+100;
    observeResults();
    if(resultReady(state.match))ba::log("REMOTE PROFILE results complete: match=%s players=%zu originalGetters=1 liveChildren=1",state.match.c_str(),state.players.size());
}
static void retire(const std::string& match) {
    if(!enabled() || !state.front)return;
    require(state.match==match,"remote profile retirement match changed");
    state=State{};
    ba::log("REMOTE PROFILE observer retired: match=%s rootedOwners=0",match.c_str());
}
}
