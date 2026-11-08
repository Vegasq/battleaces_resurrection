#include "client_compatibility.hpp"
#include "match_loading_state.hpp"
#include <cassert>
#include <iostream>
int main(){
    ba_client_compat::State policy;
    assert(policy.serverError("BA_UPDATE_REQUIRED/2/Client update required.\nGet the latest installer from GitHub Releases."));
    assert(policy.message.find("Client update required.")==0);
    const auto saved=policy.message;
    assert(!policy.serverError("connection ended") && policy.message==saved);
    for(const auto& input:{"BA_UPDATE_REQUIRED//text","BA_UPDATE_REQUIRED/4294967296/text",
                          "BA_UPDATE_REQUIRED/x/text","BA_UPDATE_REQUIRED/2/","BA_UPDATE_REQUIRED/2/bad\rtext"}) {
        bool failed=false;try{policy.serverError(input);}catch(const std::runtime_error&){failed=true;}
        assert(failed && policy.message==saved);
    }
    assert(policy.serverError("extra hello fields") && policy.message.find("Server update required.")==0);
    policy.accepted();assert(policy.message.empty());
    ba_match_loading::Model model;
    const auto ticket=model.begin(ba_match_loading::Source::Practice,"offline",ba_match_loading::Stage::Loading);
    assert(model.setPersistent(saved) && model.displayVisible());
    assert(model.finish(ticket) && !model.visible && model.displayVisible());
    assert(!model.expire(UINT64_MAX) && model.displayVisible());
    const auto next=model.begin(ba_match_loading::Source::Public,"retry",ba_match_loading::Stage::Preparing);
    assert(model.persistentMessage==saved && model.owns(next));
    assert(model.setPersistent("") && model.displayVisible() && model.owns(next));
    assert(model.finish(next) && !model.displayVisible());
    std::cout<<"Client update policy bounds, persistence, offline ownership and successful reconnect checks passed\n";
}
