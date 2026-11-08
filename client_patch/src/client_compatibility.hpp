#pragma once
#include <cstdint>
#include <stdexcept>
#include <string>
namespace ba_client_compat {
constexpr uint32_t revision=1;
struct State {
    std::string message;
    void accepted(){message.clear();}
    bool serverError(const std::string& error) {
        const std::string prefix="BA_UPDATE_REQUIRED/";
        if(error.rfind(prefix,0)==0) {
            const auto slash=error.find('/',prefix.size());
            if(slash==std::string::npos || slash==prefix.size() || slash-prefix.size()>10)
                throw std::runtime_error("invalid update policy");
            uint64_t minimum=0;
            for(size_t i=prefix.size();i<slash;++i){
                const char c=error[i];if(c<'0'||c>'9')throw std::runtime_error("invalid update revision");
                minimum=minimum*10+static_cast<unsigned>(c-'0');
                if(minimum>UINT32_MAX)throw std::runtime_error("invalid update revision");
            }
            const auto text=error.substr(slash+1);
            if(text.empty() || text.size()>160)throw std::runtime_error("invalid update message size");
            for(unsigned char c:text)if((c<32 || c>126) && c!='\n')throw std::runtime_error("invalid update message text");
            message=text;return true;
        }
        // An older server rejects this client's revision trailer before welcome.
        if(error=="extra hello fields" || error=="unsupported community protocol" ||
           error=="unsupported game protocol; update client and server together") {
            message="Server update required.\nThis client is incompatible with the server. Offline AI is still available.";
            return true;
        }
        return false;
    }
};
static State state;
}
