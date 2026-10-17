// Asset-free test: compile separately, never into BattleAcesOffline.dll.
#include "command_line.h"
#include <cassert>
#include <iostream>
int main() {
    using namespace ba_command_line;
    std::wstring out;
    auto args=parse(L"\"C:\\Games\\Battle Aces.exe\" -player-name=\"Player One\" -room=alpha");
    assert(args.size()==3 && args[0]==L"C:\\Games\\Battle Aces.exe");
    assert(value(args,L"-player-name=",out) && out==L"Player One");
    assert(value(args,L"-room=",out) && out==L"alpha");
    args=parse(L"game.exe \"-player-name=Player Two\" -room=\"\" -offline-lan");
    assert(value(args,L"-player-name=",out) && out==L"Player Two");
    assert(value(args,L"-room=",out) && out.empty());
    assert(has(args,L"-offline-lan") && !has(args,L"-offline"));
    args=parse(L"game.exe -player-name=\"contains -room=wrong\" -room=right -lan-slot=1");
    assert(value(args,L"-room=",out) && out==L"right");
    assert(value(args,L"-lan-slot=",out) && out==L"1");
    assert(!value(args,L"-player=",out));
    args=parse(L"game.exe -path=\"C:\\Some Folder\\\\\" -literal=one\\\"two");
    assert(value(args,L"-path=",out) && out==L"C:\\Some Folder\\");
    assert(value(args,L"-literal=",out) && out==L"one\"two");
    args=parse(L"game.exe\t-player-name=\"Jos\u00e9 One\"\t-room=final");
    assert(value(args,L"-player-name=",out) && out==L"Jos\u00e9 One");
    assert(value(args,L"-room=",out) && out==L"final");
    args=parse(L"game.exe -room=first -room=second -path=C:\\a\\b");
    assert(value(args,L"-room=",out) && out==L"first");
    assert(value(args,L"-path=",out) && out==L"C:\\a\\b");
    std::cout << "command-line argument tests passed\n";
}
