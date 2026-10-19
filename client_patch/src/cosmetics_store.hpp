#pragma once
#include <windows.h>
#include <optional>
#include "cosmetics_state.hpp"
namespace ba_cosmetics_state {
struct Handle {
    HANDLE value=INVALID_HANDLE_VALUE;
    Handle()=default;explicit Handle(HANDLE h):value(h){}
    Handle(const Handle&)=delete;Handle& operator=(const Handle&)=delete;
    ~Handle(){if(value!=INVALID_HANDLE_VALUE)CloseHandle(value);}
};
inline void regular(HANDLE handle,bool directory=false) {
    BY_HANDLE_FILE_INFORMATION info{};
    require(handle!=INVALID_HANDLE_VALUE && GetFileType(handle)==FILE_TYPE_DISK && GetFileInformationByHandle(handle,&info) &&
        !(info.dwFileAttributes&FILE_ATTRIBUTE_REPARSE_POINT) && !!(info.dwFileAttributes&FILE_ATTRIBUTE_DIRECTORY)==directory,
        "cosmetic state requires an ordinary local file/directory");
}
inline HANDLE directory(const std::wstring& path) {
    require(CreateDirectoryW(path.c_str(),nullptr) || GetLastError()==ERROR_ALREADY_EXISTS,"cannot create cosmetic state directory");
    Handle handle(CreateFileW(path.c_str(),FILE_READ_ATTRIBUTES,FILE_SHARE_READ|FILE_SHARE_WRITE,nullptr,OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS|FILE_FLAG_OPEN_REPARSE_POINT,nullptr));regular(handle.value,true);
    const auto result=handle.value;handle.value=INVALID_HANDLE_VALUE;return result;
}
class Store {
    std::string key;
    std::wstring folder,target;
    Handle baseHandle,folderHandle,lockHandle;
    std::optional<std::string> previous;
    bool observed=false;
    unsigned sequence=0;
    std::optional<std::string> read() const {
        Handle handle(CreateFileW(target.c_str(),GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL|FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
        if(handle.value==INVALID_HANDLE_VALUE && GetLastError()==ERROR_FILE_NOT_FOUND)return std::nullopt;
        regular(handle.value);LARGE_INTEGER size{};
        require(GetFileSizeEx(handle.value,&size) && size.QuadPart>0 && size.QuadPart<=MaxBytes,"cosmetic state file size limit");
        char bytes[MaxBytes+1];DWORD count=0;
        require(ReadFile(handle.value,bytes,sizeof(bytes),&count,nullptr) && count==size.QuadPart,"cosmetic state read changed or failed");
        return std::string(bytes,count);
    }
public:
    Store(const std::wstring& game,const std::string& profile):key(profile) {
        require(profileKey(key),"invalid local cosmetic profile key");
        require(!game.empty() && (game.back()==L'\\' || game.back()==L'/'),"cosmetic game directory requires absolute trailing separator");
        wchar_t absolute[32768];const DWORD length=GetFullPathNameW(game.c_str(),32768,absolute,nullptr);
        require(length && length<32768 && std::wstring(absolute)==game,"cosmetic state game directory is not canonical");
        const auto base=game+L".battleaces-resurrection";baseHandle.value=directory(base);
        folder=base+L"\\profiles";folderHandle.value=directory(folder);
        const std::wstring wide(key.begin(),key.end());target=folder+L"\\"+wide+L".cosmetics.json";
        const auto lock=folder+L"\\"+wide+L".cosmetics.lock";
        lockHandle.value=CreateFileW(lock.c_str(),GENERIC_READ|GENERIC_WRITE,FILE_SHARE_READ,nullptr,OPEN_ALWAYS,
            FILE_ATTRIBUTE_NORMAL|FILE_FLAG_OPEN_REPARSE_POINT,nullptr);
        require(lockHandle.value!=INVALID_HANDLE_VALUE,"cosmetic profile already in use or unavailable");regular(lockHandle.value);
    }
    const std::wstring& path() const {return target;}
    std::optional<std::string> load() {previous=read();observed=true;return previous;}
    void save(const std::string& bytes) {
        require(observed,"cosmetic store must load before saving");const State state=decode(bytes);
        require(state.profile==key,"cosmetic state profile mismatch");
        require(read()==previous,"cosmetic state changed outside this process");
        const auto temporary=target+L"."+std::to_wstring(GetCurrentProcessId())+L"."+std::to_wstring(++sequence)+L".tmp";
        Handle handle(CreateFileW(temporary.c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr));
        require(handle.value!=INVALID_HANDLE_VALUE,"cannot create cosmetic save temporary file");
        DWORD written=0;const bool good=WriteFile(handle.value,bytes.data(),static_cast<DWORD>(bytes.size()),&written,nullptr) &&
            written==bytes.size() && FlushFileBuffers(handle.value);
        CloseHandle(handle.value);handle.value=INVALID_HANDLE_VALUE;
        if(!good){DeleteFileW(temporary.c_str());throw std::runtime_error("cosmetic save write/flush failed");}
        if(!MoveFileExW(temporary.c_str(),target.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)) {
            DeleteFileW(temporary.c_str());throw std::runtime_error("cosmetic atomic save replacement failed");
        }
        previous=bytes;
    }
};
}
