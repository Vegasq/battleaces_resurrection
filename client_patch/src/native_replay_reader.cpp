#pragma once
// Opt-in owned codec readback, never high-level Replay.Load/Play or ordinary UI.
namespace ba_native_replay_reader {
using ba::Obj;using ba_local::Root;using ba_native_settings::require;
static Obj type(const char* ns,const char* name,const char* image=nullptr) {
    Obj result=ba::find_class(ns,name);require(result!=nullptr,"replay reader class missing");
    if(image)require(!strcmp(ba::api<const char*(*)(Obj)>("il2cpp_image_get_name")(
        ba::api<Obj(*)(Obj)>("il2cpp_class_get_image")(result)),image),"replay reader assembly differs");
    return result;
}
static Obj method(Obj klass,const char* name,unsigned count,uintptr_t rva,uint32_t token) {
    void* iterator=nullptr;Obj found=nullptr;
    while(Obj candidate=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(klass,&iterator)) {
        if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(candidate),name) ||
           ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(candidate)!=count ||
           ba::read<Obj>(candidate,0)!=ba::native<Obj>(rva))continue;
        require(!found && ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_token")(candidate)==token,
            "replay reader original overload/token differs");found=candidate;
    }
    require(found!=nullptr,"replay reader exact original method missing");return found;
}
struct ManagedError:std::runtime_error {
    std::string type;
    explicit ManagedError(std::string name):std::runtime_error("replay reader managed invocation failed"),type(std::move(name)){}
};
static Obj invoke(Obj method,Obj receiver,void** args=nullptr,const char* faultCase=nullptr) {
    Obj exception=nullptr;Obj result=ba::api<Obj(*)(Obj,Obj,void**,Obj*)>("il2cpp_runtime_invoke")(method,receiver,args,&exception);
    if(exception) {
        Root failure(exception);char text[2048]={};ba::api<void(*)(Obj,char*,int)>("il2cpp_format_exception")(failure.get(),text,sizeof(text));
        const std::string name=std::string(ba::api<const char*(*)(Obj)>("il2cpp_class_get_namespace")(ba::klass(failure.get())))+"."+
            ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(ba::klass(failure.get()));
        if(faultCase)ba::log("NATIVE REPLAY fault managed exception: case=%s type=%s detail=%s",faultCase,name.c_str(),text);
        else ba::log("NATIVE REPLAY decoder managed exception: %s",text);
        throw ManagedError(name);
    }
    return result; // Original void constructors/ReadRawMessage normally return null.
}
static std::unique_ptr<Root> allocate(Obj klass) {
    ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(klass);
    auto result=std::make_unique<Root>(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(klass));
    require(result->get()!=nullptr,"replay reader allocation failed");return result;
}
static Obj get(Obj receiver,const char* name,uintptr_t rva,uint32_t token) {
    require(receiver!=nullptr,"replay reader getter owner missing");
    return invoke(method(ba::klass(receiver),name,0,rva,token),receiver);
}
static int count(Obj collection) {
    require(collection && !strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_namespace")(ba::klass(collection)),"Google.Protobuf.Collections") &&
        !strncmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(ba::klass(collection)),"RepeatedField",13),
        "replay reader expected original closed repeated field");
    const int result=ba_local::count(collection);require(result>=0 && result<=65536,"replay reader repeated field bound");return result;
}
struct Streams {
    std::unique_ptr<Root> file,deflate,coded;
    bool closed=false;unsigned disposed=0,errors=0;
    void close() noexcept {
        if(closed)return;closed=true;
        for(auto* stream:{&coded,&deflate,&file})if(*stream) {
            try {
                Obj m=stream==&coded?method(type("Google.Protobuf","CodedInputStream","Google.Protobuf.dll"),"Dispose",0,0x312d970,0x0600003a):
                    method(type("System.IO","Stream","mscorlib.dll"),"Dispose",0,0x33c5400,0x060031ef);
                invoke(m,(*stream)->get());++disposed;
            }catch(...){++errors;}
        }
    }
    ~Streams(){close();}
};
struct Find {
    HANDLE handle=INVALID_HANDLE_VALUE;
    ~Find(){if(handle!=INVALID_HANDLE_VALUE)FindClose(handle);}
};
static std::wstring replayFile() {
    require(ba_native_storage::replay!=nullptr,"replay reader destination has not been prepared");
    const auto& directory=ba_native_storage::replay->directory;WIN32_FIND_DATAW data{};Find search;
    search.handle=FindFirstFileW((directory.apiPath()+L"\\*.rep").c_str(),&data);
    require(search.handle!=INVALID_HANDLE_VALUE,"replay reader has no saved replay");
    std::wstring selected;unsigned entries=0;
    do {
        require(++entries<=128 && !(data.dwFileAttributes&(FILE_ATTRIBUTE_DIRECTORY|FILE_ATTRIBUTE_REPARSE_POINT)),
            "replay reader directory entry refused");
        const std::wstring name=data.cFileName;
        if(name.rfind(L"authored-retention-",0)==0)continue;
        require(selected.empty() && name.find_first_of(L"\\/:")==std::wstring::npos,"replay reader requires exactly one native replay");
        selected=name;
    }while(FindNextFileW(search.handle,&data));
    require(GetLastError()==ERROR_NO_MORE_FILES && !selected.empty(),"replay reader enumeration incomplete");
    return selected;
}
struct Result {
    std::string failure,exception,phase="open";
    int frames=0,initial=0,playerBatches=0;
    unsigned disposed=0,cleanupErrors=0;
    bool identity=false,limits=false;
};
static Result decode(const std::wstring& leaf,const char* faultCase=nullptr) {
    require(!leaf.empty() && leaf.find_first_of(L"\\/:")==std::wstring::npos,"replay reader refuses a non-leaf selection");
    const auto extended=ba_native_storage::replay->directory.apiPath()+L"\\"+leaf;
    ba_native_settings::Handle pin(CreateFileW(extended.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,
        FILE_FLAG_OPEN_REPARSE_POINT,nullptr));ba_native_settings::ordinary(pin.value);
    LARGE_INTEGER size{};require(GetFileSizeEx(pin.value,&size) && size.QuadPart>0 && size.QuadPart<=4*1024*1024,
        "replay reader compressed size bound");
    wchar_t finalPath[32768];const DWORD length=GetFinalPathNameByHandleW(pin.value,finalPath,32768,FILE_NAME_NORMALIZED|VOLUME_NAME_DOS);
    require(length && length<32768 && !_wcsicmp(finalPath,extended.c_str()),"replay reader escaped pinned destination");
    const auto fileType=type("System.IO","FileStream","mscorlib.dll"),deflateType=type("System.IO.Compression","DeflateStream","System.dll"),
        codedType=type("Google.Protobuf","CodedInputStream","Google.Protobuf.dll"),messageType=type("GamePb","Replay","RGame.Generated.dll");
    Root path(ba::api<Obj(*)(const wchar_t*,int32_t)>("il2cpp_string_new_utf16")(extended.data(),static_cast<int32_t>(extended.size())));
    Streams streams;Result result;
    try {
        streams.file=allocate(fileType);int open=3,read=1,share=1,buffer=4096,options=0;bool anonymous=false;
        void* fileArgs[]={path.get(),&open,&read,&share,&buffer,&anonymous,&options};
        invoke(method(fileType,".ctor",7,0x3557960,0x060032b6),streams.file->get(),fileArgs);
        Root safe(ba::read<Obj>(streams.file->get(),0x38));require(safe.get()!=nullptr,"replay reader original file handle missing");
        BY_HANDLE_FILE_INFORMATION pinned{},actual{};
        require(GetFileInformationByHandle(pin.value,&pinned) && GetFileInformationByHandle(ba::read<HANDLE>(safe.get(),0x10),&actual) &&
            pinned.dwVolumeSerialNumber==actual.dwVolumeSerialNumber && pinned.nFileIndexHigh==actual.nFileIndexHigh &&
            pinned.nFileIndexLow==actual.nFileIndexLow,"replay reader original stream identity differs");
        result.identity=true;
        streams.deflate=allocate(deflateType);int decompress=0;bool leaveOpen=false,gzip=false;
        void* deflateArgs[]={streams.file->get(),&decompress,&leaveOpen,&gzip};
        invoke(method(deflateType,".ctor",4,0x44f8660,0x06000da0),streams.deflate->get(),deflateArgs);
        int byteLimit=16*1024*1024,recursionLimit=64;void* codedArgs[]={streams.deflate->get(),&byteLimit,&recursionLimit};
        streams.coded=std::make_unique<Root>(invoke(method(codedType,"CreateWithLimits",3,0x312d770,0x0600002e),nullptr,codedArgs));
        require(streams.coded->get()!=nullptr,"replay reader coded stream missing");
        Root bytes(get(streams.coded->get(),"get_SizeLimit",0x887b30,0x06000031)),recursion(get(streams.coded->get(),"get_RecursionLimit",0x865460,0x06000032));
        require(ba_catalog::unbox<int>(bytes.get())==byteLimit && ba_catalog::unbox<int>(recursion.get())==recursionLimit,
            "replay reader original parser limits differ");
        result.limits=true;
        auto message=allocate(messageType);invoke(method(messageType,".ctor",0,0x3a1f130,0x060006eb),message->get());
        result.phase="parse";
        void* messageArgs[]={message->get()};invoke(method(codedType,"ReadRawMessage",1,0x312e860,0x0600005f),streams.coded->get(),messageArgs,faultCase);
        result.phase="validate";
        Root end(get(streams.coded->get(),"get_IsAtEnd",0x312e6a0,0x0600005c));require(ba_catalog::unbox<bool>(end.get()),"replay reader decoded stream not exhausted");
        Root game(get(message->get(),"get_GameData",0x70f380,0x060006ee)),batches(get(message->get(),"get_InputActions",0x6ea1f0,0x060006f0));
        require(game.get() && ba::klass(game.get())==type("GamePb","GameData","RGame.Generated.dll"),"replay reader GameData missing");
        Root config(get(game.get(),"get_GameConfig",0x70f380,0x060006d7)),setup(get(game.get(),"get_InitialActions",0x6ea1f0,0x060006d9));
        require(config.get() && ba::klass(config.get())==type("GamePb","GameConfig","RGame.Generated.dll"),"replay reader GameConfig missing");
        Root version(get(config.get(),"get_VersionBuild",0x845f70,0x06000308));
        require(version.get() && ba::klass(version.get())==type("CommonPb","VersionBuild"),"replay reader build model missing");
        Root build(get(version.get(),"get_Build",0x70f380,0x06002e4d));require(ba_native_settings::wide(build.get())==L"37822","replay reader build differs");
        result.frames=count(batches.get());result.initial=count(setup.get());require(result.frames>0 && result.initial>0,"replay reader empty recording/setup");
        for(int index=0;index<result.frames;++index) {
            void* args[]={&index};Root batch(ba::call(batches.get(),"get_Item",1,args));
            require(batch.get() && ba::klass(batch.get())==type("GamePb","InputActions","RGame.Generated.dll"),"replay reader batch class differs");
            Root frame(get(batch.get(),"get_GameFrame",0x6f9db0,0x0600097c));
            require(ba_catalog::unbox<int>(frame.get())==index,"replay reader recorded frames are not contiguous");
            Root players(get(batch.get(),"get_PlayerInputActions",0x728d00,0x06000985));if(count(players.get()))++result.playerBatches;
        }
        require(result.playerBatches>0,"replay reader lacks recorded player batches");
    }catch(const ManagedError& error){result.failure=error.what();result.exception=error.type;}
    catch(const std::exception& error){result.failure=error.what();}
    streams.close();result.disposed=streams.disposed;result.cleanupErrors=streams.errors;return result;
}
static void faults() {
    struct Case {const char* name;const wchar_t* leaf;const char* exception;};
    for(const auto& test:std::initializer_list<Case>{
        {"invalid-deflate",L"authored-codec-invalid-deflate.case","System.IO.IOException"},
        {"invalid-wire",L"authored-codec-invalid-wire.case","Google.Protobuf.InvalidProtocolBufferException"},
        {"truncated-field",L"authored-codec-truncated-field.case","Google.Protobuf.InvalidProtocolBufferException"},
        {"recursion-limit",L"authored-codec-recursion-limit.case","Google.Protobuf.InvalidProtocolBufferException"},
        {"size-limit",L"authored-codec-size-limit.case","Google.Protobuf.InvalidProtocolBufferException"},
        {"empty-recording",L"authored-codec-empty-recording.case",""}}) {
        const auto result=decode(test.leaf,test.name);
        require(result.identity && result.limits && result.disposed==3 && result.cleanupErrors==0 && !result.failure.empty(),
            "replay fault control failed admission/rejection/cleanup");
        require(result.exception==test.exception && (result.exception.empty()?
            result.phase=="validate" && result.failure=="replay reader GameData missing":result.phase=="parse"),
            "replay fault control rejected at an unexpected phase/type");
        // decode's pin is gone; exclusive read admission witnesses that the
        // original managed streams also released their file handles.
        const auto path=ba_native_storage::replay->directory.apiPath()+L"\\"+test.leaf;
        ba_native_settings::Handle exclusive(CreateFileW(path.c_str(),GENERIC_READ,0,nullptr,OPEN_EXISTING,FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
        ba_native_settings::ordinary(exclusive.value);
        ba::log("NATIVE REPLAY fault rejected: case=%s phase=%s exception=%s streamsDisposed=3 cleanupErrors=0 fileIdentityPinned=1 limitsVerified=1 exclusiveReopen=1 playbackCalls=0",
            test.name,result.phase.c_str(),result.exception.empty()?"none":result.exception.c_str());
    }
    ba::log("NATIVE REPLAY fault suite passed: cases=6 originalCodec=1 helperLimits=16777216,64 playbackCalls=0 BA_RESURRECTION_NATIVE_REPLAY_FAULTS_V1");
}
static void probe() {
    if(!ba::flag(L"-native-replay-readback-smoke"))return;
    require(ba::flag(L"-native-quit-after-practice") && ba_native_settings::session &&
        ba_native_settings::session->profile().rfind("nativestest_",0)==0 &&
        ba_practice::completed==1 && !ba_practice::active(),"replay readback requires one completed owned diagnostic match");
    const auto leaf=replayFile(),canonical=ba_native_storage::replay->directory.path()+L"\\"+leaf;const auto result=decode(leaf);
    require(result.failure.empty(),result.failure.c_str());require(result.cleanupErrors==0 && result.disposed==3,"replay reader stream cleanup failed");
    ba::log("NATIVE REPLAY codec readback passed: frames=%d first=0 last=%d initialActions=%d playerBatches=%d build=37822 streamsDisposed=3 fileIdentityPinned=1 canonicalPathCharacters=%zu sizeLimit=16777216 recursionLimit=64 playbackCalls=0 BA_RESURRECTION_NATIVE_REPLAY_READER_V1",
        result.frames,result.frames-1,result.initial,result.playerBatches,canonical.size());
    if(ba::flag(L"-native-replay-faults-smoke"))faults();
}
}
