// Optional original call/tail observers. Include after actor repair. Collection
// operations and their native return values still belong to the original game.
namespace ba_prediction_click_routes {
namespace actors=ba_prediction_actors;
namespace proof=ba_prediction_click_provenance;
using ba::Obj;
static void failed(const char* reason)noexcept {
    actors::clickForget(actors::state());
    ba::log("Prediction click provenance failed: reason=%s retry=0",reason);
    ba_prediction_worker::movementFail(reason);
}
static void mutation(Obj set,uint32_t id,Obj info,int part) {
    if(!actors::clickActive())return;
    auto& state=actors::state();if(!actors::clickCurrent(state))return;
    actors::require(!info,"click provenance original collection MethodInfo differs");
    if(part>=0 && actors::clickObserveRemovalPart(state,set,id,static_cast<proof::RemovalPart>(part)))return;
    actors::clickExternalEdit(state); // Includes empty Clear, duplicate Add and absent Remove.
}
static void observe(Obj set,uint32_t id,Obj info,int part)noexcept {
    try{mutation(set,id,info,part);}
    catch(const std::exception& error){failed(error.what());}
    catch(...){failed("unknown original selection mutation observation exception");}
}
}
extern "C" __declspec(dllexport) void OfflinePredictionNaturalSelectionRemove(void* selector,void* batch,void* info) {
    ba::init();using namespace ba_prediction_click_routes;
    const auto original=ba::native<void(*)(Obj,Obj,Obj)>(0x3bf0cf0);
    auto& state=actors::state();proof::Removal operation;bool tracking=false;
    if(actors::clickActive()) {
        try{
            const char* name=batch?ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(ba::klass(batch)):"null";
            ba::log("Prediction original dying removal entry: world=%llu managerBoundary=%u managerUpdate=%llu batchClass=%s provenancePhase=%u acceptedSerial=%llu",
                static_cast<unsigned long long>(state.world),state.originalManagerUpdate?1u:0u,
                static_cast<unsigned long long>(state.managerUpdateSerial),name?name:"null",static_cast<unsigned>(state.clickProvenance.phase()),
                static_cast<unsigned long long>(state.inputIntent.accepted()?state.inputIntent.accepted()->serial:0));
            tracking=actors::clickBeginNatural(state,selector,batch,info,operation);
        }
        catch(const std::exception& error){failed(error.what());}
        catch(...){failed("unknown original natural-removal preparation exception");}
    }
    try{original(selector,batch,info);} // Exact original tail destination, once.
    catch(...){if(tracking)actors::clickForget(state);throw;}
    if(tracking) {
        try{if(!actors::clickFinishNatural(state,selector,operation))actors::clickExternalEdit(state);}
        catch(const std::exception& error){failed(error.what());}
        catch(...){failed("unknown original natural-removal completion exception");}
    }
}
extern "C" __declspec(dllexport) bool OfflinePredictionSelectionRemovePreview(void* set,uint32_t id,void* info) {
    ba::init();ba_prediction_click_routes::observe(set,id,info,0);
    return ba::native<bool(*)(ba::Obj,uint32_t,ba::Obj)>(0x3c66610)(set,id,info);
}
extern "C" __declspec(dllexport) bool OfflinePredictionSelectionRemoveCurrent(void* set,uint32_t id,void* info) {
    ba::init();ba_prediction_click_routes::observe(set,id,info,1);
    return ba::native<bool(*)(ba::Obj,uint32_t,ba::Obj)>(0x3c66610)(set,id,info);
}
extern "C" __declspec(dllexport) bool OfflinePredictionPreviewAdd(void* set,uint32_t id,void* info) {
    ba::init();ba_prediction_click_routes::observe(set,id,info,-1);
    return ba::native<bool(*)(ba::Obj,uint32_t,ba::Obj)>(0x3c661b0)(set,id,info);
}
extern "C" __declspec(dllexport) bool OfflinePredictionSelectionAdd(void* set,uint32_t id,void* info) {
    ba::init();ba_prediction_click_routes::observe(set,id,info,-1);
    return ba::native<bool(*)(ba::Obj,uint32_t,ba::Obj)>(0x3c661b0)(set,id,info);
}
extern "C" __declspec(dllexport) void OfflinePredictionPreviewClear(void* set,void* info) {
    ba::init();ba_prediction_click_routes::observe(set,UINT32_MAX,info,-1);
    ba::native<void(*)(ba::Obj,ba::Obj)>(0x3c66c50)(set,info);
}
extern "C" __declspec(dllexport) void OfflinePredictionSelectionClear(void* set,void* info) {
    ba::init();ba_prediction_click_routes::observe(set,UINT32_MAX,info,-1);
    ba::native<void(*)(ba::Obj,ba::Obj)>(0x3c66c50)(set,info);
}
