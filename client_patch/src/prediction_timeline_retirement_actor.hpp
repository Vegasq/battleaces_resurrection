#pragma once
// Included inside ba_prediction_actors, after original ownership helpers.
// A retracted HQ death must not leave its old director driving a reused actor.
// Stop while the old Unit is still dead/released, before the original pool and
// initialization paths restore presentation. Do not suppress future timelines.
class RetiredTimelines {
    struct Entry {
        Root actor,director,config;
        std::unique_ptr<Root> stopped;
        policy::ActorIdentity identity;
        uint64_t token=0;
        uint32_t registryId=0;
        Obj stop=nullptr,getState=nullptr,stateClass=nullptr,callback=nullptr;
        int32_t paused=0;
        unsigned subscribers=0;
        bool attempted=false,callbacksCaptured=false;
        Entry(Obj unit,Obj value,Obj definition):actor(unit),director(value),config(definition){}
    };
    State* owner_=nullptr;
    uint64_t world_=0;DWORD thread_=0;std::string match_;
    std::unique_ptr<Root> manager_,simulation_,frames_,frame_;
    std::vector<std::unique_ptr<Entry>> entries_;
    static Obj resultClass(Obj info) {
        return ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(info));
    }
    static Obj parameterClass(Obj info,unsigned index) {
        Obj value=ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(info,index);
        require(value&&!ba::api<bool(*)(Obj)>("il2cpp_type_is_byref")(value),"retired timeline parameter is byref");
        return ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(value);
    }
    static void signature(Obj info,Obj returned) {
        uint32_t implementation=0;
        require(!(ba::api<uint32_t(*)(Obj,uint32_t*)>("il2cpp_method_get_flags")(info,&implementation)&0x10u)&&
            resultClass(info)==returned,"retired timeline original signature differs");
    }
    static Obj stoppedInvoke(Obj handler) {
        Obj found=nullptr;void* iterator=nullptr;
        while(Obj info=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(ba::klass(handler),&iterator)) {
            if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(info),"Invoke")||
                ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(info)!=1)continue;
            require(!found,"retired timeline stopped Invoke is ambiguous");found=info;
        }
        require(found,"retired timeline stopped Invoke missing");return found;
    }
    static Obj fieldClass(Obj object,const char* name,size_t offset) {
        field(object,name,offset);Obj info=ba::field(object,name);
        require(!(ba::api<uint32_t(*)(Obj)>("il2cpp_field_get_flags")(info)&0x10u),"retired timeline field is static");
        Obj value=ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(info);
        require(value&&!ba::api<bool(*)(Obj)>("il2cpp_type_is_byref")(value),"retired timeline field is byref");
        return ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(value);
    }
    static uint32_t registryId(Obj actor) {
        Obj id=type("Uncapped","Id");uint32_t alignment=0;
        require(fieldClass(actor,"<EventOwnerId>k__BackingField",0x30)==id&&
            ba::api<int32_t(*)(Obj,uint32_t*)>("il2cpp_class_value_size")(id,&alignment)==4,
            "retired timeline registry Id ABI differs");
        return ba::read<uint32_t>(actor,0x30); // Registry Id, never a native entity ID.
    }
    static void released(const Entry& entry) {
        require(entry.actor.get()&&entry.director.get()&&entry.config.get(),"retired timeline rooted object was lost");
        classIs(entry.actor.get(),"Uncapped","Unit");
        require(fieldClass(entry.actor.get(),"<DeadToTheSim>k__BackingField",0x160)==type("System","Boolean")&&
            ba::read<uint8_t>(entry.actor.get(),0x160)==1,"retired timeline owner is not an original dead Unit");
        field(entry.actor.get(),"_componentData",0x158);
        require(!ba::read<Obj>(entry.actor.get(),0x158)&&
            ba::read<Obj>(entry.actor.get(),0x168)==entry.config.get()&&
            ba::read<Obj>(entry.actor.get(),0x48)==entry.director.get()&&registryId(entry.actor.get())==entry.registryId,
            "retired timeline released owner changed");
        require(ba::read<Obj>(entry.director.get(),0x10)&&ba::read<uint8_t>(entry.config.get(),0x2c)==1&&
            (!entry.callbacksCaptured||ba::read<Obj>(entry.director.get(),0x28)==(entry.stopped?entry.stopped->get():nullptr)),
            "retired timeline director or callback ownership changed");
        const auto actual=resident(entry.actor.get());
        require(actual.entityId==entry.identity.entityId&&actual.unitType==entry.identity.unitType&&
            actual.armyId==entry.identity.armyId,"retired timeline resident identity changed");
        // This exact Unit override makes the known stopped callback return
        // without HandleLabelChange while dead. Other subscribers are refused.
        method(entry.actor.get(),"get_IsControlledBySim",0,0x060022dc,0x3c02a30);
        guard(0x3c02a30,"\x80\xb9\x60\x01\x00\x00\x00\x74\x03\x32\xc0\xc3\x48\x83\xb9\x58\x01\x00\x00\x00\x0f\x97\xc0\xc3",24);
    }
    static void callbacks(Entry& entry,bool capture) {
        Obj directorType=type("UnityEngine.Playables","PlayableDirector");
        Obj declared=fieldClass(entry.director.get(),"stopped",0x28);
        require(declared&&ba::api<bool(*)(Obj,Obj)>("il2cpp_class_is_assignable_from")(
            type("System","MulticastDelegate"),declared)&&
            !strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_namespace")(declared),"System")&&
            !strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(declared),"Action`1"),
            "retired timeline stopped delegate declaration differs");
        Obj handler=ba::read<Obj>(entry.director.get(),0x28);
        if(capture){if(handler)entry.stopped=std::make_unique<Root>(handler);}
        else require(handler==(entry.stopped?entry.stopped->get():nullptr),"retired timeline stopped delegate changed");
        unsigned count=0;
        if(handler) {
            require(ba::klass(handler)==declared,"retired timeline stopped concrete delegate differs");
            Obj invokeMethod=stoppedInvoke(handler);signature(invokeMethod,type("System","Void"));
            require(parameterClass(invokeMethod,0)==directorType,"retired timeline stopped argument differs");
            Root list(ba::call(handler,"GetInvocationList"));require(list.get(),"retired timeline subscriber list missing");
            const auto length=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(list.get());
            require(length<=16,"retired timeline subscriber count exceeds qualified bound");
            for(uintptr_t index=0;index<length;++index) {
                Root listener(ba::read<Obj>(list.get(),0x20+index*sizeof(Obj)));require(listener.get(),"retired timeline subscriber missing");
                Root target(ba::call(listener.get(),"get_Target"));
                const Obj observed=ba::get<Obj>(listener.get(),"method");
                if(target.get()!=entry.actor.get()||observed!=entry.callback)
                    ba::log("Retired timeline subscriber refused: entity=%u actor=%p target=%p method=%p expectedMethod=%p index=%llu",
                        entry.identity.entityId,entry.actor.get(),target.get(),observed,entry.callback,
                        static_cast<unsigned long long>(index));
                require(target.get()==entry.actor.get()&&observed==entry.callback,
                    "retired timeline has an unqualified stopped subscriber");
            }
            count=static_cast<unsigned>(length);
        }
        if(capture){entry.subscribers=count;entry.callbacksCaptured=true;}
        else require(count==entry.subscribers,"retired timeline subscriber count changed");
    }
    static int32_t state(const Entry& entry) {
        Root value(invoke(entry.getState,entry.director.get()));
        require(value.get()&&ba::klass(value.get())==entry.stateClass,"retired timeline state scalar differs");
        return unbox<int32_t>(value.get());
    }
    void roots(State& owner) const {
        requireOwned(owner);require(!owner.originalManagerUpdate,"retired timeline stop entered original update");
        require(&owner==owner_&&owner.world==world_&&owner.match==match_&&owner.thread==thread_&&
            owner.manager&&owner.simulation&&manager_&&simulation_&&frames_&&frame_&&
            manager_->get()&&simulation_->get()&&frames_->get()&&frame_->get()&&
            owner.manager->get()==manager_->get()&&owner.simulation->get()==simulation_->get(),
            "retired timeline manager or simulation root changed");
        require(ba::read<Obj>(manager_->get(),0x40)==simulation_->get()&&
            ba::read<Obj>(simulation_->get(),0x70)==manager_->get()&&
            ba::read<Obj>(simulation_->get(),0x148)==frames_->get(),"retired timeline frame owner changed");
    }
    void lease(State& owner,const Entry& entry) const {
        roots(owner);
        require(Current::resolveFrame(frames_->get())==frame_->get(),"retired timeline current frame changed");
        Current now(frames_->get());const auto next=now.identity(entry.identity.entityId);
        require(now.frame.get()==frame_->get()&&next&&next->unitType==entry.identity.unitType&&next->armyId==entry.identity.armyId&&
            now.retainedAlive(entry.identity.entityId)&&confirmedToken(owner,*next)==entry.token,
            "retired timeline canonical lifetime changed");
        const auto cached=owner.identities.find(entry.actor.get());
        require(cached!=owner.identities.end()&&cached->second.incarnation==entry.token&&
            cached->second.identity.entityId==entry.identity.entityId&&
            cached->second.identity.unitType==entry.identity.unitType&&cached->second.identity.armyId==entry.identity.armyId,
            "retired timeline cached actor lifetime changed");
        const auto retained=units(ba::read<Obj>(manager_->get(),0xa0));
        require(std::count(retained.begin(),retained.end(),entry.actor.get())==1,
            "retired timeline lost its retained actor membership");
        for(Obj actor:units(ba::read<Obj>(manager_->get(),0x10)))
            require(actor!=entry.actor.get()&&resident(actor).entityId!=entry.identity.entityId,
                "retired timeline actor was already recreated");
        released(entry);
        roots(owner);
    }
