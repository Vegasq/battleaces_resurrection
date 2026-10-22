#pragma once
// Included inside ba_telemetry_audit. Explicit owned diagnostics only. These
// original path getters do NOT enumerate/read reports. The temporary icall
// override routes only this game thread; other callers retain their original
// implementation. This is NOT whole-process or startup cache isolation.
namespace cache_probe {
using ba::Obj;
static Obj rootValue=nullptr;
static std::atomic<DWORD> rootThread{0};
static Obj (*originalPath)()=nullptr;
static Obj ownedPath() {
    if(GetCurrentThreadId()==rootThread.load(std::memory_order_acquire))return rootValue;
    return originalPath();
}
static void require(bool value,const char* why){if(!value)throw std::runtime_error(why);}
static void original(size_t rva,size_t size,const char* expected) {
    Bytes bytes(size);
    require(copy(reinterpret_cast<uintptr_t>(ba::module)+rva,bytes.data(),bytes.size()) && digest(bytes)==expected,
        "cache probe original method bytes mismatch");
}
static std::wstring text(Obj value) {return ba_native_settings::wide(value);}
static Obj method(Obj type,const char* name,int count,size_t rva) {
    void* iterator=nullptr;Obj found=nullptr;
    while(auto item=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(type,&iterator)) {
        if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(item),name) ||
            ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(item)!=static_cast<uint32_t>(count) ||
            ba::read<uintptr_t>(item,0)!=reinterpret_cast<uintptr_t>(ba::module)+rva)continue;
        require(found==nullptr,"cache probe ambiguous method");found=item;
    }
    require(found!=nullptr,"cache probe exact original method absent");return found;
}
static Obj invoke(Obj entry,Obj receiver,void** arguments) {
    Obj exception=nullptr;
    Obj value=ba::api<Obj(*)(Obj,Obj,void**,Obj*)>("il2cpp_runtime_invoke")(entry,receiver,arguments,&exception);
    require(exception==nullptr,"cache probe original constructor/parser raised a managed exception");return value;
}
static bool rejects(Obj type,Obj entry,void** arguments) {
    ba_local::Root receiver(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(type));
    Obj exception=nullptr;
    ba::api<Obj(*)(Obj,Obj,void**,Obj*)>("il2cpp_runtime_invoke")(entry,receiver.get(),arguments,&exception);
    return exception && ba::klass(exception)==ba::find_class("System.Collections.Generic","KeyNotFoundException");
}
static int count(Obj value) {
    require(value!=nullptr,"cache probe collection missing");
    ba_local::Root boxed(ba::call(value,"get_Count"));
    const auto data=ba::api<void*(*)(Obj)>("il2cpp_object_unbox")(boxed.get());
    require(data!=nullptr,"cache probe collection count missing");return *static_cast<int*>(data);
}
static Obj item(Obj value,const char* key) {
    ba_local::Root name(ba::str(key));void* arguments[]={name.get()};
    return ba::call(value,"get_Item",1,arguments);
}
static void headers(Obj report,const std::wstring& version) {
    ba_local::Root values(ba::get<Obj>(report,"<Headers>k__BackingField"));
    require(values.get() && ba::read<uintptr_t>(values.get(),0x18)==2,"cache request header array differs");
    require(text(ba::read<Obj>(values.get(),0x20))==L"Bugsnag-Api-Key" &&
        text(ba::read<Obj>(values.get(),0x28))==L"00000000000000000000000000000120" &&
        text(ba::read<Obj>(values.get(),0x30))==L"Bugsnag-Payload-Version" &&
        text(ba::read<Obj>(values.get(),0x38))==version,"cache request header values differ");
}
static constexpr const char* eventFixture=R"({"id":"authored-event-120","apiKey":"00000000000000000000000000000120","notifier":{"name":"Resurrection Diagnostic","version":"120","url":"http://127.0.0.1/"},"event":{"unhandled":false,"severity":"info","severityReason":{"type":"handledException"},"metaData":{},"app":{},"device":{},"exceptions":[{"errorClass":"AuthoredCacheFixtureException","message":"Synthetic privacy cache fixture 120","type":"csharp","stacktrace":[]}]}})";
static constexpr const char* sessionFixture=R"({"id":"authored-session-120","notifier":{"name":"Resurrection Diagnostic","version":"120","url":"http://127.0.0.1/"},"app":{},"device":{},"sessions":[{"id":"00000000-0000-0000-0000-000000000120","startedAt":"2026-01-01T00:00:00Z","user":{"id":"authored-cache-fixture-120","name":"Synthetic Fixture"}}]})";
struct DiskInputs {std::unique_ptr<ba_local::Root> event,session;};
using DiskCallback=std::function<void(Obj,Obj,Obj)>;
static std::unique_ptr<DiskInputs> disk(Obj,const std::wstring&,const DiskCallback& callback={});
#include "telemetry_cache_delivery_probe.cpp"
static void typed(const std::wstring& selected,bool fromDisk,bool delivery) {
    // Full supported-build original-body hashes, including nested constructors.
    // Raw binaries/disassembly are NOT embedded in this helper or repository.
    #include "telemetry_cache_signatures.hpp"
    const auto configType=ba::find_class("BugsnagUnity","Configuration");
    const auto endpointType=ba::find_class("BugsnagUnity","EndpointConfiguration");
    const auto jsonType=ba::find_class("BugsnagUnity","SimpleJson");
    const auto objectType=ba::find_class("BugsnagUnity","JsonObject");
    const auto reportType=ba::find_class("BugsnagUnity.Payload","Report");
    const auto sessionType=ba::find_class("BugsnagUnity.Payload","SessionReport");
    ba_local::Root key(ba::str("00000000000000000000000000000120"));
    ba_local::Root config(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(configType));
    void* configArgs[]={key.get()};invoke(method(configType,".ctor",1,0x819760),config.get(),configArgs);
    ba_local::Root notify(ba::str("http://127.0.0.1:9/notify")),sessionUrl(ba::str("http://127.0.0.1:9/session"));
    ba_local::Root endpoints(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(endpointType));
    void* endpointArgs[]={notify.get(),sessionUrl.get()};
    invoke(method(endpointType,".ctor",2,0x8227b0),endpoints.get(),endpointArgs);
    ba::set<Obj>(config.get(),"Endpoints",endpoints.get());
    const auto deserialize=method(jsonType,"DeserializeObject",1,0x8299e0);
    const auto dictionary=method(objectType,"GetDictionary",0,0x827c00);
    const auto reportCtor=method(reportType,".ctor",2,0x84b090);
    const auto sessionCtor=method(sessionType,".ctor",2,0x84d2f0);
    auto parse=[&](Obj literal) {
        void* arguments[]={literal};
        ba_local::Root parsed(invoke(deserialize,nullptr,arguments));
        require(parsed.get() && ba::klass(parsed.get())==objectType,"cache JSON did not deserialize to genuine JsonObject");
        return invoke(dictionary,parsed.get(),nullptr);
    };
    auto reconstruct=[&](Obj eventSource,Obj sessionSource,Obj manager) {
    ba_local::Root eventData(parse(eventSource));
    ba_local::Root sessionData(parse(sessionSource));
    ba_local::Root report(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(reportType));
    ba_local::Root session(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(sessionType));
    void* reportArgs[]={config.get(),eventData.get()};invoke(reportCtor,report.get(),reportArgs);
    void* sessionArgs[]={config.get(),sessionData.get()};invoke(sessionCtor,session.get(),sessionArgs);
    require(text(ba::get<Obj>(report.get(),"<Id>k__BackingField"))==L"authored-event-120" &&
        text(ba::get<Obj>(session.get(),"<Id>k__BackingField"))==L"authored-session-120","cache reconstructed report IDs differ");
    require(ba::get<Obj>(report.get(),"<Endpoint>k__BackingField")==ba::get<Obj>(endpoints.get(),"Notify") &&
        ba::get<Obj>(session.get(),"<Endpoint>k__BackingField")==ba::get<Obj>(endpoints.get(),"Session"),"cache report endpoints differ");
    headers(report.get(),L"4.0");headers(session.get(),L"1.0");
    ba_local::Root event(ba::get<Obj>(report.get(),"Event"));
    require(event.get() && text(ba::get<Obj>(event.get(),"<ApiKey>k__BackingField"))==text(key.get()) &&
        ba::get<Obj>(event.get(),"<_metadata>k__BackingField") && ba::get<Obj>(event.get(),"_appWithState") &&
        ba::get<Obj>(event.get(),"_deviceWithState") && ba::get<Obj>(event.get(),"_user") &&
        !ba::get<Obj>(event.get(),"<Session>k__BackingField"),"cache Event owner/metadata mismatch");
    ba_local::Root errors(ba::get<Obj>(event.get(),"_errors"));
    require(count(errors.get())==1,"authored cached exception was not reconstructed");
    int index=0;void* indexArgs[]={&index};ba_local::Root error(ba::call(errors.get(),"get_Item",1,indexArgs));
    require(text(item(error.get(),"errorClass"))==L"AuthoredCacheFixtureException" &&
        text(item(error.get(),"message"))==L"Synthetic privacy cache fixture 120" &&
        text(item(error.get(),"type"))==L"csharp","authored exception fields not retained");
    ba_local::Root sessions(item(session.get(),"sessions"));
    require(count(sessions.get())==1,"authored cached session record not retained");
    ba_local::Root recordJson(ba::call(sessions.get(),"get_Item",1,indexArgs));
    require(recordJson.get() && ba::klass(recordJson.get())==objectType,"authored session record is not JsonObject");
    // JsonObject also has an integer indexer. Reuse its reviewed dictionary
    // bridge before literal-key reads; name/arity lookup alone is ambiguous.
    ba_local::Root record(invoke(dictionary,recordJson.get(),nullptr));
    require(text(item(record.get(),"id"))==L"00000000-0000-0000-0000-000000000120" &&
        text(item(record.get(),"startedAt"))==L"2026-01-01T00:00:00Z","authored session fields not retained");
    ba_local::Root missingIdSource(ba::str(R"({"notifier":{},"app":{},"device":{},"sessions":[]})"));
    ba_local::Root missingId(parse(missingIdSource.get()));
    void* badSessionArgs[]={config.get(),missingId.get()};
    ba_local::Root missingKeySource(ba::str(R"({"id":"invalid-authored-event","notifier":{},"event":{}})"));
    ba_local::Root missingKey(parse(missingKeySource.get()));
    void* badReportArgs[]={config.get(),missingKey.get()};
    require(rejects(sessionType,sessionCtor,badSessionArgs) && rejects(reportType,reportCtor,badReportArgs),
        "original cached constructors accepted missing required keys");
    if(fromDisk)
        ba::log("TELEMETRY CACHETYPE probe passed: version=%d thread=%lu parsed=4 constructed=2 errors=1 sessions=1 authoredFieldsRetained=1 missingKeyRejected=2 cacheManagerConstructed=1 reportDelivered=0 diskQueueRead=1 fromDisk=2",
            delivery?3:2,GetCurrentThreadId());
    else
        ba::log("TELEMETRY CACHETYPE probe passed: version=1 thread=%lu parsed=4 constructed=2 errors=1 sessions=1 authoredFieldsRetained=1 missingKeyRejected=2 cacheManagerConstructed=0 reportDelivered=0 diskQueueRead=0",
            GetCurrentThreadId());
    if(delivery)guardedDelivery(config.get(),manager,report.get(),session.get(),selected);
    };
    if(delivery) {
        // Keep the genuine cache owner, its configuration and thread-local path
        // selected throughout reconstruction/guard calls. Never reconstruct the
        // CacheManager after seeds: its original ctor includes expiry/deletion.
        disk(config.get(),selected,reconstruct);
    }else if(fromDisk) {
        auto inputs=disk(config.get(),selected);
        reconstruct(inputs->event->get(),inputs->session->get(),nullptr);
    }else {
        ba_local::Root eventSource(ba::str(eventFixture)),sessionSource(ba::str(sessionFixture));
        reconstruct(eventSource.get(),sessionSource.get(),nullptr);
    }
}
class PathScope {
    void* volatile* slot;
    void* previous;
    ba_local::Root root;
    bool active=false;
public:
    explicit PathScope(const std::wstring& selected):
        slot(reinterpret_cast<void* volatile*>(reinterpret_cast<uintptr_t>(ba::module)+0x6e61f00)),
        previous(nullptr),root(ba::api<Obj(*)(const wchar_t*,int32_t)>("il2cpp_string_new_utf16")(
            selected.data(),static_cast<int32_t>(selected.size()))) {
        require(root.get()!=nullptr && !rootValue && !rootThread,"cache path root allocation/ownership");
        auto resolved=ba::api<void*(*)(const char*)>("il2cpp_resolve_icall")("UnityEngine.Application::get_persistentDataPath()");
        require(resolved!=nullptr,"cache path icall resolution failed");
        previous=InterlockedCompareExchangePointer(slot,nullptr,nullptr);
        require(!previous || previous==resolved,"cache path icall already overridden");
        originalPath=reinterpret_cast<Obj(*)()>(resolved);
        rootValue=root.get();rootThread=GetCurrentThreadId();
        if(InterlockedCompareExchangePointer(slot,reinterpret_cast<void*>(&ownedPath),previous)!=previous) {
            rootValue=nullptr;rootThread=0;throw std::runtime_error("cache path icall changed before selection");
        }
        active=true;
    }
    bool restore() noexcept {
        if(!active)return false;
        const bool restored=InterlockedCompareExchangePointer(slot,previous,reinterpret_cast<void*>(&ownedPath))==
            reinterpret_cast<void*>(&ownedPath);
        active=false;rootThread=0;rootValue=nullptr;return restored;
    }
    ~PathScope(){if(active)restore();}
    PathScope(const PathScope&)=delete;
    PathScope& operator=(const PathScope&)=delete;
};
#include "telemetry_cache_disk_probe.cpp"
static void run() noexcept {
    static const bool delivery=ba::flag(L"-telemetry-cache-delivery-probe") || ba::flag(L"-telemetry-cache-failure-probe");
    static const bool fromDisk=ba::flag(L"-telemetry-cache-disk-probe") || delivery;
    static const bool enabled=ba::flag(L"-telemetry-cache-probe") || fromDisk;
    static bool attempted=false;
    if(!enabled || attempted)return;
    attempted=true;
    try {
        require(requested() && checked && !disabled && completeRecipe17 && auditThread==GetCurrentThreadId() &&
            ba::flag(L"-native-quit-smoke") && ba_native_settings::session &&
            ba_native_settings::session->profile().compare(0,12,"nativestest_")==0,
            "cache probe requires complete recipe17 and explicit owned game-thread diagnostic");
        original(0x8364e0,160,"d547e382cad835bbf8f9587fc04aeca3d324dc47e0806e5957ccf7bb06bff003");
        original(0x836580,112,"017aa617c00d2e5a71df7599ee517c08e6c22cccc017e43fed278346ef0bcf43");
        original(0x8365f0,112,"17c801369b2bc5823aec24cd0dad9bb05d7fd45c6ed443a5c8900ea1ac870c06");
        original(0x837e50,192,"233619b5348e22fde5cf16e5cb004877924e453a5574ecb3da7e7edd6795126a");
        original(0x5021d80,80,"c4438c6106e839f61d264d22bd99aeb3f79d14cd697550126151bd93a78b2590");
        original(0x5023d90,208,"906877e9767066a92fd13bd0b923bd04d31b0c1b0ab826640c4c79c57ef0c464");
        const auto& settings=ba_native_settings::session->path();
        const auto slash=settings.find_last_of(L'\\');
        require(slash!=std::wstring::npos,"cache probe profile path missing");
        const auto selected=settings.substr(0,slash)+L"\\qc";
        ba_cosmetics_state::Handle directory(ba_cosmetics_state::directory(selected));
        ba_native_settings::exactDirectory(directory.value,selected);
        {
            PathScope scope(selected);
            ba_local::Root application(ba::native<Obj(*)(void*)>(0x5021d80)(nullptr));
            ba_local::Root cache(ba::native<Obj(*)(void*)>(0x8364e0)(nullptr));
            ba_local::Root events(ba::native<Obj(*)(void*)>(0x8365f0)(nullptr));
            ba_local::Root sessions(ba::native<Obj(*)(void*)>(0x836580)(nullptr));
            require(text(application.get())==selected && text(cache.get())==selected+L"/Bugsnag" &&
                text(events.get())==selected+L"/Bugsnag/Events" && text(sessions.get())==selected+L"/Bugsnag/Sessions",
                "original cache getters did not use selected disposable root");
            require(scope.restore(),"cache path icall restore failed");
        }
        ba::log("TELEMETRY CACHEPATH probe passed: version=1 thread=%lu getters=4 originalBodies=1 scopedOwnedRoot=1 icallRestored=1 reportEnumeration=0 reportPayloadRead=0 wholeRunIsolation=0",
            GetCurrentThreadId());
        typed(selected,fromDisk,delivery);
    }catch(const std::exception& error) {
        ba::log("TELEMETRY CACHE probe failed: %s; no success claim",error.what());
    }catch(...) {ba::log("TELEMETRY CACHE probe failed: unknown error; no success claim");}
}
#include "telemetry_cache_startup_probe.cpp"
}
