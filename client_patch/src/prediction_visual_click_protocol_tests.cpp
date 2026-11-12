#include "prediction_visual_click_protocol.hpp"
#include <iostream>
#include <limits>
#include <stdexcept>

namespace test {
using ba_prediction_visual_click_protocol::Progress;
using ba_prediction_visual_click_protocol::Stage;
using ba_prediction_visual_click_protocol::Point;
static void check(bool value,const char* why){if(!value)throw std::runtime_error(why);}
template<class F>static void refuses(F action) {
    bool failed=false;try{action();}catch(const std::invalid_argument&){failed=true;}
    check(failed,"invalid visual click ordering was accepted");
}
static Progress waitingDown() {Progress p;p.queue(1,10,100);p.queue(2,11,110);return p;}
static Progress waitingUp() {
    auto p=waitingDown();p.before(true,7,11,111);p.returned(true,7,112,true);p.queue(3,12,120);return p;
}
static void balanced() {
    auto p=waitingUp();p.before(false,9,12,121);p.returned(false,9,122,false);p.close(13,123,true);
    check(p.stage==Stage::Closed,"balanced click did not close");
    refuses([&]{p.queue(1,14,140);});refuses([&]{p.close(14,140,true);});
}
static void actualDeliveryRequired() {
    auto p=waitingDown();refuses([&]{p.queue(3,12,120);});refuses([&]{p.close(12,120,true);});
    refuses([&]{p.before(true,7,10,111);});refuses([&]{p.before(true,7,11,110);});
    p.before(true,7,11,111);refuses([&]{p.before(true,8,12,112);});
    refuses([&]{p.returned(true,8,112,true);});refuses([&]{p.returned(true,7,110,true);});
}
static void singleAndBalancedReleaseRequired() {
    auto p=waitingDown();p.before(true,7,11,111);refuses([&]{p.returned(true,7,112,false);});
    p.returned(true,7,112,true);refuses([&]{p.queue(3,11,120);});refuses([&]{p.queue(3,12,112);});
    p.queue(3,12,120);refuses([&]{p.before(false,7,12,121);});
    p.before(false,9,12,121);p.returned(false,9,122,false);
    refuses([&]{p.close(12,123,true);});refuses([&]{p.close(13,123,false);});p.close(13,123,true);
}
static void noSyntheticCallbacksOrCrossEpisodeTickets() {
    Progress p;refuses([&]{p.before(true,1,1,1);});refuses([&]{p.queue(2,1,1);});
    p.queue(1,10,100);refuses([&]{p.queue(2,10,101);});refuses([&]{p.queue(2,11,100);});
    p.queue(2,11,110);refuses([&]{p.before(false,2,11,111);});
    auto up=waitingUp();refuses([&]{up.returned(false,9,121,false);});
    up.before(false,9,12,121);refuses([&]{up.returned(true,9,122,true);});
}
static void consumedPositionCannotBeRetargetedAtPress() {
    // Retained Actual86: position delivery A was observed, then the diagnostic
    // reprojected the moving unit to B at press. B is not the consumed event A.
    constexpr float ax=499.185455322265625f,ay=282.197265625f;
    constexpr float bx=499.34808349609375f,by=282.3006591796875f;
    Point point;point.bind(ax,ay);auto progress=waitingDown();
    check(point.matches(ax,ay)&&!point.matches(bx,by),"retargeted press was confused with consumed position");
    refuses([&]{point.bind(bx,by);});
    progress.before(true,7,11,111);progress.returned(true,7,112,true);progress.queue(3,12,120);
    check(point.x()==ax&&point.y()==ay&&point.matches(ax,ay),"press changed the retained release point");
    progress.before(false,9,12,121);progress.returned(false,9,122,false);progress.close(13,123,true);
    check(point.matches(ax,ay),"balanced close changed the original consumed point");
}
static void pointBindingIsFiniteExactAndSingleUse() {
    Point point;refuses([&]{(void)point.x();});refuses([&]{(void)point.y();});
    refuses([&]{point.bind(std::numeric_limits<float>::infinity(),2);});
    refuses([&]{point.bind(1,std::numeric_limits<float>::quiet_NaN());});
    point.bind(499.185455322265625f,282.197265625f);
    refuses([&]{point.bind(point.x(),point.y());});
    check(!point.matches(std::nextafter(point.x(),std::numeric_limits<float>::infinity()),point.y()),
        "different Single bits were accepted as the consumed mouse position");
    check(point.matches(point.x(),point.y()),"unchanged Single point was refused");
}
static void matchedCounterfactualPreservesTheSameSeparatelyRoundedOffset() {
    using namespace ba_prediction_visual_click_protocol;
    const ScreenPoint p{562.58062744140625f,309.367584228515625f};
    const ScreenPoint q{560.16766357421875f,307.831512451171875f};
    const ScreenPoint r{584.36260986328125f,323.234893798828125f};
    const auto matched=matchedAnchor(p,q,r);
    check(matched.offset.x==2.4129638671875f&&matched.offset.y==1.53607177734375f&&
        matched.raw.x==586.77557373046875f&&matched.raw.y==324.770965576171875f,
        "Actual87 consumed point offset was not applied to the raw projection");
    const auto zero=matchedAnchor(p,p,r);check(zero.offset.x==0&&zero.offset.y==0&&
        zero.raw.x==r.x&&zero.raw.y==r.y,"zero spatial offset changed the raw counterfactual");
    const auto rounded=matchedAnchor({16777216.0f,16777216.0f},{-1.0f,-1.0f},{-16777216.0f,-16777216.0f});
    check(rounded.offset.x==16777216.0f&&rounded.raw.x==0&&rounded.raw.y==0,
        "spatial counterfactual used double reassociation instead of two Single operations");
    refuses([&]{(void)matchedAnchor({std::numeric_limits<float>::max(),0},{-std::numeric_limits<float>::max(),0},{0,0});});
}
static void firstAcquisitionRequiresNaturalEmptySelection() {
    using ba_prediction_visual_click_protocol::acquireSelection;
    // Actual88's original hover adds preview74 while committed selection stays
    // empty until Up. The unsuccessful90 empty click instead retained current74.
    check(acquireSelection(false,1.884,74,{}, {}, {}),"natural empty acquisition was refused");
    check(acquireSelection(false,1.688,74,{}, {74}, {}),"original subject hover was treated as committed selection");
    check(!acquireSelection(false,1.688,74,{74}, {}, {}),"already-selected subject qualified as a first acquisition");
    check(!acquireSelection(false,1.688,74,{}, {}, {74}),"active casting qualified as an empty acquisition");
    check(!acquireSelection(false,0,74,{}, {}, {}),"zero control qualified as a corrected acquisition");
}
static void firstAcquisitionRequiresActualCorrectedUpCommit() {
    using ba_prediction_visual_click_protocol::acquireSelection;
    check(acquireSelection(true,0.5,74,{74},{},{}),"corrected original Up commit was refused");
    check(!acquireSelection(true,1.5,74,{}, {}, {}),"released but uncommitted Up qualified");
    check(!acquireSelection(true,1.5,74,{75},{},{}),"another selected unit qualified");
    check(!acquireSelection(true,1.5,74,{74,75},{},{}),"multiple selected units qualified");
    check(!acquireSelection(true,1.5,74,{74},{74},{}),"held preview qualified as completed Up");
    check(!acquireSelection(true,std::nextafter(0.5,0.0),74,{74},{},{}),"correction that expired before commit qualified");
    check(!acquireSelection(true,std::numeric_limits<double>::infinity(),74,{74},{},{}),"nonfinite correction qualified");
    check(!acquireSelection(true,std::numeric_limits<double>::quiet_NaN(),74,{74},{},{}),"unknown correction qualified");
}
static void neutralPrefixPreservesActualFourEventOrdinals() {
    Progress p;p.afterNeutral(10,100,11,110);
    refuses([&]{p.queue(1,12,120);});refuses([&]{p.queue(3,12,120);});
    refuses([&]{p.before(true,7,12,120);});refuses([&]{p.close(12,120,true);});
    p.queue(2,12,120);p.queue(3,13,130);p.before(true,7,13,131);p.returned(true,7,132,true);
    refuses([&]{p.queue(3,14,140);});p.queue(4,14,140);
    p.before(false,9,14,141);p.returned(false,9,142,false);p.close(15,143,true);
    check(p.stage==Stage::Closed&&p.neutralPrefix,"four actual events did not close one balanced first click");
    refuses([&]{p.queue(1,16,160);});
    Progress legacy;legacy.queue(1,10,100);refuses([&]{legacy.queue(3,11,110);});
}
static void neutralPrefixRequiresBoundedActualConsumption() {
    Progress p;
    refuses([&]{p.afterNeutral(10,100,10,110);});
    refuses([&]{p.afterNeutral(10,100,11,100);});
    refuses([&]{p.afterNeutral(10,100,11,250101);});
    refuses([&]{p.afterNeutral(0,100,11,110);});
    p.afterNeutral(10,100,11,250100);
    refuses([&]{p.afterNeutral(10,100,12,250100);});
    refuses([&]{p.queue(2,11,250101);});
    refuses([&]{p.queue(2,12,250100);});
    p.queue(2,12,250101);
    auto alreadyStarted=waitingDown();refuses([&]{alreadyStarted.afterNeutral(10,100,12,120);});
}
static void neutralAndSubjectPointsAreSeparateImmutableControls() {
    Point neutral,subject;neutral.bind(480,270);subject.bind(558.1957397460938f,319.71246337890625f);
    check(!neutral.matches(subject.x(),subject.y()),"neutral control was relabeled as subject delivery");
    refuses([&]{neutral.bind(subject.x(),subject.y());});
    refuses([&]{subject.bind(neutral.x(),neutral.y());});
    check(neutral.matches(480,270)&&subject.matches(558.1957397460938f,319.71246337890625f),
        "subject acquisition retargeted a consumed neutral event");
}
static void nestedWorldResetRetainsDefaultProtocol() {
    struct Nested {Progress progress;};struct World {Nested click;Point point;};
    World world{};world.click.progress=waitingUp();world.point.bind(1,2);
    world=World{};
    check(world.click.progress.stage==Stage::Ready,"new world inherited an old click stage");
    refuses([&]{world.point.x();});
    world.click.progress=waitingDown();world.click.progress.before(true,7,11,111);
    refuses([&]{world.click.progress.returned(true,7,112,false);});
}
}
int main(){try{
    test::balanced();test::actualDeliveryRequired();test::singleAndBalancedReleaseRequired();test::noSyntheticCallbacksOrCrossEpisodeTickets();
    test::consumedPositionCannotBeRetargetedAtPress();test::pointBindingIsFiniteExactAndSingleUse();
    test::matchedCounterfactualPreservesTheSameSeparatelyRoundedOffset();
    test::firstAcquisitionRequiresNaturalEmptySelection();test::firstAcquisitionRequiresActualCorrectedUpCommit();
    test::nestedWorldResetRetainsDefaultProtocol();
    test::neutralPrefixPreservesActualFourEventOrdinals();test::neutralPrefixRequiresBoundedActualConsumption();
    test::neutralAndSubjectPointsAreSeparateImmutableControls();
    std::cout<<"visual click protocol:13 authored groups PASS; original runtime remains separate\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
