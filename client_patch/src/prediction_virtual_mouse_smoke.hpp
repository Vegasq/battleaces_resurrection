#pragma once
#include <cmath>
#include <cstdint>
#include <cstring>
#include <initializer_list>
#include <memory>
#include <string>
#include <vector>
#include "prediction_actor_fixture_smoke.hpp"

// Owned-process diagnostic borrowing the Mouse already bound to the owner's
// original actions. No device is added, removed, made current or reconfigured;
// no OS input is injected. Legacy namespace/API names remain consumer-compatible.
// Queue receipts are not delivery observations. The ordinary frontend/InputSystem
// loop must deliver the original subscriptions. ownedButtonPressed is the legacy
// API name for the borrowed process Mouse's observed primary button state.
namespace ba_prediction_actor_smoke { namespace virtual_mouse {
namespace actors=ba_prediction_actors;
using ba::Obj;
using ba_local::Root;
struct QueueReceipt {uint64_t sequence=0;bool held=false;};
struct Snapshot {
    uint64_t world=0;std::string match;
    Obj selector=nullptr,action=nullptr,control=nullptr,device=nullptr;
    uint64_t queuedSequence=0;
    bool selectorPrimaryHeld=false,selectorContextHeld=false,ownedButtonPressed=false;
};
struct ReleaseObservation {Snapshot pressedSnapshot,releasedSnapshot;uint64_t pressUpdate=0,releaseUpdate=0;};
static void require(bool value,const char* reason){actors::require(value,reason);}
static Obj resultClass(Obj method) {
    return ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
        ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(method));
}
static Obj parameterClass(Obj method,uint32_t index) {
    return ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
        ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(method,index));
}
static bool inText(Obj pointer) {
    const auto base=reinterpret_cast<uintptr_t>(ba::module),address=reinterpret_cast<uintptr_t>(pointer);
    const auto image=reinterpret_cast<const uint8_t*>(base);
    require(image!=nullptr,"virtual mouse original module missing");
    const auto dos=reinterpret_cast<const IMAGE_DOS_HEADER*>(image);
    require(dos->e_magic==IMAGE_DOS_SIGNATURE&&dos->e_lfanew>0&&dos->e_lfanew<4096,"virtual mouse original PE header differs");
    const auto pe=reinterpret_cast<const IMAGE_NT_HEADERS64*>(image+dos->e_lfanew);
    require(pe->Signature==IMAGE_NT_SIGNATURE&&pe->FileHeader.Machine==IMAGE_FILE_MACHINE_AMD64&&
        pe->OptionalHeader.Magic==IMAGE_NT_OPTIONAL_HDR64_MAGIC&&pe->FileHeader.NumberOfSections<=96,
        "virtual mouse original PE architecture differs");
    if(address<base||address-base>=pe->OptionalHeader.SizeOfImage)return false;
    const auto sections=IMAGE_FIRST_SECTION(pe);
    for(unsigned i=0;i<pe->FileHeader.NumberOfSections;++i) {
        const auto& section=sections[i];const uint64_t start=section.VirtualAddress,size=section.Misc.VirtualSize;
        const bool code=!memcmp(section.Name,".text\0",6)||!memcmp(section.Name,"il2cpp\0",7);
        if(code&&(section.Characteristics&IMAGE_SCN_MEM_EXECUTE)&&
            start+size<=pe->OptionalHeader.SizeOfImage&&address-base>=start&&address-base<start+size)return true;
    }
    return false;
}
static void signature(Obj method,Obj declaring,bool isStatic,Obj result,std::initializer_list<Obj> parameters,int byRef=-1) {
    uint32_t implementation=0;
    require(method&&ba::api<Obj(*)(Obj)>("il2cpp_method_get_declaring_type")(method)==declaring&&
        ((ba::api<uint32_t(*)(Obj,uint32_t*)>("il2cpp_method_get_flags")(method,&implementation)&0x10u)!=0)==isStatic&&
        ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(method)==parameters.size()&&resultClass(method)==result&&
        !ba::api<bool(*)(Obj)>("il2cpp_type_is_byref")(
            ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(method))&&inText(ba::read<Obj>(method,0)),
        "virtual mouse original method ABI differs");
    unsigned index=0;for(Obj parameter:parameters) {
        Obj type=ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(method,index);
        require(parameterClass(method,index)==parameter&&ba::api<bool(*)(Obj)>("il2cpp_type_is_byref")(type)==
            (static_cast<int>(index)==byRef),"virtual mouse original parameter ABI differs");++index;
    }
}
// Enumerate a CLASS directly; actors::method expects an object, not a class.
static Obj exact(Obj declaring,const char* name,uint32_t token,unsigned count,uintptr_t rva=0) {
    Obj found=nullptr;void* iterator=nullptr;
    while(Obj method=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(declaring,&iterator)) {
        if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(method),name)||
            ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_token")(method)!=token||
            ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(method)!=count)continue;
        require(!found&&(!rva||ba::read<Obj>(method,0)==ba::native<Obj>(rva)),"virtual mouse original method binding differs");found=method;
    }
    require(found!=nullptr,"virtual mouse original method unavailable");return found;
}
static void named(Obj type,const char* space,const char* name,const char* image=nullptr) {
    require(type&&!strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_namespace")(type),space)&&
        !strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(type),name),"virtual mouse original type differs");
    if(image)require(!strcmp(ba::api<const char*(*)(Obj)>("il2cpp_image_get_name")(
        ba::api<Obj(*)(Obj)>("il2cpp_class_get_image")(type)),image),"virtual mouse original assembly differs");
}
static void valueSize(Obj type,int32_t bytes) {
    require(ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(type),"virtual mouse expected value carrier missing");
    actors::clickScalarSize(type,bytes);
}
static bool instanceOf(Obj object,Obj expected) {
    return object&&ba::api<bool(*)(Obj,Obj)>("il2cpp_class_is_assignable_from")(expected,ba::klass(object));
}
struct Api {
    Obj mouse=nullptr,device=nullptr,control=nullptr,button=nullptr,vectorControl=nullptr,action=nullptr,reference=nullptr;
    Obj eventType=nullptr,arrayType=nullptr,controlsType=nullptr,vector=nullptr,single=nullptr,boolean=nullptr,integer=nullptr;
    Obj controlsLengthField=nullptr;
    Obj left=nullptr,right=nullptr,position=nullptr,getDevice=nullptr,getEnabled=nullptr;
    Obj from=nullptr,dispose=nullptr,write=nullptr,queue=nullptr,getAction=nullptr,getControls=nullptr,count=nullptr,item=nullptr,isPressed=nullptr;
    int32_t allocator=0;bool ready=false;
};
static Api& api(){static Api* value=new Api;return *value;}
static void resolve() {
    auto& a=api();if(a.ready)return;
    auto input=[](const char* name){Obj result=actors::type("UnityEngine.InputSystem",name);
        named(result,"UnityEngine.InputSystem",name,"Unity.InputSystem.dll");return result;};
    a.mouse=input("Mouse");a.device=input("InputDevice");a.control=input("InputControl");a.action=input("InputAction");a.reference=input("InputActionReference");
    a.button=actors::type("UnityEngine.InputSystem.Controls","ButtonControl");a.vectorControl=actors::type("UnityEngine.InputSystem.Controls","Vector2Control");
    a.vector=actors::type("UnityEngine","Vector2");a.single=actors::type("System","Single");a.boolean=actors::type("System","Boolean");a.integer=actors::type("System","Int32");
    Obj voidType=actors::type("System","Void"),object=actors::type("System","Object");
    Obj system=input("InputSystem"),extensions=input("InputControlExtensions"),pointer=input("Pointer");
    Obj stateEvent=actors::type("UnityEngine.InputSystem.LowLevel","StateEvent"),allocator=actors::type("Unity.Collections","Allocator");
    a.eventType=actors::type("UnityEngine.InputSystem.LowLevel","InputEventPtr");
    a.left=exact(a.mouse,"get_leftButton",0x06000735,0,0x897250);signature(a.left,a.mouse,false,a.button,{});
    a.right=exact(a.mouse,"get_rightButton",0x06000739,0,0x8974f0);signature(a.right,a.mouse,false,a.button,{});
    a.position=exact(pointer,"get_position",0x06000766,0,0x893910);signature(a.position,pointer,false,a.vectorControl,{});
    a.getDevice=exact(a.control,"get_device",0x060004f9,0,0x845f70);signature(a.getDevice,a.control,false,a.device,{});
    a.getEnabled=exact(a.device,"get_enabled",0x06000651,0,0x46acda0);signature(a.getEnabled,a.device,false,a.boolean,{});
    a.isPressed=exact(a.button,"get_isPressed",0x0600136e,0,0x4678780);signature(a.isPressed,a.button,false,a.boolean,{});
    a.getAction=exact(a.reference,"get_action",0x06000287,0,0x46564f0);signature(a.getAction,a.reference,false,a.action,{});
    a.getControls=exact(a.action,"get_controls",0x0600013e,0,0x4638f00);a.controlsType=resultClass(a.getControls);
    named(a.controlsType,"UnityEngine.InputSystem.Utilities","ReadOnlyArray`1","Unity.InputSystem.dll");valueSize(a.controlsType,16);
    signature(a.getControls,a.action,false,a.controlsType,{});
    a.count=exact(a.controlsType,"get_Count",0x060015c3,0);signature(a.count,a.controlsType,false,a.integer,{});
    a.item=exact(a.controlsType,"get_Item",0x060015c4,1);signature(a.item,a.controlsType,false,a.control,{a.integer});
    a.controlsLengthField=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(a.controlsType,"m_Length");
    require(a.controlsLengthField&&ba::api<Obj(*)(Obj)>("il2cpp_field_get_parent")(a.controlsLengthField)==a.controlsType&&
        !(ba::api<uint32_t(*)(Obj)>("il2cpp_field_get_flags")(a.controlsLengthField)&0x10u)&&
        ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(a.controlsLengthField))==a.integer,
        "virtual mouse closed controls m_Length field ABI differs");
    a.from=exact(stateEvent,"From",0x0600109a,3,0x4782480);a.arrayType=resultClass(a.from);
    // The exact nongeneric From definition fixes this closed return to Byte.
    named(a.arrayType,"Unity.Collections","NativeArray`1");valueSize(a.arrayType,16);valueSize(a.eventType,8);
    signature(a.from,stateEvent,true,a.arrayType,{a.device,a.eventType,allocator},1);
    a.dispose=exact(a.arrayType,"Dispose",0x060000bf,0);signature(a.dispose,a.arrayType,false,voidType,{});
    a.write=exact(extensions,"WriteValueFromObjectIntoEvent",0x0600055d,3,0x46a1bb0);
    signature(a.write,extensions,true,voidType,{a.control,a.eventType,object});
    a.queue=exact(system,"QueueEvent",0x060004c5,1,0x469bdd0);signature(a.queue,system,true,voidType,{a.eventType});
    valueSize(a.vector,8);valueSize(a.single,4);valueSize(a.boolean,1);valueSize(a.integer,4);valueSize(allocator,4);
    Obj temp=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(allocator,"Temp");
    require(temp&&ba::api<Obj(*)(Obj)>("il2cpp_field_get_parent")(temp)==allocator&&
        (ba::api<uint32_t(*)(Obj)>("il2cpp_field_get_flags")(temp)&0x50u)==0x50u&&
        ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(temp))==allocator,
        "virtual mouse original Temp allocator differs");
    ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(temp,&a.allocator);
    require(a.allocator==2,"virtual mouse original Temp allocator value differs");a.ready=true;
}
static Obj referenceField(Obj object,const char* name,size_t offset,Obj type) {
    Obj member=ba::field(object,name);
    require(ba::api<Obj(*)(Obj)>("il2cpp_field_get_parent")(member)==ba::klass(object)&&
        ba::api<size_t(*)(Obj)>("il2cpp_field_get_offset")(member)==offset&&
        !(ba::api<uint32_t(*)(Obj)>("il2cpp_field_get_flags")(member)&0x10u)&&
        ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(member))==type,
        "virtual mouse original owner field ABI differs");return ba::read<Obj>(object,offset);
}
static Obj ownerGraph(actors::State& owner,Obj selector) {
    const bool expired=ba::flag(L"-prediction-expired-click-smoke"),held=ba::flag(L"-prediction-held-click-smoke");
    const bool mobileHeld=ba::flag(L"-prediction-mobile-held-click-smoke");
    require((unsigned(expired)+unsigned(held)+unsigned(mobileHeld)==1)&&
        (!mobileHeld||(ba::flag(L"-prediction-mobile-correction-smoke")&&!ba_prediction_actor_fixture_smoke::mirrored()))&&
        ba::initialThread&&GetCurrentThreadId()==ba::initialThread&&
        GetCurrentThreadId()==ba_local::updateThread&&owner.thread==GetCurrentThreadId()&&!owner.failed&&owner.world&&
        owner.world==ba_prediction_worker::movementWorldId()&&owner.match==ba_prediction_worker::movementMatchId()&&
        owner.match.size()==32&&owner.manager&&owner.simulation&&ba_prediction_movement::ownsPresentation(owner.simulation->get())&&
        ba_prediction_actor_fixture_smoke::validScope()&&ba::lanSlot()==ba_prediction_actor_fixture_smoke::victimSlot(),
        "virtual mouse lost its original frontend/presentation owner");
    actors::classIs(selector,"Uncapped","UnitSelector");Obj server=ba_local::server();actors::classIs(server,"Uncapped","GameServerIntegration");
    require(ba_local::isTarget(server)&&referenceField(server,"_gameSimulation",0x140,actors::type("Uncapped","Simulation"))==owner.simulation->get()&&
        referenceField(selector,"_unitManager",0x40,actors::type("Uncapped","UnitManager"))==owner.manager->get()&&
        referenceField(selector,"_simulation",0x138,actors::type("Uncapped","Simulation"))==owner.simulation->get(),
        "virtual mouse selector/server graph differs");
    Obj handler=referenceField(selector,"_playerInputHandler",0x70,actors::type("Uncapped","PlayerInputHandler"));
    actors::classIs(handler,"Uncapped","PlayerInputHandler");
    require(referenceField(handler,"_simulation",0x40,actors::type("Uncapped","Simulation"))==owner.simulation->get()&&
        referenceField(handler,"_gameServerIntegration",0x50,actors::type("Uncapped","GameServerIntegration"))==server,
        "virtual mouse original input handler graph differs");
    actors::clickField(selector,"_isPointerDown",0x16c,actors::type("System","Boolean"),1);
    actors::clickField(selector,"_isContextPointerDown",0x16d,actors::type("System","Boolean"),1);
    actors::clickField(selector,"_isDragging",0x119,actors::type("System","Boolean"),1);return handler;
}
static bool selectorFlag(Obj selector,size_t offset) {
    const auto value=ba::read<uint8_t>(selector,offset);require(value<=1,"virtual mouse selector Boolean differs");return value!=0;
}
static Obj actionReference(Obj handler,unsigned index) {
    static const char* names[]={"PlayerPointerPositionInputRef","PlayerPointerDownInputRef","PlayerPointerContextDownInputRef"};
    require(index<3,"virtual mouse action index differs");Obj result=referenceField(handler,names[index],0x100+8*index,api().reference);
    require(result&&ba::klass(result)==api().reference,"virtual mouse original action reference missing");return result;
}
struct ControlScan {int32_t count=-1,reflectedLength=-1;bool truncated=false;};
static bool includes(Obj action,Obj expected,ControlScan* scan=nullptr,unsigned auditIndex=3,
    std::vector<std::unique_ptr<Root>>* candidates=nullptr) {
    auto& a=api();require(action&&ba::klass(action)==a.action,"virtual mouse original action differs");
    Root controls(actors::invoke(a.getControls,action));require(controls.get()&&ba::klass(controls.get())==a.controlsType,"virtual mouse closed controls carrier differs");
    auto payload=[&](){void* value=ba::api<void*(*)(Obj)>("il2cpp_object_unbox")(controls.get());
        require(value,"virtual mouse controls value receiver missing");return value;};
    Root count(actors::invoke(a.count,payload()));actors::classIs(count.get(),"System","Int32");const auto length=actors::unbox<int32_t>(count.get());
    if(scan) {
        scan->count=length;scan->truncated=length>16;
        const auto objectAddress=reinterpret_cast<uintptr_t>(controls.get());
        const auto valueAddress=reinterpret_cast<uintptr_t>(payload());
        const auto offset=ba::api<size_t(*)(Obj)>("il2cpp_field_get_offset")(a.controlsLengthField);
        // Derive the boxed payload boundary from the SDK, not a guessed object
        // header or raw ReadOnlyArray member layout. Value size16 was preflighted.
        require(valueAddress>=objectAddress&&offset>=valueAddress-objectAddress&&
            offset-(valueAddress-objectAddress)<=16-sizeof(scan->reflectedLength),
            "virtual mouse closed controls m_Length offset is outside its value payload");
        ba::api<void(*)(Obj,Obj,void*)>("il2cpp_field_get_value")(controls.get(),a.controlsLengthField,&scan->reflectedLength);
        require(length==scan->reflectedLength,"virtual mouse controls Count/reflected m_Length disagree");
    }
    require(length>=0&&length<=256,"virtual mouse actual action control bound differs");bool found=false;
    for(int32_t index=0;index<length;++index) {
        void* args[]={&index};Root control(actors::invoke(a.item,payload(),args));require(control.get(),"virtual mouse action control missing");
        if(control.get()==expected)found=true;
        if((auditIndex<3&&index<16)||candidates) {
            Root device(actors::invoke(a.getDevice,control.get()));Obj controlClass=ba::klass(control.get());
            if(candidates&&instanceOf(device.get(),a.mouse)) {
                bool seen=false;for(const auto& prior:*candidates)if(prior->get()==device.get())seen=true;
                if(!seen) {
                    auto retained=std::make_unique<Root>(device.get());require(retained->get()==device.get(),"bound process Mouse candidate root failed");
                    candidates->push_back(std::move(retained));
                }
            }
            if(auditIndex>=3||index>=16)continue;
            Obj deviceClass=device.get()?ba::klass(device.get()):nullptr;
            auto name=[](Obj type,const char* api){return type?ba::api<const char*(*)(Obj)>(api)(type):"";};
            ba::log("VIRTUAL MOUSE CONTROL {\"schema\":1,\"phase\":\"begin\",\"index\":%u,\"ordinal\":%d,\"action\":\"%p\",\"control\":\"%p\",\"class\":\"%s.%s\",\"device\":\"%p\",\"device_class\":\"%s.%s\",\"expected\":%s}",
                auditIndex,index,action,control.get(),name(controlClass,"il2cpp_class_get_namespace"),name(controlClass,"il2cpp_class_get_name"),
                device.get(),name(deviceClass,"il2cpp_class_get_namespace"),name(deviceClass,"il2cpp_class_get_name"),control.get()==expected?"true":"false");
        }
    }
    return found;
}
struct Session {
    actors::State* owner=nullptr;uint64_t world=0,sequence=0;std::string match;
    int victimSlot=-1;bool mirror=false;
    bool active=false,closed=false,failed=false,queueUncertain=false,lastHeld=false,sawPress=false,sawRelease=false;
    std::unique_ptr<Root> selector,handler,server,manager,simulation,device,controls[3],references[3],actions[3];
};
static Session& session(){static Session* value=new Session;return *value;}
static std::unique_ptr<Root> root(Obj object,bool optional=false) {
    require(optional||object,"virtual mouse required root missing");auto result=std::make_unique<Root>(object);
    require(result->get()==object,"virtual mouse GC root allocation differs");return result;
}
static void releaseRoots(Session& s) {
    for(unsigned i=0;i<3;++i){s.controls[i].reset();s.actions[i].reset();s.references[i].reset();}
    s.device.reset();s.handler.reset();s.selector.reset();s.server.reset();s.manager.reset();s.simulation.reset();s.owner=nullptr;
}
struct BindingChoice {
    std::unique_ptr<Root> device,controls[3],references[3],actions[3];
};
static bool originalBoolean(Obj method,Obj receiver) {
    Root value(actors::invoke(method,receiver));require(value.get()&&ba::klass(value.get())==api().boolean,"bound process Mouse Boolean result differs");
    return actors::unbox<bool>(value.get());
}
static void enabled(Obj device) {
    require(originalBoolean(api().getEnabled,device),"bound existing process Mouse is disabled; device state was not changed");
}
static BindingChoice choose(Obj handler) {
    BindingChoice choice;std::vector<std::unique_ptr<Root>> candidates;
    for(unsigned i=0;i<3;++i) {
        choice.references[i]=root(actionReference(handler,i));choice.actions[i]=root(actors::invoke(api().getAction,choice.references[i]->get()));
        ControlScan scan;includes(choice.actions[i]->get(),nullptr,&scan,3,&candidates);
    }
    for(const auto& candidate:candidates) {
        std::unique_ptr<Root> controls[3];controls[0]=root(actors::invoke(api().position,candidate->get()));
        controls[1]=root(actors::invoke(api().left,candidate->get()));controls[2]=root(actors::invoke(api().right,candidate->get()));
        if(!instanceOf(controls[0]->get(),api().vectorControl)||!instanceOf(controls[1]->get(),api().button)||!instanceOf(controls[2]->get(),api().button))continue;
        bool qualifies=true;
        for(unsigned i=0;i<3;++i) {
            Root device(actors::invoke(api().getDevice,controls[i]->get()));
            const bool member=includes(choice.actions[i]->get(),controls[i]->get());
            if(device.get()!=candidate->get()||!member)qualifies=false;
        }
        if(!qualifies)continue;
        require(!choice.device,"bound process Mouse choice is ambiguous across actual action controls");choice.device=root(candidate->get());
        for(unsigned i=0;i<3;++i)choice.controls[i]=std::move(controls[i]);
    }
    require(choice.device!=nullptr,"no unique existing Mouse has its position/left/right controls in all three original actions");
    enabled(choice.device->get());return choice;
}
static void released(Obj selector,const BindingChoice& choice) {
    require(!selectorFlag(selector,0x16c)&&!selectorFlag(selector,0x16d)&&!selectorFlag(selector,0x119),
        "bound process Mouse requires selector both-up and no drag before beginning");
    require(!originalBoolean(api().isPressed,choice.controls[1]->get())&&!originalBoolean(api().isPressed,choice.controls[2]->get()),
        "bound process Mouse requires both original buttons released before beginning");
}
static void preflight(actors::State& owner,Obj selector) {
    Obj handler=ownerGraph(owner,selector);resolve();auto choice=choose(handler);released(selector,choice);
}
static std::string bindingFailure(unsigned index,const char* condition) {
    return "virtual mouse binding index="+std::to_string(index)+" condition="+condition;
}
static void bindingRequire(bool value,unsigned index,const char* condition) {
    if(!value)throw std::runtime_error(bindingFailure(index,condition));
}
static void live(bool audit=false) {
    auto& s=session();require(s.active&&!s.closed&&!s.failed&&s.owner&&s.selector&&s.device,"virtual mouse session unavailable");
    require(s.victimSlot==ba_prediction_actor_fixture_smoke::victimSlot()&&
        s.mirror==ba_prediction_actor_fixture_smoke::mirrored()&&
        ownerGraph(*s.owner,s.selector->get())==s.handler->get()&&s.owner->world==s.world&&s.owner->match==s.match&&
        s.owner->manager->get()==s.manager->get()&&s.owner->simulation->get()==s.simulation->get()&&ba_local::server()==s.server->get()&&
        instanceOf(s.device->get(),api().mouse),"virtual mouse retained owner changed");
    // Re-resolve the unique qualifying original Mouse and its getter controls at
    // every observation/queue boundary; retained identity alone is insufficient.
    auto current=choose(s.handler->get());
    require(current.device->get()==s.device->get(),"borrowed process Mouse identity changed");
    for(unsigned i=0;i<3;++i)require(current.controls[i]->get()==s.controls[i]->get(),"borrowed process Mouse getter control changed");
    std::string firstFailure;
    for(unsigned i=0;i<3;++i) {
        const char* query="action_reference";
        try {
            bindingRequire(actionReference(s.handler->get(),i)==s.references[i]->get(),i,"action_reference");
            query="get_action";Root action(actors::invoke(api().getAction,s.references[i]->get()));
            query="get_device";Root device(actors::invoke(api().getDevice,s.controls[i]->get()));
            const bool sameAction=action.get()==s.actions[i]->get(),sameDevice=device.get()==s.device->get();
            bool member=false;
            if(audit) {
                // Query every index before rejecting any ordinary false guard.
                // These are original read-only queries; no event has been made.
                ControlScan scan;query="controls_query";
                auto record=[&](bool valid) {
                    ba::log("VIRTUAL MOUSE BINDING {\"schema\":1,\"phase\":\"begin\",\"input_source\":\"bound_existing_mouse\",\"index\":%u,\"world\":%llu,\"retained_action\":\"%p\",\"action\":\"%p\",\"action_same\":%s,\"control\":\"%p\",\"control_device\":\"%p\",\"borrowed_device\":\"%p\",\"device_same\":%s,\"count\":%d,\"reflected_length\":%d,\"truncated\":%s,\"query_valid\":%s,\"member\":%s}",
                        i,static_cast<unsigned long long>(s.world),s.actions[i]->get(),action.get(),sameAction?"true":"false",s.controls[i]->get(),device.get(),s.device->get(),sameDevice?"true":"false",scan.count,scan.reflectedLength,scan.truncated?"true":"false",valid?"true":"false",valid?(member?"true":"false"):"null");
                };
                try{member=includes(action.get(),s.controls[i]->get(),&scan,i);}catch(...){record(false);throw;}
                record(true);
            }
            query="action_identity";bindingRequire(sameAction,i,query);
            query="control_device";bindingRequire(sameDevice,i,query);
            if(!audit){query="controls_query";member=includes(action.get(),s.controls[i]->get());}
            query="control_membership";bindingRequire(member,i,query);
        } catch(const std::exception& error) {
            if(!audit)throw;
            ba::log("Virtual mouse binding audit failed: index=%u condition=%s reason=%s",i,query,error.what());
            if(firstFailure.empty())firstFailure=bindingFailure(i,query);
        }
    }
    if(!firstFailure.empty())throw std::runtime_error(firstFailure);
}
static void begin(actors::State& owner,Obj selector) {
    auto& s=session();require(!s.active&&!s.failed&&(!s.world||s.closed),"virtual mouse previous session was not legally closed");
    Obj handler=ownerGraph(owner,selector);resolve();auto choice=choose(handler);released(selector,choice);
    s=Session{};s.owner=&owner;s.world=owner.world;s.match=owner.match;s.active=true;
    s.victimSlot=ba_prediction_actor_fixture_smoke::victimSlot();s.mirror=ba_prediction_actor_fixture_smoke::mirrored();
    try {
        s.selector=root(selector);s.handler=root(ownerGraph(owner,selector));s.server=root(ba_local::server());
        s.manager=root(owner.manager->get());s.simulation=root(owner.simulation->get());s.device=std::move(choice.device);
        for(unsigned i=0;i<3;++i){s.references[i]=std::move(choice.references[i]);s.actions[i]=std::move(choice.actions[i]);s.controls[i]=std::move(choice.controls[i]);}
        live(true);
    } catch(...) {
        s.failed=true;
        // No event has been queued. Only our roots belong to this session; the
        // borrowed original device and its bindings are never changed or removed.
        releaseRoots(s);s.active=false;
        throw;
    }
}
static Snapshot observe() {
    live();auto& s=session();Snapshot result;result.world=s.world;result.match=s.match;result.selector=s.selector->get();
    result.action=s.actions[1]->get();result.control=s.controls[1]->get();result.device=s.device->get();result.queuedSequence=s.sequence;
    result.selectorPrimaryHeld=selectorFlag(result.selector,0x16c);result.selectorContextHeld=selectorFlag(result.selector,0x16d);
    Root pressed(actors::invoke(api().isPressed,result.control));require(pressed.get()&&ba::klass(pressed.get())==api().boolean,"virtual mouse original button observation differs");
    result.ownedButtonPressed=actors::unbox<bool>(pressed.get());
    if(s.sequence==2&&result.selectorPrimaryHeld&&!result.selectorContextHeld&&result.ownedButtonPressed)s.sawPress=true;
    if(s.sequence==3&&s.sawPress&&!result.selectorPrimaryHeld&&!result.selectorContextHeld&&!result.ownedButtonPressed)s.sawRelease=true;
    return result;
}
static QueueReceipt queuePositionButton(float x,float y,bool held) {
    live();auto& s=session();auto& a=api();require(std::isfinite(x)&&std::isfinite(y)&&s.sequence<3&&
        held==(s.sequence==1)&&(!s.sequence||s.sequence!=2||s.sawPress),"virtual mouse diagnostic queue order/position differs");
    struct EventPointer {void* pointer=nullptr;};static_assert(sizeof(EventPointer)==8,"InputEventPtr ABI differs");
    struct Point {float x,y;};static_assert(sizeof(Point)==8,"Vector2 ABI differs");
    EventPointer event;void* fromArgs[]={s.device->get(),&event,&a.allocator};
    Root carrier(actors::invoke(a.from,nullptr,fromArgs));bool disposalAttempted=false;
    auto dispose=[&](){require(!disposalAttempted,"virtual mouse event disposed twice");disposalAttempted=true;
        void* payload=ba::api<void*(*)(Obj)>("il2cpp_object_unbox")(carrier.get());
        require(payload,"virtual mouse NativeArray value receiver missing");actors::invoke(a.dispose,payload);};
    try {
        require(carrier.get()&&ba::klass(carrier.get())==a.arrayType&&event.pointer,"virtual mouse original StateEvent carrier differs");
        Point point{x,y};float primary=held?1.0f:0.0f,context=0.0f;
        Root position(ba::api<Obj(*)(Obj,void*)>("il2cpp_value_box")(a.vector,&point));
        Root button(ba::api<Obj(*)(Obj,void*)>("il2cpp_value_box")(a.single,&primary));
        Root right(ba::api<Obj(*)(Obj,void*)>("il2cpp_value_box")(a.single,&context));
        require(position.get()&&ba::klass(position.get())==a.vector&&button.get()&&ba::klass(button.get())==a.single&&
            right.get()&&ba::klass(right.get())==a.single,"virtual mouse original value boxing differs");
        Root* values[]={&position,&button,&right};
        for(unsigned i=0;i<3;++i){void* args[]={s.controls[i]->get(),&event,values[i]->get()};actors::invoke(a.write,nullptr,args);}
        // Unity InputSystem 1.7 official API promises a complete event copy before
        // return, and documents using StateEvent.From + QueueEvent. The retained
        // original image stops at an engine icall: no machine-code copy proof or
        // exact package patch identity is claimed. Never retain Temp across calls.
        void* args[]={&event};s.queueUncertain=true;actors::invoke(a.queue,nullptr,args);
        ++s.sequence;s.lastHeld=held;dispose();s.queueUncertain=false;
        ba::log("Bound process Mouse queued only: world=%llu sequence=%llu held=%d deliveryObserved=0 input_source=bound_existing_mouse native_device_removed=0",
            static_cast<unsigned long long>(s.world),static_cast<unsigned long long>(s.sequence),held?1:0);
        return {s.sequence,held};
    } catch(...) {
        s.failed=true;
        if(!disposalAttempted&&carrier.get()&&ba::klass(carrier.get())==a.arrayType) {
            try{dispose();}catch(...){ba::log("Virtual mouse event Dispose failed; session retained");}
        }
        // The documented using/Dispose ownership also applies on exceptions;
        // uncertain delivery does not transfer the caller's buffer ownership.
        // No fabricated release/selector writes/removal follows a failed queue.
        throw;
    }
}
static bool tuple(const Snapshot& value,const Session& s) {
    return value.world==s.world&&value.match==s.match&&value.selector==s.selector->get()&&value.action==s.actions[1]->get()&&
        value.control==s.controls[1]->get()&&value.device==s.device->get();
}
static void close(const ReleaseObservation& observation) {
    live();auto& s=session();const auto& press=observation.pressedSnapshot;const auto& release=observation.releasedSnapshot;
    require(s.sequence==3&&!s.lastHeld&&!s.queueUncertain&&s.sawPress&&s.sawRelease&&tuple(press,s)&&tuple(release,s)&&
        press.queuedSequence==2&&press.selectorPrimaryHeld&&!press.selectorContextHeld&&press.ownedButtonPressed&&
        release.queuedSequence==3&&!release.selectorPrimaryHeld&&!release.selectorContextHeld&&!release.ownedButtonPressed&&
        observation.pressUpdate&&observation.releaseUpdate>observation.pressUpdate,"virtual mouse balanced original callback observations differ");
    const auto actual=observe();require(tuple(actual,s)&&actual.queuedSequence==3&&!actual.selectorPrimaryHeld&&
        !actual.selectorContextHeld&&!actual.ownedButtonPressed,"virtual mouse original release no longer holds");
    require(!selectorFlag(actual.selector,0x119)&&!originalBoolean(api().isPressed,s.controls[2]->get()),
        "borrowed process Mouse cannot close with an active drag/context button");
    try{releaseRoots(s);s.active=false;s.closed=true;}
    catch(...){s.failed=true;throw;}
}
}}
