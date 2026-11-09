#define WIN32_LEAN_AND_MEAN
#include <windows.h> // Match integration include order, including min/max macros.
#include "prediction_schedule.hpp"
#include <algorithm>
#include <array>
#include <cstdlib>
#include <deque>
#include <functional>
#include <iostream>
#include <new>
#include <set>
#include <sstream>
#include <type_traits>

namespace p=ba_prediction_schedule;
// Test-executable-only allocator faults. No hook or allocator override ships in
// the policy header. All cases are single-threaded; arm only around one action.
static std::ptrdiff_t allocationCountdown=-1;
void* operator new(std::size_t size) {
    if(allocationCountdown==0)throw std::bad_alloc();
    if(allocationCountdown>0)--allocationCountdown;
    if(void* result=std::malloc(size?size:1))return result;
    throw std::bad_alloc();
}
void operator delete(void* pointer)noexcept{std::free(pointer);}
void operator delete(void* pointer,std::size_t)noexcept{std::free(pointer);}
static void check(bool condition,const char* message) {
    if(!condition)throw std::runtime_error(message);
}
static p::Bytes idle(){return {0x0a,1,7};}
static p::Bytes order(){return {0x0a,1,7,0x12,1,42};}
static p::InputBody input(p::Frame frame) {
    return frame%17==0?p::InputBody{order(),1}:p::InputBody{idle(),0};
}
static std::vector<p::InputBody> startup(std::size_t count) {
    std::vector<p::InputBody> result;
    for(std::size_t index=0;index<count;++index)result.push_back(input(static_cast<p::Frame>(index)));
    return result;
}
static std::string snapshot(const p::InputCreditPlanner& planner) {
    const auto m=planner.metrics();std::ostringstream out;
    out<<m.submissions<<','<<m.receipts<<','<<m.confirmations<<','<<m.matched<<','<<m.normalized<<','
       <<m.peak_pending_inputs<<','<<m.peak_authority_backlog<<','<<m.peak_buffered_bytes<<','
       <<planner.next_input_frame()<<','<<planner.received_frame()<<','<<planner.confirmed_frame()<<','
       <<planner.predicted_frame()<<','<<planner.available_credits()<<','<<planner.buffered_bytes()<<','
       <<planner.retired();
    for(const auto& value:planner.pending_inputs()) {
        out<<";P"<<value.frame()<<':'<<value.action_count();
        for(auto byte:value.body())out<<':'<<static_cast<unsigned>(byte);
    }
    for(const auto& value:planner.authority_backlog()) {
        out<<";A"<<value.frame()<<':'<<value.submitted_action_count()<<':'<<value.canonical_action_count();
        for(auto byte:value.submitted_body())out<<':'<<static_cast<unsigned>(byte);
        out<<'/';for(auto byte:value.canonical_body())out<<':'<<static_cast<unsigned>(byte);
    }
    return out.str();
}
static void rejects(const std::function<void()>& action) {
    bool rejected=false;try{action();}catch(const p::InputCreditError&){rejected=true;}
    check(rejected,"invalid scheduler operation accepted");
}
static void atomicReject(p::InputCreditPlanner& planner,const std::function<void()>& action) {
    const auto before=snapshot(planner);rejects(action);
    check(snapshot(planner)==before,"rejected operation mutated planner");
}
static void startupWindowsAndPayload() {
    for(std::uint32_t window:{6U,12U}) {
        p::InputCreditPlanner planner(window);const auto seeded=planner.seed(startup(window));
        check(seeded.size()==window && planner.pending_inputs().size()==window,"startup count differs from own window");
        for(std::size_t index=0;index<seeded.size();++index) {
            const auto payload=seeded[index].payload();
            check(seeded[index].frame()==static_cast<p::Frame>(index),"startup frame gap");
            check(payload.size()==seeded[index].body().size()+4 && payload[0]==static_cast<std::uint8_t>(index) &&
                  payload[1]==0 && payload[2]==0 && payload[3]==0,"existing INPUT wire header changed");
            check(p::Bytes(payload.begin()+4,payload.end())==seeded[index].body(),"INPUT payload changed supplied body");
        }
        check(planner.available_credits()==0 && planner.received_frame()==-1 &&
              planner.confirmed_frame()==-1 && planner.predicted_frame()==-1,"startup minted cursor progress");
        atomicReject(planner,[&]{planner.submit(idle(),0);});
    }
}
static void creditsArePermissionAndCursorsAreSeparate() {
    p::InputCreditPlanner planner(6);planner.seed(startup(6));
    for(p::Frame frame=0;frame<12;++frame)planner.mark_predicted(frame);
    check(planner.available_credits()==0,"prediction minted input credit");
    planner.observe_authority(0,order(),1);
    check(planner.received_frame()==0 && planner.confirmed_frame()==-1 && planner.predicted_frame()==11 &&
          planner.available_credits()==1,"receipt advanced wrong cursor");
    planner.mark_confirmed(0);planner.mark_predicted(12);
    check(planner.available_credits()==1,"confirmation/speculation spent or minted credit");
    planner.observe_authority(1,idle(),0);planner.mark_confirmed(1);
    check(planner.available_credits()==2 && planner.next_input_frame()==6,"receipt forced immediate input");
    check(planner.submit(idle(),0).frame()==6 && planner.submit(idle(),0).frame()==7 &&
          planner.available_credits()==0,"deferred credits lost or exceeded");
    atomicReject(planner,[&]{planner.observe_authority(1,idle(),0);});
}
static void immutableBodiesAndNormalization() {
    static_assert(std::is_same_v<decltype(std::declval<const p::ScheduledInput&>().body()),const p::Bytes&>);
    p::InputCreditPlanner planner(6);auto supplied=order();auto sent=planner.submit(supplied,1);
    supplied[0]=0xff;auto payload=sent.payload();payload.back()=0xff;
    check(planner.pending_inputs()[0].body()==order(),"caller rewrote pending bytes");
    auto canonical=idle();const auto receipt=planner.observe_authority(0,canonical,0);canonical[0]=0xff;
    check(receipt.frame()==0 && receipt.submitted_body()==order() && receipt.canonical_body()==idle() &&
          receipt.submitted_action_count()==1 && receipt.canonical_action_count()==0 &&
          !receipt.matched() && receipt.normalized() && receipt.noop(),"normalization lost frame/disposition");
    planner.mark_confirmed(0);
    check(receipt.submitted_body()==order() && planner.buffered_bytes()==0,"receipt lifetime depended on pending entry");
    const auto first=planner.submit(order(),1),second=planner.submit(order(),1);
    check(first.frame()==1 && second.frame()==2 && first.body()==second.body(),"identical actions were deduplicated");
}
static void invalidFramesAndKnownAuthority() {
    p::InputCreditPlanner planner(6);
    atomicReject(planner,[&]{planner.observe_authority(0,idle(),0);});
    planner.seed(startup(6));
    for(p::Frame bad:{p::Frame(-1),p::Frame(1),p::Frame(7),p::MAX_FRAME+1})
        atomicReject(planner,[&]{planner.observe_authority(bad,idle(),0);});
    planner.observe_authority(0,order(),1);
    atomicReject(planner,[&]{planner.mark_predicted(0);});
    atomicReject(planner,[&]{planner.mark_confirmed(1);});
    planner.mark_confirmed(0);
    for(p::Frame bad:{p::Frame(-1),p::Frame(5),p::Frame(7),p::MAX_FRAME+1})
        atomicReject(planner,[&]{planner.submit(idle(),0,bad);});
    atomicReject(planner,[&]{planner.observe_authority(0,order(),1);});
    atomicReject(planner,[&]{planner.mark_confirmed(0);});
    atomicReject(planner,[&]{planner.mark_predicted(p::MAX_FRAME+1);});
}
static void predictionBoundsAndRollback() {
    p::Limits limits;limits.max_prediction_ahead=2;p::InputCreditPlanner planner(6,limits);
    planner.seed(startup(6));planner.mark_predicted(0);planner.mark_predicted(1);
    atomicReject(planner,[&]{planner.mark_predicted(2);});
    planner.observe_authority(0,order(),1);planner.mark_confirmed(0);planner.mark_predicted(2);
    check(planner.rollback_prediction()==2 && planner.predicted_frame()==0 &&
          planner.available_credits()==1,"rollback changed authority credit");
    planner.mark_predicted(1);check(planner.available_credits()==1,"replaying prediction minted credit");
}
static void startupAndCapacityFaults() {
    for(std::size_t count:{5U,7U}) {
        p::InputCreditPlanner planner(6);atomicReject(planner,[&]{planner.seed(startup(count));});
    }
    p::InputCreditPlanner malformed(6);auto inputs=startup(6);inputs.back().action_count=257;
    atomicReject(malformed,[&]{malformed.seed(inputs);});
    p::Limits bytes;bytes.max_buffered_bytes=20;p::InputCreditPlanner limited(6,bytes);
    auto large=startup(6);large[0].body=p::Bytes(21,1);
    atomicReject(limited,[&]{limited.seed(large);});
    limited.seed(std::vector<p::InputBody>(6,p::InputBody{idle(),0}));
    atomicReject(limited,[&]{limited.observe_authority(0,idle(),0);});
    p::Limits backlog;backlog.max_authority_backlog=2;p::InputCreditPlanner queued(6,backlog);
    queued.seed(startup(6));queued.observe_authority(0,order(),1);queued.observe_authority(1,idle(),0);
    atomicReject(queued,[&]{queued.observe_authority(2,idle(),0);});
    queued.mark_confirmed(0);queued.observe_authority(2,idle(),0);
    check(queued.received_frame()==2,"confirmation failed to release backlog capacity");
}
static void bodyAndConfigurationLimits() {
    p::InputCreditPlanner empty(6);empty.submit({},0);
    check(empty.observe_authority(0,idle(),0).normalized(),"explicit empty input did not map to canonical identity");
    p::InputCreditPlanner planner(6);
    atomicReject(planner,[&]{planner.submit(p::Bytes(65537,1),0);});
    atomicReject(planner,[&]{planner.submit(idle(),257);});
    atomicReject(planner,[&]{planner.submit({},1);});
    planner.submit(p::Bytes(65536,1),256); // Envelope/identity validation belongs to the caller.
    atomicReject(planner,[&]{planner.observe_authority(0,{},0);});
    atomicReject(planner,[&]{planner.observe_authority(0,idle(),257);});
    planner.observe_authority(0,idle(),0);
    for(std::uint32_t window:{0U,1U,13U,0xffffffffU})rejects([&]{p::InputCreditPlanner invalid(window);});
    for(unsigned which=0;which<6;++which) {
        p::Limits limits;
        if(which==0)limits.max_prediction_ahead=0;
        if(which==1)limits.max_prediction_ahead=121;
        if(which==2)limits.max_authority_backlog=0;
        if(which==3)limits.max_authority_backlog=65;
        if(which==4)limits.max_buffered_bytes=0;
        if(which==5)limits.max_buffered_bytes=33U*1024U*1024U;
        rejects([&]{p::InputCreditPlanner invalid(6,limits);});
    }
}
static void retirementAndRematch() {
    p::InputCreditPlanner old(6);old.seed(startup(6));old.observe_authority(0,order(),1);old.retire();
    check(old.available_credits()==0 && old.buffered_bytes()==0 && old.pending_inputs().empty() &&
          old.authority_backlog().empty(),"retired match retained pending bodies/credit");
    atomicReject(old,[&]{old.submit(idle(),0);});
    atomicReject(old,[&]{old.observe_authority(1,idle(),0);});
    atomicReject(old,[&]{old.mark_confirmed(0);});
    atomicReject(old,[&]{old.mark_predicted(0);});
    atomicReject(old,[&]{old.rollback_prediction();});
    atomicReject(old,[&]{old.seed(startup(6));});
    p::InputCreditPlanner fresh(12);fresh.seed(startup(12));fresh.observe_authority(0,order(),1);
    check(fresh.received_frame()==0 && fresh.confirmed_frame()==-1 && fresh.available_credits()==1,
          "new match inherited old cursors or own window");
}
static void failEachAllocation(std::uint32_t window,const std::function<void(p::InputCreditPlanner&)>& prepare,
                               const std::function<void(p::InputCreditPlanner&)>& action) {
    unsigned failures=0;
    for(std::ptrdiff_t position=0;position<64;++position) {
        p::InputCreditPlanner planner(window);prepare(planner);const auto before=snapshot(planner);
        bool failed=false;allocationCountdown=position;
        try{action(planner);}catch(const std::bad_alloc&){failed=true;}
        catch(...){allocationCountdown=-1;throw;}
        allocationCountdown=-1;
        if(failed){++failures;check(snapshot(planner)==before,"allocation failure partially committed planner");}
        else {check(failures>=2,"allocation fault control did not exercise owned body allocation");return;}
    }
    throw std::runtime_error("allocation fault sweep did not reach successful operation");
}
static void allocationFailureAtomicity() {
    const auto supplied=startup(6);const auto body=idle();
    failEachAllocation(6,[](auto&){},[&](auto& planner){planner.seed(supplied);});
    failEachAllocation(6,[](auto&){},[&](auto& planner){planner.submit(body,0);});
    // The ninth pending receipt also crosses a deque storage boundary on MSVC,
    // testing commit atomicity beyond the canonical bytevector's allocations.
    failEachAllocation(12,[](auto& planner){
        planner.seed(startup(12));
        for(p::Frame frame=0;frame<8;++frame){const auto value=input(frame);planner.observe_authority(frame,value.body,value.action_count);}
    },[&](auto& planner){planner.observe_authority(8,body,0);});
}
static void asymmetricTwoHundredFrames() {
    p::InputCreditPlanner fast(6),slow(12);std::array<p::InputCreditPlanner*,2> peers{&fast,&slow};
    const std::array<int,2> outbound{1,5},inbound{1,4};
    struct Message{int tick;int slot;p::ScheduledInput input;};
    std::deque<Message> arrivals,authority;std::array<std::set<p::Frame>,2> serverInputs;
    for(int slot=0;slot<2;++slot) {
        for(const auto& value:peers[slot]->seed(startup(slot==0?6U:12U)))serverInputs[slot].insert(value.frame());
        for(p::Frame frame=0;frame<12;++frame)peers[slot]->mark_predicted(frame);
    }
    p::Frame serverFrame=0;int lastPublished=-1;unsigned stalls=0,normalized=0;
    for(int tick=0;tick<400 && (fast.received_frame()<199 || slow.received_frame()<199);++tick) {
        for(auto it=authority.begin();it!=authority.end();) {
            if(it->tick>tick){++it;continue;}
            auto& planner=*peers[it->slot];const auto frame=it->input.frame();
            const auto canonical=frame==85?idle():it->input.body();
            const auto receipt=planner.observe_authority(frame,canonical,frame==85?0U:it->input.action_count());
            if(receipt.normalized()){++normalized;check(frame==85 && receipt.noop(),"unexpected normalization identity");}
            planner.mark_confirmed(frame);planner.mark_predicted(frame+12);
            const auto supplied=input(planner.next_input_frame());const auto sent=planner.submit(supplied.body,supplied.action_count);
            check(sent.frame()==frame+planner.input_window() && sent.frame()<serverFrame+planner.input_window(),
                  "own negotiated future bound exceeded");
            check(planner.available_credits()==0 && planner.pending_inputs().size()==planner.input_window(),
                  "continuous replenishment changed pending lead");
            arrivals.push_back({tick+outbound[it->slot],it->slot,sent});it=authority.erase(it);
        }
        for(auto it=arrivals.begin();it!=arrivals.end();) {
            if(it->tick>tick){++it;continue;}
            check(it->input.frame()>=serverFrame && serverInputs[it->slot].insert(it->input.frame()).second,
                  "late/duplicated server input in asymmetric run");it=arrivals.erase(it);
        }
        if(serverFrame<200) {
            if(!serverInputs[0].count(serverFrame) || !serverInputs[1].count(serverFrame)){++stalls;continue;}
            check(lastPublished<0 || tick==lastPublished+1,"asymmetric peers interrupted canonical cadence");
            lastPublished=tick;
            for(int slot=0;slot<2;++slot) {
                serverInputs[slot].erase(serverFrame);const auto supplied=input(serverFrame);
                // Retain the actual immutable submitted input; never reidentify by equal action bytes.
                const auto pending=peers[slot]->pending_inputs();
                auto found=std::find_if(pending.begin(),pending.end(),[&](const auto& value){return value.frame()==serverFrame;});
                check(found!=pending.end() && found->body()==supplied.body,"lost numbered original input");
                authority.push_back({tick+inbound[slot],slot,*found});
            }
            ++serverFrame;
        }
    }
    check(serverFrame==200 && fast.received_frame()==199 && slow.received_frame()==199 &&
          stalls==0 && normalized==2,"asymmetric 200-frame conservation failed");
    check(fast.metrics().submissions==206 && slow.metrics().submissions==212 &&
          fast.metrics().confirmations==200 && slow.metrics().confirmations==200,"asymmetric credit accounting failed");
}
int main() {
    try {
        startupWindowsAndPayload();creditsArePermissionAndCursorsAreSeparate();immutableBodiesAndNormalization();
        invalidFramesAndKnownAuthority();predictionBoundsAndRollback();startupAndCapacityFaults();
        bodyAndConfigurationLimits();retirementAndRematch();allocationFailureAtomicity();asymmetricTwoHundredFrames();
        std::cout<<"prediction schedule: 10 scenario groups PASS (200 asymmetric frames, windows6/12, allocation faults)\n";return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
