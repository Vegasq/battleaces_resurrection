#pragma once
#include <cstdint>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

// Explicit local experiment. These are command sequence numbers, never
// speculative simulation frames. The authoritative input/presentation path
// stays separate. Ordinary launchers do not request this protocol.
namespace ba_original_commands {
using Bytes=std::vector<unsigned char>;
constexpr unsigned char negotiate=70,ack=71,batch=72,heartbeat=73,firstOutputReady=74,version=1;
constexpr uint64_t heartbeatInterval=1000;
inline void require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
inline bool validateContext(bool requested,bool unified,bool tlsV2,bool community) {
    if(!requested)return false;
    require(unified && tlsV2 && community,"original command experiment requires unified TLSV2 community");
    return true;
}
inline bool canStart(bool experimental,size_t queued){return queued>=(experimental?1u:2u);}
inline void matchKey(const std::string& match) {
    require(match.size()==32,"original command match key length");
    for(unsigned char c:match)require((c>='0'&&c<='9') || (c>='a'&&c<='f'),"original command match key invalid");
}
inline void append(Bytes& out,uint64_t value,unsigned count) {
    for(unsigned i=0;i<count;++i)out.push_back(static_cast<unsigned char>(value>>(8*i)));
}
inline Bytes negotiation(){return Bytes{version};}
inline Bytes encodeBatch(const std::string& match,uint64_t sequence,const Bytes& body) {
    matchKey(match);require(sequence>0,"original command sequence must start at1");
    require(!body.empty() && body.size()<=65536,"original command body size limit");
    Bytes out{version};out.insert(out.end(),match.begin(),match.end());append(out,sequence,8);
    out.insert(out.end(),body.begin(),body.end());return out;
}
inline Bytes encodeHeartbeat(const std::string& match,int32_t applied) {
    matchKey(match);require(applied>=-1,"original command heartbeat frame invalid");
    Bytes out{version};out.insert(out.end(),match.begin(),match.end());append(out,static_cast<uint32_t>(applied),4);return out;
}
inline Bytes encodeOutputReady(const std::string& match) {
    matchKey(match);Bytes out{version};out.insert(out.end(),match.begin(),match.end());return out;
}
struct Batch {uint64_t sequence;Bytes payload;};
class State {
    bool pending_=false,ready_=false,running_=false,firstOutputSent_=false;
    std::string match_;
    uint64_t sequence_=1,nextHeartbeat_=0;
    int32_t applied_=-1,smokeFrame_=-1;
public:
    bool pending() const{return pending_;}
    bool ready() const{return ready_;}
    const std::string& match() const{return match_;}
    uint64_t sequence() const{return sequence_;}
    int32_t lastApplied() const{return applied_;}
    void request(){require(!pending_ && !ready_,"duplicate original command negotiation");pending_=true;}
    void acknowledge(const Bytes& payload) {
        require(pending_ && !ready_ && payload==Bytes{version},"unexpected original command negotiation ACK");
        pending_=false;ready_=true;
    }
    void clearMatch(){match_.clear();running_=false;firstOutputSent_=false;sequence_=1;nextHeartbeat_=0;applied_=-1;smokeFrame_=-1;}
    void disconnect(){clearMatch();pending_=ready_=false;}
    void assign(const std::string& match,uint64_t now) {
        require(ready_ && match_.empty(),"original command assignment before negotiation or duplicate match");
        matchKey(match);match_=match;nextHeartbeat_=now;
    }
    void start(uint64_t now) {
        require(ready_ && !match_.empty() && !running_,"original command START before assignment or repeated");
        running_=true;firstOutputSent_=false;sequence_=1;applied_=-1;smokeFrame_=-1;nextHeartbeat_=now;
    }
    std::optional<Batch> batch(const Bytes& body,unsigned actions) {
        require(ready_ && running_,"original command batch before negotiated START");
        if(!actions)return std::nullopt;
        require(actions<=256 && sequence_<(std::numeric_limits<uint64_t>::max)(),"original command action/sequence limit");
        Batch result{sequence_,encodeBatch(match_,sequence_,body)};++sequence_;return result;
    }
    std::optional<Bytes> heartbeat(uint64_t now) {
        if(!ready_ || match_.empty() || now<nextHeartbeat_)return std::nullopt;
        const auto maximum=(std::numeric_limits<uint64_t>::max)();
        nextHeartbeat_=now>maximum-heartbeatInterval?maximum:now+heartbeatInterval;
        return encodeHeartbeat(match_,applied_);
    }
    std::optional<Bytes> firstOutputReady(int32_t presented) {
        require(ready_ && running_ && !match_.empty(),"first output readiness outside active command match");
        require(presented>=-1,"first output presented frame invalid");
        if(presented<0 || applied_<0 || firstOutputSent_)return std::nullopt;
        firstOutputSent_=true;return encodeOutputReady(match_);
    }
    void applied(int32_t frame) {
        require(running_ && frame>=0 && static_cast<int64_t>(frame)==static_cast<int64_t>(applied_)+1,
                "original command applied frame is not contiguous");applied_=frame;
    }
    bool smoke(int32_t frame) {
        require(running_ && frame>=0 && frame>=smokeFrame_,"original command smoke frame invalid");
        if(frame==smokeFrame_)return false;smokeFrame_=frame;return true;
    }
};
}
