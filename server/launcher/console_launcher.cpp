// Foreground Windows server launcher. Python retains its original SIGINT/asyncio
// cleanup. No batch shell is waiting to ask a second termination question.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdint.h>
#include <string>
#include <vector>
#include <stdexcept>
#include "launch_args.hpp"

extern "C" __declspec(dllexport) const char* BattleAcesServerConsoleAbi() {
    return "BA_RESURRECTION_SERVER_CONSOLE_V1";
}
namespace {
struct Handle {
    HANDLE value=nullptr;
    explicit Handle(HANDLE handle=nullptr):value(handle){}
    ~Handle(){if(value && value!=INVALID_HANDLE_VALUE)CloseHandle(value);}
    Handle(const Handle&)=delete;Handle& operator=(const Handle&)=delete;
};
void require(bool okay) {if(!okay)throw std::runtime_error("server launcher operation failed");}
BOOL WINAPI control(DWORD event) {
    // A custom handler is process-local, unlike the inheritable NULL/TRUE ignore
    // flag. Python receives this SAME console event with normal SIGINT enabled.
    return event==CTRL_C_EVENT;
}
HANDLE stdio(DWORD which,bool input) {
    const auto source=GetStdHandle(which);HANDLE copy=nullptr;
    if(source && source!=INVALID_HANDLE_VALUE) {
        require(DuplicateHandle(GetCurrentProcess(),source,GetCurrentProcess(),&copy,0,TRUE,DUPLICATE_SAME_ACCESS)!=0);
        return copy;
    }
    SECURITY_ATTRIBUTES security{sizeof(security),nullptr,TRUE};
    copy=CreateFileW(L"NUL",input?GENERIC_READ:GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE,
                     &security,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
    require(copy!=INVALID_HANDLE_VALUE);return copy;
}
struct Attributes {
    std::vector<unsigned char> storage;
    LPPROC_THREAD_ATTRIBUTE_LIST list=nullptr;
    explicit Attributes(HANDLE* handles) {
        SIZE_T bytes=0;InitializeProcThreadAttributeList(nullptr,1,0,&bytes);require(bytes>0);
        storage.resize(bytes);list=reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(storage.data());
        require(InitializeProcThreadAttributeList(list,1,0,&bytes)!=0);
        if(!UpdateProcThreadAttribute(list,0,PROC_THREAD_ATTRIBUTE_HANDLE_LIST,handles,3*sizeof(HANDLE),nullptr,nullptr)) {
            DeleteProcThreadAttributeList(list);list=nullptr;require(false);
        }
    }
    ~Attributes(){if(list)DeleteProcThreadAttributeList(list);}
};
int run(int argc,wchar_t** argv) {
    wchar_t module[32768];const auto length=GetModuleFileNameW(nullptr,module,32768);
    require(length>0 && length<32768);
    std::wstring path(module,length);const auto slash=path.find_last_of(L"\\/");require(slash!=std::wstring::npos);
    path.resize(slash+1);const auto executable=path+L"program\\runtime\\python.exe";
    const auto attributes=GetFileAttributesW(executable.c_str());
    require(attributes!=INVALID_FILE_ATTRIBUTES && !(attributes&FILE_ATTRIBUTE_DIRECTORY));
    std::wstring command=ba_server_launcher::quote(executable)+L" -I -B -m tools.package_server start";
    for(int i=1;i<argc;++i)command+=L" "+ba_server_launcher::quote(argv[i]);
    require(command.size()<32767);
    require(SetConsoleCtrlHandler(nullptr,FALSE)!=0);
    require(SetConsoleCtrlHandler(control,TRUE)!=0);

    Handle job(CreateJobObjectW(nullptr,nullptr));require(job.value!=nullptr);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};limits.BasicLimitInformation.LimitFlags=JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    require(SetInformationJobObject(job.value,JobObjectExtendedLimitInformation,&limits,sizeof(limits))!=0);
    Handle input(stdio(STD_INPUT_HANDLE,true)),output(stdio(STD_OUTPUT_HANDLE,false)),error(stdio(STD_ERROR_HANDLE,false));
    HANDLE inherited[]{input.value,output.value,error.value};Attributes attrs(inherited);
    STARTUPINFOEXW startup{};startup.StartupInfo.cb=sizeof(startup);startup.StartupInfo.dwFlags=STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput=input.value;startup.StartupInfo.hStdOutput=output.value;startup.StartupInfo.hStdError=error.value;
    startup.lpAttributeList=attrs.list;
    PROCESS_INFORMATION process{};
    require(CreateProcessW(executable.c_str(),command.data(),nullptr,nullptr,TRUE,
        EXTENDED_STARTUPINFO_PRESENT|CREATE_SUSPENDED,nullptr,nullptr,&startup.StartupInfo,&process)!=0);
    Handle child(process.hProcess),thread(process.hThread);
    if(!AssignProcessToJobObject(job.value,child.value)) {
        // Never resume an unowned child. The only direct termination is this
        // just-created suspended process, before Python/config/assets execute.
        TerminateProcess(child.value,1);WaitForSingleObject(child.value,INFINITE);require(false);
    }
    require(ResumeThread(thread.value)!=static_cast<DWORD>(-1));
    require(WaitForSingleObject(child.value,INFINITE)==WAIT_OBJECT_0);
    DWORD code=1;require(GetExitCodeProcess(child.value,&code)!=0);
    JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting{};
    const auto deadline=GetTickCount64()+3000;
    do {
        require(QueryInformationJobObject(job.value,JobObjectBasicAccountingInformation,&accounting,sizeof(accounting),nullptr)!=0);
        if(!accounting.ActiveProcesses)break;
        Sleep(20);
    }while(GetTickCount64()<deadline);
    // A normal Python exit must leave no native worker. Closing our job bounds
    // abnormal exits/orphans, but such cleanup must never masquerade as success.
    if(accounting.ActiveProcesses || accounting.TotalTerminatedProcesses) {
        fputs("Server workers remained after host exit; owned cleanup required.\n",stderr);return 1;
    }
    return static_cast<int>(code);
}
}
int wmain(int argc,wchar_t** argv) {
    try {return run(argc,argv);}
    catch(...) {fputs("Server launcher failed: verify the complete local package and Windows runtime.\n",stderr);return 1;}
}
