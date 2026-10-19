#pragma once
// Experimental cosmetic-only call sites. Shared Steam/dictionary methods stay original.
extern "C" __declspec(dllexport) int32_t OfflineCosmeticVisibilityIndex(void*,uint32_t,void*);
extern "C" __declspec(dllexport) bool OfflineCosmeticOwned(uint32_t,void*);
extern "C" __declspec(dllexport) void OfflineCosmeticItemCache(void*,void*);
namespace ba_cosmetics {
static void uiTrace();
static void pickerSmoke();
static bool unlockReady=false,unlockFailed=false,unlockSmokeDone=false,saveDeferred=false;
static volatile LONG unlockOwnerThread=0;
static unsigned requestsDeferred=0,requestsRejected=0,presenceDeferred=0,decksDeferred=0;
static auto& ownedFront=*new std::unique_ptr<Root>();
static auto& ownedAccount=*new std::unique_ptr<Root>();
static auto& ownedCosmetics=*new std::unique_ptr<Root>();
static auto& itemIds=*new std::vector<uint32_t>();
static auto& entitlementIds=*new std::vector<uint32_t>();
static bool contains(const std::vector<uint32_t>& values,uint32_t key) {
    return std::find(values.begin(),values.end(),key)!=values.end();
}
static bool unlockEnabled() {return ba::localMenu() && ba::flag(L"-local-cosmetics-experimental");}
static bool unlockActive() {
    // Other native threads never inspect Unity-owned roots or mutable catalog data.
    if(static_cast<DWORD>(InterlockedCompareExchange(&unlockOwnerThread,0,0))!=GetCurrentThreadId())return false;
    if(!unlockReady || !unlockEnabled() || !ba::owner)return false;
    Obj services=ba::read<Obj>(ba::owner,0x38),front=ownedFront->get(),account=ownedAccount->get(),cosmetics=ownedCosmetics->get();
    return services && ba::read<Obj>(services,0x10)==front && ba::read<Obj>(front,0x258)==account &&
        ba::read<Obj>(front,0x250)==cosmetics && ba::read<Obj>(account,0x88)==cosmetics;
}
static bool ownsFront(Obj front) {return unlockActive() && ownedFront->get()==front;}
static void deferred(const char* operation) {
    if(!saveDeferred)ba::log("Experimental cosmetics changed: operation=%s localSavePending=1 persistenceImplemented=0",operation);
    saveDeferred=true;
}
static void unlockSmoke(Obj front) {
    if(unlockSmokeDone || !ba::flag(L"-cosmetics-unlock-smoke"))return;
    require(unlockActive(),"cosmetic smoke ownership changed");
    const auto before=saved(ownedCosmetics->get());
    Obj cls=ba::find_class("Uncapped","SteamInventory");ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(cls);
    Obj field=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(cls,"EntitlementCache");
    require(field!=nullptr,"cosmetic smoke native entitlement cache field missing");
    Obj value=nullptr;ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(field,&value);Root cache(value);
    require(cache.get()!=nullptr,"cosmetic smoke original entitlement cache missing");
    const int count=ba_catalog::unbox<int>(ba::call(cache.get(),"get_Count"));
    Obj find=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(ba::klass(cache.get()),"FindEntry",1);
    require(find!=nullptr,"cosmetic smoke original dictionary method missing");
    unsigned missingBefore=0,ownedModels=0;
    for(uint32_t key:entitlementIds) {
        const int32_t original=ba::native<int32_t(*)(Obj,uint32_t,Obj)>(0x2c936e0)(cache.get(),key,find);
        missingBefore+=original<0?1:0;
        require(OfflineCosmeticVisibilityIndex(cache.get(),key,find)>=0 && OfflineCosmeticOwned(key,nullptr),"known cosmetic not unlocked");
    }
    // Missing-key fallback must keep the signed negative index, never Boolean0.
    for(uint32_t key:{0u,UINT32_MAX}) {
        require(!contains(entitlementIds,key),"cosmetic sentinel unexpectedly granted");
        const int32_t original=ba::native<int32_t(*)(Obj,uint32_t,Obj)>(0x2c936e0)(cache.get(),key,find);
        require(OfflineCosmeticVisibilityIndex(cache.get(),key,find)==original && original<0,"unknown cosmetic index fallback changed");
        require(OfflineCosmeticOwned(key,nullptr)==ba::native<bool(*)(uint32_t,Obj)>(0x3e86920)(key,nullptr),"unknown ownership fallback changed");
    }
    Obj modelClass=ba::find_class("Uncapped","SelectCosmeticItemModel");ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(modelClass);
    for(uint32_t id:itemIds) {
        Root model(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(modelClass));void* args[]={&id};ba::call(model.get(),".ctor",1,args);
        require(ba::get<bool>(model.get(),"<Owned>k__BackingField"),"native cosmetic model constructor not owned");
        ba::native<void(*)(Obj,Obj)>(0x3b69790)(model.get(),nullptr);
        const int rarity=ba::get<int>(model.get(),"<Rarity>k__BackingField");
        OfflineCosmeticItemCache(model.get(),nullptr);
        require(ba::get<bool>(model.get(),"<Owned>k__BackingField") && ba::get<int>(model.get(),"<Rarity>k__BackingField")==rarity,
            "cosmetic model owned/rarity mismatch");++ownedModels;
    }
    // Exercise the original serializer and patched case37 tail without equipping
    // anything. The scoped wrapper must consume exactly this native request.
    const unsigned requestsBefore=requestsDeferred,rejectedBefore=requestsRejected;
    ba::call(front,"SaveAllCosmetics");
    require(requestsDeferred==requestsBefore+1 && requestsRejected==rejectedBefore,"native cosmetic save was not contained as case37");
    require(ba_catalog::unbox<int>(ba::call(cache.get(),"get_Count"))==count && saved(ownedCosmetics->get())==before &&
        ba_dedicated_session::worldIdle(ba::read<Obj>(front,0xd8)),"cosmetic smoke changed inventory/loadout/world");
    const std::string report="{\"schema\":1,\"passed\":true,\"items\":"+std::to_string(ownedModels)+",\"entitlement_keys\":"+
        std::to_string(entitlementIds.size())+",\"original_missing_keys\":"+std::to_string(missingBefore)+
        ",\"unknown_signed_fallback\":true,\"rarity_preserved\":true,\"inventory_unchanged\":true,\"loadout_unchanged\":true,\"world_idle\":true,\"native_save_case37_suppressed\":true}\n";
    const auto path=ba_export::moduleDirectory()+L"investigation\\runtime\\cosmetics-unlock-"+std::to_wstring(GetCurrentProcessId())+L".json";
    require(GetFileAttributesW(path.c_str())==INVALID_FILE_ATTRIBUTES && GetLastError()==ERROR_FILE_NOT_FOUND,"cosmetic smoke output unavailable");
    ba_export::atomicWrite(path,reinterpret_cast<const unsigned char*>(report.data()),report.size());unlockSmokeDone=true;
    ba::log("COSMETICS UNLOCK SMOKE passed: items=%u keys=%zu missingBefore=%u rarityPreserved=1 unknownSignedFallback=1 inventoryUnchanged=1 loadoutUnchanged=1 worldIdle=1 nativeSaveCase37Suppressed=1",
        ownedModels,entitlementIds.size(),missingBefore);
}
static void unlockUpdate(Obj front) {
    if(!unlockEnabled() || unlockFailed || !ba_local_menu::ready(front))return;
    try {
        require(ba_dedicated_session::unityThread==GetCurrentThreadId(),"cosmetic unlock off Unity thread");
        if(!unlockReady) {
            if(!ba_dedicated_session::inMenu() || !ba_dedicated_session::worldIdle(ba::read<Obj>(front,0xd8)))return;
            const bool a=ba_public_bots::cosmetics.ready(),b=slots.ready();if(!a || !b)return;
            const auto text=serialize();require(text==serialize(),"cosmetic unlock catalog changed");
            ownedFront=std::make_unique<Root>(front);ownedAccount=std::make_unique<Root>(ba::get<Obj>(front,"_accountService"));
            ownedCosmetics=std::make_unique<Root>(ba::get<Obj>(ownedAccount->get(),"_cosmetics"));
            require(ownedCosmetics->get()!=nullptr,"cosmetic unlock missing account cosmetics");
            Root elements(ba::call(ba_public_bots::cosmetics.get(),"get_Elements"));
            for(size_t i=0;i<ba_catalog::length(elements.get());++i) {
                Root item(ba_catalog::arrayAt(elements.get(),i)),definition(ba::call(item.get(),"get_Definition"));
                itemIds.push_back(ba_catalog::unbox<uint32_t>(ba::call(item.get(),"get_ID")));
                const uint32_t key=ba::get<uint32_t>(definition.get(),"EntitlementKey");
                if(key && key!=UINT32_MAX && !contains(entitlementIds,key))entitlementIds.push_back(key);
            }
            unlockReady=true;InterlockedExchange(&unlockOwnerThread,static_cast<LONG>(GetCurrentThreadId()));
            require(unlockActive(),"cosmetic unlock local owner mismatch");
            ba::log("BA_RESURRECTION_COSMETICS_UNLOCK_V1 ready: items=%zu entitlementKeys=%zu cosmeticCallSitesOnly=1 persistenceImplemented=0",itemIds.size(),entitlementIds.size());
        }
        unlockSmoke(front);
        uiTrace();
        pickerSmoke();
    } catch(const std::exception& error) {
        InterlockedExchange(&unlockOwnerThread,0);unlockFailed=true;unlockReady=false;ba::log("Cosmetics unlock failed: %s",error.what());
    }
}
}
extern "C" __declspec(dllexport) int32_t OfflineCosmeticVisibilityIndex(void* dictionary,uint32_t key,void* method) {
    ba::init();
    if(ba_cosmetics::unlockActive() && ba_cosmetics::contains(ba_cosmetics::entitlementIds,key))return 0;
    return ba::native<int32_t(*)(void*,uint32_t,void*)>(0x2c936e0)(dictionary,key,method);
}
extern "C" __declspec(dllexport) bool OfflineCosmeticOwned(uint32_t key,void* method) {
    ba::init();
    if(ba_cosmetics::unlockActive() && ba_cosmetics::contains(ba_cosmetics::entitlementIds,key))return true;
    return ba::native<bool(*)(uint32_t,void*)>(0x3e86920)(key,method);
}
extern "C" __declspec(dllexport) void OfflineCosmeticItemCache(void* model,void* method) {
    ba::init();
    ba::native<void(*)(void*,void*)>(0x3b69790)(model,method);
    if(ba_cosmetics::unlockActive() && model && ba::klass(model)==ba::find_class("Uncapped","SelectCosmeticItemModel") &&
        ba_cosmetics::contains(ba_cosmetics::itemIds,ba::read<uint32_t>(model,0x10)))
        ba::set<bool>(model,"<Owned>k__BackingField",true);
}
extern "C" __declspec(dllexport) void OfflineCosmeticSaveDeckDeferred(void* account,void* method) {
    ba::init();
    if(ba_cosmetics::unlockActive() && ba_cosmetics::ownedAccount->get()==account) {
        ++ba_cosmetics::decksDeferred;ba_cosmetics::deferred("selected deck");return;
    }
    ba::native<void(*)(void*,void*)>(0x3e2e040)(account,method);
}
extern "C" __declspec(dllexport) void OfflineCosmeticPresence(uint32_t banner,uint32_t portrait,void* front) {
    ba::init();
    if(ba_cosmetics::ownsFront(front)) {++ba_cosmetics::presenceDeferred;ba_cosmetics::deferred("Steam presence");return;}
    ba::native<void(*)(uint32_t,uint32_t,void*)>(0x3e902d0)(banner,portrait,nullptr);
}
extern "C" __declspec(dllexport) void OfflineCosmeticSaveRequest(void* front,void* consumer,void* method) {
    ba::init();
    if(ba_cosmetics::ownsFront(front)) {
        void* request=consumer?ba::read<void*>(consumer,0x20):nullptr;
        const bool valid=request && ba::read<int>(consumer,0x28)==37 && ba::read<void*>(request,0x20);
        if(!valid){++ba_cosmetics::requestsRejected;ba::log("Cosmetics save request rejected: unexpected native case37 shape; retired traffic suppressed");}
        ++ba_cosmetics::requestsDeferred;ba_cosmetics::deferred("cosmetic loadout");return;
    }
    ba::native<void(*)(void*,void*,void*)>(0x256df90)(front,consumer,method);
}
