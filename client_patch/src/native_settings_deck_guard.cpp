#pragma once
#include <algorithm>
// Preserve original parsing and unfinished decks; refuse bad persisted graphs
// before the original selector's starter fallback can save over them.
namespace ba_native_settings {
using ba::Obj;using ba_local::Root;
static bool persistedDeck=false;
static std::wstring persistedDeckText;
static DWORD deckInputThread=0;
static std::wstring deckText(Obj value) {
    require(value && ba::klass(value)==ba::find_class("System","String"),"deck input is not a native string");
    const int count=ba::api<int(*)(Obj)>("il2cpp_string_length")(value);
    require(count>=0 && count<=1024*1024,"deck input exceeds supported size");
    return std::wstring(ba::api<const wchar_t*(*)(Obj)>("il2cpp_string_chars")(value),count);
}
static bool tomlNode(Obj table,const char* key,Obj& result) {
    require(table && ba::klass(table)==ba::find_class("Tommy","TomlTable"),"deck account/root is not a TOML table");
    result=nullptr;if(!ba::read<Obj>(table,0x28))return false;
    Root name(ba::str(key));void* args[]={name.get(),&result};Root found(ba::call(table,"TryGetNode",2,args));
    return ba_catalog::unbox<bool>(found.get());
}
static void inspectDeckTable(Obj value) {
    Root table(value);persistedDeck=false;persistedDeckText.clear();deckInputThread=GetCurrentThreadId();
    Obj accountValue=nullptr;if(!tomlNode(table.get(),"account",accountValue))return;
    Root account(accountValue);Obj deckValue=nullptr;if(!tomlNode(account.get(),"decks",deckValue))return;
    Root node(deckValue);
    require(node.get() && ba::klass(node.get())==ba::find_class("Tommy","TomlString"),"persisted account.decks is not a TOML string");
    Root text(ba::read<Obj>(node.get(),0x30));persistedDeckText=deckText(text.get());
    require(!persistedDeckText.empty(),"persisted account.decks is empty");persistedDeck=true;
}
static Obj staticObject(Obj type,const char* name) {
    Obj field=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(type,name);
    require(field!=nullptr,"early deck static field unavailable");Obj value=nullptr;
    ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(field,&value);return value;
}
static Obj arrayField(Obj deck,const char* name,size_t count) {
    Root array(ba::get<Obj>(deck,name));
    Obj field=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(ba::klass(deck),name);
    require(field!=nullptr,"persisted deck array field missing");
    Obj type=ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(field);
    Obj expected=ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(type);
    require(array.get() && ba::klass(array.get())==expected && ba_catalog::length(array.get())==count,
        "persisted deck array type/dimensions invalid");return array.get();
}
struct SerializedDeck {std::array<uint32_t,8> units{};std::array<uint32_t,4> groups{};};
struct DeckDocument {SerializedDeck selected;std::vector<SerializedDeck> saved;};
static Obj jsonProperty(Obj object,const char* key,bool required=true) {
    require(object && ba::klass(object)==ba::find_class("Newtonsoft.Json.Linq","JObject"),"persisted JSON deck is not an object");
    Root name(ba::str(key));void* args[]={name.get()};Root property(ba::call(object,"Property",1,args));
    if(!property.get()){require(!required,"persisted JSON required deck field missing");return nullptr;}
    return ba::call(property.get(),"get_Value");
}
template<size_t N> static void jsonKeys(Obj value,std::array<uint32_t,N>& keys) {
    Root array(value);require(array.get() && ba::klass(array.get())==ba::find_class("Newtonsoft.Json.Linq","JArray"),"persisted JSON deck keys are not an array");
    Root count(ba::call(array.get(),"get_Count"));require(ba_catalog::unbox<int>(count.get())==N,"persisted JSON deck array dimensions invalid");
    Root first(ba::call(array.get(),"get_First"));Obj current=first.get();
    for(size_t i=0;i<N;++i) {
        Root item(current),value(jsonProperty(item.get(),"_id"));
        require(value.get() && ba::klass(value.get())==ba::find_class("Newtonsoft.Json.Linq","JValue"),"persisted JSON deck ID is not a scalar");
        Root number(ba::call(value.get(),"get_Value"));
        require(number.get() && ba::klass(number.get())==ba::find_class("System","Int64"),"persisted JSON deck ID is not an integer");
        const auto key=ba_catalog::unbox<int64_t>(number.get());require(key>=0 && key<=UINT32_MAX,"persisted JSON deck ID exceeds uint32");
        keys[i]=static_cast<uint32_t>(key);current=ba::call(item.get(),"get_Next");
    }
    require(!current,"persisted JSON deck array traversal differs");
}
static SerializedDeck jsonDeck(Obj value) {
    Root deck(value),units(jsonProperty(deck.get(),"_units")),groups(jsonProperty(deck.get(),"_activeAbilities"));
    SerializedDeck result;jsonKeys(units.get(),result.units);jsonKeys(groups.get(),result.groups);return result;
}
static DeckDocument jsonDocument(Obj input) {
    // Use the game's retained parser for presence/types, not Unity's initialized
    // default graph: '{}' can otherwise look like a real all-empty deck.
    void* args[]={input};Root document(ba::invoke(ba::find_class("Newtonsoft.Json.Linq","JObject"),nullptr,"Parse",1,args));
    Root selected(jsonProperty(document.get(),"SelectedDeck"));DeckDocument result;result.selected=jsonDeck(selected.get());
    Root saved(jsonProperty(document.get(),"Decks",false));if(!saved.get())return result;
    if(ba::klass(saved.get())==ba::find_class("Newtonsoft.Json.Linq","JValue")) {
        Root scalar(ba::call(saved.get(),"get_Value"));require(!scalar.get(),"persisted JSON saved decks are not an array/null");return result;
    }
    require(ba::klass(saved.get())==ba::find_class("Newtonsoft.Json.Linq","JArray"),"persisted JSON saved decks are not an array");
    Root count(ba::call(saved.get(),"get_Count"));const int size=ba_catalog::unbox<int>(count.get());
    require(size>=0 && size<=4096,"persisted JSON saved-deck count exceeds supported bound");
    Root first(ba::call(saved.get(),"get_First"));Obj current=first.get();
    for(int i=0;i<size;++i) {Root item(current);result.saved.push_back(jsonDeck(item.get()));current=ba::call(item.get(),"get_Next");}
    require(!current,"persisted JSON saved-deck traversal differs");return result;
}
static std::vector<uint32_t> abilityIds() {
    Root table(ba_catalog::table("ActiveAbilityGroupTable"));require(table.get()!=nullptr,"installed ability table unavailable");
    Root elements(ba::call(table.get(),"get_Elements"));const auto count=ba_catalog::length(elements.get());
    require(count>0 && count<=16384,"installed ability catalog unavailable/oversized");std::vector<uint32_t> result;
    for(size_t i=0;i<count;++i) {
        Root row(ba_catalog::arrayAt(elements.get(),i));require(row.get()!=nullptr,"installed ability row missing");
        Root id(ba::call(row.get(),"get_ID"));result.push_back(ba_catalog::unbox<uint32_t>(id.get()));
    }
    return result;
}
static void validateDeck(Obj value,Obj data,const std::vector<uint32_t>& abilities,const SerializedDeck& serialized) {
    Root deck(value);require(deck.get() && ba::klass(deck.get())==ba::find_class("Uncapped","Deck"),"persisted selected/stored deck missing or wrong type");
    Root units(arrayField(deck.get(),"_units",8)),groups(arrayField(deck.get(),"_activeAbilities",4));
    for(size_t i=0;i<8;++i)require(ba::read<uint32_t>(units.get(),0x20+4*i)==serialized.units[i],"native/serialized unit IDs differ");
    for(size_t i=0;i<4;++i)require(ba::read<uint32_t>(groups.get(),0x20+4*i)==serialized.groups[i],"native/serialized ability IDs differ");
    for(int index=0;index<8;++index) {
        uint32_t key=ba::read<uint32_t>(units.get(),0x20+4*index);if(!key || key==UINT32_MAX)continue;
        bool allowLocked=true;void* args[]={&key,&index,data,nullptr,&allowLocked};Root valid(ba::call(deck.get(),"IsValidSlot",5,args));
        require(ba_catalog::unbox<bool>(valid.get()),"persisted unit ID/duplicate/slot rule invalid");
    }
    for(unsigned i=0;i<4;++i) {
        const auto key=ba::read<uint32_t>(groups.get(),0x20+4*i);if(!key || key==UINT32_MAX)continue;
        require(std::find(abilities.begin(),abilities.end(),key)!=abilities.end(),"persisted ability ID is not installed");
    }
}
static void validateStorage(Obj value,const DeckDocument& serialized) {
    Root storage(value);require(storage.get() && ba::klass(storage.get())==ba::find_class("Uncapped","LocalDeckStorage"),"persisted JSON did not yield native deck storage");
    Obj singletonType=ba::find_class("Uncapped","RGameSingleton");
    Obj parent=ba::api<Obj(*)(Obj)>("il2cpp_class_get_parent")(singletonType);
    require(parent && !strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(parent),"SimpleMonoBehaviourSingleton`1") &&
        !strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_namespace")(parent),"Hextant"),"early singleton parent differs");
    Root owner(staticObject(parent,"_instance"));require(owner.get() && ba::klass(owner.get())==singletonType &&
        ba::read<uintptr_t>(owner.get(),0x10),"early singleton owner unavailable");
    Root provider(ba::get<Obj>(owner.get(),"_menuStaticGameDataProvider")),data(ba::get<Obj>(provider.get(),"_localMenuStaticGameData"));
    require(data.get() && ba::klass(data.get())==ba::find_class("Uncapped","StaticGameData"),"early local static data unavailable");
    Root global(ba::get<Obj>(data.get(),"_globalConfig")),configuration(ba::get<Obj>(global.get(),"DeckConfiguration"));
    Root slots(ba::get<Obj>(configuration.get(),"_deck"));require(ba_catalog::length(slots.get())==8,"native slot configuration unavailable");
    const auto abilities=abilityIds();Root selected(ba::get<Obj>(storage.get(),"SelectedDeck"));validateDeck(selected.get(),data.get(),abilities,serialized.selected);
    Root decks(ba::get<Obj>(storage.get(),"Decks"));
    if(decks.get()) {
        const int count=ba::get<int>(decks.get(),"_size");Root items(ba::get<Obj>(decks.get(),"_items"));
        require(count>=0 && count<=4096 && items.get() && static_cast<size_t>(count)<=ba_catalog::length(items.get()),"persisted saved-deck list bounds invalid");
        require(static_cast<size_t>(count)==serialized.saved.size(),"native/serialized saved-deck counts differ");
        for(int i=0;i<count;++i)validateDeck(ba_catalog::arrayAt(items.get(),i),data.get(),abilities,serialized.saved[i]);
    } else require(serialized.saved.empty(),"native saved-deck list missing");
}
}
extern "C" __declspec(dllexport) void* OfflineLocalDeckStorageLoad(void* method) {
    ba::init();
    try {
        using namespace ba_native_settings;
        require(session!=nullptr,"persisted deck gate requires prepared native settings isolation");
        Root registry(staticObject(ba::find_class("Uncapped","VariableRegister"),"InstanceInternal"));
        Root variable(ba::get<Obj>(registry.get(),"_decks")),input(ba::get<Obj>(variable.get(),"_var"));
        const auto text=deckText(input.get());
        if(persistedDeck)require(deckInputThread==GetCurrentThreadId() && text==persistedDeckText,"persisted deck provenance changed before native JSON load");
        std::unique_ptr<DeckDocument> serialized;if(persistedDeck)serialized=std::make_unique<DeckDocument>(jsonDocument(input.get()));
        Root storage(ba::native<Obj(*)(void*)>(0x3dac3b0)(method));
        if(persistedDeck)validateStorage(storage.get(),*serialized);
        session->acceptInput();
        ba::log("NATIVE SETTINGS deck input accepted: persisted=%d originalJson=1 originalSlotRules=%d incompleteAllowed=1 selectorNotCreated=1 BA_RESURRECTION_NATIVE_DECK_INPUT_V1",persistedDeck,persistedDeck);
        return storage.get(); // Root released immediately before caller stores/barriers the unchanged object.
    }catch(const std::exception& error) {
        ba::log("Native persisted deck load refused: %s; inputPreserved=1 selectorUnused=1",error.what());
    }
    TerminateProcess(GetCurrentProcess(),ERROR_BAD_CONFIGURATION);ExitProcess(ERROR_BAD_CONFIGURATION);
}
