#pragma once
// Our bounded application-state format; no installed catalog data is embedded.
#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>
namespace ba_cosmetics_state {
constexpr size_t SlotCount=17,MaxBytes=4096;
using Pairs=std::vector<std::pair<uint32_t,uint32_t>>;
inline void require(bool condition,const char* why) {if(!condition)throw std::runtime_error(why);}
inline bool profileKey(const std::string& value) {
    if(value.empty() || value.size()>48)return false;
    for(char c:value)if(!((c>='a'&&c<='z') || (c>='0'&&c<='9') || c=='_' || c=='-'))return false;
    if(value=="con" || value=="prn" || value=="aux" || value=="nul")return false;
    if(value.size()==4 && (value.compare(0,3,"com")==0 || value.compare(0,3,"lpt")==0) && value[3]>='1' && value[3]<='9')return false;
    return true;
}
inline bool digest(const std::string& value) {
    return value.size()==64 && std::all_of(value.begin(),value.end(),[](char c){return (c>='0'&&c<='9') || (c>='a'&&c<='f');});
}
struct State {std::string profile,catalog;Pairs slots;};
inline void validate(const State& state) {
    require(profileKey(state.profile),"invalid local cosmetic profile key");
    require(digest(state.catalog),"invalid cosmetic catalog digest");
    require(state.slots.size()==SlotCount,"incomplete cosmetic state");
    std::vector<uint32_t> ids,items;
    for(const auto& pair:state.slots) {
        require(pair.first && std::find(ids.begin(),ids.end(),pair.first)==ids.end(),"duplicate/zero cosmetic state slot");ids.push_back(pair.first);
        require(!pair.second || std::find(items.begin(),items.end(),pair.second)==items.end(),"duplicate nonzero cosmetic state item");
        if(pair.second)items.push_back(pair.second);
    }
}
inline std::string encode(const State& state) {
    validate(state);
    std::string text="{\"schema\":1,\"build\":37822,\"profile\":\""+state.profile+"\",\"catalog_sha256\":\""+state.catalog+"\",\"slots\":[";
    for(const auto& pair:state.slots) {
        if(text.back()!='[')text+=',';
        text+='[';text+=std::to_string(pair.first);text+=',';text+=std::to_string(pair.second);text+=']';
    }
    text+="]}\n";require(text.size()<=MaxBytes,"cosmetic state byte limit");return text;
}
// State is application generated canonical JSON. Reordered fields, escaped keys,
// duplicate keys, coercions and other JSON spellings are rejected, never merged.
struct Reader {
    const std::string& text;size_t offset=0;
    void token(const char* value) {
        const size_t count=std::char_traits<char>::length(value);
        require(text.compare(offset,count,value)==0,"invalid cosmetic state format");offset+=count;
    }
    std::string string() {
        token("\"");const auto end=text.find('"',offset);require(end!=std::string::npos,"unterminated cosmetic state string");
        const auto value=text.substr(offset,end-offset);offset=end+1;return value;
    }
    uint32_t number() {
        require(offset<text.size() && text[offset]>='0' && text[offset]<='9',"invalid cosmetic state integer");
        const size_t first=offset;uint64_t value=0;
        while(offset<text.size() && text[offset]>='0' && text[offset]<='9') {
            value=value*10+static_cast<unsigned>(text[offset++]-'0');require(value<=UINT32_MAX,"cosmetic state integer overflow");
        }
        require(offset==first+1 || text[first]!='0',"noncanonical cosmetic state integer");return static_cast<uint32_t>(value);
    }
};
inline State decode(const std::string& text) {
    require(!text.empty() && text.size()<=MaxBytes,"cosmetic state byte limit");Reader reader{text};State state;
    reader.token("{\"schema\":1,\"build\":37822,\"profile\":");state.profile=reader.string();
    reader.token(",\"catalog_sha256\":");state.catalog=reader.string();reader.token(",\"slots\":[");
    for(size_t i=0;i<SlotCount;++i) {
        if(i)reader.token(",");reader.token("[");const auto slot=reader.number();reader.token(",");const auto item=reader.number();reader.token("]");state.slots.emplace_back(slot,item);
    }
    reader.token("]}\n");require(reader.offset==text.size(),"trailing cosmetic state bytes");validate(state);return state;
}
}
