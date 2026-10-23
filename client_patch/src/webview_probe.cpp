#pragma once
#include "webview_probe_policy.hpp"
#include "webview_probe_entries.hpp"
#include <cmath>
// Owned diagnostic only. Original managed callbacks and Unity rendering own the view.
namespace ba_webview_probe {
using ba::Obj;using ba_local::Root;
struct V2 {float x,y;};struct Rect {float x,y,width,height;};struct Size {int width,height;};
struct Control {
    unsigned stage=0;ULONGLONG deadline=0,due=0,sampled=0;DWORD thread=0;
    bool started=false,mayCleanup=false,initialized=false,pageLoaded=false,disposed=false,destroyed=false,destroyConfirmed=false,stopCompleted=false,failed=false;
    float rectWidth=0,rectHeight=0;int width=0,height=0;std::string error,cache;
    bool componentEnabled=false,componentActive=false,cachedView=false,initializingView=false,viewObject=false;
    bool initializingReady=false,initializingDisposed=false,initializingNative=false;
    std::unique_ptr<Root> prefab,view,init,page,stop;
};
static auto& state=*new Control();
static void require(bool ok,const char* text){if(!ok)throw std::runtime_error(text);}
static bool boolean(Obj o,const char* name) {
    Root b(ba::call(o,name));require(b.get()!=nullptr,"WebView Boolean result absent");
    return *ba::api<bool*(*)(Obj)>("il2cpp_object_unbox")(b.get());
}
static bool completed(Obj task) {
    require(task!=nullptr,"WebView task absent");if(!boolean(task,"get_IsCompleted"))return false;
    require(!boolean(task,"get_IsCanceled") && !boolean(task,"get_IsFaulted"),"WebView managed task failed or canceled");return true;
}
static std::string utf8(const std::wstring& value) {
    const int n=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,value.c_str(),static_cast<int>(value.size()),nullptr,0,nullptr,nullptr);
    require(n>0,"WebView cache path encoding");std::string out(n,'\0');
    require(WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,value.c_str(),static_cast<int>(value.size()),&out[0],n,nullptr,nullptr)==n,"WebView cache path conversion");return out;
}
static Obj standalone(){return ba::find_class("Vuplex.WebView","StandaloneWebView");}
static void publish(const char* phase) {
    const std::string text="{\"schema\":1,\"pid\":"+std::to_string(GetCurrentProcessId())+",\"phase\":"+ba_catalog::quote(phase)+
        ",\"stage\":"+std::to_string(state.stage)+",\"thread\":"+std::to_string(state.thread)+
        ",\"initialized\":"+(state.initialized?"true":"false")+",\"page_loaded\":"+(state.pageLoaded?"true":"false")+
        ",\"disposed\":"+(state.disposed?"true":"false")+",\"prefab_destroy_requested\":"+(state.destroyed?"true":"false")+
        ",\"prefab_destroyed\":"+(state.destroyConfirmed?"true":"false")+
        ",\"stop_task_completed\":"+(state.stopCompleted?"true":"false")+",\"failed\":"+(state.failed?"true":"false")+
        ",\"component_enabled\":"+(state.componentEnabled?"true":"false")+",\"component_active\":"+(state.componentActive?"true":"false")+
        ",\"cached_view\":"+(state.cachedView?"true":"false")+",\"supplied_view\":"+(state.initializingView?"true":"false")+
        ",\"view_object\":"+(state.viewObject?"true":"false")+",\"supplied_ready\":"+(state.initializingReady?"true":"false")+
        ",\"supplied_disposed\":"+(state.initializingDisposed?"true":"false")+",\"supplied_native\":"+(state.initializingNative?"true":"false")+
        ",\"rect_width\":"+std::to_string(state.rectWidth)+",\"rect_height\":"+std::to_string(state.rectHeight)+
        ",\"width\":"+std::to_string(state.width)+",\"height\":"+std::to_string(state.height)+
        ",\"cache\":"+ba_catalog::quote(state.cache)+",\"error\":"+ba_catalog::quote(state.error)+"}\n";
    const auto path=ba_export::moduleDirectory()+L"investigation\\runtime\\webview-proof-"+std::to_wstring(GetCurrentProcessId())+L".json";
    ba_export::atomicWrite(path,reinterpret_cast<const unsigned char*>(text.data()),text.size());
    ba::log("WEBVIEW PROBE %s: stage=%u initialized=%d pageLoaded=%d disposed=%d prefabDestroyed=%d stopTask=%d failed=%d",
        phase,state.stage,state.initialized?1:0,state.pageLoaded?1:0,state.disposed?1:0,state.destroyed?1:0,state.stopCompleted?1:0,state.failed?1:0);
}
static void verifyEntries() {
    const auto module=reinterpret_cast<const unsigned char*>(GetModuleHandleW(L"GameAssembly.dll"));require(module!=nullptr,"WebView game module absent");
    const auto dos=reinterpret_cast<const IMAGE_DOS_HEADER*>(module);require(dos->e_magic==IMAGE_DOS_SIGNATURE && dos->e_lfanew>0 && dos->e_lfanew<4096,"WebView PE header");
    const auto pe=reinterpret_cast<const IMAGE_NT_HEADERS64*>(module+dos->e_lfanew);require(pe->Signature==IMAGE_NT_SIGNATURE && pe->FileHeader.Machine==IMAGE_FILE_MACHINE_AMD64 && pe->OptionalHeader.SizeOfImage>=16,"WebView PE architecture");
    for(const auto& e:ba_webview_probe_entries::entries) {
        require(e.rva<=pe->OptionalHeader.SizeOfImage-16,"WebView method range");
        std::vector<unsigned char> bytes(module+e.rva,module+e.rva+16);
        require(ba_export::hash(bytes)==e.sha256,"WebView original method prefix differs");
    }
}
static void cacheDirectory() {
    require(ba_native_settings::session!=nullptr,"WebView settings owner absent");
    const auto file=ba_native_settings::session->path();const auto slash=file.find_last_of(L'\\');require(slash!=std::wstring::npos,"WebView profile directory");
    const auto path=file.substr(0,slash+1)+L"webview-cache";
    require(CreateDirectoryW(path.c_str(),nullptr)!=0,"WebView owned cache must be fresh");
    ba_native_settings::Handle h(CreateFileW(path.c_str(),FILE_READ_ATTRIBUTES,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,FILE_FLAG_BACKUP_SEMANTICS|FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
    require(h.value!=INVALID_HANDLE_VALUE,"WebView owned cache handle");BY_HANDLE_FILE_INFORMATION info{};
    require(GetFileInformationByHandle(h.value,&info) && (info.dwFileAttributes&FILE_ATTRIBUTE_DIRECTORY) && !(info.dwFileAttributes&FILE_ATTRIBUTE_REPARSE_POINT),"WebView cache ordinary directory");
    state.cache=utf8(path);Root input(ba::str(state.cache.c_str()));void* args[]={input.get()};ba::invoke(standalone(),nullptr,"SetCachePath",1,args);
}
static void destroyPrefab() {
    if(state.prefab && !state.destroyed){ba::call(state.prefab->get(),"Destroy");state.destroyed=true;}
}
static void requestStop() {
    destroyPrefab();state.stop=std::make_unique<Root>(ba::invoke(standalone(),nullptr,"TerminateBrowserProcess",0));
    state.stage=4;state.deadline=GetTickCount64()+20000;publish("stop_requested");
}
static void sampleInitialization() {
    const auto prefab=state.prefab->get();
    state.componentEnabled=boolean(prefab,"get_enabled");state.componentActive=boolean(prefab,"get_isActiveAndEnabled");
    state.cachedView=ba::get<Obj>(prefab,"_cachedWebView")!=nullptr;
    state.viewObject=ba::get<Obj>(prefab,"_webViewGameObject")!=nullptr;
    // This field is an optional caller-supplied IWebView, not the internally
    // created view's in-flight owner. Null is valid for Instantiate().
    Root initializing(ba::get<Obj>(prefab,"_webViewForInitialization"));state.initializingView=initializing.get()!=nullptr;
    if(initializing.get()) {
        state.initializingReady=boolean(initializing.get(),"get_IsInitialized");
        state.initializingDisposed=boolean(initializing.get(),"get_IsDisposed");
        state.initializingNative=ba::get<void*>(initializing.get(),"_nativeWebViewPtr")!=nullptr;
    }
    Root transform(ba::call(prefab,"get_transform")),rect(ba::call(transform.get(),"get_rect"));require(rect.get()!=nullptr,"WebView measured rect absent");
    const auto value=*ba::api<Rect*(*)(Obj)>("il2cpp_object_unbox")(rect.get());
    require(std::isfinite(value.width) && std::isfinite(value.height),"WebView measured rect not finite");
    state.rectWidth=value.width;state.rectHeight=value.height;
    require(value.width>=16 && value.height>=16 && value.width<=2048 && value.height<=2048,"WebView measured rect invalid");
}
static void update(Obj front) {
    static const bool enabled=ba::flag(L"-native-webview-proof");if(!enabled || state.stage==5)return;
    if(!ba_local_menu::ready(front))return;
    try {
        const auto now=GetTickCount64();
        if(!state.started) {
            require(ba_webview_probe_policy::allowed(ba::arguments(),ba::argument(L"-local-profile=")),"WebView proof requires explicit owned gated diagnostic");
            require(ba_dedicated_session::inMenu() && ba_dedicated_session::worldIdle(ba::read<Obj>(front,0xd8)),"WebView proof requires idle menu");
            state.started=true;state.thread=GetCurrentThreadId();verifyEntries();
            Root bridge(ba::invoke(standalone(),nullptr,"WebView_browserProcessIsRunning",0));
            require(bridge.get() && !*ba::api<bool*(*)(Obj)>("il2cpp_object_unbox")(bridge.get()),"WebView bridge already exists before owned cache setup");
            cacheDirectory();state.mayCleanup=true;
            state.prefab=std::make_unique<Root>(ba::invoke(ba::find_class("Vuplex.WebView","CanvasWebViewPrefab"),nullptr,"Instantiate",0));
            require(state.prefab->get()!=nullptr,"WebView original prefab factory returned null");
            Root empty(ba::str(""));ba::set<Obj>(state.prefab->get(),"InitialUrl",empty.get());
            Root menu(ba::get<Obj>(ba::owner,"<UIMenuController>k__BackingField")),main(ba::get<Obj>(menu.get(),"_mainMenu"));
            Root parent(ba::call(main.get(),"get_transform")),transform(ba::call(state.prefab->get(),"get_transform"));
            bool keep=false;void* parents[]={parent.get(),&keep};ba::call(transform.get(),"SetParent",2,parents);
            V2 anchor{.5f,.5f};void* anchors[]={&anchor};
            ba::call(transform.get(),"set_anchorMin",1,anchors);ba::call(transform.get(),"set_anchorMax",1,anchors);
            ba::call(transform.get(),"set_pivot",1,anchors);
            V2 size{256,144},position{0,0};void* sizes[]={&size};void* positions[]={&position};
            ba::call(transform.get(),"set_sizeDelta",1,sizes);ba::call(transform.get(),"set_anchoredPosition",1,positions);
            Root go(ba::call(state.prefab->get(),"get_gameObject"));require(boolean(go.get(),"get_activeInHierarchy"),"WebView prefab not active in hierarchy");
            state.init=std::make_unique<Root>(ba::call(state.prefab->get(),"WaitUntilInitialized"));
            state.stage=1;state.sampled=now;state.deadline=now+60000;publish("configured");return;
        }
        require(state.thread==GetCurrentThreadId(),"WebView proof moved off Unity thread");require(now<state.deadline,"WebView proof phase timeout");
        if(state.stage==1) {
            if(now-state.sampled>=1000){sampleInitialization();state.sampled=now;publish("waiting_initialization");}
            if(!completed(state.init->get()))return;
            state.view=std::make_unique<Root>(ba::call(state.prefab->get(),"get_WebView"));require(state.view->get()!=nullptr,"WebView initialization produced no view");
            require(boolean(state.view->get(),"get_IsInitialized") && !boolean(state.view->get(),"get_IsDisposed") && ba::get<void*>(state.view->get(),"_nativeWebViewPtr"),"WebView native readiness differs");
            Root transform(ba::call(state.prefab->get(),"get_transform")),rect(ba::call(transform.get(),"get_rect"));require(rect.get()!=nullptr,"WebView measured rect absent");
            const auto r=*ba::api<Rect*(*)(Obj)>("il2cpp_object_unbox")(rect.get());
            require(r.width>=16 && r.height>=16 && r.width<=2048 && r.height<=2048,"WebView measured rect invalid");
            state.rectWidth=r.width;state.rectHeight=r.height;
            Root size(ba::call(state.view->get(),"get_Size"));require(size.get()!=nullptr,"WebView native size absent");
            const auto s=*ba::api<Size*(*)(Obj)>("il2cpp_object_unbox")(size.get());state.width=s.width;state.height=s.height;
            require(s.width>=16 && s.height>=16 && s.width<=4096 && s.height<=4096,"WebView initialized pixel size invalid");state.initialized=true;
            state.page=std::make_unique<Root>(ba::call(state.view->get(),"WaitForNextPageLoadToFinish"));
            Root html(ba::str("<!doctype html><html><head><meta charset='utf-8'><title>Battle Aces local check</title></head><body>Owned local WebView check. No scripts or external resources.</body></html>"));
            void* args[]={html.get()};ba::call(state.view->get(),"LoadHtml",1,args);state.stage=2;state.deadline=now+20000;publish("initialized");return;
        }
        if(state.stage==2) {
            if(!completed(state.page->get()))return;state.pageLoaded=true;state.stage=3;state.due=now+2000;state.deadline=now+10000;publish("page_loaded");return;
        }
        if(state.stage==3) {
            if(now<state.due)return;
            require(!boolean(state.view->get(),"get_IsDisposed"),"WebView disposed before owned cleanup");
            ba::call(state.view->get(),"Dispose");require(boolean(state.view->get(),"get_IsDisposed"),"WebView Dispose did not publish state");state.disposed=true;
            requestStop();return;
        }
        if(state.stage==4) {
            if(!completed(state.stop->get()))return;state.stopCompleted=true;
            void* args[]={state.prefab?state.prefab->get():nullptr};
            Root exists(ba::invoke(ba::find_class("UnityEngine","Object"),nullptr,"op_Implicit",1,args));
            require(exists.get()!=nullptr,"WebView prefab lifetime Boolean absent");
            if(*ba::api<bool*(*)(Obj)>("il2cpp_object_unbox")(exists.get()))return;
            state.destroyConfirmed=true;state.stage=5;publish(state.failed?"failed":"completed");
            state.page.reset();state.init.reset();state.view.reset();state.prefab.reset();state.stop.reset();return;
        }
    } catch(const std::exception& e) {
        state.failed=true;if(state.error.empty())state.error=e.what();else{state.error+="; ";state.error+=e.what();}ba::log("WEBVIEW PROBE failure: %s",e.what());
        if(state.mayCleanup && state.stage<4) {
            try {requestStop();return;}catch(const std::exception& cleanup){state.error+="; cleanup: ";state.error+=cleanup.what();}
        }
        state.stage=5;try{publish("failed");}catch(const std::exception& out){ba::log("WEBVIEW PROBE output failed: %s",out.what());}
    }
}
}
