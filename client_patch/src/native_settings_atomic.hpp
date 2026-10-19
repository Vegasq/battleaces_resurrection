#pragma once
#include "native_settings.hpp"
#include <cstddef>
#include <cstring>
#include <cwchar>
#include <vector>
// Same-directory publication of bytes written by the original native serializer.
// Never repair/import an orphan temporary file or fall back to truncating target.
namespace ba_native_settings {
class SaveGate {
    std::atomic_flag busy=ATOMIC_FLAG_INIT;
public:
    class Lease {
        SaveGate& gate;bool owned;
    public:
        explicit Lease(SaveGate& value):gate(value),owned(!value.busy.test_and_set(std::memory_order_acquire)){}
        ~Lease(){if(owned)gate.busy.clear(std::memory_order_release);}
        bool acquired() const{return owned;}
        Lease(const Lease&)=delete;Lease& operator=(const Lease&)=delete;
    };
};
class WriteTransaction {
    std::wstring target,temporary;
    Handle previous,pin,ready;
    BY_HANDLE_FILE_INFORMATION oldIdentity{},tempIdentity{};
    bool existed=false,published=false;
    static bool identity(HANDLE file,const BY_HANDLE_FILE_INFORMATION& expected) {
        BY_HANDLE_FILE_INFORMATION actual{};
        return GetFileInformationByHandle(file,&actual) && actual.dwVolumeSerialNumber==expected.dwVolumeSerialNumber &&
            actual.nFileIndexHigh==expected.nFileIndexHigh && actual.nFileIndexLow==expected.nFileIndexLow;
    }
    static void close(Handle& file) {
        if(file.value==INVALID_HANDLE_VALUE)return;
        require(CloseHandle(file.value)!=0,"native save handle close failed");file.value=INVALID_HANDLE_VALUE;
    }
    static std::vector<unsigned char> security(HANDLE file) {
        constexpr auto information=OWNER_SECURITY_INFORMATION|GROUP_SECURITY_INFORMATION|DACL_SECURITY_INFORMATION;
        DWORD length=0;GetKernelObjectSecurity(file,information,nullptr,0,&length);
        require(length && GetLastError()==ERROR_INSUFFICIENT_BUFFER,"native settings original permissions unavailable");
        std::vector<unsigned char> descriptor(length);
        require(GetKernelObjectSecurity(file,information,descriptor.data(),length,&length)!=0,
            "native settings original permissions read failed");
        return descriptor;
    }
    void verifyPermissions() {
        if(!existed)return;
        auto before=security(previous.value),after=security(ready.value);
        PSID ownerBefore=nullptr,ownerAfter=nullptr,groupBefore=nullptr,groupAfter=nullptr;
        BOOL defaultedBefore=FALSE,defaultedAfter=FALSE;
        require(GetSecurityDescriptorOwner(before.data(),&ownerBefore,&defaultedBefore) &&
            GetSecurityDescriptorOwner(after.data(),&ownerAfter,&defaultedAfter) && ownerBefore && ownerAfter &&
            EqualSid(ownerBefore,ownerAfter),"native settings replacement owner differs");
        require(GetSecurityDescriptorGroup(before.data(),&groupBefore,&defaultedBefore) &&
            GetSecurityDescriptorGroup(after.data(),&groupAfter,&defaultedAfter) && groupBefore && groupAfter &&
            EqualSid(groupBefore,groupAfter),"native settings replacement group differs");
        PACL aclBefore=nullptr,aclAfter=nullptr;BOOL presentBefore=FALSE,presentAfter=FALSE;
        require(GetSecurityDescriptorDacl(before.data(),&presentBefore,&aclBefore,&defaultedBefore) &&
            GetSecurityDescriptorDacl(after.data(),&presentAfter,&aclAfter,&defaultedAfter) &&
            presentBefore==presentAfter && defaultedBefore==defaultedAfter && !!aclBefore==!!aclAfter &&
            (!aclBefore || (aclBefore->AclSize==aclAfter->AclSize && !memcmp(aclBefore,aclAfter,aclBefore->AclSize))),
            "native settings replacement permissions differ from inherited profile permissions");
        SECURITY_DESCRIPTOR_CONTROL controlBefore=0,controlAfter=0;DWORD revision=0;
        constexpr auto mask=SE_DACL_PROTECTED|SE_DACL_AUTO_INHERITED|SE_DACL_AUTO_INHERIT_REQ;
        require(GetSecurityDescriptorControl(before.data(),&controlBefore,&revision) &&
            GetSecurityDescriptorControl(after.data(),&controlAfter,&revision) && (controlBefore&mask)==(controlAfter&mask),
            "native settings replacement permission inheritance differs");
    }
public:
    explicit WriteTransaction(const std::wstring& destination):target(destination) {
        previous.value=CreateFileW(target.c_str(),GENERIC_READ|GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_DELETE,nullptr,
            OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL|FILE_FLAG_OPEN_REPARSE_POINT,nullptr);
        if(previous.value==INVALID_HANDLE_VALUE)require(GetLastError()==ERROR_FILE_NOT_FOUND,"native settings replacement target unavailable");
        else {
            ordinary(previous.value);require(GetFileInformationByHandle(previous.value,&oldIdentity)!=0,"native settings target identity unavailable");
            require(!(oldIdentity.dwFileAttributes&(FILE_ATTRIBUTE_READONLY|FILE_ATTRIBUTE_HIDDEN|FILE_ATTRIBUTE_SYSTEM)),
                "native settings target attributes prohibit writing");existed=true;
        }
        const auto slash=target.find_last_of(L'\\');require(slash!=std::wstring::npos,"native save target directory missing");
        static std::atomic<unsigned> sequence{0};
        for(unsigned attempt=0;attempt<16;++attempt) {
            const unsigned next=++sequence;require(next!=0,"native save temporary sequence exhausted");
            wchar_t name[32];swprintf_s(name,L"ba-%08lx-%08x.tmp",GetCurrentProcessId(),next);
            temporary=target.substr(0,slash+1)+name;require(temporary.size()<MAX_PATH,"native save temporary path too long");
            // Read handle allows the original StreamWriter's share-read
            // open,while denying deletion/replacement throughout serialization.
            pin.value=CreateFileW(temporary.c_str(),GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE,nullptr,
                CREATE_NEW,FILE_ATTRIBUTE_NORMAL|FILE_FLAG_OPEN_REPARSE_POINT,nullptr);
            if(pin.value!=INVALID_HANDLE_VALUE)break;
            require(GetLastError()==ERROR_FILE_EXISTS || GetLastError()==ERROR_ALREADY_EXISTS,"native save temporary creation failed");
        }
        require(pin.value!=INVALID_HANDLE_VALUE,"native save temporary name collisions");ordinary(pin.value);
        require(GetFileInformationByHandle(pin.value,&tempIdentity)!=0,"native save temporary identity unavailable");
    }
    ~WriteTransaction() {
        if(published || temporary.empty())return;
        // Reopen only this owned identity;never delete a substituted pathname.
        if(pin.value!=INVALID_HANDLE_VALUE){CloseHandle(pin.value);pin.value=INVALID_HANDLE_VALUE;}
        if(ready.value==INVALID_HANDLE_VALUE)ready.value=CreateFileW(temporary.c_str(),DELETE|FILE_READ_ATTRIBUTES,FILE_SHARE_READ,
            nullptr,OPEN_EXISTING,FILE_FLAG_OPEN_REPARSE_POINT,nullptr);
        if(ready.value!=INVALID_HANDLE_VALUE && identity(ready.value,tempIdentity)) {
            FILE_DISPOSITION_INFO remove{TRUE};SetFileInformationByHandle(ready.value,FileDispositionInfo,&remove,sizeof(remove));
        }
        // Cleanup failures leave an ignored orphan;no automatic recovery/import.
    }
    WriteTransaction(const WriteTransaction&)=delete;WriteTransaction& operator=(const WriteTransaction&)=delete;
    const std::wstring& path() const{return temporary;}
    void commit() {
        require(!published && ready.value==INVALID_HANDLE_VALUE,"native save transaction already committed");
        // Original Save has already closed its stream. The reopened exclusive
        // writer/deleter must still be the created file before any flush/rename.
        close(pin);
        ready.value=CreateFileW(temporary.c_str(),GENERIC_READ|GENERIC_WRITE|DELETE,FILE_SHARE_READ,nullptr,
            OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL|FILE_FLAG_OPEN_REPARSE_POINT,nullptr);
        if(ready.value==INVALID_HANDLE_VALUE)throw std::runtime_error("native save output reopen failed Win32="+std::to_string(GetLastError()));
        ordinary(ready.value);require(identity(ready.value,tempIdentity),"native save temporary identity changed");
        LARGE_INTEGER size{};require(GetFileSizeEx(ready.value,&size) && size.QuadPart>0 && size.QuadPart<=16*1024*1024,
            "native save output size invalid");
        if(existed) {
            Handle current(CreateFileW(target.c_str(),FILE_READ_ATTRIBUTES,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,
                nullptr,OPEN_EXISTING,FILE_FLAG_OPEN_REPARSE_POINT,nullptr));ordinary(current.value);
            require(identity(current.value,oldIdentity),"native settings target changed outside this save");
        }
        verifyPermissions();require(FlushFileBuffers(ready.value)!=0,"native settings output flush failed");
        const size_t bytes=target.size()*sizeof(wchar_t);
        std::vector<unsigned char> buffer(offsetof(FILE_RENAME_INFO,FileName)+bytes+sizeof(wchar_t),0);
        auto rename=reinterpret_cast<FILE_RENAME_INFO*>(buffer.data());rename->ReplaceIfExists=existed;
        rename->FileNameLength=static_cast<DWORD>(bytes);memcpy(rename->FileName,target.c_str(),bytes);
        // Release the old-file validation handle before classic replacement.
        // Session's separate profile lock remains held. External edits during
        // this publication boundary are unsupported;no hostile-process claim.
        close(previous);
        if(!SetFileInformationByHandle(ready.value,FileRenameInfo,rename,static_cast<DWORD>(buffer.size())))
            throw std::runtime_error("native settings output publication failed Win32="+std::to_string(GetLastError()));
        published=true; // No fallible work after publication;never undo a new save.
    }
};
}
