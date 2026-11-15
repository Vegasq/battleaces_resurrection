#include "original_command_scheduling.hpp"
#include <cassert>
#include <iostream>
#include <functional>

namespace q=ba_original_commands;
static const std::string first="0123456789abcdef0123456789abcdef";
static const std::string second="abcdef0123456789abcdef0123456789";
static void rejects(const std::function<void()>& action) {
    bool failed=false;try{action();}catch(const std::runtime_error&){failed=true;}assert(failed);
}
int main() {
    assert(q::firstOutputReady==74);
    assert(!q::validateContext(false,false,false,false));
    assert(!q::canStart(false,1) && q::canStart(false,2));
    assert(!q::canStart(true,0) && q::canStart(true,1));
    assert(q::validateContext(true,true,true,true));
    rejects([]{q::validateContext(true,false,true,true);});
    rejects([]{q::validateContext(true,true,false,true);});
    rejects([]{q::validateContext(true,true,true,false);});
    assert(q::version==1 && q::capability==2 && q::negotiation()==q::Bytes{2});
    for(unsigned mode:{0u,3u,4u,255u})assert(!q::allowsPublic(mode));
    assert(q::allowsLocalFallback(false,false) && q::allowsLocalFallback(false,true));
    assert(q::allowsLocalFallback(true,false) && !q::allowsLocalFallback(true,true));
    for(unsigned mode:{1u,2u,5u}) {
        assert(q::allowsPublic(mode));
        const unsigned count=mode==1?2:4,allowed=mode==5?5:(1u<<count)-1;
        for(unsigned slot=0;slot<count;++slot)for(unsigned mask=0;mask<16;++mask) {
            if((mask&(1u<<slot)) && !(mask&~allowed))assert(q::publicArrivalMode(mode,count,slot,mask));
            else rejects([&]{q::publicArrivalMode(mode,count,slot,mask);});
        }
    }
    rejects([]{q::publicArrivalMode(1,2,2,4);});
    rejects([]{q::publicArrivalMode(1,4,0,1);});
    rejects([]{q::publicArrivalMode(2,2,0,1);});
    rejects([]{q::publicArrivalMode(0,2,0,1);});
    q::State publicState;
    rejects([&]{publicState.assignPublic(first,0,1,2,0,1);});
    publicState.request();publicState.acknowledge({2});
    assert(publicState.ready() && !publicState.assigned() && !publicState.heartbeat(0));
    rejects([&]{publicState.start(0);}); // Capability alone cannot activate command batches or READY.
    assert(publicState.assignPublic(first,0,1,2,0,3));
    assert(publicState.assigned());publicState.start(0);publicState.applied(0);
    assert(publicState.firstOutputReady(0)); // Public humans use the same scheduling contract.
    publicState.clearMatch();
    assert(publicState.assignPublic(second,100,1,2,0,1));
    assert(publicState.assigned() && publicState.heartbeat(100));
    publicState.start(100);publicState.applied(0);
    assert(publicState.firstOutputReady(0));
    publicState.clearMatch();
    assert(publicState.assignPublic(first,200,5,4,2,5));
    assert(publicState.assigned() && publicState.heartbeat(200)); // AI-to-coop keeps arrival mode with fresh state.
    publicState.start(200);assert(publicState.sequence()==1 && publicState.lastApplied()==-1);
    publicState.applied(0);assert(publicState.firstOutputReady(0));
    q::State state;
    rejects([&]{state.acknowledge({1});});
    rejects([&]{state.assign(first,0);});
    state.request();assert(state.pending() && !state.ready());
    rejects([&]{state.request();});
    rejects([&]{state.acknowledge({});});
    rejects([&]{state.acknowledge({1,1});});
    rejects([&]{state.acknowledge({1});}); // Old Custom-only hosts cannot silently accept the new scope.
    state.acknowledge({2});assert(state.ready() && !state.pending());
    rejects([&]{state.acknowledge({1});});
    state.assign(first,100);
    rejects([&]{state.batch({0x0a},1);});
    rejects([&]{state.firstOutputReady(0);});
    auto heartbeat=state.heartbeat(100);
    assert(heartbeat && heartbeat->size()==37 && (*heartbeat)[0]==1);
    assert(std::string(heartbeat->begin()+1,heartbeat->begin()+33)==first);
    for(size_t i=33;i<37;++i)assert((*heartbeat)[i]==0xff);
    assert(!state.heartbeat(1099));
    assert(state.heartbeat(1100)); // Liveness does not require presentation/start.
    state.start(1200);
    assert(state.sequence()==1 && state.lastApplied()==-1);
    assert(state.heartbeat(1200)); // START resets its heartbeat deadline.
    assert(!state.firstOutputReady(-1));
    assert(!state.firstOutputReady(0)); // A stale presented counter is not this match's output.
    assert(!state.batch({},0) && state.sequence()==1); // Retail idle sends no batch.
    assert(state.smoke(0) && !state.smoke(0));
    auto batch=state.batch({0x0a,0x00},1);
    assert(batch && batch->sequence==1 && state.sequence()==2 && batch->payload.size()==43);
    assert(batch->payload[0]==1 && std::string(batch->payload.begin()+1,batch->payload.begin()+33)==first);
    assert(batch->payload[33]==1);
    for(size_t i=34;i<41;++i)assert(batch->payload[i]==0);
    assert(batch->payload[41]==0x0a && batch->payload[42]==0);
    // Commands/heartbeat progress even when the authoritative view is held.
    assert(state.batch({0x12},1)->sequence==2 && state.lastApplied()==-1);
    assert(!state.firstOutputReady(-1)); // Applying/queuing input is not presentation.
    assert(state.heartbeat(2200));
    state.applied(0);state.applied(1);
    assert(!state.firstOutputReady(-1)); // Even applied frames cannot bypass publication.
    auto outputReady=state.firstOutputReady(0);
    assert(outputReady && outputReady->size()==33 && (*outputReady)[0]==1);
    assert(std::string(outputReady->begin()+1,outputReady->end())==first);
    assert(!state.firstOutputReady(0) && !state.firstOutputReady(1));
    assert(state.lastApplied()==1 && state.smoke(2) && !state.smoke(2));
    rejects([&]{state.applied(1);});
    rejects([&]{state.applied(3);});
    heartbeat=state.heartbeat(3200);assert(heartbeat && (*heartbeat)[33]==1 && (*heartbeat)[34]==0);
    rejects([&]{state.batch({},1);});
    rejects([&]{state.batch(q::Bytes(65537),1);});
    rejects([&]{state.batch({1},257);});
    state.clearMatch();assert(state.ready() && state.match().empty() && !state.heartbeat(9000));
    rejects([&]{state.acknowledge({1});}); // Rematch preserves the acknowledged session.
    state.assign(second,9000);state.start(9010);
    assert(state.sequence()==1 && state.lastApplied()==-1 && state.smoke(0));
    assert(!state.firstOutputReady(-1));
    assert(!state.firstOutputReady(0));
    state.applied(0);
    assert(state.firstOutputReady(0) && !state.firstOutputReady(1));
    assert(state.batch({1},1)->sequence==1);
    state.disconnect();assert(!state.ready() && !state.pending() && state.match().empty());
    rejects([&]{state.firstOutputReady(0);});
    rejects([&]{state.acknowledge({1});}); // Stale ACK after stream closure.
    state.request();state.acknowledge({2});state.assign(first,0);state.start(0);
    assert(state.batch({1},1)->sequence==1);
    for(const std::string& invalid:{std::string(),std::string(31,'a'),std::string(33,'a'),std::string(32,'G')})
        rejects([&]{q::encodeBatch(invalid,1,{1});});
    rejects([&]{q::encodeOutputReady("bad");});
    rejects([&]{state.firstOutputReady(-2);});
    rejects([&]{q::encodeBatch(first,0,{1});});
    const auto encoded=q::encodeBatch(first,0x0807060504030201ull,{0x7f});
    for(size_t i=0;i<8;++i)assert(encoded[33+i]==i+1);
    const auto hb=q::encodeHeartbeat(first,0x01020304);
    assert(hb[33]==4 && hb[34]==3 && hb[35]==2 && hb[36]==1);
    rejects([&]{q::encodeHeartbeat(first,-2);});
    std::cout<<"Original command scheduling state/wire tests passed\n";
}
