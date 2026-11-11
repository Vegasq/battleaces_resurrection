#pragma once
// Include inside ba_prediction_actors after its reflection and click helpers.
// This reads raw cached membership. GetUnitsOfType's iterator filters dead IDs
// and therefore cannot certify the cache left behind by an original death.
static Obj clickSelectionReturn(Obj info) {
    Obj value=ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(info);
    require(value && !ba::api<bool(*)(Obj)>("il2cpp_type_is_byref")(value),
            "click selection byref return differs");
    return ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(value);
}
static void clickSelectionSignature(Obj info,Obj result) {
    uint32_t implementation=0;
    require(!(ba::api<uint32_t(*)(Obj,uint32_t*)>("il2cpp_method_get_flags")(info,&implementation)&0x10u) &&
            clickSelectionReturn(info)==result,"click selection original instance signature differs");
}
static Obj clickSelectionDeclaredField(Obj object,const char* name,size_t offset) {
    field(object,name,offset);Obj member=ba::field(object,name);
    require(member && ba::api<Obj(*)(Obj)>("il2cpp_field_get_parent")(member)==ba::klass(object) &&
            !(ba::api<uint32_t(*)(Obj)>("il2cpp_field_get_flags")(member)&0x10u),
            "click selection original field owner differs");
    Obj value=ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(member);
    require(value && !ba::api<bool(*)(Obj)>("il2cpp_type_is_byref")(value),
            "click selection byref field differs");
    return ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(value);
}
static bool clickSelectionClassName(Obj value,const char* space,const char* name) {
    if(!value)return false;
    const char* actualSpace=ba::api<const char*(*)(Obj)>("il2cpp_class_get_namespace")(value);
    const char* actualName=ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(value);
    return actualSpace && actualName && !strcmp(actualSpace,space) && !strcmp(actualName,name);
}
static Obj clickSelectionClassMethod(Obj klass,const char* name,uint32_t token) {
    Obj found=nullptr;void* iterator=nullptr;
    while(Obj info=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(klass,&iterator)) {
        const char* actual=ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(info);
        if(!actual || strcmp(actual,name) ||
           ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_token")(info)!=token ||
           ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(info))continue;
        require(!found && ba::read<Obj>(info,0),"click selection original iterator overload differs");
        found=info;
    }
    require(found,"click selection original iterator method missing");return found;
}
static bool clickSelectionShape(Obj selection,uint32_t entity,uint32_t unitType,bool present) {
    classIs(selection,"Uncapped.Collections","UnitSelectionSet");
    Root retained(selection);
    const Obj selectionClass=ba::klass(selection);
    const Obj ledClass=clickSelectionDeclaredField(selection,"_allUnits",0x18);
    const Obj dictionaryClass=clickSelectionDeclaredField(selection,"_subsetsByType",0x20);
    require(clickSelectionClassName(ledClass,"","LedUnitSet") &&
            ba::api<Obj(*)(Obj)>("il2cpp_class_get_declaring_type")(ledClass)==selectionClass &&
            clickSelectionClassName(dictionaryClass,"System.Collections.Generic","Dictionary`2"),
            "click selection declared cache classes differ");
    Root all(ba::read<Obj>(selection,0x18)),subsets(ba::read<Obj>(selection,0x20));
    require(all.get() && subsets.get() && ba::klass(all.get())==ledClass &&
            ba::klass(subsets.get())==dictionaryClass,"click selection actual cache classes differ");
    const Obj boolean=type("System","Boolean"),integer=type("System","Int32"),nothing=type("System","Void");
    const Obj getTyped=method(selection,"GetUnitsOfType",1,0x060025a1,0x3c65810);
    const Obj typedClass=clickSelectionReturn(getTyped);
    clickSelectionSignature(getTyped,typedClass);
    require(clickSelectionClassName(typedClass,"","SelectedEntitiesOfType") &&
            ba::api<Obj(*)(Obj)>("il2cpp_class_get_declaring_type")(typedClass)==selectionClass &&
            ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(typedClass),
            "click selection original typed view differs");
    Obj keyType=ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(getTyped,0);
    const Obj keyClass=keyType?ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(keyType):nullptr;
    require(keyType && !ba::api<bool(*)(Obj)>("il2cpp_type_is_byref")(keyType) &&
            clickSelectionClassName(keyClass,"Uncapped","IntKey`1") &&
            ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(keyClass),
            "click selection original closed key differs");
    clickScalarSize(keyClass,4);
    uint32_t keyAlignment=0;
    require(ba::api<int32_t(*)(Obj,uint32_t*)>("il2cpp_class_value_size")(keyClass,&keyAlignment)==4 &&
            keyAlignment==4,"click selection original key alignment differs");
    const Obj lookup=method(subsets.get(),"TryGetValue",2,0x06002de7);
    clickSelectionSignature(lookup,boolean);
    Obj lookupKey=ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(lookup,0);
    Obj lookupValue=ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(lookup,1);
    require(lookupKey && lookupValue &&
            !ba::api<bool(*)(Obj)>("il2cpp_type_is_byref")(lookupKey) &&
            ba::api<bool(*)(Obj)>("il2cpp_type_is_byref")(lookupValue) &&
            ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(lookupKey)==keyClass &&
            ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(lookupValue)==ledClass &&
            !ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(ledClass),
            "click selection closed dictionary lookup signature differs");
    const Obj countMethod=method(subsets.get(),"get_Count",0,0x06002dcc);
    const Obj valuesMethod=method(subsets.get(),"get_Values",0,0x06002dd0);
    clickSelectionSignature(countMethod,integer);
    const Obj valuesClass=clickSelectionReturn(valuesMethod);
    clickSelectionSignature(valuesMethod,valuesClass);
    require(valuesClass && !ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(valuesClass),
            "click selection original Values class differs");
    auto boxedInt=[&](Obj info,Obj receiver) {
        Root result(invoke(info,receiver));
        require(result.get() && ba::klass(result.get())==integer,"click selection count box differs");
        return unbox<int32_t>(result.get());
    };
    auto boxedBool=[&](Obj info,Obj receiver,void** args=nullptr) {
        Root result(invoke(info,receiver,args));
        require(result.get() && ba::klass(result.get())==boolean,"click selection Boolean box differs");
        return unbox<bool>(result.get());
    };
    const int32_t count=boxedInt(countMethod,subsets.get());
    require(count>=0 && static_cast<size_t>(count)<=maximumActors,"click selection typed count exceeds bound");
    size_t total=0;
    auto rawIds=[&](Obj led) {
        require(led && ba::klass(led)==ledClass,"click selection cached Led class differs");
        require(clickSelectionDeclaredField(led,"<Entities>k__BackingField",0x10)==
                type("Uncapped.Collections","EntityIdSet"),"click selection Led entity storage type differs");
        auto result=ids(ba::read<Obj>(led,0x10));
        require(result.size()<=maximumActors-total,"click selection cached ID budget exceeded");
        total+=result.size();return result;
    };
    const std::vector<uint32_t> expected=present?std::vector<uint32_t>{entity}:std::vector<uint32_t>{};
    bool matches=rawIds(all.get())==expected;total=0;
    Obj lookedUp=nullptr;void* args[]={&unitType,&lookedUp};
    const bool found=boxedBool(lookup,subsets.get(),args);Root correct(lookedUp);
    require(found==bool(correct.get()),"click selection dictionary out value differs");
    if(correct.get())require(ba::klass(correct.get())==ledClass,"click selection lookup Led class differs");
    if(present && !found)matches=false;
    Root values(invoke(valuesMethod,subsets.get()));
    require(values.get() && ba::klass(values.get())==valuesClass &&
            clickSelectionDeclaredField(values.get(),"_dictionary",0x10)==dictionaryClass &&
            ba::read<Obj>(values.get(),0x10)==subsets.get(),"click selection Values owner differs");
    const Obj enumerate=method(values.get(),"GetEnumerator",0,0x06002e18);
    const Obj iteratorClass=clickSelectionReturn(enumerate);
    clickSelectionSignature(enumerate,iteratorClass);
    require(iteratorClass && ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(iteratorClass),
            "click selection original iterator is not a value type");
    // Validate all original cleanup/iteration metadata before acquiring a box.
    const Obj dispose=clickSelectionClassMethod(iteratorClass,"Dispose",0x06002e26);
    const Obj move=clickSelectionClassMethod(iteratorClass,"MoveNext",0x06002e27);
    const Obj current=clickSelectionClassMethod(iteratorClass,"get_Current",0x06002e28);
    clickSelectionSignature(dispose,nothing);clickSelectionSignature(move,boolean);
    clickSelectionSignature(current,ledClass);
    Root iterator(invoke(enumerate,values.get()));bool disposed=false;
    auto receiver=[&]() {
        require(iterator.get() && ba::klass(iterator.get())==iteratorClass,"click selection iterator box differs");
        Obj result=ba::api<Obj(*)(Obj)>("il2cpp_object_unbox")(iterator.get());
        require(result,"click selection iterator unbox missing");return result;
    };
    auto close=[&]() {if(!disposed){disposed=true;invoke(dispose,receiver());}};
    try {
        require(clickSelectionDeclaredField(iterator.get(),"_dictionary",0x10)==dictionaryClass &&
                ba::read<Obj>(iterator.get(),0x10)==subsets.get(),"click selection iterator dictionary owner differs");
        size_t groups=0,correctOccurrences=0;
        std::vector<uint32_t> combined;
        for(;;) {
            if(!boxedBool(move,receiver()))break;
            require(++groups<=static_cast<size_t>(count),"click selection typed enumeration grew");
            Root led(invoke(current,receiver()));
            auto entries=rawIds(led.get());combined.insert(combined.end(),entries.begin(),entries.end());
            if(led.get()==correct.get()) {
                ++correctOccurrences;if(entries!=expected)matches=false;
            }
        }
        require(groups==static_cast<size_t>(count) && boxedInt(countMethod,subsets.get())==count,
                "click selection typed enumeration count changed");
        if(combined!=expected || (found && correctOccurrences!=1) || (present && correctOccurrences!=1))matches=false;
        require(ba::read<Obj>(retained.get(),0x18)==all.get() &&
                ba::read<Obj>(retained.get(),0x20)==subsets.get() &&
                ba::read<Obj>(values.get(),0x10)==subsets.get() &&
                ba::read<Obj>(iterator.get(),0x10)==subsets.get(),"click selection cache owner changed");
        total=0;if(rawIds(all.get())!=expected)matches=false;
        close();return matches;
    } catch(...) {try{close();}catch(...){ba::log("Click selection original iterator cleanup failed; retry=0");}throw;}
}
