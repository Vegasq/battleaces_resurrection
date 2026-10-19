#pragma once
#include "public_wire.hpp"

// Pure client arbitration. Transport and native objects are owned by the adapter.
namespace ba_public_attempt {
namespace wire=ba_public_wire;
using wire::require;
struct Attempt {
    uint64_t ticket,started,connection=0;
    unsigned mode;wire::Deck deck;
    bool full=false;ba_community_wire::Selection cosmetics;
    int phase=-1;
    bool entered=false,readySent=false,committed=false,assigned=false,cancelled=false,retired=false;
    std::string match,reason;
    wire::Assignment seat{};
    Attempt(uint64_t generation,unsigned gameMode,const wire::Deck& selected,uint64_t now):
        ticket(generation),started(now),mode(gameMode),deck(selected) {
        require(ticket!=0,"public attempt ticket missing");wire::participants(mode);
    }
    Attempt(uint64_t generation,unsigned gameMode,const ba_community_wire::Loadout& selected,uint64_t now):
        Attempt(generation,gameMode,selected.deck,now) {full=selected.full;cosmetics=selected.cosmetics;if(full)cosmetics.validate();}
    uint32_t remaining(uint64_t now) const {
        require(now>=started,"public monotonic clock regressed");
        return now-started>=wire::maxWaitMs?0:wire::maxWaitMs-static_cast<uint32_t>(now-started);
    }
    void enter(uint64_t epoch) {
        require(epoch && !entered && !cancelled && !retired,"public ENTER ownership");connection=epoch;entered=true;
    }
    bool owns(uint64_t epoch,uint64_t incoming) const {
        if(epoch!=connection || incoming<ticket)return false;
        require(entered && incoming==ticket,"future/unowned public ticket");return true;
    }
    bool state(uint64_t epoch,const wire::State& value) {
        if(!owns(epoch,value.ticket))return false;
        if(retired)return false;
        require(value.mode==mode,"public mode changed within ticket");
        if(value.phase==wire::Waiting) {
            require(!committed && !assigned && value.match.empty(),"public committed match requeued");
            match.clear();readySent=false;
        } else if(value.phase==wire::Offered) {
            require(!committed && !assigned && !value.match.empty() && (!readySent || value.match==match),
                "public offer replaced without retirement");match=value.match;
        } else if(value.phase>=wire::Preparing && value.phase<=wire::Results) {
            require(readySent && !match.empty() && value.match==match,"public commit/result differs from READY proposal");
            require(phase<wire::Preparing || value.phase>=phase,"public committed phase regressed");
            if(value.phase==wire::Running)require(assigned,"public start before assignment");
            committed=true;
        } else {
            require(value.phase==wire::Retired && (!assigned || phase==wire::Results),"active public assignment retired");
            require(value.match.empty() || value.match==match,"public retirement proposal mismatch");retired=true;
        }
        phase=value.phase;reason=value.reason;return true;
    }
    void ready() {
        require(phase==wire::Offered && !readySent && !cancelled && !retired,"public READY ownership");readySent=true;
    }
    bool assignment(uint64_t epoch,const wire::Assignment& value) {
        if(!owns(epoch,value.ticket) || retired)return false;
        require(committed && phase>=wire::Preparing && phase<=wire::Loading && !assigned &&
            value.mode==mode && value.match==match && value.deck==deck && value.full==full &&
            (!full || value.cosmetics==cosmetics),"public assignment ownership/full loadout");
        seat=value;assigned=true;return !cancelled;
    }
    bool mayFallback() const {
        // After READY a lost reply is ambiguous. Only explicit pre-assignment
        // retirement makes fallback safe for that same intent again.
        return !cancelled && !assigned && ((!readySent && !committed) || retired);
    }
};
}
