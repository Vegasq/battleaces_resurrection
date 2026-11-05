#pragma once
// Opt-in owned diagnostic: original selection and Back only; no Equip or asset writes.
namespace ba_cosmetics {
static unsigned sprayMenuStage=0,sprayMenuIndex=0,sprayMenuSample=0;
static ULONGLONG sprayMenuDue=0,sprayMenuDeadline=0;
static const uint32_t sprayMenuItems[]={54,10,71,151,152,203,54};
static auto& sprayMenuBefore=*new Pairs();
static auto& sprayMenuVM=*new std::unique_ptr<Root>();
static auto& sprayMenuRows=*new std::string();
static void guardSprayMenuBodies() {
    originalBackBody(0x3ca07d0,387,"d0a8c3478dfcc2a58530d851a6dc30118f677db996725a0997d999ed97735308");
    originalBackBody(0x3b67a50,123,"72b82650bfaafde2eed9b0ee1610811bad144e134088c4f28b55d73a6dd87b9a");
    originalBackBody(0x3b67f80,882,"eb5fcbf79f398b989a995b235dcd07b36888969d88d2120c313e5b4cd7533888");
    originalBackBody(0x3b68300,2250,"32d34b50eb4f12776c8d0b864e006dd7ff32fdd59a062a422757f073d2c237f1");
    originalBackBody(0x3c80e40,167,"91f3405e080d9597628ef7950d5b114adc6deb6a21eb7d14d65cf568246e8fff");
    originalBackBody(0x3c80ef0,477,"d6d8825fc5b333d01513ebc796ae25b796e0f503d3653b748af207729c312359");
    originalBackBody(0x3c810d0,140,"8b4aef6000a9812b091db0ea67fb6f567bf275c82c2bcd8df6d21b9ef61f17d8");
    originalBackBody(0x3c9fe90,103,"26cc03c694ce698c556f9943faa85956d9d48967cd42899c74abb3660549c07f");
    originalBackBody(0x3c9ff00,1586,"82f580edc457a388c238090a98f4c68fdfe7963a5fd3291578e19519dfa7409e");
}
static std::string sprayMenuObservation(const char* phase) {
    namespace ui=ba_practice_settings_ui;
    Obj vm=sprayMenuVM->get();const bool initialized=ba::get<bool>(vm,"_isInitialized");
    Root model(initialized?ba::call(vm,"get_Model"):nullptr);
    Root sprite(ba::get<Obj>(vm,"_sprite")),material(ba::get<Obj>(vm,"_material"));
    Root override(ba::get<Obj>(vm,"_materialOverride"));
    // Original SprayCosmetic prefab binds CosmeticItemVM.Material directly
    // to its own Image.material. Its optional _materialOverride is null.
    Root graphic(ui::component(vm,"UnityEngine.UI","Graphic"));
    require(graphic.get()!=nullptr,"spray graphic missing");
    Root actualMaterial(ba::call(graphic.get(),"get_material"));
    Root image(ui::component(vm,"UnityEngine.UI","Image"));
    Root actualSprite(image.get()?ba::call(image.get(),"get_sprite"):nullptr);
    const uint32_t item=model.get()?ba::get<uint32_t>(model.get(),"Item"):0;
    const std::string row="{\"phase\":"+ba_catalog::quote(phase)+",\"index\":"+std::to_string(sprayMenuIndex)+
        ",\"item\":"+std::to_string(sprayMenuItems[sprayMenuIndex])+",\"tick\":"+std::to_string(GetTickCount64())+
        ",\"model_item\":"+std::to_string(item)+",\"cosmetic_type\":"+std::to_string(ba::get<uint32_t>(vm,"_cosmeticType"))+
        ",\"vm_id\":"+std::to_string(emoteObjectId(vm))+",\"graphic_id\":"+std::to_string(emoteObjectId(graphic.get()))+
        ",\"sprite\":"+ba_catalog::quote(emoteName(sprite.get()))+",\"sprite_id\":"+std::to_string(emoteObjectId(sprite.get()))+
        ",\"material\":"+ba_catalog::quote(emoteName(material.get()))+",\"material_id\":"+std::to_string(emoteObjectId(material.get()))+
        ",\"actual_material\":"+ba_catalog::quote(emoteName(actualMaterial.get()))+
        ",\"actual_material_id\":"+std::to_string(emoteObjectId(actualMaterial.get()))+
        ",\"material_binding_matches\":"+videoBool(material.get() && actualMaterial.get()==material.get())+
        ",\"override_present\":"+videoBool(override.get()!=nullptr)+",\"image_present\":"+videoBool(image.get()!=nullptr)+
        ",\"image_enabled\":"+videoBool(image.get() && ba_catalog::unbox<bool>(ba::call(image.get(),"get_enabled")))+
        ",\"actual_sprite\":"+ba_catalog::quote(emoteName(actualSprite.get()))+
        ",\"actual_sprite_id\":"+std::to_string(emoteObjectId(actualSprite.get()))+
        ",\"sprite_binding_matches\":"+videoBool(sprite.get() && actualSprite.get()==sprite.get())+
        ",\"vm_active\":"+videoBool(ui::active(vm))+",\"vm_initialized\":"+videoBool(initialized)+
        ",\"graphic_active\":"+videoBool(ui::active(graphic.get()))+"}";
    if(!sprayMenuRows.empty())sprayMenuRows+=',';sprayMenuRows+=row;
    writeCosmeticProof((L"spray-menu-sample-"+std::to_wstring(sprayMenuSample++)).c_str(),row+"\n");
    return row;
}
static void sprayPreviewSmoke() {
    if(!ba::flag(L"-cosmetics-spray-menu-smoke") || sprayMenuStage>=10)return;
    namespace ui=ba_practice_settings_ui;
    if(sprayMenuStage==9) {
        try {if(editBack && editBackComplete()){sprayMenuStage=11;ba::log("SPRAY MENU failure returned to menu: originalBack=1");}}
        catch(const std::exception& e){sprayMenuStage=11;ba::log("SPRAY MENU cleanup failed: %s",e.what());}
        return;
    }
    try {
        require(ba::flag(L"-native-quit-smoke") && ba::flag(L"-native-quit-gate-smoke") &&
            ba::argument(L"-native-quit-mode=")=="confirm" && profileKey.rfind("nativestest_spray_",0)==0 &&
            ba_native_settings::session && ba_native_settings::session->profile()==profileKey &&
            !ba::flag(L"-cosmetics-equip-smoke") && !ba::flag(L"-cosmetics-picker-smoke") &&
            !ba::flag(L"-cosmetics-preview-smoke") && !ba::flag(L"-cosmetics-video-smoke") &&
            !ba::flag(L"-cosmetics-emote-smoke") && !ba::flag(L"-cosmetics-emote-match-smoke") &&
            !ba::flag(L"-profile-edits-smoke") && !ba::flag(L"-practice-ai-smoke"),
            "spray menu requires isolated explicitly gated diagnostic profile");
        const auto now=GetTickCount64();
        if(!sprayMenuDeadline){sprayMenuDeadline=now+90000;sprayMenuDue=now+2500;return;}
        require(now<sprayMenuDeadline,"spray menu deadline");if(now<sprayMenuDue)return;
        require(persistenceReady && stateStore && unlockActive() && ba_dedicated_session::inMenu() &&
            ba_client::nativeIdle(ownedFront->get()),"spray preview requires writable idle owned menu");
        if(sprayMenuStage==0) {
            Root menu(ba::get<Obj>(ba::owner,"<UIMenuController>k__BackingField")),main(ba::get<Obj>(menu.get(),"_mainMenu"));
            if(!main.get() || !ba::get<bool>(main.get(),"_isInitialized") || !ui::active(main.get()))return;
            Root transform(ui::findChild(main.get(),"LeftMenus/LeftButtons/CosmeticsButton"));
            Root button(ui::component(transform.get(),"Doozy.Runtime.UIManager.Components","UIButton"));ui::checkButton(button.get(),"CosmeticScreen");
            if(!ui::selectable(button.get()))return;
            guardSprayMenuBodies();Root slot(slots.at(8));auto ids=compatible(slot.get());std::sort(ids.begin(),ids.end());
            require(ids==std::vector<uint32_t>({10,54,71,151,152,203}),"spray catalog membership differs");
            sprayMenuBefore=normalize(rawSnapshot().first);equipExpected=sprayMenuBefore;
            ba::native<void(*)(Obj,Obj)>(0x89fe30)(button.get(),nullptr);
            sprayMenuStage=1;sprayMenuDue=now+600;ba::log("SPRAY MENU opened: originalButton=1 uniqueItems=6 noEquip=1");return;
        }
        require(normalize(rawSnapshot().first)==sprayMenuBefore && accepted==sprayMenuBefore && committed==sprayMenuBefore,
            "spray preview changed equipped loadout");
        if(sprayMenuStage==1) {
            if(!sprayMenuIndex)targetSlot(8);else reacquirePicker();
            selectItem(sprayMenuItems[sprayMenuIndex],false);sprayMenuStage=2;sprayMenuDue=now+500;
            ba::log("SPRAY MENU selected: index=%u item=%u",sprayMenuIndex,sprayMenuItems[sprayMenuIndex]);return;
        }
        if(sprayMenuStage==2) {
            reacquirePicker();Root preview(ba::get<Obj>(picker->get(),"_selectedCosmeticItemPreviewVM"));
            require(ba::get<uint32_t>(preview.get(),"_selectedCosmeticItem")==sprayMenuItems[sprayMenuIndex] &&
                ba::get<uint32_t>(preview.get(),"_category")==8,"spray preview selection/category mismatch");
            Root vm(ba::get<Obj>(preview.get(),"_selectedSprayVM"));
            require(ui::exact(vm.get(),"Uncapped","CosmeticItemVM") && ui::active(vm.get()) &&
                ba::get<bool>(vm.get(),"_isInitialized"),"spray VM inactive/uninitialized");
            sprayMenuVM=std::make_unique<Root>(vm.get());
            if(!ba::get<Obj>(vm.get(),"_sprite") || !ba::get<Obj>(vm.get(),"_material") || ba_native_quit::staticInt("LoadingCount"))return;
            sprayMenuObservation("loaded");sprayMenuStage=3;sprayMenuDue=now+500;return;
        }
        if(sprayMenuStage==3) {
            sprayMenuObservation("settled");
            if(sprayMenuIndex<6){++sprayMenuIndex;sprayMenuStage=1;sprayMenuDue=now+250;return;}
            editBackBegin();sprayMenuStage=4;sprayMenuDue=now+750;return;
        }
        if(sprayMenuStage==4) {
            if(!editBackComplete())return;
            const auto returned=sprayMenuObservation("back");writeCosmeticProof(L"spray-menu-return",returned+"\n");
            require(!ui::active(sprayMenuVM->get()) && !ba::get<bool>(sprayMenuVM->get(),"_isInitialized"),
                "Back retained active initialized spray preview");
            writeCosmeticProof(L"spray-menu-cases","{\"schema\":1,\"visual_audio_verified\":false,\"physical_input_tested\":false,\"loadout_unchanged\":true,\"observations\":["+sprayMenuRows+"]}\n");
            sprayMenuVM.reset();sprayMenuStage=10;
            ba::log("SPRAY MENU completed: items=6 selections=7 bindings=1 originalBack=1 inactive=1 loadoutUnchanged=1");return;
        }
    } catch(const std::exception& e) {
        sprayMenuStage=11;ba::log("SPRAY MENU failed: index=%u reason=%s",sprayMenuIndex,e.what());
        try {if(picker){if(!editBack){equipExpected=sprayMenuBefore;editBackBegin();}sprayMenuStage=9;}}
        catch(const std::exception& cleanup){ba::log("SPRAY MENU cleanup unavailable: %s",cleanup.what());}
    }
}
}
