#pragma once
// Offline preferences belong to this patched installation, never the original
// Region variable. UI changes affect the next match; practice snapshots them.
namespace ba_practice_settings {
using ba::Obj;using ba_local::Root;
static uint32_t selected=18;
static bool initialized=false;
static const char* name(uint32_t value) {
    if(value==17)return "easy";if(value==18)return "normal";if(value==19)return "hard";
    throw std::runtime_error("invalid practice difficulty");
}
static uint32_t profile(const std::string& value) {
    if(value=="17")return 17;if(value=="18")return 18;if(value=="19")return 19;
    throw std::runtime_error("practice AI profile must be17,18 or19");
}
static std::wstring settingsPath() {
    wchar_t path[32768];const DWORD length=GetModuleFileNameW(ba::module,path,32768);
    if(!length || length>=32768)throw std::runtime_error("practice settings installation path unavailable");
    wchar_t* slash=wcsrchr(path,L'\\');if(!slash)throw std::runtime_error("practice settings installation path invalid");
    *(slash+1)=0;return std::wstring(path)+L".battleaces-resurrection\\practice-settings.ini";
}
static std::string contents(uint32_t value) {return std::string("schema=1\r\ndifficulty=")+name(value)+"\r\n";}
static bool load(uint32_t& value) {
    const auto path=settingsPath();
    HANDLE file=CreateFileW(path.c_str(),GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(file==INVALID_HANDLE_VALUE) {
        const DWORD error=GetLastError();
        if(error!=ERROR_FILE_NOT_FOUND)ba::log("Practice difficulty preference unavailable: error=%lu; using default",error);
        return false;
    }
    char data[256];DWORD count=0;LARGE_INTEGER size{};
    const bool read=GetFileSizeEx(file,&size) && size.QuadPart>0 && size.QuadPart<sizeof(data) &&
        ReadFile(file,data,static_cast<DWORD>(size.QuadPart),&count,nullptr) && count==size.QuadPart;
    CloseHandle(file);
    if(read) {
        std::string text(data,count); // Accept ordinary Windows or Unix line endings.
        std::string normalized;for(char c:text)if(c!='\r')normalized+=c;
        for(uint32_t candidate:{17u,18u,19u}) {
            if(normalized==std::string("schema=1\ndifficulty=")+name(candidate)+"\n") {value=candidate;return true;}
        }
    }
    ba::log("Practice difficulty preference invalid; using default");return false;
}
static bool save(uint32_t value) {
    const auto path=settingsPath();
    const auto temporary=path+L"."+std::to_wstring(GetCurrentProcessId())+L"."+std::to_wstring(GetTickCount64())+L".tmp";
    HANDLE file=CreateFileW(temporary.c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(file==INVALID_HANDLE_VALUE) {ba::log("Practice difficulty save failed: error=%lu",GetLastError());return false;}
    const auto data=contents(value);DWORD count=0;
    bool okay=WriteFile(file,data.data(),static_cast<DWORD>(data.size()),&count,nullptr) && count==data.size() && FlushFileBuffers(file);
    DWORD error=okay?ERROR_SUCCESS:GetLastError();CloseHandle(file);
    if(okay && !MoveFileExW(temporary.c_str(),path.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)) {okay=false;error=GetLastError();}
    if(!okay) {DeleteFileW(temporary.c_str());ba::log("Practice difficulty save failed: error=%lu; session selection retained",error);}
    return okay;
}
static uint32_t selection() {
    if(!initialized) {
        selected=profile(ba::argument(L"-practice-ai-default-profile=","18"));
        const auto overrideValue=ba::argument(L"-practice-ai-profile=");
        const char* source="default";
        if(!overrideValue.empty()) {selected=profile(overrideValue);source="override";}
        else if(load(selected))source="saved";
        initialized=true;
        ba::log("Practice difficulty initialized: selected=%s profile=%u source=%s; BA_RESURRECTION_PRACTICE_SETTINGS_V1",name(selected),selected,source);
    }
    return selected;
}
static bool choose(uint32_t value) {
    name(value);selection();selected=value;
    const bool saved=save(value);
    ba::log("Practice difficulty selected: selected=%s profile=%u saved=%d applies=next-match",name(value),value,saved?1:0);
    return saved;
}
}
