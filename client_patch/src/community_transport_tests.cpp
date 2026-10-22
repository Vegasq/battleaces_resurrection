// The actual session decoder/request tracker with an authored clock/wire sink.
#include "community_wire.hpp"
#include "loadout_publication.hpp"
#include <cassert>
#include <deque>
#include <iostream>
using ULONGLONG=unsigned long long;
static ULONGLONG now=100;
static ULONGLONG GetTickCount64(){return now;}
namespace ba_public {static void controlReset() {}}
namespace ba_client {static void controlReset() {}}
namespace ba_lan {
static ba_community_wire::Packet last{};
static std::string currentProfile="me";
static std::string authenticatedProfile(){return currentProfile;}
static void send(unsigned char kind,const std::vector<unsigned char>& bytes){last={kind,bytes};}
}
#include "community_transport.cpp"
using namespace ba_community_wire;
template<class F> void rejects(F call){bool caught=false;try{call();}catch(const std::exception&){caught=true;}assert(caught);}
static Writer greeting(const char* profile="me") {
    Writer w;w.number(1,2);w.number(3,2);w.id(profile);w.deck({1,2,3,4,5,6,7,8});return w;
}
static Writer listing(unsigned revision=1) {
    Writer w;w.number(revision,8);w.number(1,2);w.id("me");w.text("Local Player");w.number(0,1);w.number(1,1);return w;
}
int main() {
    namespace c=ba_community;
    rejects([]{c::receive(DirectoryKind,listing().bytes);});
    rejects([]{c::receive(WelcomeKind,greeting("someone_else").bytes);});
    c::receive(WelcomeKind,greeting().bytes);assert(c::online && c::welcome.profile=="me");
    rejects([]{c::receive(WelcomeKind,greeting().bytes);});
    c::receive(DirectoryKind,listing(2).bytes);assert(c::player("me")->name=="Local Player");
    rejects([]{c::receive(DirectoryKind,listing(1).bytes);});
    assert(c::alias("me")==c::alias("me") && c::alias("me")>2 && c::alias("me")!=c::alias("another"));
    const auto id=c::send(create(c::nextRequest()));assert(id==1 && c::pending.size()==1 && ba_lan::last.kind==Create);
    Writer state;state.number(1,8);state.number(Open,1);state.number(0,4);state.id("lobby");state.id("me");state.text("");state.text("");state.number(1,1);
    state.id("me");state.deck({1,2,3,4,5,6,7,8});state.number(0,1);state.number(0,1);
    c::receive(LobbyKind,state.bytes);assert(c::lobby.id=="lobby" && c::pending.size()==1);
    Writer ack;ack.number(id,4);ack.number(Create,1);ack.number(1,1);ack.text("");ack.id("lobby");
    auto wrong=ack.bytes;wrong[4]=Leave;rejects([&]{c::receive(AckKind,wrong);});assert(c::pending.size()==1);
    c::receive(AckKind,ack.bytes);assert(c::pending.empty());rejects([&]{c::receive(AckKind,ack.bytes);});
    Writer abort;abort.id("match");abort.text("worker stopped");
    c::receive(AbortedKind,abort.bytes);assert(c::abortPending && c::online && c::lobby.id=="lobby");
    c::send(leave(c::nextRequest(),"lobby"));now+=15001;rejects([]{c::checkTimeouts();});
    c::reset();assert(!c::online && !c::abortPending && c::pending.empty() && c::events.empty() && c::requestId==0);
    ba_lan::currentProfile="new_identity";
    rejects([]{c::receive(WelcomeKind,greeting().bytes);});
    c::receive(WelcomeKind,greeting("new_identity").bytes);assert(c::welcome.profile=="new_identity");
    c::reset();ba_lan::currentProfile="me";
    c::receive(WelcomeKind,greeting().bytes);c::receive(DirectoryKind,listing().bytes);
    for(unsigned i=0;i<32;++i)c::send(refresh(c::nextRequest()));
    rejects([]{c::nextRequest();});c::reset();
    c::receive(WelcomeKind,greeting().bytes);
    for(unsigned i=1;i<256;++i)c::receive(DirectoryKind,listing().bytes);
    rejects([]{c::receive(DirectoryKind,listing().bytes);});c::reset();
    ba_loadout_publication::State publication;
    publication.submit(3,SetDeck);publication.submit(5,SetLoadout);
    assert(publication.acknowledge(3,SetDeck,true) && !publication.accepted && publication.pending);
    rejects([&]{publication.acknowledge(5,SetDeck,true);});assert(publication.pending);
    assert(publication.acknowledge(5,SetLoadout,true) && publication.accepted && !publication.pending);
    assert(!publication.acknowledge(6,SetDeck,true)); // A Custom operation owns a different ACK.
    publication.submit(7,SetLoadout);assert(publication.acknowledge(7,SetLoadout,false) && !publication.accepted);
    publication.reset();assert(!publication.acknowledge(5,SetLoadout,true));publication.submit(1,SetLoadout);
    c::reset();auto modern=greeting();modern.bytes[0]=2;c::receive(WelcomeKind,modern.bytes);
    rejects([]{c::receive(DirectoryKind,listing().bytes);});
    Writer portraitListing;portraitListing.number(1,2);
    for(unsigned i=0;i<32;++i)portraitListing.number(0,1);
    auto base=listing();portraitListing.bytes.insert(portraitListing.bytes.end(),base.bytes.begin(),base.bytes.end());
    portraitListing.number(0,4);c::receive(DirectoryPortraits,portraitListing.bytes);
    assert(c::directory.portraits && c::player("me")->portrait==0);c::reset();
    c::receive(WelcomeKind,greeting().bytes);rejects([&]{c::receive(DirectoryPortraits,portraitListing.bytes);});c::reset();
    std::cout << "community presence, deferred ACK correlation, revision, timeout and queue bounds passed\n";
}
