#pragma once
// Included inside the owned mobile smoke namespace, after its observation helpers.
// No standard headers here: the containing TU supplies them at global scope.
// This reads original UI getters only. It never asks the caster factory for an
// instance: that lookup can instantiate/cache a caster even without activation.
namespace caster_survey {
static Obj fieldType(Obj object,const char* name,size_t offset,Obj expected=nullptr) {
    actors::field(object,name,offset);
    Obj result=ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
        ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(ba::field(object,name)));
    require(result&&(!expected||result==expected),"caster survey original field type differs");return result;
}
static void reference(Obj object,const char* name,size_t offset,const char* space,const char* typeName) {
    fieldType(object,name,offset,actors::type(space,typeName));
}
static Obj getter(Obj object,const char* name,unsigned count,uint32_t token,uintptr_t rva,Obj result,const char* bytes) {
    Obj info=actors::method(object,name,count,token,rva);FocusObservation::signature(info,false,result);
    if(bytes)actors::guard(rva,bytes,16);return info;
}
struct Value {
    std::unique_ptr<Root> root;
    Value(actors::State& owner,Obj info,Obj object,void** args) {
        Obj raw=actors::invoke(info,object,args);root=std::make_unique<Root>(raw);
        require(!raw||root->get()==raw,"caster survey getter result GC root allocation failed");
        owned(owner);require(!ba_lan::stopped&&!ba_community::abortPending&&ba_lan::running,
            "caster survey original getter stopped its owner");
    }
    Obj get()const{return root->get();}
};
static Value read(actors::State& owner,Obj info,Obj object,void** args=nullptr){return Value(owner,info,object,args);}
template<class T> static T scalar(Obj boxed,Obj expected) {
    require(boxed&&ba::klass(boxed)==expected,"caster survey boxed getter class differs");
    original::checkValue(expected,static_cast<int32_t>(sizeof(T)),"caster survey boxed getter size differs");
    return actors::unbox<T>(boxed);
}
static std::string classText(Obj klass) {
    const char* space=ba::api<const char*(*)(Obj)>("il2cpp_class_get_namespace")(klass);
    const char* name=ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(klass);
    require(space&&name&&strlen(space)<256&&strlen(name)<256,"caster survey class text bound");
    return std::string(space)+"."+name;
}
static std::string className(Obj object){return classText(ba::klass(object));}
static bool assignable(Obj object,const char* name) {
    return object&&ba::api<bool(*)(Obj,Obj)>("il2cpp_class_is_assignable_from")(actors::type("Uncapped",name),ba::klass(object));
}
static int count(actors::State& owner,Obj set) {
    actors::classIs(set,"Uncapped.Collections","UnitSelectionSet");
    reference(set,"_simFrames",0x48,"Uncapped.Collections.ComponentBuffers","IReadOnlySimFrameCollection");
    require(ba::read<Obj>(set,0x48)==ba::read<Obj>(owner.simulation->get(),0x148),"caster survey mapped frame owner differs");
    Obj info=getter(set,"get_Count",0,0x060025b5,0x3c68f00,actors::type("System","Int32"),
        "\x48\x89\x5c\x24\x10\x48\x89\x4c\x24\x08\x57\x48\x83\xec\x70\x48");
    auto result=read(owner,info,set);const int value=scalar<int32_t>(result.get(),actors::type("System","Int32"));
    require(value>=0&&value<=8192,"caster survey original Count bound");return value;
}
static bool unityTruth(actors::State& owner,Obj object) {
    Obj info=actors::method(object,"op_Implicit",1,0x06000f04,0x508fda0);
    FocusObservation::signature(info,true,actors::type("System","Boolean"));
    require(original::parameterClass(info,0)==actors::type("UnityEngine","Object"),"caster survey Unity truth parameter differs");
    void* args[]={object};auto result=read(owner,info,nullptr,args);return scalar<bool>(result.get(),actors::type("System","Boolean"));
}
struct Key {uint32_t id=0;std::string observation;};
static Key configKey(actors::State& owner,Obj config) {
    require(assignable(config,"AbilityConfig"),"caster survey config is not AbilityConfig");
    Obj keyClass=fieldType(config,"Key",0x34);Obj keyField=ba::field(config,"Key");
    const char* name=ba::api<const char*(*)(Obj)>("il2cpp_field_get_name")(keyField);
    Obj declaring=ba::api<Obj(*)(Obj)>("il2cpp_field_get_parent")(keyField);
    require(name&&!strcmp(name,"Key")&&declaring==actors::type("Uncapped","AbilityConfig")&&
        !strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_namespace")(keyClass),"Uncapped")&&
        !strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(keyClass),"IntKey`1"),
        "caster survey original AbilityConfig.Key declaration differs");
    original::checkValue(keyClass,4,"caster survey closed IntKey<Ability> ABI differs");
    Root key(ba::api<Obj(*)(Obj,Obj)>("il2cpp_field_get_value_object")(keyField,config));owned(owner);
    require(key.get()&&ba::klass(key.get())==keyClass,"caster survey boxed Key differs from exact declared field type");
    // This original generic getter has no statically established closed RVA.
    // Preserve its actual closed MethodInfo and invoke the UNBOXED value payload.
    Obj info=getter(key.get(),"get_ID",0,0x0600151a,0,actors::type("System","UInt32"),nullptr);
    Obj payload=ba::api<Obj(*)(Obj)>("il2cpp_object_unbox")(key.get());require(payload,"caster survey Key payload missing");
    auto result=read(owner,info,payload);Key answer;answer.id=scalar<uint32_t>(result.get(),actors::type("System","UInt32"));
    // Field token04000d92 is STATIC original metadata provenance. The shipped
    // SDK does not export field_get_token; no FieldInfo layout is guessed.
    answer.observation="{\"declaring_class\":"+ba_catalog::quote(classText(declaring))+",\"field_name\":\"Key\",\"field_offset\":"+
        std::to_string(ba::api<size_t(*)(Obj)>("il2cpp_field_get_offset")(keyField))+",\"declared_class\":"+ba_catalog::quote(classText(keyClass))+
        ",\"boxed_class\":"+ba_catalog::quote(className(key.get()))+",\"declared_boxed_class_equal\":true,\"value_size\":4,"+
        "\"getter_token\":"+std::to_string(ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_token")(info))+
        ",\"getter_rva_guarded\":false,\"field_token_source\":\"static_original_metadata\",\"closed_argument_source\":\"original_AbilityConfig.Key_metadata\"}";
    return answer;
}
struct Button {
    size_t index=0;bool present=false,lookup=false,candidate=false;
    std::optional<int32_t> slot,mappedCount,kind,castType;
    std::optional<bool> valid,hasCasters,groupPresent,groupLive,groupMatches,smart;
    std::optional<uint32_t> castMethod,configId;
    std::optional<bool> configPresent;
    std::optional<std::string> buttonClass,groupClass;
    std::optional<std::string> keyObservation;
    std::optional<std::vector<uint32_t>> mappedIds;
    std::string reason="null_button";
    template<class T> static void value(std::ostream& out,const std::optional<T>& v){if(v)out<<*v;else out<<"null";}
    static void text(std::ostream& out,const std::optional<std::string>& v){out<<(v?ba_catalog::quote(*v):"null");}
    void json(std::ostream& out)const {
        out<<"{\"index\":"<<index<<",\"present\":"<<present<<",\"button_class\":";text(out,buttonClass);
        out<<",\"slot\":";value(out,slot);out<<",\"valid_button\":";value(out,valid);
        out<<",\"mapped_ids\":"<<(mappedIds?idsJson(*mappedIds):"null")<<",\"mapped_count\":";value(out,mappedCount);
        out<<",\"has_mapped_casters\":";value(out,hasCasters);out<<",\"group_present\":";value(out,groupPresent);
        out<<",\"group_class\":";text(out,groupClass);out<<",\"group_unity_truth\":";value(out,groupLive);
        out<<",\"panel_group_matches\":";value(out,groupMatches);out<<",\"group_kind\":";value(out,kind);
        out<<",\"cast_type\":";value(out,castType);out<<",\"cast_type_method_token\":";value(out,castMethod);
        out<<",\"smart_casting\":";value(out,smart);out<<",\"config_lookup_performed\":"<<lookup<<",\"config_present\":";value(out,configPresent);
        out<<",\"config_id\":";value(out,configId);out<<",\"config_key_observation\":"<<(keyObservation?*keyObservation:"null");
        out<<",\"candidate\":"<<candidate<<",\"candidate_reason\":"<<ba_catalog::quote(reason)<<'}';
    }
};
static Button inspect(actors::State& owner,Obj selector,Obj panel,Obj array,size_t index) {
    Button row;row.index=index;Obj rawButton=ba::read<Obj>(array,0x20+index*sizeof(Obj));Root button(rawButton);
    require(!rawButton||button.get()==rawButton,"caster survey button GC root allocation failed");if(!button.get())return row;
    require(assignable(button.get(),"AbilityButtonAction"),"caster survey active array button type differs");
    row.present=true;row.buttonClass=className(button.get());row.reason="unmapped";
    reference(button.get(),"_abilityInputHandler",0x180,"Uncapped","IAbilityInputHandler");
    reference(button.get(),"_simulation",0x198,"Uncapped","Simulation");
    require(ba::read<Obj>(button.get(),0x180)==selector&&ba::read<Obj>(button.get(),0x198)==owner.simulation->get(),
        "caster survey actual button belongs to another selector/simulation");
    Obj slotType=fieldType(button.get(),"_slot",0x70,actors::type("Uncapped","AbilityButton"));
    require(ba::api<bool(*)(Obj)>("il2cpp_class_is_enum")(slotType),"caster survey button slot is not its enum");
    Obj slotInfo=getter(button.get(),"get_Slot",0,0x060016a3,0xb2b240,slotType,"\x8b\x41\x70\xc3\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc");
    auto slot=read(owner,slotInfo,button.get());row.slot=scalar<int32_t>(slot.get(),slotType);
    require(*row.slot==ba::read<int32_t>(button.get(),0x70),"caster survey slot getter/field mismatch");
    reference(button.get(),"_mappedAbilityGroup",0xb8,"Uncapped","AbilityGroup");
    Obj groupInfo=getter(button.get(),"get_MappedAbilityGroup",0,0x060016a4,0x81a9a0,actors::type("Uncapped","AbilityGroup"),
        "\x48\x8b\x81\xb8\x00\x00\x00\xc3\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc");
    auto group=read(owner,groupInfo,button.get());row.groupPresent=group.get()!=nullptr;
    require(group.get()==ba::read<Obj>(button.get(),0xb8),"caster survey mapped group getter/field mismatch");
    if(*row.slot>=0&&*row.slot<12) {
        Obj validInfo=getter(panel,"IsValidButton",1,0x060016f9,0x3b415e0,actors::type("System","Boolean"),
            "\x48\x89\x5c\x24\x08\x57\x48\x83\xec\x20\x80\x3d\x20\x74\x31\x03");
        require(original::parameterClass(validInfo,0)==slotType,"caster survey panel slot parameter differs");
        int32_t actualSlot=*row.slot;void* args[]={&actualSlot};auto valid=read(owner,validInfo,panel,args);row.valid=scalar<bool>(valid.get(),actors::type("System","Boolean"));
        if(*row.valid) {
            Obj mapped=getter(panel,"GetAbilityGroup",1,0x060016f8,0x3b41510,actors::type("Uncapped","AbilityGroup"),
                "\x48\x89\x5c\x24\x08\x57\x48\x83\xec\x20\x80\x3d\xef\x74\x31\x03");
            require(original::parameterClass(mapped,0)==slotType,"caster survey panel group parameter differs");
            auto actual=read(owner,mapped,panel,args);row.groupMatches=actual.get()==group.get();
        }
    } else row.reason="unsupported_slot"; // Record, never index the panel using an invalid enum.
    reference(button.get(),"_mappedCasters",0xb0,"Uncapped.Collections","UnitSelectionSet");Obj rawCasters=ba::read<Obj>(button.get(),0xb0);Root casters(rawCasters);
    require(!rawCasters||casters.get()==rawCasters,"caster survey mapped caster GC root allocation failed");
    if(casters.get()) {
        row.mappedIds=selection::selectionIds(casters.get());row.mappedCount=count(owner,casters.get());
        Obj info=getter(button.get(),"get_HasMappedCasters",0,0x060016b7,0x3eb1c80,actors::type("System","Boolean"),
            "\x48\x83\xec\x28\x48\x8b\x89\xb0\x00\x00\x00\x48\x85\xc9\x74\x11");
        auto result=read(owner,info,button.get());row.hasCasters=scalar<bool>(result.get(),actors::type("System","Boolean"));
        require(*row.hasCasters==(*row.mappedCount>0),"caster survey HasMappedCasters/Count mismatch");
    }
    if(group.get()) {
        require(assignable(group.get(),"AbilityGroup"),"caster survey mapped group class differs");row.groupClass=className(group.get());row.groupLive=unityTruth(owner,group.get());
        Obj kindType=fieldType(group.get(),"AbilityGroupType",0x38,actors::type("Uncapped","AbilityGroupType"));original::checkValue(kindType,4,"caster survey group kind ABI differs");
        row.kind=ba::read<int32_t>(group.get(),0x38);reference(group.get(),"SmartCasting",0x3d,"System","Boolean");row.smart=ba::read<bool>(group.get(),0x3d);
        if(*row.groupLive) {
            Obj castClass=actors::type("Uncapped","AbilityCastType");
            require(ba::api<bool(*)(Obj)>("il2cpp_class_is_enum")(castClass),"caster survey cast type enum differs");
            Obj instant=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(castClass,"Instant");
            require(instant&&(ba::api<uint32_t(*)(Obj)>("il2cpp_field_get_flags")(instant)&0x50u)==0x50u,
                "caster survey Instant enum literal differs");int32_t instantValue=0;
            ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(instant,&instantValue);
            require(instantValue==2,"caster survey original Instant enum value differs");
            Obj base=getter(group.get(),"get_CastType",0,0x06000177,0x86f7d0,castClass,"\x8b\x41\x54\xc3\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc");
            Obj actual=ba::api<Obj(*)(Obj,Obj)>("il2cpp_object_get_virtual_method")(group.get(),base);require(actual,"caster survey virtual cast getter missing");
            const auto tokenValue=ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_token")(actual);
            require(tokenValue==0x06000177||tokenValue==0x06000193,"caster survey unsupported original cast getter override");
            const auto rva=tokenValue==0x06000177?uintptr_t{0x86f7d0}:uintptr_t{0x37b51d0};
            require(ba::read<Obj>(actual,0)==ba::native<Obj>(rva)&&ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(actual)==0,
                "caster survey virtual cast getter pointer/arity differs");FocusObservation::signature(actual,false,castClass);
            if(tokenValue==0x06000193)actors::guard(rva,"\x48\x8b\x41\x70\x48\x85\xc0\x74\x04\x8b\x40\x58\xc3\xb8\x02\x00",16);
            auto result=read(owner,actual,group.get());row.castType=scalar<int32_t>(result.get(),castClass);row.castMethod=tokenValue;
            require(*row.castType>=2&&*row.castType<=10,"caster survey unknown original cast type value");
        }
    }
    if(row.hasCasters.value_or(false)&&group.get()&&row.groupLive.value_or(false)) {
        Obj info=getter(button.get(),"GetMappedAbilityConfig",0,0x060016a6,0x3eaff10,actors::type("Uncapped","AbilityConfig"),
            "\x48\x89\x5c\x24\x10\x48\x89\x74\x24\x18\x48\x89\x7c\x24\x20\x41");
        row.lookup=true;auto config=read(owner,info,button.get());row.configPresent=config.get()!=nullptr;
        if(config.get()){const auto key=configKey(owner,config.get());row.configId=key.id;row.keyObservation=key.observation;}
    }
    row.candidate=row.valid.value_or(false)&&row.groupMatches.value_or(false)&&row.groupLive.value_or(false)&&
        row.hasCasters.value_or(false)&&row.mappedCount==1&&row.mappedIds&&*row.mappedIds==std::vector<uint32_t>{11}&&
        row.configId&&(*row.configId==12||*row.configId==14)&&row.castType&&*row.castType!=2&&row.smart==false;
    if(row.candidate)row.reason="noninstant_ui_mapping_only";else if(row.reason!="unsupported_slot")row.reason="ineligible_mapping";
    return row;
}
static void observe(actors::State& owner,Obj selector,int frame) {
    owned(owner);require(ba::lanSlot()==1&&frame==145,"caster survey requires guest publication145");idle(owner,selector,11);
    const auto begin=stamp();const auto tick=GetTickCount64();Root selectorRoot(selector),server(ba_local::server());
    require(selectorRoot.get()==selector,"caster survey selector GC root allocation failed");
    View before(owner,selector);require(before.current&&before.context.admitted(before.current),"caster survey current admitted unit11 missing");Root actor(before.current);
    const auto identity=actors::resident(actor.get());const auto observedToken=token(before.context,actor.get());
    const auto physical=before.native.identity(11);
    const auto known=owner.admission.entities.find(11);require(identity.entityId==11&&identity.unitType==1&&identity.armyId==1&&
        physical&&physical->entityId==11&&physical->unitType==1&&physical->armyId==1&&
        observedToken&&known!=owner.admission.entities.end()&&known->second.type==1&&known->second.army==1&&known->second.incarnation==observedToken,
        "caster survey current/canonical identity differs");
    const auto confirmedIncarnation=known->second.incarnation;
    actors::field(actor.get(),"_componentData",0x158);actors::field(actor.get(),"<DeadToTheSim>k__BackingField",0x160);
    require(ba::read<Obj>(actor.get(),0x158)&&!ba::read<bool>(actor.get(),0x160)&&before.nativeValue&&*before.nativeValue!=6,
        "caster survey unit11 is not initialized/native alive");
    Root source(ba::read<Obj>(selector,0x90)),preview(ba::read<Obj>(selector,0x88)),casting(ba::read<Obj>(selector,0x98));
    const auto sourceIds=selection::selectionIds(source.get()),previewIds=selection::selectionIds(preview.get()),castingIds=selection::selectionIds(casting.get());
    const int sourceCount=count(owner,source.get()),queued=pending(owner);require(sourceIds==std::vector<uint32_t>{11}&&sourceCount==1&&queued==0,"caster survey source/queue precondition differs");
    reference(selector,"_simulation",0x138,"Uncapped","Simulation");reference(selector,"_unitManager",0x40,"Uncapped","UnitManager");
    require(ba::read<Obj>(selector,0x138)==owner.simulation->get()&&ba::read<Obj>(selector,0x40)==owner.manager->get(),"caster survey selector owner chain differs");
    reference(selector,"_commandPanel",0xc8,"Uncapped","CommandPanel");Root panel(ba::read<Obj>(selector,0xc8));actors::classIs(panel.get(),"Uncapped","CommandPanel");
    reference(panel.get(),"_unitSelector",0xc0,"Uncapped","UnitSelector");reference(panel.get(),"_simulation",0xb0,"Uncapped","Simulation");
    reference(panel.get(),"_unitManager",0xc8,"Uncapped","UnitManager");reference(panel.get(),"_gameServerIntegration",0xb8,"Uncapped","GameServerIntegration");
    require(ba::read<Obj>(panel.get(),0xc0)==selector&&ba::read<Obj>(panel.get(),0xb0)==owner.simulation->get()&&
        ba::read<Obj>(panel.get(),0xc8)==owner.manager->get()&&ba::read<Obj>(panel.get(),0xb8)==server.get(),"caster survey panel owner chain differs");
    reference(panel.get(),"_activeGrid",0x90,"Uncapped","IAbilityGrid");Root grid(ba::read<Obj>(panel.get(),0x90));
    Obj arrayClass=fieldType(panel.get(),"_activeAbilityButtonActions",0xa8);Obj rawArray=ba::read<Obj>(panel.get(),0xa8);Root array(rawArray);size_t length=0;
    require(!rawArray||array.get()==rawArray,"caster survey active array GC root allocation failed");
    require(ba::api<int(*)(Obj)>("il2cpp_class_get_rank")(arrayClass)==1&&
        ba::api<Obj(*)(Obj)>("il2cpp_class_get_element_class")(arrayClass)==actors::type("Uncapped","AbilityButtonAction")&&
        ba::api<int(*)(Obj)>("il2cpp_type_get_type")(ba::api<Obj(*)(Obj)>("il2cpp_class_get_type")(arrayClass))==0x1d,
        "caster survey active button array ABI differs");
    if(array.get()){require(ba::klass(array.get())==arrayClass,"caster survey active array declared/actual type differs");length=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(array.get());}
    require(length<=12,"caster survey active button array exceeds supported diagnostic cap12; not truncated");
    std::vector<Button> rows;for(size_t i=0;i<length;++i)rows.push_back(inspect(owner,selector,panel.get(),array.get(),i));
    owned(owner);View after(owner,selector);const int sourceAfter=count(owner,source.get()),queuedAfter=pending(owner);
    require(ba_local::server()==server.get()&&after.current==actor.get()&&after.context.admitted(actor.get())&&token(after.context,actor.get())==observedToken&&
        ba::read<int>(owner.simulation->get(),0xac)==frame&&ba::read<Obj>(selector,0xc8)==panel.get()&&ba::read<Obj>(panel.get(),0xa8)==array.get()&&
        ba::read<Obj>(panel.get(),0x90)==grid.get()&&ba::read<Obj>(selector,0x90)==source.get()&&ba::read<Obj>(selector,0x88)==preview.get()&&
        ba::read<Obj>(selector,0x98)==casting.get()&&!ba::read<Obj>(selector,0x100)&&sourceAfter==sourceCount&&queuedAfter==queued&&
        ba::read<Obj>(actor.get(),0x158)&&!ba::read<bool>(actor.get(),0x160)&&after.nativeValue==before.nativeValue&&
        selection::selectionIds(source.get())==sourceIds&&selection::selectionIds(preview.get())==previewIds&&selection::selectionIds(casting.get())==castingIds,
        "caster survey read-only owner/selection/queue snapshot changed");
    const auto end=stamp();require(end>begin,"caster survey QPC bracket did not advance");std::ostringstream out;out<<std::boolalpha;
    out<<"{\"schema\":1,\"event\":\"mapped_buttons\",\"route\":\"owned_active_buttons_original_getters\",\"world\":"<<state().world
       <<",\"match\":"<<ba_catalog::quote(state().match)<<",\"slot\":1,\"entity\":11,\"unit_type\":1,\"army\":1,\"frame\":"<<frame
       <<",\"tick_ms\":"<<tick<<",\"sample_begin_us\":"<<begin<<",\"sample_end_us\":"<<end<<",\"incarnation\":"<<observedToken
       <<",\"confirmed_incarnation\":"<<confirmedIncarnation<<",\"current_actual_entity\":11,\"current_actual_type\":1,\"current_actual_army\":1"
       <<",\"current_admitted\":true,\"current_initialized\":true,\"current_native_state\":"<<*before.nativeValue
       <<",\"source_ids_before\":"<<idsJson(sourceIds)<<",\"source_ids_after\":"<<idsJson(selection::selectionIds(source.get()))
       <<",\"preview_ids_before\":"<<idsJson(previewIds)<<",\"preview_ids_after\":"<<idsJson(selection::selectionIds(preview.get()))
       <<",\"casting_ids_before\":"<<idsJson(castingIds)<<",\"casting_ids_after\":"<<idsJson(selection::selectionIds(casting.get()))
       <<",\"source_count_before\":"<<sourceCount<<",\"source_count_after\":"<<sourceAfter<<",\"pending_before\":"<<queued<<",\"pending_after\":"<<queuedAfter
       <<",\"active_caster_before\":null,\"active_caster_after\":null,\"active_array_present\":"<<(array.get()!=nullptr)<<",\"active_array_count\":"<<length<<",\"buttons\":[";
    for(size_t i=0;i<rows.size();++i){if(i)out<<',';rows[i].json(out);}out<<"],\"eligible_slots\":[";bool first=true;
    for(const auto& row:rows)if(row.candidate){if(!first)out<<',';first=false;out<<*row.slot;}
    out<<"],\"settings_scope\":\"AbilityGroup.SmartCasting\",\"activation_performed\":false,\"caster_class_observed\":null}";
    const auto text=out.str();require(text.size()<=65536,"caster survey value receipt exceeds diagnostic cap; not truncated");ba::log("MOBILE CASTER SURVEY %s",text.c_str());
}
}
