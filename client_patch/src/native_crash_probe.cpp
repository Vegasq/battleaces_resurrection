#pragma once
// Explicit owned diagnostic only. Called synchronously from the original menu
// update thread; never invokes the original uploader, init, flush or teardown.
// A private-profile gate must be published by the external retained owner.
static void nativeCrashProbe() noexcept {
    static const bool enabled=ba::flag(L"-native-crash-probe");
    static bool ready=false,failed=false,fired=false;
    if(!enabled || failed || fired)return;
    try {
        auto require=[](bool value,const char* message){if(!value)throw std::runtime_error(message);};
        require(requested() && checked && !disabled && completeRecipe && !quitAttempted &&
            auditThread==GetCurrentThreadId() && ba_native_settings::session &&
            ba_native_settings::session->profile().rfind("nativestest_crash169_",0)==0,
            "native crash requires owned profile/current recipe/menu thread");
        require(!ba::flag(L"-native-quit-smoke") && !ba::flag(L"-telemetry-cache-probe") &&
            !ba::flag(L"-telemetry-cache-startup-probe") && !ba::flag(L"-webview-runtime-probe"),
            "native crash cannot combine unrelated automation");
        struct State {
            uintptr_t controller=0,manager=0,sentinel=0;
            unsigned long mode=0,savedMode=0,expectedMode=0;
            bool operator==(const State& other)const {
                return controller==other.controller && manager==other.manager && sentinel==other.sentinel &&
                    mode==other.mode && savedMode==other.savedMode && expectedMode==other.expectedMode;
            }
        };
        auto capture=[&]() {
            State state;
            require(read(unity,0x1d0e128,state.controller) && state.controller,"native controller absent");
            ULONG_PTR low=0,high=0;GetCurrentThreadStackLimits(&low,&high);
            require(low && high>low && state.controller>=low && state.controller<=high &&
                high-state.controller>=0xd0,"native controller is not live on this original thread stack");
            require(read(state.controller,8,state.savedMode) && read(state.controller,0x40,state.expectedMode),
                "native error-mode owner unreadable");
            state.mode=GetErrorMode();
            require(state.mode==3 && state.expectedMode==3,"native process reporting policy differs");
            uintptr_t callback=0,again=0;
            require(read(state.controller,0x70,callback) && callback==unity+0x801fb0,"native cursor callback differs");
            // +28 is the REQUEST EVENT, not a pipe. All six IPC handles remain
            // invalid under the child skip; the event guard precedes payload IO.
            for(size_t offset:{0x20u,0x28u,0x30u,0x38u,0x40u,0x48u}) {
                uintptr_t handle=0;
                require(read(state.controller+0x78,offset,handle) && handle==UINTPTR_MAX,"native IPC handle is active");
            }
            unsigned char recursion=1,breakOnCrash=1;
            require(read(unity,0x1d0e941,recursion) && !recursion &&
                read(unity,0x1d0e930,breakOnCrash) && !breakOnCrash,"native crash recursion/dialog policy differs");
            require(read(unity,0x1d08f98,state.manager),"native report owner unreadable");
            if(state.manager) {
                unsigned char registered=1,enabledFlag=1;uint64_t count=1;uint16_t marker=0;
                require(read(state.manager,0,registered) && !registered && read(state.manager,1,enabledFlag) && !enabledFlag &&
                    read(state.manager,0x80,state.sentinel) && state.sentinel && read(state.manager,0x88,count) && !count,
                    "native report manager is active or pending");
                for(size_t offset:{0u,8u,16u}) {
                    uintptr_t link=0;require(read(state.sentinel,offset,link) && link==state.sentinel,"native report tree is not empty");
                }
                require(read(state.sentinel,0x18,marker) && marker==0x101,"native report sentinel differs");
            }
            require(read(unity,0x1d0e128,again) && again==state.controller,"native controller lifetime changed");
            return state;
        };
        const auto state=capture();
        if(!ready) {
            // Full untouched wrapper/dispatcher bodies, not an inferred managed
            // thunk or the inner dispatcher with its additional output pointer.
            for(const auto& item:std::vector<std::tuple<size_t,size_t,const char*>>{
                {0x1484d0,0x42,"774b4236b5e54ff991f74e292fa6e9df1f891ec4b7a867e517da4b3ec3f968e2"},
                {0x6f4b60,0x120,"2c4baef7a720780d41323409745a4a409a976846bb1cfc65007b58cd3ea4c5f4"}}) {
                Bytes bytes(std::get<1>(item));
                require(copy(unity+std::get<0>(item),bytes.data(),bytes.size()) && digest(bytes)==std::get<2>(item),
                    "native registered crash function differs");
            }
            uintptr_t entry=0;
            require(read(unity,0x18cf630,entry) && entry==unity+0x1484d0,"native crash registrar binding differs");
            ready=true;
            ba::log("NATIVE CRASH ready: version=1 thread=%lu recipe=23 mode=%lu savedMode=%lu expectedMode=%lu managerPresent=%u managerDisabledChecked=%u pendingTreeChecked=%u managerAbsent=%u controllerOnCurrentStack=1 ipcInvalid=6 cursorCallbackRva=801fb0 recursion=0 breakOnCrash=0 originalWrapperRva=1484d0 gateRequired=1",
                GetCurrentThreadId(),state.mode,state.savedMode,state.expectedMode,state.manager?1u:0u,
                state.manager?1u:0u,state.manager?1u:0u,state.manager?0u:1u);
        }
        const auto& settings=ba_native_settings::session->path();const auto slash=settings.find_last_of(L'\\');
        require(slash!=std::wstring::npos,"native crash profile directory absent");
        const auto path=settings.substr(0,slash)+L"\\native-crash169.arm";
        ba_cosmetics_state::Handle gate(CreateFileW(path.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,
            OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL|FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
        if(gate.value==INVALID_HANDLE_VALUE) {
            const DWORD error=GetLastError();
            if(error!=ERROR_FILE_NOT_FOUND)
                ba::log("NATIVE CRASH gate open failed: version=1 thread=%lu error=%lu",GetCurrentThreadId(),error);
            require(error==ERROR_FILE_NOT_FOUND,"native crash gate unavailable");return;
        }
        ba_native_settings::ordinary(gate.value,false);
        wchar_t finalPath[32768];const auto n=GetFinalPathNameByHandleW(gate.value,finalPath,32768,FILE_NAME_NORMALIZED|VOLUME_NAME_DOS);
        require(n && n<32768,"native crash gate final path unavailable");
        std::wstring actual(finalPath);if(actual.rfind(L"\\\\?\\",0)==0)actual.erase(0,4);
        require(CompareStringOrdinal(actual.c_str(),-1,path.c_str(),-1,TRUE)==CSTR_EQUAL,"native crash gate escaped its owned profile");
        static constexpr char authorization[]="BA_NATIVE_CRASH169_AUTHORIZED\n";
        LARGE_INTEGER size{};char bytes[sizeof(authorization)]{};DWORD received=0;
        require(GetFileSizeEx(gate.value,&size) && size.QuadPart==sizeof(authorization)-1 &&
            ReadFile(gate.value,bytes,sizeof(authorization)-1,&received,nullptr) && received==sizeof(authorization)-1 &&
            memcmp(bytes,authorization,sizeof(authorization)-1)==0,"native crash gate contents differ");
        require(capture()==state,"native crash preconditions changed before trigger");
        fired=true;
        ba::log("NATIVE CRASH trigger: version=1 thread=%lu category=0 wrapperRva=1484d0 nativeCaller=1 mode=%lu",
            GetCurrentThreadId(),state.mode);
        reinterpret_cast<void(*)(int)>(unity+0x1484d0)(0);
        throw std::runtime_error("native crash unexpectedly returned");
    } catch(const std::exception& error) {
        failed=true;ba::log("NATIVE CRASH refused: version=1 thread=%lu reason=%s",GetCurrentThreadId(),error.what());
    }
}
