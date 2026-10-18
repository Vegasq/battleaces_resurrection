#pragma once
// Local mode4 coordinator, deliberately separate from dedicated match seats.
// Original-build evidence: docs/try-deck-ai-native.txt. Opt-in until qualified.
namespace ba_practice {
using ba::Obj;using ba_local::Root;
namespace wire=ba_community_wire;
enum class Phase {Idle,Reserving,Building,Loading,Running,Result,Returning,Failed};
struct State {
    Phase phase=Phase::Idle;
    ba_match_loading::Ticket loadingTicket=0;
    std::unique_ptr<Root> front,controller,human,bot,humanDeck,botDeck,encoded,ai,process,completionInfo,completionUI;
    std::string match;
    uint32_t request=0,aiProfile=18,difficultyProfile=18;
    uint64_t worldLease=0;
    bool reserved=false,buildStarted=false,adding=false,joinPending=false,aiStarted=false,result=false;
    bool conceded=false,continued=false,modalReleased=false;
    bool humanReady=false,botReady=false,humanJoined=false,botJoined=false;
    ULONGLONG began=0,diagnostic=0,aiRequestedAt=0,completionAt=0;
};
static auto& state=*new State();
// The original table loader retains its asset for application lifetime, matching
// the other StaticTables preloads. Do not unload it between practice matches.
static auto& characterReference=*new std::unique_ptr<Root>();
static auto& characterTask=*new std::unique_ptr<Root>();
static bool characterLoaded=false;
static unsigned generations=0,completed=0;
static bool active(){return state.phase!=Phase::Idle;}
static Obj need(Obj value,const char* message){if(!value)throw std::runtime_error(message);return value;}
static void require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
static void root(std::unique_ptr<Root>& target,Obj value){target=std::make_unique<Root>(need(value,"practice root missing"));}
static Obj server(){return state.front?ba::read<Obj>(state.front->get(),0xd8):nullptr;}
static Obj manager(){return need(ba::get<Obj>(ba::owner,"<AIManager>k__BackingField"),"practice AI manager missing");}
static Obj table(const char* name) {
    Obj tableClass=ba::find_class("Uncapped",name);
    Root type(ba::api<Obj(*)(Obj)>("il2cpp_type_get_object")(ba::api<Obj(*)(Obj)>("il2cpp_class_get_type")(tableClass)));
    void* tableArgs[]={type.get()};return ba::invoke(ba::find_class("Uncapped","StaticTables"),nullptr,"GetTable",1,tableArgs);
}
static void arraySet(Obj array,size_t index,Obj value) {
    ba::api<void(*)(Obj,void**,Obj)>("il2cpp_gc_wbarrier_set_field")(array,reinterpret_cast<void**>(static_cast<char*>(array)+0x20+index*sizeof(Obj)),value);
}
static bool boolean(Obj value){return *ba::api<bool*(*)(Obj)>("il2cpp_object_unbox")(need(value,"practice boolean result missing"));}
static bool characterTableReady() {
    if(characterLoaded)return true;
    if(!characterTask && table("AICharacterTable")){characterLoaded=true;return true;}
    if(!characterTask) {
        Obj cls=ba::find_class("Uncapped","StaticTables");
        Obj method=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(cls,"LoadTableAsync",1);
        Root reflected(ba::api<Obj(*)(Obj,Obj)>("il2cpp_method_get_object")(method,cls));
        Root types(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(ba::find_class("System","Type"),2));
        size_t index=0;
        for(const char* name:{"AICharacter","AICharacterTable"}) {
            Root type(ba::api<Obj(*)(Obj)>("il2cpp_type_get_object")(ba::api<Obj(*)(Obj)>("il2cpp_class_get_type")(ba::find_class("Uncapped",name))));
            arraySet(types.get(),index++,type.get());
        }
        void* genericArgs[]={types.get()};Root closed(ba::call(reflected.get(),"MakeGenericMethod",1,genericArgs));
        Obj referenceClass=ba::find_class("UnityEngine.AddressableAssets","AssetReference");
        ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(referenceClass);
        Root reference(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(referenceClass));
        Root guid(ba::str("524d3ead68bbbbc48bdbc8a383e4c934"));void* ctorArgs[]={guid.get()};
        ba::invoke(referenceClass,reference.get(),".ctor",1,ctorArgs);root(characterReference,reference.get());
        Root parameters(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(ba::find_class("System","Object"),1));
        arraySet(parameters.get(),0,reference.get());void* invokeArgs[]={nullptr,parameters.get()};
        root(characterTask,ba::call(closed.get(),"Invoke",2,invokeArgs));
        ba::log("Practice requested original async AICharacterTable load from installed asset");
    }
    Root done(ba::call(characterTask->get(),"get_IsCompleted"));
    require(GetTickCount64()-state.began<30000,"practice AI table load deadline");
    if(!boolean(done.get()))return false;
    Root faulted(ba::call(characterTask->get(),"get_IsFaulted")),cancelled(ba::call(characterTask->get(),"get_IsCanceled"));
    if(boolean(faulted.get())) {
        Root error(ba::call(characterTask->get(),"get_Exception"));
        ba::log("Practice AI table load failed: %s",ba_catalog::utf8(ba::call(error.get(),"ToString")).c_str());
        throw std::runtime_error("practice original table loader failed");
    }
    require(!boolean(cancelled.get()) && table("AICharacterTable"),"practice loader completed without table");
    Root elementType(ba::api<Obj(*)(Obj)>("il2cpp_type_get_object")(ba::api<Obj(*)(Obj)>("il2cpp_class_get_type")(ba::find_class("Uncapped","AICharacter"))));
    void* mappingArgs[]={elementType.get()};Root mapped(ba::invoke(ba::find_class("Uncapped","StaticTables"),nullptr,"GetElementTableType",1,mappingArgs));
    require(mapped.get() && ba_catalog::utf8(ba::call(mapped.get(),"get_Name"))=="AICharacterTable","practice table mapping missing");
    characterLoaded=true;ba::log("Practice original AICharacterTable load/registration completed");return true;
}
static Obj tableElement(const char* name,uint32_t id) {
    Root loaded(need(table(name),"practice AI table not loaded"));
    Obj method=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(ba::find_class("Uncapped","IIntTable"),"GetElementByID",1);
    method=ba::api<Obj(*)(Obj,Obj)>("il2cpp_object_get_virtual_method")(loaded.get(),method);
    void* args[]={&id};return ba_local::invokeMethod(method,loaded.get(),args);
}
static uint32_t profileId() {
    return state.aiProfile; // Frozen at match creation, including through results.
}
static void applyDifficultyModifiers(Obj config) {
    if(!ba::localMenu())return;
    Root profile(tableElement("AIProfileTable",state.difficultyProfile));
    require(profile.get() && ba::get<bool>(profile.get(),"Enable") && ba::get<int>(profile.get(),"GameMode")==4,"difficulty modifier profile mismatch");
    Root definition(need(ba::get<Obj>(profile.get(),"AIConfigDefinition"),"difficulty definition missing"));
    Root rows(need(ba::get<Obj>(definition.get(),"_cheatModifiersByRating"),"difficulty rating row missing"));
    require(ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(rows.get())==1,"difficulty requires one authored rating row");
    Root row(need(ba::read<Obj>(rows.get(),0x20),"difficulty row missing"));
    Root authored(need(ba::get<Obj>(row.get(),"CheatModifier"),"difficulty strength missing"));
    Root strength(need(ba::call(authored.get(),"ToProto"),"difficulty fixed-point conversion failed"));
    const int64_t unity=INT64_C(4294967296);
    const int64_t resources=ba::get<int64_t>(strength.get(),"resourceMultiplier_");
    const int64_t damage=ba::get<int64_t>(strength.get(),"armyDamageMultiplier_");
    const int64_t health=ba::get<int64_t>(strength.get(),"armyHealthMultiplier_");
    for(int64_t value:{resources,damage,health})require(value>0 && value<=4*unity,"difficulty strength outside supported bounds");
    Root armies(ba::get<Obj>(config,"armies_"));
    require(ba_local::count(armies.get())==2,"difficulty army count changed");
    Root bot(ba_bootstrap::item(armies.get(),1));
    require(ba::get<uint32_t>(bot.get(),"armyId_")==1,"difficulty bot army mismatch");
    if(resources==unity && damage==unity && health==unity) {
        ba::log("Practice difficulty modifiers: selected=%s resourceQ=%lld damageQ=%lld healthQ=%lld baselineUnchanged=1 humanUnchanged=1",
            ba_practice_settings::name(state.difficultyProfile),resources,damage,health);return;
    }
    Root existing(ba::get<Obj>(bot.get(),"modifiers_"));
    Root modifiers(existing.get()?ba::call(existing.get(),"Clone"):ba::make("GamePb","ArmyModifiers"));
    const int64_t baseline=existing.get()?ba::get<int64_t>(existing.get(),"resourcingMultiplier_"):unity;
    require(baseline>0 && baseline<=16*unity,"difficulty baseline resource multiplier outside supported bounds");
    // Positive Q32 product without float rounding or an overflowing 64-bit product.
    const uint64_t a=static_cast<uint64_t>(baseline),b=static_cast<uint64_t>(resources),mask=UINT64_C(0xffffffff);
    const uint64_t product=((a>>32)*(b>>32)<<32)+(a>>32)*(b&mask)+(a&mask)*(b>>32)+(((a&mask)*(b&mask))>>32);
    ba::set<int64_t>(modifiers.get(),"resourcingMultiplier_",static_cast<int64_t>(product));
    std::vector<uint32_t> used;
    auto collect=[&used](Obj list) {
        const int count=ba_local::count(need(list,"difficulty modifier collection missing"));
        require(count>=0 && count<=16384,"difficulty modifier collection capacity");
        for(int i=0;i<count;++i)used.push_back(ba::get<uint32_t>(ba_bootstrap::item(list,i),"key_"));
    };
    collect(ba::get<Obj>(config,"modifiers_"));
    for(int i=0;i<2;++i) {
        Obj original=ba::get<Obj>(ba_bootstrap::item(armies.get(),i),"modifiers_");
        if(original)collect(ba::get<Obj>(original,"armyBuffs_"));
    }
    uint32_t key=0xbaac0001;
    while(std::find(used.begin(),used.end(),key)!=used.end())++key;
    require(key!=0 && key!=UINT32_MAX,"difficulty modifier key exhausted");
    Root buff(ba::make("GamePb","ModifierConfig"));ba::set<uint32_t>(buff.get(),"key_",key);
    for(const auto& entry:std::array<std::pair<int,int64_t>,2>{{{1,damage},{4,health}}}) {
        Root attribute(ba::make("GamePb","EntityAttribute"));
        ba::set<int>(attribute.get(),"type_",entry.first);ba::set<int64_t>(attribute.get(),"value_",entry.second);
        Root modifier(ba::make("GamePb","EntityAttributeModifier"));
        ba::set<int>(modifier.get(),"modifierType_",1);ba::set<Obj>(modifier.get(),"attribute_",attribute.get());
        ba_local::addItem(ba::get<Obj>(buff.get(),"modifiers_"),modifier.get());
    }
    ba_local::addItem(ba::get<Obj>(modifiers.get(),"armyBuffs_"),buff.get());
    ba::set<Obj>(bot.get(),"modifiers_",modifiers.get());
    ba::log("Practice difficulty modifiers: selected=%s resourceQ=%lld damageQ=%lld healthQ=%lld effectiveResourceQ=%llu buffKey=%u humanUnchanged=1",
        ba_practice_settings::name(state.difficultyProfile),resources,damage,health,product,key);
    if(ba::flag(L"-practice-ai-smoke"))ba::log("Practice bot army modifiers: %s",ba_catalog::utf8(ba::call(modifiers.get(),"ToString")).c_str());
}
static Obj aiDeck() {
    Root profile(tableElement("AIProfileTable",profileId()));
    require(profile.get() && ba::get<bool>(profile.get(),"Enable") && ba::get<int>(profile.get(),"GameMode")==4,"practice shipped AI profile mismatch");
    Obj config=need(ba::get<Obj>(profile.get(),"AIConfigDefinition"),"practice AI config missing");
    Obj decks=need(ba::get<Obj>(config,"_decks"),"practice authored AI decks missing");
    require(ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(decks)>0,"practice AI deck list empty");
    Obj choice=need(ba::read<Obj>(decks,0x20),"practice first authored AI deck missing");
    require(ba::get<int>(choice,"Type")==1,"practice first deck is not a shipped character choice");
    const auto characterId=ba::read<uint32_t>(choice,0x20);
    Root character(tableElement("AICharacterTable",characterId));
    Obj definition=need(ba::get<Obj>(need(character.get(),"practice AI character missing"),"AICharacterDefinition"),"practice AI character definition missing");
    Root shared(ba::get<Obj>(definition,"Deck"));Root copy(ba::make("Uncapped","Deck"));
    void* copyArgs[]={need(shared.get(),"practice authored AI deck missing")};ba::call(copy.get(),"CopyFromDeck",1,copyArgs);
    ba::log("Practice AI policy: profile=%u first shipped character=%u; shared definition copied; offlineDifficulty=%d",profileId(),characterId,ba::localMenu()?1:0);
    return ba_dedicated_deck::proto(copy.get());
}
static void fail(const char* where,const std::exception& error) {
    ba_local::ready.store(false);ba_local::accepting.store(false);
    state.phase=Phase::Failed;
    ba_match_loading::error(state.loadingTicket,"Practice could not start.");
    state.loadingTicket=0;
    ba::log("Practice stopped in %s: %s; retaining native objects until safe cleanup",where,error.what());
}
static uint64_t humanId() {
    return ba::get<uint64_t>(ba::get<Obj>(ba::get<Obj>(state.human->get(),"playerHandleWithName_"),"playerHandle_"),"steamId_");
}
static void start(Obj front,Obj controller) {
    if(!ba::localMenu() && !ba::flag(L"-practice-ai-experimental")) {ba::log("Try Deck vs AI is not enabled in this build's normal launcher");return;}
    if(active()){ba::log("Practice already pending or active; duplicate start ignored");return;}
    if(ba::localMenu())
        require(ba_local_menu::ready(front),"local practice menu is not ready");
    else require(ba::community() && ba_community_native::owns(front) && ba_community_native::installed &&
        ba_community::online && !ba_lan::stopped,"practice requires a healthy community presence");
    require(ba_dedicated_session::inMenu() && ba_dedicated_session::worldIdle(ba::read<Obj>(front,0xd8)) &&
        !ba_dedicated_session::joined && ba_community_native::authority.phase==wire::None &&
        ba_community_native::requests.empty() && ba_community_invites::operations.empty() &&
        !ba::get<Obj>(front,"_party") && ba_lan::bootstrap.empty(),"leave multiplayer before starting practice");
    require(ba_dedicated_deck::canReady(front),"practice selected deck is not valid");
    if(ba::unified())ba_client::prepareLocal(front);
    state.difficultyProfile=ba::localMenu()?ba_practice_settings::selection():
        ba_practice_settings::profile(ba::argument(L"-practice-ai-profile=","17"));
    // Shipped Easy17 has no tactical group rules and failed movement acceptance.
    // Offline Easy uses the working Normal tactics plus Easy's authored strength.
    state.aiProfile=ba::localMenu() && state.difficultyProfile==17?18:state.difficultyProfile;
    root(state.front,front);root(state.controller,controller);
    root(state.human,ba::get<Obj>(front,"_playerGameHandle"));
    root(state.humanDeck,ba_dedicated_deck::selectedProto(front));
    unsigned char random[16];require(BCryptGenRandom(nullptr,random,sizeof(random),BCRYPT_USE_SYSTEM_PREFERRED_RNG)>=0,"practice match identity generation failed");
    static const char hex[]="0123456789abcdef";state.match.clear();
    for(unsigned char byte:random){state.match+=hex[byte>>4];state.match+=hex[byte&15];}++generations;
    state.began=GetTickCount64();
    if(ba::unified())state.worldLease=ba_client::acquireLocal(front);
    if(ba::localMenu())state.phase=Phase::Building;
    else {
        state.phase=Phase::Reserving;
        state.request=ba_community::send(wire::practice(ba_community::nextRequest(),true));
    }
    state.loadingTicket=ba_match_loading::begin(ba_match_loading::Source::Practice,state.match,ba_match_loading::Stage::Preparing);
    ba::log("Practice requested: match=%s mode=4 selectedDeckSnapshot=1 standalone=%d",state.match.c_str(),ba::localMenu()?1:0);
    ba::log("Practice difficulty snapshot: selected=%s modifierProfile=%u tuningProfile=%u",ba_practice_settings::name(state.difficultyProfile),state.difficultyProfile,state.aiProfile);
}
static bool acknowledge(Obj front,const wire::Ack& ack) {
    if(ack.kind!=wire::Practice)return false;
    require(active() && state.front && state.front->get()==front && ack.request==state.request,"unexpected practice acknowledgement");
    state.request=0;
    if(state.phase==Phase::Reserving) {
        if(!ack.success){
            ba_match_loading::error(state.loadingTicket,"Practice is unavailable. Leave multiplayer and try again.");
            ba::log("Practice reservation rejected: %s",ack.reason.c_str());state=State{};return true;
        }
        state.reserved=true;state.phase=Phase::Building;
    } else {
        require(state.phase==Phase::Returning && ack.success,"practice availability return rejected");
        ++completed;ba::log("Practice returned: completed=%u mode=4 seat=%d presenceRetained=1",completed,ba::lanSlot());
        state=State{};
    }
    return true;
}
static void build() {
    require(state.phase==Phase::Building && !state.buildStarted,"practice duplicate map builder");
    require(ba::localMenu() || !ba_lan::stopped,"practice presence lost before creation");
    if(!characterTableReady())return;
    state.buildStarted=true;
    Obj method=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(ba::find_class("Uncapped.UI","IGameSettingController"),"GetConfigForMode",1);
    method=ba::api<Obj(*)(Obj,Obj)>("il2cpp_object_get_virtual_method")(state.controller->get(),method);
    int mode=4;void* modeArgs[]={&mode};Root config(ba_local::invokeMethod(method,state.controller->get(),modeArgs));
    need(config.get(),"practice mode config unavailable");
    root(state.botDeck,aiDeck());
    Root bot(ba_lan_bootstrap::playerLan(1));ba::set<uint32_t>(bot.get(),"aiProfileId_",profileId());
    Obj named=ba::get<Obj>(bot.get(),"playerHandleWithName_");
    ba::set<Obj>(named,"playerName_",ba::str("Practice AI"));ba::set<Obj>(named,"filteredName_",ba::str("Practice AI"));
    root(state.bot,bot.get());require(humanId()!=2,"practice human and AI identity collision");
    Root army(ba::make("GamePb","ArmyConfig"));ba::set<uint32_t>(army.get(),"armyId_",1);ba::set<uint32_t>(army.get(),"allianceId_",1);
    ba::set<Obj>(army.get(),"deck_",state.botDeck->get());ba_local::addItem(ba::get<Obj>(army.get(),"players_"),state.bot->get());
    Root list(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(ba::find_class("GamePb","ArmyConfig"),1));
    ba::api<void(*)(Obj,void**,Obj)>("il2cpp_gc_wbarrier_set_field")(list.get(),reinterpret_cast<void**>(static_cast<char*>(list.get())+0x20),army.get());
    if(ba_bootstrap::frontRoot)ba::api<void(*)(uint32_t)>("il2cpp_gchandle_free")(ba_bootstrap::frontRoot);
    ba_bootstrap::frontRoot=ba::api<uint32_t(*)(Obj,bool)>("il2cpp_gchandle_new")(state.front->get(),false);
    ba_bootstrap::bootstrapThread=GetCurrentThreadId();ba_bootstrap::creating=true;ba_bootstrap::awaitingWorld=false;
    void* args[]={config.get(),list.get()};ba::call(state.front->get(),"CreateDebugAIGame",2,args);
    ba::log("Practice original CreateDebugAIGame requested: selectedHumanDeckSnapshot=1");
}
static void consume(Obj front,Obj request,Obj data) {
    require(state.phase==Phase::Building && state.buildStarted && front==state.front->get(),"practice create callback ownership");
    require(ba::get<Obj>(request,"gameData_")==data,"practice request data changed");
    Obj config=need(ba::get<Obj>(data,"gameConfig_"),"practice static config missing");
    require(ba::get<int>(config,"gameMode_")==4,"practice builder changed mode");
    applyDifficultyModifiers(config);
    Obj armies=ba::get<Obj>(config,"armies_");
    require(ba_local::count(armies)==2,"practice primary map must have two armies");
    for(int index=0;index<2;++index) {
        Obj army=ba_bootstrap::item(armies,index);
        require(ba::get<uint32_t>(army,"armyId_")==static_cast<uint32_t>(index),"practice army order mismatch");
        Obj players=ba::get<Obj>(army,"players_");ba::call(players,"Clear");
        ba_local::addItem(players,index?state.bot->get():state.human->get());
        ba::set<uint32_t>(army,"allianceId_",index);
        ba::set<Obj>(army,"deck_",index?state.botDeck->get():state.humanDeck->get());
        if(ba::flag(L"-practice-ai-smoke"))
            ba::log("Practice army snapshot: %s",ba_catalog::utf8(ba::call(army,"ToString")).substr(0,16384).c_str());
    }
    Obj local=need(ba::get<Obj>(front,"<ClientConfig>k__BackingField"),"practice client config missing");
    for(const auto& entry:std::array<std::pair<const char*,const char*>,3>{{
        {"versionBuild_","clientBuild_"},{"versionConfig_","gameApiVersion_"},{"dllProfile_","dllProfile_"}}})
        ba::set<Obj>(config,entry.first,ba::get<Obj>(local,entry.second));
    ba::set<Obj>(server(),"<ClientConfig>k__BackingField",local);
    if(ba::flag(L"-practice-ai-smoke"))ba_lan_smoke::prepare(data,0);
    root(state.encoded,ba_bootstrap::encodeGameData(data));state.phase=Phase::Loading;
    ba_match_loading::advance(state.loadingTicket,ba_match_loading::Stage::Loading);
    ba::log("Practice map ready: mode=4 armies=2 humanProfile=0 aiProfile=%u selectedHumanDeck=1 primaryMap=1",profileId());
    ba_bootstrap::beginJoined(front,state.encoded->get(),state.human->get(),false,state.match.c_str());
}
static bool assetsReady(Obj gameServer) {
    require(state.phase==Phase::Loading && gameServer==server(),"practice asset readiness ownership");
    return state.humanReady;
}
static void worldReady(Obj gameServer) {
    require(state.phase==Phase::Loading && gameServer==server(),"practice world readiness ownership");
    require(state.humanReady,"practice human ready signal missing");state.phase=Phase::Running;
    ba_match_loading::advance(state.loadingTicket,ba_match_loading::Stage::Starting);
    ba::log("Practice world ready: humanWorld=%llu aiWorld=%llu",ba::read<uint64_t>(ba::read<Obj>(gameServer,0x140),0x1a8),ba::get<uint64_t>(manager(),"_aiWorld"));
}
static void captureAIJoin(Obj ai,Obj connection,bool spectator) {
    require(state.aiStarted && state.phase==Phase::Running && !state.ai && !spectator &&
        GetCurrentThreadId()==ba_dedicated_session::unityThread && ai!=server() &&
        ba::get<Obj>(ai,"_playerGameHandle")==state.bot->get() && !ba::read<Obj>(ai,0x140),"practice AI join ownership");
    require(ba_catalog::utf8(ba::get<Obj>(ba::get<Obj>(connection,"gameHandle_"),"gameName_"))==state.match,"practice AI join identity");
    root(state.ai,ai);Root cloned(ba::call(connection,"Clone"));
    ba::set<Obj>(ai,"_currentConnectionInfo",cloned.get());
    Obj selector=need(ba::get<Obj>(ai,"_deckSelector"),"practice AI selector missing");
    require(ba::klass(selector)==ba::find_class("Uncapped","LocalAIDeckSelector"),"practice AI selector ownership mismatch");
    void* fromArgs[]={state.botDeck->get()};Root deck(ba::invoke(ba::find_class("Uncapped","Deck"),nullptr,"FromProto",1,fromArgs));
    void* selectArgs[]={deck.get()};ba::call(selector,"set_SelectedDeck",1,selectArgs);
    ba_local::attachPeer(ai);state.joinPending=true;
    ba::log("Practice AI join captured: separateService=1 sharedWorld=1 networkJoin=0");
}
static void addAI() {
    require(!state.aiStarted,"practice AI already requested");state.aiStarted=true;
    require(ba_local::count(ba::get<Obj>(manager(),"_aiPlayers"))==0,"practice AI manager is not empty");
    Obj sim=ba::read<Obj>(server(),0x140);
    require(sim && ba::get<Obj>(manager(),"_playerSimulation")==sim,"practice AI manager simulation mismatch");
    // RequestAIWithProfile -> OnAddAI reads the obsolete transport's address
    // and port. Its AddLocalAI callee accepts the connection explicitly.
    // Preserve the original DLL type3/profile identity and native AI lifecycle.
    Root address(ba::str("offline")),port(ba::str("0")),name(ba::str(state.match.c_str()));
    uint32_t army=1,sequence=1;int type=3;
    void* args[]={state.bot->get(),address.get(),port.get(),name.get(),sim,nullptr,nullptr,&type,&army,&sequence};
    state.aiRequestedAt=GetTickCount64();
    state.adding=true;
    try {Root process(ba::call(manager(),"AddLocalAI",10,args));need(process.get(),"practice native AI process not created");}
    catch(...){state.adding=false;throw;}
    state.adding=false;
    ba::log("Practice native AI requested: profile=%u army=1 processes=%d",profileId(),ba_local::count(ba::get<Obj>(manager(),"_aiPlayers")));
}
static void deliverAIJoin() {
    require(state.ai && state.joinPending,"practice AI response without request");
    Obj players=ba::get<Obj>(manager(),"_aiPlayers");Obj selected=nullptr;
    for(int index=0;index<ba_local::count(players);++index) {
        Obj process=ba_bootstrap::item(players,index),game=ba::get<Obj>(process,"_game");
        Obj services=game?ba::get<Obj>(game,"_serverManager"):nullptr;
        if(services && ba::get<Obj>(services,"<GameServer>k__BackingField")==state.ai->get()) {
            require(!selected && ba::get<Obj>(game,"_playerSimReference")==ba::read<Obj>(server(),0x140) &&
                ba::get<uint32_t>(process,"_requestedAsArmyId")==1,"practice AI process membership mismatch");selected=process;
        }
    }
    root(state.process,need(selected,"practice AI joining process disappeared"));
    Obj ai=state.ai->get();require(!ba::read<Obj>(ai,0x140),"practice AI tried to own simulation");
    ba::set<Obj>(ai,"<ClientConfig>k__BackingField",ba::get<Obj>(server(),"<ClientConfig>k__BackingField"));
    Obj conn=ba::get<Obj>(ai,"_currentConnectionInfo"),handle=ba::get<Obj>(conn,"gameHandle_");
    Root response(ba::make("GamePb","JoinedGame"));
    ba::set<Obj>(response.get(),"gameHandle_",handle);ba::set<Obj>(response.get(),"playerHandle_",state.bot->get());
    ba::set<Obj>(response.get(),"gameDataEncoded_",state.encoded->get());ba::set<Obj>(response.get(),"gameConnectionInfo_",conn);
    ba::set<int>(response.get(),"serverState_",0);
    int error=0;void* args[]={&error,response.get()};ba::call(ai,"ProcessJoinedGame",2,args);
    require(state.botReady,"practice AI ready signal missing");
    Root started(ba::make("GamePb","GameStarted"));ba::set<Obj>(started.get(),"gameHandle_",handle);
    ba::set<int>(started.get(),"serverState_",1);void* startArgs[]={started.get()};ba::call(ai,"ProcessGameStarted",1,startArgs);
    state.joinPending=false;
    OfflineSetLocalReady(true);
    ba::log("Practice AI JoinedGame delivered: nativeJoinArmy=1 simulationOwner=0");
}
static bool signalReady(Obj gameServer) {
    if(!active())return false;
    if(gameServer==server()) {
        require(!state.humanReady,"practice duplicate human readiness");state.humanReady=true;
        ba::log("Practice native human asset-ready callback received");return true;
    }
    if(state.ai && gameServer==state.ai->get()) {
        require(!state.botReady,"practice duplicate AI readiness");state.botReady=true;
        ba::log("Practice native AI ready callback received");return true;
    }
    return false;
}
static void input(Obj gameServer,Obj action) {
    const bool bot=state.ai && gameServer==state.ai->get();
    require(bot || gameServer==server(),"practice input from unrelated service");
    Root join(ba::call(action,"get_JoinArmy"));if(!join.get())return;
    bool& joined=bot?state.botJoined:state.humanJoined;
    require(!joined,"practice duplicate JoinArmy");
    const uint32_t army=ba::get<uint32_t>(join.get(),"armyId_"),expected=bot?1:0;
    require(army==31 || army==expected,"practice JoinArmy assigned wrong army");
    Obj deck=need(ba::get<Obj>(join.get(),"deck_"),"practice native JoinArmy deck missing");
    Obj frozen=bot?state.botDeck->get():state.humanDeck->get();
    if(ba::flag(L"-practice-ai-smoke"))
        ba::log("Practice original JoinArmy: %s",ba_catalog::utf8(ba::call(join.get(),"ToString")).substr(0,16384).c_str());
    for(const char* field:{"units_","activeAbilityGroups_"}) {
        Obj actual=ba::get<Obj>(deck,field),wanted=ba::get<Obj>(frozen,field);
        require(ba_local::count(actual)==ba_local::count(wanted),"practice native deck length differs from snapshot");
        for(int i=0;i<ba_local::count(wanted);++i)
            require(ba_lan_bootstrap::uintAt(actual,i)==ba_lan_bootstrap::uintAt(wanted,i),"practice native deck differs from snapshot");
    }
    ba::set<uint32_t>(join.get(),"armyId_",expected);ba::set<Obj>(join.get(),"deck_",frozen);joined=true;
    ba::log("Practice native JoinArmy validated: army=%u selectedUnits=8 abilities=4 exactSnapshot=1",expected);
}
static Obj completionListener(Obj gameServer,Obj data) {
    Root event(ba::get<Obj>(gameServer,"OnEndOfGameResponse"));if(!event.get())return nullptr;
    Root listeners(ba::call(event.get(),"GetInvocationList"));
    const auto count=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(listeners.get());
    require(count<=128,"practice completion listener capacity");Obj found=nullptr;
    for(size_t i=0;i<count;++i) {
        Obj entry=ba::read<Obj>(listeners.get(),0x20+i*sizeof(Obj));Root target(ba::call(entry,"get_Target"));
        if(!target.get() || ba::klass(target.get())!=ba::find_class("Uncapped.UI","UIGameCompletedContent"))continue;
        Root method(ba::call(entry,"get_Method"));
        require(ba_catalog::utf8(ba::call(method.get(),"get_Name"))=="HandleEndOfGameResponse","practice unexpected completion handler");
        require(!found && ba::get<bool>(target.get(),"_isInitialized") &&
            ba::get<Obj>(target.get(),"_simulation")==ba::read<Obj>(gameServer,0x140) &&
            ba::get<Obj>(target.get(),"_serviceManager")==ba::get<Obj>(ba::owner,"<ServiceManager>k__BackingField") &&
            ba::get<Obj>(target.get(),"_matchData")==data && !ba::get<bool>(target.get(),"_endGameResponseReceived") &&
            ba::get<int>(target.get(),"_shutdownReason")==0,"practice stale/duplicate completion content");
        found=target.get();
    }
    return found;
}
static int smokeFrames() {
    static const int frames=[](){
        const auto value=ba::argument(L"-practice-ai-smoke-frames=");if(value.empty())return 1200;
        size_t consumed=0;int result=std::stoi(value,&consumed);
        require(consumed==value.size() && result>=1200 && result<=3600,"practice smoke frame limit invalid");return result;
    }();return frames;
}
static bool gameUpdate(Obj gameServer,Obj method) {
    if(!active())return false;
    if(gameServer!=server())return state.ai && gameServer==state.ai->get();
    if(state.phase==Phase::Failed)return true;
    try {
        if(state.phase==Phase::Loading)require(GetTickCount64()-state.began<60000,"practice world/assets readiness deadline");
        ba_bootstrap::poll(gameServer);
        if(state.phase==Phase::Running) {
            if(!state.aiStarted)addAI();
            else if(state.joinPending)deliverAIJoin();
            if(!state.botJoined)require(GetTickCount64()-state.aiRequestedAt<30000,"practice AI joining deadline");
            if(ba::flag(L"-practice-ai-smoke") && ba::flag(L"-lan-smoke"))
                ba_lan_smoke::enqueue(gameServer,ba_local::lastSubmittedFrame+1);
            OfflineGameUpdate(gameServer,method);
            if(ba_local::failed.load())throw std::runtime_error("practice input loop failed");
            // World creation precedes the AI join and native UI loading. Keep
            // feedback until both players can run and the original FSM is InGame.
            if(state.loadingTicket && state.humanReady && state.botReady && state.humanJoined &&
               state.botJoined && !state.joinPending && ba_local::ready.load() && ba_dedicated::loadingInGame()) {
                ba::log("Match loading readiness: source=practice ticket=%llu nativeInGame=1 botReady=1 joinDelivered=1 localReady=1 humanJoined=1 botJoined=1 match=%s",
                    static_cast<unsigned long long>(state.loadingTicket),state.match.c_str());
                ba_match_loading::success(state.loadingTicket);state.loadingTicket=0;
            }
            Obj sim=ba::read<Obj>(gameServer,0x140);
            if(ba::flag(L"-practice-ai-smoke") && state.process && GetTickCount64()-state.diagnostic>=10000) {
                state.diagnostic=GetTickCount64();Root paused(ba::call(manager(),"GetAnyAIPaused"));
                ba::log("Practice AI cadence: sim=%d aiUpdated=%d hasDll=%d anyPaused=%d simFlag1b0=%d joining=%d humanStep=%.6f aiStep=%.6f",
                    ba::read<int>(sim,0xa8),ba::get<int>(manager(),"_lastUpdatedFrame"),ba::get<bool>(manager(),"_hasDllAI")?1:0,
                    boolean(paused.get())?1:0,ba::read<bool>(sim,0x1b0)?1:0,ba::get<int>(state.process->get(),"_joiningStatus"),
                    ba::native<float(*)(Obj,Obj)>(0x3e4fa20)(gameServer,nullptr),ba::native<float(*)(Obj,Obj)>(0x3e4fa20)(state.ai->get(),nullptr));
                uint32_t army=1;void* profileArgs[]={&army};Root effective(ba::call(manager(),"ActiveAIProfile",1,profileArgs));
                if(effective.get()) {
                    Root tuning(ba::get<Obj>(effective.get(),"AIFuzzyTuning"));
                    ba::log("Practice effective AI profile: id=%u expectedTableEntry=%d name=%s tuning=%s",
                        ba::get<uint32_t>(effective.get(),"_id"),effective.get()==tableElement("AIProfileTable",profileId())?1:0,
                        ba_catalog::utf8(ba::get<Obj>(effective.get(),"Name")).c_str(),
                        tuning.get()?ba_catalog::utf8(ba::call(tuning.get(),"get_name")).c_str():"null");
                }
                ba_audit::practiceAIView(state.process->get(),ba::read<int>(sim,0xa8));
            }
            if(ba::flag(L"-practice-ai-smoke") && !state.conceded && ba::read<int>(sim,0xa8)>=smokeFrames()) {
                state.conceded=true;ba::call(sim,"ConcedeGame");ba::log("PRACTICE SMOKE native ConcedeGame (automated)");
            }
            Obj data=ba::call(ba::owner,"get_MatchDataManager"),info=ba::get<Obj>(data,"_matchInfo");
            if(info && ba::get<bool>(info,"MatchCompleted")) {
                require(ba::get<int>(info,"GameMode")==4,"practice result mode mismatch");
                if(!state.completionInfo) {
                    root(state.completionInfo,info);state.completionAt=GetTickCount64();ba_local::ready.store(false);return true;
                }
                require(info==state.completionInfo->get(),"practice completed match changed before result");
                require(GetTickCount64()-state.completionAt<5000,"practice completion UI subscriber deadline");
                Obj listener=completionListener(gameServer,data);if(!listener)return true;
                if(!state.completionUI){root(state.completionUI,listener);return true;}
                require(listener==state.completionUI->get(),"practice completion UI changed before result");
                ba_local::ready.store(false);state.result=true;state.phase=Phase::Result;
                ba_dedicated_results::endResponse(gameServer,info,0,humanId(),ba::get<uint32_t>(info,"WinningAllianceId"),false);
            }
        }
    }catch(const std::exception& e){fail("game update",e);}
    return true;
}
static void release() {
    require(ba_dedicated_session::inMenu() && ba_dedicated_session::worldIdle(server()) &&
        !ba::get<uint64_t>(manager(),"_aiWorld") && !ba_local::count(ba::get<Obj>(manager(),"_aiPlayers")),"practice native shutdown not complete");
    ba_local::ready.store(false);ba_local::accepting.store(false);
    {
        ba_local::QueueLock lock;
        for(Obj producer:{server(),state.ai?state.ai->get():nullptr})if(producer)
            for(size_t offset:{size_t(0x180),size_t(0x188)}) {
                Obj queue=ba::read<Obj>(producer,offset);if(queue)ba::call(queue,"Clear");
            }
    }
    if(ba_local::peerRoot)ba_local::detachPeer();
    state.process.reset();state.ai.reset();
    ba_dedicated_session::releaseRoot(ba_local::serverRoot);
    ba_local::failed.store(false);ba_local::updateThread=0;ba_local::previousTime=0;
    ba_local::submittedTicks=0;ba_local::lastSubmittedFrame=-1;ba_local::accumulatedMs=0;
    ba_bootstrap::awaitingWorld=false;ba_bootstrap::creating=false;
    ba_dedicated_session::releaseRoot(ba_bootstrap::frontRoot);ba_bootstrap::bootstrapThread=0;
    // This boundary proves actual native shutdown; requesting a menu transition
    // alone must not pretend that an outstanding async load has been cancelled.
    ba_match_loading::cancel(state.loadingTicket,"practice returned to menu");state.loadingTicket=0;
    if(ba::localMenu()) {
        if(ba::unified())ba_client::releaseLocal(state.front->get(),state.worldLease);
        ++completed;ba::log("Practice returned: completed=%u mode=4 seat=-1 presenceRetained=0 standalone=1",completed);
        state=State{};return;
    }
    if(ba_lan::stopped) {
        ba::log("Practice native shutdown complete; disconnected presence recovery deferred to menu");
        state=State{};return;
    }
    state.phase=Phase::Returning;
    state.request=ba_community::send(wire::practice(ba_community::nextRequest(),false));
}
static bool frontUpdate(Obj front) {
    if(!active())return false;
    try {
        require(state.front && state.front->get()==front,"practice front ownership");
        if(!ba::localMenu() && !ba_lan::stopped) {
            try{ba_lan::poll();ba_community_native::update(front);}
            catch(const std::exception& e){ba_lan::fail("practice presence",e);}
        }
        if(!active())return true;
        if(state.phase==Phase::Building && !state.buildStarted)build();
        if((state.phase==Phase::Running || state.phase==Phase::Failed) && !ba_bootstrap::creating &&
           !ba_bootstrap::awaitingWorld && ba_dedicated_session::inMenu() && ba_dedicated_session::worldIdle(server()) &&
           !ba::get<uint64_t>(manager(),"_aiWorld") && !ba_local::count(ba::get<Obj>(manager(),"_aiPlayers"))) {
            release();return true;
        }
        if(state.phase==Phase::Result) {
            if(!state.modalReleased && ba_dedicated_session::worldIdle(server())) {
                Root login(ba_dedicated_session::loginController(front,server()));
                if(login.get() && ba::get<Obj>(login.get(),"_activeShowUIObject")==ba::get<Obj>(login.get(),"_disconnectedModal")) {
                    state.modalReleased=true;ba::call(login.get(),"HideReconnectUI");
                }
            }
            if(ba_dedicated_session::inMenu() && ba_dedicated_session::worldIdle(server()))release();
            else if(ba::flag(L"-practice-ai-smoke") && !state.continued && state.result && ba_dedicated_session::worldIdle(server())) {
                Obj controller=ba::get<Obj>(ba::owner,"<UIPostGameController>k__BackingField");
                Obj result=controller?ba::get<Obj>(controller,"_matchResultState"):nullptr;
                Obj fsm=controller?ba::get<Obj>(controller,"_fsm"):nullptr;
                if(result && fsm && ba::get<Obj>(fsm,"_currentState")==result) {
                    Obj vm=ba::get<Obj>(result,"_matchResultVM"),nav=vm?ba::get<Obj>(vm,"_navigationStack"):nullptr;
                    if(nav && !ba_local::count(ba::get<Obj>(nav,"_navigationStack"))) {
                        state.continued=true;ba::call(vm,"OnContinue");ba::log("PRACTICE SMOKE native Continue (automated)");
                    }
                }
            }
        }
    }catch(const std::exception& e){fail("front update",e);}
    return true;
}
static void smoke(Obj front) {
    const unsigned matches=ba::argument(L"-practice-ai-smoke-matches=","1")=="2"?2u:1u;
    if(!ba::flag(L"-practice-ai-smoke") || active() || completed>=matches ||
       !(ba::localMenu()?ba_local_menu::ready(front):ba_community_native::installed))return;
    if(ba::unified() && !ba_client::allowPracticeSmoke())return;
    static ULONGLONG at=0;static bool opened=false,clicked=false;static unsigned round=0;
    if(round!=completed) {
        round=completed;at=0;opened=false;clicked=false;
        if(ba::flag(L"-practice-ai-deck-smoke"))ba_dedicated_deck::rematchSmokeSelection(front);
    }
    if(!at) {
        const unsigned delay=std::stoul(ba::argument(L"-practice-ai-smoke-delay-ms=","3000"));
        require(delay>=3000 && delay<=60000,"practice smoke idle delay outside bounds");
        at=GetTickCount64()+delay;return;
    }
    if(GetTickCount64()<at || clicked)return;
    require(GetTickCount64()-at<30000,"practice native Edit Deck availability deadline");
    require(ba_dedicated_session::inMenu() && ba_dedicated_session::worldIdle(ba::read<Obj>(front,0xd8)),"practice smoke requires idle menu");
    Root menu(ba::get<Obj>(ba::owner,"<UIMenuController>k__BackingField"));
    Root flow(ba::get<Obj>(need(menu.get(),"practice menu controller missing"),"_menuFlowGraph"));
    require(flow.get() && ba::klass(flow.get())==ba::find_class("Uncapped.UI","MenuFlowController") &&
        ba::get<Obj>(ba::owner,"_menuFlowController")==flow.get(),"practice menu flow ownership mismatch");
    if(!opened) {
        Root link(ba::make("Uncapped.UI","UILink"));ba::set<int>(link.get(),"PrefabKey",3);
        ba::native<void(*)(Obj,Obj,Obj)>(0x3d52440)(flow.get(),link.get(),nullptr);opened=true;
        ba::log("PRACTICE SMOKE native menu TravelToScreen EditDeck key=3 (automated)");return;
    }
    Root graph(ba::get<Obj>(flow.get(),"_flowGraph"));Root node(ba::get<Obj>(graph.get(),"ActiveNode"));
    if(!node.get() || ba::klass(node.get())!=ba::find_class("Uncapped.UI","ShowUIObjectNode"))return;
    Root descriptors(ba::get<Obj>(node.get(),"ShowUIObject")),views(ba::get<Obj>(node.get(),"_uiObject"));
    if(!descriptors.get() || !views.get())return;
    const auto count=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(descriptors.get());
    require(count<=32,"practice menu descriptor capacity");
    if(ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(views.get())!=count)return;
    Obj found=nullptr;
    for(size_t i=0;i<count;++i) {
        Obj descriptor=ba::read<Obj>(descriptors.get(),0x20+i*sizeof(Obj));
        if(!descriptor || ba::get<int>(descriptor,"_prefabKey")!=3)continue;
        require(!found,"practice duplicate acquired editor");found=ba::read<Obj>(views.get(),0x20+i*sizeof(Obj));
    }
    Root view(found);if(!view.get() || !ba::read<Obj>(view.get(),0x10) || !ba::get<bool>(view.get(),"_isInitialized"))return;
    require(ba::klass(view.get())==ba::find_class("Uncapped.UI","EditDeckVM"),"practice acquired editor class mismatch");
    Root owner(ba::get<Obj>(view.get(),"<Owner>k__BackingField"));if(!owner.get())return;
    require(ba::get<bool>(owner.get(),"<IsInitialized>k__BackingField") &&
        ba::get<int>(owner.get(),"<PrefabType>k__BackingField")==3 &&
        ba::get<Obj>(owner.get(),"<Root>k__BackingField")==view.get() &&
        ba::get<Obj>(owner.get(),"_pool")==ba::get<Obj>(node.get(),"_pool"),"practice editor lifetime owner mismatch");
    Obj container=ba::get<Obj>(owner.get(),"_uiContainer");if(!container || !ba::native<bool(*)(Obj,Obj)>(0x88a350)(container,nullptr))return;
    Root go(ba::native<Obj(*)(Obj,Obj)>(0x6ec1a0)(view.get(),nullptr));
    if(!ba::native<bool(*)(Obj,Obj)>(0x508a650)(go.get(),nullptr))return;
    Root type(ba_community_roster::reflectedType("Uncapped.UI","MatchVSAIButtonVM"));
    Root children(ba::native<Obj(*)(Obj,Obj,bool,Obj)>(0x5089c40)(go.get(),type.get(),true,nullptr));
    const auto childrenCount=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(children.get());
    require(childrenCount<=16,"practice button capacity");Obj button=nullptr;
    for(size_t i=0;i<childrenCount;++i) {
        Obj candidate=ba::read<Obj>(children.get(),0x20+i*sizeof(Obj));
        if(ba::get<int>(candidate,"_gameModeSelection")!=4)continue;
        require(!button,"practice duplicate mode4 button");button=candidate;
    }
    Root vm(button);if(!vm.get() || !ba::get<bool>(vm.get(),"_isInitialized") ||
        !ba::native<bool(*)(Obj,Obj)>(0x5084710)(vm.get(),nullptr))return;
    require(ba::get<Obj>(vm.get(),"<Owner>k__BackingField")==owner.get() &&
        ba::get<Obj>(vm.get(),"_serviceManager")==ba::get<Obj>(ba::owner,"<ServiceManager>k__BackingField") &&
        ba::get<Obj>(vm.get(),"_gameSettingController")==ba::owner,"practice button injection mismatch");
    Root bindings(ba::get<Obj>(vm.get(),"_bindings"));if(!bindings.get() || !ba::get<bool>(bindings.get(),"_initialized"))return;
    Root buttonType(ba_community_roster::reflectedType("Doozy.Runtime.UIManager.Components","UIButton"));
    Root control(ba::native<Obj(*)(Obj,Obj,Obj)>(0x50856a0)(vm.get(),buttonType.get(),nullptr));
    if(!control.get() || !ba::native<bool(*)(Obj,Obj)>(0x5084710)(control.get(),nullptr) ||
        !ba::native<bool(*)(Obj,Obj)>(0x53af310)(control.get(),nullptr))return;
    require(ba::get<Obj>(graph.get(),"ActiveNode")==node.get(),"practice editor changed before callback");
    ba::native<void(*)(Obj,Obj)>(0x3d25e20)(vm.get(),nullptr);clicked=true;
    require(active(),"practice original button did not start local reservation");
    ba::log("PRACTICE SMOKE original EditDeck mode4 callback: owned=1 visible=1 interactable=1 preamble=1 (automated; not mouse input)");
}
static void releaseOfflineIdleDisconnect(Obj front) {
    // The original login controller watches the deliberately disconnected front
    // service. Cancel only its owned legacy disconnect UI, once per idle return.
    // In particular, cancel its delayed coroutine even before a modal appears.
    Obj game=ba::read<Obj>(front,0xd8);
    if(!ba_local_menu::ready(front) || active() || !ba_dedicated_session::inMenu() ||
       !ba_dedicated_session::worldIdle(game) || ba::read<bool>(ba::owner,0x280))return;
    static unsigned generation=0,checks=0,observations=0;
    static bool attempted=false;
    static ULONGLONG checkAt=0,observationAt=0;
    if(generation!=completed) {
        generation=completed;checks=observations=0;attempted=false;checkAt=observationAt=0;
    }
    const ULONGLONG now=GetTickCount64();
    if(attempted) {
        if(!ba::flag(L"-practice-ai-smoke") || observations>=6 || now<observationAt)return;
        observationAt=now+5000;++observations;
        Root controller(ba_dedicated_session::loginController(front,game));
        require(controller.get()!=nullptr,"offline idle login owner disappeared");
        Obj activeDescriptor=ba::get<Obj>(controller.get(),"_activeShowUIObject");
        Obj modal=ba::get<Obj>(controller.get(),"_activeModal");
        ba::log("Practice offline idle observation: generation=%u sample=%u clear=%d activeShow=%p modal=%p worldIdle=1",
            generation,observations,(!activeDescriptor && !modal)?1:0,activeDescriptor,modal);
        return;
    }
    if(checks>=120 || now<checkAt)return;
    checkAt=now+250;++checks;
    Root controller(ba_dedicated_session::loginController(front,game));if(!controller.get())return;
    if(ba::get<bool>(controller.get(),"_isTrackingGameConnection") ||
       ba::read<int>(front,0x118)!=0 || ba::read<Obj>(front,0x20) || ba::read<bool>(front,0x38))return;
    Obj descriptor=ba::get<Obj>(controller.get(),"_disconnectedModal");
    Obj activeDescriptor=ba::get<Obj>(controller.get(),"_activeShowUIObject");
    Obj modal=ba::get<Obj>(controller.get(),"_activeModal");
    if(!((descriptor && activeDescriptor==descriptor) || (!activeDescriptor && !modal)))return;
    attempted=true; // Never repeat a partially failed native destruction.
    ba::log("Practice offline idle disconnect release: generation=%u frontStatus=0 originalChannel=null tracking=0 activeShow=%p modal=%p; one original HideReconnectUI call",
        generation,activeDescriptor,modal);
    ba::call(controller.get(),"HideReconnectUI");
    observationAt=now+5000;
}
static void offlineUpdate(Obj front) {
    if(!ba::offlinePractice() || !ba_local_menu::ensure(front))return;
    try {
        static bool logged=false;
        if(!logged){logged=true;ba::log("Offline practice menu ready: native local deck storage; no community or LAN transport; BA_RESURRECTION_OFFLINE_PRACTICE_V1");}
        if(frontUpdate(front))return;
        releaseOfflineIdleDisconnect(front);
        ba_practice_settings_ui::update(front);
        if(!ba::flag(L"-practice-settings-smoke") || ba_practice_settings_ui::smokeComplete())smoke(front);
    }catch(const std::exception& e){
        if(active())fail("offline menu",e);
        else ba::log("Offline practice menu failed: %s",e.what());
    }
}
}
extern "C" __declspec(dllexport) void OfflinePracticeAIJoin(void* ai,void* connection,bool spectator,void* method) {
    ba::init();
    if(!ba_practice::active() || !ba_practice::state.bot || !ai ||
       ba::get<ba::Obj>(ai,"_playerGameHandle")!=ba_practice::state.bot->get()) {
        ba::native<void(*)(void*,void*,bool,void*)>(0x3e53940)(ai,connection,spectator,method);return;
    }
    try{ba_practice::captureAIJoin(ai,connection,spectator);}
    catch(const std::exception& e){ba_practice::fail("AI join",e);}
}
