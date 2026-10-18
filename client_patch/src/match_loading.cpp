#pragma once
// Authored nonblocking UI. Native API/enum evidence: docs/match-loading.txt.
// This never borrows the game's global modal spinner or changes a game FSM.
namespace ba_match_loading {
using ba::Obj;using ba_local::Root;
static auto& model=*new Model();
static bool rendererFailed=false,threadFailureReported=false;
static std::string painted;
static ULONGLONG lastPaint=0;
static bool paintedVisible=false;
struct Vec2 {float x,y;};
struct Color {float r,g,b,a;};
struct View {
    Root object,canvas,group,panel,textRect,background,text,font;
    View(Obj o,Obj c,Obj g,Obj p,Obj tr,Obj b,Obj t,Obj f):object(o),canvas(c),group(g),panel(p),textRect(tr),background(b),text(t),font(f){}
};
static auto& view=*new std::unique_ptr<View>();
struct Capture {Ticket ticket;std::string event;int afterFrame;};
static auto& capture=*new std::unique_ptr<Capture>();
static unsigned captureSequence=0;
static void require(bool value,const char* why) {if(!value)throw std::runtime_error(why);}
static bool unityThread() {
    if(ba::initialThread && ba::initialThread==GetCurrentThreadId())return true;
    if(!threadFailureReported){ba::log("Match loading UI ignored an off-thread call");threadFailureReported=true;}
    return false;
}
static const char* sourceName(Source source) {
    switch(source){case Source::Practice:return "practice";case Source::Dedicated:return "dedicated";case Source::Custom:return "custom";case Source::Public:return "public";}
    return "unknown";
}
static const char* stageName(Stage stage) {
    switch(stage){case Stage::Preparing:return "preparing";case Stage::Waiting:return "waiting";case Stage::Loading:return "loading";case Stage::Starting:return "starting";}
    return "unknown";
}
static const char* stageText(Stage stage) {
    switch(stage){case Stage::Preparing:return "Preparing match";case Stage::Waiting:return "Waiting for the other player";
        case Stage::Loading:return "Loading match";case Stage::Starting:return "Starting match";}
    return "Preparing match";
}
static int frame() {
    Root value(ba::invoke(ba::find_class("UnityEngine","Time"),nullptr,"get_frameCount",0));
    require(value.get()!=nullptr,"loading UI frame unavailable");
    return *ba::api<int*(*)(Obj)>("il2cpp_object_unbox")(value.get());
}
static bool boolean(Obj value) {
    require(value!=nullptr,"loading UI boolean unavailable");return *ba::api<bool*(*)(Obj)>("il2cpp_object_unbox")(value);
}
template<class T> static void setValue(Obj target,const char* method,T value) {void* args[]={&value};ba::call(target,method,1,args);}
static void setObject(Obj target,const char* method,Obj value) {void* args[]={value};ba::call(target,method,1,args);}
static Obj reflected(const char* ns,const char* name) {
    Obj type=ba::api<Obj(*)(Obj)>("il2cpp_class_get_type")(ba::find_class(ns,name));
    return ba::api<Obj(*)(Obj)>("il2cpp_type_get_object")(type);
}
static Obj add(Obj object,const char* ns,const char* name) {
    Root type(reflected(ns,name));
    // The only retained one-argument overload is AddComponent(System.Type).
    // runtime_invoke converts managed failures into the renderer's caught error.
    void* args[]={type.get()};Obj value=ba::call(object,"AddComponent",1,args);
    require(value && ba::klass(value)==ba::find_class(ns,name),"loading UI component type mismatch");return value;
}
static void parent(Obj transform,Obj target) {
    bool keepWorld=false;void* args[]={target,&keepWorld};ba::call(transform,"SetParent",2,args);
}
static Obj makeObject(const char* name,std::vector<std::unique_ptr<Root>>& created) {
    Obj cls=ba::find_class("UnityEngine","GameObject");ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(cls);
    Root object(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(cls)),label(ba::str(name));
    void* args[]={label.get()};ba::invoke(cls,object.get(),".ctor",1,args);
    created.push_back(std::make_unique<Root>(object.get()));return object.get();
}
static void ensureView() {
    if(view)return;
    Root font(ba::invoke(ba::find_class("TMPro","TMP_Settings"),nullptr,"get_defaultFontAsset",0));
    require(font.get() && ba::read<Obj>(font.get(),0x10),"loading UI default font unavailable");
    std::vector<std::unique_ptr<Root>> created;
    try {
        Root object(makeObject("BattleAcesResurrectionMatchStatus",created));setValue(object.get(),"SetActive",false);
        Root rootRect(add(object.get(),"UnityEngine","RectTransform"));
        Root canvas(add(object.get(),"UnityEngine","Canvas"));
        setValue(canvas.get(),"set_renderMode",0);setValue(canvas.get(),"set_sortingOrder",10000);
        Root scaler(add(object.get(),"UnityEngine.UI","CanvasScaler"));
        setValue(scaler.get(),"set_uiScaleMode",1);setValue(scaler.get(),"set_referenceResolution",Vec2{960,540});
        setValue(scaler.get(),"set_screenMatchMode",0);setValue(scaler.get(),"set_matchWidthOrHeight",.5f);
        Root group(add(object.get(),"UnityEngine","CanvasGroup"));
        setValue(group.get(),"set_interactable",false);setValue(group.get(),"set_blocksRaycasts",false);

        Root panelObject(makeObject("StatusPanel",created)),panel(add(panelObject.get(),"UnityEngine","RectTransform"));
        parent(panel.get(),rootRect.get());
        setValue(panel.get(),"set_anchorMin",Vec2{.5f,1});setValue(panel.get(),"set_anchorMax",Vec2{.5f,1});
        setValue(panel.get(),"set_pivot",Vec2{.5f,1});setValue(panel.get(),"set_anchoredPosition",Vec2{0,-64});
        setValue(panel.get(),"set_sizeDelta",Vec2{560,54});
        Root background(add(panelObject.get(),"UnityEngine.UI","Image"));
        setValue(background.get(),"set_color",Color{.025f,.05f,.065f,.96f});setValue(background.get(),"set_raycastTarget",false);

        Root textObject(makeObject("StatusText",created)),textRect(add(textObject.get(),"UnityEngine","RectTransform"));
        parent(textRect.get(),panel.get());
        setValue(textRect.get(),"set_anchorMin",Vec2{0,0});setValue(textRect.get(),"set_anchorMax",Vec2{1,1});
        setValue(textRect.get(),"set_pivot",Vec2{.5f,.5f});setValue(textRect.get(),"set_anchoredPosition",Vec2{0,0});
        setValue(textRect.get(),"set_sizeDelta",Vec2{-32,-12});
        Root text(add(textObject.get(),"TMPro","TextMeshProUGUI"));
        setObject(text.get(),"set_font",font.get());setValue(text.get(),"set_fontSize",22.0f);
        setValue(text.get(),"set_alignment",514);setValue(text.get(),"set_richText",false);
        setValue(text.get(),"set_raycastTarget",false);
        void* persistent[]={object.get()};ba::invoke(ba::find_class("UnityEngine","Object"),nullptr,"DontDestroyOnLoad",1,persistent);
        view=std::make_unique<View>(object.get(),canvas.get(),group.get(),panel.get(),textRect.get(),background.get(),text.get(),font.get());
        ba::log("Match loading UI created: privateCanvas=1 inputBlocked=0 BA_RESURRECTION_MATCH_LOADING_V1");
    }catch(...) {
        for(auto it=created.rbegin();it!=created.rend();++it)try {
            if(ba::read<Obj>((*it)->get(),0x10)) {
                setValue((*it)->get(),"SetActive",false);void* args[]={(*it)->get()};
                ba::invoke(ba::find_class("UnityEngine","Object"),nullptr,"Destroy",1,args);
            }
        }catch(...){}
        throw;
    }
}
static void paint(bool force=false) {
    if(rendererFailed || (!model.visible && !view))return;
    try {
        if(model.visible)ensureView();
        require(view && ba::read<Obj>(view->object.get(),0x10),"loading UI owned canvas was destroyed");
        const auto now=GetTickCount64();
        if(!force && paintedVisible==model.visible && (!model.visible || now-lastPaint<400))return;
        std::string text=model.notice?model.message:stageText(model.stage);
        if(model.pending)text+=std::string(1+(now/400)%3,'.');
        if(model.visible && text!=painted) {
            Root label(ba::str(text.c_str()));setObject(view->text.get(),"set_text",label.get());
            setValue(view->text.get(),"set_color",model.notice?Color{1,.78f,.46f,1}:Color{.83f,.95f,1,1});
            Root actual(ba::call(view->text.get(),"get_text"));
            require(ba_catalog::utf8(actual.get())==text,"loading UI text readback failed");painted=text;
        }
        setValue(view->object.get(),"SetActive",model.visible);
        Root shown(ba::call(view->object.get(),"get_activeInHierarchy"));
        require(boolean(shown.get())==model.visible,"loading UI visibility readback failed");
        Root blocked(ba::call(view->group.get(),"get_blocksRaycasts")),textRaycast(ba::call(view->text.get(),"get_raycastTarget"));
        require(!boolean(blocked.get()) && !boolean(textRaycast.get()),"loading UI must not capture input");
        paintedVisible=model.visible;lastPaint=now;
    }catch(const std::exception& e) {
        rendererFailed=true;ba::log("Match loading UI failed: %s; gameplay remains independent",e.what());
        if(view)try{setValue(view->object.get(),"SetActive",false);}catch(...){}
    }
}
static void changed(const char* event,const char* reason="") {
    paint(true);
    ba::log("Match loading event=%s source=%s ticket=%llu identity=%s stage=%s pending=%d visible=%d nativeVisible=%d rendererFailed=%d reason=%s",
        event,sourceName(model.source),model.ticket,model.identity.c_str(),stageName(model.stage),model.pending?1:0,model.visible?1:0,
        paintedVisible?1:0,rendererFailed?1:0,reason);
    if(ba::flag(L"-match-loading-smoke") && !rendererFailed)try {
        capture=std::make_unique<Capture>(Capture{model.ticket,event,frame()+2});
    }catch(const std::exception& e){ba::log("Match loading capture failed: %s",e.what());}
}
static Ticket begin(Source source,const std::string& identity,Stage stage) {
    if(!unityThread())return 0;
    try {
        const auto old=model.ticket;const auto ticket=model.begin(source,identity,stage);
        if(ticket!=old)changed("show");return ticket;
    }catch(const std::exception& e){ba::log("Match loading UI failed to begin: %s",e.what());return 0;}
}
static void advance(Ticket ticket,Stage stage) {if(unityThread() && model.advance(ticket,stage))changed("stage");}
static void success(Ticket ticket) {if(unityThread() && model.finish(ticket))changed("ready");}
static void cancel(Ticket ticket,const char* reason) {if(unityThread() && model.finish(ticket))changed("cancel",reason);}
static void error(Ticket ticket,const char* message) {if(unityThread() && model.error(ticket,message,GetTickCount64()))changed("error",message);}
static void update(void* front) {
    if(!front || (!model.visible && !view && !capture))return;
    if(!unityThread())return;
    if(model.expire(GetTickCount64()))changed("expired");
    paint();
    if(capture && capture->ticket==model.ticket && !rendererFailed)try {
        if(frame()<capture->afterFrame)return;
        wchar_t module[32768];const auto length=GetModuleFileNameW(ba::module,module,32768);
        require(length && length<32768,"loading capture installation unavailable");
        wchar_t* slash=wcsrchr(module,L'\\');require(slash!=nullptr,"loading capture path invalid");*(slash+1)=0;
        const std::string filename="match-loading-"+std::to_string(GetCurrentProcessId())+"-"+std::to_string(model.ticket)+"-"+
            std::to_string(++captureSequence)+"-"+capture->event+".png";
        std::wstring path=std::wstring(module)+L"investigation\\runtime\\"+std::wstring(filename.begin(),filename.end());
        Root name(ba::api<Obj(*)(const wchar_t*,int)>("il2cpp_string_new_utf16")(path.data(),static_cast<int>(path.size())));
        void* args[]={name.get()};ba::invoke(ba::find_class("UnityEngine","ScreenCapture"),nullptr,"CaptureScreenshot",1,args);
        ba::log("Match loading capture requested: file=%s ticket=%llu event=%s nativeVisible=%d frame=%d",filename.c_str(),model.ticket,capture->event.c_str(),paintedVisible?1:0,frame());
        capture.reset();
    }catch(const std::exception& e){ba::log("Match loading capture failed: %s",e.what());capture.reset();}
}
}
