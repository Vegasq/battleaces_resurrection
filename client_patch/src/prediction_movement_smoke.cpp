// Explicit owned verification only. Include after actor/selection/movement and
// call tick() AFTER ba_client::update in OfflineFrontUpdate. Never an ordinary
// launcher flag. This fixture invokes original managed constructors; it is NOT
// physical UI input, and contains no synthetic native SimProcessMsg/SimFrame.
#include <cmath>
#include <iomanip>
#include <locale>
#include <sstream>
#include "native_quit_gate.hpp"

namespace ba_prediction_movement_smoke {
using ba::Obj;
using ba_local::Root;
namespace actors=ba_prediction_actors;
namespace selection=ba_prediction_selection;
namespace worker=ba_prediction_worker;
struct Vec3 {float x=0,y=0,z=0;};
static_assert(sizeof(Vec3)==12,"original Unity Vector3 ABI differs");
struct MotionSample {Vec3 point{};uint64_t sampledUs=0;};
struct State {
    uint64_t world=0,incarnation=0;
    std::string match;
    std::string actionSha;
    uint32_t entity=0,unitType=0;
    bool attempted=false,failed=false;
    bool batchSeen=false,authoritySeen=false;
    unsigned samples=0;
    unsigned turnsIssued=0;
    std::array<std::string,2> turnHashes{};
    std::array<ba_native_quit_gate::Wait,2> turnGateWaits{};
    Vec3 activeTarget{};
    std::deque<MotionSample> motion;
    ULONGLONG lastSample=0,createdTick=0;
    std::unique_ptr<Root> actor;
};
static State& state(){static State* lifetime=new State;return *lifetime;}
static void require(bool value,const char* why){actors::require(value,why);}
static bool enabled(){return ba::flag(L"-prediction-movement-smoke") || ba::flag(L"-prediction-server-ai-move-smoke");}
static int moveDistance() {
    const auto text=ba::argument(L"-prediction-movement-smoke-distance=","8");
    require(text=="8"||text=="48","movement feel distance must be8or48");
    return text=="48"?48:8;
}
static const std::wstring& transitionGateDirectory() {
    static const auto directory=[]() {
        std::wstring path;
        if(!ba_command_line::value(ba::arguments(),L"-prediction-movement-smoke-transition-gates=",path))return path;
        require(path.size()>3&&path.size()<30000&&path[1]==L':'&&path[2]==L'\\',
            "movement turn gates require an absolute local directory");
        while(path.size()>3&&path.back()==L'\\')path.pop_back();
        wchar_t full[32768];const DWORD length=GetFullPathNameW(path.c_str(),32768,full,nullptr);
        require(length&&length<32768&&path==full,"movement turn gate directory is not canonical");
        ba_native_settings::Handle pin(CreateFileW(path.c_str(),FILE_LIST_DIRECTORY|FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ|FILE_SHARE_WRITE,nullptr,OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS|FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
        require(pin.value!=INVALID_HANDLE_VALUE,"movement turn gate directory is unavailable");
        ba_native_settings::exactDirectory(pin.value,path);
        return path;
    }();
    return directory;
}
static bool transitionGate(unsigned ordinal) {
    const auto& directory=transitionGateDirectory();if(directory.empty())return false;
    auto& s=state();
    require((ordinal==2||ordinal==3)&&s.world&&s.incarnation&&s.match.size()==32&&
        s.match.find_first_not_of("0123456789abcdef")==std::string::npos,
        "movement turn gate binding is invalid");
    const auto filename=s.match+"-"+std::to_string(s.world)+"-turn"+std::to_string(ordinal)+".ready";
    const auto path=directory+L"\\"+std::wstring(filename.begin(),filename.end());
    auto& wait=s.turnGateWaits[ordinal-2];
    ba_native_settings::Handle file(CreateFileW(path.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,
        FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
    if(file.value==INVALID_HANDLE_VALUE) {
        const DWORD error=GetLastError();const auto result=wait.failed(error,GetTickCount64());
        if(result==ba_native_quit_gate::Result::Missing)return false;
        if(result==ba_native_quit_gate::Result::Sharing) {
            if(wait.attempts==1)ba::log("MOVEMENT TURN gate busy: world=%llu ordinal=%u win32=%lu retryBoundMs=%u",
                static_cast<unsigned long long>(s.world),ordinal,error,static_cast<unsigned>(wait.MaxWaitMs));
            return false;
        }
        ba::log("MOVEMENT TURN gate open refused: world=%llu ordinal=%u win32=%lu retryExpired=%d retryBoundMs=%u",
            static_cast<unsigned long long>(s.world),ordinal,error,result==ba_native_quit_gate::Result::Expired?1:0,
            static_cast<unsigned>(wait.MaxWaitMs));
        throw std::runtime_error("movement turn gate cannot be read; win32="+std::to_string(error));
    }
    ba_native_settings::ordinary(file.value);
    const auto expected=std::string("BA_MOVEMENT_TURN_V1 ")+s.match+" "+std::to_string(s.world)+" "+
        std::to_string(s.entity)+" "+std::to_string(s.unitType)+" "+std::to_string(s.incarnation)+" "+
        std::to_string(ordinal)+"\n";
    LARGE_INTEGER size{};
    require(expected.size()<256&&GetFileSizeEx(file.value,&size)&&size.QuadPart==static_cast<LONGLONG>(expected.size()),
        "movement turn gate length differs");
    std::array<char,256> bytes{};DWORD read=0;
    require(ReadFile(file.value,bytes.data(),static_cast<DWORD>(expected.size()),&read,nullptr)&&
        read==expected.size()&&!memcmp(bytes.data(),expected.data(),expected.size()),
        "movement turn gate generation/actor/ordinal differs");
    const auto now=GetTickCount64();require(wait.ready(now),"movement turn gate sharing retry exceeded 1000ms");
    if(wait.active)ba::log("MOVEMENT TURN gate busy settled: world=%llu ordinal=%u attempts=%u elapsedMs=%llu strictReader=1",
        static_cast<unsigned long long>(s.world),ordinal,static_cast<unsigned>(wait.attempts),
        static_cast<unsigned long long>(wait.elapsed(now)));
    wait.clear();
    return true; // Immutable provenance; state consumes it without deleting it.
}
static void reset(){state()=State{};} // Observer GC roots only, on retained main thread.
static void failed(const char* why) noexcept {
    state().failed=true;ba::log("Movement feel smoke failed: reason=%s scriptedOriginalCtor=1 physicalUI=0",why);
    worker::movementFail(why);
}
static void finite(const Vec3& point) {
    require(std::isfinite(point.x)&&std::isfinite(point.y)&&std::isfinite(point.z)&&
        std::fabs(point.x)<2147483648.0f&&std::fabs(point.y)<2147483648.0f&&std::fabs(point.z)<2147483648.0f,
        "movement smoke point outside original Q32.32 range");
}
static std::string common(const char* event,ULONGLONG tick,unsigned moveId=1) {
    const auto& s=state();
    std::ostringstream out;out.imbue(std::locale::classic());
    out<<"{\"schema\":1,\"event\":\""<<event<<"\",\"match\":\""<<s.match<<
        "\",\"world\":"<<s.world<<",\"entity\":"<<s.entity<<",\"unit_type\":"<<s.unitType<<",\"incarnation\":"<<s.incarnation<<
        ",\"move_id\":"<<moveId<<",\"tick_ms\":"<<tick;
    return out.str();
}
static std::string pointJson(const Vec3& point) {
    finite(point);std::ostringstream out;out.imbue(std::locale::classic());out<<std::setprecision(9);
    out<<'['<<point.x<<','<<point.y<<','<<point.z<<']';return out.str();
}
static void emitTransform(actors::State& owner,const Vec3& point,ULONGLONG tick,bool baseline) {
    // QPC resolves pose intervals; the separate GetTickCount64 correlation
    // clock can quantize Windows samples by roughly sixteen milliseconds.
    uint64_t sampledUs=0;
    require(ba_frame_timing::timestampMicros(sampledUs),"movement pose QPC sampling failed");
    const auto& s=state();
    require(owner.simulation && ba::initialThread && GetCurrentThreadId()==ba::initialThread &&
        owner.thread==GetCurrentThreadId() && owner.world==s.world && owner.match==s.match &&
        owner.world==worker::movementWorldId() && owner.match==worker::movementMatchId(),
        "movement pose counters lost their owned simulation/thread");
    Obj simulation=owner.simulation->get();require(simulation,"movement pose simulation root missing");
    const int presented=ba::read<int>(simulation,0xac),completed=ba::read<int>(simulation,0xa8);
    require(presented>=-1&&completed>=-1,"movement pose native frame counters are invalid");
    if(!transitionGateDirectory().empty()) {
        auto& motion=state().motion;
        require(motion.empty()||sampledUs>motion.back().sampledUs,"movement turn pose clock is not increasing");
        if(motion.size()==64)motion.pop_front();
        motion.push_back(MotionSample{point,sampledUs});
    }
    const auto text=common("transform",tick)+",\"source\":\"UnityEngine.Transform.get_position\",\"position\":"+
        pointJson(point)+",\"sampled_us\":"+std::to_string(sampledUs)+
        ",\"baseline\":"+(baseline?"true":"false")+",\"jobsJoined\":true,"+
        "\"presented_frame\":"+std::to_string(presented)+",\"completed_frame\":"+std::to_string(completed)+"}";
    ba::log("MOVEMENT FEEL %s",text.c_str());
}
static Obj allocate(const char* name) {
    Obj klass=actors::type("Uncapped",name);
    ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(klass);
    Obj result=ba::api<Obj(*)(Obj)>("il2cpp_object_new")(klass);
    require(result,"movement smoke managed allocation failed");return result;
}
static void checkValue(Obj klass,int32_t expected,const char* why) {
    uint32_t alignment=0;
    require(klass&&ba::api<bool(*)(Obj)>("il2cpp_class_is_valuetype")(klass)&&
        ba::api<int32_t(*)(Obj,uint32_t*)>("il2cpp_class_value_size")(klass,&alignment)==expected,why);
}
static Obj parameterClass(Obj method,unsigned index) {
    return ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(
        ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(method,index));
}
static int32_t normalPerspective(Obj constructor) {
    // Exact original ctor's parameter2, NOT a guessed enum value/orientation.
    Obj klass=parameterClass(constructor,2);checkValue(klass,4,"movement smoke Perspective ABI differs");
    require(ba::api<bool(*)(Obj)>("il2cpp_class_is_enum")(klass)&&
        !strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(klass),"Perspective"),
        "movement smoke original Perspective enum missing");
    Obj normal=ba::api<Obj(*)(Obj,const char*)>("il2cpp_class_get_field_from_name")(klass,"Normal");
    require(normal,"movement smoke Normal enum literal missing");
    const uint32_t flags=ba::api<uint32_t(*)(Obj)>("il2cpp_field_get_flags")(normal);
    require((flags&0x50u)==0x50u,"movement smoke Normal field is not a static literal");
    int32_t value=0;ba::api<void(*)(Obj,void*)>("il2cpp_field_static_get_value")(normal,&value);
    return value;
}
static Obj interpolation(actors::State& owner) {
    require(owner.manager&&owner.simulation,"movement smoke actor owner roots missing");
    Obj manager=owner.manager->get(),simulation=owner.simulation->get();
    actors::field(manager,"UnitsReleased",0x88);
    Root callback(ba::read<Obj>(manager,0x88));require(callback.get(),"movement smoke release subscribers missing");
    Root listeners(ba::call(callback.get(),"GetInvocationList"));
    require(listeners.get(),"movement smoke release invocation list missing");
    const auto count=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(listeners.get());
    require(count>0&&count<=128,"movement smoke release invocation list bound");
    Obj result=nullptr;
    for(uintptr_t i=0;i<count;++i) {
        Root entry(ba::read<Obj>(listeners.get(),0x20+i*sizeof(Obj)));
        Root target(ba::call(entry.get(),"get_Target"));
        if(!target.get()||ba::klass(target.get())!=actors::type("Uncapped.Systems","UnitInterpolationSystem"))continue;
        actors::field(target.get(),"_simulation",0xe0);actors::field(target.get(),"_unitManager",0xe8);
        require(ba::read<Obj>(target.get(),0xe0)==simulation&&ba::read<Obj>(target.get(),0xe8)==manager,
            "movement smoke interpolation target belongs to another world/manager");
        Obj method=actors::method(target.get(),"UnitManager_UnitsReleased",2,0x0600254a,0x3c54ac0);
        // Compare the delegate's native MethodInfo only with recovered metadata;
        // never dereference an arbitrary delegate method address.
        require(ba::get<uintptr_t>(entry.get(),"method")==reinterpret_cast<uintptr_t>(method),
            "movement smoke interpolation release callback method differs");
        require(!result||result==target.get(),"movement smoke multiple interpolation owners");
        result=target.get();
    }
    require(result,"movement smoke current interpolation subscriber not found");return result;
}
static Vec3 actualPosition(actors::State& owner,Obj actor) {
    Root interpolate(interpolation(owner));
    Obj join=actors::method(interpolate.get(),"EnsureJobsComplete",0,0x0600254d,0x3c56040);
    actors::invoke(join,interpolate.get()); // Completes original jobs; schedules/consumes no SimFrame.
    Root transform(ba::call(actor,"get_transform"));actors::classIs(transform.get(),"UnityEngine","Transform");
    Root boxed(ba::call(transform.get(),"get_position"));
    checkValue(ba::klass(boxed.get()),12,"movement smoke returned Vector3 size differs");
    require(ba::klass(boxed.get())==actors::type("UnityEngine","Vector3"),"movement smoke get_position did not return Vector3");
    const Vec3 point=actors::unbox<Vec3>(boxed.get());finite(point);return point;
}
static std::string actionHash(Obj command) {
    // Diagnostic-only original ToProto over immutable typed arrays. The normal
    // queued command still goes through its ordinary ToProto/drain/67/72 route.
    // The verifier must compare this digest with THAT independently captured
    // actual batch; this prequeue conversion alone is no delivery proof.
    Root action(ba_local::toProto(command));
    const auto raw=ba_lan::serialize(action.get());require(!raw.empty(),"movement smoke original ToProto was empty");
    const auto hash=ba_lan::sha(raw);char text[65]{};
    for(size_t i=0;i<32;++i)sprintf_s(text+i*2,3,"%02x",hash[i]);return text;
}
static void enqueueMove(selection::Context& context,Obj actor,const Vec3& origin) {
    auto& s=state();s.attempted=true;
    const auto known=context.state.identities.find(actor);
    require(known!=context.state.identities.end()&&known->second.incarnation&&context.admitted(actor),
        "movement smoke chosen actor is not currently confirmed");
    s.entity=known->second.identity.entityId;s.incarnation=known->second.incarnation;
    s.unitType=known->second.identity.unitType;
    require(ba_lan_smoke::plan.ready&&s.unitType==ba_lan_smoke::plan.unit&&
        known->second.identity.armyId==static_cast<uint32_t>(ba::lanSlot()),
        "movement smoke source is not the own confirmed opening unit");
    s.actor=std::make_unique<Root>(actor);
    emitTransform(context.state,origin,GetTickCount64(),true);
    const float travel=static_cast<float>(moveDistance());
    Vec3 target=origin;const float distance=std::sqrt(origin.x*origin.x+origin.z*origin.z);
    if(distance>.1f){target.x-=travel*origin.x/distance;target.z-=travel*origin.z/distance;}
    else target.x+=travel;
    finite(target);
    s.activeTarget=target;
    Obj uintClass=actors::type("System","UInt32");checkValue(uintClass,4,"movement smoke uint32 ABI differs");
    Root ids(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(uintClass,1));require(ids.get(),"movement smoke source array allocation failed");
    std::memcpy(static_cast<unsigned char*>(ids.get())+0x20,&s.entity,sizeof(s.entity));
    Root group(allocate("ExecuteCommandEntityTypeData"));
    Obj groupCtor=actors::method(group.get(),".ctor",3,0x060000f3,0x34b3080);
    checkValue(parameterClass(groupCtor,2),4,"movement smoke IntKey<UnitType> ABI differs");
    uint32_t ability=12,unitType=s.unitType;void* groupArgs[]={ids.get(),&ability,&unitType};
    actors::invoke(groupCtor,group.get(),groupArgs);
    actors::field(group.get(),"<Casters>k__BackingField",0x10);
    actors::field(group.get(),"<AbilityId>k__BackingField",0x18);
    actors::field(group.get(),"<UnitType>k__BackingField",0x1c);
    require(ba::read<Obj>(group.get(),0x10)==ids.get()&&ba::read<uint32_t>(group.get(),0x18)==12&&
        ba::read<uint32_t>(group.get(),0x1c)==s.unitType,"movement smoke original group constructor differs");
    Root groups(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(ba::klass(group.get()),1));
    require(groups.get(),"movement smoke group array allocation failed");
    auto* slot=reinterpret_cast<Obj*>(static_cast<unsigned char*>(groups.get())+0x20);
    ba::api<void(*)(Obj,Obj*,Obj)>("il2cpp_gc_wbarrier_set_field")(groups.get(),slot,group.get());
    require(*slot==group.get(),"movement smoke typed group array write barrier did not publish reference");
    Root command(allocate("ExecuteTargetGroundCommand"));
    Obj ctor=actors::method(command.get(),".ctor",4,0x060000e6,0x37ae080);
    require(parameterClass(ctor,1)==actors::type("UnityEngine","Vector3"),"movement smoke original target parameter differs");
    int32_t perspective=normalPerspective(ctor);bool queued=false;
    void* args[]={groups.get(),&target,&perspective,&queued};actors::invoke(ctor,command.get(),args);
    s.createdTick=GetTickCount64();
    actors::field(command.get(),"<CastersByType>k__BackingField",0x10);
    actors::field(command.get(),"<Position>k__BackingField",0x18);
    actors::field(command.get(),"<Queued>k__BackingField",0x24);actors::field(command.get(),"_mapPerspective",0x28);
    const Vec3 stored=ba::read<Vec3>(command.get(),0x18);
    require(ba::read<Obj>(command.get(),0x10)==groups.get()&&!ba::read<bool>(command.get(),0x24)&&
        ba::read<int32_t>(command.get(),0x28)==perspective&&!memcmp(&stored,&target,sizeof(target)),
        "movement smoke original ground command constructor differs");
    const auto hash=actionHash(command.get());
    s.actionSha=hash;
    // All constructor arguments are immutable independent arrays. Admission is
    // checked again immediately before the normal queue acquires the command.
    require(context.admitted(actor),"movement smoke source changed before original enqueue");
    Obj server=ba_local::server();actors::classIs(server,"Uncapped","GameServerIntegration");
    require(ba::read<Obj>(server,0x140)==context.state.simulation->get(),"movement smoke server/simulation owner differs");
    Obj queue=ba::read<Obj>(server,0x180);const int before=ba_local::count(queue);
    Obj enqueue=actors::method(server,"EnqueueInputCommand",1,0x06001115,0x3e53530);
    void* input[]={command.get()};actors::invoke(enqueue,server,input);
    require(ba_local::count(queue)==before+1,"movement smoke original enqueue did not add exactly one ICommand");
    const auto text=common("command_created",s.createdTick)+
        ",\"original_callback\":\"Uncapped.ExecuteTargetGroundCommand..ctor\",\"ability\":12,\"target\":"+
        pointJson(target)+",\"action_sha256\":\""+hash+"\",\"scriptedOriginalCtor\":true,\"physicalUI\":false,"+
        "\"queueDelta\":1,\"perspectiveLiteral\":\"Normal\"}";
    ba::log("MOVEMENT FEEL %s",text.c_str());
}
static void enqueueTurn(selection::Context& context,const Vec3& origin,unsigned ordinal,int presented,int completed) {
    auto& s=state();
    require(!transitionGateDirectory().empty()&&moveDistance()==48&&ba::lanSlot()==0&&
        ba::argument(L"-prediction-movement-smoke-start-frame=","440")=="440"&&
        ordinal==s.turnsIssued+2&&ordinal<=3&&presented<650&&completed<650&&s.batchSeen&&s.authoritySeen,
        "movement turn is late/out of order/outside the explicit subject fixture");
    require(s.actor&&s.motion.size()>=2,"movement turn has no retained actor/motion history");
    Obj actor=s.actor->get();
    const auto admitted=[&]() {
        const auto known=context.state.identities.find(actor);
        return known!=context.state.identities.end()&&known->second.incarnation==s.incarnation&&
            known->second.identity.entityId==s.entity&&known->second.identity.unitType==s.unitType&&
            known->second.identity.armyId==static_cast<uint32_t>(ba::lanSlot())&&context.admitted(actor);
    };
    require(admitted(),"movement turn confirmed actor identity changed");
    const auto current=s.motion.back();
    require(!memcmp(&current.point,&origin,sizeof(origin)),"movement turn origin is not the current actual pose");
    MotionSample prior{};bool found=false;
    for(auto it=s.motion.rbegin()+1;it!=s.motion.rend();++it) {
        if(current.sampledUs-it->sampledUs<100000)continue;
        prior=*it;found=true;break;
    }
    require(found&&current.sampledUs-prior.sampledUs<=500000,"movement turn lacks recent100ms actual motion");
    const float dx=origin.x-prior.point.x,dz=origin.z-prior.point.z;
    const float length=std::sqrt(dx*dx+dz*dz);
    const float remainingX=s.activeTarget.x-origin.x,remainingZ=s.activeTarget.z-origin.z;
    require(length>.05f&&remainingX*remainingX+remainingZ*remainingZ>.0625f,
        "movement turn requires actual ongoing unfinished travel");
    const float travel=ordinal==2?48.0f:32.0f;
    Vec3 target=origin;target.x-=travel*dx/length;target.z-=travel*dz/length;finite(target);

    // Same recovered original ABI as order1, with NEW independent immutable
    // caster/group arrays. Never clear a shared selection or fabricate input.
    Obj uintClass=actors::type("System","UInt32");checkValue(uintClass,4,"movement turn uint32 ABI differs");
    Root ids(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(uintClass,1));
    require(ids.get(),"movement turn source array allocation failed");
    std::memcpy(static_cast<unsigned char*>(ids.get())+0x20,&s.entity,sizeof(s.entity));
    Root group(allocate("ExecuteCommandEntityTypeData"));
    Obj groupCtor=actors::method(group.get(),".ctor",3,0x060000f3,0x34b3080);
    checkValue(parameterClass(groupCtor,2),4,"movement turn IntKey<UnitType> ABI differs");
    uint32_t ability=12,unitType=s.unitType;void* groupArgs[]={ids.get(),&ability,&unitType};
    actors::invoke(groupCtor,group.get(),groupArgs);
    actors::field(group.get(),"<Casters>k__BackingField",0x10);
    actors::field(group.get(),"<AbilityId>k__BackingField",0x18);
    actors::field(group.get(),"<UnitType>k__BackingField",0x1c);
    require(ba::read<Obj>(group.get(),0x10)==ids.get()&&ba::read<uint32_t>(group.get(),0x18)==12&&
        ba::read<uint32_t>(group.get(),0x1c)==s.unitType,"movement turn original group constructor differs");
    Root groups(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(ba::klass(group.get()),1));
    require(groups.get(),"movement turn group array allocation failed");
    auto* slot=reinterpret_cast<Obj*>(static_cast<unsigned char*>(groups.get())+0x20);
    ba::api<void(*)(Obj,Obj*,Obj)>("il2cpp_gc_wbarrier_set_field")(groups.get(),slot,group.get());
    require(*slot==group.get(),"movement turn typed array reference was not published");
    Root command(allocate("ExecuteTargetGroundCommand"));
    Obj ctor=actors::method(command.get(),".ctor",4,0x060000e6,0x37ae080);
    require(parameterClass(ctor,1)==actors::type("UnityEngine","Vector3"),"movement turn target parameter differs");
    int32_t perspective=normalPerspective(ctor);bool queued=false;
    void* args[]={groups.get(),&target,&perspective,&queued};actors::invoke(ctor,command.get(),args);
    const auto createdTick=GetTickCount64();
    actors::field(command.get(),"<CastersByType>k__BackingField",0x10);
    actors::field(command.get(),"<Position>k__BackingField",0x18);
    actors::field(command.get(),"<Queued>k__BackingField",0x24);actors::field(command.get(),"_mapPerspective",0x28);
    const Vec3 stored=ba::read<Vec3>(command.get(),0x18);
    require(ba::read<Obj>(command.get(),0x10)==groups.get()&&!ba::read<bool>(command.get(),0x24)&&
        ba::read<int32_t>(command.get(),0x28)==perspective&&!memcmp(&stored,&target,sizeof(target)),
        "movement turn original ground constructor differs");
    const auto hash=actionHash(command.get());
    require(hash!=s.actionSha&&(s.turnsIssued==0||hash!=s.turnHashes[0]),
        "movement turn must have a distinct original action hash");
    require(admitted(),"movement turn source changed before original enqueue");
    Obj server=ba_local::server();actors::classIs(server,"Uncapped","GameServerIntegration");
    require(ba::read<Obj>(server,0x140)==context.state.simulation->get(),"movement turn server/simulation owner differs");
    const auto& movement=ba_prediction_movement::state;
    require(movement.world==s.world&&movement.match==s.match&&movement.owner==GetCurrentThreadId()&&
        movement.physicalNext>=1&&!movement.failed,"movement turn physical owner differs");
    const auto physical=movement.physicalNext-1;
    Obj queue=ba::read<Obj>(server,0x180);const int before=ba_local::count(queue);
    Obj enqueue=actors::method(server,"EnqueueInputCommand",1,0x06001115,0x3e53530);
    uint64_t enqueueUs=0;
    require(ba_frame_timing::timestampMicros(enqueueUs)&&enqueueUs>=current.sampledUs,"movement turn enqueue QPC failed");
    void* input[]={command.get()};actors::invoke(enqueue,server,input);
    require(ba_local::count(queue)==before+1,"movement turn original enqueue did not add exactly one ICommand");
    s.turnHashes[s.turnsIssued]=hash;++s.turnsIssued;s.activeTarget=target;
    const auto text=common("command_created",createdTick,ordinal)+",\"ordinal\":"+std::to_string(ordinal)+
        ",\"sampled_us\":"+std::to_string(current.sampledUs)+",\"enqueue_sampled_us\":"+std::to_string(enqueueUs)+
        ",\"physical_frame\":"+std::to_string(physical)+",\"presented_frame\":"+std::to_string(presented)+
        ",\"completed_frame\":"+std::to_string(completed)+",\"origin\":"+pointJson(origin)+",\"target\":"+pointJson(target)+
        ",\"motion_from\":"+pointJson(prior.point)+",\"motion_from_sampled_us\":"+std::to_string(prior.sampledUs)+
        ",\"ability\":12,\"action_sha256\":\""+hash+"\",\"original_callback\":\"Uncapped.ExecuteTargetGroundCommand..ctor\","+
        "\"originalCtor\":true,\"physicalUI\":false,\"queueDelta\":1}";
    ba::log("MOVEMENT TURN %s",text.c_str());
}
static void tick() {
    if(!enabled())return;
    try {
        require(ba::initialThread&&GetCurrentThreadId()==ba::initialThread,"movement feel smoke requires retained Unity main thread");
        const auto world=worker::movementWorldId();const auto& match=worker::movementMatchId();
        if(!worker::movementEnabled()||!world||match.empty()){reset();return;}
        auto& s=state();if(s.world!=world||s.match!=match){reset();s.world=world;s.match=match;}
        if(s.failed)return;
        auto& owner=actors::state();
        if(owner.world!=world||owner.match!=match||!owner.manager||!owner.simulation)return; // Before first publication.
        require(!owner.failed&&owner.thread==GetCurrentThreadId(),"movement feel actor owner is failed/foreign");
        if(ba_lan::matchEnded)return;
        const bool serverAiMove=ba::flag(L"-prediction-server-ai-move-smoke");
        require(ba::unified()&&ba::community()&&ba::dedicated()&&ba::lan()&&ba_lan::originalCommandScheduling()&&
            ba_lan::running && (serverAiMove ? (ba_lan::publicMatch && ba_prediction_movement::state.publicRoute &&
                ba::flag(L"-prediction-server-ai-observe")) : !ba_lan::publicMatch),
            "movement feel smoke requires its negotiated Custom or explicit server AI match");
        const auto slotText=ba::argument(L"-prediction-movement-smoke-slot=","0");
        require(slotText=="0"||slotText=="1","movement feel smoke slot must be0or1");
        const int captureEnd=moveDistance()==48?650:600;
        if(ba::lanSlot()!=slotText[0]-'0')return;
        const auto startText=ba::argument(L"-prediction-movement-smoke-start-frame=","440");
        require(startText=="440"||startText=="460","movement feel start frame must be440or460");
        require(transitionGateDirectory().empty()||(slotText=="0"&&startText=="440"&&moveDistance()==48),
            "movement turn gates require the48m slot0/frame440 subject");
        const int startFrame=startText=="440"?440:460;
        Obj simulation=owner.simulation->get();
        const int completed=ba::read<int>(simulation,0xa8),presented=ba::read<int>(simulation,0xac);
        if(completed<startFrame-20||presented<startFrame-20)return;
        // This pose episode ends before the separate normal Concede700
        // lifecycle fixture legitimately retires the tracked army's units.
        if(s.attempted && (completed>=captureEnd || presented>=captureEnd)) {
            require(transitionGateDirectory().empty()||s.turnsIssued==2,"movement turn gate arrived too late/missing before capture end");
            return;
        }
        selection::Context context(selection::currentSelector());
        require(context.state.world==s.world&&context.state.match==s.match,"movement feel context changed generation");
        if(!s.attempted) {
            for(const auto& entry:context.live) {
                const auto identity=owner.identities.find(entry.second);
                if(identity==owner.identities.end()||!ba_lan_smoke::plan.ready||
                   identity->second.identity.unitType!=ba_lan_smoke::plan.unit||!context.admitted(entry.second))continue;
                const auto now=GetTickCount64();if(s.lastSample&&now-s.lastSample<15)return;
                s.entity=identity->second.identity.entityId;s.incarnation=identity->second.incarnation;
                s.unitType=identity->second.identity.unitType;
                const auto point=actualPosition(owner,entry.second);s.lastSample=GetTickCount64();
                emitTransform(owner,point,s.lastSample,true);
                if(completed>=startFrame&&presented>=startFrame)enqueueMove(context,entry.second,point);
                return;
            }
            require(presented<600,"movement feel opening unit was not confirmed by frame600");return;
        }
        require(s.actor&&context.admitted(s.actor->get())&&
            owner.identities.at(s.actor->get()).incarnation==s.incarnation,"movement feel tracked actor was replaced/unconfirmed; no rebinding");
        const auto now=GetTickCount64();if(s.lastSample&&now-s.lastSample<15)return;
        require(s.samples<2048,"movement feel bounded transform sample count reached");
        const auto point=actualPosition(owner,s.actor->get());s.lastSample=GetTickCount64();++s.samples;
        emitTransform(owner,point,s.lastSample,false);
        if(!transitionGateDirectory().empty()&&s.turnsIssued<2&&transitionGate(s.turnsIssued+2))
            enqueueTurn(context,point,s.turnsIssued+2,presented,completed);
    } catch(const std::exception& error){failed(error.what());}
    catch(...){failed("unknown movement feel smoke exception");}
}
static std::string digest(const std::vector<uint8_t>& raw) {
    const auto hash=ba_lan::sha(raw);char text[65]{};
    for(size_t i=0;i<32;++i)sprintf_s(text+i*2,3,"%02x",hash[i]);return text;
}
static unsigned matchingActions(Obj actions) {
    const int count=ba_local::count(actions);require(count>=0&&count<=256,"movement smoke action count exceeds limit");
    unsigned matches=0;
    for(int index=0;index<count;++index) {
        void* args[]={&index};Root action(ba::call(actions,"get_Item",1,args));
        if(digest(ba_lan::serialize(action.get()))==state().actionSha)++matches;
    }
    return matches;
}
static bool bound() {
    const auto& s=state();
    return enabled()&&s.attempted&&!s.failed&&!s.actionSha.empty()&&s.world==worker::movementWorldId()&&
        s.match==worker::movementMatchId();
}
static void registered(uint64_t sequence,int assigned,const std::vector<uint8_t>& body) {
    if(!bound())return;
    Root player(ba_lan::parse("InputActionsByPlayer",body));
    const auto count=matchingActions(ba::get<Obj>(player.get(),"actions_"));if(!count)return;
    auto& s=state();require(count==1&&!s.batchSeen,"scripted Move was registered more than once");s.batchSeen=true;
    const auto text=common("batch_registered",GetTickCount64())+",\"sequence\":"+std::to_string(sequence)+
        ",\"speculative_frame\":"+std::to_string(assigned)+",\"body_sha256\":\""+digest(body)+
        "\",\"action_sha256\":\""+s.actionSha+"\",\"workerOp\":67}";
    ba::log("MOVEMENT FEEL %s",text.c_str());
}
static void authoritative(const std::vector<uint8_t>& raw,const std::string& wireSha) {
    // The dedicated mobile fixture needs the actual accepted65 receipt too.
    // Generic command generation and FEEL state remain gated by enabled/bound.
    const bool serverAiObserve=ba::flag(L"-prediction-server-ai-observe");
    if(!enabled()&&!ba::flag(L"-prediction-mobile-correction-smoke")&&!serverAiObserve)return;
    require(!serverAiObserve || ba_prediction_movement::state.publicRoute,
        "server AI authority observation lost its actual public assignment");
    Root frame(ba_lan::parse("InputActions",raw));Obj players=ba::get<Obj>(frame.get(),"playerInputActions_");
    const int count=ba_local::count(players);require(count>=0&&count<=2,"movement smoke canonical participant count differs");
    int totalActions=0;
    for(int index=0;index<count;++index) {
        void* args[]={&index};Root player(ba::call(players,"get_Item",1,args));
        totalActions+=ba_local::count(ba::get<Obj>(player.get(),"actions_"));
    }
    if(totalActions || serverAiObserve) {
        require(wireSha.size()==64&&wireSha.find_first_not_of("0123456789abcdef")==std::string::npos,
            "movement smoke accepted authority lacks its actual wire fingerprint");
        // Actual accepted65, still under the same native bridge gate. This
        // generic record also witnesses the other human's unknown Move.
        const auto text=std::string("{\"schema\":1,\"world\":")+std::to_string(worker::movementWorldId())+
            ",\"match\":\""+worker::movementMatchId()+"\",\"frame\":"+
            std::to_string(ba::get<int>(frame.get(),"gameFrame_"))+",\"tick_ms\":"+
            std::to_string(GetTickCount64())+",\"canonical_sha256\":\""+digest(raw)+
            "\",\"wire_sha256\":\""+wireSha+"\"}";
        ba::log("MOVEMENT AUTHORITY %s",text.c_str());
    }
    if(!bound())return;
    unsigned matches=0;
    for(int index=0;index<count;++index) {
        void* args[]={&index};Root player(ba::call(players,"get_Item",1,args));
        Obj handle=ba::get<Obj>(player.get(),"playerHandle_");
        Obj named=handle?ba::get<Obj>(handle,"playerHandleWithName_"):nullptr;
        Obj identity=named?ba::get<Obj>(named,"playerHandle_"):nullptr;
        require(identity,"movement smoke canonical player identity missing");
        if(ba::get<uint64_t>(identity,"steamId_")!=static_cast<uint64_t>(ba::lanSlot()+1))continue;
        matches+=matchingActions(ba::get<Obj>(player.get(),"actions_"));
    }
    if(!matches)return;
    auto& s=state();require(matches==1&&s.batchSeen&&!s.authoritySeen,"scripted Move canonical receipt duplicated/unbound");s.authoritySeen=true;
    const auto text=common("authority_received",GetTickCount64())+",\"frame\":"+
        std::to_string(ba::get<int>(frame.get(),"gameFrame_"))+",\"action_sha256\":\""+s.actionSha+"\",\"workerOp\":65}";
    ba::log("MOVEMENT FEEL %s",text.c_str());
}
// Corrected/continuation state comes from the explicit worker observer's
// quiescent original native snapshots, joined by opaque world/frame identity.
}
