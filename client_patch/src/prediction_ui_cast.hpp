#pragma once
// Included inside mobile after the original UI binding helpers. This separate
// mode exercises an authoritative UI88 command, never predicted Move12 feel.
namespace ui_cast {
namespace life=caster_lifetime;
struct Perspective {
    uint32_t alliance=0;int32_t map=0,composite=0,normal=0,flipped=0;
    bool queue=false;int frame=-1;
};
struct State {
    uint64_t world=0;std::string match,casterClass;
    std::unique_ptr<Root> selector,source,casting,commands,caster;
    caster_survey::Button mapping;unsigned activations=0,casts=0;int lastFrame=-1;
    Obj lastCaster=nullptr;bool drained=false,finished=false;
    std::optional<uint64_t> nextBefore,nextAfter,originUs,callBegin,callEnd;
    std::optional<bool> result;std::optional<Perspective> perspective;
    std::optional<original::Vec3> origin,target;
    std::vector<uint32_t> queuedSource,queuedCasting,lastCasting;ULONGLONG queuedTick=0;
};
static State& state(){static auto* value=new State;return *value;}
// Scalar evidence only. Never keep an old scene, pointer or incarnation alive
// or use prior numeric IDs as admission for a unit in the next world.
struct ResidueCertificate {
    bool valid=false;uint64_t world=0,nextBefore=0,nextAfter=0;int completeFrame=-1;std::string match;
};
static ResidueCertificate& certificate(){static auto* value=new ResidueCertificate;return *value;}
static void clear(){auto& s=state();if(!s.world)return;require(ba::initialThread&&GetCurrentThreadId()==ba::initialThread,
    "UI cast observer retirement requires Unity owner");
    if(s.world==1) {
        auto& proof=certificate();proof=ResidueCertificate{};
        if(s.finished&&s.drained&&s.activations==1&&s.casts==1&&s.nextBefore&&s.nextAfter&&
           *s.nextBefore<(std::numeric_limits<uint64_t>::max)()&&*s.nextAfter==*s.nextBefore+1&&s.lastFrame>=260&&
           s.lastCasting==std::vector<uint32_t>{11}) {
            proof.valid=true;proof.world=s.world;proof.match=s.match;proof.nextBefore=*s.nextBefore;proof.nextAfter=*s.nextAfter;proof.completeFrame=s.lastFrame;
        }
    }
    s=State{};
}
static void preactivation(actors::State& owner,Obj selector,uint32_t entity) {
    owned(owner);const int frame=ba::read<int>(owner.simulation->get(),0xac);
    require(ba::flag(L"-prediction-mobile-ui-cast-smoke")&&ba::lanSlot()==1&&entity==11&&frame>=130&&frame<=145&&
        selection::currentSelector()==selector,"UI scratch allowance is outside its explicit guest preactivation scope");
    caster_survey::reference(selector,"_simulation",0x138,"Uncapped","Simulation");caster_survey::reference(selector,"_unitManager",0x40,"Uncapped","UnitManager");
    require(ba::read<Obj>(selector,0x138)==owner.simulation->get()&&ba::read<Obj>(selector,0x40)==owner.manager->get(),"UI scratch selector owner differs");
    caster_survey::reference(selector,"_castingSet",0x98,"Uncapped.Collections","UnitSelectionSet");Root casting(ba::read<Obj>(selector,0x98));
    actors::classIs(casting.get(),"Uncapped.Collections","UnitSelectionSet");
    caster_survey::reference(casting.get(),"_simFrames",0x48,"Uncapped.Collections.ComponentBuffers","IReadOnlySimFrameCollection");
    const Obj frames=ba::read<Obj>(casting.get(),0x48),currentFrames=ba::read<Obj>(owner.simulation->get(),0x148);
    const bool frameOwner=frames&&frames==currentFrames;const auto ids=selection::selectionIds(casting.get());
    const bool references=actors::selectionReferences(casting.get(),std::set<uint32_t>{11});
    std::optional<bool> typed;std::string typedError;
    try{typed=actors::groupCacheMembership(casting.get(),11);}catch(const std::exception& error){typedError=error.what();}
    catch(...){typedError="unknown typed casting membership observation";}
    std::optional<int> castingCount;if(frameOwner&&typedError.empty())castingCount=caster_survey::count(owner,casting.get());
    for(const auto& entry:std::initializer_list<std::pair<const char*,size_t>>{{"_activeAbilityCaster",0x100},{"_isPointerDown",0x16c},
        {"_isContextPointerDown",0x16d},{"_doubleClickFirstClickReferenceUnitEntityId",0x128}})actors::field(selector,entry.first,entry.second);
    const Obj active=ba::read<Obj>(selector,0x100);const int queued=pending(owner);
    const bool left=ba::read<bool>(selector,0x16c),right=ba::read<bool>(selector,0x16d);const uint32_t click=ba::read<uint32_t>(selector,0x128);
    const auto& proof=certificate();const bool prior=proof.valid&&proof.world==1&&owner.world==2&&!proof.match.empty()&&proof.match!=owner.match&&
        proof.completeFrame>=260&&proof.nextBefore<(std::numeric_limits<uint64_t>::max)()&&proof.nextAfter==proof.nextBefore+1;
    const bool empty=ids.empty()&&!references&&typed==false&&typedError.empty();
    const bool residue=owner.world==2&&prior&&ids==std::vector<uint32_t>{11}&&typed==true&&typedError.empty();
    const bool allowed=(owner.world==1?empty:(owner.world==2&&(empty||residue)))&&frameOwner&&!active&&queued==0&&!left&&!right&&click!=11&&
        !ba_lan::stopped&&!ba_community::abortPending&&ba_lan::running;
    static uint64_t notedWorld=0;static std::string notedMatch;
    if(notedWorld!=owner.world||notedMatch!=owner.match||!allowed) {
        std::ostringstream out;out<<std::boolalpha;
        out<<"{\"schema\":1,\"event\":\"preactivation\",\"world\":"<<owner.world<<",\"match\":"<<ba_catalog::quote(owner.match)
           <<",\"slot\":1,\"entity\":11,\"frame\":"<<frame<<",\"tick_ms\":"<<GetTickCount64()<<",\"sampled_us\":"<<stamp()
           <<",\"casting_set\":\""<<casting.get()<<"\",\"casting_ids\":"<<idsJson(ids)<<",\"casting_count\":";caster_survey::Button::value(out,castingCount);
        out<<",\"casting_references_victim\":"<<references<<",\"typed_member11\":";caster_survey::Button::value(out,typed);
        out<<",\"typed_proof_error\":"<<(typedError.empty()?"null":ba_catalog::quote(typedError))<<",\"casting_frame_collection\":\""<<frames
           <<"\",\"current_frame_collection\":\""<<currentFrames<<"\",\"frame_owner_matches\":"<<frameOwner<<",\"active_caster\":\""<<active
           <<"\",\"pending_commands\":"<<queued<<",\"left_held\":"<<left<<",\"right_held\":"<<right<<",\"click_reference\":"<<click
           <<",\"prior_completed_world\":"<<proof.world<<",\"prior_match\":"<<(proof.valid?ba_catalog::quote(proof.match):"null")
           <<",\"prior_normal_drain_complete\":"<<proof.valid<<",\"prior_next_sequence_before\":";
        if(proof.valid)out<<proof.nextBefore;else out<<"null";out<<",\"prior_next_sequence_after\":";if(proof.valid)out<<proof.nextAfter;else out<<"null";
        out<<",\"prior_complete_frame\":";if(proof.valid)out<<proof.completeFrame;else out<<"null";
        out<<",\"policy_result\":"<<ba_catalog::quote(allowed?(residue?"prior_drained_residue":"strict_empty"):"refused")
           <<",\"scope\":\"inactive_scratch_only_not_admission\",\"physicalUI\":false}";
        const auto text=out.str();require(text.size()<=8192,"UI scratch receipt bound");ba::log("MOBILE UI RESIDUE %s",text.c_str());notedWorld=owner.world;notedMatch=owner.match;
    }
    require(allowed,"UI preactivation scratch is neither strict-empty nor prospectively owned completed-drain residue");
}
static bool started(){return state().activations!=0;}
static bool queued(){return state().casts!=0;}
static bool aliases(Obj selector) {
    const auto& s=state();Obj server=ba_local::server();return s.selector&&s.selector->get()==selector&&s.source&&s.casting&&s.commands&&server&&
        ba::read<Obj>(selector,0x90)==s.source->get()&&ba::read<Obj>(selector,0x98)==s.casting->get()&&ba::read<Obj>(server,0x180)==s.commands->get();
}
static void guard(actors::State& owner,Obj selector,int frame) {
    owned(owner);const auto& s=state();require(s.world==owner.world&&s.match==owner.match&&frame>=145&&frame<280&&
        ba::read<int>(owner.simulation->get(),0xac)==frame&&aliases(selector),"UI cast observation owner/alias/frame differs");
    for(const auto& entry:std::initializer_list<std::pair<const char*,size_t>>{{"_isPointerDown",0x16c},{"_isContextPointerDown",0x16d},
        {"_doubleClickFirstClickReferenceUnitEntityId",0x128},{"_activeAbilityCaster",0x100},{"_appendCommands",0x118}})actors::field(selector,entry.first,entry.second);
    require(!ba_lan::stopped&&!ba_community::abortPending&&ba_lan::running&&!ba::read<bool>(selector,0x16c)&&
        !ba::read<bool>(selector,0x16d)&&ba::read<uint32_t>(selector,0x128)!=11,"UI cast crossed a gesture/stopped owner");
    const int count=pending(owner);require(count==0||(s.casts&&!s.drained&&count==1),"UI cast pending queue escaped its one-command phase");
    if(s.casts&&!s.drained) {
        require(selection::selectionIds(s.source->get())==s.queuedSource&&selection::selectionIds(s.casting->get())==s.queuedCasting,
            "UI cast lazy source98/selection changed before normal serialization");
        const auto now=GetTickCount64();require(now>=s.queuedTick&&(count==0||now-s.queuedTick<=1000),"UI cast normal drain exceeded one second");
    }
    if(s.casts)require(!ba::read<Obj>(selector,0x100),"original UI cast auto-Pop did not remain inactive");
}
static int32_t literal(Obj klass,const char* name) {
    Obj field=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(klass,name);
    require(field&&(ba::api<uint32_t(*)(Obj)>("il2cpp_field_get_flags")(field)&0x50u)==0x50u,"UI cast Perspective literal differs");
    int32_t value=0;ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(field,&value);return value;
}
static Perspective currentPerspective(actors::State& owner,Obj selector,Obj caster,int frame) {
    require(ba::klass(caster)==actors::type("Uncapped","TargetGroundOrUnitAbilityCaster"),"UI88 actual caster is outside the qualified Composite route");
    caster_survey::reference(selector,"_mapManager",0x50,"Uncapped","MapManager");Root manager(ba::read<Obj>(selector,0x50));
    actors::classIs(manager.get(),"Uncapped","MapManager");
    Obj getMap=actors::method(manager.get(),"get_CurrentMap",0,0x0600077e,0x845d70);FocusObservation::signature(getMap,false,actors::type("Uncapped","Map"));
    auto map=caster_survey::read(owner,getMap,manager.get());actors::classIs(map.get(),"Uncapped","Map");
    Obj get=actors::method(map.get(),"GetAlliancePerspective",1,0x0600075b,0x3db8f80);Obj enumClass=FocusObservation::returns(get);
    require(enumClass&&ba::api<bool(*)(Obj)>("il2cpp_class_is_enum")(enumClass)&&
        !strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(enumClass),"Perspective")&&
        original::parameterClass(get,0)==actors::type("System","UInt32"),"UI cast original map Perspective ABI differs");
    FocusObservation::signature(get,false,enumClass);original::checkValue(enumClass,4,"UI cast Perspective size differs");
    caster_survey::reference(owner.simulation->get(),"_localPlayer",0x90,"Uncapped","SimPlayer");Root player(ba::read<Obj>(owner.simulation->get(),0x90));actors::classIs(player.get(),"Uncapped","SimPlayer");
    caster_survey::reference(player.get(),"AllianceID",0x3c,"System","UInt32");Perspective proof;proof.alliance=ba::read<uint32_t>(player.get(),0x3c);proof.frame=frame;
    proof.normal=literal(enumClass,"Normal");proof.flipped=literal(enumClass,"Flipped");require(proof.normal==0&&proof.flipped==1,"UI cast original Perspective literals changed");
    void* args[]={&proof.alliance};auto mapValue=caster_survey::read(owner,get,map.get(),args);proof.map=caster_survey::scalar<int32_t>(mapValue.get(),enumClass);
    Obj composite=life::method(caster,"get_MapPerspective",0,0x0600006c,0x883ec0,enumClass,"\x8b\x41\x24\xc3\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc");
    auto value=caster_survey::read(owner,composite,caster);proof.composite=caster_survey::scalar<int32_t>(value.get(),enumClass);
    Obj queue=life::method(caster,"get_QueueCast",0,0x06000068,0x876150,actors::type("System","Boolean"),
        "\x0f\xb6\x41\x20\xc3\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc");
    auto queueValue=caster_survey::read(owner,queue,caster);proof.queue=caster_survey::scalar<bool>(queueValue.get(),actors::type("System","Boolean"));
    // These are independent observations BEFORE the original Minimap call.
    // Composite activation forwards the map to its children without writing this
    // independent parent cache. Normal serialization must prove the real Flip/Q32
    // command semantics; this fixture neither sets nor transforms either value.
    require((proof.map==proof.normal||proof.map==proof.flipped)&&
        (proof.composite==proof.normal||proof.composite==proof.flipped),"UI cast original Perspective enum value differs");return proof;
}
static std::string bits(const original::Vec3& value){uint32_t parts[3]{};std::memcpy(parts,&value,sizeof(value));return "["+std::to_string(parts[0])+","+std::to_string(parts[1])+","+std::to_string(parts[2])+"]";}
static void event(actors::State& owner,Obj selector,int frame,const char* name) {
    auto& s=state();owned(owner);Obj raw=ba::read<Obj>(selector,0x100);Root active(raw);require(!raw||active.get()==raw,"UI cast active observer root failed");
    std::optional<bool> related;std::optional<std::string> activeClass;
    if(active.get()){related=life::related(owner,selector,active.get());activeClass=caster_survey::className(active.get());}
    const auto sampled=stamp();s.lastFrame=frame;s.lastCaster=active.get();View view(owner,selector);
    const auto sourceIds=selection::selectionIds(s.source->get()),castingIds=selection::selectionIds(s.casting->get());
    s.lastCasting=castingIds;
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::boolalpha;
    out<<"{\"schema\":1,\"event\":"<<ba_catalog::quote(name)<<",\"world\":"<<s.world<<",\"match\":"<<ba_catalog::quote(s.match)
       <<",\"slot\":1,\"entity\":11,\"unit_type\":1,\"army\":1,\"frame\":"<<frame<<",\"tick_ms\":"<<GetTickCount64()<<",\"sampled_us\":"<<sampled
       <<",\"button_slot\":4,\"config_id\":88,\"ui_cast_type\":5,\"ui_group_kind\":2,\"smart_casting\":false"
       <<",\"retained_caster\":\""<<(s.caster?s.caster->get():nullptr)<<"\",\"retained_caster_class\":"<<(s.caster?ba_catalog::quote(s.casterClass):"null")
       <<",\"active_caster\":\""<<active.get()<<"\",\"active_caster_class\":"<<(activeClass?ba_catalog::quote(*activeClass):"null")
       <<",\"same_retained\":"<<(active.get()&&s.caster&&active.get()==s.caster->get())<<",\"is_unit_selection_related\":";caster_survey::Button::value(out,related);
    out<<",\"source_set\":\""<<s.source->get()<<"\",\"casting_set\":\""<<s.casting->get()<<"\",\"command_queue\":\""<<s.commands->get()
       <<"\",\"alias_storage_unchanged\":"<<aliases(selector)<<",\"source_ids\":"<<idsJson(sourceIds)<<",\"source_count\":"<<caster_survey::count(owner,s.source->get())
       <<",\"casting_ids\":"<<idsJson(castingIds)<<",\"casting_count\":"<<caster_survey::count(owner,s.casting->get())<<",\"pending_commands\":"<<pending(owner)
       <<",\"activation_calls\":"<<s.activations<<",\"cast_calls\":"<<s.casts<<",\"drain_observed\":"<<s.drained<<",\"next_sequence_before_cast\":";
    caster_survey::Button::value(out,s.nextBefore);out<<",\"next_sequence_after_drain\":";caster_survey::Button::value(out,s.nextAfter);
    out<<",\"cast_result\":";caster_survey::Button::value(out,s.result);
    out<<",\"origin\":"<<(s.origin?original::pointJson(*s.origin):"null")<<",\"origin_bits\":"<<(s.origin?bits(*s.origin):"null")
       <<",\"target\":"<<(s.target?original::pointJson(*s.target):"null")<<",\"target_bits\":"<<(s.target?bits(*s.target):"null")<<",\"origin_sampled_us\":";
    caster_survey::Button::value(out,s.originUs);out<<",\"minimap_call_begin_us\":";caster_survey::Button::value(out,s.callBegin);out<<",\"minimap_call_end_us\":";caster_survey::Button::value(out,s.callEnd);
    out<<",\"local_alliance\":";if(s.perspective)out<<s.perspective->alliance;else out<<"null";
    out<<",\"map_perspective\":";if(s.perspective)out<<s.perspective->map;else out<<"null";
    out<<",\"composite_map_perspective\":";if(s.perspective)out<<s.perspective->composite;else out<<"null";
    out<<",\"composite_queue_cast_before\":";if(s.perspective)out<<s.perspective->queue;else out<<"null";
    out<<",\"perspective_observed_frame\":";if(s.perspective)out<<s.perspective->frame;else out<<"null";
    out<<",\"map_perspective_source\":\"Uncapped.Map.GetAlliancePerspective\",\"composite_map_perspective_source\":\"Uncapped.CompositeAbilityCaster.get_MapPerspective\""
       <<",\"map_perspective_enum\":\"Uncapped.Map.Perspective\",\"map_perspective_enum_matches_composite\":";
    if(s.perspective)out<<true;else out<<"null";
    out<<",\"map_perspective_value_name\":"<<(s.perspective?ba_catalog::quote(s.perspective->map==s.perspective->normal?"Normal":"Flipped"):"null")
       <<",\"map_perspective_normal\":0,\"map_perspective_flipped\":1,\"selector_append\":"<<ba::read<bool>(selector,0x118)
       <<",\"left_held\":"<<ba::read<bool>(selector,0x16c)<<",\"right_held\":"<<ba::read<bool>(selector,0x16d)<<",\"click_reference\":"<<ba::read<uint32_t>(selector,0x128)
       <<",\"native_identity_present\":"<<view.nativePresent<<",\"native_state\":";caster_survey::Button::value(out,view.nativeValue);
    out<<",\"current_actor\":\""<<view.current<<"\",\"current_admitted\":"<<view.context.admitted(view.current)<<",\"original_incarnation\":"<<mobile::state().originalToken
       <<",\"current_incarnation\":"<<token(view.context,view.current)<<",\"route\":\"original_ui_minimap\",\"original_callback\":\"Uncapped.UnitSelector.ProcessActiveAbilityCaster_Minimap\""
       <<",\"original_callback_token\":100672042,\"originalCtor\":false,\"extra_pop_calls\":0,\"extra_to_proto_calls\":0,\"manual_caster_set_calls\":0,\"direct_factory_calls\":0,\"physicalUI\":false}";
    const auto text=out.str();require(text.size()<=8192,"UI cast receipt bound");ba::log("MOBILE UI CAST %s",text.c_str());
}
static void activate(actors::State& owner,Obj selector,int frame) {
    auto& s=state();require(!s.world&&frame==145&&ba::lanSlot()==1,"UI cast activation requires fresh guest145");preactivation(owner,selector,11);
    if(owner.world==1)certificate()=ResidueCertificate{};
    auto mapping=life::findMapping(owner,selector);s.world=owner.world;s.match=owner.match;s.mapping=mapping.row;
    s.selector=std::make_unique<Root>(selector);s.source=std::make_unique<Root>(ba::read<Obj>(selector,0x90));s.casting=std::make_unique<Root>(ba::read<Obj>(selector,0x98));
    Obj server=ba_local::server();actors::field(server,"_queuedInputCommands",0x180);s.commands=std::make_unique<Root>(ba::read<Obj>(server,0x180));
    require(s.selector->get()==selector&&s.source->get()&&s.casting->get()&&s.commands->get(),"UI cast observer root allocation failed");
    caster_survey::reference(selector,"_activeAbilityCaster",0x100,"Uncapped","IAbilityCaster");caster_survey::reference(selector,"_appendCommands",0x118,"System","Boolean");
    guard(owner,selector,frame);View view(owner,selector);require(view.current&&view.context.admitted(view.current)&&token(view.context,view.current)==mobile::state().originalToken&&
        ba::read<Obj>(view.current,0x158)&&!ba::read<bool>(view.current,0x160)&&view.nativePresent&&view.nativeValue&&*view.nativeValue!=6&&
        selection::selectionIds(s.source->get())==std::vector<uint32_t>{11}&&caster_survey::count(owner,s.source->get())==1,"UI cast source145 is not current initialized admitted11");
    Obj activationClass=actors::type("Uncapped","ButtonActivationInfo");Obj info=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(activationClass,"get_HotkeyActivation",0);
    require(info&&ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_token")(info)==0x060015c2&&ba::read<Obj>(info,0)==ba::native<Obj>(0x3e9b750)&&
        ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(info)==0,"UI cast original HotkeyActivation overload differs");
    FocusObservation::signature(info,true,activationClass);actors::guard(0x3e9b750,"\x48\x83\xec\x28\x80\x3d\x05\xec\xfb\x02\x00\x75\x18\x48\x8d\x0d",16);
    auto activation=caster_survey::read(owner,info,nullptr);actors::classIs(activation.get(),"Uncapped","ButtonActivationInfo");
    Obj activationType=caster_survey::fieldType(activation.get(),"<Type>k__BackingField",0x10,actors::type("Uncapped","ButtonActivationType"));original::checkValue(activationType,4,"UI cast activation enum size differs");
    caster_survey::reference(activation.get(),"<Count>k__BackingField",0x14,"System","Int32");require(ba::read<int32_t>(activation.get(),0x10)==1&&ba::read<int32_t>(activation.get(),0x14)==1,"UI cast HotkeyActivation type/count differs");
    event(owner,selector,frame,"before_activation");Obj perform=life::method(mapping.button->get(),"PerformButtonAction",1,0x060016ac,0x3eb0c00,actors::type("System","Void"),
        "\x48\x89\x5c\x24\x08\x57\x48\x83\xec\x30\x80\x3d\x0b\x98\xfa\x02");
    require(original::parameterClass(perform,0)==activationClass,"UI cast Perform reference parameter differs");void* args[]={activation.get()};
    ++s.activations;caster_survey::read(owner,perform,mapping.button->get(),args);Obj current=ba::read<Obj>(selector,0x100);
    if(current){s.caster=std::make_unique<Root>(current);require(s.caster->get()==current,"UI cast retained caster GC root failed");s.casterClass=caster_survey::className(current);s.perspective=currentPerspective(owner,selector,current,frame);}
    event(owner,selector,frame,"after_activation");guard(owner,selector,frame);require(current&&s.caster&&life::related(owner,selector,current),"UI cast original activation did not retain a unit-related caster");
}
static void observe(actors::State& owner,Obj selector,int frame,const char* stage=nullptr) {
    auto& s=state();if(!s.activations)return;guard(owner,selector,frame);
    if(stage||s.lastFrame!=frame||s.lastCaster!=ba::read<Obj>(selector,0x100))event(owner,selector,frame,stage?stage:"snapshot");
    if(!s.casts)require(s.caster&&ba::read<Obj>(selector,0x100)==s.caster->get(),"UI cast retained caster was cleared or replaced before180");
    if(s.casts&&!s.drained&&pending(owner)==0) {
        require(s.nextBefore&&*s.nextBefore<(std::numeric_limits<uint64_t>::max)(),"UI cast next sequence cannot advance");
        const auto next=ba_lan::originalCommands.sequence();require(next==*s.nextBefore+1,"UI cast queue emptied without exactly one normal batch serialization");
        s.nextAfter=next;s.drained=true;event(owner,selector,frame,"normal_drain_observed");
    }
}
static void cast(actors::State& owner,Obj selector,int frame) {
    auto& s=state();observe(owner,selector,frame);require(frame==180&&s.activations==1&&!s.casts,"UI cast must run once at180");
    auto mapping=life::findMapping(owner,selector);s.mapping=mapping.row;View view(owner,selector);
    require(view.current&&view.context.admitted(view.current)&&token(view.context,view.current)==mobile::state().originalToken&&view.nativePresent&&view.nativeValue&&*view.nativeValue!=6&&
        ba::read<Obj>(view.current,0x158)&&!ba::read<bool>(view.current,0x160)&&selection::selectionIds(s.source->get())==std::vector<uint32_t>{11}&&
        caster_survey::count(owner,s.source->get())==1&&pending(owner)==0,"UI cast180 source is not current initialized admitted11/Count1");
    s.perspective=currentPerspective(owner,selector,s.caster->get(),frame);require(!s.perspective->queue&&!ba::read<bool>(selector,0x118),"UI cast requires original nonqueued/nonappend settings");
    s.origin=original::actualPosition(owner,view.current);s.originUs=stamp();s.target=original::Vec3{s.origin->x+16.f,s.origin->y,s.origin->z};original::finite(*s.target);
    Obj vector=actors::type("UnityEngine","Vector3");original::checkValue(vector,12,"UI cast original Vector3 size differs");
    const char* names[]={"x","y","z"};for(size_t i=0;i<3;++i){Obj field=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(vector,names[i]);
        require(field&&ba::api<size_t(*)(Obj)>("il2cpp_field_get_offset")(field)==0x10+i*4&&
            ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(field))==actors::type("System","Single"),"UI cast Vector3 closed field layout differs");}
    Obj method=life::method(selector,"ProcessActiveAbilityCaster_Minimap",1,0x0600222a,0x3bf4260,actors::type("System","Boolean"),
        "\x48\x89\x74\x24\x20\x57\x48\x81\xec\xa0\x00\x00\x00\x80\x3d\xb6");
    require(original::parameterClass(method,0)==vector,"UI cast Minimap Vector3 parameter differs");s.nextBefore=ba_lan::originalCommands.sequence();require(*s.nextBefore>0&&*s.nextBefore<(std::numeric_limits<uint64_t>::max)(),"UI cast next sequence invalid");
    event(owner,selector,frame,"before_cast");original::Vec3 argument=*s.target;void* args[]={&argument};s.callBegin=stamp();++s.casts;
    auto returned=caster_survey::read(owner,method,selector,args);s.callEnd=stamp();s.result=caster_survey::scalar<bool>(returned.get(),actors::type("System","Boolean"));s.queuedTick=GetTickCount64();
    s.queuedSource=selection::selectionIds(s.source->get());s.queuedCasting=selection::selectionIds(s.casting->get());event(owner,selector,frame,"after_cast_queued");
    require(*s.callEnd>*s.callBegin&&*s.result&&!std::memcmp(&argument,&*s.target,sizeof(argument))&&pending(owner)==1&&!ba::read<Obj>(selector,0x100)&&
        s.queuedSource==std::vector<uint32_t>{11}&&s.queuedCasting==std::vector<uint32_t>{11}&&caster_survey::count(owner,s.casting->get())==1,
        "original UI Minimap did not produce the bounded queued88/auto-Pop/scratch witness");guard(owner,selector,frame);
}
static void complete(actors::State& owner,Obj selector,int frame){observe(owner,selector,frame);auto& s=state();require(frame>=260&&s.activations==1&&s.casts==1&&s.drained&&!s.finished&&
    pending(owner)==0&&!ba::read<Obj>(selector,0x100),"UI cast completion lacks its normal drain");event(owner,selector,frame,"complete");s.finished=true;}
}
