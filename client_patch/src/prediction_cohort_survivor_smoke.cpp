// Explicit initial-cohort false-death diagnostic. Include after the RouteA
// diagnostic for its guarded readonly cache/state helpers, never its tick.
#include "prediction_cohort_survivor_smoke.hpp"

namespace ba_prediction_survivor {
namespace actors=ba_prediction_actors;
namespace selection=ba_prediction_selection;
namespace worker=ba_prediction_worker;
namespace base=ba_prediction_actor_smoke::mobile;
namespace cohort=ba_prediction_cohort;
namespace original=ba_prediction_movement_smoke;
using ba::Obj;using ba_local::Root;
struct Initial {uint32_t id;uint64_t token;std::unique_ptr<Root> actor;};
struct State {
    uint64_t world=0,generation=0,lastSample=0;std::string match;
    std::vector<Initial> initial;
    std::unique_ptr<Root> selector,group,helper,command,action;
    unsigned selectionCalls=0,groupCalls=0,actionIndex=0;
    uint64_t sequence=0,enqueuedUs=0;
    int lastFrame=-1,dead=-1,released=-1,restored=-1;
    bool setup=false,queued=false,serialized=false,registered=false,complete=false,failed=false;
};
static State& state(){static auto* s=new State;return *s;}
static void require(bool ok,const char* why){actors::require(ok,why);}
bool enabled(){return ba::flag(L"-prediction-cohort-survivor-smoke");}
void requireFlags() {
    if(!enabled())return;
    require(worker::movementEnabled()&&ba::flag(L"-prediction-mobile-correction-smoke")&&ba::flag(L"-lan-smoke")&&
        ba::flag(L"-original-command-scheduling-experimental"),"survivor diagnostic requires its explicit mobile/arrival fixture");
    for(const auto* flag:{L"-prediction-cohort-smoke",L"-prediction-movement-smoke",L"-prediction-actor-correction-smoke",
        L"-prediction-actor-mirror-smoke",L"-prediction-expired-click-smoke",L"-prediction-held-click-smoke",
        L"-prediction-terminal-timeline-smoke",L"-prediction-mobile-group-intent-smoke",L"-prediction-mobile-group-user-edits-smoke",
        L"-prediction-mobile-recovery-stall-smoke",L"-prediction-mobile-recall-smoke",L"-prediction-mobile-focus-smoke",
        L"-prediction-mobile-focus-no-start-smoke",L"-prediction-mobile-focus-restart-smoke",L"-prediction-mobile-caster-survey-smoke",
        L"-prediction-mobile-caster-lifetime-smoke",L"-prediction-mobile-ui-cast-smoke",L"-prediction-mobile-held-click-smoke",
        L"-prediction-mobile-context-move-smoke",L"-prediction-mobile-context-hold-smoke",L"-prediction-mobile-original-hold-smoke",
        L"-prediction-server-ai-observe",L"-prediction-server-ai-move-smoke"})
        require(!ba::flag(flag),"survivor diagnostic overlaps another optional scope");
}
static void owned(actors::State& owner) {
    base::owned(owner);const auto& s=state();
    require(owner.world==s.world&&owner.match==s.match&&s.world&&s.selector,"survivor diagnostic owner changed");
    require(ba_prediction_actor_smoke::selectorFor(owner)==s.selector->get(),"survivor original selector changed");
}
static int frame(actors::State& owner){return ba::read<int>(owner.simulation->get(),0xac);}
static std::string common(const char* event,actors::State& owner,uint64_t sampled=0,ULONGLONG tick=0) {
    owned(owner);const auto& s=state();std::ostringstream out;out.imbue(std::locale::classic());
    out<<"{\"schema\":1,\"event\":\""<<event<<"\",\"world\":"<<s.world<<",\"match\":\""<<s.match
       <<"\",\"slot\":"<<ba::lanSlot()<<",\"frame\":"<<frame(owner)<<",\"completed_frame\":"<<ba::read<int>(owner.simulation->get(),0xa8)
       <<",\"tick_ms\":"<<(tick?tick:GetTickCount64())<<",\"sampled_us\":"<<(sampled?sampled:base::stamp());return out.str();
}
static bool hasType(actors::State& owner,Obj selected,uint32_t id) {
    owned(owner);actors::classIs(selected,"Uncapped.Collections","UnitSelectionSet");
    const auto before=selection::selectionIds(selected);const Obj frames=ba::read<Obj>(selected,0x48);
    require(frames==ba::read<Obj>(owner.simulation->get(),0x148),"survivor HasType frame owner differs");
    actors::guard(0x3c63c80,"\x48\x89\x5c\x24\x08\x57\x48\x83\xec\x20\x80\x3d\x7b\x54\x1f\x03",16);
    Obj method=actors::method(selected,"HasType",1,0x06002598,0x3c63c80);
    base::FocusObservation::signature(method,false,actors::type("System","Boolean"));
    require(original::parameterClass(method,0)==actors::type("System","UInt32"),"survivor HasType argument ABI differs");
    void* args[]={&id};Root boxed(actors::invoke(method,selected,args));owned(owner);
    require(ba::read<Obj>(selected,0x48)==frames&&selection::selectionIds(selected)==before,"survivor HasType changed raw IDs/owner");
    return actors::unbox<bool>(boxed.get());
}
struct Member {
    uint32_t id;uint64_t originalToken=0,token=0,canonical=0;Obj actor=nullptr,old=nullptr;
    bool present=false,admitted=false,initialized=false,oldActive=false,oldRetained=false,oldDead=false,oldComponent=false;
    bool currentHasType=false,groupHasType=false,pose=false;std::optional<uint32_t> nativeState;
    original::Vec3 position{};uint64_t sampled=0;
    policy::Member proof()const{return {id,1,static_cast<uint32_t>(ba::lanSlot()),token,canonical,present,nativeState.value_or(UINT32_MAX),initialized,admitted};}
};
static std::vector<Member> members(actors::State& owner,Obj selector,bool poses) {
    owned(owner);auto& s=state();selection::Context context(selector);actors::Current native(ba::read<Obj>(owner.simulation->get(),0x148));
    const auto active=actors::units(ba::read<Obj>(owner.manager->get(),0x10)),retained=actors::units(ba::read<Obj>(owner.manager->get(),0xa0));
    std::vector<Member> result;
    for(const auto& initial:s.initial) {
        Member m{};m.id=initial.id;m.originalToken=initial.token;m.old=initial.actor->get();
        const actors::policy::ActorIdentity identity{m.id,1,static_cast<uint32_t>(ba::lanSlot())};
        m.canonical=actors::confirmedToken(owner,identity);const auto current=context.live.find(m.id);
        if(current!=context.live.end()) {
            m.actor=current->second;const auto resident=actors::resident(m.actor);
            require(resident.entityId==identity.entityId&&resident.unitType==identity.unitType&&resident.armyId==identity.armyId,"survivor current actor identity differs");
            m.token=base::token(context,m.actor);m.admitted=context.admitted(m.actor);
            actors::field(m.actor,"_componentData",0x158);actors::field(m.actor,"<DeadToTheSim>k__BackingField",0x160);
            m.initialized=ba::read<Obj>(m.actor,0x158)!=nullptr&&!ba::read<bool>(m.actor,0x160);
        }
        const auto actual=native.identity(m.id);m.present=actual.has_value();
        if(actual){require(actual->entityId==identity.entityId&&actual->unitType==identity.unitType&&actual->armyId==identity.armyId,
            "survivor native identity differs");m.nativeState=cohort::nativeState(native,m.id);}
        m.oldActive=std::find(active.begin(),active.end(),m.old)!=active.end();m.oldRetained=std::find(retained.begin(),retained.end(),m.old)!=retained.end();
        actors::field(m.old,"_componentData",0x158);actors::field(m.old,"<DeadToTheSim>k__BackingField",0x160);
        m.oldDead=ba::read<bool>(m.old,0x160);m.oldComponent=ba::read<Obj>(m.old,0x158)!=nullptr;
        m.currentHasType=hasType(owner,ba::read<Obj>(selector,0x90),m.id);
        if(s.group)m.groupHasType=hasType(owner,ba::read<Obj>(s.group->get(),0x20),m.id);
        if(m.id==12)policy::continuous(reinterpret_cast<uintptr_t>(m.old),reinterpret_cast<uintptr_t>(m.actor),m.token,m.canonical,
            m.originalToken,m.present,m.initialized,m.admitted);
        if(poses&&m.present&&m.nativeState&&*m.nativeState!=6&&m.initialized&&m.admitted) {
            m.position=original::actualPosition(owner,m.actor);m.sampled=base::stamp();original::finite(m.position);m.pose=true;
        }
        result.push_back(m);
    }
    owned(owner);return result;
}
static std::string memberJson(const std::vector<Member>& values) {
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::boolalpha<<std::setprecision(9)<<'[';bool first=true;
    for(const auto& m:values) {
        if(!first)out<<',';first=false;
        out<<"{\"id\":"<<m.id<<",\"unit_type\":1,\"army\":"<<ba::lanSlot()<<",\"original_token\":"<<m.originalToken
           <<",\"incarnation\":"<<m.token<<",\"canonical_token\":"<<m.canonical<<",\"actor\":"<<cohort::pointer(m.actor)
           <<",\"native_present\":"<<m.present<<",\"current_has_type\":"<<m.currentHasType<<",\"group_has_type\":";
        if(state().group)out<<m.groupHasType;else out<<"null";
        out<<",\"native_state\":"<<(m.nativeState?std::to_string(*m.nativeState):"null")<<",\"admitted\":"<<m.admitted
           <<",\"initialized\":"<<m.initialized<<",\"original_actor\":"<<cohort::pointer(m.old)<<",\"original_active\":"<<m.oldActive
           <<",\"original_retained\":"<<m.oldRetained<<",\"original_dead\":"<<m.oldDead<<",\"original_component\":"<<m.oldComponent
           <<",\"position\":"<<(m.pose?original::pointJson(m.position):"null")<<",\"position_bits\":";
        if(m.pose){uint32_t bits[3]{};memcpy(bits,&m.position,sizeof(bits));out<<'['<<bits[0]<<','<<bits[1]<<','<<bits[2]<<']';}else out<<"null";
        out<<",\"position_sampled_us\":"<<(m.pose?std::to_string(m.sampled):"null")<<",\"jobs_joined\":"<<m.pose<<'}';
    }
    out<<']';return out.str();
}
static void snapshot(const char* event,actors::State& owner,Obj selector) {
    auto& s=state();const auto values=members(owner,selector,true);const auto current=cohort::cache(ba::read<Obj>(selector,0x90));
    const auto history=ba_prediction_actor_smoke::expired_click::history(selector);
    require(current.frames==ba::read<Obj>(owner.simulation->get(),0x148),"survivor current selection frame owner differs");
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::boolalpha<<common(event,owner)
       <<",\"members\":"<<memberJson(values)<<",\"selector\":"<<cohort::pointer(selector)<<",\"manager\":"<<cohort::pointer(owner.manager->get())
       <<",\"simulation\":"<<cohort::pointer(owner.simulation->get())<<",\"group_generation\":"<<owner.groupGeneration
       <<",\"current_ids\":"<<base::idsJson(current.ids)<<",\"preview_ids\":"<<base::idsJson(selection::selectionIds(ba::read<Obj>(selector,0x88)))
       <<",\"casting_ids\":"<<base::idsJson(selection::selectionIds(ba::read<Obj>(selector,0x98)))<<",\"active_caster\":"<<cohort::pointer(ba::read<Obj>(selector,0x100))
       <<",\"primary\":"<<ba::read<bool>(selector,0x16c)<<",\"context\":"<<ba::read<bool>(selector,0x16d)<<",\"drag\":"<<history.drag
       <<",\"last_click_id\":"<<history.id<<",\"click_mode\":"<<history.mode<<",\"pending_commands\":"<<base::pending(owner)
       <<",\"selection_calls\":"<<s.selectionCalls<<",\"group_assign_calls\":"<<s.groupCalls
       <<",\"selection_scope_player_initiated\":"<<(s.selectionCalls?"false":"null")<<",\"history_writes\":0"
       <<",\"current_count\":"<<current.count<<",\"current_all_ids\":"<<base::idsJson(current.ids)<<",\"current_typed_ids\":"<<base::idsJson(current.typed)
       <<",\"current_frame_owner\":"<<cohort::pointer(current.frames);
    if(s.group) {
        actors::IntentGroup group(owner,s.group->get(),4);const auto cache=cohort::cache(group.selected.get());
        require(owner.groupGeneration==s.generation&&group.helper.get()==s.helper->get()&&base::groupFor(selector)==s.group->get()&&
            cache.frames==current.frames,"survivor original group/helper/generation/frame owner changed");
        out<<",\"group\":"<<cohort::pointer(group.group.get())<<",\"helper\":"<<cohort::pointer(group.helper.get())
           <<",\"group_ids\":"<<base::idsJson(cache.ids)<<",\"group_count\":"<<cache.count<<",\"group_all_ids\":"<<base::idsJson(cache.ids)
           <<",\"group_typed_ids\":"<<base::idsJson(cache.typed)<<",\"group_frame_owner\":"<<cohort::pointer(cache.frames)
           <<",\"tracked_released_ids\":"<<base::idsJson(actors::ids(ba::read<Obj>(group.group.get(),0x10)))
           <<",\"auto_type1\":"<<actors::automaticType(ba::read<Obj>(group.group.get(),0x30),1);
    } else out<<",\"group\":null,\"helper\":null,\"group_ids\":null,\"group_count\":null,\"group_all_ids\":null,\"group_typed_ids\":null,\"group_frame_owner\":null,\"tracked_released_ids\":null,\"auto_type1\":null";
    out<<",\"physicalUI\":false}";ba::log("COHORT SURVIVOR %s",out.str().c_str());s.lastSample=GetTickCount64();s.lastFrame=frame(owner);
}
static void setup(actors::State& owner,Obj selector) {
    auto& s=state();owned(owner);selection::Context context(selector);
    const std::vector<uint32_t> ids=ba::lanSlot()==1?std::vector<uint32_t>{11,12}:std::vector<uint32_t>{10};
    for(uint32_t id:ids) {
        const auto found=context.live.find(id);require(found!=context.live.end()&&context.admitted(found->second),"survivor initial confirmed member missing");
        const auto resident=actors::resident(found->second);
        require(resident.entityId==id&&resident.unitType==1&&resident.armyId==static_cast<uint32_t>(ba::lanSlot()),"survivor initial member identity differs");
        const auto token=base::token(context,found->second);require(token&&token==actors::confirmedToken(owner,resident),"survivor initial member canonical token differs");
        s.initial.push_back({id,token,std::make_unique<Root>(found->second)});
    }
    if(ba::lanSlot()==1) {
        std::vector<policy::Member> proof;for(const auto& m:members(owner,selector,false))proof.push_back(m.proof());policy::selection(proof);
        cohort::idle(owner,selector);Obj begin=actors::method(selector,"BeginSelectionChange",1,0x06002237,0x3bf5af0);
        Obj clear=actors::method(selector,"ClearSelection",0,0x06002217,0x3bf2680),add=actors::method(selector,"AddToSelection",1,0x06002214,0x3bf2510);
        actors::field(selector,"_selectionChangeHelper",0x80);Root helper(ba::read<Obj>(selector,0x80));require(helper.get(),"survivor selection helper missing");
        actors::field(helper.get(),"<IsSuspended>k__BackingField",0x10);require(!ba::read<bool>(helper.get(),0x10),"survivor selection already suspended");
        Obj dispose=actors::method(helper.get(),"Dispose",0,0x060000cd,0x3b02160);bool disposed=false;
        auto close=[&](){if(!disposed&&ba::read<bool>(helper.get(),0x10)){disposed=true;actors::invoke(dispose,helper.get());}};
        try {bool player=false;void* args[]={&player};
            require(actors::invoke(begin,selector,args)==helper.get()&&ba::read<bool>(helper.get(),0x10),"survivor selection scope owner/suspension differs");owned(owner);
            ++s.selectionCalls;actors::invoke(clear,selector);owned(owner);
            for(uint32_t id:ids){void* argsId[]={&id};actors::invoke(add,selector,argsId);owned(owner);}close();owned(owner);
            require(disposed&&!ba::read<bool>(helper.get(),0x10),"survivor original selection scope did not close");
        } catch(...) {try{close();}catch(...){ba::log("Survivor selection cleanup failed; retry=0");}throw;}
        require(cohort::sameIds(selection::selectionIds(ba::read<Obj>(selector,0x90)),ids),"survivor original pair selection differs");
        base::assignSelected(owner,selector,4);++s.groupCalls;s.group=std::make_unique<Root>(base::groupFor(selector));
        actors::IntentGroup group(owner,s.group->get(),4);s.helper=std::make_unique<Root>(group.helper.get());s.generation=owner.groupGeneration;
    }
    s.setup=true;snapshot(ba::lanSlot()==1?"selected":"setup",owner,selector);
}
static void move(actors::State& owner,Obj selector) {
    auto& s=state();cohort::idle(owner,selector);const auto values=members(owner,selector,true);const bool pair=ba::lanSlot()==1;
    std::vector<uint32_t> sources;std::vector<policy::Member> proof;
    for(const auto& m:values) {
        require(m.pose&&m.token==m.originalToken&&m.canonical==m.originalToken,"survivor Move lacks an actual current confirmed pose/lease");
        sources.push_back(m.id);proof.push_back(m.proof());
    }
    if(pair){const auto current=cohort::cache(ba::read<Obj>(selector,0x90));policy::move(proof,current.ids,current.count);}
    else require(values.size()==1&&values[0].id==10&&values[0].admitted,"survivor escape source differs");
    original::Vec3 target{-32.f,0.f,0.f};
    if(pair)target={(values[0].position.x+values[1].position.x)*.5f,(values[0].position.y+values[1].position.y)*.5f,
        (values[0].position.z+values[1].position.z)*.5f+8.f};
    original::finite(target);uint32_t ability=12,unitType=1;
    Root ids(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(actors::type("System","UInt32"),sources.size()));require(ids.get(),"survivor original ID array allocation failed");
    memcpy(static_cast<unsigned char*>(ids.get())+0x20,sources.data(),sources.size()*sizeof(uint32_t));
    Root typed(original::allocate("ExecuteCommandEntityTypeData"));Obj groupCtor=actors::method(typed.get(),".ctor",3,0x060000f3,0x34b3080);
    void* groupArgs[]={ids.get(),&ability,&unitType};actors::invoke(groupCtor,typed.get(),groupArgs);owned(owner);
    require(ba::read<Obj>(typed.get(),0x10)==ids.get()&&ba::read<uint32_t>(typed.get(),0x18)==12&&ba::read<uint32_t>(typed.get(),0x1c)==1,
        "survivor original typed constructor readback differs");
    Root groups(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(ba::klass(typed.get()),1));require(groups.get(),"survivor original typed group array missing");
    auto* entry=reinterpret_cast<Obj*>(static_cast<unsigned char*>(groups.get())+0x20);
    ba::api<void(*)(Obj,Obj*,Obj)>("il2cpp_gc_wbarrier_set_field")(groups.get(),entry,typed.get());
    Root command(original::allocate("ExecuteTargetGroundCommand"));Obj ctor=actors::method(command.get(),".ctor",4,0x060000e6,0x37ae080);
    require(original::parameterClass(ctor,1)==actors::type("UnityEngine","Vector3"),"survivor original Vector3 ABI differs");
    const auto perspective=base::currentPerspective(owner,selector,ctor);int32_t value=perspective.value;bool queued=false;auto argument=target;
    void* args[]={groups.get(),&argument,&value,&queued};actors::invoke(ctor,command.get(),args);owned(owner);
    actors::field(command.get(),"<Position>k__BackingField",0x18);actors::field(command.get(),"<Queued>k__BackingField",0x24);actors::field(command.get(),"_mapPerspective",0x28);
    const auto stored=ba::read<original::Vec3>(command.get(),0x18);
    require(ba::read<Obj>(command.get(),0x10)==groups.get()&&!ba::read<bool>(command.get(),0x24)&&ba::read<int32_t>(command.get(),0x28)==value&&
        !memcmp(&stored,&target,sizeof(target)),"survivor original ground constructor readback differs");
    selection::Context recheck(selector);
    for(const auto& m:values)require(recheck.admitted(m.id)&&recheck.live.at(m.id)==m.actor&&base::token(recheck,m.actor)==m.originalToken,
        "survivor Move source changed before enqueue");
    cohort::idle(owner,selector);Obj server=ba_local::server();Obj enqueue=actors::method(server,"EnqueueInputCommand",1,0x06001115,0x3e53530);
    s.command=std::make_unique<Root>(command.get());const auto sampled=base::stamp();const auto tick=GetTickCount64();
    void* input[]={command.get()};actors::invoke(enqueue,server,input);owned(owner);s.enqueuedUs=base::stamp();s.queued=true;
    require(base::pending(owner)==1,"survivor original enqueue did not grow by exactly one ICommand");
    uint32_t bits[3]{};memcpy(bits,&target,sizeof(bits));std::ostringstream out;out<<common("move_queued",owner,sampled,tick)
       <<",\"source_ids\":"<<base::idsJson(sources)<<",\"incarnations\":[";
    for(size_t i=0;i<values.size();++i){if(i)out<<',';out<<values[i].originalToken;}
    out<<"],\"origins\":[";for(size_t i=0;i<values.size();++i){if(i)out<<',';out<<original::pointJson(values[i].position);}
    out<<"],\"origins_sampled_us\":[";for(size_t i=0;i<values.size();++i){if(i)out<<',';out<<values[i].sampled;}
    out<<"],\"target\":"<<original::pointJson(target)<<",\"target_bits\":["<<bits[0]<<','<<bits[1]<<','<<bits[2]
       <<"],\"command\":"<<cohort::pointer(command.get())<<",\"command_class\":\"Uncapped.ExecuteTargetGroundCommand\",\"queued\":false,\"ability\":12"
       <<",\"queue_before\":0,\"queue_after\":1,\"originalCtor\":true,\"original_callback\":\"Uncapped.ExecuteTargetGroundCommand..ctor\""
       <<",\"enqueue_sampled_us\":"<<s.enqueuedUs<<perspective.json()<<",\"physicalUI\":false}";ba::log("COHORT SURVIVOR %s",out.str().c_str());
}
void tick() {
    if(!enabled())return;
    try {
        requireFlags();const auto world=worker::movementWorldId();const auto& match=worker::movementMatchId();auto& s=state();
        if(!world||match.empty()){s=State{};return;}
        auto& owner=actors::state();if(owner.world!=world||owner.match!=match||!owner.manager||!owner.simulation)return;
        if(s.world!=world||s.match!=match) {
            s=State{};s.world=world;s.match=match;
            // Shared helpers validate this diagnostic tuple only. The singleton
            // mobile tick/setup/focus/reselection is never entered in this mode.
            base::state()=base::State{};base::state().world=world;base::state().match=match;
            s.selector=std::make_unique<Root>(ba_prediction_actor_smoke::selectorFor(owner));
        }
        if(s.failed||s.complete)return;owned(owner);if(ba_lan::matchEnded)return;
        require(ba::unified()&&ba::community()&&ba::dedicated()&&ba::lan()&&ba_lan::originalCommandScheduling()&&ba_lan::running&&!ba_lan::publicMatch&&
            (ba::lanSlot()==0||ba::lanSlot()==1),"survivor fixture requires negotiated two-human Custom");
        const int current=frame(owner);if(current<130)return;Obj selector=s.selector->get();
        if(!s.setup){require(current==130,"survivor missed initial selection130");setup(owner,selector);return;}
        const auto values=members(owner,selector,false);
        if(ba::lanSlot()==1) {
            const auto& victim=values[0];
            if(s.dead<0&&victim.nativeState&&*victim.nativeState==6){s.dead=current;snapshot("native_dead",owner,selector);}
            if(s.dead>=0&&s.released<0&&!victim.present&&!victim.oldActive&&!victim.oldRetained&&!victim.oldComponent){s.released=current;snapshot("released",owner,selector);}
            if(s.released>=0&&s.restored<0&&victim.present&&victim.nativeState&&*victim.nativeState!=6&&victim.admitted&&victim.initialized) {
                require(victim.token==victim.originalToken&&victim.canonical==victim.originalToken,"survivor restored11 changed its confirmed incarnation");
                s.restored=current;snapshot("restored",owner,selector);
            }
        }
        const int moveAt=ba::lanSlot()==1?180:150;
        if(!s.queued&&current>=moveAt) {
            require(current==moveAt,"survivor missed exact original Move frame");
            if(ba::lanSlot()==1)require(s.dead>=0&&s.released>=0&&s.restored>=0,"survivor pair Move lacks one real death/release/restore");
            snapshot("sample",owner,selector);move(owner,selector);return;
        }
        if(current>=220) {
            require(current==220&&s.queued&&s.serialized&&s.registered,"survivor completion lacks its normal original command/batch");
            snapshot("complete",owner,selector);s.complete=true;return;
        }
        if(current!=s.lastFrame||GetTickCount64()-s.lastSample>=15)snapshot("sample",owner,selector);
    } catch(const std::exception& error){state().failed=true;ba::log("Cohort survivor smoke failed: reason=%s physicalUI=0",error.what());worker::movementFail(error.what());}
    catch(...){state().failed=true;ba::log("Cohort survivor smoke failed: reason=unknown physicalUI=0");worker::movementFail("unknown cohort survivor diagnostic exception");}
}
void serialized(void* command,void* action,uint64_t sequence,int sourceNextFrame,unsigned actionIndex) {
    if(!enabled())return;auto& s=state();if(!s.command||s.command->get()!=command)return;
    auto& owner=actors::state();owned(owner);
    require(!s.failed&&s.queued&&!s.serialized&&action&&sequence&&base::stamp()>=s.enqueuedUs,"survivor normal serializer duplicate/early/unbound");
    s.action=std::make_unique<Root>(action);s.sequence=sequence;s.actionIndex=actionIndex;s.serialized=true;
    const auto text=common("serialized",owner)+",\"command\":"+cohort::pointer(command)+",\"action\":"+cohort::pointer(action)+
        ",\"sequence\":"+std::to_string(sequence)+",\"source_next_frame\":"+std::to_string(sourceNextFrame)+",\"action_index\":"+std::to_string(actionIndex)+",\"physicalUI\":false}";
    ba::log("COHORT SURVIVOR %s",text.c_str());
}
void registered(uint64_t sequence,int assigned,const std::vector<uint8_t>& body) {
    if(!enabled())return;auto& s=state();if(!s.serialized||sequence!=s.sequence)return;
    auto& owner=actors::state();owned(owner);require(!s.failed&&!s.registered,"survivor67 batch repeated");
    const auto raw=cohort::policy::action(body,s.actionIndex);s.registered=true;
    const auto text=common("batch_registered",owner)+",\"command\":"+cohort::pointer(s.command->get())+",\"action\":"+cohort::pointer(s.action->get())+
        ",\"sequence\":"+std::to_string(sequence)+",\"speculative_frame\":"+std::to_string(assigned)+",\"action_index\":"+std::to_string(s.actionIndex)+
        ",\"action_sha256\":\""+original::digest(raw)+"\",\"body_sha256\":\""+original::digest(body)+"\",\"physicalUI\":false}";
    ba::log("COHORT SURVIVOR %s",text.c_str());
}
void authoritative(const std::vector<uint8_t>& raw,const std::string& wireSha) {
    if(!enabled())return;const auto sampled=base::stamp();const auto tick=GetTickCount64();auto& s=state();
    if(!s.world||s.world!=worker::movementWorldId()||s.match!=worker::movementMatchId()||s.failed)return;
    Root message(ba_lan::parse("InputActions",raw));const int canonical=ba::get<int>(message.get(),"gameFrame_");if(canonical<130||canonical>240)return;
    require(wireSha.size()==64&&wireSha.find_first_not_of("0123456789abcdef")==std::string::npos,"survivor65 wire hash differs");
    const auto text=common("authority",actors::state(),sampled,tick)+",\"canonical_frame\":"+std::to_string(canonical)+
        ",\"wire_sha256\":\""+wireSha+"\",\"canonical_sha256\":\""+original::digest(raw)+"\",\"physicalUI\":false}";
    ba::log("COHORT SURVIVOR %s",text.c_str());
}
}
