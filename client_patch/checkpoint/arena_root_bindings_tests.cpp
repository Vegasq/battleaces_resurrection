// Authored helper/guard tests only. No Simulation.dll is loaded or executed.
// Including arena.cpp exercises the real exported refusal paths and shares
// pure validation/priming helpers; positive live NativeReader remains untested.
#include "arena.cpp"
#include <functional>
#include <iostream>
#include <thread>

static void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
static void rejects(const std::function<void()>& action) {
    bool rejected=false;try{action();}catch(const std::runtime_error&){rejected=true;}
    check(rejected,"invalid root binding accepted");
}
static unsigned unexpectedFlsCalls=0;
static PVOID WINAPI authoredFls(DWORD){++unexpectedFlsCalls;return nullptr;}
struct Fixture {
    std::vector<uint8_t> module=std::vector<uint8_t>(0x461000);
    uint8_t* memory=nullptr;
    ba_thread_state::CurrentState current;
    Fixture() {
        owner=GetCurrentThreadId();stats=Stats{};saved.clear();rootReader.reset();
        rootPrimeAttempted=rootPrimed=false;image=nullptr;unexpectedFlsCalls=0;
        for(const auto& guard:kRootGuards)std::memcpy(module.data()+guard.rva,guard.bytes,guard.size);
        auto dos=reinterpret_cast<IMAGE_DOS_HEADER*>(module.data());dos->e_magic=IMAGE_DOS_SIGNATURE;dos->e_lfanew=0x80;
        auto pe=reinterpret_cast<IMAGE_NT_HEADERS64*>(module.data()+0x80);pe->Signature=IMAGE_NT_SIGNATURE;
        pe->FileHeader.Machine=IMAGE_FILE_MACHINE_AMD64;pe->OptionalHeader.Magic=IMAGE_NT_OPTIONAL_HDR64_MAGIC;
        pe->OptionalHeader.SizeOfImage=static_cast<DWORD>(module.size());
        *reinterpret_cast<PVOID(WINAPI**)(DWORD)>(module.data()+0x385188)=authoredFls;
        image=reinterpret_cast<HMODULE>(module.data());
        // Constructor only checks bytes/headers/import pointer, never invokes
        // its original getter. Fixture memory is RW, never executable.
        rootReader=std::make_unique<ba_thread_state::NativeReader>(image);
        memory=static_cast<uint8_t*>(VirtualAlloc(nullptr,4096,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE));
        check(memory!=nullptr,"authored TLS allocation failed");
        current={owner,2,3,4,memory,reinterpret_cast<void*>(0x2222),reinterpret_cast<void*>(0x3333)};
    }
    ~Fixture(){rootReader.reset();image=nullptr;if(memory)VirtualFree(memory,0,MEM_RELEASE);}
};
static void fullCodeGuards() {
    Fixture fixture;check(rootCodeGuards(fixture.module.data()),"complete original guards refused");
    for(const auto& guard:kRootGuards)for(size_t index=0;index<guard.size;++index) {
        fixture.module[guard.rva+index]^=1;
        check(!rootCodeGuards(fixture.module.data()),"guard checked only a prefix or missed changed byte");
        fixture.module[guard.rva+index]^=1;
    }
    check(unexpectedFlsCalls==0,"byte-guard test executed getter");
}
static void checkedValuesAndLastError() {
    Fixture fixture;SetLastError(0xabcdef01);const auto values=checkedRootValues(fixture.current);
    check(GetLastError()==0xabcdef01,"root read validation changed LastError");
    const std::array<uint64_t,7> expected{{owner,2,3,4,reinterpret_cast<uint64_t>(fixture.memory),0x2222,0x3333}};
    check(values==expected,"7u64 root binding field order changed");
    for(unsigned which=0;which<7;++which) {
        auto invalid=fixture.current;
        if(which==0)invalid.threadId^=1;
        if(which==1)invalid.tlsIndex=4096;
        if(which==2)invalid.vcrIndex=FLS_OUT_OF_INDEXES;
        if(which==3)invalid.ucrtIndex=FLS_OUT_OF_INDEXES;
        if(which==4)invalid.vcrRoot=nullptr;
        if(which==5)invalid.ucrtRoot=reinterpret_cast<void*>(~uintptr_t(0));
        if(which==6)invalid.tls=nullptr;
        SetLastError(0x11112222);rejects([&]{checkedRootValues(invalid);});
        check(GetLastError()==0x11112222,"refused binding changed LastError");
    }
    DWORD old=0;check(VirtualProtect(fixture.memory,4096,PAGE_READONLY,&old)!=FALSE,"TLS readonly control failed");
    rejects([&]{checkedRootValues(fixture.current);});DWORD unused;
    check(VirtualProtect(fixture.memory,4096,old,&unused)!=FALSE,"TLS control restore failed");
}
static void primingCallsAndFailures() {
    Fixture fixture;unsigned vcr=0,ucrt=0,read=0;
    auto first=[&]()->void*{++vcr;SetLastError(17);return fixture.current.vcrRoot;};
    auto second=[&]()->void*{++ucrt;SetLastError(18);return fixture.current.ucrtRoot;};
    auto current=[&]{++read;SetLastError(19);return fixture.current;};
    SetLastError(0x33445566);const auto result=primeRootFunctions(current,first,second);
    check(vcr==1 && ucrt==1 && read==1 && result[5]==0x2222 && result[6]==0x3333,"priming did not call each getter once");
    check(GetLastError()==0x33445566,"priming changed LastError");
    vcr=ucrt=read=0;
    rejects([&]{primeRootFunctions(current,[&]()->void*{++vcr;return nullptr;},second);});
    check(vcr==1 && ucrt==0 && read==0,"zero VCR root continued priming");
    vcr=ucrt=read=0;
    rejects([&]{primeRootFunctions(current,first,[&]()->void*{++ucrt;return reinterpret_cast<void*>(~uintptr_t(0));});});
    check(vcr==1 && ucrt==1 && read==0,"sentinel UCRT root read as valid");
    rejects([&]{primeRootFunctions([&]{auto changed=fixture.current;changed.vcrRoot=reinterpret_cast<void*>(5);return changed;},first,second);});
    check(unexpectedFlsCalls==0,"authored priming invoked original FLS import");
}
static void exportedRefusalsHaveNoPartialWrite() {
    Fixture fixture;std::array<uint64_t,7> output;output.fill(0xaaaaaaaaaaaaaaaaULL);const auto before=output;
    SetLastError(0x98765432);check(BAGetRootBindings(output.data(),7)==-1 && output==before,"unprimed export wrote output");
    check(GetLastError()==0x98765432,"readonly refusal changed LastError");
    rootPrimed=true;
    check(BAGetRootBindings(output.data(),6)==-1 && BAGetRootBindings(nullptr,7)==-1 && output==before,"invalid output shape partially wrote");
    rootPrimed=false;rootPrimeAttempted=true;
    check(BAPrimeRootBindings()==-1,"second prime attempt accepted");rootPrimeAttempted=false;
    stats.captures=1;check(BAPrimeRootBindings()==-1,"priming after capture accepted");stats.captures=0;
    saved.push_back(std::make_unique<Checkpoint>());check(BAPrimeRootBindings()==-1,"priming with live checkpoint accepted");saved.clear();
    // A changed full-body guard refuses before either original lazy getter.
    fixture.module[kRootGuards[1].rva+kRootGuards[1].size-1]^=1;
    SetLastError(0x98765432);check(BAPrimeRootBindings()==-2 && !rootPrimed,"unguarded original primer would execute");
    check(GetLastError()==0x98765432 && unexpectedFlsCalls==0,"guard refusal executed getter/changed LastError");
}
static void exportedReadGuardAndForeignOwner() {
    Fixture fixture;std::array<uint64_t,7> output;output.fill(9);const auto before=output;rootPrimed=true;
    fixture.module[kRootGuards[0].rva+kRootGuards[0].size-1]^=1;SetLastError(0x12344321);
    check(BAGetRootBindings(output.data(),7)==-2 && output==before,"readonly export bypassed guard or partially wrote");
    check(GetLastError()==0x12344321 && unexpectedFlsCalls==0,"readonly guard executed original getter");
    stats.error=0;fixture.module[kRootGuards[0].rva+kRootGuards[0].size-1]^=1;
    int code=0;DWORD error=0;
    std::thread foreignOwner([&]{SetLastError(0x56788765);code=BAGetRootBindings(output.data(),7);error=GetLastError();});foreignOwner.join();
    check(code==-1 && error==0x56788765 && output==before && stats.foreignThreads==1 && stats.error==1,
          "foreign root reader bypassed owner/LastError/output guard");
    check(unexpectedFlsCalls==0,"foreign refusal called original getter");
}
int main() {
    try {
        fullCodeGuards();checkedValuesAndLastError();primingCallsAndFailures();
        exportedRefusalsHaveNoPartialWrite();exportedReadGuardAndForeignOwner();
        std::cout<<"arena root bindings:5 authored guard/ABI/priming/refusal groups PASS; no original native execution\n";return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
