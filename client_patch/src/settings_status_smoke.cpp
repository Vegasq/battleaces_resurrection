#pragma once
// Explicit owned-client diagnostics only. Invoke original UI callbacks and read
// the authored footer; do not write settings, create game state, or fake status.
namespace ba_settings_status_smoke {
using ba::Obj;using ba_local::Root;
namespace ui=ba_practice_settings_ui;
static unsigned stage=0,generation=0;
static ULONGLONG due=0,deadline=0;
static bool finished=false;
static auto& retired=*new std::unique_ptr<Root>();
static auto& controller=*new std::unique_ptr<Root>();
static auto& show=*new std::unique_ptr<Root>();
static std::wstring capturePath;
static bool matchMode(){return ba::flag(L"-settings-status-smoke-match");}
static bool offlineMode(){return ba::flag(L"-settings-status-smoke-offline");}
static void next(unsigned value,unsigned delay=500) {stage=value;due=GetTickCount64()+delay;deadline=GetTickCount64()+30000;}
static Obj screen() {
    if(!matchMode())return ui::settingsScreen();
    if(!show)return nullptr;
    Obj value=ba::get<Obj>(show->get(),"_uiObject");
    if(!value || !ba::get<bool>(value,"_isInitialized") || !ui::active(value))return nullptr;
    ui::require(ui::exact(value,"Uncapped.UI","UIOptionsMenu") && ui::row && ui::row->screen.get()==value,
        "status smoke acquired in-match Settings ownership differs");
    return value;
}
static bool openMatch(Obj front) {
    if(ba_client::worldOwner!=ba_client::Owner::Remote || ba_dedicated_session::inMenu())return false;
    Root server(ba::read<Obj>(front,0xd8)),sim(ba::read<Obj>(server.get(),0x140));
    if(!sim.get() || !ba::read<bool>(sim.get(),0x1a0) || ba::read<int>(sim.get(),0xac)<40)return false;
    Root type(ui::reflectedType("Uncapped","ConcedeFlowUIController"));void* args[]={type.get()};
    Root values(ba::invoke(ba::find_class("UnityEngine","Resources"),nullptr,"FindObjectsOfTypeAll",1,args));
    for(size_t i=0;i<ui::arrayCount(values.get(),64);++i) {
        Obj value=ui::arrayItem(values.get(),i);
        if(ba::get<Obj>(value,"_simulation")!=sim.get() || !ui::active(value))continue;
        ui::require(!controller,"status smoke ambiguous in-match controller");controller=std::make_unique<Root>(value);
    }
    if(!controller)return false;
    ui::require(ba::get<Obj>(controller->get(),"_signalRouter")==ba::read<Obj>(ba::owner,0x238),
        "status smoke in-match signal owner differs");
    // Original build37822 TryShowOptionsConcedeView, also used by replay smoke.
    ba::native<void(*)(Obj,Obj)>(0x3b44490)(controller->get(),nullptr);
    ba::log("SETTINGS STATUS SMOKE original in-match options opened: remoteWorld=1 nativeCallback=1");return true;
}
static bool clickMatchSettings() {
    ui::require(controller!=nullptr,"status smoke controller missing");
    Root source(ba::get<Obj>(controller->get(),"_showOptionsComponent"));
    Root path(ui::findChild(controller->get(),"OptionsSelector/VerticalButtons/ShowOptionsMenuButton"));
    ui::require(ui::exact(source.get(),"Uncapped.UI","ShowUIObjectComponent") && path.get() &&
        ui::component(path.get(),"Uncapped.UI","ShowUIObjectComponent")==source.get(),"status smoke in-match Settings hierarchy differs");
    Root button(ui::component(path.get(),"Doozy.Runtime.UIManager.Components","UIButton"));
    Root id(ba::get<Obj>(button.get(),"Id"));
    ui::require(ui::exact(button.get(),"Doozy.Runtime.UIManager.Components","UIButton") && id.get() &&
        !ba::get<bool>(id.get(),"Custom") && ba_catalog::utf8(ba::get<Obj>(id.get(),"Category"))=="Game" &&
        ba_catalog::utf8(ba::get<Obj>(id.get(),"Name"))=="ShowOptionsMenu","status smoke in-match button ID differs");
    if(!ui::selectable(button.get()))return false;
    Root input(ui::component(path.get(),"Uncapped","BindUISelectableToInputAction"));
    Root event(ba::get<Obj>(input.get(),"ClickEvent")),group(ba::get<Obj>(event.get(),"m_PersistentCalls"));
    Root calls(ba::get<Obj>(group.get(),"m_Calls"));
    ui::require(calls.get() && ba_local::count(calls.get())==2,"status smoke in-match click binding count differs");
    for(int i=0;i<2;++i) {
        Root call(ui::item(calls.get(),i));
        ui::require(ba::get<Obj>(call.get(),"m_Target")== (i?ba::get<Obj>(controller->get(),"_optionsConcedeView"):source.get()) &&
            ba_catalog::utf8(ba::get<Obj>(call.get(),"m_MethodName"))==(i?"Hide":"Show") &&
            ba::get<int>(call.get(),"m_CallState")!=0,"status smoke in-match click binding target differs");
    }
    show=std::make_unique<Root>(source.get());
    // Unlike MainMenu's Doozy signal route, this button's native input binder
    // owns the Show/Hide callback chain. UIButton.Click alone does not invoke
    // it. Dispatch its verified existing UnityEvent without replacing handlers.
    ba::call(event.get(),"Invoke");
    ba::log("SETTINGS STATUS SMOKE original in-match Settings ClickEvent: bindingTargetsVerified=1 serializedCallbacks=1 mouseInput=0");return true;
}
static void verify(const char* phase,bool online) {
    const auto& value=ba_settings_status_ui::view;Obj current=screen();
    ui::require(current && ui::row && value && !ba_settings_status_ui::failed &&
        value->screen.get()==current && value->generation==ui::releases && ui::active(value->text.get()),
        "status smoke footer missing or wrong owner");
    Root text(ba::call(value->text.get(),"get_text"));const auto actual=ba_catalog::utf8(text.get());
    ui::require(actual==ba_settings_status_ui::label() && actual.find("Resurrection "+ba_settings_connection::buildLabel())!=std::string::npos &&
        ba_settings_connection::statusLine().rfind(online?"Online":"Offline",0)==0 && actual.find("Server: ")!=std::string::npos,
        "status smoke expected footer state differs");
    Root raycast(ba::call(value->text.get(),"get_raycastTarget")),rich(ba::call(value->text.get(),"get_richText"));
    ui::require(!ba_match_loading::boolean(raycast.get()) && !ba_match_loading::boolean(rich.get()),"status smoke footer input/markup policy differs");
    Root parent(ba::call(ba::call(value->object.get(),"get_transform"),"get_parent"));
    ui::require(parent.get()==ui::findChild(current,"GameObject"),"status smoke footer is outside native Settings panel");
    Root children(ba::call(parent.get(),"get_childCount"));unsigned matches=0;
    const int count=ui::integer(children.get());ui::require(count>=1 && count<=64,"status smoke panel child bound");
    for(int i=0;i<count;++i) {
        void* args[]={&i};Root child(ba::call(parent.get(),"GetChild",1,args)),name(ba::call(child.get(),"get_name"));
        if(ba_catalog::utf8(name.get())=="BattleAcesResurrectionSettingsStatus")++matches;
    }
    ui::require(matches==1,"status smoke duplicate footer child");
    ba::log("SETTINGS STATUS SMOKE readback: phase=%s online=%d active=1 ownedLabels=1 raycast=0 richText=0 text=%s",
        phase,online,ba_catalog::quote(actual).c_str());
}
static void capture(const char* phase) {
    const std::string suffix="settings-status-"+std::to_string(GetCurrentProcessId())+"-"+phase+".png";
    capturePath=ba_export::moduleDirectory()+L"investigation\\runtime\\"+std::wstring(suffix.begin(),suffix.end());
    ui::require(GetFileAttributesW(capturePath.c_str())==INVALID_FILE_ATTRIBUTES && GetLastError()==ERROR_FILE_NOT_FOUND,
        "status smoke capture path already exists");
    Root name(ba::api<Obj(*)(const wchar_t*,int32_t)>("il2cpp_string_new_utf16")(capturePath.data(),static_cast<int32_t>(capturePath.size())));
    void* args[]={name.get()};ba::invoke(ba::find_class("UnityEngine","ScreenCapture"),nullptr,"CaptureScreenshot",1,args);
    ba::log("SETTINGS STATUS SMOKE capture scheduled: phase=%s engineFile=1",phase);
}
static bool captured() {
    WIN32_FILE_ATTRIBUTE_DATA data{};
    if(!GetFileAttributesExW(capturePath.c_str(),GetFileExInfoStandard,&data))return false;
    ui::require(!(data.dwFileAttributes&(FILE_ATTRIBUTE_DIRECTORY|FILE_ATTRIBUTE_REPARSE_POINT)) && !data.nFileSizeHigh,
        "status smoke invalid capture file");
    return data.nFileSizeLow>1024;
}
static bool close() {
    Obj current=screen();if(!current)return false;
    Root path(ui::findChild(current,"GameObject/Bottom Buttons/BackButton"));
    Root button(ui::component(path.get(),"Doozy.Runtime.UIManager.Components","UIButton"));ui::checkButton(button.get(),"Back");
    if(!ui::selectable(button.get()))return false;
    ui::require(ba_settings_status_ui::view!=nullptr,"status smoke footer missing before close");
    retired=std::make_unique<Root>(ba_settings_status_ui::view->object.get());generation=ui::releases;
    ba::native<void(*)(Obj,Obj)>(0x89fe30)(button.get(),nullptr);return true;
}
static bool released() {
    if(ui::releases==generation || ba_settings_status_ui::view || ui::row)return false;
    if(retired && ba::read<Obj>(retired->get(),0x10))return false;
    retired.reset();ba::log("SETTINGS STATUS SMOKE released: nativeOwnerReleased=1 ownedChildDestroyed=1");return true;
}
static void update(Obj front) {
    if(!ba::flag(L"-settings-status-smoke") || finished)return;
    try {
        ui::require(ui::unityThread() && ba::unified(),"status smoke requires owned unified Unity client");
        const auto now=GetTickCount64();if(!deadline){next(0,2500);deadline=now+90000;return;}
        if(now<due)return;ui::require(now<deadline,"status smoke stage deadline");
        ui::require(!ba_settings_status_ui::failed,"status renderer failed");
        if(stage==0) {
            if(matchMode()){if(openMatch(front))next(10);}
            else if(ba_local_menu::ready(front) && ba_dedicated_session::inMenu() && ui::openSettings())next(1);
        }else if(stage==10) {if(clickMatchSettings())next(1);}
        else if(stage==1) {
            if(!screen() || !ba_settings_status_ui::view)return;
            verify("initial",!offlineMode());capture("initial");next(2);
        }else if(stage==2) {
            if(!captured() || !ui::selectGeneral(screen(),true))return;next(3);
        }else if(stage==3) {
            verify("general",!offlineMode());capture("general");next(4);
        }else if(stage==4) {if(captured() && close())next(5);}
        else if(stage==5) {
            if(!released())return;
            if(matchMode()){finished=true;controller.reset();show.reset();ba::log("SETTINGS STATUS SMOKE passed: scope=in-match online=1 released=1 nativeCallbacks=1");}
            else if(ui::openSettings())next(6);
        }else if(stage==6) {
            if(!screen() || !ui::selectGeneral(screen(),true))return;next(7);
        }else if(stage==7) {
            verify("reopened",!offlineMode());capture("reopened");
            ba::log("SETTINGS STATUS SMOKE ready for owned disconnect: offlineMode=%d",offlineMode());next(8);
        }else if(stage==8) {
            if(!captured())return;
            if(!offlineMode() && ba_settings_connection::statusLine().rfind("Offline",0)!=0)return;
            verify("offline",false);capture("offline");next(9);
        }else if(stage==9) {if(captured() && close())next(11);}
        else if(stage==11 && released()) {
            finished=true;ba::log("SETTINGS STATUS SMOKE passed: scope=menu onlineDrop=%d reopen=1 released=1 nativeCallbacks=1",!offlineMode());
        }
    }catch(const std::exception& error) {finished=true;ba::log("SETTINGS STATUS SMOKE failed: stage=%u reason=%s",stage,error.what());}
}
}
