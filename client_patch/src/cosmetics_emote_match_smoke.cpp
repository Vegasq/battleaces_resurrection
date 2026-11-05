#pragma once
// Owned opt-in match diagnostic. Original selector and PerformEmote only;
// observe native cadence, frame lifetime and hide without changing them.
namespace ba_cosmetics {
static unsigned matchEmoteStage=0,matchEmoteIndex=0,matchEmoteSample=0;
static int matchEmoteFrame=-1;
static ULONGLONG matchEmoteDeadline=0;
static auto& matchEmoteAbilities=*new std::unique_ptr<Root>();
static auto& matchEmoteSystem=*new std::unique_ptr<Root>();
static auto& matchEmoteState=*new std::unique_ptr<Root>();
static auto& matchEmoteView=*new std::unique_ptr<Root>();
static auto& matchEmoteAsset=*new std::unique_ptr<Root>();
static auto& matchEmoteLoadout=*new Pairs();
static auto& matchEmoteRows=*new std::string();
static uint32_t matchEmoteArmy=0,matchEmoteItem=0;
static int matchEmoteStart=0,matchEmoteEnd=0,matchEmoteRate=0;
static void guardMatchEmoteBodies();
static bool matchEmoteBool(Obj value,const char* method) {return ba_catalog::unbox<bool>(ba::call(value,method));}
static std::string matchEmoteObservation(Obj sim,const char* phase) {
    namespace ui=ba_practice_settings_ui;
    Obj state=matchEmoteState->get(),vm=matchEmoteView->get();
    Root container(ba::get<Obj>(vm,"_uiContainer")),solo(ba::get<Obj>(vm,"_soloAnimation"));
    const bool initialized=ba::get<bool>(vm,"_isInitialized");uint32_t item=0,portrait=0;
    if(initialized) {
        Root model(ba::call(vm,"get_Model")),selected(ba::get<Obj>(model.get(),"<EmoteCosmetic>k__BackingField"));
        item=ba::get<uint32_t>(selected.get(),"_value");portrait=ba::get<uint32_t>(model.get(),"<PortraitCosmetic>k__BackingField");
    }
    const bool graph=matchEmoteBool(solo.get(),"get_IsInitialized");
    Obj asset=ba::get<Obj>(state,"<LastEmoteAsset>k__BackingField");
    const std::string row="{\"phase\":"+ba_catalog::quote(phase)+",\"index\":"+std::to_string(matchEmoteIndex)+
        ",\"item\":"+std::to_string(matchEmoteItem)+",\"army\":"+std::to_string(matchEmoteArmy)+
        ",\"frame\":"+std::to_string(ba::read<int>(sim,0xac))+",\"tick\":"+std::to_string(GetTickCount64())+
        ",\"start\":"+std::to_string(matchEmoteStart)+",\"end\":"+std::to_string(matchEmoteEnd)+",\"rate\":"+std::to_string(matchEmoteRate)+
        ",\"state_start\":"+std::to_string(ba::get<int>(state,"<LastEmoteStartFrame>k__BackingField"))+
        ",\"state_end\":"+std::to_string(ba::get<int>(state,"<LastEmoteEndFrame>k__BackingField"))+
        ",\"asset_present\":"+videoBool(asset!=nullptr)+",\"asset_matches\":"+videoBool(asset==matchEmoteAsset->get())+
        ",\"model_item\":"+std::to_string(item)+",\"portrait\":"+std::to_string(portrait)+
        ",\"view_id\":"+std::to_string(emoteObjectId(vm))+",\"vm_initialized\":"+videoBool(initialized)+
        ",\"visible\":"+videoBool(matchEmoteBool(container.get(),"get_isVisible"))+
        ",\"hidden\":"+videoBool(matchEmoteBool(container.get(),"get_isHidden"))+
        ",\"solo_active\":"+videoBool(ui::active(solo.get()))+",\"playing\":"+videoBool(ba::get<bool>(solo.get(),"_IsPlaying"))+
        ",\"graph_ready\":"+videoBool(graph)+",\"seconds\":"+std::to_string(graph?ba_catalog::unbox<float>(ba::call(solo.get(),"get_Time")):-1)+"}";
    if(!matchEmoteRows.empty())matchEmoteRows+=',';matchEmoteRows+=row;
    writeCosmeticProof((L"match-emote-sample-"+std::to_wstring(matchEmoteSample++)).c_str(),row+"\n");
    return row;
}
static void emoteMatchSmoke() {
    if(!ba::flag(L"-cosmetics-emote-match-smoke") || matchEmoteStage>=10)return;
    namespace ui=ba_practice_settings_ui;
    try {
        require(ba::offlinePractice() && ba::flag(L"-practice-ai-smoke") && ba::flag(L"-native-quit-after-practice") &&
            ba::flag(L"-native-quit-smoke") && profileKey.rfind("nativestest_emmatch_",0)==0 &&
            !ba::flag(L"-cosmetics-emote-smoke") && !ba::flag(L"-cosmetics-equip-smoke"),"isolated match-emote diagnostic required");
        if(!matchEmoteDeadline)matchEmoteDeadline=GetTickCount64()+150000;
        require(GetTickCount64()<matchEmoteDeadline,"match-emote diagnostic deadline");
        if(!ba_practice::active() || ba_practice::state.phase!=ba_practice::Phase::Running || !ba_dedicated::loadingInGame())return;
        Obj server=ba_practice::server(),sim=ba::read<Obj>(server,0x140),player=ba::read<Obj>(sim,0x90);
        if(!player || ba::read<int>(sim,0xac)<40)return;
        if(matchEmoteStage==0) {
            Root type(ui::reflectedType("Uncapped.UI","UICosmeticAbilities"));void* args[]={type.get()};
            Root all(ba::invoke(ba::find_class("UnityEngine","Resources"),nullptr,"FindObjectsOfTypeAll",1,args));Obj found=nullptr;
            for(size_t i=0;i<ui::arrayCount(all.get(),64);++i) {
                Obj value=ui::arrayItem(all.get(),i);
                if(ba::get<Obj>(value,"_gameServer")!=server || ba::get<Obj>(value,"_simulation")!=sim ||
                    !ba::get<bool>(value,"_isInitialized") || !ui::active(value))continue;
                require(!found,"duplicate owned cosmetic abilities");found=value;
            }
            if(!found)return;guardMatchEmoteBodies();
            matchEmoteLoadout=normalize(rawSnapshot().first);matchEmoteArmy=ba::read<uint32_t>(player,0x38);
            matchEmoteAbilities=std::make_unique<Root>(found);matchEmoteSystem=std::make_unique<Root>(ba::get<Obj>(found,"_emoteSystem"));
            require(ba::get<Obj>(matchEmoteSystem->get(),"_simulation")==sim && ba::get<Obj>(matchEmoteSystem->get(),"_gameServer")==server,
                "match emote system ownership differs");
            Root states(ba::get<Obj>(matchEmoteSystem->get(),"_armyEmoteStates"));require(matchEmoteArmy<ui::arrayCount(states.get(),16),"emote army bound");
            matchEmoteState=std::make_unique<Root>(ui::arrayItem(states.get(),matchEmoteArmy));require(matchEmoteState->get(),"emote army state missing");
            Root display(ba::get<Obj>(matchEmoteSystem->get(),"_emoteDisplay"));void* displayArgs[]={&matchEmoteArmy};
            matchEmoteView=std::make_unique<Root>(ba::call(display.get(),"GetEmoteDisplay",1,displayArgs));require(matchEmoteView->get(),"emote display missing");
            matchEmoteRate=ba_catalog::unbox<int>(ba::call(server,"GetUnscaledSimTickRate"));require(matchEmoteRate>0 && matchEmoteRate<=120,"emote tick rate bound");
            matchEmoteStage=1;ba::log("MATCH EMOTE armed: army=%u originalButtons=4 noDirectShowHide=1",matchEmoteArmy);
        }
        require(normalize(rawSnapshot().first)==matchEmoteLoadout && accepted==matchEmoteLoadout && committed==matchEmoteLoadout,
            "match emote changed loadout");
        if(matchEmoteStage==1) {
            if(!matchEmoteBool(player,"IsEmoteReady"))return;
            require(!ba::get<Obj>(matchEmoteState->get(),"<LastEmoteAsset>k__BackingField"),"previous emote still owned");
            if(!matchEmoteBool(matchEmoteAbilities->get(),"get_IsSelectorVisible"))ba::call(matchEmoteAbilities->get(),"TryToggleEmoteSpraySelector");
            matchEmoteStage=2;return;
        }
        if(matchEmoteStage==2) {
            Root selector(ba::get<Obj>(matchEmoteAbilities->get(),"_cosmeticsSelector"));
            if(!matchEmoteBool(selector.get(),"get_isVisible") || !matchEmoteBool(player,"IsEmoteReady"))return;
            Root buttons(ba::get<Obj>(matchEmoteAbilities->get(),"_performEmoteButtons"));require(ui::arrayCount(buttons.get(),4)==4,"four emote controls required");
            Root button(ui::arrayItem(buttons.get(),matchEmoteIndex)),control(ba::get<Obj>(button.get(),"_button"));
            require(ba::get<uint32_t>(button.get(),"<EmoteIndex>k__BackingField")==matchEmoteIndex &&
                ba::get<Obj>(button.get(),"_simulation")==sim && ba::get<Obj>(button.get(),"_gameServer")==server,"emote button binding differs");
            if(!ui::active(button.get()) || !ui::selectable(control.get()))return;
            void* args[]={&matchEmoteArmy,&matchEmoteIndex};Root item(ba::call(matchEmoteSystem->get(),"GetArmyEmote",2,args));
            matchEmoteItem=ba_catalog::unbox<uint32_t>(ba::call(item.get(),"get_ID"));
            require(matchEmoteItem==selectedAt(matchEmoteLoadout,9+matchEmoteIndex),"equipped emote slot differs");
            Root definition(ba::call(item.get(),"get_Definition"));Obj metadata=nullptr;void* assetArgs[]={&metadata};
            require(ba_catalog::unbox<bool>(ba::call(definition.get(),"TryGetEmoteAssetReference",1,assetArgs)) && metadata,"emote metadata missing");
            matchEmoteAsset=std::make_unique<Root>(metadata);require(ba::get<float>(metadata,"LifeTime")==3.0f,"emote lifetime changed");
            ba::call(button.get(),"PerformEmote");
            matchEmoteStart=ba::get<int>(matchEmoteState->get(),"<LastEmoteStartFrame>k__BackingField");
            matchEmoteEnd=ba::get<int>(matchEmoteState->get(),"<LastEmoteEndFrame>k__BackingField");
            matchEmoteObservation(sim,"dispatch-return");
            require(ba::get<Obj>(matchEmoteState->get(),"<LastEmoteAsset>k__BackingField")==metadata &&
                matchEmoteEnd-matchEmoteStart==3*matchEmoteRate,"original emote trigger did not establish lifetime");
            matchEmoteFrame=ba::read<int>(sim,0xac);matchEmoteStage=3;
            ba::log("MATCH EMOTE dispatched: index=%u item=%u start=%d end=%d rate=%d originalCallback=1",matchEmoteIndex,matchEmoteItem,matchEmoteStart,matchEmoteEnd,matchEmoteRate);return;
        }
        if(matchEmoteStage==3) {
            int frame=ba::read<int>(sim,0xac);if(frame==matchEmoteFrame)return;matchEmoteFrame=frame;
            require(frame<matchEmoteEnd+5*matchEmoteRate,"original emote did not finish hiding");
            matchEmoteObservation(sim,"frame");
            Root container(ba::get<Obj>(matchEmoteView->get(),"_uiContainer"));
            if(ba::get<Obj>(matchEmoteState->get(),"<LastEmoteAsset>k__BackingField") || !matchEmoteBool(container.get(),"get_isHidden"))return;
            matchEmoteObservation(sim,"expired");
            ba::log("MATCH EMOTE expired: index=%u item=%u frame=%d end=%d originalHide=1",matchEmoteIndex,matchEmoteItem,frame,matchEmoteEnd);
            if(++matchEmoteIndex<4){matchEmoteStage=1;return;}
            writeCosmeticProof(L"match-emote-cases","{\"schema\":1,\"loadout_unchanged\":true,\"physical_input_tested\":false,\"visual_audio_verified\":false,\"observations\":["+matchEmoteRows+"]}\n");
            matchEmoteAsset.reset();matchEmoteView.reset();matchEmoteState.reset();matchEmoteSystem.reset();matchEmoteAbilities.reset();
            matchEmoteStage=10;ba::log("MATCH EMOTE completed: buttons=4 originalLifetime=1 loadoutUnchanged=1");
        }
    } catch(const std::exception& e) {matchEmoteStage=11;ba::log("MATCH EMOTE failed: index=%u reason=%s",matchEmoteIndex,e.what());}
}
}

