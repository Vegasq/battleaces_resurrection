#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace ba_prediction_cohort {
bool enabled();
void requireFlags();
void tick();
void serialized(void*,void*,uint64_t,int,unsigned);
void registered(uint64_t,int,const std::vector<uint8_t>&);
void authoritative(const std::vector<uint8_t>&,const std::string&);
namespace policy {
inline void require(bool ok,const char* reason){if(!ok)throw std::runtime_error(reason);}
struct Member {uint32_t id,type,army;uint64_t token,canonical;bool ready,initialized,admitted;};
inline std::vector<uint32_t> choose(const std::set<uint32_t>& before,const std::vector<Member>& members,unsigned slot) {
    require(slot<=1&&!members.empty()&&members.size()<=8,"cohort census/seat bound");
    std::vector<uint32_t> ids,born;
    for(const auto& m:members) {
        require(m.type==1&&m.army==slot&&m.token&&m.token==m.canonical&&m.ready&&m.initialized&&m.admitted,
                "cohort source is not ready/confirmed/initialized own Gunbot");
        ids.push_back(m.id);if(!before.count(m.id))born.push_back(m.id);
    }
    std::sort(ids.begin(),ids.end());
    require(std::adjacent_find(ids.begin(),ids.end())==ids.end()&&born.size()==1,"cohort birth is duplicate/ambiguous/missing");
    require(slot==1?(before.count(11)&&ids.size()==2&&std::binary_search(ids.begin(),ids.end(),uint32_t{11})):
                    (ids.size()==1&&!before.count(ids[0])),"cohort initial/born roster differs");
    return ids;
}
inline uint64_t varint(const std::vector<uint8_t>& bytes,size_t& at) {
    uint64_t result=0;
    for(unsigned shift=0;shift<70;shift+=7) {
        require(at<bytes.size(),"cohort raw protobuf varint truncated");const auto byte=bytes[at++];
        require(shift<63||(byte&0xfeu)==0,"cohort raw protobuf varint overflow");
        result|=uint64_t(byte&0x7fu)<<shift;if(!(byte&0x80u))return result;
    }
    throw std::runtime_error("cohort raw protobuf varint overlong");
}
inline std::vector<uint8_t> action(const std::vector<uint8_t>& body,unsigned index) {
    require(!body.empty()&&body.size()<=65536&&index<256,"cohort raw67 body/index bound");
    size_t at=0;unsigned count=0,identities=0;std::vector<uint8_t> result;
    while(at<body.size()) {
        const auto tag=varint(body,at);const auto field=tag>>3,wire=tag&7u;
        require((field==1||field==2)&&wire==2,"cohort raw67 player field differs");
        const auto length=varint(body,at);require(length>0&&length<=body.size()-at,"cohort raw67 child bound");
        const auto end=at+static_cast<size_t>(length);
        if(field==1)require(++identities==1,"cohort raw67 identity repeated");
        else {require(count<256,"cohort raw67 action count bound");if(count++==index)result.assign(body.begin()+at,body.begin()+end);}
        at=end;
    }
    require(identities==1&&!result.empty(),"cohort raw67 passive action ordinal missing");return result;
}
}
}
