#pragma once
// Include after ba helpers and local_loop.cpp. Exact-build prototype; no patching.
// Native evidence and hook bytes: local-bootstrap-hooks.json and ../metadata/.
// This provides a local tutorial merge policy, not recovered server source.
namespace ba_bootstrap {
using ba::Obj;
using ba_local::Root;
static bool awaitingWorld=false, creating=false;
static uint32_t frontRoot=0;
static DWORD bootstrapThread=0;
static void beginJoined(Obj front,Obj encoded,Obj player,bool lan,const char* localMatch=nullptr);

static Obj item(Obj list,int index) {
    void* args[]={&index};return ba::call(list,"get_Item",1,args);
}
static Obj checked(Obj value,const char* reason) {
    if(!value)throw std::runtime_error(reason);return value;
}
static Obj identity(Obj front) {
    Obj game=ba::get<Obj>(front,"_playerGameHandle");
    if(game && ba::get<Obj>(game,"playerHandleWithName_")) return game;
    Root id(ba::make("CommonPb","PlayerHandle"));
    ba::set<uint64_t>(id.get(),"steamId_",1);
    ba::set<bool>(id.get(),"isAliased_",true);
    Root name(ba::make("CommonPb","PlayerHandleWithName"));
    ba::set<Obj>(name.get(),"playerHandle_",id.get());
    ba::set<Obj>(name.get(),"playerName_",ba::str("Offline Player"));
    ba::set<Obj>(name.get(),"filteredName_",ba::str("Offline Player"));
    Root handle(ba::make("CommonPb","PlayerGameHandle"));
    ba::set<Obj>(handle.get(),"playerHandleWithName_",name.get());
    ba::set<uint32_t>(handle.get(),"aiProfileId_",0);
    ba::set<Obj>(front,"_playerGameHandle",handle.get());
    return handle.get();
}
static void overlayTutorial(Obj gameData,Obj dynamic) {
    Obj config=checked(ba::get<Obj>(gameData,"gameConfig_"),"static GameConfig missing");
    Obj armies=ba::get<Obj>(config,"armies_");
    Obj overrides=checked(ba::get<Obj>(checked(dynamic,"dynamic config missing"),"armyConfigOverrides_"),"army overrides missing");
    // Tutorial authored static data retains map, army modifiers and initial units.
    // Dynamic data supplies human/AI identities and explicit scripted decks.
    // Empty profile deck never erases a shipped tutorial deck.
    for(int i=0;i<ba_local::count(overrides);++i) {
        Root dyn(item(overrides,i));
        Obj over=checked(ba::get<Obj>(dyn.get(),"armyConfigOverrides_"),"null army override");
        uint32_t id=ba::get<uint32_t>(over,"armyId_");
        Obj dest=nullptr;
        for(int j=0;j<ba_local::count(armies);++j) {
            Obj candidate=item(armies,j);
            if(ba::get<uint32_t>(candidate,"armyId_")==id) {dest=candidate;break;}
        }
        if(!dest)throw std::runtime_error("tutorial dynamic army not present in static map");
        Obj players=ba::get<Obj>(over,"players_");
        if(ba_local::count(players)) {
            Obj output=ba::get<Obj>(dest,"players_");ba::call(output,"Clear");
            for(int p=0;p<ba_local::count(players);++p)ba_local::addItem(output,item(players,p));
        }
        Obj deck=ba::get<Obj>(over,"deck_");
        if(deck && ba_local::count(ba::get<Obj>(deck,"units_")))ba::set<Obj>(dest,"deck_",deck);
        // IDs 0/1 and alliance 0/1 are explicitly authored by FTUE converter.
        ba::set<uint32_t>(dest,"allianceId_",ba::get<uint32_t>(over,"allianceId_"));
        for(const char* field : {"bannerId_","portraitId_"}) {
            uint32_t v=ba::get<uint32_t>(over,field);if(v)ba::set<uint32_t>(dest,field,v);
        }
        Obj modifiers=ba::get<Obj>(over,"modifiers_");
        if(modifiers)ba::set<Obj>(dest,"modifiers_",modifiers);
        Obj resultDeck=ba::get<Obj>(dest,"deck_");
        ba::log("Offline tutorial army %u: players=%d unitsInDeck=%d profileDeckRequested=%d",id,
            ba_local::count(ba::get<Obj>(dest,"players_")),
            resultDeck ? ba_local::count(ba::get<Obj>(resultDeck,"units_")) : 0,
            ba::get<bool>(dyn.get(),"useCurrentPlayerDeck_") ? 1:0);
    }
    ba::log("Offline authored GameData: armies=%d initialActions=%d",ba_local::count(armies),
        ba_local::count(ba::get<Obj>(gameData,"initialActions_")));
}
static Obj encodeGameData(Obj gameData) {
    void* serializeArgs[]={gameData};
    Root bytes(ba::invoke(ba::find_class("Google.Protobuf","MessageExtensions"),nullptr,"ToByteArray",1,serializeArgs));
    uintptr_t length=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(bytes.get());
    if(length>0x7fffffff)throw std::runtime_error("GameData serialization too large");
    Root stream(ba::make("System.IO","MemoryStream"));
    Obj gzipClass=ba::find_class("System.IO.Compression","GZipStream");
    ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(gzipClass);
    Root gzip(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(gzipClass));
    Obj enumClass=ba::find_class("System.IO.Compression","CompressionMode");
    Obj compressField=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(enumClass,"Compress");
    if(!compressField)throw std::runtime_error("CompressionMode.Compress missing");
    int compress=0;
    ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(compressField,&compress);
    bool leaveOpen=true;void* ctorArgs[]={stream.get(),&compress,&leaveOpen};
    ba::invoke(gzipClass,gzip.get(),".ctor",3,ctorArgs);
    int offset=0, count=static_cast<int>(length);void* writeArgs[]={bytes.get(),&offset,&count};
    ba::call(gzip.get(),"Write",3,writeArgs);
    ba::call(gzip.get(),"Close"); // Stream.Close dispatches protected virtual Dispose(true).
    Root compressed(ba::call(stream.get(),"ToArray"));
    uintptr_t compressedLength=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(compressed.get());
    if(compressedLength>0x7fffffff)throw std::runtime_error("compressed GameData too large");
    count=static_cast<int>(compressedLength);void* copyArgs[]={compressed.get(),&offset,&count};
    Obj result=ba::invoke(ba::find_class("Google.Protobuf","ByteString"),nullptr,"CopyFrom",3,copyArgs);
    ba::log("Offline GameData serialized: %llu bytes, gzip %d bytes",static_cast<unsigned long long>(length),count);
    return result;
}
static void fail(const char* where,const std::exception& error) {
    awaitingWorld=false;creating=false;
    if(ba_practice::active()){ba_practice::fail(where,error);return;}
    if(ba::exportServerAssets()){ba_export::failed(error.what());return;}
    if(ba::dedicated()){ba_lan::fail(where,error);return;}
    ba_local::fail(where,error);
}
static void poll(Obj server) {
    if(ba::community() && ba_community::abortPending && !ba_practice::active())return;
    if(!awaitingWorld || !ba_local::isTarget(server))return;
    if(GetCurrentThreadId()!=bootstrapThread)throw std::runtime_error("bootstrap update on unexpected thread");
    Obj sim=ba::read<Obj>(server,0x140);
    if(!sim || !ba::read<bool>(sim,0x1a0) || !ba::read<Obj>(sim,0x1a8)
        || ba::read<bool>(server,0xd8))return;
    // Mode4 schedules human readiness through AssetMemoryManager.CheckDone(1)
    // after CreateGame. World existence alone does not prove asset prewarming.
    if(ba_practice::active() && !ba_practice::assetsReady(server))return;
    // Reuse original state transition, which writes Simulating and frame -1.
    Root started(ba::make("GamePb","GameStarted"));
    Obj conn=ba::get<Obj>(server,"_currentConnectionInfo");
    ba::set<Obj>(started.get(),"gameHandle_",ba::get<Obj>(conn,"gameHandle_"));
    ba::set<int>(started.get(),"serverState_",1);
    void* args[]={started.get()};ba::call(server,"ProcessGameStarted",1,args);
    awaitingWorld=false;creating=false;
    if(ba_practice::active())ba_practice::worldReady(server);
    else if(ba::lan()) {
        Obj localPlayer=ba::read<Obj>(sim,0x90);
        int army=localPlayer ? ba::read<int>(localPlayer,0x38) : -1;
        ba::log("LAN local simulation player army=%d expected=%d",army,ba::lanSlot());
        if(army!=ba::lanSlot())throw std::runtime_error("LAN local player assigned wrong army");
        ba_lan::ready();
    } else OfflineSetLocalReady(true);
    ba::log("Offline world ready; original GameStarted applied.");
}
}

