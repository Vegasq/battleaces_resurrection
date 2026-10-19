// Authored fixtures only; no game installation or recovered packet captures.
#include "community_wire.hpp"
#include <cassert>
#include <iostream>
using namespace ba_community_wire;
template<class F> void rejects(F call){bool rejected=false;try{call();}catch(const std::exception&){rejected=true;}assert(rejected);}
int main() {
    Writer w;w.number(1,2);w.number(3,2);w.id("test_profile");w.deck({1,2,3,4,5,6,7,8});
    const auto welcome=std::get<Welcome>(decode(WelcomeKind,w.bytes));
    assert(welcome.profile=="test_profile" && welcome.deck[7]==8);
    for(size_t length=0;length<w.bytes.size();++length)rejects([&]{decode(WelcomeKind,Bytes(w.bytes.begin(),w.bytes.begin()+length));});
    w.bytes.push_back(0);rejects([&]{decode(WelcomeKind,w.bytes);});w.bytes.pop_back();
    w.bytes[0]=2;rejects([&]{decode(WelcomeKind,w.bytes);});
    for(const auto& text:{std::string("\xc0\xaf"),std::string("\xed\xa0\x80"),std::string("\xf4\x90\x80\x80"),
        std::string("\xe2\x28\xa1"),std::string("\xf0\x90"),std::string("\n")})rejects([&]{utf8(text);});
    assert(utf8("One \xf0\x9f\x8e\xae")==5);
    rejects([]{key("../profile");});rejects([]{key("");});rejects([]{create(0);});
    Writer directory;directory.number(7,8);directory.number(2,2);
    for(const auto& profile:{"a","b"}){directory.id(profile);directory.text("Name");directory.number(0,1);directory.number(1,1);}
    auto rows=std::get<Directory>(decode(DirectoryKind,directory.bytes));assert(rows.revision==7 && rows.players.size()==2 && rows.players[1].invitable);
    auto bad=directory.bytes;bad[8]=137;rejects([&]{decode(DirectoryKind,bad);});
    bad=directory.bytes;bad.back()=2;rejects([&]{decode(DirectoryKind,bad);});
    Writer state;state.number(9,8);state.number(Starting,1);state.number(4,4);
    state.id("lobby");state.id("a");state.text("");state.text("");state.number(2,1);
    for(const auto& profile:{"a","b"}){state.id(profile);state.deck({1,2,3,4,5,6,7,8});state.number(profile[0]=='a',1);state.number(0,1);}
    auto lobby=std::get<Lobby>(decode(LobbyKind,state.bytes));assert(lobby.host=="a" && lobby.epoch==4 && lobby.members[0].ready && !lobby.members[1].ready);
    auto readyPacket=ready(33,lobby,true);assert(readyPacket.kind==Ready);Reader readyReader(readyPacket.payload);
    assert(readyReader.u32()==33 && readyReader.id()=="lobby" && readyReader.u32()==4 && readyReader.flag());readyReader.end();
    auto startPacket=start(34,lobby);Reader startReader(startPacket.payload);
    assert(startReader.u32()==34 && startReader.id()=="lobby" && startReader.u64()==9);startReader.end();
    auto invalid=state.bytes;invalid[8]=Results;rejects([&]{decode(LobbyKind,invalid);});
    Writer ack;ack.number(34,4);ack.number(Start,1);ack.number(0,1);ack.text("stale revision");ack.text("");
    const auto rejected=std::get<Ack>(decode(AckKind,ack.bytes));assert(!rejected.success && rejected.request==34 && rejected.reason=="stale revision");
    rejects([]{decode(255,{});});rejects([]{decode(WelcomeKind,Bytes(32769));});
    Loadout full;full.deck={1,2,3,4,5,6,7,8};full.full=true;
    for(size_t i=0;i<32;++i)full.cosmetics.catalog[i]=static_cast<unsigned char>(i);
    for(size_t i=0;i<17;++i)full.cosmetics.slots[i]={static_cast<uint32_t>(100+i),static_cast<uint32_t>(1000+i)};
    auto publication=setLoadout(36,full);assert(publication.kind==65 && publication.payload.size()==206);
    Reader fullReader(publication.payload);assert(fullReader.u32()==36 && fullReader.u16()==1 && fullReader.deck()==full.deck && fullReader.selection()==full.cosmetics);fullReader.end();
    for(size_t n=0;n<168;++n)rejects([&]{auto bytes=Bytes(publication.payload.begin()+38,publication.payload.begin()+38+n);Reader partial(bytes);partial.selection();});
    auto wrong=full;wrong.cosmetics.slots[1].first=wrong.cosmetics.slots[0].first;rejects([&]{setLoadout(37,wrong);});
    wrong=full;wrong.cosmetics.slots[1].second=wrong.cosmetics.slots[0].second;rejects([&]{setLoadout(37,wrong);});
    Writer complete;complete.number(1,2);complete.number(10,8);complete.number(Open,1);complete.number(0,4);
    complete.id("lobby");complete.id("a");complete.text("");complete.text("");complete.number(1,1);
    complete.id("a");complete.deck(full.deck);complete.selection(full.cosmetics);complete.number(0,1);complete.number(0,1);
    auto extended=std::get<Lobby>(decode(LobbyLoadout,complete.bytes));assert(extended.full && extended.members[0].full && extended.members[0].cosmetics==full.cosmetics);
    rejects([&]{decode(LobbyKind,complete.bytes);});rejects([&]{decode(LobbyLoadout,state.bytes);});
    std::cout << "community v1 bounds, Unicode, identity, epoch and ACK tests passed\n";
}
