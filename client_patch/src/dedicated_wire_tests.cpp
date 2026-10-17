// Authored protocol fixtures only; no game assets or game-derived code.
#include "dedicated_wire.hpp"
#include <cassert>
#include <iostream>

int main() {
    using namespace ba_wire;
    static_assert(protocol==3);
    std::vector<unsigned char> welcome(34,0);
    welcome[0]=1;
    for(unsigned window=2;window<=12;++window) {
        welcome[1]=static_cast<unsigned char>(window);
        auto decoded=parseWelcome(welcome,255);
        assert(decoded.slot==1 && decoded.inputWindow==window);
        assert(parseWelcome(welcome,1).slot==1);
    }
    auto rejected=[](const std::vector<unsigned char>& value,int requested=255) {
        bool failed=false;
        try {parseWelcome(value,requested);}catch(const std::exception&){failed=true;}
        assert(failed);
    };
    for(unsigned window:{0u,1u,13u,255u}) {welcome[1]=static_cast<unsigned char>(window);rejected(welcome);}
    welcome[1]=6;rejected(welcome,0);
    welcome[0]=2;rejected(welcome);welcome[0]=1;
    welcome.pop_back();rejected(welcome);  // Legacy protocol2 WELCOME is33 bytes.
    welcome.clear();rejected(welcome);
    std::cout << "dedicated protocol3 welcome bounds passed\n";
}
