#pragma once
// Included inside cache_probe, after PathScope. Only fresh owned diagnostic
// directories may reach the original constructor, whose expiry pass can delete.
static void emptyDirectory(const std::wstring& path) {
    WIN32_FIND_DATAW data{};HANDLE search=FindFirstFileW((path+L"\\*").c_str(),&data);
    if(search==INVALID_HANDLE_VALUE){require(GetLastError()==ERROR_FILE_NOT_FOUND,"owned queue directory enumeration failed");return;}
    bool empty=true,complete=false;
    do {
        if(wcscmp(data.cFileName,L".") && wcscmp(data.cFileName,L"..")){empty=false;break;}
        if(!FindNextFileW(search,&data)){complete=GetLastError()==ERROR_NO_MORE_FILES;break;}
    }while(true);
    const bool closed=FindClose(search)!=0;
    require(empty && complete && closed,"cache constructor requires verified EMPTY owned queues");
}
class StaticConfiguration {
    Obj field=nullptr,expected=nullptr;
    void (*getValue)(Obj,void*)=nullptr;
    void (*setValue)(Obj,void*)=nullptr;
    bool active=false;
public:
    StaticConfiguration(Obj type,Obj config):expected(config) {
        getValue=ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value");
        setValue=ba::api<void(*)(Obj,void*)>("il2cpp_field_static_set_value");
        field=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(type,"_configuration");
        require(field && (ba::api<uint32_t(*)(Obj)>("il2cpp_field_get_flags")(field)&0x10),"cache configuration static field absent");
        const auto fieldType=ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(field);
        require(fieldType && ba::api<int(*)(Obj)>("il2cpp_type_get_type")(fieldType)==18,"cache static configuration reference ABI mismatch");
        Obj previous=nullptr;
        getValue(field,&previous);
        require(previous==nullptr,"cache diagnostic refuses an existing SDK configuration owner");active=true;
    }
    bool selected() const {
        Obj current=nullptr;getValue(field,&current);
        return current==expected;
    }
    bool restore() noexcept {
        if(!active)return false;active=false;
        Obj current=nullptr;getValue(field,&current);
        if(current && current!=expected)return false;
        // Supported original CLASS branch stores the argument DIRECTLY. Passing
        // &anObjSlot here would retain a stack pointer as a managed object!
        setValue(field,nullptr);
        getValue(field,&current);
        return current==nullptr;
    }
    ~StaticConfiguration(){if(active)restore();}
    StaticConfiguration(const StaticConfiguration&)=delete;
    StaticConfiguration& operator=(const StaticConfiguration&)=delete;
};
class QueueFixture {
    std::wstring path;
    std::string payload;
    BY_HANDLE_FILE_INFORMATION created{};
public:
    QueueFixture(const std::wstring& target,const char* authored):path(target),payload(authored) {
        ba_cosmetics_state::Handle file(CreateFileW(path.c_str(),GENERIC_READ|GENERIC_WRITE,
            FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,CREATE_NEW,
            FILE_ATTRIBUTE_NORMAL|FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
        ba_native_settings::ordinary(file.value);
        DWORD written=0;
        require(WriteFile(file.value,payload.data(),static_cast<DWORD>(payload.size()),&written,nullptr) &&
            written==payload.size() && FlushFileBuffers(file.value) && GetFileInformationByHandle(file.value,&created),
            "authored queue seed write/flush/identity failed");
    }
    void verify() const {
        // Normal read semantics: no write/delete-sharing restriction may mask an
        // SDK mutation. Compare actual identity/content after the original calls.
        ba_cosmetics_state::Handle file(CreateFileW(path.c_str(),GENERIC_READ,
            FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL|FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
        ba_native_settings::ordinary(file.value);BY_HANDLE_FILE_INFORMATION current{};
        require(GetFileInformationByHandle(file.value,&current) &&
            current.dwVolumeSerialNumber==created.dwVolumeSerialNumber && current.nFileIndexHigh==created.nFileIndexHigh &&
            current.nFileIndexLow==created.nFileIndexLow && current.nFileSizeHigh==0 && current.nFileSizeLow==payload.size() &&
            CompareFileTime(&current.ftCreationTime,&created.ftCreationTime)==0,"authored queue file identity/size changed");
        Bytes actual(payload.size()+1);DWORD count=0;
        require(ReadFile(file.value,actual.data(),static_cast<DWORD>(actual.size()),&count,nullptr) &&
            count==payload.size() && !memcmp(actual.data(),payload.data(),payload.size()),"authored queue file bytes changed");
    }
};
static std::unique_ptr<DiskInputs> disk(Obj config,const std::wstring& selected,const DiskCallback& callback) {
    #include "telemetry_cache_disk_signatures.hpp"
    const auto folder=selected+L"\\queue121";
    require(CreateDirectoryW(folder.c_str(),nullptr)!=0,"queue diagnostic requires a NEW disposable root");
    ba_cosmetics_state::Handle folderHandle(ba_cosmetics_state::directory(folder));
    ba_native_settings::exactDirectory(folderHandle.value,folder);
    const auto cachePath=folder+L"\\Bugsnag",eventPath=cachePath+L"\\Events",sessionPath=cachePath+L"\\Sessions";
    ba_cosmetics_state::Handle cacheHandle(ba_cosmetics_state::directory(cachePath));
    ba_cosmetics_state::Handle eventHandle(ba_cosmetics_state::directory(eventPath));
    ba_cosmetics_state::Handle sessionHandle(ba_cosmetics_state::directory(sessionPath));
    ba_native_settings::exactDirectory(cacheHandle.value,cachePath);
    ba_native_settings::exactDirectory(eventHandle.value,eventPath);
    ba_native_settings::exactDirectory(sessionHandle.value,sessionPath);
    emptyDirectory(eventPath);emptyDirectory(sessionPath);
    auto result=std::make_unique<DiskInputs>();
    {
        PathScope scope(folder);
        ba_local::Root events(ba::native<Obj(*)(void*)>(0x8365f0)(nullptr));
        ba_local::Root sessions(ba::native<Obj(*)(void*)>(0x836580)(nullptr));
        require(text(events.get())==folder+L"/Bugsnag/Events" && text(sessions.get())==folder+L"/Bugsnag/Sessions",
            "original queue getters did not select the fresh owned root");
        const auto type=ba::find_class("BugsnagUnity","CacheManager");
        ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(type);
        const auto deviceField=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(type,"_deviceIdFile");
        require(deviceField!=nullptr,"cache filename static field absent");Obj previousDevice=nullptr;
        ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(deviceField,&previousDevice);
        ba_local::Root deviceFilename(previousDevice);
        StaticConfiguration configuration(type,config);
        ba_local::Root manager(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(type));
        void* constructorArgs[]={config};invoke(method(type,".ctor",1,0x836660),manager.get(),constructorArgs);
        require(configuration.selected(),"cache constructor did not retain the supplied genuine configuration");
        emptyDirectory(eventPath);emptyDirectory(sessionPath);
        QueueFixture event(eventPath+L"\\authored-event-120.event",eventFixture);
        QueueFixture session(sessionPath+L"\\authored-session-120.session",sessionFixture);
        event.verify();session.verify();
        ba_local::Root eventFiles(invoke(method(type,"GetCachedEventFiles",0,0x836730),manager.get(),nullptr));
        ba_local::Root sessionFiles(invoke(method(type,"GetCachedSessionFiles",0,0x8367b0),manager.get(),nullptr));
        require(eventFiles.get() && sessionFiles.get() && ba::read<uintptr_t>(eventFiles.get(),0x18)==1 &&
            ba::read<uintptr_t>(sessionFiles.get(),0x18)==1,"original queue enumerators did not find exactly the two seeds");
        auto eventName=text(ba::read<Obj>(eventFiles.get(),0x20));
        auto sessionName=text(ba::read<Obj>(sessionFiles.get(),0x20));
        std::replace(eventName.begin(),eventName.end(),L'/',L'\\');
        std::replace(sessionName.begin(),sessionName.end(),L'/',L'\\');
        require(_wcsicmp(eventName.c_str(),(eventPath+L"\\authored-event-120.event").c_str())==0 &&
            _wcsicmp(sessionName.c_str(),(sessionPath+L"\\authored-session-120.session").c_str())==0,
            "original enumerators returned unexpected file paths");
        ba_local::Root eventId(ba::str("authored-event-120")),sessionId(ba::str("authored-session-120"));
        void* eventArgs[]={eventId.get()};void* sessionArgs[]={sessionId.get()};
        ba::log("TELEMETRY CACHEREAD begin: version=1 thread=%lu kind=event",GetCurrentThreadId());
        result->event=std::make_unique<ba_local::Root>(invoke(method(type,"GetCachedEvent",1,0x837d10),manager.get(),eventArgs));
        ba::log("TELEMETRY CACHEREAD end: version=1 thread=%lu kind=event",GetCurrentThreadId());
        ba::log("TELEMETRY CACHEREAD begin: version=1 thread=%lu kind=session",GetCurrentThreadId());
        result->session=std::make_unique<ba_local::Root>(invoke(method(type,"GetCachedSession",1,0x837db0),manager.get(),sessionArgs));
        ba::log("TELEMETRY CACHEREAD end: version=1 thread=%lu kind=session",GetCurrentThreadId());
        require(ba_native_settings::utf8(text(result->event->get()))==eventFixture &&
            ba_native_settings::utf8(text(result->session->get()))==sessionFixture,"original cached reader bytes differ from authored seeds");
        ba_local::Root missing(ba::str("missing-authored-report-121"));void* missingArgs[]={missing.get()};
        require(!invoke(method(type,"GetCachedEvent",1,0x837d10),manager.get(),missingArgs) &&
            !invoke(method(type,"GetCachedSession",1,0x837db0),manager.get(),missingArgs),"missing queue IDs did not return null");
        if(callback)callback(result->event->get(),result->session->get(),manager.get());
        event.verify();session.verify();
        require(configuration.selected(),"cache diagnostic changed the selected static configuration");
        Obj afterDevice=nullptr;ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(deviceField,&afterDevice);
        require(afterDevice==deviceFilename.get(),"cache reader changed static device filename metadata");
        require(configuration.restore(),"cache static configuration restore failed");
        require(scope.restore(),"cache reader path override restore failed");
    }
    ba::log("TELEMETRY CACHEREADER probe passed: version=1 thread=%lu instanceCtor=1 emptyBeforeCtor=1 emptyAfterCtor=1 seeds=2 enumerated=2 reads=2 rawBytesMatched=2 missingIdNull=2 fileIdentityBytesUnchanged=2 staticConfigRestored=1 deviceFilenameUnchanged=1 icallRestored=1 wholeRunIsolation=0",
        GetCurrentThreadId());
    return result;
}
