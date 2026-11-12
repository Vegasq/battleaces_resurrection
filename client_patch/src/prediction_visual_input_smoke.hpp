#pragma once
namespace ba_prediction_visual_sync {
static void observe(const ba_prediction_visual::FrontendObservation&,ba::Obj,ba::Obj,
    ba_prediction_visual::Vec3,bool,bool,const char*,const std::string&);
}
// Stage 1: one original camera acquisition, then original frontend queries. This does not
// inject input, mutate selection, synchronize physics, or qualify callbacks.
// Include after actor smoke, whose existing metadata helpers are reused only.
namespace ba_prediction_visual_input {
namespace actors=ba_prediction_actors;
namespace visual=ba_prediction_visual;
namespace abi=ba_prediction_actor_smoke::virtual_mouse;
using ba::Obj;
using ba_local::Root;
using Vec3=visual::Vec3;
struct Vec2 {float x=0,y=0;};
struct Rect {float x=0,y=0,width=0,height=0;};
static_assert(sizeof(Vec2)==8 && sizeof(Rect)==16,"visual input query value ABI differs");
struct State {
    uint64_t world=0;std::string match;
    bool failed=false,zeroBefore=false,zeroAfter=false;
    unsigned nonzero=0;
    int lastFrame=-1;
    std::map<uint64_t,unsigned> revisions;
    uint64_t focusReturned=0,focusOrdinal=0;
    int focusFrame=-1;
    visual::FrontendObservation focusOwner;
    Obj focusSelector=nullptr,focusCamera=nullptr,focusController=nullptr;
};
static State& state(){static State* lifetime=new State;return *lifetime;}
static uint64_t& ordinal(){static uint64_t value=0;return value;}
static bool enabled(){static const bool value=ba::flag(L"-prediction-visual-input-smoke");return value;}
static void require(bool value,const char* reason){actors::require(value,reason);}
static std::string pointer(Obj value) {
    std::ostringstream out;out<<'"'<<"0x"<<std::hex<<reinterpret_cast<uintptr_t>(value)<<'"';return out.str();
}
struct Api {Obj projection=nullptr,friendly=nullptr,drag=nullptr,rectangle=nullptr,getPosition=nullptr;bool ready=false;};
static Api& api(){static Api value;return value;}
static void resolve(Obj selector,Obj camera,Obj transform) {
    auto& a=api();if(a.ready)return;
    const Obj boolean=actors::type("System","Boolean"),vector=actors::type("UnityEngine","Vector3");
    const Obj unit=actors::type("Uncapped","Unit"),cameraType=actors::type("UnityEngine","Camera");
    const Obj vector2=actors::type("UnityEngine","Vector2"),rect=actors::type("UnityEngine","Rect");
    const Obj data=actors::type("Uncapped.Extensions","HitTestData"),utility=actors::type("Uncapped","UnitHitTestUtility");
    require(!ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(data),
        "visual input HitTestData must retain its original reference ABI");
    abi::valueSize(vector,12);abi::valueSize(vector2,8);abi::valueSize(rect,16);
    a.projection=actors::method(camera,"WorldToScreenPoint",1,0x0600028a,0x50280c0);
    abi::signature(a.projection,cameraType,false,vector,{vector});
    a.getPosition=actors::method(transform,"get_position",0,0x0600109a,0x509cb00);
    abi::signature(a.getPosition,actors::type("UnityEngine","Transform"),false,vector,{});
    a.friendly=actors::method(selector,"HitTestFriendlyUnits",2,0x0600223a,0x3bf6080);
    abi::signature(a.friendly,actors::type("Uncapped","UnitSelector"),false,boolean,{vector2,unit},1);
    a.drag=abi::exact(utility,"PerformDragBoxHitTest",0x06002341,2,0x3c0c8d0);
    abi::signature(a.drag,utility,true,boolean,{unit,data});
    a.rectangle=abi::exact(data,"From2DRect",0x06000133,2,0x3b06ec0);
    abi::signature(a.rectangle,data,true,data,{cameraType,rect});
    actors::guard(0x3bf6080,"\x48\x89\x5c\x24\x08\x48\x89\x74\x24\x18\x57\x48\x81\xec\xa0\x00",16);
    actors::guard(0x3c0c8d0,"\x48\x89\x4c\x24\x08\x53\x56\x57\x41\x56\x41\x57\x48\x81\xec\x00",16);
    actors::guard(0x3b06ec0,"\x48\x89\x5c\x24\x08\x48\x89\x74\x24\x10\x57\x48\x83\xec\x30\x80",16);
    actors::guard(0x50280c0,"\x48\x89\x5c\x24\x08\x57\x48\x83\xec\x40\xf2\x41\x0f\x10\x00\x33",16);
    actors::guard(0x509cb00,"\x48\x89\x5c\x24\x08\x57\x48\x83\xec\x20\x33\xc0\x48\x8b\xfa\x48",16);
    a.ready=true;
}
static Vec3 position(Obj transform) {
    Root boxed(actors::invoke(api().getPosition,transform));actors::classIs(boxed.get(),"UnityEngine","Vector3");
    const auto result=actors::unbox<Vec3>(boxed.get());visual::finite(result);return result;
}
static Vec3 project(Obj camera,Vec3 value) {
    void* args[]={&value};Root boxed(actors::invoke(api().projection,camera,args));
    actors::classIs(boxed.get(),"UnityEngine","Vector3");const auto result=actors::unbox<Vec3>(boxed.get());
    visual::finite(result);require(result.z>0,"visual input query point is behind the camera");return result;
}
static bool equal(Vec3 a,Vec3 b){return a.x==b.x && a.y==b.y && a.z==b.z;}
struct Hit {bool hit=false;Obj unit=nullptr;std::unique_ptr<Root> root;std::string identity="null";};
static Hit ray(Obj selector,Vec3 point,actors::State& owner) {
    Hit result;Vec2 screen{point.x,point.y};Obj picked=nullptr;void* args[]={&screen,&picked};
    Root boxed(actors::invoke(api().friendly,selector,args));actors::classIs(boxed.get(),"System","Boolean");
    result.hit=actors::unbox<bool>(boxed.get());result.unit=picked;
    if(!picked)return result;
    result.root=std::make_unique<Root>(picked);actors::classIs(picked,"Uncapped","Unit");
    const auto id=actors::resident(picked);const auto retained=owner.identities.find(picked);
    uint64_t token=0,lease=0;
    if(retained!=owner.identities.end()){token=retained->second.incarnation;lease=retained->second.presentationLease;}
    Root transform(ba::call(picked,"get_transform"));actors::classIs(transform.get(),"UnityEngine","Transform");
    std::ostringstream out;out<<"{\"entity\":"<<id.entityId<<",\"unit_type\":"<<id.unitType<<",\"army\":"<<id.armyId
        <<",\"incarnation\":"<<token<<",\"lease\":"<<lease<<",\"actor\":"<<pointer(picked)
        <<",\"transform\":"<<pointer(transform.get())<<'}';result.identity=out.str();return result;
}
static bool drag(Obj camera,Obj unit,Vec3 point) {
    // Independent query data only. The selector's actual drag data and mode
    // stay untouched; the original utility chooses the unit's active mode.
    Rect rect{point.x-3.0f,point.y-3.0f,6.0f,6.0f};void* makeArgs[]={camera,&rect};
    Root data(actors::invoke(api().rectangle,nullptr,makeArgs));actors::classIs(data.get(),"Uncapped.Extensions","HitTestData");
    void* args[]={unit,data.get()};Root boxed(actors::invoke(api().drag,nullptr,args));
    actors::classIs(boxed.get(),"System","Boolean");return actors::unbox<bool>(boxed.get());
}
static void observe() {
    require(ba_prediction_worker::visualCorrectionsEnabled() && ba::flag(L"-prediction-movement-smoke") &&
        ba::flag(L"-prediction-visual-observe") && !ba_lan::publicMatch &&
        !ba::argument(L"-prediction-movement-smoke-transition-gates=","").empty(),
        "visual input query requires the owned changing-delay movement diagnostic");
    require(ordinal()!=UINT64_MAX,"visual input frontend ordinal exhausted");++ordinal();
    visual::FrontendObservation value;if(!visual::frontendObservation(value))return;
    auto& s=state();if(s.world!=value.identity.world || s.match!=value.identity.match) {
        s=State{};s.world=value.identity.world;s.match=value.identity.match;
    }
    const auto& spec=visual::trace();
    require(spec.enabled && value.identity.entity==spec.entity && value.identity.unitType==spec.type &&
        value.identity.army==spec.army && value.identity.army==static_cast<uint32_t>(ba::lanSlot()),
        "visual input query observation identity differs");
    if(value.frame<spec.first || value.frame>spec.last || s.lastFrame==value.frame || s.zeroAfter)return;
    const double magnitude=std::hypot(std::hypot(value.offset.x,value.offset.y),value.offset.z);
    const bool zero=magnitude==0;
    if(!s.focusReturned) {
        if(value.frame<510)return;
        require(value.frame<=511 && zero,"visual input missed its zero-offset camera acquisition window");
    } else {
        const auto now=visual::stamp();require(now>=s.focusReturned,"visual input camera clock regressed");
        if(now-s.focusReturned<200000)return;
    }
    const char* control=nullptr;
    if(s.focusReturned && zero && !s.nonzero && !s.zeroBefore)control="zero_before";
    else if(zero && s.nonzero && value.frame>=spec.last-5)control="zero_after";
    else if(magnitude>=0.5 && s.nonzero<8 && s.revisions[value.revision]<2)control="nonzero";
    if(s.focusReturned && !control)return;
    auto& owner=actors::state();Root actor(value.actor),transform(value.transform),simulation(value.simulation),manager(value.manager);
    unsigned liveMatches=0;
    for(Obj candidate:actors::units(ba::read<Obj>(manager.get(),0x10))) {
        const auto id=actors::resident(candidate);
        if(id.entityId==value.identity.entity) {
            require(candidate==actor.get() && id.unitType==value.identity.unitType && id.armyId==value.identity.army,
                "visual input active entity identity differs");++liveMatches;
        }
    }
    require(liveMatches==1,"visual input target is not one unique active actor");
    Root selector(ba::get<Obj>(ba::owner,"<UnitSelector>k__BackingField"));actors::classIs(selector.get(),"Uncapped","UnitSelector");
    actors::field(selector.get(),"_unitManager",0x40);actors::field(selector.get(),"_simulation",0x138);
    actors::field(selector.get(),"_camera",0xc0);
    require(ba::read<Obj>(selector.get(),0x40)==manager.get() && ba::read<Obj>(selector.get(),0x138)==simulation.get(),
        "visual input selector owner differs");
    Root camera(ba::read<Obj>(selector.get(),0xc0));actors::classIs(camera.get(),"UnityEngine","Camera");
    namespace cameraAbi=ba_prediction_actor_smoke::expired_click;
    Root controller(cameraAbi::reference(selector.get(),"_cameraController",0x20,actors::type("Uncapped","CameraController")));
    actors::classIs(controller.get(),"Uncapped","CameraController");
    require(cameraAbi::reference(controller.get(),"Camera",0x20,actors::type("UnityEngine","Camera"))==camera.get() &&
        cameraAbi::reference(controller.get(),"_simulation",0xb0,actors::type("Uncapped","Simulation"))==simulation.get() &&
        cameraAbi::reference(controller.get(),"_unitManager",0xb8,actors::type("Uncapped","UnitManager"))==manager.get() &&
        cameraAbi::reference(controller.get(),"_unitSelector",0xe0,actors::type("Uncapped","UnitSelector"))==selector.get(),
        "visual input original camera owner graph differs");
    Root actualTransform(ba::call(actor.get(),"get_transform"));require(actualTransform.get()==transform.get(),"visual input actor Transform changed");
    resolve(selector.get(),camera.get(),transform.get());
    const auto actual=position(transform.get());const auto displayedScreen=project(camera.get(),value.displayed),rawScreen=project(camera.get(),value.raw);
    const auto width=ba_prediction_actor_smoke::expired_click::screenDimension("get_width",0x06000479,0x5038860,
        "\x48\x83\xec\x28\x48\x8b\x05\x45\xa1\xe2\x01\x48\x85\xc0\x75\x18");
    const auto height=ba_prediction_actor_smoke::expired_click::screenDimension("get_height",0x0600047a,0x50388b0,
        "\x48\x83\xec\x28\x48\x8b\x05\xfd\xa0\xe2\x01\x48\x85\xc0\x75\x18");
    require(width>0 && height>0,"visual input viewport dimensions differ");
    auto inside=[&](Vec3 point){return point.x>=3 && point.x<=width-3 && point.y>=3 && point.y<=height-3;};
    const auto current=ba_prediction_selection::selectionIds(ba::read<Obj>(selector.get(),0x90));
    const auto preview=ba_prediction_selection::selectionIds(ba::read<Obj>(selector.get(),0x88));
    const auto casting=ba_prediction_selection::selectionIds(ba::read<Obj>(selector.get(),0x98));
    actors::field(actor.get(),"DragSelectionHitBox",0xe8);const auto mode=ba::read<int32_t>(actor.get(),0xe8);
    if(!s.focusReturned) {
        require(equal(actual,value.displayed) && value.offset.x==0 && value.offset.y==0 && value.offset.z==0,
            "visual input camera acquisition is not a zero-offset completed pose");
        const auto focus=actors::method(controller.get(),"FocusOnUnit",1,0x060015ec,0x3e9e310);
        abi::signature(focus,actors::type("Uncapped","CameraController"),false,actors::type("System","Void"),{actors::type("Uncapped","Unit")});
        actors::guard(0x3e9e310,"\x48\x89\x5c\x24\x08\x57\x48\x83\xec\x40\x80\x3d\x50\xc0\xfb\x02",16);
        const auto started=visual::stamp();void* args[]={actor.get()};actors::invoke(focus,controller.get(),args);
        const auto returned=visual::stamp();const auto actualAfter=position(transform.get()),screenAfter=project(camera.get(),value.displayed);
        visual::FrontendObservation after;
        require(started>=value.joinedUs && returned>=started && visual::frontendObservation(after) &&
            after.joinedUs==value.joinedUs && after.lease==value.lease && equal(actualAfter,actual) &&
            ba::read<Obj>(selector.get(),0xc0)==camera.get() && ba::read<Obj>(selector.get(),0x20)==controller.get() &&
            ba_prediction_selection::selectionIds(ba::read<Obj>(selector.get(),0x90))==current &&
            ba_prediction_selection::selectionIds(ba::read<Obj>(selector.get(),0x88))==preview &&
            ba_prediction_selection::selectionIds(ba::read<Obj>(selector.get(),0x98))==casting,
            "visual input camera acquisition changed target ownership, pose or selection");
        const auto checked=visual::stamp();require(checked>=returned,"visual input camera completion clock regressed");
        s.focusReturned=returned;s.focusOrdinal=ordinal();s.focusFrame=value.frame;s.focusOwner=value;
        s.focusSelector=selector.get();s.focusCamera=camera.get();s.focusController=controller.get();
        std::ostringstream out;out.imbue(std::locale::classic());out<<std::setprecision(17)<<std::boolalpha;
        out<<"{\"schema\":1,\"event\":\"focus_returned\",\"scope\":\"original_camera_acquisition\",\"world\":"<<s.world
           <<",\"match\":\""<<s.match<<"\",\"frame\":"<<value.frame<<",\"entity\":"<<value.identity.entity
           <<",\"unit_type\":"<<value.identity.unitType<<",\"army\":"<<value.identity.army<<",\"incarnation\":"<<value.identity.incarnation
           <<",\"lease\":"<<value.lease<<",\"generation\":"<<value.generation<<",\"frontend_ordinal\":"<<ordinal()
           <<",\"started_us\":"<<started<<",\"returned_us\":"<<returned<<",\"checked_us\":"<<checked
           <<",\"joined_us\":"<<value.joinedUs<<",\"policy_us\":"<<value.policyUs<<",\"publication_us\":"<<value.publicationUs
           <<",\"alpha\":"<<value.alpha<<",\"thread\":"<<GetCurrentThreadId()<<",\"owner_thread\":"<<owner.thread
           <<",\"actor\":"<<pointer(actor.get())<<",\"transform\":"<<pointer(transform.get())<<",\"selector\":"<<pointer(selector.get())
           <<",\"manager\":"<<pointer(manager.get())<<",\"simulation\":"<<pointer(simulation.get())
           <<",\"camera_controller\":"<<pointer(controller.get())<<",\"camera\":"<<pointer(camera.get())
           <<",\"raw\":"<<visual::xyz(value.raw)<<",\"displayed\":"<<visual::xyz(value.displayed)
           <<",\"offset\":["<<value.offset.x<<','<<value.offset.y<<','<<value.offset.z<<"],\"actual_before\":"<<visual::xyz(actual)
           <<",\"actual_after\":"<<visual::xyz(actualAfter)<<",\"screen_before\":"<<visual::xyz(displayedScreen)
           <<",\"screen_after\":"<<visual::xyz(screenAfter)<<",\"viewport\":["<<width<<','<<height
           <<"],\"method_token\":\"0x060015ec\",\"method_rva\":\"0x3e9e310\",\"camera_calls\":1,\"settle_us\":200000"
           <<",\"physical_input\":false,\"selection_writes\":0,\"sync_transforms\":false}";
        ba::log("VISUAL INPUT FOCUS %s",out.str().c_str());return;
    }
    require(value.lease==s.focusOwner.lease && value.generation==s.focusOwner.generation &&
        visual::policy::sameIdentity(value.identity,s.focusOwner.identity) && actor.get()==s.focusOwner.actor &&
        transform.get()==s.focusOwner.transform && simulation.get()==s.focusOwner.simulation && manager.get()==s.focusOwner.manager &&
        selector.get()==s.focusSelector && camera.get()==s.focusCamera && controller.get()==s.focusController && ordinal()>s.focusOrdinal,
        "visual input query changed its acquired camera/target lifetime");
    const auto sampled=visual::stamp();require(sampled>=value.joinedUs,"visual input join clock moved backwards");
    require(sampled>=s.focusReturned && sampled-s.focusReturned>=200000,"visual input camera has not settled");
    const auto displayedRay=ray(selector.get(),displayedScreen,owner),rawRay=ray(selector.get(),rawScreen,owner);
    const bool displayedDrag=drag(camera.get(),actor.get(),displayedScreen),rawDrag=drag(camera.get(),actor.get(),rawScreen);
    visual::FrontendObservation after;
    require(visual::frontendObservation(after) && after.joinedUs==value.joinedUs && after.lease==value.lease &&
        equal(position(transform.get()),actual) && ba::read<int32_t>(actor.get(),0xe8)==mode &&
        ba_prediction_selection::selectionIds(ba::read<Obj>(selector.get(),0x90))==current &&
        ba_prediction_selection::selectionIds(ba::read<Obj>(selector.get(),0x88))==preview &&
        ba_prediction_selection::selectionIds(ba::read<Obj>(selector.get(),0x98))==casting,
        "visual input original query changed its owner, pose, mode or selection");
    const auto ended=visual::stamp();require(ended>=sampled,"visual input query clock moved backwards");
    const bool rayDiscriminates=displayedRay.hit!=rawRay.hit || displayedRay.unit!=rawRay.unit;
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::setprecision(17)<<std::boolalpha;
    out<<"{\"schema\":1,\"event\":\"query\",\"scope\":\"original_frontend_queries\",\"world\":"<<s.world
       <<",\"match\":\""<<s.match<<"\",\"frame\":"<<value.frame<<",\"entity\":"<<value.identity.entity
       <<",\"unit_type\":"<<value.identity.unitType<<",\"army\":"<<value.identity.army<<",\"incarnation\":"<<value.identity.incarnation
       <<",\"lease\":"<<value.lease<<",\"generation\":"<<value.generation<<",\"revision\":"<<value.revision
       <<",\"frontend_ordinal\":"<<ordinal()<<",\"sampled_us\":"<<sampled<<",\"query_end_us\":"<<ended<<",\"joined_us\":"<<value.joinedUs
       <<",\"policy_us\":"<<value.policyUs<<",\"publication_us\":"<<value.publicationUs<<",\"alpha\":"<<value.alpha
       <<",\"actor\":"<<pointer(actor.get())<<",\"transform\":"<<pointer(transform.get())<<",\"selector\":"<<pointer(selector.get())
       <<",\"manager\":"<<pointer(manager.get())<<",\"simulation\":"<<pointer(simulation.get())
       <<",\"focus_ordinal\":"<<s.focusOrdinal<<",\"focus_frame\":"<<s.focusFrame<<",\"focus_returned_us\":"<<s.focusReturned
       <<",\"camera_controller\":"<<pointer(controller.get())<<",\"camera\":"<<pointer(camera.get())
       <<",\"thread\":"<<GetCurrentThreadId()<<",\"owner_thread\":"<<owner.thread
       <<",\"offset\":["<<value.offset.x<<','<<value.offset.y<<','<<value.offset.z<<"],\"raw\":"<<visual::xyz(value.raw)
       <<",\"displayed\":"<<visual::xyz(value.displayed)<<",\"actual\":"<<visual::xyz(actual)
       <<",\"root_matches_join\":"<<equal(actual,value.displayed)<<",\"displayed_screen\":"<<visual::xyz(displayedScreen)
       <<",\"raw_screen\":"<<visual::xyz(rawScreen)<<",\"viewport\":["<<width<<','<<height<<"]"
       <<",\"displayed_inside\":"<<inside(displayedScreen)<<",\"raw_inside\":"<<inside(rawScreen)
       <<",\"drag_rect_half_pixels\":3,\"drag_mode\":"<<mode
       <<",\"displayed_ray\":{\"hit\":"<<displayedRay.hit<<",\"identity\":"<<displayedRay.identity
       <<"},\"raw_ray\":{\"hit\":"<<rawRay.hit<<",\"identity\":"<<rawRay.identity
       <<"},\"displayed_drag\":"<<displayedDrag<<",\"raw_drag\":"<<rawDrag<<",\"ray_discriminates\":"<<rayDiscriminates
       <<",\"drag_discriminates\":"<<(displayedDrag!=rawDrag)<<",\"control\":\""<<control
       <<"\",\"physical_input\":false,\"selection_writes\":0,\"sync_transforms\":false}";
    ba::log("PREDICTION VISUAL INPUT %s",out.str().c_str());s.lastFrame=value.frame;
    if(zero){if(s.nonzero)s.zeroAfter=true;else s.zeroBefore=true;}else{++s.nonzero;++s.revisions[value.revision];}
    ba_prediction_visual_sync::observe(value,selector.get(),camera.get(),displayedScreen,
        inside(displayedScreen),displayedRay.hit&&displayedRay.unit==actor.get(),control,out.str());
}
static void tick() {
    if(!enabled() || state().failed)return;
    try {observe();}
    catch(const std::exception& error) {
        state().failed=true;ba::log("Prediction visual input smoke failed: %s",error.what());
        if(ba::initialThread && GetCurrentThreadId()==ba::initialThread) {
            try {ba_frame_timing::flush();}catch(...) {}
        }
        ba_prediction_worker::movementFail(error.what());
    }
}
}
