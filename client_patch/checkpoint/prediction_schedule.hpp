#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <map>
#include <memory>
#include <optional>
#include <stdexcept>
#include <utility>
#include <vector>

// Isolated numbered-input bookkeeping, not a transport or simulation hook.
// One owner thread/instance per match. The caller MUST validate/route the current
// match's authority, canonical own-slot identity and protobuf/action counts
// before observe_authority. No protobuf is parsed and no idle/Join is invented.
// Receiving F alone permits F+W; confirmation/prediction never grant credits.
// Credit does NOT admit an action: the server checks entity identity/ownership
// immediately on future INPUT as well as at commit. Predicted new-spawn IDs may
// be absent/different there. Before submit, integration must retain and defer or
// rebind such orders using confirmed-entity admission; never silently drop them
// or weaken server validation. This planner neither resolves nor submits IDs.
namespace ba_prediction_schedule {
using Frame=std::int64_t; // -1 cursors and MAX_FRAME+1 exhausted-input sentinel.
using Bytes=std::vector<std::uint8_t>;
inline constexpr Frame MAX_FRAME=0x7fffffff;
inline constexpr std::size_t MAX_BODY_BYTES=64U*1024U;

class InputCreditError:public std::invalid_argument {
public:using std::invalid_argument::invalid_argument;
};
inline void require(bool condition,const char* message) {
    if(!condition)throw InputCreditError(message);
}
struct InputBody {Bytes body;std::uint32_t action_count=0;};
struct Limits {
    std::uint32_t max_prediction_ahead=12,max_authority_backlog=64;
    std::size_t max_buffered_bytes=16U*1024U*1024U;
};
struct Metrics {
    std::uint64_t submissions=0,receipts=0,confirmations=0,matched=0,normalized=0;
    std::size_t peak_pending_inputs=0,peak_authority_backlog=0,peak_buffered_bytes=0;
};
class InputCreditPlanner;

// Own immutable bytes, copied once from caller storage. Returning snapshots or
// keeping receipts cannot mutate a pending submission or depend on its lifetime.
class ScheduledInput {
public:
    Frame frame()const{return frame_;}
    const Bytes& body()const{return *body_;}
    std::uint32_t action_count()const{return action_count_;}
    Bytes payload()const {
        const auto frame=static_cast<std::uint32_t>(frame_);
        Bytes result;result.reserve(4+body_->size());
        for(unsigned shift=0;shift<32;shift+=8)result.push_back(static_cast<std::uint8_t>(frame>>shift));
        result.insert(result.end(),body_->begin(),body_->end());return result;
    }
private:
    friend class InputCreditPlanner;
    ScheduledInput(Frame frame,const Bytes& body,std::uint32_t count):
        frame_(frame),body_(std::make_shared<const Bytes>(body)),action_count_(count){}
    Frame frame_;
    std::shared_ptr<const Bytes> body_;
    std::uint32_t action_count_;
};
class AuthorityReceipt {
public:
    Frame frame()const{return submitted_.frame();}
    const Bytes& submitted_body()const{return submitted_.body();}
    const Bytes& canonical_body()const{return *canonical_;}
    std::uint32_t submitted_action_count()const{return submitted_.action_count();}
    std::uint32_t canonical_action_count()const{return canonical_count_;}
    bool matched()const{return submitted_body()==canonical_body();}
    bool normalized()const{return !matched();}
    bool noop()const{return canonical_count_==0;}
private:
    friend class InputCreditPlanner;
    AuthorityReceipt(const ScheduledInput& submitted,const Bytes& canonical,std::uint32_t count):
        submitted_(submitted),canonical_(std::make_shared<const Bytes>(canonical)),canonical_count_(count){}
    ScheduledInput submitted_;
    std::shared_ptr<const Bytes> canonical_;
    std::uint32_t canonical_count_;
};

class InputCreditPlanner {
public:
    explicit InputCreditPlanner(std::uint32_t window,Limits limits={}):window_(window),limits_(limits) {
        require(window>=2 && window<=12,"input window must be2..12");
        require(limits.max_prediction_ahead>=1 && limits.max_prediction_ahead<=120,"invalid prediction lead limit");
        require(limits.max_authority_backlog>=1 && limits.max_authority_backlog<=64,"invalid authority backlog limit");
        require(limits.max_buffered_bytes>=1 && limits.max_buffered_bytes<=32U*1024U*1024U,"invalid planner byte limit");
    }
    InputCreditPlanner(const InputCreditPlanner&)=delete;
    InputCreditPlanner& operator=(const InputCreditPlanner&)=delete;

    std::uint32_t input_window()const{return window_;}
    Frame next_input_frame()const{return next_input_;}
    Frame received_frame()const{return received_;}
    Frame confirmed_frame()const{return confirmed_;}
    Frame predicted_frame()const{return predicted_;}
    std::size_t buffered_bytes()const{return buffered_bytes_;}
    bool retired()const{return retired_;}
    Metrics metrics()const{return metrics_;}
    Frame available_credits()const {
        if(retired_)return 0;
        return (std::max)(Frame(0),(std::min)(static_cast<Frame>(window_)+received_+1-next_input_,
                                            MAX_FRAME-next_input_+1));
    }
    std::vector<ScheduledInput> pending_inputs()const {
        std::vector<ScheduledInput> result;result.reserve(pending_.size());
        for(const auto& pair:pending_)result.push_back(pair.second);
        return result;
    }
    std::vector<AuthorityReceipt> authority_backlog()const{return {authority_.begin(),authority_.end()};}

