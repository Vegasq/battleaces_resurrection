#pragma once
// New explicit diagnostic only: an owned Frida shim selects the SDK-specific
// root for the process lifetime before managed startup. No general Unity path
// substitution and no cache instance ctor/expiry/reader/sender is used here.
static void startupRun() noexcept {
    static const bool enabled=ba::flag(L"-telemetry-cache-startup-probe");
    static bool attempted=false;if(!enabled || attempted)return;attempted=true;
    try {
        require(requested() && checked && !disabled && completeRecipe18 && auditThread==GetCurrentThreadId() &&
            ba::flag(L"-native-quit-smoke") && ba_native_settings::session &&
            ba_native_settings::session->profile().compare(0,12,"nativestest_")==0,
            "startup cache probe requires explicit owned complete-recipe diagnostic");
        require(!ba::flag(L"-telemetry-cache-probe") && !ba::flag(L"-telemetry-cache-disk-probe") &&
            !ba::flag(L"-telemetry-cache-delivery-probe") && !ba::flag(L"-telemetry-cache-failure-probe"),"startup cache fixture cannot run scoped reader/path overrides");
        original(0x836580,112,"017aa617c00d2e5a71df7599ee517c08e6c22cccc017e43fed278346ef0bcf43");
        original(0x8365f0,112,"17c801369b2bc5823aec24cd0dad9bb05d7fd45c6ed443a5c8900ea1ac870c06");
        original(0x837e50,192,"233619b5348e22fde5cf16e5cb004877924e453a5574ecb3da7e7edd6795126a");
        original(0x5021d80,80,"c4438c6106e839f61d264d22bd99aeb3f79d14cd697550126151bd93a78b2590");
        const auto& settings=ba_native_settings::session->path();const auto slash=settings.find_last_of(L'\\');
        require(slash!=std::wstring::npos,"startup cache profile path absent");
        const auto folder=settings.substr(0,slash)+L"\\queue123";
        ba_cosmetics_state::Handle directory(CreateFileW(folder.c_str(),FILE_LIST_DIRECTORY|FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS|FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
        ba_native_settings::exactDirectory(directory.value,folder);
        ba_local::Root applicationBefore(ba::native<Obj(*)(void*)>(0x5021d80)(nullptr));
        const auto type=ba::find_class("BugsnagUnity","CacheManager");
        ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(type);
        // The root entry is deliberately replaced by the externally sealed
        // early shim; its original full-body hash is checked there, not here.
        ba_local::Root root(ba::native<Obj(*)(void*)>(0x8364e0)(nullptr));
        ba_local::Root events(ba::native<Obj(*)(void*)>(0x8365f0)(nullptr));
        ba_local::Root sessions(ba::native<Obj(*)(void*)>(0x836580)(nullptr));
        Obj filename=nullptr,config=nullptr;
        auto field=[&](const char* name) {
            auto value=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(type,name);
            require(value!=nullptr,"startup cache static field missing");return value;
        };
        ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(field("_deviceIdFile"),&filename);
        ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(field("_configuration"),&config);
        ba_local::Root deviceFilename(filename);
        ba_local::Root applicationAfter(ba::native<Obj(*)(void*)>(0x5021d80)(nullptr));
        require(text(root.get())==folder+L"/Bugsnag" && text(events.get())==folder+L"/Bugsnag/Events" &&
            text(sessions.get())==folder+L"/Bugsnag/Sessions" && text(filename)==folder+L"/Bugsnag/deviceId.txt" &&
            !config && text(applicationBefore.get())==text(applicationAfter.get()) &&
            text(applicationBefore.get())!=folder,"startup SDK roots/config/general Unity path mismatch");
        ba::log("TELEMETRY CACHESTARTUP probe passed: version=1 thread=%lu originalGetters=3 sdkRootMatched=1 deviceFilenameMatched=1 staticConfigNull=1 generalUnityPathUnchanged=1 cacheInstanceConstructed=0 reportPayloadRead=0 expiryCalled=0 scopedIcallOverride=0 externalEarlyRootShimRequired=1",
            GetCurrentThreadId());
    }catch(const std::exception& error) {ba::log("TELEMETRY CACHESTARTUP probe failed: %s; no success claim",error.what());}
    catch(...) {ba::log("TELEMETRY CACHESTARTUP probe failed: unknown; no success claim");}
}
