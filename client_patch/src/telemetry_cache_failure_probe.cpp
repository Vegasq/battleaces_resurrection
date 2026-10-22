#pragma once
// Included inside cache_probe. Explicit genuine pending-owner fixture only.
static void disabledDeviceIdentity(Obj,Obj,const std::wstring&);
static Obj listMethod(Obj type,const char* name,unsigned token,unsigned arity) {
    void* iterator=nullptr;Obj found=nullptr;
    while(auto entry=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(type,&iterator)) {
        if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(entry),name) ||
           ba::api<unsigned(*)(Obj)>("il2cpp_method_get_param_count")(entry)!=arity ||
           ba::api<unsigned(*)(Obj)>("il2cpp_method_get_token")(entry)!=token)continue;
        require(!found,"ambiguous closed pending-list method");found=entry;
    }
    require(found!=nullptr,"closed pending-list method absent");return found;
}
static void guardedCacheFailure(Obj config,Obj manager,Obj payload,Obj pending,Obj report,Obj session,
                                const std::wstring& selected) {
    #include "telemetry_cache_failure_signatures.hpp"
    original(0x7049a0,5,"fb6bf83d7403f34405349e1715c8966083af4295fe7dc65bad96d9a60589f9aa");
    original(0x6f7190,6,"2db31f4e09597946e56e859813bfdad7046d457c32332c3a882654d1e3ffdf67");
    original(0x845d70,5,"ca3aab76b94acd7081ad378320443ef2f9a4c3551ec59cde6a86c27d7062522a");
    original(0x6ebf80,3,"4bc724f3b1d0caf4fe369c18cba3102e6c4ea057f63fe1587e3973134a7f755e");
    original(0x6ea000,84,"cc865e49c085c545f4e97a0ed6450d79e97b76f9c5d9ea59b98ad8414bef67cd");
    original(0x6f9db0,4,"38058506e8e859d5be73a33baa621352c08ea01f2224ee170173253757193941");
    original(0x1b4f040,104,"476f005a2e49f266db8016855544d7b224abb05a137587ed1d172f511144e554");
    original(0x14bc50,95,"d483845413ec79ccf8580c829b4736de836de0565ce4b0bec45379036c51e51b");
    original(0x19a2600,284,"621f2bf437a46519dc09614aa249e5b3b683e5bfe5e543219b9fa81f128f88e1");
    const auto payloadType=ba::klass(payload),listType=ba::klass(pending);
    require(count(pending)==0,"failure fixture requires empty genuine pending list");
    for(auto field:std::vector<std::pair<const char*,int>>{{"_items",0x10},{"_size",0x18},{"_version",0x1c}}) {
        const auto info=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(listType,field.first);
        require(info && !(ba::api<unsigned(*)(Obj)>("il2cpp_field_get_flags")(info)&0x10) &&
            ba::api<int(*)(Obj)>("il2cpp_field_get_offset")(info)==field.second,"closed pending-list layout differs");
    }
    void* nestedIterator=nullptr;Obj pendingType=nullptr;
    while(auto type=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_nested_types")(payloadType,&nestedIterator))
        if(!strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(type),"PendingPayload")) {
            require(!pendingType && ba::api<Obj(*)(Obj)>("il2cpp_class_get_declaring_type")(type)==payloadType,
                "pending payload nested ownership differs");pendingType=type;
        }
    require(pendingType!=nullptr,"genuine nested pending payload absent");
    const auto ctor=method(pendingType,".ctor",2,0x818f80);
    const auto add=listMethod(listType,"Add",0x06002e64,1);
    const auto sizeEntry=listMethod(listType,"get_Count",0x06002e59,0);
    require(ba::read<uintptr_t>(add,0)==reinterpret_cast<uintptr_t>(ba::module)+0x6ea000,
        "closed pending List.Add does not use the source-reviewed reference sharing body");
    require(ba::read<uintptr_t>(sizeEntry,0)==reinterpret_cast<uintptr_t>(ba::module)+0x6f9db0,
        "closed pending List.Count does not use the source-reviewed leaf");
    const auto remove=method(payloadType,"RemovePendingPayload",1,0x825190);
    const auto failed=method(payloadType,"SendPayloadFailed",1,0x824b60);
    const auto cacheEvent=method(payloadType,"CacheEvent",1,0x824f70);
    const auto cacheSession=method(payloadType,"CacheSession",1,0x824e20);
    const auto payloadFields=instanceFields(payload),reportFields=instanceFields(report),sessionFields=instanceFields(session);
    const auto configFields=instanceFields(config);const auto configType=ba::klass(config);
    for(auto value:std::vector<std::pair<const char*,int>>{{"MaxPersistedEvents",0x140},{"MaxPersistedSessions",0x144}}) {
        const auto field=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(configType,value.first);
        require(field && !(ba::api<unsigned(*)(Obj)>("il2cpp_field_get_flags")(field)&0x10) &&
            ba::api<int(*)(Obj)>("il2cpp_field_get_offset")(field)==value.second &&
            ba::api<int(*)(Obj)>("il2cpp_type_get_type")(ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(field))==8,
            "cache limit fixture Int32 field differs");
    }
    const int eventLimit=ba::get<int>(config,"MaxPersistedEvents"),sessionLimit=ba::get<int>(config,"MaxPersistedSessions");
    struct Limits {Obj config;int events,sessions;~Limits(){ba::set<int>(config,"MaxPersistedEvents",events);ba::set<int>(config,"MaxPersistedSessions",sessions);}}
        limits{config,eventLimit,sessionLimit};
    ba::set<int>(config,"MaxPersistedEvents",0);ba::set<int>(config,"MaxPersistedSessions",0);
    ba_local::Root json(ba::str("authored invalid JSON126; cache handler must not parse or persist it"));
    ba::log("TELEMETRY CACHEFAILURE begin: version=1 thread=%lu genuinePendingOwners=1 activeClientConstructed=0",GetCurrentThreadId());
    for(int round=0;round<8;++round) {
        const int kind=round%4;const bool matched=round<4;
        const Obj object=(kind==0 || kind==2)?report:session;
        const auto idEntry=method(ba::klass(object),"get_Id",0,(object==report)?0x7049a0:0x845d70);
        ba_local::Root id(invoke(idEntry,object,nullptr));require(!text(id.get()).empty(),"typed fixture report ID missing");
        std::vector<std::unique_ptr<ba_local::Root>> owners,ids;
        for(int i=0;i<4;++i) {
            ids.push_back(std::make_unique<ba_local::Root>((matched && (i==1 || i==3))?id.get():
                ba::str(("authored-unmatched-126-"+std::to_string(i)).c_str())));
            owners.push_back(std::make_unique<ba_local::Root>(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(pendingType)));
            void* args[]={json.get(),ids.back()->get()};invoke(ctor,owners.back()->get(),args);
            void* addArgs[]={owners.back()->get()};invoke(add,pending,addArgs);
        }
        require(count(pending)==4,"genuine pending inserts did not produce four owners");
        ba_local::Root items(ba::get<Obj>(pending,"_items"));const int version=ba::get<int>(pending,"_version");
        require(items.get() && ba::read<uintptr_t>(items.get(),0x18)>=4 && version>=0 && version<100000,
            "genuine pending backing array/version invalid");
        std::vector<Bytes> fields;
        for(int i=0;i<4;++i) {
            require(ba::read<Obj>(items.get(),0x20+i*8)==owners[i]->get(),"genuine Add order differs");
            fields.push_back(instanceFields(owners[i]->get()));
        }
        const auto entry=kind<2?failed:(kind==2?cacheEvent:cacheSession);
        void* arguments[]={kind<2?object:id.get()};invoke(entry,payload,arguments);
        require(count(pending)==(matched?2:4) && ba::get<Obj>(pending,"_items")==items.get() &&
            ba::get<int>(pending,"_version")==version+(matched?1:0),"pending retirement count/version/array differs");
        for(int i=0;i<4;++i) {
            const Obj expected=matched?(i<2?owners[i*2]->get():nullptr):owners[i]->get();
            require(ba::read<Obj>(items.get(),0x20+i*8)==expected &&
                instanceFields(owners[i]->get())==fields[i] && ba::get<Obj>(owners[i]->get(),"Json")==json.get() &&
                ba::get<Obj>(owners[i]->get(),"PayloadId")==ids[i]->get(),"pending order/ref clearing/borrowed fields differ");
        }
        // Retire only our remaining sentinels via genuine reviewed cleanup.
        for(auto& ownedId:ids) {void* args[]={ownedId->get()};invoke(remove,payload,args);}
        require(count(pending)==0,"authored pending cleanup incomplete");
    }
    disabledDeviceIdentity(config,manager,selected);
    require(ba::get<int>(config,"MaxPersistedEvents")==0 && ba::get<int>(config,"MaxPersistedSessions")==0,
        "cache handlers changed owned zero-limit configuration");
    ba::set<int>(config,"MaxPersistedEvents",eventLimit);ba::set<int>(config,"MaxPersistedSessions",sessionLimit);
    require(instanceFields(payload)==payloadFields && instanceFields(report)==reportFields &&
        instanceFields(session)==sessionFields && staticList(payloadType,"_pendingPayloads")==pending && instanceFields(config)==configFields,
        "failure fixture changed manager/report fields or static list identity");
    ba::log("TELEMETRY CACHEFAILURE probe passed: version=1 thread=%lu cases=8 matchedCases=4 missCases=4 removedMatches=8 unmatchedRetained=24 clearedArrayRefs=8 cleanupVersionUpdates=4 missListUnchanged=4 pendingAfter=0 genuinePendingOwners=32 typedFailureBranches=2 cacheHandlers=2 cacheLimitsZero=1 configLimitsRestored=1 reportFieldsUnchanged=2 payloadManagerFieldsUnchanged=1 listIdentityRetained=1 devicePositiveRead=1 deviceEmpty=1 deviceSeedUnchanged=1 configRestored=1 retainedFilenameUnchanged=1 reportDelivered=0 operationalClient=0 wholeRunIsolation=0",GetCurrentThreadId());
}
