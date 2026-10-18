#pragma once
// Include after dedicated_deck.cpp and before local_bootstrap.cpp.
// S36, on Unity main thread: ba_dedicated_results::receive(resultJson).
// After ba_lan::tick(server), including while running=false:
//     ba_dedicated_results::update(server).
// No patches or exports. Deliver the existing end-response event so the native
// victory/defeat popup can finish its normal coroutine and enter post-game UI.
namespace ba_dedicated_results {
using ba::Obj;using ba_local::Root;
static bool pending=false,delivered=false,updating=false;
static int gameOverFrame=-1;
static uint32_t winningAlliance=31,concededMask=0;
static uint64_t checksum=0;
static ULONGLONG receivedAt=0,lastWaitLog=0;
static std::string matchId;
static Obj require(Obj obj,const char* text){if(!obj)throw std::runtime_error(text);return obj;}
static std::string tokenText(Obj json,const char* path) {
    Root key(ba::str(path));void* args[]={key.get()};Root value(ba::call(json,"SelectToken",1,args));
    Root text(ba::call(require(value.get(),"dedicated result field missing"),"ToString"));
    return ba_catalog::utf8(text.get());
}
static uint64_t number(Obj json,const char* path) {
    std::string text=tokenText(json,path);
    if(text.empty() || text.size()>20)throw std::runtime_error("dedicated result integer invalid");
    for(char c:text)if(c<'0'||c>'9')throw std::runtime_error("dedicated result integer invalid");
    size_t used=0;uint64_t value=std::stoull(text,&used);
    if(used!=text.size())throw std::runtime_error("dedicated result integer malformed");return value;
}
static void receive(const std::string& json) {
    if(!ba::dedicated())return;
    Root text(ba::str(json.c_str()));void* args[]={text.get()};
    Root object(ba::invoke(ba::find_class("Newtonsoft.Json.Linq","JObject"),nullptr,"Parse",1,args));
    const std::string incoming=tokenText(object.get(),"match");
    if(incoming!=ba_lan::dedicatedMatchId)throw std::runtime_error("dedicated result match identity mismatch");
    if(delivered || pending){if(incoming==matchId)return;throw std::runtime_error("dedicated duplicate result mismatch");}
    const std::string complete=tokenText(object.get(),"result.complete");
    if(complete!="True" && complete!="true")throw std::runtime_error("dedicated result is not a completed native match");
    const uint64_t frame=number(object.get(),"result.game_over_frame");
    const uint64_t winner=number(object.get(),"result.winning_alliance");
    const uint64_t mask=number(object.get(),"result.army_conceded_flag");
    if(frame>INT32_MAX || (winner>1 && winner!=31) || mask>UINT32_MAX)throw std::runtime_error("dedicated result outside two-player match bounds");
    gameOverFrame=static_cast<int>(frame);winningAlliance=static_cast<uint32_t>(winner);concededMask=static_cast<uint32_t>(mask);
    checksum=number(object.get(),"result.game_over_checksum");matchId=incoming;pending=true;receivedAt=GetTickCount64();
    ba::log("Dedicated authoritative result pending: frame=%d winner=%u conceded=%u checksum=%llu",gameOverFrame,winningAlliance,concededMask,static_cast<unsigned long long>(checksum));
}
static void endResponse(Obj server,Obj matchInfo,int localArmy=ba::lanSlot(),uint64_t localId=0,
                        uint32_t winner=winningAlliance,bool custom=true) {
    if(!localId)localId=static_cast<uint64_t>(localArmy+1);
    Obj front=ba::read<Obj>(server,0x118);
    Obj account=require(ba::get<Obj>(require(front,"dedicated results front missing"),"_accountService"),"dedicated results account missing");
    Obj profile=require(ba::get<Obj>(account,"<ProfileCache>k__BackingField"),"dedicated results profile missing");
    Obj sim=require(ba::read<Obj>(server,0x140),"dedicated result simulation missing");
    Obj localPlayer=require(ba::get<Obj>(sim,"_localPlayer"),"dedicated result local player missing");
    if(ba::get<uint32_t>(localPlayer,"ArmyID")!=static_cast<uint32_t>(localArmy))
        throw std::runtime_error("dedicated result local army identity mismatch");
    // The original result VM identifies the local record using ProfileCache's
    // SteamId and the static aliased-ID flag. These are the same private IDs
    // already assigned by identityLan, not authenticated Steam identities.
    ba::set<uint64_t>(profile,"steamId_",localId);
    ba::set<bool>(profile,"isAlias_",true);
    Obj presence=ba::find_class("Uncapped","SteamRichPresence");
    ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(presence);
    Obj aliasField=require(ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(presence,"IsAliased"),"dedicated result alias field missing");
    bool aliased=true;ba::api<void(*)(Obj,void*)>("il2cpp_field_static_set_value")(aliasField,&aliased);
    Obj matchData=require(ba::call(ba::owner,"get_MatchDataManager"),"dedicated match data missing");
    Obj localCache=require(ba::get<Obj>(matchData,"_localPlayerCache"),"dedicated result local cache missing");
    const bool localWon=ba::get<uint32_t>(localPlayer,"AllianceID")==winner;
    ba::set<bool>(localCache,"WonMatch",localWon);
    // This is a private dedicated match, not a ranked service match. Preserve
    // MODE_1V1 and native win/loss data while the shipped custom-game flag
    // suppresses progression, quests, battlepass and rating reward flows.
    if(custom)ba::set<bool>(matchInfo,"IsCustomGame",true);
    Root response(ba::make("CommonPb","EndOfGameResponse"));
    Root progression(ba::call(require(ba::get<Obj>(profile,"progression_"),"dedicated results progression missing"),"Clone"));
    ba::set<Obj>(response.get(),"progression_",progression.get());
    ba::set<uint64_t>(response.get(),"featureFlags_",ba::get<uint64_t>(ba::get<Obj>(profile,"accountData_"),"featureFlags_"));
    ba::set<int32_t>(response.get(),"gameMode_",ba::get<int32_t>(matchInfo,"GameMode"));
    ba::set<uint32_t>(response.get(),"winningAllianceId_",winner);
    // Keep newRewards/playerRatings empty: no invented XP, currency or ratings.
    // AccountService's original listener also touches login-only survey and
    // progression services. Temporarily omit that listener for this local result
    // while preserving the original MatchData/UI listeners and their ordering.
    Root original(require(ba::get<Obj>(server,"OnEndOfGameResponse"),"dedicated result subscribers missing"));
    Root listeners(ba::call(original.get(),"GetInvocationList"));
    const size_t count=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(listeners.get());
    Obj delegateClass=ba::find_class("System","Delegate");std::vector<Obj> excluded;
    for(size_t i=0;i<count;++i) {
        Obj entry=ba::read<Obj>(listeners.get(),0x20+i*sizeof(Obj));Root target(ba::call(entry,"get_Target"));
        if(target.get()!=account)continue;
        void* removeArgs[]={ba::get<Obj>(server,"OnEndOfGameResponse"),entry};
        Root filtered(ba::invoke(delegateClass,nullptr,"Remove",2,removeArgs));
        ba::set<Obj>(server,"OnEndOfGameResponse",filtered.get());excluded.push_back(entry);
    }
    auto restore=[&]() {
        // Use the current list, not the original snapshot: the UI completion
        // handler normally unsubscribes itself during response delivery.
        for(Obj entry:excluded) {
            void* combineArgs[]={ba::get<Obj>(server,"OnEndOfGameResponse"),entry};
            Root combined(ba::invoke(delegateClass,nullptr,"Combine",2,combineArgs));
            ba::set<Obj>(server,"OnEndOfGameResponse",combined.get());
        }
    };
    try {int32_t error=0;void* args[]={response.get(),&error};ba::call(server,"ProcessEndOfGameResponse",2,args);}
    catch(...){restore();throw;}
    restore();
    ba::log("%s native EndOfGameResponse delivered; winner=%u native-complete=%d listeners=%llu account-listeners-preserved=%llu rewards=0 ratings=0 progression unchanged custom=%d local-id=%llu aliased=1 local-won=%d",
        custom?"Dedicated":"Practice",winner,ba::get<bool>(matchInfo,"MatchCompleted")?1:0,static_cast<unsigned long long>(count),static_cast<unsigned long long>(excluded.size()),custom?1:0,static_cast<unsigned long long>(localId),localWon?1:0);
}
static void update(Obj server) {
    if(!ba::dedicated() || !pending || delivered || updating || !server)return;
    struct Guard{Guard(){updating=true;}~Guard(){updating=false;}}guard;
    Obj sim=require(ba::read<Obj>(server,0x140),"dedicated result simulation missing");
    Obj matchData=require(ba::call(ba::owner,"get_MatchDataManager"),"dedicated match data missing");
    Obj matchInfo=require(ba::get<Obj>(matchData,"_matchInfo"),"dedicated match info missing");
    const bool localComplete=ba::get<bool>(matchInfo,"MatchCompleted");
    const int presented=ba::get<int32_t>(sim,"_currentPresentedFrame");
    if(!ba_lan::frames.empty() || ba_lan::running || presented<gameOverFrame || !localComplete) {
        ULONGLONG now=GetTickCount64();if(now-receivedAt>5000 && now-lastWaitLog>5000) {
            lastWaitLog=now;ba::log("Dedicated results waiting for native completion: presented=%d expected=%d completed=%d queued=%llu running=%d",presented,gameOverFrame,localComplete?1:0,static_cast<unsigned long long>(ba_lan::frames.size()),ba_lan::running?1:0);
        }return;
    }
    if(ba::get<uint32_t>(matchInfo,"WinningAllianceId")!=winningAlliance)throw std::runtime_error("dedicated authoritative result disagrees with local presented winner");
    endResponse(server,matchInfo,ba::lanSlot(),0,winningAlliance,!ba_public::active());delivered=true;pending=false;
}
}
