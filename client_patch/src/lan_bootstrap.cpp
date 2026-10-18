#pragma once
// Include after ba helpers and local_loop.cpp; does not patch or launch anything.
// Exact-build evidence: ../network/protocol.txt, deckselector-selected.asm,
// Deck.ToProtoBuildtime RVA0x3cd43c0, Deck.FromProto RVA0x3cd4630.
// Slot convention is zero based: 0/1 => aliased SteamId1/2.
namespace ba_lan_bootstrap {
using ba::Obj;
using ba_local::Root;
static Obj required(Obj value,const char* reason) {
    if(!value)throw std::runtime_error(reason);return value;
}
static Obj at(Obj list,int index) {
    void* args[]={&index};return ba::call(required(list,"LAN list missing"),"get_Item",1,args);
}
static Obj playerLan(int slot) {
    if(slot<0 || slot>1)throw std::runtime_error("LAN slot must be zero based 0 or 1");
    Root id(ba::make("CommonPb","PlayerHandle"));
    ba::set<uint64_t>(id.get(),"steamId_",static_cast<uint64_t>(slot+1));
    ba::set<bool>(id.get(),"isAliased_",true);
    Root named(ba::make("CommonPb","PlayerHandleWithName"));
    ba::set<Obj>(named.get(),"playerHandle_",id.get());
    Obj text=ba::str(slot==0 ? "LAN Player 1" : "LAN Player 2");
    ba::set<Obj>(named.get(),"playerName_",text);
    ba::set<Obj>(named.get(),"filteredName_",text);
    Root result(ba::make("CommonPb","PlayerGameHandle"));
    ba::set<Obj>(result.get(),"playerHandleWithName_",named.get());
    ba::set<uint32_t>(result.get(),"aiProfileId_",0);
    return result.get();
}
static Obj identityLan(Obj front,int slot) {
    Root result(playerLan(slot));
    ba::set<Obj>(required(front,"LAN front missing"),"_playerGameHandle",result.get());
    ba::set<Obj>(front,"_currentPlayerName",ba::str(slot==0 ? "LAN Player 1" : "LAN Player 2"));
    ba::log("LAN identity: slot=%d aliased SteamId=%d",slot,slot+1);
    return result.get();
}
static uint32_t uintAt(Obj repeated,int index) {
    Root boxed(at(repeated,index));
    return *ba::api<uint32_t*(*)(Obj)>("il2cpp_object_unbox")(required(boxed.get(),"LAN unit missing"));
}
static void addUint(Obj repeated,uint32_t value) {
    Obj selected=nullptr;void* iter=nullptr;
    while(Obj method=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(ba::klass(repeated),&iter)) {
        if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(method),"Add"))continue;
        if(ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(method)!=1)continue;
        Obj type=ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(method,0);
        if(ba::api<int(*)(Obj)>("il2cpp_type_get_type")(type)==9) {selected=method;break;}
    }
    void* args[]={&value};ba_local::invokeMethod(required(selected,"RepeatedField<uint>.Add missing"),repeated,args);
}
static bool validDeck(Obj deck,Obj config) {
    if(!deck)return false;
    Obj units=ba::get<Obj>(deck,"units_");
    if(!units || ba_local::count(units)!=8)return false;
    Obj entities=required(ba::get<Obj>(config,"entities_"),"LAN entity configs missing");
    for(int slot=0;slot<8;++slot) {
        // Shipped FTUE decks retain eight positions, with 0 for an empty slot.
        // Require both opening unit slots; every occupied slot must exist in
        // this normal map's entity definitions. This is a limited test deck.
        uint32_t id=uintAt(units,slot);
        if(!id) {if(slot<2)return false;continue;}
        bool found=false;
        for(int i=0;i<ba_local::count(entities);++i)
            if(ba::get<uint32_t>(at(entities,i),"entityType_")==id) {found=true;break;}
        if(!found)return false;
    }
    return true;
}
static Obj protoFromAuthoredDeck(Obj runtimeDeck) {
    // ToProtoShared copies active abilities. ToProtoBuildtime copies each
    // four-byte _units element into protobuf units_ after that same call.
    // Reproduce only that proven copy; cosmetic lookup is unnecessary here.
    Root result(ba::call(runtimeDeck,"ToProtoShared"));
    Obj source=required(ba::get<Obj>(runtimeDeck,"_units"),"authored deck units missing");
    size_t count=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(source);
    if(count!=8)return nullptr;
    Obj dest=ba::get<Obj>(result.get(),"units_");
    for(size_t i=0;i<count;++i)addUint(dest,ba::read<uint32_t>(source,0x20+4*i));
    return result.get();
}
static Obj shippedDeck(Obj config,Obj dynamic) {
    Obj armies=ba::get<Obj>(config,"armies_");
    for(int i=0;i<ba_local::count(armies);++i) {
        Obj candidate=ba::get<Obj>(at(armies,i),"deck_");
        if(validDeck(candidate,config)) {ba::log("LAN deck source: authored army %d",i);return candidate;}
    }
    if(dynamic) {
        Obj overrides=ba::get<Obj>(dynamic,"armyConfigOverrides_");
        for(int i=0;overrides && i<ba_local::count(overrides);++i) {
            Obj army=ba::get<Obj>(at(overrides,i),"armyConfigOverrides_");
            Obj candidate=army ? ba::get<Obj>(army,"deck_") : nullptr;
            if(validDeck(candidate,config)) {ba::log("LAN deck source: authored dynamic army %d",i);return candidate;}
        }
    }
    // The tutorial mode assets are already retained by RGameSingleton's loaded
    // GameModeConfigList. They do not require loading the tutorial scene or its
    // separate Addressable objective data. FTUEArmyToProto.ToProto at RVA
    // 0x3db0a70 uses PlayerDeck+0x20 or EnemyDeck+0x38 and copies _units;
    // FTUEOneVsOneArmyToProto has Deck+0x20 and EnemyDeck+0x38.
    required(ba::owner,"LAN owner missing for shipped tutorial deck");
    for(int mode : {3,4}) {
        void* modeArgs[]={&mode};
        Root modeConfig(ba::call(ba::owner,"GetConfigForMode",1,modeArgs));
        if(!modeConfig.get())continue;
        Obj provider=ba::get<Obj>(modeConfig.get(),"GameDataProvider");
        Obj converter=provider ? ba::get<Obj>(provider,"ArmiesConverter") : nullptr;
        if(!converter)continue;
        ba::log("LAN inspecting loaded mode%d army converter %s",mode,
            ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(ba::klass(converter)));
        for(const char* fieldName : {"PlayerDeck","Deck","EnemyDeck"}) {
            Obj field=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(ba::klass(converter),fieldName);
            if(!field)continue;
            Obj authored=nullptr;ba::api<void(*)(Obj,Obj,void*)>("il2cpp_field_get_value")(converter,field,&authored);
            if(!authored)continue;
            Root candidate(protoFromAuthoredDeck(authored));
            if(validDeck(candidate.get(),config)) {
                ba::log("LAN deck source: loaded shipped mode%d %s.%s",mode,
                    ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(ba::klass(converter)),fieldName);
                return candidate.get();
            }
            if(candidate.get()) {
                Obj units=ba::get<Obj>(candidate.get(),"units_");
                ba::log("LAN rejected mode%d %s deck: %d slots; opening slot empty or occupied unit absent from map",mode,fieldName,ba_local::count(units));
                for(int i=0;i<ba_local::count(units);++i)ba::log("  authored slot%d entityType=%u",i,uintAt(units,i));
            }
        }
    }
    Obj assetClass=ba::find_class("Uncapped","AIDeckPreset");
    Obj type=ba::api<Obj(*)(Obj)>("il2cpp_class_get_type")(assetClass);
    Root reflectedType(ba::api<Obj(*)(Obj)>("il2cpp_type_get_object")(type));
    void* args[]={reflectedType.get()};
    Root assets(ba::invoke(ba::find_class("UnityEngine","Resources"),nullptr,"FindObjectsOfTypeAll",1,args));
    size_t count=assets.get() ? ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(assets.get()) : 0;
    ba::log("LAN searching %llu loaded authored AIDeckPreset assets",static_cast<unsigned long long>(count));
    for(size_t i=0;i<count;++i) {
        Obj asset=ba::read<Obj>(assets.get(),0x20+sizeof(Obj)*i);
        if(!asset)continue;
        Obj def=ba::get<Obj>(asset,"Definition");
        Obj deck=def ? ba::get<Obj>(def,"_deck") : nullptr;
        if(!deck)continue;
        Root candidate(protoFromAuthoredDeck(deck));
        if(validDeck(candidate.get(),config)) {
            ba::log("LAN deck source: shipped AIDeckPreset index %llu",static_cast<unsigned long long>(i));
            return candidate.get();
        }
    }
    throw std::runtime_error("no loaded authored eight-slot deck with two opening units compatible with LAN map");
}
static void overlayLan(Obj gameData,Obj dynamic) {
    Obj config=required(ba::get<Obj>(required(gameData,"LAN GameData missing"),"gameConfig_"),"LAN GameConfig missing");
    Obj map=ba::get<Obj>(config,"map_");
    Obj mapName=map ? ba::get<Obj>(map,"displayName_") : nullptr;
    Obj mapKey=map ? ba::get<Obj>(map,"assetRuntimeKey_") : nullptr;
    ba::log("LAN map: %ls; asset=%ls",mapName ? ba::api<const wchar_t*(*)(Obj)>("il2cpp_string_chars")(mapName) : L"?",mapKey ? ba::api<const wchar_t*(*)(Obj)>("il2cpp_string_chars")(mapKey) : L"?");
    Obj armies=required(ba::get<Obj>(config,"armies_"),"LAN armies missing");
    if(ba_local::count(armies)!=2)throw std::runtime_error("normal LAN mode must supply exactly two authored armies");
    Root deck(required(shippedDeck(config,dynamic),"LAN default deck missing"));
    ba::set<int>(config,"gameMode_",1);
    ba::set<uint64_t>(config,"rngSeedValue_",UINT64_C(0x42414c414e303031));
    for(int slot=0;slot<2;++slot) {
        Obj army=at(armies,slot);
        if(ba::get<uint32_t>(army,"armyId_")!=static_cast<uint32_t>(slot))throw std::runtime_error("LAN authored army order must be 0,1");
        Obj players=required(ba::get<Obj>(army,"players_"),"LAN army player list missing");
        ba::call(players,"Clear");
        Root player(playerLan(slot));ba_local::addItem(players,player.get());
        Root ownDeck(ba::call(deck.get(),"Clone"));
        ba::set<Obj>(army,"deck_",ownDeck.get());
        ba::set<uint32_t>(army,"allianceId_",static_cast<uint32_t>(slot));
        ba::log("LAN army slot%d id%u alliance%u: one human, eight authored unit slots",slot,
            ba::get<uint32_t>(army,"armyId_"),ba::get<uint32_t>(army,"allianceId_"));
    }
    Obj units=ba::get<Obj>(deck.get(),"units_");
    int occupied=0;
    for(int i=0;i<8;++i) {
        uint32_t id=uintAt(units,i);if(id)++occupied;
        ba::log("LAN test deck slot%d entityType=%u%s",i,id,id ? "" : " (empty authored slot)");
    }
    ba::log("LAN shared shipped test deck: %d occupied and %d empty slots; limited unit selection for initial 1v1 test",occupied,8-occupied);
    ba::log("LAN normal GameData prepared; authored initialActions=%d fixed seed=0x42414c414e303031",
        ba_local::count(ba::get<Obj>(gameData,"initialActions_")));
}
static void installDeckLan(Obj front,Obj gameData,int slot) {
    if(slot<0 || slot>3)throw std::runtime_error("LAN deck slot outside supported roster");
    Obj config=required(ba::get<Obj>(gameData,"gameConfig_"),"LAN install GameConfig missing");
    Obj armies=ba::get<Obj>(config,"armies_");
    const int count=ba_local::count(armies);
    if((count!=2 && count!=4) || slot>=count)throw std::runtime_error("LAN deck slot missing from roster");
    Obj proto=required(ba::get<Obj>(at(armies,slot),"deck_"),"LAN assigned deck missing");
    if(!validDeck(proto,config))throw std::runtime_error("LAN assigned test deck has invalid opening units or map unit IDs");
    void* fromArgs[]={proto};
    Root runtime(ba::invoke(ba::find_class("Uncapped","Deck"),nullptr,"FromProto",1,fromArgs));
    Obj selector=required(ba::get<Obj>(front,"_deckSelector"),"LAN deck selector missing");
    void* selectArgs[]={runtime.get()};ba::call(selector,"SetDeck",1,selectArgs);
    if(wcsstr(GetCommandLineW(),L"-lan-smoke"))ba_lan_smoke::prepare(gameData,slot);
    ba::log("LAN local DeckSelector updated from shared army%d before JoinArmyCommand",slot);
}
static Obj decodeGameDataLan(Obj encoded) {
    Root bytes(ba::call(required(encoded,"LAN compressed GameData missing"),"ToByteArray"));
    size_t length=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(bytes.get());
    if(length==0 || length>1024*1024)throw std::runtime_error("LAN compressed GameData length invalid");
    Root source(ba::make("System.IO","MemoryStream"));
    int offset=0,count=static_cast<int>(length);void* writeArgs[]={bytes.get(),&offset,&count};
    ba::call(source.get(),"Write",3,writeArgs);
    int64_t position=0;void* positionArgs[]={&position};ba::call(source.get(),"set_Position",1,positionArgs);
    Obj gzipClass=ba::find_class("System.IO.Compression","GZipStream");
    Obj modeClass=ba::find_class("System.IO.Compression","CompressionMode");
    ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(gzipClass);
    Root gzip(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(gzipClass));
    Obj selected=nullptr;void* iter=nullptr;
    while(Obj method=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(gzipClass,&iter)) {
        if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(method),".ctor"))continue;
        if(ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(method)!=3)continue;
        Obj type=ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(method,1);
        if(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(type)==modeClass){selected=method;break;}
    }
    Obj modeField=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(modeClass,"Decompress");
    int mode=0;ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(required(modeField,"Decompress mode missing"),&mode);
    bool leaveOpen=true;void* ctorArgs[]={source.get(),&mode,&leaveOpen};
    ba_local::invokeMethod(required(selected,"GZipStream(Stream,CompressionMode,bool) missing"),gzip.get(),ctorArgs);
    Root dest(ba::make("System.IO","MemoryStream"));
    void* copyArgs[]={dest.get()};ba::call(gzip.get(),"CopyTo",1,copyArgs);ba::call(gzip.get(),"Close");
    Root raw(ba::call(dest.get(),"ToArray"));
    ba_lan::Bytes decoded=ba_lan::arrayBytes(raw.get());
    ba::log("LAN decoded GameData: gzip=%llu proto=%llu",static_cast<unsigned long long>(length),static_cast<unsigned long long>(decoded.size()));
    return ba_lan::parse("GameData",decoded);
}
}
