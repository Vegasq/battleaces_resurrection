// Diagnostic-only Unity/pipeline timing. -lan-audit is used by owned match
// probes; ordinary clients never open this file or sample presentation state.
namespace ba_frame_timing {
static FILE* stream=nullptr;
static uint64_t update=0,rows=0;
static bool enabled() {static const bool value=ba::flag(L"-lan-audit");return value;}
static void write(const char* event,int frame,int sim,int presented,size_t queued) {
    if(!enabled())return;
    if(!stream) {
        wchar_t path[32768],suffix[128];
        if(!GetModuleFileNameW(ba::module,path,32768))return;
        wchar_t* slash=wcsrchr(path,L'\\');if(!slash)return;*(slash+1)=0;
        swprintf_s(suffix,L"investigation\\runtime\\frame-timing-%lu.tsv",GetCurrentProcessId());
        wcscat_s(path,suffix);
        stream=_wfsopen(path,L"w",_SH_DENYNO);
        if(!stream)return;
        fprintf(stream,"ms\tevent\tupdate\tframe\tsim\tpresented\tqueued\n");
    }
    fprintf(stream,"%llu\t%s\t%llu\t%d\t%d\t%d\t%zu\n",
        static_cast<unsigned long long>(GetTickCount64()),event,
        static_cast<unsigned long long>(update),frame,sim,presented,queued);
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
static void flush() {if(stream)fflush(stream);}
}
