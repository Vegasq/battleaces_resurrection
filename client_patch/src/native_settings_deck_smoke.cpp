#pragma once
namespace ba_native_settings {
static void observe(ba::Obj front) {
    if(!ba::flag(L"-native-settings-deck-proof"))return;
    static bool done=false;if(done || !ba_local_menu::ready(front) || !ba_dedicated_deck::initialized ||
        !ba_dedicated_session::inMenu() || !ba_dedicated_session::worldIdle(ba::read<ba::Obj>(front,0xd8)))return;
    try {
        using ba_local::Root;verify();require(session!=nullptr,"native settings proof session missing");
        Root account(ba::get<ba::Obj>(front,"_accountService")),selector(ba::get<ba::Obj>(front,"_deckSelector"));
        Root storage(ba::get<ba::Obj>(account.get(),"_localDeckStorage")),deck(ba_dedicated_deck::selected(account.get()));
        require(account.get()==ba_dedicated_deck::account() &&
            ba::get<ba::Obj>(selector.get(),"_localDeckStorage")==storage.get() &&
            ba::get<ba::Obj>(storage.get(),"SelectedDeck")==deck.get(),"native settings deck ownership mismatch");
        const bool edit=ba::flag(L"-native-settings-deck-edit");
        if(edit) {
            require(session->profile().compare(0,12,"nativestest_")==0,"native deck edit requires an explicit disposable test profile");
            Root data(ba_dedicated_deck::staticData(account.get())),units(ba::get<ba::Obj>(deck.get(),"_units"));
            int index=0;uint32_t replacement=0;
            for(uint32_t candidate:{75u,74u,1u,6u}) {
                bool duplicate=false;for(int i=0;i<8;++i)duplicate|=ba::read<uint32_t>(units.get(),0x20+4*i)==candidate;
                if(duplicate)continue;
                bool allowLocked=false;void* args[]={&candidate,&index,data.get(),account.get(),&allowLocked};
                Root valid(ba::call(deck.get(),"IsValidSlot",5,args));
                if(ba_catalog::unbox<bool>(valid.get())){replacement=candidate;break;}
            }
            require(replacement!=0,"native settings proof lacks a valid distinct unit");
            const auto before=ba_dedicated_deck::savedChanges;void* args[]={&index,&replacement};ba::call(deck.get(),"set_Item",2,args);
            void* abilityArgs[]={data.get(),account.get()};ba::call(deck.get(),"AutoAssignAbilities",2,abilityArgs);
            require(ba_dedicated_deck::savedChanges>before && ba_dedicated_deck::canReady(front),"native deck edit did not reach original save callback");
        }
        auto values=[&](const char* field,size_t length) {
            Root array(ba::get<ba::Obj>(deck.get(),field));require(ba_catalog::length(array.get())==length,"native deck array size mismatch");
            std::string result="[";for(size_t i=0;i<length;++i){if(i)result+=',';result+=std::to_string(ba::read<uint32_t>(array.get(),0x20+4*i));}return result+"]";
        };
        const auto units=values("_units",8),abilities=values("_activeAbilities",4);
        ba::log("NATIVE SETTINGS DECK proof: {\"profile\":%s,\"units\":%s,\"activeAbilityGroups\":%s,\"edited\":%s,\"owned\":true,\"pathVerified\":true,\"worldIdle\":true}",
            ba_catalog::quote(session->profile()).c_str(),units.c_str(),abilities.c_str(),edit?"true":"false");done=true;
    }catch(const std::exception& error){done=true;ba::log("Native settings deck proof failed: %s",error.what());}
}
}