namespace ba_cosmetics {
static void guardMatchEmoteBodies() {
    originalBackBody(0x37ada80,361,"12dca16a2994ab8fe6ff4ca8ae3cdbbcc0b644ac2b7f17a03ee90d338f905005");
    originalBackBody(0x3e54000,241,"c6138a377d0876dfc99d04099bd34454cbcdfcb36fe97f4d04fa2fa01a533975");
    originalBackBody(0x3e5c7e0,48,"9717d8280710f7f216802d90050e232b01e501380412a77022f8e4d55be11211");
    originalBackBody(0x3c23210,351,"ee341738bd2170bccde345d807ec133d3237ae5aebcb3e9e3dda3dcd6203bf14");
    originalBackBody(0x3c23370,138,"ef5b2acc55ffef8e1c669962b177c697be3d714882fb110f9240275ed75917ec");
    originalBackBody(0x3c220e0,1732,"29105fa651efeff2172df96b93fc6dc12b226e0777e8b3fc611bf4a303f95cbf");
    originalBackBody(0x3c227b0,104,"511478c2002f3a7443f092a607a0947f44484b9f4908198545c93433f65186f6");
    originalBackBody(0x3c22820,141,"42ac461fcc9b4adb8d418e5f4c1c8d95d830174ac33e923c19f29abce1ed80c4");
    originalBackBody(0x3c228b0,512,"d8a1f50c2eb406fad3457097497680f8a267f21c9070bd1f49950502f24904d3");
    originalBackBody(0x3c7ff00,825,"565d603336f43219fe89c12f009716c114a0c7810d359a5037cb5bb7e2ed7dbb");
    originalBackBody(0x3c80240,472,"f212112b68bf51e22d170b906bb82db497b2882eac64b9dbbc89bc9bb96b18a1");
    originalBackBody(0x3c80450,145,"5a4b0575012f56e039637f1c3fd8a3cb99863a2c21c5de4d59abc77fb9a65896");
    originalBackBody(0x3c806a0,336,"11fc76b0b3e2ff33d45ee1b7b6ef6545a6df5152bb7b3013c6eeb94b18b94f68");
    originalBackBody(0x3c807f0,159,"2a3efffb7d55956682242e9fe4437bebc1a25524833a2b3d3c71e0ccb411d5ba");
    originalBackBody(0x3c81160,470,"dc0212cc9b35460a2da4d9b2e1f5e4d1af9844d68d1c2f4557f661a6ecc54839");
    originalBackBody(0x3c81500,522,"ce296661f9eb760d87aa6880dff897fad5ee3519ad0fc54f54984bb2ab03f9ae");
    originalBackBody(0x3c81750,31,"61729843996da81ce6b88cdc4952a86712b6e43b2533683a40f88bf231e69386");
    originalBackBody(0x3c22ab0,360,"c9a40148499a9f0f03f483e102fe8981ce0114569e268008a5052448b899f245");
    originalBackBody(0x3c22c20,251,"04649202ba59ff736f22ee05aab5bc9814566057d7778204a3d4e57c546ec222");
    originalBackBody(0x3c22d20,682,"4cef46077a0d094d3e92373c67339e6da6a4f91833776681b4c12fa3d5e04db4");
    originalBackBody(0x3c80e40,167,"91f3405e080d9597628ef7950d5b114adc6deb6a21eb7d14d65cf568246e8fff");
    originalBackBody(0x3c80ef0,477,"d6d8825fc5b333d01513ebc796ae25b796e0f503d3653b748af207729c312359");
    originalBackBody(0x3c810d0,140,"8b4aef6000a9812b091db0ea67fb6f567bf275c82c2bcd8df6d21b9ef61f17d8");
}
}
