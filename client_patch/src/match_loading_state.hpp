#pragma once
#include <cstdint>
#include <stdexcept>
#include <string>

namespace ba_match_loading {
using Ticket=uint64_t;
enum class Source {Practice,Dedicated,Custom};
enum class Stage {Preparing,Waiting,Loading,Starting};

// Presentation has no authority to create, cancel or finish a game. Tickets
// prevent a late completion from hiding the next attempt's status.
struct Model {
    Ticket sequence=0,ticket=0;
    Source source=Source::Practice;
    Stage stage=Stage::Preparing;
    std::string identity,message;
    bool pending=false,visible=false,notice=false;
    uint64_t expires=0;

    Ticket begin(Source kind,const std::string& key,Stage value) {
        if(key.empty() || key.size()>160)throw std::invalid_argument("invalid loading identity");
        if(pending && source==kind && identity==key)return ticket;
        if(sequence==UINT64_MAX)throw std::overflow_error("loading ticket exhausted");
        ticket=++sequence;source=kind;identity=key;stage=value;
        pending=visible=true;notice=false;expires=0;message.clear();return ticket;
    }
    bool owns(Ticket value) const {return pending && value && value==ticket;}
    bool advance(Ticket value,Stage next) {
        if(!owns(value) || stage==next)return false;stage=next;return true;
    }
    bool finish(Ticket value) {
        if(!owns(value))return false;pending=visible=notice=false;message.clear();expires=0;return true;
    }
    bool error(Ticket value,const char* text,uint64_t now) {
        if(!owns(value))return false;
        message=text?text:"Unable to start match.";
        if(message.empty() || message.size()>160)message="Unable to start match.";
        pending=false;visible=notice=true;expires=now+10000;return true;
    }
    bool expire(uint64_t now) {
        if(!notice || now<expires)return false;visible=notice=false;expires=0;return true;
    }
};
}