#include "lan_bootstrap.cpp"

namespace ba_bootstrap {
static void create(Obj front,Obj controller,int mode) {
        ba::init();
        if(mode!=3 && !((ba::lan() || ba::exportServerAssets()) && mode==1))throw std::runtime_error("unsupported offline game mode");
        if(creating)throw std::runtime_error("offline game creation already pending");
        checked(front,"front service missing");checked(controller,"game setting controller missing");
        if(ba::lan() || ba::exportServerAssets())ba_lan_bootstrap::identityLan(front,ba::exportServerAssets()?0:ba::lanSlot());else identity(front);
        Obj contract=ba::find_class("Uncapped.UI","IGameSettingController");
        Obj method=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(contract,"GetConfigForMode",1);
        method=ba::api<Obj(*)(Obj,Obj)>("il2cpp_object_get_virtual_method")(controller,checked(method,"GetConfigForMode missing"));
        void* configArgs[]={&mode};Root config(ba_local::invokeMethod(method,controller,configArgs));
        checked(config.get(),"shipped GameModeConfig unavailable");
        if(frontRoot)ba::api<void(*)(uint32_t)>("il2cpp_gchandle_free")(frontRoot);
        frontRoot=ba::api<uint32_t(*)(Obj,bool)>("il2cpp_gchandle_new")(front,false);
        bootstrapThread=GetCurrentThreadId();creating=true;awaitingWorld=false;
        bool addGenericPlayer=false;void* args[]={config.get(),&addGenericPlayer,nullptr};
        ba::log("Offline mode%d creation: invoking shipped CreateDebugGame map/config builders (export=%d).",mode,ba::exportServerAssets()?1:0);
        ba::call(front,"CreateDebugGame",3,args);
}
}

