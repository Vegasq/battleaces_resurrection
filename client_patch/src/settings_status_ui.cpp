#pragma once
// A read-only child of the original Settings screen. The validated Settings
// owner is shared by menu and in-match options; no menu-flow automation runs
// here. Build/endpoint text comes from the launcher's verified package/bridge.
namespace ba_settings_status_ui {
using ba::Obj;using ba_local::Root;
using ba_match_loading::Vec2;using ba_match_loading::Color;
using ba_match_loading::setValue;using ba_match_loading::setObject;
using ba_match_loading::require;
struct Rect {float x,y,width,height;};
struct View {
    Root screen,owner,object,text;
    unsigned generation;
    std::string painted;
    View(Obj s,Obj o,Obj g,Obj t,unsigned n):screen(s),owner(o),object(g),text(t),generation(n){}
};
static auto& view=*new std::unique_ptr<View>();
static bool failed=false;
static ULONGLONG lastPaint=0;
static void destroy() {
    if(!view)return;
    // Only our authored child is ever destroyed; native pool/screens are owned
    // by the game. Hide first because Unity's Destroy is deferred to frame end.
    if(ba::read<Obj>(view->object.get(),0x10)) {
        setValue(view->object.get(),"SetActive",false);
        void* args[]={view->object.get()};
        ba::invoke(ba::find_class("UnityEngine","Object"),nullptr,"Destroy",1,args);
    }
    view.reset();
    ba::log("Settings build/status released: ownedChildOnly=1");
}
static void create(const ba_practice_settings_ui::Row& row) {
    // Original OptionsMenu has a centered 1020x830 panel. Its button row uses
    // y40..80; keep this label inside the free y0..40 footer, not at screen edge.
    Root screenRect(ba_practice_settings_ui::findChild(row.screen.get(),"GameObject"));
    require(screenRect.get()!=nullptr,"settings panel missing");
    Root rectValue(ba::call(screenRect.get(),"get_rect"));
    require(rectValue.get()!=nullptr,"settings screen rectangle missing");
    const auto rect=*ba::api<Rect*(*)(Obj)>("il2cpp_object_unbox")(rectValue.get());
    require(rect.width>=1000 && rect.width<=1040 && rect.height>=810 && rect.height<=850,
        "settings panel rectangle differs from original prefab");
    Root font(ba::invoke(ba::find_class("TMPro","TMP_Settings"),nullptr,"get_defaultFontAsset",0));
    require(font.get() && ba::read<Obj>(font.get(),0x10),"settings status font missing");
    std::vector<std::unique_ptr<Root>> created;
    try {
        Root object(ba_match_loading::makeObject("BattleAcesResurrectionSettingsStatus",created));
        setValue(object.get(),"SetActive",false);
        Root panel(ba_match_loading::add(object.get(),"UnityEngine","RectTransform"));
        ba_match_loading::parent(panel.get(),screenRect.get());
        setValue(panel.get(),"set_anchorMin",Vec2{0,0});setValue(panel.get(),"set_anchorMax",Vec2{1,0});
        setValue(panel.get(),"set_pivot",Vec2{.5f,0});
        setValue(panel.get(),"set_anchoredPosition",Vec2{0,6});
        setValue(panel.get(),"set_sizeDelta",Vec2{-50,32});
        Root text(ba_match_loading::add(object.get(),"TMPro","TextMeshProUGUI"));
        setObject(text.get(),"set_font",font.get());setValue(text.get(),"set_fontSize",18.0f);
        setValue(text.get(),"set_alignment",514);setValue(text.get(),"set_richText",false);
        setValue(text.get(),"set_raycastTarget",false);setValue(text.get(),"set_color",Color{.85f,.91f,.94f,1});
        // Long DNS names remain within the Settings footer at narrow resolutions.
        setValue(text.get(),"set_enableAutoSizing",true);
        setValue(text.get(),"set_fontSizeMin",12.0f);setValue(text.get(),"set_fontSizeMax",18.0f);
        view=std::make_unique<View>(row.screen.get(),row.owner.get(),object.get(),text.get(),ba_practice_settings_ui::releases);
        ba::log("Settings build/status created: screen=%.0fx%.0f inputBlocked=0 BA_SETTINGS_STATUS_UI_V1",rect.width,rect.height);
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
static std::string label() {
    std::string result="Resurrection "+ba_settings_connection::buildLabel()+"  |  "+ba_settings_connection::statusLine();
    if(ba::unified() && ba_client::worldOwner==ba_client::Owner::Practice)result+="  |  Local AI";
    else if(ba::offlinePractice())result+="  |  Local AI";
    else if(ba_client::replayWorld() || ba_native_replay_playback::enabled())result+="  |  Replay";
    result+="  |  Server: "+ba_settings_connection::serverLabel();
    return result;
}
static void update(Obj) {
    if(failed || !ba_practice_settings_ui::unityThread())return;
    try {
        const auto& row=ba_practice_settings_ui::row;
        const bool valid=row && !row->releasing && !row->failed &&
            ba::read<Obj>(row->screen.get(),0x10) && ba::get<bool>(row->screen.get(),"_isInitialized") &&
            ba::get<Obj>(row->screen.get(),"<Owner>k__BackingField")==row->owner.get() &&
            ba::get<Obj>(row->owner.get(),"<Root>k__BackingField")==row->screen.get();
        if(view && (!valid || view->screen.get()!=row->screen.get() || view->owner.get()!=row->owner.get() ||
            view->generation!=ba_practice_settings_ui::releases))destroy();
        if(!valid)return;
        const bool shown=ba_practice_settings_ui::active(row->screen.get());
        if(!shown){if(view)setValue(view->object.get(),"SetActive",false);return;}
        if(!view)create(*row);
        const auto now=GetTickCount64();
        if(now-lastPaint<250 && !view->painted.empty())return;
        lastPaint=now;
        const auto next=label();
        if(next!=view->painted) {
            Root value(ba::str(next.c_str()));setObject(view->text.get(),"set_text",value.get());
            Root actual(ba::call(view->text.get(),"get_text"));
            require(ba_catalog::utf8(actual.get())==next,"settings status text readback failed");
            view->painted=next;
            ba::log("Settings build/status text: %s",ba_catalog::quote(next).c_str());
        }
        setValue(view->object.get(),"SetActive",true);
        Root raycast(ba::call(view->text.get(),"get_raycastTarget"));
        require(!ba_match_loading::boolean(raycast.get()),"settings status captures input");
    }catch(const std::exception& error) {
        failed=true;
        ba::log("Settings build/status failed: %s; gameplay independent",error.what());
        try{destroy();}catch(...){}
    }
}
}
