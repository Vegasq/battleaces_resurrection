#pragma once
// Explicit owned fixture only. Both original constructors run with complete
// recipe21 masks;core objects stay genuine while reporting subscriptions/IO
// are bypassed. No fabricated INativeClient or uninitialized Client is used.
struct CacheClientFixture {
    std::unique_ptr<ba_local::Root> nativeRoot,clientRoot;
    struct Hook {Obj field;std::unique_ptr<ba_local::Root> previous;};
    std::vector<Hook> hooks;
    Obj manager=nullptr,payload=nullptr,delivery=nullptr;
    Bytes nativeFields,clientFields;
    explicit CacheClientFixture(Obj config) {
        #include "telemetry_cache_client_signatures.hpp"
        for(const auto& item:std::vector<std::tuple<const char*,const char*,const char*>>{
            {"UnityEngine","Application","lowMemory"},
            {"UnityEngine","Application","s_LogCallbackHandler"},
            {"UnityEngine","Application","s_LogCallbackHandlerThreaded"},
            {"UnityEngine.SceneManagement","SceneManager","sceneLoaded"}}) {
            const auto type=ba::find_class(std::get<0>(item),std::get<1>(item));
            const auto field=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(type,std::get<2>(item));
            require(field && (ba::api<uint32_t(*)(Obj)>("il2cpp_field_get_flags")(field)&0x10),"SDK fixture callback field differs");
            Obj value=nullptr;ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(field,&value);
            hooks.push_back({field,std::make_unique<ba_local::Root>(value)});
        }
        ba::log("TELEMETRY CACHECLIENT begin: version=1 thread=%lu constructorGuards=6 callbackHeads=4",GetCurrentThreadId());
        const auto nativeType=ba::find_class("BugsnagUnity","NativeClient");
        nativeRoot=std::make_unique<ba_local::Root>(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(nativeType));
        void* nativeArgs[]={config};invoke(method(nativeType,".ctor",1,0x834b50),nativeRoot->get(),nativeArgs);
        require(ba::get<Obj>(nativeRoot->get(),"<Configuration>k__BackingField")==config &&
            ba::get<Obj>(nativeRoot->get(),"<Breadcrumbs>k__BackingField") &&
            ba::get<Obj>(nativeRoot->get(),"_fallbackMetadata"),"SDK native original constructor dependencies differ");
        const auto clientType=ba::find_class("BugsnagUnity","Client");
        clientRoot=std::make_unique<ba_local::Root>(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(clientType));
        void* clientArgs[]={nativeRoot->get()};invoke(method(clientType,".ctor",1,0x812690),client(),clientArgs);
        require(ba::get<Obj>(client(),"<NativeClient>k__BackingField")==nativeRoot->get(),"SDK Client lost its genuine native interface");
        unsigned core=0;
        for(const char* name:{"<SessionTracking>k__BackingField","_cachedUser","_storedMetadata","_uniqueCounter","_logTypeCounter",
            "CacheManager","PayloadManager","_delivery","<CallbackLock>k__BackingField","_foregroundStopwatch",
            "_backgroundStopwatch","MainThread","_featureFlags","_requestStartTimes"}) {
            require(ba::get<Obj>(client(),name)!=nullptr,"SDK Client core field was not initialized");++core;
        }
        require(core==14,"SDK Client core field coverage differs");
        manager=ba::get<Obj>(client(),"CacheManager");payload=ba::get<Obj>(client(),"PayloadManager");delivery=ba::get<Obj>(client(),"_delivery");
        require(ba::get<Obj>(payload,"_cacheManager")==manager && ba::get<Obj>(delivery,"_client")==client() &&
            ba::get<Obj>(delivery,"_configuration")==config && ba::get<Obj>(delivery,"_cacheManager")==manager &&
            ba::get<Obj>(delivery,"_payloadManager")==payload && !ba::get<bool>(delivery,"_cacheDeliveryInProcess"),
            "SDK Client delivery/cache graph or idle state differs");
        nativeFields=instanceFields(nativeRoot->get());clientFields=instanceFields(client());unchanged();
        ba::log("TELEMETRY CACHECLIENT probe passed: version=1 thread=%lu nativeCtorCalls=1 clientCtorCalls=1 genuineNativeInterface=1 configurationRetained=1 coreFieldsPresent=14 dependencyGraphMatched=1 idleDelivery=1 globalCallbackHeadsUnchanged=4 reportingDisabled=1 wholeRunIsolation=0",
            GetCurrentThreadId());
    }
    Obj client() const {return clientRoot?clientRoot->get():nullptr;}
    void unchanged() const {
        require(instanceFields(nativeRoot->get())==nativeFields && instanceFields(client())==clientFields,"guarded delivery changed SDK Client/native fields");
        for(const auto& hook:hooks) {
            Obj value=nullptr;ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(hook.field,&value);
            require(value==hook.previous->get(),"SDK Client fixture changed an existing global callback head");
        }
    }
};
