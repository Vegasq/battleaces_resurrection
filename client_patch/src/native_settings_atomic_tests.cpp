#define WIN32_LEAN_AND_MEAN
#include "native_settings_atomic.hpp"
#include <iostream>
#include <functional>
#include <thread>
namespace settings=ba_native_settings;
static void check(bool okay,const char* message){if(!okay)throw std::runtime_error(message);}
static void rejects(const std::function<void()>& action){bool refused=false;try{action();}catch(const std::exception&){refused=true;}check(refused,"unsafe publication accepted");}
static void write(const std::wstring& path,const char* text,bool flush=true) {
    settings::Handle file(CreateFileW(path.c_str(),GENERIC_WRITE,FILE_SHARE_READ,nullptr,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr));
    settings::ordinary(file.value);DWORD count=0;const auto length=static_cast<DWORD>(strlen(text));
    check(WriteFile(file.value,text,length,&count,nullptr) && count==length && (!flush || FlushFileBuffers(file.value)),"fixture write failed");
}
static std::string read(const std::wstring& path) {
    settings::Handle file(CreateFileW(path.c_str(),GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,
        FILE_FLAG_OPEN_REPARSE_POINT,nullptr));settings::ordinary(file.value);char buffer[4096];DWORD count=0;
    check(ReadFile(file.value,buffer,sizeof(buffer),&count,nullptr)!=0,"fixture read failed");return std::string(buffer,count);
}
struct Folder {
    std::wstring path;
    Folder() {
        wchar_t current[32768];check(GetCurrentDirectoryW(32768,current)>0,"test cwd missing");static unsigned sequence=0;
        path=std::wstring(current)+L"\\native-atomic-tests-\u00e9-"+std::to_wstring(GetCurrentProcessId())+L"-"+std::to_wstring(++sequence);
        check(CreateDirectoryW(path.c_str(),nullptr)!=0,"owned fixture directory already exists");path+=L"\\";
    }
    ~Folder() {
        const auto profile=path+L".battleaces-resurrection\\profiles\\alpha";
        WIN32_FIND_DATAW entry{};
        const auto pattern=profile+L"\\ba-*.tmp";HANDLE found=FindFirstFileW(pattern.c_str(),&entry);
        if(found!=INVALID_HANDLE_VALUE) {
            do {if(!(entry.dwFileAttributes&(FILE_ATTRIBUTE_DIRECTORY|FILE_ATTRIBUTE_REPARSE_POINT)))
                DeleteFileW((profile+L"\\"+entry.cFileName).c_str());}while(FindNextFileW(found,&entry));FindClose(found);
        }
        for(const auto name:{L"\\gameconfig-localuser.toml",L"\\native-settings.lock",L"\\alias.toml"}) {
            const auto file=profile+name;SetFileAttributesW(file.c_str(),FILE_ATTRIBUTE_NORMAL);DeleteFileW(file.c_str());
        }
        RemoveDirectoryW(profile.c_str());RemoveDirectoryW((path+L".battleaces-resurrection\\profiles").c_str());
        RemoveDirectoryW((path+L".battleaces-resurrection").c_str());RemoveDirectoryW(path.substr(0,path.size()-1).c_str());
    }
};
static std::vector<unsigned char> dacl(HANDLE file) {
    DWORD count=0;GetKernelObjectSecurity(file,DACL_SECURITY_INFORMATION,nullptr,0,&count);check(count!=0,"DACL size missing");
    std::vector<unsigned char> descriptor(count);check(GetKernelObjectSecurity(file,DACL_SECURITY_INFORMATION,descriptor.data(),count,&count)!=0,"DACL read failed");
    BOOL present=FALSE,defaulted=FALSE;PACL acl=nullptr;
    check(GetSecurityDescriptorDacl(descriptor.data(),&present,&acl,&defaulted) && present && acl,"fixture DACL missing");
    const auto start=reinterpret_cast<unsigned char*>(acl);return {start,start+acl->AclSize};
}
static void replacement() {
    Folder folder;settings::Session session(folder.path,"alpha");const auto target=session.path();
    {settings::WriteTransaction transaction(target);write(transaction.path(),"first complete save");std::cout<<"First publication\n"<<std::flush;transaction.commit();}
    check(read(target)=="first complete save","first publication missing");
    {settings::WriteTransaction transaction(target);write(transaction.path(),"partial serializer failure");}
    check(read(target)=="first complete save","failed serialization changed target");
    {settings::WriteTransaction transaction(target);rejects([&]{transaction.commit();});}
    check(read(target)=="first complete save","empty serialization changed target");
    std::vector<unsigned char> permissions;
    {
        settings::Handle original(CreateFileW(target.c_str(),READ_CONTROL,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,
            nullptr,OPEN_EXISTING,0,nullptr));permissions=dacl(original.value);
    }
    {settings::WriteTransaction transaction(target);write(transaction.path(),"second complete save");std::cout<<"Existing publication\n"<<std::flush;transaction.commit();}
    check(read(target)=="second complete save","replacement publication missing");
    {
        settings::Handle original(CreateFileW(target.c_str(),READ_CONTROL,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,
            nullptr,OPEN_EXISTING,0,nullptr));check(dacl(original.value)==permissions,"replacement changed DACL");
    }
    {
        settings::Handle deny(CreateFileW(target.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr));
        check(deny.value!=INVALID_HANDLE_VALUE,"deny-write fixture failed");rejects([&]{settings::WriteTransaction blocked(target);});
    }
    check(SetFileAttributesW(target.c_str(),FILE_ATTRIBUTE_READONLY)!=0,"readonly fixture failed");
    rejects([&]{settings::WriteTransaction blocked(target);});SetFileAttributesW(target.c_str(),FILE_ATTRIBUTE_NORMAL);
    const auto alias=target.substr(0,target.find_last_of(L'\\')+1)+L"alias.toml";
    check(CreateHardLinkW(alias.c_str(),target.c_str(),nullptr)!=0,"hard-link fixture failed");
    rejects([&]{settings::WriteTransaction blocked(target);});check(DeleteFileW(alias.c_str())!=0,"hard-link cleanup failed");
    {
        settings::WriteTransaction transaction(target);settings::Handle intruder(CreateFileW(transaction.path().c_str(),DELETE,
            FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,0,nullptr));
        const DWORD denied=GetLastError();std::cout<<"Temporary delete open refused="<<(intruder.value==INVALID_HANDLE_VALUE)<<" Win32="<<denied<<'\n'<<std::flush;
        check(intruder.value==INVALID_HANDLE_VALUE && (denied==ERROR_SHARING_VIOLATION || denied==ERROR_ACCESS_DENIED),
            "temporary can be replaced during serializer");
        write(transaction.path(),"third complete save");transaction.commit();
    }
    check(read(target)=="third complete save","failure controls changed target");
}
static void ordering() {
    settings::SaveGate gate;
    {
        settings::SaveGate::Lease outer(gate);check(outer.acquired(),"initial writer refused");
        settings::SaveGate::Lease nested(gate);check(!nested.acquired(),"same-thread writer reentry accepted");
        bool accepted=true;std::thread other([&]{settings::SaveGate::Lease overlapping(gate);accepted=overlapping.acquired();});other.join();
        check(!accepted,"concurrent writer accepted");
    }
    {settings::SaveGate::Lease later(gate);check(later.acquired(),"writer gate did not release");}
    settings::SaveOutcome outcome;check(outcome.load(),"fresh outcome is failed");
    outcome.record(2,false);outcome.record(1,true);check(!outcome.load(),"older success hid newer write refusal");
    outcome.record(4,true);outcome.record(3,false);check(outcome.load(),"older failure replaced newer successful save");
    check(outcome.newerThan(3) && !outcome.newerThan(4),"older delayed request can enter after a newer publication");
    outcome.record(6,false);outcome.record(5,true);check(!outcome.load(),"nested refusal cleared by outer successful completion");
}
static void barrier(const wchar_t* name) {
    settings::Handle event(OpenEventW(EVENT_MODIFY_STATE,FALSE,name));check(event.value!=INVALID_HANDLE_VALUE && SetEvent(event.value),"child barrier unavailable");
    Sleep(INFINITE);
}
static int child(const wchar_t* folder,const wchar_t* stage,const wchar_t* event) {
    settings::Session session(std::wstring(folder)+L"\\","alpha");session.acceptInput();settings::WriteTransaction transaction(session.path());
    if(!wcscmp(stage,L"partial")) {
        settings::Handle file(CreateFileW(transaction.path().c_str(),GENERIC_WRITE,FILE_SHARE_READ,nullptr,CREATE_ALWAYS,0,nullptr));
        settings::ordinary(file.value);DWORD count=0;check(WriteFile(file.value,"unfinished",10,&count,nullptr) && count==10,"partial child write failed");barrier(event);
    }
    write(transaction.path(),"complete replacement");if(!wcscmp(stage,L"serialized"))barrier(event);
    transaction.commit();barrier(event);return 0;
}
static void interrupted(const wchar_t* stage,bool existing) {
    Folder folder;std::wstring target;
    {settings::Session session(folder.path,"alpha");target=session.path();if(existing)write(target,"last good save");}
    static unsigned sequence=0;const auto eventName=L"Local\\BattleAcesAtomic-"+std::to_wstring(GetCurrentProcessId())+L"-"+std::to_wstring(++sequence);
    settings::Handle event(CreateEventW(nullptr,TRUE,FALSE,eventName.c_str()));check(event.value!=nullptr,"event creation failed");
    wchar_t executable[32768];check(GetModuleFileNameW(nullptr,executable,32768)>0,"test executable path missing");
    const auto command=std::wstring(L"\"")+executable+L"\" --child \""+folder.path.substr(0,folder.path.size()-1)+L"\" "+stage+L" "+eventName;
    std::vector<wchar_t> mutableCommand(command.begin(),command.end());mutableCommand.push_back(0);
    settings::Handle job(CreateJobObjectW(nullptr,nullptr));JOBOBJECT_EXTENDED_LIMIT_INFORMATION limit{};
    limit.BasicLimitInformation.LimitFlags=JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    check(job.value!=nullptr && SetInformationJobObject(job.value,JobObjectExtendedLimitInformation,&limit,sizeof(limit)),"child job setup failed");
    STARTUPINFOW startup{};startup.cb=sizeof(startup);PROCESS_INFORMATION info{};
    check(CreateProcessW(executable,mutableCommand.data(),nullptr,nullptr,FALSE,CREATE_NO_WINDOW|CREATE_SUSPENDED,nullptr,nullptr,&startup,&info)!=0,"child launch failed");
    settings::Handle process(info.hProcess),thread(info.hThread);
    if(!AssignProcessToJobObject(job.value,process.value)){TerminateProcess(process.value,99);WaitForSingleObject(process.value,10000);throw std::runtime_error("child job assignment failed");}
    check(ResumeThread(thread.value)!=DWORD(-1),"child resume failed");
    const auto signaled=WaitForSingleObject(event.value,30000);
    check(TerminateProcess(process.value,97) && WaitForSingleObject(process.value,10000)==WAIT_OBJECT_0,"owned child kill/reap failed");
    check(signaled==WAIT_OBJECT_0,"owned child never reached selected interruption boundary");
    const bool committed=!wcscmp(stage,L"committed");
    if(existing || committed)check(read(target)==(committed?"complete replacement":"last good save"),"interruption damaged published settings");
    else check(GetFileAttributesW(target.c_str())==INVALID_FILE_ATTRIBUTES && GetLastError()==ERROR_FILE_NOT_FOUND,"interruption fabricated a partial target");
    {settings::Session restart(folder.path,"alpha");restart.acceptInput();settings::WriteTransaction next(target);write(next.path(),"successful restart");next.commit();}
    check(read(target)=="successful restart","orphan temporary prevented later successful save");
}
int wmain(int argc,wchar_t** argv) {
    try {
        if(argc==5 && !wcscmp(argv[1],L"--child"))return child(argv[2],argv[3],argv[4]);
        check(argc==1,"unexpected atomic test arguments");ordering();std::cout<<"Replacement checks\n"<<std::flush;replacement();
        for(bool existing:{false,true})for(const auto stage:{L"partial",L"serialized",L"committed"}) {
            std::wcout<<L"Interruption check existing="<<existing<<L" stage="<<stage<<L'\n'<<std::flush;interrupted(stage,existing);
        }
        std::cout<<"Native settings publication, failure preservation, permissions and six owned process-interruption checks passed\n";return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
