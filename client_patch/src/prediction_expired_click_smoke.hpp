#pragma once
#include <cmath>
#include <cstdint>
#include <cstring>
#include <sstream>
#include <optional>
#include "prediction_virtual_mouse_smoke.hpp"

// Explicit owned diagnostic only. Input is delivered by the original InputSystem
// on ordinary updates; no callback contexts or selector fields are fabricated.
namespace ba_prediction_actor_smoke { namespace expired_click {
namespace actors=ba_prediction_actors;
namespace vm=ba_prediction_actor_smoke::virtual_mouse;
using ba::Obj;
using ba_local::Root;
static bool enabled(){return ba::flag(L"-prediction-expired-click-smoke");}
static void require(bool value,const char* why){actors::require(value,why);}
struct History {
    uint32_t id=0;int32_t mode=0;
    bool primary=false,context=false,drag=false;
    float lastUp=0,window=0;
};
struct State {
    uint64_t world=0,update=0,sequence=0,inputSequence=0,pressUpdate=0,releaseUpdate=0,positionUpdate=0;
    std::string match;
    unsigned stage=0;
    ULONGLONG focusedAt=0;
    float x=0,y=0;
    uint32_t lastUpBits=0,windowBits=0;
    bool ready=false,closed=false,complete=false,failed=false;
    vm::Snapshot last{},pressed{},released{};
};
static State& state(){static State* value=new State;return *value;}
static uint64_t& frontendOrdinal(){static uint64_t value=0;return value;}
static void frontendUpdate(){require(frontendOrdinal()!=UINT64_MAX,"expired click callback ordinal overflow");++frontendOrdinal();}
static uint32_t bits(float value){uint32_t result=0;std::memcpy(&result,&value,sizeof(result));return result;}
static void owned(actors::State& owner,Obj selector,int victimSlot=1) {
    require(ba::initialThread && GetCurrentThreadId()==ba::initialThread &&
        GetCurrentThreadId()==ba_local::updateThread && owner.thread==GetCurrentThreadId() && !owner.failed &&
        owner.world && owner.world==ba_prediction_worker::movementWorldId() &&
        owner.match==ba_prediction_worker::movementMatchId() && owner.match.size()==32 &&
        owner.manager && owner.simulation && ba_prediction_movement::ownsPresentation(owner.simulation->get()),
        "expired click fixture lost its frontend/presentation owner");
    actors::classIs(selector,"Uncapped","UnitSelector");
    actors::field(selector,"_unitManager",0x40);actors::field(selector,"_simulation",0x138);
    require((victimSlot==1||(victimSlot==0&&ba_prediction_actor_fixture_smoke::mirrored()))&&
        ba_prediction_actor_fixture_smoke::validScope()&&ba::lanSlot()==victimSlot && ba::read<Obj>(selector,0x40)==owner.manager->get() &&
        ba::read<Obj>(selector,0x138)==owner.simulation->get(),"expired click fixture selector graph differs");
}
static void validateHistory(Obj selector) {
    Obj single=actors::type("System","Single"),boolean=actors::type("System","Boolean");
    actors::clickField(selector,"_doubleClickFirstClickReferenceUnitEntityId",0x128,actors::type("System","UInt32"),4);
    actors::clickField(selector,"_doubleClickTime",0x28,single,4);
    actors::clickField(selector,"_lastPointerUpTime",0x154,single,4);
    actors::clickField(selector,"_isPointerDown",0x16c,boolean,1);
    actors::clickField(selector,"_isContextPointerDown",0x16d,boolean,1);
    actors::clickField(selector,"_isDragging",0x119,boolean,1);actors::clickMode(selector);
}
static History history(Obj selector) {
    History h;h.id=ba::read<uint32_t>(selector,0x128);h.mode=ba::read<int32_t>(selector,0x170);
    auto boolean=[&](size_t offset){const auto value=ba::read<uint8_t>(selector,offset);
        require(value<=1,"expired click fixture Boolean differs");return value!=0;};
    h.primary=boolean(0x16c);h.context=boolean(0x16d);h.drag=boolean(0x119);
    h.lastUp=ba::read<float>(selector,0x154);h.window=ba::read<float>(selector,0x28);
    require(h.mode>=0&&h.mode<=2&&std::isfinite(h.lastUp)&&h.lastUp>=0&&
        std::isfinite(h.window)&&h.window>=0,"expired click fixture history scalar differs");return h;
}
static void preserved(Obj selector) {
    const auto& s=state();const auto h=history(selector);
    require(h.id==5&&h.mode==0&&!h.primary&&!h.context&&!h.drag&&
        bits(h.lastUp)==s.lastUpBits&&bits(h.window)==s.windowBits,
        "expired click fixture changed released history/gesture");
}
static std::string pointer(Obj value) {
    require(value!=nullptr,"expired click fixture owner identity missing");
    std::ostringstream out;out<<std::hex<<reinterpret_cast<uintptr_t>(value);return out.str();
}
static void record(actors::State& owner,Obj selector,int frame,const char* event,std::optional<float> observedNow=std::nullopt) {
    owned(owner,selector);auto& s=state();const auto h=history(selector);
    const float now=observedNow?*observedNow:actors::clickNow();
    require(std::isfinite(now)&&now>=0&&now>=h.lastUp&&s.world==owner.world&&s.match==owner.match&&
        s.last.selector==selector&&s.last.world==s.world&&s.last.match==s.match,
        "expired click fixture record ownership/clock differs");
    if(!s.closed)require(s.last.queuedSequence==s.inputSequence&&
        s.last.selectorPrimaryHeld==h.primary&&s.last.selectorContextHeld==h.context,
        "expired click fixture current input snapshot differs");
    const auto boolean=[](bool value){return value?"true":"false";};
    std::ostringstream out;
    out<<"{\"schema\":1,\"event\":\""<<event<<"\",\"sequence\":"<<++s.sequence
       <<",\"world\":"<<s.world<<",\"match\":\""<<s.match<<"\",\"slot\":1,\"entity\":5,\"frame\":"<<frame
       <<",\"update\":"<<s.update<<",\"update_scope\":\"original_frontend_callback\",\"input_sequence\":"<<s.inputSequence
       <<",\"selector\":\""<<pointer(s.last.selector)<<"\",\"action\":\""<<pointer(s.last.action)
       <<"\",\"control\":\""<<pointer(s.last.control)<<"\",\"device\":\""<<pointer(s.last.device)
       <<"\",\"input_source\":\"bound_existing_mouse\",\"ownership_scope\":\""<<(s.closed?"retained_scalar":"borrowed_current")<<"\",\"owned_button\":";
    if(s.closed)out<<"null";else out<<boolean(s.last.ownedButtonPressed);
    out<<",\"input_closed\":"<<boolean(s.closed)<<",\"click_id\":"<<h.id<<",\"mode\":"<<h.mode
       <<",\"primary\":"<<boolean(h.primary)<<",\"context\":"<<boolean(h.context)<<",\"drag\":"<<boolean(h.drag)
       <<",\"now_bits\":"<<bits(now)<<",\"last_up_bits\":"<<bits(h.lastUp)<<",\"window_bits\":"<<bits(h.window)
       <<",\"originalClockSingle\":true,\"physicalUI\":false}";
    ba::log("EXPIRED CLICK %s",out.str().c_str());
}
static Obj reference(Obj owner,const char* name,size_t offset,Obj type) {
    Obj field=ba::field(owner,name);
    require(ba::api<size_t(*)(Obj)>("il2cpp_field_get_offset")(field)==offset&&
        ba::api<Obj(*)(Obj)>("il2cpp_field_get_parent")(field)==ba::klass(owner)&&
        !(ba::api<uint32_t(*)(Obj)>("il2cpp_field_get_flags")(field)&0x10u)&&
        ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(field))==type,
        "expired click fixture camera field ABI differs");return ba::read<Obj>(owner,offset);
}
static void signature(Obj method,bool isStatic,Obj result) {
    uint32_t implementation=0;
    require(((ba::api<uint32_t(*)(Obj,uint32_t*)>("il2cpp_method_get_flags")(method,&implementation)&0x10u)!=0)==isStatic&&
        ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
            ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(method))==result,
        "expired click fixture method signature differs");
}
static void focus(Obj selector) {
    Obj method=actors::method(selector,"OnFocusOnHQ",0,0x0600221f,0x3bf2f30);
    signature(method,false,actors::type("System","Void"));
    actors::guard(0x3bf2f30,"\x40\x53\x48\x83\xec\x20\x48\x8b\xd9\x48\xc7\x44\x24\x30\x00\x00",16);
    actors::invoke(method,selector);
}
static int screenDimension(const char* name,uint32_t token,uintptr_t rva,const char* entry) {
    Obj screen=actors::type("UnityEngine","Screen"),found=nullptr;void* iterator=nullptr;
    while(Obj method=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(screen,&iterator)) {
        if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(method),name)||
            ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_token")(method)!=token||
            ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(method)!=0)continue;
        require(!found&&ba::read<Obj>(method,0)==ba::native<Obj>(rva),"expired click fixture Screen method differs");
        signature(method,true,actors::type("System","Int32"));found=method;
    }
    require(found!=nullptr,"expired click fixture Screen method missing");actors::guard(rva,entry,16);
    Root value(actors::invoke(found,nullptr));actors::classIs(value.get(),"System","Int32");return actors::unbox<int32_t>(value.get());
}
static std::pair<float,float> project(actors::State& owner,Obj selector,Obj core,uint32_t coreId=5,int victimSlot=1,uint32_t unitType=3,
                                    const float* groundPoint=nullptr) {
    owned(owner,selector,victimSlot);const auto identity=actors::resident(core);
    const bool contextMove=ba::flag(L"-prediction-mobile-context-move-smoke");
    const bool mobile=(ba::flag(L"-prediction-mobile-held-click-smoke")||contextMove)&&ba::flag(L"-prediction-mobile-correction-smoke")&&
        !ba_prediction_actor_fixture_smoke::mirrored()&&victimSlot==1&&coreId==11&&unitType==1;
    require(!groundPoint||(contextMove&&mobile),"ground projection requires the explicit context Move fixture");
    require((mobile||(unitType==3&&coreId==(victimSlot==0?0u:5u)))&&identity.entityId==coreId&&identity.unitType==unitType&&
        identity.armyId==static_cast<uint32_t>(victimSlot)&&
        ba_prediction_selection::Context(selector).admitted(core),"expired click fixture HQ target is not admitted");
    Root controller(reference(selector,"_cameraController",0x20,actors::type("Uncapped","CameraController")));
    actors::classIs(controller.get(),"Uncapped","CameraController");
    Root camera(reference(controller.get(),"Camera",0x20,actors::type("UnityEngine","Camera")));
    actors::classIs(camera.get(),"UnityEngine","Camera");
    require(reference(selector,"_camera",0xc0,actors::type("UnityEngine","Camera"))==camera.get()&&
        reference(controller.get(),"_simulation",0xb0,actors::type("Uncapped","Simulation"))==owner.simulation->get()&&
        reference(controller.get(),"_unitManager",0xb8,actors::type("Uncapped","UnitManager"))==owner.manager->get()&&
        reference(controller.get(),"_unitSelector",0xe0,actors::type("Uncapped","UnitSelector"))==selector,
        "expired click fixture camera graph differs");
    Obj getTransform=actors::method(core,"get_transform",0,0x06000e05,0x891420);
    signature(getTransform,false,actors::type("UnityEngine","Transform"));
    actors::guard(0x891420,"\x40\x53\x48\x83\xec\x20\x48\x8b\x05\x7b\x33\x5d\x06\x48\x8b\xd9",16);
    Root transform(actors::invoke(getTransform,core));actors::classIs(transform.get(),"UnityEngine","Transform");
    Obj getPosition=actors::method(transform.get(),"get_position",0,0x0600109a,0x509cb00);
    Obj vector=actors::type("UnityEngine","Vector3");signature(getPosition,false,vector);actors::clickScalarSize(vector,12);
    actors::guard(0x509cb00,"\x48\x89\x5c\x24\x08\x57\x48\x83\xec\x20\x33\xc0\x48\x8b\xfa\x48",16);
    Root position(actors::invoke(getPosition,transform.get()));actors::classIs(position.get(),"UnityEngine","Vector3");
    Obj projection=actors::method(camera.get(),"WorldToScreenPoint",1,0x0600028a,0x50280c0);signature(projection,false,vector);
    require(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
        ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(projection,0))==vector,
        "expired click fixture projection parameter differs");
    actors::guard(0x50280c0,"\x48\x89\x5c\x24\x08\x57\x48\x83\xec\x40\xf2\x41\x0f\x10\x00\x33",16);
    struct Point {float x,y,z;};Point supplied{};
    if(groundPoint){std::memcpy(&supplied,groundPoint,sizeof(supplied));require(std::isfinite(supplied.x)&&
        std::isfinite(supplied.y)&&std::isfinite(supplied.z),"context Move ground projection is not finite");}
    void* args[]={groundPoint?static_cast<void*>(&supplied):ba::api<void*(*)(Obj)>("il2cpp_object_unbox")(position.get())};
    Root projected(actors::invoke(projection,camera.get(),args));actors::classIs(projected.get(),"UnityEngine","Vector3");
    const auto point=actors::unbox<Point>(projected.get());
    const auto width=screenDimension("get_width",0x06000479,0x5038860,"\x48\x83\xec\x28\x48\x8b\x05\x45\xa1\xe2\x01\x48\x85\xc0\x75\x18");
    const auto height=screenDimension("get_height",0x0600047a,0x50388b0,"\x48\x83\xec\x28\x48\x8b\x05\xfd\xa0\xe2\x01\x48\x85\xc0\x75\x18");
    ba::log("Click target projection: world=%llu frame=%d x=%.9g y=%.9g z=%.9g width=%d height=%d",
        static_cast<unsigned long long>(owner.world),ba::read<int>(owner.simulation->get(),0xac),
        static_cast<double>(point.x),static_cast<double>(point.y),static_cast<double>(point.z),width,height);
    require(width>0&&height>0&&std::isfinite(point.x)&&std::isfinite(point.y)&&std::isfinite(point.z)&&point.z>0&&
        point.x>=width*.15f&&point.x<=width*.85f&&point.y>=height*.2f&&point.y<=height*.85f,
        "expired click fixture HQ projection is outside the interior view");return {point.x,point.y};
}
// Called exactly once per original frontend callback, before the existing HQ
// setup. It never advances InputSystem or native simulation itself.
static bool prepare(actors::State& owner,Obj selector,Obj core,int frame) {
    owned(owner,selector);auto& s=state();
    require(!s.failed,"expired click fixture cannot reuse a failed input episode");
    if(s.world!=owner.world||s.match!=owner.match) {
        require(!s.world||(s.closed&&s.complete),"expired click fixture retired an unfinished input session");
        s=State{};s.world=owner.world;s.match=owner.match;
    }
    s.update=frontendOrdinal();require(s.update!=0,"expired click fixture callback ordinal missing");if(s.ready)return true;
    require(frame>=120&&frame<145,"expired click fixture missed pre-death preparation window");
    if(!s.stage) {
        validateHistory(selector);const auto h=history(selector);
        require(!h.primary&&!h.context&&!h.drag&&h.mode==0,"expired click fixture starts with active gesture");
        vm::preflight(owner,selector);vm::begin(owner,selector);s.last=vm::observe();
        require(!s.last.selectorPrimaryHeld&&!s.last.selectorContextHeld&&!s.last.ownedButtonPressed&&
            s.last.queuedSequence==0,"expired click fixture owned mouse is not initially released");
        focus(selector);s.focusedAt=GetTickCount64();record(owner,selector,frame,"focused");s.stage=1;return false;
    }
    require(GetTickCount64()-s.focusedAt<2000,"expired click fixture input/camera wait expired");
    if(s.stage==1) {
        if(GetTickCount64()-s.focusedAt<200)return false;
        const auto point=project(owner,selector,core);s.x=point.first;s.y=point.second;
        const auto receipt=vm::queuePositionButton(s.x,s.y,false);require(receipt.sequence==1&&!receipt.held,"expired click fixture position queue differs");
        s.inputSequence=receipt.sequence;s.last=vm::observe();record(owner,selector,frame,"position_queued");
        s.positionUpdate=s.update;s.stage=2;return false;
    }
    if(s.stage==2) {
        require(s.update>s.positionUpdate,"expired click fixture did not return to the frontend");
        const auto receipt=vm::queuePositionButton(s.x,s.y,true);require(receipt.sequence==2&&receipt.held,"expired click fixture press queue differs");
        s.inputSequence=receipt.sequence;s.stage=3;return false;
    }
    if(s.stage==3) {
        s.last=vm::observe();if(!s.last.selectorPrimaryHeld||!s.last.ownedButtonPressed)return false;
        require(!s.last.selectorContextHeld,"expired click fixture contextual gesture became active");
        s.pressed=s.last;s.pressUpdate=s.update;record(owner,selector,frame,"pressed");
        const auto receipt=vm::queuePositionButton(s.x,s.y,false);require(receipt.sequence==3&&!receipt.held,"expired click fixture release queue differs");
        s.inputSequence=receipt.sequence;s.stage=4;return false;
    }
    if(s.stage==4) {
        s.last=vm::observe();if(s.last.selectorPrimaryHeld||s.last.ownedButtonPressed)return false;
        require(s.update>s.pressUpdate&&!s.last.selectorContextHeld,"expired click fixture release ordering differs");
        const auto h=history(selector);require(h.id==5&&h.mode==0&&!h.primary&&!h.context&&!h.drag,
            "expired click fixture original hit test/release did not select its HQ");
        s.lastUpBits=bits(h.lastUp);s.windowBits=bits(h.window);s.released=s.last;s.releaseUpdate=s.update;
        record(owner,selector,frame,"released");s.stage=5;return false;
    }
    require(s.stage==5,"expired click fixture stage differs");
    s.last=vm::observe();preserved(selector);const auto h=history(selector);const float now=actors::clickNow();
    require(std::isfinite(now)&&now>=h.lastUp,"expired click fixture original clock moved backwards");
    const float elapsed=now-h.lastUp;if(!(std::isfinite(elapsed)&&elapsed>h.window))return false;
    require(!actors::affectedLiveClick(selector,std::set<uint32_t>{5}),"expired click fixture shared guard still reports live intent");
    record(owner,selector,frame,"expired_before_setup",now);
    vm::ReleaseObservation release;release.pressedSnapshot=s.pressed;release.releasedSnapshot=s.released;
    release.pressUpdate=s.pressUpdate;release.releaseUpdate=s.releaseUpdate;vm::close(release);
    s.closed=true;preserved(selector);record(owner,selector,frame,"input_closed");s.ready=true;return true;
}
static void observe(actors::State& owner,Obj selector,int frame,const char* event) {
    auto& s=state();require(s.ready&&s.closed&&!s.complete,"expired click fixture post-input phase differs");
    preserved(selector);require(!actors::affectedLiveClick(selector,std::set<uint32_t>{5}),
        "expired click fixture history became live during correction");record(owner,selector,frame,event);
    if(!strcmp(event,"complete")){require(s.sequence==10,"expired click fixture episode incomplete");s.complete=true;}
}
static void clear() {
    // Keep the first real failure and any uncertain adapter session. Repeated
    // inactive frontend callbacks must not replace it with cleanup-error spam.
    auto& s=state();if(s.failed)return;
    require(!s.world||(s.closed&&s.complete),"expired click fixture ended with unbalanced input");s=State{};
}
static void markFailed(){state().failed=true;}
}}
