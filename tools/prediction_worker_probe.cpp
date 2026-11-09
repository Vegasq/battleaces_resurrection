// Owned native-host verifier. This driver never loads Simulation.dll/BAHeap;
// only the suspended/Job-owned Python worker owns their native ABI and threads.
#include "../client_patch/checkpoint/native_worker_channel.hpp"
#include "../client_patch/checkpoint/native_rpc_backend.hpp"
#include <array>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>

namespace w=ba_native_worker_wire;
namespace c=ba_native_worker_channel;
namespace rpc=ba_native_rpc_backend;
namespace fs=std::filesystem;
using Clock=std::chrono::steady_clock;
static void require(bool okay,const char* message){if(!okay)throw std::runtime_error(message);}
static std::string quoted(const std::string& text) {
    std::string out="\"";
    for(const auto ch:text) {
        const auto value=static_cast<unsigned char>(ch);
        if(ch=='\"' || ch=='\\'){out+='\\';out+=ch;}
        else if(value<32){const char hex[]="0123456789abcdef";out+="\\u00";out+=hex[value>>4];out+=hex[value&15];}
        else out+=ch;
    }
    out+='\"';return out;
}
static uint64_t micros(Clock::time_point start) {
    return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::microseconds>(Clock::now()-start).count());
}
static w::Bytes file(const fs::path& path,size_t maximum) {
    const auto count=fs::file_size(path);require(count>0 && count<=maximum,"probe input file length outside cap");
    std::ifstream stream(path,std::ios::binary);require(bool(stream),"probe input could not open");
    w::Bytes result(static_cast<size_t>(count));stream.read(reinterpret_cast<char*>(result.data()),static_cast<std::streamsize>(result.size()));
    require(stream.gcount()==static_cast<std::streamsize>(result.size()),"probe input truncated");return result;
}
static std::vector<w::Bytes> journal(const fs::path& path) {
    const auto raw=file(path,64u*1024u*1024u);size_t at=0;std::vector<w::Bytes> result;
    while(at<raw.size()) {
        require(result.size()<1200,"canonical journal exceeds1200frames");const auto count=w::read32(raw,at);
        require(count>0 && count<=2u*1024u*1024u,"canonical frame length outside cap");result.push_back(w::readBytes(raw,at,count));
    }
    require(result.size()==1200,"combat journal must contain exactly1200frames");return result;
}
static void save(const fs::path& path,const w::Bytes& raw) {
    std::ofstream out(path,std::ios::binary);out.write(reinterpret_cast<const char*>(raw.data()),static_cast<std::streamsize>(raw.size()));
    require(bool(out),"probe artifact write failed");
}
static void u32(std::ofstream& out,uint32_t value) {
    w::Bytes bytes;w::append32(bytes,value);out.write(reinterpret_cast<const char*>(bytes.data()),4);
}
struct Snapshots {
    std::ofstream out;
    explicit Snapshots(const fs::path& path):out(path,std::ios::binary){out.write("BASNP001",8);require(bool(out),"snapshot artifact open failed");}
    void add(uint32_t frame,const w::Bytes& bytes) {
        require(bytes.size()>=8 && bytes.size()<=16u*1024u*1024u,"native snapshot length outside cap");
        u32(out,frame);u32(out,static_cast<uint32_t>(bytes.size()));
        out.write(reinterpret_cast<const char*>(bytes.data()),static_cast<std::streamsize>(bytes.size()));
        require(bool(out),"snapshot artifact write failed");
    }
};
struct Driver {
    std::unique_ptr<c::Process> process;
    std::ofstream calls,logs;
    Clock::time_point started=Clock::now();
    std::string phase="startup";
    int frame=-1;
    int moduleToken=0;
    uint64_t ordinal=0,logCount=0;
    explicit Driver(const fs::path& output):calls(output/L"calls.tsv"),logs(output/L"logs.jsonl") {
        calls<<"ordinal\topcode\tphase\tframe\tduration_us\tresult\tdata_bytes\tlogs\n";
        require(bool(calls) && bool(logs),"probe call artifact open failed");
    }
    w::Response call(uint8_t opcode,const w::Bytes& body,DWORD limit=5000) {
        // Leave at least10s of the90s budget for terminal shutdown/reaping.
        const uint64_t elapsed=micros(started)/1000;require(elapsed<80000,"native probe request budget exceeds80seconds");
        const DWORD timeout=static_cast<DWORD>((std::min)(uint64_t(limit),80000-elapsed));
        const auto begin=Clock::now();auto out=process->request(opcode,body,timeout);const auto duration=micros(begin);
        calls<<++ordinal<<'\t'<<unsigned(opcode)<<'\t'<<phase<<'\t'<<frame<<'\t'<<duration<<'\t'<<out.result<<'\t'<<out.data.size()<<'\t'<<out.logs.size()<<'\n';
        for(const auto& log:out.logs) {
            ++logCount;const std::string text(log.text.begin(),log.text.end());
            logs<<"{\"request\":"<<ordinal<<",\"kind\":"<<log.kind<<",\"text\":"<<quoted(text)<<"}\n";
        }
        return out;
    }
    void plain(uint8_t opcode,const w::Bytes& body,DWORD timeout=5000) {
        const auto out=call(opcode,body,timeout);require(out.result==0 && out.data.empty(),"native plain API returned nonzero/data");
    }
};
static w::Bytes worldBody(uint64_t world){w::Bytes body;w::append64(body,world);return body;}
static w::Bytes pair(const w::Response& response,bool signedSize=false) {
    require(response.result==0,"native buffer Make/Size returned nonzero");size_t at=0;const auto size=w::read32(response.data,at);
    if(signedSize)require(static_cast<int32_t>(size)>=0,"native signed buffer size negative");
    const auto result=static_cast<int32_t>(w::read32(response.data,at));const auto length=w::read32(response.data,at);
    require(result==0 && size<=16u*1024u*1024u && size==length && length==response.data.size()-at,"atomic native buffer pair differs");
    return w::readBytes(response.data,at,length);
}
static w::Bytes frameSnapshot(Driver& driver,uint64_t world,uint32_t viewer) {
    auto body=worldBody(world);w::append32(body,viewer);w::append32(body,0);return pair(driver.call(9,body));
}
static bool __cdecl relay(void* context,uint8_t opcode,const w::Bytes& bytes,w::Response& response) {
    try{response=static_cast<Driver*>(context)->call(opcode,bytes);return true;}catch(...){return false;}
}
static uint32_t metadata(Driver& driver,uint64_t world,const fs::path& output) {
    driver.phase="metadata";
    auto body=worldBody(world);w::append32(body,0);save(output/L"map.bin",pair(driver.call(15,body),true));
    body=worldBody(world);w::append32(body,0);w::append32(body,0);
    const auto players=driver.call(13,body);require(players.result==0,"native players Size returned nonzero");size_t at=0;
    const auto size=w::read32(players.data,at);w::read32(players.data,at);const auto get=w::read32(players.data,at);const auto length=w::read32(players.data,at);
    require(get==0 && size<=16u*1024u*1024u && size==length && length==players.data.size()-at,"atomic native players pair differs");
    save(output/L"players.bin",w::readBytes(players.data,at,length));
    for(const uint32_t registry:{1u,3u}) {
        body=worldBody(world);w::append32(body,registry);w::append32(body,0);
        save(output/(registry==1?L"labels1.bin":L"labels3.bin"),pair(driver.call(11,body)));
    }
    body=worldBody(world);w::append32(body,0);const auto countResponse=driver.call(23,body);at=0;
    require(countResponse.result==0 && countResponse.data.size()==4,"native system count failed");const auto count=w::read32(countResponse.data,at);
    require(count>0 && count<=2048,"native system count outside cap");
    body=worldBody(world);w::append32(body,count);body.insert(body.end(),size_t(count)*128,0xa5);
    const auto attributes=driver.call(24,body);require(attributes.result==0 && attributes.data.size()==size_t(count)*128,"system128byte record array differs");
    require(std::any_of(attributes.data.begin(),attributes.data.end(),[](uint8_t value){return value!=0xa5;}),"system record output remained seed-only");
    save(output/L"system-records.bin",attributes.data);return count;
}
static void debugChecks(Driver& driver,uint64_t world) {
    driver.phase="debug_stub";
    for(const uint32_t seed:{0u,17u,0xffffffffu}) {
        auto body=worldBody(world);w::append32(body,seed);const auto count=driver.call(18,body);size_t at=0;
        require(count.result==8 && count.data.size()==4 && w::read32(count.data,at)==seed,"debug count no-write seed contract differs");
        body=worldBody(world);w::append32(body,seed);w::append32(body,0);const auto sized=driver.call(19,body);at=0;
        require(sized.result==8 && sized.data.size()==12 && w::read32(sized.data,at)==seed && w::read32(sized.data,at)==8 && w::read32(sized.data,at)==0,
                "debug Size no-write seed contract differs");
    }
    require(driver.call(21,worldBody(world)).result==8,"debug Clear stub status differs");
    auto body=worldBody(world);w::append32(body,0);require(driver.call(22,body).result==8,"debug Active stub status differs");
    require(rpc::initialize(&driver.moduleToken,&relay,&driver)==0,"isolated RPC backend setup failed");
    std::array<uint8_t,32> sentinel;sentinel.fill(0xa7);const auto before=driver.ordinal;
    require(rpc::BARpcSimGetDebugDrawCommandBuffer(world,sentinel.data(),0)==8 &&
            rpc::BARpcSimGetDebugDrawCommandBuffer(world,sentinel.data(),0)==8 && driver.ordinal==before &&
            std::all_of(sentinel.begin(),sentinel.end(),[](uint8_t value){return value==0xa7;}),
            "client-local debug Get sent wire request or wrote sentinel bytes");
}
static uint64_t create(Driver& driver,const w::Bytes& bootstrap) {
    const auto result=driver.call(5,bootstrap,30000);require(result.result==0 && result.data.size()==8,"native world creation failed");size_t at=0;
    const auto world=w::read64(result.data,at);require(world!=0,"native world ID is zero");return world;
}
static void replay(Driver& driver,uint64_t world,const std::vector<w::Bytes>& inputs,size_t count,
                   const fs::path& output,const std::string& phase,bool allies,
                   const fs::path* metadataOutput=nullptr,uint32_t* systems=nullptr) {
    driver.phase=phase;Snapshots main(output/L"frames31.bin");
    std::unique_ptr<Snapshots> alliance0,alliance1;
    if(allies){alliance0=std::make_unique<Snapshots>(output/L"frames0.bin");alliance1=std::make_unique<Snapshots>(output/L"frames1.bin");}
    for(size_t frame=0;frame<count;++frame) {
        driver.frame=static_cast<int>(frame);auto body=worldBody(world);body.insert(body.end(),inputs[frame].begin(),inputs[frame].end());driver.plain(7,body);
        body=worldBody(world);w::append32(body,50);w::append32(body,0x12345678);const auto stepped=driver.call(8,body);
        require(stepped.result==0 && stepped.data.size()==4,"native Step result/time output differs");
        main.add(static_cast<uint32_t>(frame),frameSnapshot(driver,world,31));
        if(allies){alliance0->add(static_cast<uint32_t>(frame),frameSnapshot(driver,world,0));alliance1->add(static_cast<uint32_t>(frame),frameSnapshot(driver,world,1));}
        if(frame==0 && metadataOutput && systems) {
            *systems=metadata(driver,world,*metadataOutput);debugChecks(driver,world);driver.phase=phase;
        }
    }
    driver.frame=-1;
}
int wmain(int argc,wchar_t** argv) {
    if(argc==2 && std::wstring(argv[1])==L"--help") {
        std::cout<<"prediction_worker_probe PythonExe moduleRoot originalDLL heapHelper cooperative dataDir combatBaselineDir freshOutput\n";return 0;
    }
    if(argc!=9){std::cerr<<"Expected8arguments; use --help\n";return 2;}
    const fs::path output=fs::absolute(argv[8]);std::unique_ptr<Driver> driver;bool passed=false,createdOwnOutput=false;std::string error;
    uint32_t systems=0;uint64_t first=0,second=0;const auto begin=Clock::now();
    try {
        require(!fs::exists(output),"probe output must be fresh");
        require(fs::create_directory(output),"could not create fresh probe output");createdOwnOutput=true;
        fs::create_directories(fs::absolute(argv[6]));
        const fs::path baseline=fs::absolute(argv[7]);const auto bootstrap=file(baseline/L"shared/bootstrap.pb",w::maxPayload);
        const auto inputs=journal(baseline/L"shared/canonical-frames.bin");driver=std::make_unique<Driver>(output);
        const std::wstring trusted=L"import runpy,sys;sys.path.insert(0,sys.argv[1]);sys.argv=[sys.argv[2],*sys.argv[3:]];runpy.run_module(sys.argv[0],run_name='__main__')";
        const std::vector<std::wstring> arguments={L"-I",L"-S",L"-B",L"-u",L"-c",trusted,fs::absolute(argv[2]).wstring(),L"client_patch.prediction_worker",
            L"--original-dll",fs::absolute(argv[3]).wstring(),L"--heap-helper",fs::absolute(argv[4]).wstring(),
            L"--cooperative",fs::absolute(argv[5]).wstring(),L"--data-dir",fs::absolute(argv[6]).wstring()};
        driver->process=std::make_unique<c::Process>(fs::absolute(argv[1]).wstring(),arguments,output.wstring(),(output/L"worker.stderr").wstring());
        driver->plain(3,{1},30000);w::Bytes flags;w::append32(flags,0);driver->plain(4,flags);driver->plain(1,{0});
        first=create(*driver,bootstrap);
        fs::create_directory(output/L"combat");replay(*driver,first,inputs,1200,output/L"combat","combat",true,&output,&systems);
        driver->phase="roundtrip_benchmark";
        for(unsigned i=0;i<500;++i) {
            auto body=worldBody(first);w::append32(body,0);const auto response=driver->call(23,body);size_t at=0;
            require(response.result==0 && response.data.size()==4 && w::read32(response.data,at)==systems,"system count benchmark changed");
        }
        driver->phase="rematch";driver->plain(6,worldBody(first));second=create(*driver,bootstrap);require(second!=first,"rematch reused stale world key");
        fs::create_directory(output/L"rematch");replay(*driver,second,inputs,240,output/L"rematch","rematch",false);
        driver->plain(6,worldBody(second));driver->plain(2,{});driver->process->shutdown(2000);
        const auto stats=driver->process->stats();require(stats.naturalShutdown && stats.processReaped && stats.ioJoined &&
            !stats.ioAbandoned && stats.exitCode==0 && stats.jobTerminations==0,"native host did not naturally exit/reap");passed=true;
    }catch(const std::exception& problem){error=problem.what();}
    if(driver && driver->process && driver->process->healthy()) {
        try{driver->process->shutdown(2000);}catch(const std::exception& problem){if(error.empty())error=problem.what();passed=false;}
    }
    if(createdOwnOutput) {
        std::ofstream report(output/L"driver.json");c::Stats stats;
        if(driver && driver->process)stats=driver->process->stats();
        report<<"{\"passed\":"<<(passed?"true":"false")<<",\"error\":"<<quoted(error)<<",\"elapsed_us\":"<<micros(begin)
              <<",\"combat_frames\":"<<(passed?1200:0)<<",\"rematch_frames\":"<<(passed?240:0)<<",\"system_count\":"<<systems
              <<",\"first_world\":"<<first<<",\"rematch_world\":"<<second<<",\"calls\":"<<(driver?driver->ordinal:0)
              <<",\"logs\":"<<(driver?driver->logCount:0)<<",\"pid\":"<<stats.pid<<",\"exit_code\":"<<stats.exitCode
              <<",\"job_assigned_before_resume\":"<<(stats.assignedBeforeResume?"true":"false")
              <<",\"process_reaped\":"<<(stats.processReaped?"true":"false")<<",\"io_joined\":"<<(stats.ioJoined?"true":"false")
              <<",\"natural_shutdown\":"<<(stats.naturalShutdown?"true":"false")<<",\"job_terminations\":"<<stats.jobTerminations
              <<",\"timeouts\":"<<stats.timeouts<<",\"io_abandoned\":"<<stats.ioAbandoned<<"}\n";
    }
    std::cout<<"{\"passed\":"<<(passed?"true":"false")<<",\"error\":"<<quoted(error)<<",\"elapsed_us\":"<<micros(begin)<<"}\n";
    return passed?0:1;
}
