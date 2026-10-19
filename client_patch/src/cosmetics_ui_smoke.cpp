#pragma once
// Explicit UI diagnostics only. Captured hierarchy/IDs stay in ignored files.
namespace ba_cosmetics {
static bool traced=false;
static void traceButtons(Obj transform,const std::string& parent,unsigned depth,unsigned& nodes,std::string& rows) {
    namespace ui=ba_practice_settings_ui;
    require(depth<=32 && ++nodes<=8192,"cosmetic UI trace tree limit");
    const std::string path=parent+"/"+ui::objectName(transform);
    Root button(ui::component(transform,"Doozy.Runtime.UIManager.Components","UIButton"));
    if(button.get()) {
        Root id(ba::get<Obj>(button.get(),"Id"));require(id.get()!=nullptr,"cosmetic UI trace button ID missing");
        if(!rows.empty())rows+=',';
        rows+="{\"path\":"+ba_catalog::quote(path)+",\"category\":"+ba_catalog::quote(ba_catalog::utf8(ba::get<Obj>(id.get(),"Category")))+
            ",\"name\":"+ba_catalog::quote(ba_catalog::utf8(ba::get<Obj>(id.get(),"Name")))+",\"active\":"+(ui::active(button.get())?"true":"false")+"}";
    }
    const int count=ba_catalog::unbox<int>(ba::call(transform,"get_childCount"));require(count>=0 && count<=1024,"cosmetic UI trace children limit");
    for(int i=0;i<count;++i) {void* args[]={&i};Root child(ba::call(transform,"GetChild",1,args));require(child.get()!=nullptr,"cosmetic UI trace child missing");traceButtons(child.get(),path,depth+1,nodes,rows);}
}
static void uiTrace() {
    if(traced || !ba::flag(L"-cosmetics-ui-trace"))return;
    namespace ui=ba_practice_settings_ui;
    Root menu(ba::get<Obj>(ba::owner,"<UIMenuController>k__BackingField")),main(ba::get<Obj>(menu.get(),"_mainMenu"));
    if(!main.get() || !ba::get<bool>(main.get(),"_isInitialized") || !ui::active(main.get()))return;
    Root transform(ba::call(main.get(),"get_transform")),root(ba::call(transform.get(),"get_root"));
    unsigned nodes=0;std::string rows;traceButtons(root.get(),"",0,nodes,rows);
    const std::string text="{\"schema\":1,\"nodes\":"+std::to_string(nodes)+",\"buttons\":["+rows+"]}\n";
    const auto path=ba_export::moduleDirectory()+L"investigation\\runtime\\cosmetics-ui-trace-"+std::to_wstring(GetCurrentProcessId())+L".json";
    require(GetFileAttributesW(path.c_str())==INVALID_FILE_ATTRIBUTES && GetLastError()==ERROR_FILE_NOT_FOUND,"cosmetic UI trace output unavailable");
    ba_export::atomicWrite(path,reinterpret_cast<const unsigned char*>(text.data()),text.size());traced=true;
    ba::log("COSMETICS UI TRACE complete: nodes=%u readOnly=1",nodes);
}
static unsigned pickerStage=0,pickerIndex=0,pickerCases=0,pickerEmpty=0,pickerAll=0;
static ULONGLONG pickerDue=0,pickerDeadline=0;
static uint32_t originalSlot=0;static int originalFilter=0;static bool originalSlotValid=false;
static auto& picker=*new std::unique_ptr<Root>();
static auto& pickerBefore=*new std::vector<uint32_t>();
static auto& pickerRows=*new std::string();
static void findPicker(Obj transform,unsigned depth,unsigned& nodes) {
    namespace ui=ba_practice_settings_ui;
    require(depth<=32 && ++nodes<=8192,"cosmetic picker tree limit");
    Root vm(ui::component(transform,"Uncapped.UI","SelectCosmeticVM"));
    if(vm.get() && ui::active(vm.get()) && ba::get<bool>(vm.get(),"_isInitialized")) {
        require(!picker,"multiple active cosmetic pickers");picker=std::make_unique<Root>(vm.get());
    }
    const int count=ba_catalog::unbox<int>(ba::call(transform,"get_childCount"));require(count>=0 && count<=1024,"cosmetic picker child limit");
    for(int i=0;i<count;++i){void* args[]={&i};Root child(ba::call(transform,"GetChild",1,args));findPicker(child.get(),depth+1,nodes);}
}
static void checkPicker() {
    namespace ui=ba_practice_settings_ui;Obj vm=picker->get();
    require(unlockActive() && vm && ui::active(vm) && ba::get<bool>(vm,"_isInitialized") &&
        ba::get<bool>(vm,"<IsModelSet>k__BackingField") && ba::get<Obj>(vm,"_cosmetics")==ownedCosmetics->get() &&
        ba::get<Obj>(vm,"_clientConfig")==ba::get<Obj>(ba::owner,"_clientGlobalConfig") &&
        ba::get<Obj>(vm,"_signalRouter")==ba::get<Obj>(ownedFront->get(),"_signalRouter"),"cosmetic picker lifetime/dependency mismatch");
    Root owner(ba::get<Obj>(vm,"<Owner>k__BackingField")),model(ba::get<Obj>(vm,"_model"));
    require(owner.get() && ba::get<bool>(owner.get(),"<IsInitialized>k__BackingField") && model.get() &&
        ba::klass(model.get())==ba::find_class("Uncapped.UI","SelectCosmeticModel"),"cosmetic picker native model ownership");
}
static std::vector<uint32_t> compatible(Obj slot) {
    std::vector<uint32_t> result;Root items(ba::call(ba_public_bots::cosmetics.get(),"get_Elements"));
    for(size_t i=0;i<ba_catalog::length(items.get());++i) {
        Root item(ba_catalog::arrayAt(items.get(),i)),definition(ba::call(item.get(),"get_Definition"));
        void* args[]={definition.get()};Root yes(ba::call(slot,"FilterItem",1,args));
        if(ba_tables::boolean(yes.get()))result.push_back(ba_catalog::unbox<uint32_t>(ba::call(item.get(),"get_ID")));
    }
    return result;
}
static void checkItems(uint32_t slot,int filter,const std::vector<uint32_t>& expected) {
    checkPicker();void* args[]={&filter};ba::call(picker->get(),"OnFilterValueChanged",1,args);
    Root model(ba::get<Obj>(picker->get(),"_model")),items(ba::get<Obj>(picker->get(),"_selectCosmeticItems"));
    const uint32_t modelSlot=ba::get<uint32_t>(model.get(),"Slot"),vmSlot=ba::get<uint32_t>(picker->get(),"_slot");
    // Native model Slot0 is a valid dynamic/default view. Selecting the already
    // resolved slot is a no-op and deliberately does not replace that model.
    require(vmSlot==slot && (!modelSlot || modelSlot==slot) && ba::get<int>(model.get(),"Filter")==filter &&
        ba::get<int>(picker->get(),"_filter")==filter,"cosmetic picker selection/filter readback");
    const int count=ba_local::count(items.get());require(count>=0 && count<=4096,"cosmetic picker list bounds");
    require(static_cast<size_t>(count)==(filter==2?0:expected.size()),"cosmetic picker filtered item count mismatch");
    std::vector<uint32_t> actual;
    for(int i=0;i<count;++i) {
        Root item(ba_practice_settings_ui::item(items.get(),i));const uint32_t id=ba::get<uint32_t>(item.get(),"Item");
        require(contains(expected,id) && !contains(actual,id) && ba::get<bool>(item.get(),"<Owned>k__BackingField"),"cosmetic picker unknown/duplicate/unowned item");actual.push_back(id);
    }
    if(filter==0)pickerAll+=count;++pickerCases;
}
static void pickerSmoke() {
    if(!ba::flag(L"-cosmetics-picker-smoke") || pickerStage==5)return;
    namespace ui=ba_practice_settings_ui;const auto now=GetTickCount64();
    if(!pickerDeadline){pickerDeadline=now+60000;pickerDue=now+2500;return;}
    require(now<pickerDeadline,"cosmetic picker diagnostic deadline");if(now<pickerDue)return;
    require(unlockActive() && ba_dedicated_session::inMenu() && ba_dedicated_session::worldIdle(ba::read<Obj>(ownedFront->get(),0xd8)),"cosmetic picker requires idle local menu");
    if(pickerStage==0) {
        Root menu(ba::get<Obj>(ba::owner,"<UIMenuController>k__BackingField")),main(ba::get<Obj>(menu.get(),"_mainMenu"));
        if(!main.get() || !ba::get<bool>(main.get(),"_isInitialized") || !ui::active(main.get()))return;
        Root transform(ui::findChild(main.get(),"LeftMenus/LeftButtons/CosmeticsButton"));require(transform.get()!=nullptr,"cosmetic picker button hierarchy missing");
        Root button(ui::component(transform.get(),"Doozy.Runtime.UIManager.Components","UIButton"));ui::checkButton(button.get(),"CosmeticScreen");
        if(!ui::selectable(button.get()))return;pickerBefore=saved(ownedCosmetics->get());
        ba::native<void(*)(Obj,Obj)>(0x89fe30)(button.get(),nullptr);pickerStage=1;pickerDue=now+350;
        ba::log("COSMETICS PICKER SMOKE original MainMenu/CosmeticScreen button Click (automated callback)");return;
    }
    if(pickerStage==1) {
        Root menu(ba::get<Obj>(ba::owner,"<UIMenuController>k__BackingField")),main(ba::get<Obj>(menu.get(),"_mainMenu"));
        Root transform(ba::call(main.get(),"get_transform")),root(ba::call(transform.get(),"get_root"));unsigned nodes=0;findPicker(root.get(),0,nodes);
        if(!picker)return;checkPicker();Root model(ba::get<Obj>(picker->get(),"_model"));
        originalSlot=ba::get<uint32_t>(picker->get(),"_slot");originalFilter=ba::get<int>(model.get(),"Filter");
        originalSlotValid=slots.at(originalSlot)!=nullptr;
        ba::log("COSMETICS PICKER SMOKE initial view: modelSlot=%u vmSlot=%u filter=%d slotValid=%d",ba::get<uint32_t>(model.get(),"Slot"),originalSlot,originalFilter,originalSlotValid?1:0);
        require(originalFilter>=0 && originalFilter<=2,"cosmetic picker initial filter invalid");
        pickerStage=2;
    }
    if(pickerStage==3) {
        const auto path=ba_export::moduleDirectory()+L"investigation\\runtime\\cosmetics-picker-"+std::to_wstring(GetCurrentProcessId())+L".png";
        Root name(ba::api<Obj(*)(const wchar_t*,int)>("il2cpp_string_new_utf16")(path.data(),static_cast<int>(path.size())));void* args[]={name.get()};
        ba::invoke(ba::find_class("UnityEngine","ScreenCapture"),nullptr,"CaptureScreenshot",1,args);pickerStage=2;++pickerIndex;pickerDue=now+350;return;
    }
    if(pickerStage==2) {
        checkPicker();Root all(ba::call(slots.get(),"get_Elements"));
        if(pickerIndex<ba_catalog::length(all.get())) {
            Root slot(ba_catalog::arrayAt(all.get(),pickerIndex));const auto expected=compatible(slot.get());
            if(expected.empty()){++pickerEmpty;++pickerIndex;return;}
            uint32_t id=ba_catalog::unbox<uint32_t>(ba::call(slot.get(),"get_ID"));void* args[]={&id};
            ba::call(picker->get(),"OnCosmeticSlotSelected",1,args);
            for(int filter=0;filter<3;++filter)checkItems(id,filter,expected);
            int filter=0;void* filterArgs[]={&filter};ba::call(picker->get(),"OnFilterValueChanged",1,filterArgs);
            if(!pickerRows.empty())pickerRows+=',';pickerRows+="{\"slot\":"+std::to_string(id)+",\"all\":"+std::to_string(expected.size())+",\"owned\":"+std::to_string(expected.size())+",\"unowned\":0}";
            Root config(ba::get<Obj>(ba::owner,"_clientGlobalConfig"));
            if(id==ba::get<uint32_t>(config.get(),"PortraitCosmeticSlot")){pickerStage=3;pickerDue=now+500;return;}
            ++pickerIndex;pickerDue=now+250;return;
        }
        if(originalSlotValid){void* args[]={&originalSlot};ba::call(picker->get(),"OnCosmeticSlotSelected",1,args);}
        void* filterArgs[]={&originalFilter};ba::call(picker->get(),"OnFilterValueChanged",1,filterArgs);
        pickerStage=4;pickerDue=now+500;return;
    }
    if(pickerStage==4) {
        checkPicker();require(saved(ownedCosmetics->get())==pickerBefore,"cosmetic picker browsing changed loadout");
        const std::string text="{\"schema\":1,\"passed\":true,\"filter_cases\":"+std::to_string(pickerCases)+",\"empty_slots_skipped\":"+
            std::to_string(pickerEmpty)+",\"all_items_across_slots\":"+std::to_string(pickerAll)+",\"initial_slot_valid\":"+(originalSlotValid?"true":"false")+
            ",\"loadout_unchanged\":true,\"slots\":["+pickerRows+"]}\n";
        const auto path=ba_export::moduleDirectory()+L"investigation\\runtime\\cosmetics-picker-"+std::to_wstring(GetCurrentProcessId())+L".json";
        require(GetFileAttributesW(path.c_str())==INVALID_FILE_ATTRIBUTES && GetLastError()==ERROR_FILE_NOT_FOUND,"cosmetic picker proof output unavailable");
        ba_export::atomicWrite(path,reinterpret_cast<const unsigned char*>(text.data()),text.size());pickerStage=5;
        ba::log("COSMETICS PICKER SMOKE passed: cases=%u allItems=%u emptySlotsSkipped=%u originalCallbacks=1 loadoutUnchanged=1 noEquip=1",pickerCases,pickerAll,pickerEmpty);
    }
}
}
