// Optional authored native probe: no game installation or game-derived bytes.
#include "secure_bridge.hpp"
#include <cstdio>
#include <cstdlib>

int main(int argc,char** argv) {
    if(argc!=2)return 2;
    try {
        char* end=nullptr;const unsigned long long handle=_strtoui64(argv[1],&end,10);
        if(!end || *end || !handle)return 3;
        ba_secure::Channel channel;channel.attach(static_cast<uintptr_t>(handle));
        for(const char* expected:{"test","more"}) {
            channel.begin();
            if(channel.send(expected,4)!=4)throw std::runtime_error("probe send backpressure");
            char received[4]={};size_t count=0;const ULONGLONG deadline=GetTickCount64()+5000;
            while(count<4 && GetTickCount64()<deadline) {
                int n=channel.receive(received+count,static_cast<int>(4-count));
                if(n==0)throw std::runtime_error("probe early EOF");
                if(n>0)count+=n;else Sleep(1);
            }
            if(count!=4 || memcmp(received,expected,4))throw std::runtime_error("probe reply mismatch");
            channel.end();
        }
        puts("Native private bridge completed two authenticated sessions");
        return 0;
    }catch(const std::exception& error){fprintf(stderr,"%s\n",error.what());return 1;}
}
