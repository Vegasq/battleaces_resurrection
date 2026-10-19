#pragma once
// Original acknowledgment-only dialog, dispatched on a later idle Unity update.
// The native writer records its final result; it never calls UI.
namespace ba_settings_notice {
using ba::Obj;using ba_local::Root;
namespace ui=ba_practice_settings_ui;
static const char* title="Settings could not be saved";
static const char* body="A settings save failed. Your changes may not survive a restart. Check that the game folder is writable, then try saving again.";
static unsigned long long handled=0;
struct Notice {
    Root controller,pool,dialog,lifetime,model,titleReference,bodyReference;
    std::unique_ptr<Root> titleLocalizer,bodyLocalizer,titleLabel,bodyLabel;
    std::unique_ptr<Root> oldTitleReference,oldBodyReference,oldTitleText,oldBodyText;
    std::wstring capturePath;
    unsigned stage=0;int afterFrame=0,stableFrame=0;ULONGLONG deadline,due=0;
    Notice(Obj c,Obj p,Obj t,Obj b):controller(c),pool(p),dialog(ba::get<Obj>(c,"_simpleDialogObject")),
        lifetime(ba::get<Obj>(dialog.get(),"<Owner>k__BackingField")),model(ba::get<Obj>(dialog.get(),"_model")),
        titleReference(t),bodyReference(b),deadline(GetTickCount64()+15000){}
};
// Retain roots across engine teardown; do not run managed destructors from CRT.
static auto& current=*new std::unique_ptr<Notice>();
static bool safe(Obj front) {
    return ui::unityThread() && ba_local_menu::ready(front) && front==ba_dedicated_session::observedFront &&
        ba_dedicated_session::inMenu() && ba_client::nativeIdle(front) && ba_client::worldOwner==ba_client::Owner::None &&
        !ba_dedicated_session::joined && !ba_public::active() && !ba_practice::active() &&
        ba_native_quit::staticInt("LoadingCount")==0 && !ba_native_quit::wantsQuit();
}
static bool owned() {
    auto& n=*current;
    if(ba::get<Obj>(n.controller.get(),"_simpleDialogObject")!=n.dialog.get())return false;
    ui::require(ui::exact(n.dialog.get(),"Uncapped.UI","SimpleDialogVM") &&
        ba::get<Obj>(n.controller.get(),"_uiPool")==n.pool.get() &&
        ba::get<Obj>(n.dialog.get(),"_uiPool")==n.pool.get() &&
        ba::get<Obj>(n.dialog.get(),"<Owner>k__BackingField")==n.lifetime.get() &&
        ba::get<Obj>(n.lifetime.get(),"<Root>k__BackingField")==n.dialog.get() &&
        ba::get<Obj>(n.lifetime.get(),"_pool")==n.pool.get() &&
        ba::get<int>(n.lifetime.get(),"<PrefabType>k__BackingField")==89,"settings notice dialog owner mismatch");
    return ba::get<bool>(n.dialog.get(),"_isInitialized") &&
        ba::get<bool>(n.lifetime.get(),"<IsInitialized>k__BackingField") && ui::active(n.dialog.get());
}
static bool labelVisible(Obj label,const char* expected) {
    if(!ui::active(label) || !ba::native<bool(*)(Obj,Obj)>(0x5084710)(label,nullptr))return false;
    Root value(ba::call(label,"get_text")),renderer(ui::component(label,"UnityEngine","CanvasRenderer"));
    ui::require(ba_catalog::utf8(value.get())==expected && renderer.get(),"settings notice text readback differs");
    Root alpha(ba::call(renderer.get(),"GetAlpha")),inherited(ba::call(renderer.get(),"GetInheritedAlpha")),cull(ba::call(renderer.get(),"get_cull"));
    return ba_catalog::unbox<float>(alpha.get())>=.99f && ba_catalog::unbox<float>(inherited.get())>=.99f && !ba_catalog::unbox<bool>(cull.get());
}
static bool emptyIdle(Obj reference) {
    return ui::exact(reference,"UnityEngine.Localization","LocalizedString") &&
        ba_catalog::unbox<bool>(ba::call(reference,"get_IsEmpty")) && !ba::read<uintptr_t>(reference,0xd8);
}
static void textRoute(const char* field,const char* path,std::unique_ptr<Root>& localizer,std::unique_ptr<Root>& label) {
    Root child(ui::findChild(current->dialog.get(),path)),event(ba::get<Obj>(current->dialog.get(),field));
    ui::require(child.get() && ui::exact(event.get(),"UnityEngine.Localization.Components","LocalizeStringEvent") &&
        ui::component(child.get(),"UnityEngine.Localization.Components","LocalizeStringEvent")==event.get(),"settings notice text owner mismatch");
    Root tmp(ui::component(child.get(),"TMPro","TMP_Text")),update(ba::get<Obj>(event.get(),"m_UpdateString"));
    ui::require(tmp.get(),"settings notice TMP missing");ui::persistentTarget(update.get(),tmp.get(),"set_text");
    Root group(ba::get<Obj>(update.get(),"m_PersistentCalls")),calls(ba::get<Obj>(group.get(),"m_Calls"));
    Root callback(ui::item(calls.get(),0)),invoked(ba::get<Obj>(update.get(),"m_Calls")),runtime(ba::get<Obj>(invoked.get(),"m_RuntimeCalls"));
    ui::require(ba::get<int>(callback.get(),"m_Mode")==0 && ba::get<int>(callback.get(),"m_CallState")==2 &&
        ba_local::count(runtime.get())==0,"settings notice text event has unqualified listeners");
    localizer=std::make_unique<Root>(event.get());label=std::make_unique<Root>(tmp.get());
}
static void snapshotText() {
    auto& n=*current;
    // Validate BOTH routes/listeners and capture BOTH baselines before the first
    // setter. A bad body route must not leave an already-customized title.
    textRoute("_title","GameObject/Dialog/DialogMain/Vertical/Title_Loc",n.titleLocalizer,n.titleLabel);
    textRoute("_body","GameObject/Dialog/DialogMain/Vertical/Content/DescriptionText",n.bodyLocalizer,n.bodyLabel);
    Root t(n.titleLocalizer->get()),b(n.bodyLocalizer->get());
    Root tr(ba::get<Obj>(t.get(),"m_StringReference")),br(ba::get<Obj>(b.get(),"m_StringReference"));
    ui::require(emptyIdle(tr.get()) && emptyIdle(br.get()),"settings notice original text references are not empty/idle");
    Root tc(ui::findChild(n.dialog.get(),"GameObject/Dialog/DialogMain/Vertical/Title_Loc"));
    Root bc(ui::findChild(n.dialog.get(),"GameObject/Dialog/DialogMain/Vertical/Content/DescriptionText"));
    Root tl(ui::component(tc.get(),"TMPro","TMP_Text")),bl(ui::component(bc.get(),"TMPro","TMP_Text"));
    ui::require(tl.get() && bl.get(),"settings notice original labels missing");
    n.oldTitleReference=std::make_unique<Root>(tr.get());n.oldBodyReference=std::make_unique<Root>(br.get());
    n.oldTitleText=std::make_unique<Root>(ba::call(tl.get(),"get_text"));n.oldBodyText=std::make_unique<Root>(ba::call(bl.get(),"get_text"));
}
static bool restoreReleased() {
    auto& n=*current;
    if(ba::flag(L"-native-settings-notice-smoke"))ba::log("NATIVE SETTINGS notice cleanup gates: sameModel=%d active=%d sameOwner=%d sameRoot=%d controller=%d initialized=%d titlePrivate=%d bodyPrivate=%d titleEmpty=%d bodyEmpty=%d oldTitleEmpty=%d oldBodyEmpty=%d",
        n.model.get() && ba::get<Obj>(n.dialog.get(),"_model")==n.model.get(),ui::active(n.dialog.get()),
        ba::get<Obj>(n.dialog.get(),"<Owner>k__BackingField")==n.lifetime.get(),
        ba::get<Obj>(n.lifetime.get(),"<Root>k__BackingField")==n.dialog.get(),
        ba::get<Obj>(n.controller.get(),"_simpleDialogObject")!=nullptr,ba::get<bool>(n.lifetime.get(),"<IsInitialized>k__BackingField"),
        n.titleLocalizer && ba::get<Obj>(n.titleLocalizer->get(),"m_StringReference")==n.titleReference.get(),
        n.bodyLocalizer && ba::get<Obj>(n.bodyLocalizer->get(),"m_StringReference")==n.bodyReference.get(),
        emptyIdle(n.titleReference.get()),emptyIdle(n.bodyReference.get()),
        n.oldTitleReference && emptyIdle(n.oldTitleReference->get()),n.oldBodyReference && emptyIdle(n.oldBodyReference->get()));
    if(!n.oldTitleReference || !n.titleLocalizer || !n.bodyLocalizer ||
        !n.model.get() || ba::get<Obj>(n.dialog.get(),"_model")!=n.model.get() || ui::active(n.dialog.get()) ||
        ba::get<Obj>(n.dialog.get(),"<Owner>k__BackingField")!=n.lifetime.get() ||
        ba::get<Obj>(n.lifetime.get(),"<Root>k__BackingField")!=n.dialog.get() ||
        ba::get<Obj>(n.controller.get(),"_simpleDialogObject") ||
        ba::get<bool>(n.lifetime.get(),"<IsInitialized>k__BackingField") ||
        ba::get<Obj>(n.titleLocalizer->get(),"m_StringReference")!=n.titleReference.get() ||
        ba::get<Obj>(n.bodyLocalizer->get(),"m_StringReference")!=n.bodyReference.get() ||
        !emptyIdle(n.titleReference.get()) || !emptyIdle(n.bodyReference.get()) ||
        !emptyIdle(n.oldTitleReference->get()) || !emptyIdle(n.oldBodyReference->get()))return false;
    for(const auto& values:{std::array<Obj,3>{n.titleLocalizer->get(),n.oldTitleReference->get(),n.oldTitleText->get()},
                            std::array<Obj,3>{n.bodyLocalizer->get(),n.oldBodyReference->get(),n.oldBodyText->get()}}) {
        ba::native<void(*)(Obj,Obj,Obj)>(0x47f5cb0)(values[0],values[1],nullptr);
        ba::native<void(*)(Obj,Obj,Obj)>(0x47f5f50)(values[0],values[2],nullptr);
    }
    Root t(ba::call(n.titleLabel->get(),"get_text")),b(ba::call(n.bodyLabel->get(),"get_text"));
    ui::require(ba::get<Obj>(n.titleLocalizer->get(),"m_StringReference")==n.oldTitleReference->get() &&
        ba::get<Obj>(n.bodyLocalizer->get(),"m_StringReference")==n.oldBodyReference->get() &&
        ba_catalog::utf8(t.get())==ba_catalog::utf8(n.oldTitleText->get()) &&
        ba_catalog::utf8(b.get())==ba_catalog::utf8(n.oldBodyText->get()),"settings notice released text restoration differs");
    return true;
}
static void paint(Obj event,Obj reference,const char* text) {
    // Original setter detaches the old handler and any prior loading operation.
    ba::native<void(*)(Obj,Obj,Obj)>(0x47f5cb0)(event,reference,nullptr);
    ui::require(ba::get<Obj>(event,"m_StringReference")==reference &&
        ba_catalog::unbox<bool>(ba::call(reference,"get_IsEmpty")) && !ba::read<Obj>(reference,0xd8),"settings notice localization is not empty/idle");
    Root value(ba::str(text));ba::native<void(*)(Obj,Obj,Obj)>(0x47f5f50)(event,value.get(),nullptr);
}
static void capture() {
    const auto path=ba_export::moduleDirectory()+L"investigation\\runtime\\native-settings-notice-"+
        std::wstring(ba_native_settings::session->profile().begin(),ba_native_settings::session->profile().end())+L".png";
    ui::require(GetFileAttributesW(path.c_str())==INVALID_FILE_ATTRIBUTES && GetLastError()==ERROR_FILE_NOT_FOUND,"settings notice capture exists");
    // AsTexture during Update can read a partially rendered frame. Let the
    // engine schedule its file capture;acknowledge only after a complete PNG.
    Root filename(ba::api<Obj(*)(const wchar_t*,int32_t)>("il2cpp_string_new_utf16")(path.data(),static_cast<int32_t>(path.size())));
    void* args[]={filename.get()};ba::invoke(ba::find_class("UnityEngine","ScreenCapture"),nullptr,"CaptureScreenshot",1,args);
    current->capturePath=path;ba::log("NATIVE SETTINGS notice capture scheduled: engineFile=1 updateReadback=0");
}
static bool captureReady() {
    using ba_native_settings::Handle;
    Handle file(CreateFileW(current->capturePath.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,
        FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
    if(file.value==INVALID_HANDLE_VALUE) {
        const auto error=GetLastError();ui::require(error==ERROR_FILE_NOT_FOUND || error==ERROR_SHARING_VIOLATION,
            "settings notice scheduled capture unavailable");return false;
    }
    ba_native_settings::ordinary(file.value);LARGE_INTEGER size{};
    ui::require(GetFileSizeEx(file.value,&size) && size.QuadPart<16*1024*1024,"settings notice scheduled capture size bound");
    if(size.QuadPart<20)return false;
    unsigned char header[8],tail[12];DWORD count=0;
    if(!ReadFile(file.value,header,sizeof(header),&count,nullptr) || count!=sizeof(header))return false;
    LARGE_INTEGER offset{};offset.QuadPart=-12;
    if(!SetFilePointerEx(file.value,offset,nullptr,FILE_END) || !ReadFile(file.value,tail,sizeof(tail),&count,nullptr) || count!=sizeof(tail))return false;
    static const unsigned char png[]={137,80,78,71,13,10,26,10},end[]={0,0,0,0,73,69,78,68,174,66,96,130};
    return !memcmp(header,png,sizeof(png)) && !memcmp(tail,end,sizeof(end));
}
static void geometry(Obj label,const char* name) {
    struct Color {float r,g,b,a;};struct Rect {float x,y,width,height;};struct Vec3 {float x,y,z;};
    Root info(ba::call(label,"get_textInfo")),mesh(ba::call(label,"get_mesh"));
    ui::require(info.get() && ba::get<Obj>(info.get(),"textComponent")==label && mesh.get(),"settings notice diagnostic text geometry unavailable");
    Root vertices(ba::call(mesh.get(),"get_vertexCount")),transform(ba::call(label,"get_rectTransform"));
    Root box(ba::call(transform.get(),"get_rect")),scale(ba::call(transform.get(),"get_lossyScale"));
    const auto rect=ba_catalog::unbox<Rect>(box.get());const auto size=ba_catalog::unbox<Vec3>(scale.get());
    const auto color=ba::get<Color>(label,"m_fontColor");
    ba::log("NATIVE SETTINGS notice geometry: label=%s characters=%d lines=%d pages=%d vertices=%d rect=%g,%g,%g,%g scale=%g,%g,%g color=%g,%g,%g,%g face=%u renderMode=%d first=%d maxCharacters=%d maxLines=%d page=%d",
        name,ba::get<int>(info.get(),"characterCount"),ba::get<int>(info.get(),"lineCount"),ba::get<int>(info.get(),"pageCount"),
        ba_catalog::unbox<int>(vertices.get()),rect.x,rect.y,rect.width,rect.height,size.x,size.y,size.z,color.r,color.g,color.b,color.a,
        ba::get<uint32_t>(label,"m_faceColor"),ba::get<int>(label,"m_renderMode"),ba::get<int>(label,"m_firstVisibleCharacter"),
        ba::get<int>(label,"m_maxVisibleCharacters"),ba::get<int>(label,"m_maxVisibleLines"),ba::get<int>(label,"m_pageToDisplay"));
}
static void inspectBody() {
    auto& n=*current;geometry(n.titleLabel->get(),"title");geometry(n.bodyLabel->get(),"body");
    Root content(ui::findChild(n.dialog.get(),"GameObject/Dialog/DialogMain/Vertical/Content"));
    Root canvas(ui::component(content.get(),"UnityEngine","Canvas")),labelCanvas(ba::call(n.bodyLabel->get(),"get_canvas"));
    ui::require(canvas.get(),"settings notice content canvas missing");
    Root enabled(ba::call(canvas.get(),"get_enabled")),active(ba::call(canvas.get(),"get_isActiveAndEnabled")),
        mode(ba::call(canvas.get(),"get_renderMode")),sorting(ba::call(canvas.get(),"get_sortingOrder")),
        overrideSorting(ba::call(canvas.get(),"get_overrideSorting")),root(ba::call(canvas.get(),"get_rootCanvas"));
    Root rootEnabled(ba::call(root.get(),"get_enabled"));
    ba::log("NATIVE SETTINGS notice body canvas: enabled=%d active=%d mode=%d sorting=%d override=%d labelCanvasSame=%d rootEnabled=%d",
        ba_catalog::unbox<bool>(enabled.get()),ba_catalog::unbox<bool>(active.get()),ba_catalog::unbox<int>(mode.get()),
        ba_catalog::unbox<int>(sorting.get()),ba_catalog::unbox<bool>(overrideSorting.get()),labelCanvas.get()==canvas.get(),ba_catalog::unbox<bool>(rootEnabled.get()));
}
static void update(Obj front) {
    const auto failures=ba_native_settings::saveFailures.load();
    if(!current && (ba_native_settings::lastSaveSucceeded.load() || failures==handled)){handled=failures;return;}
    if(!ba_native_settings::session || !safe(front))return;
    const bool smoke=ba::flag(L"-native-settings-notice-smoke");
    try {
        if(smoke)ui::require(ba::flag(L"-native-settings-write-smoke") &&
            ba_native_settings::session->profile().rfind("nativestest_",0)==0,"settings notice smoke requires an owned writer fixture");
        if(!current) {
            Root controller(ba::get<Obj>(ba::owner,"<UIPopupController>k__BackingField")),menu(ba::get<Obj>(ba::owner,"<UIMenuController>k__BackingField"));
            ui::require(ui::exact(controller.get(),"Uncapped.UI","UIPopupController") && ba::read<Obj>(controller.get(),0x10) && ui::active(controller.get()),"settings notice controller unavailable");
            Root pool(ba::get<Obj>(controller.get(),"_uiPool")),router(ba::get<Obj>(front,"_signalRouter")),descriptor(ba::get<Obj>(controller.get(),"_simpleDialog"));
            ui::require(pool.get() && ba::get<Obj>(menu.get(),"_pool")==pool.get() && router.get() &&
                ba::get<Obj>(controller.get(),"_signalRouter")==router.get() && ba::get<int>(descriptor.get(),"_prefabKey")==89 &&
                !ba::get<bool>(descriptor.get(),"_overrideCanvasLayer") && !ba::get<Obj>(descriptor.get(),"_parent"),"settings notice controller/pool mismatch");
            if(ba::get<Obj>(controller.get(),"_simpleDialogObject") || ba::get<Obj>(controller.get(),"_spinnerDialogObject"))return;
            Root navigation(ba::get<Obj>(ba::owner,"<NavigationStack>k__BackingField"));if(ba_native_quit::navCount(navigation.get()))return;
            Root t(ba::make("UnityEngine.Localization","LocalizedString")),b(ba::make("UnityEngine.Localization","LocalizedString"));
            void* args[]={t.get(),b.get()};ba::call(controller.get(),"ShowSimpleDialog",2,args);
            current=std::make_unique<Notice>(controller.get(),pool.get(),t.get(),b.get());handled=failures;
            ui::require(current->dialog.get() && current->lifetime.get(),"settings notice original Show returned no dialog");
            ba::log("NATIVE SETTINGS notice dispatched: failures=%llu writerCallback=0 unityThread=1 BA_RESURRECTION_NATIVE_SETTINGS_NOTICE_V1",failures);
            return;
        }
        auto& n=*current;
        if(ba::get<Obj>(n.controller.get(),"_simpleDialogObject")!=n.dialog.get()) {
            ui::require(!ba::get<Obj>(n.controller.get(),"_simpleDialogObject") &&
                !ba::get<bool>(n.lifetime.get(),"<IsInitialized>k__BackingField"),"settings notice replaced without original release");
            ba::log("NATIVE SETTINGS notice released: originalPoolRelease=1 controllerCleared=1");
            const bool restored=restoreReleased();ba::log("NATIVE SETTINGS notice text cleanup: restored=%d skipOnOwnershipMismatch=1",restored);
            if(smoke) {
                ui::require(restored,"settings notice smoke did not restore its released pooled text");
                Root t(ba::make("UnityEngine.Localization","LocalizedString")),b(ba::make("UnityEngine.Localization","LocalizedString"));
                void* args[]={t.get(),b.get()};ba::call(n.controller.get(),"ShowSimpleDialog",2,args);
                ui::require(ba::get<Obj>(n.controller.get(),"_simpleDialogObject")==n.dialog.get() &&
                    ba::get<bool>(n.lifetime.get(),"<IsInitialized>k__BackingField") &&
                    ba::get<Obj>(n.titleLocalizer->get(),"m_StringReference")==n.oldTitleReference->get() &&
                    ba::get<Obj>(n.bodyLocalizer->get(),"m_StringReference")==n.oldBodyReference->get(),"settings notice original pooled reuse differs");
                Root tv(ba::call(n.titleLabel->get(),"get_text")),bv(ba::call(n.bodyLabel->get(),"get_text"));
                ui::require(ba_catalog::utf8(tv.get())==ba_catalog::utf8(n.oldTitleText->get()) &&
                    ba_catalog::utf8(bv.get())==ba_catalog::utf8(n.oldBodyText->get()),"settings notice text leaked into next original dialog");
                ba::call(n.dialog.get(),"OnButton1Click");
                ui::require(!ba::get<Obj>(n.controller.get(),"_simpleDialogObject") &&
                    !ba::get<bool>(n.lifetime.get(),"<IsInitialized>k__BackingField"),"settings notice reused dialog did not release");
                ba::log("NATIVE SETTINGS notice pooled reuse passed: sameRoot=1 originalReferences=1 priorText=1 originalRelease=1");
            }
            current.reset();return;
        }
        if(n.stage>=3)return;ui::require(GetTickCount64()<n.deadline,"settings notice presentation deadline");
        if(!owned())return;
        Root container(ba::get<Obj>(n.lifetime.get(),"_uiContainer")),bindings(ba::get<Obj>(n.dialog.get(),"_bindings"));
        if(!container.get() || !ba::native<bool(*)(Obj,Obj)>(0x88a350)(container.get(),nullptr) ||
            !bindings.get() || !ba::get<bool>(bindings.get(),"_initialized"))return;
        Root model(ba::get<Obj>(n.dialog.get(),"_model"));
        ui::require(model.get()==n.model.get() && ui::exact(model.get(),"Uncapped.UI","SimpleDialogModel") && ba::get<int>(model.get(),"ButtonFlags")==1 &&
            ba::get<Obj>(model.get(),"Title")==n.titleReference.get() && ba::get<Obj>(model.get(),"BodyText")==n.bodyReference.get() &&
            !ba::get<Obj>(model.get(),"OnButton1Click") && !ba::get<Obj>(model.get(),"OnButton2Click") && !ba::get<Obj>(model.get(),"OnButton3Click"),"settings notice model differs");
        if(!n.stage) {
            snapshotText();
            paint(n.titleLocalizer->get(),n.titleReference.get(),title);
            paint(n.bodyLocalizer->get(),n.bodyReference.get(),body);
            n.stage=1;n.due=GetTickCount64()+300;n.afterFrame=ba_match_search::frame()+3;return;
        }
        if(GetTickCount64()<n.due)return;
        const int frame=ba_match_search::frame();if(frame<n.afterFrame)return;
        ui::require(ba::get<Obj>(n.titleLocalizer->get(),"m_StringReference")==n.titleReference.get() &&
            ba::get<Obj>(n.bodyLocalizer->get(),"m_StringReference")==n.bodyReference.get(),"settings notice localization generation changed");
        if(!labelVisible(n.titleLabel->get(),title) || !labelVisible(n.bodyLabel->get(),body))return;
        // Wall-clock delay alone can elapse across a stalled Update. Allow
        // actual rendered frames after both labels are visible before the
        // diagnostic capture/acknowledgment qualification advances.
        if(n.stage==1) {
            if(!n.stableFrame){n.stableFrame=frame+2;return;}
            if(frame<n.stableFrame)return;
        }
        Root child(ui::findChild(n.dialog.get(),"GameObject/Dialog/DialogMain/Vertical/Buttons/OkButton"));
        Root button(ui::component(child.get(),"Doozy.Runtime.UIManager.Components","UIButton"));ba_native_quit::clickTarget(button.get(),n.dialog.get(),"OnButton1Click");
        if(n.stage==1) {
            if(smoke) {
                if(n.capturePath.empty()){inspectBody();capture();return;}
                if(!captureReady())return;
            }
            ba::log("NATIVE SETTINGS notice rendered: originalDialog=1 prefab=89 titleAndBody=1 emptyLocalization=1 captured=%d",smoke);
            n.stage=smoke?2:3;n.due=GetTickCount64()+1000;return;
        }
        // Only an explicit owned diagnostic acknowledges on the player's behalf.
        n.stage=3;ba::log("NATIVE SETTINGS notice smoke original acknowledgment (automated)");ba::call(n.dialog.get(),"OnButton1Click");
    }catch(const std::exception& error){handled=failures;ba::log("Native settings notice failed: %s",error.what());current.reset();}
}
}
