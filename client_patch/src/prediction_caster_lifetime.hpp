#pragma once
// Included inside mobile after its survey helpers. No headers inside this namespace.
// Programmatic original UI activation/cancellation only: no cast, factory query,
// GetCasterSet, settings/ID writes, or extension of movement prediction eligibility.
namespace caster_lifetime {
struct State {
    uint64_t world=0;std::string match;
    std::unique_ptr<Root> selector,activated,source,casting;
    std::string activatedClass;caster_survey::Button mapping;
    unsigned activationCalls=0,popCalls=0;int lastFrame=-1;
    Obj lastActive=nullptr;bool cleaned=false,beforeFresh=false,finished=false,naturalClear=false;
    std::optional<int> firstNaturalFrame;std::optional<uint64_t> firstNaturalUs;
    int activationType=0,activationCount=0;bool fromHotkey=false,held=false;
};
static State& state(){static auto* value=new State;return *value;}
static void clear() {
    auto& s=state();if(!s.world)return;
    require(ba::initialThread&&GetCurrentThreadId()==ba::initialThread,"active caster observer retirement requires Unity owner");s=State{};
}
static bool observing(int frame){return state().activationCalls&&frame>=145&&frame<180;}
static void guard(actors::State& owner,Obj selector,int frame) {
    owned(owner);require(frame>=145&&frame<180&&ba::read<int>(owner.simulation->get(),0xac)==frame,
        "active caster observation crossed its bounded publication interval");
    for(const auto& field:std::initializer_list<std::pair<const char*,size_t>>{{"_activeAbilityCaster",0x100},{"_castingSet",0x98},
        {"_selectionSet",0x90},{"_doubleClickFirstClickReferenceUnitEntityId",0x128},{"_isPointerDown",0x16c},{"_isContextPointerDown",0x16d}})
        actors::field(selector,field.first,field.second);
    const auto& s=state();require(s.world==owner.world&&s.match==owner.match&&s.selector&&s.selector->get()==selector&&
        s.source&&s.source->get()==ba::read<Obj>(selector,0x90)&&s.casting&&s.casting->get()==ba::read<Obj>(selector,0x98),
        "active caster observation roots/world changed");
    require(!ba_lan::stopped&&!ba_community::abortPending&&ba_lan::running&&pending(owner)==0&&
        !ba::read<bool>(selector,0x16c)&&!ba::read<bool>(selector,0x16d)&&ba::read<uint32_t>(selector,0x128)!=11,
        "active caster observation crossed pending input/gesture/owner boundary");
    require(!s.cleaned||!ba::read<Obj>(selector,0x100),"active caster reappeared after explicit cleanup");
}
static Obj method(Obj object,const char* name,unsigned arity,uint32_t token,uintptr_t rva,Obj result,const char* bytes) {
    return caster_survey::getter(object,name,arity,token,rva,result,bytes);
}
static bool related(actors::State& owner,Obj selector,Obj caster) {
    require(caster&&ba::api<bool(*)(Obj,Obj)>("il2cpp_class_is_assignable_from")
        (actors::type("Uncapped","IAbilityCaster"),ba::klass(caster)),"active caster is not the original managed interface");
    Obj info=method(selector,"IsUnitSelectionRelatedAbility",1,0x0600226c,0x3bf8720,actors::type("System","Boolean"),
        "\x48\x89\x5c\x24\x08\x57\x48\x83\xec\x20\x80\x3d\x14\x08\x26\x03");
    require(original::parameterClass(info,0)==actors::type("Uncapped","IAbilityCaster"),"active caster Related parameter differs");
    void* args[]={caster};auto value=caster_survey::read(owner,info,selector,args);
    return caster_survey::scalar<bool>(value.get(),actors::type("System","Boolean"));
}
static void event(actors::State& owner,Obj selector,int frame,const char* name,const char* popReason=nullptr) {
    auto& s=state();owned(owner);Obj rawCurrent=ba::read<Obj>(selector,0x100);Root current(rawCurrent);
    require(!rawCurrent||current.get()==rawCurrent,"active caster observation GC root allocation failed");const auto sampled=stamp();
    std::optional<bool> relation;std::optional<std::string> currentClass;
    if(current.get()){relation=related(owner,selector,current.get());currentClass=caster_survey::className(current.get());}
    if(s.activationCalls&&s.popCalls==0&&s.lastActive&&!current.get()&&!s.naturalClear) {
        s.naturalClear=true;s.firstNaturalFrame=frame;s.firstNaturalUs=sampled;
    }
    s.lastActive=current.get();s.lastFrame=frame;
    const auto sourceIds=selection::selectionIds(s.source->get()),castingIds=selection::selectionIds(s.casting->get());
    const int sourceCount=caster_survey::count(owner,s.source->get()),castingCount=caster_survey::count(owner,s.casting->get());
    View view(owner,selector);const auto activeRelation=!current.get()?"none":current.get()==(s.activated?s.activated->get():nullptr)?"same":"replaced";
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::boolalpha;
    out<<"{\"schema\":1,\"event\":"<<ba_catalog::quote(name)<<",\"world\":"<<s.world<<",\"match\":"<<ba_catalog::quote(s.match)
       <<",\"slot\":1,\"entity\":11,\"unit_type\":1,\"army\":1,\"frame\":"<<frame<<",\"tick_ms\":"<<GetTickCount64()<<",\"sampled_us\":"<<sampled
       <<",\"button_slot\":"<<*s.mapping.slot<<",\"config_id\":"<<*s.mapping.configId<<",\"ui_cast_type\":"<<*s.mapping.castType
       <<",\"ui_group_kind\":"<<*s.mapping.kind<<",\"smart_casting\":"<<*s.mapping.smart
       <<",\"activated_caster\":\""<<(s.activated?s.activated->get():nullptr)<<"\",\"activated_caster_class\":"<<(s.activated?ba_catalog::quote(s.activatedClass):"null")
       <<",\"active_caster\":\""<<current.get()<<"\",\"active_caster_class\":"<<(currentClass?ba_catalog::quote(*currentClass):"null")
       <<",\"active_relation\":"<<ba_catalog::quote(activeRelation)<<",\"is_unit_selection_related\":";
    caster_survey::Button::value(out,relation);
    out<<",\"source_ids\":"<<idsJson(sourceIds)<<",\"source_count\":"<<sourceCount<<",\"casting_ids\":"<<idsJson(castingIds)<<",\"casting_count\":"<<castingCount
       <<",\"pending_commands\":"<<pending(owner)<<",\"left_held\":"<<ba::read<bool>(selector,0x16c)<<",\"right_held\":"<<ba::read<bool>(selector,0x16d)
       <<",\"click_reference\":"<<ba::read<uint32_t>(selector,0x128)<<",\"activation_calls\":"<<s.activationCalls<<",\"explicit_pop_calls\":"<<s.popCalls
       <<",\"pop_reason\":"<<(popReason?ba_catalog::quote(popReason):"null")<<",\"natural_clear_observed\":"<<s.naturalClear<<",\"first_natural_clear_frame\":";
    caster_survey::Button::value(out,s.firstNaturalFrame);out<<",\"first_natural_clear_us\":";caster_survey::Button::value(out,s.firstNaturalUs);
    out<<",\"activation_info_type\":"<<s.activationType<<",\"activation_info_count\":"<<s.activationCount<<",\"activation_info_from_hotkey\":"<<s.fromHotkey
       <<",\"activation_info_held\":"<<s.held<<",\"native_identity_present\":"<<view.nativePresent<<",\"native_state\":";
    caster_survey::Button::value(out,view.nativeValue);
    out<<",\"current_actor\":\""<<view.current<<"\",\"current_admitted\":"<<view.context.admitted(view.current)
       <<",\"original_incarnation\":"<<mobile::state().originalToken<<",\"current_incarnation\":"<<token(view.context,view.current)
       <<",\"direct_factory_calls\":0,\"cast_calls\":0,\"physicalUI\":false}";
    const auto text=out.str();require(text.size()<=8192,"active caster receipt bound");ba::log("MOBILE ACTIVE CASTER %s",text.c_str());
}
struct Mapping {std::unique_ptr<Root> panel,array,button;caster_survey::Button row;};
static Mapping findMapping(actors::State& owner,Obj selector,int targetSlot=4,uint32_t configId=88,int castType=5,int groupKind=2) {
    Mapping result;caster_survey::reference(selector,"_commandPanel",0xc8,"Uncapped","CommandPanel");
    result.panel=std::make_unique<Root>(ba::read<Obj>(selector,0xc8));actors::classIs(result.panel->get(),"Uncapped","CommandPanel");
    caster_survey::reference(result.panel->get(),"_unitSelector",0xc0,"Uncapped","UnitSelector");
    caster_survey::reference(result.panel->get(),"_simulation",0xb0,"Uncapped","Simulation");
    caster_survey::reference(result.panel->get(),"_unitManager",0xc8,"Uncapped","UnitManager");
    caster_survey::reference(result.panel->get(),"_gameServerIntegration",0xb8,"Uncapped","GameServerIntegration");
    require(ba::read<Obj>(result.panel->get(),0xc0)==selector&&ba::read<Obj>(result.panel->get(),0xb0)==owner.simulation->get()&&
        ba::read<Obj>(result.panel->get(),0xc8)==owner.manager->get()&&ba::read<Obj>(result.panel->get(),0xb8)==ba_local::server(),"active caster panel owner differs");
    Obj arrayClass=caster_survey::fieldType(result.panel->get(),"_activeAbilityButtonActions",0xa8);
    result.array=std::make_unique<Root>(ba::read<Obj>(result.panel->get(),0xa8));
    require(result.array->get()&&ba::klass(result.array->get())==arrayClass&&ba::api<int(*)(Obj)>("il2cpp_class_get_rank")(arrayClass)==1&&
        ba::api<Obj(*)(Obj)>("il2cpp_class_get_element_class")(arrayClass)==actors::type("Uncapped","AbilityButtonAction")&&
        ba::api<int(*)(Obj)>("il2cpp_type_get_type")(ba::api<Obj(*)(Obj)>("il2cpp_class_get_type")(arrayClass))==0x1d,"active caster button array ABI differs");
    const auto length=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(result.array->get());require(length<=12,"active caster button array exceeds diagnostic cap");unsigned matches=0;
    for(size_t i=0;i<length;++i) {
        const auto row=caster_survey::inspect(owner,selector,result.panel->get(),result.array->get(),i);
        if(row.present&&row.slot==targetSlot){++matches;result.row=row;result.button=std::make_unique<Root>(ba::read<Obj>(result.array->get(),0x20+i*sizeof(Obj)));}
    }
    const auto& row=result.row;require(matches==1&&result.button&&result.button->get()&&row.configId==configId&&row.castType==castType&&row.kind==groupKind&&row.smart==false&&
        row.valid==true&&row.groupMatches==true&&row.groupLive==true&&row.hasCasters==true&&row.mappedCount==1&&row.mappedIds&&*row.mappedIds==std::vector<uint32_t>{11},
        "original unique ability button mapping unavailable");return result;
}
static void pop(actors::State& owner,Obj selector,int frame,const char* reason) {
    auto& s=state();guard(owner,selector,frame);Root current(ba::read<Obj>(selector,0x100));
    require(s.popCalls==0&&current.get(),"active caster Pop requires current nonnull100 and no earlier fixture Pop");
    event(owner,selector,frame,"before_explicit_pop");
    Obj info=method(selector,"PopActiveAbility",0,0x0600223b,0x3bf6320,actors::type("System","Void"),
        "\x48\x89\x5c\x24\x20\x56\x48\x83\xec\x20\x80\x3d\x07\x2c\x26\x03");
    ++s.popCalls;caster_survey::read(owner,info,selector);guard(owner,selector,frame);
    require(!ba::read<Obj>(selector,0x100),"original Pop did not clear active100");s.cleaned=true;event(owner,selector,frame,"after_explicit_pop",reason);
}
static void activate(actors::State& owner,Obj selector,int frame) {
    auto& s=state();require(!s.world&&!s.activationCalls&&frame==145&&ba::lanSlot()==1,"active caster activation requires fresh guest145");idle(owner,selector,11);
    caster_survey::reference(selector,"_activeAbilityCaster",0x100,"Uncapped","IAbilityCaster");
    View view(owner,selector);require(view.current&&view.context.admitted(view.current)&&view.nativePresent&&view.nativeValue&&*view.nativeValue!=6&&
        ba::read<Obj>(view.current,0x158)&&!ba::read<bool>(view.current,0x160)&&token(view.context,view.current)==mobile::state().originalToken,
        "active caster source11 is not initialized/current admitted original incarnation");
    const auto identity=actors::resident(view.current);require(identity.entityId==11&&identity.unitType==1&&identity.armyId==1,"active caster source identity differs");
    auto mapping=findMapping(owner,selector);s.world=owner.world;s.match=owner.match;s.mapping=mapping.row;
    s.selector=std::make_unique<Root>(selector);s.source=std::make_unique<Root>(ba::read<Obj>(selector,0x90));s.casting=std::make_unique<Root>(ba::read<Obj>(selector,0x98));
    require(s.selector->get()==selector&&s.source->get()&&s.casting->get()&&selection::selectionIds(s.source->get())==std::vector<uint32_t>{11}&&caster_survey::count(owner,s.source->get())==1,
        "active caster source/observer roots unavailable");
    Obj activationClass=actors::type("Uncapped","ButtonActivationInfo");
    Obj hotkey=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(activationClass,"get_HotkeyActivation",0);
    require(hotkey&&ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_token")(hotkey)==0x060015c2&&ba::read<Obj>(hotkey,0)==ba::native<Obj>(0x3e9b750)&&
        ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(hotkey)==0,"active caster HotkeyActivation overload differs");
    FocusObservation::signature(hotkey,true,activationClass);actors::guard(0x3e9b750,"\x48\x83\xec\x28\x80\x3d\x05\xec\xfb\x02\x00\x75\x18\x48\x8d\x0d",16);
    auto activation=caster_survey::read(owner,hotkey,nullptr);actors::classIs(activation.get(),"Uncapped","ButtonActivationInfo");
    Obj activationType=caster_survey::fieldType(activation.get(),"<Type>k__BackingField",0x10,actors::type("Uncapped","ButtonActivationType"));
    require(ba::api<bool(*)(Obj)>("il2cpp_class_is_enum")(activationType),"active caster HotkeyActivation.Type is not its original enum");
    original::checkValue(activationType,4,"active caster HotkeyActivation.Type value ABI differs");
    caster_survey::reference(activation.get(),"<Count>k__BackingField",0x14,"System","Int32");
    Obj from=method(activation.get(),"get_IsFromHotKey",0,0x060015bf,0x3624090,actors::type("System","Boolean"),
        "\x0f\xb6\x41\x10\x24\x01\xc3\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc");
    Obj held=method(activation.get(),"get_IsHeld",0,0x060015c0,0x3e9b6f0,actors::type("System","Boolean"),
        "\x8b\x41\x10\xd1\xe8\x24\x01\xc3\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc");
    auto fromValue=caster_survey::read(owner,from,activation.get());auto heldValue=caster_survey::read(owner,held,activation.get());
    s.activationType=ba::read<int32_t>(activation.get(),0x10);s.activationCount=ba::read<int32_t>(activation.get(),0x14);
    s.fromHotkey=caster_survey::scalar<bool>(fromValue.get(),actors::type("System","Boolean"));s.held=caster_survey::scalar<bool>(heldValue.get(),actors::type("System","Boolean"));
    require(s.activationType==1&&s.activationCount==1&&s.fromHotkey&&!s.held,"original HotkeyActivation type/count/held differs");
    guard(owner,selector,frame);event(owner,selector,frame,"before_activation");
    View currentSource(owner,selector);require(currentSource.current&&currentSource.context.admitted(currentSource.current)&&
        token(currentSource.context,currentSource.current)==mobile::state().originalToken&&currentSource.nativePresent&&currentSource.nativeValue&&*currentSource.nativeValue!=6&&
        ba::read<Obj>(currentSource.current,0x158)&&!ba::read<bool>(currentSource.current,0x160)&&
        selection::selectionIds(s.source->get())==std::vector<uint32_t>{11}&&caster_survey::count(owner,s.source->get())==1,
        "active caster source changed before original Perform");
    Obj perform=method(mapping.button->get(),"PerformButtonAction",1,0x060016ac,0x3eb0c00,actors::type("System","Void"),
        "\x48\x89\x5c\x24\x08\x57\x48\x83\xec\x30\x80\x3d\x0b\x98\xfa\x02");
    require(original::parameterClass(perform,0)==activationClass,"active caster Perform reference parameter differs");
    void* args[]={activation.get()};++s.activationCalls;caster_survey::read(owner,perform,mapping.button->get(),args);
    Obj current=ba::read<Obj>(selector,0x100);bool selectionRelated=false;
    if(current) {
        s.activated=std::make_unique<Root>(current);require(s.activated->get()==current,"active caster observer GC root allocation failed");
        s.activatedClass=caster_survey::className(current);selectionRelated=related(owner,selector,current);
    }
    event(owner,selector,frame,"after_activation");guard(owner,selector,frame);
    require(current&&selectionRelated,"original UI activation did not leave a unit-related managed caster");
    if(s.world==1)pop(owner,selector,frame,"explicit_cancel");else require(s.world==2,"active caster diagnostic supports exactly two sequential worlds");
}
static void snapshot(actors::State& owner,Obj selector,int frame) {
    auto& s=state();if(!s.activationCalls||!observing(frame))return;guard(owner,selector,frame);
    if(frame!=s.lastFrame||ba::read<Obj>(selector,0x100)!=s.lastActive)event(owner,selector,frame,"snapshot");
}
static void restored(actors::State& owner,Obj selector,int frame) {
    auto& s=state();guard(owner,selector,frame);event(owner,selector,frame,"restored_before_cleanup");
    if(s.world==2) {
        if(ba::read<Obj>(selector,0x100))pop(owner,selector,frame,"post_restore_cleanup");
        else{s.cleaned=true;event(owner,selector,frame,"cleanup_skipped");}
    }
    require(s.cleaned&&!ba::read<Obj>(selector,0x100),"active caster restoration cleanup incomplete");
}
static void beforeFresh(actors::State& owner,Obj selector,int frame) {
    auto& s=state();require(s.activationCalls==1&&s.cleaned&&!s.beforeFresh,"active caster fresh move lacks completed lifetime phase");
    idle(owner,selector,11);event(owner,selector,frame,"before_fresh");s.beforeFresh=true;
}
static void complete(actors::State& owner,Obj selector,int frame) {
    auto& s=state();require(s.activationCalls==1&&s.cleaned&&s.beforeFresh&&!s.finished,"active caster completion is missing its bounded phase");
    idle(owner,selector,11);event(owner,selector,frame,"complete");s.finished=true;
}
}
