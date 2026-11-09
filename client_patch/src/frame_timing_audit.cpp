// Shared monotonic timestamp plus opt-in Unity/pipeline timing. Ordinary
// clients use the clock but never open the trace or sample presentation state.
#include <algorithm>
#include <cstdint>
#include <algorithm>
#include <limits>
#include <type_traits>
#include <vector>
namespace ba_frame_timing {
static FILE* stream=nullptr;
static uint64_t update=0,rows=0;
struct TimingRow {
    uint64_t ms,qpcUs,update;
    const char* event; // Every caller supplies a process-lifetime string literal.
    size_t queued;
    int frame,sim,presented;
    bool haveQpc;
};
static_assert(std::is_trivial<TimingRow>::value && std::is_standard_layout<TimingRow>::value,
              "Buffered timing rows must remain plain data");
static constexpr size_t maximumBufferedRows=1000000,initialBufferedRows=131072;
static std::vector<TimingRow> bufferedRows;
static bool bufferReserved=false,captureStopped=false;
static unsigned captureTarget() {
    static const unsigned value=[]() -> unsigned {
        const auto text=ba::argument(L"-frame-timing-frames=","");
        if(text.empty())return 0;
        unsigned target=0;
        if(text.size()<=4 && text.find_first_not_of("0123456789")==std::string::npos) {
            for(char c:text)target=target*10+static_cast<unsigned>(c-'0');
            if(target>=600 && target<=1800)return target;
        }
        ba::log("Frame timing capture ignored: -frame-timing-frames requires600..1800");
        return 0;
    }();
    return value;
}
static bool enabled() {
    if(captureStopped)return false;
    if(captureTarget()) {
        // Reserve before the first active-world row. This mode performs no
        // trace file operations until its measured prefix has finished.
        if(!bufferReserved){bufferedRows.reserve(initialBufferedRows);bufferReserved=true;}
        return true;
    }
    static const bool live=ba::flag(L"-lan-audit") || ba::flag(L"-frame-timing");
    return live;
}
static bool timestampMicros(uint64_t& output) {
    static const uint64_t frequency=[]() -> uint64_t {
        LARGE_INTEGER value{};
        return QueryPerformanceFrequency(&value) && value.QuadPart>0?
            static_cast<uint64_t>(value.QuadPart):0;
    }();
    LARGE_INTEGER counter{};
    if(!frequency || !QueryPerformanceCounter(&counter) || counter.QuadPart<0)return false;
    const auto ticks=static_cast<uint64_t>(counter.QuadPart);
    const uint64_t seconds=ticks/frequency,remainder=ticks%frequency;
    constexpr uint64_t scale=1000000;
    const auto maximum=(std::numeric_limits<uint64_t>::max)();
    // Divide first: multiplying the absolute counter by1e6 can overflow even
    // when the resulting timestamp fits. Keep the remainder product bounded too.
    if(seconds>maximum/scale || remainder>maximum/scale)return false;
    const uint64_t whole=seconds*scale,fraction=remainder*scale/frequency;
    if(fraction>maximum-whole)return false;
    output=whole+fraction;return true;
}
static bool openStream() {
    if(!stream) {
        wchar_t path[32768],suffix[128];
        if(!GetModuleFileNameW(ba::module,path,32768))return false;
        wchar_t* slash=wcsrchr(path,L'\\');if(!slash)return false;*(slash+1)=0;
        swprintf_s(suffix,L"investigation\\runtime\\frame-timing-%lu.tsv",GetCurrentProcessId());
        wcscat_s(path,suffix);
        stream=_wfsopen(path,L"w",_SH_DENYNO);
        if(!stream)return false;
        fprintf(stream,"ms\tevent\tupdate\tframe\tsim\tpresented\tqueued\tqpc_us\n");
    }
    return true;
}
static void writeRow(const TimingRow& row) {
    fprintf(stream,"%llu\t%s\t%llu\t%d\t%d\t%d\t%zu\t",
        static_cast<unsigned long long>(row.ms),row.event,
        static_cast<unsigned long long>(row.update),row.frame,row.sim,row.presented,row.queued);
    if(row.haveQpc)fprintf(stream,"%llu",static_cast<unsigned long long>(row.qpcUs));
    fputc('\n',stream);
}
static void dumpBuffered(const char* reason=nullptr) {
    if(captureStopped || bufferedRows.empty())return;
    captureStopped=true;
    const size_t captured=bufferedRows.size();
    bool failed=!openStream();
    if(stream) {
        for(const auto& row:bufferedRows)writeRow(row);
        failed=ferror(stream)!=0;
        if(fclose(stream))failed=true;
        stream=nullptr;
    }
    std::vector<TimingRow>().swap(bufferedRows);
    if(reason || failed)ba::log("Frame timing capture stopped: rows=%zu target=%u reason=%s writeFailed=%d; capture incomplete",
        captured,captureTarget(),reason?reason:"trace output failure",failed?1:0);
}
static void write(const char* event,int frame,int sim,int presented,size_t queued) {
    if(!enabled())return;
    const unsigned target=captureTarget();
    if(!target && !openStream())return;
    TimingRow row{};
    row.haveQpc=timestampMicros(row.qpcUs);row.ms=GetTickCount64();row.update=update;
    row.event=event;row.queued=queued;row.frame=frame;row.sim=sim;row.presented=presented;
    if(target) {
        if(bufferedRows.size()>=maximumBufferedRows) {
            dumpBuffered("row limit exceeded");return;
        }
        if(bufferedRows.size()==bufferedRows.capacity())
            bufferedRows.reserve((std::min)(maximumBufferedRows,bufferedRows.capacity()*2));
        bufferedRows.push_back(row);
        if(!strcmp(event,"view") && presented>=static_cast<int>(target)+2)dumpBuffered();
        return;
    }
    writeRow(row);
    if(++rows%32==0)fflush(stream);
}
static void observe(ba::Obj front) {
    if(!enabled())return;
    ++update;
    if(!front)return;
    ba::Obj server=ba::read<ba::Obj>(front,0xd8);
    if(!server)return;
    ba::Obj sim=ba::read<ba::Obj>(server,0x140);
    if(!sim || !ba::read<bool>(sim,0x1a0))return;
    write("view",-1,ba::read<int>(sim,0xa8),ba::read<int>(sim,0xac),0);
}
static void arrival(int frame,size_t queued) {write("arrival",frame,-1,-1,queued);}
static void applied(int frame,ba::Obj sim,size_t queued) {
    write("apply",frame,ba::read<int>(sim,0xa8),ba::read<int>(sim,0xac),queued);
}
static void published(ba::Obj sim,size_t queued) {
    if(!enabled() || !sim)return;
    const int presented=ba::read<int>(sim,0xac);
    write("publication",presented,ba::read<int>(sim,0xa8),presented,queued);
}
static void flush() {
    if(captureTarget()){dumpBuffered("explicit flush before target");return;}
    if(stream)fflush(stream);
}
}
