#pragma once
// Application-lifetime local profile/deck ownership. It has no network dependency.
namespace ba_local_menu {
using ba::Obj;using ba_local::Root;
static auto& frontRoot=*new std::unique_ptr<Root>();
static auto& identityRoot=*new std::unique_ptr<Root>();
static bool initialized=false,baseInitialized=false,failed=false;
static void require(bool condition,const char* message) {if(!condition)throw std::runtime_error(message);}
static bool ready(Obj front) {return initialized && !failed && frontRoot && frontRoot->get()==front;}
static void captureHeader(unsigned sequence) {
    require(ba::flag(L"-menu-profile-proof"),"menu header capture requires explicit diagnostic");
    const auto path=ba_export::moduleDirectory()+L"investigation\\runtime\\menu-profile-"+std::to_wstring(GetCurrentProcessId())+L"-"+std::to_wstring(sequence)+L".png";
    require(GetFileAttributesW(path.c_str())==INVALID_FILE_ATTRIBUTES && GetLastError()==ERROR_FILE_NOT_FOUND,"menu header capture output unavailable");
    Obj render=ba::find_class("UnityEngine","RenderTexture");Root target(ba::invoke(render,nullptr,"get_active",0));
    auto restore=[&](){void* values[]={target.get()};ba::invoke(render,nullptr,"set_active",1,values);};
    void* clear[]={nullptr};ba::invoke(render,nullptr,"set_active",1,clear);
    std::unique_ptr<Root> texture;
    try {texture=std::make_unique<Root>(ba::invoke(ba::find_class("UnityEngine","ScreenCapture"),nullptr,"CaptureScreenshotAsTexture",0));}
    catch(...) {restore();throw;}
    restore();Root restored(ba::invoke(render,nullptr,"get_active",0));
    require(restored.get()==target.get(),"menu header capture render state not restored");
    require(texture && texture->get(),"menu header screenshot missing");
    auto destroy=[&](){void* values[]={texture->get()};ba::invoke(ba::find_class("UnityEngine","Object"),nullptr,"Destroy",1,values);};
    try {
        void* values[]={texture->get()};Root png(ba::invoke(ba::find_class("UnityEngine","ImageConversion"),nullptr,"EncodeToPNG",1,values));
        const auto bytes=ba_catalog::length(png.get());require(bytes>8 && bytes<16*1024*1024,"menu header screenshot byte bound");
        ba_export::atomicWrite(path,static_cast<const unsigned char*>(png.get())+0x20,bytes);
    }catch(...) {destroy();throw;}
    destroy();
}
static void refreshHeaderName(Obj front) {
    static ULONGLONG next=0,proofDue=0;static bool unavailable=false,proven=false;static unsigned proofSequence=0;
    if(unavailable || !ready(front))return;
    if(!ba_dedicated_session::inMenu() || !ba_dedicated_session::worldIdle(ba::read<Obj>(front,0xd8))) {
        proven=false;proofDue=0;return;
    }
    const auto now=GetTickCount64();if(now<next)return;
    next=now+500;
    try {
        require(GetCurrentThreadId()==ba_dedicated_session::unityThread,"menu header called off Unity thread");
        Root controller(ba::get<Obj>(ba::owner,"<UIMenuController>k__BackingField"));
        Root main(ba::get<Obj>(controller.get(),"_mainMenu"));
        if(!main.get() || !ba::get<bool>(main.get(),"_isInitialized"))return;
        auto active=[](Obj object) {Root go(ba::native<Obj(*)(Obj,Obj)>(0x6ec1a0)(object,nullptr));
            return go.get() && ba::native<bool(*)(Obj,Obj)>(0x508a650)(go.get(),nullptr);};
        if(!active(main.get()))return;
        Root root(ba::call(main.get(),"get_transform")),path(ba::str("LeftMenus/PlayerInfo"));void* find[]={path.get()};
        Root transform(ba::call(root.get(),"Find",1,find));if(!transform.get())return;
        auto component=[](Obj transform,const char* ns,const char* name) {
            Obj type=ba::api<Obj(*)(Obj)>("il2cpp_class_get_type")(ba::find_class(ns,name));
            Root reflected(ba::api<Obj(*)(Obj)>("il2cpp_type_get_object")(type));
            return ba::native<Obj(*)(Obj,Obj,Obj)>(0x50856a0)(transform,reflected.get(),nullptr);
        };
        Root owner(component(transform.get(),"Uncapped.UI","UISelfPlayerProfile"));
        if(!owner.get() || !ba::get<bool>(owner.get(),"_isInitialized") || !active(owner.get()))return;
        Root vm(ba::get<Obj>(owner.get(),"_playerProfileVM"));
        if(!vm.get() || !ba::get<bool>(vm.get(),"_isInitialized"))return;
        Root set(ba::call(vm.get(),"get_IsModelSet"));
        if(!set.get() || !ba_catalog::unbox<bool>(set.get()))return;
        Root services(ba::get<Obj>(ba::owner,"<ServiceManager>k__BackingField"));
        require(ba::klass(vm.get())==ba::find_class("Uncapped.UI","PlayerProfileVM") &&
            ba::get<Obj>(vm.get(),"_serviceManager")==services.get() &&
            ba::get<Obj>(owner.get(),"_serviceManager")==services.get() &&
            ba::read<Obj>(services.get(),0x10)==front &&
            ba::get<Obj>(owner.get(),"_deckSelector")==ba::get<Obj>(front,"_deckSelector"),"menu header service ownership mismatch");
        Root identity(ba::get<Obj>(front,"_playerGameHandle")),named(ba::get<Obj>(identity.get(),"playerHandleWithName_"));
        // Match the shipped header's two-string selection. Front.get_DisplayName
        // adds an alias suffix; Front.SetPlayerName starts an original connection.
        Root wanted(ba::get<Obj>(named.get(),ba::get<bool>(front,"_nameRestrictedRegion")?"filteredName_":"playerName_"));
        require(wanted.get() && ba::klass(wanted.get())==ba::find_class("System","String"),"menu header name unavailable");
        Root before(ba::call(vm.get(),"get_PlayerName"));const auto expected=ba_catalog::utf8(wanted.get());
        if(ba_catalog::utf8(before.get())!=expected) {
            ba::native<void(*)(Obj,Obj,Obj)>(0x3d29560)(vm.get(),wanted.get(),nullptr);
            ba::log("Local menu header name refreshed: originalBinding=1 networkRequest=0");
        }
        if(!proven && ba::flag(L"-menu-profile-proof")) {
            Root labelPath(ba::str("PlayerName"));void* args[]={labelPath.get()};
            Root labelTransform(ba::call(transform.get(),"Find",1,args));
            Root label(labelTransform.get()?component(labelTransform.get(),"TMPro","TextMeshProUGUI"):nullptr);
            if(!label.get())return;
            Root text(ba::call(label.get(),"get_text")),actual(ba::call(vm.get(),"get_PlayerName"));
            if(ba_catalog::utf8(text.get())!=expected || ba_catalog::utf8(actual.get())!=expected)return;
            if(!proofDue){proofDue=now+2500;return;}if(now<proofDue)return;
            captureHeader(++proofSequence);
            proven=true;ba::log("MENU PROFILE PROOF passed: {\"name\":%s,\"label\":%s,\"owned\":true,\"worldIdle\":true,\"networkRequest\":false,\"capture\":true,\"renderStateRestored\":true,\"sequence\":%u}",
                ba_catalog::quote(expected).c_str(),ba_catalog::quote(ba_catalog::utf8(text.get())).c_str(),proofSequence);
        }
    }catch(const std::exception& error) {
        unavailable=true;ba::log("Local menu header binding failed: %s",error.what());
    }
}
static void restoreIdentity(Obj front) {
    require(frontRoot && frontRoot->get()==front && identityRoot,"local menu identity ownership");
    require(ba_dedicated_session::worldIdle(ba::read<Obj>(front,0xd8)) &&
        !ba_bootstrap::creating && !ba_bootstrap::awaitingWorld,"local identity requires an idle native world");
    Obj named=ba::get<Obj>(identityRoot->get(),"playerHandleWithName_");
    Obj name=ba::get<Obj>(named,"playerName_");
    ba::set<Obj>(front,"_playerGameHandle",identityRoot->get());
    ba::set<Obj>(front,"_currentPlayerName",name);
    Obj account=ba::get<Obj>(front,"_accountService");
    Obj profile=ba::get<Obj>(account,"<ProfileCache>k__BackingField");
    require(profile!=nullptr,"local menu profile missing");
    ba::set<uint64_t>(profile,"steamId_",1);ba::set<bool>(profile,"isAlias_",true);
    ba::set<Obj>(profile,"name_",name);
}
static bool ensure(Obj front) {
    if(failed)return false;
    try {
        Obj services=ba::get<Obj>(ba::owner,"<ServiceManager>k__BackingField");
        require(services && ba::read<Obj>(services,0x10)==front &&
            ba::read<Obj>(services,0x18)==ba::read<Obj>(front,0xd8),"local menu service ownership");
        if(!ba_dedicated_session::unityThread)ba_dedicated_session::unityThread=GetCurrentThreadId();
        require(ba_dedicated_session::unityThread==GetCurrentThreadId(),"local menu called off Unity thread");
        ba_dedicated_session::observedFront=front;
        if(initialized) {require(ready(front),"local menu front changed");refreshHeaderName(front);return true;}
        if(!ba_dedicated_session::inMenu() || !ba_dedicated_session::worldIdle(ba::read<Obj>(front,0xd8)))return false;
        if(!baseInitialized) {
        frontRoot=std::make_unique<Root>(front);
        identityRoot=std::make_unique<Root>(ba_lan_bootstrap::identityLan(front,0));
        Root name(ba::str(ba::argument(L"-player-name=","Offline Player").c_str()));
        Obj named=ba::get<Obj>(identityRoot->get(),"playerHandleWithName_");
        ba::set<Obj>(named,"playerName_",name.get());ba::set<Obj>(named,"filteredName_",name.get());
        Obj account=ba::get<Obj>(front,"_accountService");ba::local_profile(account);
        Obj selector=ba::get<Obj>(front,"_deckSelector"),storage=ba::read<Obj>(ba::owner,0x110);
        require(selector && storage && selector==ba::read<Obj>(ba::owner,0x108) &&
            selector==ba::get<Obj>(account,"_deckSelector") && storage==ba::read<Obj>(selector,0x10) &&
            storage==ba::get<Obj>(account,"_localDeckStorage"),"local menu native deck storage ownership");
        restoreIdentity(front);
        ba_dedicated_deck::initializeLocal(front);ba_practice_settings::selection();
        baseInitialized=true;
        }
        require(frontRoot && frontRoot->get()==front,"local menu initialization owner changed");
        if(!ba_cosmetics::prepare(front))return false;
        // Search can begin before optional presence. One application clock keeps
        // its DateTime epoch stable across authentication and reconnection.
        ba_community_invites::anchorClock(front);initialized=true;
        ba::log("Local menu ready: native local deck storage; configured name; transportIndependent=1 BA_RESURRECTION_LOCAL_MENU_V1");
        return true;
    } catch(const std::exception& error) {
        failed=true;ba::log("Local menu initialization failed: %s",error.what());return false;
    }
}
}
