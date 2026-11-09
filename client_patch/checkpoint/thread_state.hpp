#pragma once
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <intrin.h>
#include <array>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <functional>
#include <limits>
#include <stdexcept>
#include <utility>

// Isolated exact-build experiment. Not part of the ordinary game helper.
// The caller serializes ALL DLL API entry/exit observations and checkpoint
// operations with an external gate, with no DLL callback/CRT work outside it.
// All registered threads must remain alive throughout capture/validation/copy.
// A retained handle identifies a thread and detects prior exit; it cannot pin
// a running thread's lifetime. No other native API may be in flight here.
namespace ba_thread_state {
inline constexpr size_t nativeTlsBytes=133,maximumThreads=8;

struct LastError {
    DWORD value=GetLastError();
    ~LastError(){SetLastError(value);}
};
inline void require(bool value,const char* message) {
    if(!value)throw std::runtime_error(message);
}
inline void writableTls(const uint8_t* address) {
    require(address!=nullptr,"native TLS block is null");
    const auto first=reinterpret_cast<uintptr_t>(address);
    require(first<=(std::numeric_limits<uintptr_t>::max)()-nativeTlsBytes,"native TLS range overflow");
    const auto end=first+nativeTlsBytes;
    for(auto cursor=first;cursor<end;) {
        MEMORY_BASIC_INFORMATION info{};
        require(VirtualQuery(reinterpret_cast<const void*>(cursor),&info,sizeof(info))==sizeof(info),
                "native TLS memory query failed");
        const auto protection=info.Protect&0xff;
        require(info.State==MEM_COMMIT && !(info.Protect&(PAGE_GUARD|PAGE_NOACCESS)) &&
                (protection==PAGE_READWRITE || protection==PAGE_WRITECOPY ||
                 protection==PAGE_EXECUTE_READWRITE || protection==PAGE_EXECUTE_WRITECOPY),
                "native TLS range is not writable committed memory");
        const auto base=reinterpret_cast<uintptr_t>(info.BaseAddress);
        require(base<=(std::numeric_limits<uintptr_t>::max)()-info.RegionSize,"native TLS region overflow");
        const auto next=base+info.RegionSize;
        require(next>cursor,"native TLS memory query did not advance");cursor=next;
    }
}

struct CurrentState {
    DWORD threadId=0,tlsIndex=TLS_OUT_OF_INDEXES,vcrIndex=FLS_OUT_OF_INDEXES,ucrtIndex=FLS_OUT_OF_INDEXES;
    uint8_t* tls=nullptr;
    void* vcrRoot=nullptr;
    void* ucrtRoot=nullptr;
};
inline bool sameIndices(const CurrentState& a,const CurrentState& b) {
    return a.tlsIndex==b.tlsIndex && a.vcrIndex==b.vcrIndex && a.ucrtIndex==b.ucrtIndex;
}
inline bool sameBindings(const CurrentState& a,const CurrentState& b) {
    return a.threadId==b.threadId && sameIndices(a,b) && a.tls==b.tls &&
           a.vcrRoot==b.vcrRoot && a.ucrtRoot==b.ucrtRoot;
}

// Caller binds the loaded module's original/derived SHA and keeps it loaded.
// Local guards catch wrong architecture/layout or an altered getter; they are
// not a substitute for that source/binary identity check. No target is loaded.
class NativeReader {
public:
    explicit NativeReader(HMODULE module):image_(reinterpret_cast<uint8_t*>(module)) {
        LastError preserve;
        static_assert(sizeof(void*)==8,"original native reader requires Windows x64");
        require(image_!=nullptr,"native module is null");
        const auto dos=reinterpret_cast<const IMAGE_DOS_HEADER*>(image_);
        require(dos->e_magic==IMAGE_DOS_SIGNATURE && dos->e_lfanew>0 && dos->e_lfanew<4096,
                "invalid native DOS header");
        const auto pe=reinterpret_cast<const IMAGE_NT_HEADERS64*>(image_+dos->e_lfanew);
        require(pe->Signature==IMAGE_NT_SIGNATURE && pe->FileHeader.Machine==IMAGE_FILE_MACHINE_AMD64 &&
                pe->OptionalHeader.Magic==IMAGE_NT_OPTIONAL_HDR64_MAGIC &&
                pe->OptionalHeader.SizeOfImage>=0x460744,"unsupported native image layout");
        static constexpr uint8_t prefix[]={0x48,0x89,0x5c,0x24,0x08,0x57,0x48,0x83,0xec,0x20};
        require(std::memcmp(image_+vcrGetterRva,prefix,sizeof(prefix))==0,
                "original nonallocating VCR getter guard failed");
        fls_=*reinterpret_cast<FlsGetter const*>(image_+ucrtGetValueIat);
        require(fls_!=nullptr,"native UCRT FlsGetValue import is null");
    }
    CurrentState operator()()const {
        LastError preserve;
        CurrentState result;result.threadId=GetCurrentThreadId();
        result.tlsIndex=*reinterpret_cast<const DWORD*>(image_+tlsIndexRva);
        result.vcrIndex=*reinterpret_cast<const DWORD*>(image_+vcrIndexRva);
        result.ucrtIndex=*reinterpret_cast<const DWORD*>(image_+ucrtIndexRva);
        require(result.tlsIndex!=TLS_OUT_OF_INDEXES && result.tlsIndex<4096 &&
                result.vcrIndex!=FLS_OUT_OF_INDEXES && result.ucrtIndex!=FLS_OUT_OF_INDEXES,
                "native TLS/FLS index is uninitialized");
        auto slots=reinterpret_cast<uint8_t**>(__readgsqword(0x58));
        require(slots!=nullptr,"native current-thread TLS vector is null");
        result.tls=slots[result.tlsIndex];writableTls(result.tls);
        // This getter preserves GetLastError and uses the DLL's actual FLS or
        // TLS fallback. It does not allocate a PTD; it maps its -1 sentinel to
        // null. Caller-established quiescence excludes in-progress CRT setup.
        result.vcrRoot=reinterpret_cast<void*(*)()>(image_+vcrGetterRva)();
        require(*reinterpret_cast<FlsGetter const*>(image_+ucrtGetValueIat)==fls_,
                "native UCRT FlsGetValue import changed");
        result.ucrtRoot=fls_(result.ucrtIndex);
        require(result.ucrtRoot!=reinterpret_cast<void*>(~uintptr_t(0)),"native UCRT PTD is initializing");
        return result;
    }
private:
    using FlsGetter=PVOID (WINAPI*)(DWORD);
    static constexpr size_t tlsIndexRva=0x45f300,vcrIndexRva=0x432260,ucrtIndexRva=0x432550;
    static constexpr size_t vcrGetterRva=0x34392c,ucrtGetValueIat=0x385188;
    uint8_t* image_=nullptr;
    FlsGetter fls_=nullptr;
};

class ThreadRegistry {
    struct SavedThread {
        CurrentState bindings;
        uint64_t revision=0;
        std::array<uint8_t,nativeTlsBytes> tls{};
    };
public:
    using Reader=std::function<CurrentState()>;
    class Snapshot {
        friend class ThreadRegistry;
        uint64_t registry_=0;
        size_t count_=0;
        std::array<SavedThread,maximumThreads> threads_{};
    public:
        size_t threadCount()const{return count_;}
    };
    explicit ThreadRegistry(Reader reader):reader_(std::move(reader)),id_(newIdentity()) {
        require(static_cast<bool>(reader_),"thread registry reader unavailable");
    }
    ~ThreadRegistry(){for(size_t i=0;i<count_;++i)if(threads_[i].handle)CloseHandle(threads_[i].handle);}
    ThreadRegistry(const ThreadRegistry&)=delete;ThreadRegistry& operator=(const ThreadRegistry&)=delete;
    ThreadRegistry(ThreadRegistry&&)=delete;ThreadRegistry& operator=(ThreadRegistry&&)=delete;

