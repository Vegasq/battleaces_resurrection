#define WIN32_LEAN_AND_MEAN
#include "cosmetics_store.hpp"
#include <iostream>
#include <functional>
namespace state=ba_cosmetics_state;
static void check(bool yes,const char* why){if(!yes)throw std::runtime_error(why);}
static void rejects(const std::function<void()>& action){bool rejected=false;try{action();}catch(const std::runtime_error&){rejected=true;}check(rejected,"invalid state/operation accepted");}
static state::State fixture(const std::string& profile="alpha") {
    state::State value{profile,std::string(64,'a'),{}};
    for(uint32_t i=0;i<17;++i)value.slots.emplace_back(1000+i,i<14?5000+i:0);return value;
}
static void codec() {
    auto value=fixture();std::swap(value.slots[3].second,value.slots[11].second);
    const auto text=state::encode(value),parsed=state::encode(state::decode(text));check(parsed==text,"state order/full map did not round-trip");
    check(state::decode(text).slots.size()==17 && state::decode(text).slots.back().second==0,"empty slot lost");
    for(size_t i=0;i<text.size();++i)rejects([&]{state::decode(text.substr(0,i));});
    for(const auto& key:{"", "..", "alpha/other", "alpha\\other", "ALPHA", "con", "prn", "aux", "nul", "com1", "lpt9", "space key", "a:b"})
        check(!state::profileKey(key),"unsafe profile key accepted");
    for(const auto& key:{"default", "alpha-2", "beta_3", "com0", "lpt10"})check(state::profileKey(key),"safe profile key rejected");
    check(state::profileKey(std::string(48,'a')) && !state::profileKey(std::string(49,'a')),"profile key bound failed");
    for(auto bad:{text+" ",text+std::string("\0extra",6),std::string(state::MaxBytes+1,'x'),std::string("{}")})rejects([&]{state::decode(bad);});
    for(const auto& replacement:{"-1","true","1.0","1e3","01000","4294967296"}) {
        auto bad=text;const auto at=bad.find("1000");check(at!=std::string::npos,"fixture missing");bad.replace(at,4,replacement);rejects([&]{state::decode(bad);});
    }
    for(const auto& marker:{"\"schema\":1","\"build\":37822","\"profile\":","\"slots\":"}) {
        auto bad=text;const auto at=bad.find(marker);bad.insert(at,"\"extra\":0,");rejects([&]{state::decode(bad);});
    }
    auto bad=value;bad.profile="con";rejects([&]{state::encode(bad);});
    bad=value;bad.catalog[0]='A';rejects([&]{state::encode(bad);});
    bad=value;bad.slots.pop_back();rejects([&]{state::encode(bad);});
    bad=value;bad.slots[1].first=bad.slots[0].first;rejects([&]{state::encode(bad);});
    bad=value;bad.slots[1].second=bad.slots[0].second;rejects([&]{state::encode(bad);});
    bad=value;bad.slots[0].first=0;rejects([&]{state::encode(bad);});
    value.slots[0]={UINT32_MAX,UINT32_MAX};check(state::decode(state::encode(value)).slots==value.slots,"uint32 boundary failed");
}
static void write(const std::wstring& path,const std::string& bytes) {
    state::Handle handle(CreateFileW(path.c_str(),GENERIC_WRITE,0,nullptr,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr));state::regular(handle.value);
    DWORD count=0;check(WriteFile(handle.value,bytes.data(),static_cast<DWORD>(bytes.size()),&count,nullptr) && count==bytes.size(),"fixture write failed");
}
struct Folder {
    std::wstring path;
    Folder() {
        wchar_t current[32768],full[32768];const DWORD count=GetCurrentDirectoryW(32768,current);check(count && count<32768,"test cwd missing");
        std::wstring selected=std::wstring(current)+L"\\cosmetics-state-tests-"+std::to_wstring(GetCurrentProcessId())+L"-"+std::to_wstring(GetTickCount64());
        const DWORD length=GetFullPathNameW(selected.c_str(),32768,full,nullptr);check(length && length<32768 && std::wstring(full)==selected,"test path escaped cwd");
        check(CreateDirectoryW(full,nullptr)!=0,"test directory already exists or unavailable");path=std::wstring(full)+L"\\";
    }
    ~Folder() {
        // Only fixed owned fixture files; no recursive or enumerated deletion.
        for(const auto& key:{L"alpha",L"beta"})for(const auto& suffix:{L".cosmetics.json",L".cosmetics.lock"}) {
            const auto file=path+L".battleaces-resurrection\\profiles\\"+key+suffix;
            SetFileAttributesW(file.c_str(),FILE_ATTRIBUTE_NORMAL);DeleteFileW(file.c_str());
        }
        RemoveDirectoryW((path+L".battleaces-resurrection\\profiles").c_str());RemoveDirectoryW((path+L".battleaces-resurrection").c_str());
        const auto root=path.substr(0,path.size()-1);RemoveDirectoryW(root.c_str());
    }
};
static void storage() {
    Folder directory;const auto first=state::encode(fixture()),second=state::encode(fixture("beta"));std::wstring alpha;
    {
        state::Store store(directory.path,"alpha");alpha=store.path();check(!store.load(),"new profile exists");store.save(first);
        check(store.load()==std::optional<std::string>(first),"saved profile mismatch");
        DWORD before=0,after=0;GetProcessHandleCount(GetCurrentProcess(),&before);
        for(int i=0;i<50;++i)rejects([&]{state::Store conflict(directory.path,"alpha");});
        GetProcessHandleCount(GetCurrentProcess(),&after);check(after==before,"failed competing writer leaked handles");
        {state::Store beta(directory.path,"beta");check(!beta.load(),"profiles share state");beta.save(second);}
        check(store.load()==std::optional<std::string>(first),"other profile changed selection");
        rejects([&]{store.save(second);});check(store.load()==std::optional<std::string>(first),"cross-profile write changed file");
        auto changed=fixture();changed.slots[0].second=9000;const auto next=state::encode(changed);
        check(SetFileAttributesW(alpha.c_str(),FILE_ATTRIBUTE_READONLY)!=0,"fixture readonly failed");rejects([&]{store.save(next);});
        check(store.load()==std::optional<std::string>(first),"failed atomic replacement damaged old file");
        check(SetFileAttributesW(alpha.c_str(),FILE_ATTRIBUTE_NORMAL)!=0,"fixture readonly restore failed");store.save(next);
        check(store.load()==std::optional<std::string>(next),"atomic replacement did not persist");
        write(alpha,"external edit");rejects([&]{store.save(first);});check(store.load()==std::optional<std::string>("external edit"),"external edit overwritten");
    }
    {state::Store restart(directory.path,"beta");check(restart.load()==std::optional<std::string>(second),"restart lost profile");}
    write(alpha,std::string(state::MaxBytes+1,'x'));{state::Store oversized(directory.path,"alpha");rejects([&]{oversized.load();});}
    rejects([&]{state::Store unsafe(directory.path,"../beta");});
    // Parent exists as a file: never redirect state writes or delete it.
    Folder blocked;const auto parent=blocked.path+L".battleaces-resurrection";write(parent,"ordinary fixture");
    rejects([&]{state::Store unavailable(blocked.path,"alpha");});check(DeleteFileW(parent.c_str())!=0,"blocked fixture changed");
}
int main(){try{codec();storage();std::cout<<"Cosmetic full-map codec, atomic saves, restart, isolation and writer-lock checks passed\n";return 0;}
    catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
