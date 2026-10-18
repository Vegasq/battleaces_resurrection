#pragma once
// Installed roster inputs only; no recovered names, decks or cosmetic assets are
// embedded here. Selection policy is ours, not a claim about the retired server.
namespace ba_public_bots {
using ba::Obj;using ba_local::Root;using ba_tables::require;
static auto& management=*new ba_tables::Asset("AIManagementConfigDefinition","26805241a24f37c429496a6a8b55fcb1");
static auto& profiles=*new ba_tables::Table("AIProfile","AIProfileTable","35290f27a7e495444bf634c20a53d056");
static auto& presets=*new ba_tables::Table("AIDeckPreset","AIDeckPresetTable","3bd57d6a122bd49479f5530caa5e81b7");
static auto& cosmetics=*new ba_tables::Table("CosmeticItem","CosmeticItemTable","c0a3ae0b3a257c04482d362032ce18c4");
static auto& previousName=*new std::string();
static bool ready(int mode=1) {
    // Poll all independent loads; short circuiting would unnecessarily serialize them.
    const bool a=management.ready(),b=profiles.ready(),c=presets.ready(),d=cosmetics.ready();
    const bool e=mode==1 || ba_bot_characters::ready();
    return a && b && c && d && e;
}
static uint32_t random(uint32_t bound) {
    require(bound>0,"public bot random range empty");
    const uint32_t threshold=static_cast<uint32_t>((UINT64_C(1)<<32)%bound);
    uint32_t value=0;
    do {require(BCryptGenRandom(nullptr,reinterpret_cast<PUCHAR>(&value),sizeof(value),BCRYPT_USE_SYSTEM_PREFERRED_RNG)>=0,
        "public bot random generator failed");}while(value<threshold);
    return value%bound;
}
static uint32_t length(Obj array,uint32_t maximum) {
    require(array!=nullptr,"public bot array missing");
    const auto n=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(array);
    require(n>0 && n<=maximum,"public bot array capacity invalid");return static_cast<uint32_t>(n);
}
static Obj item(Obj array,uint32_t index) {
    Obj value=ba::read<Obj>(array,0x20+index*sizeof(Obj));
    require(value!=nullptr,"public bot array element missing");return value;
}
static uint32_t profile(int mode,bool teammate) {
    Obj modes=ba::get<Obj>(management.get(),"_profilesByGameMode"),selected=nullptr;
    const auto n=length(modes,32);
    for(uint32_t i=0;i<n;++i)if(ba::get<int>(item(modes,i),"_gameMode")==mode) {
        require(!selected,"duplicate public bot mode");selected=item(modes,i);
    }
    require(selected!=nullptr,"public bot mode has no authored profile pool");
    Obj choices=ba::get<Obj>(selected,teammate?"_teammateAIProfilesByWeight":"_opponentAIProfilesByWeight");
    require(choices!=nullptr,"public bot role pool missing");
    if(mode==5 && teammate && !ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(choices))return profile(2,true);
    const auto count=length(choices,128);
    std::vector<std::pair<uint32_t,uint32_t>> pool;uint32_t total=0;
    for(uint32_t i=0;i<count;++i) {
        Obj row=item(choices,i);const uint32_t id=ba::get<uint32_t>(row,"AiProfile"),weight=ba::get<uint32_t>(row,"_weight");
        Root entry(profiles.at(id));
        require(entry.get() && ba::get<int>(entry.get(),"GameMode")==mode,"public bot profile mode mismatch");
        if(!ba::get<bool>(entry.get(),"Enable") || !weight)continue;
        require(weight<=1000000 && total<=1000000-weight,"public bot weights exceed capacity");
        pool.emplace_back(id,weight);total+=weight;
    }
    require(total>0,"public bot enabled profile pool empty");
    // A bounded test-only override lets the native harness qualify every profile.
    const auto forced=mode==1 && ba::flag(L"-public-ai-smoke")?ba::argument(L"-public-ai-smoke-profile="):std::string();
    if(!forced.empty()) {
        size_t used=0;const auto id=std::stoul(forced,&used);
        require(used==forced.size() && id<=UINT32_MAX,"public bot test profile invalid");
        for(const auto& entry:pool)if(entry.first==id)return entry.first;
        throw std::runtime_error("public bot test profile is not in enabled mode pool");
    }
    uint32_t pick=random(total);
    for(const auto& entry:pool){if(pick<entry.second)return entry.first;pick-=entry.second;}
    throw std::runtime_error("public bot weighted selection failed");
}
static uint32_t cosmetic(Obj collection,const char* field) {
    Obj array=ba::get<Obj>(collection,field);const uint32_t n=length(array,1024);
    // IntKey<T> is a four-byte value type, not an object reference.
    const uint32_t id=ba::read<uint32_t>(array,0x20+random(n)*sizeof(uint32_t));
    require(id && cosmetics.at(id),"public bot cosmetic definition missing");return id;
}
struct Snapshot {
    uint32_t profile=0,preset=0,portrait=0,banner=0,nameIndex=0,character=0;
    std::string name;
    std::unique_ptr<Root> deck;
};
static Snapshot choose(int mode,const std::vector<std::string>& excludedNames,bool teammate=false) {
    require(ready(mode),"public bot assets not ready");Snapshot result;result.profile=profile(mode,teammate);
    Root entry(profiles.at(result.profile));Obj definition=ba::get<Obj>(entry.get(),"AIConfigDefinition");
    require(definition!=nullptr,"public bot profile definition missing");
    auto excluded=[&](const std::string& name){return std::find(excludedNames.begin(),excludedNames.end(),name)!=excludedNames.end();};
    Obj decks=ba::get<Obj>(definition,"_decks");const auto deckCount=length(decks,128);
    std::vector<Obj> eligible;
    for(uint32_t i=0;i<deckCount;++i) {
        Obj candidate=item(decks,i);const int kind=ba::get<int>(candidate,"Type");
        require(kind==1 || kind==2,"public bot deck kind unsupported");
        if(kind==1 && excluded(ba_bot_characters::name(ba::read<uint32_t>(candidate,0x20))))continue;
        eligible.push_back(candidate);
    }
    require(!eligible.empty(),"public bot has no distinct character deck");
    Obj choice=eligible[random(static_cast<uint32_t>(eligible.size()))];const int kind=ba::get<int>(choice,"Type");
    Root shared(ba::call(choice,"GetDeck")),copy(ba::make("Uncapped","Deck"));
    require(shared.get()!=nullptr,"public bot shared deck missing");
    void* copyArgs[]={shared.get()};ba::call(copy.get(),"CopyFromDeck",1,copyArgs);
    result.deck=std::make_unique<Root>(ba_dedicated_deck::proto(copy.get()));
    if(kind==1) {
        result.character=ba::read<uint32_t>(choice,0x20);
        Root character(ba_bot_characters::characters.at(result.character));
        require(character.get()!=nullptr,"public bot character missing");
        result.name=ba_bot_characters::name(result.character);
        Root characterDefinition(ba::get<Obj>(character.get(),"AICharacterDefinition"));
        require(characterDefinition.get()!=nullptr,"public bot character definition missing");
        const auto ids=ba_bot_characters::appearance(characterDefinition.get(),result.deck->get(),cosmetics);
        result.portrait=ids.first;result.banner=ids.second;
    } else {
        result.preset=ba::read<uint32_t>(choice,0x24);
        Obj namesConfig=ba::get<Obj>(management.get(),"_nameConfig");
        require(namesConfig!=nullptr,"public bot names configuration missing");
        Obj names=ba::get<Obj>(namesConfig,"_englishNames");const uint32_t count=length(names,100000);
        for(unsigned attempt=0;attempt<64;++attempt) {
            result.nameIndex=random(count);auto name=ba_catalog::utf8(item(names,result.nameIndex));
            if(name.empty() || name.size()>32 || excluded(name) || name==previousName)continue;
            bool valid=true;for(unsigned char c:name)if(c<32 || c==127)valid=false;
            if(valid){result.name=std::move(name);break;}
        }
        require(!result.name.empty(),"public bot could not choose a distinct installed name");
        Obj allowed=ba::get<Obj>(management.get(),"_randomizeCosmeticOptions");
        require(allowed!=nullptr,"public bot cosmetic choices missing");
        result.portrait=cosmetic(allowed,"Portrait");result.banner=cosmetic(allowed,"Banner");
        // SimPlayer obtains equipped portrait/banner from the deck's cosmetic
        // entitlements, not the standalone ArmyConfig/JoinArmy fields. Freeze both
        // representations so native loading and post-game models use the same IDs.
        Root entitlement(ba::make("CommonPb","Entitlement"));
        Obj keys=ba::get<Obj>(entitlement.get(),"cosmeticAssetKeys_");
        ba_dedicated_deck::addUint(keys,result.portrait);ba_dedicated_deck::addUint(keys,result.banner);
        Obj entries=ba::get<Obj>(result.deck->get(),"entitlements_");
        require(ba_local::count(entries)==0,"public deck already has unvalidated cosmetic entitlements");
        ba_local::addItem(entries,entitlement.get());
    }
    previousName=result.name;
    ba::log("Public bot snapshot: mode=%d profile=%u preset=%u nameIndex=%u name=%s portrait=%u banner=%u nativePools=1 clonedDeck=1 character=%u teammate=%d",
        mode,result.profile,result.preset,result.nameIndex,result.name.c_str(),result.portrait,result.banner,result.character,teammate?1:0);
    return result;
}
}
