#pragma once
// Include inside ba_prediction_actors after prediction_click_selection.hpp.
// Caller owns the original group suspension, notification and State validation.
// Raw pending members survive; no live iterator, Clear, Add or field write.
class GroupSelectionPurge {
    struct Bucket {
        Root led,entities;
        std::vector<uint32_t> before,expected,targets;
        uint32_t lastLeader=UINT32_MAX;
        Bucket(Obj value,Obj ids):led(value),entities(ids){}
    };
    using Census=std::vector<std::unique_ptr<Bucket>>;
    Root selected_;
    std::unique_ptr<Root> all_,subsets_,allEntities_;
    Obj ledClass_=nullptr,dictionaryClass_=nullptr,valuesClass_=nullptr;
    Obj remove_=nullptr,dirty_=nullptr,count_=nullptr,values_=nullptr;
    Obj boolean_=nullptr,integer_=nullptr,unsigned_=nullptr,nothing_=nullptr;
    static Obj parameter(Obj info,unsigned index) {
        return ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(info,index);
    }
    Obj typedLookup()const {
        const Obj getTyped=method(selected_.get(),"GetUnitsOfType",1,0x060025a1,0x3c65810);
        const Obj view=clickSelectionReturn(getTyped);clickSelectionSignature(getTyped,view);
        require(clickSelectionClassName(view,"","SelectedEntitiesOfType") &&
                ba::api<Obj(*)(Obj)>("il2cpp_class_get_declaring_type")(view)==ba::klass(selected_.get()) &&
                ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(view) &&
                ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(getTyped)==1 &&
                ba::api<Obj(*)(Obj)>("il2cpp_method_get_declaring_type")(getTyped)==ba::klass(selected_.get()),
                "group typed original view signature differs");
        const Obj keyType=parameter(getTyped,0);
        const Obj key=keyType?ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(keyType):nullptr;
        require(keyType && !ba::api<bool(*)(Obj)>("il2cpp_type_is_byref")(keyType) &&
                clickSelectionClassName(key,"Uncapped","IntKey`1") &&
                ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(key),"group typed original key differs");
        clickScalarSize(key,4);uint32_t alignment=0;
        require(ba::api<int32_t(*)(Obj,uint32_t*)>("il2cpp_class_value_size")(key,&alignment)==4 && alignment==4,
                "group typed original key ABI differs");
        const Obj lookup=method(subsets_->get(),"TryGetValue",2,0x06002de7);
        clickSelectionSignature(lookup,boolean_);
        const Obj lookupKey=parameter(lookup,0),lookupValue=parameter(lookup,1);
        require(ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(lookup)==2 &&
                ba::api<Obj(*)(Obj)>("il2cpp_method_get_declaring_type")(lookup)==dictionaryClass_ &&
                lookupKey && lookupValue && !ba::api<bool(*)(Obj)>("il2cpp_type_is_byref")(lookupKey) &&
                ba::api<bool(*)(Obj)>("il2cpp_type_is_byref")(lookupValue) &&
                ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(lookupKey)==key &&
                ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(lookupValue)==ledClass_ &&
                !ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(ledClass_),
                "group typed closed dictionary lookup differs");
        return lookup;
    }
    void methods()const {
        require(method(all_->get(),"Remove",1,0x060025c8,0x3c699b0)==remove_ &&
                method(selected_.get(),"MarkCountAsDirty",0,0x0600259a,0x3c63de0)==dirty_,
                "group purge original mutator changed");
        clickSelectionSignature(remove_,boolean_);clickSelectionSignature(dirty_,nothing_);
        require(ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(remove_)==1 &&
                ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(dirty_)==0 &&
                ba::api<Obj(*)(Obj)>("il2cpp_method_get_declaring_type")(remove_)==ledClass_ &&
                ba::api<Obj(*)(Obj)>("il2cpp_method_get_declaring_type")(dirty_)==ba::klass(selected_.get()),
                "group purge mutator declaration/arity differs");
        Obj arg=parameter(remove_,0);
        require(arg && !ba::api<bool(*)(Obj)>("il2cpp_type_is_byref")(arg) &&
                ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(arg)==unsigned_,
                "group purge original Led Remove parameter differs");
    }
    int32_t count()const {
        Root value(invoke(count_,subsets_->get()));
        require(value.get() && ba::klass(value.get())==integer_,"group purge count box differs");
        const auto result=unbox<int32_t>(value.get());
        require(result>=0 && static_cast<size_t>(result)<=maximumActors,"group purge cache count exceeds bound");
        return result;
    }
    bool boolean(Obj info,Obj receiver,void** args=nullptr)const {
        Root value(invoke(info,receiver,args));
        require(value.get() && ba::klass(value.get())==boolean_,"group purge Boolean box differs");
        const auto result=unbox<uint8_t>(value.get());
        require(result<=1,"group purge Boolean representation differs");return result!=0;
    }
    std::vector<uint32_t> members(const Bucket& bucket)const {
        require(bucket.led.get() && ba::klass(bucket.led.get())==ledClass_ &&
                clickSelectionDeclaredField(bucket.led.get(),"<Entities>k__BackingField",0x10)==
                    type("Uncapped.Collections","EntityIdSet") &&
                ba::read<Obj>(bucket.led.get(),0x10)==bucket.entities.get(),
                "group purge Led storage owner changed");
        auto result=ids(bucket.entities.get());
        require(result.size()<=maximumActors,"group purge raw bucket exceeds bound");
        std::sort(result.begin(),result.end());
        require(std::adjacent_find(result.begin(),result.end())==result.end() &&
                (result.empty() || result.back()!=UINT32_MAX),"group purge raw ID invariant differs");
        require(clickSelectionDeclaredField(bucket.led.get(),"<Leader>k__BackingField",0x18)==unsigned_ &&
                clickSelectionDeclaredField(bucket.led.get(),"_lastKnownLeaderId",0x1c)==unsigned_,
                "group purge original leader fields differ");
        const auto leader=ba::read<uint32_t>(bucket.led.get(),0x18);
        // Original GetSelectionLeader can persist UINT32_MAX while raw pending
        // members remain when PickBestLeader cannot resolve any candidate.
        require(leader==UINT32_MAX || (!result.empty() && std::binary_search(result.begin(),result.end(),leader)),
                "group purge raw leader is not a member");
        return result;
    }
    Census census()const {
        validate();const int32_t expectedCount=count();Census result;std::set<Obj> seen,seenEntities;
        size_t typedBudget=0;
        auto append=[&](Obj led,bool typed) {
            require(led && ba::klass(led)==ledClass_ && seen.insert(led).second,
                    "group purge cached Led class/alias differs");
            require(clickSelectionDeclaredField(led,"<Entities>k__BackingField",0x10)==
                    type("Uncapped.Collections","EntityIdSet"),"group purge declared entity storage differs");
            auto bucket=std::make_unique<Bucket>(led,ba::read<Obj>(led,0x10));
            require(seenEntities.insert(bucket->entities.get()).second,"group purge entity storage alias differs");
            bucket->before=members(*bucket);bucket->expected=bucket->before;
            bucket->lastLeader=ba::read<uint32_t>(led,0x1c);
            if(typed) {
                require(bucket->before.size()<=maximumActors-typedBudget,"group purge typed ID budget exceeded");
                typedBudget+=bucket->before.size();
            }
            result.push_back(std::move(bucket));
        };
        append(all_->get(),false);
        Root values(invoke(values_,subsets_->get()));
        require(values.get() && ba::klass(values.get())==valuesClass_ &&
                clickSelectionDeclaredField(values.get(),"_dictionary",0x10)==dictionaryClass_ &&
                ba::read<Obj>(values.get(),0x10)==subsets_->get(),"group purge Values owner differs");
        const Obj enumerate=method(values.get(),"GetEnumerator",0,0x06002e18);
        const Obj iteratorClass=clickSelectionReturn(enumerate);clickSelectionSignature(enumerate,iteratorClass);
        require(iteratorClass && ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(iteratorClass),
                "group purge iterator is not a value type");
        const Obj dispose=clickSelectionClassMethod(iteratorClass,"Dispose",0x06002e26);
        const Obj move=clickSelectionClassMethod(iteratorClass,"MoveNext",0x06002e27);
        const Obj current=clickSelectionClassMethod(iteratorClass,"get_Current",0x06002e28);
        clickSelectionSignature(dispose,nothing_);clickSelectionSignature(move,boolean_);
        clickSelectionSignature(current,ledClass_);
        Root iterator(invoke(enumerate,values.get()));bool disposed=false;
        auto receiver=[&]() {
            require(iterator.get() && ba::klass(iterator.get())==iteratorClass,"group purge iterator box differs");
            Obj value=ba::api<Obj(*)(Obj)>("il2cpp_object_unbox")(iterator.get());
            require(value,"group purge iterator unbox missing");return value;
        };
        auto close=[&]() {if(!disposed){disposed=true;invoke(dispose,receiver());}};
        try {
            require(clickSelectionDeclaredField(iterator.get(),"_dictionary",0x10)==dictionaryClass_ &&
                    ba::read<Obj>(iterator.get(),0x10)==subsets_->get(),"group purge iterator owner differs");
            size_t found=0;
            while(boolean(move,receiver())) {
                require(++found<=static_cast<size_t>(expectedCount),"group purge cache enumeration grew");
                Root led(invoke(current,receiver()));append(led.get(),true);
            }
            require(found==static_cast<size_t>(expectedCount) && count()==expectedCount &&
                    ba::read<Obj>(values.get(),0x10)==subsets_->get() &&
                    ba::read<Obj>(iterator.get(),0x10)==subsets_->get(),"group purge cache census changed");
            validate();close();validate();return result;
        } catch(...) {
            try{close();}catch(...){ba::log("Group purge original iterator cleanup failed; retry=0");}
            throw;
        }
    }
public:
    explicit GroupSelectionPurge(Obj selected)
        :selected_(selected),all_(nullptr),subsets_(nullptr) {
        classIs(selected_.get(),"Uncapped.Collections","UnitSelectionSet");
        boolean_=type("System","Boolean");integer_=type("System","Int32");
        unsigned_=type("System","UInt32");nothing_=type("System","Void");
        clickScalarSize(boolean_,1);clickScalarSize(integer_,4);clickScalarSize(unsigned_,4);
        uint32_t alignment=0;
        require(ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(unsigned_) &&
                ba::api<int32_t(*)(Obj,uint32_t*)>("il2cpp_class_value_size")(unsigned_,&alignment)==4 &&
                alignment==4,"group purge original UInt32 value ABI differs");
        ledClass_=clickSelectionDeclaredField(selected_.get(),"_allUnits",0x18);
        dictionaryClass_=clickSelectionDeclaredField(selected_.get(),"_subsetsByType",0x20);
        require(clickSelectionClassName(ledClass_,"","LedUnitSet") &&
                ba::api<Obj(*)(Obj)>("il2cpp_class_get_declaring_type")(ledClass_)==ba::klass(selected_.get()) &&
                !ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(ledClass_) &&
                clickSelectionClassName(dictionaryClass_,"System.Collections.Generic","Dictionary`2"),
                "group purge declared cache classes differ");
        // Independently retain both constructor receivers without copying a
        // GC-handle-owning Root through assignment.
        all_=std::make_unique<Root>(ba::read<Obj>(selected_.get(),0x18));
        subsets_=std::make_unique<Root>(ba::read<Obj>(selected_.get(),0x20));
        require(all_->get() && subsets_->get() && ba::klass(all_->get())==ledClass_ &&
                ba::klass(subsets_->get())==dictionaryClass_,"group purge actual cache classes differ");
        require(clickSelectionDeclaredField(all_->get(),"<Entities>k__BackingField",0x10)==
                type("Uncapped.Collections","EntityIdSet"),"group purge all entity storage type differs");
        allEntities_=std::make_unique<Root>(ba::read<Obj>(all_->get(),0x10));
        remove_=method(all_->get(),"Remove",1,0x060025c8,0x3c699b0);
        dirty_=method(selected_.get(),"MarkCountAsDirty",0,0x0600259a,0x3c63de0);
        count_=method(subsets_->get(),"get_Count",0,0x06002dcc);
        values_=method(subsets_->get(),"get_Values",0,0x06002dd0);
        clickSelectionSignature(count_,integer_);valuesClass_=clickSelectionReturn(values_);
        clickSelectionSignature(values_,valuesClass_);
        require(valuesClass_ && !ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(valuesClass_),
                "group purge Values return class differs");
        validate();Bucket all(all_->get(),ba::read<Obj>(all_->get(),0x10));(void)members(all);
    }
    void validate()const {
        classIs(selected_.get(),"Uncapped.Collections","UnitSelectionSet");
        require(clickSelectionDeclaredField(selected_.get(),"_allUnits",0x18)==ledClass_ &&
                clickSelectionDeclaredField(selected_.get(),"_subsetsByType",0x20)==dictionaryClass_ &&
                ba::read<Obj>(selected_.get(),0x18)==all_->get() &&
                ba::read<Obj>(selected_.get(),0x20)==subsets_->get() && all_->get() && subsets_->get() &&
                ba::klass(all_->get())==ledClass_ && ba::klass(subsets_->get())==dictionaryClass_,
                "group purge selection cache owner changed");
        require(clickSelectionDeclaredField(all_->get(),"<Entities>k__BackingField",0x10)==
                    type("Uncapped.Collections","EntityIdSet") &&
                allEntities_->get() && ba::read<Obj>(all_->get(),0x10)==allEntities_->get(),
                "group purge all entity storage owner changed");
        require(clickSelectionDeclaredField(selected_.get(),"<OnlyHQSelected>k__BackingField",0x58)==boolean_ &&
                ba::read<uint8_t>(selected_.get(),0x58)==0 &&
                clickSelectionDeclaredField(selected_.get(),"_recomputeOverallLeader",0x10)==boolean_ &&
                ba::read<uint8_t>(selected_.get(),0x10)<=1 &&
                clickSelectionDeclaredField(selected_.get(),"_lastFrameCountRecalculated",0x54)==integer_,
                "group purge non-HQ/derived cache invariant differs");
        methods();
    }
    bool hasTypedMember(uint32_t entity,uint32_t unitType)const {
        validate();const Obj lookup=typedLookup();auto before=census();
        auto stable=[&](const Census& buckets) {
            validate();require(count()==static_cast<int32_t>(buckets.size()-1),"group typed census count changed after cleanup");
            for(const auto& bucket:buckets)
                require(members(*bucket)==bucket->before && ba::read<uint32_t>(bucket->led.get(),0x1c)==bucket->lastLeader,
                        "group typed raw cache changed after cleanup");
        };
        stable(before);
        // An original user removal wins even if stale typed ghosts remain.
        if(!std::binary_search(before.front()->before.begin(),before.front()->before.end(),entity))return false;
        Obj value=nullptr;void* args[]={&unitType,&value};
        const bool found=boolean(lookup,subsets_->get(),args);Root correct(value);
        require(found && correct.get() && ba::klass(correct.get())==ledClass_,
                "group typed present member lacks expected-key Led");
        auto after=census();stable(after);require(after.size()==before.size(),"group typed cache topology changed during lookup");
        size_t hits=0;bool expected=false;
        for(const auto& bucket:after) {
            const auto prior=std::find_if(before.begin(),before.end(),[&](const auto& old){return old->led.get()==bucket->led.get();});
            require(prior!=before.end() && (*prior)->entities.get()==bucket->entities.get() &&
                    (*prior)->before==bucket->before && (*prior)->lastLeader==bucket->lastLeader,
                    "group typed raw cache changed during lookup");
            if(bucket->led.get()!=all_->get() && std::binary_search(bucket->before.begin(),bucket->before.end(),entity)) {
                ++hits;expected=bucket->led.get()==correct.get();
            }
        }
        require(hits==1 && expected,"group typed member has wrong-key, missing or multiple cached buckets");
        validate();return true;
    }
    void invalidateCount() {
        validate();const auto recompute=ba::read<uint8_t>(selected_.get(),0x10);
        invoke(dirty_,selected_.get());validate();
        require(ba::read<int32_t>(selected_.get(),0x54)==-1 && ba::read<uint8_t>(selected_.get(),0x10)==recompute,
                "group purge original count invalidation differs");
    }
    bool erase(const std::vector<uint32_t>& retiredIds) {
        validate();require(retiredIds.size()<=maximumActors,"group purge retirement ID budget exceeded");
        const std::set<uint32_t> retired(retiredIds.begin(),retiredIds.end());
        require(!retired.count(UINT32_MAX),"group purge sentinel retirement ID differs");
        if(retired.empty())return false;
        auto buckets=census();bool changed=false;
        const auto recompute=ba::read<uint8_t>(selected_.get(),0x10);
        for(auto& bucket:buckets) {
            bucket->expected.clear();
            for(auto id:bucket->before) {
                if(retired.count(id)){bucket->targets.push_back(id);changed=true;}
                else bucket->expected.push_back(id);
            }
            require(members(*bucket)==bucket->before && ba::read<uint32_t>(bucket->led.get(),0x1c)==bucket->lastLeader,
                    "group purge raw membership changed before mutation");
        }
        if(!changed)return false;
        invalidateCount();
        require(ba::read<int32_t>(selected_.get(),0x54)==-1 && ba::read<uint8_t>(selected_.get(),0x10)==recompute,
                "group purge original count invalidation differs");
        for(auto& bucket:buckets) {
            require(members(*bucket)==bucket->before && ba::read<uint32_t>(bucket->led.get(),0x1c)==bucket->lastLeader,
                    "group purge bucket changed before original removal");
            for(auto id:bucket->targets) {
                validate();void* args[]={&id};
                require(boolean(remove_,bucket->led.get(),args),"group purge original Led removal refused a present ID");
                validate();
            }
            require(members(*bucket)==bucket->expected && ba::read<uint32_t>(bucket->led.get(),0x1c)==bucket->lastLeader,
                    "group purge original removal changed unrelated membership/leader memory");
        }
        auto after=census();require(after.size()==buckets.size(),"group purge cache topology changed during removal");
        for(const auto& value:after) {
            const auto found=std::find_if(buckets.begin(),buckets.end(),[&](const auto& prior){return prior->led.get()==value->led.get();});
            require(found!=buckets.end() && (*found)->entities.get()==value->entities.get() &&
                    (*found)->expected==value->before && (*found)->lastLeader==value->lastLeader,
                    "group purge final raw cache differs");
        }
        validate();require(ba::read<int32_t>(selected_.get(),0x54)==-1 &&
                ba::read<uint8_t>(selected_.get(),0x10)==recompute,"group purge derived cache changed during removal");
        return true;
    }
};
