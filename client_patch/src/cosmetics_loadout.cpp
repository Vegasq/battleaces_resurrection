#pragma once
namespace ba_cosmetics {
static std::vector<uint32_t> orderedItems(const FrozenLoadout& frozen) {
    std::vector<uint32_t> result;
    for(const auto& pair:frozen.slots)if(pair.second)result.push_back(pair.second);
    return result;
}
static void captureHumanProfile(const std::string& match,bool result) {
    require(ba::flag(L"-human-cosmetics-smoke") && unlockActive(),"human capture requires explicit owned diagnostic");
    const auto path=ba_export::moduleDirectory()+L"investigation\\runtime\\human-cosmetics-"+std::to_wstring(GetCurrentProcessId())+L"-"+
        std::wstring(match.begin(),match.end())+(result?L"-result.png":L"-in-game.png");
    require(GetFileAttributesW(path.c_str())==INVALID_FILE_ATTRIBUTES && GetLastError()==ERROR_FILE_NOT_FOUND,"human capture output unavailable");
    // CaptureScreenshot defers its read until a later frame with a portrait RT
    // active. Read the backbuffer synchronously and restore render state before
    // encoding/writing the private diagnostic image instead.
    Obj textureClass=ba::find_class("UnityEngine","RenderTexture");Root target(ba::invoke(textureClass,nullptr,"get_active",0));
    auto restore=[&](){void* values[]={target.get()};ba::invoke(textureClass,nullptr,"set_active",1,values);};
    std::unique_ptr<Root> texture;
    void* clear[]={nullptr};ba::invoke(textureClass,nullptr,"set_active",1,clear);
    try {
        texture=std::make_unique<Root>(ba::invoke(ba::find_class("UnityEngine","ScreenCapture"),nullptr,"CaptureScreenshotAsTexture",0));
    }catch(...) {restore();throw;}
    restore();Root restored(ba::invoke(textureClass,nullptr,"get_active",0));require(restored.get()==target.get(),"human capture render state not restored");
    require(texture && texture->get(),"human synchronous screenshot missing");
    auto destroy=[&](){void* args[]={texture->get()};ba::invoke(ba::find_class("UnityEngine","Object"),nullptr,"Destroy",1,args);};
    try {
        void* args[]={texture->get()};Root png(ba::invoke(ba::find_class("UnityEngine","ImageConversion"),nullptr,"EncodeToPNG",1,args));
        const auto bytes=ba_catalog::length(png.get());require(bytes>8 && bytes<16*1024*1024,"human screenshot byte bound");
        ba_export::atomicWrite(path,static_cast<const unsigned char*>(png.get())+0x20,bytes);
    }catch(...) {destroy();throw;}
    destroy();ba::log("HUMAN COSMETICS capture saved: phase=%s synchronous=1 renderStateRestored=1",result?"result":"in-game");
}
static void validateHumanDeck(Obj deck,const FrozenLoadout& frozen) {
    if(!frozen.active)return;
    Root entries(ba::get<Obj>(deck,"entitlements_"));
    require(entries.get() && ba_local::count(entries.get())==1,"human cosmetic entitlement count mismatch");
    Root entitlement(ba_bootstrap::item(entries.get(),0));
    require(ba::get<uint32_t>(entitlement.get(),"inventoryServiceId_")==0,"human cosmetic service mismatch");
    Root keys(ba::get<Obj>(entitlement.get(),"cosmeticAssetKeys_"));const auto wanted=orderedItems(frozen);
    require(ba_local::count(keys.get())==static_cast<int>(wanted.size()),"human cosmetic item count mismatch");
    for(size_t i=0;i<wanted.size();++i)
        require(ba_lan_bootstrap::uintAt(keys.get(),static_cast<int>(i))==wanted[i],"human cosmetic native order mismatch");
}
static FrozenLoadout freezeHuman(Obj front,Obj freshDeck) {
    FrozenLoadout result;
    // Ordinary launch and a failed experimental setup retain existing gameplay.
    if(!unlockEnabled() || unlockFailed)return result;
    require(ownsFront(front) && persistenceReady,"human cosmetic freeze owner unavailable");
    require(ba_dedicated_session::inMenu() && ba_dedicated_session::worldIdle(ba::read<Obj>(front,0xd8)),"human cosmetic freeze requires idle menu");
    Root deck(freshDeck),entries(ba::get<Obj>(deck.get(),"entitlements_"));
    require(entries.get() && ba_local::count(entries.get())==0,"human cosmetic destination is not fresh");
    result.slots=normalize(rawSnapshot().first);result.catalog=catalogHash;
    require(ba_cosmetics_state::digest(result.catalog),"human cosmetic catalog digest missing");
    Root config(ba::get<Obj>(ba::owner,"_clientGlobalConfig"));
    require(config.get()!=nullptr,"human cosmetic role config missing");
    auto role=[&](const char* field) {
        const auto slot=ba::get<uint32_t>(config.get(),field);
        const auto found=std::find_if(result.slots.begin(),result.slots.end(),[&](const auto& pair){return pair.first==slot;});
        require(found!=result.slots.end() && found->second,"human cosmetic role missing");return found->second;
    };
    result.portrait=role("PortraitCosmeticSlot");result.banner=role("BannerCosmeticSlot");
    Root entitlement(ba::make("CommonPb","Entitlement"));ba::set<uint32_t>(entitlement.get(),"inventoryServiceId_",0);
    Root keys(ba::get<Obj>(entitlement.get(),"cosmeticAssetKeys_"));
    for(uint32_t item:orderedItems(result))ba_dedicated_deck::addUint(keys.get(),item);
    ba_local::addItem(entries.get(),entitlement.get());result.active=true;validateHumanDeck(deck.get(),result);
    ba::log("Human cosmetic intent frozen: slots=%zu items=%zu portrait=%u banner=%u catalog=%s synchronous=1",
        result.slots.size(),orderedItems(result).size(),result.portrait,result.banner,result.catalog.c_str());
    return result;
}
static void applyHumanRoles(Obj message,const FrozenLoadout& frozen) {
    if(!frozen.active)return;
    validateHumanDeck(ba::get<Obj>(message,"deck_"),frozen);
    ba::set<uint32_t>(message,"portraitId_",frozen.portrait);ba::set<uint32_t>(message,"bannerId_",frozen.banner);
    if(ba::flag(L"-human-cosmetics-smoke"))
        ba::log("HUMAN COSMETICS frozen message: %s",ba_catalog::utf8(ba::call(message,"ToString")).c_str());
}
static void practiceHumanProof(Obj server,const FrozenLoadout& frozen) {
    require(frozen.active && ownsFront(ownedFront->get()),"human cosmetic proof requires active scoped loadout");
    Root sim(ba::read<Obj>(server,0x140)),player(ba::get<Obj>(sim.get(),"_localPlayer"));
    require(player.get() && ba::get<uint32_t>(player.get(),"ArmyID")==0,"human cosmetic proof local army mismatch");
    require(ba::get<uint32_t>(player.get(),"Portrait")==frozen.portrait && ba::get<uint32_t>(player.get(),"Banner")==frozen.banner,"human SimPlayer cosmetic roles mismatch");
    Root deck(ba::get<Obj>(player.get(),"Deck")),keys(ba::get<Obj>(deck.get(),"CosmeticItemKeys"));const auto wanted=orderedItems(frozen);
    require(keys.get() && ba_catalog::length(keys.get())==wanted.size(),"human SimDeck cosmetic count mismatch");
    for(size_t i=0;i<wanted.size();++i)require(ba::read<uint32_t>(keys.get(),0x20+i*4)==wanted[i],"human SimDeck cosmetic order mismatch");
    Root cosmetics(ba::get<Obj>(player.get(),"Cosmetics"));const auto flat=saved(cosmetics.get());Pairs decoded;
    for(size_t i=0;i<flat.size();i+=2)decoded.emplace_back(flat[i],flat[i+1]);
    require(normalize(decoded)==frozen.slots,"human SimPlayer complete cosmetic map mismatch");
    ba::log("HUMAN COSMETICS SimPlayer passed: portrait=%u banner=%u army=0 frozenSlots=17 orderedDeck=1 completeMap=1",frozen.portrait,frozen.banner);
}
static void practiceRematchSmoke(Obj front) {
    require(ba::flag(L"-human-cosmetics-smoke") && ownsFront(front) && persistenceReady && profileKey.rfind("cosmeticstest_",0)==0,
        "human cosmetic rematch diagnostic requires owned test profile");
    const auto before=normalize(rawSnapshot().first);auto expected=before;
    Root config(ba::get<Obj>(ba::owner,"_clientGlobalConfig"));const auto portraitSlot=ba::get<uint32_t>(config.get(),"PortraitCosmeticSlot");
    for(auto& pair:expected)if(pair.first==portraitSlot) {
        Root slot(slots.at(pair.first));
        for(uint32_t item:itemIds) {
            if(std::any_of(expected.begin(),expected.end(),[&](auto selected){return selected.second==item;}))continue;
            Root candidate(ba_public_bots::cosmetics.at(item)),definition(ba::call(candidate.get(),"get_Definition"));void* args[]={definition.get()};
            if(ba_tables::boolean(ba::call(slot.get(),"FilterItem",1,args))) {pair.second=item;break;}
        }
    }
    require(expected!=before,"human rematch needs alternate installed portrait");
    for(const auto& pair:expected)if(std::find(before.begin(),before.end(),pair)==before.end()) {
        auto slot=pair.first,item=pair.second;void* args[]={&slot,&item};ba::call(ownedCosmetics->get(),"EquipCosmeticAsset",2,args);
    }
    require(normalize(rawSnapshot().first)==expected,"human rematch native equip readback mismatch");
    // Deliberately no observe(): the immediately following freeze must see this
    // same-frame equip instead of the last periodic persistence snapshot.
    ba::log("HUMAN COSMETICS rematch equipped: %s",ba_cosmetics_state::encode({profileKey,catalogHash,expected}).c_str());
}
}
