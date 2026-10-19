#pragma once
// Opt-in original callback diagnostics. No normal launcher selects/equips items.
namespace ba_cosmetics {
static unsigned equipStage=0;
static ULONGLONG equipDue=0,equipDeadline=0;
static auto& equipBefore=*new Pairs();
static auto& equipExpected=*new Pairs();
static uint32_t portraitSlot=0,portraitFirst=0,portraitSecond=0,emoteA=0,emoteB=0,emoteX=0,emoteY=0;
static uint32_t selectedAt(const Pairs& selection,uint32_t slot) {
    for(auto pair:selection)if(pair.first==slot)return pair.second;
    throw std::runtime_error("cosmetic diagnostic slot missing");
}
static void expectedAt(uint32_t slot,uint32_t item) {
    for(auto& pair:equipExpected)if(pair.first==slot){pair.second=item;return;}
    throw std::runtime_error("cosmetic diagnostic target missing");
}
static void reacquirePicker() {
    picker.reset();Root menu(ba::get<Obj>(ba::owner,"<UIMenuController>k__BackingField")),main(ba::get<Obj>(menu.get(),"_mainMenu"));
    Root transform(ba::call(main.get(),"get_transform")),root(ba::call(transform.get(),"get_root"));unsigned nodes=0;
    findPicker(root.get(),0,nodes);require(picker!=nullptr,"cosmetic diagnostic picker no longer active");checkPicker();
}
static void targetSlot(uint32_t id) {
    reacquirePicker();void* args[]={&id};ba::call(picker->get(),"OnCosmeticSlotSelected",1,args);
    int filter=0;void* filters[]={&filter};ba::call(picker->get(),"OnFilterValueChanged",1,filters);
    require(ba::get<uint32_t>(picker->get(),"_slot")==id,"cosmetic equip target mismatch");
}
static void selectItem(uint32_t id,bool confirm) {
    const auto current=ba::get<uint32_t>(picker->get(),"_slot");Root slot(slots.at(current));const auto items=compatible(slot.get());
    require(contains(items,id),"cosmetic diagnostic incompatible selection");void* args[]={&id};
    ba::call(picker->get(),confirm?"OnSelectAndConfirm":"OnSelectItem",1,args);
}
static void chooseEquipItems() {
    equipBefore=normalize(rawSnapshot().first);equipExpected=equipBefore;
    Root config(ba::get<Obj>(ba::owner,"_clientGlobalConfig"));portraitSlot=ba::get<uint32_t>(config.get(),"PortraitCosmeticSlot");
    Root portrait(slots.at(portraitSlot));const auto portraits=compatible(portrait.get());
    for(auto item:portraits)if(item!=selectedAt(equipBefore,portraitSlot)) {
        if(!portraitFirst)portraitFirst=item;else if(!portraitSecond){portraitSecond=item;break;}
    }
    require(portraitFirst && portraitSecond,"cosmetic equip needs two alternate portraits");
    Root all(ba::call(slots.get(),"get_Elements"));
    for(size_t i=0;i<ba_catalog::length(all.get()) && !emoteY;++i) {
        Root a(ba_catalog::arrayAt(all.get(),i));const auto candidates=compatible(a.get());if(candidates.size()<4)continue;
        const auto aId=ba_catalog::unbox<uint32_t>(ba::call(a.get(),"get_ID"));
        for(size_t j=i+1;j<ba_catalog::length(all.get()) && !emoteY;++j) {
            Root b(ba_catalog::arrayAt(all.get(),j));if(compatible(b.get())!=candidates)continue;
            const auto bId=ba_catalog::unbox<uint32_t>(ba::call(b.get(),"get_ID"));uint32_t x=0,y=0;
            for(auto item:candidates) {
                if(std::any_of(equipBefore.begin(),equipBefore.end(),[&](auto pair){return pair.second==item;}))continue;
                if(!x)x=item;else {y=item;break;}
            }
            if(x && y){emoteA=aId;emoteB=bId;emoteX=x;emoteY=y;}
        }
    }
    require(emoteX && emoteY,"cosmetic equip needs equivalent slots with two unused items");
}
static void validateProjection(const Pairs& selection) {
    Root config(ba::get<Obj>(ba::owner,"_clientGlobalConfig")),profile(ba::get<Obj>(ownedAccount->get(),"<ProfileCache>k__BackingField"));
    Root loadout(ba::get<Obj>(profile.get(),"cosmeticLoadout_"));require(loadout.get()!=nullptr,"cosmetic diagnostic projection missing");
    // Build37822 full ToProto's twelve configured fields, independently read back.
    for(unsigned i=0;i<12;++i) {
        const uint32_t slot=ba::read<uint32_t>(config.get(),0xc8+4*i);Root child(ba::read<Obj>(loadout.get(),0x18+8*i));
        require(child.get() && ba::get<uint32_t>(child.get(),"id_")==selectedAt(selection,slot),"cosmetic twelve-field projection mismatch");
    }
}
static void writeCosmeticProof(const wchar_t* prefix,const std::string& text) {
    const auto path=ba_export::moduleDirectory()+L"investigation\\runtime\\"+prefix+L"-"+std::to_wstring(GetCurrentProcessId())+L".json";
    require(GetFileAttributesW(path.c_str())==INVALID_FILE_ATTRIBUTES && GetLastError()==ERROR_FILE_NOT_FOUND,"cosmetic proof output already exists");
    ba_export::atomicWrite(path,reinterpret_cast<const unsigned char*>(text.data()),text.size());
}
static void equipSmoke() {
    if(!ba::flag(L"-cosmetics-equip-smoke") || equipStage==10)return;
    const auto now=GetTickCount64();if(!equipDeadline){equipDeadline=now+60000;equipDue=now+2500;return;}
    require(now<equipDeadline,"cosmetic equip diagnostic deadline");if(now<equipDue)return;
    require(persistenceReady && stateStore && unlockActive() && ba_dedicated_session::inMenu() &&
        ba_dedicated_session::worldIdle(ba::read<Obj>(ownedFront->get(),0xd8)),"cosmetic equip requires writable idle test profile");
    require(profileKey.rfind("cosmeticstest_",0)==0,"cosmetic equip requires an explicit disposable test profile");
    if(equipStage==0) {
        namespace ui=ba_practice_settings_ui;
        Root menu(ba::get<Obj>(ba::owner,"<UIMenuController>k__BackingField")),main(ba::get<Obj>(menu.get(),"_mainMenu"));
        if(!main.get() || !ba::get<bool>(main.get(),"_isInitialized") || !ui::active(main.get()))return;
        Root transform(ui::findChild(main.get(),"LeftMenus/LeftButtons/CosmeticsButton"));
        Root button(ui::component(transform.get(),"Doozy.Runtime.UIManager.Components","UIButton"));ui::checkButton(button.get(),"CosmeticScreen");
        if(!ui::selectable(button.get()))return;chooseEquipItems();ba::native<void(*)(Obj,Obj)>(0x89fe30)(button.get(),nullptr);
        equipStage=1;equipDue=now+500;return;
    }
    require(normalize(rawSnapshot().first)==equipExpected,"cosmetic callback full-map readback mismatch");
    if(equipStage==1) {
        targetSlot(portraitSlot);selectItem(portraitFirst,false);
        Root preview(ba::get<Obj>(picker->get(),"_selectedCosmeticItemPreviewVM")),model(ba::get<Obj>(preview.get(),"_model"));
        require(model.get() && ba_catalog::unbox<uint32_t>(ba::call(model.get(),"get_ID"))==portraitFirst &&
            normalize(rawSnapshot().first)==equipBefore,"cosmetic select preview/loadout mismatch");
    } else if(equipStage==2) {
        reacquirePicker();ba::call(picker->get(),"OnEquipSelectedItem");expectedAt(portraitSlot,portraitFirst);
    } else if(equipStage==3) {
        targetSlot(portraitSlot);selectItem(portraitSecond,true);expectedAt(portraitSlot,portraitSecond);
    } else if(equipStage==4) {
        targetSlot(emoteA);selectItem(emoteX,false);ba::call(picker->get(),"OnEquipSelectedItem");expectedAt(emoteA,emoteX);
    } else if(equipStage==5) {
        targetSlot(emoteB);selectItem(emoteY,false);ba::call(picker->get(),"OnEquipSelectedItem");expectedAt(emoteB,emoteY);
    } else if(equipStage==6) {
        targetSlot(emoteA);selectItem(emoteY,true);expectedAt(emoteA,emoteY);expectedAt(emoteB,emoteX);
    } else if(equipStage==7) {
        ba::call(ownedCosmetics->get(),"TryResetInvalidCosmeticsToDefault");
        require(normalize(rawSnapshot().first)==equipExpected,"native invalid-item validator changed valid nondefault choices");
    } else if(equipStage==8) {
        reacquirePicker();targetSlot(portraitSlot);
        const auto path=ba_export::moduleDirectory()+L"investigation\\runtime\\cosmetics-equip-"+std::to_wstring(GetCurrentProcessId())+L".png";
        Root name(ba::api<Obj(*)(const wchar_t*,int)>("il2cpp_string_new_utf16")(path.data(),static_cast<int>(path.size())));void* args[]={name.get()};
        ba::invoke(ba::find_class("UnityEngine","ScreenCapture"),nullptr,"CaptureScreenshot",1,args);
    } else if(equipStage==9) {
        observe();require(accepted==equipExpected && committed==equipExpected && persistenceWrites>0 && !projectionPending,"cosmetic diagnostic save not committed");
        validateProjection(accepted);
        const std::string before=ba_cosmetics_state::encode({profileKey,catalogHash,equipBefore}),after=ba_cosmetics_state::encode({profileKey,catalogHash,accepted});
        writeCosmeticProof(L"cosmetics-equip","{\"schema\":1,\"passed\":true,\"selection_callback\":true,\"equip_callback\":true,\"confirm_callback\":true,\"swap_prior_item\":true,\"valid_reset_preserved\":true,\"projection12\":true,\"world_idle\":true,\"writes\":"+
            std::to_string(persistenceWrites)+",\"before\":"+before+",\"after\":"+after+"}\n");
        equipStage=10;ba::log("COSMETICS EQUIP SMOKE passed: nativeCallbacks=1 fullMap=17 priorItemSwap=1 atomicSave=1 projection12=1 noMatch=1");return;
    }
    ++equipStage;equipDue=now+500;
}
static void persistenceProof() {
    static bool complete=false;static ULONGLONG due=0;
    if(complete || !ba::flag(L"-cosmetics-persistence-proof") || !persistenceReady)return;
    const auto now=GetTickCount64();if(!due){due=now+2500;return;}if(now<due)return;
    if(ba::flag(L"-cosmetics-equip-smoke") && equipStage!=10)return;
    const auto actual=normalize(rawSnapshot().first);require(actual==accepted && !projectionPending,"cosmetic persistence proof stale");validateProjection(actual);
    writeCosmeticProof(L"cosmetics-persistence","{\"schema\":1,\"passed\":true,\"restored\":"+std::string(persistenceRestored?"true":"false")+
        ",\"writable\":"+(stateStore?"true":"false")+",\"read_error\":"+(persistenceReadError?"true":"false")+",\"projection12\":true,\"state\":"+
        ba_cosmetics_state::encode({profileKey,catalogHash,actual})+"}\n");
    complete=true;ba::log("COSMETICS PERSISTENCE PROOF passed: slots=17 restored=%d writable=%d projection12=1",persistenceRestored?1:0,stateStore?1:0);
}
}
