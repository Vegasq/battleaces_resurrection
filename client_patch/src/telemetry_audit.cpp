#pragma once
#include "telemetry_sampling.hpp"
#include <memory>
// Read-only, opt-in observation of the supported UnityPlayer native layout.
// Include after lan_transport.cpp for its local SHA-256 utility. Field sampling
// invokes no Unity/telemetry API. A SEPARATE explicit owned menu diagnostic below
// calls checked replacements and a reviewed data-free native Create/Destroy
// cycle;no identity query,collector or flush is invoked.
namespace ba_telemetry_audit {
using Bytes=std::vector<unsigned char>;
static constexpr size_t fileSize=30902464;
static constexpr uint32_t imageSize=0x1e58000,peOffset=0x148,timeStamp=0x66a03c5f;
static constexpr uint32_t originalChecksum=0x1d80675;
static constexpr const char* originalHash="ac144d56d53f07904d52ed27a1539de90bc3290038fe52d73d2f6b268c85d6bc";
struct Signature {size_t rva,offset;const char* original;const char* candidate;unsigned group;};
// Recognition only. These signatures NEVER patch a file or process. Candidate
// recognition is not approval or runtime qualification of those patch groups.
static const Signature signatures[]={
    {0xc90c2a,0xc9002a,"0fb64210488bf2884101488bd984c00f","31c09090",0},
    {0x80366f,0x802a6f,"0f85a40500004c39b424200800000f84","e9a505000090",0},
    {0xc93d10,0xc93110,"488bc44889480855488da868ffffff48","c3",0},
    {0xc8c5f3,0xc8b9f3,"0f85b80000004c8bcbc64308014c8d","e9b900000090",1},
    {0xc66c20,0xc66020,"40574883ec7080b9c015000000488b","c3",1},
    {0xc2f570,0xc2e970,"40534883ec2080b9c015000000488b","c3",1},
    {0xc333da,0xc327da,"41c6865116000001e8c93f03004c89","41c6865116000000",1},
    {0x2078b0,0x206cb0,"84c9488b0d6f72b0010f95c0388151","31c9",1},
    {0xc2f3fc,0xc2e7fc,"c687c315000001e878340000488bc7","c687c315000000",1},
    {0x207a60,0x206e60,"84c9488b0dbf70b0010f95c03881c3","31c9",1},
    {0xc381d0,0xc375d0,"44894c24204c894424184889542410","31c0c3",1},
    {0xc37400,0xc36800,"48895c2408488974241848897c2420","b802000000c3",1},
    {0xc33440,0xc32840,"4883ec288b81c815000085c0488b15","31c0c3",1},
    {0x1fd3a0,0x1fc7a0,"4055535657415441554157488d6c24f0","31c0c3",1},
    {0x1fda50,0x1fce50,"40534881ec50060000488b1dc810b101","31c0c3",1},
    {0xc392c0,0xc386c0,"48895c24205556574154415541564157","31c0c3",1},
    {0xc2e240,0xc2d640,"405356574883ec60488bfac744245449","31c0c3",1},
    {0xc40840,0xc3fc40,"885424105553564154488dac2448f8ffff4881ecb80800004c8be1b00133c989","83b99014000002750ac7819014000000000000c3",1},
    {0x20c560,0x20b960,"4055535657415441554157488d6c24f0","31c0c3",1},
    {0xc2f790,0xc2eb90,"48895c24204c89442418488954241055","e95b090000",1},
    {0xc2fc09,0xc2f009,"e802bddcffeb07488d059193d50049c7","e902000000",1},
    {0xc3016b,0xc2f56b,"4c8d3d66a9df00c744246c490000004c","e9b3000000",1},
    {0xc30273,0xc2f673,"4438adc80000000f857a020000488bb5","e904050000",1},
    {0xc3a5d0,0xc399d0,"48895c240848896c2410488974241848","c3",1},
    {0xc39d14,0xc39114,"e827440100488d8fb8040000ff150a07","9090909090",1},
    {0xc3a2a5,0xc396a5,"e8963e0100488d8bb8040000ff157901","9090909090",1},
    {0xc41f0c,0xc4130c,"e82fc20000488d8bb8040000ff151285","9090909090",1},
    {0xc32468,0xc31868,"e8a394dcffeb07488d05326bd50049c7","e902000000",1},
    {0x2048a0,0x203ca0,"4055534157488d6c24b94881ec900000","c3",1},
    {0x204cb0,0x2040b0,"4055534157488d6c24b94881ec900000","c3",1},
    {0xc30838,0xc2fc38,"e843ae52ff4088bb8801000033c0c683","9090909090",1},
    {0x208350,0x207750,"40555341544157488dac24a8feffff48","b802000000c3",1},
    {0x208840,0x207c40,"4883ec284c8bc1488d54243033c9ff15","b802000000c3",1},
    {0x20afa0,0x20a3a0,"4055535657415441554157488d6c24e0","b802000000c3",1},
    {0x207ad0,0x206ed0,"488bc4554155488da8d8feffff4881ec","b802000000c3",1},
    {0x208890,0x207c90,"40555741544157488d6c24c14881ec98","b802000000c3",1},
    {0x208c50,0x208050,"4055535741544157488d6c24c94881ec","b802000000c3",1},
    {0x209000,0x208400,"40555357415441554157488d6c24e848","b802000000c3",1},
    {0x2096c0,0x208ac0,"4055535657415441554157488d6c24f0","b802000000c3",1},
    {0x209d80,0x209180,"488bc4554154488da8d8feffff4881ec","b802000000c3",1},
    {0x20a610,0x209a10,"488bc44c894820554155488da8c8feff","b802000000c3",1},
    {0x20b690,0x20aa90,"488bc4554157488da848ffffff4881ec","b802000000c3",1},
    {0x20bea0,0x20b2a0,"4055535657415441554157488d6c24f0","b802000000c3",1},
    {0x205084,0x204484,"488bfac7451b01000000488bd9c645f7","31ff90",1},
    {0x205550,0x204950,"40555356574157488d6c24c04881ec40","31c0c3",1},
    {0x205cd0,0x2050d0,"44894424185553574157488d6c24c148","31c0c3",1},
    {0x206110,0x205510,"44894424185553574157488d6c24c148","31c0c3",1},
    {0x206550,0x205950,"4c894424185553574157488d6c24c148","31c0c3",1},
    {0x206a30,0x205e30,"4c894424185553574157488d6c24c148","31c0c3",1},
    {0x206f10,0x206310,"40555356574157488d6c24c94881ecd0","31c0c3",1},
    {0x207340,0x206740,"f20f115424185553574157488d6c24c1","31c0c3",1},
    {0x202050,0x201450,"40555357415441554157488d6c24d848","b802000000c3",1},
    {0x2026f0,0x201af0,"4055535657415441554157488dac2460","b802000000c3",1},
    {0x203050,0x202450,"4055535657415441554157488d6c24f0","b802000000c3",1},
    {0x203710,0x202b10,"488bc45553415441554157488d688848","b802000000c3",1},
    {0x203df0,0x2031f0,"488bc45553415441554157488da818ff","b802000000c3",1},
    {0xd84ec6,0xd842c6,"0f857d0100004c8bcbc603014c8d0587","e97e01000090",2},
    {0xd84e3e,0xd8423e,"c740080001000048897810c6401901e8","c7400800000000",2},
    {0x292110,0x291510,"84c9488b0d8fcba7010f95c24883c108","31c9",2},
    {0xc33210,0xc32610,"4883ec5848833d0cb90d01000f851002","",3},
    {0xc8c510,0xc8b910,"4883ec48803d4f260801000f859e0100","",3},
    {0xd84de0,0xd841e0,"4883ec4848833dbc9ef800000f855c02","",3},
    {0xc307c0,0xc2fbc0,"48895c2408574883ec20418079200141","",3},
    {0x205070,0x204470,"4055535741544157488d6c24c94881ec","",3},
    {0x205430,0x204830,"4885c90f840f010000574883ec30488b","",3},
};
static uintptr_t unity=0;
static bool checked=false,disabled=false,startupLogged=false,quitAttempted=false,completeRecipe15=false;
static unsigned snapshots=0;
static ba_telemetry_sampling::Schedule schedule;
static DWORD auditThread=0;
static bool requested() {
    static const bool enabled=ba::flag(L"-telemetry-audit");
    return enabled;
}
static bool copy(uintptr_t address,void* destination,size_t size) {
    if(!address || size>UINTPTR_MAX-address)return false;
    SIZE_T copied=0;
    return ReadProcessMemory(GetCurrentProcess(),reinterpret_cast<const void*>(address),destination,size,&copied) && copied==size;
}
template<class T> static bool read(uintptr_t base,size_t offset,T& out) {
    return base && offset<=UINTPTR_MAX-base && copy(base+offset,&out,sizeof(out));
}
static Bytes hex(const char* text) {
    Bytes out;const size_t length=strlen(text);
    if(length%2)throw std::runtime_error("audit signature length");
    auto digit=[](char c)->unsigned {if(c>='0'&&c<='9')return c-'0';if(c>='a'&&c<='f')return c-'a'+10;throw std::runtime_error("audit signature digit");};
    for(size_t i=0;i<length;i+=2)out.push_back(static_cast<unsigned char>((digit(text[i])<<4)|digit(text[i+1])));
    return out;
}
static std::string digest(const Bytes& bytes) {
    auto hash=ba_lan::sha(bytes);char text[65];
    for(size_t i=0;i<hash.size();++i)sprintf_s(text+2*i,sizeof(text)-2*i,"%02x",hash[i]);
    return text;
}
static bool verifyModule() {
    if(checked)return !disabled;
    checked=true;disabled=true;
    try {
        unity=reinterpret_cast<uintptr_t>(GetModuleHandleW(L"UnityPlayer.dll"));
        IMAGE_DOS_HEADER dos{};IMAGE_NT_HEADERS64 nt{};
        if(!read(unity,0,dos) || dos.e_magic!=IMAGE_DOS_SIGNATURE || dos.e_lfanew!=peOffset ||
           !read(unity,peOffset,nt) || nt.Signature!=IMAGE_NT_SIGNATURE ||
           nt.FileHeader.Machine!=IMAGE_FILE_MACHINE_AMD64 || nt.FileHeader.NumberOfSections!=8 ||
           nt.FileHeader.TimeDateStamp!=timeStamp || nt.OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR64_MAGIC ||
           nt.OptionalHeader.SizeOfImage!=imageSize)throw std::runtime_error("unsupported loaded UnityPlayer PE identity");
        wchar_t path[32768];DWORD n=GetModuleFileNameW(reinterpret_cast<HMODULE>(unity),path,32768);
        if(!n || n>=32768)throw std::runtime_error("UnityPlayer file path unavailable");
        struct File {HANDLE value=INVALID_HANDLE_VALUE;~File(){if(value!=INVALID_HANDLE_VALUE)CloseHandle(value);}} file;
        file.value=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
        LARGE_INTEGER size{};
        if(file.value==INVALID_HANDLE_VALUE || !GetFileSizeEx(file.value,&size) || size.QuadPart!=fileSize)
            throw std::runtime_error("UnityPlayer file unavailable or wrong length");
        Bytes bytes(fileSize);DWORD received=0;
        if(!ReadFile(file.value,bytes.data(),static_cast<DWORD>(bytes.size()),&received,nullptr) || received!=bytes.size())
            throw std::runtime_error("UnityPlayer file read incomplete");
        const std::string actualHash=digest(bytes);unsigned groups[4]={};
        for(const auto& signature:signatures) {
            Bytes original=hex(signature.original),replacement=hex(signature.candidate),candidate=original;
            if(replacement.size()>original.size() || signature.offset>bytes.size()-original.size() ||
               signature.rva>imageSize-original.size())throw std::runtime_error("audit signature bounds");
            if(!replacement.empty())memcpy(candidate.data(),replacement.data(),replacement.size());
            const auto* onDisk=bytes.data()+signature.offset;
            const bool pristine=memcmp(onDisk,original.data(),original.size())==0;
            if(!pristine && memcmp(onDisk,candidate.data(),candidate.size())!=0)
                throw std::runtime_error("unrecognized UnityPlayer instruction signature");
            Bytes loaded(original.size());
            if(!copy(unity+signature.rva,loaded.data(),loaded.size()) || memcmp(loaded.data(),onDisk,loaded.size()))
                throw std::runtime_error("loaded UnityPlayer signature disagrees with its file");
            if(!pristine)++groups[signature.group];
            // Restore only this LOCAL hash buffer, never the engine or its file.
            memcpy(bytes.data()+signature.offset,original.data(),original.size());
        }
        memcpy(bytes.data()+peOffset+24+64,&originalChecksum,sizeof(originalChecksum));
        if(digest(bytes)!=originalHash)throw std::runtime_error("unsupported UnityPlayer normalized SHA256");
        completeRecipe15=groups[0]==3 && groups[1]==53 && groups[2]==3;
        disabled=false;
        ba::log("Telemetry audit build verified: UnityPlayer sha256=%s normalized=%s crashSignatures=%u/3 coreCandidateSignatures=%u/53 performanceCandidateSignatures=%u/3; READ ONLY, no qualification claim",
            actualHash.c_str(),originalHash,groups[0],groups[1],groups[2]);
    } catch(const std::exception& e) {ba::log("Telemetry audit disabled: %s; no object reads attempted",e.what());}
    return !disabled;
}
static void sample(const char* stage) {
    if(disabled || snapshots>=ba_telemetry_sampling::maxSnapshots || !requested() || !verifyModule())return;
    if(!auditThread)auditThread=GetCurrentThreadId();
    if(auditThread!=GetCurrentThreadId()) {disabled=true;ba::log("Telemetry audit disabled: thread changed");return;}
    const unsigned sequence=++snapshots;
    uintptr_t main=0,session=0,performance=0,hook=0,perfHook=0;
    if(!read(unity,0x1d0eb28,main) || !read(unity,0x1d0eb40,session) || !read(unity,0x1d0eca8,performance) ||
       !read(unity,0x1ce04a0,hook) || !read(unity,0x1ce0588,perfHook)) {
        disabled=true;ba::log("Telemetry audit disabled: singleton/global read failed");return;
    }
    ba::log("Telemetry audit %u/17 stage=%s retained main=%d session=%d performance=%d callbackHooks main=%d performance=%d",
        sequence,stage,main?1:0,session?1:0,performance?1:0,hook?1:0,perfHook?1:0);
    if(main) {
        uintptr_t vtable=0,worker=0;uint32_t state=0,init=0,archive=0;
        unsigned char baseStarted=0,derivedStarted=0,enabled=0,deviceStats=0;
        uintptr_t queue[3]={},confirm[3]={};
        const bool valid=read(main,0,vtable) && vtable==unity+0x1a2c538 &&
            read(main,8,state) && read(main,0xe10,init) && read(main,0x480,archive) && read(main,0x4e0,worker) &&
            read(main,0x15c0,baseStarted) && read(main,0x1650,derivedStarted) &&
            read(main,0x1651,enabled) && read(main,0x15c3,deviceStats) &&
            read(main,0x1458,queue) && read(main,0x1458,confirm);
        int queued=-1;
        if(valid && !memcmp(queue,confirm,sizeof(queue)) && queue[0]<=queue[1] && queue[1]<=queue[2] &&
           (queue[1]-queue[0])%sizeof(uintptr_t)==0 && (queue[1]-queue[0])/sizeof(uintptr_t)<=50)
            queued=static_cast<int>((queue[1]-queue[0])/sizeof(uintptr_t));
        if(valid)ba::log("Telemetry audit %u main: state_8=%u init_e10_nonzero=%d archiveFlush_480_nonzero=%d worker_4e0_present=%d registered_15c0=%u registered_1650=%u enabled_1651=%u deviceStats_15c3=%u preinitQueueCount=%d",
            sequence,state,init?1:0,archive?1:0,worker?1:0,baseStarted,derivedStarted,enabled,deviceStats,queued);
        else ba::log("Telemetry audit %u main: unavailable (read or derived-vtable check failed)",sequence);
    }
    if(session) {
        uintptr_t vtable=0;unsigned char registered=0;uint32_t state=0;uint64_t value10=0,value20=0;
        if(read(session,0,vtable) && vtable==unity+0x1a2b078 && read(session,8,registered) &&
           read(session,0xc,state) && read(session,0x10,value10) && read(session,0x20,value20))
            ba::log("Telemetry audit %u session: registered_8=%u state_c_nonzero=%d value_10_nonzero=%d value_20_nonzero=%d",
                sequence,registered,state?1:0,value10?1:0,value20?1:0);
        else ba::log("Telemetry audit %u session: unavailable (read or vtable check failed)",sequence);
    }
    if(performance) {
        unsigned char registered=0,enabled=0;
        if(read(performance,0,registered) && read(performance,9,enabled))
            ba::log("Telemetry audit %u performance: registered_0=%u enabled_9=%u",sequence,registered,enabled);
        else ba::log("Telemetry audit %u performance: unavailable (read failed)",sequence);
    }
    uintptr_t mainAfter=0,sessionAfter=0,performanceAfter=0;
    const bool stable=read(unity,0x1d0eb28,mainAfter) && read(unity,0x1d0eb40,sessionAfter) && read(unity,0x1d0eca8,performanceAfter) &&
        mainAfter==main && sessionAfter==session && performanceAfter==performance;
    ba::log("Telemetry audit %u snapshotEnd singletonPointersStable=%d; scalar observations are not atomic or network evidence",sequence,stable?1:0);
}
static void startup() {
    if(startupLogged || !requested())return;
    startupLogged=true;sample("startup-after-engine-init");
}
static void beforeQuit() noexcept {
    // Only the explicit owned native-Quit diagnostic calls this,immediately
    // before the original OnConfirm dispatch. No telemetry API/Unity call,lock,
    // teardown hook or object mutation. Observation failure must not block Quit.
    if(!requested())return;
    if(quitAttempted)return;
    quitAttempted=true;
    try {
        if(!startupLogged || disabled || !auditThread || auditThread!=GetCurrentThreadId())return;
        const unsigned before=snapshots;
        sample("pre-quit-confirm");
        ba::log("TELEMETRY PREQUIT boundary: thread=%lu samplesBefore=%u samplesAfter=%u readOnly=1 originalConfirmNext=1",
            GetCurrentThreadId(),before,snapshots);
    } catch(...) {
        disabled=true;
        // No exception from the observer may consume the original Quit callback.
    }
}
static void deviceProbe() noexcept {
    // Exact no-argument Windows x64 ABI established from the retained complete
    // original body and paired internal-call registration. Never invoke an
    // original/partial recipe or call collectors/flush/lower-level helpers.
    static const bool enabled=ba::flag(L"-telemetry-device-probe");
    static bool attempted=false;
    if(!enabled || attempted)return;
    attempted=true;
    try {
        auto require=[](bool value,const char* why){if(!value)throw std::runtime_error(why);};
        require(requested() && checked && !disabled && completeRecipe15 && auditThread==GetCurrentThreadId() &&
            ba::flag(L"-native-quit-smoke") && ba_native_settings::session &&
            ba_native_settings::session->profile().compare(0,12,"nativestest_")==0,
            "complete recipe15,initialized game thread and explicit owned diagnostic required");
        struct Main {
            uintptr_t pointer=0,vtable=0,worker=0;
            uint64_t header[4]={};uint32_t marker=0,state=0,init=0,archive=0;
            unsigned char registered=0,derived=0,enabled=0,deviceStats=0;
        };
        auto capture=[&](Main& s) {
            uintptr_t confirm=0;
            return read(unity,0x1d0eb28,s.pointer) && s.pointer && read(s.pointer,0,s.vtable) &&
                s.vtable==unity+0x1a2c538 && read(s.pointer,0x1470,s.header) && read(s.pointer,0x1490,s.marker) &&
                read(s.pointer,8,s.state) && read(s.pointer,0xe10,s.init) && read(s.pointer,0x480,s.archive) &&
                read(s.pointer,0x4e0,s.worker) && read(s.pointer,0x15c0,s.registered) &&
                read(s.pointer,0x1650,s.derived) && read(s.pointer,0x1651,s.enabled) && read(s.pointer,0x15c3,s.deviceStats) &&
                read(unity,0x1d0eb28,confirm) && confirm==s.pointer;
        };
        auto same=[](const Main& a,const Main& b) {
            return a.pointer==b.pointer && a.vtable==b.vtable && a.worker==b.worker &&
                !memcmp(a.header,b.header,sizeof(a.header)) && a.marker==b.marker && a.state==b.state &&
                a.init==b.init && a.archive==b.archive && a.registered==b.registered && a.derived==b.derived &&
                a.enabled==b.enabled && a.deviceStats==b.deviceStats;
        };
        Main before,confirm,after,last;
        require(capture(before) && capture(confirm) && same(before,confirm),"unstable pre-call analytics object");
        ba::log("TELEMETRY DEVICE baseline: headerDataPresent=%d allocator=%u count=%llu encodedCapacity=%llu marker=%u; no payload traversal",
            before.header[0]?1:0,static_cast<uint32_t>(before.header[1]),before.header[2],before.header[3],before.marker);
        // This is the empty custom32-byte configuration container,NOT the
        // three-pointer pre-init queue at+1458. Do not follow its data pointer.
        // Upper32 bits of header[1] may be padding: compare raw equality only.
        require(!before.header[0] && static_cast<uint32_t>(before.header[1])==0x4b && !before.header[2] &&
            before.header[3]==1 && before.marker==0 && before.state==0 && before.init==0 && before.archive==0 &&
            !before.worker && !before.registered && !before.derived && !before.enabled && !before.deviceStats,
            "device probe requires retained disabled constructor state and marker0");
        const auto* signature=static_cast<const Signature*>(nullptr);
        for(const auto& item:signatures)if(item.rva==0x1fda50)signature=&item;
        require(signature!=nullptr,"device API signature absent");
        Bytes expected=hex(signature->original),replacement=hex(signature->candidate),loaded(expected.size());
        memcpy(expected.data(),replacement.data(),replacement.size());
        require(copy(unity+signature->rva,loaded.data(),loaded.size()) && loaded==expected &&
            replacement==Bytes({0x31,0xc0,0xc3}),"loaded device API is not the complete guarded entry");
        // Original returns AL,not a fully defined int. Guard returns false before
        // singleton access or hardware collection. No yielding between snapshots.
        const bool result=reinterpret_cast<bool(*)()>(unity+signature->rva)();
        require(!result && capture(after) && capture(last) && same(before,after) && same(after,last),
            "device API result or sampled configuration changed");
        ba::log("TELEMETRY DEVICE probe passed: version=1 thread=%lu calls=1 returned=0 mainStable=1 disabledFieldsUnchanged=1 rawHeaderUnchanged=1 markerBefore=0 markerAfter=0 configCount=0 payloadRead=0",
            GetCurrentThreadId());
        // These separate analytics-only void entries are checked RETs. Borrowed
        // unreadable inputs must never be dereferenced. Observe only SSO tags/
        // remaining-capacity bytes,not inline identity data or heap payloads.
        struct IdentityMeta {unsigned char userTag=0,userRemaining=0,deviceTag=0,deviceRemaining=0;};
        auto identities=[&](IdentityMeta& s) {
            return read(before.pointer,0x1130,s.userTag) && read(before.pointer,0x1128,s.userRemaining) &&
                read(before.pointer,0x14c8,s.deviceTag) && read(before.pointer,0x14c0,s.deviceRemaining);
        };
        IdentityMeta idBefore,idAfter;
        require(identities(idBefore) && idBefore.userTag==1 && idBefore.userRemaining==24 &&
            idBefore.deviceTag==1 && idBefore.deviceRemaining==24,"owned empty identity SSO metadata required");
        for(const size_t rva:{size_t(0x2048a0),size_t(0x204cb0)}) {
            const Signature* entry=nullptr;for(const auto& item:signatures)if(item.rva==rva)entry=&item;
            require(entry!=nullptr,"identity setter signature absent");
            Bytes guarded=hex(entry->original),change=hex(entry->candidate),live(guarded.size());
            require(change==Bytes({0xc3}),"identity setter must be an entry RET");
            memcpy(guarded.data(),change.data(),change.size());
            require(copy(unity+rva,live.data(),live.size()) && live==guarded,"identity setter not fully guarded");
            reinterpret_cast<void(*)(void*)>(unity+rva)(reinterpret_cast<void*>(uintptr_t(1)));
        }
        require(identities(idAfter) && idBefore.userTag==idAfter.userTag && idBefore.userRemaining==idAfter.userRemaining &&
            idBefore.deviceTag==idAfter.deviceTag && idBefore.deviceRemaining==idAfter.deviceRemaining &&
            capture(after) && capture(last) && same(before,after) && same(after,last),"identity metadata or disabled state changed");
        ba::log("TELEMETRY IDENTITY probe passed: version=1 thread=%lu calls=2 borrowedUnreadable=1 mainStable=1 emptySsoMetadataUnchanged=1 identityPayloadRead=0",
            GetCurrentThreadId());
        // Guarded CALLBACK body deliberately retains data-free progress. All
        // native strings below are authored stack fixtures,never user payloads.
        unsigned char adTag=0,adRemaining=0,tracking=0,dirty=0;
        uintptr_t receiverTable=0;
        require(read(before.pointer,0x1498,receiverTable) && receiverTable==unity+0x1a2c630 &&
            read(before.pointer,0x1618,adTag) && adTag==1 && read(before.pointer,0x1610,adRemaining) && adRemaining==24 &&
            read(before.pointer,0x1620,tracking) && !tracking && read(before.pointer,0x1621,dirty) && !dirty && before.state==0 && !before.init,
            "ads callback requires owned disabled empty constructor state");
        const Signature *callback=nullptr,*copySite=nullptr;
        for(const auto& item:signatures){if(item.rva==0xc307c0)callback=&item;if(item.rva==0xc30838)copySite=&item;}
        require(callback && copySite,"ads callback signatures absent");
        for(const auto* item:{callback,copySite}) {
            Bytes expected=hex(item->original),change=hex(item->candidate),live(expected.size());
            if(!change.empty())memcpy(expected.data(),change.data(),change.size());
            require(copy(unity+item->rva,live.data(),live.size()) && live==expected,"ads callback not guarded as reviewed");
        }
        require(hex(copySite->candidate)==Bytes(5,0x90),"ads copy guard must contain five NOPs");
        alignas(8) unsigned char supplied[40]={},error[40]={},suppliedBefore[40]={},errorBefore[40]={};
        supplied[0]='x';supplied[24]=23;supplied[32]=1;error[24]=24;error[32]=1;
        const uint32_t allocator=0x49;memcpy(supplied+36,&allocator,4);memcpy(error+36,&allocator,4);
        memcpy(suppliedBefore,supplied,sizeof(supplied));memcpy(errorBefore,error,sizeof(error));
        reinterpret_cast<void(*)(void*,const void*,unsigned char,const void*)>(unity+0xc307c0)(
            reinterpret_cast<void*>(before.pointer+0x1498),supplied,1,error);
        require(!memcmp(suppliedBefore,supplied,sizeof(supplied)) && !memcmp(errorBefore,error,sizeof(error)) &&
            read(before.pointer,0x1618,adTag) && adTag==1 && read(before.pointer,0x1610,adRemaining) && adRemaining==24 &&
            read(before.pointer,0x1620,tracking) && tracking==1 && read(before.pointer,0x1621,dirty) && dirty==1 &&
            capture(after) && capture(last) && same(before,after) && same(after,last),"ads callback retention/progress differs");
        ba::log("TELEMETRY ADS probe passed: version=1 thread=%lu calls=1 authoredInput=1 retainedEmpty=1 tracking=1 dirty=1 state=0 borrowedUnchanged=1 retainedPayloadRead=0",
            GetCurrentThreadId());
        // Verified constant-result entries only;never execute original event
        // wrappers with unreadable borrowed inputs or manufacture managed data.
        for(const size_t rva:{size_t(0x208350),size_t(0x208840),size_t(0x20afa0)}) {
            const Signature* entry=nullptr;for(const auto& item:signatures)if(item.rva==rva)entry=&item;
            require(entry!=nullptr,"event entry signature absent");
            Bytes guarded=hex(entry->original),change=hex(entry->candidate),live(guarded.size());
            require(change==Bytes({0xb8,2,0,0,0,0xc3}),"event entry must return original disabled result");
            memcpy(guarded.data(),change.data(),change.size());
            require(copy(unity+rva,live.data(),live.size()) && live==guarded,"event entry not fully guarded");
            const auto unreadable=reinterpret_cast<void*>(uintptr_t(1));
            const int result=rva==0x20afa0?
                reinterpret_cast<int(*)(void*,void*,int,void*)>(unity+rva)(unreadable,unreadable,1,unreadable):
                reinterpret_cast<int(*)(void*)>(unity+rva)(unreadable);
            require(result==2,"event API did not return original disabled result");
        }
        require(capture(after) && capture(last) && same(before,after) && same(after,last) &&
            identities(idAfter) && idBefore.userTag==idAfter.userTag && idBefore.userRemaining==idAfter.userRemaining &&
            idBefore.deviceTag==idAfter.deviceTag && idBefore.deviceRemaining==idAfter.deviceRemaining &&
            read(before.pointer,0x1618,adTag) && adTag==1 && read(before.pointer,0x1610,adRemaining) && adRemaining==24 &&
            read(before.pointer,0x1620,tracking) && tracking==1 && read(before.pointer,0x1621,dirty) && dirty==1,
            "event API changed sampled disabled state or identity metadata");
        ba::log("TELEMETRY EVENTS probe passed: version=1 thread=%lu calls=3 returnedDisabled=3 borrowedUnreadable=1 sampledStateUnchanged=1 payloadRead=0",
            GetCurrentThreadId());
        // Remaining registered entries include mixed double/Boolean/stack ABI.
        // All calls execute only the verified constant-disabled replacement.
        for(const size_t rva:{size_t(0x207ad0),size_t(0x208890),size_t(0x208c50),size_t(0x209000),size_t(0x2096c0),
                             size_t(0x209d80),size_t(0x20a610),size_t(0x20b690),size_t(0x20bea0)}) {
            const Signature* entry=nullptr;for(const auto& item:signatures)if(item.rva==rva)entry=&item;
            require(entry!=nullptr,"event-control entry signature absent");
            Bytes guarded=hex(entry->original),change=hex(entry->candidate),live(guarded.size());
            require(change==Bytes({0xb8,2,0,0,0,0xc3}),"event-control entry must return disabled status2");
            memcpy(guarded.data(),change.data(),change.size());
            require(copy(unity+rva,live.data(),live.size()) && live==guarded,"event-control entry not fully guarded");
            const auto input=reinterpret_cast<void*>(uintptr_t(1));int status=-1;
            switch(rva) {
                case 0x207ad0:status=reinterpret_cast<int(*)(void*,double,void*,void*,void*,bool)>(unity+rva)(input,1.25,input,input,input,true);break;
                case 0x208890:status=reinterpret_cast<int(*)(void*)>(unity+rva)(input);break;
                case 0x208c50:status=reinterpret_cast<int(*)(void*,bool)>(unity+rva)(input,true);break;
                case 0x209000:status=reinterpret_cast<int(*)(void*,int,void*)>(unity+rva)(input,1,input);break;
                case 0x2096c0:status=reinterpret_cast<int(*)(void*,bool,int,void*)>(unity+rva)(input,true,1,input);break;
                case 0x209d80:case 0x20a610:status=reinterpret_cast<int(*)(void*,int,int,void*,int,void*,void*)>(unity+rva)(input,1,1,input,1,input,input);break;
                case 0x20b690:status=reinterpret_cast<int(*)(void*,void*,int,void*)>(unity+rva)(input,input,1,input);break;
                case 0x20bea0:status=reinterpret_cast<int(*)(void*,int,int,void*)>(unity+rva)(input,1,1,input);break;
            }
            require(status==2,"event-control API did not return disabled status2");
        }
        require(capture(after) && capture(last) && same(before,after) && same(after,last) &&
            identities(idAfter) && idBefore.userTag==idAfter.userTag && idBefore.userRemaining==idAfter.userRemaining &&
            idBefore.deviceTag==idAfter.deviceTag && idBefore.deviceRemaining==idAfter.deviceRemaining &&
            read(before.pointer,0x1618,adTag) && adTag==1 && read(before.pointer,0x1610,adRemaining) && adRemaining==24 &&
            read(before.pointer,0x1620,tracking) && tracking==1 && read(before.pointer,0x1621,dirty) && dirty==1,
            "event-control API changed sampled disabled state or identity metadata");
        ba::log("TELEMETRY EVENTCONTROL probe passed: version=1 thread=%lu calls=9 returnedDisabled=9 borrowedUnreadable=1 sampledStateUnchanged=1 payloadRead=0",
            GetCurrentThreadId());
        // Create retains ORIGINAL native allocation/construction/cleanup but
        // discards its incoming name. No managed wrapper type is fabricated.
        for(const size_t rva:{size_t(0x205070),size_t(0x205084),size_t(0x205430),size_t(0x205550),size_t(0x205cd0),
                             size_t(0x206110),size_t(0x206550),size_t(0x206a30),size_t(0x206f10),size_t(0x207340)}) {
            const Signature* entry=nullptr;for(const auto& item:signatures)if(item.rva==rva)entry=&item;
            require(entry!=nullptr,"custom-data signature absent");
            Bytes expected=hex(entry->original),change=hex(entry->candidate),live(expected.size());
            if(rva==0x205084)require(change==Bytes({0x31,0xff,0x90}),"Create must ignore only incoming name");
            else if(rva==0x205070 || rva==0x205430)require(change.empty(),"Create entry/Destroy must remain original");
            else require(change==Bytes({0x31,0xc0,0xc3}),"custom-data Add must return Boolean false");
            if(!change.empty())memcpy(expected.data(),change.data(),change.size());
            require(copy(unity+rva,live.data(),live.size()) && live==expected,"custom-data lifetime/guard differs");
        }
        const auto input=reinterpret_cast<void*>(uintptr_t(1));
        using Destroy=void(*)(void*);
        std::unique_ptr<void,Destroy> event(
            reinterpret_cast<void*(*)(void*,void*)>(unity+0x205070)(nullptr,input),
            reinterpret_cast<Destroy>(unity+0x205430));
        require(event.get()!=nullptr,"original empty event allocation failed");
        const auto address=reinterpret_cast<uintptr_t>(event.get());
        auto emptyEvent=[&]() {
            uintptr_t table=0,document=0,node=0;uint64_t first=1,second=1,total=1;uint32_t kind=0;
            unsigned char tag=0,remaining=0;
            return read(address,0,table) && table==unity+0x1a2c4f0 &&
                read(address,0x160,document) && document==address+0x48 &&
                read(document,0x78,node) && node==address+0xf8 &&
                read(node,0,first) && !first && read(node,8,second) && !second && read(node,0x10,kind) && kind==3 &&
                read(address,0x1b8,total) && !total &&
                read(address,0x1b0,tag) && tag==1 && read(address,0x1a8,remaining) && remaining==24;
        };
        require(emptyEvent(),"original event is not empty with expected inline metadata");
        require(!reinterpret_cast<bool(*)(void*,void*,void*)>(unity+0x205550)(input,input,input) &&
            !reinterpret_cast<bool(*)(void*,void*,int32_t)>(unity+0x205cd0)(input,input,-1) &&
            !reinterpret_cast<bool(*)(void*,void*,uint32_t)>(unity+0x206110)(input,input,1) &&
            !reinterpret_cast<bool(*)(void*,void*,int64_t)>(unity+0x206550)(input,input,-1) &&
            !reinterpret_cast<bool(*)(void*,void*,uint64_t)>(unity+0x206a30)(input,input,1) &&
            !reinterpret_cast<bool(*)(void*,void*,bool)>(unity+0x206f10)(input,input,true) &&
            !reinterpret_cast<bool(*)(void*,void*,double)>(unity+0x207340)(input,input,1.25) && emptyEvent(),
            "custom-data Add did not return false or empty metadata changed");
        event.reset();  // Original destroy returned;never inspect this freed owner.
        require(capture(after) && capture(last) && same(before,after) && same(after,last),
            "custom-data lifetime changed sampled disabled Main state");
        ba::log("TELEMETRY CUSTOMDATA probe passed: version=1 thread=%lu creates=1 adds=7 addFalse=7 destroys=1 realNativeOwner=1 emptyMetadataUnchanged=1 borrowedUnreadable=1 borrowedPayloadRead=0",
            GetCurrentThreadId());
        // Continuous-event failure is synchronous status2,not a completion
        // callback. Check and invoke replacements only;no collector is created.
        for(const size_t rva:{size_t(0x202050),size_t(0x2026f0),size_t(0x203050),size_t(0x203710),size_t(0x203df0)}) {
            const Signature* entry=nullptr;for(const auto& item:signatures)if(item.rva==rva)entry=&item;
            require(entry!=nullptr,"continuous-event signature absent");
            Bytes guarded=hex(entry->original),change=hex(entry->candidate),live(guarded.size());
            require(change==Bytes({0xb8,2,0,0,0,0xc3}),"continuous-event entry must return disabled status2");
            memcpy(guarded.data(),change.data(),change.size());
            require(copy(unity+rva,live.data(),live.size()) && live==guarded,"continuous-event entry not fully guarded");
            const auto borrowed=reinterpret_cast<void*>(uintptr_t(1));int status=-1;
            switch(rva) {
                case 0x202050:status=reinterpret_cast<int(*)(void*,void*,void*)>(unity+rva)(borrowed,borrowed,borrowed);break;
                case 0x2026f0:status=reinterpret_cast<int(*)(void*,void*,int,void*,int,void*)>(unity+rva)(borrowed,borrowed,1,borrowed,1,borrowed);break;
                case 0x203050:status=reinterpret_cast<int(*)(void*,void*,int,void*)>(unity+rva)(borrowed,borrowed,1,borrowed);break;
                case 0x203710:status=reinterpret_cast<int(*)(void*,void*,float,float,bool)>(unity+rva)(borrowed,borrowed,1.25f,2.5f,true);break;
                case 0x203df0:status=reinterpret_cast<int(*)(void*,void*,float,float,bool,int,void*)>(unity+rva)(borrowed,borrowed,1.25f,2.5f,true,1,borrowed);break;
            }
            require(status==2,"continuous-event API did not return disabled status2");
        }
        require(capture(after) && capture(last) && same(before,after) && same(after,last),
            "continuous-event replacement changed sampled disabled Main state");
        ba::log("TELEMETRY CONTINUOUS probe passed: version=1 thread=%lu calls=5 returnedDisabled=5 borrowedUnreadable=1 sampledStateUnchanged=1 borrowedPayloadRead=0",
            GetCurrentThreadId());
    } catch(...) {
        // A refusal makes no success claim and never blocks original Quit.
        // If reached after the callback,its data-free progress is retained.
        try {ba::log("TELEMETRY DEVICE probe failed: no success claim; original game flow retained");} catch(...) {}
    }
}
#include "telemetry_cache_probe.cpp"
static void update() {
    if(!requested() || disabled || !startupLogged || !ba::owner || quitAttempted ||
       snapshots>=ba_telemetry_sampling::maxRegularSnapshots)return;
    if(!auditThread || auditThread!=GetCurrentThreadId()) {
        disabled=true;ba::log("Telemetry audit disabled: state observation thread changed");return;
    }
    try {
        using ba::Obj;using ba_telemetry_sampling::Stage;
        Obj fsm=ba::read<Obj>(ba::owner,0x2b0);
        Obj current=fsm?ba::get<Obj>(fsm,"_currentState"):nullptr;
        Stage stage=Stage::Other;
        const char* label=nullptr;
        if(current) {
            if(current==ba::read<Obj>(ba::owner,0x2c0)){stage=Stage::Menu;label="menu";}
            else if(current==ba::read<Obj>(ba::owner,0x2f0)){stage=Stage::PostGame;label="postgame";}
            // These owner fields already select the helper's established native
            // InGame readiness and offline-tutorial startup states. No new native
            // layout or transition is inferred by this observer.
            else if(current==ba::read<Obj>(ba::owner,0x2e8)){stage=Stage::InGame;label="ingame";}
            else if(current==ba::read<Obj>(ba::owner,0x2f8)){stage=Stage::Tutorial;label="tutorial";}
        }
        if(schedule.due(stage,GetTickCount64(),snapshots))sample(label);
        if(stage==Stage::Menu){deviceProbe();cache_probe::run();}
    } catch(const std::exception&) {
        disabled=true;ba::log("Telemetry audit disabled: state observation failed");
    }
}
}
