#include "prediction_queued_orders_smoke.hpp"
#include <cassert>
#include <functional>
#include <limits>
using namespace ba_prediction_queued_orders;
static void refused(const std::function<void()>& operation) {
    bool failed=false;try{operation();}catch(const std::runtime_error&){failed=true;}assert(failed);
}
int main() {
    const auto points=std::vector<policy::close::Point>{{81,0,61},{81,0,59},{79,0,61},{79,0,59}};
    const auto targets=policy::targets(points);
    assert(targets.first.x==80.f&&targets.first.y==0.f&&targets.first.z==76.f);
    assert(targets.queued.x==81.f&&targets.queued.y==0.f&&targets.queued.z==45.f);
    const auto ordered=policy::targets({{100000000.f,0,0},{1,0,0},{-100000000.f,0,0},{1,0,0}});
    assert(ordered.first.x==.25f);
    refused([](){policy::targets({});});
    refused([](){policy::targets({{0,0,0},{0,0,0},{0,0,0},{0,0,std::numeric_limits<float>::infinity()}});});
    policy::cache({14,11,13,12},{11,12,13,14},4);
    policy::cache({11},{11},1,true);
    refused([](){policy::cache({11,12,13,14},{11,12,13,14},4,true);});
    refused([](){policy::cache({11},{11,12},1,true);});
    refused([](){policy::cache({11},{11},0,true);});
    policy::order(policy::Tag::Approach,{11,12,13,14},12,false,0);
    policy::order(policy::Tag::First,{11},88,false,0);
    policy::order(policy::Tag::Queued,{11},12,true,1); // A may already be moving.
    policy::order(policy::Tag::Queued,{11},12,true,0); // A can still be opaque.
    refused([](){policy::order(policy::Tag::First,{11},12,false,0);});
    refused([](){policy::order(policy::Tag::Queued,{11},12,false,0);});
    refused([](){policy::order(policy::Tag::Queued,{11,12},12,true,0);});
    refused([](){policy::order(policy::Tag::First,{11},88,true,0);});
    refused([](){policy::order(policy::Tag::First,{11},88,false,1);});
    refused([](){policy::order(policy::Tag::Queued,{11},12,true,6);});
    assert(policy::at(policy::Tag::Approach)==180&&policy::at(policy::Tag::First)==300&&policy::at(policy::Tag::Queued)==302);
    assert(std::string(policy::name(policy::Tag::First))=="first"&&std::string(policy::name(policy::Tag::Queued))=="queued");
    const std::vector<uint8_t> body{10,1,9,18,1,7,18,1,8};
    assert((ba_prediction_cohort::policy::action(body,1)==std::vector<uint8_t>{8}));
    refused([&](){ba_prediction_cohort::policy::action(body,2);});
    return 0;
}
