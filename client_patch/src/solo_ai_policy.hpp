#pragma once
#include "public_attempt.hpp"
#include <stdexcept>
#include <string>

// Local arbitration only; never infer the human count after READY/assignment.
namespace ba_solo_ai {
enum class Host {Local,Server};
inline Host parseHost(const std::string& value="local") {
    if(value=="local")return Host::Local;
    if(value=="server")return Host::Server;
    throw std::runtime_error("solo AI host must be local or server");
}
inline const char* name(Host value){return value==Host::Local?"local":"server";}
constexpr const char* offerReason="solo_ai_offer";
enum class Action {Online,CancelOffer,AwaitRetirement,StartLocal,RetireOnly};
class Handoff {
    Host host_;
    bool pending_=false,proposalChanged_=false;
    std::string proposal_;
public:
    explicit Handoff(Host host):host_(host){}
    bool pending() const{return pending_;}
    Action observe(const ba_public_attempt::Attempt& intent,bool joining=false) {
        // User cancellation and any possible online commit take precedence.
        // Existing public lifecycle code owns those states,not a local transfer.
        if(intent.cancelled || joining || intent.readySent || intent.committed || intent.assigned) {
            pending_=false;return Action::Online;
        }
        if(pending_) {
            if(intent.retired)
                return !proposalChanged_ && intent.mayFallback()?Action::StartLocal:Action::RetireOnly;
            if(intent.phase==ba_public_wire::Waiting ||
               (intent.phase==ba_public_wire::Offered &&
                (intent.match!=proposal_ || intent.reason!=offerReason)))proposalChanged_=true;
            return Action::AwaitRetirement;
        }
        if(host_==Host::Local && intent.entered && !intent.retired &&
           intent.phase==ba_public_wire::Offered && intent.reason==offerReason && !intent.match.empty()) {
            proposal_=intent.match;pending_=true;return Action::CancelOffer;
        }
        return Action::Online;
    }
};
}
