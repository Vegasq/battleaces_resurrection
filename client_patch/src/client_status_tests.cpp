#include "client_status.hpp"
#include <cassert>
#include <vector>
using Bytes=std::vector<unsigned char>;
static Bytes target(const std::string& host,uint16_t port,const std::string& peer="") {
    Bytes out={1,static_cast<unsigned char>(host.size())};out.insert(out.end(),host.begin(),host.end());
    out.push_back(static_cast<unsigned char>(port));out.push_back(static_cast<unsigned char>(port>>8));
    out.push_back(static_cast<unsigned char>(peer.size()));out.insert(out.end(),peer.begin(),peer.end());return out;
}
static ba_client_status::Target read(const Bytes& data){return ba_client_status::decode(data.data(),data.size());}
int main() {
    assert(read(target("",0)).label()=="Not configured");
    assert(read(target("ba.sendsignal.cc",47623,"165.227.125.73")).label()=="ba.sendsignal.cc:47623 (165.227.125.73)");
    assert(read(target("127.0.0.1",47623,"127.0.0.1")).label()=="127.0.0.1:47623");
    assert(read(target("::1",47623,"::1")).label()=="[::1]:47623");
    for(const auto& bad:std::vector<Bytes>{{}, {1,0,1,0,0}, {1,0,0,0,0,0}, target("<b>bad</b>",1),
            target("server",0), target("server",1,"bad@ip"), target(std::string(254,'a'),1)}) {
        bool failed=false;try{read(bad);}catch(const std::runtime_error&){failed=true;}assert(failed);
    }
    assert(ba_client_status::safeBuild("0.5.0-rc1 (build abcdef0)")=="0.5.0-rc1 (build abcdef0)");
    assert(ba_client_status::safeBuild("<b>build</b>")=="Development (build unknown)");
    assert(ba_client_status::safeConfigured("bad\nendpoint")=="Not configured");
    assert(ba_client_status::safeConfigured("ba.sendsignal.cc:47623")=="ba.sendsignal.cc:47623");
}
