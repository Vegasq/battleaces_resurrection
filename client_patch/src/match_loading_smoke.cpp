#pragma once
// Explicit native callback qualification only; absent from normal launchers.
namespace ba_match_loading_smoke {
static unsigned stage=0;
static ULONGLONG since=0;
static ba_match_loading::Ticket original=0;
static void require(bool value,const char* text) {if(!value)throw std::runtime_error(text);}
static void play(ba::Obj front) {ba::native<void(*)(ba::Obj,ba::Obj,int,ba::Obj)>(0x3e3c0d0)(front,ba::owner,1,nullptr);}
static void update(void* front) {
    if(!ba::flag(L"-match-loading-normal-smoke") || stage>=4 || !ba::dedicated() || ba::community())return;
    try {
        if(!ba_dedicated_session::lobbyInstalled || !ba_dedicated_session::inMenu())return;
        const auto now=GetTickCount64();
        if(!stage) {
            play(front);require(ba_dedicated::loadingIntent,"native Play did not start loading intent");
            original=ba_dedicated::loadingTicket;
            if(ba::argument(L"-match-loading-role=","host")=="guest") {
                ba::log("MATCH LOADING NORMAL SMOKE guest native Play submitted");stage=4;return;
            }
            play(front);require(ba_dedicated::loadingTicket==original,"duplicate Play replaced pending ticket");
            ba::log("MATCH LOADING NORMAL SMOKE host native Play and duplicate submitted; ticket=%llu",original);
            stage=1;since=now;
        } else if(stage==1 && ba_lan::lobbyReady && now-since>=1000) {
            ba::native<void(*)(ba::Obj,bool,ba::Obj)>(0x3e3e760)(front,true,nullptr);
            require(!ba_dedicated::loadingIntent && !ba_match_loading::model.visible,"native Cancel retained loading status");
            ba::log("MATCH LOADING NORMAL SMOKE native Cancel; waiting for in-flight readiness");stage=2;since=now;
        } else if(stage==2 && now-since>=2000) {
            require(!ba_dedicated::loadingIntent && !ba_match_loading::model.visible,"old readiness reopened cancelled status");
            require(ba_lan::bootstrap.empty(),"cancelled solo lobby started a match");
            play(front);require(ba_dedicated::loadingIntent && ba_dedicated::loadingTicket!=original,"retry did not get a new ticket");
            ba::log("MATCH LOADING NORMAL SMOKE retry submitted; stale readiness did not reopen status");stage=4;
        }
    }catch(const std::exception& e){stage=5;ba::log("MATCH LOADING NORMAL SMOKE failed: %s",e.what());}
}
}
