#pragma once
// Explicit one-shot intervention, not a production synchronization policy.
// The original Stage 1 query is already logged before this observer is called.
namespace ba_prediction_visual_sync {
namespace actors=ba_prediction_actors;
namespace visual=ba_prediction_visual;
namespace ui=ba_prediction_visual_input;
namespace click=ba_prediction_visual_click;
namespace vm=ba_prediction_actor_smoke::virtual_mouse;
namespace history=ba_prediction_actor_smoke::expired_click;
using ba::Obj;
using ba_local::Root;
using Vec3=visual::Vec3;
static bool enabled(){static const bool value=ba::flag(L"-prediction-visual-sync-smoke");return value;}
static void require(bool value,const char* why){actors::require(value,why);}
struct State {uint64_t world=0;std::string match;unsigned worlds=0;bool attempted=false,reported=false;};
static State& state(){static State value;return value;}
struct Module {
    uintptr_t base=0;
    void (*sync)()=nullptr;
};
static Module resolve() {
    Module result;result.base=reinterpret_cast<uintptr_t>(GetModuleHandleW(L"UnityPlayer.dll"));
    require(result.base!=0,"visual sync loaded UnityPlayer is missing");
    const auto* dos=reinterpret_cast<const IMAGE_DOS_HEADER*>(result.base);
    require(dos->e_magic==IMAGE_DOS_SIGNATURE&&dos->e_lfanew==0x148,"visual sync loaded UnityPlayer DOS identity differs");
    const auto* nt=reinterpret_cast<const IMAGE_NT_HEADERS64*>(result.base+0x148);
    require(nt->Signature==IMAGE_NT_SIGNATURE&&nt->FileHeader.Machine==IMAGE_FILE_MACHINE_AMD64&&
        nt->FileHeader.NumberOfSections==8&&nt->FileHeader.TimeDateStamp==0x66a03c5f&&
        nt->OptionalHeader.Magic==IMAGE_NT_OPTIONAL_HDR64_MAGIC&&nt->OptionalHeader.SizeOfImage==0x1e58000,
        "visual sync loaded UnityPlayer PE identity differs");
    const auto target=ba::api<void*(*)(const char*)>("il2cpp_resolve_icall")("UnityEngine.Physics::SyncTransforms");
    require(reinterpret_cast<uintptr_t>(target)==result.base+0x1771f0,"visual sync registered engine icall target differs");
    MEMORY_BASIC_INFORMATION memory{};
    require(VirtualQuery(target,&memory,sizeof(memory))==sizeof(memory)&&memory.AllocationBase==reinterpret_cast<void*>(result.base)&&
        memory.State==MEM_COMMIT&&!(memory.Protect&(PAGE_GUARD|PAGE_NOACCESS))&&
        (memory.Protect&(PAGE_EXECUTE|PAGE_EXECUTE_READ|PAGE_EXECUTE_READWRITE|PAGE_EXECUTE_WRITECOPY)),
        "visual sync registered engine target is not executable in UnityPlayer");
    require(std::memcmp(target,"\xe9\x8b\x1a\x56\x00",5)==0&&
        std::memcmp(reinterpret_cast<const void*>(result.base+0x6d8c80),
            "\x4c\x8b\xdc\x53\x55\x56\x57\x48\x83\xec\x78\x8b\x0d\x6f\xd0\x53",16)==0&&
        std::memcmp(reinterpret_cast<const void*>(result.base+0x6d8f9d),"\x48\x83\xc4\x78\x5f\x5e\x5d\x5b\xc3",9)==0,
        "visual sync registered engine instructions differ");
    result.sync=reinterpret_cast<void(*)()>(target);return result;
}
static std::string moduleJson(const Module& value) {
    std::ostringstream out;out<<"{\"base\":"<<ui::pointer(reinterpret_cast<Obj>(value.base))
       <<",\"pe_timestamp\":1721777247,\"pe_image_size\":31817728,\"pe_offset\":328"
       <<",\"resolver\":\"il2cpp_resolve_icall\",\"icall\":\"UnityEngine.Physics::SyncTransforms\",\"target\":"
       <<ui::pointer(reinterpret_cast<Obj>(value.base+0x1771f0))
       <<",\"target_rva\":\"0x1771f0\",\"wrapper_hex\":\"e98b1a5600\",\"engine_rva\":\"0x6d8c80\"}";
    return out.str();
}
struct Capture {visual::FrontendObservation pose;Vec3 actual,projected;std::string stable;uint64_t checked=0;};
static Capture capture(Obj selector,Obj camera) {
    Capture out;require(visual::frontendObservation(out.pose),"visual sync has no current completed pose");
    auto& owner=actors::state();require(owner.thread==GetCurrentThreadId(),"visual sync is not on the original owner thread");
    require(ba_prediction_selection::currentSelector()==selector&&ba::read<Obj>(selector,0xc0)==camera&&
        ba::read<Obj>(selector,0x40)==out.pose.manager&&ba::read<Obj>(selector,0x138)==out.pose.simulation,
        "visual sync selector owner changed");
    const Obj handler=vm::ownerGraph(owner,selector);vm::resolve();auto mouse=vm::choose(handler);
    history::validateHistory(selector);const auto h=history::history(selector);
    const auto current=ba_prediction_selection::selectionIds(ba::read<Obj>(selector,0x90));
    const auto preview=ba_prediction_selection::selectionIds(ba::read<Obj>(selector,0x88));
    const auto casting=ba_prediction_selection::selectionIds(ba::read<Obj>(selector,0x98));
    out.actual=ui::position(out.pose.transform);out.projected=ui::project(camera,out.actual);
    require(click::sameVectorBits(out.actual,out.pose.displayed),"visual sync actual root differs from completed pose");
    const float x=ba::read<float>(selector,0x14c),y=ba::read<float>(selector,0x150);
    require(std::isfinite(x)&&std::isfinite(y),"visual sync pointer is nonfinite");
    const bool primary=vm::originalBoolean(vm::api().isPressed,mouse.controls[1]->get());
    const bool context=vm::originalBoolean(vm::api().isPressed,mouse.controls[2]->get());
    const auto& p=out.pose;std::ostringstream json;json.imbue(std::locale::classic());json<<std::setprecision(17)<<std::boolalpha;
    json<<"{\"selector\":"<<ui::pointer(selector)<<",\"camera\":"<<ui::pointer(camera)
        <<",\"camera_controller\":"<<ui::pointer(ba::read<Obj>(selector,0x20))
        <<",\"actor\":"<<ui::pointer(p.actor)<<",\"transform\":"<<ui::pointer(p.transform)
        <<",\"manager\":"<<ui::pointer(p.manager)<<",\"simulation\":"<<ui::pointer(p.simulation)<<",\"handler\":"<<ui::pointer(handler)
        <<",\"thread\":"<<GetCurrentThreadId()<<",\"owner_thread\":"<<owner.thread
        <<",\"frame\":"<<p.frame<<",\"revision\":"<<p.revision<<",\"joined_us\":"<<p.joinedUs
        <<",\"policy_us\":"<<p.policyUs<<",\"publication_us\":"<<p.publicationUs<<",\"alpha\":"<<p.alpha
        <<",\"lease\":"<<p.lease<<",\"generation\":"<<p.generation<<",\"entity\":"<<p.identity.entity
        <<",\"unit_type\":"<<p.identity.unitType<<",\"army\":"<<p.identity.army<<",\"incarnation\":"<<p.identity.incarnation
        <<",\"actual\":"<<visual::xyz(out.actual)<<",\"projected\":"<<visual::xyz(out.projected)
        <<",\"drag_mode\":"<<ba::read<int32_t>(p.actor,0xe8)
        <<",\"raw\":"<<visual::xyz(p.raw)<<",\"displayed\":"<<visual::xyz(p.displayed)
        <<",\"offset\":["<<p.offset.x<<','<<p.offset.y<<','<<p.offset.z<<"],\"pointer\":["<<x<<','<<y<<']'
        <<",\"history\":{\"id\":"<<h.id<<",\"mode\":"<<h.mode<<",\"primary\":"<<h.primary<<",\"context\":"<<h.context
        <<",\"drag\":"<<h.drag<<",\"last_up\":"<<h.lastUp<<",\"window\":"<<h.window<<'}'
        <<",\"current_ids\":"<<click::ids(current)<<",\"preview_ids\":"<<click::ids(preview)<<",\"casting_ids\":"<<click::ids(casting)
        <<",\"pending_commands\":"<<click::pending()<<",\"mouse\":{\"device\":"<<ui::pointer(mouse.device->get());
    const char* keys[]={"controls","actions","references"};
    for(unsigned k=0;k<3;++k) {
        json<<",\""<<keys[k]<<"\":[";
        for(unsigned i=0;i<3;++i){if(i)json<<',';json<<ui::pointer(k==0?mouse.controls[i]->get():k==1?mouse.actions[i]->get():mouse.references[i]->get());}
        json<<']';
    }
    json<<",\"primary\":"<<primary<<",\"context\":"<<context<<",\"session_active\":"<<vm::session().active
        <<",\"session_sequence\":"<<vm::session().sequence<<"}";
    out.stable=json.str();out.checked=visual::stamp();
    require(out.checked>=p.joinedUs&&out.checked-p.joinedUs<=50000,"visual sync completed pose is stale");return out;
}
static std::string captureJson(const Capture& value){return value.stable+",\"checked_us\":"+std::to_string(value.checked)+'}';}
static void unchanged(const Capture& before,const Capture& after,Vec3 point) {
    require(click::samePose(before.pose,after.pose)&&click::sameVectorBits(before.actual,after.actual)&&
        click::sameVectorBits(before.projected,after.projected)&&click::sameVectorBits(after.projected,point)&&before.stable==after.stable,
        "visual sync probe changed its owner, completed pose, projected point, input or selection");
}
static std::string hitJson(const ui::Hit& hit,uint64_t begin,uint64_t end) {
    std::ostringstream out;out<<std::boolalpha<<"{\"begin_us\":"<<begin<<",\"end_us\":"<<end<<",\"hit\":"<<hit.hit
        <<",\"identity\":"<<hit.identity<<'}';return out.str();
}
static void observe(const visual::FrontendObservation& pose,Obj selector,Obj camera,Vec3 point,
                    bool inside,bool subject,const char* control,const std::string& source) {
    if(!enabled())return;
    require(ba::flag(L"-prediction-visual-input-smoke")&&ba::flag(L"-prediction-visual-observe")&&
        ba::flag(L"-prediction-visual-click-acquire")&&
        ba_prediction_worker::visualCorrectionsEnabled()&&!ba_lan::publicMatch,"visual sync requires the owned visual input diagnostic");
    auto& s=state();if(s.world!=pose.identity.world||s.match!=pose.identity.match) {
        require(pose.identity.world>s.world&&s.worlds<2&&(!s.world||s.reported),
            "visual sync world order or previous completion differs");
        const auto count=s.worlds+1;s=State{};s.worlds=count;s.world=pose.identity.world;s.match=pose.identity.match;
    }
    if(s.attempted||s.reported)return;
    const bool trigger=std::strcmp(control,"nonzero")==0&&inside&&!subject&&click::magnitude(pose)>=0.5;
    const bool terminal=std::strcmp(control,"zero_after")==0;
    if(!trigger&&!terminal)return;
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::setprecision(17)<<std::boolalpha;
    out<<"{\"schema\":1,\"event\":\""<<(trigger?"probe":"no_trigger")<<"\",\"world\":"<<s.world
       <<",\"match\":\""<<s.match<<"\",\"sequence\":1,\"source\":"<<source<<",\"point\":["<<point.x<<','<<point.y
       <<"],\"point_bits\":["<<click::protocol::Point::bits(point.x)<<','<<click::protocol::Point::bits(point.y)<<']';
    if(!trigger) {
        out<<",\"module\":null,\"pre\":null,\"sync\":{\"calls\":0},\"post\":null,\"before\":null,\"after\":null"
           <<",\"checked_us\":"<<visual::stamp()<<",\"invariants_unchanged\":true,\"selection_writes\":0,\"history_writes\":0,\"physical_input\":false}";
        s.reported=true;ba::log("VISUAL SYNC %s",out.str().c_str());return;
    }
    s.attempted=true; // Set before resolution or any query: a failure never retries.
    ba::log("Visual sync capability: BA_RESURRECTION_VISUAL_SYNC_V1");
    const auto module=resolve();const auto before=capture(selector,camera);
    require(click::samePose(pose,before.pose)&&click::sameVectorBits(before.projected,point),"visual sync source query pose or point changed");
    const auto preBegin=visual::stamp();auto pre=ui::ray(selector,point,actors::state());const auto preEnd=visual::stamp();
    const auto sham=capture(selector,camera);unchanged(before,sham,point);
    const auto entered=visual::stamp();module.sync();const auto returned=visual::stamp();
    const auto synced=capture(selector,camera);unchanged(before,synced,point);
    const auto postBegin=visual::stamp();auto post=ui::ray(selector,point,actors::state());const auto postEnd=visual::stamp();
    const auto after=capture(selector,camera);unchanged(before,after,point);
    require(before.checked<=preBegin&&preBegin<=preEnd&&preEnd<=sham.checked&&sham.checked<=entered&&entered<=returned&&
        returned<=synced.checked&&synced.checked<=postBegin&&postBegin<=postEnd&&postEnd<=after.checked,
        "visual sync query or intervention clock order differs");
    out<<",\"module\":"<<moduleJson(module)<<",\"pre\":"<<hitJson(pre,preBegin,preEnd)
       <<",\"sync\":{\"entered_us\":"<<entered<<",\"returned_us\":"<<returned<<",\"calls\":1},\"post\":"<<hitJson(post,postBegin,postEnd)
       <<",\"before\":"<<captureJson(before)<<",\"after\":"<<captureJson(after)<<",\"checked_us\":"<<after.checked
       <<",\"invariants_unchanged\":true,\"selection_writes\":0,\"history_writes\":0,\"physical_input\":false}";
    s.reported=true;ba::log("VISUAL SYNC %s",out.str().c_str());
}
}
