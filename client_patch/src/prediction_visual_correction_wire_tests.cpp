#include "prediction_visual_correction_wire.hpp"
#include <cassert>
#include <iostream>
#include <limits>
namespace wire=ba_native_worker_wire;
namespace correction=ba_prediction_correction_wire;
static void set32(wire::Bytes& bytes,size_t at,uint32_t value) {
    assert(at+4<=bytes.size());for(unsigned i=0;i<4;++i)bytes[at+i]=static_cast<uint8_t>(value>>(i*8));
}
static wire::Bytes packet() {
    // Explicit Python <IQiiQI> + <IIIQfff> layout, not the decoder's structs.
    wire::Bytes out;wire::append32(out,1);wire::append64(out,0x1020304050607080ull);
    wire::append32(out,7);wire::append32(out,6);wire::append64(out,9);wire::append32(out,1);
    wire::append32(out,74);wire::append32(out,1);wire::append32(out,0);wire::append64(out,75);
    wire::append32(out,0x3fa00000);wire::append32(out,0xbf000000);wire::append32(out,0x00000000);
    return out;
}
static void refused(const wire::Bytes& bytes,uint64_t world=0x1020304050607080ull,int32_t frame=7) {
    bool failed=false;try{correction::decode(bytes,world,frame);}catch(const wire::ProtocolError&){failed=true;}
    assert(failed);
}
int main() {
    auto bytes=packet();const auto frame=correction::decode(bytes,0x1020304050607080ull,7);
    assert(frame.head==6 && frame.revision==9 && frame.deltas.size()==1);
    const auto& value=frame.deltas[0];
    assert(value.entity==74 && value.type==1 && value.army==0 && value.incarnation==75);
    assert(value.x==1.25f && value.y==-.5f && value.z==0);
    const auto envelope=wire::encodeResponse(correction::Opcode,3,{0,{},bytes});
    assert(envelope[5]==(77|128));
    for(size_t length=0;length<bytes.size();++length)refused(wire::Bytes(bytes.begin(),bytes.begin()+length));
    auto bad=bytes;bad.push_back(0);refused(bad);
    refused(bytes,1,7);refused(bytes,0x1020304050607080ull,8);refused(bytes,0x1020304050607080ull,-1);
    for(const auto change:std::vector<std::pair<size_t,uint32_t>>{{0,2},{16,5},{20,0},{28,65537},{44,0},{52,0x7f800000},{56,0x7fc00001}}) {
        bad=bytes;set32(bad,change.first,change.second);refused(bad);
    }
    // Whole distinct entity records must be ordered and have distinct tokens.
    bad=bytes;bad.insert(bad.end(),bytes.begin()+32,bytes.end());set32(bad,28,2);refused(bad);
    set32(bad,64,75);refused(bad); // Ordered IDs cannot reuse incarnation75.
    set32(bad,76,76);assert(correction::decode(bad,0x1020304050607080ull,7).deltas.size()==2);
    bad=bytes;bad.resize(32);set32(bad,28,0);set32(bad,16,0xffffffff);
    assert(correction::decode(bad,0x1020304050607080ull,7).deltas.empty());
    set32(bad,16,6);refused(bad); // Empty records never claim a native correction head.
    std::cout<<"Presentation correction wire checks passed\n";
}
