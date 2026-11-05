#pragma once
// Opt-in owned menu diagnostic. Original selection, PlayPreview and Back only;
// never sets the clip, frame, player state or cleanup fields itself.
namespace ba_cosmetics {
static unsigned videoStage=0,videoIndex=0,videoSamples=0;
static ULONGLONG videoDue=0,videoDeadline=0;
static auto& videoBefore=*new Pairs();
static auto& videoVM=*new std::unique_ptr<Root>();
static auto& videoPlayer=*new std::unique_ptr<Root>();
static auto& videoRows=*new std::string();
static int64_t videoFirstFrame=-1;
static double videoFirstTime=-1;
static bool videoAdvanced=false;
static const uint32_t videoItems[]={11,12,11};
static std::string videoBool(bool v){return v?"true":"false";}
static void guardVideoBodies() {
    originalBackBody(0x3b6afe0,208,"2e478bbd1c8d8dad9b9c78385787072808647ff40b1af4dd2f35fb058ef21497");
    originalBackBody(0x3b6b0b0,202,"c915cbee7f9820137992c681e36e8698e925292ef781270a6f18785467cae1cf");
    originalBackBody(0x3b6b180,324,"4afe62b085f69352477a045820b73d5ef0037385daf13c78fad1c588f792a49a");
    originalBackBody(0x3b6b2d0,381,"ef4024ecc27614779d750ede9fadeeccc30adb69d6f9f798da83faece626cd89");
    originalBackBody(0x3b6b450,281,"adf12baa3bfca8232aa1fa07fd15064097a5da4067118b614a78acd305c04dca");
    originalBackBody(0x3b6b570,133,"a4bead2747131fd7e8460cb92ec4a81129eebf2a879674272129b19412ab6fe5");
    originalBackBody(0x3b6b600,45,"651038d273d4991093e9e89f54b43c516eb89ff0ad225b480e9cb5948b5bc9c0");
    originalBackBody(0x3b6b630,233,"a69364eb70a863b7ea027bc2386aaeec3406975a74f47dd0f91c9ccf68d78b1c");
    originalBackBody(0x3b6b720,665,"0ce4a0e56e67bb4b12ea36ed9442379e85105dd2cb58bacd0e34ba9a0b9b7eee");
    originalBackBody(0x3b6b9c0,105,"7581048caa4fab4dccef14bb4a7bbed79d9c8f85c1249eb9e45a859002b89be8");
    originalBackBody(0x3b6ba30,180,"ce82854732685ba1f0b872fb34d1da4945ac293da61285a58383ef4034b1d014");
    originalBackBody(0x3b6baf0,57,"084e71e7fb277fc9b112d5e2b55f162dbc5285b6fd6eb56e695eeca084d302d8");
    originalBackBody(0x3c9fd30,193,"1d800992e4413358779219a8b057a0784cda90f214f09b5e2c177ed9e1641c7a");
    originalBackBody(0x3c9fe00,136,"edae0039f2ec2daf88532b2dacad7e45e2ef377f31ab77524b309b5e12fe45ae");
    originalBackBody(0x3c9fe90,103,"26cc03c694ce698c556f9943faa85956d9d48967cd42899c74abb3660549c07f");
    originalBackBody(0x3c9ff00,1586,"82f580edc457a388c238090a98f4c68fdfe7963a5fd3291578e19519dfa7409e");
    originalBackBody(0x3ca10b0,901,"6c267f69d413c8fa2f6e722b428710cb594d1db4282dc17e2b195de35ac37f24");
    originalBackBody(0x53ea4d0,79,"04e24e9306dd65e740c98dc496c43007caccbcf6b2e7a619637fa7eaa2470e6f");
    originalBackBody(0x53ea520,79,"802e237c2999ce45c333f3f664396beb32ed7b153e787863bbdfbc9693d71a1e");
    originalBackBody(0x53ea570,79,"f28e86b7a7fc9a6824b909e75aa6dde144818237e530aeda0bb88df333018da0");
    originalBackBody(0x53ea5c0,79,"81dee47c79cb5269a2bc610be24231c4024f30dbbedfb5ac9b397a27034c0f4f");
    originalBackBody(0x53ea610,79,"8cb449ef55b8b0ca2536e83a7ae3fb2fb8578e6221a9880b2b60ebc37ce12e9c");
    originalBackBody(0x53ea660,79,"88cb5b3a9fae4d2c07fb2b1b6fbe1a51e2a719b518d4e17e32e13a2c1bdb7798");
    originalBackBody(0x53eab20,79,"dea7803dc44eb5ea8e792dbcc3838d3d634bb7b20afd23149494d5fc7e01e203");
    originalBackBody(0x53ead80,79,"3c8f41c6c0f6b85fbcbc6b8579538099b68f55f435c3b367b63b0cdd3995bf5a");
    originalBackBody(0x53eb240,79,"201c72677ce69c1003b62578b51769c59597ec074084e40368565efb066df414");
    originalBackBody(0x53eb3f0,79,"b37dd06d8c752ab9492812964f35afbbd53ced3407c26ac84b87a9c03bb942a2");
    originalBackBody(0x53eb490,79,"d6578306f19b4ef8b49a2c6b43a42b4df5e6db52f19ba9dcc99ed284d6b18a15");
    originalBackBody(0x53eb4e0,79,"b5ae5acf2d994bbfcc4b5fc429a3c966fe7d9f9ef05e5517eb70d5d65ca659cd");
    originalBackBody(0x53eb5d0,79,"ae37d479e7ef8f246e504b597f72f3117cb84ee7e5a577b284ee63ec7578abc4");
    originalBackBody(0x53eb680,79,"484c2e04ece66af2ea8c311bf06c6dac9a43c80d1597adfefcfe22fe761937c7");
}

static std::string videoObservation(const char* phase) {
    Obj vm=videoVM->get(),player=videoPlayer->get();
    Root clip(ba::call(player,"get_clip")),target(ba::call(player,"get_targetTexture"));
    Root modelClip(ba::get<Obj>(vm,"_videoClip"));
    std::string path,name;
    if(clip.get()) {
        Root p(ba::call(clip.get(),"get_originalPath")),n(ba::call(clip.get(),"get_name"));
        path=ba_catalog::utf8(p.get());name=ba_catalog::utf8(n.get());
    }
    const int64_t frame=ba_catalog::unbox<int64_t>(ba::call(player,"get_frame"));
    const double seconds=ba_catalog::unbox<double>(ba::call(player,"get_time"));
    const bool playing=ba_catalog::unbox<bool>(ba::call(player,"get_isPlaying"));
    const bool prepared=ba_catalog::unbox<bool>(ba::call(player,"get_isPrepared"));
    const int playerId=ba_catalog::unbox<int>(ba::call(player,"GetInstanceID"));
    const int clipId=clip.get()?ba_catalog::unbox<int>(ba::call(clip.get(),"GetInstanceID")):0;
    const std::string row="{\"phase\":"+ba_catalog::quote(phase)+",\"index\":"+std::to_string(videoIndex)+
        ",\"item\":"+std::to_string(videoItems[videoIndex])+",\"tick\":"+std::to_string(GetTickCount64())+
        ",\"player_id\":"+std::to_string(playerId)+",\"clip_id\":"+std::to_string(clipId)+
        ",\"clip_name\":"+ba_catalog::quote(name)+",\"original_path\":"+ba_catalog::quote(path)+
        ",\"model_clip_present\":"+videoBool(modelClip.get()!=nullptr)+",\"player_clip_present\":"+videoBool(clip.get()!=nullptr)+
        ",\"clip_binding_matches\":"+videoBool(clip.get()==modelClip.get())+
        ",\"frame\":"+std::to_string(frame)+",\"seconds\":"+std::to_string(seconds)+
        ",\"playing\":"+videoBool(playing)+",\"prepared\":"+videoBool(prepared)+
        ",\"target_present\":"+videoBool(target.get()!=nullptr)+",\"vm_active\":"+videoBool(ba_practice_settings_ui::active(vm))+
        ",\"vm_initialized\":"+videoBool(ba::get<bool>(vm,"_isInitialized"))+
        ",\"pending_play\":"+videoBool(ba::get<bool>(vm,"_pendingPlayRequested"))+
        ",\"disabled_clip_present\":"+videoBool(ba::get<Obj>(vm,"_clipPlayingOnDisable")!=nullptr)+"}";
    if(!videoRows.empty())videoRows+=',';videoRows+=row;
    // A separate immutable file for each sample preserves evidence on failure.
    writeCosmeticProof((L"video-sample-"+std::to_wstring(videoSamples++)).c_str(),row+"\n");
    if(std::string(phase)=="progress" && playing && prepared && clip.get()==modelClip.get()) {
        require(clip.get()!=nullptr,"video player has no bound clip");
        const std::string expected=videoItems[videoIndex]==11?"Fatality_Default":"Fatality_Warpout";
        require(name==expected,"video player is bound to the wrong fatality clip");
        if(videoFirstFrame<0 && frame>=0){videoFirstFrame=frame;videoFirstTime=seconds;}
        else if(frame>videoFirstFrame && seconds>videoFirstTime)videoAdvanced=true;
    }
    return row;
}
static void videoPreviewSmoke() {
    if(!ba::flag(L"-cosmetics-video-smoke") || videoStage>=10)return;
    namespace ui=ba_practice_settings_ui;
    // Failure cleanup has its own branch: do not re-enter the failed operation.
    if(videoStage==9) {
        try {if(editBack && editBackComplete()){videoStage=11;ba::log("VIDEO PREVIEW failure returned to menu: originalBack=1");}}
        catch(const std::exception& e){videoStage=11;ba::log("VIDEO PREVIEW cleanup failed: %s",e.what());}
        return;
    }
    try {
        require(ba::flag(L"-native-quit-smoke") && ba::flag(L"-native-quit-gate-smoke") &&
            ba::argument(L"-native-quit-mode=")=="confirm" && profileKey.rfind("nativestest_video_",0)==0 &&
            ba_native_settings::session && ba_native_settings::session->profile()==profileKey &&
            !ba::flag(L"-cosmetics-equip-smoke") && !ba::flag(L"-cosmetics-picker-smoke") &&
            !ba::flag(L"-cosmetics-preview-smoke") && !ba::flag(L"-profile-edits-smoke") && !ba::flag(L"-practice-ai-smoke"),
            "video previews require isolated explicitly gated diagnostic profile");
        const auto now=GetTickCount64();
        if(!videoDeadline){videoDeadline=now+120000;videoDue=now+2500;return;}
        require(now<videoDeadline,"video preview deadline");if(now<videoDue)return;
        require(persistenceReady && stateStore && unlockActive() && ba_dedicated_session::inMenu() &&
            ba_client::nativeIdle(ownedFront->get()),"video preview requires writable idle owned menu");
        if(videoStage==0) {
            Root menu(ba::get<Obj>(ba::owner,"<UIMenuController>k__BackingField")),main(ba::get<Obj>(menu.get(),"_mainMenu"));
            if(!main.get() || !ba::get<bool>(main.get(),"_isInitialized") || !ui::active(main.get()))return;
            Root transform(ui::findChild(main.get(),"LeftMenus/LeftButtons/CosmeticsButton"));
            Root button(ui::component(transform.get(),"Doozy.Runtime.UIManager.Components","UIButton"));ui::checkButton(button.get(),"CosmeticScreen");
            if(!ui::selectable(button.get()))return;
            guardVideoBodies();videoBefore=normalize(rawSnapshot().first);equipExpected=videoBefore;
            ba::native<void(*)(Obj,Obj)>(0x89fe30)(button.get(),nullptr);
            videoStage=1;videoDue=now+600;ba::log("VIDEO PREVIEW opened: originalButton=1 noEquip=1");return;
        }
        require(normalize(rawSnapshot().first)==videoBefore && accepted==videoBefore && committed==videoBefore,
            "video preview changed equipped loadout");
        if(videoStage==1) {
            // Only enter the fatality category once, then switch directly
            // between its items. This retains the video-to-video transition.
            if(videoIndex==0)targetSlot(4);else reacquirePicker();
            selectItem(videoItems[videoIndex],false);videoFirstFrame=-1;videoFirstTime=-1;videoAdvanced=false;
            videoStage=2;videoDue=now+300;ba::log("VIDEO PREVIEW selected: index=%u item=%u",videoIndex,videoItems[videoIndex]);return;
        }
        if(videoStage==2) {
            reacquirePicker();Root preview(ba::get<Obj>(picker->get(),"_selectedCosmeticItemPreviewVM"));
            require(ba::get<uint32_t>(preview.get(),"_selectedCosmeticItem")==videoItems[videoIndex] &&
                ba::get<bool>(preview.get(),"_hasVideo"),"fatality selection has no original video preview");
            Root vm(ba::get<Obj>(preview.get(),"_videoPreviewVM"));
            require(ui::exact(vm.get(),"Uncapped","CosmeticVideoPreviewVM") && ui::active(vm.get()) &&
                ba::get<bool>(vm.get(),"_isInitialized"),"video VM inactive/uninitialized");
            videoVM=std::make_unique<Root>(vm.get());videoPlayer=std::make_unique<Root>(ba::get<Obj>(vm.get(),"_videoPlayer"));
            require(videoPlayer->get()!=nullptr,"video player missing");
            if(!ba::get<Obj>(vm.get(),"_videoClip") || ba_native_quit::staticInt("LoadingCount"))return;
            videoObservation("loaded");
            ba::call(preview.get(),"PlayPreview");
            videoObservation("play-return");videoStage=3;videoDue=now+250;return;
        }
        if(videoStage==3) {
            videoObservation("progress");videoDue=now+250;
            if(!videoAdvanced)return;
            ba::log("VIDEO PREVIEW advanced: index=%u item=%u frameAndTime=1",videoIndex,videoItems[videoIndex]);
            if(videoIndex<2){++videoIndex;videoStage=1;return;}
            // Leave directly from a playing video; the original UI release
            // must perform cleanup. Never call Cleanup or Stop in this driver.
            editBackBegin();videoStage=4;videoDue=now+750;return;
        }
        if(videoStage==4) {
            if(!editBackComplete())return;
            const auto returned=videoObservation("back");
            writeCosmeticProof(L"video-preview-return",returned+"\n");
            Obj vm=videoVM->get(),player=videoPlayer->get();
            require(!ui::active(vm) && !ba::get<bool>(vm,"_isInitialized") && !ba::get<Obj>(vm,"_videoClip") &&
                !ba::get<Obj>(vm,"_clipPlayingOnDisable") && !ba::get<bool>(vm,"_pendingPlayRequested") &&
                !ba::call(player,"get_clip") && !ba_catalog::unbox<bool>(ba::call(player,"get_isPlaying")),
                "original Back did not release video playback/clip ownership");
            writeCosmeticProof(L"video-preview-cases","{\"schema\":1,\"visual_audio_verified\":false,\"physical_input_tested\":false,\"loadout_unchanged\":true,\"observations\":["+videoRows+"]}\n");
            videoVM.reset();videoPlayer.reset();videoStage=10;
            ba::log("VIDEO PREVIEW completed: clips=2 selections=3 frameAndTime=1 originalBack=1 clipCleared=1 stopped=1 loadoutUnchanged=1");return;
        }
    } catch(const std::exception& e) {
        videoStage=11;ba::log("VIDEO PREVIEW failed: index=%u reason=%s",videoIndex,e.what());
        try {if(picker){if(!editBack){equipExpected=videoBefore;editBackBegin();}videoStage=9;}}
        catch(const std::exception& cleanup){ba::log("VIDEO PREVIEW cleanup unavailable: %s",cleanup.what());}
    }
}
}
