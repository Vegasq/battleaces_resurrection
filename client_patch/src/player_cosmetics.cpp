#pragma once
// Explicit read-only catalog export. Installed IDs/assets remain outside source.
namespace ba_cosmetics {
using ba::Obj;using ba_local::Root;using ba_tables::require;
static void unlockUpdate(Obj);
static auto& slots=*new ba_tables::Table("CosmeticSlot","CosmeticSlotTable","80afad8f743498b4881dccafa8ebb850");
static bool finished=false;
static std::vector<uint32_t> saved(Obj cosmetics) {
    Obj list=ba::get<Obj>(cosmetics,"_savedItems");require(list!=nullptr,"cosmetics saved list missing");
    const int count=ba::read<int>(list,0x18);Obj array=ba::read<Obj>(list,0x10);
    require(count>=0 && count<=17 && array && ba_catalog::length(array)>=static_cast<size_t>(count),"cosmetics saved list bounds");
    std::vector<uint32_t> result;
    for(int i=0;i<count*2;++i)result.push_back(ba::read<uint32_t>(array,0x20+i*4));
    return result;
}
static std::string numbers(const std::vector<uint32_t>& values) {
    std::string result="[";for(auto value:values){if(result.size()>1)result+=',';result+=std::to_string(value);}return result+"]";
}
static std::string serialize() {
    Root items(ba::call(ba_public_bots::cosmetics.get(),"get_Elements")),slotItems(ba::call(slots.get(),"get_Elements"));
    const size_t itemCount=ba_catalog::length(items.get()),slotCount=ba_catalog::length(slotItems.get());
    require(itemCount>0 && itemCount<=4096 && slotCount==17,"cosmetics catalog capacity unsupported");
    std::vector<uint32_t> ids,order,defaults;std::vector<std::unique_ptr<Root>> definitions;
    std::string itemRows,slotRows;
    for(size_t i=0;i<itemCount;++i) {
        Root item(ba_catalog::arrayAt(items.get(),i));require(item.get()!=nullptr,"cosmetics item missing");
        const uint32_t id=ba_catalog::unbox<uint32_t>(ba::call(item.get(),"get_ID"));
        require(id && std::find(ids.begin(),ids.end(),id)==ids.end(),"cosmetics duplicate/zero item");ids.push_back(id);
        definitions.push_back(std::make_unique<Root>(ba::call(item.get(),"get_Definition")));
        Obj definition=definitions.back()->get();require(definition!=nullptr,"cosmetics definition missing");
        if(!itemRows.empty())itemRows+=',';
        itemRows+="{\"id\":"+std::to_string(id)+",\"entitlement\":"+std::to_string(ba::get<uint32_t>(definition,"EntitlementKey"))+
            ",\"label\":"+std::to_string(ba::get<uint32_t>(definition,"Label"))+"}";
    }
    for(size_t i=0;i<slotCount;++i) {
        Root slot(ba_catalog::arrayAt(slotItems.get(),i));require(slot.get()!=nullptr,"cosmetics slot missing");
        const uint32_t id=ba_catalog::unbox<uint32_t>(ba::call(slot.get(),"get_ID")),fallback=ba::get<uint32_t>(slot.get(),"DefaultItem");
        require(id && std::find(order.begin(),order.end(),id)==order.end(),"cosmetics duplicate/zero slot");order.push_back(id);
        std::vector<uint32_t> compatible;
        for(size_t j=0;j<ids.size();++j) {
            // FilterItem takes CosmeticDefinition, not CosmeticItem or a label ID.
            void* args[]={definitions[j]->get()};Root accepted(ba::call(slot.get(),"FilterItem",1,args));
            if(ba_tables::boolean(accepted.get()))compatible.push_back(ids[j]);
        }
        require((!fallback && compatible.empty()) || (fallback && std::find(compatible.begin(),compatible.end(),fallback)!=compatible.end()),
            "cosmetics default/category mismatch");
        require(!fallback || std::find(defaults.begin(),defaults.end(),fallback)==defaults.end(),"cosmetics duplicate nonzero default");defaults.push_back(fallback);
        if(!slotRows.empty())slotRows+=',';
        slotRows+="{\"id\":"+std::to_string(id)+",\"default_item\":"+std::to_string(fallback)+",\"compatible_items\":"+numbers(compatible)+"}";
    }
    Root config(ba::get<Obj>(ba::owner,"_clientGlobalConfig"));require(config.get()!=nullptr,"cosmetics global config missing");
    const uint32_t portrait=ba::get<uint32_t>(config.get(),"PortraitCosmeticSlot"),banner=ba::get<uint32_t>(config.get(),"BannerCosmeticSlot");
    require(portrait!=banner && std::find(order.begin(),order.end(),portrait)!=order.end() && std::find(order.begin(),order.end(),banner)!=order.end(),
        "cosmetics identity slot roles invalid");
    return "{\"schema\":1,\"build\":37822,\"native_slot_order\":"+numbers(order)+",\"roles\":{\"portrait\":"+std::to_string(portrait)+
        ",\"banner\":"+std::to_string(banner)+"},\"items\":["+itemRows+"],\"slots\":["+slotRows+"]}\n";
}
static void update(Obj front) {
    unlockUpdate(front);
    if(finished || !ba::flag(L"-player-cosmetics-catalog-export") || !ba::localMenu() || !ba_local_menu::ready(front))return;
    try {
        require(ba_dedicated_session::unityThread==GetCurrentThreadId(),"cosmetics export off Unity thread");
        if(!ba_dedicated_session::inMenu() || !ba_dedicated_session::worldIdle(ba::read<Obj>(front,0xd8)))return;
        const bool a=ba_public_bots::cosmetics.ready(),b=slots.ready();if(!a || !b)return;
        Root account(ba::get<Obj>(front,"_accountService")),cosmetics(ba::get<Obj>(account.get(),"_cosmetics"));
        require(cosmetics.get()!=nullptr,"cosmetics owned account missing");const auto before=saved(cosmetics.get());
        const std::string text=serialize();require(text==serialize(),"cosmetics catalog serialization not repeatable");
        require(ba::get<Obj>(account.get(),"_cosmetics")==cosmetics.get() && saved(cosmetics.get())==before &&
            ba_dedicated_session::inMenu() && ba_dedicated_session::worldIdle(ba::read<Obj>(front,0xd8)),"cosmetics export changed loadout/world");
        const std::wstring path=ba_export::moduleDirectory()+L"investigation\\runtime\\player-cosmetics-catalog-"+std::to_wstring(GetCurrentProcessId())+L".json";
        require(GetFileAttributesW(path.c_str())==INVALID_FILE_ATTRIBUTES && GetLastError()==ERROR_FILE_NOT_FOUND,"cosmetics output already exists or is unavailable");
        ba_export::atomicWrite(path,reinterpret_cast<const unsigned char*>(text.data()),text.size());finished=true;
        ba::log("BA_RESURRECTION_COSMETIC_CATALOG_V1 exported: bytes=%zu repeatable=1 loadoutUnchanged=1 worldIdle=1",text.size());
    } catch(const std::exception& error) {finished=true;ba::log("Cosmetics catalog export failed: %s",error.what());}
}
}
