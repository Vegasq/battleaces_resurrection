#pragma once
// The exact MatchResultVM.OnContinue caller retains its original navigation gate
// and signal router. Community/local public matches issue no progression rewards;
// send the original End signal instead of entering the retired reward pipeline.
// Shipped build37822: call3d61142 ->11f3a50; PostGameScreens2=rewards,7=End.
// See docs/public-results.txt for metadata, disassembly and native failure proof.
extern "C" __declspec(dllexport) void OfflineMatchResultContinue(ba::Obj router,int screen,ba::Obj methodInfo) {
    const bool remote=ba_public::active() && ba_dedicated_results::delivered && ba_lan::matchEnded;
    const bool local=ba_practice::active() && ba_practice::state.result && ba_practice::state.mode!=4;
    if(screen==2 && ba::owner && (remote || local))try {
        ba::Obj fsm=ba::read<ba::Obj>(ba::owner,0x2b0);
        ba::Obj controller=ba::get<ba::Obj>(ba::owner,"<UIPostGameController>k__BackingField");
        ba::Obj postFsm=controller?ba::get<ba::Obj>(controller,"_fsm"):nullptr;
        ba::Obj resultState=controller?ba::get<ba::Obj>(controller,"_matchResultState"):nullptr;
        ba::Obj data=ba::get<ba::Obj>(ba::owner,"<MatchDataManager>k__BackingField");
        ba::Obj info=data?ba::get<ba::Obj>(data,"_matchInfo"):nullptr;
        if(fsm && controller && postFsm && resultState && info &&
           ba::get<ba::Obj>(fsm,"_currentState")==ba::read<ba::Obj>(ba::owner,0x2f0) &&
           ba::get<ba::Obj>(postFsm,"_currentState")==resultState &&
           ba::get<ba::Obj>(controller,"_signalRouter")==router &&
           ba::get<bool>(info,"MatchCompleted") && !ba::get<bool>(info,"IsCustomGame")) {
            const int mode=ba::get<int>(info,"GameMode");
            if(mode==1 || mode==2 || mode==5) {
                screen=7;
                ba::log("Public result Continue routed: mode=%d source=%s next=End rewards=0 progressionUnchanged=1 publicModePreserved=1",
                    mode,remote?"remote":"local");
            }
        }
    } catch(const std::exception& error) {ba::log("Public result Continue routing failed: %s",error.what());}
    ba::native<void(*)(ba::Obj,int,ba::Obj)>(0x11f3a50)(router,screen,methodInfo);
}