extern "C" __declspec(dllexport) void OfflineCreateGame(void* front,void* controller,int mode,void*) {
    using namespace ba_bootstrap;
    try {
        ba::init();
        // Export poll invokes create directly. Menu Play cannot start a match
        // while this explicit local asset-generation mode is active.
        if(ba::exportServerAssets())return;
        if(ba::dedicated()){ba_dedicated::ready(front,mode);return;}
        create(front,controller,mode);
    } catch(const std::exception& error) {fail("create game",error);}
}

extern "C" __declspec(dllexport) void OfflineConsumeCreateRequest(void* front,void* consumer,void*) {
    using namespace ba_bootstrap;
    try {
        ba::init();
        if(!creating || GetCurrentThreadId()!=bootstrapThread)throw std::runtime_error("unexpected local create callback");
        Obj expected=ba::api<Obj(*)(uint32_t)>("il2cpp_gchandle_get_target")(frontRoot);
        if(front!=expected)throw std::runtime_error("local create callback front mismatch");
        Root request(ba::get<Obj>(checked(consumer,"create consumer missing"),"frontServerMessages_"));
        if(ba::klass(request.get())!=ba::find_class("GamePb","CreateGameRequest"))throw std::runtime_error("unexpected local request type");
        Root data(ba::get<Obj>(request.get(),"gameData_"));checked(data.get(),"debug builder supplied no GameData");
        if(ba_practice::active()){ba_practice::consume(front,request.get(),data.get());return;}
        if(ba::lan() || ba::exportServerAssets())ba_lan_bootstrap::overlayLan(data.get(),ba::get<Obj>(request.get(),"dynamicGameData_"));
        else overlayTutorial(data.get(),ba::get<Obj>(request.get(),"dynamicGameData_"));
        Obj server=checked(ba::read<Obj>(front,0xd8),"game server integration missing");
        Obj config=checked(ba::get<Obj>(data.get(),"gameConfig_"),"game config missing");
        Obj localConfig=ba::get<Obj>(server,"<ClientConfig>k__BackingField");
        if(!localConfig)localConfig=ba::get<Obj>(front,"<ClientConfig>k__BackingField");
        checked(localConfig,"shipped ClientConfig missing");
        if(!ba::exportServerAssets())ba::set<Obj>(server,"<ClientConfig>k__BackingField",localConfig);
        ba::set<Obj>(config,"versionBuild_",checked(ba::get<Obj>(localConfig,"clientBuild_"),"shipped client build missing"));
        ba::set<Obj>(config,"versionConfig_",ba::get<Obj>(localConfig,"gameApiVersion_"));
        ba::set<Obj>(config,"dllProfile_",ba::get<Obj>(localConfig,"dllProfile_"));
        Root encoded(encodeGameData(data.get()));
        if(ba::exportServerAssets()) {
            ba_export::consume(data.get(),encoded.get());
            awaitingWorld=false;creating=false;
            if(frontRoot){ba::api<void(*)(uint32_t)>("il2cpp_gchandle_free")(frontRoot);frontRoot=0;}
            return;
        }
        if(ba::lan()){if(ba::lanSlot()==0)ba_lan::publish(encoded.get());return;}
        Obj player=identity(front);
        beginJoined(front,encoded.get(),player,false);
    } catch(const std::exception& error) {fail("consume create request",error);}
}

