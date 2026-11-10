// Explicit owned correction fixture. Original selection/control-group/focus APIs
// only; no simulated callbacks, native state writes or observer-token changes.
namespace ba_prediction_actor_smoke {
namespace actors=ba_prediction_actors;
namespace selection=ba_prediction_selection;
namespace worker=ba_prediction_worker;
using ba::Obj;
using ba_local::Root;
struct State {
    uint64_t world=0;
    std::string match;
    std::unique_ptr<Root> originalCore,group;
    uint32_t entity=0;
    int firstDead=-1,firstRestored=-1;
    bool setup=false,passed=false,failed=false,escapeQueued=false,focusRetainedAtDeath=false;
};
static State& state(){static State* value=new State;return *value;}
static void require(bool ok,const char* why){actors::require(ok,why);}
static void event(const char* name,int frame,Obj current=nullptr) {
    const auto& s=state();
    ba::log("ACTOR CORRECTION {\"schema\":1,\"event\":\"%s\",\"world\":%llu,\"match\":\"%s\",\"entity\":%u,\"army\":%d,\"unit_type\":3,\"frame\":%d,\"tick_ms\":%llu,\"original_actor\":\"%p\",\"current_actor\":\"%p\",\"original_focus_supported\":false,\"original_group_supported\":false,\"focus_retained_at_death\":%s,\"physicalUI\":false}",
        name,static_cast<unsigned long long>(s.world),s.match.c_str(),s.entity,ba::lanSlot(),frame,
        static_cast<unsigned long long>(GetTickCount64()),
        s.originalCore?s.originalCore->get():nullptr,current,s.focusRetainedAtDeath?"true":"false");
}
static Obj selectorFor(actors::State& owner) {
    Obj selector=selection::currentSelector();actors::classIs(selector,"Uncapped","UnitSelector");
    actors::field(selector,"_unitManager",0x40);
    require(owner.manager&&ba::read<Obj>(selector,0x40)==owner.manager->get(),"actor fixture selector owner differs");
    return selector;
}
static Obj coreFor(actors::State& owner) {
    Obj found=nullptr;
    for(Obj actor:actors::units(ba::read<Obj>(owner.manager->get(),0x10))) {
        const auto identity=actors::resident(actor);
        if(identity.armyId!=static_cast<uint32_t>(ba::lanSlot())||identity.unitType!=3)continue;
        actors::field(actor,"_componentData",0x158);
        actors::field(actor,"<DeadToTheSim>k__BackingField",0x160);
        if(ba::read<bool>(actor,0x160)||!ba::read<Obj>(actor,0x158))continue;
        require(!found,"actor fixture requires exactly one live owned Core3");found=actor;
    }
    return found;
}
static void setup(actors::State& owner,Obj selector,int frame) {
    auto& s=state();Obj core=coreFor(owner);require(core,"actor fixture own Core missing");
    selection::Context admission(selector);require(admission.admitted(core),"actor fixture Core is not confirmed");
    const auto identity=actors::resident(core);require(identity.entityId==5,"actor fixture victim Core ID differs");
    s.entity=identity.entityId;s.originalCore=std::make_unique<Root>(core);
    actors::field(core,"_entityConfig",0x168);
    Obj config=ba::read<Obj>(core,0x168);actors::field(config,"IsHQ",0x2c);
    require(ba::read<bool>(config,0x2c),"actor fixture Core is not original HQ presentation type");
    // These exact original non-callback methods are also used by real input.
    Obj clear=actors::method(selector,"ClearSelection",0,0x06002217,0x3bf2680);
    Obj add=actors::method(selector,"AddToSelection",1,0x06002214,0x3bf2510);
    Obj assign=actors::method(selector,"AssignSelectionToControlGroup",2,0x0600220e,0x3bf14e0);
    Obj focus=actors::method(selector,"FocusControlGroup",2,0x06002221,0x3bf3010);
    Obj begin=actors::method(selector,"BeginSelectionChange",1,0x06002237,0x3bf5af0);
    actors::field(selector,"_selectionChangeHelper",0x80);
    Root helper(ba::read<Obj>(selector,0x80));require(helper.get(),"actor fixture selection helper missing");
    actors::field(helper.get(),"<IsSuspended>k__BackingField",0x10);
    require(!ba::read<bool>(helper.get(),0x10),"actor fixture selection already suspended");
    Obj dispose=actors::method(helper.get(),"Dispose",0,0x060000cd,0x3b02160);
    bool disposed=false;
    auto close=[&](){if(!disposed&&ba::read<bool>(helper.get(),0x10)) {
        disposed=true;actors::invoke(dispose,helper.get());
    }};
    try {
        bool playerInitiated=true;void* beginArgs[]={&playerInitiated};
        require(actors::invoke(begin,selector,beginArgs)==helper.get(),"actor fixture original scope owner differs");
        ba::log("Actor fixture original selection scope begun: entity=%u",s.entity);
        actors::invoke(clear,selector);void* addArgs[]={&s.entity};actors::invoke(add,selector,addArgs);
        close();require(disposed&&!ba::read<bool>(helper.get(),0x10),"actor fixture original scope did not close");
    } catch(...) {try{close();}catch(...){ba::log("Actor fixture original selection cleanup failed; retry=0");}throw;}
    require(selection::selectionIds(ba::read<Obj>(selector,0x90))==std::vector<uint32_t>{s.entity},
        "actor fixture original selection did not retain exactly its Core");
    ba::log("Actor fixture original selection committed: entity=%u",s.entity);
    int groupId=4;bool replace=true;void* assignArgs[]={&groupId,&replace};actors::invoke(assign,selector,assignArgs);
    bool repeat=true;void* focusArgs[]={&groupId,&repeat};actors::invoke(focus,selector,focusArgs);
    actors::field(selector,"_repeatFocusUnit",0xa8);actors::field(selector,"_focusChaseControlGroup",0xa0);
    // Original HasAssignableUnit deliberately excludes IsHQ. The sole Core
    // selection cannot populate a control group or begin persistent focus.
    // Exercise that ordinary refusal without bypassing it through lower APIs.
    require(!ba::read<Obj>(selector,0xa8)&&ba::read<int>(selector,0xa0)==-1,
        "actor fixture sole HQ unexpectedly entered persistent focus");
    Obj panel=ba::read<Obj>(selector,0x38);actors::classIs(panel,"Uncapped","ControlGroupPanel");
    actors::field(panel,"_controlGroups",0x38);Obj groups=ba::read<Obj>(panel,0x38);
    require(groups&&ba::read<uintptr_t>(groups,0x18)>4,"actor fixture group4 unavailable");
    s.group=std::make_unique<Root>(ba::read<Obj>(groups,0x20+4*sizeof(Obj)));
    actors::classIs(s.group->get(),"Uncapped","ControlGroup");actors::field(s.group->get(),"<ID>k__BackingField",0x38);
    require(ba::read<int>(s.group->get(),0x38)==groupId,"actor fixture group index/ID differ");
    Obj selected=ba::read<Obj>(s.group->get(),0x20);void* idArgs[]={&s.entity};
    Root contains(actors::invoke(actors::method(selected,"Contains",1,0x060025b7),selected,idArgs));
    require(!actors::unbox<bool>(contains.get()),"actor fixture original group admitted excluded HQ");
    s.setup=true;event("original_hq_selection_established",frame,core);
}
static void escape(actors::State& owner,Obj selector,int frame) {
    namespace original=ba_prediction_movement_smoke;
    auto& s=state();selection::Context admission(selector);
    auto found=admission.live.find(10);require(found!=admission.live.end(),"actor fixture initial Gunbot10 missing");
    Obj actor=found->second;const auto identity=actors::resident(actor);
    require(identity.armyId==0&&identity.unitType==1&&admission.admitted(actor),"actor fixture escape source is not confirmed Gunbot1");
    uint32_t id=identity.entityId,ability=12,unitType=identity.unitType;
    original::Vec3 target{-69.77999877929688f,0.f,-80.8499984741211f};original::finite(target);
    Root ids(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(actors::type("System","UInt32"),1));
    require(ids.get(),"actor fixture escape ID array missing");
    std::memcpy(static_cast<unsigned char*>(ids.get())+0x20,&id,sizeof(id));
    Root group(original::allocate("ExecuteCommandEntityTypeData"));
    Obj groupCtor=actors::method(group.get(),".ctor",3,0x060000f3,0x34b3080);
    void* groupArgs[]={ids.get(),&ability,&unitType};
    actors::invoke(groupCtor,group.get(),groupArgs);
    require(ba::read<Obj>(group.get(),0x10)==ids.get()&&ba::read<uint32_t>(group.get(),0x18)==ability&&
        ba::read<uint32_t>(group.get(),0x1c)==unitType,"actor fixture original escape group differs");
    Root groups(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(ba::klass(group.get()),1));
    require(groups.get(),"actor fixture escape group array missing");
    auto* slot=reinterpret_cast<Obj*>(static_cast<unsigned char*>(groups.get())+0x20);
    ba::api<void(*)(Obj,Obj*,Obj)>("il2cpp_gc_wbarrier_set_field")(groups.get(),slot,group.get());
    require(*slot==group.get(),"actor fixture escape group reference not published");
    Root command(original::allocate("ExecuteTargetGroundCommand"));
    Obj ctor=actors::method(command.get(),".ctor",4,0x060000e6,0x37ae080);
    require(original::parameterClass(ctor,1)==actors::type("UnityEngine","Vector3"),
        "actor fixture escape target ABI differs");
    int32_t perspective=original::normalPerspective(ctor);bool queued=false;
    void* args[]={groups.get(),&target,&perspective,&queued};actors::invoke(ctor,command.get(),args);
    const auto hash=original::actionHash(command.get());
    require(admission.admitted(actor),"actor fixture escape source changed before enqueue");
    Obj server=ba_local::server();actors::classIs(server,"Uncapped","GameServerIntegration");
    require(ba::read<Obj>(server,0x140)==owner.simulation->get(),"actor fixture escape server changed");
    Obj queue=ba::read<Obj>(server,0x180);const int before=ba_local::count(queue);
    Obj enqueue=actors::method(server,"EnqueueInputCommand",1,0x06001115,0x3e53530);
    void* commandArgs[]={command.get()};actors::invoke(enqueue,server,commandArgs);
    require(ba_local::count(queue)==before+1,"actor fixture original escape enqueue delta differs");s.escapeQueued=true;
    ba::log("ACTOR ORDER {\"schema\":1,\"event\":\"original_escape_move\",\"world\":%llu,\"match\":\"%s\",\"army\":0,\"entity\":10,\"unit_type\":1,\"ability\":12,\"frame\":%d,\"tick_ms\":%llu,\"action_sha256\":\"%s\",\"originalCtor\":true,\"physicalUI\":false}",
        static_cast<unsigned long long>(s.world),s.match.c_str(),frame,static_cast<unsigned long long>(GetTickCount64()),hash.c_str());
}
static void tick() {
    if(!ba::flag(L"-prediction-actor-correction-smoke"))return;
    try {
        const auto world=worker::movementWorldId();const auto match=worker::movementMatchId();
        if(!worker::movementEnabled()||!world||match.empty()){state()=State{};return;}
        auto& s=state();if(s.world!=world||s.match!=match){s=State{};s.world=world;s.match=match;}
        if(s.failed||s.passed)return;
        auto& owner=actors::state();
        if(owner.world!=world||owner.match!=match||!owner.manager||!owner.simulation)return;
        require(!owner.failed&&owner.thread==GetCurrentThreadId(),"actor fixture owner failed/changed");
        if(ba_lan::matchEnded)return;
        require(ba::unified()&&ba::community()&&ba::dedicated()&&ba::lan()&&ba_lan::originalCommandScheduling()&&
            ba_lan::running&&!ba_lan::publicMatch,"actor fixture requires negotiated prediction Custom");
        const int frame=ba::read<int>(owner.simulation->get(),0xac);
        if(ba::lanSlot()==0) {
            if(s.escapeQueued||frame<152)return;
            require(frame==152,"actor fixture missed its physical escape frame152");
            escape(owner,selectorFor(owner),frame);return;
        }
        require(ba::lanSlot()==1,"actor fixture requires exactly two human seats");
        if(frame<130)return;
        Obj selector=selectorFor(owner);
        if(!s.setup){require(frame<145,"actor fixture missed pre-death selection window");setup(owner,selector,frame);return;}
        if(s.firstDead<0) {
            Obj old=s.originalCore->get();
            if(!ba::read<bool>(old,0x160)||ba::read<Obj>(old,0x158))return;
            const auto retained=actors::units(ba::read<Obj>(owner.manager->get(),0xa0));
            require(std::find(retained.begin(),retained.end(),old)!=retained.end(),"actor fixture dead HQ was not retained by original manager");
            s.focusRetainedAtDeath=ba::read<Obj>(selector,0xa8)==old&&ba::read<int>(selector,0xa0)==4;
            s.firstDead=frame;event("original_dead_hq_retained",frame,old);return;
        }
        Obj core=coreFor(owner);if(!core)return;
        require(actors::resident(core).entityId==s.entity,"actor fixture resurrected Core identity differs");
        selection::Context admission(selector);require(admission.admitted(core),"actor fixture restored Core not admitted");
        require(!ba::read<Obj>(selector,0xa8)&&ba::read<int>(selector,0xa0)==-1,
            "actor fixture restored Core retains old focus");
        Obj selected=ba::read<Obj>(s.group->get(),0x20);void* idArgs[]={&s.entity};
        Root contains(actors::invoke(actors::method(selected,"Contains",1,0x060025b7),selected,idArgs));
        require(!actors::unbox<bool>(contains.get()),"actor fixture group retains retired HQ membership");
        actors::field(s.group->get(),"_trackedReleasedUnits",0x10);
        Obj tracked=ba::read<Obj>(s.group->get(),0x10);
        Root remembered(actors::invoke(actors::method(tracked,"Contains",1,0x060000ac,0x3782540),tracked,idArgs));
        require(!actors::unbox<bool>(remembered.get()),"actor fixture group retains released HQ identity");
        if(s.firstRestored<0){s.firstRestored=frame;event("original_hq_restored_and_admitted",frame,core);}
        if(frame>=s.firstRestored+2){s.passed=true;event("hq_selection_correction_passed",frame,core);}
    } catch(const std::exception& error) {
        state().failed=true;ba::log("Actor correction smoke failed: reason=%s physicalUI=0",error.what());
        worker::movementFail(error.what());
    }
}
}
