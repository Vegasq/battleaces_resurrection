#pragma once
// Explicit fresh-instance guard fixture. The real SDK Client is absent; this
// does not initialize an operational SDK or qualify resumed/in-flight delivery.
static Bytes instanceFields(Obj value) {
    require(value!=nullptr,"delivery fixture object absent");
    const auto size=ba::api<uint32_t(*)(Obj)>("il2cpp_class_instance_size")(ba::klass(value));
    require(size>=16 && size<=4096,"delivery fixture instance extent differs");
    Bytes bytes(size-16);
    require(copy(reinterpret_cast<uintptr_t>(value)+16,bytes.data(),bytes.size()),"delivery fixture field snapshot failed");
    return bytes;
}
static Obj staticList(Obj type,const char* name) {
    const auto field=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(type,name);
    require(field && (ba::api<uint32_t(*)(Obj)>("il2cpp_field_get_flags")(field)&0x10),"delivery fixture static list absent");
    Obj value=nullptr;ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(field,&value);
    require(value && count(value)==0,"delivery fixture requires empty genuine SDK lists");return value;
}
static void guardedDelivery(Obj config,Obj manager,Obj report,Obj session) {
    require(config && manager && report && session,"delivery fixture requires genuine cache/report dependencies");
    #include "telemetry_cache_delivery_signatures.hpp"
    const auto payloadType=ba::find_class("BugsnagUnity","PayloadManager");
    const auto deliveryType=ba::find_class("BugsnagUnity","Delivery");
    ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(payloadType);
    ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(deliveryType);
    ba_local::Root pending(staticList(payloadType,"_pendingPayloads"));
    ba_local::Root finished(staticList(deliveryType,"_finishedCacheDeliveries"));
    ba_local::Root payload(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(payloadType));
    void* payloadArgs[]={manager};invoke(method(payloadType,".ctor",1,0x717fb0),payload.get(),payloadArgs);
    ba_local::Root delivery(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(deliveryType));
    void* deliveryArgs[]={nullptr,config,manager,payload.get()};
    invoke(method(deliveryType,".ctor",4,0x81c490),delivery.get(),deliveryArgs);
    require(ba::get<Obj>(payload.get(),"_cacheManager")==manager &&
        !ba::get<Obj>(delivery.get(),"_client") && ba::get<Obj>(delivery.get(),"_configuration")==config &&
        ba::get<Obj>(delivery.get(),"_cacheManager")==manager && ba::get<Obj>(delivery.get(),"_payloadManager")==payload.get() &&
        ba::get<Obj>(delivery.get(),"<_callbackLock>k__BackingField") &&
        !ba::get<bool>(delivery.get(),"_cacheDeliveryInProcess"),"delivery original constructor references/state differ");
    struct Iterator {
        ba_local::Root value;
        Obj move,dispose,current;
        Bytes fields;
        Iterator(Obj result,Obj owner,const char* name,size_t moveRva,size_t disposeRva):value(result) {
            require(value.get()!=nullptr,"delivery original factory returned null");
            const auto type=ba::klass(value.get());
            require(ba::api<Obj(*)(Obj)>("il2cpp_class_get_declaring_type")(type)==owner &&
                !strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(type),name),"delivery original factory returned unexpected nested class");
            move=method(type,"MoveNext",0,moveRva);
            dispose=method(type,"System.IDisposable.Dispose",0,disposeRva);
            current=method(type,"System.Collections.IEnumerator.get_Current",0,0x70f380);
            require(ba::get<int>(value.get(),"<>1__state")==0 && !ba::get<Obj>(value.get(),"<>2__current"),
                "delivery original iterator is not fresh state zero");
            fields=instanceFields(value.get());
        }
        void stop() {
            // Direct ABI is Boolean AL, not a boxed Boolean. Full masked-body
            // hashes above are checked before any replacement can be called.
            require(!reinterpret_cast<bool(*)(Obj,Obj)>(ba::read<uintptr_t>(move,0))(value.get(),move),
                "guarded delivery iterator did not finish immediately");
            require(instanceFields(value.get())==fields && !invoke(current,value.get(),nullptr),
                "guarded delivery iterator changed captures/state/current");
            // Source-reviewed original Dispose is a no-op for verified state0.
            // No Reset/finally helper or original MoveNext is invoked.
            invoke(dispose,value.get(),nullptr);
            require(instanceFields(value.get())==fields,"fresh delivery iterator Dispose changed fields");
        }
    };
    std::vector<std::unique_ptr<Iterator>> iterators;
    const auto cached=method(deliveryType,"DeliverCachedPayloads",0,0x81f8b0);
    iterators.push_back(std::make_unique<Iterator>(invoke(cached,delivery.get(),nullptr),deliveryType,
        "<DeliverCachedPayloads>d__36",0x8201f0,0x6af170));
    require(ba::get<Obj>(iterators.back()->value.get(),"<>4__this")==delivery.get(),"cached iterator owner differs");
    const auto process=method(deliveryType,"ProcessCachedItems",1,0x81f950);
    const auto push=method(deliveryType,"PushToServer",1,0x81cf00);
    for(Obj object:{report,session}) {
        ba_local::Root reflection(ba::api<Obj(*)(Obj)>("il2cpp_type_get_object")(
            ba::api<Obj(*)(Obj)>("il2cpp_class_get_type")(ba::klass(object))));
        require(reflection.get()!=nullptr,"delivery fixture reflection type absent");
        void* typeArgs[]={reflection.get()};
        iterators.push_back(std::make_unique<Iterator>(invoke(process,delivery.get(),typeArgs),deliveryType,
            "<ProcessCachedItems>d__37",0x8204c0,0x820430));
        require(ba::get<Obj>(iterators.back()->value.get(),"<>4__this")==delivery.get() &&
            ba::get<Obj>(iterators.back()->value.get(),"t")==reflection.get(),"process iterator captures differ");
        void* reportArgs[]={object};
        iterators.push_back(std::make_unique<Iterator>(invoke(push,delivery.get(),reportArgs),deliveryType,
            "<PushToServer>d__21",0x820de0,0x820d10));
        require(ba::get<Obj>(iterators.back()->value.get(),"<>4__this")==delivery.get() &&
            ba::get<Obj>(iterators.back()->value.get(),"payload")==object,"push iterator captures differ");
    }
    const auto deliverEntry=method(deliveryType,"Deliver",1,0x81c6a0);
    const auto startEntry=method(deliveryType,"StartDeliveringCachedPayloads",0,0x81f730);
    const auto deliveryFields=instanceFields(delivery.get()),payloadFields=instanceFields(payload.get());
    const auto reportFields=instanceFields(report),sessionFields=instanceFields(session);
    const auto pendingFields=instanceFields(pending.get()),finishedFields=instanceFields(finished.get());
    ba::log("TELEMETRY CACHEDELIVERY begin: version=1 thread=%lu fresh=1 absentClient=1",GetCurrentThreadId());
    for(Obj object:{report,session})
        reinterpret_cast<void(*)(Obj,Obj,Obj)>(ba::read<uintptr_t>(deliverEntry,0))(delivery.get(),object,deliverEntry);
    reinterpret_cast<void(*)(Obj,Obj)>(ba::read<uintptr_t>(startEntry,0))(delivery.get(),startEntry);
    for(auto& iterator:iterators)iterator->stop();
    require(instanceFields(delivery.get())==deliveryFields && instanceFields(payload.get())==payloadFields &&
        instanceFields(report)==reportFields && instanceFields(session)==sessionFields &&
        staticList(payloadType,"_pendingPayloads")==pending.get() && staticList(deliveryType,"_finishedCacheDeliveries")==finished.get() &&
        instanceFields(pending.get())==pendingFields && instanceFields(finished.get())==finishedFields,
        "guarded fresh delivery changed owner/report/list fields");
    ba::log("TELEMETRY CACHEDELIVERY probe passed: version=1 thread=%lu realPayloadManager=1 realDelivery=1 absentClient=1 activeClientConstructed=0 deliverCalls=2 cachedStartCalls=1 iteratorFactories=5 moveNextFalse=5 originalDisposes=5 freshStateRetained=5 currentNull=5 capturesRetained=5 pendingCount=0 finishedCount=0 listFieldsUnchanged=2 reportFieldsUnchanged=2 deliveryFieldsUnchanged=1 payloadManagerFieldsUnchanged=1 reportDelivered=0 wholeRunIsolation=0",
        GetCurrentThreadId());
}
