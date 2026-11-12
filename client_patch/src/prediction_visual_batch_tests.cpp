#include "prediction_visual_batch.hpp"
#include <cstdio>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
struct Write {int id;bool mutate;bool restoration=false;};
void check(bool value,const char* why){if(!value)throw std::runtime_error(why);}
struct Harness {
    std::vector<std::string> events;
    int fail=0;
    size_t synced=0;
    void run(std::vector<Write> writes) {
        ba_prediction_visual_batch::publish(writes,[&] {
            events.push_back("resolve");if(fail==1)throw std::runtime_error("binding refused");
        },[&](Write& write) {
            events.push_back(std::string(write.restoration?"restore":"write")+std::to_string(write.id));
            if(fail==2&&write.id==2)throw std::runtime_error("setter refused");
        },[&](size_t count) {
            events.push_back("sync");synced=count;if(fail==3)throw std::runtime_error("sync refused");
        },[&](Write& write) {
            events.push_back("observe"+std::to_string(write.id));
        });
    }
};
void ordered() {
    Harness h;h.run({{1,true},{2,false},{3,true}});
    check(h.events==std::vector<std::string>{"resolve","write1","write3","sync","observe1","observe2","observe3"},
        "all changes must finish before one sync and every observation");
    check(h.synced==2,"batch count must count actual helper writes");
}
void noWrites() {
    Harness h;h.fail=1;h.run({{1,false},{2,false}});
    check(h.events==std::vector<std::string>{"observe1","observe2"}&&!h.synced,
        "ordinary observation must not resolve or invoke physics");
}
void empty() {Harness h;h.run({});check(h.events.empty(),"empty owner batch must not call anything");}
void restoration() {
    Harness h;h.run({{1,true,true}});
    check(h.events==std::vector<std::string>{"resolve","restore1","sync","observe1"}&&h.synced==1,
        "zero-offset restoration must synchronize before it is observable");
}
void failure(int stage,const std::vector<std::string>& expected) {
    Harness h;h.fail=stage;bool threw=false;
    try{h.run({{1,true},{2,true},{3,false}});}catch(const std::runtime_error&){threw=true;}
    check(threw&&h.events==expected,"failed publication must stop without retry or observation");
}
}
int main() {
    try {
        ordered();noWrites();empty();restoration();
        failure(1,{"resolve"});
        failure(2,{"resolve","write1","write2"});
        failure(3,{"resolve","write1","write2","sync"});
        std::puts("visual correction batch tests: 7 groups PASS");return 0;
    }catch(const std::exception& error){std::fprintf(stderr,"visual correction batch test failed: %s\n",error.what());return 1;}
}
