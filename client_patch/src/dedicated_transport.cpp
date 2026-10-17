#pragma once
namespace ba_dedicated_deck { static bool canReady(ba::Obj front);static ba::Obj selectedProto(ba::Obj front); }
// Thin game-facing adapter; configuration and native world authority live in server/.
namespace ba_dedicated {
using ba::Obj;using ba_local::Root;using ba_lan::Bytes;
static bool installing=false, initialized=false;
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
static void submitDeck(Obj deck) {
    if(!ba::dedicated() || installing || !initialized || !ba_lan::welcomed || !ba_lan::bootstrap.empty())return;
    Obj units=ba::get<Obj>(deck,"units_");int count=ba_local::count(units);
    if(count!=8){ba::log("Dedicated deck incomplete (%d slots); waiting for8",count);return;}
    Bytes ids;for(int index=0;index<8;++index){void* args[]={&index};Root value(ba::call(units,"get_Item",1,args));uint32_t id=*ba::api<uint32_t*(*)(Obj)>("il2cpp_object_unbox")(value.get());ba_lan::append32(ids,id);}
    ba_lan::send(22,ids);ba::log("Dedicated selected deck submitted for validation");
}
static void ready(Obj front,int mode) {
    if(!ba_lan::welcomed || !initialized)throw std::runtime_error("dedicated lobby not ready yet");
    if(!ba_lan::bootstrap.empty())return;
    if(!ba_dedicated_deck::canReady(front))return;
    Root selected(ba_dedicated_deck::selectedProto(front));submitDeck(selected.get());
    ba_lan::send(23,Bytes{1});ba::log("Dedicated ready requested from native Play (mode=%d); waiting for other player",mode);
}
static void cancelReady(Obj) {
    if(ba::dedicated() && ba_lan::welcomed && ba_lan::bootstrap.empty()) {
        ba_lan::send(23,Bytes{0});ba::log("Dedicated lobby readiness cancelled from native UI");
    }
}
}
