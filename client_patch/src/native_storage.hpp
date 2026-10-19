#pragma once
#include "native_settings.hpp"
namespace ba_native_storage {
enum class Kind { Replays, Backup };
// Session must outlive its children: it pins the installation/profile ancestors.
// Pin these directories too; the original game still owns child-file I/O.
class Directory {
    Kind storageKind;
    std::wstring selected;
    ba_native_settings::Handle handle;
public:
    Directory(const ba_native_settings::Session& session,Kind kind):storageKind(kind) {
        using namespace ba_native_settings;
        const wchar_t* name=nullptr;
        switch(kind) {
        case Kind::Replays:name=L"AutoSaveReplays";break;
        case Kind::Backup:name=L"StorageSyncBackup";break;
        default:throw std::runtime_error("invalid native storage kind");
        }
        const auto slash=session.path().find_last_of(L'\\');
        require(slash!=std::wstring::npos,"native storage profile parent missing");
        selected=session.path().substr(0,slash+1)+name;
        require(selected.size()<MAX_PATH,"native storage directory exceeds native path limit");
        handle.value=ba_cosmetics_state::directory(selected);exactDirectory(handle.value,selected);
    }
    const std::wstring& path() const{return selected;}
    std::wstring apiPath() const {
        if(storageKind==Kind::Backup)return selected;
        // Extend only the already validated/pinned local-drive replay folder.
        // Native team filenames can exceed MAX_PATH although the folder cannot.
        ba_native_settings::require(selected.size()>3 && selected[1]==L':' && selected[2]==L'\\',
            "extended replay path requires an absolute local directory");
        return L"\\\\?\\"+selected;
    }
};
}
