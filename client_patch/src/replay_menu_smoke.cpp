#pragma once
// Explicit healthy original replay API/lifecycle control. No ReplayFiles batch,
// manual FSM transition, helper ticks, new UI route, or simulated button click.
namespace ba_replay_menu {
using ba::Obj;using ba_local::Root;using ba_native_settings::require;
namespace codec=ba_native_replay_reader;
namespace ui=ba_practice_settings_ui;
struct Probe {
    Root owner,front,replay,simulation;
    ba_native_settings::Handle file;
    uint64_t world=0;int frames=0;
    Probe(Obj a,Obj b,Obj c,Obj d):owner(a),front(b),replay(c),simulation(d){}
};
static auto& probe=*new std::unique_ptr<Probe>();
static unsigned stage=0;static ULONGLONG due=0,deadline=0;
static std::string lastState;
static bool canInspect(){return probe && (stage==1 || stage==2);}
static void update(Obj front) {
    if(!ba::flag(L"-native-replay-menu-smoke") || stage>=4 || GetTickCount64()<due)return;
    due=GetTickCount64()+50;
    try {
        require(ui::unityThread() && ba::offlinePractice() && ba_native_settings::session &&
            ba::flag(L"-native-quit-smoke") && ba::flag(L"-native-quit-gate-smoke") &&
            ba::flag(L"-replay-binding-inventory") && ba::flag(L"-replay-signal-inventory") &&
            ba::flag(L"-replay-nody-inventory") && !ba::flag(L"-practice-ai-smoke") &&
            !ba::flag(L"-native-replay-playback-smoke"),"replay menu control requires one owned diagnostic API sequence");
        const auto& profile=ba_native_settings::session->profile();const std::string prefix="nativestest_replayui_";
        require(profile.size()==prefix.size()+12 && profile.rfind(prefix,0)==0 &&
            profile.find_first_not_of("0123456789abcdef",prefix.size())==std::string::npos,
            "replay menu requires a fresh owned profile");
        Root fsm(ba::get<Obj>(ba::owner,"_mainFSM")),current(ba::get<Obj>(fsm.get(),"_currentState"));
        const auto state=ba_replay_binding::className(current.get());
        if(state!=lastState){lastState=state;ba::log("NATIVE REPLAY MENU state: stage=%u state=%s",stage,state.c_str());}
        const auto now=GetTickCount64();
        if(stage==0) {
            if(!ba_local_menu::ready(front) || !ba_dedicated_session::inMenu() || !ba_client::nativeIdle(front))return;
            if(!deadline){deadline=now+60000;due=now+2500;return;}
            require(now<deadline,"replay menu entry deadline");
            require(!ba_practice::active() && !ba_local::server() && ba_client::worldOwner==ba_client::Owner::None &&
                ba::read<Obj>(current.get(),0x18)==ba::owner && current.get()==ba::read<Obj>(ba::owner,0x2c0),
                "replay menu requires the original idle main-menu owner");
            Root replay(ba::get<Obj>(ba::owner,"<Replay>k__BackingField")),simulation(ba::get<Obj>(replay.get(),"_simulation"));
            require(replay.get() && codec::type("Uncapped","Replay","RGame.dll")==ba::klass(replay.get()) &&
                simulation.get() && !ba::read<uint64_t>(simulation.get(),0x1a8) &&
                !ba::get<Obj>(replay.get(),"_gameData"),"replay menu refuses preexisting replay/world data");
            probe=std::make_unique<Probe>(ba::owner,front,replay.get(),simulation.get());
            auto& directory=ba_native_storage::destination(ba_native_storage::Kind::Replays);
            const auto selected=directory.directory.apiPath()+L"\\native-menu-replay.rep";
            probe->file.value=CreateFileW(selected.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,
                FILE_FLAG_OPEN_REPARSE_POINT,nullptr);ba_native_settings::ordinary(probe->file.value);
            LARGE_INTEGER size{};require(GetFileSizeEx(probe->file.value,&size) && size.QuadPart>0 &&
                size.QuadPart<=4*1024*1024,"replay menu selected file bound");
            wchar_t final[32768];const auto count=GetFinalPathNameByHandleW(probe->file.value,final,32768,FILE_NAME_NORMALIZED|VOLUME_NAME_DOS);
            require(count && count<32768 && !_wcsicmp(final,selected.c_str()),"replay menu file escapes the pinned owned directory");
            Root path(ba::api<Obj(*)(const wchar_t*,int32_t)>("il2cpp_string_new_utf16")(selected.data(),static_cast<int32_t>(selected.size())));
            ba::log("NATIVE REPLAY MENU load dispatch: profile=%s mainMenu=1 worldIdle=1 originalLoadReplayFromFile=1 extraPlayCalls=0 fsmWrites=0 helperTicks=0",profile.c_str());
            stage=1;deadline=now+60000;void* args[]={path.get()};
            Root loaded(codec::invoke(codec::method(ba::klass(replay.get()),"LoadReplayFromFile",1,0x3dddab0,0x06000952),replay.get(),args));
            require(loaded.get() && ba_catalog::unbox<bool>(loaded.get()),"original replay file load returned false");
            Root frames(codec::get(replay.get(),"get_FrameCount",0x3ddb470,0x0600092a)),data(ba::get<Obj>(replay.get(),"_gameData"));
            probe->frames=ba_catalog::unbox<int>(frames.get());require(data.get() && probe->frames>30 && probe->frames<=65536,
                "replay menu decoded data/frame bound");
            const auto digest=ba_lan::sha(ba_lan::serialize(data.get()));std::string hash;char byte[3];
            for(unsigned char value:digest){sprintf_s(byte,"%02x",value);hash+=byte;}
            ba::log("NATIVE REPLAY MENU loaded: frames=%d gameDataSha256=%s loadReturned=1 originalPlayInternal=1",probe->frames,hash.c_str());
            return;
        }
        require(now<deadline && probe && probe->owner.get()==ba::owner && probe->front.get()==front &&
            ba::get<Obj>(probe->replay.get(),"_simulation")==probe->simulation.get(),"replay menu owner/deadline differs");
        if(stage==1) {
            if(state!=".RGameInGameState" || !ba::read<bool>(probe->simulation.get(),0x1a0) ||
                ba::read<int>(probe->simulation.get(),0xac)<30)return;
            probe->world=ba::read<uint64_t>(probe->simulation.get(),0x1a8);
            require(probe->world && ba::read<Obj>(current.get(),0x18)==ba::owner && !ba_practice::active(),
                "replay menu original in-game world/owner unavailable");
            ba::log("NATIVE REPLAY MENU in-game: world=%llu presented=%d originalMainFsm=1 practiceActive=0 frames=%d",
                static_cast<unsigned long long>(probe->world),ba::read<int>(probe->simulation.get(),0xac),probe->frames);
            stage=2;
        }
        if(stage==2) {
            if(!ba_replay_binding::finished)return;
            require(ba_replay_binding::passed && state==".RGameInGameState" &&
                ba::read<uint64_t>(probe->simulation.get(),0x1a8)==probe->world,"replay menu requires the unchanged passive replay inventory");
            Root type(ui::reflectedType("Uncapped","ConcedeFlowUIController"));void* args[]={type.get()};
            Root values(ba::invoke(ba::find_class("UnityEngine","Resources"),nullptr,"FindObjectsOfTypeAll",1,args));
            std::unique_ptr<Root> controller;
            for(size_t i=0;i<ui::arrayCount(values.get(),64);++i) {
                Obj candidate=ui::arrayItem(values.get(),i);
                if(ba::get<Obj>(candidate,"_simulation")!=probe->simulation.get() || !ui::active(candidate))continue;
                require(!controller,"replay menu cleanup controller ambiguous");controller=std::make_unique<Root>(candidate);
            }
            require(controller && ba::get<Obj>(controller->get(),"_signalRouter")==ba::read<Obj>(ba::owner,0x238),
                "replay menu cleanup requires the current original controller");
            stage=3;
            ba::log("NATIVE REPLAY MENU exit API dispatch: originalReplayEndGame=1 buttonClicks=0 fsmWrites=0 helperTicks=0");
            codec::invoke(codec::method(ba::klass(controller->get()),"ReplayEndGame",0,0x3b443b0,0x06001718),controller->get());
            ba::log("NATIVE REPLAY MENU exit API returned: originalCallbackReturned=1");return;
        }
        if(stage==3) {
            if(!ba_dedicated_session::inMenu() || !ba_local_menu::ready(front) || !ba_client::nativeIdle(front))return;
            require(!ba::read<uint64_t>(probe->simulation.get(),0x1a8) &&
                !ba::read<bool>(probe->simulation.get(),0x1a0) && !ba_practice::active() &&
                ba_client::worldOwner==ba_client::Owner::None,"replay menu exit did not release the original world");
            probe.reset();stage=4;
            ba::log("NATIVE REPLAY MENU API control passed: mainMenu=1 worldIdle=1 originalExitApi=1 probeRootsReleased=1 filePinReleased=1 buttonClicks=0 fsmWrites=0 helperTicks=0 BA_RESURRECTION_REPLAY_MENU_V1");
        }
    } catch(const std::exception& error){probe.reset();stage=5;ba::log("Native replay menu control failed: %s",error.what());}
}
}
