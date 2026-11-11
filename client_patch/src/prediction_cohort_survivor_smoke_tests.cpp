#include "prediction_cohort_survivor_smoke.hpp"
#include <cassert>
#include <functional>
using namespace ba_prediction_survivor;
static void refused(const std::function<void()>& operation) {
    bool failed=false;try{operation();}catch(const std::runtime_error&){failed=true;}assert(failed);
}
int main() {
    const policy::Member victim{11,1,1,31,31,true,9,true,true},survivor{12,1,1,40,40,true,9,true,true};
    policy::selection({victim,survivor}); // Real initial selection can precede activation readiness.
    refused([&](){policy::selection({victim,victim});});
    refused([&](){policy::selection({victim});});
    for(unsigned mode=0;mode<7;++mode) {
        auto changed=survivor;
        if(mode==0)changed.canonical=0;if(mode==1)changed.nativePresent=false;if(mode==2)changed.initialized=false;
        if(mode==3)changed.admitted=false;if(mode==4)changed.army=0;if(mode==5)changed.id=13;if(mode==6)changed.state=6;
        refused([&](){policy::selection({victim,changed});});
    }
    auto readyVictim=victim,readySurvivor=survivor;readyVictim.state=0;readySurvivor.state=0;
    policy::move({readyVictim,readySurvivor},{12,11},2);
    refused([&](){policy::move({victim,survivor},{11,12},2);});
    refused([&](){policy::move({readyVictim,readySurvivor},{12},1);});
    refused([&](){policy::move({readyVictim,readySurvivor},{11,12},1);});
    // Member11 may disappear/recreate. Member12 must never borrow a new lease or actor.
    policy::continuous(100,100,40,40,40,true,true,true);
    refused([](){policy::continuous(100,101,40,40,40,true,true,true);});
    refused([](){policy::continuous(100,100,41,41,40,true,true,true);});
    refused([](){policy::continuous(100,100,40,40,40,false,true,true);});
    refused([](){policy::continuous(100,100,40,40,40,true,false,true);});
    refused([](){policy::continuous(100,100,40,0,40,true,true,true);});
    // The passive normal serialization binding must use the actual raw67 ordinal.
    assert((ba_prediction_cohort::policy::action({10,1,9,18,1,7},0)==std::vector<uint8_t>{7}));
    refused([](){ba_prediction_cohort::policy::action({10,1,9,18,2,7},0);});
    return 0;
}
