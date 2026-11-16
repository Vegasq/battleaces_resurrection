#pragma once
#include <cstdint>
#include <stdexcept>
#include <string>

namespace ba_client_status {
inline void require(bool value) {if(!value)throw std::runtime_error("Invalid public client status metadata");}
inline bool endpointCharacter(unsigned char c) {
    return (c>='a' && c<='z') || (c>='0' && c<='9') || c=='.' || c==':' || c=='-';
}
struct Target {
    std::string host,peer;
    uint16_t port=0;
    std::string label() const {
        if(host.empty())return "Not configured";
        const std::string address=(host.find(':')==std::string::npos?host:"["+host+"]")+":"+std::to_string(port);
        return address+(!peer.empty() && peer!=host?" ("+peer+")":"");
    }
};
inline Target decode(const unsigned char* data,size_t size) {
    require(size>=5 && size<=303 && data[0]==1);
    const size_t count=data[1];require(count<=253 && size>=count+5);
    const size_t peerCount=data[4+count];require(peerCount<=45 && size==count+peerCount+5);
    Target result;result.host.assign(reinterpret_cast<const char*>(data+2),count);
    result.port=static_cast<uint16_t>(data[2+count]|(data[3+count]<<8));
    result.peer.assign(reinterpret_cast<const char*>(data+5+count),peerCount);
    require(count?(result.port!=0):(result.port==0 && peerCount==0));
    for(unsigned char c:result.host)require(endpointCharacter(c));
    for(unsigned char c:result.peer)require((c>='0' && c<='9') || (c>='a' && c<='f') || c=='.' || c==':');
    return result;
}
inline std::string safeBuild(const std::string& text) {
    if(text.empty() || text.size()>96)return "Development (build unknown)";
    for(unsigned char c:text)if(!((c>='A'&&c<='Z') || (c>='a'&&c<='z') || (c>='0'&&c<='9') ||
        c=='.'||c=='+'||c=='('||c==')'||c==','||c==' '||c=='-'))return "Development (build unknown)";
    return text;
}
inline std::string safeConfigured(const std::string& text) {
    if(text.empty() || text.size()>263)return "Not configured";
    for(unsigned char c:text)if(!endpointCharacter(c) && c!='[' && c!=']')return "Not configured";
    return text;
}
}
