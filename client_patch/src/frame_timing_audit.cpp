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
static bool bufferReserved=false,captureStopped=false,captureFailed=false,streamCreated=false;
static size_t bufferedRowsSeen=0;
static unsigned captureWorld=0,completedWorlds=0;
static int lastArrival=-1;
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
static unsigned captureWorldLimit() {
    static const unsigned value=[]() -> unsigned {
        const auto text=ba::argument(L"-frame-timing-worlds=","");
        if(text.empty())return 1;
        if(captureTarget() && (text=="1" || text=="2"))return text=="2"?2u:1u;
        ba::log("Frame timing worlds ignored: requires1..2 and buffered -frame-timing-frames");
        return 1;
    }();
    return value;
}
static bool enabled() {
    if(captureStopped || captureFailed)return false;
    if(captureTarget()) {
        // Reserve before the first active-world row. This mode performs no
        // trace file operations until its measured prefix has finished.
        if(!bufferReserved){
            bufferedRows.reserve((std::min)(initialBufferedRows,maximumBufferedRows-bufferedRowsSeen));
            bufferReserved=true;
        }
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
        // The opt-in second world keeps the first completed segment byte for
        // byte. No trace file is opened during either measured prefix.
        stream=_wfsopen(path,streamCreated?L"a":L"w",_SH_DENYNO);
        if(!stream)return false;
        if(!streamCreated)fprintf(stream,"ms\tevent\tupdate\tframe\tsim\tpresented\tqueued\tqpc_us\n");
        streamCreated=true;
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
    if(reason || failed)captureFailed=true;
    else if(captureWorldLimit()==2) {
        if(captureWorld==completedWorlds+1)completedWorlds=captureWorld;
        else {captureFailed=true;reason="target reached without a new authoritative frame0";}
    }
    if(reason || failed)ba::log("Frame timing capture stopped: rows=%zu target=%u reason=%s writeFailed=%d; capture incomplete",
        captured,captureTarget(),reason?reason:"trace output failure",failed?1:0);
}
static void rejectBuffered(const char* reason) {
    if(captureFailed)return;
    captureFailed=true;
    if(!captureStopped && !bufferedRows.empty())dumpBuffered(reason);
    else {
        captureStopped=true;
        ba::log("Frame timing capture rejected: world=%u completed=%u reason=%s; capture incomplete",
            captureWorld,completedWorlds,reason);
    }
}
static bool acceptArrival(int frame) {
    // Only the explicit two-world buffered diagnostic owns this state. The
    // default single-world and ordinary live tracing keep their old behavior.
    if(captureFailed)return false;
    if(frame==0) {
        if(!captureWorld) {captureWorld=1;lastArrival=0;return true;}
        if(!captureStopped || completedWorlds!=captureWorld) {
            rejectBuffered("new frame0 before prior target completed");return false;
        }
        if(captureWorld>=captureWorldLimit()) {
            rejectBuffered("world limit exceeded");return false;
        }
        if(!bufferedRows.empty() || bufferedRowsSeen>=maximumBufferedRows) {
            rejectBuffered("cumulative row limit or unfinished prior buffer");return false;
        }
        ++captureWorld;lastArrival=0;captureStopped=false;bufferReserved=false;
        return true; // Rearm BEFORE write() checks captureStopped for frame0.
    }
    if(captureStopped)return false;
    if(!captureWorld || frame!=lastArrival+1) {
        rejectBuffered("noncontiguous or missing initial authoritative frame0");return false;
    }
    lastArrival=frame;return true;
}
static void write(const char* event,int frame,int sim,int presented,size_t queued) {
    if(!enabled())return;
    const unsigned target=captureTarget();
    if(!target && !openStream())return;
    TimingRow row{};
    row.haveQpc=timestampMicros(row.qpcUs);row.ms=GetTickCount64();row.update=update;
    row.event=event;row.queued=queued;row.frame=frame;row.sim=sim;row.presented=presented;
    if(target) {
        if(bufferedRowsSeen>=maximumBufferedRows) {
            dumpBuffered("row limit exceeded");return;
        }
        if(bufferedRows.size()==bufferedRows.capacity())
            bufferedRows.reserve((std::min)(maximumBufferedRows,bufferedRows.capacity()*2));
        bufferedRows.push_back(row);
        ++bufferedRowsSeen; // Cumulative across both opted-in worlds, not reset.
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
static void arrival(int frame,size_t queued) {
    if(captureTarget() && captureWorldLimit()==2 && !acceptArrival(frame))return;
    write("arrival",frame,-1,-1,queued);
}
static void applied(int frame,ba::Obj sim,size_t queued) {
    write("apply",frame,ba::read<int>(sim,0xa8),ba::read<int>(sim,0xac),queued);
}
static void published(ba::Obj sim,size_t queued) {
    if(!enabled() || !sim)return;
    const int presented=ba::read<int>(sim,0xac);
    // online_presentation calls this only after the original RVA0x3e65c70
    // returned AND ac changed, following pure pacing bookkeeping. write()
    // samples QPC here; this is not a first-observed counter-change proxy.
    // a8 can finish later view queries after ac; do not manufacture sim>=ac.
    write("publication",presented,ba::read<int>(sim,0xa8),presented,queued);
}
static void flush() {
    if(captureTarget()){dumpBuffered("explicit flush before target");return;}
    if(stream)fflush(stream);
}
}
