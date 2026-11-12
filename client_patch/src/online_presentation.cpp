#pragma once
// Only RGameInstance.ProcessUpdate's direct presentation call is redirected.
// The original method and all rendering/jobs after this call remain intact.
extern "C" __declspec(dllexport) void OfflinePresentAvailableSimFrame(void* simulation,void* methodInfo) {
    ba::init();
    const auto original=ba::native<void(*)(ba::Obj,ba::Obj)>(0x3e65c70);
    if(!ba_lan::presentationActive(simulation)) {
        original(simulation,methodInfo);return;
    }
    try {
        // The native worker replaces this single latest-result slot; it does
        // not block when occupied. The remote input path therefore permits
        // only one unpresented frame, rather than running the worker ahead.
        // Reading only its presence mirrors the original method's first test;
        // the original retains all locking,buffer ownership and publication.
        if(!ba::read<ba::Obj>(simulation,0x110))return;
        if(ba_prediction_movement::ownsPresentation(simulation)) {
            const auto now=ba_lan::movementPacingNowUs();
            if(!ba_prediction_movement::canPublish(simulation,now))return;
            const int before=ba::read<int>(simulation,0xac);
            ba_prediction_stages::mark("stage.present.enter",simulation);
            original(simulation,methodInfo);
            ba_prediction_stages::mark("stage.present.original",simulation);
            if(ba::read<int>(simulation,0xac)!=before) {
                ba_prediction_movement::published(simulation,ba_lan::movementPacingNowUs());
                ba_prediction_stages::mark("stage.present.clock",simulation);
                ba_prediction_visual::published(simulation);
                ba_prediction_stages::mark("stage.present.visual",simulation);
                ba_frame_timing::published(simulation,ba_lan::frames.size());
            }
            return; // Movement admission owns the single absolute phase.
        }
        auto& clock=ba_lan::presentationClock;
        const auto now=ba_lan::presentationNowUs();
        if(!clock.started()) {
            clock.start(now);
            ba::log("Online presentation clock: tick_us=50000 pendingFrameLimit=1 BA_RESURRECTION_ONLINE_PRESENTATION_V1");
        }
        if(!clock.ready(now))return;
        const int before=ba::read<int>(simulation,0xac);
        original(simulation,methodInfo);
        if(ba::read<int>(simulation,0xac)!=before) {
            clock.pushed(ba_lan::presentationNowUs());
            ba_frame_timing::published(simulation,ba_lan::frames.size());
        }
    } catch(const std::exception& error) {
        ba_lan::fail("online presentation",error);
    }
}
