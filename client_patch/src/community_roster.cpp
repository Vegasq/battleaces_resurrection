#pragma once
// The existing pooled outer row keeps its real FriendModel and InviteToGame
// binding. Its child FriendVM is presentation-only: it never observes a synthetic
// Steam identity. Exact prefab/binding evidence is in custom-roster-bindings.txt.
namespace ba_community_roster {
using ba::Obj;using ba_local::Root;
namespace wire=ba_community_wire;
struct Row {
    std::string profile;Root row,model,child;
    Row(std::string p,Obj r,Obj m,Obj c):profile(std::move(p)),row(r),model(m),child(c){}
};
static auto& rows=*new std::vector<std::unique_ptr<Row>>();
static auto& screen=*new std::unique_ptr<Root>();
static bool dirty=false,building=false;
static unsigned smokeStage=0,smokeRounds=0;
static unsigned smokeChurn=0;
static ULONGLONG smokeAt=0;
static auto& smokeButton=*new std::unique_ptr<Root>();
static bool initialized(Obj object) {return object && ba::read<bool>(object,0x20);}
static bool session() {return ba_community_native::owns(ba_dedicated_session::observedFront);}
static bool owns(Obj object) {
    return session() && object && !strcmp(ba_dedicated_session::className(object),"CustomGameInvitePlayerVM") &&
        ba::get<Obj>(object,"_frontServer")==ba_dedicated_session::observedFront;
}
static Row* ownedRow(Obj object) {
    if(!session())return nullptr;
    for(auto& row:rows)if(row->row.get()==object)return row.get();
    return nullptr;
}
static void virtualBind(Obj object,Obj model,Obj method) {
    wire::require(object!=nullptr,"community model binder object missing");
    const auto pointer=ba::read<void(*)(Obj,Obj,Obj)>(ba::klass(object),0x238);
    wire::require(pointer!=nullptr,"community model binder unavailable");pointer(object,model,method);
}
static std::string literalName(const std::string& text) {
    // Both the label and its truncation tooltip accept TMP rich text. Normalize
    // only the presentation string; named protobuf identities stay byte-exact.
    std::string result;
    for(char value:text) {
        if(value=='<')result+="\xef\xbc\x9c";
        else if(value=='>')result+="\xef\xbc\x9e";
        else result+=value;
    }
    return result;
}
template<class T> static void property(Obj child,uintptr_t setter,T value) {
    ba::native<void(*)(Obj,T,Obj)>(setter)(child,value,nullptr);
}
static void present(Obj child,const wire::Player* player) {
    wire::require(child && !strcmp(ba_dedicated_session::className(child),"FriendVM"),"community child renderer type");
    // Clear an old observed native model through its own lifecycle, without
    // invoking a Refresh for our owned model or forging IsModelSet=true.
    if(ba::read<bool>(child,0x50))ba::call(child,"ClearModel");
    wire::require(!ba::read<bool>(child,0x50),"community child still observes a model");
    const bool self=player && player->profile==ba_community::welcome.profile;
    const bool busy=player && (!player->invitable || player->status!=0);
    const char* status=!player?"":self?"You":ba_community_invites::pending(player->profile)?"Invitation pending":player->status==2?"In a match":player->status==1?"In a lobby":busy?"Unavailable":"Available";
    Root name(ba::str(player?literalName(player->name).c_str():"")),label(ba::str(status));
    property(child,0x3d00b70,name.get());property(child,0x3d00e80,label.get());
    property(child,0x3d00c10,player!=nullptr);property(child,0x3d00cb0,player && player->status==2);
    property(child,0x3d00d50,player?1:3);property(child,0x3d00de0,busy);
    property(child,0x3d00f20,0);property(child,0x3d00fc0,0);property(child,0x3d01060,0);
    property(child,0x3d01100,false);property(child,0x3d011b0,false);property<Obj>(child,0x3d01250,nullptr);
    property(child,0x3d012f0,false);property(child,0x3d01390,false);property(child,0x3d01440,false);
    property(child,0x3d014f0,false);property(child,0x3d01590,false);property(child,0x3d01640,player!=nullptr);
    if(initialized(child))ba::native<void(*)(Obj,Obj)>(0x3d699d0)(child,nullptr);
}
static void clearPresentation() {for(auto& row:rows)present(row->child.get(),nullptr);}
static void reset() {
    // resetAtMenu runs on the owned Unity thread. Do not leave live observed
    // outer models referring to a discarded ownership registry.
    if(screen && initialized(screen->get())) {
        clearPresentation();
        ba::native<void(*)(Obj,Obj)>(0x3ca98e0)(screen->get(),nullptr);
    }
    rows.clear();screen.reset();smokeButton.reset();dirty=false;building=false;
    smokeStage=0;smokeRounds=0;smokeChurn=0;smokeAt=0;
}
static Obj reflectedType(const char* ns,const char* name) {
    Obj type=ba::api<Obj(*)(Obj)>("il2cpp_class_get_type")(ba::find_class(ns,name));
    return ba::api<Obj(*)(Obj)>("il2cpp_type_get_object")(type);
}
static Obj modelFor(const wire::Player& player) {
    // Reconstruct the evidenced simple constructor, omitting its Steam presence
    // call. No texture/avatar task, Steam list, or global friend state is created.
    Obj klass=ba::find_class("Uncapped.UI","FriendModel");
    ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(klass);
    Root model(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(klass));
    Root extension(ba::make("Uncapped.UI","FriendExtension")),service(ba::make("CommonPb","ServiceHandle"));
    ba::set<uint64_t>(model.get(),"_friend",ba_community::alias(player.profile));
    ba::set<Obj>(model.get(),"_friendExtension",extension.get());
    ba::set<bool>(model.get(),"_isImageDirty",false);
    ba::set<bool>(extension.get(),"AliasedVersion",true);ba::set<bool>(extension.get(),"IsAliased",true);
    ba::set<int>(extension.get(),"PartyStatus",player.invitable?3:1);
    // The original row's region/environment checks are superseded by the scoped
    // final reason/CanInvite wrappers. These fields must still be valid objects.
    ba::set<Obj>(extension.get(),"Environment",ba::str("community"));
    ba::set<Obj>(extension.get(),"PlayerHandle",ba_community_native::named(player.profile));
    ba::set<Obj>(service.get(),"handle_",ba::str(player.profile.c_str()));
    ba::set<Obj>(extension.get(),"FrontHandle",service.get());
    return model.get();
}
static void populate(Obj object) {
    wire::require(owns(object) && initialized(object) && !building,"community roster lifecycle/ownership");
    wire::require(!screen || screen->get()==object || !initialized(screen->get()),"multiple active community invite pickers");
    building=true;
    try {
        clearPresentation();
        ba::native<void(*)(Obj,Obj)>(0x3ca98e0)(object,nullptr);
        rows.clear();screen=std::make_unique<Root>(object);
        ba_community_native::pruneIdentities();
        Root pool(ba::get<Obj>(object,"_pool")),parent(ba::get<Obj>(object,"_root"));
        wire::require(pool.get() && parent.get() && !strcmp(ba_dedicated_session::className(pool.get()),"UIPoolManager"),"community roster pool unavailable");
        Root type(reflectedType("Uncapped.UI","CustomGameInvitePlayerItemVM"));
        Root rowPool(ba::native<Obj(*)(Obj,Obj,Obj)>(0x3d5d030)(pool.get(),type.get(),nullptr));
        for(const auto& player:ba_community_native::directory.players) {
            Root model(modelFor(player));
            Root row(ba::native<Obj(*)(Obj,Obj,Obj,Obj)>(0x3d5cf30)(pool.get(),rowPool.get(),parent.get(),nullptr));
            bool listed=false;
            try {
                wire::require(row.get() && !strcmp(ba_dedicated_session::className(row.get()),"CustomGameInvitePlayerItemVM"),"community pool returned wrong row");
                Root child(ba::get<Obj>(row.get(),"_friendVM"));
                wire::require(initialized(child.get()),"community row child bindings not initialized");
                rows.push_back(std::make_unique<Row>(player.profile,row.get(),model.get(),child.get()));
                virtualBind(row.get(),model.get(),ba::read<Obj>(ba::klass(row.get()),0x240));
                ba_local::addItem(ba::get<Obj>(object,"_inviteItems"),row.get());listed=true;
                wire::require(!ba::read<bool>(child.get(),0x50),"community row child unexpectedly bound");
            } catch(...) {
                if(!listed && row.get()) {
                    // A failed bind must not retain ownership of an object that
                    // is already back in the native pool and may be reused.
                    if(!rows.empty() && rows.back()->row.get()==row.get())rows.pop_back();
                    ba::native<void(*)(Obj,Obj,Obj)>(0x3d5cf90)(pool.get(),row.get(),nullptr);
                }
                throw;
            }
        }
        property(object,0x3ca9010,!rows.empty());dirty=false;building=false;
        ba::log("Community roster populated: revision=%llu rows=%llu presentationOnly=1 BA_RESURRECTION_COMMUNITY_ROSTER_V1",
            static_cast<unsigned long long>(ba_community_native::directory.revision),static_cast<unsigned long long>(rows.size()));
    } catch(...) {
        building=false;
        // Tear down any successfully appended prefix through the native list.
        // If native cleanup itself fails, retain its ownership records so a
        // later callback can never mistake a synthetic model for a Steam model.
        try {
            clearPresentation();
            ba::native<void(*)(Obj,Obj)>(0x3ca98e0)(object,nullptr);
            rows.clear();screen.reset();
        } catch(...) {ba::log("Community roster failed-build cleanup incomplete; ownership retained");}
        throw;
    }
}
static void released(Obj object) {
    if(screen && screen->get()==object) {
        clearPresentation();rows.clear();screen.reset();dirty=false;
        ba::log("Community roster released: rows=0 childBindings=0");
    }
}
static void changed() {dirty=true;}
static void update() {
    if(dirty && screen && initialized(screen->get()) && !building)populate(screen->get());
}
static bool canInvite(const Row& row) {return ba_community_invites::canInvite(row.profile);}
static Obj mainScreen() {
    Root manager(ba_community_native::manager(ba_dedicated_session::observedFront));
    wire::require(manager.get()!=nullptr,"community main screen manager unavailable");
    Root event(ba::get<Obj>(manager.get(),"PredictedLobbyChanged"));if(!event.get())return nullptr;
    Root delegates(ba::call(event.get(),"GetInvocationList"));
    const auto count=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(delegates.get());
    wire::require(count<=128,"community main screen listener capacity");
    for(size_t i=0;i<count;++i) {
        Root target(ba::call(ba::read<Obj>(delegates.get(),0x20+sizeof(Obj)*i),"get_Target"));
        if(target.get() && !strcmp(ba_dedicated_session::className(target.get()),"CustomGameMainScreenVM") &&
            initialized(target.get()) && ba::get<Obj>(target.get(),"_frontServer")==ba_dedicated_session::observedFront &&
            ba::get<Obj>(target.get(),"_customGameLobbyManager")==manager.get())return target.get();
    }
    return nullptr;
}
static void smoke(Obj front); // Defined below after the ordinary adapter hooks.
}

