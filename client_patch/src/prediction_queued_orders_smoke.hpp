#pragma once
#include "prediction_close_formation_smoke.hpp"

namespace ba_prediction_queued_orders {
bool enabled();
void requireFlags();
void tick();
void serialized(void*,void*,uint64_t,int,unsigned);
void registered(uint64_t,int,const std::vector<uint8_t>&);
void authoritative(const std::vector<uint8_t>&,const std::string&);
namespace policy {
namespace close=ba_prediction_close_formation::policy;
using Member=close::Member;
using close::validate;
inline void require(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
enum class Tag:unsigned {Approach,First,Queued};
inline const char* name(Tag tag) {
    switch(tag){case Tag::Approach:return "approach";case Tag::First:return "first";case Tag::Queued:return "queued";}
    throw std::runtime_error("queued orders tag differs");
}
inline int at(Tag tag) {
    switch(tag){case Tag::Approach:return 180;case Tag::First:return 300;case Tag::Queued:return 302;}
    throw std::runtime_error("queued orders frame differs");
}
inline unsigned slot(Tag){return 1u;}
inline uint32_t ability(Tag tag){return tag==Tag::First?88u:12u;}
inline bool queued(Tag tag){return tag==Tag::Queued;}
inline void cache(const std::vector<uint32_t>& ids,const std::vector<uint32_t>& typed,int count,bool single=false) {
    if(!single){close::cache(ids,typed,count);return;}
    require(ids==std::vector<uint32_t>{11}&&typed==std::vector<uint32_t>{11}&&count==1,
        "queued orders current selection is not exactly the original subject11");
}
struct Targets {close::Point first,queued;};
inline Targets targets(const std::vector<close::Point>& points) {
    const auto first=close::freshTarget(points);
    const close::Point second{points.front().x,points.front().y,close::add(points.front().z,-16.f)};
    require(std::isfinite(second.x)&&std::isfinite(second.y)&&std::isfinite(second.z),"queued orders frozen target is nonfinite");
    return {first,second};
}
inline void order(Tag tag,const std::vector<uint32_t>& ids,uint32_t abilityId,bool queuedValue,uint32_t state) {
    require(ids==(tag==Tag::Approach?std::vector<uint32_t>{11,12,13,14}:std::vector<uint32_t>{11})&&
        abilityId==ability(tag)&&queuedValue==queued(tag)&&state!=6&&(tag==Tag::Queued||state==0),
        "queued orders original source/ability/queued/readiness differs");
}
}
}
