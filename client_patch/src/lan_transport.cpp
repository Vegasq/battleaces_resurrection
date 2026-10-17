#pragma once
// Experimental loopback transport. All IL2CPP work stays on Unity's main thread.
namespace ba_lan {
using ba::Obj; using ba_local::Root;
using Bytes=std::vector<unsigned char>;
static SOCKET socketValue=INVALID_SOCKET;
static bool connecting=false, welcomed=false, stopped=false, worldReady=false, running=false;
static bool winsockStarted=false,peerClosed=false,submittedFirst=false;
static ULONGLONG connectStarted=0;
static std::string failureReason;
static Bytes rx,tx,bootstrap;
static Bytes dedicatedDeck;
static bool lobbyReady=false;
static bool matchEnded=false;
static std::string dedicatedMatchId;
static size_t txPosition=0;
static std::deque<Bytes> frames;
static int nextFrame=0;
static uint64_t bootstrapHash=0;
static FILE* receipts=nullptr;
static void closeReceipts() {if(receipts){fclose(receipts);receipts=nullptr;}}
static void recordReceipt(int frame,int actions,int sim,const char* digest) {
    if(!ba::dedicated() || !ba::flag(L"-lan-audit"))return;
    if(dedicatedMatchId.empty())throw std::runtime_error("receipt match ID missing");
    if(!receipts) {
        wchar_t filename[32768],suffix[160];GetModuleFileNameW(ba::module,filename,32768);
        wchar_t* slash=wcsrchr(filename,L'\\');if(!slash)throw std::runtime_error("receipt module path");*(slash+1)=0;
        swprintf_s(suffix,L"investigation\\runtime\\dedicated-receipts-%lu-%hs.tsv",GetCurrentProcessId(),dedicatedMatchId.c_str());wcscat_s(filename,suffix);
        receipts=_wfsopen(filename,L"a",_SH_DENYNO);if(!receipts)throw std::runtime_error("receipt output unavailable");
        fprintf(receipts,"pid\tmatch\tframe\tactions\tsim\tsha256\n");
    }
    fprintf(receipts,"%lu\t%s\t%d\t%d\t%d\t%s\n",GetCurrentProcessId(),dedicatedMatchId.c_str(),frame,actions,sim,digest);fflush(receipts);
}
static void closeSocket() {
    if(socketValue!=INVALID_SOCKET){closesocket(socketValue);socketValue=INVALID_SOCKET;}
    connecting=false;
    if(winsockStarted){WSACleanup();winsockStarted=false;}
}
static void saveReceivedBootstrap(const Bytes& data) {
    wchar_t path[32768],suffix[128];GetModuleFileNameW(ba::module,path,32768);wchar_t* slash=wcsrchr(path,L'\\');if(slash)*(slash+1)=0;
    swprintf_s(suffix,L"investigation\\runtime\\lan-bootstrap-%lu.pb.gz",GetCurrentProcessId());wcscat_s(path,suffix);
    FILE* evidence=_wfsopen(path,L"wb",_SH_DENYNO);
    if(!evidence)throw std::runtime_error("client bootstrap evidence file unavailable");
    size_t written=fwrite(data.data(),1,data.size(),evidence);fclose(evidence);
    if(written!=data.size())throw std::runtime_error("client bootstrap evidence write incomplete");
    // Keep the legacy latest capture and an immutable per-match capture. A
    // second match in the same process must not erase the first bootstrap.
    if(!dedicatedMatchId.empty()) {
        wchar_t* end=wcsrchr(path,L'\\');if(end)*(end+1)=0;
        swprintf_s(suffix,L"dedicated-bootstrap-%lu-%hs.pb.gz",GetCurrentProcessId(),dedicatedMatchId.c_str());wcscat_s(path,suffix);
        evidence=_wfsopen(path,L"wb",_SH_DENYNO);
        if(!evidence)throw std::runtime_error("per-match bootstrap evidence file unavailable");
        written=fwrite(data.data(),1,data.size(),evidence);fclose(evidence);
        if(written!=data.size())throw std::runtime_error("per-match bootstrap evidence write incomplete");
    }
}
static std::array<unsigned char,32> sha(const Bytes& bytes) {
    BCRYPT_ALG_HANDLE alg=nullptr; BCRYPT_HASH_HANDLE hash=nullptr;
    std::array<unsigned char,32> result{};
    if(BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0)<0)throw std::runtime_error("SHA256 provider failed");
    if(BCryptCreateHash(alg,&hash,nullptr,0,nullptr,0,0)<0){BCryptCloseAlgorithmProvider(alg,0);throw std::runtime_error("SHA256 create failed");}
    NTSTATUS status=BCryptHashData(hash,const_cast<PUCHAR>(bytes.data()),static_cast<ULONG>(bytes.size()),0);
    if(status>=0)status=BCryptFinishHash(hash,result.data(),32,0);
    BCryptDestroyHash(hash); BCryptCloseAlgorithmProvider(alg,0);
    if(status<0)throw std::runtime_error("SHA256 failed");return result;
}
static uint32_t u32(const Bytes& b,size_t at) {
    if(at+4>b.size())throw std::runtime_error("short LAN frame");uint32_t n;memcpy(&n,b.data()+at,4);return n;
}
static void append32(Bytes& b,uint32_t n) { const unsigned char* p=reinterpret_cast<unsigned char*>(&n);b.insert(b.end(),p,p+4); }
static void send(unsigned char type,const Bytes& payload={}) {
    if(stopped || payload.size()>1024*1024 || tx.size()-txPosition>2*1024*1024)throw std::runtime_error("LAN send queue limit");
    if(txPosition){tx.erase(tx.begin(),tx.begin()+txPosition);txPosition=0;}
    append32(tx,static_cast<uint32_t>(payload.size()+1));tx.push_back(type);tx.insert(tx.end(),payload.begin(),payload.end());
}
static void fail(const char* where,const std::exception& e) {
    failureReason=e.what();
    stopped=true;running=false;closeSocket();
    ba_local::fail(where,e);
}
static Bytes arrayBytes(Obj array) {
    if(!array)throw std::runtime_error("null managed byte array");
    size_t length=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(array);
    if(length>1024*1024)throw std::runtime_error("LAN protobuf too large");
    auto p=static_cast<unsigned char*>(array)+32;return Bytes(p,p+length);
}
static Obj byteArray(const Bytes& bytes) {
    Obj array=ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(ba::find_class("System","Byte"),bytes.size());
    if(!array)throw std::runtime_error("byte array allocation failed");
    if(!bytes.empty())memcpy(static_cast<unsigned char*>(array)+32,bytes.data(),bytes.size());return array;
}
static Bytes serialize(Obj message) {
    void* args[]={message};Root bytes(ba::invoke(ba::find_class("Google.Protobuf","MessageExtensions"),nullptr,"ToByteArray",1,args));return arrayBytes(bytes.get());
}
static Obj byteString(const Bytes& bytes) {
    Root array(byteArray(bytes));int offset=0,length=static_cast<int>(bytes.size());void* args[]={array.get(),&offset,&length};
    return ba::invoke(ba::find_class("Google.Protobuf","ByteString"),nullptr,"CopyFrom",3,args);
}
static Obj parse(const char* type,const Bytes& bytes) {
    Root output(ba::make("GamePb",type)),array(byteArray(bytes));
    Obj selected=nullptr;void* iterator=nullptr;
    Obj k=ba::find_class("Google.Protobuf","MessageExtensions");
    while(Obj m=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(k,&iterator)) {
        if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(m),"MergeFrom") || ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(m)!=2)continue;
        Obj pt=ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(m,1);
        Obj pc=ba::api<Obj(*)(Obj)>("il2cpp_class_from_type")(pt);
        if(pc==ba::klass(array.get())){selected=m;break;}
    }
    if(!selected)throw std::runtime_error("MergeFrom(IMessage,byte[]) unavailable");
    void* args[]={output.get(),array.get()};ba_local::invokeMethod(selected,nullptr,args);return output.get();
}
static void connect() {
    WSADATA data{};if(WSAStartup(MAKEWORD(2,2),&data))throw std::runtime_error("WSAStartup failed");winsockStarted=true;
    connectStarted=GetTickCount64();
    socketValue=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);if(socketValue==INVALID_SOCKET)throw std::runtime_error("LAN socket failed");
    u_long nonblocking=1;if(ioctlsocket(socketValue,FIONBIO,&nonblocking))throw std::runtime_error("LAN nonblocking mode failed");
    BOOL yes=TRUE;setsockopt(socketValue,IPPROTO_TCP,TCP_NODELAY,reinterpret_cast<char*>(&yes),sizeof(yes));
    std::string endpoint=ba::argument(L"-dedicated-server=","127.0.0.1:47622");
    size_t colon=endpoint.rfind(':');if(colon==std::string::npos)throw std::runtime_error("server address must be IPv4:port");
    std::string host=endpoint.substr(0,colon);int port=atoi(endpoint.substr(colon+1).c_str());
    sockaddr_in address{};address.sin_family=AF_INET;address.sin_port=htons(static_cast<u_short>(port));
    if(port<1 || port>65535 || InetPtonA(AF_INET,host.c_str(),&address.sin_addr)!=1)throw std::runtime_error("server address must be IPv4:port");
    int r=::connect(socketValue,reinterpret_cast<sockaddr*>(&address),sizeof(address));
    if(r==SOCKET_ERROR && WSAGetLastError()!=WSAEWOULDBLOCK)throw std::runtime_error("loopback relay connection failed");
    connecting=r==SOCKET_ERROR;
    static const char* hex="e59d08c01479b27404778048d7e13546dbf3771f6b3912744c7c2bdf80c4e758";
    const int requestedSlot=ba::requestedLanSlot();
    Bytes hello;if(ba::dedicated()){hello.push_back(2);hello.push_back(0);}hello.push_back(static_cast<unsigned char>(requestedSlot));
    for(int i=0;i<32;++i){unsigned value=0;sscanf_s(hex+2*i,"%2x",&value);hello.push_back(static_cast<unsigned char>(value));}
    if(ba::dedicated()) {
        const char* sim="107bb83dc416a16492277392c50104660e34c48911345ae2e0d5afe3929a07fb";
        for(int i=0;i<32;++i){unsigned value=0;sscanf_s(sim+2*i,"%2x",&value);hello.push_back(static_cast<unsigned char>(value));}
        std::string profile=ba::argument(L"-player-id=",requestedSlot==255?"":(requestedSlot?"player1":"player0"));
        if(profile.empty())throw std::runtime_error("server-assigned seat requires a stable -player-id");
        std::string values[]={profile,ba::argument(L"-player-name=",requestedSlot==1?"Player2":"Player1"),ba::argument(L"-room=","local")};
        for(const auto& value:values){if(value.size()>128)throw std::runtime_error("dedicated hello value too long");hello.push_back(static_cast<unsigned char>(value.size()));hello.push_back(0);hello.insert(hello.end(),value.begin(),value.end());}
    }
    send(ba::dedicated()?21:1,hello);ba::log("LAN connecting to %s requested slot %d protocol=%d",endpoint.c_str(),requestedSlot,ba::dedicated()?2:1);
}
static void poll() {
    if(stopped || peerClosed)return;
    if(socketValue==INVALID_SOCKET)connect();
    if(!welcomed && GetTickCount64()-connectStarted>15000)throw std::runtime_error("match server welcome timed out");
    if(connecting) {
        fd_set writeSet,errorSet;FD_ZERO(&writeSet);FD_ZERO(&errorSet);FD_SET(socketValue,&writeSet);FD_SET(socketValue,&errorSet);timeval time{};
        if(select(0,nullptr,&writeSet,&errorSet,&time)==SOCKET_ERROR)throw std::runtime_error("LAN select failed");
        if(FD_ISSET(socketValue,&errorSet))throw std::runtime_error("configured match server unavailable");
        if(!FD_ISSET(socketValue,&writeSet))return;
        int error=0,errorSize=sizeof(error);if(getsockopt(socketValue,SOL_SOCKET,SO_ERROR,reinterpret_cast<char*>(&error),&errorSize)||error)throw std::runtime_error("LAN connection failed");connecting=false;
    }
    while(txPosition<tx.size()) {
        int n=::send(socketValue,reinterpret_cast<const char*>(tx.data()+txPosition),static_cast<int>(tx.size()-txPosition),0);
        if(n==SOCKET_ERROR){if(WSAGetLastError()==WSAEWOULDBLOCK)break;throw std::runtime_error("LAN send failed");}
        if(n<=0)throw std::runtime_error("LAN send closed");txPosition+=n;
    }
    if(txPosition==tx.size()){tx.clear();txPosition=0;}
    unsigned char buffer[65536];bool reachedEof=false;
    for(int i=0;i<16;++i) {
        int n=recv(socketValue,reinterpret_cast<char*>(buffer),sizeof(buffer),0);
        if(n==SOCKET_ERROR){if(WSAGetLastError()==WSAEWOULDBLOCK)break;throw std::runtime_error("LAN receive failed");}
        // FIN can arrive in the same poll as the final S36. Parse all preceding
        // bytes before deciding whether the close aborted an unfinished match.
        if(!n){reachedEof=true;break;}rx.insert(rx.end(),buffer,buffer+n);
        if(rx.size()>2*1024*1024)throw std::runtime_error("LAN receive queue limit");
    }
    size_t consumed=0;
    while(rx.size()-consumed>=4) {
        uint32_t length=u32(rx,consumed);if(length<1 || length>1024*1024+1)throw std::runtime_error("LAN message length invalid");
        if(rx.size()-consumed<length+4)break;
        unsigned char type=rx[consumed+4];Bytes payload(rx.begin()+consumed+5,rx.begin()+consumed+4+length);consumed+=4+length;
        if(type==11){if(payload.size()!=1 || payload[0]!=ba::lanSlot())throw std::runtime_error("LAN slot mismatch");welcomed=true;ba::log("LAN welcome slot %d",payload[0]);}
        else if(type==31){if(!ba::dedicated() || welcomed || payload.size()!=33 || payload[0]>1 || (ba::requestedLanSlot()!=255 && payload[0]!=ba::requestedLanSlot()))throw std::runtime_error("dedicated slot mismatch");ba::dedicatedAssignedSlot=payload[0];dedicatedDeck=Bytes(payload.begin()+1,payload.end());welcomed=true;ba::log("Dedicated lobby welcome slot %d; saved deck received",payload[0]);}
        else if(type==32){if(payload.size()!=32 || !dedicatedMatchId.empty())throw std::runtime_error("dedicated match ID invalid");for(unsigned char c:payload)if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')))throw std::runtime_error("dedicated match ID malformed");dedicatedMatchId=std::string(payload.begin(),payload.end());}
        else if(type==35){if(!welcomed || payload.size()!=70)throw std::runtime_error("dedicated lobby payload invalid");lobbyReady=(payload[1]&(1<<ba::lanSlot()))!=0;ba::log("Dedicated lobby connected_mask=%u ready_mask=%u revision=%u",payload[0],payload[1],u32(payload,2));}
        else if(type==37){std::string notice(payload.begin(),payload.end());ba::log("Dedicated server notice: %s",notice.c_str());}
        else if(type==36){std::string result(payload.begin(),payload.end());ba::log("Dedicated match ended: %s",result.c_str());ba_dedicated_results::receive(result);matchEnded=true;}
        else if(type==12){if(!bootstrap.empty() || payload.empty())throw std::runtime_error("duplicate or empty bootstrap");bootstrap=std::move(payload);if(ba::dedicated())saveReceivedBootstrap(bootstrap);auto h=sha(bootstrap);memcpy(&bootstrapHash,h.data(),8);ba::log("LAN canonical GameData received: %llu bytes hash-prefix=%016llx",static_cast<unsigned long long>(bootstrap.size()),bootstrapHash);}
        else if(type==13){if(!worldReady || !payload.empty() || running)throw std::runtime_error("unexpected LAN start");running=true;nextFrame=0;ba::log("LAN both players ready; synchronized start");}
        else if(type==14){if(!running || frames.size()>=8)throw std::runtime_error("unexpected LAN frame");frames.push_back(std::move(payload));}
        else if(type==255){std::string message(payload.begin(),payload.end());throw std::runtime_error(message.c_str());}
        else throw std::runtime_error("unknown LAN message type");
    }
    if(consumed)rx.erase(rx.begin(),rx.begin()+consumed);
    if(reachedEof) {
        if(!rx.empty())throw std::runtime_error("match server disconnected mid-message");
        closeSocket();peerClosed=true;
        if(!ba::dedicated() || !matchEnded)throw std::runtime_error("match server disconnected before a result");
        tx.clear();txPosition=0;
        ba::log("Dedicated result connection closed; preserving native result/Continue flow");
    }
}
static void publish(Obj encoded) {
    Root bytes(ba::call(encoded,"ToByteArray"));Bytes data=arrayBytes(bytes.get());
    wchar_t path[32768],suffix[128];GetModuleFileNameW(ba::module,path,32768);wchar_t* slash=wcsrchr(path,L'\\');if(slash)*(slash+1)=0;
    swprintf_s(suffix,L"investigation\\runtime\\lan-bootstrap-%lu.pb.gz",GetCurrentProcessId());wcscat_s(path,suffix);
    FILE* evidence=_wfsopen(path,L"wb",_SH_DENYNO);
    if(evidence){fwrite(data.data(),1,data.size(),evidence);fclose(evidence);}
    send(2,data);ba::log("LAN host published shared GameData; evidence lan-bootstrap-%lu.pb.gz",GetCurrentProcessId());
}
static void ready() { worldReady=true;auto h=sha(bootstrap);send(3,Bytes(h.begin(),h.end()));ba::log("LAN world ready; waiting for other player"); }
static void normalizeAction(Obj action) {
    Root join(ba::call(action,"get_JoinArmy"));
    if(join.get()) {
        uint32_t army=ba::get<uint32_t>(join.get(),"armyId_");
        if(army==31) {
            ba::set<uint32_t>(join.get(),"armyId_",ba::lanSlot());
            ba::log("LAN resolved JoinArmy auto-assignment 31 to fixed army%d",ba::lanSlot());
        } else if(army!=static_cast<uint32_t>(ba::lanSlot()))throw std::runtime_error("LAN JoinArmy must match fixed slot");
    }
}
static void submit(Obj server,int frame) {
    if(matchEnded)return;
    if(wcsstr(GetCommandLineW(),L"-lan-smoke"))ba_lan_smoke::enqueue(server,frame);
    Root player(ba::make("GamePb","InputActionsByPlayer"));ba::set<Obj>(player.get(),"playerHandle_",ba::read<Obj>(server,0x1a8));
    Obj output=ba::get<Obj>(player.get(),"actions_");int count=0;
    while(count<256){Root command(ba_local::dequeue(ba::read<Obj>(server,0x180)));if(!command.get())break;Root action(ba_local::toProto(command.get()));normalizeAction(action.get());ba_local::addItem(output,action.get());++count;}
    while(count<256){Root action(ba_local::dequeue(ba::read<Obj>(server,0x188)));if(!action.get())break;normalizeAction(action.get());ba_local::addItem(output,action.get());++count;}
    Bytes payload;append32(payload,frame);Bytes body=serialize(player.get());if(body.size()>65536)throw std::runtime_error("LAN input batch exceeds 64KiB");payload.insert(payload.end(),body.begin(),body.end());send(4,payload);
    if(count)ba::log("LAN submitted frame %d with %d local actions",frame,count);
}
static void tick(Obj server) {
    if(!running || stopped || !ba_local::isTarget(server))return;
    // Three queued batches absorb Unity scheduling without lowering the relay's
    // 20Hz cadence; this prototype intentionally adds roughly100ms input delay.
    if(!submittedFirst){for(int f=0;f<3;++f)submit(server,f);submittedFirst=true;}
    Obj sim=ba::read<Obj>(server,0x140);
    while(!frames.empty() && nextFrame-ba::read<int>(sim,0xa8)<4) {
        Bytes frame=std::move(frames.front());frames.pop_front();
        if(u32(frame,0)!=static_cast<uint32_t>(nextFrame))throw std::runtime_error("noncontiguous LAN frame");
        uint32_t length=u32(frame,4);if(length>frame.size()-8)throw std::runtime_error("invalid LAN player payload");
        Root message(ba::make("GamePb","InputActions"));ba::set<int>(message.get(),"gameFrame_",nextFrame);ba::set<int>(message.get(),"debugFramesPerSecond_",20);ba::set<int>(message.get(),"debugGameTimeStepMs_",50);ba::set<float>(message.get(),"debugGameSpeed_",1.0f);
        int total=0;
        for(int slot=0;slot<2;++slot) {
            Bytes body(slot==0 ? frame.begin()+8 : frame.begin()+8+length,slot==0 ? frame.begin()+8+length : frame.end());
            Root player(parse("InputActionsByPlayer",body));
            Obj handle=ba::get<Obj>(player.get(),"playerHandle_");Obj name=ba::get<Obj>(handle,"playerHandleWithName_");Obj id=ba::get<Obj>(name,"playerHandle_");
            if(ba::get<uint64_t>(id,"steamId_")!=static_cast<uint64_t>(slot+1) || !ba::get<bool>(id,"isAliased_") || ba::get<uint32_t>(handle,"aiProfileId_"))throw std::runtime_error("LAN input identity mismatch");
            int actions=ba_local::count(ba::get<Obj>(player.get(),"actions_"));total+=actions;
            if(actions)ba_local::addItem(ba::get<Obj>(message.get(),"playerInputActions_"),player.get());
        }
        bool catching=false;void* args[]={message.get(),&catching};ba::call(server,"ProcessInputActions",2,args);void* push[]={message.get()};ba::call(sim,"PushSimMessage",1,push);
        if(nextFrame%200==0 || total || (ba::dedicated() && ba::flag(L"-lan-audit"))) {
            auto hash=sha(frame);char hex[65];for(int i=0;i<32;++i)sprintf_s(hex+i*2,3,"%02x",hash[i]);
            recordReceipt(nextFrame,total,ba::read<int>(sim,0xa8),hex);
            if(nextFrame%200==0 || total)ba::log("LAN received frame %d, actions=%d, sim=%d sha256=%s match=%s",nextFrame,total,ba::read<int>(sim,0xa8),hex,dedicatedMatchId.c_str());
        }
        ++nextFrame;submit(server,nextFrame+2);
    }
    if(matchEnded && frames.empty())running=false;
}
}
