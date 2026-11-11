// Standalone ordinary-stat initial cohort. Include after the cohort diagnostic
// for its guarded readonly cache/state helpers; no mobile/death tick is entered.
#include "prediction_close_formation_smoke.hpp"

namespace ba_prediction_close_formation {
namespace actors=ba_prediction_actors;
namespace selection=ba_prediction_selection;
namespace worker=ba_prediction_worker;
namespace base=ba_prediction_actor_smoke::mobile;
namespace cohort=ba_prediction_cohort;
namespace original=ba_prediction_movement_smoke;
using ba::Obj;using ba_local::Root;
struct Initial {uint32_t id;uint64_t token;std::unique_ptr<Root> actor;};
struct Order {
    policy::Tag tag=policy::Tag::Approach;
    std::unique_ptr<Root> command,action;
    uint64_t sequence=0,enqueuedUs=0;unsigned actionIndex=0;
    bool queued=false,serialized=false,registered=false;
};
struct State {
    uint64_t world=0,generation=0,lastSample=0;std::string match;int lastFrame=-1;
    std::vector<Initial> initial;std::array<Order,3> orders;
    std::unique_ptr<Root> selector,group,helper;
    unsigned selectionCalls=0,groupCalls=0;
    bool setup=false,complete=false,failed=false;
};
static State& state(){static auto* s=new State;return *s;}
static void require(bool ok,const char* why){actors::require(ok,why);}
bool enabled(){return ba::flag(L"-prediction-close-formation-smoke");}
void requireFlags() {
    if(!enabled())return;
    require(worker::movementEnabled()&&ba::flag(L"-lan-smoke")&&ba::flag(L"-original-command-scheduling-experimental"),
        "close formation requires its explicit ordinary prediction/arrival fixture");
    for(const auto* flag:{L"-prediction-queued-orders-smoke",L"-prediction-cohort-smoke",L"-prediction-cohort-survivor-smoke",L"-prediction-cohort-canonical-death-smoke",
        L"-prediction-mobile-correction-smoke",L"-prediction-movement-smoke",L"-prediction-actor-correction-smoke",L"-prediction-actor-mirror-smoke",
        L"-prediction-expired-click-smoke",L"-prediction-held-click-smoke",L"-prediction-terminal-timeline-smoke",
        L"-prediction-mobile-group-intent-smoke",L"-prediction-mobile-group-user-edits-smoke",L"-prediction-mobile-recovery-stall-smoke",
        L"-prediction-mobile-recall-smoke",L"-prediction-mobile-focus-smoke",L"-prediction-mobile-focus-no-start-smoke",
        L"-prediction-mobile-focus-restart-smoke",L"-prediction-mobile-caster-survey-smoke",L"-prediction-mobile-caster-lifetime-smoke",
        L"-prediction-mobile-ui-cast-smoke",L"-prediction-mobile-held-click-smoke",L"-prediction-mobile-context-move-smoke",
        L"-prediction-mobile-context-hold-smoke",L"-prediction-mobile-original-hold-smoke",L"-prediction-server-ai-observe",
        L"-prediction-server-ai-move-smoke",L"-public-queue-smoke"})
        require(!ba::flag(flag),"close formation overlaps another diagnostic scope");
}
static void owned(actors::State& owner) {
    base::owned(owner);const auto& s=state();
    require(s.world&&owner.world==s.world&&owner.match==s.match&&s.selector&&
        ba_prediction_actor_smoke::selectorFor(owner)==s.selector->get(),"close formation presentation owner/selector changed");
}
static int frame(actors::State& owner){return ba::read<int>(owner.simulation->get(),0xac);}
static std::string common(const char* event,actors::State& owner,const Order* order=nullptr,uint64_t sampled=0,ULONGLONG tick=0) {
    owned(owner);const auto& s=state();std::ostringstream out;out.imbue(std::locale::classic());
    out<<"{\"schema\":1,\"event\":\""<<event<<"\",\"order_tag\":";
    if(order)out<<'"'<<policy::name(order->tag)<<'"';else out<<"null";
    out<<",\"world\":"<<s.world<<",\"match\":\""<<s.match<<"\",\"slot\":"<<ba::lanSlot()
       <<",\"frame\":"<<frame(owner)<<",\"completed_frame\":"<<ba::read<int>(owner.simulation->get(),0xa8)
       <<",\"tick_ms\":"<<(tick?tick:GetTickCount64())<<",\"sampled_us\":"<<(sampled?sampled:base::stamp());return out.str();
}
static std::vector<cohort::Member> members(actors::State& owner,Obj selector,bool poses,bool ready=false) {
    owned(owner);const auto values=cohort::census(owner,selector,poses);const auto& s=state();std::vector<policy::Member> proof;
    require(values.size()==s.initial.size(),"close formation native initial member census changed");
    for(size_t i=0;i<values.size();++i) {
        const auto& m=values[i];const auto& initial=s.initial[i];
        require(m.id==initial.id,"close formation member order changed");
        proof.push_back({m.id,1,static_cast<uint32_t>(ba::lanSlot()),m.nativeState,m.token,m.canonical,initial.token,
            reinterpret_cast<uintptr_t>(m.actor),reinterpret_cast<uintptr_t>(initial.actor->get()),true,m.initialized,m.admitted});
    }
    policy::validate(proof,static_cast<unsigned>(ba::lanSlot()),ready);owned(owner);return values;
}
static std::string memberJson(const std::vector<cohort::Member>& values) {
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::boolalpha<<std::setprecision(9)<<'[';
    for(size_t i=0;i<values.size();++i) {
        const auto& m=values[i];const auto& initial=state().initial[i];if(i)out<<',';
        uint32_t bits[3]{};memcpy(bits,&m.position,sizeof(bits));
        out<<"{\"id\":"<<m.id<<",\"unit_type\":1,\"army\":"<<ba::lanSlot()<<",\"original_token\":"<<initial.token
           <<",\"incarnation\":"<<m.token<<",\"canonical_token\":"<<m.canonical<<",\"original_actor\":"<<cohort::pointer(initial.actor->get())
           <<",\"actor\":"<<cohort::pointer(m.actor)<<",\"native_present\":true,\"native_state\":"<<m.nativeState
           <<",\"admitted\":"<<m.admitted<<",\"initialized\":"<<m.initialized<<",\"position\":"<<original::pointJson(m.position)
           <<",\"position_bits\":["<<bits[0]<<','<<bits[1]<<','<<bits[2]<<"],\"position_sampled_us\":"<<m.sampled<<",\"jobs_joined\":true}";
    }
    out<<']';return out.str();
}
static void snapshot(const char* event,actors::State& owner,Obj selector) {
    auto& s=state();const auto values=members(owner,selector,true);const auto current=cohort::cache(ba::read<Obj>(selector,0x90));
    const auto history=ba_prediction_actor_smoke::expired_click::history(selector);
    require(current.frames==ba::read<Obj>(owner.simulation->get(),0x148),"close formation current cache frame owner differs");
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
        policy::cache(current.ids,current.typed,current.count);policy::cache(cache.ids,cache.typed,cache.count);
        require(owner.groupGeneration==s.generation&&group.helper.get()==s.helper->get()&&base::groupFor(selector)==s.group->get()&&
            cache.frames==current.frames,"close formation group/helper/generation/frame owner changed");
        out<<",\"group\":"<<cohort::pointer(group.group.get())<<",\"helper\":"<<cohort::pointer(group.helper.get())
           <<",\"group_ids\":"<<base::idsJson(cache.ids)<<",\"group_count\":"<<cache.count<<",\"group_all_ids\":"<<base::idsJson(cache.ids)
           <<",\"group_typed_ids\":"<<base::idsJson(cache.typed)<<",\"group_frame_owner\":"<<cohort::pointer(cache.frames)
           <<",\"tracked_released_ids\":"<<base::idsJson(actors::ids(ba::read<Obj>(group.group.get(),0x10)))
           <<",\"auto_type1\":"<<actors::automaticType(ba::read<Obj>(group.group.get(),0x30),1);
    } else out<<",\"group\":null,\"helper\":null,\"group_ids\":null,\"group_count\":null,\"group_all_ids\":null,\"group_typed_ids\":null,\"group_frame_owner\":null,\"tracked_released_ids\":null,\"auto_type1\":null";
    out<<",\"physicalUI\":false}";ba::log("CLOSE FORMATION %s",out.str().c_str());s.lastSample=GetTickCount64();s.lastFrame=frame(owner);
}
static void setup(actors::State& owner,Obj selector) {
    auto& s=state();owned(owner);const auto values=cohort::census(owner,selector,false);
    for(const auto& m:values)s.initial.push_back({m.id,m.token,std::make_unique<Root>(m.actor)});
    members(owner,selector,false,true);cohort::idle(owner,selector);
    if(ba::lanSlot()==1) {
        Obj begin=actors::method(selector,"BeginSelectionChange",1,0x06002237,0x3bf5af0);
        Obj clear=actors::method(selector,"ClearSelection",0,0x06002217,0x3bf2680),add=actors::method(selector,"AddToSelection",1,0x06002214,0x3bf2510);
        actors::field(selector,"_selectionChangeHelper",0x80);Root helper(ba::read<Obj>(selector,0x80));require(helper.get(),"close formation selection helper missing");
        actors::field(helper.get(),"<IsSuspended>k__BackingField",0x10);require(!ba::read<bool>(helper.get(),0x10),"close formation selection already suspended");
        Obj dispose=actors::method(helper.get(),"Dispose",0,0x060000cd,0x3b02160);bool disposed=false;
        auto close=[&](){if(!disposed&&ba::read<bool>(helper.get(),0x10)){disposed=true;actors::invoke(dispose,helper.get());}};
        try {bool player=false;void* args[]={&player};
            require(actors::invoke(begin,selector,args)==helper.get()&&ba::read<bool>(helper.get(),0x10),"close formation selection scope owner/suspension differs");owned(owner);
            ++s.selectionCalls;actors::invoke(clear,selector);owned(owner);
            for(const auto& m:s.initial){auto id=m.id;void* arg[]={&id};actors::invoke(add,selector,arg);owned(owner);}close();owned(owner);
            require(disposed&&!ba::read<bool>(helper.get(),0x10),"close formation original selection scope did not close");
        } catch(...) {try{close();}catch(...){ba::log("Close formation selection cleanup failed; retry=0");}throw;}
        base::assignSelected(owner,selector,4);++s.groupCalls;s.group=std::make_unique<Root>(base::groupFor(selector));
        actors::IntentGroup group(owner,s.group->get(),4);s.helper=std::make_unique<Root>(group.helper.get());s.generation=owner.groupGeneration;
    }
    s.setup=true;snapshot(ba::lanSlot()==1?"selected":"setup",owner,selector);
}
static void move(actors::State& owner,Obj selector,Order& order) {
    require(policy::slot(order.tag)==static_cast<unsigned>(ba::lanSlot())&&frame(owner)==policy::at(order.tag)&&!order.queued,
        "close formation original order seat/frame/repeat differs");
    cohort::idle(owner,selector);const auto values=members(owner,selector,true,true);std::vector<uint32_t> sources;
    for(const auto& m:values)sources.push_back(m.id);
    if(ba::lanSlot()==1){const auto current=cohort::cache(ba::read<Obj>(selector,0x90));policy::cache(current.ids,current.typed,current.count);}
    original::Vec3 target{60.f,0.f,44.f};
    if(order.tag==policy::Tag::Approach)target={70.f,0.f,50.f};
    if(order.tag==policy::Tag::Fresh) {
        std::vector<policy::Point> points;for(const auto& m:values)points.push_back({m.position.x,m.position.y,m.position.z});
        const auto center=policy::freshTarget(points);target={center.x,center.y,center.z};
    }
    original::finite(target);uint32_t ability=12,unitType=1;
    Root ids(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(actors::type("System","UInt32"),sources.size()));require(ids.get(),"close formation ID array allocation failed");
    memcpy(static_cast<unsigned char*>(ids.get())+0x20,sources.data(),sources.size()*sizeof(uint32_t));
    Root typed(original::allocate("ExecuteCommandEntityTypeData"));Obj typedCtor=actors::method(typed.get(),".ctor",3,0x060000f3,0x34b3080);
    void* typeArgs[]={ids.get(),&ability,&unitType};actors::invoke(typedCtor,typed.get(),typeArgs);owned(owner);
    require(ba::read<Obj>(typed.get(),0x10)==ids.get()&&ba::read<uint32_t>(typed.get(),0x18)==12&&ba::read<uint32_t>(typed.get(),0x1c)==1,
        "close formation original typed constructor readback differs");
    Root groups(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(ba::klass(typed.get()),1));require(groups.get(),"close formation original group array missing");
    auto* entry=reinterpret_cast<Obj*>(static_cast<unsigned char*>(groups.get())+0x20);
    ba::api<void(*)(Obj,Obj*,Obj)>("il2cpp_gc_wbarrier_set_field")(groups.get(),entry,typed.get());
    Root command(original::allocate("ExecuteTargetGroundCommand"));Obj ctor=actors::method(command.get(),".ctor",4,0x060000e6,0x37ae080);
    require(original::parameterClass(ctor,1)==actors::type("UnityEngine","Vector3"),"close formation original Vector3 ABI differs");
    const auto perspective=base::currentPerspective(owner,selector,ctor);int32_t value=perspective.value;bool queued=false;auto argument=target;
    require(perspective.value==(ba::lanSlot()==1?perspective.flipped:perspective.normal),"close formation original map perspective differs from qualified fixture");
    void* args[]={groups.get(),&argument,&value,&queued};actors::invoke(ctor,command.get(),args);owned(owner);
    actors::field(command.get(),"<Position>k__BackingField",0x18);actors::field(command.get(),"<Queued>k__BackingField",0x24);actors::field(command.get(),"_mapPerspective",0x28);
    const auto stored=ba::read<original::Vec3>(command.get(),0x18);
    require(ba::read<Obj>(command.get(),0x10)==groups.get()&&!ba::read<bool>(command.get(),0x24)&&ba::read<int32_t>(command.get(),0x28)==value&&
        !memcmp(&stored,&target,sizeof(target)),"close formation original ground constructor readback differs");
    selection::Context recheck(selector);
    for(const auto& m:values)require(recheck.admitted(m.id)&&recheck.live.at(m.id)==m.actor&&base::token(recheck,m.actor)==m.token,
        "close formation source changed before original enqueue");
    cohort::idle(owner,selector);Obj server=ba_local::server();Obj enqueue=actors::method(server,"EnqueueInputCommand",1,0x06001115,0x3e53530);
    order.command=std::make_unique<Root>(command.get());const auto sampled=base::stamp();const auto tick=GetTickCount64();
    void* input[]={command.get()};actors::invoke(enqueue,server,input);owned(owner);order.enqueuedUs=base::stamp();order.queued=true;
    require(base::pending(owner)==1,"close formation original enqueue did not grow by exactly one ICommand");
    uint32_t bits[3]{};memcpy(bits,&target,sizeof(bits));std::ostringstream out;out<<common("move_queued",owner,&order,sampled,tick)
       <<",\"source_ids\":"<<base::idsJson(sources)<<",\"incarnations\":[";
    for(size_t i=0;i<values.size();++i){if(i)out<<',';out<<values[i].token;}
    out<<"],\"origins\":[";for(size_t i=0;i<values.size();++i){if(i)out<<',';out<<original::pointJson(values[i].position);}
    out<<"],\"origins_sampled_us\":[";for(size_t i=0;i<values.size();++i){if(i)out<<',';out<<values[i].sampled;}
    out<<"],\"target\":"<<original::pointJson(target)<<",\"target_bits\":["<<bits[0]<<','<<bits[1]<<','<<bits[2]
       <<"],\"command\":"<<cohort::pointer(command.get())<<",\"command_class\":\"Uncapped.ExecuteTargetGroundCommand\",\"queued\":false,\"ability\":12"
       <<",\"queue_before\":0,\"queue_after\":1,\"originalCtor\":true,\"original_callback\":\"Uncapped.ExecuteTargetGroundCommand..ctor\""
       <<",\"enqueue_sampled_us\":"<<order.enqueuedUs<<perspective.json()<<",\"physicalUI\":false}";ba::log("CLOSE FORMATION %s",out.str().c_str());
}
void tick() {
    if(!enabled())return;
    try {
        requireFlags();const auto world=worker::movementWorldId();const auto& match=worker::movementMatchId();auto& s=state();
        if(!world||match.empty()){s=State{};return;}
        auto& owner=actors::state();if(owner.world!=world||owner.match!=match||!owner.manager||!owner.simulation)return;
        if(s.world!=world||s.match!=match) {
            s=State{};s.world=world;s.match=match;
            // Initialize only the diagnostic owner tuple used by shared helpers;
            // ordinary actor/selection state and singleton fixture stages are untouched.
            base::state()=base::State{};base::state().world=world;base::state().match=match;
            s.selector=std::make_unique<Root>(ba_prediction_actor_smoke::selectorFor(owner));
            for(unsigned i=0;i<3;++i)s.orders[i].tag=static_cast<policy::Tag>(i);
        }
        if(s.failed||s.complete)return;owned(owner);if(ba_lan::matchEnded)return;
        require(ba::unified()&&ba::community()&&ba::dedicated()&&ba::lan()&&ba_lan::originalCommandScheduling()&&ba_lan::running&&!ba_lan::publicMatch&&
            (ba::lanSlot()==0||ba::lanSlot()==1),"close formation requires negotiated two-human Custom");
        const int current=frame(owner);if(current<130)return;Obj selector=s.selector->get();
        if(!s.setup){require(current==130,"close formation missed initial selection130");setup(owner,selector);return;}
        for(auto& order:s.orders)if(policy::slot(order.tag)==static_cast<unsigned>(ba::lanSlot())&&!order.queued&&current>=policy::at(order.tag)) {
            require(current==policy::at(order.tag),"close formation missed exact original order frame");snapshot("sample",owner,selector);move(owner,selector,order);return;
        }
        if(current>=360) {
            require(current==360,"close formation missed completion360");
            for(const auto& order:s.orders)if(policy::slot(order.tag)==static_cast<unsigned>(ba::lanSlot()))
                require(order.queued&&order.serialized&&order.registered,"close formation lacks normal original order/batch receipt");
            snapshot("complete",owner,selector);s.complete=true;return;
        }
        if(current!=s.lastFrame||GetTickCount64()-s.lastSample>=15)snapshot("sample",owner,selector);
    } catch(const std::exception& error){state().failed=true;ba::log("Close formation smoke failed: reason=%s physicalUI=0",error.what());worker::movementFail(error.what());}
    catch(...){state().failed=true;ba::log("Close formation smoke failed: reason=unknown physicalUI=0");worker::movementFail("unknown close formation diagnostic exception");}
}
void serialized(void* command,void* action,uint64_t sequence,int sourceNextFrame,unsigned actionIndex) {
    if(!enabled())return;auto& s=state();
    for(auto& order:s.orders)if(order.command&&order.command->get()==command) {
        auto& owner=actors::state();owned(owner);
        require(!s.failed&&order.queued&&!order.serialized&&action&&sequence&&base::stamp()>=order.enqueuedUs,
            "close formation normal serializer duplicate/early/unbound");
        order.action=std::make_unique<Root>(action);order.sequence=sequence;order.actionIndex=actionIndex;order.serialized=true;
        const auto text=common("serialized",owner,&order)+",\"command\":"+cohort::pointer(command)+",\"action\":"+cohort::pointer(action)+
            ",\"sequence\":"+std::to_string(sequence)+",\"source_next_frame\":"+std::to_string(sourceNextFrame)+",\"action_index\":"+std::to_string(actionIndex)+",\"physicalUI\":false}";
        ba::log("CLOSE FORMATION %s",text.c_str());return;
    }
}
void registered(uint64_t sequence,int assigned,const std::vector<uint8_t>& body) {
    if(!enabled())return;auto& s=state();
    for(auto& order:s.orders)if(order.serialized&&order.sequence==sequence) {
        auto& owner=actors::state();owned(owner);require(!s.failed&&!order.registered,"close formation67 batch repeated");
        const auto raw=cohort::policy::action(body,order.actionIndex);order.registered=true;
        const auto text=common("batch_registered",owner,&order)+",\"command\":"+cohort::pointer(order.command->get())+",\"action\":"+cohort::pointer(order.action->get())+
            ",\"sequence\":"+std::to_string(sequence)+",\"speculative_frame\":"+std::to_string(assigned)+",\"action_index\":"+std::to_string(order.actionIndex)+
            ",\"action_sha256\":\""+original::digest(raw)+"\",\"body_sha256\":\""+original::digest(body)+"\",\"physicalUI\":false}";
        ba::log("CLOSE FORMATION %s",text.c_str());return;
    }
}
void authoritative(const std::vector<uint8_t>& raw,const std::string& wireSha) {
    if(!enabled())return;const auto sampled=base::stamp();const auto tick=GetTickCount64();auto& s=state();
    if(!s.world||s.world!=worker::movementWorldId()||s.match!=worker::movementMatchId()||s.failed)return;
    Root message(ba_lan::parse("InputActions",raw));const int canonical=ba::get<int>(message.get(),"gameFrame_");if(canonical<130||canonical>380)return;
    require(wireSha.size()==64&&wireSha.find_first_not_of("0123456789abcdef")==std::string::npos,"close formation65 wire hash differs");
    const auto text=common("authority",actors::state(),nullptr,sampled,tick)+",\"canonical_frame\":"+std::to_string(canonical)+
        ",\"wire_sha256\":\""+wireSha+"\",\"canonical_sha256\":\""+original::digest(raw)+"\",\"physicalUI\":false}";
    ba::log("CLOSE FORMATION %s",text.c_str());
}
}