public:
    void prepare(State& owner,const std::vector<Retire>& actors,Obj frames,const Current& current) {
        requireOwned(owner);require(entries_.empty()&&!frames_,"retired timeline preflight repeated");std::set<Obj> directors;
        require(owner.manager&&owner.simulation&&owner.manager->get()&&owner.simulation->get()&&frames&&current.frame.get(),
            "retired timeline initial roots missing");
        owner_=&owner;world_=owner.world;match_=owner.match;thread_=owner.thread;
        manager_=std::make_unique<Root>(owner.manager->get());simulation_=std::make_unique<Root>(owner.simulation->get());
        frames_=std::make_unique<Root>(frames);frame_=std::make_unique<Root>(current.frame.get());
        for(const auto& actor:actors) {
            if(!actor.alreadyReleased)continue;
            classIs(actor.actor,"Uncapped","Unit");field(actor.actor,"_playableDirector",0x48);
            Obj director=ba::read<Obj>(actor.actor,0x48);if(!director)continue;
            require(actor.incarnation&&actor.resident.entityId!=UINT32_MAX&&
                actor.resident.entityId==actor.current.entityId&&actor.resident.unitType==actor.current.unitType&&
                actor.resident.armyId==actor.current.armyId&&confirmedToken(owner,actor.current)==actor.incarnation&&
                current.retainedAlive(actor.current.entityId),"retired timeline requires the same confirmed living identity");
            classIs(director,"UnityEngine.Playables","PlayableDirector");
            require(directors.insert(director).second,"retired timeline director ownership is ambiguous");
            field(director,"m_CachedPtr",0x10);require(ba::read<Obj>(director,0x10),"retired timeline director was destroyed");
            field(actor.actor,"_entityConfig",0x168);Obj config=ba::read<Obj>(actor.actor,0x168);
            require(config&&fieldClass(config,"IsHQ",0x2c)==type("System","Boolean")&&
                ba::read<uint8_t>(config,0x2c)==1,"retired timeline owner is not the original HQ presentation");
            auto entry=std::make_unique<Entry>(actor.actor,director,config);
            entry->identity=actor.current;entry->token=actor.incarnation;entry->registryId=registryId(actor.actor);
            require(fieldClass(actor.actor,"_playableDirector",0x48)==type("UnityEngine.Playables","PlayableDirector"),
                "retired timeline director field ABI differs");
            entry->stop=method(director,"Stop",0,0x06000018,0x50ddfb0);signature(entry->stop,type("System","Void"));
            entry->getState=method(director,"get_state",0,0x06000001,0x50dd470);
            entry->stateClass=resultClass(entry->getState);uint32_t alignment=0;
            require(entry->stateClass==type("UnityEngine.Playables","PlayState")&&
                ba::api<bool(*)(Obj)>("il2cpp_class_is_enum")(entry->stateClass)&&
                ba::api<int32_t(*)(Obj,uint32_t*)>("il2cpp_class_value_size")(entry->stateClass,&alignment)==4,
                "retired timeline original state enum differs");
            signature(entry->getState,entry->stateClass);
            Obj paused=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(entry->stateClass,"Paused");
            require(paused&&(ba::api<uint32_t(*)(Obj)>("il2cpp_field_get_flags")(paused)&0x50u)==0x50u,
                "retired timeline Paused enum literal differs");
            ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(paused,&entry->paused);
            entry->callback=method(actor.actor,"OnPlayableDirectorStopped",1,0x06001c04,0x3b927c0);
            signature(entry->callback,type("System","Void"));
            require(parameterClass(entry->callback,0)==type("UnityEngine.Playables","PlayableDirector"),
                "retired timeline original stopped callback ABI differs");
            guard(0x50ddfb0,"\x40\x53\x48\x83\xec\x20\x48\x8b\x05\xab\x80\xd8\x01\x48\x8b\xd9\x48\x85\xc0\x75\x18\x48\x8d\x0d\xcc\x34\x62\x00\xe8\xbf\x91\x53",32);
            guard(0x50dd470,"\x40\x53\x48\x83\xec\x20\x48\x8b\x05\x33\x8c\xd8\x01\x48\x8b\xd9\x48\x85\xc0\x75\x18\x48\x8d\x0d\xf4\x3d\x62\x00\xe8\xff\x9c\x53",32);
            guard(0x3b927c0,"\x40\x53\x48\x83\xec\x20\x48\x8b\x11\x48\x8b\xd9\x48\x8b\x82\x18\x03\x00\x00\x48\x8b\x92\x20\x03\x00\x00\xff\xd0\x84\xc0\x74\x19",32);
            released(*entry);callbacks(*entry,true);entries_.push_back(std::move(entry));
        }
    }
    void stop(State& owner) {
        for(auto& entry:entries_) {
            lease(owner,*entry);callbacks(*entry,false);require(!entry->attempted,"retired timeline stop retried");
            const auto before=state(*entry);
            ba::log("Prediction retired timeline stop begin: world=%llu match=%s entity=%u token=%llu ownerId=%u actor=%p director=%p beforeState=%d subscribers=%u beforePool=1",
                static_cast<unsigned long long>(owner.world),owner.match.c_str(),entry->identity.entityId,
                static_cast<unsigned long long>(entry->token),entry->registryId,entry->actor.get(),entry->director.get(),before,entry->subscribers);
            // Revalidate after the delegate/state getters and logging, directly
            // before the first mutation. Public delegate edits replace the
            // immutable delegate object; released() rechecks that exact root.
            lease(owner,*entry);entry->attempted=true;
            invoke(entry->stop,entry->director.get()); // Original Stop and its original stopped dispatch, once.
            lease(owner,*entry);require(state(*entry)==entry->paused,"retired timeline remained active after original Stop");
            ba::log("Prediction retired timeline stopped: world=%llu match=%s entity=%u token=%llu ownerId=%u director=%p afterState=%d originalStop=1 beforePool=1",
                static_cast<unsigned long long>(owner.world),owner.match.c_str(),entry->identity.entityId,
                static_cast<unsigned long long>(entry->token),entry->registryId,entry->director.get(),entry->paused);
        }
    }
};
