#pragma once
// Included inside ba_telemetry_audit. Explicit guarded calls on retained genuine
// owners only;never invoke original acquisition,preparation or archive helpers.
static void activationProbe() noexcept {
    static const bool enabled=ba::flag(L"-telemetry-activation-probe");
    static bool attempted=false;if(!enabled || attempted)return;attempted=true;
    try {
        auto require=[](bool value,const char* why){if(!value)throw std::runtime_error(why);};
        require(requested() && checked && !disabled && completeRecipe && auditThread==GetCurrentThreadId() &&
            ba::flag(L"-native-quit-smoke") && ba_native_settings::session &&
            ba_native_settings::session->profile().compare(0,12,"nativestest_")==0,
            "activation probe requires explicit owned complete-recipe diagnostic");
        for(const auto& item:std::vector<std::tuple<size_t,size_t,const char*>>{
            {0xc3b990,396,"33dd9a0f48556d7ee39c46d924894c76123eb8f20b6fc9321f91c165eb7f43f0"},
            {0xc478c0,2936,"a079881cee3edae4056387d294994e7390b085c8f9cf6da6e768fa343ab7fc0d"},
            {0xc34270,348,"73e6e66cc10e14c650098bdd6d42cb59b6a62ad657a5745996c66b3b41198e22"}}) {
            Bytes bytes(std::get<1>(item));
            require(copy(unity+std::get<0>(item),bytes.data(),bytes.size()) && digest(bytes)==std::get<2>(item),
                "activation probe complete patched body differs");
        }
        struct Main {uintptr_t pointer=0,table=0,worker=0;uint32_t state=0,init=0,archive=0;unsigned char busy=0;};
        auto capture=[&](Main& s) {
            uintptr_t again=0;
            return read(unity,0x1d0eb28,s.pointer) && s.pointer && read(s.pointer,0,s.table) && s.table==unity+0x1a2c538 &&
                read(s.pointer,8,s.state) && read(s.pointer,0xc4,s.busy) && read(s.pointer,0xe10,s.init) &&
                read(s.pointer,0x480,s.archive) && read(s.pointer,0x4e0,s.worker) &&
                read(unity,0x1d0eb28,again) && again==s.pointer;
        };
        auto same=[](const Main& a,const Main& b) {
            return a.pointer==b.pointer && a.table==b.table && a.worker==b.worker && a.state==b.state &&
                a.init==b.init && a.archive==b.archive && a.busy==b.busy;
        };
        Main before,after;require(capture(before) && !before.state && !before.init && !before.archive && !before.worker && !before.busy,
            "activation probe requires genuine inactive Main constructor state");
        uintptr_t session=0,table=0,again=0;unsigned char tag=0,remaining=0;uint32_t allocator=0;
        require(read(unity,0x1d0eb40,session) && session && read(session,0,table) && table>=unity && table<unity+imageSize &&
            read(session,0x68,tag) && tag==1 && read(session,0x60,remaining) && remaining==24 && read(session,0x6c,allocator) &&
            read(unity,0x1d0eb40,again) && again==session,"activation probe requires genuine empty retained Session metadata");
        ba::log("TELEMETRY ACTIVATION begin: version=1 thread=%lu retainedMain=1 retainedSession=1 originalInitializerInvoked=0",GetCurrentThreadId());
        const auto transition=reinterpret_cast<unsigned(*)(void*,int)>(unity+0xc3b990);
        require(transition(reinterpret_cast<void*>(before.pointer),1)==0 && capture(after) && same(before,after),
            "initialization decline changed sampled state or failed to clear reentrancy");
        auto* busy=reinterpret_cast<unsigned char*>(before.pointer+0xc4);
        struct Restore {unsigned char* field;unsigned char value;~Restore(){*field=value;}} restore{busy,before.busy};
        *busy=1;
        Main busyBefore,busyAfter;require(capture(busyBefore),"busy sample failed");
        require(transition(reinterpret_cast<void*>(before.pointer),1)==0 && capture(busyAfter) && same(busyBefore,busyAfter),
            "original busy rejection changed sampled state");
        *busy=before.busy;
        require(transition(reinterpret_cast<void*>(before.pointer),0)==0 && capture(after) && same(before,after),
            "unmodified same-state decline changed sampled state");
        const auto prepare=reinterpret_cast<bool(*)(void*,const void*,const void*,unsigned)>(unity+0xc34270);
        require(!prepare(reinterpret_cast<void*>(before.pointer),reinterpret_cast<const void*>(uintptr_t(1)),
            reinterpret_cast<const void*>(uintptr_t(1)),0xffffffffu) && capture(after) && same(before,after),
            "configuration preparation did not decline before borrowed input access");
        const auto result=reinterpret_cast<const void*(*)(void*)>(unity+0xc478c0)(reinterpret_cast<void*>(session));
        unsigned char tagAfter=0,remainingAfter=0;uint32_t allocatorAfter=0;uintptr_t tableAfter=0;
        require(result==reinterpret_cast<void*>(session+0x48) && read(unity,0x1d0eb40,again) && again==session &&
            read(session,0,tableAfter) && tableAfter==table && read(session,0x68,tagAfter) && tagAfter==tag &&
            read(session,0x60,remainingAfter) && remainingAfter==remaining && read(session,0x6c,allocatorAfter) && allocatorAfter==allocator &&
            capture(after) && same(before,after),"retained-value getter result or sampled metadata changed");
        ba::log("TELEMETRY ACTIVATION probe passed: version=1 thread=%lu transitionCalls=3 initializationDeclined=1 busyRejected=1 sameStateDeclined=1 configPreparationCalls=1 configDeclined=1 borrowedUnreadable=2 mainStable=1 busyRestored=1 cloudGetterCalls=1 retainedStringAddress=1 emptySsoMetadataUnchanged=1 identityPayloadRead=0 originalAcquisitionInvoked=0 originalInitializerInvoked=0 wholeRunIsolation=0",GetCurrentThreadId());
    }catch(const std::exception& error) {ba::log("TELEMETRY ACTIVATION probe failed: %s; no success claim",error.what());}
    catch(...) {ba::log("TELEMETRY ACTIVATION probe failed: unknown; no success claim");}
}