extern "C" __declspec(dllexport) void OfflineCommunityPopulate(void* object,void* method) {
    ba::init();
    if(!ba::community()){ba::native<void(*)(ba::Obj,ba::Obj)>(0x3ca9b30)(object,method);return;}
    try{ba_community_roster::populate(object);}
    catch(const std::exception& e){ba_lan::fail("community roster population",e);}
}
extern "C" __declspec(dllexport) void OfflineCommunityRosterRelease(void* object,void* method) {
    ba::init();
    if(ba::community())try{ba_community_roster::released(object);}
    catch(const std::exception& e){ba_lan::fail("community roster release",e);}
    ba::native<void(*)(ba::Obj,ba::Obj)>(0x3d69a50)(object,method);
}
extern "C" __declspec(dllexport) void OfflineCommunityForceFriends(void* friends,uint64_t identity,void* method) {
    ba::init();
    if(!ba::community()){ba::native<void(*)(ba::Obj,uint64_t,ba::Obj)>(0x3e738a0)(friends,identity,method);return;}
    try {
        using namespace ba_community_roster;
        Root main(mainScreen());
        wire::require(session() && main.get() && friends && ba::get<Obj>(main.get(),"_steamFriends")==friends,
            "community friend refresh ownership");
    }catch(const std::exception& e){ba_lan::fail("community roster friend refresh",e);}
}
extern "C" __declspec(dllexport) void OfflineCommunityFriendPresentation(void* child,void* model,void* method) {
    ba::init();
    try {
        using namespace ba_community_roster;
        for(const auto& row:rows)if(row->child.get()==child || row->model.get()==model) {
            wire::require(session() && row->child.get()==child && row->model.get()==model,"community child binding outside owned row");
            present(child,ba_community_native::player(row->profile));return;
        }
        virtualBind(child,model,method);
    }catch(const std::exception& e){ba_lan::fail("community friend presentation",e);}
}
extern "C" __declspec(dllexport) void OfflineCommunityInviteReason(void* object,int reason,void* method) {
    ba::init();
    if(auto* row=ba_community_roster::ownedRow(object))reason=ba_community_invites::pending(row->profile)?4:0;
    ba::native<void(*)(ba::Obj,int,ba::Obj)>(0x3ca83c0)(object,reason,method);
}
extern "C" __declspec(dllexport) bool OfflineCommunityCanInvite(void* object,bool* backing,bool value,void* property,void* alsoUpdate,void* method) {
    ba::init();
    if(auto* row=ba_community_roster::ownedRow(object)) {
        if(backing==reinterpret_cast<bool*>(static_cast<char*>(object)+0x58))value=ba_community_roster::canInvite(*row);
    }
    return ba::native<bool(*)(ba::Obj,bool*,bool,ba::Obj,ba::Obj,ba::Obj)>(0x2366d0)(object,backing,value,property,alsoUpdate,method);
}

