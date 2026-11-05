#pragma once
// Ordinary explicit file selection. Original Replay owns loading, playback and Leave.
namespace ba_replay_entry {
using ba::Obj;using ba_local::Root;using ba_native_settings::require;
namespace codec=ba_native_replay_reader;
enum class Stage {Waiting,Playing,Done};
static Stage stage=Stage::Waiting;
static uint64_t lease=0;
static unsigned failuresBefore=0;
static bool sawWorld=false,noticeShown=false;
static bool requested() {
    static const bool value=[](){std::wstring path;return ba::flag(L"-replay-select") ||
        ba_command_line::value(ba::arguments(),L"-replay-file=",path);}();
    return value;
}
static bool safe(Obj front) {
    return GetCurrentThreadId()==ba::initialThread && ba_local_menu::ready(front) &&
        ba_dedicated_session::inMenu() && ba_client::nativeIdle(front) &&
        !ba_public::active() && !ba_practice::active() && !ba_dedicated_session::joined &&
        ba_native_quit::staticInt("LoadingCount")==0 && !ba_native_quit::wantsQuit();
}
static bool choose(std::wstring& path) {
    wchar_t buffer[32768]={};
    OPENFILENAMEW dialog{};dialog.lStructSize=sizeof(dialog);
    dialog.hwndOwner=GetActiveWindow();dialog.lpstrFile=buffer;dialog.nMaxFile=32768;
    dialog.lpstrTitle=L"Watch Battle Aces replay";
    dialog.lpstrFilter=L"Battle Aces replays (*.rep)\0*.rep\0All files (*.*)\0*.*\0\0";
    dialog.Flags=OFN_EXPLORER|OFN_FILEMUSTEXIST|OFN_PATHMUSTEXIST|OFN_NOCHANGEDIR|OFN_DONTADDTORECENT;
    if(GetOpenFileNameW(&dialog)){path=buffer;return true;}
    require(CommDlgExtendedError()==0,"Windows could not open the replay file chooser");
    return false;
}
static bool retryNotice(const wchar_t* message) {
    return MessageBoxW(GetActiveWindow(),message,L"Replay could not be opened",MB_RETRYCANCEL|MB_ICONWARNING)==IDRETRY;
}
static void open(Obj front,const std::wstring& selected) {
    require(safe(front) && ba_client::worldOwner==ba_client::Owner::None,
        "replay selection requires an idle menu without another world owner");
    require(!selected.empty() && selected.size()<32000 && selected.find_first_of(L"\r\n") == std::wstring::npos,
        "invalid replay filename");
    ba_native_settings::Handle pin(CreateFileW(selected.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,
        FILE_FLAG_OPEN_REPARSE_POINT,nullptr));ba_native_settings::ordinary(pin.value);
    require(GetFileType(pin.value)==FILE_TYPE_DISK,"choose a regular replay file on a local drive");
    LARGE_INTEGER size{};require(GetFileSizeEx(pin.value,&size) && size.QuadPart>0 && size.QuadPart<=64LL*1024*1024,
        "replay file must be nonempty and at most 64 MiB");
    wchar_t finalPath[32768];DWORD length=GetFinalPathNameByHandleW(pin.value,finalPath,32768,FILE_NAME_NORMALIZED|VOLUME_NAME_DOS);
    require(length>=7 && length<32768 && !wcsncmp(finalPath,L"\\\\?\\",4) && finalPath[5]==L':' && finalPath[6]==L'\\',
        "choose a replay file on a local drive");
    const std::wstring path(finalPath,length);
    // A second original FileStream is identity-checked against this share-read-only
    // handle. It remains pinned through both bounded admission and high-level load.
    const auto decoded=codec::decodePinned(path,pin.value,false);
    require(decoded.identity && decoded.limits && decoded.disposed==3 && !decoded.cleanupErrors && decoded.failure.empty(),
        "replay data is invalid, incomplete or exceeds supported decoding limits");
    Root replay(ba::get<Obj>(ba::owner,"<Replay>k__BackingField"));
    require(replay.get() && ba::klass(replay.get())==codec::type("Uncapped","Replay","RGame.dll"),"original replay owner missing");
    Root simulation(ba::get<Obj>(replay.get(),"_simulation"));
    require(simulation.get() && !ba::read<uint64_t>(simulation.get(),0x1a8),"replay simulation is already active");
    lease=ba_client::acquireReplay(front);failuresBefore=ba_replay_runtime::failures;
    Root managedPath(ba::api<Obj(*)(const wchar_t*,int32_t)>("il2cpp_string_new_utf16")(path.data(),static_cast<int32_t>(path.size())));
    void* args[]={managedPath.get()};
    ba::log("Replay file entry: boundedAdmission=1 originalLoadReplayFromFile=1 frames=%d BA_RESURRECTION_REPLAY_ENTRY_V1",decoded.frames);
    Root loaded(codec::invoke(codec::method(ba::klass(replay.get()),"LoadReplayFromFile",1,0x3dddab0,0x06000952),replay.get(),args));
    require(loaded.get() && ba_catalog::unbox<bool>(loaded.get()),"the original replay loader refused this file");
    stage=Stage::Playing;
}
static bool update(Obj front) {
    if(!requested() || stage==Stage::Done)return false;
    try {
        require(ba::unified() && !ba::offlinePractice() && !ba_native_replay_playback::enabled() &&
            !ba::flag(L"-native-replay-menu-smoke"),"ordinary replay entry cannot use diagnostic playback");
        if(stage==Stage::Playing) {
            Root replay(ba::get<Obj>(ba::owner,"<Replay>k__BackingField")),simulation(ba::get<Obj>(replay.get(),"_simulation"));
            sawWorld=sawWorld || ba::read<uint64_t>(simulation.get(),0x1a8)!=0;
            if(ba_replay_runtime::failures!=failuresBefore)throw std::runtime_error("original replay playback failed");
            // Original shutdown can retain decoded replay data. Its idle world,
            // unloaded assets and return to MainMenu release our lease; clearing
            // the native recording is neither required nor ours to perform.
            if(sawWorld && safe(front)) {
                ba_client::releaseReplay(front,lease);lease=0;stage=Stage::Done;
                ba::log("Replay file entry finished: originalLeave=1 idleMenu=1");return false;
            }
            return true;
        }
        if(!safe(front) || ba_client::worldOwner!=ba_client::Owner::None)return true;
        std::wstring path;
        if(!ba_command_line::value(ba::arguments(),L"-replay-file=",path) && !choose(path)) {
            stage=Stage::Done;ba::log("Replay file selection cancelled: loadCalls=0");return false;
        }
        for(;;) {
            try{open(front,path);return true;}
            catch(const std::exception& error) {
                ba::log("Replay file entry refused: %s",error.what());
                if(lease) {
                    if(!safe(front))throw;
                    ba_client::releaseReplay(front,lease);lease=0;
                }
                if(!retryNotice(L"The replay could not be read or played. Choose a complete replay on a local drive (up to 64 MiB). Close programs writing to it. Retry to choose another file, or Cancel to return to the menu.") || !choose(path)) {
                    stage=Stage::Done;return false;
                }
            }
        }
    }catch(const std::exception& error) {
        ba::log("Replay file entry stopped: %s; retaining active native owner",error.what());
        if(safe(front)) {
            if(lease){ba_client::releaseReplay(front,lease);lease=0;}
            stage=Stage::Done;
        }
        if(!noticeShown) {
            noticeShown=true;MessageBoxW(GetActiveWindow(),
                L"Replay playback failed. If a replay is still open, use Options > Leave Replay. Your saved files have not been changed.",
                L"Replay playback failed",MB_OK|MB_ICONWARNING);
        }
        return stage!=Stage::Done;
    }
}
}