    ScheduledInput submit(const Bytes& body,std::uint32_t action_count,std::optional<Frame> frame=std::nullopt) {
        active();const Frame assigned=frame.value_or(next_input_);valid_frame(assigned);
        require(assigned==next_input_,"submitted input must be the next contiguous frame");
        valid_body(body,action_count,false);
        require(available_credits()>0,"no authoritative input credit available");capacity(body.size());
        ScheduledInput scheduled(assigned,body,action_count);
        require(pending_.emplace(assigned,scheduled).second,"input frame already pending");
        // All allocation/validation precedes mutations below. Returning the
        // immutable snapshot only moves/copies shared ownership, never bytes.
        next_input_=assigned+1;buffered_bytes_+=body.size();++metrics_.submissions;peaks();return scheduled;
    }
    std::vector<ScheduledInput> seed(const std::vector<InputBody>& bodies) {
        active();require(next_input_==0 && received_==-1,"startup inputs may be seeded only once");
        require(bodies.size()==window_,"startup requires exactly one supplied body per input credit");
        std::size_t bytes=0;
        for(const auto& value:bodies){valid_body(value.body,value.action_count,false);bytes+=value.body.size();}
        capacity(bytes);
        std::map<Frame,ScheduledInput> staged;std::vector<ScheduledInput> result;result.reserve(window_);
        Frame frame=0;
        for(const auto& value:bodies) {
            ScheduledInput scheduled(frame,value.body,value.action_count);
            staged.emplace(frame,scheduled);result.push_back(scheduled);++frame;
        }
        // The whole startup commits only after every body and allocation passed.
        pending_.swap(staged);next_input_=frame;buffered_bytes_+=bytes;
        metrics_.submissions+=window_;peaks();return result;
    }
    AuthorityReceipt observe_authority(Frame frame,const Bytes& canonical,std::uint32_t action_count) {
        active();valid_frame(frame);const auto found=pending_.find(frame);
        require(frame==received_+1 && found!=pending_.end(),"authority must be new, contiguous and previously submitted");
        valid_body(canonical,action_count,true);
        require(authority_.size()<limits_.max_authority_backlog,"unconfirmed authority backlog limit reached");
        capacity(canonical.size());
        AuthorityReceipt receipt(found->second,canonical,action_count);
        authority_.push_back(receipt);
        received_=frame;buffered_bytes_+=canonical.size();++metrics_.receipts;
        if(receipt.matched())++metrics_.matched;else ++metrics_.normalized;
        peaks();return receipt;
    }
    AuthorityReceipt mark_confirmed(Frame frame) {
        active();valid_frame(frame);const auto found=pending_.find(frame);
        require(frame==confirmed_+1 && !authority_.empty() && authority_.front().frame()==frame &&
                found!=pending_.end(),"confirmation requires the next received authority frame");
        AuthorityReceipt receipt=authority_.front();
        const auto bytes=found->second.body().size()+receipt.canonical_body().size();
        require(bytes<=buffered_bytes_,"planner byte accounting underflow");
        authority_.pop_front();pending_.erase(found);buffered_bytes_-=bytes;
        confirmed_=frame;predicted_=(std::max)(predicted_,frame);++metrics_.confirmations;return receipt;
    }
    void mark_predicted(Frame frame) {
        active();valid_frame(frame);
        require(frame==predicted_+1 && frame>received_,"prediction must be the next unknown frame");
        require(frame-confirmed_<=limits_.max_prediction_ahead,"prediction lead limit reached");predicted_=frame;
    }
    // Call only AFTER an actual world restore; this method restores no world.
    Frame rollback_prediction() {
        active();const auto old=predicted_;predicted_=confirmed_;return old;
    }
    // The caller retires the old instance before routing a rematch to a fresh
    // planner. This policy does not identify match IDs or authenticate callbacks.
    void retire() {
        retired_=true;pending_.clear();authority_.clear();buffered_bytes_=0;
    }
private:
    void active()const{require(!retired_,"input planner has retired its match");}
    static void valid_frame(Frame frame){require(frame>=0 && frame<=MAX_FRAME,"frame must be a nonnegative int32");}
    static void valid_body(const Bytes& body,std::uint32_t count,bool canonical) {
        require(body.size()<=MAX_BODY_BYTES && count<=256,"input body/action count limit");
        require(!body.empty() || (!canonical && count==0),"empty canonical identity or action body");
    }
    void capacity(std::size_t extra)const {
        require(buffered_bytes_<=limits_.max_buffered_bytes && extra<=limits_.max_buffered_bytes-buffered_bytes_,
                "input planner byte capacity reached");
    }
    void peaks() {
        metrics_.peak_pending_inputs=(std::max)(metrics_.peak_pending_inputs,pending_.size());
        metrics_.peak_authority_backlog=(std::max)(metrics_.peak_authority_backlog,authority_.size());
        metrics_.peak_buffered_bytes=(std::max)(metrics_.peak_buffered_bytes,buffered_bytes_);
    }
    const std::uint32_t window_;
    const Limits limits_;
    Frame next_input_=0,received_=-1,confirmed_=-1,predicted_=-1;
    std::map<Frame,ScheduledInput> pending_;
    std::deque<AuthorityReceipt> authority_;
    std::size_t buffered_bytes_=0;
    bool retired_=false;
    Metrics metrics_;
};
}
