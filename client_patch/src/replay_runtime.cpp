#pragma once
#include "replay_update_policy.hpp"
// Restore only the original replay pump omitted by OfflineGameUpdate. The
// original ProcessUpdate also does networking and must not be called wholesale.
namespace ba_replay_runtime {
using ba::Obj;using ba_local::Root;using ba_native_settings::require;
static void update(Obj server) {
    static bool failed=false,logged=false;
    if(failed || !ba::owner || !server)return;
    try {
        require(ba::initialThread && GetCurrentThreadId()==ba::initialThread,
            "replay update requires the original Unity thread");
        Obj services=ba::read<Obj>(ba::owner,0x38);
        if(!services || server!=ba::read<Obj>(services,0x18))return;
        Root integration(server),replay(ba::read<Obj>(server,0x168));
        if(!replay.get())return;
        Obj simulation=ba::read<Obj>(server,0x140);
        const ba_replay_update::Context context{
            true,replay.get()==ba::read<Obj>(ba::owner,0x40),
            simulation && simulation==ba::read<Obj>(replay.get(),0x18),
            ba::read<Obj>(replay.get(),0x40)!=nullptr,
            ba_practice::active() || ba_local::ready.load(),
            ba_client::worldOwner!=ba_client::Owner::None || ba_dedicated_session::joined,
            ba_bootstrap::creating || ba_bootstrap::awaitingWorld,
            ba_native_replay_playback::enabled()};
        if(!ba_replay_update::ownsReplay(context))return;
        Root simulationRoot(simulation);
        // The explicit original batch diagnostic has its own state/coroutine
        // pump. Preserve that independently qualified path without double steps.
        namespace codec=ba_native_replay_reader;
        static Obj connectedMethod=nullptr,updateMethod=nullptr;
        if(!updateMethod) {
            require(ba::klass(server)==codec::type("Uncapped","GameServerIntegration","RGame.dll") &&
                ba::klass(replay.get())==codec::type("Uncapped","Replay","RGame.dll"),
                "original replay update types differ");
            connectedMethod=codec::method(ba::klass(server),"HasActiveGameConnectionInfo",0,0x3e50530,0x060010fb);
            updateMethod=codec::method(ba::klass(replay.get()),"UpdateReplayRunner",0,0x3ddd190,0x0600094d);
        }
        const bool spectator=ba::read<bool>(server,0x1a0);
        bool connected=false;
        if(!spectator) {
            Root value(codec::invoke(connectedMethod,integration.get()));
            require(value.get()!=nullptr,"original replay connection predicate returned no value");
            connected=ba_catalog::unbox<bool>(value.get());
        }
        if(!ba_replay_update::originalEligibility(spectator,connected,ba::read<int>(server,0x19c)))return;
        require(ba::read<Obj>(replay.get(),0x78)!=nullptr,"original replay runner missing");
        codec::invoke(updateMethod,replay.get());
        if(!logged){logged=true;ba::log("Original replay runner update restored: primaryIntegration=1 originalPredicate=1 helperTicks=0");}
    } catch(const std::exception& error) {
        // Replay failure must not disable local input production or its timer.
        failed=true;ba::log("Original replay runner update failed: %s",error.what());
    }
}
}
