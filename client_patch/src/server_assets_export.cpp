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
static void consume(Obj gameData,Obj encoded) {
    if(phase!=Phase::Building || outputLock==INVALID_HANDLE_VALUE)throw std::runtime_error("unexpected export builder callback");
    Root encodedArray(ba::call(encoded,"ToByteArray"));Bytes compressed=arrayBytes(encodedArray.get(),2*1024*1024);
    void* args[]={gameData};Root rawArray(ba::invoke(ba::find_class("Google.Protobuf","MessageExtensions"),nullptr,"ToByteArray",1,args));
    Bytes raw=arrayBytes(rawArray.get(),16*1024*1024);
    ba_catalog::exportFile(path(L"unit-catalog.json").c_str());
    Bytes catalog=readFile(path(L"unit-catalog.json"));
    atomicWrite(path(L"map-1v1.pb.gz"),compressed.data(),compressed.size());
    std::string manifest="{\"schema\":1,\"asset_format\":1,\"complete\":true,\"build\":37822,\"pid\":"+std::to_string(GetCurrentProcessId())+
        ",\"source\":\"loaded original normal 1v1 GameData builder and runtime unit tables\","
        "\"original_gameassembly_sha256\":\"e59d08c01479b27404778048d7e13546dbf3771f6b3912744c7c2bdf80c4e758\","
        "\"simulation_sha256\":\"107bb83dc416a16492277392c50104660e34c48911345ae2e0d5afe3929a07fb\","
        "\"files\":{\"map-1v1.pb.gz\":{\"bytes\":"+std::to_string(compressed.size())+",\"sha256\":\""+hash(compressed)+
        "\"},\"unit-catalog.json\":{\"bytes\":"+std::to_string(catalog.size())+",\"sha256\":\""+hash(catalog)+
        "\"}},\"raw_game_data\":{\"bytes\":"+std::to_string(raw.size())+",\"sha256\":\""+hash(raw)+"\"}}\n";
    restoreIdentity();
    atomicWrite(path(L"export.json"),reinterpret_cast<const unsigned char*>(manifest.data()),manifest.size());
    phase=Phase::Complete;releaseLock();
    note("COMPLETE: map-1v1.pb.gz, unit-catalog.json and export.json written; no match started. You may close the game.");
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
        int mode=1;void* modeArgs[]={&mode};Root config(ba::call(ba::owner,"GetConfigForMode",1,modeArgs));
        if(!config.get() || !ba::get<Obj>(config.get(),"GameDataProvider"))return;
        savedFront=root(front);savedPlayer=root(ba::get<Obj>(front,"_playerGameHandle"));savedName=root(ba::get<Obj>(front,"_currentPlayerName"));
        phase=Phase::Building;note("Calling the original mode1 map/config builder; its create request will be exported locally.");
        ba_bootstrap::create(front,ba::owner,1);
    }catch(const std::exception& error){failed(error.what());}
}
}