namespace ba_bootstrap {
static void beginJoined(Obj front,Obj encoded,Obj player,bool lan,const char* localMatch) {
        Obj server=checked(ba::read<Obj>(front,0xd8),"game server integration missing");
        if(lan) {
            Root data(ba_lan_bootstrap::decodeGameDataLan(encoded));
            ba_lan_bootstrap::installDeckLan(front,data.get(),ba::lanSlot());
        }
        if(!ba::get<Obj>(server,"<ClientConfig>k__BackingField"))
            ba::set<Obj>(server,"<ClientConfig>k__BackingField",checked(ba::get<Obj>(front,"<ClientConfig>k__BackingField"),"local ClientConfig missing"));
        bootstrapThread=GetCurrentThreadId();
        Root handle(ba::make("CommonPb","GameHandle"));
        ba::set<Obj>(handle.get(),"gameName_",ba::str(localMatch ? localMatch : ba::dedicated() ? ba_lan::dedicatedMatchId.c_str() : (lan ? "loopback-1v1" : "offline-tutorial01")));
        Root connection(ba::make("CommonPb","GameConnectionInfo"));
        ba::set<Obj>(connection.get(),"gameHandle_",handle.get());
        ba::set<Obj>(connection.get(),"address_",ba::str(localMatch ? "offline" : ba::dedicated() ? ba::argument(L"-dedicated-server=").c_str() : "offline"));
        ba::set<bool>(connection.get(),"isSpectator_",false);
        ba::set<Obj>(server,"_currentConnectionInfo",connection.get());
        ba::set<Obj>(server,"_playerGameHandle",player);
        Root joined(ba::make("GamePb","JoinedGame"));
        ba::set<Obj>(joined.get(),"gameHandle_",handle.get());
        ba::set<Obj>(joined.get(),"playerHandle_",player);
        ba::set<int>(joined.get(),"serverState_",0); // WaitingToStart until map callback finishes.
        ba::set<Obj>(joined.get(),"gameDataEncoded_",encoded);
        ba::set<Obj>(joined.get(),"gameConnectionInfo_",connection.get());
        ba::set<bool>(joined.get(),"spectator_",false);
        ba::set<bool>(joined.get(),"reconnected_",false);
        // JoinedGame ctor initializes inputActionsEncoded_ to ByteString.Empty.
        OfflinePrepareLocalGame(server);
        if(!ba_local::isTarget(server))throw std::runtime_error("local input preparation failed");
        if(localMatch)ba_audit::beginMatch(localMatch);
        else if(ba::dedicated())ba_audit::beginMatch(ba_lan::dedicatedMatchId);
        Obj joining=ba::get<Obj>(server,"StartJoiningGame");
        if(joining)ba::call(joining,"Invoke");
        int success=0;void* args[]={&success,joined.get()};
        ba::log("Offline delivering synthesized JoinedGame to original simulation/map bootstrap.");
        // Front.JoinedGame only publishes network/Steam presence. The ordinary
        // world bootstrap supports a null front integration at this call site.
        Root frontService(ba::get<Obj>(server,"_frontServerIntegration"));
        Root telemetry(ba::get<Obj>(server,"_telemetryDataProvider"));
        ba::log("Joined-game dependencies: telemetry=%p analytics=%p pendingRTT=%p",telemetry.get(),
            ba::read<Obj>(telemetry.get(),0x28),ba::read<Obj>(server,0x108));
        ba::set<Obj>(server,"_frontServerIntegration",nullptr);
        try {ba::call(server,"ProcessJoinedGame",2,args);}
        catch(...) {
            ba::set<Obj>(server,"_frontServerIntegration",frontService.get());
            throw;
        }
        ba::set<Obj>(server,"_frontServerIntegration",frontService.get());
        awaitingWorld=true;
}
}

