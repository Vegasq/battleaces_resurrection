#define WIN32_LEAN_AND_MEAN
#include "native_settings.hpp"
#include <iostream>
#include <functional>
namespace settings=ba_native_settings;
static void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
static void rejects(const std::function<void()>& action){bool failed=false;try{action();}catch(const std::exception&){failed=true;}check(failed,"unsafe native settings path accepted");}
static void write(const std::wstring& path,const std::string& text) {
    settings::Handle file(CreateFileW(path.c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr));
    settings::ordinary(file.value);DWORD count=0;
    check(WriteFile(file.value,text.data(),static_cast<DWORD>(text.size()),&count,nullptr) && count==text.size() && FlushFileBuffers(file.value),"fixture write failed");
}
static std::string read(const std::wstring& path) {
    settings::Handle file(CreateFileW(path.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr));
    settings::ordinary(file.value);char text[4096];DWORD count=0;check(ReadFile(file.value,text,sizeof(text),&count,nullptr)!=0,"fixture read failed");return std::string(text,count);
}
struct Folder {
    std::wstring path;
    Folder() {
        wchar_t current[32768],full[32768];check(GetCurrentDirectoryW(32768,current)>0,"test cwd missing");
        static unsigned sequence=0;
        const auto selected=std::wstring(current)+L"\\native-settings-tests-\u00e9-"+std::to_wstring(GetCurrentProcessId())+L"-"+std::to_wstring(GetTickCount64())+L"-"+std::to_wstring(++sequence);
        check(GetFullPathNameW(selected.c_str(),32768,full,nullptr)>0,"test canonical path unavailable");
        check(std::wstring(full)==selected && CreateDirectoryW(full,nullptr),"test directory unsafe or exists");path=selected+L"\\";
    }
    ~Folder() {
        // Fixed owned fixtures only. No recursive/enumerated deletion.
        for(const auto key:{L"alpha",L"beta"}) {
            const auto folder=path+L".battleaces-resurrection\\profiles\\"+key;
            for(const auto suffix:{L"\\gameconfig-localuser.toml",L"\\gameconfig-localuser.toml.link",L"\\native-settings.lock"}) {
                const auto file=folder+suffix;SetFileAttributesW(file.c_str(),FILE_ATTRIBUTE_NORMAL);DeleteFileW(file.c_str());
            }
            RemoveDirectoryW(folder.c_str());
        }
        RemoveDirectoryW((path+L".battleaces-resurrection\\profiles").c_str());
        RemoveDirectoryW((path+L".battleaces-resurrection").c_str());RemoveDirectoryW(path.substr(0,path.size()-1).c_str());
    }
};
static void arguments() {
    check(settings::profile(ba_command_line::parse(L"game.exe"))=="default","default profile missing");
    check(settings::profile(ba_command_line::parse(L"game.exe -local-profile=alpha_2"))=="alpha_2","profile option missing");
    for(const auto key:{L"",L"..",L"../alpha",L"CON",L"con",L"com1",L"lpt9",L"Upper",L"\u00e9",L"alpha.beta",L"alpha beta"})
        rejects([&]{settings::profile({L"game.exe",std::wstring(L"-local-profile=")+key});});
    rejects([]{settings::profile({L"game.exe",L"-local-profile=alpha",L"-local-profile=beta"});});
    rejects([]{settings::profile({L"game.exe",L"-local-profile="+std::wstring(49,L'a')});});
}
static void storage() {
    Folder first,second;std::wstring target;
    {
        settings::Session alpha(first.path,"alpha");target=alpha.path();
        check(target==first.path+L".battleaces-resurrection\\profiles\\alpha\\gameconfig-localuser.toml","path selection mismatch");
        check(GetFileAttributesW(target.c_str())==INVALID_FILE_ATTRIBUTES,"preparation fabricated a native config");
        write(target,"[account]\ndecks = 'authored selection A'\n");
        DWORD before=0,after=0;GetProcessHandleCount(GetCurrentProcess(),&before);
        for(int i=0;i<30;++i)rejects([&]{settings::Session conflict(first.path,"alpha");});
        GetProcessHandleCount(GetCurrentProcess(),&after);check(before==after,"failed competing writer leaked handles");
        settings::Session beta(first.path,"beta");write(beta.path(),"authored selection B");
        settings::Session other(second.path,"alpha");write(other.path(),"authored other installation");
        check(read(target)=="[account]\ndecks = 'authored selection A'\n","another profile/installation changed state");
        check(read(beta.path())=="authored selection B" && read(other.path())=="authored other installation","profile state not independent");
    }
    {
        settings::Session restart(first.path,"alpha");
        check(restart.hadExistingInput() && restart.inputProtected(),"existing input is not protected before native deck acceptance");
        check(read(restart.path())=="[account]\ndecks = 'authored selection A'\n","protected input is not readable/unchanged");
        settings::Handle blockedWrite(CreateFileW(target.c_str(),GENERIC_WRITE,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr));
        check(blockedWrite.value==INVALID_HANDLE_VALUE && GetLastError()==ERROR_SHARING_VIOLATION,"startup writer can modify unvalidated input");
        restart.acceptInput();check(!restart.inputProtected(),"accepted input guard was not released");
        settings::Handle allowedWrite(CreateFileW(target.c_str(),GENERIC_WRITE,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr));
        check(allowedWrite.value!=INVALID_HANDLE_VALUE,"accepted input is still unwritable");
    }
    check(SetFileAttributesW(target.c_str(),FILE_ATTRIBUTE_READONLY)!=0,"readonly fixture failed");
    rejects([&]{settings::Session readonly(first.path,"alpha");});check(SetFileAttributesW(target.c_str(),FILE_ATTRIBUTE_NORMAL)!=0,"readonly reset failed");
    check(CreateHardLinkW((target+L".link").c_str(),target.c_str(),nullptr)!=0,"hard-link fixture unavailable");
    rejects([&]{settings::Session hardlink(first.path,"alpha");});check(DeleteFileW((target+L".link").c_str())!=0,"hard-link fixture cleanup failed");
    check(read(target)=="[account]\ndecks = 'authored selection A'\n","rejected paths changed config");
    rejects([&]{settings::Session traversal(first.path,"../alpha");});
    rejects([&]{settings::Session relative(L"relative\\","alpha");});
    Folder blocked;const auto parent=blocked.path+L".battleaces-resurrection";write(parent,"ordinary blocker");
    rejects([&]{settings::Session noDirectory(blocked.path,"alpha");});
    check(read(parent)=="ordinary blocker" && DeleteFileW(parent.c_str()),"blocked parent was changed");
}
int main(){try{arguments();storage();std::cout<<"Native settings path, Unicode installation, writer-lock, isolation, restart and failure checks passed\n";return 0;}
    catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
