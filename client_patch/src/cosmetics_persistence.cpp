#pragma once
#include "cosmetics_store.hpp"
namespace ba_cosmetics {
using Pairs=ba_cosmetics_state::Pairs;
struct ListToken {
    Obj list=nullptr,array=nullptr;int count=0,version=0;
    bool operator==(const ListToken& other)const{return list==other.list && array==other.array && count==other.count && version==other.version;}
};
static bool persistenceReady=false,projectionPending=false,persistenceReadError=false,persistenceRestored=false;
static unsigned persistenceWrites=0;
static ULONGLONG lastSaveAttempt=0,lastProjectionAttempt=0,lastSnapshotError=0;
static auto& profileKey=*new std::string();
static auto& catalogHash=*new std::string();
static auto& accepted=*new Pairs();
static auto& committed=*new Pairs();
static auto& stateStore=*new std::unique_ptr<ba_cosmetics_state::Store>();
static ListToken observedToken;
static ListToken listToken() {
    require(unlockActive(),"cosmetic snapshot owner unavailable");
    Obj list=ba::read<Obj>(ownedCosmetics->get(),0x10);require(list!=nullptr,"cosmetic snapshot list missing");
    return {list,ba::read<Obj>(list,0x10),ba::read<int>(list,0x18),ba::read<int>(list,0x1c)};
}
static std::pair<Pairs,ListToken> rawSnapshot() {
    const auto token=listToken();Root list(token.list),array(token.array);
    require(array.get()!=nullptr,"cosmetic snapshot array missing");const auto capacity=ba_catalog::length(array.get());
    require(token.count>=0 && token.count<=17 && array.get() && capacity>=static_cast<size_t>(token.count) && capacity<=64,"cosmetic snapshot bounds");
    Pairs values;values.reserve(token.count);
    for(int i=0;i<token.count;++i)values.emplace_back(ba::read<uint32_t>(array.get(),0x20+i*8),ba::read<uint32_t>(array.get(),0x24+i*8));
    require(token==listToken(),"cosmetic snapshot changed during copy");return {std::move(values),token};
}
static Pairs normalize(const Pairs& values,bool complete=false) {
    require(values.size()<=17 && (!complete || values.size()==17),"cosmetic snapshot incomplete");
    std::vector<uint32_t> provided,used;Root elements(ba::call(slots.get(),"get_Elements"));Pairs result;
    require(ba_catalog::length(elements.get())==17,"cosmetic slot count changed");
    for(const auto& pair:values) {
        require(pair.first && !contains(provided,pair.first) && slots.at(pair.first),"cosmetic snapshot unknown/duplicate slot");provided.push_back(pair.first);
    }
    for(size_t i=0;i<17;++i) {
        Root slot(ba_catalog::arrayAt(elements.get(),i));const uint32_t id=ba_catalog::unbox<uint32_t>(ba::call(slot.get(),"get_ID"));
        const uint32_t fallback=ba::get<uint32_t>(slot.get(),"DefaultItem");uint32_t selected=fallback;
        const auto found=std::find_if(values.begin(),values.end(),[&](const auto& pair){return pair.first==id;});
        if(found!=values.end())selected=found->second?found->second:(complete?0:fallback);
        require(!complete || found!=values.end(),"cosmetic snapshot missing slot");
        if(selected) {
            require(contains(itemIds,selected) && !contains(used,selected),"cosmetic snapshot unknown/duplicate item");
            Root item(ba_public_bots::cosmetics.at(selected)),definition(ba::call(item.get(),"get_Definition"));void* args[]={definition.get()};
            Root valid(ba::call(slot.get(),"FilterItem",1,args));require(ba_tables::boolean(valid.get()),"cosmetic snapshot wrong-slot item");used.push_back(selected);
        } else require(!fallback,"cosmetic snapshot empty nonempty slot");
        result.emplace_back(id,selected);
    }
    return result;
}
static void project() {
    Root config(ba::get<Obj>(ba::owner,"_clientGlobalConfig"));require(config.get()!=nullptr,"cosmetic projection config missing");
    // Both original ToProto overloads have argc2; pin the full object overload.
    Obj exact=nullptr;void* iterator=nullptr;
    while(Obj method=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(ba::find_class("Uncapped","CosmeticsUtils"),&iterator)) {
        if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(method),"ToProto") ||
            ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(method)!=2)continue;
        Obj type=ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(method,0);
        if(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(type)!=ba::klass(ownedCosmetics->get()))continue;
        require(!exact,"ambiguous full cosmetic projection overload");exact=method;
    }
    require(exact && ba::read<void*>(exact,0)==reinterpret_cast<void*>(ba::native<void(*)()>(0x3cc0940)),"full cosmetic projection overload changed");
    void* args[]={ownedCosmetics->get(),config.get()};Root loadout(ba_local::invokeMethod(exact,nullptr,args));
    Root profile(ba::get<Obj>(ownedAccount->get(),"<ProfileCache>k__BackingField"));
    require(loadout.get() && profile.get(),"cosmetic profile projection missing");
    ba::set<Obj>(profile.get(),"cosmeticLoadout_",loadout.get());projectionPending=false;
}
static void apply(const Pairs& selection) {
    const auto validated=normalize(selection,true);require(unlockActive(),"cosmetic restore owner changed");
    require(ba_dedicated_session::inMenu() && ba_dedicated_session::worldIdle(ba::read<Obj>(ownedFront->get(),0xd8)),"cosmetic restore requires idle native world");
    for(auto pair:validated)if(pair.second) {void* args[]={&pair.first,&pair.second};ba::call(ownedCosmetics->get(),"EquipCosmeticAsset",2,args);}
    require(normalize(rawSnapshot().first)==validated,"cosmetic native restore readback mismatch");
}
static void persistenceInitialize(const std::string& catalog) {
    profileKey=ba::argument(L"-local-profile=","default");require(ba_cosmetics_state::profileKey(profileKey),"invalid local cosmetic profile key");
    catalogHash=ba_export::hash(ba_export::Bytes(catalog.begin(),catalog.end()));
    const auto initial=normalize(rawSnapshot().first);bool restored=false;
    try {
        stateStore=std::make_unique<ba_cosmetics_state::Store>(ba_export::moduleDirectory(),profileKey);
        const auto bytes=stateStore->load();
        if(bytes) {
            const auto state=ba_cosmetics_state::decode(*bytes);
            require(state.profile==profileKey && state.catalog==catalogHash,"saved cosmetic profile/catalog mismatch");
            const auto selection=normalize(state.slots,true);
            try {apply(selection);}catch(...) {apply(initial);throw;}
            restored=true;
        }
    } catch(const std::exception& error) {
        persistenceReadError=true;stateStore.reset();ba::log("Cosmetic persistence unavailable: %s; current session remains usable; saved file retained",error.what());
    }
    const auto snapshot=rawSnapshot();accepted=normalize(snapshot.first);committed=accepted;observedToken=snapshot.second;
    project();persistenceReady=true;persistenceRestored=restored;saveDeferred=false;
    ba::log("BA_RESURRECTION_COSMETICS_PERSIST_V1 ready: profile=%s slots=%zu restored=%d writable=%d projection12=1",profileKey.c_str(),accepted.size(),restored?1:0,stateStore?1:0);
}
static void observe() {
    if(!persistenceReady || !unlockActive())return;
    const auto now=GetTickCount64();
    try {
        const auto token=listToken();
        if(!(token==observedToken)) {
            const auto raw=rawSnapshot();const auto selection=normalize(raw.first);observedToken=raw.second;
            if(selection!=accepted) {accepted=selection;projectionPending=true;}
        }
        if(projectionPending && now>=lastProjectionAttempt && now-lastProjectionAttempt>=500) {
            lastProjectionAttempt=now;try{project();}catch(const std::exception& error){lastProjectionAttempt=now+4500;ba::log("Cosmetic profile projection pending: %s",error.what());}
        }
        if(stateStore && accepted!=committed && now>=lastSaveAttempt && now-lastSaveAttempt>=500) {
            lastSaveAttempt=now;
            try {
                stateStore->save(ba_cosmetics_state::encode({profileKey,catalogHash,accepted}));committed=accepted;++persistenceWrites;
                ba::log("Cosmetic full loadout saved: profile=%s slots=%zu writes=%u atomic=1",profileKey.c_str(),accepted.size(),persistenceWrites);
            }catch(const std::exception& error){lastSaveAttempt=now+4500;ba::log("Cosmetic save pending: %s; in-memory selection retained",error.what());}
        }
        saveDeferred=false;
    }catch(const std::exception& error){if(now-lastSnapshotError>=5000){lastSnapshotError=now;ba::log("Cosmetic snapshot rejected: %s; prior saved selection retained",error.what());}}
}
}
