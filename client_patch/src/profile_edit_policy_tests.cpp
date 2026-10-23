#include "profile_edit_policy.hpp"
#include <cassert>
#include <iostream>
int main() {
    const auto args=ba_command_line::parse(L"game.exe -profile-edits-smoke -cosmetics-equip-smoke -practice-settings-smoke "
        L"-native-settings-deck-proof -native-settings-deck-edit -native-quit-smoke -native-quit-gate-smoke -native-quit-mode=confirm");
    assert(ba_profile_edit_policy::allowed(args,"nativestest_edits141"));
    for(const auto& profile:{"default","nativestest_","cosmeticstest_owned","nativestest_../owner","nativestest_Upper"})
        assert(!ba_profile_edit_policy::allowed(args,profile));
    assert(!ba_profile_edit_policy::allowed(args,"nativestest_"+std::string(35,'a')));
    for(size_t i=1;i<args.size();++i) {
        auto missing=args;missing.erase(missing.begin()+i);
        assert(!ba_profile_edit_policy::allowed(missing,"nativestest_edits141"));
    }
    for(const auto* mode:{L"cancel",L"inventory",L"confirmation"}) {
        auto changed=args;changed.back()=std::wstring(L"-native-quit-mode=")+mode;
        assert(!ba_profile_edit_policy::allowed(changed,"nativestest_edits141"));
    }
    assert(!ba_profile_edit_policy::allowed(ba_command_line::parse(L"game.exe"),"nativestest_edits141"));
    std::cout<<"Profile edit diagnostic policy tests passed\n";
}
