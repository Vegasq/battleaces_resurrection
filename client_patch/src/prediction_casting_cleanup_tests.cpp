// Actual shared Plan header, authored access/lock model only. No native/Unity DLL.
#include "prediction_casting_cleanup.hpp"
#include <iostream>
#include <set>
#include <string>
#include <vector>

namespace {
using ba_prediction_casting_cleanup::Plan;
int checks=0;
void check(bool value,const char* why){++checks;if(!value)throw std::runtime_error(why);}
struct Access {
    bool held=false,active=false,click=false,valid=true,throwClear=false;
    unsigned validations=0,clears=0,locks=0;
    std::vector<int> commands,serialized{8,9},selection{74,90},preview{90};
    std::set<int> casting{74,90};
    std::vector<std::string> events;
    struct Lock {
        Access& a;
        explicit Lock(Access& value):a(value){check(!a.held,"recursive queue lock");a.held=true;++a.locks;a.events.push_back("lock");}
        ~Lock(){a.events.push_back("unlock");a.held=false;}
        Lock(const Lock&)=delete;Lock& operator=(const Lock&)=delete;
    };
    void validate(){check(!held,"validation invoked inside queue lock");++validations;events.push_back("validate");if(!valid)throw std::runtime_error("owner/layout/method mismatch");}
    bool hasActiveCaster(){check(!held,"active callback invoked inside queue lock");return active;}
    bool hasAffectedLiveClick(){check(!held,"click callback invoked inside queue lock");return click;}
    int commandCount(){check(held,"ICommand count outside actual lock");events.push_back("count180");return static_cast<int>(commands.size());}
    void clearCasting(){check(held,"casting Clear outside actual queue lock");events.push_back("clear98");if(throwClear)throw std::runtime_error("original Clear failed");casting.clear();++clears;}
};
template<class F>void refuses(F action){bool failed=false;try{action();}catch(const std::runtime_error&){failed=true;}check(failed,"missing required refusal");}
void testClearAndOrdinals(){
    Access a;const auto serialized=a.serialized,selection=a.selection,preview=a.preview;
    Plan<Access> p(a,true);p.prepare();check(p.willClear(),"affected plan missing");
    check(a.clears==0&&!a.held,"prepare mutated/retained queue lock");check(p.commit(),"clear not committed");
    check(a.casting.empty()&&a.clears==1&&!a.held,"casting clear/lock mismatch");
    check(a.serialized==serialized&&a.selection==selection&&a.preview==preview,"unrelated queue/selection changed");
    check(a.events==std::vector<std::string>{"validate","lock","count180","unlock","validate","lock","count180","clear98","unlock"},"preflight/commit order changed");
    refuses([&]{p.commit();});check(a.clears==1,"duplicate clear");
}
void testPendingAndLateCommands(){
    Access pending;pending.commands={3,4,5};const auto before=pending.commands;
    Plan<Access> blocked(pending,true);refuses([&]{blocked.prepare();});
    check(pending.commands==before&&pending.serialized==std::vector<int>{8,9}&&pending.clears==0&&!pending.held,"pending command lost/reordered");
    Access late;Plan<Access> p(late,true);p.prepare();late.commands={17,17,18};
    refuses([&]{p.commit();});check(late.commands==std::vector<int>{17,17,18}&&late.clears==0&&!late.held,"late producer changed/lost");
    Access capped;capped.commands={257};Plan<Access> remainder(capped,true);refuses([&]{remainder.prepare();});
    check(capped.commands==std::vector<int>{257}&&capped.clears==0,"drain cap remainder discarded");
}
void testOwnerRefusals(){
    for(unsigned mode=0;mode<3;++mode){
        Access a;a.valid=mode!=0;a.active=mode==1;a.click=mode==2;Plan<Access> p(a,true);
        refuses([&]{p.prepare();});check(a.clears==0&&a.locks==0&&!a.held,"owner refusal happened after mutation/lock");
    }
    for(unsigned mode=0;mode<3;++mode){
        Access a;Plan<Access> p(a,true);p.prepare();a.valid=mode!=0;a.active=mode==1;a.click=mode==2;
        refuses([&]{p.commit();});check(a.clears==0&&!a.held,"changed owner accepted at commit");
    }
}
void testUnaffectedAndFaults(){
    Access a;a.active=a.click=true;a.commands={1};Plan<Access> p(a,false);p.prepare();check(!p.willClear()&&!p.commit(),"unaffected set cleared");
    check(a.clears==0&&a.validations==0&&a.locks==0&&a.casting.size()==2,"unaffected owner touched");
    Access b;Plan<Access> unprepared(b,true);refuses([&]{unprepared.commit();});check(!b.clears&&!b.held,"unprepared mutation");
    Access c;Plan<Access> fault(c,true);fault.prepare();c.throwClear=true;refuses([&]{fault.commit();});
    check(!c.held&&c.clears==0&&c.commands.empty()&&c.serialized==std::vector<int>{8,9},"failed Clear leaked lock or altered commands");
}
}
int main(){try{
    testClearAndOrdinals();testPendingAndLateCommands();testOwnerRefusals();testUnaffectedAndFaults();
    std::cout<<checks<<" casting cleanup checks passed; authored access model, no native execution\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
