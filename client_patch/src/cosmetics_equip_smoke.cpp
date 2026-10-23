#pragma once
#include "profile_edit_policy.hpp"
// Opt-in original callback diagnostics. No normal launcher selects/equips items.
namespace ba_cosmetics {
static unsigned equipStage=0;
static ULONGLONG equipDue=0,equipDeadline=0;
static auto& equipBefore=*new Pairs();
static auto& equipExpected=*new Pairs();
static uint32_t portraitSlot=0,portraitFirst=0,portraitSecond=0,emoteA=0,emoteB=0,emoteX=0,emoteY=0;
struct EditBackLease {
    Root flow,graph,node,picker,owner,screen,menu,main,mainOwner,pool,mainDescriptor,destination;
    EditBackLease(Obj f,Obj g,Obj n,Obj p,Obj o,Obj s,Obj m,Obj v,Obj vo,Obj poolValue,Obj descriptor,Obj target):
        flow(f),graph(g),node(n),picker(p),owner(o),screen(s),menu(m),main(v),mainOwner(vo),pool(poolValue),mainDescriptor(descriptor),destination(target){}
};
static auto& editBack=*new std::unique_ptr<EditBackLease>();
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
static void originalBackBody(uintptr_t rva,size_t size,const char* expected) {
    ba_telemetry_audit::Bytes body(size);
    require(ba_telemetry_audit::copy(reinterpret_cast<uintptr_t>(ba::module)+rva,body.data(),body.size()) &&
        ba_telemetry_audit::digest(body)==expected,"profile edit original Back bytes differ");
}
static void editBackBegin() {
    namespace ui=ba_practice_settings_ui;
    reacquirePicker();Root flow(ui::flowController()),graph(ba::get<Obj>(flow.get(),"_flowGraph"));
    require(graph.get()!=nullptr,"profile edit Back graph missing");
    Root node(ba::get<Obj>(graph.get(),"ActiveNode"));
    require(ui::exact(node.get(),"Uncapped.UI","ShowUIObjectNode"),"profile edit Back requires original acquired node");
    Root owner(ba::get<Obj>(picker->get(),"<Owner>k__BackingField")),screen(ba::get<Obj>(owner.get(),"<Root>k__BackingField"));
    require(screen.get() && ba::get<bool>(screen.get(),"_isInitialized") && ui::active(screen.get()) &&
        ba::get<Obj>(screen.get(),"<Owner>k__BackingField")==owner.get() &&
        ba::get<Obj>(owner.get(),"_pool")==ba::get<Obj>(node.get(),"_pool") &&
        ba::get<Obj>(picker->get(),"_pool")==ba::get<Obj>(owner.get(),"_pool") &&
        ba::get<Obj>(picker->get(),"_menuFlowController")==flow.get(),"profile edit picker acquired lifetime differs");
    Root descriptors(ba::get<Obj>(node.get(),"ShowUIObject")),views(ba::get<Obj>(node.get(),"_uiObject"));
    const auto count=ui::arrayCount(descriptors.get(),32);require(ui::arrayCount(views.get(),32)==count,"profile edit acquired arrays differ");
    unsigned found=0;
    for(size_t i=0;i<count;++i)if(ui::arrayItem(views.get(),i)==screen.get()) {
        Obj descriptor=ui::arrayItem(descriptors.get(),i);
        require(descriptor && ba::get<int>(descriptor,"_prefabKey")==ba::get<int>(owner.get(),"<PrefabType>k__BackingField"),
            "profile edit acquired descriptor differs");++found;
    }
    require(found==1,"profile edit picker root is not the unique current acquired view");
    Root previous(picker->get()),transform(ba::call(screen.get(),"get_transform"));picker.reset();unsigned nodes=0;
    findPicker(transform.get(),0,nodes);require(picker && picker->get()==previous.get(),"profile edit picker lies outside acquired root");
    require(ba::get<Obj>(graph.get(),"ActiveNode")==node.get(),"profile edit graph changed during binding");
    originalBackBody(0x3d53fb0,112,"8db7941bfa43e107b56c9509e596833e5b47ba5e115732071c5aae55bb6d8cd6");
    originalBackBody(0x3d54c30,256,"56dbe8de729eb4d59d1946bf65b18cdb61fbc4859b430d96fa5254093b4ab139");
    originalBackBody(0x3d56800,352,"15cbb9b9b4581a5bb3e2b7d7b1028f69495e0929b68fb0d5c9595ad87e76e730");
    Root fromPort(ba::get<Obj>(node.get(),"_fromPort"));
    require(ui::exact(fromPort.get(),"System","String") &&
        ba::api<int(*)(Obj)>("il2cpp_string_length")(fromPort.get())>0,"profile edit Back has no prior port");
    require(ba::read<Obj>(node.get(),0x20)==graph.get(),"profile edit node belongs to another graph");
    Root priorPort(ba::native<Obj(*)(Obj,Obj,Obj)>(0x953270)(graph.get(),fromPort.get(),nullptr));
    require(priorPort.get() && ba::read<Obj>(priorPort.get(),0x78),"profile edit prior port has no destination node");
    // Additional original UI policy gate, not called by direct GoBack itself.
    // The original getter can initialize metadata/normalize its loading counter.
    const bool canGoBack=ba::native<bool(*)(Obj,Obj)>(0x3d54c30)(node.get(),nullptr);
    // Container state is separate evidence: the original controller/node Back
    // bodies do not consult UIContainer.isVisible. Never call this desktop proof.
    Root container(ba::get<Obj>(owner.get(),"_uiContainer"));
    const bool compatible=container.get() && ba::api<bool(*)(Obj,Obj)>("il2cpp_class_is_assignable_from")(
        ba::find_class("Doozy.Runtime.UIManager.Containers","UIContainer"),ba::klass(container.get()));
    bool visible=false;int containerState=0;std::string containerClass="null";
    if(container.get())containerClass=std::string(ba::api<const char*(*)(Obj)>("il2cpp_class_get_namespace")(ba::klass(container.get())))+"."+
        ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(ba::klass(container.get()));
    if(compatible) {
        originalBackBody(0x88a350,8,"e9943457754d79d150465f361e8b6688d8d9366e64f713d9ecde13171986de87");
        containerState=ba::read<int>(container.get(),0x54);
        visible=ba::native<bool(*)(Obj,Obj)>(0x88a350)(container.get(),nullptr);
        require(visible==(containerState==0),"profile edit container state/getter mismatch");
    }
    writeCosmeticProof(L"profile-edits-back-state","{\"schema\":1,\"physical_visibility_tested\":false,\"can_go_back\":"+
        std::string(canGoBack?"true":"false")+",\"prior_port_nonempty\":true,\"container_present\":"+(container.get()?"true":"false")+
        ",\"container_class\":"+ba_catalog::quote(containerClass)+",\"container_compatible\":"+(compatible?"true":"false")+
        ",\"container_state\":"+(compatible?std::to_string(containerState):"null")+",\"container_visible\":"+
        (compatible?(visible?"true":"false"):"null")+",\"picker_active\":"+(ui::active(picker->get())?"true":"false")+
        ",\"picker_initialized\":"+(ba::get<bool>(picker->get(),"_isInitialized")?"true":"false")+
        ",\"owner_initialized\":"+(ba::get<bool>(owner.get(),"<IsInitialized>k__BackingField")?"true":"false")+
        ",\"screen_active\":true,\"screen_initialized\":true,\"owned_current_view\":true}\n");
    require(!container.get() || compatible,"profile edit unknown UI container class");
    require(canGoBack,"profile edit original CanGoBack declined");
    originalBackBody(0x3d509c0,1008,"0bee3b9fa0845e1b48825dd50a57703f1e44f7aada642425816888e1e1f601d3");
    originalBackBody(0x3d628c0,416,"084a1088fc41966d1f192c6ab1680c7a55cb30eb3dbf7e37bc879f0db3ef1bf6");
    Root menu(ba::get<Obj>(ba::owner,"<UIMenuController>k__BackingField")),main(ba::get<Obj>(menu.get(),"_mainMenu"));
    require(ui::exact(main.get(),"Uncapped.UI","PlayScreenVM") && ba::get<bool>(main.get(),"_isInitialized"),
        "profile edit persistent main missing");
    Root mainOwner(ba::get<Obj>(main.get(),"<Owner>k__BackingField")),pool(ba::get<Obj>(menu.get(),"_pool")),descriptor(ba::get<Obj>(menu.get(),"_showMainMenu"));
    require(mainOwner.get() && pool.get() && descriptor.get() && ba::get<bool>(mainOwner.get(),"<IsInitialized>k__BackingField") &&
        ba::get<Obj>(mainOwner.get(),"<Root>k__BackingField")==main.get() && ba::get<Obj>(mainOwner.get(),"_pool")==pool.get() &&
        ba::get<int>(mainOwner.get(),"<PrefabType>k__BackingField")==ba::get<int>(descriptor.get(),"_prefabKey"),
        "profile edit persistent main acquired ownership differs");
    Obj method=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(
        ba::klass(flow.get()),"Uncapped.UI.IMenuFlowController.GoBack",0);
    require(method && ba::read<uintptr_t>(method,0)==reinterpret_cast<uintptr_t>(ba::module)+0x3d53fb0,
        "profile edit original GoBack method differs");
    editBack=std::make_unique<EditBackLease>(flow.get(),graph.get(),node.get(),picker->get(),owner.get(),screen.get(),
        menu.get(),main.get(),mainOwner.get(),pool.get(),descriptor.get(),ba::read<Obj>(priorPort.get(),0x78));
    ba::log("PROFILE EDITS Back dispatch: ownedCurrentView=1 originalGoBack=1 fullMap=17");
    ba::call(flow.get(),"Uncapped.UI.IMenuFlowController.GoBack");
}
static bool editBackComplete() {
    namespace ui=ba_practice_settings_ui;
    require(editBack && ui::flowController()==editBack->flow.get(),"profile edit Back controller changed");
    Root current(ba::get<Obj>(editBack->graph.get(),"ActiveNode"));
    if(!ui::exact(current.get(),"Uncapped.UI","ShowUIObjectNode") || current.get()==editBack->node.get())return false;
    const bool directDestination=current.get()==editBack->destination.get();
    const bool graphMatches=ba::read<Obj>(current.get(),0x20)==editBack->graph.get();
    static bool destinationReported=false;
    if(!destinationReported) {
        ba::log("PROFILE EDITS settled navigation: directTargetMatches=%d currentGraphMatches=%d",directDestination?1:0,graphMatches?1:0);
        destinationReported=true;
    }
    // SetActiveNode invokes OnEnter/callbacks before returning; original entry
    // nodes may synchronously redirect. The direct target is an observation.
    Root menu(ba::get<Obj>(ba::owner,"<UIMenuController>k__BackingField")),main(ba::get<Obj>(menu.get(),"_mainMenu"));
    if(!main.get() || !ui::active(main.get()) || !ba::get<bool>(main.get(),"_isInitialized") ||
        ba::get<bool>(editBack->owner.get(),"<IsInitialized>k__BackingField") ||
        ba::get<bool>(editBack->picker.get(),"_isInitialized") || ba::get<bool>(editBack->screen.get(),"_isInitialized"))return false;
    require(!ui::active(editBack->screen.get()),"profile edit released screen still active");
    Root views(ba::get<Obj>(current.get(),"_uiObject"));const auto count=ui::arrayCount(views.get(),32);unsigned found=0;
    for(size_t i=0;i<count;++i) {
        Obj view=ui::arrayItem(views.get(),i);require(view!=editBack->screen.get(),"profile edit old screen remains acquired");
        if(view==main.get())++found;
    }
    Root owner(ba::get<Obj>(main.get(),"<Owner>k__BackingField"));
    const bool ownerInitialized=owner.get() && ba::get<bool>(owner.get(),"<IsInitialized>k__BackingField");
    const bool rootMatches=owner.get() && ba::get<Obj>(owner.get(),"<Root>k__BackingField")==main.get();
    const bool poolMatches=owner.get() && ba::get<Obj>(owner.get(),"_pool")==ba::get<Obj>(menu.get(),"_pool");
    static unsigned previousState=~0u;
    const unsigned state=static_cast<unsigned>(count)*32+found*8+(ownerInitialized?4:0)+(rootMatches?2:0)+(poolMatches?1:0);
    if(state!=previousState) {
        ba::log("PROFILE EDITS main recovery: acquiredViews=%u mainMatches=%u ownerInitialized=%d rootMatches=%d poolMatches=%d",
            static_cast<unsigned>(count),found,ownerInitialized?1:0,rootMatches?1:0,poolMatches?1:0);previousState=state;
    }
    require(found<=1,"profile edit main duplicated in acquired views");
    // UIMenuController.UpdateVisibility retains main directly, separately from
    // node-acquired views. Validate its own generation/descriptor instead.
    if(!ownerInitialized || !rootMatches || !poolMatches)return false;
    require(menu.get()==editBack->menu.get() && main.get()==editBack->main.get() && owner.get()==editBack->mainOwner.get() &&
        ba::get<Obj>(menu.get(),"_pool")==editBack->pool.get() && ba::get<Obj>(menu.get(),"_showMainMenu")==editBack->mainDescriptor.get() &&
        ba::get<int>(owner.get(),"<PrefabType>k__BackingField")==ba::get<int>(editBack->mainDescriptor.get(),"_prefabKey"),
        "profile edit persistent main generation changed");
    require(ba_client::nativeIdle(ownedFront->get()) && ba_client::worldOwner==ba_client::Owner::None &&
        ba_native_quit::staticInt("LoadingCount")==0,"profile edit return has active world/assets");
    Root navigation(ba::get<Obj>(ba::owner,"<NavigationStack>k__BackingField"));
    require(ba_native_quit::navCount(navigation.get())==0,"profile edit return has active navigation");
    require(normalize(rawSnapshot().first)==equipExpected && accepted==equipExpected && committed==equipExpected && !projectionPending,
        "profile edit Back changed committed cosmetics");
    validateProjection(accepted);picker.reset();editBack.reset();
    writeCosmeticProof(L"profile-edits-return","{\"schema\":1,\"passed\":true,\"original_back\":true,\"old_picker_released\":true,\"main_acquired\":true,\"navigation_empty\":true,\"world_idle\":true,\"loading_count\":0,\"full_map_preserved\":true,\"main_owned_by_menu_controller\":true,\"current_graph_matches\":"+
        std::string(graphMatches?"true":"false")+",\"direct_destination_matches\":"+(directDestination?"true":"false")+
        ",\"acquired_views\":"+std::to_string(count)+",\"main_matches_in_node_views\":"+std::to_string(found)+"}\n");
    ba::log("PROFILE EDITS returned: originalBack=1 oldPickerReleased=1 mainAcquired=1 navigationCount=0 worldIdle=1 loadingCount=0 fullMap=17");return true;
}
static void equipSmoke() {
    if(!ba::flag(L"-cosmetics-equip-smoke") || equipStage>=12)return;
    const bool combined=ba::flag(L"-profile-edits-smoke");
    if(!combined && equipStage==10)return;
    if(combined) {
        require(ba_profile_edit_policy::allowed(ba::arguments(),ba::argument(L"-local-profile=")),"profile edits require explicit owned gated diagnostic");
        if(!ba_practice_settings_ui::smokeComplete())return;
    }
    const auto now=GetTickCount64();if(!equipDeadline){equipDeadline=now+60000;equipDue=now+2500;return;}
    require(now<equipDeadline,"cosmetic equip diagnostic deadline");if(now<equipDue)return;
    require(persistenceReady && stateStore && unlockActive() && ba_dedicated_session::inMenu() &&
        ba_dedicated_session::worldIdle(ba::read<Obj>(ownedFront->get(),0xd8)),"cosmetic equip requires writable idle test profile");
    require(profileKey.rfind("cosmeticstest_",0)==0 || (combined && ba_native_settings::session &&
        ba_native_settings::session->profile()==profileKey && profileKey.rfind("nativestest_",0)==0),
        "cosmetic equip requires an explicit disposable test profile");
    if(equipStage==10) {editBackBegin();equipStage=11;equipDue=now+500;return;}
    if(equipStage==11) {if(editBackComplete())equipStage=12;return;}
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
    if(ba::flag(L"-cosmetics-equip-smoke") && equipStage!=(ba::flag(L"-profile-edits-smoke")?12u:10u))return;
    const auto actual=normalize(rawSnapshot().first);require(actual==accepted && !projectionPending,"cosmetic persistence proof stale");validateProjection(actual);
    writeCosmeticProof(L"cosmetics-persistence","{\"schema\":1,\"passed\":true,\"restored\":"+std::string(persistenceRestored?"true":"false")+
        ",\"writable\":"+(stateStore?"true":"false")+",\"read_error\":"+(persistenceReadError?"true":"false")+",\"projection12\":true,\"state\":"+
        ba_cosmetics_state::encode({profileKey,catalogHash,actual})+"}\n");
    complete=true;ba::log("COSMETICS PERSISTENCE PROOF passed: slots=17 restored=%d writable=%d projection12=1",persistenceRestored?1:0,stateStore?1:0);
}
}
