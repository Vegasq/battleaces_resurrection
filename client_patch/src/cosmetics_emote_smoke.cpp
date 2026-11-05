#pragma once
// Explicit owned diagnostic. Only original picker/PlayPreview/Back actions;
// no Equip, component property writes, direct Play/Stop or forced cleanup.
namespace ba_cosmetics {
static unsigned emoteStage=0,emoteIndex=0,emoteSample=0;
static ULONGLONG emoteDue=0,emoteDeadline=0;
static auto& emoteCases=*new std::vector<uint32_t>();
static auto& emoteBefore=*new Pairs();
static auto& emoteVM=*new std::unique_ptr<Root>();
static auto& emoteSolo=*new std::unique_ptr<Root>();
static auto& emoteRows=*new std::string();
static float emoteFirstTime=-1;
static bool emoteAdvanced=false;
static void guardEmoteBodies() {
    originalBackBody(0x3c22ab0,360,"c9a40148499a9f0f03f483e102fe8981ce0114569e268008a5052448b899f245");
    originalBackBody(0x3c22c20,251,"04649202ba59ff736f22ee05aab5bc9814566057d7778204a3d4e57c546ec222");
    originalBackBody(0x3c22d20,682,"4cef46077a0d094d3e92373c67339e6da6a4f91833776681b4c12fa3d5e04db4");
    originalBackBody(0x3c80e40,167,"91f3405e080d9597628ef7950d5b114adc6deb6a21eb7d14d65cf568246e8fff");
    originalBackBody(0x3c80ef0,477,"d6d8825fc5b333d01513ebc796ae25b796e0f503d3653b748af207729c312359");
    originalBackBody(0x3c810d0,140,"8b4aef6000a9812b091db0ea67fb6f567bf275c82c2bcd8df6d21b9ef61f17d8");
    originalBackBody(0x3c9fe90,103,"26cc03c694ce698c556f9943faa85956d9d48967cd42899c74abb3660549c07f");
    originalBackBody(0x3c9ff00,1586,"82f580edc457a388c238090a98f4c68fdfe7963a5fd3291578e19519dfa7409e");
    originalBackBody(0x3ca0eb0,507,"3ce498d59f45ba8dc2ba1e98e9edc1439e19e00335cdc68e6bff262484520830");
    originalBackBody(0x3ca1bc0,156,"33a0933f4590b881c5f4352514b0e34a3151cf751758de3a74ee44f00bfb8efb");
    originalBackBody(0x3ca1c60,296,"262026067b2b83be0ab252ed99d0e8ac1822b26109149760f5ed272b9be928de");
    originalBackBody(0x3ca1d90,108,"ce036221fb2b3dd2aa8d1aced87db1f5338038cbbb8da1f1fac4a3ece2bc2439");
    originalBackBody(0x3ca1e00,579,"0095ea3efed1334478f27c1560cef3e7e0b2eb95ed22278781d3bd57146ddabf");
    originalBackBody(0x3ca2050,579,"41901e11648dd40f02013a201574705a3ad47372543673fc2fe6c4218692b18a");
    originalBackBody(0x3ca22a0,456,"01d08116a6d044405bd773a48af89424aad8e4c18ab0c711c2db98b0fbd9c0eb");
    originalBackBody(0x3ca2470,776,"63580655d153d650e3486e613e938d9acc383dac08b6612c159dbf39a4ba0f23");
    originalBackBody(0x3ca2780,882,"a9a8d20f0ddd32144da2b11dc8ce764a16e4a9b9f24fb00fac4178f840a12175");
    originalBackBody(0x3ca2b00,1375,"971a6830c8572085b4eea6267d8b274e0f86906e95e2f0d5631c7020d0132278");
    originalBackBody(0x7170f0,197,"f3a73f82871c510af603e0428b52ffa0e62176bb7f4e1a70618e83a4b0ce9381");
    originalBackBody(0x7172a0,345,"6935a0b40178df9130ff8caf46ad04ff34c3c2bd1832537ad0c62060a8fcbf66");
    originalBackBody(0x717500,268,"8ec059fcd7297e3f0d0da0658ef00efba8c27c2c820324ca96416a25e2b21775");
    originalBackBody(0x717610,121,"d55795ed26cfb14480e1eb3267946bd073071a772348b158fee3174b906cb3ba");
    originalBackBody(0x717690,121,"d776923de1c2f05334e06edd4aa0e28bc832bd7b6ee40209b6b3ca101e0074ea");
    originalBackBody(0x717800,697,"86dbc489c3b8380c1c5e9fc380648d4049e02a8bb2343fbaaa77edbf28dbe4ff");
    originalBackBody(0x717b90,270,"41dcfd6d0816f9da2a45cc13cf558b1dba8134e4b701b8801018fbd231a08f73");
    originalBackBody(0x717ca0,154,"505a695a8b6341ccb005a6fdbb9d805a5807a05d56cc909ec25b80f1d474cab3");
    originalBackBody(0x3e0fec0,1462,"362f8530dd2bfea97461ea818dba0ed9b475e3d8a18749ee7f5d3610e4b41f9f");
    originalBackBody(0x3e10a30,346,"6569f452365b0f15075ddd033d3202ae37ae0a1febe556683d8f65906000d8de");
    originalBackBody(0x3ca30a0,411,"8d04d23658569628fdfc6333041939a053c99b22ee3611dba356dfe5f905d4a0");
    originalBackBody(0x3ca3240,445,"77f7b3d4b73a0dff89b625779a899c3a0b7d00b25c992ebe036dd3717b5df083");
    originalBackBody(0x3ca1960,148,"653b73a1c530dcd31654cb597c994407baa80692510577ae7fd30e3676c28431");
    originalBackBody(0x88de60,994,"59e7c232b0a84b368041b534572ab536464ceecfa3ccfc509bc704bd5f3fc22f");
    originalBackBody(0x88e270,478,"8542f1b70ca838cc225404ab88d981d978e5cd01dc4d3c128082b98370e98da3");
    originalBackBody(0x88e520,670,"efa81dc852c441fdb8442edfed0e08b17e6865c71a45a936f9930c530d9504c2");
    originalBackBody(0x88ea50,726,"02ce220b59cdfe08f36e484ba46d8b9f579ddcdfb74d776e901b6922dc5733ba");
}

static std::string emoteName(Obj value) {
    if(!value)return {};Root n(ba::call(value,"get_name"));return ba_catalog::utf8(n.get());
}
static int emoteObjectId(Obj value) {
    return value?ba_catalog::unbox<int>(ba::call(value,"GetInstanceID")):0;
}
static std::string emoteStrings(Obj array) {
    require(array && ba_catalog::length(array)<32,"emote effect array bounds");std::string s="[";
    for(size_t i=0;i<ba_catalog::length(array);++i){if(i)s+=',';s+=ba_catalog::quote(ba_catalog::utf8(ba_catalog::arrayAt(array,i)));}return s+"]";
}
static std::string emoteObservation(const char* phase) {
    namespace ui=ba_practice_settings_ui;
    Obj vm=emoteVM->get(),solo=emoteSolo->get();
    const bool initialized=ba::get<bool>(vm,"_isInitialized");
    Root clip(ba::get<Obj>(vm,"_animation")),actualClip(ba::get<Obj>(solo,"_Clip"));
    Root material(ba::get<Obj>(vm,"_material")),override(ba::get<Obj>(vm,"_materialOverride"));
    Root graphic(ui::component(override.get(),"UnityEngine.UI","Graphic"));require(graphic.get()!=nullptr,"emote graphic missing");
    Root actualMaterial(ba::call(graphic.get(),"get_material"));
    Root animator(ba::get<Obj>(vm,"_textAnimator")),dialog(ba::get<Obj>(vm,"_dialog"));
    Root effects(ba::get<Obj>(animator.get(),"defaultBehaviorsTags"));
    Root localized(dialog.get()?ba::get<Obj>(dialog.get(),"m_CurrentStringChangedValue"):nullptr);
    Root text(ba::get<Obj>(animator.get(),"_text"));
    int64_t key=0;if(dialog.get()){Root boxed(ba::call(dialog.get(),"get_TableEntryReference"));key=ba::get<int64_t>(boxed.get(),"m_KeyId");}
    uint32_t modelItem=0,portrait=0;bool dialogMatches=false;
    if(initialized) {
        Root model(ba::call(vm,"get_Model"));Root selected(ba::get<Obj>(model.get(),"<EmoteCosmetic>k__BackingField"));
        modelItem=ba::get<uint32_t>(selected.get(),"_value");portrait=ba::get<uint32_t>(model.get(),"<PortraitCosmetic>k__BackingField");
        Root item(ba_public_bots::cosmetics.at(modelItem)),definition(ba::call(item.get(),"get_Definition"));
        Obj metadata=nullptr;void* args[]={&metadata};Root found(ba::call(definition.get(),"TryGetEmoteAssetReference",1,args)),reference(metadata);
        require(ba_catalog::unbox<bool>(found.get()) && reference.get(),"original emote metadata missing");
        dialogMatches=dialog.get()==ba::get<Obj>(reference.get(),"Text");
    }
    const bool graphReady=ba_catalog::unbox<bool>(ba::call(solo,"get_IsInitialized"));
    const float seconds=graphReady?ba_catalog::unbox<float>(ba::call(solo,"get_Time")):-1;
    const bool playing=ba::get<bool>(solo,"_IsPlaying");
    const int id=ba_catalog::unbox<int>(ba::call(solo,"GetInstanceID"));
    const std::string row="{\"phase\":"+ba_catalog::quote(phase)+",\"index\":"+std::to_string(emoteIndex)+
        ",\"item\":"+std::to_string(emoteCases[emoteIndex])+",\"tick\":"+std::to_string(GetTickCount64())+
        ",\"model_item\":"+std::to_string(modelItem)+",\"portrait\":"+std::to_string(portrait)+
        ",\"solo_id\":"+std::to_string(id)+",\"animation\":"+ba_catalog::quote(emoteName(clip.get()))+
        ",\"animation_id\":"+std::to_string(emoteObjectId(clip.get()))+
        ",\"actual_animation\":"+ba_catalog::quote(emoteName(actualClip.get()))+
        ",\"actual_animation_id\":"+std::to_string(emoteObjectId(actualClip.get()))+
        ",\"material\":"+ba_catalog::quote(emoteName(material.get()))+
        ",\"clip_binding_matches\":"+videoBool(clip.get() && actualClip.get()==clip.get())+
        ",\"material_binding_matches\":"+videoBool(material.get() && actualMaterial.get()==material.get())+
        ",\"dialog_matches_definition\":"+videoBool(dialogMatches)+",\"text_key\":"+std::to_string(key)+
        ",\"localized_text\":"+ba_catalog::quote(ba_catalog::utf8(localized.get()))+
        ",\"animator_text\":"+ba_catalog::quote(ba_catalog::utf8(text.get()))+
        ",\"effects\":"+emoteStrings(effects.get())+",\"typewriter\":"+videoBool(ba::get<bool>(vm,"_isTypeWriter"))+
        ",\"seconds\":"+std::to_string(seconds)+",\"playing\":"+videoBool(playing)+",\"graph_ready\":"+videoBool(graphReady)+
        ",\"vm_active\":"+videoBool(ui::active(vm))+",\"vm_initialized\":"+videoBool(initialized)+
        ",\"solo_active\":"+videoBool(ui::active(solo))+",\"pending_show\":"+videoBool(ba::get<bool>(vm,"_pendingShowRequested"))+"}";
    if(!emoteRows.empty())emoteRows+=',';emoteRows+=row;
    writeCosmeticProof((L"emote-sample-"+std::to_wstring(emoteSample++)).c_str(),row+"\n");
    if(std::string(phase)=="progress") {
        require(initialized && modelItem==emoteCases[emoteIndex] && portrait==selectedAt(emoteBefore,6) &&
            clip.get() && actualClip.get() && material.get() && actualMaterial.get() && dialogMatches,
            "emote model/component missing");
        // Retain mismatches for every selection; the external verifier rejects
        // them. Observing the complete sequence does not accept its bindings.
        if(graphReady && playing && seconds>=0){if(emoteFirstTime<0)emoteFirstTime=seconds;else if(seconds>emoteFirstTime)emoteAdvanced=true;}
    }
    return row;
}
static void emotePreviewSmoke() {
    if(!ba::flag(L"-cosmetics-emote-smoke") || emoteStage>=10)return;
    namespace ui=ba_practice_settings_ui;
    if(emoteStage==9) {
        try {if(editBack && editBackComplete()){emoteStage=11;ba::log("EMOTE PREVIEW failure returned to menu: originalBack=1");}}
        catch(const std::exception& e){emoteStage=11;ba::log("EMOTE PREVIEW cleanup failed: %s",e.what());}return;
    }
    try {
        require(ba::flag(L"-native-quit-smoke") && ba::flag(L"-native-quit-gate-smoke") && ba::argument(L"-native-quit-mode=")=="confirm" &&
            profileKey.rfind("nativestest_emote_",0)==0 && ba_native_settings::session && ba_native_settings::session->profile()==profileKey &&
            !ba::flag(L"-cosmetics-equip-smoke") && !ba::flag(L"-cosmetics-picker-smoke") && !ba::flag(L"-cosmetics-preview-smoke") &&
            !ba::flag(L"-cosmetics-video-smoke") && !ba::flag(L"-profile-edits-smoke") && !ba::flag(L"-practice-ai-smoke"),
            "emote previews require isolated explicitly gated diagnostic profile");
        const auto now=GetTickCount64();if(!emoteDeadline){emoteDeadline=now+180000;emoteDue=now+2500;return;}
        require(now<emoteDeadline,"emote preview deadline");if(now<emoteDue)return;
        require(persistenceReady && stateStore && unlockActive() && ba_dedicated_session::inMenu() && ba_client::nativeIdle(ownedFront->get()),
            "emote preview requires writable idle owned menu");
        if(emoteStage==0) {
            Root menu(ba::get<Obj>(ba::owner,"<UIMenuController>k__BackingField")),main(ba::get<Obj>(menu.get(),"_mainMenu"));
            if(!main.get() || !ba::get<bool>(main.get(),"_isInitialized") || !ui::active(main.get()))return;
            Root transform(ui::findChild(main.get(),"LeftMenus/LeftButtons/CosmeticsButton"));
            Root button(ui::component(transform.get(),"Doozy.Runtime.UIManager.Components","UIButton"));ui::checkButton(button.get(),"CosmeticScreen");
            if(!ui::selectable(button.get()))return;
            guardEmoteBodies();Root slot(slots.at(9));emoteCases=compatible(slot.get());std::sort(emoteCases.begin(),emoteCases.end());
            require(emoteCases.size()==46 && std::adjacent_find(emoteCases.begin(),emoteCases.end())==emoteCases.end(),"emote catalog shape differs");
            emoteCases.push_back(emoteCases.front());emoteBefore=normalize(rawSnapshot().first);equipExpected=emoteBefore;
            ba::native<void(*)(Obj,Obj)>(0x89fe30)(button.get(),nullptr);emoteStage=1;emoteDue=now+600;
            ba::log("EMOTE PREVIEW opened: originalButton=1 uniqueItems=46 noEquip=1");return;
        }
        require(normalize(rawSnapshot().first)==emoteBefore && accepted==emoteBefore && committed==emoteBefore,"emote preview changed loadout");
        if(emoteStage==1) {
            if(!emoteIndex)targetSlot(9);else reacquirePicker();selectItem(emoteCases[emoteIndex],false);
            emoteFirstTime=-1;emoteAdvanced=false;emoteStage=2;emoteDue=now+350;
            ba::log("EMOTE PREVIEW selected: index=%u item=%u",emoteIndex,emoteCases[emoteIndex]);return;
        }
        if(emoteStage==2) {
            reacquirePicker();Root preview(ba::get<Obj>(picker->get(),"_selectedCosmeticItemPreviewVM"));
            require(ba::get<uint32_t>(preview.get(),"_selectedCosmeticItem")==emoteCases[emoteIndex] && ba::get<bool>(preview.get(),"_hasEmote"),"selected emote preview missing");
            Root vm(ba::get<Obj>(preview.get(),"_selectedEmoteVM"));require(ui::exact(vm.get(),"Uncapped.UI","EmoteDisplayVM") &&
                ui::active(vm.get()) && ba::get<bool>(vm.get(),"_isInitialized"),"emote VM inactive/uninitialized");
            emoteVM=std::make_unique<Root>(vm.get());emoteSolo=std::make_unique<Root>(ba::get<Obj>(vm.get(),"_soloAnimation"));
            if(!ba::get<Obj>(vm.get(),"_animation") || !ba::get<Obj>(vm.get(),"_material") || ba_native_quit::staticInt("LoadingCount"))return;
            emoteObservation("loaded");ba::call(preview.get(),"PlayPreview");emoteObservation("play-return");
            emoteStage=3;emoteDue=now+250;return;
        }
        if(emoteStage==3) {
            emoteObservation("progress");emoteDue=now+250;if(!emoteAdvanced)return;
            ba::log("EMOTE PREVIEW advanced: index=%u item=%u playableTime=1",emoteIndex,emoteCases[emoteIndex]);
            if(emoteIndex+1<emoteCases.size()){++emoteIndex;emoteStage=1;return;}
            editBackBegin();emoteStage=4;emoteDue=now+750;return;
        }
        if(emoteStage==4) {
            if(!editBackComplete())return;const auto returned=emoteObservation("back");writeCosmeticProof(L"emote-preview-return",returned+"\n");
            require(!ui::active(emoteVM->get()) && !ba::get<bool>(emoteVM->get(),"_isInitialized") &&
                !ui::active(emoteSolo->get()) && !ba::get<bool>(emoteSolo->get(),"_IsPlaying"),"Back did not stop/release emote preview");
            writeCosmeticProof(L"emote-preview-cases","{\"schema\":1,\"visual_audio_verified\":false,\"physical_input_tested\":false,\"loadout_unchanged\":true,\"observations\":["+emoteRows+"]}\n");
            emoteVM.reset();emoteSolo.reset();emoteStage=10;
            ba::log("EMOTE PREVIEW completed: items=46 selections=47 playableTime=1 originalBack=1 stopped=1 loadoutUnchanged=1");return;
        }
    } catch(const std::exception& e) {
        emoteStage=11;ba::log("EMOTE PREVIEW failed: index=%u reason=%s",emoteIndex,e.what());
        try {if(picker){if(!editBack){equipExpected=emoteBefore;editBackBegin();}emoteStage=9;}}
        catch(const std::exception& cleanup){ba::log("EMOTE PREVIEW cleanup unavailable: %s",cleanup.what());}
    }
}
}
