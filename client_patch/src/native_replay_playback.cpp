#pragma once
// Explicit original batch playback qualification only. No ordinary menu route.
namespace ba_native_replay_playback {
using ba::Obj;using ba_local::Root;using ba_native_settings::require;
namespace codec=ba_native_replay_reader;
static bool enabled(){return ba::flag(L"-native-replay-playback-smoke");}
struct Closed {
    Root reflected;Obj method;
    explicit Closed(Obj value):reflected(value),method(ba::api<Obj(*)(Obj)>("il2cpp_method_get_from_reflection")(reflected.get())){}
};
static std::unique_ptr<Closed> generic(const char* name,uint32_t token,Obj argumentClass,uintptr_t rva) {
    Obj klass=codec::type("Uncapped","Variable","RGame.VariableRegister.dll"),open=nullptr;void* iterator=nullptr;
    while(Obj candidate=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(klass,&iterator)) {
        if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(candidate),name) ||
           ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_token")(candidate)!=token)continue;
        require(!open && ba::api<bool(*)(Obj)>("il2cpp_method_is_generic")(candidate),"replay variable generic definition differs");open=candidate;
    }
    require(open!=nullptr,"replay variable original generic method missing");
    Root reflected(ba::api<Obj(*)(Obj,Obj)>("il2cpp_method_get_object")(open,klass));require(reflected.get()!=nullptr,"replay variable reflection missing");
    Root types(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(codec::type("System","Type","mscorlib.dll"),1));
    Root argument(ba::api<Obj(*)(Obj)>("il2cpp_type_get_object")(ba::api<Obj(*)(Obj)>("il2cpp_class_get_type")(argumentClass)));
    require(types.get() && argument.get(),"replay variable generic argument missing");ba_tables::arraySet(types.get(),0,argument.get());
    void* args[]={types.get()};Root closed(codec::invoke(codec::method(ba::klass(reflected.get()),"MakeGenericMethod",1,0x349cf30,0x0600265b),reflected.get(),args));
    require(closed.get()!=nullptr,"replay variable generic construction failed");auto result=std::make_unique<Closed>(closed.get());
    require(result->method && ba::read<Obj>(result->method,0)==ba::native<Obj>(rva) &&
        ba::api<Obj(*)(Obj)>("il2cpp_method_get_class")(result->method)==klass &&
        ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_token")(result->method)==token &&
        ba::api<bool(*)(Obj)>("il2cpp_method_is_inflated")(result->method),"replay variable closed method identity differs");
    Root arguments(ba::call(result->reflected.get(),"GetGenericArguments")),contains(ba::call(result->reflected.get(),"get_ContainsGenericParameters"));
    require(ba_catalog::length(arguments.get())==1 && ba_catalog::arrayAt(arguments.get(),0)==argument.get() &&
        !ba_catalog::unbox<bool>(contains.get()),"replay variable closed generic type differs");
    return result;
}
struct Probe {
    Root owner,registry,replay,target,initial;
    ba_native_settings::Handle file;
    std::unique_ptr<Closed> setter,getObject,getFiles;
    std::unique_ptr<Root> paths,simulation;
    bool armed=false,failed=false,metadata=false,entered=false;
    int frames=0,last=-1,lastLogged=-1000;unsigned samples=0;ULONGLONG due=0;
    Probe(Obj a,Obj b,Obj c,Obj d,Obj e):owner(a),registry(b),replay(c),target(d),initial(e){}
};
static auto& probe=*new std::unique_ptr<Probe>(); // Retain pins/roots through batch Quit.
static Obj variable(const char* field) {
    Obj result=ba::get<Obj>(probe->registry.get(),field);
    require(result && ba::klass(result)==codec::type("Uncapped","Variable","RGame.VariableRegister.dll"),"replay variable field type differs");return result;
}
static Obj read(Obj variable,bool persistent,bool files=false) {
    void* args[]={&persistent};return codec::invoke(files?probe->getFiles->method:probe->getObject->method,variable,args);
}
static void defaults() {
    for(bool persistent:{false,true}) {
        for(const char* name:{"ReplaySmokeTest","AISmokeTest","PerfTest","ProfilingOutput","PlayModeTest","DPSTest","_forceCrashGame","_simulationProfilingEnabled"}) {
            Root value(read(variable(name),persistent));require(value.get() && ba::klass(value.get())==codec::type("System","Boolean","mscorlib.dll") &&
                !ba_catalog::unbox<bool>(value.get()),"replay batch requires original safe Boolean defaults");
        }
        for(const char* name:{"ReplayStartFrame","ReplayEndFrame"}) {
            Root value(read(variable(name),persistent));require(value.get() && ba::klass(value.get())==codec::type("System","Int32","mscorlib.dll") &&
                ba_catalog::unbox<int>(value.get())==-1,"replay batch requires full original frame range");
        }
        Root marker(read(variable("ProfileMarkersInFile"),persistent));require(marker.get() &&
            ba::klass(marker.get())==codec::type("System","String","mscorlib.dll") && ba_native_settings::wide(marker.get()).empty(),
            "replay batch requires empty original capture marker");
    }
}
static void* prepare(void* initial,void* owner) {
    require(enabled() && !probe && ba::initialThread==GetCurrentThreadId() && ba_native_settings::session,
        "replay batch requires one initialized Unity startup");
    const auto& profile=ba_native_settings::session->profile();const std::string prefix="nativestest_replay_";
    require(profile.size()==prefix.size()+12 && profile.rfind(prefix,0)==0 && profile.find_first_not_of("0123456789abcdef",prefix.size())==std::string::npos,
        "replay batch requires a fresh owned profile");
    require(owner && ba::klass(owner)==codec::type("Uncapped","RGameSingleton","RGame.dll") && ba::read<Obj>(initial,0x18)==owner &&
        ba::read<Obj>(owner,0x38) && !ba_practice::active() && !ba_local::server() &&
        ba_client::worldOwner==ba_client::Owner::None && !ba_bootstrap::creating && !ba_bootstrap::awaitingWorld,
        "replay batch singleton/startup ownership differs");
    codec::method(ba::klass(initial),"Update",0,0x3dec5a0,0x06000a57);
    Root replay(ba::read<Obj>(owner,0x40)),target(ba::read<Obj>(owner,0x308));
    require(replay.get() && ba::klass(replay.get())==codec::type("Uncapped","Replay","RGame.dll"),"replay batch existing Replay type differs");
    // TransitionTo requests NextState; the FSM executor supplies destination
    // Context before TransitionIn. Require this fresh state to be unentered.
    require(target.get() && ba::get<Obj>(owner,"_rgameReplayFileState")==target.get() &&
        !ba::read<Obj>(target.get(),0x18),"replay batch existing target context differs");
    codec::method(ba::klass(target.get()),"TransitionIn",0,0x3df48b0,0x06000aca);
    const auto registryType=codec::type("Uncapped","VariableRegister","RGame.VariableRegister.dll");
    Obj field=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(registryType,"InstanceInternal");
    require(field && (ba::api<unsigned(*)(Obj)>("il2cpp_field_get_flags")(field)&0x10),"replay registry existing static field missing");
    Obj registry=nullptr;ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(field,&registry);
    require(registry && ba::klass(registry)==registryType,"replay registry is not already initialized");
    probe=std::make_unique<Probe>(owner,registry,replay.get(),target.get(),initial);
    const auto stringType=codec::type("System","String","mscorlib.dll");Obj stringsType=ba::api<Obj(*)(Obj,unsigned)>("il2cpp_array_class_get")(stringType,1);
    probe->setter=generic("Set",0x06000017,codec::type("System","Object","mscorlib.dll"),0x1279a80);
    probe->getObject=generic("Get",0x06000018,codec::type("System","Object","mscorlib.dll"),0x12790d0);
    probe->getFiles=generic("Get",0x06000018,stringsType,0x12790d0);defaults();
    Root files(variable("ReplayFiles")),live(read(files.get(),false,true)),saved(read(files.get(),true,true));
    require(live.get() && saved.get() && ba::klass(live.get())==stringsType && ba::klass(saved.get())==stringsType &&
        ba_catalog::length(live.get())==0 && ba_catalog::length(saved.get())==0,"replay batch refuses preexisting replay intent");
    auto& destination=ba_native_storage::destination(ba_native_storage::Kind::Replays);
    const auto selected=destination.directory.apiPath()+L"\\native-playback-"+std::wstring(100,L'x')+L".rep";
    probe->file.value=CreateFileW(selected.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_FLAG_OPEN_REPARSE_POINT,nullptr);
    ba_native_settings::ordinary(probe->file.value);LARGE_INTEGER size{};
    require(GetFileSizeEx(probe->file.value,&size) && size.QuadPart>0 && size.QuadPart<=4*1024*1024,"replay batch file bound");
    wchar_t final[32768];const DWORD length=GetFinalPathNameByHandleW(probe->file.value,final,32768,FILE_NAME_NORMALIZED|VOLUME_NAME_DOS);
    require(length && length<32768 && !_wcsicmp(final,selected.c_str()),"replay batch selected file escapes pinned profile");
    Root path(ba::api<Obj(*)(const wchar_t*,int32_t)>("il2cpp_string_new_utf16")(selected.data(),static_cast<int32_t>(selected.size())));
    probe->paths=std::make_unique<Root>(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(stringType,1));
    require(path.get() && probe->paths->get(),"replay batch selected path allocation failed");ba_tables::arraySet(probe->paths->get(),0,path.get());
    Root fsm(ba::read<Obj>(owner,0x2b0)),before(ba::get<Obj>(fsm.get(),"_currentState"));
    require(before.get()==initial && ba::read<Obj>(fsm.get(),0x10)==owner,"replay batch initial FSM changed");
    bool persistent=false;void* args[]={probe->paths->get(),&persistent};codec::invoke(probe->setter->method,files.get(),args);
    Root actual(read(files.get(),false,true)),retained(read(files.get(),true,true));
    require(actual.get()==probe->paths->get() && ba::klass(actual.get())==stringsType && ba_catalog::length(actual.get())==1 &&
        ba_catalog::arrayAt(actual.get(),0)==path.get() && retained.get()==saved.get() && ba_catalog::length(retained.get())==0 &&
        ba::get<Obj>(fsm.get(),"_currentState")==initial,"replay variable original readback/persistence/FSM differs");
    defaults();int start=-1,end=-1;void* captureArgs[]={&start,&end};
    Root capture(codec::invoke(codec::method(ba::klass(owner),"ShouldCapture",2,0x3dea120,0x06000a4e),owner,captureArgs));
    require(!ba_catalog::unbox<bool>(capture.get()),"replay batch unexpectedly requested capture");
    probe->armed=true;
    ba::log("NATIVE REPLAY playback armed: profile=%s selected=%s persistentUnchanged=1 frameStart=-1 frameEnd=-1 capture=0 helperTick=0 BA_RESURRECTION_NATIVE_REPLAY_PLAYBACK_V1",
        profile.c_str(),ba_catalog::quote(ba_native_settings::utf8(selected)).c_str());
    return target.get();
}
static void observe() {
    if(!probe || !probe->armed || probe->failed || GetTickCount64()<probe->due)return;probe->due=GetTickCount64()+50;
    try {
        require(ba::initialThread==GetCurrentThreadId() && ba::owner==probe->owner.get() && ba::read<Obj>(ba::owner,0x40)==probe->replay.get(),
            "replay observer owner differs");
        Root fsm(ba::read<Obj>(ba::owner,0x2b0)),current(ba::get<Obj>(fsm.get(),"_currentState"));
        require(ba::read<Obj>(fsm.get(),0x10)==ba::owner,"replay observer FSM owner differs");
        if(current.get()!=probe->target.get()) {
            require(!probe->entered && current.get()==probe->initial.get() &&
                ba::read<Obj>(current.get(),0x10)==probe->target.get() && !ba::read<Obj>(probe->target.get(),0x18),
                "replay observer startup transition differs");return;
        }
        require(ba::read<Obj>(probe->target.get(),0x18)==ba::owner,"replay observer entered context differs");
        if(!probe->entered){probe->entered=true;ba::log("NATIVE REPLAY playback entered: originalFsmContext=1 existingState=1 helperContextWrites=0");}
        Root game(ba::get<Obj>(probe->replay.get(),"_gameData"));if(!game.get())return;
        Root frames(codec::get(probe->replay.get(),"get_FrameCount",0x3ddb470,0x0600092a)),last(codec::get(probe->replay.get(),"get_LastFrame",0xad70e0,0x0600092c));
        const int count=ba_catalog::unbox<int>(frames.get()),end=ba_catalog::unbox<int>(last.get());if(!count)return;
        require(count>0 && count<=65536 && end==count-1,"replay observer recording count differs");
        if(!probe->metadata) {
            const auto digest=ba_lan::sha(ba_lan::serialize(game.get()));std::string hash;char byte[3];
            for(unsigned char value:digest){sprintf_s(byte,"%02x",value);hash+=byte;}
            probe->frames=count;probe->last=end;probe->metadata=true;
            ba::log("NATIVE REPLAY playback data: frames=%d last=%d gameDataSha256=%s originalSerialization=1",count,end,hash.c_str());
        }
        require(count==probe->frames && end==probe->last,"replay observer recording changed");
        Root simulation(ba::get<Obj>(probe->replay.get(),"_simulation"));require(simulation.get() &&
            ba::klass(simulation.get())==codec::type("Uncapped","Simulation","RGame.dll"),"replay observer simulation differs");
        Root world(codec::get(simulation.get(),"get_World",0x897250,0x0600122b));const auto handle=ba_catalog::unbox<uint64_t>(world.get());if(!handle)return;
        if(!probe->simulation)probe->simulation=std::make_unique<Root>(simulation.get());require(probe->simulation->get()==simulation.get(),"replay observer simulation generation changed");
        Root sim(codec::get(simulation.get(),"get_CurrentSimFrame",0xae5970,0x06001213)),presented(codec::get(simulation.get(),"get_CurrentPresentedFrame",0x214cb90,0x06001214));
        const int frame=ba_catalog::unbox<int>(presented.get());if(frame<probe->lastLogged+200 && frame!=end)return;
        require(++probe->samples<=512,"replay observer sample bound");probe->lastLogged=frame;
        Root speed(codec::get(probe->replay.get(),"get_PlaybackSpeed",0x87c8b0,0x06000938));
        ba::log("NATIVE REPLAY playback progress: sim=%d presented=%d world=%llu speed=%.3f frames=%d last=%d observerOnly=1",
            ba_catalog::unbox<int>(sim.get()),frame,static_cast<unsigned long long>(handle),static_cast<double>(ba_catalog::unbox<float>(speed.get())),count,end);
    }catch(const std::exception& error){probe->failed=true;ba::log("Native replay observation failed: %s",error.what());}
}
}
