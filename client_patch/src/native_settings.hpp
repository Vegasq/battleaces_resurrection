#pragma once
#include "command_line.h"
#include "cosmetics_store.hpp"
#include <atomic>
// Prepare only the destination/lock. The original game owns TOML serialization.
namespace ba_native_settings {
using ba_cosmetics_state::Handle;
inline void require(bool condition,const char* message){if(!condition)throw std::runtime_error(message);}
// Publish completion by request order. A late older success must not hide a
// newer refused/failed write (including same-thread reentry).
class SaveOutcome {
    std::atomic<unsigned long long> latest{1};
public:
    bool load() const{return (latest.load()&1)!=0;}
    bool newerThan(unsigned long long sequence) const{return (latest.load()>>1)>sequence;}
    void record(unsigned long long sequence,bool succeeded) noexcept {
        if(!sequence || sequence>(~0ull>>1)){latest.store(~1ull);return;}
        const auto replacement=(sequence<<1)|(succeeded?1ull:0ull);auto observed=latest.load();
        while((observed>>1)<sequence && !latest.compare_exchange_weak(observed,replacement)){}
    }
};
inline std::string profile(const std::vector<std::wstring>& args) {
    std::string result="default";unsigned count=0;
    for(size_t i=1;i<args.size();++i)if(args[i].compare(0,15,L"-local-profile=")==0) {
        require(++count==1,"duplicate native local profile option");result.clear();
        for(wchar_t c:args[i].substr(15)){require(c<128,"native local profile must be ASCII");result.push_back(static_cast<char>(c));}
    }
    require(ba_cosmetics_state::profileKey(result),"invalid native local profile key");return result;
}
inline void ordinary(HANDLE file,bool directory=false) {
    ba_cosmetics_state::regular(file,directory);BY_HANDLE_FILE_INFORMATION info{};
    require(GetFileInformationByHandle(file,&info) && (directory || info.nNumberOfLinks==1),"native settings cannot use hard links");
}
inline void exactDirectory(HANDLE file,const std::wstring& expected) {
    ordinary(file,true);wchar_t finalPath[32768];
    const DWORD count=GetFinalPathNameByHandleW(file,finalPath,32768,FILE_NAME_NORMALIZED|VOLUME_NAME_DOS);
    require(count && count<32768,"native settings final directory unavailable");std::wstring actual(finalPath);
    if(actual.compare(0,4,L"\\\\?\\")==0)actual.erase(0,4);
    require(_wcsicmp(actual.c_str(),expected.c_str())==0,"native settings directory resolves outside installation");
}
class Session {
    std::string key;
    std::wstring target;
    Handle gameHandle,baseHandle,profilesHandle,profileHandle,lockHandle,inputGuard;
    bool hadInput=false;
    std::atomic<bool> inputPending{false};
public:
    Session(const std::wstring& game,const std::string& selected):key(selected) {
        require(ba_cosmetics_state::profileKey(key),"invalid native local profile key");
        require(game.size()>3 && game[1]==L':' && game[2]==L'\\' && game.back()==L'\\',"native settings require an absolute local installation");
        wchar_t full[32768];const DWORD count=GetFullPathNameW(game.c_str(),32768,full,nullptr);
        require(count && count<32768 && game==full,"native settings installation is not canonical");
        const auto root=game.substr(0,game.size()-1);
        gameHandle.value=CreateFileW(root.c_str(),FILE_LIST_DIRECTORY|FILE_READ_ATTRIBUTES,FILE_SHARE_READ|FILE_SHARE_WRITE,nullptr,OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS|FILE_FLAG_OPEN_REPARSE_POINT,nullptr);exactDirectory(gameHandle.value,root);
        const auto base=game+L".battleaces-resurrection";
        baseHandle.value=ba_cosmetics_state::directory(base);exactDirectory(baseHandle.value,base);
        const auto profiles=base+L"\\profiles";
        profilesHandle.value=ba_cosmetics_state::directory(profiles);exactDirectory(profilesHandle.value,profiles);
        const auto folder=profiles+L"\\"+std::wstring(key.begin(),key.end());
        profileHandle.value=ba_cosmetics_state::directory(folder);exactDirectory(profileHandle.value,folder);
        target=folder+L"\\gameconfig-localuser.toml";
        require(target.size()<MAX_PATH,"native settings path exceeds the supported loader length");
        lockHandle.value=CreateFileW((folder+L"\\native-settings.lock").c_str(),GENERIC_READ|GENERIC_WRITE,FILE_SHARE_READ,
            nullptr,OPEN_ALWAYS,FILE_ATTRIBUTE_NORMAL|FILE_FLAG_OPEN_REPARSE_POINT,nullptr);
        require(lockHandle.value!=INVALID_HANDLE_VALUE,"native local profile is already in use or unavailable");ordinary(lockHandle.value);
        Handle existing(CreateFileW(target.c_str(),GENERIC_READ|GENERIC_WRITE,FILE_SHARE_READ,nullptr,OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL|FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
        if(existing.value==INVALID_HANDLE_VALUE)require(GetLastError()==ERROR_FILE_NOT_FOUND,"native settings file is unavailable or unwritable");
        else {
            ordinary(existing.value);BY_HANDLE_FILE_INFORMATION before{},after{};
            require(GetFileInformationByHandle(existing.value,&before)!=0,"native settings input identity unavailable");
            require(CloseHandle(existing.value)!=0,"native settings preflight handle release failed");existing.value=INVALID_HANDLE_VALUE;
            // Native startup writes options before deserializing the deck. Keep
            // an existing input readable but unwritable until the early guard
            // accepts it; original StreamWriter failures/results stay intact.
            inputGuard.value=CreateFileW(target.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL|FILE_FLAG_OPEN_REPARSE_POINT,nullptr);ordinary(inputGuard.value);
            require(GetFileInformationByHandle(inputGuard.value,&after) && before.dwVolumeSerialNumber==after.dwVolumeSerialNumber &&
                before.nFileIndexHigh==after.nFileIndexHigh && before.nFileIndexLow==after.nFileIndexLow,
                "native settings input changed during preflight");hadInput=true;inputPending=true;
        }
        const auto probe=folder+L"\\native-settings-write-"+std::to_wstring(GetCurrentProcessId())+L".tmp";
        Handle writable(CreateFileW(probe.c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr));
        require(writable.value!=INVALID_HANDLE_VALUE,"native settings directory is not writable");
        DWORD written=0;const bool okay=WriteFile(writable.value,"\n",1,&written,nullptr) && written==1 && FlushFileBuffers(writable.value);
        CloseHandle(writable.value);writable.value=INVALID_HANDLE_VALUE;
        const bool removed=DeleteFileW(probe.c_str())!=0;
        require(okay && removed,"native settings write/flush/delete check failed");
    }
    const std::string& profile() const{return key;}
    const std::wstring& path() const{return target;}
    bool inputProtected() const{return inputPending.load();}
    bool hadExistingInput() const{return hadInput;}
    void acceptInput() {
        if(inputGuard.value==INVALID_HANDLE_VALUE)return;
        require(CloseHandle(inputGuard.value)!=0,"validated native settings input handle release failed");inputGuard.value=INVALID_HANDLE_VALUE;inputPending=false;
    }
};
}