    // Call both before AND after every native API, including initialization,
    // read-only queries and shutdown. TLS bytes may change; bindings are tracked
    // separately. New threads and lazy roots before a new capture are permitted.
    void observe() {
        LastError preserve;const auto current=read();
        for(size_t i=0;i<count_;++i)if(threads_[i].observed.threadId==current.threadId) {
            auto& entry=threads_[i];alive(entry);
            if(!sameBindings(entry.observed,current)) {
                require(entry.revision<(std::numeric_limits<uint64_t>::max)(),"native binding revision exhausted");
                ++entry.revision;entry.observed=current;
            }
            return;
        }
        require(count_<maximumThreads,"native thread registration limit reached");
        HANDLE handle=OpenThread(SYNCHRONIZE|THREAD_QUERY_LIMITED_INFORMATION,FALSE,current.threadId);
        require(handle!=nullptr,"cannot retain native API thread handle");
        Thread entry;entry.handle=handle;entry.observed=current;entry.revision=1;
        try {alive(entry);}catch(...){CloseHandle(handle);throw;}
        threads_[count_++]=entry;
    }
    Snapshot capture()const {
        LastError preserve;const auto current=read();checkObservedCurrent(current);
        Snapshot result;result.registry_=id_;result.count_=count_;
        // Validate all sources before copying any TLS. Other-thread FLS roots
        // are the last observed bindings, never sampled from a foreign TEB.
        for(size_t i=0;i<count_;++i) {
            const auto& entry=threads_[i];alive(entry);writableTls(entry.observed.tls);
            require(sameIndices(entry.observed,current),"native global TLS/FLS indices differ across threads");
            result.threads_[i].bindings=entry.observed;result.threads_[i].revision=entry.revision;
        }
        for(size_t i=0;i<count_;++i)
            std::memcpy(result.threads_[i].tls.data(),threads_[i].observed.tls,nativeTlsBytes);
        return result;
    }
    // Call BEFORE any arena/.data mutation. Other threads' actual FLS roots
    // cannot be read cross-thread: their last API-exit observation is valid only
    // under the caller's no-outside-DLL-callback/CRT-work lifetime contract.
    void validate(const Snapshot& saved)const {
        LastError preserve;
        require(saved.registry_==id_ && saved.count_==count_ && count_>0,
                "native checkpoint registry/thread set changed");
        const auto current=read();checkObservedCurrent(current);
        for(size_t i=0;i<count_;++i) {
            const auto& entry=threads_[i];const auto& old=saved.threads_[i];alive(entry);
            require(sameBindings(entry.observed,old.bindings) && entry.revision==old.revision &&
                    sameIndices(current,old.bindings),"native checkpoint TLS/FLS binding changed");
            writableTls(old.bindings.tls);
        }
    }
    void restore(const Snapshot& saved)const {
        LastError preserve;validate(saved);
        // Nothing below can reject after an earlier TLS block has been copied.
        // The external gate/lifetime contract prevents concurrent unmapping or
        // DLL index/root changes between validation and these fixed-size writes.
        for(size_t i=0;i<count_;++i)
            std::memcpy(saved.threads_[i].bindings.tls,saved.threads_[i].tls.data(),nativeTlsBytes);
    }
    size_t threadCount()const{return count_;}
private:
    struct Thread {CurrentState observed;HANDLE handle=nullptr;uint64_t revision=0;};
    static uint64_t newIdentity() {
        auto value=nextId_.load();
        for(;;) {
            require(value>0 && value<(std::numeric_limits<uint64_t>::max)(),"thread registry identities exhausted");
            if(nextId_.compare_exchange_weak(value,value+1))return value;
        }
    }
    CurrentState read()const {
        auto value=reader_();
        require(value.threadId==GetCurrentThreadId(),"native reader is not on its reported API thread");
        require(value.tlsIndex!=TLS_OUT_OF_INDEXES && value.vcrIndex!=FLS_OUT_OF_INDEXES &&
                value.ucrtIndex!=FLS_OUT_OF_INDEXES,"native TLS/FLS index is uninitialized");
        require(value.vcrRoot!=reinterpret_cast<void*>(~uintptr_t(0)) &&
                value.ucrtRoot!=reinterpret_cast<void*>(~uintptr_t(0)),"native PTD sentinel is not quiescent");
        writableTls(value.tls);return value;
    }
    static void alive(const Thread& entry) {
        require(entry.handle && GetThreadId(entry.handle)==entry.observed.threadId &&
                GetProcessIdOfThread(entry.handle)==GetCurrentProcessId() &&
                WaitForSingleObject(entry.handle,0)==WAIT_TIMEOUT,"registered native API thread exited or changed");
    }
    void checkObservedCurrent(const CurrentState& current)const {
        for(size_t i=0;i<count_;++i)if(threads_[i].observed.threadId==current.threadId) {
            require(sameBindings(threads_[i].observed,current),"current native TLS/FLS bindings changed without observation");
            return;
        }
        throw std::runtime_error("checkpoint caller is not a registered native API thread");
    }
    Reader reader_;
    inline static std::atomic<uint64_t> nextId_{1};
    uint64_t id_=0;
    size_t count_=0;
    std::array<Thread,maximumThreads> threads_{};
};
} // namespace ba_thread_state
