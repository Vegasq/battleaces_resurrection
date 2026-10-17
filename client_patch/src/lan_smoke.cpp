#pragma once
// Optional normal-gameplay smoke test; include after local_loop.cpp and before
// lan_transport.cpp. No shared config edits, debug flags, or resource grants.
// Evidence (ORIGINAL GameAssembly.dll): ../network/ai-buildunit.asm,
// ai-build-command.asm, smoke-runtime-types.json, smoke-proto-ability.json.
// prepare(gameData,slot) runs before JoinArmy; enqueue(server,frame) runs on the
// main thread immediately BEFORE the ordinary transport drains ICommand.
namespace ba_lan_smoke {
using ba::Obj;
using ba_local::Root;
struct Plan { bool ready=false,attempted=false;int slot=-1;uint32_t key=0,unit=0; };
static Plan plan;
static Obj require(Obj object,const char* message) { if(!object)throw std::runtime_error(message);return object; }
static Obj item(Obj list,int index) {
    void* args[]={&index};return ba::call(require(list,"smoke list missing"),"get_Item",1,args);
}
static uint32_t unitAt(Obj list,int index) {
    Root boxed(item(list,index));return *ba::api<uint32_t*(*)(Obj)>("il2cpp_object_unbox")(require(boxed.get(),"smoke unit missing"));
}
static void prepare(Obj gameData,int slot) {
    plan=Plan{};
    if((!ba::lan() && !ba::offlinePractice()) || !wcsstr(GetCommandLineW(),L"-lan-smoke"))return;
    try {
        if(slot<0 || slot>1)throw std::runtime_error("smoke slot must be 0 or 1");
        Obj config=require(ba::get<Obj>(gameData,"gameConfig_"),"smoke GameConfig missing");
        Obj armies=require(ba::get<Obj>(config,"armies_"),"smoke armies missing");
        Obj army=require(item(armies,slot),"smoke local army missing");
        if(ba::get<uint32_t>(army,"armyId_")!=static_cast<uint32_t>(slot))throw std::runtime_error("smoke army order differs");
        Obj deck=require(ba::get<Obj>(army,"deck_"),"smoke assigned deck missing");
        const uint32_t unit=unitAt(ba::get<Obj>(deck,"units_"),slot);
        if(!unit)throw std::runtime_error("smoke opening deck slot is empty");
        Obj abilities=require(ba::get<Obj>(config,"abilities_"),"smoke ability list missing");
        int matches=0;uint32_t key=0;
        for(int index=0;index<ba_local::count(abilities);++index) {
            Obj ability=item(abilities,index);
            // Read the generated oneof getter, rather than assuming its case ID.
            Obj create=ba::call(ability,"get_CreateUnitFromDeckAbility");
            if(create && ba::get<int>(create,"deckSlot_")==slot) {
                key=ba::get<uint32_t>(ability,"key_");++matches;
                ba::log("LAN smoke candidate slot%d deckSlot%d ability=%u unitType=%u",slot,slot,key,unit);
            }
        }
        if(matches!=1)throw std::runtime_error("smoke requires exactly one normal build ability for selected deck slot");
        plan.slot=slot;plan.key=key;plan.unit=unit;plan.ready=true;
        ba::log("LAN smoke prepared: slot%d will request normal deckSlot%d unitType=%u ability=%u at input frame%d",slot,slot,unit,key,slot==0?300:400);
    } catch(const std::exception& e) {ba::log("LAN normal-build smoke disabled during preparation: %s",e.what());}
}
static void enqueue(Obj server,int frame) {
    const int surrenderFrame=atoi(ba::argument(L"-dedicated-surrender-frame=","600").c_str());
    if(ba::dedicated() && ba::lanSlot()==0 && frame==surrenderFrame && wcsstr(GetCommandLineW(),L"-dedicated-surrender-smoke")) {
        try {
            Obj sim=require(ba::read<Obj>(server,0x140),"surrender simulation missing");
            int before=ba_local::count(ba::read<Obj>(server,0x180));ba::call(sim,"ConcedeGame");
            ba::log("DEDICATED SURRENDER smoke frame%d normal ConcedeGame commandQueueDelta=%d",frame,ba_local::count(ba::read<Obj>(server,0x180))-before);
        }catch(const std::exception& e){ba::log("Dedicated surrender smoke failed: %s",e.what());}
    }
    if(!plan.ready || plan.attempted || frame!=(plan.slot==0?300:400))return;
    plan.attempted=true;
    try {
        Obj simulation=require(ba::read<Obj>(server,0x140),"smoke simulation missing");
        Obj game=require(ba::get<Obj>(require(ba::owner,"smoke owner missing"),"<PlayerGameInstance>k__BackingField"),"smoke player game instance missing");
        if(ba::read<Obj>(game,0x10)!=simulation)throw std::runtime_error("smoke game/simulation mismatch");
        Obj services=require(ba::read<Obj>(game,0x18),"smoke service manager missing");
        if(ba::read<Obj>(services,0x18)!=server)throw std::runtime_error("smoke game/server mismatch");
        Obj player=require(ba::get<Obj>(simulation,"_localPlayer"),"smoke local SimPlayer missing");
        const uint32_t army=ba::get<uint32_t>(player,"ArmyID");
        if(army!=static_cast<uint32_t>(plan.slot))throw std::runtime_error("smoke local army mismatch");
        require(ba::read<Obj>(game,0x80),"smoke presented frame collection missing");
        Root buffers(require(ba::call(game,"get_SimFrame"),"smoke current frame missing"));
        const uint32_t headquarters=ba::native<uint32_t(*)(Obj,uint32_t,Obj)>(0x3c6f290)(buffers.get(),army,nullptr);
        if(headquarters==UINT32_MAX)throw std::runtime_error("smoke army has no headquarters in current frame");
        Obj staticData=require(ba::get<Obj>(simulation,"_staticGameData"),"smoke static data missing");
        // The uint overload is a dictionary lookup returning null when absent.
        Root ability(require(ba::native<Obj(*)(Obj,uint32_t,Obj)>(0x3e722d0)(staticData,plan.key,nullptr),"smoke runtime build ability missing"));
        if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(ba::klass(ability.get())),"CreateUnitFromDeckAbilityConfig"))
            throw std::runtime_error("smoke resolved ability is not a deck build ability");
        if(ba::get<int>(ability.get(),"<DeckSlot>k__BackingField")!=plan.slot)throw std::runtime_error("smoke runtime deck slot mismatch");
        uint32_t armyArg=army;void* costArgs[]={&armyArg};
        Root cost(ba::call(ability.get(),"GetResourceCost",1,costArgs));
        const int primary=cost.get()?ba::get<int>(cost.get(),"_primaryResource"):-1;
        const int secondary=cost.get()?ba::get<int>(cost.get(),"_secondaryResource"):-1;
        Obj queue=require(ba::read<Obj>(server,0x180),"smoke input queue missing");
        const int before=ba_local::count(queue);
        bool meetsPrerequisite=false;
        // Native Win64 signature of AIUtility.BuildUnit: game, player, ability,
        // out bool, Nullable<Flatbuffers.ArmyResources> by value, MethodInfo*.
        // This 24-byte nullable aggregate is passed by pointer by Win64 ABI.
        // Byte0=false is the original optional/default value. The helper checks
        // only that byte when empty (original VA183b156e9); CanCast still runs,
        // and the native simulation remains responsible for actual resources.
        alignas(8) unsigned char noResourceSnapshot[24]={};
        const bool queued=ba::native<bool(*)(Obj,Obj,Obj,bool*,const void*,Obj)>(0x3b15510)
            (game,player,ability.get(),&meetsPrerequisite,noResourceSnapshot,nullptr);
        const int after=ba_local::count(queue);
        ba::log("LAN NORMAL BUILD smoke frame%d slot%d army%u HQ%u deckSlot%d unitType%u ability%u cost=(%d,%d) prerequisite=%d queued=%d commandQueueDelta=%d presentedFrame=%d",
            frame,plan.slot,army,headquarters,plan.slot,plan.unit,plan.key,primary,secondary,
            meetsPrerequisite?1:0,queued?1:0,after-before,ba::read<int>(simulation,0xac));
        if(queued && after!=before+1)ba::log("LAN smoke warning: original build helper returned true but command queue did not grow by one");
    } catch(const std::exception& e) {ba::log("LAN normal-build smoke stopped at frame%d: %s",frame,e.what());}
}
}
