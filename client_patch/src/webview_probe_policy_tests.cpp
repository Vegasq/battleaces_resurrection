#include "webview_probe_policy.hpp"
#include <cassert>
#include <iostream>
int main() {
    using namespace ba_webview_probe_policy;
    const std::vector<std::wstring> good={L"game.exe",L"-native-webview-proof",L"-native-quit-smoke",L"-native-quit-gate-smoke",L"-native-quit-mode=confirm"};
    assert(allowed(good,"nativestest_webview147_a1"));
    for(size_t i=1;i<good.size();++i){auto a=good;a.erase(a.begin()+i);assert(!allowed(a,"nativestest_webview147_a1"));}
    for(const auto* p:{"default","nativestest_","nativestest_../other","nativestest_a/b","nativestest_a\\b","nativestest_UPPER"})assert(!allowed(good,p));
    auto bad=good;bad.back()=L"-native-quit-mode=cancel";assert(!allowed(bad,"nativestest_webview147_a1"));
    for(const auto* f:{L"-profile-edits-smoke",L"-practice-ai-smoke",L"-unified-smoke",L"-custom-menu-smoke",L"-offline-tutorial2"}) {
        auto a=good;a.push_back(f);assert(!allowed(a,"nativestest_webview147_a1"));
    }
    assert(!allowed({L"game.exe",L"-offline-practice"},"nativestest_webview147_a1"));
    std::cout<<"WebView diagnostic policy tests passed\n";
}
