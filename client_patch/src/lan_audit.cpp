#pragma once
// Include after ba helpers. Hooks ONLY the two SimThread CALL instructions listed
// in lan-audit-hooks.json; leave Simulation.ReadSimFrame entry unmodified.
// This samples selected observable state, NOT a complete simulation checksum.
// Canonical field offsets/strides are from ORIGINAL generated FlatBuffer getters:
// ../network/audit-getters.asm. No native pointers/padding enter canonical hashes.
#include <algorithm>
#include <vector>
#include <map>

namespace ba_audit {
using ba::Obj;
using MakeFrame = int(*)(uint64_t,uint32_t,uint32_t*);
using GetFrame = int(*)(uint64_t,void*);
static constexpr uint32_t MaxFrameBytes = 16u*1024u*1024u;
static constexpr unsigned Interval = 20;
struct MatchContext {std::string id;unsigned ordinal=0;};
static SRWLOCK contextLock=SRWLOCK_INIT;
static MatchContext context;
struct ContextGuard {
    bool exclusive;
    explicit ContextGuard(bool write):exclusive(write){if(write)AcquireSRWLockExclusive(&contextLock);else AcquireSRWLockShared(&contextLock);}
    ~ContextGuard(){if(exclusive)ReleaseSRWLockExclusive(&contextLock);else ReleaseSRWLockShared(&contextLock);}
};
static void beginMatch(const std::string& id) {
    if(id.size()!=32)throw std::runtime_error("audit match ID invalid");
    // Called on Unity's thread before ProcessJoinedGame starts a sim worker.
    ContextGuard guard(true);
    if(context.id!=id){context.id=id;++context.ordinal;}
}
static MatchContext currentMatch() {
    ContextGuard guard(false);return context;
}

struct Hash {
    uint64_t value=14695981039346656037ull;
    void bytes(const void* source,size_t count) {
        const unsigned char* p=static_cast<const unsigned char*>(source);
        for(size_t i=0;i<count;++i) { value^=p[i];value*=1099511628211ull; }
    }
    void u32(uint32_t x) { unsigned char p[4]={static_cast<unsigned char>(x),static_cast<unsigned char>(x>>8),static_cast<unsigned char>(x>>16),static_cast<unsigned char>(x>>24)};bytes(p,4); }
};
struct Buffer {
    const std::vector<unsigned char>& bytes;
    void bounds(size_t p,size_t n) const {
        if(p>bytes.size() || n>bytes.size()-p)throw std::runtime_error("audit FlatBuffer bounds");
    }
    template<class T> T read(size_t p) const { bounds(p,sizeof(T));T x;memcpy(&x,bytes.data()+p,sizeof(T));return x; }
    size_t field(size_t table,unsigned index) const {
        if(!table)return 0;
        const int64_t v=static_cast<int64_t>(table)-read<int32_t>(table);
        if(v<0)throw std::runtime_error("audit negative vtable");
        const size_t at=static_cast<size_t>(v), slot=4u+2u*index;
        if(slot+2>read<uint16_t>(at))return 0;
        const uint16_t offset=read<uint16_t>(at+slot);
        if(!offset)return 0;
        bounds(table+offset,1);return table+offset;
    }
    size_t indirect(size_t p) const { if(!p)return 0;const size_t result=p+read<uint32_t>(p);bounds(result,4);return result; }
    size_t table(size_t parent,unsigned index) const { return indirect(field(parent,index)); }
    size_t vector(size_t parent,unsigned index,uint32_t& count,size_t stride) const {
        size_t p=indirect(field(parent,index));count=p?read<uint32_t>(p):0;
        if(!p)return 0;
        if(count>1000000u)throw std::runtime_error("audit unreasonable vector length");
        bounds(p+4,static_cast<size_t>(count)*stride);return p+4;
    }
};
struct Record { uint32_t id;size_t index; };
static void practiceAIView(Obj process,int simulationFrame) {
    // Observe the AI's already-copied main-thread buffer. TryReadSimView is a
    // consuming operation and must not be called by an additional diagnostic.
    // DLL AI skips managed Update, so UtilizedSize/FrameNumber are stale here.
    if(simulationFrame<10 || ba::get<int>(process,"_joiningStatus")!=4)return;
    Obj temporary=ba::get<Obj>(process,"_simFrameTempBuffers");if(!temporary)return;
    Obj allocator=ba::get<Obj>(temporary,"_byteAllocator");if(!allocator)return;
    const auto data=ba::read<const unsigned char*>(allocator,0x28);
    const int length=ba::read<int>(allocator,0x20);
    if(!data || !length)return;
    if(length<8 || static_cast<uint32_t>(length)>MaxFrameBytes)throw std::runtime_error("practice AI copied frame bounds");
    std::vector<unsigned char> snapshot(data,data+length);Buffer buffer{snapshot};
    const size_t root=buffer.read<uint32_t>(0);buffer.bounds(root,4);
    const size_t frameField=buffer.field(root,0),allianceField=buffer.field(root,1);
    ba::log("Practice AI copied view: sim=%d frame=%u alliance=%u bytes=%d nonConsuming=1",simulationFrame,
        frameField?buffer.read<uint32_t>(frameField):0,allianceField?buffer.read<uint32_t>(allianceField):0,length);
    // Decode existing observable components only. These are the same verified
    // field layouts used by summarize; no additional simulation/outbox read.
    struct Entity {uint32_t army=UINT32_MAX,type=0;int32_t health=0;std::array<uint32_t,3> position{};bool located=false;};
    std::map<uint32_t,Entity> entities;
    for(unsigned field:{2u,3u,5u,7u}) {
        const size_t component=buffer.table(root,field);const unsigned words=field==7?3:1;
        uint32_t idsCount=0,valuesCount=0;
        const size_t ids=buffer.vector(component,0,idsCount,4),values=buffer.vector(component,1,valuesCount,words*4);
        if(idsCount!=valuesCount || idsCount>32768)throw std::runtime_error("practice AI entity component bounds");
        for(uint32_t i=0;i<idsCount;++i) {
            auto& entity=entities[buffer.read<uint32_t>(ids+4*i)];const size_t value=values+4*words*i;
            if(field==2)entity.army=buffer.read<uint32_t>(value);
            else if(field==3)entity.type=buffer.read<uint32_t>(value);
            // Native generated vector1 is MaxHealth; vector2 is CurrentDamage.
            // Keep the historical log field name for evidence-reader compatibility.
            else if(field==5)entity.health=buffer.read<int32_t>(value);
            else {entity.located=true;for(unsigned word=0;word<3;++word)entity.position[word]=buffer.read<uint32_t>(value+4*word);}
        }
    }
    unsigned count=0;
    for(const auto& row:entities) {
        const auto& entity=row.second;if(entity.army!=1 || !entity.type || !entity.located)continue;
        if(++count>128)break;
        ba::log("Practice AI entity: frame=%u army=1 id=%u type=%u position=(%u,%u,%u) health=%d",
            frameField?buffer.read<uint32_t>(frameField):0,row.first,entity.type,
            entity.position[0],entity.position[1],entity.position[2],entity.health);
    }
}
static uint32_t component(Hash& hash,const Buffer& buffer,size_t root,unsigned rootField,unsigned valueWords,bool health=false) {
    hash.u32(rootField);
    const size_t t=buffer.table(root,rootField);
    uint32_t idsCount=0,valuesCount=0,damageCount=0;
    const size_t ids=buffer.vector(t,0,idsCount,4);
    const size_t values=buffer.vector(t,1,valuesCount,4u*valueWords);
    const size_t damage=health ? buffer.vector(t,2,damageCount,4) : 0;
    if(idsCount!=valuesCount || (health && idsCount!=damageCount))throw std::runtime_error("audit component vector lengths disagree");
    std::vector<Record> order;order.reserve(idsCount);
    for(uint32_t i=0;i<idsCount;++i)order.push_back({buffer.read<uint32_t>(ids+4u*i),i});
    std::sort(order.begin(),order.end(),[](const Record& a,const Record& b){ return a.id<b.id; });
    hash.u32(idsCount);
    for(size_t i=0;i<order.size();++i) {
        const Record& row=order[i];
        if(i && row.id==order[i-1].id)throw std::runtime_error("audit duplicate component ID");
        hash.u32(row.id);
        for(unsigned word=0;word<valueWords;++word)
            hash.u32(buffer.read<uint32_t>(values+(row.index*valueWords+word)*4u));
        if(health)hash.u32(buffer.read<uint32_t>(damage+row.index*4u));
    }
    return idsCount;
}
struct Sample { uint32_t frame,armyCount,typeCount,healthCount,positionCount,resourceCount;uint64_t canonical,raw; };
static Sample summarize(const std::vector<unsigned char>& bytes,uint32_t viewer) {
    Buffer b{bytes};const size_t root=b.read<uint32_t>(0);b.bounds(root,4);
    const size_t frameField=b.field(root,0);
    Sample s{};s.frame=frameField?b.read<uint32_t>(frameField):0;
    Hash h;h.u32(1);h.u32(viewer);h.u32(s.frame);
    s.armyCount=component(h,b,root,2,1);
    s.typeCount=component(h,b,root,3,1);
    s.healthCount=component(h,b,root,5,1,true);
    s.positionCount=component(h,b,root,7,3);
    s.resourceCount=component(h,b,root,21,8);
    s.canonical=h.value;Hash raw;raw.bytes(bytes.data(),bytes.size());s.raw=raw.value;
    return s;
}
struct State {
    bool disabled=false,announced=false,practiceHumanCoreObserved=false;
    uint64_t world=0;
    int lastSampledPreviousFrame=-2147483647;
    MakeFrame make=nullptr;
    GetFrame get=nullptr;
    FILE* output=nullptr;
    FILE* resources=nullptr;
    FILE* legacyOutput=nullptr;
    FILE* legacyResources=nullptr;
    MatchContext match;
    std::vector<unsigned char> buffer;
    void close() {
        for(FILE* f:{output,resources,legacyOutput,legacyResources})if(f)fclose(f);
        output=nullptr;resources=nullptr;legacyOutput=nullptr;legacyResources=nullptr;practiceHumanCoreObserved=false;
    }
    ~State() {close();}
};
static thread_local State state;
static bool practiceHumanCoreHealth(const std::vector<unsigned char>& bytes,uint32_t frame) {
    Buffer buffer{bytes};const size_t root=buffer.read<uint32_t>(0);
    struct Entity {uint32_t army=UINT32_MAX,type=0;int32_t maxHealth=0;};
    std::map<uint32_t,Entity> entities;
    for(unsigned field:{2u,3u,5u}) {
        const size_t table=buffer.table(root,field);uint32_t idsCount=0,valuesCount=0;
        const size_t ids=buffer.vector(table,0,idsCount,4),values=buffer.vector(table,1,valuesCount,4);
        if(idsCount!=valuesCount || idsCount>32768)throw std::runtime_error("practice human health component bounds");
        for(uint32_t i=0;i<idsCount;++i) {
            auto& entity=entities[buffer.read<uint32_t>(ids+4*i)];
            if(field==2)entity.army=buffer.read<uint32_t>(values+4*i);
            else if(field==3)entity.type=buffer.read<uint32_t>(values+4*i);
            else entity.maxHealth=buffer.read<int32_t>(values+4*i);
        }
    }
    for(const auto& record:entities)if(record.second.army==0 && record.second.type==3 && record.second.maxHealth>0) {
        ba::log("Practice human core MaxHealth: frame=%u value=%d viewer=0",frame,record.second.maxHealth);return true;
    }
    return false;
}
static void path(wchar_t* target,size_t count,const wchar_t* suffix) {
    GetModuleFileNameW(ba::module,target,static_cast<DWORD>(count));
    wchar_t* slash=wcsrchr(target,L'\\');if(!slash)throw std::runtime_error("audit module path");*(slash+1)=0;
    wcscat_s(target,count,L"investigation\\runtime\\");wcscat_s(target,count,suffix);
}
static void resourceRows(FILE* output,const std::vector<unsigned char>& bytes,uint32_t frame,uint32_t viewer) {
    Buffer b{bytes};const size_t root=b.read<uint32_t>(0),t=b.table(root,21);
    uint32_t count=0,valueCount=0;
    const size_t ids=b.vector(t,0,count,4),values=b.vector(t,1,valueCount,32);
    if(count!=valueCount)throw std::runtime_error("audit resource vector lengths disagree");
    std::vector<Record> order;order.reserve(count);
    for(uint32_t i=0;i<count;++i)order.push_back({b.read<uint32_t>(ids+4u*i),i});
    std::sort(order.begin(),order.end(),[](const Record& a,const Record& c){return a.id<c.id;});
    // Original generated accessors confirm offsets0,4,...28, all signed int32.
    // ../network/army-resource-getters.asm retains each accessor's instruction.
    for(const Record& row:order) {
        fprintf(output,"%lu\t%lu\t%u\t%u\t%u",GetCurrentProcessId(),GetCurrentThreadId(),frame,viewer,row.id);
        for(unsigned word=0;word<8;++word)fprintf(output,"\t%d",b.read<int32_t>(values+row.index*32u+word*4u));
        fputc('\n',output);
    }
}
static void capture(Obj simulation,uint32_t originalViewer) {
    State& s=state;
    if(!ba::flag(L"-lan-audit"))return;
    const MatchContext match=currentMatch();
    if(s.match.id!=match.id) {
        s.close();s.match=match;s.disabled=false;s.announced=false;s.world=0;
        s.lastSampledPreviousFrame=-2147483647;
    }
    if(s.disabled)return;
    const uint64_t world=ba::read<uint64_t>(simulation,0x1a8);
    if(!world)return;
    const int previousFrame=ba::read<int>(simulation,0xa8);
    if(s.world!=world || previousFrame<s.lastSampledPreviousFrame) {s.world=world;s.lastSampledPreviousFrame=-2147483647;}
    if(s.lastSampledPreviousFrame!=-2147483647 && static_cast<int64_t>(previousFrame)-s.lastSampledPreviousFrame<Interval)return;
    if(!s.make || !s.get) {
        HMODULE nativeModule=GetModuleHandleW(L"Simulation.dll");
        if(!nativeModule)throw std::runtime_error("audit Simulation.dll unavailable");
        s.make=reinterpret_cast<MakeFrame>(GetProcAddress(nativeModule,"SimMakeSimFrame"));
        s.get=reinterpret_cast<GetFrame>(GetProcAddress(nativeModule,"SimGetSimFrameBuffer"));
        if(!s.make || !s.get)throw std::runtime_error("audit native exports unavailable");
    }
    if(!s.output) {
        wchar_t suffix[160],filename[32768];
        if(s.match.id.empty())swprintf_s(suffix,L"lan-audit-%lu.tsv",GetCurrentProcessId());
        else swprintf_s(suffix,L"lan-audit-%lu-%hs.tsv",GetCurrentProcessId(),s.match.id.c_str());
        path(filename,32768,suffix);
        s.output=_wfsopen(filename,L"a",_SH_DENYNO);
        if(!s.output)throw std::runtime_error("audit output unavailable");
        if(s.match.ordinal==1 && !s.match.id.empty()) {
            swprintf_s(suffix,L"lan-audit-%lu.tsv",GetCurrentProcessId());path(filename,32768,suffix);
            s.legacyOutput=_wfsopen(filename,L"a",_SH_DENYNO);
            if(!s.legacyOutput)throw std::runtime_error("legacy audit output unavailable");
        }
        for(FILE* f:{s.output,s.legacyOutput})if(f)fprintf(f,"pid\tthread\tframe\tviewer\tcanonical_fnv1a64\traw_fnv1a64\tbytes\tarmy_entities\ttype_entities\thealth_entities\tposition_entities\tresource_armies\n");
    }
    if(!s.resources) {
        wchar_t suffix[160],filename[32768];
        if(s.match.id.empty())swprintf_s(suffix,L"lan-resources-%lu.tsv",GetCurrentProcessId());
        else swprintf_s(suffix,L"lan-resources-%lu-%hs.tsv",GetCurrentProcessId(),s.match.id.c_str());
        path(filename,32768,suffix);
        s.resources=_wfsopen(filename,L"a",_SH_DENYNO);
        if(!s.resources)throw std::runtime_error("audit resources output unavailable");
        if(s.match.ordinal==1 && !s.match.id.empty()) {
            swprintf_s(suffix,L"lan-resources-%lu.tsv",GetCurrentProcessId());path(filename,32768,suffix);
            s.legacyResources=_wfsopen(filename,L"a",_SH_DENYNO);
            if(!s.legacyResources)throw std::runtime_error("legacy resources output unavailable");
        }
        for(FILE* f:{s.resources,s.legacyResources})if(f)fprintf(f,"pid\tthread\tframe\tviewer\tarmy\tprimary\tsecondary\tcurrent_supply\tmax_supply\tprimary_gathered\tsecondary_gathered\tprimary_lost\tsecondary_lost\n");
    }
    // The normal ReadSimFrame has already copied its data into managed scratch.
    // Multiple views are an existing supported worker path (recordSimFrames).
    // Restore native output's original perspective before returning as well.
    struct Restore { State& s;uint64_t world;uint32_t viewer;~Restore(){uint32_t ignored=0;if(s.make)s.make(world,viewer,&ignored);} } restore{s,world,originalViewer};
    for(uint32_t viewer=0;viewer<2;++viewer) {
        uint32_t size=0;
        const int result=s.make(world,viewer,&size);
        if(result!=0 || size<8 || size>MaxFrameBytes)throw std::runtime_error("audit SimMakeSimFrame failed/size out of bounds");
        s.buffer.resize(size);
        if(s.get(world,s.buffer.data())!=0)throw std::runtime_error("audit SimGetSimFrameBuffer failed");
        const Sample sample=summarize(s.buffer,viewer);
        if(viewer==0 && ba::offlinePractice() && ba::flag(L"-practice-ai-smoke") && !s.practiceHumanCoreObserved)
            s.practiceHumanCoreObserved=practiceHumanCoreHealth(s.buffer,sample.frame);
        for(FILE* f:{s.output,s.legacyOutput})if(f)fprintf(f,"%lu\t%lu\t%u\t%u\t%016llx\t%016llx\t%u\t%u\t%u\t%u\t%u\t%u\n",GetCurrentProcessId(),GetCurrentThreadId(),sample.frame,viewer,
            static_cast<unsigned long long>(sample.canonical),static_cast<unsigned long long>(sample.raw),size,sample.armyCount,sample.typeCount,sample.healthCount,sample.positionCount,sample.resourceCount);
        resourceRows(s.resources,s.buffer,sample.frame,viewer);
        if(s.legacyResources)resourceRows(s.legacyResources,s.buffer,sample.frame,viewer);
        if(!s.announced && wcsstr(GetCommandLineW(),L"-lan-audit-dump")) {
            wchar_t suffix[160],filename[32768];
            if(s.match.id.empty())swprintf_s(suffix,L"lan-audit-%lu-view%u-frame%u.bin",GetCurrentProcessId(),viewer,sample.frame);
            else swprintf_s(suffix,L"lan-audit-%lu-%hs-view%u-frame%u.bin",GetCurrentProcessId(),s.match.id.c_str(),viewer,sample.frame);
            path(filename,32768,suffix);
            FILE* f=_wfsopen(filename,L"wb",_SH_DENYNO);if(f){fwrite(s.buffer.data(),1,s.buffer.size(),f);fclose(f);}
        }
    }
    for(FILE* f:{s.output,s.resources,s.legacyOutput,s.legacyResources})if(f)fflush(f);
    s.lastSampledPreviousFrame=previousFrame;
    if(!s.announced) {s.announced=true;ba::log("LAN observable-state audit active on simulation worker %lu; fixed views0/1 every20frames; pid=%lu match=%s ordinal=%u",GetCurrentThreadId(),GetCurrentProcessId(),s.match.id.c_str(),s.match.ordinal);}
}
}

extern "C" __declspec(dllexport) void OfflineAuditReadSimFrame(void* simulation,void* scratch,uint32_t viewer,void* methodInfo) {
    // Original is NOT entry-hooked: this is only a wrapper for two direct CALLs.
    ba::native<void(*)(void*,void*,uint32_t,void*)>(0x3e68090)(simulation,scratch,viewer,methodInfo);
    try { ba_audit::capture(simulation,viewer); }
    catch(const std::exception& e) {ba_audit::state.disabled=true;ba::log("LAN audit disabled: %s",e.what());}
}
