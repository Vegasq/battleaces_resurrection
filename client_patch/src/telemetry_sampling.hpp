#pragma once
#include <cstdint>

namespace ba_telemetry_sampling {
constexpr unsigned maxSnapshots=17;
constexpr uint64_t repeatIntervalMs=10000;
enum class Stage {Other,Menu,InGame,PostGame,Tutorial};

// Call on initialized main-thread updates, before test automation can leave a
// result/menu state. The observation budget includes the separate startup sample.
// This schedules bounded scalar samples, never engine calls or lifecycle changes.
struct Schedule {
    Stage previous=Stage::Other;
    unsigned entrySamples=0;
    uint64_t sampledAt=0;

    bool due(Stage stage,uint64_t now,unsigned snapshots) {
        if(snapshots>=maxSnapshots)return false;
        if(stage!=previous){previous=stage;entrySamples=0;}
        if(stage==Stage::Other || entrySamples>=2)return false;
        if(entrySamples && (now<sampledAt || now-sampledAt<repeatIntervalMs))return false;
        ++entrySamples;sampledAt=now;return true;
    }
};
}
