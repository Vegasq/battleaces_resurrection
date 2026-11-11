#include "prediction_close_formation_smoke.hpp"
#include <cassert>
#include <functional>
#include <limits>
using namespace ba_prediction_close_formation;
static void refused(const std::function<void()>& operation) {
    bool failed=false;try{operation();}catch(const std::runtime_error&){failed=true;}assert(failed);
}
int main() {
    std::vector<policy::Member> members;
    for(uint32_t id=11;id<=14;++id)members.push_back({id,1,1,0,id+100,id+100,id+100,id+1000,id+1000,true,true,true});
    assert((policy::validate(members,1,true)==std::vector<uint32_t>{11,12,13,14}));
    const policy::Member host{10,1,0,0,40,40,40,1000,1000,true,true,true};
    assert((policy::validate({host},0,true)==std::vector<uint32_t>{10}));
    refused([&](){policy::validate({members[0]},0,true);});
    auto moving=members;for(auto& member:moving)member.state=1;
    policy::validate(moving,1,false);refused([&](){policy::validate(moving,1,true);});
    for(unsigned mode=0;mode<9;++mode) {
        auto changed=members;auto& m=changed[2];
        if(mode==0)m.actor++;if(mode==1)m.token++;if(mode==2)m.canonical=0;if(mode==3)m.present=false;
        if(mode==4)m.initialized=false;if(mode==5)m.admitted=false;if(mode==6)m.army=0;
        if(mode==7)m.id=12;if(mode==8)m.state=6;
        refused([&](){policy::validate(changed,1,false);});
    }
    refused([&](){policy::validate({members[0],members[1]},1,true);});
    policy::cache({14,11,13,12},{11,12,13,14},4);
    refused([](){policy::cache({11,12,13,14},{11,12,13},4);});
    refused([](){policy::cache({11,12,13,14},{11,12,13,14},3);});
    refused([](){policy::cache({11,12,13,13},{11,12,13,14},4);});
    const auto center=policy::freshTarget({{81,0,61},{81,0,59},{79,0,61},{79,0,59}});
    assert(center.x==80.f&&center.y==0.f&&center.z==76.f);
    const auto ordered=policy::freshTarget({{100000000.f,0,0},{1,0,0},{-100000000.f,0,0},{1,0,0}});
    assert(ordered.x==.25f); // Ordered Single rounding, not a double/reassociated sum.
    refused([](){policy::freshTarget({{0,0,0}});});
    refused([](){policy::freshTarget({{0,0,0},{0,0,0},{0,0,0},{std::numeric_limits<float>::infinity(),0,0}});});
    assert(policy::at(policy::Tag::Approach)==180&&policy::at(policy::Tag::Fresh)==300&&policy::at(policy::Tag::Remote)==320);
    assert(policy::slot(policy::Tag::Remote)==0&&policy::slot(policy::Tag::Fresh)==1);
    assert(std::string(policy::name(policy::Tag::Fresh))=="fresh");
    const std::vector<uint8_t> body{10,1,9,18,1,7,18,1,8};
    assert((ba_prediction_cohort::policy::action(body,1)==std::vector<uint8_t>{8}));
    refused([&](){ba_prediction_cohort::policy::action(body,2);});
    return 0;
}
