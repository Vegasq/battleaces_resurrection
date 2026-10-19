#pragma once
// Original owned menu callbacks only; opt-in diagnostics, never normal launch.
namespace ba_native_quit {
using ba::Obj;using ba_local::Root;namespace ui=ba_practice_settings_ui;
static void require(bool value,const char* why){if(!value)throw std::runtime_error(why);}
struct Probe {
    Root menu,main,pool,owner,show,quit,model,navigation;
    std::unique_ptr<Root> modal,modalOwner;
    Probe(Obj a,Obj b,Obj c,Obj d,Obj e,Obj f,Obj g,Obj h):menu(a),main(b),pool(c),owner(d),show(e),quit(f),model(g),navigation(h){}
};
static auto& probe=*new std::unique_ptr<Probe>();
static unsigned stage=0;static ULONGLONG deadline=0,due=0;
static int staticInt(const char* name) {
    auto field=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(ba::find_class("Uncapped","AsyncAssetTables"),name);
    require(field!=nullptr,"native Quit asset field missing");int value=0;
    ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(field,&value);return value;
}
static bool wantsQuit() {
    auto field=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(ba::find_class("Uncapped","AsyncAssetTables"),"WantsToQuit");
    require(field!=nullptr,"native Quit wants field missing");bool value=false;
    ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(field,&value);return value;
}
static void eventTarget(Obj event,Obj expected,const char* method) {
    ui::persistentTarget(event,expected,method);
    Root group(ba::get<Obj>(event,"m_PersistentCalls")),calls(ba::get<Obj>(group.get(),"m_Calls")),call(ui::item(calls.get(),0));
    require(ba::get<int>(call.get(),"m_Mode")==1 && ba::get<int>(call.get(),"m_CallState")==2,"native Quit persistent event mode/state differs");
}
static void clickTarget(Obj button,Obj expected,const char* method) {
    require(ui::exact(button,"Doozy.Runtime.UIManager.Components","UIButton") && ui::selectable(button) &&
        ba::get<bool>(button,"<selectableInitialized>k__BackingField"),"native Quit button unavailable");
    Root go(ui::gameObject(button)),container(ba::get<Obj>(button,"Behaviours")),values(ba::get<Obj>(container.get(),"Behaviours"));
    require(ba::get<Obj>(container.get(),"SignalSource")==go.get() && ba::get<Obj>(container.get(),"Selectable")==button,
        "native Quit button event owner mismatch");
    const int count=ba_local::count(values.get());require(count>=1 && count<=32,"native Quit behaviour list bound");
    unsigned found=0;
    for(int i=0;i<count;++i) {
        Root item(ui::item(values.get(),i));if(ba::get<int>(item.get(),"BehaviourName")!=7)continue;
        require(++found==1 && ba::get<Obj>(item.get(),"Selectable")==button,"native Quit click behaviour mismatch");
        Root event(ba::get<Obj>(item.get(),"Event"));eventTarget(event.get(),expected,method);
    }
    require(found==1,"native Quit PointerLeftClick event missing");
}
static void modelTarget(Obj model,Obj quit) {
    require(ui::exact(model,"Uncapped.UI","ModalConfirmModel") && !ba::get<bool>(model,"CloseOnConfirm") &&
        ba::get<bool>(model,"CloseOnCancel") && ba::get<int>(model,"DefaultCloseAction")==2,"native Quit model flags differ");
    Root meta(ba::get<Obj>(model,"Meta"));require(meta.get()!=nullptr,"native Quit model meta missing");
    Obj wanted=nullptr;void* iter=nullptr;
    while(Obj type=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_nested_types")(ba::find_class("Uncapped.UI","ModalConfirmModel"),&iter))
        if(!strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(type),"InvokeUnityEvent")){require(!wanted,"native Quit duplicate meta type");wanted=type;}
    require(wanted && ba::klass(meta.get())==wanted,"native Quit meta type mismatch");
    Root event(ba::get<Obj>(meta.get(),"ConfirmEvent"));eventTarget(event.get(),quit,"Quit");
    Root invoked(ba::get<Obj>(event.get(),"m_Calls")),runtime(ba::get<Obj>(invoked.get(),"m_RuntimeCalls"));
    require(ba_local::count(runtime.get())==0,"native Quit confirm has unqualified dynamic listeners");
    Root cancel(ba::get<Obj>(meta.get(),"CancelEvent")),group(ba::get<Obj>(cancel.get(),"m_PersistentCalls")),calls(ba::get<Obj>(group.get(),"m_Calls"));
    require(ba_local::count(calls.get())==0,"native Quit cancel event changed");
    Root cancelInvoked(ba::get<Obj>(cancel.get(),"m_Calls")),cancelRuntime(ba::get<Obj>(cancelInvoked.get(),"m_RuntimeCalls"));
    require(ba_local::count(cancelRuntime.get())==0,"native Quit cancel has unqualified dynamic listeners");
}
static int navCount(Obj navigation) {Root list(ba::get<Obj>(navigation,"_navigationStack"));return ba_local::count(list.get());}
static bool graphicsVisible(Obj modal) {
    // The shipped key52 prefab is ordinary graphics,not a Doozy UIContainer.
    // Check an actual visible title renderer,including inherited CanvasGroups.
    Root child(ui::findChild(modal,"ModalContainer/TitleText"));require(child.get(),"native Quit title path missing");
    Root text(ui::component(child.get(),"TMPro","TMP_Text")),renderer(ui::component(child.get(),"UnityEngine","CanvasRenderer"));
    require(text.get() && renderer.get(),"native Quit title graphics missing");
    if(!ui::active(text.get()) || !ba::native<bool(*)(Obj,Obj)>(0x5084710)(text.get(),nullptr))return false;
    Root label(ba::call(text.get(),"get_text"));if(ba_catalog::utf8(label.get()).empty())return false;
    Root alpha(ba::call(renderer.get(),"GetAlpha")),inherited(ba::call(renderer.get(),"GetInheritedAlpha")),culled(ba::call(renderer.get(),"get_cull"));
    const float own=ba_catalog::unbox<float>(alpha.get()),parents=ba_catalog::unbox<float>(inherited.get());
    return own>=.99f && own<=1.01f && parents>=.99f && parents<=1.01f && !ba_catalog::unbox<bool>(culled.get());
}
static void validateMain(Obj front) {
    require(ui::unityThread() && ba_local_menu::ready(front) && front==ba_dedicated_session::observedFront &&
        ba_dedicated_session::inMenu() && ba_client::nativeIdle(front) && ba_client::worldOwner==ba_client::Owner::None &&
        !ba_dedicated_session::joined && staticInt("LoadingCount")==0 && !wantsQuit(),"native Quit requires an owned idle unloaded menu");
    require(probe && ba::get<Obj>(ba::owner,"<UIMenuController>k__BackingField")==probe->menu.get() &&
        ba::get<Obj>(probe->menu.get(),"_mainMenu")==probe->main.get() && ui::active(probe->main.get()) &&
        ba::get<bool>(probe->main.get(),"_isInitialized") && ba::get<bool>(probe->owner.get(),"<IsInitialized>k__BackingField") &&
        ba::get<Obj>(probe->main.get(),"<Owner>k__BackingField")==probe->owner.get() &&
        ba::get<Obj>(probe->menu.get(),"_pool")==probe->pool.get(),"native Quit main generation changed");
    require(ba::get<Obj>(probe->show.get(),"_pool")==probe->pool.get() && ba::get<bool>(probe->quit.get(),"_isInitialized") &&
        ba::get<Obj>(probe->quit.get(),"<Owner>k__BackingField")==probe->owner.get(),"native Quit component lifecycle mismatch");
    Root descriptor(ba::get<Obj>(probe->show.get(),"_showUIObject"));
    require(ba::get<int>(descriptor.get(),"_prefabKey")==52 && ba::get<Obj>(descriptor.get(),"_model")==probe->model.get() &&
        !ba::get<bool>(descriptor.get(),"_overrideCanvasLayer") && !ba::get<Obj>(descriptor.get(),"_parent"),"native Quit show descriptor changed");
    require(ba::get<Obj>(ba::owner,"<NavigationStack>k__BackingField")==probe->navigation.get() &&
        ba::get<Obj>(probe->menu.get(),"_navigationStack")==probe->navigation.get(),"native Quit navigation ownership mismatch");
    modelTarget(probe->model.get(),probe->quit.get());
}
static void capture(const wchar_t* suffix=L"") {
    const auto path=ba_export::moduleDirectory()+L"investigation\\runtime\\native-quit-"+
        std::wstring(ba_native_settings::session->profile().begin(),ba_native_settings::session->profile().end())+suffix+L".png";
    require(GetFileAttributesW(path.c_str())==INVALID_FILE_ATTRIBUTES && GetLastError()==ERROR_FILE_NOT_FOUND,"native Quit capture exists");
    Obj render=ba::find_class("UnityEngine","RenderTexture");Root before(ba::invoke(render,nullptr,"get_active",0));
    auto restore=[&](){void* args[]={before.get()};ba::invoke(render,nullptr,"set_active",1,args);};
    void* clear[]={nullptr};ba::invoke(render,nullptr,"set_active",1,clear);
    std::unique_ptr<Root> texture;
    try {texture=std::make_unique<Root>(ba::invoke(ba::find_class("UnityEngine","ScreenCapture"),nullptr,"CaptureScreenshotAsTexture",0));}
    catch(...){restore();throw;}restore();Root actual(ba::invoke(render,nullptr,"get_active",0));
    require(actual.get()==before.get() && texture && texture->get(),"native Quit capture render state differs");
    auto destroy=[&](){void* args[]={texture->get()};ba::invoke(ba::find_class("UnityEngine","Object"),nullptr,"Destroy",1,args);};
    try {void* args[]={texture->get()};Root png(ba::invoke(ba::find_class("UnityEngine","ImageConversion"),nullptr,"EncodeToPNG",1,args));
        const auto length=ba_catalog::length(png.get());require(length>8 && length<16*1024*1024,"native Quit capture size bound");
        ba_export::atomicWrite(path,static_cast<const unsigned char*>(png.get())+0x20,length);
    }catch(...){destroy();throw;}destroy();
}
static bool gateReady() {
    if(!ba::flag(L"-native-quit-gate-smoke"))return true;
    require(ba_native_settings::session && ba_native_settings::session->profile().rfind("nativestest_",0)==0,
        "native Quit gate requires an owned profile");
    const auto& settings=ba_native_settings::session->path();
    const auto path=settings.substr(0,settings.find_last_of(L'\\')+1)+L"native-quit.ready";
    ba_native_settings::Handle file(CreateFileW(path.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,
        FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
    if(file.value==INVALID_HANDLE_VALUE) {
        require(GetLastError()==ERROR_FILE_NOT_FOUND,"native Quit gate is unavailable");return false;
    }
    ba_native_settings::ordinary(file.value);LARGE_INTEGER size{};
    require(GetFileSizeEx(file.value,&size) && size.QuadPart==0,"native Quit gate must be an empty ordinary file");
    static bool reported=false;if(!reported){reported=true;ba::log("NATIVE QUIT owned gate released: profile=%s BA_RESURRECTION_NATIVE_QUIT_GATE_V1",
        ba_native_settings::session->profile().c_str());}return true;
}
static void update(Obj front) {
    if(!ba::flag(L"-native-quit-smoke") || stage>=4)return;
    Obj dispatch=nullptr,dispatchMethod=nullptr;
    try {
        if(!gateReady())return; // Explicit external qualification gate only.
        if(ba::flag(L"-native-quit-after-practice")) {
            require(ba::localMenu() && ba::flag(L"-practice-ai-smoke") &&
                ba::argument(L"-practice-ai-smoke-matches=","1")=="1" && ba_practice::completed<=1,
                "native Quit post-practice requires exactly one owned local diagnostic match");
            if(ba_practice::completed!=1 || ba_practice::active())return;
        }
        const auto now=GetTickCount64();if(!deadline){deadline=now+60000;due=now+2500;return;}
        require(now<deadline,"native Quit menu diagnostic deadline");if(now<due)return;
        const auto mode=ba::argument(L"-native-quit-mode=","inventory");
        require(mode=="inventory" || mode=="cancel" || mode=="confirm","native Quit diagnostic mode invalid");
        if(stage==0) {
            Root menu(ba::get<Obj>(ba::owner,"<UIMenuController>k__BackingField")),main(ba::get<Obj>(menu.get(),"_mainMenu"));
            if(!main.get() || !ui::active(main.get()) || !ba::get<bool>(main.get(),"_isInitialized"))return;
            Root pool(ba::get<Obj>(menu.get(),"_pool")),owner(ba::get<Obj>(main.get(),"<Owner>k__BackingField"));
            Root child(ui::findChild(main.get(),"QuitButtonParent/QuitButton"));require(child.get(),"native Quit child missing");
            Root quit(ui::component(child.get(),"Uncapped.UI","UIQuitButton")),show(ui::component(child.get(),"Uncapped.UI","ShowUIObjectComponent"));
            Root button(ui::component(child.get(),"Doozy.Runtime.UIManager.Components","UIButton"));
            Root trigger(ui::component(child.get(),"Doozy.Runtime.UIManager.Triggers","PointerLeftClickTrigger"));
            require(quit.get() && show.get() && button.get() && trigger.get() && ui::active(quit.get()) &&
                ba::native<bool(*)(Obj,Obj)>(0x5084710)(show.get(),nullptr) && ba::native<bool(*)(Obj,Obj)>(0x5084710)(trigger.get(),nullptr),"native Quit components unavailable");
            Root descriptor(ba::get<Obj>(show.get(),"_showUIObject")),model(ba::get<Obj>(descriptor.get(),"_model"));
            Root navigation(ba::get<Obj>(ba::owner,"<NavigationStack>k__BackingField"));
            probe=std::make_unique<Probe>(menu.get(),main.get(),pool.get(),owner.get(),show.get(),quit.get(),model.get(),navigation.get());
            validateMain(front);clickTarget(button.get(),show.get(),"Show");
            require(navCount(navigation.get())==0 && !ba_catalog::unbox<bool>(ba::call(show.get(),"get_IsShown")),"native Quit requires empty navigation and no prior dialog");
            // Optional codec failure must not suppress the original Quit check.
            try{ba_native_replay_reader::probe();}
            catch(const std::exception& error){ba::log("NATIVE REPLAY codec readback failed: %s; originalQuitContinues=1",error.what());}
            validateMain(front);
            arm();ba::log("NATIVE QUIT owned menu verified: profile=%s mode=%s navigationCount=0 assetLoadingCount=0 worldIdle=1 persistentTargets=1",
                ba_native_settings::session->profile().c_str(),mode.c_str());
            if(mode=="inventory"){stage=4;ba::log("NATIVE QUIT inventory passed: callbacks=0");return;}
            stage=1;mark("Show.dispatch");ba::call(show.get(),"Show");mark("Show.return");due=now+2500;return;
        }
        validateMain(front);
        if(stage==1 || stage==3) {
            Root modal(ba::get<Obj>(probe->show.get(),"_uiObject"));
            static bool inventoried=false;
            if(stage==1 && !inventoried) {
                inventoried=true;Root owner(modal.get()?ba::get<Obj>(modal.get(),"<Owner>k__BackingField"):nullptr);
                Root container(owner.get()?ba::get<Obj>(owner.get(),"_uiContainer"):nullptr);
                ba::log("NATIVE QUIT waiting modal: exists=%d initialized=%d active=%d owner=%d ownerInitialized=%d container=%d containerVisible=%d navigationCount=%d class=%s",
                    modal.get()!=nullptr,modal.get() && ba::get<bool>(modal.get(),"_isInitialized"),modal.get() && ui::active(modal.get()),
                    owner.get()!=nullptr,owner.get() && ba::get<bool>(owner.get(),"<IsInitialized>k__BackingField"),container.get()!=nullptr,
                    container.get() && ba::native<bool(*)(Obj,Obj)>(0x88a350)(container.get(),nullptr),navCount(probe->navigation.get()),
                    modal.get()?ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(ba::klass(modal.get())):"null");
                due=now+500;return;
            }
            if(!modal.get() || !ba::get<bool>(modal.get(),"_isInitialized") || !ui::active(modal.get()))return;
            require(ui::exact(modal.get(),"Uncapped.UI","ModalConfirmVM"),"native Quit acquired wrong modal class");
            Root owner(ba::get<Obj>(modal.get(),"<Owner>k__BackingField"));
            require(ba_catalog::unbox<bool>(ba::call(modal.get(),"get_IsModelSet")) && ba::get<Obj>(modal.get(),"_model")==probe->model.get() &&
                ba::get<bool>(owner.get(),"<IsInitialized>k__BackingField") && ba::get<Obj>(owner.get(),"<Root>k__BackingField")==modal.get() &&
                ba::get<int>(owner.get(),"<PrefabType>k__BackingField")==52 && ba::get<Obj>(owner.get(),"_pool")==probe->pool.get() &&
                ba::get<Obj>(modal.get(),"_navigationStack")==probe->navigation.get(),"native Quit acquired model/lifetime mismatch");
            if(!graphicsVisible(modal.get()))return;
            Root list(ba::get<Obj>(probe->navigation.get(),"_navigationStack"));
            require(ba_local::count(list.get())==1 && ui::item(list.get(),0)==modal.get(),"native Quit is not the current navigation entry");
            for(const char* name:{"CancelButton","ConfirmButton"}) {
                const auto path=std::string("ModalContainer/Buttons/")+name;Root child(ui::findChild(modal.get(),path.c_str()));
                Root button(ui::component(child.get(),"Doozy.Runtime.UIManager.Components","UIButton"));
                clickTarget(button.get(),modal.get(),!strcmp(name,"CancelButton")?"OnCancel":"OnConfirm");
            }
            if(stage==1) {
                probe->modal=std::make_unique<Root>(modal.get());probe->modalOwner=std::make_unique<Root>(owner.get());
                const bool captured=ba::flag(L"-native-quit-capture");if(captured)capture();
                ba::log("NATIVE QUIT owned confirmation verified: mode=%s prefab=52 currentNavigation=1 nativeModel=1 captured=%d",mode.c_str(),captured);
                // Let the capture's deferred texture Destroy complete before
                // probing shutdown; revalidate the same owner on a later frame.
                stage=3;due=now+1000;return;
            }
            require(probe->modal && probe->modal->get()==modal.get() && probe->modalOwner->get()==owner.get(),"native Quit confirmation generation changed");
            if(mode=="cancel") {stage=2;mark("OnCancel.dispatch");ba::call(modal.get(),"OnCancel");mark("OnCancel.return");due=now+1000;return;}
            dispatch=modal.get();dispatchMethod=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(ba::klass(dispatch),"OnConfirm",0);
            require(dispatchMethod!=nullptr,"native Quit original confirmation method missing");stage=4;
            mark("OnConfirm.dispatch");ba::log("NATIVE QUIT original confirmation dispatch: thread=%lu worldIdle=1 assetLoadingCount=0 naturalExitDeadlineSeconds=60",GetCurrentThreadId());
        }else if(stage==2) {
            require(!ba::get<Obj>(probe->show.get(),"_uiObject") && !ba_catalog::unbox<bool>(ba::call(probe->show.get(),"get_IsShown")) &&
                !ba::get<bool>(probe->modalOwner->get(),"<IsInitialized>k__BackingField") && navCount(probe->navigation.get())==0 && !wantsQuit(),
                "native Quit Cancel did not restore the original menu");
            probe->modal.reset();probe->modalOwner.reset();stage=4;mark("Cancel.verified");ba::log("NATIVE QUIT cancel passed: nativeRelease=1 navigationCount=0 menuRetained=1 quitRequested=0");
        }
    }catch(const std::exception& error){stage=4;mark("probe.failed");ba::log("Native Quit probe failed: %s",error.what());return;}
    // No diagnostic managed allocation/inspection or local GC-root destruction
    // after the original confirmation callback. Its true MethodInfo is retained.
    if(dispatch) {
        Obj exception=nullptr;ba::api<Obj(*)(Obj,Obj,void**,Obj*)>("il2cpp_runtime_invoke")(dispatchMethod,dispatch,nullptr,&exception);
        mark(exception?"OnConfirm.exception":"OnConfirm.return");
    }
}
}
