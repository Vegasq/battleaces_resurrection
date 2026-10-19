#pragma once
#include "native_settings_atomic.hpp"
namespace ba_native_settings {
static bool saveIsolated(ba::Obj loader,ba::Obj path,ba::Obj table,void* method,unsigned long long sequence) {
    // Retain synchronization until OS exit,including native engine teardown.
    static auto& writer=*new SaveGate();SaveGate::Lease lease(writer);
    const auto finish=[sequence](bool okay) noexcept {lastSaveSucceeded.record(sequence,okay);return okay;};
    if(!lease.acquired()){ba::log("NATIVE SETTINGS atomic save refused: concurrent/reentrant writer");return finish(false);}
    try {
        require(sequence && sequence<=(~0ull>>1),"native settings save sequence exhausted");
        require(!lastSaveSucceeded.newerThan(sequence),"native settings older request superseded before writer admission");
        using ba_local::Root;Root loaderRoot(loader),pathRoot(path),tableRoot(table);
        require(session && !session->inputProtected(),"native save publication before input acceptance");
        WriteTransaction transaction(session->path());
        Root temporary(ba::api<ba::Obj(*)(const wchar_t*,int32_t)>("il2cpp_string_new_utf16")(
            transaction.path().data(),static_cast<int32_t>(transaction.path().size())));
        require(temporary.get()!=nullptr,"native save temporary managed path allocation failed");
        const bool serialized=ba::native<bool(*)(void*,void*,void*,void*)>(0x3796060)(loaderRoot.get(),temporary.get(),tableRoot.get(),method);
        if(!serialized){ba::log("NATIVE SETTINGS atomic save refused: original serializer failed published=0 inPlaceFallback=0");return finish(false);}
        require(!lastSaveSucceeded.newerThan(sequence),"native settings save superseded during serialization");
        transaction.commit();ba::log("NATIVE SETTINGS atomic save published: originalSerializer=1 flushed=1 BA_RESURRECTION_NATIVE_SETTINGS_ATOMIC_V1");
        return finish(true); // Complete before releasing the serialization gate.
    }catch(const std::exception& error) {
        ba::log("NATIVE SETTINGS atomic save refused: %s; published=0 inPlaceFallback=0",error.what());return finish(false);
    }
}
}
