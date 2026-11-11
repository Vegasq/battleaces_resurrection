#include "prediction_cohort_smoke.hpp"
#include <cassert>
#include <functional>
using namespace ba_prediction_cohort;
static void refused(const std::function<void()>& operation) {
    bool failed=false;try{operation();}catch(const std::runtime_error&){failed=true;}assert(failed);
}
int main() {
    const policy::Member initial{11,1,1,31,31,true,true,true},born{87,1,1,40,40,true,true,true};
    assert((policy::choose({11},{born,initial},1)==std::vector<uint32_t>{11,87}));
    const policy::Member remote{91,1,0,50,50,true,true,true};
    assert((policy::choose({},{remote},0)==std::vector<uint32_t>{91}));
    refused([&](){policy::choose({11},{initial},1);});
    refused([&](){policy::choose({11},{initial,born,born},1);});
    refused([&](){policy::choose({11,87},{initial,born},1);});
    for(unsigned mode=0;mode<5;++mode) {
        auto changed=born;if(mode==0)changed.canonical=0;if(mode==1)changed.ready=false;
        if(mode==2)changed.initialized=false;if(mode==3)changed.admitted=false;if(mode==4)changed.army=0;
        refused([&](){policy::choose({11},{initial,changed},1);});
    }
    const std::vector<uint8_t> body{10,1,9,18,2,8,7,18,1,6};
    assert((policy::action(body,0)==std::vector<uint8_t>{8,7}));
    assert((policy::action(body,1)==std::vector<uint8_t>{6}));
    refused([&](){policy::action(body,2);});
    for(const auto& malformed:std::vector<std::vector<uint8_t>>{{10,1},{10,1,9,18,3,1},{10,1,9,10,1,9,18,1,1},
        {10,1,9,24,1},{10,1,9,18,128},{255,255,255,255,255,255,255,255,255,255,1}})
        refused([&](){policy::action(malformed,0);});
    return 0;
}
