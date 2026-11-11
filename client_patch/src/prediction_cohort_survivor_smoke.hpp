#pragma once
#include "prediction_cohort_smoke.hpp"

namespace ba_prediction_survivor {
bool enabled();
bool canonicalDeath();
void requireFlags();
void tick();
void serialized(void*,void*,uint64_t,int,unsigned);
void registered(uint64_t,int,const std::vector<uint8_t>&);
void authoritative(const std::vector<uint8_t>&,const std::string&);
namespace policy {
inline void require(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
struct Member {
    uint32_t id,type,army;uint64_t token,canonical;
    bool nativePresent;uint32_t state;bool initialized,admitted;
};
inline void selection(const std::vector<Member>& members) {
    require(members.size()==2,"survivor selection needs exactly two actual members");
    std::set<uint32_t> ids;
    for(const auto& m:members) {
        require(m.type==1&&m.army==1&&m.token&&m.token==m.canonical&&m.nativePresent&&m.state!=6&&m.initialized&&m.admitted,
            "survivor selection needs current confirmed initialized own Gunbots");
        require(ids.insert(m.id).second,"survivor duplicate member");
    }
    require(ids==std::set<uint32_t>{11,12},"survivor initial identities differ");
}
inline void move(const std::vector<Member>& members,const std::vector<uint32_t>& current,int count) {
    selection(members);
    require(count==2&&current.size()==2&&std::set<uint32_t>(current.begin(),current.end())==std::set<uint32_t>{11,12},
        "survivor original Move requires the retained pair selection");
    for(const auto& m:members)require(m.state==0,"survivor original Move requires actual ready members");
}
inline void continuous(uintptr_t original,uintptr_t current,uint64_t token,uint64_t canonical,
                       uint64_t originalToken,bool present,bool initialized,bool admitted) {
    require(original&&current==original&&originalToken&&token==originalToken&&canonical==originalToken&&
        present&&initialized&&admitted,"surviving member lost its original continuous admitted lease");
}
inline void survivorMove(const std::vector<Member>& members,const std::vector<uint32_t>& resolved,int count) {
    require(members.size()==1&&resolved==std::vector<uint32_t>{12}&&count==1,
        "canonical loss Move requires exactly the original resolvable survivor");
    const auto& m=members.front();
    require(m.id==12&&m.type==1&&m.army==1&&m.token&&m.token==m.canonical&&m.nativePresent&&
        m.state==0&&m.initialized&&m.admitted,"canonical loss Move survivor is not ready/admitted");
}
}
}