namespace ba_community_roster {
static void verifyRenderedName(Obj child,const std::string& expected) {
    Root collection(ba::get<Obj>(child,"_bindings"));
    wire::require(collection.get() && ba::get<bool>(collection.get(),"_initialized"),"community row bindings inactive");
    Root bindings(ba::get<Obj>(collection.get(),"_bindings"));
    const int count=ba_local::count(bindings.get());wire::require(count<=128,"community row binding capacity");
    unsigned checked=0;
    for(int i=0;i<count;++i) {
        void* args[]={&i};Root binding(ba::call(bindings.get(),"get_Item",1,args));
        Root source(ba::get<Obj>(binding.get(),"_source"));
        Root value(ba::get<Obj>(source.get(),"BindyValue"));
        if(!value.get() || ba::get<Obj>(value.get(),"Target")!=child ||
            ba_catalog::utf8(ba::get<Obj>(value.get(),"VariableName"))!="PlayerName")continue;
        Root targets(ba::get<Obj>(binding.get(),"_targets"));
        const int targetCount=ba_local::count(targets.get());wire::require(targetCount<=16,"community name binding target capacity");
        for(int j=0;j<targetCount;++j) {
            void* itemArgs[]={&j};Root target(ba::call(targets.get(),"get_Item",1,itemArgs));
            Root targetValue(ba::get<Obj>(target.get(),"BindyValue"));
            Root label(ba::get<Obj>(targetValue.get(),"Target"));
            wire::require(ba_catalog::utf8(ba::get<Obj>(targetValue.get(),"VariableName"))=="text","unexpected community name binding property");
            Root actual(ba::call(label.get(),"get_text"));
            wire::require(ba_catalog::utf8(actual.get())==expected,"community TMP label did not receive name");
            Root gameObject(ba::call(label.get(),"get_gameObject")),active(ba::call(gameObject.get(),"get_activeInHierarchy"));
            wire::require(*ba::api<bool*(*)(Obj)>("il2cpp_object_unbox")(active.get()),"community TMP label hierarchy inactive");++checked;
        }
    }
    wire::require(checked>0,"community row PlayerName receiver missing");
}
static Obj pickerButton(Obj main) {
    Root allowed(ba::call(main,"get_CanInvitePlayer"));
    wire::require(*ba::api<bool*(*)(Obj)>("il2cpp_object_unbox")(allowed.get()),"community picker button unavailable");
    Root type(reflectedType("Uncapped.UI","ShowUIObjectComponent"));
    Root gameObject(ba::native<Obj(*)(Obj,Obj)>(0x6ec1a0)(main,nullptr));
    Root components(ba::native<Obj(*)(Obj,Obj,bool,Obj)>(0x5089c40)(gameObject.get(),type.get(),true,nullptr));
    const auto count=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(components.get());
    wire::require(count<=128,"community picker component capacity");Obj result=nullptr;
    for(size_t i=0;i<count;++i) {
        Obj button=ba::read<Obj>(components.get(),0x20+i*sizeof(Obj));
        Root descriptor(ba::get<Obj>(button,"_showUIObject"));
        if(descriptor.get() && ba::get<int>(descriptor.get(),"_prefabKey")==101) {
            wire::require(!result && !ba::get<Obj>(descriptor.get(),"_model") && ba::get<Obj>(button,"_pool"),"community picker descriptor mismatch");result=button;
        }
    }
    wire::require(result!=nullptr,"community picker component missing");return result;
}
static void smoke(Obj front) {
    if(!ba::flag(L"-community-roster-smoke"))return;
    const auto now=GetTickCount64();if(!smokeAt){smokeAt=now+2500;return;}if(now<smokeAt)return;
    Root manager(ba_community_native::manager(front));
    if(smokeStage==0 && ba_community::directory.players.size()>=2) {
        Root controller(ba::get<Obj>(manager.get(),"_menuFlowController"));
        wire::require(controller.get() && !strcmp(ba_dedicated_session::className(controller.get()),"MenuFlowController") &&
            ba::get<Obj>(controller.get(),"_flowGraph"),"community menu navigation unavailable");
        Root link(ba::make("Uncapped.UI","UILink"));ba::set<int>(link.get(),"PrefabKey",97);
        smokeStage=1;ba::log("COMMUNITY ROSTER SMOKE native menu TravelToScreen CustomGameScreen (NOT manual UI input)");
        // The real screen's Initialize owns EnterLobbyScreen/Create. Calling the
        // manager alone proves admission but does not display this screen.
        ba::native<void(*)(Obj,Obj,Obj)>(0x3d52440)(controller.get(),link.get(),nullptr);
    } else if(smokeStage==1 && !ba_community_native::installedLobby.empty() && ba_community_native::requests.empty()) {
        Root main(mainScreen());if(!main.get())return;
        smokeButton=std::make_unique<Root>(pickerButton(main.get()));
        smokeStage=2;smokeAt=now+1500;
        ba::log("COMMUNITY ROSTER SMOKE native picker Show (NOT manual UI input)");
        ba::native<void(*)(Obj,Obj)>(0x3d62c40)(smokeButton->get(),nullptr);
    } else if(smokeStage==2) {
        wire::require(screen && initialized(screen->get()) && rows.size()==ba_community::directory.players.size(),"community roster smoke row count");
        wire::require(ba::get<Obj>(smokeButton->get(),"_uiObject")==screen->get(),"community picker owner mismatch");
        for(const auto& row:rows) {
            const auto* player=ba_community_native::player(row->profile);
            wire::require(player && ba::read<bool>(row->row.get(),0x50) && !ba::read<bool>(row->child.get(),0x50) &&
                ba::get<bool>(row->row.get(),"_canInvite")==canInvite(*row),"community roster smoke binding/action guard");
            const auto expected=literalName(player->name);
            wire::require(ba_catalog::utf8(ba::get<Obj>(row->child.get(),"_playerName"))==expected,"community roster smoke name mismatch");
            verifyRenderedName(row->child.get(),expected);
        }
        if(!smokeRounds) {
            if(smokeChurn==0 && rows.size()==3) {
                smokeChurn=1;ba::log("COMMUNITY ROSTER SMOKE live join: count=3 TMP checked");
            } else if(smokeChurn==1 && rows.size()==2) {
                smokeChurn=2;ba::log("COMMUNITY ROSTER SMOKE live departure: count=2 TMP checked");
            }
            if(smokeChurn!=2){smokeAt=now+100;return;}
        }
        ++smokeRounds;
        ba::log("COMMUNITY ROSTER SMOKE rows verified round=%u count=%llu; TMP text and active hierarchy checked, outer bound, child unbound, availability checked",smokeRounds,static_cast<unsigned long long>(rows.size()));
        ba::call(smokeButton->get(),"Hide");
        wire::require(!screen && rows.empty(),"community roster smoke release retained rows");
        smokeStage=smokeRounds<3?1:3;smokeAt=now+1000;
    } else if(smokeStage==3) {
        smokeStage=4;ba::native<void(*)(Obj,bool,Obj)>(0x3cab820)(manager.get(),false,nullptr);
    } else if(smokeStage==4 && ba_community_native::requests.empty() && ba_community_native::installedLobby.empty()) {
        wire::require(!screen && rows.empty(),"community roster smoke final ownership");smokeStage=5;
        ba::log("COMMUNITY ROSTER SMOKE passed: three pooled open/close cycles; rows=0 childBindings=0 presence retained");
    }
}
}
