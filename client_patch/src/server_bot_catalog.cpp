#pragma once
// Included inside ba_export. All values come from locally installed tables;
// this file contains no recovered names, decks or cosmetic inventories.
namespace bot_catalog {
using ba_tables::require;
static auto& characters=ba_bot_characters::characters;
static auto& characterNames=ba_bot_characters::characterNames;
static auto& slots=*new ba_tables::Table("CosmeticSlot","CosmeticSlotTable","80afad8f743498b4881dccafa8ebb850");
static void cleanup(){ba_bot_characters::cleanup();}
static bool ready() {
    const bool a=ba_public_bots::ready(),b=ba_bot_characters::ready(),c=slots.ready();
    return a && b && c;
}
static size_t size(Obj array,size_t maximum) {
    require(array!=nullptr,"bot export array missing");
    const size_t result=ba_catalog::length(array);require(result<=maximum,"bot export array limit");return result;
}
static std::string hex(const Bytes& bytes) {
    const char* alphabet="0123456789abcdef";std::string result;result.reserve(bytes.size()*2);
    for(unsigned char value:bytes){result+=alphabet[value>>4];result+=alphabet[value&15];}return result;
}
static Bytes protoBytes(Obj value) {
    void* args[]={value};Root array(ba::invoke(ba::find_class("Google.Protobuf","MessageExtensions"),nullptr,"ToByteArray",1,args));
    return arrayBytes(array.get(),65536);
}
static std::string integerArray(Obj array,size_t maximum) {
    std::string result="[";const size_t count=size(array,maximum);
    for(size_t i=0;i<count;++i) {
        const uint32_t id=ba::read<uint32_t>(array,0x20+i*4);
        require(id && ba_public_bots::cosmetics.at(id),"bot export cosmetic does not resolve");
        if(i)result+=',';result+=std::to_string(id);
    }
    return result+"]";
}
static std::string deck(Obj choice) {
    const int type=ba::get<int>(choice,"Type");require(type>=0 && type<=2,"bot export unknown deck kind");
    Root shared(ba::call(choice,"GetDeck"));require(shared.get()!=nullptr,"bot export deck resolution failed");
    Root copy(ba::make("Uncapped","Deck"));void* copyArgs[]={shared.get()};ba::call(copy.get(),"CopyFromDeck",1,copyArgs);
    Root proto(ba_dedicated_deck::proto(copy.get()));
    uint32_t reference=0,portrait=0,banner=0;std::string name;
    if(type==1) {
        reference=ba::read<uint32_t>(choice,0x20);Root character(characters.at(reference));
        require(character.get()!=nullptr,"bot export character missing");
        Root definition(ba::get<Obj>(character.get(),"AICharacterDefinition"));
        require(definition.get()!=nullptr,"bot export character definition missing");
        for(const auto& entry:characterNames)if(entry.first==reference){name=entry.second;break;}
        require(!name.empty() && name.size()<=96,"bot export character name invalid");
        const auto ids=ba_bot_characters::appearance(definition.get(),proto.get(),ba_public_bots::cosmetics);
        portrait=ids.first;banner=ids.second;
    } else if(type==2)reference=ba::read<uint32_t>(choice,0x24);
    return "{\"kind\":"+std::to_string(type)+",\"reference\":"+std::to_string(reference)+
        ",\"name\":"+ba_catalog::quote(name)+",\"portrait\":"+std::to_string(portrait)+",\"banner\":"+std::to_string(banner)+
        ",\"deck_hex\":"+ba_catalog::quote(hex(protoBytes(proto.get())))+"}";
}
static std::string weights(Obj array,int mode,std::vector<uint32_t>& referenced) {
    std::string result="[";const size_t count=size(array,128);bool first=true;
    for(size_t i=0;i<count;++i) {
        Obj row=ba_catalog::arrayAt(array,i);require(row!=nullptr,"bot export profile row missing");
        const uint32_t id=ba::get<uint32_t>(row,"AiProfile"),weight=ba::get<uint32_t>(row,"_weight");
        Root profile(ba_public_bots::profiles.at(id));require(profile.get() && ba::get<int>(profile.get(),"GameMode")==mode,"bot export mode/profile mismatch");
        if(!weight || !ba::get<bool>(profile.get(),"Enable"))continue;
        require(weight<=1000000,"bot export weight limit");
        if(!first)result+=',';first=false;
        result+="{\"profile\":"+std::to_string(id)+",\"weight\":"+std::to_string(weight)+"}";
        if(std::find(referenced.begin(),referenced.end(),id)==referenced.end())referenced.push_back(id);
    }
    return result+"]";
}
static Bytes serialize() {
    require(ready(),"bot export tables not ready");
    Root management(ba_public_bots::management.get());
    Obj modes=ba::get<Obj>(management.get(),"_profilesByGameMode");std::string modeRows,profileRows;
    std::vector<uint32_t> referenced;std::vector<int> seen;
    for(size_t i=0;i<size(modes,32);++i) {
        Obj row=ba_catalog::arrayAt(modes,i);require(row!=nullptr,"bot export mode row missing");
        const int mode=ba::get<int>(row,"_gameMode");if(mode!=1 && mode!=2 && mode!=4 && mode!=5)continue;
        require(std::find(seen.begin(),seen.end(),mode)==seen.end(),"bot export duplicate mode");seen.push_back(mode);
        const auto opponents=weights(ba::get<Obj>(row,"_opponentAIProfilesByWeight"),mode,referenced);
        const auto teammates=weights(ba::get<Obj>(row,"_teammateAIProfilesByWeight"),mode,referenced);
        if(!modeRows.empty())modeRows+=',';
        modeRows+="{\"mode\":"+std::to_string(mode)+",\"opponents\":"+opponents+",\"teammates\":"+teammates+"}";
    }
    require(seen.size()==4,"bot export required modes missing");
    for(uint32_t id:referenced) {
        Root profile(ba_public_bots::profiles.at(id));Root definition(ba::get<Obj>(profile.get(),"AIConfigDefinition"));
        require(definition.get()!=nullptr,"bot export profile definition missing");
        Obj choices=ba::get<Obj>(definition.get(),"_decks");const size_t count=size(choices,128);require(count>0,"bot export empty decks");
        std::string decks;
        for(size_t i=0;i<count;++i){if(i)decks+=',';decks+=deck(ba_catalog::arrayAt(choices,i));}
        if(!profileRows.empty())profileRows+=',';
        profileRows+="{\"profile\":"+std::to_string(id)+",\"mode\":"+std::to_string(ba::get<int>(profile.get(),"GameMode"))+
            ",\"decks\":["+decks+"]}";
    }
    std::string names;Root namesConfig(ba::get<Obj>(management.get(),"_nameConfig"));require(namesConfig.get()!=nullptr,"bot export name config missing");
    Obj english=ba::get<Obj>(namesConfig.get(),"_englishNames");const size_t nameCount=size(english,100000);require(nameCount>0,"bot export names missing");
    for(size_t i=0;i<nameCount;++i){if(i)names+=',';names+=ba_catalog::quote(ba_catalog::utf8(ba_catalog::arrayAt(english,i)));}
    Root allowed(ba::get<Obj>(management.get(),"_randomizeCosmeticOptions"));require(allowed.get()!=nullptr,"bot export cosmetic pools missing");
    const auto portraits=integerArray(ba::get<Obj>(allowed.get(),"Portrait"),1024),banners=integerArray(ba::get<Obj>(allowed.get(),"Banner"),1024);
    std::string allCosmetics;Root cosmeticTable(ba_public_bots::cosmetics.get()),elements(ba::call(cosmeticTable.get(),"get_Elements"));
    const size_t cosmeticCount=size(elements.get(),4096);
    for(size_t i=0;i<cosmeticCount;++i) {
        Root id(ba::call(ba_catalog::arrayAt(elements.get(),i),"get_ID"));if(i)allCosmetics+=',';
        allCosmetics+=std::to_string(ba_catalog::unbox<uint32_t>(id.get()));
    }
    std::string strengths;
    for(uint32_t id:{17u,18u,19u}) {
        Root profile(ba_public_bots::profiles.at(id)),definition(ba::get<Obj>(profile.get(),"AIConfigDefinition"));
        require(ba::get<bool>(profile.get(),"Enable") && ba::get<int>(profile.get(),"GameMode")==4,"bot export strength profile mismatch");
        Obj rows=ba::get<Obj>(definition.get(),"_cheatModifiersByRating");require(size(rows,16)==1,"bot export strength row mismatch");
        Root strength(ba::call(ba::get<Obj>(ba_catalog::arrayAt(rows,0),"CheatModifier"),"ToProto"));
        if(!strengths.empty())strengths+=',';
        strengths+="{\"profile\":"+std::to_string(id)+",\"resource_q\":"+std::to_string(ba::get<int64_t>(strength.get(),"resourceMultiplier_"))+
            ",\"damage_q\":"+std::to_string(ba::get<int64_t>(strength.get(),"armyDamageMultiplier_"))+
            ",\"health_q\":"+std::to_string(ba::get<int64_t>(strength.get(),"armyHealthMultiplier_"))+"}";
    }
    const std::string text="{\"schema\":1,\"build\":37822,\"names_language\":\"en\",\"character_names_language\":\"exporting_client_locale\","
        "\"modes\":["+modeRows+"],\"profiles\":["+profileRows+"],\"names\":["+names+"],\"portraits\":"+portraits+
        ",\"banners\":"+banners+",\"cosmetic_ids\":["+allCosmetics+"],\"strengths\":["+strengths+"]}\n";
    require(text.size()<=4*1024*1024,"bot export catalog size limit");return Bytes(text.begin(),text.end());
}
static Bytes exportFile() {
    Bytes result=serialize();require(result==serialize(),"bot export catalog is not repeatable");
    atomicWrite(path(L"bot-catalog.json"),result.data(),result.size());
    note("Bot catalog exported from original mode pools, copied decks, names, cosmetics and difficulty modifiers.");return result;
}
}
