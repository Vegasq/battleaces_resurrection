#pragma once
// Shared installed character/localization reader, factored from the qualified
// server catalog exporter. AsyncOperationHandle refs outlive the load callback.
namespace ba_bot_characters {
using ba::Obj;using ba_local::Root;using ba_tables::require;
static auto& characters=*new ba_tables::Table("AICharacter","AICharacterTable","524d3ead68bbbbc48bdbc8a383e4c934");
static auto& characterNames=*new std::vector<std::pair<uint32_t,std::string>>();
static ULONGLONG namesBegan=0;
static bool namesComplete=false;
static Obj unbox(Obj boxed) {return ba::api<Obj(*)(Obj)>("il2cpp_object_unbox")(boxed);}
static Obj resourceMethod(Obj manager,const char* name) {
    // ResourceManager also has generic overloads. Select its non-generic
    // AsyncOperationHandle parameter explicitly rather than by arity alone.
    Obj selected=nullptr;void* iterator=nullptr;
    while(Obj method=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_methods")(ba::klass(manager),&iterator)) {
        if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_method_get_name")(method),name) ||
           ba::api<uint32_t(*)(Obj)>("il2cpp_method_get_param_count")(method)!=1)continue;
        Obj type=ba::api<Obj(*)(Obj,uint32_t)>("il2cpp_method_get_param")(method,0);
        char* typeName=ba::api<char*(*)(Obj)>("il2cpp_type_get_name")(type);
        const bool match=typeName && !strcmp(typeName,"UnityEngine.ResourceManagement.AsyncOperations.AsyncOperationHandle");
        if(typeName)ba::api<void(*)(void*)>("il2cpp_free")(typeName);
        if(match){require(!selected,"bot character ambiguous resource method");selected=method;}
    }
    require(selected!=nullptr,"bot character resource method missing");return selected;
}
struct NameOperation {
    uint32_t id;Root handle,manager;Obj releaseMethod;bool acquired=false;
    NameOperation(uint32_t key,Obj nonGeneric,Obj resourceManager):id(key),handle(nonGeneric),manager(resourceManager),
        releaseMethod(resourceMethod(manager.get(),"Release")) {
        void* args[]={unbox(handle.get())};ba_local::invokeMethod(resourceMethod(manager.get(),"Acquire"),manager.get(),args);acquired=true;
    }
    void release() {
        if(!acquired)return;acquired=false;
        void* args[]={unbox(handle.get())};ba_local::invokeMethod(releaseMethod,manager.get(),args);
    }
    ~NameOperation() {try{release();}catch(const std::exception& error){ba::log("Bot export localization release: %s",error.what());}}
};
static auto& nameOperations=*new std::vector<std::unique_ptr<NameOperation>>();
static void cleanup() {nameOperations.clear();}
static Obj handleCall(Obj boxed,const char* name) {
    Obj method=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(ba::klass(boxed),name,0);
    require(method!=nullptr,"bot character localization handle method missing");
    return ba_local::invokeMethod(method,unbox(boxed),nullptr);
}
static bool ready() {
    if(!characters.ready())return false;
    if(namesComplete)return true;
    if(!namesBegan) {
        namesBegan=GetTickCount64();Root table(characters.get()),elements(ba::call(table.get(),"get_Elements"));
        const size_t count=ba_catalog::length(elements.get());require(count>0 && count<=256,"bot character count invalid");
        for(size_t i=0;i<count;++i) {
            Root character(ba_catalog::arrayAt(elements.get(),i)),id(ba::call(character.get(),"get_ID"));
            Root definition(ba::get<Obj>(character.get(),"AICharacterDefinition"));
            Root localized(ba::get<Obj>(definition.get(),"CharacterName"));require(localized.get()!=nullptr,"bot character localization missing");
            Root generic(ba::call(localized.get(),"GetLocalizedStringAsync"));
            require(generic.get()!=nullptr,"bot character localization operation missing");
            void* convertArgs[]={unbox(generic.get())};
            Root handle(ba::invoke(ba::klass(generic.get()),nullptr,"op_Implicit",1,convertArgs));
            Root manager(ba::invoke(ba::find_class("UnityEngine.AddressableAssets","Addressables"),nullptr,"get_ResourceManager",0));
            require(handle.get() && manager.get(),"bot character localization resource missing");
            // The localization operation auto-releases next frame. A GC root
            // preserves the boxed value but not the operation: acquire one ref.
            nameOperations.emplace_back(std::make_unique<NameOperation>(ba_catalog::unbox<uint32_t>(id.get()),handle.get(),manager.get()));
        }
    }
    require(GetTickCount64()-namesBegan<30000,"bot character localization deadline");
    for(const auto& entry:nameOperations) {
        Root done(handleCall(entry->handle.get(),"get_IsDone"));if(!ba_tables::boolean(done.get()))return false;
    }
    for(const auto& entry:nameOperations) {
        Root status(handleCall(entry->handle.get(),"get_Status"));require(ba_catalog::unbox<int>(status.get())==1,"bot character localization failed");
        Root value(handleCall(entry->handle.get(),"get_Result"));const auto name=ba_catalog::utf8(value.get());
        require(!name.empty() && name.size()<=96,"bot character localized character name invalid");characterNames.emplace_back(entry->id,name);entry->release();
    }
    cleanup();namesComplete=true;
    return true;
}
static std::pair<uint32_t,uint32_t> appearance(Obj definition,Obj proto,ba_tables::Table& cosmeticTable) {
    uint32_t portrait=0,banner=0;
    Root cosmetics(ba::get<Obj>(definition,"Cosmetics"));require(cosmetics.get()!=nullptr,"bot character cosmetics missing");
    Obj cls=ba::find_class("Uncapped","CosmeticsUtils");
    Obj method=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(cls,"AddCosmeticsEntitlements",3);
    require(method!=nullptr,"bot character cosmetic helper missing");
    Root reflected(ba::api<Obj(*)(Obj,Obj)>("il2cpp_method_get_object")(method,cls));
    Root parameters(ba::call(reflected.get(),"GetParameters"));
    require(ba_catalog::length(parameters.get())==3,"bot character cosmetic helper signature changed");
    Root parameter(ba_catalog::arrayAt(parameters.get(),1)),byRef(ba::call(parameter.get(),"get_ParameterType"));
    Root listType(ba::call(byRef.get(),"GetElementType"));require(listType.get()!=nullptr,"bot character entitlement ref type missing");
    Obj listClass=ba::api<Obj(*)(Obj)>("il2cpp_class_from_system_type")(listType.get());
    require(listClass!=nullptr,"bot character entitlement list class missing");
    ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(listClass);
    Root ownedList(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(listClass));ba::invoke(listClass,ownedList.get(),".ctor",0);
    // The original Deck.ToProtoRuntime constructs this list first. The
    // helper allocates entries, but dereferences (and never creates) list.
    Obj generated=ownedList.get();bool allowUnowned=true;void* args[]={cosmetics.get(),&generated,&allowUnowned};
    ba_local::invokeMethod(method,nullptr,args);Root entitlements(generated);
    require(generated==ownedList.get(),"bot character cosmetic helper replaced owned list");
    const int count=ba_local::count(entitlements.get());require(count>=0 && count<=64,"bot character entitlement count invalid");
    Obj target=ba::get<Obj>(proto,"entitlements_");require(ba_local::count(target)==0,"bot character deck unexpectedly includes entitlements");
    for(int i=0;i<count;++i) {
        Obj entitlement=ba_bootstrap::item(entitlements.get(),i);ba_local::addItem(target,entitlement);
        Obj keys=ba::get<Obj>(entitlement,"cosmeticAssetKeys_");const int keyCount=ba_local::count(keys);
        require(keyCount>=0 && keyCount<=128,"bot character cosmetic key count limit");
        for(int k=0;k<keyCount;++k) {
            const auto id=ba_lan_bootstrap::uintAt(keys,k);Root item(cosmeticTable.at(id));
            require(item.get()!=nullptr,"bot character cosmetic key missing");Root cosmeticDefinition(ba::call(item.get(),"get_Definition"));
            const auto label=ba::get<uint32_t>(cosmeticDefinition.get(),"Label");
            if(label==2){require(!portrait,"bot character duplicate portrait");portrait=id;}
            if(label==3){require(!banner,"bot character duplicate banner");banner=id;}
        }
    }
    require(portrait && banner,"bot character effective appearance missing");
    return {portrait,banner};
}
static const std::string& name(uint32_t id) {
    for(const auto& entry:characterNames)if(entry.first==id)return entry.second;
    throw std::runtime_error("bot character localized name missing");
}
}
