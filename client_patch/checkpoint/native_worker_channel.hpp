#pragma once
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <algorithm>
#include <limits>
#include <memory>
#include <mutex>
#include <string>
#include <utility>
#include <vector>
#include "native_worker_wire.hpp"

// Client-side isolated worker owner. Never run construction/destruction under
// the loader lock; callers serialize lifetime with their native API gate.
// A caller must not destroy Process while another caller is inside request.
namespace ba_native_worker_channel {
namespace wire=ba_native_worker_wire;
class Handle {
public:
    Handle()=default;explicit Handle(HANDLE value):value_(value){}
    ~Handle(){reset();}
    Handle(const Handle&)=delete;Handle& operator=(const Handle&)=delete;
    Handle(Handle&& other)noexcept:value_(other.release()){}
    Handle& operator=(Handle&& other)noexcept{if(this!=&other)reset(other.release());return *this;}
    HANDLE get()const{return value_;}
    explicit operator bool()const{return value_ && value_!=INVALID_HANDLE_VALUE;}
    HANDLE release(){const auto result=value_;value_=nullptr;return result;}
    void reset(HANDLE value=nullptr){if(*this)CloseHandle(value_);value_=value;}
private:HANDLE value_=nullptr;
};
struct Stats {
    uint64_t requests=0,responses=0,timeouts=0,protocolFailures=0,ioFailures=0,hostFailures=0;
    uint64_t jobTerminations=0,retainedProcessTerminations=0,ioAbandoned=0;
    DWORD pid=0,exitCode=STILL_ACTIVE;
    bool processCreated=false,assignedBeforeResume=false,resumed=false;
    bool ioStarted=false,ioJoined=false,processReaped=false,naturalShutdown=false;
};
// Per-instance launch boundary permits authored failure controls without a
// process-wide hook or changing the owned process/Job cleanup implementation.
struct LaunchApi {
    decltype(&CreateProcessW) createProcess=&CreateProcessW;
    decltype(&SetInformationJobObject) setJobInformation=&SetInformationJobObject;
    decltype(&AssignProcessToJobObject) assignProcess=&AssignProcessToJobObject;
};
inline std::wstring quote(const std::wstring& value) {
    std::wstring out=L"\"";size_t slashes=0;
    for(const auto ch:value) {
        if(ch==L'\\'){++slashes;continue;}
        if(ch==L'\"'){out.append(slashes*2+1,L'\\');out+=ch;slashes=0;continue;}
        out.append(slashes,L'\\');slashes=0;out+=ch;
    }
    out.append(slashes*2,L'\\');out+=L'\"';return out;
}

class Process {
public:
    Process(const std::wstring& executable,const std::vector<std::wstring>& arguments,
            const std::wstring& workingDirectory,const std::wstring& stderrPath,LaunchApi launch={})
        :state_(std::make_shared<State>()) {
        try {
            wire::require(!executable.empty() && !workingDirectory.empty() && !stderrPath.empty(),"worker paths required");
            wire::require(launch.createProcess && launch.setJobInformation && launch.assignProcess,"worker launch API required");
            SECURITY_ATTRIBUTES security{sizeof(security),nullptr,TRUE};
            HANDLE first=nullptr,second=nullptr;
            check(CreatePipe(&first,&second,&security,0)!=0,"CreatePipe stdin");
            Handle childInput(first);state_->input.reset(second);
            check(SetHandleInformation(state_->input.get(),HANDLE_FLAG_INHERIT,0)!=0,"parent stdin inheritance");
            first=second=nullptr;check(CreatePipe(&first,&second,&security,0)!=0,"CreatePipe stdout");
            state_->output.reset(first);Handle childOutput(second);
            check(SetHandleInformation(state_->output.get(),HANDLE_FLAG_INHERIT,0)!=0,"parent stdout inheritance");
            Handle childError(CreateFileW(stderrPath.c_str(),GENERIC_WRITE,FILE_SHARE_READ,&security,
                                          CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr));
            check(static_cast<bool>(childError),"create fresh worker stderr");
            STARTUPINFOEXW startup{};startup.StartupInfo.cb=sizeof(startup);
            startup.StartupInfo.dwFlags=STARTF_USESTDHANDLES|STARTF_USESHOWWINDOW;
            startup.StartupInfo.wShowWindow=SW_HIDE;
            startup.StartupInfo.hStdInput=childInput.get();startup.StartupInfo.hStdOutput=childOutput.get();
            startup.StartupInfo.hStdError=childError.get();
            SIZE_T amount=0;InitializeProcThreadAttributeList(nullptr,1,0,&amount);
            check(amount>0,"size worker handle attribute list");
            std::vector<uint8_t> storage(amount);
            startup.lpAttributeList=reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(storage.data());
            check(InitializeProcThreadAttributeList(startup.lpAttributeList,1,0,&amount)!=0,"initialize worker handle list");
            struct Attributes {LPPROC_THREAD_ATTRIBUTE_LIST value;~Attributes(){DeleteProcThreadAttributeList(value);}} attributes{startup.lpAttributeList};
            HANDLE inherited[]={childInput.get(),childOutput.get(),childError.get()};
            check(UpdateProcThreadAttribute(startup.lpAttributeList,0,PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                                             inherited,sizeof(inherited),nullptr,nullptr)!=0,"set explicit worker handles");
            std::wstring command=quote(executable);
            for(const auto& argument:arguments){command+=L' ';command+=quote(argument);}
            wire::require(command.size()<32767,"worker command line exceeds Windows bound");
            std::vector<wchar_t> mutableCommand(command.begin(),command.end());mutableCommand.push_back(0);
            PROCESS_INFORMATION info{};
            check(launch.createProcess(executable.c_str(),mutableCommand.data(),nullptr,nullptr,TRUE,
                  CREATE_SUSPENDED|CREATE_NO_WINDOW|EXTENDED_STARTUPINFO_PRESENT,nullptr,
                  workingDirectory.c_str(),&startup.StartupInfo,&info)!=0,"create hidden suspended worker");
            process_.reset(info.hProcess);mainThread_.reset(info.hThread);
            state_->stats.pid=info.dwProcessId;state_->stats.processCreated=true;
            job_.reset(CreateJobObjectW(nullptr,nullptr));check(static_cast<bool>(job_),"create owned worker Job");
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};limits.BasicLimitInformation.LimitFlags=JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            check(launch.setJobInformation(job_.get(),JobObjectExtendedLimitInformation,&limits,sizeof(limits))!=0,"set owned worker Job limit");
            check(launch.assignProcess(job_.get(),process_.get())!=0,"assign suspended worker to Job");
            state_->stats.assignedBeforeResume=true;
            auto context=new std::shared_ptr<State>(state_);
            ioThread_.reset(CreateThread(nullptr,0,&Process::ioEntry,context,0,nullptr));
            if(!ioThread_){delete context;check(false,"create client I/O thread");}
            state_->stats.ioStarted=true;
            check(ResumeThread(mainThread_.get())==1,"resume owned worker after Job assignment");
            state_->stats.resumed=true;
            // Parent must close all child-side pipe handles before any request,
            // so terminating this Job reliably produces EOF in its I/O thread.
        }catch(...){cleanup(true);throw;}
    }
    ~Process(){cleanup(true);}
    Process(const Process&)=delete;Process& operator=(const Process&)=delete;
    Process(Process&&)=delete;Process& operator=(Process&&)=delete;

