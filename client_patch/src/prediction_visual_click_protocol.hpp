#pragma once
#include <cstdint>
#include <cmath>
#include <cstring>
#include <stdexcept>

// Pure ordering for one borrowed-Mouse click. Queue return never proves delivery.
namespace ba_prediction_visual_click_protocol {
class Point {
    uint32_t x_=0,y_=0;
    bool bound_=false;
    static float value(uint32_t bits){float result;std::memcpy(&result,&bits,sizeof(result));return result;}
public:
    static uint32_t bits(float value){uint32_t result;std::memcpy(&result,&value,sizeof(result));return result;}
    void bind(float x,float y) {
        if(bound_||!std::isfinite(x)||!std::isfinite(y))throw std::invalid_argument("visual click point is already bound or nonfinite");
        x_=bits(x);y_=bits(y);bound_=true;
    }
    float x()const {if(!bound_)throw std::invalid_argument("visual click point is unbound");return value(x_);}
    float y()const {if(!bound_)throw std::invalid_argument("visual click point is unbound");return value(y_);}
    bool matches(float x,float y)const {return bound_&&bits(x)==x_&&bits(y)==y_;}
};
struct ScreenPoint {float x=0,y=0;};
struct MatchedAnchor {ScreenPoint offset,raw;};
inline MatchedAnchor matchedAnchor(ScreenPoint consumed,ScreenPoint displayed,ScreenPoint raw) {
    // Keep the two Single operations separately rounded even under optimization.
    volatile float dx=consumed.x-displayed.x,dy=consumed.y-displayed.y;
    volatile float x=raw.x+dx,y=raw.y+dy;
    if(!std::isfinite(dx)||!std::isfinite(dy)||!std::isfinite(x)||!std::isfinite(y))
        throw std::invalid_argument("visual aim Single arithmetic is nonfinite");
    return {{dx,dy},{x,y}};
}
enum class Stage {Ready,PositionQueued,DownQueued,DownEntered,DownReturned,UpQueued,UpEntered,UpReturned,Closed};
struct Progress {
    Stage stage=Stage::Ready;
    uint64_t queuedOrdinal=0,queuedUs=0,enteredUs=0,ticket=0,downTicket=0,returnedUs=0;
    static void require(bool value,const char* why){if(!value)throw std::invalid_argument(why);}
    void queue(unsigned sequence,uint64_t ordinal,uint64_t stamp) {
        require(ordinal&&stamp,"visual click queue has no clock/ordinal");
        const Stage expected=sequence==1?Stage::Ready:sequence==2?Stage::PositionQueued:Stage::DownReturned;
        require(sequence>=1&&sequence<=3&&stage==expected,"visual click queue order differs");
        require(!queuedOrdinal||(ordinal>queuedOrdinal&&stamp>queuedUs),"visual click queue lacks later frontend delivery observation");
        require(sequence!=3||stamp>returnedUs,"visual click Up was queued before Down returned");
        queuedOrdinal=ordinal;queuedUs=stamp;
        stage=sequence==1?Stage::PositionQueued:sequence==2?Stage::DownQueued:Stage::UpQueued;
    }
    void before(bool down,uint64_t serial,uint64_t ordinal,uint64_t stamp) {
        require(stage==(down?Stage::DownQueued:Stage::UpQueued),"visual click callback was not requested");
        require(serial&&ordinal>=queuedOrdinal&&stamp>queuedUs,"visual click callback preceded its queue receipt");
        require(down||serial>downTicket,"visual click Up does not follow its Down ticket");
        enteredUs=stamp;ticket=serial;if(down)downTicket=serial;
        stage=down?Stage::DownEntered:Stage::UpEntered;
    }
    void returned(bool down,uint64_t serial,uint64_t stamp,bool singleAccepted) {
        require(stage==(down?Stage::DownEntered:Stage::UpEntered)&&serial==ticket&&stamp>=enteredUs,
            "visual click callback return has another entry");
        require(!down||singleAccepted,"visual click original Down did not produce Single authorization");
        returnedUs=stamp;stage=down?Stage::DownReturned:Stage::UpReturned;
    }
    void close(uint64_t ordinal,uint64_t stamp,bool released) {
        require(stage==Stage::UpReturned&&ordinal>queuedOrdinal&&stamp>=returnedUs&&released,
            "visual click close lacks a later balanced original release");
        stage=Stage::Closed;
    }
};
}
