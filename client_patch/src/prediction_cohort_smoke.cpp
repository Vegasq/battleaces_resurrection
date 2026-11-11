// Explicit RouteA diagnostic; include after prediction_actor_smoke.cpp.
// Original selection/command APIs only. No native writes or extra ToProto.
#include "prediction_cohort_smoke.hpp"
#include <iomanip>
#include <sstream>

namespace ba_prediction_cohort {
namespace actors=ba_prediction_actors;
namespace selection=ba_prediction_selection;
namespace worker=ba_prediction_worker;
namespace base=ba_prediction_actor_smoke::mobile;
namespace original=ba_prediction_movement_smoke;
using ba::Obj;using ba_local::Root;
struct State {
    uint64_t world=0,lastSample=0;std::string match;
    std::set<uint32_t> before;std::vector<uint32_t> ids;std::vector<uint64_t> tokens;
    std::unique_ptr<Root> selector,group,helper,command,action;
    unsigned selectionCalls=0,groupCalls=0,actionIndex=0;
    uint64_t sequence=0,generation=0,enqueuedUs=0;bool prebuild=false,selected=false,queued=false,serialized=false,registered=false,complete=false,failed=false;
};
static State& state(){static auto* s=new State;return *s;}
static void require(bool ok,const char* why){actors::require(ok,why);}
bool enabled(){return ba::flag(L"-prediction-cohort-smoke");}
void requireFlags() {
    if(!enabled())return;
    require(worker::movementEnabled()&&ba::flag(L"-prediction-mobile-correction-smoke")&&
        ba::flag(L"-lan-smoke")&&ba::flag(L"-original-command-scheduling-experimental"),
        "cohort diagnostic requires its explicit mobile/arrival/build fixture");
    for(const auto* flag:{L"-prediction-queued-orders-smoke",L"-prediction-close-formation-smoke",L"-prediction-cohort-survivor-smoke",L"-prediction-movement-smoke",L"-prediction-actor-correction-smoke",L"-prediction-actor-mirror-smoke",
        L"-prediction-expired-click-smoke",L"-prediction-held-click-smoke",L"-prediction-terminal-timeline-smoke",
        L"-prediction-mobile-group-intent-smoke",L"-prediction-mobile-group-user-edits-smoke",L"-prediction-mobile-recovery-stall-smoke",
        L"-prediction-mobile-recall-smoke",L"-prediction-mobile-focus-smoke",L"-prediction-mobile-focus-no-start-smoke",
        L"-prediction-mobile-focus-restart-smoke",L"-prediction-mobile-caster-survey-smoke",L"-prediction-mobile-caster-lifetime-smoke",
        L"-prediction-mobile-ui-cast-smoke",L"-prediction-mobile-held-click-smoke",L"-prediction-mobile-context-move-smoke",
        L"-prediction-mobile-context-hold-smoke",L"-prediction-mobile-original-hold-smoke",L"-prediction-server-ai-observe",
        L"-prediction-server-ai-move-smoke"})require(!ba::flag(flag),"cohort diagnostic overlaps another optional scope");
}
static std::string pointer(Obj value){if(!value)return "null";std::ostringstream out;out<<'"'<<value<<'"';return out.str();}
static bool sameIds(const std::vector<uint32_t>& actual,const std::vector<uint32_t>& expected) {
    return actual.size()==expected.size()&&std::set<uint32_t>(actual.begin(),actual.end())==std::set<uint32_t>(expected.begin(),expected.end());
}
static int frame(actors::State& owner){return ba::read<int>(owner.simulation->get(),0xac);}
static std::string common(const char* event,actors::State& owner,uint64_t sampled=0,ULONGLONG tick=0) {
    auto& s=state();base::owned(owner);std::ostringstream out;out.imbue(std::locale::classic());
    out<<"{\"schema\":1,\"event\":\""<<event<<"\",\"world\":"<<s.world<<",\"match\":\""<<s.match
       <<"\",\"slot\":"<<ba::lanSlot()<<",\"frame\":"<<frame(owner)<<",\"completed_frame\":"<<ba::read<int>(owner.simulation->get(),0xa8)
       <<",\"tick_ms\":"<<(tick?tick:GetTickCount64())<<",\"sampled_us\":"<<(sampled?sampled:base::stamp());return out.str();
}
static uint32_t nativeState(const actors::Current& native,uint32_t id) {
    Root states(ba::call(native.frame.get(),"get_StateBuffer"));require(actors::contains(states.get(),id),"cohort native state missing");
    Obj get=actors::method(states.get(),"get_Item",1,0x0600013d);
    Obj type=ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(ba::api<Obj(*)(Obj)>("il2cpp_method_get_return_type")(get));uint32_t alignment=0;
    require((type==actors::type("System","UInt32")||ba::api<bool(*)(Obj)>("il2cpp_class_is_enum")(type))&&
        ba::api<int32_t(*)(Obj,uint32_t*)>("il2cpp_class_value_size")(type,&alignment)==4,"cohort native state ABI differs");
    void* args[]={&id};Root value(actors::invoke(get,states.get(),args));return actors::unbox<uint32_t>(value.get());
}
struct Member {uint32_t id;uint64_t token,canonical;Obj actor;uint32_t nativeState;bool admitted,initialized;original::Vec3 position;uint64_t sampled;};
static std::vector<Member> census(actors::State& owner,Obj selector,bool poses) {
    selection::Context context(selector);actors::Current native(ba::read<Obj>(owner.simulation->get(),0x148));
    std::vector<Member> result;
    for(const auto& entry:context.live) {
        const auto observed=actors::resident(entry.second);const auto actual=native.identity(entry.first);
        if(observed.armyId!=static_cast<uint32_t>(ba::lanSlot())||observed.unitType!=1||!actual)continue;
        require(actual->armyId==observed.armyId&&actual->unitType==1,"cohort current identity differs from actor");
        actors::field(entry.second,"_componentData",0x158);actors::field(entry.second,"<DeadToTheSim>k__BackingField",0x160);
        Member m{entry.first,base::token(context,entry.second),actors::confirmedToken(owner,observed),entry.second,
            nativeState(native,entry.first),context.admitted(entry.second),
            ba::read<Obj>(entry.second,0x158)!=nullptr&&!ba::read<bool>(entry.second,0x160),{},0};
        if(poses){m.position=original::actualPosition(owner,m.actor);m.sampled=base::stamp();original::finite(m.position);}
        result.push_back(m);require(result.size()<=8,"cohort own Gunbot census exceeds bound");
    }
    return result;
}
static std::string membersJson(const std::vector<Member>& members,bool poses) {
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::boolalpha<<std::setprecision(9)<<'[';
    for(size_t i=0;i<members.size();++i) {
        if(i)out<<',';const auto& m=members[i];out<<"{\"id\":"<<m.id<<",\"unit_type\":1,\"army\":"<<ba::lanSlot()
           <<",\"incarnation\":"<<m.token<<",\"canonical_token\":"<<m.canonical<<",\"actor\":"<<pointer(m.actor)
           <<",\"native_state\":"<<m.nativeState<<",\"admitted\":"<<m.admitted<<",\"initialized\":"<<m.initialized
           <<",\"position\":";
        if(poses)out<<original::pointJson(m.position);else out<<"null";
        out<<",\"position_bits\":";
        if(poses){uint32_t bits[3]{};memcpy(bits,&m.position,sizeof(bits));out<<'['<<bits[0]<<','<<bits[1]<<','<<bits[2]<<']';}else out<<"null";
        out<<",\"position_sampled_us\":"<<(poses?std::to_string(m.sampled):"null")<<",\"jobs_joined\":"<<(poses?"true":"false")<<'}';
    }
    out<<']';return out.str();
}
struct Cache {std::vector<uint32_t> ids,typed;int count;Obj frames;};
static Cache cache(Obj selected) {
    actors::classIs(selected,"Uncapped.Collections","UnitSelectionSet");actors::field(selected,"_simFrames",0x48);
    Cache result{selection::selectionIds(selected),{},0,ba::read<Obj>(selected,0x48)};
    for(uint32_t id:result.ids)require(actors::groupCacheMembership(selected,id),"cohort typed membership missing");
    Root subsets(ba::read<Obj>(selected,0x20));uint32_t type=1;Obj led=nullptr;void* lookupArgs[]={&type,&led};
    Root has(actors::invoke(actors::method(subsets.get(),"TryGetValue",2,0x06002de7),subsets.get(),lookupArgs));Root typed(led);
    require(actors::unbox<bool>(has.get())==bool(typed.get()),"cohort type1 lookup out value differs");
    if(typed.get()){actors::field(typed.get(),"<Entities>k__BackingField",0x10);result.typed=actors::ids(ba::read<Obj>(typed.get(),0x10));}
    Obj get=actors::method(selected,"get_Count",0,0x060025b5,0x3c68f00);Root count(actors::invoke(get,selected));result.count=actors::unbox<int32_t>(count.get());
    require(result.count>=0&&result.count<=8&&selection::selectionIds(selected)==result.ids,"cohort original Count changed raw selection");
    return result;
}
static void idle(actors::State& owner,Obj selector) {
    base::owned(owner);const auto history=ba_prediction_actor_smoke::expired_click::history(selector);
    require(!history.drag&&!ba::read<Obj>(selector,0x100)&&selection::selectionIds(ba::read<Obj>(selector,0x98)).empty()&&
        !ba::read<bool>(selector,0x16c)&&!ba::read<bool>(selector,0x16d)&&base::pending(owner)==0,
        "cohort original input/command state is not idle");
}
static void choose(actors::State& owner,Obj selector,const std::vector<Member>& members) {
    auto& s=state();std::vector<policy::Member> proof;
    for(const auto& m:members)proof.push_back({m.id,1,static_cast<uint32_t>(ba::lanSlot()),m.token,m.canonical,m.nativeState==0,m.initialized,m.admitted});
    s.ids=policy::choose(s.before,proof,static_cast<unsigned>(ba::lanSlot()));
    s.generation=owner.groupGeneration;
    for(const auto& m:members)s.tokens.push_back(m.token);
    if(ba::lanSlot()==0){s.selected=true;return;}
    idle(owner,selector);Obj begin=actors::method(selector,"BeginSelectionChange",1,0x06002237,0x3bf5af0);
    Obj clear=actors::method(selector,"ClearSelection",0,0x06002217,0x3bf2680),add=actors::method(selector,"AddToSelection",1,0x06002214,0x3bf2510);
    actors::field(selector,"_selectionChangeHelper",0x80);Root helper(ba::read<Obj>(selector,0x80));
    actors::field(helper.get(),"<IsSuspended>k__BackingField",0x10);require(!ba::read<bool>(helper.get(),0x10),"cohort selection scope already active");
    Obj dispose=actors::method(helper.get(),"Dispose",0,0x060000cd,0x3b02160);bool disposed=false;
    auto close=[&](){if(!disposed&&ba::read<bool>(helper.get(),0x10)){disposed=true;actors::invoke(dispose,helper.get());}};
    // The earlier mobile fixture deliberately retains group focus. As with its
    // fresh selection at180, use the original programmatic scope: a user-
    // initiated scope is refused while that focus is active (retained Actual18).
    try {bool player=false;void* args[]={&player};
        require(actors::invoke(begin,selector,args)==helper.get()&&ba::read<bool>(helper.get(),0x10),
            "cohort selection scope owner/suspension differs");base::owned(owner);
        ++s.selectionCalls;actors::invoke(clear,selector);base::owned(owner);
        for(auto id:s.ids){void* ids[]={&id};actors::invoke(add,selector,ids);base::owned(owner);}close();base::owned(owner);
        require(disposed&&!ba::read<bool>(helper.get(),0x10),"cohort original selection scope did not close");
    } catch(...) {try{close();}catch(...){ba::log("Cohort selection cleanup failed; retry=0");}throw;}
    require(sameIds(selection::selectionIds(ba::read<Obj>(selector,0x90)),s.ids),"cohort original two-ID selection differs");
    base::assignSelected(owner,selector,4);++s.groupCalls;s.group=std::make_unique<Root>(base::groupFor(selector));
    actors::IntentGroup checked(owner,s.group->get(),4);s.helper=std::make_unique<Root>(checked.helper.get());s.selected=true;
}
static void snapshot(const char* event,actors::State& owner,Obj selector,bool poses=true) {
    auto& s=state();const auto members=census(owner,selector,poses);std::vector<uint32_t> ids;std::vector<uint64_t> tokens;
    for(const auto& m:members){ids.push_back(m.id);tokens.push_back(m.token);}
    if(s.selected)require(ids==s.ids&&tokens==s.tokens,"cohort current logical member identities changed");
    const auto history=ba_prediction_actor_smoke::expired_click::history(selector);
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::boolalpha<<common(event,owner)
       <<",\"members\":"<<membersJson(members,poses)<<",\"selector\":"<<pointer(selector)
       <<",\"manager\":"<<pointer(owner.manager->get())<<",\"simulation\":"<<pointer(owner.simulation->get())
       <<",\"group_generation\":"<<owner.groupGeneration<<",\"current_ids\":"<<base::idsJson(selection::selectionIds(ba::read<Obj>(selector,0x90)))
       <<",\"preview_ids\":"<<base::idsJson(selection::selectionIds(ba::read<Obj>(selector,0x88)))
       <<",\"casting_ids\":"<<base::idsJson(selection::selectionIds(ba::read<Obj>(selector,0x98)))
       <<",\"active_caster\":"<<pointer(ba::read<Obj>(selector,0x100))<<",\"primary\":"<<ba::read<bool>(selector,0x16c)
       <<",\"context\":"<<ba::read<bool>(selector,0x16d)<<",\"drag\":"<<history.drag
       <<",\"last_click_id\":"<<history.id<<",\"click_mode\":"<<history.mode<<",\"selection_calls\":"<<s.selectionCalls
       <<",\"group_assign_calls\":"<<s.groupCalls<<",\"selection_scope_player_initiated\":"<<(s.selectionCalls?"false":"null")
       <<",\"history_writes\":0,\"physicalUI\":false";
    if(s.selected&&ba::lanSlot()==1) {
        actors::IntentGroup group(owner,s.group->get(),4);
        require(owner.groupGeneration==s.generation,"cohort group generation changed");
        require(group.helper.get()==s.helper->get()&&base::groupFor(selector)==s.group->get(),"cohort original group/helper changed");
        const auto current=cache(ba::read<Obj>(selector,0x90)),groupCache=cache(group.selected.get());
        require(sameIds(current.ids,s.ids)&&sameIds(current.typed,s.ids)&&current.count==2&&
            sameIds(groupCache.ids,s.ids)&&sameIds(groupCache.typed,s.ids)&&groupCache.count==2,
            "cohort original current/group/type1 cache lost a member");
        require(current.frames==groupCache.frames&&current.frames==ba::read<Obj>(owner.simulation->get(),0x148),"cohort raw cache frame owner changed");
        out<<",\"current_count\":"<<current.count<<",\"current_all_ids\":"<<base::idsJson(current.ids)<<",\"current_typed_ids\":"<<base::idsJson(current.typed)
           <<",\"group\":"<<pointer(group.group.get())<<",\"helper\":"<<pointer(group.helper.get())<<",\"frame_owner\":"<<pointer(current.frames)
           <<",\"group_ids\":"<<base::idsJson(groupCache.ids)<<",\"group_count\":"<<groupCache.count<<",\"group_all_ids\":"<<base::idsJson(groupCache.ids)
           <<",\"group_typed_ids\":"<<base::idsJson(groupCache.typed)<<",\"tracked_released_ids\":"<<base::idsJson(actors::ids(ba::read<Obj>(group.group.get(),0x10)))
           <<",\"auto_type1\":"<<actors::automaticType(ba::read<Obj>(group.group.get(),0x30),1);
    } else out<<",\"current_count\":null,\"current_all_ids\":null,\"current_typed_ids\":null,\"group\":null,\"helper\":null,\"frame_owner\":null,\"group_ids\":null,\"group_count\":null,\"group_all_ids\":null,\"group_typed_ids\":null,\"tracked_released_ids\":null,\"auto_type1\":null";
    out<<'}';ba::log("COHORT %s",out.str().c_str());s.lastSample=GetTickCount64();
}
static void move(actors::State& owner,Obj selector) {
    auto& s=state();idle(owner,selector);const auto members=census(owner,selector,true);
    require(members.size()==s.ids.size(),"cohort Move source census changed");
    for(size_t i=0;i<members.size();++i)require(members[i].id==s.ids[i]&&members[i].token==s.tokens[i]&&
        members[i].canonical==s.tokens[i]&&members[i].admitted&&members[i].initialized&&members[i].nativeState==0,
        "cohort Move source is no longer ready/admitted");
    original::Vec3 target=members[0].position;
    if(ba::lanSlot()==1) {
        require(members.size()==2,"cohort Move needs exactly two members");const auto& second=members[1].position;
        target={(target.x+second.x)*.5f,(target.y+second.y)*.5f,(target.z+second.z)*.5f+8.f};
    } else target.x+=8.f;
    original::finite(target);uint32_t ability=12,unitType=1;
    Root ids(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(actors::type("System","UInt32"),s.ids.size()));
    require(ids.get(),"cohort original source array allocation failed");memcpy(static_cast<unsigned char*>(ids.get())+0x20,s.ids.data(),s.ids.size()*sizeof(uint32_t));
    Root typed(original::allocate("ExecuteCommandEntityTypeData"));Obj groupCtor=actors::method(typed.get(),".ctor",3,0x060000f3,0x34b3080);
    void* typeArgs[]={ids.get(),&ability,&unitType};actors::invoke(groupCtor,typed.get(),typeArgs);
    require(ba::read<Obj>(typed.get(),0x10)==ids.get()&&ba::read<uint32_t>(typed.get(),0x18)==12&&ba::read<uint32_t>(typed.get(),0x1c)==1,
        "cohort original typed constructor readback differs");
    Root groups(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(ba::klass(typed.get()),1));require(groups.get(),"cohort group array missing");
    auto* entry=reinterpret_cast<Obj*>(static_cast<unsigned char*>(groups.get())+0x20);
    ba::api<void(*)(Obj,Obj*,Obj)>("il2cpp_gc_wbarrier_set_field")(groups.get(),entry,typed.get());
    Root command(original::allocate("ExecuteTargetGroundCommand"));Obj ctor=actors::method(command.get(),".ctor",4,0x060000e6,0x37ae080);
    require(original::parameterClass(ctor,1)==actors::type("UnityEngine","Vector3"),"cohort original Vector3 ABI differs");
    const auto perspective=base::currentPerspective(owner,selector,ctor);int32_t value=perspective.value;bool queued=false;auto argument=target;
    void* args[]={groups.get(),&argument,&value,&queued};actors::invoke(ctor,command.get(),args);base::owned(owner);
    actors::field(command.get(),"<Position>k__BackingField",0x18);actors::field(command.get(),"<Queued>k__BackingField",0x24);actors::field(command.get(),"_mapPerspective",0x28);
    const auto stored=ba::read<original::Vec3>(command.get(),0x18);
    require(ba::read<Obj>(command.get(),0x10)==groups.get()&&!ba::read<bool>(command.get(),0x24)&&
        ba::read<int32_t>(command.get(),0x28)==value&&!memcmp(&stored,&target,sizeof(target)),"cohort original Move constructor readback differs");
    selection::Context recheck(selector);
    for(size_t i=0;i<s.ids.size();++i)require(recheck.admitted(s.ids[i])&&recheck.live.at(s.ids[i])==members[i].actor&&
        base::token(recheck,recheck.live.at(s.ids[i]))==s.tokens[i],
        "cohort source lease changed before original enqueue");
    if(ba::lanSlot()==1)require(sameIds(selection::selectionIds(ba::read<Obj>(selector,0x90)),s.ids),"cohort selection changed before original Move");
    idle(owner,selector);Obj server=ba_local::server();Obj enqueue=actors::method(server,"EnqueueInputCommand",1,0x06001115,0x3e53530);
    s.command=std::make_unique<Root>(command.get());const auto sampled=base::stamp();const auto tick=GetTickCount64();
    void* input[]={command.get()};actors::invoke(enqueue,server,input);s.enqueuedUs=base::stamp();s.queued=true;
    require(base::pending(owner)==1,"cohort original enqueue did not grow by exactly one ICommand");
    uint32_t bits[3]{};memcpy(bits,&target,sizeof(bits));std::ostringstream out;
    out<<common("move_queued",owner,sampled,tick)<<",\"source_ids\":"<<base::idsJson(s.ids)<<",\"incarnations\":[";
    for(size_t i=0;i<s.tokens.size();++i){if(i)out<<',';out<<s.tokens[i];}
    out<<"],\"origins\":[";for(size_t i=0;i<members.size();++i){if(i)out<<',';out<<original::pointJson(members[i].position);}
    out<<"],\"origins_sampled_us\":[";for(size_t i=0;i<members.size();++i){if(i)out<<',';out<<members[i].sampled;}
    out<<"],\"target\":"<<original::pointJson(target)<<",\"target_bits\":["<<bits[0]<<','<<bits[1]<<','<<bits[2]
       <<"],\"command\":"<<pointer(command.get())<<",\"command_class\":\"Uncapped.ExecuteTargetGroundCommand\",\"queued\":false,\"ability\":12"
       <<",\"queue_before\":0,\"queue_after\":1,\"originalCtor\":true,\"original_callback\":\"Uncapped.ExecuteTargetGroundCommand..ctor\""
       <<",\"enqueue_sampled_us\":"<<s.enqueuedUs<<perspective.json()<<",\"physicalUI\":false}";
    ba::log("COHORT %s",out.str().c_str());
}
void tick() {
    if(!enabled())return;
    try {
        requireFlags();auto& s=state();auto& owner=actors::state();const auto world=worker::movementWorldId();const auto& match=worker::movementMatchId();
        if(!world||match.empty())return;
        if(s.world!=world||s.match!=match){s=State{};s.world=world;s.match=match;}
        if(s.failed||s.complete||owner.world!=world||owner.match!=match||!owner.manager||!owner.simulation)return;
        base::owned(owner);if(ba_lan::matchEnded)return;
        require(ba::unified()&&ba::community()&&ba::dedicated()&&ba::lan()&&ba_lan::running&&!ba_lan::publicMatch,
            "cohort diagnostic requires its negotiated Custom owner");
        const int current=frame(owner);if(current<249)return;Obj selector=selection::currentSelector();
        if(!s.prebuild) {
            require(current==249,"cohort missed prebuild census249");
            for(const auto& m:census(owner,selector,false))s.before.insert(m.id);
            s.selector=std::make_unique<Root>(selector);s.prebuild=true;snapshot("prebuild",owner,selector,false);return;
        }
        require(selector==s.selector->get(),"cohort original selector generation changed");if(current<420)return;
        if(!s.selected){require(current==420,"cohort missed original selection420");choose(owner,selector,census(owner,selector,false));snapshot("selected",owner,selector);return;}
        const int at=ba::lanSlot()==1?440:460;
        if(!s.queued&&current>=at){require(current==at,"cohort missed original Move frame");snapshot("sample",owner,selector);move(owner,selector);return;}
        if(current>=520){require(current==520&&s.queued&&s.serialized&&s.registered,"cohort completion lacks original Move/normal serialization/batch");snapshot("complete",owner,selector);s.complete=true;return;}
        if(GetTickCount64()-s.lastSample>=15)snapshot("sample",owner,selector);
    } catch(const std::exception& error){state().failed=true;ba::log("Cohort smoke failed: reason=%s physicalUI=0",error.what());worker::movementFail(error.what());}
    catch(...){state().failed=true;ba::log("Cohort smoke failed: reason=unknown physicalUI=0");worker::movementFail("unknown cohort diagnostic exception");}
}
void serialized(void* command,void* action,uint64_t sequence,int sourceNextFrame,unsigned actionIndex) {
    if(!enabled())return;auto& s=state();if(!s.command||s.command->get()!=command)return;
    auto& owner=actors::state();base::owned(owner);
    require(!s.failed&&s.queued&&!s.serialized&&action&&sequence&&base::stamp()>=s.enqueuedUs,"cohort normal serializer is duplicate/early/unbound");
    s.action=std::make_unique<Root>(action);s.sequence=sequence;s.actionIndex=actionIndex;s.serialized=true;
    const auto text=common("serialized",owner)+",\"command\":"+pointer(command)+",\"action\":"+pointer(action)+
        ",\"sequence\":"+std::to_string(sequence)+",\"source_next_frame\":"+std::to_string(sourceNextFrame)+
        ",\"action_index\":"+std::to_string(actionIndex)+",\"physicalUI\":false}";
    ba::log("COHORT %s",text.c_str());
}
void registered(uint64_t sequence,int assigned,const std::vector<uint8_t>& body) {
    if(!enabled())return;auto& s=state();if(!s.serialized||sequence!=s.sequence)return;
    auto& owner=actors::state();base::owned(owner);require(!s.failed&&!s.registered,"cohort67 batch repeated");
    const auto raw=policy::action(body,s.actionIndex);s.registered=true;
    const auto text=common("batch_registered",owner)+",\"command\":"+pointer(s.command->get())+",\"action\":"+pointer(s.action->get())+
        ",\"sequence\":"+std::to_string(sequence)+",\"speculative_frame\":"+std::to_string(assigned)+
        ",\"action_index\":"+std::to_string(s.actionIndex)+",\"action_sha256\":\""+original::digest(raw)+
        "\",\"body_sha256\":\""+original::digest(body)+"\",\"physicalUI\":false}";
    ba::log("COHORT %s",text.c_str());
}
void authoritative(const std::vector<uint8_t>& raw,const std::string& wireSha) {
    if(!enabled())return;const auto sampled=base::stamp();const auto tick=GetTickCount64();auto& s=state();
    if(!s.world||s.world!=worker::movementWorldId()||s.match!=worker::movementMatchId()||s.failed)return;
    Root message(ba_lan::parse("InputActions",raw));const int canonical=ba::get<int>(message.get(),"gameFrame_");
    if(canonical<400||canonical>540)return;
    require(wireSha.size()==64&&wireSha.find_first_not_of("0123456789abcdef")==std::string::npos,"cohort65 wire hash differs");
    const auto text=common("authority",actors::state(),sampled,tick)+",\"canonical_frame\":"+std::to_string(canonical)+
        ",\"wire_sha256\":\""+wireSha+"\",\"canonical_sha256\":\""+original::digest(raw)+"\",\"physicalUI\":false}";
    ba::log("COHORT %s",text.c_str());
}
}
