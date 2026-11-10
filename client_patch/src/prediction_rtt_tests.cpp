// Real community decoder/poller with an authored monotonic clock/wire sink.
// No native game, sockets, installed client, assets or live server are used.
#include "prediction_pacing.hpp"
#include "community_wire.hpp"
#include <cassert>
#include <deque>
#include <iostream>
using ULONGLONG=unsigned long long;
namespace p=ba_prediction_pacing;
static uint64_t nowUs=0;
static ULONGLONG GetTickCount64(){return nowUs/1000;}
namespace ba_public {static void controlReset(){}}
namespace ba_client {static void controlReset(){}}
namespace ba_lan {
struct Sent {unsigned char kind;std::vector<unsigned char> body;};
static std::vector<Sent> packets;
static p::RoundTrips samples;
static p::RefreshRequests refresh;
static uint64_t generation=0,lastDirectory=0;
static std::optional<uint64_t> otherReply;
static bool feature=true,active=true;
static void ensure(uint64_t current) {
    if(generation!=current){samples.reset(current);refresh.reset(current);otherReply.reset();generation=current;}
}
static bool movementPacingRequested(){return feature;}
static uint64_t movementPacingNowUs(){return nowUs;}
static void resetMovementRoundTrips(){samples={};refresh={};generation=lastDirectory=0;otherReply.reset();}
static bool movementRefreshActive(){return active;}
static bool movementRefreshDue(uint64_t current,uint64_t now,bool capacity){ensure(current);return refresh.due(current,now,capacity,otherReply);}
static void movementRefreshSent(uint64_t current,uint32_t id,uint64_t now){refresh.sent(current,id,now);}
static void movementDirectoryReceived(uint64_t bytes){refresh.directoryBytes(bytes);}
static void movementRoundTrip(uint64_t current,unsigned char kind,uint32_t id,uint64_t start,uint64_t stop) {
    ensure(current);
    const bool owned=kind==ba_community_wire::Refresh && refresh.tracks(current,id);
    lastDirectory=owned?refresh.directoryBytes():0;
    if(owned)assert(refresh.complete(current,id,stop));
    const bool accepted=samples.observe(current,start,stop);
    if(accepted && !owned)otherReply=stop;
}
static std::string authenticatedProfile(){return "rtt_test";}
static void send(unsigned char kind,const std::vector<unsigned char>& data){packets.push_back({kind,data});}
}
#include "community_transport.cpp"
namespace c=ba_community;
namespace w=ba_community_wire;
static unsigned cases=0;
template<class Fn> static bool refused(Fn fn){try{fn();return false;}catch(const std::exception&){return true;}}
static void setup(bool feature=true,bool active=true) {
    ba_lan::feature=true;c::reset();nowUs=0;ba_lan::packets.clear();
    ba_lan::feature=feature;ba_lan::active=active;assert(c::player("absent")==nullptr);
    w::Writer greeting;greeting.number(1,2);greeting.number(3,2);greeting.id("rtt_test");greeting.deck({1,2,3,4,5,6,7,8});
    c::receive(w::WelcomeKind,greeting.bytes);
}
static w::Bytes ack(uint32_t id,unsigned char kind=w::Refresh) {
    w::Writer out;out.number(id,4);out.number(kind,1);out.number(1,1);out.text("");out.text("");return out.bytes;
}
static void risingAndFalling() {
    p::RoundTrips r;r.reset(1);assert(r.observe(1,0,130000));
    r.observe(1,6000000,6475000);r.observe(1,8000000,8475000);
    assert(*r.estimate()==475000); // Exact authored RED against former min8.
    assert(p::assignmentTarget(299,8475000,8475000,*r.estimate()).assigned==309);++cases;
    assert(r.observe(1,9000000,9130000));assert(*r.estimate()==130000);
    assert(p::assignmentTarget(299,9130000,9130000,*r.estimate()).assigned==302);++cases;
}
static void jitterAndPositiveOutlier() {
    p::RoundTrips r;r.reset(1);r.observe(1,0,130000);
    r.observe(1,2000000,2900000);assert(*r.estimate()==130000);
    assert(*r.estimate(4200000)==130000); // One larger sample alone cannot raise.
    r.observe(1,4270000,4400000);assert(*r.estimate()==130000);++cases;
    r.reset(1);r.observe(1,0,130000);
    r.observe(1,3700000,4100000);r.observe(1,3800000,4200000);
    assert(*r.estimate()==130000); // Two ACKs in a UI burst lack support span.
    r.observe(1,4600000,5000000);assert(*r.estimate()==400000);++cases;
    r.reset(1);r.observe(1,0,475000);r.observe(1,1000000,1490000);
    r.observe(1,2000000,2470000);r.observe(1,3000000,4500000);
    assert(*r.estimate()==470000);assert(r.count()<=8);++cases;
}
static void pauseRematchAndTime() {
    p::RoundTrips r;r.reset(9);r.observe(9,0,130000);
    assert(*r.estimate(1000000)==130000); // Valid short same-connection rematch.
    assert(!r.estimate(5000000) && r.count()==0);
    assert(!r.observe(9,1000000,5100000));assert(!r.estimate()); // Paused old request.
    assert(r.observe(9,5200000,5675000));assert(*r.estimate()==475000);++cases;
    const auto saved=r.estimate();
    assert(!r.observe(8,6000000,6130000));assert(r.estimate()==saved);
    assert(!r.observe(9,5500000,5600000));assert(r.estimate()==saved);
    assert(refused([&]{r.estimate(5600000);}));assert(r.estimate()==saved);
    r.reset(10);assert(!r.estimate() && !r.observe(9,6000000,6130000));++cases;
}
static void schedulerBounds() {
    p::RefreshRequests q;q.reset(2);
    assert(!q.due(2,0,false,std::nullopt));assert(q.due(2,0,true,std::nullopt));
    q.sent(2,1,0);assert(!q.due(2,10000000,true,std::nullopt)); // One outstanding.
    assert(!q.complete(1,1,10000000));assert(!q.complete(2,2,10000000));
    assert(q.complete(2,1,10000000));assert(q.due(2,10000000,true,std::nullopt));
    q.sent(2,2,10000000);assert(refused([&]{q.sent(2,3,10000001);}));
    q.complete(2,2,10475000);
    assert(!q.due(2,11999999,true,std::nullopt));assert(q.due(2,12000000,true,std::nullopt));++cases;
    assert(!q.due(2,12000000,true,11000000)); // Reuse recent existing ACK traffic.
    assert(refused([&]{q.due(2,11999999,true,std::nullopt);}));
    assert(refused([&]{q.due(3,12000000,true,std::nullopt);}));++cases;
}
static void inactiveAndCapacity() {
    for(unsigned context=0;context<3;++context) {
        setup(context!=0,false); // Ordinary, menu, public/non-owned are inactive.
        nowUs=10000000;c::pollMovementRefresh();
        assert(ba_lan::packets.empty() && c::requestId==0 && c::pending.empty());
    }
    setup();for(unsigned i=0;i<32;++i)c::send(w::refresh(c::nextRequest()));
    c::pollMovementRefresh();assert(ba_lan::packets.size()==32 && c::requestId==32);++cases;
}
static void actualCorrelationAndRoster() {
    setup();c::pollMovementRefresh();assert(ba_lan::packets.size()==1 && c::pending.size()==1);
    const auto id=c::requestId;
    assert(ba_lan::packets.back().kind==w::Refresh && ba_lan::packets.back().body.size()+5==9);
    nowUs=130000;
    assert(refused([&]{c::receive(w::AckKind,ack(id+1));}));
    assert(refused([&]{c::receive(w::AckKind,ack(id,w::Leave));}));
    assert(ba_lan::refresh.pending()==id && !ba_lan::samples.estimate());
    w::Writer directory;directory.number(1,8);directory.number(1,2);directory.id("rtt_test");
    directory.text("Player");directory.number(3,1);directory.number(0,1);
    c::receive(w::DirectoryKind,directory.bytes);c::receive(w::AckKind,ack(id));
    assert(ba_lan::lastDirectory==directory.bytes.size()+5 && ba_lan::refresh.pending()==0);
    assert(*ba_lan::samples.estimate()==130000 && ack(id).size()+5==15);
    assert(refused([&]{c::receive(w::AckKind,ack(id));}));assert(ba_lan::samples.count()==1);
    c::checkTimeouts();++cases;
}
static void noSampleAcquisitionAndExistingTraffic() {
    setup();nowUs=3000000;c::pollMovementRefresh();
    const auto id=c::requestId;assert(!ba_lan::samples.estimate());
    c::pollMovementRefresh();assert(ba_lan::packets.size()==1);
    nowUs=3475000;c::receive(w::AckKind,ack(id));assert(*ba_lan::samples.estimate()==475000);
    p::Policy phase;phase.authorityReceived(0,3000000);
    auto zero=phase.decide(0,-1,-1,3000000,std::nullopt);assert(zero.allowed);phase.queued(zero);phase.published(0,3100000);
    phase.authorityReceived(1,3475000);
    assert(phase.decide(1,0,0,3475000,ba_lan::samples.estimate(nowUs)).allowed);++cases;
    setup();const auto own=c::send(w::refresh(c::nextRequest()));
    c::pollMovementRefresh();assert(ba_lan::packets.size()==1); // Reuse an existing outstanding request too.
    nowUs=130000;c::receive(w::AckKind,ack(own));assert(ba_lan::otherReply==130000);
    nowUs=2129999;c::pollMovementRefresh();assert(ba_lan::packets.size()==1);
    nowUs=2130000;c::pollMovementRefresh();assert(ba_lan::packets.size()==2);++cases;
}
static void changingPathWithRealPoller() {
    setup();uint32_t response=0;uint64_t responseAt=0,riseAt=0,fallAt=0;
    std::vector<uint64_t> sends;
    for(nowUs=0;nowUs<=30000000;nowUs+=1000) {
        if(response && nowUs>=responseAt){c::receive(w::AckKind,ack(response));response=0;}
        const auto before=ba_lan::packets.size();c::pollMovementRefresh();
        if(ba_lan::packets.size()!=before) {
            assert(!response);response=c::requestId;
            const auto rtt=nowUs>=8000000 && nowUs<20000000?475000ull:130000ull;
            responseAt=nowUs+rtt;sends.push_back(nowUs);
        }
        auto value=ba_lan::samples.estimate(nowUs);
        if(nowUs>=8000000 && value && *value==475000 && !riseAt)riseAt=nowUs;
        if(nowUs>=20000000 && value && *value==130000 && !fallAt)fallAt=nowUs;
    }
    assert(riseAt>=8000000 && riseAt<=13500000);assert(fallAt>=20000000 && fallAt<=22500000);
    for(size_t i=1;i<sends.size();++i)assert(sends[i]-sends[i-1]>=2000000);
    assert(sends.size()<=16);
    std::cout<<"changing-path model rise_ms="<<riseAt/1000<<" fall_ms="<<fallAt/1000
             <<" refreshes="<<sends.size()<<" interval_min_ms=2000\n";++cases;
}
int main() {
    risingAndFalling();jitterAndPositiveOutlier();pauseRematchAndTime();schedulerBounds();
    inactiveAndCapacity();actualCorrelationAndRoster();noSampleAcquisitionAndExistingTraffic();changingPathWithRealPoller();
    std::cout<<"PASS "<<cases<<" changing-RTT/real-control cases; authored timing/wire only\n";
}
