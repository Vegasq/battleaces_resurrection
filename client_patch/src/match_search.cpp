#pragma once
// Original public queue presentation. No retired matchmaking requests are sent.
// The caller owns arbitration; this object owns one native presentation generation.
namespace ba_match_search {
using ba::Obj;using ba_local::Root;
using Ticket=uint64_t;
enum class Phase {None,Searching,Found};
static Ticket serial=0,ticket=0,lastReleased=0;
static Phase phase=Phase::None;
static bool cancelPending=false;
static bool joiningPosted=false;
static int mode=0;
static auto& frontRoot=*new std::unique_ptr<Root>();
static auto& viewRoot=*new std::unique_ptr<Root>();
static auto& buttonRoot=*new std::unique_ptr<Root>();
static int observedSeconds=-1;
struct Capture {Ticket ticket;std::string event;int afterFrame;};
static auto& captures=*new std::deque<Capture>();
static unsigned captureSerial=0;
static void require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
static bool diagnostic(){return ba::flag(L"-match-search-smoke");}
static int frame() {
    Root boxed(ba::invoke(ba::find_class("UnityEngine","Time"),nullptr,"get_frameCount",0,nullptr));
    return *ba::api<int*(*)(Obj)>("il2cpp_object_unbox")(boxed.get());
}
static void capture(const char* event,Ticket value) {
    if(diagnostic())captures.push_back(Capture{value,event,frame()+2});
}
static Obj notification() {
    Obj controller=ba::get<Obj>(ba::owner,"<UINotificationController>k__BackingField");
    return controller?ba::get<Obj>(controller,"_matchmakingNotification"):nullptr;
}
static Obj view() {Obj value=notification();return value?ba::get<Obj>(value,"_viewModel"):nullptr;}
static bool owns(Ticket value){return value && ticket==value && frontRoot && phase!=Phase::None;}
static void publish(bool searching,bool found) {
    Obj front=frontRoot->get();
    require(!ba::get<int32_t>(front,"_pendingInviteResponseRequests"),"search presentation overlaps invite response");
    ba::set<bool>(front,"_inMatchmakingQueue",searching);
    ba::set<bool>(front,"_localIsInMatchmaking",searching);
    ba::set<bool>(front,"_matchmakingGame",found);
    ba::set<int32_t>(front,"_pendingMatchmakingRequests",0);
    ba::set<int32_t>(front,"_localMatchmakingGameMode",mode);
    ba::set<int32_t>(front,"_matchmakingGameMode",searching || found?mode:0);
    int32_t error=0;void* args[]={&error};ba::call(front,"UpdateMatchmakingStatus",1,args);
}
static void release(Ticket value,const char* reason) {
    if(!owns(value))return;
    publish(false,false);
    ba::log("Native search released: ticket=%llu reason=%s status=%d",static_cast<unsigned long long>(ticket),reason,
        ba::get<int32_t>(frontRoot->get(),"_matchmakingStatus"));
    if(diagnostic()) {
        require(!view(),"native search notification survived release");
        if(buttonRoot)require(!ba::get<bool>(buttonRoot->get(),"_isMatching"),"native Play remained matching after release");
        capture("released",ticket);
    }
    lastReleased=ticket;phase=Phase::None;ticket=0;cancelPending=false;viewRoot.reset();frontRoot.reset();buttonRoot.reset();
}
static Ticket begin(Obj front,int gameMode) {
    require(front && !ticket && serial!=UINT64_MAX && (gameMode==1 || gameMode==2 || gameMode==5),"native search ownership/mode");
    require(!ba::get<Obj>(front,"_party") && !ba::get<int32_t>(front,"_pendingInviteResponseRequests") &&
        !ba::get<int32_t>(front,"_pendingMatchmakingRequests"),
        "native search requires idle public menu");
    Obj invites=ba::get<Obj>(front,"_partyInvites");
    require(invites && !ba_local::count(invites),"native search overlaps invitation ownership");
    Obj server=ba::get<Obj>(front,"_gameServerIntegration");
    Obj connection=server?ba::get<Obj>(server,"_currentConnectionInfo"):nullptr;
    require(connection && ba::get<Obj>(connection,"gameHandle_"),"native search connection placeholder missing");
    require(!ba::native<bool(*)(Obj)>(0xa524c0)(nullptr),"native search requires suppressed Steam initialization");
    Root now(ba::call(front,"GetCurrentServerTime"));require(now.get()!=nullptr,"native search clock missing");
    const uint64_t stamp=*ba::api<uint64_t*(*)(Obj)>("il2cpp_object_unbox")(now.get());
    frontRoot=std::make_unique<Root>(front);mode=gameMode;ticket=++serial;phase=Phase::Searching;cancelPending=false;joiningPosted=false;observedSeconds=-1;
    try {
        ba::set<uint64_t>(front,"_timeEnteredQueue",stamp);publish(true,false);
        require(ba::get<int32_t>(front,"_matchmakingStatus")==5,"native search did not enter InQueue");
        require(view()!=nullptr,"original matchmaking notification VM missing");viewRoot=std::make_unique<Root>(view());
        ba::log("Native search began: ticket=%llu mode=%d nativeStatus=5 originalPanel=1 timestamp=%llu",
            static_cast<unsigned long long>(ticket),mode,static_cast<unsigned long long>(stamp));
        return ticket;
    } catch(...) {try{release(ticket,"begin failed");}catch(...){}throw;}
}
static bool requestCancel(Obj front) {
    if(!ticket || !frontRoot || frontRoot->get()!=front || phase!=Phase::Searching)return false;
    cancelPending=true;
    ba::log("Native search cancel queued: ticket=%llu",static_cast<unsigned long long>(ticket));return true;
}
static bool cancelled(Ticket value){return owns(value) && cancelPending;}
static bool found(Ticket value) {
    if(!owns(value) || phase!=Phase::Searching || cancelPending)return false;
    phase=Phase::Found;publish(false,true);
    ba::log("Native search match accepted: ticket=%llu status=%d",static_cast<unsigned long long>(ticket),
        ba::get<int32_t>(frontRoot->get(),"_matchmakingStatus"));
    return true;
}
static void joining(Obj front) {
    if(!ticket)return;
    require(frontRoot && frontRoot->get()==front && phase==Phase::Found && !joiningPosted,
        "native joining signal ownership");
    Obj server=ba::get<Obj>(front,"_gameServerIntegration");
    Root active(ba::call(server,"HasActiveGameConnectionInfo"));
    require(active.get() && *ba::api<bool*(*)(Obj)>("il2cpp_object_unbox")(active.get()),
        "native joining requires installed match connection");
    Obj router=ba::get<Obj>(front,"_signalRouter");
    require(router && router==ba::read<Obj>(ba::owner,0x238),"native joining router ownership");
    Obj post=nullptr;void* iterator=nullptr;
    while(Obj method=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(ba::klass(router),&iterator)) {
        if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(method),"PostSignal") ||
           ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(method)!=1)continue;
        Obj type=ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(method,0);
        if(ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(type)!=ba::find_class("System","Object"))continue;
        require(!post,"ambiguous native object signal overload");post=method;
    }
    require(post && ba::read<void*>(post,0)==reinterpret_cast<void*>(ba::native<void(*)()>(0x3e57c80)),
        "native object signal overload unavailable");
    int loadingMode=mode; // Native public modes 1/2/5 map directly; Try Deck uses 10.
    Root signal(ba::api<Obj(*)(Obj,void*)>("il2cpp_value_box")(ba::find_class("Uncapped.Signals","JoiningGameSignal"),&loadingMode));
    void* args[]={signal.get()};ba_local::invokeMethod(post,router,args);joiningPosted=true;
    ba::log("Native search joining signal: ticket=%llu mode=%d activeConnection=1 originalRouter=1",
        static_cast<unsigned long long>(ticket),mode);
    capture("joining",ticket);
}
static void observeButton(Obj button) {
    if(!diagnostic())return;
    require(ticket && phase==Phase::Searching && button,"native search button ownership");
    require(ba::get<bool>(button,"_isMatching"),"original public Play did not enter Searching");
    Root enabled(ba::call(button,"get_Interactable"));
    require(!*ba::api<bool*(*)(Obj)>("il2cpp_object_unbox")(enabled.get()),"original public Play still interactable in queue");
    buttonRoot=std::make_unique<Root>(button);
    if(lastReleased) {
        require(!found(lastReleased),"retired search accepted a late match");
        release(lastReleased,"stale diagnostic release");
        require(ticket && phase==Phase::Searching && viewRoot->get()==view(),"stale search released current presentation");
        ba::log("Native search stale ticket rejected: retired=%llu current=%llu panelRetained=1",
            static_cast<unsigned long long>(lastReleased),static_cast<unsigned long long>(ticket));
    }
    ba::log("Native search button: ticket=%llu matching=1 interactable=0 original=1",static_cast<unsigned long long>(ticket));
}
static void clickCancel(Ticket value) {
    require(diagnostic() && owns(value) && phase==Phase::Searching && viewRoot && viewRoot->get()==view(),"native Cancel diagnostic ownership");
    Root caller(viewRoot->get());ba::call(caller.get(),"OnCancelClicked");
    require(cancelPending,"original Cancel did not retire public intent");
    ba::log("Native search original Cancel invoked: ticket=%llu (automated; not mouse input)",static_cast<unsigned long long>(value));
}
static void update(void*) {
    if(!diagnostic())return;
    if(ticket && phase==Phase::Searching && !cancelPending) {
        require(viewRoot && viewRoot->get()==view(),"native search notification owner changed");
        Root seconds(ba::call(viewRoot->get(),"get_CurrentSecondsInQueue"));
        const int current=*ba::api<int*(*)(Obj)>("il2cpp_object_unbox")(seconds.get());
        require(current>=observedSeconds,"native search elapsed time moved backwards");
        if(current!=observedSeconds) {
            ba::log("Native search timer: ticket=%llu seconds=%d",static_cast<unsigned long long>(ticket),current);
            if(current>=1 && observedSeconds<1)capture("searching",ticket);
            observedSeconds=current;
        }
    }
    if(captures.empty() || frame()<captures.front().afterFrame)return;
    const auto pending=captures.front();captures.pop_front();
    wchar_t module[32768];const auto length=GetModuleFileNameW(ba::module,module,32768);
    require(length && length<32768,"native search capture installation unavailable");
    wchar_t* slash=wcsrchr(module,L'\\');require(slash!=nullptr,"native search capture path invalid");*(slash+1)=0;
    const std::string filename="match-search-"+std::to_string(GetCurrentProcessId())+"-"+std::to_string(pending.ticket)+"-"+
        std::to_string(++captureSerial)+"-"+pending.event+".png";
    const std::wstring path=std::wstring(module)+L"investigation\\runtime\\"+std::wstring(filename.begin(),filename.end());
    Root name(ba::api<Obj(*)(const wchar_t*,int)>("il2cpp_string_new_utf16")(path.data(),static_cast<int>(path.size())));
    void* args[]={name.get()};ba::invoke(ba::find_class("UnityEngine","ScreenCapture"),nullptr,"CaptureScreenshot",1,args);
    ba::log("Native search capture requested: file=%s ticket=%llu event=%s frame=%d",filename.c_str(),
        static_cast<unsigned long long>(pending.ticket),pending.event.c_str(),frame());
}
}
