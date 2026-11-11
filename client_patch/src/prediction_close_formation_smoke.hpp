#pragma once
#include "prediction_cohort_smoke.hpp"
#include <cmath>

namespace ba_prediction_close_formation {
bool enabled();
void requireFlags();
void tick();
void serialized(void*,void*,uint64_t,int,unsigned);
void registered(uint64_t,int,const std::vector<uint8_t>&);
void authoritative(const std::vector<uint8_t>&,const std::string&);
namespace policy {
inline void require(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
enum class Tag:unsigned {Approach,Fresh,Remote};
inline const char* name(Tag tag) {
    switch(tag){case Tag::Approach:return "approach";case Tag::Fresh:return "fresh";case Tag::Remote:return "remote";}
    throw std::runtime_error("close formation order tag differs");
}
inline int at(Tag tag) {
    switch(tag){case Tag::Approach:return 180;case Tag::Fresh:return 300;case Tag::Remote:return 320;}
    throw std::runtime_error("close formation order frame differs");
}
inline unsigned slot(Tag tag){return tag==Tag::Remote?0u:1u;}
struct Member {
    uint32_t id,type,army,state;uint64_t token,canonical,originalToken;
    uintptr_t actor,originalActor;bool present,initialized,admitted;
};
inline std::vector<uint32_t> validate(const std::vector<Member>& members,unsigned seat,bool ready) {
    require(seat<=1&&members.size()==(seat==1?4u:1u),"close formation member/seat bound differs");
    std::vector<uint32_t> ids;
    for(const auto& m:members) {
        require(m.type==1&&m.army==seat&&m.originalToken&&m.token==m.originalToken&&m.canonical==m.originalToken&&
            m.actor&&m.actor==m.originalActor&&m.present&&m.initialized&&m.admitted&&m.state!=6&&(!ready||m.state==0),
            "close formation member lost its ready/continuous confirmed original lease");
        ids.push_back(m.id);
    }
    require(ids==(seat==1?std::vector<uint32_t>{11,12,13,14}:std::vector<uint32_t>{10}),
        "close formation actual initial roster/order differs");
    return ids;
}
inline void cache(const std::vector<uint32_t>& ids,const std::vector<uint32_t>& typed,int count) {
    const std::set<uint32_t> expected{11,12,13,14};
    require(count==4&&ids.size()==4&&typed.size()==4&&std::set<uint32_t>(ids.begin(),ids.end())==expected&&
        std::set<uint32_t>(typed.begin(),typed.end())==expected,"close formation current/group type1 cache differs");
}
struct Point {float x,y,z;};
inline float add(float left,float right){volatile float result=left+right;return result;}
inline float quarter(float value){volatile float result=value*.25f;return result;}
inline Point freshTarget(const std::vector<Point>& points) {
    require(points.size()==4,"close formation centroid requires four ordered actual poses");
    Point center{0.f,0.f,0.f};
    for(const auto& point:points) {
        require(std::isfinite(point.x)&&std::isfinite(point.y)&&std::isfinite(point.z),"close formation centroid pose is nonfinite");
        center={add(center.x,point.x),add(center.y,point.y),add(center.z,point.z)};
    }
    center={quarter(center.x),quarter(center.y),add(quarter(center.z),16.f)};
    require(std::isfinite(center.x)&&std::isfinite(center.y)&&std::isfinite(center.z),"close formation centroid overflow");return center;
}
}
}
