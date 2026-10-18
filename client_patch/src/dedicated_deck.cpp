#pragma once
// Include after ba_local and dedicated transport. Transport supplies:
//     namespace ba_dedicated { void submitDeck(ba::Obj commonPbDeck);
//         void ready(ba::Obj front,int mode); void cancelReady(ba::Obj front); }
// WELCOME: ba_dedicated_deck::initialize(front,savedCommonPbDeck).
// Hook AccountService.SaveSelectedDeck RVA3e2e040 to the export below.
// Preserve ClientDeckSelector.SetDeck and Deck.Changed, so existing picker,
// category validation, active-ability assignment and local storage keep working.
namespace ba_dedicated_deck {
using ba::Obj;using ba_local::Root;
static bool initialized=false,suppress=false;
static uint32_t accountRoot=0;
static uint32_t savedChanges=0;
static Obj require(Obj object,const char* message) {if(!object)throw std::runtime_error(message);return object;}
static Obj account() {return accountRoot?ba::api<Obj(*)(uint32_t)>("il2cpp_gchandle_get_target")(accountRoot):nullptr;}
static Obj ensure(Obj object,const char* field,const char* ns,const char* type) {
    Obj value=ba::get<Obj>(object,field);
    if(!value){Root created(ba::make(ns,type));ba::set<Obj>(object,field,created.get());value=created.get();}return value;
}
static Obj staticData(Obj ownerAccount) {
    Obj provider=require(ba::get<Obj>(ownerAccount,"_staticGameDataProvider"),"dedicated menu data provider missing");
    bool allowLocal=true;void* args[]={&allowLocal};
    Obj contract=ba::find_class("Uncapped","IStaticGameDataProvider");
    Obj method=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(contract,"GetStaticGameData",1);
    method=ba::api<Obj(*)(Obj,Obj)>("il2cpp_object_get_virtual_method")(provider,method);
    return require(ba_local::invokeMethod(method,provider,args),"dedicated menu static data missing");
}
static void addUint(Obj repeated,uint32_t value) {
    Obj chosen=nullptr;void* iter=nullptr;
    while(Obj method=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(ba::klass(repeated),&iter)) {
        if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(method),"Add"))continue;
        if(ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(method)!=1)continue;
        Obj type=ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(method,0);
        if(ba::api<int(*)(Obj)>("il2cpp_type_get_type")(type)==9){chosen=method;break;}
    }
    void* args[]={&value};ba_local::invokeMethod(require(chosen,"dedicated uint repeated Add missing"),repeated,args);
}
static Obj proto(Obj runtimeDeck) {
    // Exact serialization used by shipped ToProtoBuildtime, excluding cosmetics.
    // ToProtoShared preserves all four active ability slots.
    Root result(ba::call(runtimeDeck,"ToProtoShared"));
    Obj units=require(ba::get<Obj>(runtimeDeck,"_units"),"dedicated deck unit array missing");
    if(ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(units)!=8)throw std::runtime_error("dedicated deck must have eight positions");
    Obj dest=ba::get<Obj>(result.get(),"units_");
    for(int i=0;i<8;++i)addUint(dest,ba::read<uint32_t>(units,0x20+4*i));
    return result.get();
}
static Obj selected(Obj ownerAccount) {
    Obj selector=require(ba::get<Obj>(ownerAccount,"_deckSelector"),"dedicated deck selector missing");
    return require(ba::call(selector,"get_SelectedDeck"),"dedicated selected deck missing");
}
static Obj selectedProto(Obj front) {
    Obj ownerAccount=require(ba::get<Obj>(front,"_accountService"),"dedicated account missing");
    return proto(selected(ownerAccount));
}
static bool canReady(Obj front) {
    try {
        Obj ownerAccount=require(ba::get<Obj>(front,"_accountService"),"dedicated account missing");
        Obj value=selected(ownerAccount);Root data(staticData(ownerAccount));
        const bool full=ba::native<bool(*)(Obj,Obj)>(0x3daa0a0)(value,nullptr);
        const bool valid=full && ba::native<bool(*)(Obj,Obj,Obj,Obj)>(0x3daa480)(value,data.get(),ownerAccount,nullptr);
        if(!valid)ba::log("Dedicated lobby: fill all eight valid unit slots and use at most four active ability groups before ready");
        return valid;
    } catch(const std::exception& e){ba::log("Dedicated deck readiness check failed: %s",e.what());return false;}
}
static void saveSelected(Obj ownerAccount) {
    if(!initialized || suppress || ownerAccount!=account())return;
    struct Guard {Guard(){suppress=true;}~Guard(){suppress=false;}} guard;
    try {
        Root result(proto(selected(ownerAccount)));
        Obj profile=require(ba::get<Obj>(ownerAccount,"<ProfileCache>k__BackingField"),"dedicated profile missing");
        Root cached(ba::call(result.get(),"Clone"));ba::set<Obj>(profile,"selectedDeck_",cached.get());
        // LocalDeckStorage.Save already runs in OnDeckContentsChanged.
        // Standalone practice keeps the native saved deck without a server.
        if(!ba::offlinePractice())ba_dedicated::submitDeck(result.get());
        ++savedChanges;
        ba::log("Native deck picker saved current eight-slot selection; standalone=%d",ba::offlinePractice()?1:0);
    } catch(const std::exception& e){ba::log("Dedicated deck save failed: %s",e.what());}
}
static void initializeSelection(Obj front,Obj savedDeck) {
    initialized=false;
    struct Guard {Guard(){suppress=true;}~Guard(){suppress=false;}} guard;
    Obj ownerAccount=require(ba::get<Obj>(front,"_accountService"),"dedicated account missing");
    ba::local_profile(ownerAccount);
    Obj profile=require(ba::get<Obj>(ownerAccount,"<ProfileCache>k__BackingField"),"dedicated profile missing");
    Obj accountData=ensure(profile,"accountData_","CommonPb","AccountData");
    ensure(profile,"profileLocks_","CommonPb","ProfileLocks");
    Obj progression=ensure(profile,"progression_","CommonPb","PlayerProgression");
    ensure(progression,"provingGrounds_","CommonPb","ProgressionState");
    ensure(progression,"globalStatSource_","CommonPb","StatSourceCollection");
    ensure(profile,"cosmeticLoadout_","CommonPb","CosmeticLoadout");
    // These flags are local adapter state, never a claimed Steam entitlement.
    // FeatureUnlockBit values0..4: proving grounds, both tutorials, onboarding,
    // VIP. Original GetUnitUnlockedFlags ORs Vip16 when account flags bit4 set.
    // Original IsFeatureUnlocked tests bit0; no progression lock bypass needed.
    const uint64_t oldFlags=ba::get<uint64_t>(accountData,"featureFlags_");
    const uint64_t newFlags=oldFlags|UINT64_C(0x1f);
    ensure(ownerAccount,"_freeUnitRotation","Uncapped","FreeUnitRotationRuntime");
    ba::set<uint64_t>(accountData,"featureFlags_",newFlags);
    Obj changed=ba::get<Obj>(ownerAccount,"OnFeatureFlagsUpdated");
    if(changed && oldFlags!=newFlags) {
        uint64_t pair[2]={oldFlags,newFlags};void* args[]={pair};ba::call(changed,"Invoke",1,args);
    }
    // Trigger only local static initialization for picker tracking. Its shipped
    // cctor creates the in-memory TailoredUXTracking object; do not call cloud
    // InitializeAll, login handlers, or Steam synchronization.
    Root trackingFile(ba::invoke(ba::find_class("Uncapped","UncappedSteamRemoteStorageSync"),nullptr,"get_TailoredUXTrackingFile",0));
    if(!trackingFile.get() || !ba::read<Obj>(trackingFile.get(),0x10))throw std::runtime_error("dedicated local UI tracking missing");
    Root data(staticData(ownerAccount));
    void* fromArgs[]={savedDeck};
    Root runtime(savedDeck?ba::invoke(ba::find_class("Uncapped","Deck"),nullptr,"FromProto",1,fromArgs):selected(ownerAccount));
    void* abilityArgs[]={data.get(),ownerAccount};ba::call(runtime.get(),"AutoAssignAbilities",2,abilityArgs);
    Obj selector=require(ba::get<Obj>(front,"_deckSelector"),"dedicated front deck selector missing");
    if(savedDeck){void* selectArgs[]={runtime.get()};ba::call(selector,"SetDeck",1,selectArgs);}
    Root cached(proto(selected(ownerAccount)));ba::set<Obj>(profile,"selectedDeck_",cached.get());
    if(accountRoot)ba::api<void(*)(uint32_t)>("il2cpp_gchandle_free")(accountRoot);
    accountRoot=ba::api<uint32_t(*)(Obj,bool)>("il2cpp_gchandle_new")(ownerAccount,false);
    initialized=true;
    ba::log("Native deck editor initialized from %s selection; local featureFlags=0x%llx, full/valid=%d",
        savedDeck?"server":"local storage",static_cast<unsigned long long>(newFlags),canReady(front)?1:0);
}
static void initialize(Obj front,Obj savedDeck) {
    initializeSelection(front,require(savedDeck,"dedicated server supplied no saved deck"));
}
static void initializeLocal(Obj front) {initializeSelection(front,nullptr);}
static void updateLobby(Obj front,bool ready) {
    // Call only on the Unity thread and after the server confirms C_READY.
    // Clear with false before installing a match. Keep the original status
    // calculation, MatchmakingStateChange delegate and SignalRouter updates.
    if(!initialized || !front)return;
    try {
        if(ready && !ba::get<bool>(front,"_inMatchmakingQueue")) {
            Root now(ba::call(front,"GetCurrentServerTime"));
            uint64_t stamp=*ba::api<uint64_t*(*)(Obj)>("il2cpp_object_unbox")(require(now.get(),"dedicated queue timestamp missing"));
            ba::set<uint64_t>(front,"_timeEnteredQueue",stamp);
        }
        ba::set<bool>(front,"_inMatchmakingQueue",ready);
        ba::set<bool>(front,"_localIsInMatchmaking",ready);
        ba::set<bool>(front,"_matchmakingGame",false);
        ba::set<int32_t>(front,"_pendingMatchmakingRequests",0);
        ba::set<int32_t>(front,"_localMatchmakingGameMode",1);
        ba::set<int32_t>(front,"_matchmakingGameMode",1);
        int32_t error=0;void* args[]={&error};ba::call(front,"UpdateMatchmakingStatus",1,args);
        ba::log("Dedicated server-confirmed lobby ready=%d; native matchmaking status=%d",ready?1:0,ba::get<int32_t>(front,"_matchmakingStatus"));
    } catch(const std::exception& e){ba::log("Dedicated native queue feedback failed: %s",e.what());}
}
static void logDeck(const char* phase,Obj deck) {
    Obj units=require(ba::get<Obj>(deck,"_units"),"dedicated smoke unit array missing");
    Obj groups=require(ba::get<Obj>(deck,"_activeAbilities"),"dedicated smoke ability array missing");
    ba::log("Dedicated deck smoke %s units=[%u,%u,%u,%u,%u,%u,%u,%u] abilities=[%u,%u,%u,%u]",
        phase,ba::read<uint32_t>(units,0x20),ba::read<uint32_t>(units,0x24),ba::read<uint32_t>(units,0x28),ba::read<uint32_t>(units,0x2c),
        ba::read<uint32_t>(units,0x30),ba::read<uint32_t>(units,0x34),ba::read<uint32_t>(units,0x38),ba::read<uint32_t>(units,0x3c),
        ba::read<uint32_t>(groups,0x20),ba::read<uint32_t>(groups,0x24),ba::read<uint32_t>(groups,0x28),ba::read<uint32_t>(groups,0x2c));
}
static bool smokeSelection(Obj front) {
    // Optional integration test. No direct submitDeck/saveSelected invocation:
    // shipped setters must raise Changed -> selector -> original Front callback
    // -> hooked AccountService.SaveSelectedDeck. Call after initialize has
    // returned and transport installing=false, before any auto-ready request.
    if(!wcsstr(GetCommandLineW(),L"-dedicated-deck-smoke"))return true;
    static bool attempted=false,passed=false;if(attempted)return passed;attempted=true;
    try {
        if(!initialized || suppress)throw std::runtime_error("dedicated smoke called before deck initialization completed");
        Obj ownerAccount=require(ba::get<Obj>(front,"_accountService"),"dedicated smoke account missing");
        Obj value=selected(ownerAccount);Root data(staticData(ownerAccount));
        int index=ba::lanSlot()?1:0;uint32_t unit=ba::lanSlot()?6u:1u;
        bool allowLocked=false;void* validArgs[]={&unit,&index,data.get(),ownerAccount,&allowLocked};
        Root valid(ba::call(value,"IsValidSlot",5,validArgs));
        if(!*ba::api<bool*(*)(Obj)>("il2cpp_object_unbox")(require(valid.get(),"dedicated smoke validation missing")))
            throw std::runtime_error("dedicated smoke replacement rejected by original slot validator");
        const uint32_t before=savedChanges;logDeck("before",value);
        void* setArgs[]={&index,&unit};ba::call(value,"set_Item",2,setArgs);
        void* abilityArgs[]={data.get(),ownerAccount};ba::call(value,"AutoAssignAbilities",2,abilityArgs);
        logDeck("after",value);
        passed=savedChanges>before && canReady(front);
        ba::log("Dedicated deck smoke original setters slot=%d unit=%u captured-save-callbacks=%u full-valid=%d result=%s",
            index,unit,savedChanges-before,canReady(front)?1:0,passed?"PASS":"FAIL");
        return passed;
    } catch(const std::exception& e){ba::log("Dedicated deck smoke failed: %s",e.what());return false;}
}
static void rematchSmokeSelection(Obj front) {
    // Test-only second-match edit. Exercise the same native setters, Changed
    // event, AccountService hook and server persistence as a user's deck edit.
    if(!ba::flag(L"-dedicated-rematch-smoke") && !ba::flag(L"-community-match-deck-smoke") &&
       !(ba::flag(L"-practice-ai-smoke") && ba::flag(L"-practice-ai-deck-smoke")))return;
    if(!initialized || suppress)throw std::runtime_error("rematch deck editor not initialized");
    Obj ownerAccount=require(ba::get<Obj>(front,"_accountService"),"rematch account missing");
    Obj value=selected(ownerAccount);Root data(staticData(ownerAccount));
    Obj units=require(ba::get<Obj>(value,"_units"),"rematch unit array missing");
    int index=ba::offlinePractice()?0:ba::community()?(ba::flag(L"-community-match-host-smoke")?0:1):(ba::lanSlot()?1:0);
    const uint32_t old=ba::read<uint32_t>(units,0x20+4*index);
    uint32_t replacement=0;
    for(uint32_t candidate:{75u,74u,1u,6u}) {
        bool duplicate=false;
        for(int i=0;i<8;++i)if(ba::read<uint32_t>(units,0x20+4*i)==candidate)duplicate=true;
        if(duplicate)continue;
        bool allowLocked=false;void* args[]={&candidate,&index,data.get(),ownerAccount,&allowLocked};
        Root valid(ba::call(value,"IsValidSlot",5,args));
        if(*ba::api<bool*(*)(Obj)>("il2cpp_object_unbox")(require(valid.get(),"rematch slot validation missing"))) {replacement=candidate;break;}
    }
    if(!replacement || replacement==old)throw std::runtime_error("no distinct valid rematch core unit found");
    const uint32_t before=savedChanges;logDeck("rematch-before",value);
    void* setArgs[]={&index,&replacement};ba::call(value,"set_Item",2,setArgs);
    void* abilityArgs[]={data.get(),ownerAccount};ba::call(value,"AutoAssignAbilities",2,abilityArgs);
    logDeck("rematch-after",value);
    if(savedChanges==before || !canReady(front))throw std::runtime_error("native rematch deck edit did not produce a valid save");
    ba::log("DEDICATED REMATCH SMOKE automated native deck edit: slot=%d old=%u new=%u saveCallbacks=%u full-valid=1",
        index,old,replacement,savedChanges-before);
}
}
extern "C" __declspec(dllexport) void OfflineDedicatedSaveSelectedDeck(void* account,void*) {
    ba_dedicated_deck::saveSelected(account);
}
extern "C" __declspec(dllexport) void OfflineDedicatedJoinQueue(void* front,void* controller,int mode,void*) {
    try {
        if(mode==4){ba_practice::start(front,controller);return;}
        // Public queue arbitration is integrated separately. Keep the local
        // public path opt-in until online timeout/cancellation are qualified.
        if(ba::unified() && mode==1 && ba::flag(L"-public-ai-experimental")) {
            ba_practice::startPublic(front,controller,mode);return;
        }
        if(ba::dedicated() && !ba_practice::active())ba_dedicated::ready(front,mode);
    }
    catch(const std::exception& e){ba::log("Dedicated native Play could not ready lobby: %s",e.what());}
}
extern "C" __declspec(dllexport) void OfflineDedicatedLeaveQueue(void* front,bool,void*) {
    try {if(ba::dedicated())ba_dedicated::cancelReady(front);}
    catch(const std::exception& e){ba::log("Dedicated native Cancel could not leave lobby queue: %s",e.what());}
}
