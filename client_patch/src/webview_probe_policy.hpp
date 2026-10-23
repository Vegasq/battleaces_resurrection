#pragma once
#include "command_line.h"
namespace ba_webview_probe_policy {
inline bool allowed(const std::vector<std::wstring>& args,const std::string& profile) {
    if(profile.rfind("nativestest_",0)!=0 || profile.size()<13 || profile.size()>46)return false;
    for(size_t i=12;i<profile.size();++i) {
        const char c=profile[i];if(!((c>='a'&&c<='z')||(c>='0'&&c<='9')||c=='_'||c=='-'))return false;
    }
    for(const auto* flag:{L"-native-webview-proof",L"-native-quit-smoke",L"-native-quit-gate-smoke"})
        if(!ba_command_line::has(args,flag))return false;
    for(const auto* flag:{L"-profile-edits-smoke",L"-practice-ai-smoke",L"-unified-smoke",
        L"-custom-menu-smoke",L"-custom-transition-smoke",L"-remote-profile-smoke",
        L"-native-replay-playback",L"-offline-tutorial",L"-offline-tutorial2"})
        if(ba_command_line::has(args,flag))return false;
    std::wstring mode;
    return ba_command_line::value(args,L"-native-quit-mode=",mode) && mode==L"confirm";
}
}
