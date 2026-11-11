// Included inside ba_prediction_actors after the raw selection reader. This
// records original press/removal provenance only; live retirement still refuses.
namespace click_proof=ba_prediction_click_provenance;
static void clickForget(State& s)noexcept {
    s.clickProvenance.clear();s.clickSelector.reset();s.clickSnapshot={};
}
static void clickExternalEdit(State& s) {
    clickForget(s);s.inputIntent.invalidate();
}
static bool clickCurrent(State& s) {
    if(!s.clickProvenance.current(s.inputIntent)){clickForget(s);return false;}
    return s.clickSelector && s.clickSelector->get();
}
static bool clickActive() {
    return ba_prediction_worker::movementEnabled() && ba_prediction_worker::movementWorldId() &&
        !ba_prediction_worker::movementMatchId().empty() && ba::initialThread &&
        GetCurrentThreadId()==ba::initialThread;
}
static bool clickSample(State& s,Obj selector,bool suspended,const click_proof::Identity& expected,ClickSnapshot& result) {
    require(clickActive() && s.thread==GetCurrentThreadId() && !s.failed &&
        s.world==ba_prediction_worker::movementWorldId() && s.match==ba_prediction_worker::movementMatchId() &&
        s.manager && s.simulation && ba_prediction_movement::ownsPresentation(s.simulation->get()) &&
        selector==ba::get<Obj>(ba::owner,"<UnitSelector>k__BackingField"),
        "click provenance lost its current presentation owner");
    classIs(selector,"Uncapped","UnitSelector");
    field(selector,"_unitManager",0x40);field(selector,"_simulation",0x138);
    require(ba::read<Obj>(selector,0x40)==s.manager->get() &&
        ba::read<Obj>(selector,0x138)==s.simulation->get(),"click provenance graph differs");
    field(selector,"_selectionChangeHelper",0x80);field(selector,"_previewSelectionSet",0x88);
    field(selector,"_selectionSet",0x90);field(selector,"_castingSet",0x98);field(selector,"_camera",0xc0);
    field(s.simulation->get(),"_localPlayer",0x90);
    Obj player=ba::read<Obj>(s.simulation->get(),0x90);classIs(player,"Uncapped","SimPlayer");
    clickField(player,"ArmyID",0x38,type("System","UInt32"),4);
    if(expected.entity==UINT32_MAX || expected.type!=3 || expected.army!=ba::read<uint32_t>(player,0x38))return false;
    result.graph={ba::read<Obj>(selector,0x80),ba::read<Obj>(selector,0x88),ba::read<Obj>(selector,0x90),
        ba::read<Obj>(selector,0x98),ba::read<Obj>(s.simulation->get(),0x148),ba::read<Obj>(selector,0xc0),nullptr,nullptr,player};
    Obj helper=result.graph[0];require(helper && result.graph[4] && result.graph[5],"click provenance helper/frames/camera missing");
    const char* helperName=ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(ba::klass(helper));
    require(helperName && !strcmp(helperName,"SelectionChangeHelper") &&
        ba::api<Obj(*)(Obj)>("il2cpp_class_get_declaring_type")(ba::klass(helper))==ba::klass(selector),
        "click provenance original helper type differs");
    field(helper,"_unitSelector",0x20);field(helper,"_unitManager",0x28);field(helper,"_confirmerOverride",0x18);
    field(helper,"<IsSuspended>k__BackingField",0x10);field(helper,"<AutoRaise>k__BackingField",0x11);
    field(helper,"_playerInitiatedChange",0x13);
    require(ba::read<Obj>(helper,0x20)==selector && ba::read<Obj>(helper,0x28)==s.manager->get(),
        "click provenance helper belongs to another selector/manager");
    for(size_t offset:{size_t{0x10},size_t{0x11},size_t{0x13}})
        require(ba::read<uint8_t>(helper,offset)<=1,"click provenance helper Boolean differs");
    if(ba::read<bool>(helper,0x10)!=suspended || !ba::read<bool>(helper,0x11) ||
       ba::read<bool>(helper,0x13) || ba::read<Obj>(helper,0x18))return false;
    Obj boolean=type("System","Boolean"),single=type("System","Single"),vector=type("UnityEngine","Vector2");
    clickField(selector,"_isPointerDown",0x16c,boolean,1);clickField(selector,"_isContextPointerDown",0x16d,boolean,1);
    clickField(selector,"_isDragging",0x119,boolean,1);clickField(selector,"_appendCommands",0x118,boolean,1);
    clickField(selector,"<ForceSelectAllUnitsOfSameType>k__BackingField",0x190,boolean,1);
    for(size_t offset:{size_t{0x16c},size_t{0x16d},size_t{0x119},size_t{0x118},size_t{0x190}})
        require(ba::read<uint8_t>(selector,offset)<=1,"click provenance selector Boolean differs");
    clickMode(selector);clickField(selector,"_doubleClickFirstClickReferenceUnitEntityId",0x128,type("System","UInt32"),4);
    field(selector,"_focusChaseControlGroup",0xa0);field(selector,"_activeAbilityCaster",0x100);
    if(ba::read<uint8_t>(selector,0x16c)!=1 || ba::read<bool>(selector,0x16d) || ba::read<bool>(selector,0x119) ||
       ba::read<bool>(selector,0x118) || ba::read<bool>(selector,0x190) || ba::read<int>(selector,0x170)!=1 ||
       ba::read<uint32_t>(selector,0x128)!=expected.entity || ba::read<int>(selector,0xa0)!=-1 || ba::read<Obj>(selector,0x100))return false;
    clickField(selector,"_doubleClickFirstClickReferencePosition",0x12c,vector,8);
    clickField(selector,"_currentPointerPosition",0x14c,vector,8);clickField(selector,"_pointerDownPosition",0x164,vector,8);
    clickField(selector,"_lastPointerUpTime",0x154,single,4);clickField(selector,"_doubleClickTime",0x28,single,4);
    const size_t offsets[]={0x12c,0x130,0x14c,0x150,0x164,0x168,0x154,0x28};
    for(size_t index=0;index<8;++index) {
        const float value=ba::read<float>(selector,offsets[index]);
        require(std::isfinite(value) && (index<6 || value>=0),"click provenance original scalar differs");
        result.scalars[index]=ba::read<uint32_t>(selector,offsets[index]);
    }
    for(size_t index:{size_t{1},size_t{2},size_t{3}}) {
        Obj set=result.graph[index];classIs(set,"Uncapped.Collections","UnitSelectionSet");field(set,"_simFrames",0x48);
        require(ba::read<Obj>(set,0x48)==result.graph[4],"click provenance selection frame owner differs");
    }
    Root server(ba_local::server());require(server.get() && ba_local::isTarget(server.get()) &&
        ba::read<Obj>(server.get(),0x140)==s.simulation->get(),"click provenance command owner differs");
    field(server.get(),"_queuedInputCommands",0x180);Root commands(ba::read<Obj>(server.get(),0x180));
    require(commands.get()!=nullptr,"click provenance command queue missing");
    {ba_local::QueueLock lock;const int count=ba_local::count(commands.get());
        require(count>=0 && static_cast<size_t>(count)<=maximumActors,"click provenance command count bound");
        if(count)return false;}
    result.graph[6]=server.get();result.graph[7]=commands.get();return true;
}
static bool clickSameSample(State& s,Obj selector,bool suspended) {
    if(!s.clickProvenance.press())return false;
    ClickSnapshot value;return clickSample(s,selector,suspended,s.clickProvenance.press()->identity,value) &&
        value.graph==s.clickSnapshot.graph && value.scalars==s.clickSnapshot.scalars;
}
[[maybe_unused]] static void clickCapture(State& s,Obj selector,const ba_prediction_input_observer::Ticket& ticket) {
    clickForget(s);
    if(s.inUpdate || !s.inputIntent.accepted() || !click_proof::same(ticket,*s.inputIntent.accepted()) ||
       !s.manager || !s.simulation || ba::lanSlot()<0 || ba::lanSlot()>1)return;
    classIs(selector,"Uncapped","UnitSelector");
    clickField(selector,"_doubleClickFirstClickReferenceUnitEntityId",0x128,type("System","UInt32"),4);
    const auto entity=ba::read<uint32_t>(selector,0x128);if(entity==UINT32_MAX)return;
    Obj unit=nullptr;Resident observed;
    for(Obj actor:units(ba::read<Obj>(s.manager->get(),0x10))) {
        const auto found=s.identities.find(actor);
        if(found==s.identities.end() || found->second.identity.entityId!=entity)continue;
        require(!unit,"click provenance has duplicate active identity");unit=actor;observed=found->second;
    }
    if(!unit || observed.identity.unitType!=3 || !observed.incarnation ||
       observed.incarnation!=confirmedToken(s,observed.identity))return;
    const auto actual=resident(unit);
    if(actual.entityId!=entity || actual.unitType!=observed.identity.unitType || actual.armyId!=observed.identity.armyId)return;
    Root config(ba::read<Obj>(unit,0x168));clickField(config.get(),"IsHQ",0x2c,type("System","Boolean"),1);
    require(ba::read<uint8_t>(config.get(),0x2c)<=1,"click provenance HQ Boolean differs");
    if(!ba::read<bool>(config.get(),0x2c))return;
    const click_proof::Identity identity{entity,actual.unitType,actual.armyId,observed.incarnation};
    ClickSnapshot value;if(!clickSample(s,selector,false,identity,value))return;
    if(!clickSelectionShape(value.graph[1],entity,identity.type,true) || !clickSelectionShape(value.graph[2],entity,identity.type,true) ||
       !clickSelectionShape(value.graph[3],entity,identity.type,false))return;
    Current frame(value.graph[4]);const int pressedFrame=ba::read<int>(frame.frame.get(),0x40);
    const auto native=frame.identity(entity);
    if(!native || native->unitType!=identity.type || native->armyId!=identity.army ||
       confirmedToken(s,actual)!=identity.token)return;
    ClickSnapshot repeated;if(!clickSample(s,selector,false,identity,repeated) || repeated.graph!=value.graph || repeated.scalars!=value.scalars)return;
    click_proof::Press press{ticket,identity,reinterpret_cast<uintptr_t>(value.graph[0]),pressedFrame};
    auto retained=std::make_unique<Root>(selector);
    require(retained->get()==selector,"click provenance selector root failed");
    s.clickProvenance.capture(s.inputIntent,press);s.clickSelector=std::move(retained);s.clickSnapshot=value;
    ba::log("Prediction held click captured: world=%llu serial=%llu entity=%u token=%llu frame=%d rawTypedShape=1 repairAuthorized=0",
        static_cast<unsigned long long>(s.world),static_cast<unsigned long long>(ticket.serial),
        entity,static_cast<unsigned long long>(observed.incarnation),pressedFrame);
}
struct ClickOriginalUpdate {
    State& state;
    explicit ClickOriginalUpdate(State& value):state(value) {
        require(value.inUpdate && !value.originalManagerUpdate && value.managerUpdateSerial!=UINT64_MAX,
            "click original-manager boundary differs");
        ++value.managerUpdateSerial;value.originalManagerUpdate=true;
    }
    ~ClickOriginalUpdate(){state.originalManagerUpdate=false;}
};
[[maybe_unused]] static bool clickBeginNatural(State& s,Obj selector,Obj batch,Obj info,click_proof::Removal& operation) {
    if(!clickCurrent(s) || s.clickProvenance.phase()!=click_proof::Phase::Held || !s.originalManagerUpdate ||
       !s.inUpdate || info || selector!=s.clickSelector->get())return false;
    if(ba::klass(batch)!=type("Uncapped.Collections","UnitSet"))return false;
    field(batch,"_entityIds",0x18);
    const auto press=*s.clickProvenance.press();
    const auto& identity=press.identity;
    if(ids(ba::read<Obj>(batch,0x18))!=std::vector<uint32_t>{identity.entity} || !clickSameSample(s,selector,false))return false;
    if(confirmedToken(s,{identity.entity,identity.type,identity.army})!=identity.token ||
       !clickSelectionShape(s.clickSnapshot.graph[1],identity.entity,identity.type,true) ||
       !clickSelectionShape(s.clickSnapshot.graph[2],identity.entity,identity.type,true) ||
       !clickSelectionShape(s.clickSnapshot.graph[3],identity.entity,identity.type,false))return false;
    Current frame(s.clickSnapshot.graph[4]);
    operation=s.clickProvenance.beginRemoval(s.inputIntent,s.managerUpdateSerial,press.helper,press.identity,
        ba::read<int>(frame.frame.get(),0x40));return true;
}
[[maybe_unused]] static bool clickObserveRemovalPart(State& s,Obj set,uint32_t id,click_proof::RemovalPart part) {
    if(!clickCurrent(s) || !s.clickProvenance.operation())return false;
    const auto operation=*s.clickProvenance.operation();
    if(!s.originalManagerUpdate || operation.managerUpdate!=s.managerUpdateSerial ||
       !clickSameSample(s,s.clickSelector->get(),true))return false;
    const auto index=part==click_proof::RemovalPart::Preview?1u:2u;
    return set==s.clickSnapshot.graph[index] && s.clickProvenance.observe(s.inputIntent,operation,part,operation.helper,id);
}
[[maybe_unused]] static void clickSelectionCommit(State& s,Obj selector,Obj helper) {
    if(clickCurrent(s) && s.clickProvenance.operation() && selector==s.clickSelector->get()) {
        const auto operation=*s.clickProvenance.operation();
        if(s.originalManagerUpdate && operation.managerUpdate==s.managerUpdateSerial &&
           helper==s.clickSnapshot.graph[0] && clickSameSample(s,selector,true) &&
           s.clickProvenance.observe(s.inputIntent,operation,click_proof::RemovalPart::Commit,
               reinterpret_cast<uintptr_t>(helper),operation.identity.entity))return;
    }
    clickExternalEdit(s);
}
[[maybe_unused]] static bool clickFinishNatural(State& s,Obj selector,const click_proof::Removal& operation) {
    if(!clickCurrent(s) || !s.originalManagerUpdate || operation.managerUpdate!=s.managerUpdateSerial ||
       !clickSameSample(s,selector,false) || !clickSelectionShape(s.clickSnapshot.graph[1],operation.identity.entity,operation.identity.type,false) ||
       !clickSelectionShape(s.clickSnapshot.graph[2],operation.identity.entity,operation.identity.type,false) || !clickSelectionShape(s.clickSnapshot.graph[3],operation.identity.entity,operation.identity.type,false) ||
       confirmedToken(s,{operation.identity.entity,operation.identity.type,operation.identity.army})!=operation.identity.token || !s.clickProvenance.finishRemoval(s.inputIntent,operation))return false;
    ba::log("Prediction held click natural removal observed: world=%llu serial=%llu entity=%u token=%llu frame=%d operation=%llu managerUpdate=%llu originalParts=3 repairAuthorized=0",
        static_cast<unsigned long long>(s.world),static_cast<unsigned long long>(operation.ticket.serial),
        operation.identity.entity,static_cast<unsigned long long>(operation.identity.token),operation.frame,
        static_cast<unsigned long long>(operation.nonce),static_cast<unsigned long long>(operation.managerUpdate));return true;
}