namespace ba {
void lanFrontUpdate(Obj front) {
    if(dedicated()){ba_dedicated_session::update(front);return;}
    if(ba_lan::stopped)return;
    try {
        ba_lan::poll();
        static bool creationStarted=false, joined=false;
        if(ba_lan::welcomed && !creationStarted) {
            Obj state=get<Obj>(read<Obj>(owner,0x2b0),"_currentState");
            if(state==read<Obj>(owner,0x2c0)) {
                creationStarted=true;
                ba_lan_bootstrap::identityLan(front,lanSlot());
                if(lanSlot()==0)OfflineCreateGame(front,owner,1,nullptr);
                log("LAN waiting for canonical host GameData");
            }
        }
        if(creationStarted && !joined && !ba_lan::bootstrap.empty()) {
            joined=true;ba_local::Root encoded(ba_lan::byteString(ba_lan::bootstrap));
            ba_bootstrap::beginJoined(front,encoded.get(),ba_lan_bootstrap::identityLan(front,lanSlot()),true);
        }
    }catch(const std::exception& e){ba_lan::fail("LAN front update",e);}
}
}

extern "C" __declspec(dllexport) void OfflineSignalReadyToPlay(void* server,void*) {
    try {ba::init();if(ba_practice::signalReady(server))return;if(ba_local::isTarget(server))ba::log("Offline ready-to-play received; waiting for completed world initialization.");}
    catch(const std::exception& error){ba_bootstrap::fail("signal ready",error);}
}

extern "C" __declspec(dllexport) void OfflineBootstrapGameUpdate(void* server,void* method) {
    if(ba_practice::gameUpdate(server,method))return;
    try {ba::init();ba_bootstrap::poll(server);}
    catch(const std::exception& error){ba_bootstrap::fail("bootstrap update",error);}
    if(ba::lan()) {
        try {ba_lan::tick(server);ba_dedicated_results::update(server);}catch(const std::exception& error){ba_lan::fail("LAN update",error);}
    } else OfflineGameUpdate(server,method);
}
