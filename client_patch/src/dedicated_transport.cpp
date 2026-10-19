#pragma once
namespace ba_dedicated_deck { static bool canReady(ba::Obj front);static ba::Obj selectedProto(ba::Obj front); }
// Thin game-facing adapter; configuration and native world authority live in server/.
namespace ba_dedicated {
using ba::Obj;using ba_local::Root;using ba_lan::Bytes;
static bool installing=false, initialized=false;
// A Play intent outlives intermediate S35 readiness masks. Only a local
// cancellation/deck submission, a terminal failure or actual play settles it.
static ba_match_loading::Ticket loadingTicket=0;
static bool loadingIntent=false;
static uint64_t loadingGeneration=0;
static bool loadingInGame() noexcept {
    // Native LoadingGameUI enters InGame only after its UI assets are ready.
    // This observer must never turn a presentation failure into a game failure.
    try {
        if(!ba::owner)return false;
        Obj fsm=ba::read<Obj>(ba::owner,0x2b0),inGame=ba::read<Obj>(ba::owner,0x2e8);
        return fsm && inGame && ba::get<Obj>(fsm,"_currentState")==inGame;
    } catch(...){return false;}
}
static void loadingCancel(const char* reason) {
    ba_match_loading::cancel(loadingTicket,reason);loadingTicket=0;loadingIntent=false;
}
static void loadingFailure() {
    ba_match_loading::error(loadingTicket,"Connection lost while starting the match.");loadingTicket=0;loadingIntent=false;
}
static void loadingUpdate() {
    if(!loadingIntent)return;
    if(ba_lan::stopped){loadingFailure();return;}
    if(ba_lan::running && ba_lan::worldReady && loadingInGame()) {
        ba::log("Match loading readiness: source=dedicated ticket=%llu nativeInGame=1 running=1 localReady=1 worldReady=1 match=%s",
            static_cast<unsigned long long>(loadingTicket),ba_lan::dedicatedMatchId.c_str());
        ba_match_loading::success(loadingTicket);loadingTicket=0;loadingIntent=false;return;
    }
    const auto stage=ba_lan::bootstrap.empty()?ba_match_loading::Stage::Waiting:
        !ba_lan::worldReady?ba_match_loading::Stage::Loading:
        !ba_lan::running?ba_match_loading::Stage::Waiting:ba_match_loading::Stage::Starting;
    ba_match_loading::advance(loadingTicket,stage);
}
static Obj deckFromIds(const Bytes& ids) {
    if(ids.size()!=32)throw std::runtime_error("dedicated deck needs8 slots");
    Root deck(ba::make("CommonPb","Deck"));Obj units=ba::get<Obj>(deck.get(),"units_");
    Obj add=nullptr;void* iterator=nullptr;
    while(Obj method=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(ba::klass(units),&iterator)) {
        if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(method),"Add") || ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(method)!=1)continue;
        Obj pt=ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(method,0);
        if(ba::api<int(*)(Obj)>("il2cpp_type_get_type")(pt)==9){add=method;break;}
    }
    if(!add)throw std::runtime_error("dedicated uint repeated Add missing");
    for(int i=0;i<8;++i){uint32_t value=ba_lan::u32(ids,4*i);void* args[]={&value};ba_local::invokeMethod(add,units,args);}
    Obj groups=ba::get<Obj>(deck.get(),"activeAbilityGroups_");
    for(int i=0;i<4;++i){uint32_t zero=0;void* args[]={&zero};ba_local::invokeMethod(add,groups,args);}
    return deck.get();
}
static bool submitDeck(Obj deck,bool initialReady=false) {
    if(ba_public::deckLocked())return false;
    if(!ba::dedicated() || installing || !initialized || !(ba::community()?ba_community::online:ba_lan::welcomed) || !ba_lan::bootstrap.empty())return false;
    Obj units=ba::get<Obj>(deck,"units_");int count=ba_local::count(units);
    if(count!=8){ba::log("Dedicated deck incomplete (%d slots); waiting for8",count);return false;}
    Bytes ids;for(int index=0;index<8;++index){void* args[]={&index};Root value(ba::call(units,"get_Item",1,args));uint32_t id=*ba::api<uint32_t*(*)(Obj)>("il2cpp_object_unbox")(value.get());ba_lan::append32(ids,id);}
    if(ba::community()) {
        ba_community_wire::Deck values{};for(size_t i=0;i<8;++i)values[i]=ba_lan::u32(ids,4*i);
        const auto selected=ba_cosmetics::wireLoadout(deck,ba_cosmetics::currentSelection());
        if(selected.deck!=values)throw std::runtime_error("loadout unit snapshot changed during copy");
        const auto id=ba_community::nextRequest();
        const auto request=ba_community::send(selected.full?ba_community_wire::setLoadout(id,selected):ba_community_wire::setDeck(id,values));
        ba_client::deckSubmitted(request,selected);
    } else {
        ba_lan::send(22,ids);
        if(!initialReady)loadingCancel("selected deck changed");
    }
    ba::log("Dedicated selected deck submitted for validation");
    return true;
}
static void ready(Obj front,int mode) {
    if(ba_dedicated_session::retryFromPlay(front,mode))return;
    if(ba::community()){ba::log("Community prototype: use Custom Game; ordinary queue/AI adapter remains pending (mode=%d)",mode);return;}
    if(!ba_lan::welcomed || !initialized)throw std::runtime_error("dedicated lobby not ready yet");
    if(!ba_lan::bootstrap.empty())return;
    if(loadingIntent){ba::log("Dedicated Play already pending; duplicate deck/READY submission ignored");return;}
    if(!ba_dedicated_deck::canReady(front))return;
    Root selected(ba_dedicated_deck::selectedProto(front));const bool submitted=submitDeck(selected.get(),true);
    ba_lan::send(23,Bytes{1});
    if(submitted && !loadingIntent) {
        loadingIntent=true;
        loadingTicket=ba_match_loading::begin(ba_match_loading::Source::Dedicated,
            "ready:"+std::to_string(++loadingGeneration),ba_match_loading::Stage::Waiting);
    }
    ba::log("Dedicated ready requested from native Play (mode=%d); waiting for other player",mode);
}
static void cancelReady(Obj) {
    if(ba::community())return;
    if(ba::dedicated() && ba_lan::welcomed && ba_lan::bootstrap.empty()) {
        ba_lan::send(23,Bytes{0});loadingCancel("native queue cancelled");
        ba::log("Dedicated lobby readiness cancelled from native UI");
    }
}
}
