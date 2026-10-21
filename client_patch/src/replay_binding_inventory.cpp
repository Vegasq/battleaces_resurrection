#pragma once
// Explicit owned read-only inventory. Never click, create a behaviour, rebuild
// an event, or select a replay. The button may be hidden during healthy practice.
namespace ba_replay_binding {
using ba::Obj;using ba_local::Root;using ba_native_settings::require;
namespace ui=ba_practice_settings_ui;
static std::string nodyListener(Obj,Obj);
static bool finished=false;
static ULONGLONG due=0;
static std::string quote(const std::string& s){return ba_catalog::quote(s);}
static std::string identity(Obj value){return quote(std::to_string(reinterpret_cast<uintptr_t>(value)));}
static std::string className(Obj value) {
    if(!value)return "";
    Obj cls=ba::klass(value);
    return std::string(ba::api<const char*(*)(Obj)>("il2cpp_class_get_namespace")(cls))+"."+
        ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(cls);
}
static std::string text(Obj value) {
    if(!value)return "";
    require(ba::klass(value)==ba::find_class("System","String") &&
        ba::read<int>(value,0x10)>=0 && ba::read<int>(value,0x10)<=1024,"replay binding string bound/type");
    return ba_catalog::utf8(value);
}
static std::string named(Obj value,const char* field){return quote(text(ba::get<Obj>(value,field)));}
struct List {
    Root list,items;int size,version;
    explicit List(Obj value,int maximum=32):list(value),items(ba::get<Obj>(value,"_items")),
        size(ba::get<int>(value,"_size")),version(ba::get<int>(value,"_version")) {
        require(size>=0 && size<=maximum && items.get() && ba_catalog::length(items.get())>=static_cast<size_t>(size) &&
            ba_catalog::length(items.get())<=1024,"replay binding list capacity");
    }
    Obj at(int i)const {require(i>=0 && i<size,"replay binding list index");return ba_catalog::arrayAt(items.get(),i);}
    void unchanged()const {
        require(ba::get<Obj>(list.get(),"_items")==items.get() && ba::get<int>(list.get(),"_size")==size &&
            ba::get<int>(list.get(),"_version")==version,"replay binding list changed during observation");
    }
};
template<class F> static std::string array(Obj value,F encode) {
    if(!value)return "null";
    List list(value);std::string out="[";
    for(int i=0;i<list.size;++i){Root item(list.at(i));require(item.get()!=nullptr,"replay binding null entry");
        if(i)out+=",";out+=encode(item.get());}
    list.unchanged();return out+"]";
}
static std::string reference(Obj value){return "{\"id\":"+identity(value)+",\"class\":"+quote(className(value))+"}";}
static std::string argument(Obj value) {
    if(!value)return "null";
    require(ui::exact(value,"UnityEngine.Events","ArgumentCache"),"replay binding argument type");
    return "{\"object\":"+reference(ba::get<Obj>(value,"m_ObjectArgument"))+
        ",\"object_type\":"+named(value,"m_ObjectArgumentAssemblyTypeName")+
        ",\"int\":"+std::to_string(ba::get<int>(value,"m_IntArgument"))+
        ",\"float\":"+std::to_string(ba::get<float>(value,"m_FloatArgument"))+
        ",\"string\":"+named(value,"m_StringArgument")+
        ",\"bool\":"+(ba::get<bool>(value,"m_BoolArgument")?"true":"false")+"}";
}
static std::string persistent(Obj value) {
    require(ui::exact(value,"UnityEngine.Events","PersistentCall"),"replay binding persistent type");
    Root target(ba::get<Obj>(value,"m_Target")),args(ba::get<Obj>(value,"m_Arguments"));
    const auto name=text(ba::get<Obj>(value,"m_MethodName"));
    bool methodPresent=false;
    if(target.get() && !name.empty()) {
        for(Obj cls=ba::klass(target.get());cls;cls=ba::api<Obj(*)(Obj)>("il2cpp_class_get_parent")(cls)) {
            void* iterator=nullptr;
            while(Obj method=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(cls,&iterator))
                if(name==ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(method))methodPresent=true;
        }
    }
    return "{\"target\":"+reference(target.get())+",\"declared_type\":"+named(value,"m_TargetAssemblyTypeName")+
        ",\"method\":"+quote(name)+",\"method_name_present\":"+(methodPresent?"true":"false")+
        ",\"mode\":"+std::to_string(ba::get<int>(value,"m_Mode"))+
        ",\"state\":"+std::to_string(ba::get<int>(value,"m_CallState"))+
        ",\"arguments\":"+argument(args.get())+"}";
}
static std::string event(Obj value) {
    if(!value)return "null";
    Root group(ba::get<Obj>(value,"m_PersistentCalls")),calls(ba::get<Obj>(group.get(),"m_Calls"));
    Root invoked(ba::get<Obj>(value,"m_Calls"));
    // Read existing lists directly. No PrepareInvoke/Rebuild/Invoke/get_onClickEvent.
    return "{\"persistent\":"+array(calls.get(),persistent)+
        ",\"runtime\":"+array(ba::get<Obj>(invoked.get(),"m_RuntimeCalls"),reference)+
        ",\"compiled_persistent\":"+array(ba::get<Obj>(invoked.get(),"m_PersistentCalls"),reference)+
        ",\"executing\":"+array(ba::get<Obj>(invoked.get(),"m_ExecutingCalls"),reference)+
        ",\"dirty\":"+(ba::get<bool>(value,"m_CallsDirty")?"true":"false")+"}";
}
static std::string runner(Obj value) {
    require(ui::exact(value,"Doozy.Runtime.Mody","ModyActionRunner"),"replay binding runner type");
    Root module(ba::get<Obj>(value,"Module"));
    return "{\"module\":"+reference(module.get())+",\"module_name\":"+(module.get()?named(module.get(),"ModuleName"):"null")+
        ",\"action\":"+named(value,"ActionName")+",\"run\":"+std::to_string(ba::get<int>(value,"Run"))+
        ",\"ignore_cooldown\":"+(ba::get<bool>(value,"IgnoreCooldown")?"true":"false")+"}";
}
static std::string behaviour(Obj value) {
    require(ui::exact(value,"Doozy.Runtime.UIManager","UIBehaviour"),"replay binding behaviour type");
    return "{\"id\":"+identity(value)+",\"kind\":"+std::to_string(ba::get<int>(value,"BehaviourName"))+
        ",\"selectable\":"+identity(ba::get<Obj>(value,"Selectable"))+
        ",\"receiver\":"+reference(ba::get<Obj>(value,"Receiver"))+
        ",\"runners\":"+array(ba::get<Obj>(value,"Runners"),runner)+
        ",\"event\":"+event(ba::get<Obj>(value,"Event"))+"}";
}
static std::string callback(Obj value,unsigned depth=0) {
    if(!value)return "null";
    require(depth<4,"replay signal delegate depth");
    Root target(ba::get<Obj>(value,"m_target")),children(ba::get<Obj>(value,"delegates"));
    const auto address=ba::get<uintptr_t>(value,"method");
    std::string method="",declaring="";uint32_t token=0;int parameters=-1;
    // Do not dereference an arbitrary MethodInfo pointer. Resolve it only by
    // equality to actual metadata methods on this already existing target.
    unsigned parents=0;
    for(Obj cls=target.get()?ba::klass(target.get()):nullptr;cls;cls=ba::api<Obj(*)(Obj)>("il2cpp_class_get_parent")(cls)) {
        require(++parents<=32,"replay signal target inheritance bound");void* iterator=nullptr;unsigned methods=0;
        while(Obj candidate=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(cls,&iterator)) {
            require(++methods<=4096,"replay signal method bound");
            if(reinterpret_cast<uintptr_t>(candidate)!=address)continue;
            method=ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(candidate);
            declaring=std::string(ba::api<const char*(*)(Obj)>("il2cpp_class_get_namespace")(cls))+"."+
                ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(cls);
            token=ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_token")(candidate);
            parameters=static_cast<int>(ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(candidate));
        }
    }
    std::string nested="[";
    if(children.get()) {
        const auto count=ui::arrayCount(children.get(),32);
        for(size_t i=0;i<count;++i){if(i)nested+=",";Root child(ui::arrayItem(children.get(),i));
            require(child.get()!=value,"replay signal cyclic delegate");nested+=callback(child.get(),depth+1);}
    }
    nested+="]";
    return "{\"id\":"+identity(value)+",\"target\":"+reference(target.get())+
        ",\"declaring_class\":"+quote(declaring)+",\"method\":"+quote(method)+
        ",\"token\":"+std::to_string(token)+",\"parameters\":"+std::to_string(parameters)+
        ",\"metadata_resolved\":"+(!method.empty()?"true":"false")+",\"delegates\":"+nested+"}";
}
static std::string receiver(Obj value,Obj stream) {
    require(value!=nullptr,"replay signal null receiver");
    if(!ui::exact(value,"Doozy.Runtime.Signals","SignalReceiver"))
        return "{\"receiver\":"+reference(value)+",\"typed\":false,\"stream\":null,\"stream_matches\":null,\"connected\":null,\"disconnecting\":null,\"callback\":null}";
    Root associated(ba::get<Obj>(value,"<stream>k__BackingField"));
    Root action(ba::get<Obj>(value,"<onSignal>k__BackingField"));
    Root target(action.get()?ba::get<Obj>(action.get(),"m_target"):nullptr);
    return "{\"receiver\":"+reference(value)+",\"typed\":true,\"stream\":"+reference(associated.get())+
        ",\"stream_matches\":"+(associated.get()==stream?"true":"false")+
        ",\"connected\":"+(ba::get<bool>(value,"<isConnected>k__BackingField")?"true":"false")+
        ",\"disconnecting\":"+(ba::get<bool>(value,"<isDisconnecting>k__BackingField")?"true":"false")+",\"callback\":"+
        callback(action.get())+
        (ba::flag(L"-replay-nody-inventory") && ui::exact(target.get(),"Doozy.Runtime.UIManager.Nodes.Listeners","UIButtonNodyListener")?
            ",\"nody\":"+nodyListener(target.get(),value):"")+"}";
}
static std::string signalStream() {
    Obj cls=ba::find_class("Doozy.Runtime.UIManager.Components","UIButton");
    Obj field=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(cls,"s_stream");
    require(field && (ba::api<unsigned(*)(Obj)>("il2cpp_field_get_flags")(field)&0x10),"replay signal original static stream field missing");
    Obj existing=nullptr;ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(field,&existing);
    Root stream(existing);
    require(ui::exact(stream.get(),"Doozy.Runtime.Signals","SignalStream") &&
        text(ba::get<Obj>(stream.get(),"<category>k__BackingField"))=="UISelectable" &&
        text(ba::get<Obj>(stream.get(),"<name>k__BackingField"))=="UIButton","replay signal existing UIButton stream missing/different");
    Root receivers(ba::get<Obj>(stream.get(),"<receivers>k__BackingField"));List values(receivers.get());
    std::string out="{\"stream\":"+reference(stream.get())+",\"category\":\"UISelectable\",\"name\":\"UIButton\""+
        ",\"signals_counter\":"+std::to_string(ba::get<int>(stream.get(),"<signalsCounter>k__BackingField"))+
        ",\"global_callback\":"+callback(ba::get<Obj>(stream.get(),"OnSignal"))+",\"receivers\":[";
    for(int i=0;i<values.size;++i){Root entry(values.at(i));if(i)out+=",";out+=receiver(entry.get(),stream.get());}
    values.unchanged();return out+"]}";
}
static std::string path(Obj value) {
    auto transform=std::make_unique<Root>(ba::call(value,"get_transform"));std::string out;
    for(unsigned depth=0;transform->get();++depth) {
        require(depth<32,"replay binding hierarchy depth");
        Root name(ba::call(transform->get(),"get_name"));out=text(name.get())+(out.empty()?"":"/"+out);
        Root parent(ba::call(transform->get(),"get_parent"));transform=std::make_unique<Root>(parent.get());
    }
    return out;
}
static std::string snapshot(Obj controller,Obj button) {
    Root container(ba::get<Obj>(button,"Behaviours")),id(ba::get<Obj>(button,"Id"));
    require(container.get() && id.get(),"replay binding existing container/id missing");
    require(ba::get<Obj>(container.get(),"Selectable")==button,"replay binding container owner");
    return "{\"controller\":"+reference(controller)+",\"button\":"+reference(button)+
        ",\"path\":"+quote(path(button))+",\"active\":"+(ui::active(button)?"true":"false")+
        ",\"initialized\":"+(ba::get<bool>(button,"<selectableInitialized>k__BackingField")?"true":"false")+
        ",\"signal_category\":"+named(id.get(),"Category")+",\"signal_name\":"+named(id.get(),"Name")+
        ",\"signal_custom\":"+(ba::get<bool>(id.get(),"Custom")?"true":"false")+
        ",\"behaviours\":"+array(ba::get<Obj>(container.get(),"Behaviours"),behaviour)+
        (ba::flag(L"-replay-signal-inventory")?",\"button_stream\":"+signalStream():"")+"}";
}
static void observe() {
    if(!ba::flag(L"-replay-binding-inventory") || finished || GetTickCount64()<due)return;
    due=GetTickCount64()+250;
    try {
        require(ui::unityThread() && ba::offlinePractice() && ba::flag(L"-practice-ai-smoke") &&
            ba_native_settings::session && ba_native_settings::session->profile().rfind("nativestest_",0)==0,
            "replay binding inventory requires owned offline Unity practice");
        Root fsm(ba::get<Obj>(ba::owner,"_mainFSM")),current(ba::get<Obj>(fsm.get(),"_currentState"));
        if(!current.get() || className(current.get())!=".RGameInGameState")return;
        Root replay(ba::get<Obj>(ba::owner,"<Replay>k__BackingField")),simulation(ba::get<Obj>(replay.get(),"_simulation"));
        const auto world=ba::read<uint64_t>(simulation.get(),0x1a8);
        if(!world || !ba::read<bool>(simulation.get(),0x1a0) || ba::read<int>(simulation.get(),0xac)<30)return;
        Root type(ui::reflectedType("Uncapped","ConcedeFlowUIController"));void* args[]={type.get()};
        Root values(ba::invoke(ba::find_class("UnityEngine","Resources"),nullptr,"FindObjectsOfTypeAll",1,args));
        const auto count=ui::arrayCount(values.get(),64);unsigned found=0;
        std::unique_ptr<Root> selected,button;
        for(size_t i=0;i<count;++i) {
            Obj candidate=ui::arrayItem(values.get(),i);
            if(ba::get<Obj>(candidate,"_simulation")!=simulation.get() || !ui::active(candidate))continue;
            require(++found==1 && ba::get<Obj>(candidate,"_signalRouter")==ba::read<Obj>(ba::owner,0x238) &&
                ba::get<Obj>(candidate,"_gameServerIntegration") && ba::get<Obj>(candidate,"_signalReceiver"),
                "replay binding current controller ownership ambiguous");
            selected=std::make_unique<Root>(candidate);button=std::make_unique<Root>(ba::get<Obj>(candidate,"_leaveReplayButton"));
        }
        if(!found)return;
        require(ui::exact(button->get(),"Doozy.Runtime.UIManager.Components","UIButton"),"replay binding original button missing");
        const auto before=snapshot(selected->get(),button->get()),after=snapshot(selected->get(),button->get());
        require(before==after && ba::get<Obj>(fsm.get(),"_currentState")==current.get() &&
            ba::get<Obj>(replay.get(),"_simulation")==simulation.get() && ba::read<uint64_t>(simulation.get(),0x1a8)==world &&
            ba::read<bool>(simulation.get(),0x1a0),"replay binding owner/world/actions changed");
        finished=true;
        ba::log("REPLAY BINDING inventory: %s",before.c_str());
        ba::log("REPLAY BINDING inventory passed: version=1 phase=healthy-practice worldStable=1 fsmStable=1 bindingsStable=1 clicks=0 behavioursAdded=0 eventRebuilds=0 rootsReleasedOnReturn=1");
    } catch(const std::exception& error){finished=true;ba::log("Replay binding inventory failed: %s",error.what());}
}
}
