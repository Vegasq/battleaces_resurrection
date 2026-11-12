// Include after actor repair. Optional movement recipe, explicit runtime flag.
// Original native PositionBuffer, input, From/To and job scheduling stay owned
// by the game. Only joined shared presentation output and its Transform change.
#include "prediction_visual_correction.hpp"
#include "prediction_visual_lifetime.hpp"
#include <iomanip>
#include <locale>
#include <sstream>

namespace ba_prediction_visual {
using ba::Obj;
using ba_local::Root;
namespace actors=ba_prediction_actors;
namespace worker=ba_prediction_worker;
namespace policy=ba_prediction_visual_correction;
namespace lifetime=ba_prediction_visual_lifetime;
struct Vec3 {float x=0,y=0,z=0;};
struct Array {Vec3* values=nullptr;int32_t length=0,allocator=0;};
static_assert(sizeof(Vec3)==12 && sizeof(Array)==16,"original Vector3/NativeArray ABI differs");
static constexpr size_t Capacity=2048;
struct Entry {
    policy::Identity identity;
    uint64_t lease=0;
    std::unique_ptr<Root> actor,transform;
    policy::Policy correction;
    bool wrote=false;
};
// Diagnostic receipt of a completed join. Reading this never resamples policy
// or advances the original interpolation clock. Entry roots own these pointers.
struct FrontendObservation {
    policy::Identity identity;
    uint64_t lease=0,generation=0,revision=0,publicationUs=0,policyUs=0,joinedUs=0;
    int frame=-1;
    float alpha=0;
    Vec3 raw,displayed;
    policy::Vec3 offset;
    Obj actor=nullptr,transform=nullptr,simulation=nullptr,manager=nullptr;
};
struct State {
    uint64_t world=0,revision=0,publicationUs=0,traceRows=0;
    std::string match;
    std::unique_ptr<Root> simulation,manager,interpolator;
    int frame=-1;
    bool pending=false,failed=false,havePerspective=false,flipped=false,ownershipObserved=false;
    ba_prediction_correction_wire::Frame packet;
    std::map<uint32_t,Entry> entries;
    FrontendObservation frontend;
};
static State& state(){static State* lifetime=new State;return *lifetime;}
static void require(bool value,const char* why){actors::require(value,why);}
static uint64_t stamp() {
    uint64_t value=0;require(ba_frame_timing::timestampMicros(value),"visual correction QPC unavailable");return value;
}
static void mainThread() {
    require(ba::initialThread && GetCurrentThreadId()==ba::initialThread,"visual correction requires retained Unity thread");
}
struct RetainedCounts {size_t entries=0,pulses=0,roots=0;};
static RetainedCounts retained(const State& s) {
    RetainedCounts value;value.entries=s.entries.size();
    value.roots=static_cast<size_t>(bool(s.simulation))+static_cast<size_t>(bool(s.manager))+static_cast<size_t>(bool(s.interpolator));
    for(const auto& pair:s.entries) {
        value.pulses+=pair.second.correction.activePulses();
        value.roots+=static_cast<size_t>(bool(pair.second.actor))+static_cast<size_t>(bool(pair.second.transform));
    }
    return value;
}
static void clear(const char* trigger,const lifetime::Snapshot* observed=nullptr) {
    mainThread();auto& s=state();const auto before=retained(s);
    if(!s.world && !before.roots && !before.entries){s=State{};return;}
    const auto snapshot=observed?*observed:ba_prediction_movement::presentationLifetime();
    const auto reason=lifetime::retirement(s.world,s.match,s.failed,snapshot);
    if(reason==lifetime::Reason::Keep) {
        // A join from an unrelated or retiring original simulation cannot
        // discard the current owner's roots. New binding must still agree
        // with the current scalar movement/worker generation.
        require(strcmp(trigger,"new_world")!=0,"visual new-world binding contradicts active lifetime keys");return;
    }
    const auto world=s.world;const auto match=s.match;const int frame=s.frame;const bool visualFailed=s.failed;
    s=State{};const auto after=retained(s);
    require(!after.roots && !after.entries && !after.pulses,"visual root retirement is incomplete");
    if(!ba::flag(L"-prediction-presentation-stages") && !ba::flag(L"-prediction-visual-observe"))return;
    static unsigned rows=0;require(rows<64,"visual lifetime diagnostic row bound reached");++rows;
    std::ostringstream line;line.imbue(std::locale::classic());line<<std::boolalpha;
    line<<"{\"schema\":1,\"event\":\"retired\",\"world\":"<<world<<",\"match\":\""<<match
        <<"\",\"frame\":"<<frame<<",\"reason\":\""<<lifetime::name(reason)<<"\",\"trigger\":\""<<trigger
        <<"\",\"sampled_us\":"<<stamp()<<",\"thread\":"<<GetCurrentThreadId()<<",\"owner_thread\":"<<snapshot.ownerThread
        <<",\"entries_before\":"<<before.entries<<",\"pulses_before\":"<<before.pulses<<",\"roots_before\":"<<before.roots
        <<",\"entries_after\":"<<after.entries<<",\"pulses_after\":"<<after.pulses<<",\"roots_after\":"<<after.roots
        <<",\"movement_world\":"<<snapshot.movementWorld<<",\"movement_match\":\""<<snapshot.movementMatch
        <<"\",\"worker_world\":"<<snapshot.workerWorld<<",\"worker_match\":\""<<snapshot.workerMatch
        <<"\",\"prepared\":"<<snapshot.prepared<<",\"pacing_started\":"<<snapshot.pacingStarted
        <<",\"failed\":"<<snapshot.failed<<",\"visual_failed\":"<<visualFailed<<",\"end_sent\":"<<snapshot.endSent
        <<",\"drained\":"<<snapshot.drained<<",\"match_ended\":"<<snapshot.matchEnded
        <<",\"abort_pending\":"<<snapshot.abortPending<<",\"connected\":"<<snapshot.connected<<'}';
    ba::log("VISUAL CORRECTION LIFETIME %s",line.str().c_str());
}
void clearInactive(const char* trigger) {
    if(!worker::visualCorrectionsEnabled())return;
    const auto& s=state();if(!s.world && !s.simulation && !s.manager && !s.interpolator && s.entries.empty())return;
    mainThread();const auto snapshot=ba_prediction_movement::presentationLifetime();
    if(lifetime::retirement(s.world,s.match,s.failed,snapshot)!=lifetime::Reason::Keep)clear(trigger,&snapshot);
}
static void finite(const Vec3& value) {
    require(std::isfinite(value.x)&&std::isfinite(value.y)&&std::isfinite(value.z),"visual correction position is nonfinite");
}
static Obj returnClass(Obj method) {
    return ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
        ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(method));
}
static void valueSize(Obj klass,int expected) {
    uint32_t alignment=0;
    require(klass && ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(klass) &&
        ba::api<int32_t(*)(Obj,uint32_t*)>("il2cpp_class_value_size")(klass,&alignment)==expected,
        "visual correction value layout differs");
}
static actors::State& owned(Obj simulation) {
    mainThread();auto& owner=actors::state();
    require(!owner.failed && !owner.inUpdate && owner.world==worker::movementWorldId() &&
        owner.match==worker::movementMatchId() && owner.thread==GetCurrentThreadId() &&
        owner.simulation && owner.simulation->get()==simulation && owner.manager &&
        ba::read<Obj>(simulation,0x70)==owner.manager->get(),"visual correction actor owner differs");
    return owner;
}
void published(void* simulation) {
    if(!worker::visualCorrectionsEnabled())return;
    mainThread();
    if(!ba_prediction_movement::ownsPresentation(simulation)){clear("publication_inactive");return;}
    auto& owner=owned(simulation);auto& s=state();
    if(s.world!=owner.world || s.match!=owner.match) {
        clear("new_world");s.world=owner.world;s.match=owner.match;
        s.simulation=std::make_unique<Root>(simulation);s.manager=std::make_unique<Root>(owner.manager->get());
    }
    require(!s.failed && s.simulation->get()==simulation && s.manager->get()==owner.manager->get(),
        "visual correction publication changed owner");
    const int frame=ba::read<int>(simulation,0xac);
    require(frame>=0 && frame>s.frame && (!s.pending || s.packet.deltas.empty()),
        "visual correction missed/repeated a publication");
    const auto publicationUs=stamp();auto packet=worker::movementCorrections(frame);
    require(packet.world==s.world && packet.revision>=s.revision &&
        (packet.deltas.empty() || packet.revision>s.revision),"visual correction revision regressed/repeated");
    s.frame=frame;s.revision=packet.revision;s.publicationUs=publicationUs;
    s.packet=std::move(packet);s.pending=true;
}
struct Live {Obj actor=nullptr;actors::Resident resident;};
static std::map<uint32_t,Live> live(actors::State& owner,uint32_t localArmy) {
    std::map<uint32_t,Live> result;
    for(Obj actor:actors::units(ba::read<Obj>(owner.manager->get(),0x10))) {
        const auto found=owner.identities.find(actor);if(found==owner.identities.end())continue;
        const auto& resident=found->second;
        if(resident.identity.armyId!=localArmy || !resident.incarnation ||
           actors::confirmedToken(owner,resident.identity)!=resident.incarnation)continue;
        const auto actual=actors::resident(actor);
        require(actual.entityId==resident.identity.entityId && actual.unitType==resident.identity.unitType &&
            actual.armyId==resident.identity.armyId && resident.presentationLease,"visual correction actor lease/identity differs");
        actors::field(actor,"<DeadToTheSim>k__BackingField",0x160);
        if(ba::read<bool>(actor,0x160))continue;
        require(result.emplace(actual.entityId,Live{actor,resident}).second,"visual correction duplicate live entity");
    }
    return result;
}
static policy::Identity identity(const State& s,const actors::Resident& resident) {
    return {s.world,s.match,resident.identity.entityId,resident.identity.unitType,
        resident.identity.armyId,resident.incarnation};
}
static bool mapPerspective(actors::State& owner,Obj current) {
    // Bind to the map's real local-alliance perspective, not army parity.
    actors::field(current,"<LocalAllianceId>k__BackingField",0x48);
    actors::field(owner.simulation->get(),"_localPlayer",0x90);
    Root player(ba::read<Obj>(owner.simulation->get(),0x90));actors::classIs(player.get(),"Uncapped","SimPlayer");
    actors::field(player.get(),"AllianceID",0x3c);actors::field(player.get(),"ArmyID",0x38);
    uint32_t alliance=ba::read<uint32_t>(player.get(),0x3c);
    require(alliance==ba::read<uint32_t>(current,0x48) &&
        ba::read<uint32_t>(player.get(),0x38)==static_cast<uint32_t>(ba::lanSlot()),
        "visual correction local player/alliance assignment differs");
    Root selector(ba::get<Obj>(ba::owner,"<UnitSelector>k__BackingField"));
    actors::classIs(selector.get(),"Uncapped","UnitSelector");
    actors::field(selector.get(),"_simulation",0x138);actors::field(selector.get(),"_mapManager",0x50);
    require(ba::read<Obj>(selector.get(),0x138)==owner.simulation->get(),"visual correction perspective owner differs");
    Root manager(ba::read<Obj>(selector.get(),0x50));actors::classIs(manager.get(),"Uncapped","MapManager");
    const auto getMap=actors::method(manager.get(),"get_CurrentMap",0,0x0600077e,0x845d70);
    Root map(actors::invoke(getMap,manager.get()));actors::classIs(map.get(),"Uncapped","Map");
    const auto get=actors::method(map.get(),"GetAlliancePerspective",1,0x0600075b,0x3db8f80);
    Obj enumType=returnClass(get);valueSize(enumType,4);
    require(ba::api<bool(*)(Obj)>("il2cpp_class_is_enum")(enumType),"visual correction perspective result is not an enum");
    auto literal=[&](const char* name) {
        Obj field=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(enumType,name);
        require(field && (ba::api<uint32_t(*)(Obj)>("il2cpp_field_get_flags")(field)&0x50u)==0x50u,
            "visual correction perspective literal unavailable");
        int32_t value=0;ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(field,&value);return value;
    };
    const int normal=literal("Normal"),flipped=literal("Flipped");
    require(normal!=flipped,"visual correction perspective enum ambiguous");
    void* args[]={&alliance};Root boxed(actors::invoke(get,map.get(),args));
    require(boxed.get() && ba::klass(boxed.get())==enumType,"visual correction boxed perspective differs");
    const auto value=actors::unbox<int32_t>(boxed.get());
    require(value==normal || value==flipped,"visual correction unknown map perspective");return value==flipped;
}
static bool same(const Entry& entry,const State& s,const Live& value) {
    return entry.actor && entry.actor->get()==value.actor && entry.lease==value.resident.presentationLease &&
        policy::sameIdentity(entry.identity,identity(s,value.resident));
}
static Entry& bind(State& s,const Live& value) {
    const auto id=value.resident.identity.entityId;auto found=s.entries.find(id);
    if(found!=s.entries.end() && !same(found->second,s,value)){s.entries.erase(found);found=s.entries.end();}
    if(found==s.entries.end()) {
        require(s.entries.size()<Capacity,"visual correction entry capacity exceeded");
        Entry entry;entry.identity=identity(s,value.resident);entry.lease=value.resident.presentationLease;
        entry.actor=std::make_unique<Root>(value.actor);
        entry.transform=std::make_unique<Root>(ba::call(value.actor,"get_transform"));
        actors::classIs(entry.transform->get(),"UnityEngine","Transform");
        require(entry.correction.reset(entry.identity),"visual correction cannot bind identity");
        found=s.entries.emplace(id,std::move(entry)).first;
    }
    return found->second;
}
struct Clock {float now=0,start=0,elapsed=0,step=0,alpha=0;Obj time=nullptr;};
static Clock clock(Obj interpolate) {
    actors::field(interpolate,"_presentationTime",0xf0);actors::field(interpolate,"_interpolationStartTime",0x100);
    Clock result;result.time=ba::read<Obj>(interpolate,0xf0);
    actors::classIs(result.time,"Uncapped","PresentationTime");actors::field(result.time,"NowUnmodified",0x18);
    const auto now=actors::method(result.time,"Uncapped.IPresentationTime.get_NowUnmodified",0,0x06000013,0x92f6f0);
    require(returnClass(now)==actors::type("System","Single"),"visual correction original clock type differs");
    result.now=reinterpret_cast<float(*)(Obj,Obj)>(ba::read<Obj>(now,0))(result.time,now);
    result.start=ba::read<float>(interpolate,0x100);result.elapsed=result.now-result.start;
    require(std::isfinite(result.now)&&std::isfinite(result.start)&&std::isfinite(result.elapsed)&&result.elapsed>=0,
        "visual correction original interpolation time invalid");
    // Original step0 returns before reading the denominator at elapsed==0.
    if(result.elapsed==0)return result;
    actors::field(interpolate,"_serverManager",0xf8);
    Obj services=ba::read<Obj>(interpolate,0xf8);actors::classIs(services,"Uncapped","ServiceManager");
    actors::field(services,"<GameServer>k__BackingField",0x18);
    Obj server=ba::read<Obj>(services,0x18);actors::classIs(server,"Uncapped","GameServerIntegration");
    const auto step=actors::method(server,"GetScaledSimTimeStepSeconds",0,0x060010ed,0x3e4faa0);
    require(returnClass(step)==actors::type("System","Single"),"visual correction original step type differs");
    result.step=reinterpret_cast<float(*)(Obj,Obj)>(ba::read<Obj>(step,0))(server,step);
    require(std::isfinite(result.step)&&result.step>=0,"visual correction original scaled step invalid");
    if(result.step!=0)result.alpha=(std::max)(0.0f,(std::min)(1.0f,result.elapsed/result.step));
    return result;
}
struct Storage {
    Obj ids=nullptr,lookup=nullptr,reverse=nullptr;
    Array from,to,output;
    int count=0;
    explicit Storage(Obj interpolate) {
        actors::field(interpolate,"_memoryIsInitialized",0x104);
        require(ba::read<bool>(interpolate,0x104),"visual correction interpolation memory is not initialized");
        actors::field(interpolate,"_trackedUnitTransformEntities",0x20);
        ids=ba::read<Obj>(interpolate,0x20);actors::classIs(ids,"Uncapped.Collections","NativeEntityIdSet");
        actors::field(ids,"<Count>k__BackingField",0x10);count=ba::read<int>(ids,0x10);
        require(count>=0 && count<=static_cast<int>(Capacity),"visual correction tracked capacity differs");
        actors::field(interpolate,"_interpolatedPositions",0x10);
        Obj shared=ba::read<Obj>(interpolate,0x10);require(shared,"visual correction shared positions missing");
        actors::field(shared,"_valuesArray",0x10);actors::field(shared,"_ids",0x30);
        require(ba::read<Obj>(shared,0x30)==ids,"visual correction shared IDs differ");
        Obj get=actors::method(shared,"get_Item",1,0x0600013d);
        require(returnClass(get)==actors::type("UnityEngine","Vector3"),"visual correction shared element type differs");
        valueSize(returnClass(get),12);
        auto array=[&](const char* name,size_t offset) {
            actors::field(interpolate,name,offset);
            Obj klass=ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
                ba::api<Obj(*)(Obj)>("il2cpp_field_get_type")(ba::field(interpolate,name)));
            valueSize(klass,16);require(!strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(klass),"NativeArray`1"),
                "visual correction native array type differs");
            const auto value=ba::read<Array>(interpolate,offset);
            require(value.values && value.length==static_cast<int>(Capacity),"visual correction native array capacity differs");
            return value;
        };
        from=array("_fromPositionsBuffer",0x30);to=array("_toPositionsBuffer",0x50);
        output=array("_interpolatedPositionsBuffer",0x70);
        const auto sharedArray=ba::read<Array>(shared,0x10);
        require(sharedArray.values==output.values && sharedArray.length==output.length &&
            from.values!=to.values && from.values!=output.values && to.values!=output.values,
            "visual correction output/native endpoint arrays alias unexpectedly");
        actors::field(interpolate,"_presentationComponentBuffers",0x18);
        Obj buffers=ba::read<Obj>(interpolate,0x18);actors::classIs(buffers,"Uncapped","PresentationComponentBuffers");
        actors::field(buffers,"InterpolatedPositions",0x10);
        require(ba::read<Obj>(buffers,0x10)==shared,"visual correction published buffer differs");
        lookup=actors::method(ids,"TryFindIndex",2,0x060000ab,0x3782500);
        reverse=actors::method(ids,"get_Item",1,0x06000153,0x3787900);
        require(returnClass(lookup)==actors::type("System","Boolean") && returnClass(reverse)==actors::type("System","UInt32"),
            "visual correction ID lookup return types differ");
    }
    int index(uint32_t entity)const {
        int index=-1;void* args[]={&entity,&index};Root found(actors::invoke(lookup,ids,args));
        require(actors::unbox<bool>(found.get()) && index>=0 && index<count,"visual correction live ID is not tracked");
        void* backArgs[]={&index};Root back(actors::invoke(reverse,ids,backArgs));
        require(actors::unbox<uint32_t>(back.get())==entity,"visual correction full-ID reverse lookup differs");return index;
    }
};
struct Trace {bool enabled=false;uint32_t entity=0,type=0,army=0;int first=0,last=0;};
static const Trace& trace() {
    static const auto value=[]() {
        Trace out;if(!ba::flag(L"-prediction-visual-observe"))return out;
        require(worker::visualCorrectionsEnabled(),"visual observation requires explicit correction mode");
        std::istringstream in(ba::argument(L"-prediction-movement-observe-position=",""));in.imbue(std::locale::classic());
        uint64_t id=0,type=0,army=0,first=0,last=0;char a=0,b=0,c=0,d=0;
        require(static_cast<bool>(in>>id>>a>>type>>b>>army>>c>>first>>d>>last) && in.peek()==EOF &&
            a==':'&&b==':'&&c==':'&&d==':'&&id<=UINT32_MAX&&type<=UINT32_MAX&&army<=1&&
            first<=last&&last<=INT32_MAX&&last-first<=600,"visual observation identity/window invalid");
        out={true,static_cast<uint32_t>(id),static_cast<uint32_t>(type),static_cast<uint32_t>(army),
            static_cast<int>(first),static_cast<int>(last)};return out;
    }();return value;
}
static bool traced(const Entry& entry,int frame) {
    const auto& spec=trace();return spec.enabled&&frame>=spec.first&&frame<=spec.last&&
        entry.identity.entity==spec.entity&&entry.identity.unitType==spec.type&&entry.identity.army==spec.army;
}
static std::string xyz(const Vec3& point) {
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::setprecision(9);
    out<<'['<<point.x<<','<<point.y<<','<<point.z<<']';return out.str();
}
static void emitCorrection(State& s,const Entry& entry,const ba_prediction_correction_wire::Delta& delta,
                           const policy::Vec3& mapped,policy::Admission admitted,bool flipped) {
    if(!traced(entry,s.frame))return;
    require(++s.traceRows<=100000,"visual correction bounded trace exhausted");
    const Vec3 original{delta.x,delta.y,delta.z};
    const Vec3 transformed{static_cast<float>(mapped.x),static_cast<float>(mapped.y),static_cast<float>(mapped.z)};
    std::ostringstream line;line.imbue(std::locale::classic());line<<std::setprecision(17);
    line<<"{\"schema\":1,\"event\":\"correction\",\"world\":"<<s.world<<",\"match\":\""<<s.match<<
        "\",\"frame\":"<<s.frame<<",\"head\":"<<s.packet.head<<",\"revision\":"<<s.packet.revision<<
        ",\"entity\":"<<delta.entity<<",\"unit_type\":"<<delta.type<<",\"army\":"<<delta.army<<
        ",\"incarnation\":"<<delta.incarnation<<",\"lease\":"<<entry.lease<<",\"publication_us\":"<<s.publicationUs<<
        ",\"duration_us\":"<<policy::Policy::DurationUs<<",\"admission\":"<<static_cast<unsigned>(admitted)<<
        ",\"flipped\":"<<(flipped?"true":"false")<<",\"native_delta\":"<<xyz(original)<<
        ",\"mapped_delta\":"<<xyz(transformed)<<"}";
    ba::log("PREDICTION VISUAL %s",line.str().c_str());
}
static void observeOwnership(Obj simulation,Obj frame,const char* stage) {
    // Bounded diagnostic only in the existing owned movement fixture. Record
    // the initial peer fields even when no correction needs the ordinary scan.
    if(!ba::flag(L"-prediction-movement-smoke"))return;
    actors::field(frame,"<FrameNumber>k__BackingField",0x40);
    actors::field(frame,"<LocalArmyId>k__BackingField",0x44);
    actors::field(frame,"<LocalAllianceId>k__BackingField",0x48);
    actors::field(simulation,"_localPlayer",0x90);
    Root player(ba::read<Obj>(simulation,0x90));actors::classIs(player.get(),"Uncapped","SimPlayer");
    actors::field(player.get(),"ArmyID",0x38);actors::field(player.get(),"AllianceID",0x3c);
    const auto& s=state();
    ba::log("Prediction visual owner: stage=%s world=%llu frame=%d componentFrame=%d presentedFrame=%d localArmy=%u localAlliance=%u playerArmy=%u playerAlliance=%u assignedSlot=%d metadataFrame=%d metadataHead=%d revision=%llu deltas=%zu",
        stage,static_cast<unsigned long long>(s.world),s.frame,ba::read<int>(frame,0x40),ba::read<int>(simulation,0xac),
        ba::read<uint32_t>(frame,0x44),ba::read<uint32_t>(frame,0x48),ba::read<uint32_t>(player.get(),0x38),
        ba::read<uint32_t>(player.get(),0x3c),ba::lanSlot(),s.packet.frame,s.packet.head,
        static_cast<unsigned long long>(s.packet.revision),s.packet.deltas.size());
}
static void afterJoin(Obj interpolate,Obj methodInfo) {
    mainThread();require(!methodInfo,"visual correction original join MethodInfo differs");
    actors::classIs(interpolate,"Uncapped.Systems","UnitInterpolationSystem");
    actors::field(interpolate,"_simulation",0xe0);actors::field(interpolate,"_unitManager",0xe8);
    Obj simulation=ba::read<Obj>(interpolate,0xe0);
    if(!ba_prediction_movement::ownsPresentation(simulation)){clear("join_inactive");return;}
    // BEGIN/pacing may precede the first frame and actor publication. Joining
    // those original startup jobs does not yet create a presentation owner.
    if(ba::read<int>(simulation,0xac)<0){clear("unpublished_frame");return;}
    auto& owner=owned(simulation);auto& s=state();
    require(!s.failed && s.simulation && s.simulation->get()==simulation && s.world==owner.world && s.match==owner.match &&
        s.manager && s.manager->get()==owner.manager->get() && ba::read<Obj>(interpolate,0xe8)==owner.manager->get() &&
        s.frame==ba::read<int>(simulation,0xac),"visual correction final join lacks exact publication/owner");
    if(!s.interpolator || s.interpolator->get()!=interpolate) {
        s.entries.clear();s.interpolator=std::make_unique<Root>(interpolate);
        actors::guard(0x3c563be,"\x85\xdb\x74\x30\x3b\xde\x0f\x85\x18\x08\x00\x00\x33\xd2\x48\x8b\xcf",17);
        actors::guard(0x3c563d4,"\x48\x8b\x4f\x10\x48\x85\xc9\x0f\x84\x2c\x08\x00\x00",13);
        actors::method(interpolate,"EnsureJobsComplete",0,0x0600254d,0x3c56040);
    }
    const auto& spec=trace();
    const bool observeFrame=spec.enabled && s.frame>=spec.first && s.frame<=spec.last;
    if(!s.ownershipObserved && ba::flag(L"-prediction-movement-smoke")) {
        Root frame(actors::Current::resolveFrame(ba::read<Obj>(simulation,0x148)));
        observeOwnership(simulation,frame.get(),"initial");s.ownershipObserved=true;
    }
    if(s.entries.empty() && (!s.pending || s.packet.deltas.empty()) && !observeFrame) {
        // Ordinary motion must not pay for managed collections/positions or
        // scan the army on every render pass when there is no offset to decay.
        s.pending=false;return;
    }
    actors::Current current(ba::read<Obj>(simulation,0x148));
    actors::field(current.frame.get(),"<FrameNumber>k__BackingField",0x40);
    actors::field(current.frame.get(),"<LocalAllianceId>k__BackingField",0x48);
    actors::field(current.frame.get(),"_isPerspectiveFlipped",0x28);
    require(ba::read<int>(current.frame.get(),0x40)==s.frame,"visual correction component frame differs");
    // Actual77's peer frame has LocalArmyId=0 at both0 and713, while the
    // simulation player, frame alliance and assignment consistently identify1.
    // Use the same simulation-owned ArmyID as original selection/group repair;
    // the frame's LocalArmyId field is not an authenticated local player key.
    actors::field(simulation,"_localPlayer",0x90);
    Root localPlayer(ba::read<Obj>(simulation,0x90));actors::classIs(localPlayer.get(),"Uncapped","SimPlayer");
    actors::field(localPlayer.get(),"ArmyID",0x38);actors::field(localPlayer.get(),"AllianceID",0x3c);
    const auto localArmy=ba::read<uint32_t>(localPlayer.get(),0x38);
    const auto localAlliance=ba::read<uint32_t>(localPlayer.get(),0x3c);
    const auto frameAlliance=ba::read<uint32_t>(current.frame.get(),0x48);
    const int assignedSlot=ba::lanSlot();
    if(localArmy>1 || localArmy!=static_cast<uint32_t>(assignedSlot) || localAlliance!=frameAlliance) {
        observeOwnership(simulation,current.frame.get(),"refused");
        throw std::runtime_error("visual correction local player ownership differs: frame="+std::to_string(s.frame)+
            " localArmy="+std::to_string(localArmy)+" assignedSlot="+std::to_string(assignedSlot)+
            " localAlliance="+std::to_string(localAlliance)+" frameAlliance="+std::to_string(frameAlliance)+
            " pendingDeltas="+std::to_string(s.pending?s.packet.deltas.size():0));
    }
    const bool flipped=ba::read<bool>(current.frame.get(),0x28);
    if(!s.havePerspective || s.flipped!=flipped) {
        require(mapPerspective(owner,current.frame.get())==flipped,"visual correction map/component perspective disagrees");
        s.entries.clear();s.havePerspective=true;s.flipped=flipped;
    }
    const auto members=live(owner,localArmy);
    for(auto it=s.entries.begin();it!=s.entries.end();) {
        const auto found=members.find(it->first);
        if(found==members.end() || !same(it->second,s,found->second))it=s.entries.erase(it);else ++it;
    }
    if(s.pending) {
        for(const auto& delta:s.packet.deltas) {
            require(delta.army==localArmy,"visual correction metadata exposes another army");
            const auto found=members.find(delta.entity);if(found==members.end())continue;
            const auto& resident=found->second.resident;
            if(resident.identity.unitType!=delta.type || resident.incarnation!=delta.incarnation)continue;
            auto& entry=bind(s,found->second);
            const policy::Vec3 mapped{flipped?-static_cast<double>(delta.x):delta.x,delta.y,
                flipped?-static_cast<double>(delta.z):delta.z};
            const auto admitted=entry.correction.admit(entry.identity,s.packet.revision,s.frame,s.publicationUs,mapped);
            require(admitted==policy::Admission::Accepted || admitted==policy::Admission::NoCorrection ||
                admitted==policy::Admission::UncompensatedCapacity || admitted==policy::Admission::UncompensatedDistance,
                "visual correction admission identity/revision/order refused");
            emitCorrection(s,entry,delta,mapped,admitted,flipped);
        }
        s.pending=false;s.packet.deltas.clear();
    }
    if(observeFrame) {
        const auto found=members.find(spec.entity);
        if(found!=members.end() && found->second.resident.identity.unitType==spec.type &&
           found->second.resident.identity.armyId==spec.army)bind(s,found->second);
    }
    if(s.entries.empty())return;
    const auto timing=clock(interpolate);const Storage storage(interpolate);const auto now=stamp();
    struct Write {uint32_t entity=0;int index=0;Obj setter=nullptr;Vec3 from,to,raw,displayed;policy::Sample sampled;bool mutate=false;};
    std::vector<Write> writes;writes.reserve(s.entries.size());
    for(auto& pair:s.entries) {
        auto& entry=pair.second;const int index=storage.index(pair.first);
        Root transform(ba::call(entry.actor->get(),"get_transform"));
        require(transform.get()==entry.transform->get(),"visual correction actor Transform changed within its lease");
        Write write;write.entity=pair.first;write.index=index;write.from=storage.from.values[index];write.to=storage.to.values[index];
        // At zero elapsed, step0 schedules nothing. From is never overlaid and
        // is the original From->Output/Transform publication base, even when
        // this same zero-time callback repeats. Never accumulate over output.
        write.raw=timing.elapsed==0?write.from:storage.output.values[index];
        finite(write.from);finite(write.to);finite(write.raw);
        write.sampled=entry.correction.sample(entry.identity,s.frame,timing.alpha,now);
        require(write.sampled.status==policy::SampleStatus::Ok,"visual correction sample refused");
        write.displayed={static_cast<float>(write.raw.x+write.sampled.offset.x),
            static_cast<float>(write.raw.y+write.sampled.offset.y),static_cast<float>(write.raw.z+write.sampled.offset.z)};
        finite(write.displayed);
        const bool offset=write.sampled.offset.x!=0 || write.sampled.offset.y!=0 || write.sampled.offset.z!=0;
        write.mutate=offset || entry.wrote;
        if(write.mutate) {
            write.setter=actors::method(entry.transform->get(),"set_position",1,0x0600109b,0x509cb70);
            require(returnClass(write.setter)==actors::type("System","Void") &&
                ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
                    ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(write.setter,0))==actors::type("UnityEngine","Vector3"),
                "visual correction original setter signature differs");
        }
        writes.push_back(write);
    }
    require(ba::read<float>(timing.time,0x18)==timing.now && ba::read<float>(interpolate,0x100)==timing.start &&
        ba::read<int>(simulation,0xac)==s.frame,"visual correction original clock/frame changed after join");
    for(auto& write:writes) {
        auto& entry=s.entries.at(write.entity);
        if(write.mutate) {
            void* args[]={&write.displayed};actors::invoke(write.setter,entry.transform->get(),args);
            storage.output.values[write.index]=write.displayed;
            entry.wrote=write.sampled.offset.x!=0 || write.sampled.offset.y!=0 || write.sampled.offset.z!=0;
        }
        if(traced(entry,s.frame)) {
            require(++s.traceRows<=100000,"visual correction bounded trace exhausted");
            Root boxed(ba::call(entry.transform->get(),"get_position"));
            require(ba::klass(boxed.get())==actors::type("UnityEngine","Vector3"),"visual correction observed position type differs");
            const auto actual=actors::unbox<Vec3>(boxed.get());finite(actual);
            const auto output=storage.output.values[write.index];finite(output);
            if(ba::flag(L"-prediction-visual-input-smoke")) {
                s.frontend={entry.identity,entry.lease,owner.groupGeneration,s.revision,s.publicationUs,
                    now,stamp(),s.frame,timing.alpha,write.raw,write.displayed,write.sampled.offset,
                    entry.actor->get(),entry.transform->get(),simulation,owner.manager->get()};
            }
            std::ostringstream line;line.imbue(std::locale::classic());line<<std::setprecision(17);
            line<<"{\"schema\":1,\"event\":\"visual_pose\",\"world\":"<<s.world<<",\"match\":\""<<s.match<<
                "\",\"frame\":"<<s.frame<<",\"entity\":"<<write.entity<<",\"unit_type\":"<<entry.identity.unitType<<
                ",\"army\":"<<entry.identity.army<<",\"incarnation\":"<<entry.identity.incarnation<<",\"lease\":"<<entry.lease<<
                ",\"sampled_us\":"<<now<<",\"publication_us\":"<<s.publicationUs<<",\"alpha\":"<<timing.alpha<<
                ",\"elapsed\":"<<timing.elapsed<<",\"step\":"<<timing.step<<",\"flipped\":"<<(flipped?"true":"false")<<
                ",\"pulses\":"<<write.sampled.activePulses<<",\"wrote\":"<<(write.mutate?"true":"false")<<
                ",\"from\":"<<xyz(write.from)<<",\"to\":"<<xyz(write.to)<<",\"raw\":"<<xyz(write.raw)<<
                ",\"displayed\":"<<xyz(write.displayed)<<",\"output\":"<<xyz(output)<<",\"transform\":"<<xyz(actual)<<"}";
            ba::log("PREDICTION VISUAL %s",line.str().c_str());
        }
    }
    for(auto it=s.entries.begin();it!=s.entries.end();)
        if(!it->second.correction.activePulses() && !it->second.wrote && !traced(it->second,s.frame))it=s.entries.erase(it);else ++it;
}
static bool frontendObservation(FrontendObservation& result) {
    mainThread();auto& s=state();
    if(!s.frontend.joinedUs || s.failed || s.pending || !s.simulation ||
       s.frontend.frame!=s.frame || s.frontend.revision!=s.revision)return false;
    if(!ba_prediction_movement::ownsPresentation(s.simulation->get()))return false;
    auto& owner=owned(s.simulation->get());const auto& value=s.frontend;
    if(ba::read<int>(s.simulation->get(),0xac)!=value.frame)return false;
    require(value.simulation==s.simulation->get() && value.manager==owner.manager->get() &&
        value.generation==owner.groupGeneration && value.identity.world==owner.world &&
        value.identity.match==owner.match,"visual frontend receipt owner/generation changed");
    const auto found=s.entries.find(value.identity.entity);
    require(found!=s.entries.end() && found->second.actor->get()==value.actor &&
        found->second.transform->get()==value.transform && found->second.lease==value.lease &&
        policy::sameIdentity(found->second.identity,value.identity),"visual frontend receipt lost its rooted entry");
    const auto resident=owner.identities.find(value.actor);
    require(resident!=owner.identities.end() && resident->second.presentationLease==value.lease &&
        resident->second.identity.entityId==value.identity.entity &&
        resident->second.identity.unitType==value.identity.unitType &&
        resident->second.identity.armyId==value.identity.army &&
        resident->second.incarnation==value.identity.incarnation &&
        actors::confirmedToken(owner,resident->second.identity)==value.identity.incarnation &&
        !ba::read<bool>(value.actor,0x160),"visual frontend receipt incarnation/lifetime changed");
    result=value;return true;
}
}
extern "C" __declspec(dllexport) void OfflinePredictionVisualJoin(void* interpolate,void* methodInfo) {
    ba::init();
    // Preserve original call count and exception propagation before observer work.
    ba::native<void(*)(void*,void*)>(0x3c56040)(interpolate,methodInfo);
    if(!ba_prediction_worker::visualCorrectionsEnabled())return;
    // Original scene initialization joins jobs before OfflineInitialUpdate has
    // retained the Unity thread. No visual state can exist yet: every producer
    // and mutation requires that retained thread. Leave these early joins alone;
    // once retained, afterJoin still refuses calls from any different thread.
    if(!ba::initialThread)return;
    try {ba_prediction_visual::afterJoin(interpolate,methodInfo);}
    catch(const std::exception& error) {
        auto& s=ba_prediction_visual::state();s.failed=true;
        ba::log("Prediction visual correction failed: world=%llu match=%s reason=%s retry=0",
            static_cast<unsigned long long>(s.world),s.match.c_str(),error.what());
        ba_prediction_worker::movementFail(error.what());
    }
}
