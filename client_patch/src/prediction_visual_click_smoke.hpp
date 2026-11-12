#pragma once
#include "prediction_visual_click_protocol.hpp"

// Explicit owned diagnostic: ordinary InputSystem delivery, original callbacks,
// and read-only receipts. No selector/history writes or extra command creation.
namespace ba_prediction_visual_click {
namespace actors=ba_prediction_actors;
namespace visual=ba_prediction_visual;
namespace ui=ba_prediction_visual_input;
namespace vm=ba_prediction_actor_smoke::virtual_mouse;
namespace history=ba_prediction_actor_smoke::expired_click;
namespace input=ba_prediction_input;
namespace protocol=ba_prediction_visual_click_protocol;
using ba::Obj;
using Vec3=visual::Vec3;
static bool enabled(){static const bool value=ba::flag(L"-prediction-visual-click-smoke");return value;}
static bool spatialEnabled(){static const bool value=ba::flag(L"-prediction-visual-click-spatial");return value;}
static void require(bool value,const char* why){actors::require(value,why);}
struct AimFrozen {
    visual::FrontendObservation pose;
    Obj camera=nullptr;
    Vec3 actual,q,r;
    std::array<protocol::ScreenPoint,4> points{};
    protocol::MatchedAnchor matched;
    bool bound=false;
};
struct State {
    uint64_t world=0,sequence=0,pressOrdinal=0,aimSequence=0;
    std::string match;
    unsigned episode=0;
    bool failed=false,active=false,complete=false;
    protocol::Point point;
    int beforeCommands=-1,processCommands=-1;
    unsigned processStage=0;
    uint64_t processUs=0;
    visual::FrontendObservation anchor;
    vm::Snapshot pressed;
    protocol::Progress progress;
    AimFrozen aim;
};
static State& state(){static State* value=new State;return *value;}
static uint64_t& ordinal(){static uint64_t value=0;return value;}
static double magnitude(const visual::FrontendObservation& value) {
    return std::hypot(std::hypot(value.offset.x,value.offset.y),value.offset.z);
}
static int pending() {
    ba_local::QueueLock lock;Obj server=ba_local::server();actors::classIs(server,"Uncapped","GameServerIntegration");
    actors::field(server,"_queuedInputCommands",0x180);
    const auto count=ba_local::count(ba::read<Obj>(server,0x180));
    require(count>=0&&count<=4,"visual click pending command count exceeds diagnostic bound");return count;
}
static std::string ids(const std::vector<uint32_t>& values) {
    std::ostringstream out;out<<'[';for(size_t i=0;i<values.size();++i){if(i)out<<',';out<<values[i];}out<<']';return out.str();
}
struct Sample {
    visual::FrontendObservation pose;
    Obj selector=nullptr,camera=nullptr;
    Vec3 actual;
    history::History click;
    vm::Snapshot mouse;
    bool context=false;
    float now=0,x=0,y=0;
    int commands=0;
    uint64_t stamp=0;
    std::vector<uint32_t> current,preview,casting;
};
static Sample sample() {
    Sample out;auto& s=state();auto& owner=actors::state();const auto& acquired=ui::state();
    require(visual::frontendObservation(out.pose),"visual click has no current completed visual join");
    require(out.pose.identity.world==s.world&&out.pose.identity.match==s.match&&
        visual::policy::sameIdentity(out.pose.identity,s.anchor.identity)&&out.pose.lease==s.anchor.lease&&
        out.pose.generation==s.anchor.generation&&out.pose.actor==s.anchor.actor&&out.pose.transform==s.anchor.transform&&
        out.pose.simulation==s.anchor.simulation&&out.pose.manager==s.anchor.manager,
        "visual click changed its actor incarnation or presentation lifetime");
    out.selector=ba_prediction_selection::currentSelector();out.camera=acquired.focusCamera;
    require(acquired.world==s.world&&acquired.match==s.match&&acquired.focusReturned&&
        out.selector==acquired.focusSelector&&ba::read<Obj>(out.selector,0xc0)==out.camera&&
        out.pose.lease==acquired.focusOwner.lease&&out.pose.generation==acquired.focusOwner.generation&&
        visual::policy::sameIdentity(out.pose.identity,acquired.focusOwner.identity),
        "visual click lost the acquired original camera/selector");
    vm::ownerGraph(owner,out.selector);history::validateHistory(out.selector);
    actors::clickField(out.selector,"_currentPointerPosition",0x14c,actors::type("UnityEngine","Vector2"),8);
    ui::resolve(out.selector,out.camera,out.pose.transform);out.actual=ui::position(out.pose.transform);
    require(ui::equal(out.actual,out.pose.displayed),"visual click actual root differs from completed join");
    out.click=history::history(out.selector);out.now=actors::clickNow();
    require(std::isfinite(out.now)&&out.now>=out.click.lastUp,"visual click original clock regressed");
    out.x=ba::read<float>(out.selector,0x14c);out.y=ba::read<float>(out.selector,0x150);
    require(std::isfinite(out.x)&&std::isfinite(out.y),"visual click original pointer is nonfinite");
    out.current=ba_prediction_selection::selectionIds(ba::read<Obj>(out.selector,0x90));
    out.preview=ba_prediction_selection::selectionIds(ba::read<Obj>(out.selector,0x88));
    out.casting=ba_prediction_selection::selectionIds(ba::read<Obj>(out.selector,0x98));
    out.mouse=vm::observe();out.context=vm::originalBoolean(vm::api().isPressed,vm::session().controls[2]->get());
    out.commands=pending();out.stamp=visual::stamp();
    require(out.stamp>=out.pose.joinedUs&&out.stamp-out.pose.joinedUs<=50000&&
        out.pose.publicationUs<=out.pose.policyUs&&out.pose.policyUs<=out.pose.joinedUs&&
        out.stamp>=acquired.focusReturned&&out.stamp-acquired.focusReturned>=200000,
        "visual click completed join is stale or camera not settled");
    return out;
}
static std::string fields(const Sample& value,const char* event,uint64_t sequence) {
    const auto& s=state();
    const auto& p=value.pose;const auto& h=value.click;const auto& m=value.mouse;
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::setprecision(17)<<std::boolalpha;
    out<<"{\"schema\":1,\"event\":\""<<event<<"\",\"world\":"<<s.world<<",\"match\":\""<<s.match
       <<"\",\"episode\":"<<s.episode<<",\"control\":\""<<(s.episode==1?"zero":"nonzero")<<"\",\"sequence\":"<<sequence
       <<",\"frontend_ordinal\":"<<ordinal()<<",\"sampled_us\":"<<value.stamp<<",\"frame\":"<<p.frame
       <<",\"entity\":"<<p.identity.entity<<",\"unit_type\":"<<p.identity.unitType<<",\"army\":"<<p.identity.army
       <<",\"incarnation\":"<<p.identity.incarnation<<",\"lease\":"<<p.lease<<",\"generation\":"<<p.generation
       <<",\"thread\":"<<GetCurrentThreadId()<<",\"owner_thread\":"<<actors::state().thread
       <<",\"selector\":"<<ui::pointer(value.selector)<<",\"manager\":"<<ui::pointer(p.manager)
       <<",\"simulation\":"<<ui::pointer(p.simulation)<<",\"actor\":"<<ui::pointer(p.actor)
       <<",\"transform\":"<<ui::pointer(p.transform)<<",\"camera\":"<<ui::pointer(value.camera)
       <<",\"focus_ordinal\":"<<ui::state().focusOrdinal<<",\"focus_returned_us\":"<<ui::state().focusReturned
       <<",\"pending_commands\":"<<value.commands<<",\"current_ids\":"<<ids(value.current)
       <<",\"preview_ids\":"<<ids(value.preview)<<",\"casting_ids\":"<<ids(value.casting)
       <<",\"pointer\":["<<value.x<<','<<value.y<<"],\"queued_point\":["<<s.point.x()<<','<<s.point.y()<<']'
       <<",\"history\":{\"id\":"<<h.id<<",\"mode\":"<<h.mode<<",\"primary\":"<<h.primary
       <<",\"context\":"<<h.context<<",\"drag\":"<<h.drag<<",\"now\":"<<value.now
       <<",\"last_up\":"<<h.lastUp<<",\"window\":"<<h.window<<'}'
       <<",\"mouse\":{\"action\":"<<ui::pointer(m.action)<<",\"control\":"<<ui::pointer(m.control)
       <<",\"device\":"<<ui::pointer(m.device)<<",\"queued_sequence\":"<<m.queuedSequence
       <<",\"primary\":"<<m.ownedButtonPressed<<",\"context\":"<<value.context<<'}'
       <<",\"pose\":{\"frame\":"<<p.frame<<",\"revision\":"<<p.revision<<",\"joined_us\":"<<p.joinedUs
       <<",\"policy_us\":"<<p.policyUs<<",\"publication_us\":"<<p.publicationUs<<",\"alpha\":"<<p.alpha
       <<",\"raw\":"<<visual::xyz(p.raw)<<",\"displayed\":"<<visual::xyz(p.displayed)
       <<",\"offset\":["<<p.offset.x<<','<<p.offset.y<<','<<p.offset.z<<"],\"actual\":"<<visual::xyz(value.actual)
       <<",\"root_matches_join\":true},\"physical_input\":false,\"selection_writes\":0,\"history_writes\":0,\"sync_transforms\":false";
    return out.str();
}
static std::string common(const Sample& value,const char* event) {
    auto& s=state();require(s.sequence<32,"visual click bounded record count exhausted");
    return fields(value,event,++s.sequence);
}
struct HitReceipt {bool inside=false,rawInside=false,subject=false,discriminates=false;std::string json;};
static HitReceipt hit(const Sample& value,float x,float y) {
    auto& owner=actors::state();const Vec3 point{x,y,1};const Vec3 raw=ui::project(value.camera,value.pose.raw);
    const int width=history::screenDimension("get_width",0x06000479,0x5038860,
        "\x48\x83\xec\x28\x48\x8b\x05\x45\xa1\xe2\x01\x48\x85\xc0\x75\x18");
    const int height=history::screenDimension("get_height",0x0600047a,0x50388b0,
        "\x48\x83\xec\x28\x48\x8b\x05\xfd\xa0\xe2\x01\x48\x85\xc0\x75\x18");
    require(width>0&&height>0,"visual click viewport dimensions differ");
    auto inside=[&](Vec3 p){return p.x>=3&&p.y>=3&&p.x<=width-3&&p.y<=height-3;};
    auto displayedHit=ui::ray(value.selector,point,owner),rawHit=ui::ray(value.selector,raw,owner);
    HitReceipt out;out.inside=inside(point);out.rawInside=inside(raw);
    out.subject=displayedHit.hit&&displayedHit.unit==value.pose.actor;
    out.discriminates=displayedHit.hit!=rawHit.hit||displayedHit.unit!=rawHit.unit;
    std::ostringstream json;json.imbue(std::locale::classic());json<<std::setprecision(17)<<std::boolalpha;
    json<<"{\"point\":["<<x<<','<<y<<"],\"raw_point\":["<<raw.x<<','<<raw.y<<"],\"viewport\":["<<width<<','<<height
        <<"],\"inside\":"<<out.inside<<",\"raw_inside\":"<<out.rawInside
        <<",\"displayed\":{\"hit\":"<<displayedHit.hit<<",\"identity\":"<<displayedHit.identity
        <<"},\"raw\":{\"hit\":"<<rawHit.hit<<",\"identity\":"<<rawHit.identity<<"},\"discriminates\":"<<out.discriminates<<'}';
    out.json=json.str();return out;
}
static bool sameVectorBits(Vec3 a,Vec3 b){return std::memcmp(&a,&b,sizeof(a))==0;}
static bool samePose(const visual::FrontendObservation& a,const visual::FrontendObservation& b) {
    return visual::policy::sameIdentity(a.identity,b.identity)&&a.lease==b.lease&&a.generation==b.generation&&
        a.frame==b.frame&&a.revision==b.revision&&a.joinedUs==b.joinedUs&&a.policyUs==b.policyUs&&a.publicationUs==b.publicationUs&&
        protocol::Point::bits(a.alpha)==protocol::Point::bits(b.alpha)&&a.actor==b.actor&&a.transform==b.transform&&
        a.manager==b.manager&&a.simulation==b.simulation&&sameVectorBits(a.raw,b.raw)&&sameVectorBits(a.displayed,b.displayed)&&
        a.offset.x==b.offset.x&&a.offset.y==b.offset.y&&a.offset.z==b.offset.z;
}
static bool unchanged(const Sample& before,const Sample& after) {
    const auto& h=before.click;const auto& k=after.click;const auto& m=before.mouse;const auto& n=after.mouse;
    return samePose(before.pose,after.pose)&&sameVectorBits(before.actual,after.actual)&&
        before.selector==after.selector&&before.camera==after.camera&&before.commands==after.commands&&
        before.current==after.current&&before.preview==after.preview&&before.casting==after.casting&&
        protocol::Point::bits(before.x)==protocol::Point::bits(after.x)&&protocol::Point::bits(before.y)==protocol::Point::bits(after.y)&&
        h.id==k.id&&h.mode==k.mode&&h.primary==k.primary&&h.context==k.context&&h.drag==k.drag&&
        protocol::Point::bits(h.lastUp)==protocol::Point::bits(k.lastUp)&&protocol::Point::bits(h.window)==protocol::Point::bits(k.window)&&
        m.world==n.world&&m.match==n.match&&m.selector==n.selector&&m.action==n.action&&m.control==n.control&&m.device==n.device&&
        m.queuedSequence==n.queuedSequence&&m.selectorPrimaryHeld==n.selectorPrimaryHeld&&m.selectorContextHeld==n.selectorContextHeld&&
        m.ownedButtonPressed==n.ownedButtonPressed&&before.context==after.context;
}
static std::string pointJson(protocol::ScreenPoint p) {
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::setprecision(17)<<'['<<p.x<<','<<p.y<<']';return out.str();
}
static std::string pointBits(protocol::ScreenPoint p) {
    std::ostringstream out;out<<'['<<protocol::Point::bits(p.x)<<','<<protocol::Point::bits(p.y)<<']';return out.str();
}
static void spatial(const Sample& value,unsigned phase,const ba_prediction_input_observer::Ticket& ticket,
                    Obj downInfo,const void* context) {
    if(!spatialEnabled())return;
    auto& s=state();require(enabled()&&s.active&&s.episode>=1&&s.episode<=2&&phase<3&&
        ticket.kind==input::Kind::Down&&ticket.serial==s.progress.downTicket&&
        s.aimSequence==(s.episode-1)*3+phase,"visual aim phase/episode binding differs");
    const Vec3 q=ui::project(value.camera,value.actual),r=ui::project(value.camera,value.pose.raw);
    const protocol::ScreenPoint p{s.point.x(),s.point.y()},q2{q.x,q.y},r2{r.x,r.y};
    if(phase==0) {
        s.aim=AimFrozen{};s.aim.pose=value.pose;s.aim.camera=value.camera;s.aim.actual=value.actual;s.aim.q=q;s.aim.r=r;
        s.aim.matched=protocol::matchedAnchor(p,q2,r2);s.aim.points={{p,q2,r2,s.aim.matched.raw}};s.aim.bound=true;
    } else require(s.aim.bound&&samePose(s.aim.pose,value.pose)&&s.aim.camera==value.camera&&
        sameVectorBits(s.aim.actual,value.actual)&&sameVectorBits(s.aim.q,q)&&sameVectorBits(s.aim.r,r)&&
        protocol::Point::bits(s.aim.points[0].x)==protocol::Point::bits(p.x)&&
        protocol::Point::bits(s.aim.points[0].y)==protocol::Point::bits(p.y),
        "visual aim phase changed its frozen joined pose, camera or projected point bits");
    const auto& matched=s.aim.matched;const auto& points=s.aim.points;
    static const char* names[]={"consumed","displayed_root","raw_root","matched_raw"};
    static const char* phases[]={"down_before","process_before","process_returned"};
    const int width=history::screenDimension("get_width",0x06000479,0x5038860,
        "\x48\x83\xec\x28\x48\x8b\x05\x45\xa1\xe2\x01\x48\x85\xc0\x75\x18");
    const int height=history::screenDimension("get_height",0x0600047a,0x50388b0,
        "\x48\x83\xec\x28\x48\x8b\x05\xfd\xa0\xe2\x01\x48\x85\xc0\x75\x18");
    require(width>0&&height>0,"visual aim viewport differs");
    std::ostringstream queries,coordinates,bits;queries<<'[';coordinates<<'{';bits<<'{';
    uint64_t ended=value.stamp;
    for(unsigned i=0;i<4;++i) {
        const auto point=points[i];const auto begin=visual::stamp();
        require(begin>=ended,"visual aim query clock regressed");
        const auto result=ui::ray(value.selector,Vec3{point.x,point.y,1},actors::state());const auto end=visual::stamp();
        require(end>=begin,"visual aim original query clock regressed");
        const auto after=sample();require(after.stamp>=end&&unchanged(value,after),
            "visual aim original query changed root, history, selection, Mouse or owner");ended=after.stamp;
        const bool inside=point.x>=3&&point.y>=3&&point.x<=width-3&&point.y<=height-3;
        if(i){queries<<',';coordinates<<',';bits<<',';}
        queries<<"{\"point_kind\":\""<<names[i]<<"\",\"begin_us\":"<<begin<<",\"end_us\":"<<end
            <<",\"point\":"<<pointJson(point)<<",\"inside\":"<<(inside?"true":"false")
            <<",\"hit\":"<<(result.hit?"true":"false")<<",\"identity\":"<<result.identity<<'}';
        coordinates<<'"'<<names[i]<<"\":"<<pointJson(point);bits<<'"'<<names[i]<<"\":"<<pointBits(point);
    }
    queries<<']';coordinates<<'}';bits<<'}';
    std::ostringstream out;out<<fields(value,"probe",++s.aimSequence)<<",\"phase\":\""<<phases[phase]
       <<"\",\"ticket_serial\":"<<ticket.serial<<",\"down_method_info\":"<<ui::pointer(downInfo)
       <<",\"context_pointer\":"<<ui::pointer(const_cast<void*>(context))<<",\"sample_end_us\":"<<ended
       <<",\"root_screen\":"<<visual::xyz(q)<<",\"raw_root_screen\":"<<visual::xyz(r)
       <<",\"relative_offset\":"<<pointJson(matched.offset)<<",\"relative_offset_bits\":"<<pointBits(matched.offset)
       <<",\"points\":"<<coordinates.str()<<",\"point_bits\":"<<bits.str()<<",\"viewport\":["<<width<<','<<height
       <<"],\"queries\":"<<queries.str()<<",\"unchanged\":true}";
    ba::log("VISUAL AIM %s",out.str().c_str());
}
static void requirePoint(const Sample& value) {
    const auto& s=state();if(s.point.matches(value.x,value.y))return;
    ba::log("Visual click pointer refused: world=%llu episode=%u actual=[%.9g,%.9g] expected=[%.9g,%.9g] actualBits=[%08x,%08x] expectedBits=[%08x,%08x]",
        static_cast<unsigned long long>(s.world),s.episode,value.x,value.y,s.point.x(),s.point.y(),
        protocol::Point::bits(value.x),protocol::Point::bits(value.y),protocol::Point::bits(s.point.x()),protocol::Point::bits(s.point.y()));
    require(false,"visual click callback pointer differs from the actual queued event");
}
static void probe(bool before,const ba_prediction_input_observer::Ticket& ticket,Obj selector,Obj info,
                  const void* context,bool completed,uint64_t ledgerSerial) {
    auto& s=state();require(enabled()&&s.active&&!s.failed&&!s.complete&&selector==vm::session().selector->get()&&
        ticket.owner==input::owner(selector),"visual click callback has no borrowed session owner");
    const bool down=ticket.kind==input::Kind::Down;
    require(down||ticket.kind==input::Kind::Up,"visual click observed another callback kind");
    auto value=sample();requirePoint(value);
    const auto accepted=actors::state().inputIntent.accepted();
    const bool single=accepted&&accepted->serial==ticket.serial&&accepted->owner==ticket.owner&&accepted->kind==input::Kind::Down;
    std::string hitJson;
    if(before) {
        s.progress.before(down,ticket.serial,ordinal(),value.stamp);s.beforeCommands=value.commands;
        if(down) {
            require(!value.click.primary&&!value.click.context&&!value.click.drag&&value.mouse.ownedButtonPressed&&!value.context&&
                value.now-value.click.lastUp>value.click.window,"visual click Down is not an expired released primary gesture");
            const double amount=magnitude(value.pose);require(s.episode==1?amount==0:amount>=0.5,
                "visual click callback lacks its requested correction control");
            spatial(value,0,ticket,info,context);
            const auto observed=hit(value,value.x,value.y);
            require(observed.inside&&observed.rawInside&&observed.subject&&(s.episode==1||observed.discriminates),
                "visual click callback ray does not qualify the displayed subject");
            hitJson=",\"hit_test\":"+observed.json;
        }
    } else {
        require(!down||s.processStage==2,"visual click Down returned without original ProcessClick return");
        s.progress.returned(down,ticket.serial,value.stamp,completed&&single);
        require(value.commands==s.beforeCommands,"visual click original callback added a command");
        if(down) {
            require(value.click.primary&&!value.click.context&&!value.click.drag&&value.click.mode==1&&
                value.click.id==value.pose.identity.entity&&value.mouse.ownedButtonPressed&&!value.context,
                "visual click original Down did not preserve the subject Single gesture");
        } else {
            require(!value.click.primary&&!value.click.context&&!value.click.drag&&!value.mouse.ownedButtonPressed&&!value.context&&
                value.click.mode==0&&value.current==std::vector<uint32_t>{value.pose.identity.entity},
                "visual click original Up did not commit the subject and release the Mouse");
        }
    }
    const auto& route=input::routes[static_cast<unsigned>(ticket.kind)];
    std::ostringstream out;out<<common(value,before?"callback_before":"callback_returned")
       <<",\"kind\":\""<<(down?"Down":"Up")<<"\",\"ticket_serial\":"<<ticket.serial
       <<",\"ledger_serial\":"<<ledgerSerial<<",\"ledger_completed\":"<<(before?"null":completed?"true":"false")
       <<",\"single_accepted\":"<<(single?"true":"false")<<",\"method_info\":"<<ui::pointer(info)
       <<",\"dispatch_thunk\":"<<ui::pointer(ba::read<Obj>(info,0))<<",\"method_token\":\""<<(down?"0x06002266":"0x06002267")
       <<"\",\"method_rva\":\""<<(down?"0x3bf7d20":"0x3bf7f60")<<"\",\"context_pointer\":"<<ui::pointer(const_cast<void*>(context))<<hitJson<<'}';
    require(ba::read<Obj>(info,8)==ba::read<Obj>(ba::native<Obj>(route.slot),0),"visual click dispatch witness changed");
    ba::log("VISUAL CLICK %s",out.str().c_str());
}
static void process(bool before,const ba_prediction_input_observer::Ticket& ticket,Obj selector,Obj downInfo,
                    const void* context,Obj originalInfo) {
    auto& s=state();require(enabled()&&s.active&&!s.failed&&ticket.kind==input::Kind::Down&&
        s.progress.stage==protocol::Stage::DownEntered&&s.progress.ticket==ticket.serial&&
        selector==vm::session().selector->get()&&ticket.owner==input::owner(selector)&&!originalInfo,
        "visual ProcessClick has another original Down owner");
    auto value=sample();require(s.processStage==(before?0u:1u),"visual ProcessClick is duplicated or lacks entry");
    requirePoint(value);
    if(before){s.processCommands=value.commands;s.processUs=value.stamp;}
    else require(value.stamp>=s.processUs&&value.commands==s.processCommands&&value.click.primary&&
        !value.click.context&&!value.click.drag&&value.click.mode==1&&value.click.id==value.pose.identity.entity,
        "visual original ProcessClick return lost Single subject or added commands");
    spatial(value,before?1u:2u,ticket,downInfo,context);
    ++s.processStage;
    std::ostringstream out;out<<common(value,before?"process_before":"process_returned")
       <<",\"ticket_serial\":"<<ticket.serial<<",\"down_method_info\":"<<ui::pointer(downInfo)
       <<",\"method_info\":"<<ui::pointer(originalInfo)<<",\"method_rva\":\"0x3bf4a60\",\"original_entry\":"
       <<ui::pointer(ba::native<Obj>(0x3bf4a60))<<",\"context_pointer\":"<<ui::pointer(const_cast<void*>(context))<<'}';
    ba::log("VISUAL CLICK %s",out.str().c_str());
}
static void queue(bool held,const char* event) {
    auto& s=state();vm::queuePositionButton(s.point.x(),s.point.y(),held);auto value=sample();
    s.progress.queue(static_cast<unsigned>(value.mouse.queuedSequence),ordinal(),value.stamp);
    ba::log("VISUAL CLICK %s}",common(value,event).c_str());
}
static unsigned roots() {
    const auto& s=vm::session();unsigned count=0;
    for(const auto* p:{&s.selector,&s.handler,&s.server,&s.manager,&s.simulation,&s.device})if(*p)++count;
    for(unsigned i=0;i<3;++i){if(s.controls[i])++count;if(s.actions[i])++count;if(s.references[i])++count;}return count;
}
static void update() {
    require(ui::enabled()&&vm::session().kind==vm::SessionKind::Primary,"visual click requires its primary visual input diagnostic");
    auto& s=state();const uint64_t world=ba_prediction_worker::movementWorldId();const auto match=ba_prediction_worker::movementMatchId();
    if(!world)return;
    if(s.world!=world||s.match!=match) {
        require(!s.world||s.complete,"visual click old world did not finish both balanced episodes");
        require(!vm::session().active&&!roots(),"visual click old borrowed Mouse roots survived rematch");
        s=State{};s.world=world;s.match=match;
    }
    if(s.complete)return;
    const auto& acquired=ui::state();if(acquired.world!=world||acquired.match!=match||!acquired.zeroBefore)return;
    visual::FrontendObservation pose;if(!visual::frontendObservation(pose))return;
    require(pose.frame<=600,"visual click bounded acquisition window exhausted");
    if(!s.active) {
        const double amount=magnitude(pose);if(s.episode==0?amount!=0:amount<0.5)return;
        auto& owner=actors::state();Obj selector=ba_prediction_selection::currentSelector();
        vm::ownerGraph(owner,selector);history::validateHistory(selector);const auto h=history::history(selector);
        const auto now=actors::clickNow();require(std::isfinite(now)&&now>=h.lastUp,"visual click acquisition clock regressed");
        if(now-h.lastUp<=h.window)return;
        require(!h.primary&&!h.context&&!h.drag,"visual click cannot borrow an active gesture");
        s.anchor=pose;vm::begin(owner,selector);s.active=true;++s.episode;s.progress=protocol::Progress{};s.processStage=0;
        input::visualProbe=&probe;input::visualProcessProbe=&process;
        const auto value=sample();const auto projected=ui::project(value.camera,value.actual);
        s.point=protocol::Point{};s.point.bind(projected.x,projected.y);
        queue(false,"position_queued");return;
    }
    if(s.progress.stage==protocol::Stage::PositionQueued) {
        if(ordinal()<=s.progress.queuedOrdinal)return;
        const auto value=sample();
        if(!s.point.matches(value.x,value.y))return;
        require(!value.click.primary&&!value.click.context&&!value.click.drag&&!value.mouse.ownedButtonPressed&&!value.context,
            "visual click position event delivered an unexpected gesture");
        const double amount=magnitude(value.pose);if(s.episode==1?amount!=0:amount<0.5)return;
        // Position delivery was observed at this exact point. Press and release
        // retain it; movement of the displayed unit never retargets this episode.
        const auto observed=hit(value,s.point.x(),s.point.y());
        if(!observed.inside||!observed.rawInside||!observed.subject||(s.episode==2&&!observed.discriminates))return;
        queue(true,"down_queued");return;
    }
    if(s.progress.stage==protocol::Stage::DownReturned) {
        if(ordinal()<=s.progress.queuedOrdinal)return;
        const auto value=sample();require(value.mouse.ownedButtonPressed&&value.click.primary&&!value.context&&!value.click.drag,
            "visual click returned Down is no longer held");
        s.pressed=value.mouse;s.pressOrdinal=ordinal();queue(false,"up_queued");return;
    }
    if(s.progress.stage==protocol::Stage::UpReturned) {
        if(ordinal()<=s.progress.queuedOrdinal)return;
        const auto value=sample();const bool released=!value.mouse.ownedButtonPressed&&!value.context&&!value.click.primary&&
            !value.click.context&&!value.click.drag&&value.click.mode==0&&
            value.current==std::vector<uint32_t>{value.pose.identity.entity};
        s.progress.close(ordinal(),value.stamp,released);
        const unsigned before=roots();require(before==15,"visual click borrowed root count differs");
        vm::close(vm::ReleaseObservation{s.pressed,value.mouse,s.pressOrdinal,ordinal()});
        require(!roots()&&!vm::session().active,"visual click borrowed roots did not close");
        input::visualProbe=nullptr;input::visualProcessProbe=nullptr;s.active=false;
        ba::log("VISUAL CLICK %s,\"roots_before\":%u,\"roots_after\":0,\"balanced\":true}",common(value,"closed").c_str(),before);
        if(s.episode==2)s.complete=true;
    }
}
static void tick() {
    if((!enabled()&&!spatialEnabled())||state().failed)return;
    try {
        require(enabled(),"visual click spatial diagnostic requires the original click diagnostic");
        static bool marked=false;if(!marked){ba::log("BA_RESURRECTION_VISUAL_CLICK_SMOKE_V1");
            if(spatialEnabled())ba::log("BA_RESURRECTION_VISUAL_AIM_V1");marked=true;}
        require(ordinal()!=UINT64_MAX,"visual click frontend ordinal exhausted");++ordinal();update();
    } catch(const std::exception& error) {
        state().failed=true;input::visualProbe=nullptr;input::visualProcessProbe=nullptr;
        ba::log("Prediction visual click smoke failed: %s",error.what());
        ba_prediction_worker::movementFail(error.what());
    }
}
}