    wire::Response request(uint8_t opcode,const wire::Bytes& payload,DWORD timeoutMs=5000) {
        wire::require(timeoutMs>0 && timeoutMs!=INFINITE,"bounded worker timeout required");
        std::unique_lock<std::mutex> call(requestMutex_,std::try_to_lock);
        wire::require(call.owns_lock(),"worker already has an outstanding request");
        {
            std::lock_guard<std::mutex> lock(state_->mutex);
            wire::require(!state_->closed && !state_->terminal && !state_->closing,"worker channel is closed/failed");
            auto packet=wire::encodeRequest(opcode,nextId_,payload);
            wire::require(nextId_!=(std::numeric_limits<uint32_t>::max)(),"worker request IDs exhausted");
            ResetEvent(state_->done.get());state_->response={};state_->error.clear();
            state_->packet=std::move(packet);state_->opcode=opcode;state_->id=nextId_++;
            state_->closing=opcode==wire::shutdownOpcode;++state_->stats.requests;
        }
        SetEvent(state_->work.get());
        const DWORD waited=WaitForSingleObject(state_->done.get(),timeoutMs);
        if(waited!=WAIT_OBJECT_0) {
            {
                std::lock_guard<std::mutex> lock(state_->mutex);
                state_->terminal=true;
                if(waited==WAIT_TIMEOUT){++state_->stats.timeouts;state_->error="owned worker request timed out";}
                else state_->error="owned worker completion wait failed";
            }
            cleanup(true);throw std::runtime_error(waited==WAIT_TIMEOUT?"owned worker request timed out":"owned worker completion wait failed");
        }
        std::string error;
        {
            std::lock_guard<std::mutex> lock(state_->mutex);
            if(!state_->terminal)return std::move(state_->response);
            error=state_->error;
        }
        cleanup(true);throw std::runtime_error(error.empty()?"owned worker channel failed":error);
    }
    void shutdown(DWORD timeoutMs=5000) {
        wire::require(timeoutMs>0 && timeoutMs!=INFINITE,"bounded worker shutdown timeout required");
        {
            std::lock_guard<std::mutex> lock(state_->mutex);
            if(state_->stats.naturalShutdown)return;
        }
        bool acknowledged;
        {std::lock_guard<std::mutex> lock(state_->mutex);acknowledged=state_->shutdownAck;}
        if(!acknowledged) {
            const auto response=request(wire::shutdownOpcode,{},timeoutMs);
            if(response.result!=0 || !response.data.empty()) {
                markFailure("owned worker shutdown failed");cleanup(true);throw std::runtime_error("owned worker shutdown failed");
            }
        }
        if(!process_ || WaitForSingleObject(process_.get(),timeoutMs)!=WAIT_OBJECT_0) {
            markFailure("owned worker did not exit after shutdown");cleanup(true);throw std::runtime_error("owned worker did not exit after shutdown");
        }
        DWORD code=STILL_ACTIVE;check(GetExitCodeProcess(process_.get(),&code)!=0,"read worker exit code");
        if(code!=0){markFailure("owned worker shutdown exit was nonzero");cleanup(true);throw std::runtime_error("owned worker shutdown exit was nonzero");}
        {std::lock_guard<std::mutex> lock(state_->mutex);state_->stats.naturalShutdown=true;}
        cleanup(false);
        wire::require(stats().ioJoined && stats().processReaped,"worker shutdown cleanup incomplete");
    }
    Stats stats()const{std::lock_guard<std::mutex> lock(state_->mutex);return state_->stats;}
    bool failed()const{std::lock_guard<std::mutex> lock(state_->mutex);return state_->terminal;}
    bool healthy()const{std::lock_guard<std::mutex> lock(state_->mutex);return !state_->terminal && !state_->closed;}
private:
    struct State {
        std::mutex mutex;
        Handle input,output,work,done,stop;
        wire::Bytes packet;
        wire::Response response;
        uint8_t opcode=0;uint32_t id=0;
        bool terminal=false,closing=false,closed=false,shutdownAck=false;
        std::string error;Stats stats;
        State():work(CreateEventW(nullptr,FALSE,FALSE,nullptr)),done(CreateEventW(nullptr,TRUE,FALSE,nullptr)),
                stop(CreateEventW(nullptr,TRUE,FALSE,nullptr)) {
            if(!work || !done || !stop)throw std::runtime_error("create worker channel events failed");
        }
    };
    static void check(bool okay,const char* operation) {
        if(!okay)throw std::runtime_error(std::string(operation)+" failed: "+std::to_string(GetLastError()));
    }
    static void transfer(HANDLE handle,uint8_t* bytes,size_t length,bool writing) {
        size_t at=0;
        while(at<length) {
            DWORD transferred=0;const auto amount=static_cast<DWORD>((std::min)(length-at,size_t(1024*1024)));
            const BOOL okay=writing?WriteFile(handle,bytes+at,amount,&transferred,nullptr):ReadFile(handle,bytes+at,amount,&transferred,nullptr);
            check(okay!=0,writing?"worker pipe WriteFile":"worker pipe ReadFile");
            if(!transferred)throw std::runtime_error("owned worker pipe reached EOF");at+=transferred;
        }
    }
    static DWORD WINAPI ioEntry(void* raw)noexcept {
        std::unique_ptr<std::shared_ptr<State>> owner(static_cast<std::shared_ptr<State>*>(raw));
        auto state=*owner;owner.reset();
        const HANDLE waits[]={state->stop.get(),state->work.get()};
        while(WaitForMultipleObjects(2,waits,FALSE,INFINITE)==WAIT_OBJECT_0+1) {
            try {
                wire::Bytes packet;uint8_t opcode;uint32_t id;
                {std::lock_guard<std::mutex> lock(state->mutex);packet=std::move(state->packet);opcode=state->opcode;id=state->id;}
                transfer(state->input.get(),packet.data(),packet.size(),true);
                wire::Bytes bytes(wire::headerSize);transfer(state->output.get(),bytes.data(),bytes.size(),false);
                const auto header=wire::decodeHeader(bytes,true);
                wire::require(header.opcode==static_cast<uint8_t>(opcode|0x80) && header.requestId==id,
                              "worker response opcode/ID differs");
                wire::Bytes payload(header.payloadLength);transfer(state->output.get(),payload.data(),payload.size(),false);
                auto response=wire::decodeResponse(header,payload,opcode,id);
                {std::lock_guard<std::mutex> lock(state->mutex);state->response=std::move(response);++state->stats.responses;
                 if(opcode==wire::shutdownOpcode)state->shutdownAck=true;}
                SetEvent(state->done.get());if(opcode==wire::shutdownOpcode)return 0;
            }catch(const wire::HostError& error){failure(state,error.what(),2);return 1;}
             catch(const wire::ProtocolError& error){failure(state,error.what(),1);return 1;}
             catch(const std::exception& error){failure(state,error.what(),0);return 1;}
             catch(...){failure(state,"unknown owned worker I/O exception",0);return 1;}
        }
        return 0;
    }
    static void failure(const std::shared_ptr<State>& state,const std::string& message,int kind)noexcept {
        try {
            std::lock_guard<std::mutex> lock(state->mutex);
            if(!state->terminal) {
                state->terminal=true;state->error=message;
                if(kind==1)++state->stats.protocolFailures;else if(kind==2)++state->stats.hostFailures;else ++state->stats.ioFailures;
            }
            SetEvent(state->done.get());
        }catch(...){SetEvent(state->done.get());}
    }
    void markFailure(const char* error)noexcept {
        try{std::lock_guard<std::mutex> lock(state_->mutex);state_->terminal=true;if(state_->error.empty())state_->error=error;}catch(...){}
    }
    void cleanup(bool force)noexcept {
        if(!state_)return;
        SetEvent(state_->stop.get());
        if(process_) {
            if(force && WaitForSingleObject(process_.get(),0)==WAIT_TIMEOUT) {
                // A Job created before a failed limits/assignment call can be
                // empty: terminating it succeeds without touching this child.
                // Until assignment succeeds, only the retained process handle
                // owns termination of our still-suspended child.
                if(state_->stats.assignedBeforeResume && job_ && TerminateJobObject(job_.get(),0xe001)) {
                    std::lock_guard<std::mutex> lock(state_->mutex);++state_->stats.jobTerminations;
                }else if(TerminateProcess(process_.get(),0xe002)) {
                    std::lock_guard<std::mutex> lock(state_->mutex);++state_->stats.retainedProcessTerminations;
                }
            }
            const DWORD waited=WaitForSingleObject(process_.get(),2000);
            std::lock_guard<std::mutex> lock(state_->mutex);
            state_->stats.processReaped=waited==WAIT_OBJECT_0;
            if(state_->stats.processReaped)GetExitCodeProcess(process_.get(),&state_->stats.exitCode);
        }
        if(ioThread_) {
            if(WaitForSingleObject(ioThread_.get(),0)!=WAIT_OBJECT_0)CancelSynchronousIo(ioThread_.get());
            const DWORD waited=WaitForSingleObject(ioThread_.get(),2000);
            std::lock_guard<std::mutex> lock(state_->mutex);
            state_->stats.ioJoined=waited==WAIT_OBJECT_0;
            if(!state_->stats.ioJoined){++state_->stats.ioAbandoned;state_->terminal=true;}
        }
        mainThread_.reset();process_.reset();ioThread_.reset();job_.reset();
        try{std::lock_guard<std::mutex> lock(state_->mutex);state_->closed=true;}catch(...){}
        // If cancellation ever fails, the I/O thread owns a shared State until
        // it exits. No unbounded join or unsafe TerminateThread is performed.
    }
    std::shared_ptr<State> state_;
    Handle process_,mainThread_,job_,ioThread_;
    std::mutex requestMutex_;
    uint32_t nextId_=1;
};
}
