#pragma once
#include "native_settings.hpp"
namespace ba_native_backup {
using ba_native_settings::require;
// One input decision per owned profile/process. A rejected input is never
// replaced later, even if an external lock disappears. Repair requires restart.
class Input {
    enum class State { Unprepared, Existing, Missing, Accepted, Refused };
    State state=State::Unprepared;
    std::wstring target;
    ba_native_settings::Handle pin;
public:
    explicit Input(std::wstring path):target(std::move(path)) {
        require(!target.empty() && target.size()<MAX_PATH,"native backup path exceeds supported native length");
    }
    bool prepare() {
        require(state==State::Unprepared,"native backup input already examined");state=State::Refused;
        pin.value=CreateFileW(target.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL|FILE_FLAG_OPEN_REPARSE_POINT,nullptr);
        if(pin.value==INVALID_HANDLE_VALUE) {
            if(GetLastError()==ERROR_FILE_NOT_FOUND){state=State::Missing;return true;}
            return false;
        }
        ba_native_settings::ordinary(pin.value);LARGE_INTEGER size{};
        require(GetFileSizeEx(pin.value,&size) && size.QuadPart>0 && size.QuadPart<=1024*1024,
            "native backup input size invalid");
        state=State::Existing;return true;
    }
    void finish(bool nativeAccepted) {
        require(state==State::Existing || state==State::Missing,"native backup input decision unavailable");
        if(state==State::Existing && !nativeAccepted){state=State::Refused;return;}
        // Original missing-file '{}' is allowed to report false. It contains no
        // user bytes to preserve. Original Init already created valid defaults.
        if(pin.value!=INVALID_HANDLE_VALUE) {
            require(CloseHandle(pin.value)!=0,"native backup input release failed");pin.value=INVALID_HANDLE_VALUE;
        }
        state=State::Accepted;
    }
    void refuse(){state=State::Refused;}
    bool writable() const{return state==State::Accepted;}
    const std::wstring& path() const{return target;}
};
}
