#pragma once
// Included inside mobile. Original Focus/Cancel calls only; no iterator writes.
namespace focus_request {
struct State {
    uint64_t world=0;std::string match;unsigned repeatCalls=0,cancelCalls=0;bool repeated=false,finished=false;
};
static State& state(){static auto* value=new State;return *value;}
static void clear(){auto& s=state();if(s.world)require(ba::initialThread&&GetCurrentThreadId()==ba::initialThread,
    "focus request observer retirement requires Unity owner");s=State{};}
struct Probe {
    uint64_t epoch=0,requestEpoch=0,iteration=0,pendingIteration=0;uint32_t group=0,handle=0,selectorHandle=0;
    Obj iterator=nullptr;bool observerActive=false,handleReady=false,scheduling=false,ending=false;int held=-1;
    std::optional<int> originalState;std::optional<uint32_t> yield;
    std::vector<uint32_t> source,logical,selected;std::string pending;
};
static std::string pendingJson(const selection::FocusSession& active) {
    require(active.pending.size()<=8192,"focus request pending observation bound");std::ostringstream out;out<<'[';bool comma=false;
    for(const auto& item:active.pending){if(comma)out<<',';comma=true;const auto& value=item.second;
        out<<"{\"entity\":"<<item.first<<",\"unit_type\":"<<value.identity.unitType<<",\"army\":"<<value.identity.armyId
           <<",\"incarnation\":"<<value.incarnation<<'}';}out<<']';return out.str();
}
static Probe event(actors::State& owner,Obj selector,int frame,const char* name,const char* callback=nullptr,uint32_t callbackToken=0) {
    owned(owner);auto& s=state();if(!s.world){s.world=owner.world;s.match=owner.match;}
    require(s.world==owner.world&&s.match==owner.match&&frame==ba::read<int>(owner.simulation->get(),0xac)&&
        ba::lanSlot()==1&&frame>=130&&frame<280,"focus request receipt lost owner/frame");
    auto& active=selection::focusSession();const bool bound=selection::focusSameWorld(active)&&active.selector&&active.selector->get()==selector;
    const bool retired=s.world==2&&s.cancelCalls==1&&!strcmp(name,"complete")&&!active.world&&!active.selector&&!active.iterator&&
        !active.handleReady&&!active.scheduling;
    require(bound||retired,"focus request receipt lost its original selector outside completed cancellation");
    Probe p;p.observerActive=bound;p.epoch=bound?active.epoch:0;p.requestEpoch=bound?active.request.epoch:0;p.iteration=bound?active.iteration:0;p.pendingIteration=active.pendingIteration;
    p.group=bound?active.group:0;p.handle=bound?active.handle:0;p.handleReady=active.handleReady;p.scheduling=active.scheduling;p.ending=active.ending;
    p.iterator=active.iterator?active.iterator->get():nullptr;Root rooted(p.iterator);
    if(p.iterator){require(rooted.get()==p.iterator&&selection::focusIteratorOwner(p.iterator)==selector,"focus request iterator observer root differs");
        p.originalState=ba::read<int>(p.iterator,0x10);p.yield=ba::read<uint32_t>(p.iterator,0x14);}
    p.held=ba::read<int>(selector,0xa0);p.selectorHandle=ba::read<uint32_t>(selector,0xb0);
    p.source=active.sourceIds;p.logical=active.logicalIds;p.selected=selection::selectionIds(ba::read<Obj>(selector,0x90));p.pending=pendingJson(active);
    View view(owner,selector);std::ostringstream out;out<<std::boolalpha;
    out<<"{\"schema\":1,\"event\":"<<ba_catalog::quote(name)<<",\"world\":"<<s.world<<",\"match\":"<<ba_catalog::quote(s.match)
       <<",\"slot\":1,\"entity\":11,\"frame\":"<<frame<<",\"tick_ms\":"<<GetTickCount64()<<",\"sampled_us\":"<<stamp()
       <<",\"observer_active\":"<<p.observerActive<<",\"observer_world\":"<<active.world
       <<",\"active_epoch\":"<<p.epoch<<",\"request_epoch\":"<<p.requestEpoch<<",\"requested_group\":";
    if(p.requestEpoch)out<<active.request.requestedGroup;else out<<"null";out<<",\"effective_group\":";
    if(p.requestEpoch)out<<active.request.effectiveGroup;else out<<"null";out<<",\"active_group\":";
    if(bound)out<<p.group;else out<<"null";out<<",\"iterator\":\""<<p.iterator
       <<"\",\"handle\":"<<p.handle<<",\"selector_handle\":"<<p.selectorHandle<<",\"handle_ready\":"<<p.handleReady
       <<",\"scheduling\":"<<p.scheduling<<",\"ending\":"<<p.ending<<",\"iteration\":"<<p.iteration<<",\"pending_iteration\":"<<p.pendingIteration
       <<",\"pending_count\":"<<active.pending.size()<<",\"pending_identities\":"<<p.pending<<",\"original_state\":";
    if(p.originalState)out<<*p.originalState;else out<<"null";out<<",\"yield_bits\":";if(p.yield)out<<*p.yield;else out<<"null";
    out<<",\"held_group\":"<<p.held<<",\"source_ids\":"<<idsJson(p.source)<<",\"logical_ids\":"<<idsJson(p.logical)<<",\"selected_ids\":"<<idsJson(p.selected)
       <<",\"current_actor\":\""<<view.current<<"\",\"current_admitted\":"<<view.context.admitted(view.current)<<",\"original_incarnation\":"<<mobile::state().originalToken
       <<",\"current_incarnation\":"<<token(view.context,view.current)<<",\"native_identity_present\":"<<view.nativePresent
       <<",\"repeat_calls\":"<<s.repeatCalls<<",\"cancel_calls\":"<<s.cancelCalls<<",\"original_callback\":"<<(callback?ba_catalog::quote(callback):"null")
       <<",\"original_token\":";if(callbackToken)out<<callbackToken;else out<<"null";
    out<<",\"physicalUI\":false}";const auto text=out.str();require(text.size()<=8192,"focus request receipt bound");ba::log("MOBILE FOCUS REQUEST %s",text.c_str());return p;
}
static void repeat(actors::State& owner,Obj selector,int frame) {
    auto& s=state();require(!s.repeated&&!s.repeatCalls&&frame>=mobile::state().firstRestored&&frame<180,"focus request repeat missed restored phase");
    idle(owner,selector,11);View view(owner,selector);require(view.current&&view.context.admitted(view.current)&&
        token(view.context,view.current)==mobile::state().originalToken&&groupIds(groupFor(selector,4))==std::vector<uint32_t>{11},
        "focus request repeat lacks current admitted group4 member11");
    const auto before=event(owner,selector,frame,"before_repeat","Uncapped.UnitSelector.FocusControlGroup",0x06002221);Root oldIterator(before.iterator);
    require(before.epoch&&before.iterator&&oldIterator.get()==before.iterator&&before.group==4&&before.held==4&&before.handleReady&&
        !before.scheduling&&!before.ending&&before.handle==before.selectorHandle&&before.selected==std::vector<uint32_t>{11},
        "focus request needs the still-running original group4 iterator");
    Obj method=actors::method(selector,"FocusControlGroup",2,0x06002221,0x3bf3010);actors::instanceSignature(method,"Void","Int32");
    require(original::parameterClass(method,1)==actors::type("System","Boolean"),"focus request original repeat argument differs");
    int group=4;bool repeat=true;void* args[]={&group,&repeat};++s.repeatCalls;actors::invoke(method,selector,args);owned(owner);
    const auto after=event(owner,selector,frame,"after_repeat","Uncapped.UnitSelector.FocusControlGroup",0x06002221);
    require(after.epoch==before.epoch&&after.group==before.group&&after.iterator==oldIterator.get()&&after.handle==before.handle&&
        after.selectorHandle==before.selectorHandle&&after.handleReady==before.handleReady&&after.scheduling==before.scheduling&&
        after.ending==before.ending&&after.iteration==before.iteration&&after.pendingIteration==before.pendingIteration&&after.pending==before.pending&&
        after.originalState==before.originalState&&after.yield==before.yield&&after.held==before.held&&after.source==before.source&&after.logical==before.logical&&
        after.selected==before.selected&&after.requestEpoch>before.epoch&&after.requestEpoch>before.requestEpoch&&selection::focusSession().request.repeat,
        "accepted original focus without Start changed the active iterator session");s.repeated=true;
}
static void cancel(actors::State& owner,Obj selector,int frame) {
    auto& s=state();require(s.world==2&&s.repeated&&s.repeatCalls==1&&!s.cancelCalls&&frame>=170&&frame<180,"focus request cancellation missed its phase");
    event(owner,selector,frame,"before_cancel","Uncapped.UnitSelector.FocusControlGroupCancel",0x06002220);
    require(ba::read<int>(selector,0xa0)==4,"focus request cancellation lost original group4");
    RecallMethods methods(selector);int group=4;void* args[]={&group};++s.cancelCalls;actors::invoke(methods.cancel,selector,args);owned(owner);methods.validate();
    require(ba::read<int>(selector,0xa0)==-1&&!ba::read<Obj>(selector,0xa8),"focus request original Cancel did not end held intent");
    mobile::state().focusCancelled=true;event(owner,selector,frame,"after_cancel","Uncapped.UnitSelector.FocusControlGroupCancel",0x06002220);
}
static void complete(actors::State& owner,Obj selector,int frame) {
    auto& s=state();require(s.repeated&&s.repeatCalls==1&&!s.finished&&(s.world==1?s.cancelCalls==0:s.cancelCalls==1),
        "focus request completion lacks the original accepted repeat/cancel");const auto p=event(owner,selector,frame,"complete");
    require(s.world==1?(p.observerActive&&p.iterator&&p.held==4):(!p.observerActive&&!p.iterator&&p.epoch==0&&p.held==-1),
        "focus request completion did not retain/end its original active session");s.finished=true;
}
}
