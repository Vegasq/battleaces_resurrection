#pragma once
// Include AFTER lan_transport.cpp. Enabled only by the explicit worker bridge
// option; ordinary buffered/V1 ticking and original presentation stay intact.
#include "prediction_movement.hpp"
#include "prediction_pacing.hpp"
#include <algorithm>
#include <limits>

namespace ba_prediction_movement {
using ba::Obj;
using ba_local::Root;
using Bytes=ba_lan::Bytes;
namespace worker=ba_prediction_worker;
namespace pacing=ba_prediction_pacing;
static constexpr int maximumQueuedAuthority=12;
static constexpr ULONGLONG terminalTimeoutMs=10000;
struct State {
    Obj server=nullptr,simulation=nullptr;
    DWORD owner=0;
    uint64_t world=0,connectionGeneration=0,generation=0;
    uint32_t lobbyEpoch=0;
    std::string match,lobby;
    int64_t physicalNext=0,drainTarget=-1;
    int finalAuthority=-1;
    bool prepared=false,failed=false,endSent=false,drained=false,pacingStarted=false,pacingAcquired=false;
    pacing::Policy pacing;
    ULONGLONG terminalAt=0,budgetLogAt=0;
    uint64_t phaseSampleUs=0;
    unsigned phaseRows=0;
};
static State state;
static uint64_t generations=0;
static void require(bool value,const char* reason) {if(!value)throw std::runtime_error(reason);}
struct EarlyPhase {
    pacing::Decision decision{};
    int presented=-1;
    uint64_t rtt=0,sampledUs=0,tick=0;
};
// Explicit mirror diagnostics only. The measured early prefix performs no
// extra log/file I/O or allocation; flush after that window or a real failure.
static std::array<EarlyPhase,1024> earlyPhases{};
static size_t earlyPhaseCount=0;
static bool earlyPhaseOverflow=false;
static void logPhase(const char* prefix,const EarlyPhase& row) {
    const auto& d=row.decision;
    ba::log("%s {\"schema\":1,\"event\":\"decision\",\"match\":\"%s\",\"world\":%llu,\"next\":%lld,\"target_assigned\":%lld,\"presented_frame\":%d,\"rtt_us\":%llu,\"allowed\":%s,\"wait\":%u,\"decision_us\":%llu,\"sampled_us\":%llu,\"tick_ms\":%llu}",
        prefix,state.match.c_str(),static_cast<unsigned long long>(state.world),static_cast<long long>(d.frame),
        static_cast<long long>(d.target.assigned),row.presented,static_cast<unsigned long long>(row.rtt),
        d.allowed?"true":"false",static_cast<unsigned>(d.wait),static_cast<unsigned long long>(d.now),
        static_cast<unsigned long long>(row.sampledUs),static_cast<unsigned long long>(row.tick));
}
void flushEarlyPhaseDiagnostics() noexcept {
    // Both normal window completion and the failure path run on this owner.
    // A failed diagnostic write must not replace the original game failure.
    if(!earlyPhaseCount||state.owner!=GetCurrentThreadId())return;
    const size_t count=earlyPhaseCount;const bool overflow=earlyPhaseOverflow;
    earlyPhaseCount=0;earlyPhaseOverflow=false;
    try {
        for(size_t index=0;index<count;++index)logPhase("MOVEMENT EARLY PHASE",earlyPhases[index]);
        if(overflow)ba::log("Movement early phase capture incomplete: retained=%zu capacityExceeded=1; original outcome unchanged",count);
    }
    catch(...) {}
}
static void observePhase(const pacing::Decision& decision,int presented,std::optional<uint64_t> rtt) {
    static const bool requested=ba::flag(L"-prediction-movement-smoke")&&
        !ba::argument(L"-prediction-movement-smoke-transition-gates=","").empty();
    static const bool earlyRequested=ba::flag(L"-prediction-terminal-timeline-smoke")&&
        ba::flag(L"-prediction-actor-mirror-smoke")&&ba::flag(L"-prediction-held-click-smoke");
    if(earlyRequested&&decision.frame>170)flushEarlyPhaseDiagnostics();
    const bool early=earlyRequested&&decision.frame>=100&&decision.frame<=170;
    const bool transition=requested&&ba::lanSlot()==0&&decision.frame>=400&&decision.frame<650;
    if((!early&&!transition)||decision.target.assigned<1)return;
    require(state.world&&state.owner==GetCurrentThreadId()&&state.match.size()==32&&
        state.match.find_first_not_of("0123456789abcdef")==std::string::npos&&rtt.has_value(),
        "movement phase diagnostic lost its actual owned decision");
    uint64_t sampledUs=0;
    require(ba_frame_timing::timestampMicros(sampledUs)&&sampledUs>=decision.now&&sampledUs-decision.now<50000,
        "movement phase decision/QPC clocks differ or observation is stale");
    require(!state.phaseRows||sampledUs>=state.phaseSampleUs,"movement phase observation clock regressed");
    if(state.phaseRows&&sampledUs-state.phaseSampleUs<10000)return;
    require(state.phaseRows<4096,"movement phase diagnostic row bound reached");
    // Observe this EXISTING decide result, including denied decisions. Do not
    // recompute a target, spend a frame/ordinal or issue a native/worker query.
    const EarlyPhase row{decision,presented,*rtt,sampledUs,GetTickCount64()};
    if(early) {
        if(earlyPhaseCount==earlyPhases.size()){earlyPhaseOverflow=true;return;}
        earlyPhases[earlyPhaseCount++]=row;
    } else logPhase("MOVEMENT PHASE",row);
    state.phaseSampleUs=sampledUs;++state.phaseRows;
}
static void failed(const char* reason) noexcept {
    state.failed=true;
    worker::movementFail(reason);
}
void reset() noexcept {state=State{};earlyPhaseCount=0;earlyPhaseOverflow=false;}

static void context(Obj server) {
    require(ba::unified() && ba::dedicated() && ba::community() && ba::lan() &&
        ba_lan::secureMode() && ba_lan::secureVersion()==2 && ba_lan::originalCommandScheduling() &&
        ba_lan::originalCommands.ready() && !ba_lan::publicMatch && !ba_public::active() &&
        !ba_client::replayWorld(),"movement prediction requires negotiated TLSV2 Custom arrival mode");
    require(ba_local::isTarget(server) && GetCurrentThreadId()==ba_local::updateThread,
        "movement prediction requires its owned Unity update thread");
    require(ba_community::online && !ba_community::abortPending && ba_lan::welcomed,
        "movement prediction community session is not active");
    const auto& lobby=ba_community::lobby;
    const int slot=ba::lanSlot();
    require(slot>=0 && slot<2 && lobby.members.size()==2 && !lobby.id.empty() && lobby.epoch &&
        lobby.match==ba_lan::dedicatedMatchId &&
        lobby.members[static_cast<size_t>(slot)].profile==ba_community::welcome.profile &&
        ba_lan::originalCommands.match()==ba_lan::dedicatedMatchId,
        "movement prediction does not own this Custom match/seat");
}
static void bound(Obj server) {
    context(server);
    require(state.prepared && !state.failed && !state.drained && state.server==server &&
        state.owner==GetCurrentThreadId() && state.connectionGeneration==ba_community::generation &&
        state.lobbyEpoch==ba_community::lobby.epoch && state.lobby==ba_community::lobby.id &&
        state.match==ba_lan::dedicatedMatchId && state.match==worker::movementMatchId(),
        "movement prediction generation/match changed");
    require(ba::read<Obj>(server,0x140)==state.simulation && state.world &&
        ba::read<uint64_t>(state.simulation,0x1a8)==state.world && state.world==worker::movementWorldId(),
        "movement prediction world changed");
}
void beforeReady() {
    if(!worker::movementEnabled())return;
    try {
        Obj server=ba_local::server();context(server);
        Obj simulation=ba::read<Obj>(server,0x140);
        require(simulation && ba::read<bool>(simulation,0x1a0) &&
            ba::read<int>(simulation,0xa8)==-1 && ba::read<int>(simulation,0xac)==-1 &&
            ba::read<int>(server,0x198)==-1 && !ba_lan::worldReady && !ba_lan::running && ba_lan::frames.empty(),
            "movement prediction BEGIN must precede READY and every input");
        const uint64_t world=ba::read<uint64_t>(simulation,0x1a8);
        require(world && world==worker::movementWorldId(),"movement prediction native worker world is unavailable");
        require(!state.prepared || state.world!=world,"movement prediction BEGIN repeated for the same world");
        require(generations!=(std::numeric_limits<uint64_t>::max)(),"movement prediction generation exhausted");
        // A new worker key proves the host retired the old one-world session.
        // All objects below remain owned by the original server root, not here.
        reset();
        worker::movementBegin(ba_lan::dedicatedMatchId,static_cast<unsigned>(ba::lanSlot()));
        require(worker::movementWorldId()==world && worker::movementMatchId()==ba_lan::dedicatedMatchId,
            "movement prediction BEGIN did not bind the current world");
        state.server=server;state.simulation=simulation;state.owner=GetCurrentThreadId();
        state.world=world;state.connectionGeneration=ba_community::generation;
        state.lobbyEpoch=ba_community::lobby.epoch;state.lobby=ba_community::lobby.id;
        state.match=ba_lan::dedicatedMatchId;state.generation=++generations;state.prepared=true;
        ba::log("Movement prediction ready: generation=%llu match=%s world=%llu slot=%d physicalNext=0 initialCheckpoint=1 BA_RESURRECTION_MOVEMENT_PIPELINE_V1",
            static_cast<unsigned long long>(state.generation),state.match.c_str(),
            static_cast<unsigned long long>(world),ba::lanSlot());
    } catch(const std::exception& error) {failed(error.what());throw;}
    catch(...) {failed("unknown movement prediction BEGIN failure");throw std::runtime_error("unknown movement prediction BEGIN failure");}
}

void started() {
    if(!worker::movementEnabled())return;
    Obj server=ba_local::server();bound(server);
    require(!state.pacingStarted && state.physicalNext==0 &&
        ba::read<int>(state.simulation,0xac)==-1,"movement pacing START repeated/late");
    state.pacing.reset();state.pacingStarted=true;
    ba::log("Movement pacing START: match=%s world=%llu waitSteadyFrame=1 budget=12 BA_RESURRECTION_MOVEMENT_PACING_V1",
        state.match.c_str(),static_cast<unsigned long long>(state.world));
}
void authorityReceived(int frame,uint64_t receivedUs) {
    if(!worker::movementEnabled())return;
    bound(ba_local::server());require(state.pacingStarted,"movement receipt before pacing START");
    state.pacing.authorityReceived(frame,receivedUs);
    if(frame<2)ba::log("Movement pacing authority receipt: match=%s frame=%d received_us=%llu",
        state.match.c_str(),frame,static_cast<unsigned long long>(receivedUs));
}
#include "prediction_presentation_ownership.hpp"
bool activeForRefresh() {
    if(!worker::movementEnabled() || !state.prepared || !state.pacingStarted || state.failed || state.drained ||
       !ba_lan::running || !ba_lan::worldReady || ba_lan::stopped || ba_lan::matchEnded ||
       ba_community::abortPending || ba_community::lobby.phase!=ba_community_wire::Running ||
       !state.world || state.match.empty() || !worker::movementWorldId() || worker::movementMatchId().empty())return false;
    bound(state.server);return true;
}
bool canPublish(void* simulation,uint64_t nowUs) {
    require(ownsPresentation(simulation),"movement publication is outside its owned generation");
    return state.pacing.canPublish(state.physicalNext-1,nowUs);
}
void published(void* simulation,uint64_t nowUs) {
    require(ownsPresentation(simulation),"movement publication lost its owned generation");
    const int presented=ba::read<int>(simulation,0xac);
    require(presented==state.physicalNext-1,"movement native publication skipped its sole queued frame");
    state.pacing.published(presented,nowUs);
}

static Obj message(int frame) {
    Root value(ba::make("GamePb","InputActions"));
    ba::set<int>(value.get(),"gameFrame_",frame);ba::set<int>(value.get(),"debugFramesPerSecond_",20);
    ba::set<int>(value.get(),"debugGameTimeStepMs_",50);ba::set<float>(value.get(),"debugGameSpeed_",1.0f);
    return value.get();
}
static worker::MovementMetrics metrics() {
    const auto value=worker::movementMetrics();
    require(value.confirmed>=-1 && value.predicted>=-1 && value.received>=-1 &&
        value.confirmed<=value.predicted && value.confirmed<=value.received && !(value.flags&6u),
        "movement prediction worker metrics are invalid/terminal");
    require(value.predicted<state.physicalNext,"movement prediction worker executed an unqueued frame");
    return value;
}
static void canonical(Obj server,const Bytes& frame) {
    require(frame.size()>=8 && ba_lan::nextFrame>=0 &&
        ba_lan::u32(frame,0)==static_cast<uint32_t>(ba_lan::nextFrame),"noncontiguous movement authority frame");
    const size_t first=ba_lan::u32(frame,4),second=frame.size()-8;
    require(first>0 && first<=65536 && first<second && second-first<=65536,"movement authority player bounds");
    const std::array<Bytes,2> inputs{{Bytes(frame.begin()+8,frame.begin()+8+first),Bytes(frame.begin()+8+first,frame.end())}};
    Root value(message(ba_lan::nextFrame));int total=0;
    for(size_t slot=0;slot<inputs.size();++slot) {
        Root player(ba_lan::parse("InputActionsByPlayer",inputs[slot]));
        Obj handle=ba::get<Obj>(player.get(),"playerHandle_");require(handle,"movement authority player identity missing");
        Obj named=ba::get<Obj>(handle,"playerHandleWithName_");require(named,"movement authority named identity missing");
        Obj identity=ba::get<Obj>(named,"playerHandle_");require(identity,"movement authority raw identity missing");
        require(ba::get<uint64_t>(identity,"steamId_")==slot+1 && ba::get<bool>(identity,"isAliased_") &&
            !ba::get<uint32_t>(handle,"aiProfileId_"),"movement authority identity differs from assigned human");
        const int count=ba_local::count(ba::get<Obj>(player.get(),"actions_"));
        require(count>=0 && count<=256,"movement authority action count limit");total+=count;
        if(count)ba_local::addItem(ba::get<Obj>(value.get(),"playerInputActions_"),player.get());
    }
    const int frameNumber=ba_lan::nextFrame;
    require(ba::read<int>(server,0x198)==frameNumber-1,"original authority cursor is not contiguous");
    const auto wireHash=ba_lan::sha(frame);char wireHex[65]{};
    for(size_t i=0;i<32;++i)sprintf_s(wireHex+i*2,3,"%02x",wireHash[i]);
    worker::movementAuthority(ba_lan::serialize(value.get()),wireHex);
    // This original method advances its authority cursor, RTT/UI/replay once.
    // It must never be called with an empty speculative/drain frame.
    bool catching=false;void* args[]={value.get(),&catching};ba::call(server,"ProcessInputActions",2,args);
    require(ba::read<int>(server,0x198)==frameNumber,"original ProcessInputActions did not accept authority");
    if(frameNumber%200==0 || total || ba::flag(L"-lan-audit")) {
        const auto hash=ba_lan::sha(frame);char hex[65];
        for(int i=0;i<32;++i)sprintf_s(hex+i*2,3,"%02x",hash[static_cast<size_t>(i)]);
        ba_lan::recordReceipt(frameNumber,total,ba::read<int>(state.simulation,0xa8),hex);
        if(frameNumber%200==0 || total)ba::log("Movement authority accounted: frame=%d actions=%d physicalNext=%lld sha256=%s match=%s",
            frameNumber,total,static_cast<long long>(state.physicalNext),hex,state.match.c_str());
    }
    ba_lan::originalCommands.applied(frameNumber);
    require(frameNumber<INT32_MAX,"movement authority frame counter exhausted");
    ++ba_lan::nextFrame;
}

void tick(void* serverValue) {
    if(!worker::movementEnabled())return;
    if(ba_community::abortPending || ba_lan::stopped || !ba_lan::running || !ba_local::isTarget(serverValue))return;
    try {
        Obj server=serverValue;bound(server);
        ba_lan::originalInput(server); // Root wires immutable batch67 before network72.
        ba_lan::originalOutputReady(server); // READY74 requires actual publication0.
        auto value=metrics();
        // Worker authority queue is bounded14; retain margin and leave any
        // larger receive burst in the existing ordered main-thread queue.
        while(!ba_lan::frames.empty() &&
              static_cast<int64_t>(ba_lan::nextFrame)-1-value.confirmed<maximumQueuedAuthority) {
            canonical(server,ba_lan::frames.front());ba_lan::frames.pop_front();
        }
        value=metrics();
        require(value.received==ba_lan::nextFrame-1,"movement worker authority cursor differs");
        const int presented=ba::read<int>(state.simulation,0xac),completed=ba::read<int>(state.simulation,0xa8);
        require(presented>=-1 && completed>=-1 && presented<state.physicalNext && completed<state.physicalNext,
            "movement physical counters escaped their queued generation");
        if(ba_lan::matchEnded) {
            const auto now=GetTickCount64();if(!state.terminalAt)state.terminalAt=now;
            require(now-state.terminalAt<=terminalTimeoutMs,"movement terminal drain exceeded10 seconds");
            if(ba_lan::frames.empty() && !state.endSent) {
                state.finalAuthority=ba_lan::nextFrame-1;
                require(state.finalAuthority>=0,"movement result arrived before canonical startup");
                worker::movementEnd(state.finalAuthority);state.endSent=true;
                state.drainTarget=state.physicalNext-1;
                ba::log("Movement terminal drain begin: match=%s finalAuthority=%d physicalNext=%lld",
                    state.match.c_str(),state.finalAuthority,static_cast<long long>(state.physicalNext));
                value=metrics();
            }
            if(state.endSent && value.confirmed>=state.finalAuthority && (value.flags&8u)) {
                if(presented>=state.drainTarget && completed>=state.drainTarget &&
                   !ba::read<Obj>(state.simulation,0x110)) {
                    state.drained=true;ba_lan::running=false;
                    ba::log("Movement terminal drain complete: match=%s confirmed=%d physical=%d presented=%d target=%lld",
                        state.match.c_str(),value.confirmed,completed,presented,static_cast<long long>(state.drainTarget));
                }
                // ac can publish before a8 finishes the iteration's later view
                // queries. Wait for this target rather than queuing an endless
                // succession of new drain frames while a8 trails presentation.
                return;
            }
        }
        // Canonical0 owns both JoinArmy actions/entity IDs. No invented Join
        // or early one-human frame is allowed. Later unknown inputs are empty
        // here; the sole worker applies its forecast/known authority privately.
        if(ba_lan::nextFrame==0)return;
        require(state.physicalNext<=INT32_MAX,"movement physical frame counter exhausted");
        const int next=static_cast<int>(state.physicalNext);
        if(!ba_online_frame_clock::canFeed(next,presented))return;
        require(value.predicted==next-1 && !(value.flags&1u),"movement next input is already prepared/in flight");
        // Authority enqueue deliberately does not confirm. At the max lead,
        // allow only what the NEXT quiescent repair can confirm; the worker
        // checks its REAL confirmed frontier again before actual native Step.
        const int projected=(std::max)(value.confirmed,(std::min)(value.received,value.predicted));
        require(state.pacingStarted,"movement physical input before pacing START");
        const auto rtt=ba_lan::movementRoundTripEstimate();
        const auto decision=state.pacing.decide(next,presented,projected,ba_lan::movementPacingNowUs(),rtt);
        observePhase(decision,presented,rtt);
        if(!decision.allowed) {
            const auto now=GetTickCount64();
            if(!state.budgetLogAt || now-state.budgetLogAt>=1000) {
                state.budgetLogAt=now;ba::log("Movement pacing waiting: reason=%u next=%d confirmed=%d received=%d networkReceived=%lld physical=%d presented=%d targetAssigned=%lld rtt_us=%llu",
                    static_cast<unsigned>(decision.wait),next,value.confirmed,value.received,
                    static_cast<long long>(state.pacing.received()),value.predicted,presented,
                    static_cast<long long>(decision.target.assigned),static_cast<unsigned long long>(rtt.value_or(0)));
            }
            return;
        }
        Root physical(message(next));void* push[]={physical.get()};
        ba::call(state.simulation,"PushSimMessage",1,push);
        const bool recoveringBefore=state.pacing.recovering();
        state.pacing.queued(decision); // Observe ONLY the successful original queue call.
        if(recoveringBefore!=state.pacing.recovering()) {
            uint64_t queuedUs=0;require(ba_frame_timing::timestampMicros(queuedUs)&&queuedUs>=decision.now,
                "movement recovery queue/QPC clock differs");
            ba::log("MOVEMENT RECOVERY {\"schema\":1,\"event\":\"queued_mode\",\"world\":%llu,\"match\":\"%s\",\"frame\":%d,\"active\":%s,\"decision_us\":%llu,\"queue_return_us\":%llu,\"target_assigned\":%lld,\"native_dt_us\":50000}",
                static_cast<unsigned long long>(state.world),state.match.c_str(),next,
                state.pacing.recovering()?"true":"false",static_cast<unsigned long long>(decision.now),
                static_cast<unsigned long long>(queuedUs),static_cast<long long>(decision.target.assigned));
        }
        if(next && !decision.acquiring && !state.pacingAcquired) {
            state.pacingAcquired=true;
            ba::log("Movement pacing acquired: match=%s physical=%d targetAssigned=%lld rtt_us=%llu at_us=%llu BA_RESURRECTION_MOVEMENT_PACING_V1",
                state.match.c_str(),next,static_cast<long long>(decision.target.assigned),
                static_cast<unsigned long long>(rtt.value_or(0)),static_cast<unsigned long long>(decision.now));
        }
        ++state.physicalNext; // Only a successful original queue call spends this frame.
        if(state.endSent)state.drainTarget=next;
        ba_frame_timing::applied(next,state.simulation,ba_lan::frames.size());
        if(next<2 || next%200==0 || state.endSent)
            ba::log("Movement physical queued: frame=%d confirmed=%d received=%d projected=%d drain=%d match=%s",
                next,value.confirmed,value.received,projected,state.endSent?1:0,state.match.c_str());
    } catch(const std::exception& error) {failed(error.what());throw;}
    catch(...) {failed("unknown movement prediction tick failure");throw std::runtime_error("unknown movement prediction tick failure");}
}
}
