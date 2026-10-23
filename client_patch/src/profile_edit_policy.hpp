#pragma once
#include "command_line.h"
// Explicit diagnostic authorization only. Normal launchers never request it.
namespace ba_profile_edit_policy {
inline bool allowed(const std::vector<std::wstring>& args,const std::string& profile) {
    if(profile.rfind("nativestest_",0)!=0 || profile.size()<13 || profile.size()>46)return false;
    for(size_t i=12;i<profile.size();++i) {
        const char c=profile[i];if(!((c>='a'&&c<='z')||(c>='0'&&c<='9')||c=='_'||c=='-'))return false;
    }
    for(const auto* flag:{L"-profile-edits-smoke",L"-cosmetics-equip-smoke",L"-practice-settings-smoke",
                         L"-native-settings-deck-proof",L"-native-settings-deck-edit",
                         L"-native-quit-smoke",L"-native-quit-gate-smoke"})
        if(!ba_command_line::has(args,flag))return false;
    std::wstring mode;
    return ba_command_line::value(args,L"-native-quit-mode=",mode) && mode==L"confirm";
}
}
