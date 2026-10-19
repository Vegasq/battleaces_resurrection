#pragma once
// Local asset generation from the owner's loaded build37822 client. Included
// after local_bootstrap.cpp; no captured protobuf/catalog payload is embedded.
// The explicit flag suppresses both network adapters and match startup.
namespace ba_export {
using ba::Obj;using ba_local::Root;using Bytes=std::vector<unsigned char>;
enum class Phase { Waiting,Building,Complete,Failed };
static Phase phase=Phase::Waiting;
static ULONGLONG startedAt=0;
static std::wstring directory;
static HANDLE outputLock=INVALID_HANDLE_VALUE;
static uint32_t savedFront=0,savedPlayer=0,savedName=0;
static size_t mapIndex=0;
static const int mapModes[]={1,2,5};
static const wchar_t* mapFiles[]={L"map-1v1.pb.gz",L"map-2v2.pb.gz",L"map-2vai.pb.gz"};
static std::string mapRows,rawMapRows,rawOne;

static std::wstring moduleDirectory() {
    wchar_t path[32768];DWORD count=GetModuleFileNameW(ba::module,path,32768);
    if(!count || count>=32768)throw std::runtime_error("export module path unavailable");
    wchar_t* slash=wcsrchr(path,L'\\');
    if(!slash)throw std::runtime_error("export module directory unavailable");
    *(slash+1)=0;return path;
}
static std::wstring outputDirectory() {
    std::wstring result;
    const wchar_t* command=GetCommandLineW(),*cursor=command;
    const wchar_t* key=L"-server-assets-dir=";
    while((cursor=wcsstr(cursor,key))!=nullptr) {
        const wchar_t before=cursor==command?L' ':cursor[-1];
        cursor+=wcslen(key);
        if(before!=L' ' && before!=L'\t' && before!=L'\"')continue;
        const bool quoteAtValue=*cursor==L'\"';
        const bool quoted=quoteAtValue || before==L'\"';if(quoteAtValue)++cursor;
        const wchar_t* end=cursor;
        while(*end && *end!=L'\"' && (quoted || (*end!=L' ' && *end!=L'\t')))++end;
        if(end==cursor || (quoted && *end!=L'\"'))throw std::runtime_error("invalid -server-assets-dir value");
        result.assign(cursor,end);break;
    }
    if(result.empty())result=L"server-assets";
    const bool absolute=(result.size()>2 && result[1]==L':' && (result[2]==L'\\' || result[2]==L'/')) ||
                        (result.size()>1 && result[0]==L'\\' && result[1]==L'\\');
    if(!absolute)result=moduleDirectory()+result;
    wchar_t full[32768];DWORD count=GetFullPathNameW(result.c_str(),32768,full,nullptr);
    if(!count || count>=32768)throw std::runtime_error("export output path too long");
    result=full;while(result.size()>3 && (result.back()==L'\\' || result.back()==L'/'))result.pop_back();
    if(!CreateDirectoryW(result.c_str(),nullptr) && GetLastError()!=ERROR_ALREADY_EXISTS)
        throw std::runtime_error("cannot create export directory (parent must exist)");
    const DWORD attributes=GetFileAttributesW(result.c_str());
    if(attributes==INVALID_FILE_ATTRIBUTES || !(attributes&FILE_ATTRIBUTE_DIRECTORY))
        throw std::runtime_error("export output is not a directory");
    return result;
}
static std::wstring path(const wchar_t* name) {return directory+L"\\"+name;}
static void note(const char* text) {
    ba::log("Server asset export: %s",text);
    if(directory.empty())return;
    FILE* out=_wfsopen(path(L"export.log").c_str(),L"a",_SH_DENYNO);
    if(out){fprintf(out,"[%llu] PID=%lu %s\n",GetTickCount64(),GetCurrentProcessId(),text);fclose(out);}
}
static void atomicWrite(const std::wstring& target,const unsigned char* bytes,size_t size) {
    const std::wstring temporary=target+L".tmp";
    FILE* out=_wfsopen(temporary.c_str(),L"wb",_SH_DENYNO);
    if(!out)throw std::runtime_error("cannot open export temporary output");
    const bool writeFailed=(size && fwrite(bytes,1,size,out)!=size) || fflush(out)!=0;
    const int closeResult=fclose(out);
    if(writeFailed || closeResult){DeleteFileW(temporary.c_str());throw std::runtime_error("export write failed");}
    if(!MoveFileExW(temporary.c_str(),target.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)) {
        DeleteFileW(temporary.c_str());throw std::runtime_error("export atomic rename failed");
    }
}
static Bytes readFile(const std::wstring& source) {
    FILE* file=_wfsopen(source.c_str(),L"rb",_SH_DENYNO);
    if(!file)throw std::runtime_error("cannot read generated catalog");
    Bytes bytes;unsigned char buffer[16384];size_t count;
    while((count=fread(buffer,1,sizeof(buffer),file))!=0) {
        bytes.insert(bytes.end(),buffer,buffer+count);
        if(bytes.size()>4*1024*1024){fclose(file);throw std::runtime_error("generated catalog size limit");}
    }
    const bool bad=ferror(file)!=0;fclose(file);
    if(bad || bytes.empty())throw std::runtime_error("generated catalog read failed");
    return bytes;
}
static std::string hash(const Bytes& bytes) {
    const auto digest=ba_lan::sha(bytes);std::string out;out.reserve(64);
    const char* alphabet="0123456789abcdef";
    for(unsigned char value:digest){out+=alphabet[value>>4];out+=alphabet[value&15];}
    return out;
}
static Bytes arrayBytes(Obj array,size_t maximum) {
    if(!array)throw std::runtime_error("export managed byte array missing");
    const size_t length=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(array);
    if(!length || length>maximum)throw std::runtime_error("export byte array size outside bounds");
    const auto data=static_cast<const unsigned char*>(array)+0x20;
    return Bytes(data,data+length);
}
static auto& aiProfiles=*new ba_tables::Table("AIProfile","AIProfileTable","35290f27a7e495444bf634c20a53d056");
static Bytes serializeAIRule(Obj manager,Obj tuning) {
    ba_tables::require(tuning!=nullptr,"AI export tuning missing");
    Obj cls=ba::find_class("FlatBuffers","FlatBufferBuilder");
    ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(cls);
    Root builder(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(cls));
    Obj selected=nullptr;void* iterator=nullptr;
    while(Obj method=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(cls,&iterator)) {
        if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(method),".ctor") ||
           ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(method)!=1)continue;
        Obj type=ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(method,0);
        if(ba::api<int(*)(Obj)>("il2cpp_type_get_type")(type)==8){selected=method;break;}
    }
    ba_tables::require(selected!=nullptr,"AI export Int32 builder constructor missing");
    int capacity=10000;void* ctorArgs[]={&capacity};ba_local::invokeMethod(selected,builder.get(),ctorArgs);
    void* args[]={builder.get(),tuning};ba::call(manager,"BuildFlatBuffer",2,args);
    Root buffer(ba::call(builder.get(),"get_DataBuffer"));
    Root array(ba::call(buffer.get(),"ToSizedArray"));
    return arrayBytes(array.get(),8*1024*1024);
}
static std::vector<uint32_t> aiSelection(Obj manager,const char* field) {
    Obj array=ba::get<Obj>(manager,field);const size_t count=ba_catalog::length(array);
    ba_tables::require(count<=4,"AI export selection capacity invalid");
    std::vector<uint32_t> result;
    for(size_t i=0;i<count;++i)result.push_back(ba::read<uint32_t>(array,0x20+i*4));
    return result;
}
static Bytes exportAIRules() {
    Root manager(ba::get<Obj>(ba::owner,"<AIManager>k__BackingField"));
    ba_tables::require(manager.get() && aiProfiles.get(),"AI export manager/table missing");
    const uint32_t defaultId=ba::get<uint32_t>(manager.get(),"_defaultAI");
    const uint64_t world=ba::get<uint64_t>(manager.get(),"_aiWorld");
    const int lastFrame=ba::get<int>(manager.get(),"_lastUpdatedFrame");
    const auto selected=aiSelection(manager.get(),"_armyAISelection"),debug=aiSelection(manager.get(),"_debugArmyAISelection");
    const Obj simulation=ba::get<Obj>(manager.get(),"_playerSimulation");
    const int players=ba_local::count(ba::get<Obj>(manager.get(),"_aiPlayers"));
    ba_tables::require(!world && !players,"AI export requires an idle manager");
    Root table(aiProfiles.get()),elements(ba::call(table.get(),"get_Elements"));
    const size_t count=ba_catalog::length(elements.get());
    ba_tables::require(count>0 && count<=256,"AI export profile count invalid");
    std::string rows;std::vector<uint32_t> ids;size_t totalBytes=0;bool foundDefault=false;
    for(size_t index=0;index<count;++index) {
        Obj profile=ba_catalog::arrayAt(elements.get(),index);
        ba_tables::require(profile!=nullptr,"AI export null profile");
        Root idObject(ba::call(profile,"get_ID"));const uint32_t id=ba_catalog::unbox<uint32_t>(idObject.get());
        const int mode=ba::get<int>(profile,"GameMode");const bool enabled=ba::get<bool>(profile,"Enable");
        if(id!=defaultId && (!enabled || (mode!=1 && mode!=2 && mode!=4 && mode!=5)))continue;
        ba_tables::require(id && std::find(ids.begin(),ids.end(),id)==ids.end(),"AI export duplicate/zero profile");
        Root tuning(ba::get<Obj>(profile,"AIFuzzyTuning"));Bytes bytes=serializeAIRule(manager.get(),tuning.get());
        ba_tables::require(bytes==serializeAIRule(manager.get(),tuning.get()),"AI rule serialization is not repeatable");
        totalBytes+=bytes.size();ba_tables::require(totalBytes<=32*1024*1024,"AI export aggregate size limit");
        const std::string filename="ai-rules-"+std::to_string(id)+".fb";
        const std::wstring wide(filename.begin(),filename.end());atomicWrite(path(wide.c_str()),bytes.data(),bytes.size());
        if(!rows.empty())rows+=',';
        rows+="{\"profile\":"+std::to_string(id)+",\"mode\":"+std::to_string(mode)+",\"enabled\":"+(enabled?"true":"false")+
            ",\"file\":"+ba_catalog::quote(filename)+",\"bytes\":"+std::to_string(bytes.size())+",\"sha256\":"+ba_catalog::quote(hash(bytes))+"}";
        ids.push_back(id);foundDefault|=id==defaultId;
        ba::log("AI rule exported: profile=%u mode=%d bytes=%zu repeatable=1",id,mode,bytes.size());
    }
    ba_tables::require(foundDefault && !ids.empty(),"AI export default profile missing");
    ba_tables::require(ba::get<uint64_t>(manager.get(),"_aiWorld")==world &&
        ba::get<int>(manager.get(),"_lastUpdatedFrame")==lastFrame &&
        ba::get<uint32_t>(manager.get(),"_defaultAI")==defaultId &&
        ba::get<Obj>(manager.get(),"_playerSimulation")==simulation &&
        ba_local::count(ba::get<Obj>(manager.get(),"_aiPlayers"))==players &&
        aiSelection(manager.get(),"_armyAISelection")==selected && aiSelection(manager.get(),"_debugArmyAISelection")==debug,
        "AI rule export changed manager/world state");
    const std::string manifest="{\"schema\":1,\"build\":37822,\"format\":\"Uncapped.Flatbuffers.Fuzzy\",\"default_profile\":"+
        std::to_string(defaultId)+",\"ai_dll_sha256\":\"14b504d4946fe60d0d62e1e8b8a641b4c1bbd07277d1bbca09e0151512ff19ca\","
        "\"repeatable\":true,\"repeatability_scope\":\"same_loaded_process\",\"manager_unchanged\":true,\"profiles\":["+rows+"]}\n";
    Bytes result(manifest.begin(),manifest.end());atomicWrite(path(L"ai-rules.json"),result.data(),result.size());
    note("AI rules exported through original serializer; repeated bytes match and manager/world state is unchanged.");
    return result;
}
#include "server_bot_catalog.cpp"
static uint32_t root(Obj value) {
    return value?ba::api<uint32_t(*)(Obj,bool)>("il2cpp_gchandle_new")(value,false):0;
}
static void restoreIdentity() {
    if(savedFront) {
        Obj front=ba::api<Obj(*)(uint32_t)>("il2cpp_gchandle_get_target")(savedFront);
        Obj player=savedPlayer?ba::api<Obj(*)(uint32_t)>("il2cpp_gchandle_get_target")(savedPlayer):nullptr;
        Obj name=savedName?ba::api<Obj(*)(uint32_t)>("il2cpp_gchandle_get_target")(savedName):nullptr;
        ba::set<Obj>(front,"_playerGameHandle",player);ba::set<Obj>(front,"_currentPlayerName",name);
    }
    for(uint32_t* handle:{&savedFront,&savedPlayer,&savedName}) {
        if(*handle)ba::api<void(*)(uint32_t)>("il2cpp_gchandle_free")(*handle);*handle=0;
    }
}
static void releaseLock() {if(outputLock!=INVALID_HANDLE_VALUE){CloseHandle(outputLock);outputLock=INVALID_HANDLE_VALUE;}}
static void failed(const char* reason) {
    if(phase==Phase::Complete || phase==Phase::Failed)return;
    phase=Phase::Failed;
    bot_catalog::cleanup();
    try{restoreIdentity();}catch(const std::exception& error){ba::log("Export identity restoration: %s",error.what());}
    note(reason);
    if(!directory.empty() && outputLock!=INVALID_HANDLE_VALUE) {
        try {
            const std::string text="{\"schema\":1,\"complete\":false,\"error\":"+ba_catalog::quote(reason)+"}\n";
            atomicWrite(path(L"export-error.json"),reinterpret_cast<const unsigned char*>(text.data()),text.size());
        }catch(const std::exception& error){ba::log("Export failure record: %s",error.what());}
    }
    releaseLock();
}
static void overlay(Obj gameData,Obj dynamic) {
    const int mode=mapModes[mapIndex];
    if(mode==1){ba_lan_bootstrap::overlayLan(gameData,dynamic);return;}
    Obj config=ba::get<Obj>(gameData,"gameConfig_"),armies=ba::get<Obj>(config,"armies_");
    ba_tables::require(ba::get<int>(config,"gameMode_")==mode && ba_local::count(armies)==4,"team export mode/army count mismatch");
    Root deck(ba_lan_bootstrap::shippedDeck(config,dynamic));
    for(int slot=0;slot<4;++slot) {
        Obj army=ba_bootstrap::item(armies,slot);
        ba_tables::require(ba::get<uint32_t>(army,"armyId_")==static_cast<uint32_t>(slot) &&
            ba::get<uint32_t>(army,"allianceId_")==static_cast<uint32_t>(slot&1),"team export authored army/alliance mismatch");
        Root player(ba_lan_bootstrap::playerLan(0));Obj named=ba::get<Obj>(player.get(),"playerHandleWithName_");
        ba::set<uint64_t>(ba::get<Obj>(named,"playerHandle_"),"steamId_",static_cast<uint64_t>(slot+1));
        Root name(ba::str(("Export Army "+std::to_string(slot)).c_str()));
        ba::set<Obj>(named,"playerName_",name.get());ba::set<Obj>(named,"filteredName_",name.get());
        Obj players=ba::get<Obj>(army,"players_");ba::call(players,"Clear");ba_local::addItem(players,player.get());
        Root ownDeck(ba::call(deck.get(),"Clone"));ba::set<Obj>(army,"deck_",ownDeck.get());
    }
    ba::set<uint64_t>(config,"rngSeedValue_",UINT64_C(0x42414c414e303031));
    ba::log("Team export: mode=%d armies=4 authored alliances=0/1/0/1 initialActions=%d unchanged",mode,
        ba_local::count(ba::get<Obj>(gameData,"initialActions_")));
}
static void consume(Obj gameData,Obj encoded) {
    if(phase!=Phase::Building || outputLock==INVALID_HANDLE_VALUE)throw std::runtime_error("unexpected export builder callback");
    Root encodedArray(ba::call(encoded,"ToByteArray"));Bytes compressed=arrayBytes(encodedArray.get(),2*1024*1024);
    void* args[]={gameData};Root rawArray(ba::invoke(ba::find_class("Google.Protobuf","MessageExtensions"),nullptr,"ToByteArray",1,args));
    Bytes raw=arrayBytes(rawArray.get(),16*1024*1024);
    const std::wstring filename=mapFiles[mapIndex];const std::string narrow(filename.begin(),filename.end());
    atomicWrite(path(filename.c_str()),compressed.data(),compressed.size());
    const std::string rawRow="{\"bytes\":"+std::to_string(raw.size())+",\"sha256\":\""+hash(raw)+"\"}";
    if(mapIndex==0)rawOne=rawRow;
    if(!mapRows.empty()){mapRows+=',';rawMapRows+=',';}
    mapRows+=ba_catalog::quote(narrow)+":{\"bytes\":"+std::to_string(compressed.size())+",\"sha256\":\""+hash(compressed)+"\"}";
    rawMapRows+=ba_catalog::quote(narrow)+":"+rawRow;
    restoreIdentity();
    if(++mapIndex<3) {
        phase=Phase::Waiting;note("Map export saved; next original mode builder will start on a later menu poll.");return;
    }
    ba_catalog::exportFile(path(L"unit-catalog.json").c_str());
    Bytes catalog=readFile(path(L"unit-catalog.json"));
    Bytes aiRules=exportAIRules();
    Bytes botCatalog=bot_catalog::exportFile();
    const auto cosmeticText=ba_cosmetics::serialize();
    ba_tables::require(cosmeticText==ba_cosmetics::serialize(),"cosmetic export catalog is not repeatable");
    Bytes cosmeticCatalog(cosmeticText.begin(),cosmeticText.end());
    atomicWrite(path(L"cosmetic-catalog.json"),cosmeticCatalog.data(),cosmeticCatalog.size());
    std::string manifest="{\"schema\":1,\"asset_format\":1,\"complete\":true,\"build\":37822,\"pid\":"+std::to_string(GetCurrentProcessId())+
        ",\"source\":\"loaded original mode1/2/5 GameData builders and runtime tables\","
        "\"original_gameassembly_sha256\":\"e59d08c01479b27404778048d7e13546dbf3771f6b3912744c7c2bdf80c4e758\","
        "\"simulation_sha256\":\"107bb83dc416a16492277392c50104660e34c48911345ae2e0d5afe3929a07fb\","
        "\"files\":{"+mapRows+",\"unit-catalog.json\":{\"bytes\":"+std::to_string(catalog.size())+",\"sha256\":\""+hash(catalog)+
        "\"},\"ai-rules.json\":{\"bytes\":"+std::to_string(aiRules.size())+",\"sha256\":\""+hash(aiRules)+
        "\"},\"bot-catalog.json\":{\"bytes\":"+std::to_string(botCatalog.size())+",\"sha256\":\""+hash(botCatalog)+
        "\"},\"cosmetic-catalog.json\":{\"bytes\":"+std::to_string(cosmeticCatalog.size())+",\"sha256\":\""+hash(cosmeticCatalog)+
        "\"}},\"raw_game_data\":"+rawOne+",\"raw_maps\":{"+rawMapRows+"}}\n";
    atomicWrite(path(L"export.json"),reinterpret_cast<const unsigned char*>(manifest.data()),manifest.size());
    phase=Phase::Complete;releaseLock();
    note("COMPLETE: three mode maps, unit/bot/cosmetic catalogs, AI rules and export.json written; no match started. You may close the game.");
}
static void poll(Obj front) {
    if(!ba::exportServerAssets() || phase==Phase::Complete || phase==Phase::Failed)return;
    try {
        if(!startedAt) {
            startedAt=GetTickCount64();directory=outputDirectory();
            outputLock=CreateFileW(path(L"export.lock").c_str(),GENERIC_WRITE,0,nullptr,OPEN_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);
            if(outputLock==INVALID_HANDLE_VALUE)throw std::runtime_error("another export owns this output directory");
            for(const wchar_t* name:{L"export.json",L"export-error.json"})
                if(!DeleteFileW(path(name).c_str()) && GetLastError()!=ERROR_FILE_NOT_FOUND)
                    throw std::runtime_error("cannot remove prior export completion/error marker");
            note("Waiting for main menu and original game assets. Network adapters and Play are disabled in export mode.");
        }
        if(GetTickCount64()-startedAt>120000)throw std::runtime_error("server asset export timed out waiting for loaded assets/builder");
        if(phase!=Phase::Waiting)return;
        Obj fsm=ba::read<Obj>(ba::owner,0x2b0);
        if(!fsm || ba::get<Obj>(fsm,"_currentState")!=ba::read<Obj>(ba::owner,0x2c0) || !ba_catalog::available())return;
        const bool rulesReady=aiProfiles.ready(),botsReady=bot_catalog::ready(),cosmeticsReady=ba_cosmetics::catalogReady();
        if(!rulesReady || !botsReady || !cosmeticsReady)return;
        int mode=mapModes[mapIndex];void* modeArgs[]={&mode};Root config(ba::call(ba::owner,"GetConfigForMode",1,modeArgs));
        if(!config.get() || !ba::get<Obj>(config.get(),"GameDataProvider"))return;
        savedFront=root(front);savedPlayer=root(ba::get<Obj>(front,"_playerGameHandle"));savedName=root(ba::get<Obj>(front,"_currentPlayerName"));
        phase=Phase::Building;note("Calling the next original mode map/config builder; its create request will be exported locally.");
        ba_bootstrap::create(front,ba::owner,mode);
    }catch(const std::exception& error){failed(error.what());}
}
}
