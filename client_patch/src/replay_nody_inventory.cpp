#pragma once
// Only the already owned read-only replay inventory calls this. Read serialized
// ports and existing event objects; never GetValue<T>, transition or invoke.
namespace ba_replay_binding {
static bool derives(Obj cls,Obj base) {
    return cls==base || ba::api<bool(*)(Obj,Obj,bool)>("il2cpp_class_is_subclass_of")(cls,base,false);
}
static std::string graphEvents(Obj value) {
    const Obj unityEvent=ba::find_class("UnityEngine.Events","UnityEventBase");
    const Obj modyEvent=ba::find_class("Doozy.Runtime.Mody","ModyEventBase");
    const Obj delegate=ba::find_class("System","Delegate");
    std::string out="[";unsigned parents=0,fields=0,emitted=0;
    for(Obj cls=ba::klass(value);cls;cls=ba::api<Obj(*)(Obj)>("il2cpp_class_get_parent")(cls)) {
        require(++parents<=32,"replay Nody event inheritance bound");void* iterator=nullptr;
        while(Obj field=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_fields")(cls,&iterator)) {
            require(++fields<=256,"replay Nody event field bound");
            if(ba::api<unsigned(*)(Obj)>("il2cpp_field_get_flags")(field)&0x10)continue;
            Obj type=ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(field);
            Obj declared=ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(type);
            if(!declared)continue;
            const bool isEvent=derives(declared,unityEvent),isMody=derives(declared,modyEvent),isDelegate=derives(declared,delegate);
            if(!isEvent && !isMody && !isDelegate)continue;
            Obj fieldValue=nullptr;ba::api<void(*)(Obj,Obj,void*)>("il2cpp_field_get_value")(value,field,&fieldValue);
            Root action(fieldValue);if(!action.get())continue;
            require(++emitted<=32,"replay Nody event count bound");if(emitted>1)out+=",";
            const char* name=ba::api<const char*(*)(Obj)>("il2cpp_field_get_name")(field);
            out+="{\"field\":"+quote(name)+",\"value\":"+reference(action.get());
            if(isEvent)out+=",\"kind\":\"event\",\"event\":"+event(action.get());
            else if(isDelegate)out+=",\"kind\":\"delegate\",\"callback\":"+callback(action.get());
            else {
                out+=",\"kind\":\"mody\",\"runners\":"+array(ba::get<Obj>(action.get(),"Runners"),runner);
                Obj eventField=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(ba::klass(action.get()),"Event");
                if(eventField)out+=",\"event\":"+event(ba::get<Obj>(action.get(),"Event"));
            }
            out+="}";
        }
    }
    return out+"]";
}
static std::string graphPort(Obj value) {
    require(derives(ba::klass(value),ba::find_class("Doozy.Runtime.Nody","FlowPort")),"replay Nody port type");
    return "{\"object\":"+reference(value)+",\"node_id\":"+named(value,"NodeId")+
        ",\"port_id\":"+named(value,"PortId")+",\"direction\":"+std::to_string(ba::get<int>(value,"Direction"))+
        ",\"connections\":"+array(ba::get<Obj>(value,"Connections"),[](Obj v){return quote(text(v));})+
        ",\"value_type\":"+named(value,"ValueTypeQualifiedName")+",\"value\":"+named(value,"Value")+"}";
}
static std::string graphNode(Obj value,Obj graph) {
    require(derives(ba::klass(value),ba::find_class("Doozy.Runtime.Nody","FlowNode")),"replay Nody node type");
    return "{\"object\":"+reference(value)+",\"node_id\":"+named(value,"NodeId")+
        ",\"graph_id\":"+named(value,"FlowGraphId")+",\"name\":"+named(value,"NodeName")+
        ",\"state\":"+std::to_string(ba::get<int>(value,"NodeState"))+
        ",\"graph_matches\":"+(ba::get<Obj>(value,"<flowGraph>k__BackingField")==graph?"true":"false")+
        ",\"inputs\":"+array(ba::get<Obj>(value,"InputPorts"),graphPort)+
        ",\"outputs\":"+array(ba::get<Obj>(value,"OutputPorts"),graphPort)+
        ",\"events\":"+graphEvents(value)+"}";
}
static std::string nodyListener(Obj value,Obj receiver) {
    require(ba::flag(L"-replay-signal-inventory") && ba::flag(L"-replay-binding-inventory"),
        "replay Nody inventory requires the owned passive stream inventory");
    Root node(ba::get<Obj>(value,"<node>k__BackingField")),forward(ba::get<Obj>(value,"<callback>k__BackingField"));
    require(node.get() && forward.get(),"replay Nody existing node/callback missing");
    Root graph(ba::get<Obj>(node.get(),"<flowGraph>k__BackingField"));
    require(graph.get() && derives(ba::klass(graph.get()),ba::find_class("Doozy.Runtime.Nody","FlowGraph")),
        "replay Nody existing graph missing");
    Root nodes(ba::get<Obj>(graph.get(),"Nodes"));List entries(nodes.get(),128);
    std::string encoded="[";
    for(int i=0;i<entries.size;++i){Root entry(entries.at(i));require(entry.get()!=nullptr,"replay Nody null node");
        if(i)encoded+=",";encoded+=graphNode(entry.get(),graph.get());}
    entries.unchanged();encoded+="]";
    return "{\"listener\":"+reference(value)+",\"receiver_matches\":"+
        (ba::get<Obj>(value,"<receiver>k__BackingField")==receiver?"true":"false")+
        ",\"connected\":"+(ba::get<bool>(value,"<isConnected>k__BackingField")?"true":"false")+
        ",\"node\":"+reference(node.get())+",\"forwarded\":"+callback(forward.get())+
        ",\"graph\":{\"object\":"+reference(graph.get())+",\"graph_id\":"+named(graph.get(),"Id")+
        ",\"name\":"+named(graph.get(),"GraphName")+",\"state\":"+std::to_string(ba::get<int>(graph.get(),"GraphState"))+
        ",\"active_node\":"+reference(ba::get<Obj>(graph.get(),"ActiveNode"))+
        ",\"active_subgraph\":"+reference(ba::get<Obj>(graph.get(),"<activeSubGraph>k__BackingField"))+
        ",\"parent_graph\":"+reference(ba::get<Obj>(graph.get(),"<parentGraph>k__BackingField"))+
        ",\"nodes\":"+encoded+"}}";
}
}
