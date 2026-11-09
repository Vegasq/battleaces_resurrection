#include "native_worker_channel.hpp"
#include <atomic>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <thread>

namespace w=ba_native_worker_wire;
namespace c=ba_native_worker_channel;
static void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
static void rejects(const std::function<void()>& action) {
    bool rejected=false;try{action();}catch(const std::exception&){rejected=true;}
    check(rejected,"expected worker rejection missing");
}
static void exact(HANDLE handle,uint8_t* bytes,size_t size,bool writing,bool fragmented=false) {
    size_t at=0;
    while(at<size) {
        DWORD count=0;const auto length=static_cast<DWORD>((std::min)(size-at,fragmented?size_t(3):size_t(1024*1024)));
        const auto okay=writing?WriteFile(handle,bytes+at,length,&count,nullptr):ReadFile(handle,bytes+at,length,&count,nullptr);
        check(okay && count,"authored fixture pipe EOF/failure");at+=count;
    }
}
static const std::wstring quotedArgument=L"a\\\"b with spaces and trailing\\\\";
static int fixture(int argc,wchar_t** argv) {
    try {
        const std::wstring mode=argv[1];
        BOOL inJob=FALSE;check(IsProcessInJob(GetCurrentProcess(),nullptr,&inJob)!=0 && inJob,"child escaped owned Job");
        check(GetConsoleWindow()==nullptr,"authored child has a visible console");
        check(GetFileType(GetStdHandle(STD_INPUT_HANDLE))==FILE_TYPE_PIPE &&
              GetFileType(GetStdHandle(STD_OUTPUT_HANDLE))==FILE_TYPE_PIPE &&
              GetFileType(GetStdHandle(STD_ERROR_HANDLE))==FILE_TYPE_DISK,"only private stdio expected");
        if(mode==L"--echo" && argc>2) {
            check(argc==6 && argv[3]==std::wstring(L"argument with spaces") && argv[4]==quotedArgument &&
                  argv[5]==std::wstring(),"worker argv quoting changed arguments");
            const auto leaked=reinterpret_cast<HANDLE>(static_cast<uintptr_t>(std::stoull(argv[2])));
            DWORD flags=0;check(!GetHandleInformation(leaked,&flags),"unlisted inheritable handle leaked to child");
        }
        const char note[]="authored hidden fixture, owned Job verified\n";DWORD count=0;
        check(WriteFile(GetStdHandle(STD_ERROR_HANDLE),note,sizeof(note)-1,&count,nullptr)!=0,"fixture stderr failed");
        uint32_t nextId=1;
        for(;;) {
            w::Bytes headerBytes(w::headerSize);exact(GetStdHandle(STD_INPUT_HANDLE),headerBytes.data(),headerBytes.size(),false);
            const auto header=w::decodeHeader(headerBytes,false);check(header.requestId==nextId++,"request ID ordering changed");
            if(mode==L"--hang")Sleep(INFINITE); // Large payload also blocks the client's synchronous WriteFile.
            w::Bytes payload(header.payloadLength);exact(GetStdHandle(STD_INPUT_HANDLE),payload.data(),payload.size(),false);
            if(mode==L"--crash")ExitProcess(69);
            if(mode==L"--oversize") {
                auto out=w::encodeHeader({static_cast<uint8_t>(header.opcode|0x80),0,header.requestId,0},true);
                const uint32_t bad=static_cast<uint32_t>(w::maxPayload+1);
                for(unsigned i=0;i<4;++i)out[12+i]=static_cast<uint8_t>(bad>>(8*i));
                exact(GetStdHandle(STD_OUTPUT_HANDLE),out.data(),out.size(),true);Sleep(INFINITE);
            }
            if(!payload.empty() && payload[0]==0x42)Sleep(250);
            w::Bytes out;
            if(!payload.empty() && payload[0]==0xee)out=w::encodeError(header.opcode,header.requestId,{'f','i','x','t','u','r','e'});
            else {
                w::Response result;
                if(header.opcode!=w::shutdownOpcode) {
                    result.result=!payload.empty() && payload[0]==0xff?17:0;
                    result.logs.push_back({5,{'o','k'}});result.data=payload;
                }else check(payload.empty(),"SHUTDOWN request must be empty");
                out=w::encodeResponse(header.opcode,header.requestId+(mode==L"--badid"?1:0),result);
            }
            exact(GetStdHandle(STD_OUTPUT_HANDLE),out.data(),out.size(),true,true);
            if(header.opcode==w::shutdownOpcode)return 0;
        }
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 77;}
}
static void wireTests() {
    const w::Bytes input{0,1,2,255};auto packet=w::encodeRequest(8,1,input);
    check(packet.size()==20 && packet[0]=='B' && packet[4]==1 && packet[5]==8,"wire request envelope differs");
    auto header=w::decodeHeader(packet.data(),16,false);
    check(header.requestId==1 && header.payloadLength==4,"little-endian header parse differs");
    for(unsigned index:{0u,4u,5u,6u,8u}) {
        auto broken=w::Bytes(packet.begin(),packet.begin()+16);
        if(index==8)broken[8]=0;else broken[index]=0xff;
        rejects([&]{w::decodeHeader(broken,false);});
    }
    rejects([]{w::encodeRequest(10,1,{});});rejects([]{w::encodeRequest(70,1,{});});
    rejects([]{w::encodeRequest(8,0,{});});rejects([]{w::decodeHeader(nullptr,16,false);});
    w::Response original{-7,{{-2,{'o','k'}},{3,{0xe2,0x82,0xac}}},input};
    auto encoded=w::encodeResponse(8,3,original);header=w::decodeHeader(encoded.data(),16,true);
    w::Bytes payload(encoded.begin()+16,encoded.end());auto decoded=w::decodeResponse(header,payload,8,3);
    check(decoded.result==-7 && decoded.data==input && decoded.logs.size()==2 && decoded.logs[0].kind==-2,
          "ordinary native status/log/data response changed");
    rejects([&]{w::decodeResponse(header,payload,7,3);});rejects([&]{w::decodeResponse(header,payload,8,4);});
    payload.pop_back();rejects([&]{w::decodeResponse(header,payload,8,3);});
    rejects([]{w::responsePayload({0,{{0,{0xc0,0x80}}},{}});});
    rejects([]{w::responsePayload({0,{{0,w::Bytes(w::maxLogBytes+1,'a')}},{}});});
    w::Response many;many.logs.resize(w::maxLogs+1);rejects([&]{w::responsePayload(many);});
    auto error=w::encodeError(8,1,{'b','a','d'});auto errorHeader=w::decodeHeader(error.data(),16,true);
    w::Bytes errorBody(error.begin()+16,error.end());bool host=false;
    try{w::decodeResponse(errorHeader,errorBody,8,1);}catch(const w::HostError&){host=true;}
    check(host,"host error flag did not produce terminal HostError");
    errorBody.push_back(0);rejects([&]{w::decodeResponse(errorHeader,errorBody,8,1);});
}
static void record(std::ofstream& out,const char* name,const c::Stats& s) {
    out<<"{\"case\":\""<<name<<"\",\"pid\":"<<s.pid<<",\"requests\":"<<s.requests
       <<",\"responses\":"<<s.responses<<",\"timeouts\":"<<s.timeouts
       <<",\"protocol_failures\":"<<s.protocolFailures<<",\"io_failures\":"<<s.ioFailures
       <<",\"host_failures\":"<<s.hostFailures<<",\"job_terminations\":"<<s.jobTerminations
       <<",\"retained_process_terminations\":"<<s.retainedProcessTerminations
       <<",\"assigned_before_resume\":"<<s.assignedBeforeResume<<",\"process_reaped\":"<<s.processReaped
       <<",\"io_joined\":"<<s.ioJoined<<",\"io_abandoned\":"<<s.ioAbandoned
       <<",\"natural_shutdown\":"<<s.naturalShutdown<<",\"exit_code\":"<<s.exitCode<<"}\n";out.flush();
}
static void cleaned(const c::Stats& s) {
    check(s.processCreated && s.assignedBeforeResume && s.resumed && s.ioStarted && s.ioJoined &&
          s.processReaped && !s.ioAbandoned,"owned worker cleanup/creation contract failed");
}
static c::Handle unassignedChild;
static DWORD unassignedPid=0;
static BOOL WINAPI observedCreateProcess(LPCWSTR application,LPWSTR command,
        LPSECURITY_ATTRIBUTES processAttributes,LPSECURITY_ATTRIBUTES threadAttributes,
        BOOL inherit,DWORD flags,LPVOID environment,LPCWSTR directory,
        LPSTARTUPINFOW startup,LPPROCESS_INFORMATION info) {
    const BOOL okay=CreateProcessW(application,command,processAttributes,threadAttributes,
                                   inherit,flags,environment,directory,startup,info);
    if(okay) {
        HANDLE retained=nullptr;
        DuplicateHandle(GetCurrentProcess(),info->hProcess,GetCurrentProcess(),&retained,
                        SYNCHRONIZE|PROCESS_QUERY_LIMITED_INFORMATION|PROCESS_TERMINATE,FALSE,0);
        unassignedChild.reset(retained);unassignedPid=info->dwProcessId;
    }
    return okay;
}
static BOOL WINAPI failJobInformation(HANDLE,JOBOBJECTINFOCLASS,LPVOID,DWORD) {
    SetLastError(ERROR_ACCESS_DENIED);return FALSE;
}
static BOOL WINAPI failJobAssignment(HANDLE,HANDLE) {
    SetLastError(ERROR_ACCESS_DENIED);return FALSE;
}
static void unassignedFailure(const std::wstring& executable,const std::filesystem::path& output,
                              std::ofstream& receipts,bool assignment) {
    unassignedChild.reset();unassignedPid=0;
    c::LaunchApi launch;launch.createProcess=&observedCreateProcess;
    if(assignment)launch.assignProcess=&failJobAssignment;
    else launch.setJobInformation=&failJobInformation;
    const auto stderrPath=output/(assignment?L"assign_failure.stderr":L"job_limits_failure.stderr");
    bool refused=false;
    try {c::Process process(executable,{L"--echo"},output.wstring(),stderrPath.wstring(),launch);}
    catch(const std::exception&){refused=true;}
    check(bool(unassignedChild),"failed launch did not retain the exact test child handle");
    const bool reaped=WaitForSingleObject(unassignedChild.get(),0)==WAIT_OBJECT_0;
    DWORD exitCode=STILL_ACTIVE;GetExitCodeProcess(unassignedChild.get(),&exitCode);
    // A RED cleanup regression still owns this duplicate handle. Reap that
    // exact suspended child before reporting failure; never search/kill by PID.
    if(!reaped) {
        TerminateProcess(unassignedChild.get(),0xe003);
        check(WaitForSingleObject(unassignedChild.get(),2000)==WAIT_OBJECT_0,"test failed to reap retained RED child");
    }
    const bool neverExecuted=std::filesystem::file_size(stderrPath)==0;
    receipts<<"{\"case\":\""<<(assignment?"assign_failure":"job_limits_failure")
            <<"\",\"pid\":"<<unassignedPid<<",\"constructor_refused\":"<<refused
            <<",\"retained_child_reaped\":"<<reaped<<",\"exit_code\":"<<exitCode
            <<",\"fixture_never_executed\":"<<neverExecuted<<",\"test_cleanup_required\":"<<!reaped<<"}\n";
    receipts.flush();unassignedChild.reset();
    check(refused && reaped && exitCode==0xe002 && neverExecuted,
          "pre-assignment failure did not terminate/reap its exact retained suspended child");
}
int wmain(int argc,wchar_t** argv) {
    if(argc>=2 && std::wstring(argv[1])!=L"--output")return fixture(argc,argv);
    try {
        check(argc==3 && std::wstring(argv[1])==L"--output","fresh private --output directory required");
        const std::filesystem::path output=std::filesystem::absolute(argv[2]);
        check(CreateDirectoryW(output.c_str(),nullptr)!=0,"authored fixture output must be fresh");
        wchar_t path[32768];const DWORD size=GetModuleFileNameW(nullptr,path,32768);
        check(size && size<32768,"test executable path unavailable");const std::wstring executable(path,size);
        wireTests();std::ofstream receipts(output/L"processes.jsonl");
        // A high-valued inheritable sentinel avoids accidental numeric reuse by
        // a small child's startup handles. Only three stdio handles may inherit.
        SECURITY_ATTRIBUTES security{sizeof(security),nullptr,TRUE};std::vector<c::Handle> sentinels;
        for(unsigned i=0;i<256;++i){sentinels.emplace_back(CreateEventW(&security,FALSE,FALSE,nullptr));check(bool(sentinels.back()),"sentinel event allocation failed");}
        const auto sentinel=std::to_wstring(reinterpret_cast<uintptr_t>(sentinels.back().get()));
        {
            c::Process process(executable,{L"--echo",sentinel,L"argument with spaces",quotedArgument,L""},output.wstring(),(output/L"echo.stderr").wstring());
            check(process.healthy(),"new channel unhealthy");
            const auto first=process.request(8,{1,2,3},2000);const auto second=process.request(8,{0xff,5},2000);
            check(first.data==w::Bytes({1,2,3}) && first.logs[0].text==w::Bytes({'o','k'}) && second.result==17,
                  "response lifetime or nonzero native result lost");
            rejects([&]{process.request(10,{},100);});
            check(process.healthy(),"local invalid request unnecessarily killed worker");
            process.shutdown(2000);cleaned(process.stats());check(process.stats().naturalShutdown && process.stats().exitCode==0,"natural shutdown failed");
            process.shutdown(2000);record(receipts,"echo_order_handles_argv",process.stats());
        }
        DWORD before=0,after=0;check(GetProcessHandleCount(GetCurrentProcess(),&before)!=0,"read parent handle count");
        // As with the existing failure-loop baseline, take this after the
        // first successful launch initializes Windows' process-launch state.
        unassignedFailure(executable,output,receipts,false);
        unassignedFailure(executable,output,receipts,true);
        check(GetProcessHandleCount(GetCurrentProcess(),&after)!=0 && after==before,
              "failed launch leaked parent handles");
        for(const auto& mode:{L"--badid",L"--oversize",L"--crash"}) {
            c::Process process(executable,{mode},output.wstring(),(output/(std::wstring(mode+2)+L".stderr")).wstring());
            rejects([&]{process.request(8,{},2000);});check(process.failed(),"bad child did not fail terminally");
            cleaned(process.stats());record(receipts,mode==std::wstring(L"--badid")?"badid":mode==std::wstring(L"--oversize")?"oversize":"crash",process.stats());
            rejects([&]{process.request(8,{},100);});
        }
        for(const bool large:{false,true}) {
            c::Process process(executable,{L"--hang"},output.wstring(),(output/(large?L"hang_write.stderr":L"hang_read.stderr")).wstring());
            const auto start=GetTickCount64();rejects([&]{process.request(8,w::Bytes(large?2*1024*1024:1,0),150);});
            check(GetTickCount64()-start<5000,"timeout blocked the caller beyond its bounded teardown");
            cleaned(process.stats());check(process.stats().timeouts==1 && process.stats().jobTerminations==1,"timeout did not terminate only its retained Job");
            record(receipts,large?"hang_write":"hang_read",process.stats());
        }
        {
            c::Process process(executable,{L"--echo"},output.wstring(),(output/L"host_error.stderr").wstring());
            rejects([&]{process.request(8,{0xee},2000);});cleaned(process.stats());
            check(process.stats().hostFailures==1,"error flag not classified as host failure");record(receipts,"host_error",process.stats());
        }
        {
            c::Process process(executable,{L"--echo"},output.wstring(),(output/L"concurrent.stderr").wstring());
            std::atomic<bool> success=false;
            std::thread caller([&]{try{success=process.request(8,{0x42},2000).data==w::Bytes{0x42};}catch(...){}});
            const auto deadline=GetTickCount64()+1000;
            while(process.stats().requests==0 && GetTickCount64()<deadline)Sleep(1);
            rejects([&]{process.request(8,{1},100);});caller.join();check(success,"first concurrent request was disturbed");
            process.shutdown(2000);cleaned(process.stats());record(receipts,"single_outstanding",process.stats());
        }
        check(GetProcessHandleCount(GetCurrentProcess(),&after)!=0 && after==before,"worker channel leaked parent handles");
        std::cout<<"native worker wire/channel: authored child scenarios PASS; handles "<<before<<" -> "<<after<<"\n";return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
