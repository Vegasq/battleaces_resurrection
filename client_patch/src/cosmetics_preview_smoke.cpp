#pragma once
// Explicit owned diagnostic; ordinary launchers never select these flags.
namespace ba_cosmetics {
struct SkinPreviewParameters {
    uint32_t unit,color,skin,padding;
    Obj events;
    bool voice;
    unsigned char tail[7];
};
static_assert(sizeof(SkinPreviewParameters)==32 && offsetof(SkinPreviewParameters,events)==16);
struct SkinPreviewCase {uint32_t slot,item,event;};
static auto& skinCases=*new std::vector<SkinPreviewCase>();
static unsigned skinStage=0,skinIndex=0;
static ULONGLONG skinDue=0,skinDeadline=0;
static auto& skinRows=*new std::string();
static auto& skinScene=*new std::unique_ptr<Root>();
static auto& skinUnit=*new std::unique_ptr<Root>();
static auto& skinPool=*new std::unique_ptr<Root>();
static auto& skinRenderer=*new std::unique_ptr<Root>();
static auto& skinFirstUnit=*new std::unique_ptr<Root>();
static auto& skinBefore=*new Pairs();
static bool skinPoolMode(){return ba::flag(L"-cosmetics-preview-pool-smoke");}
static bool skinAvailable(Obj pool,Obj unit) {
    Root available(ba::get<Obj>(pool,"_availableObjects"));require(available.get(),"skin pool available stack missing");
    void* args[]={unit};Root found(ba::call(available.get(),"Contains",1,args));return ba_catalog::unbox<bool>(found.get());
}
static std::string skinPoolObservation(Obj pool,Obj unit) {
    Root available(ba::get<Obj>(pool,"_availableObjects")),tracked(ba::get<Obj>(pool,"_createdObjectTracker"));
    const int count=ba_catalog::unbox<int>(ba::call(available.get(),"get_Count"));
    const int all=ba::get<int>(pool,"<CountAll>k__BackingField");
    require(count>=0 && all>=count && all<=4096,"skin pool accounting bounds");
    bool created=false;if(tracked.get()){void* args[]={unit};Root found(ba::call(tracked.get(),"Contains",1,args));created=ba_catalog::unbox<bool>(found.get());}
    Root go(ba_practice_settings_ui::gameObject(unit));
    const int id=ba_catalog::unbox<int>(ba::call(go.get(),"GetInstanceID"));
    return "{\"unit_instance\":"+std::to_string(id)+",\"count_all\":"+std::to_string(all)+",\"count_available\":"+std::to_string(count)+
        ",\"available_contains_unit\":"+(skinAvailable(pool,unit)?"true":"false")+",\"created_tracker_present\":"+(tracked.get()?"true":"false")+
        ",\"created_tracker_contains_unit\":"+(created?"true":"false")+",\"active_in_hierarchy\":"+(ba_practice_settings_ui::active(unit)?"true":"false")+"}";
}
static std::vector<uint32_t> skinEventKeys(Obj array) {
    require(array && ba_catalog::length(array)<=256,"skin preview event array missing/oversized");
    std::vector<uint32_t> keys;
    for(size_t i=0;i<ba_catalog::length(array);++i)keys.push_back(ba::read<uint32_t>(array,0x20+i*4));
    return keys;
}
static std::pair<size_t,size_t> skinRegisteredEvents(Obj unit,uint32_t key) {
    namespace ui=ba_practice_settings_ui;
    // Reuse the exact already-initialized generic lookups used by the original
    // EventRunner.RegisterRequirementEvents. These look up loaded assets only.
    originalBackBody(0x78970,87,"be40b09b553c3e890e012b71f6200aa120001809be13fe4ce8fbd4e9c6ae514c");
    originalBackBody(0x137f030,793,"1ce082a508529fa56757468c6c8c4003579b17c0573fbf60381e73a7eb911b3a");
    originalBackBody(0x121ccb0,171,"17ba4c3e4e97306fd62a1e0cbad78d2e833c00ceabd65b84b40a7a35c6c8dec5");
    auto bound=[](uintptr_t rva,const char* name,uintptr_t body,unsigned count) {
        Obj method=ba::read<Obj>(ba::module,rva);
        require(reinterpret_cast<uintptr_t>(method)>0xffffffff && !(reinterpret_cast<uintptr_t>(method)&7),"skin asset lookup metadata unresolved");
        require(std::string(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(method))==name &&
            ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(method)==count &&
            ba::read<uintptr_t>(method,0)==reinterpret_cast<uintptr_t>(ba::module)+body,"skin asset lookup method binding differs");
        return method;
    };
    Obj elementMethod=bound(0x6aedfe8,"GetElement",0x121ccb0,1);void* keyArgs[]={&key};
    Root collection(ba_local::invokeMethod(elementMethod,nullptr,keyArgs));
    require(ui::exact(collection.get(),"Uncapped","EventCollection"),"skin event table lookup differs");
    Root reference(ba::get<Obj>(collection.get(),"EventConfigAsset"));
    Root memory(ba::native<Obj(*)()>(0x78970)());require(ui::exact(memory.get(),"Uncapped","AssetMemoryManager"),"skin asset manager differs");
    Obj asset=nullptr;uint32_t bucket=1;void* assetArgs[]={reference.get(),&bucket,&asset};
    Obj getMethod=bound(0x6b171b0,"TryGetLoadedAsset",0x137f030,3);
    Root got(ba_local::invokeMethod(getMethod,memory.get(),assetArgs)),loaded(asset);
    require(ba_catalog::unbox<bool>(got.get()) && ui::exact(loaded.get(),"Uncapped","EventConfigAsset"),"skin event config is not loaded");
    Root events(ba::get<Obj>(loaded.get(),"Events")),runner(ba::get<Obj>(unit,"_eventRunner"));
    Root cache(ba::get<Obj>(runner.get(),"<EventCache>k__BackingField"));
    require(events.get() && ba_catalog::length(events.get())>0 && ba_catalog::length(events.get())<=4096 && cache.get(),"skin loaded events/cache missing");
    std::vector<Obj> registered;
    auto addList=[&](Obj list) {
        if(!list)return;const int count=ba_local::count(list);require(count>=0 && count<=4096,"skin event cache list bounds");
        for(int i=0;i<count;++i){Obj event=ui::item(list,i);if(event)registered.push_back(event);}
    };
    for(const auto* field:{"_noRequirementEvents","_labelEvents","_hitEvents","_assetCreationEvents","_armyColorChangedEvents","_interactionEvents","_streakEvents"})
        addList(ba::get<Obj>(cache.get(),field));
    for(const auto* field:{"_eventsByEntityState","_eventsByEntityStateTransitions"}) {
        Root sparse(ba::get<Obj>(cache.get(),field));if(!sparse.get())continue;
        Root values(ba::get<Obj>(sparse.get(),"_values"));if(!values.get())continue;
        require(ba_catalog::length(values.get())<=4096,"skin sparse event cache bounds");
        for(size_t i=0;i<ba_catalog::length(values.get());++i)addList(ba_catalog::arrayAt(values.get(),i));
    }
    size_t matched=0;
    for(size_t i=0;i<ba_catalog::length(events.get());++i) {
        Obj event=ba_catalog::arrayAt(events.get(),i);
        if(event && std::find(registered.begin(),registered.end(),event)!=registered.end())++matched;
    }
    return {ba_catalog::length(events.get()),matched};
}
static void chooseSkinCases() {
    Root config(ba::get<Obj>(ba::owner,"_clientGlobalConfig"));
    std::vector<SkinPreviewCase> families[3];unsigned family=0;
    for(const auto* field:{"HQSkinCosmeticSlot","ExpansionSkinCosmeticSlot","WorkerSkinCosmeticSlot"}) {
        const auto slotId=ba::get<uint32_t>(config.get(),field);Root slot(slots.at(slotId));
        for(auto id:compatible(slot.get())) {
            Root item(ba_public_bots::cosmetics.at(id)),definition(ba::call(item.get(),"get_Definition"));
            Root metadata(ba::get<Obj>(definition.get(),"Metadata"));require(metadata.get(),"skin definition metadata missing");
            uint32_t key=0;unsigned matches=0;
            for(size_t i=0;i<ba_catalog::length(metadata.get());++i) {
                Root entry(ba_catalog::arrayAt(metadata.get(),i));
                if(ba_practice_settings_ui::exact(entry.get(),"Uncapped","CosmeticItemEventCollectionKey")) {
                    key=ba::get<uint32_t>(entry.get(),"Key");++matches;
                }
            }
            require(matches==1 && key,"skin definition requires exactly one event key");
            families[family].push_back({slotId,id,key});
        }
        ++family;
    }
    // Interleave families so each selection also exercises category switching.
    for(size_t i=0;i<32;++i)for(auto& values:families)if(i<values.size())skinCases.push_back(values[i]);
    require(skinCases.size()==13,"supported skin catalog differs from the13-case contract");
    if(skinPoolMode())skinCases.resize(3); // One installed skin from each family.
    skinCases.push_back(skinCases.front()); // Explicit return to the first skin.
}
static void skinPreviewSmoke() {
    if(!ba::flag(L"-cosmetics-preview-smoke") || skinStage>=6)return;
    namespace ui=ba_practice_settings_ui;
    try {
        require(ba::flag(L"-native-quit-smoke") && ba::flag(L"-native-quit-gate-smoke") &&
            ba::argument(L"-native-quit-mode=")=="confirm" && profileKey.rfind("nativestest_skins_",0)==0 &&
            ba_native_settings::session && ba_native_settings::session->profile()==profileKey &&
            !ba::flag(L"-cosmetics-equip-smoke") && !ba::flag(L"-cosmetics-picker-smoke") &&
            !ba::flag(L"-profile-edits-smoke") && !ba::flag(L"-practice-ai-smoke"),
            "skin previews require an isolated explicitly gated diagnostic profile");
        const auto now=GetTickCount64();
        if(!skinDeadline){skinDeadline=now+180000;skinDue=now+2500;return;}
        require(now<skinDeadline,"skin preview diagnostic deadline");if(now<skinDue)return;
        require(persistenceReady && stateStore && unlockActive() && ba_dedicated_session::inMenu() &&
            ba_client::nativeIdle(ownedFront->get()),"skin preview requires writable idle owned menu");
        if(skinStage==0) {
            Root menu(ba::get<Obj>(ba::owner,"<UIMenuController>k__BackingField")),main(ba::get<Obj>(menu.get(),"_mainMenu"));
            if(!main.get() || !ba::get<bool>(main.get(),"_isInitialized") || !ui::active(main.get()))return;
            Root transform(ui::findChild(main.get(),"LeftMenus/LeftButtons/CosmeticsButton"));
            Root button(ui::component(transform.get(),"Doozy.Runtime.UIManager.Components","UIButton"));ui::checkButton(button.get(),"CosmeticScreen");
            if(!ui::selectable(button.get()))return;
            chooseSkinCases();skinBefore=normalize(rawSnapshot().first);equipExpected=skinBefore;
            ba::native<void(*)(Obj,Obj)>(0x89fe30)(button.get(),nullptr);
            skinStage=1;skinDue=now+600;ba::log("SKIN PREVIEW opened: originalButton=1 cases=%zu uniqueSkins=%zu noEquip=1",skinCases.size(),skinCases.size()-1);return;
        }
        require(normalize(rawSnapshot().first)==skinBefore && accepted==skinBefore && committed==skinBefore,
            "skin preview changed the equipped loadout");
        if(skinStage==1) {
            const auto& test=skinCases.at(skinIndex);targetSlot(test.slot);selectItem(test.item,false);
            skinStage=2;skinDue=now+1000;
            ba::log("SKIN PREVIEW selected: index=%u slot=%u item=%u expectedEvent=%u",skinIndex,test.slot,test.item,test.event);return;
        }
        if(skinStage==2) {
            const auto& test=skinCases.at(skinIndex);reacquirePicker();
            Root preview(ba::get<Obj>(picker->get(),"_selectedCosmeticItemPreviewVM"));
            Root vm(ba::get<Obj>(preview.get(),"_selectedUnitCosmeticPreviewVM"));
            require(ui::exact(vm.get(),"Uncapped.UI","SelectUnitCosmeticPreviewVM") && ui::active(vm.get()) &&
                ba::get<bool>(vm.get(),"_isInitialized"),"skin preview VM not active/initialized");
            const auto requested=ba::get<SkinPreviewParameters>(vm.get(),"_previewParameters");
            const auto events=skinEventKeys(requested.events);
            require(requested.skin==test.item && requested.unit && contains(events,test.event),"skin preview selection/event mismatch");
            Root manager(ba::get<Obj>(vm.get(),"_menuSceneManager"));
            Root scene(ba::get<Obj>(manager.get(),"_unitPreviewScene"));
            if(!scene.get() || !ui::active(scene.get()))return;
            const auto actual=ba::get<SkinPreviewParameters>(scene.get(),"_unitPreviewParameters");
            if(actual.skin!=requested.skin || actual.unit!=requested.unit || !actual.events)return;
            require(skinEventKeys(actual.events)==events,"skin preview scene events differ");
            Root renderer(ba::get<Obj>(scene.get(),"_unit3DRenderer"));
            Root unit(renderer.get()?ba::get<Obj>(renderer.get(),"<Unit>k__BackingField"):nullptr);
            if(!unit.get() || !ui::active(unit.get()) || ba_native_quit::staticInt("LoadingCount")!=0)return;
            Root collections(ba::get<Obj>(unit.get(),"EventCollections"));const auto applied=skinEventKeys(collections.get());
            const auto registered=skinRegisteredEvents(unit.get(),test.event);
            ba::log("SKIN PREVIEW event registration: index=%u expected=%zu registered=%zu baseKeys=%s",skinIndex,registered.first,registered.second,numbers(applied).c_str());
            require(registered.first==registered.second,"selected event config is not fully registered on the preview unit");
            const bool priorActive=skinUnit && ui::active(skinUnit->get());
            const bool reused=skinUnit && skinUnit->get()==unit.get();
            std::string poolEvidence;
            if(skinPoolMode()) {
                Root poolManager(ba::get<Obj>(renderer.get(),"_unitPool")),pools(ba::get<Obj>(poolManager.get(),"_poolsByKey"));
                const uint32_t key=ba_catalog::unbox<uint32_t>(ba::call(unit.get(),"get_UnitType"));void* poolArgs[]={const_cast<uint32_t*>(&key)};
                Root pool(ba::call(pools.get(),"get_Item",1,poolArgs));require(key==actual.unit && pool.get(),"preview unit pool identity differs");
                const auto current=skinPoolObservation(pool.get(),unit.get());
                const auto previous=skinPool && skinUnit?skinPoolObservation(skinPool->get(),skinUnit->get()):"null";
                const bool previousAvailable=skinPool && skinUnit && skinAvailable(skinPool->get(),skinUnit->get());
                const bool firstReused=skinFirstUnit && skinFirstUnit->get()==unit.get();
                poolEvidence=",\"current_pool\":"+current+",\"previous_pool\":"+previous+",\"first_unit_reused\":"+(firstReused?"true":"false");
                writeCosmeticProof((L"skin-pool-case-"+std::to_wstring(skinIndex)).c_str(),"{\"index\":"+std::to_string(skinIndex)+poolEvidence+"}\n");
                require(!skinAvailable(pool.get(),unit.get()),"current preview unit is still in the available pool");
                require(!skinUnit || reused || previousAvailable,"previous preview unit did not return to its available pool");
                if(!skinFirstUnit)skinFirstUnit=std::make_unique<Root>(unit.get());
                skinPool=std::make_unique<Root>(pool.get());skinRenderer=std::make_unique<Root>(renderer.get());
            }
            skinScene=std::make_unique<Root>(scene.get());skinUnit=std::make_unique<Root>(unit.get());
            if(!skinPoolMode()) {
            const auto leaf=L"skin-preview-"+std::to_wstring(GetCurrentProcessId())+L"-"+std::to_wstring(skinIndex)+L".png";
            const auto path=ba_export::moduleDirectory()+L"investigation\\runtime\\"+leaf;
            require(GetFileAttributesW(path.c_str())==INVALID_FILE_ATTRIBUTES,"skin preview capture already exists");
            Root name(ba::api<Obj(*)(const wchar_t*,int)>("il2cpp_string_new_utf16")(path.data(),static_cast<int>(path.size())));void* args[]={name.get()};
            ba::invoke(ba::find_class("UnityEngine","ScreenCapture"),nullptr,"CaptureScreenshot",1,args);
            }
            if(!skinRows.empty())skinRows+=',';
            skinRows+="{\"index\":"+std::to_string(skinIndex)+",\"slot\":"+std::to_string(test.slot)+",\"item\":"+std::to_string(test.item)+
                ",\"unit_type\":"+std::to_string(actual.unit)+",\"expected_event\":"+std::to_string(test.event)+",\"preview_events\":"+numbers(events)+
                ",\"unit_base_events\":"+numbers(applied)+",\"loaded_event_count\":"+std::to_string(registered.first)+",\"registered_event_count\":"+std::to_string(registered.second)+
                ",\"prior_unit_active\":"+(priorActive?"true":"false")+",\"pooled_unit_reused\":"+(reused?"true":"false")+poolEvidence+"}";
            ba::log("SKIN PREVIEW loaded: index=%u item=%u sceneAndUnitEvents=1 activeUnit=1 loadingCount=0 captureRequested=1",skinIndex,test.item);
            skinStage=3;skinDue=now+750;return;
        }
        if(skinStage==3) {
            if(++skinIndex<skinCases.size()){skinStage=1;return;}
            writeCosmeticProof(L"skin-preview-cases","{\"schema\":1,\"runtime_observations_complete\":true,\"visual_review_complete\":false,\"loadout_unchanged\":true,\"cases\":["+skinRows+"]}\n");
            editBackBegin();skinStage=4;skinDue=now+750;return;
        }
        if(skinStage==4) {
            if(!editBackComplete())return;
            const bool sceneActive=skinScene && ui::active(skinScene->get());
            const bool unitActive=skinUnit && ui::active(skinUnit->get());
            if(skinPoolMode()) {
                const bool rendererCleared=skinRenderer && !ba::get<Obj>(skinRenderer->get(),"<Unit>k__BackingField");
                const bool returned=skinPool && skinUnit && skinAvailable(skinPool->get(),skinUnit->get());
                writeCosmeticProof(L"skin-preview-return","{\"schema\":1,\"original_back\":true,\"loadout_unchanged\":true,\"scene_active_after_back\":"+
                    std::string(sceneActive?"true":"false")+",\"unit_active_after_back\":"+(unitActive?"true":"false")+
                    ",\"renderer_unit_cleared\":"+(rendererCleared?"true":"false")+",\"returned_to_available_pool\":"+(returned?"true":"false")+
                    ",\"pool\":"+skinPoolObservation(skinPool->get(),skinUnit->get())+"}\n");
                require(!sceneActive && rendererCleared && returned,"skin preview renderer/pool ownership not released after Back");
                skinScene.reset();skinUnit.reset();skinPool.reset();skinRenderer.reset();skinFirstUnit.reset();skinStage=6;
                ba::log("SKIN POOL completed: families=3 selections=4 originalBack=1 rendererCleared=1 returnedToPool=1 sceneInactive=1 loadoutUnchanged=1");return;
            }
            writeCosmeticProof(L"skin-preview-return","{\"schema\":1,\"original_back\":true,\"loadout_unchanged\":true,\"scene_active_after_back\":"+
                std::string(sceneActive?"true":"false")+",\"unit_active_after_back\":"+(unitActive?"true":"false")+"}\n");
            require(!sceneActive && !unitActive,"skin preview remains active after original Back");
            skinScene.reset();skinUnit.reset();skinStage=6;
            ba::log("SKIN PREVIEW completed: uniqueSkins=13 selections=14 originalBack=1 sceneInactive=1 unitInactive=1 loadoutUnchanged=1 visualReviewRequired=1");
        }
    } catch(const std::exception& error) {
        skinStage=7;ba::log("SKIN PREVIEW failed: index=%u reason=%s",skinIndex,error.what());
        // Retain failure; try only the established original Back path. The
        // external controller alone can release the separately validated Quit.
        try {if(picker && !editBack){equipExpected=skinBefore;editBackBegin();}skinStage=5;}
        catch(const std::exception& cleanup){ba::log("SKIN PREVIEW cleanup unavailable: %s",cleanup.what());}
    }
    if(skinStage==5) {
        try {if(editBack && editBackComplete()){skinStage=7;ba::log("SKIN PREVIEW failure returned to menu: originalBack=1");}}
        catch(const std::exception& error){skinStage=7;ba::log("SKIN PREVIEW cleanup failed: %s",error.what());}
    }
}
}
