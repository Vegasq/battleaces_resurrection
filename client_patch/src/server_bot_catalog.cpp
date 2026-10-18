#pragma once
// Included inside ba_export. All values come from locally installed tables;
// this file contains no recovered names, decks or cosmetic inventories.
namespace bot_catalog {
using ba_tables::require;
static auto& characters=*new ba_tables::Table("AICharacter","AICharacterTable","524d3ead68bbbbc48bdbc8a383e4c934");
static auto& slots=*new ba_tables::Table("CosmeticSlot","CosmeticSlotTable","80afad8f743498b4881dccafa8ebb850");
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
        if(match){require(!selected,"bot export ambiguous resource method");selected=method;}
    }
    require(selected!=nullptr,"bot export resource method missing");return selected;
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
    require(method!=nullptr,"bot export localization handle method missing");
    return ba_local::invokeMethod(method,unbox(boxed),nullptr);
}
static bool ready() {
    const bool a=ba_public_bots::ready(),b=characters.ready(),c=slots.ready();if(!a || !b || !c)return false;
    if(namesComplete)return true;
    if(!namesBegan) {
        namesBegan=GetTickCount64();Root table(characters.get()),elements(ba::call(table.get(),"get_Elements"));
        const size_t count=ba_catalog::length(elements.get());require(count>0 && count<=256,"bot export character count invalid");
        for(size_t i=0;i<count;++i) {
            Root character(ba_catalog::arrayAt(elements.get(),i)),id(ba::call(character.get(),"get_ID"));
            Root definition(ba::get<Obj>(character.get(),"AICharacterDefinition"));
            Root localized(ba::get<Obj>(definition.get(),"CharacterName"));require(localized.get()!=nullptr,"bot export character localization missing");
            Root generic(ba::call(localized.get(),"GetLocalizedStringAsync"));
            require(generic.get()!=nullptr,"bot export localization operation missing");
            void* convertArgs[]={unbox(generic.get())};
            Root handle(ba::invoke(ba::klass(generic.get()),nullptr,"op_Implicit",1,convertArgs));
            Root manager(ba::invoke(ba::find_class("UnityEngine.AddressableAssets","Addressables"),nullptr,"get_ResourceManager",0));
            require(handle.get() && manager.get(),"bot export localization resource missing");
            // The localization operation auto-releases next frame. A GC root
            // preserves the boxed value but not the operation: acquire one ref.
            nameOperations.emplace_back(std::make_unique<NameOperation>(ba_catalog::unbox<uint32_t>(id.get()),handle.get(),manager.get()));
        }
    }
    require(GetTickCount64()-namesBegan<30000,"bot export character localization deadline");
    for(const auto& entry:nameOperations) {
        Root done(handleCall(entry->handle.get(),"get_IsDone"));if(!ba_tables::boolean(done.get()))return false;
    }
    for(const auto& entry:nameOperations) {
        Root status(handleCall(entry->handle.get(),"get_Status"));require(ba_catalog::unbox<int>(status.get())==1,"bot export character localization failed");
        Root value(handleCall(entry->handle.get(),"get_Result"));const auto name=ba_catalog::utf8(value.get());
        require(!name.empty() && name.size()<=96,"bot export localized character name invalid");characterNames.emplace_back(entry->id,name);entry->release();
    }
    cleanup();namesComplete=true;
    return true;
}
static size_t size(Obj array,size_t maximum) {
    require(array!=nullptr,"bot export array missing");
    const size_t result=ba_catalog::length(array);require(result<=maximum,"bot export array limit");return result;
}
static std::string hex(const Bytes& bytes) {
    const char* alphabet="0123456789abcdef";std::string result;result.reserve(bytes.size()*2);
    for(unsigned char value:bytes){result+=alphabet[value>>4];result+=alphabet[value&15];}return result;
}
static Bytes protoBytes(Obj value) {
    void* args[]={value};Root array(ba::invoke(ba::find_class("Google.Protobuf","MessageExtensions"),nullptr,"ToByteArray",1,args));
    return arrayBytes(array.get(),65536);
}
static std::string integerArray(Obj array,size_t maximum) {
    std::string result="[";const size_t count=size(array,maximum);
    for(size_t i=0;i<count;++i) {
        const uint32_t id=ba::read<uint32_t>(array,0x20+i*4);
        require(id && ba_public_bots::cosmetics.at(id),"bot export cosmetic does not resolve");
        if(i)result+=',';result+=std::to_string(id);
    }
    return result+"]";
}
static std::string deck(Obj choice) {
    const int type=ba::get<int>(choice,"Type");require(type>=0 && type<=2,"bot export unknown deck kind");
    Root shared(ba::call(choice,"GetDeck"));require(shared.get()!=nullptr,"bot export deck resolution failed");
    Root copy(ba::make("Uncapped","Deck"));void* copyArgs[]={shared.get()};ba::call(copy.get(),"CopyFromDeck",1,copyArgs);
    Root proto(ba_dedicated_deck::proto(copy.get()));
    uint32_t reference=0,portrait=0,banner=0;std::string name;
    if(type==1) {
        reference=ba::read<uint32_t>(choice,0x20);Root character(characters.at(reference));
        require(character.get()!=nullptr,"bot export character missing");
        Root definition(ba::get<Obj>(character.get(),"AICharacterDefinition"));
        require(definition.get()!=nullptr,"bot export character definition missing");
        for(const auto& entry:characterNames)if(entry.first==reference){name=entry.second;break;}
        require(!name.empty() && name.size()<=96,"bot export character name invalid");
        Root cosmetics(ba::get<Obj>(definition.get(),"Cosmetics"));require(cosmetics.get()!=nullptr,"bot export character cosmetics missing");
        Obj cls=ba::find_class("Uncapped","CosmeticsUtils");
        Obj method=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(cls,"AddCosmeticsEntitlements",3);
        require(method!=nullptr,"bot export cosmetic helper missing");
        Root reflected(ba::api<Obj(*)(Obj,Obj)>("il2cpp_method_get_object")(method,cls));
        Root parameters(ba::call(reflected.get(),"GetParameters"));
        require(ba_catalog::length(parameters.get())==3,"bot export cosmetic helper signature changed");
        Root parameter(ba_catalog::arrayAt(parameters.get(),1)),byRef(ba::call(parameter.get(),"get_ParameterType"));
        Root listType(ba::call(byRef.get(),"GetElementType"));require(listType.get()!=nullptr,"bot export entitlement ref type missing");
        Obj listClass=ba::api<Obj(*)(Obj)>("il2cpp_class_from_system_type")(listType.get());
        require(listClass!=nullptr,"bot export entitlement list class missing");
        ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(listClass);
        Root ownedList(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(listClass));ba::invoke(listClass,ownedList.get(),".ctor",0);
        // The original Deck.ToProtoRuntime constructs this list first. The
        // helper allocates entries, but dereferences (and never creates) list.
        Obj generated=ownedList.get();bool allowUnowned=true;void* args[]={cosmetics.get(),&generated,&allowUnowned};
        ba_local::invokeMethod(method,nullptr,args);Root entitlements(generated);
        require(generated==ownedList.get(),"bot export cosmetic helper replaced owned list");
        const int count=ba_local::count(entitlements.get());require(count>=0 && count<=64,"bot export entitlement count invalid");
        Obj target=ba::get<Obj>(proto.get(),"entitlements_");require(ba_local::count(target)==0,"bot export deck unexpectedly includes entitlements");
        for(int i=0;i<count;++i) {
            Obj entitlement=ba_bootstrap::item(entitlements.get(),i);ba_local::addItem(target,entitlement);
            Obj keys=ba::get<Obj>(entitlement,"cosmeticAssetKeys_");const int keyCount=ba_local::count(keys);
            require(keyCount>=0 && keyCount<=128,"bot export cosmetic key count limit");
            for(int k=0;k<keyCount;++k) {
                const auto id=ba_lan_bootstrap::uintAt(keys,k);Root item(ba_public_bots::cosmetics.at(id));
                require(item.get()!=nullptr,"bot export cosmetic key missing");Root definition(ba::call(item.get(),"get_Definition"));
                const auto label=ba::get<uint32_t>(definition.get(),"Label");
                if(label==2){require(!portrait,"bot export duplicate portrait");portrait=id;}
                if(label==3){require(!banner,"bot export duplicate banner");banner=id;}
            }
        }
        require(portrait && banner,"bot export effective appearance missing");
    } else if(type==2)reference=ba::read<uint32_t>(choice,0x24);
    return "{\"kind\":"+std::to_string(type)+",\"reference\":"+std::to_string(reference)+
        ",\"name\":"+ba_catalog::quote(name)+",\"portrait\":"+std::to_string(portrait)+",\"banner\":"+std::to_string(banner)+
        ",\"deck_hex\":"+ba_catalog::quote(hex(protoBytes(proto.get())))+"}";
}
static std::string weights(Obj array,int mode,std::vector<uint32_t>& referenced) {
    std::string result="[";const size_t count=size(array,128);bool first=true;
    for(size_t i=0;i<count;++i) {
        Obj row=ba_catalog::arrayAt(array,i);require(row!=nullptr,"bot export profile row missing");
        const uint32_t id=ba::get<uint32_t>(row,"AiProfile"),weight=ba::get<uint32_t>(row,"_weight");
        Root profile(ba_public_bots::profiles.at(id));require(profile.get() && ba::get<int>(profile.get(),"GameMode")==mode,"bot export mode/profile mismatch");
        if(!weight || !ba::get<bool>(profile.get(),"Enable"))continue;
        require(weight<=1000000,"bot export weight limit");
        if(!first)result+=',';first=false;
        result+="{\"profile\":"+std::to_string(id)+",\"weight\":"+std::to_string(weight)+"}";
        if(std::find(referenced.begin(),referenced.end(),id)==referenced.end())referenced.push_back(id);
    }
    return result+"]";
}
static Bytes serialize() {
    require(ready(),"bot export tables not ready");
    Root management(ba_public_bots::management.get());
    Obj modes=ba::get<Obj>(management.get(),"_profilesByGameMode");std::string modeRows,profileRows;
    std::vector<uint32_t> referenced;std::vector<int> seen;
    for(size_t i=0;i<size(modes,32);++i) {
        Obj row=ba_catalog::arrayAt(modes,i);require(row!=nullptr,"bot export mode row missing");
        const int mode=ba::get<int>(row,"_gameMode");if(mode!=1 && mode!=2 && mode!=4 && mode!=5)continue;
        require(std::find(seen.begin(),seen.end(),mode)==seen.end(),"bot export duplicate mode");seen.push_back(mode);
        const auto opponents=weights(ba::get<Obj>(row,"_opponentAIProfilesByWeight"),mode,referenced);
        const auto teammates=weights(ba::get<Obj>(row,"_teammateAIProfilesByWeight"),mode,referenced);
        if(!modeRows.empty())modeRows+=',';
        modeRows+="{\"mode\":"+std::to_string(mode)+",\"opponents\":"+opponents+",\"teammates\":"+teammates+"}";
    }
    require(seen.size()==4,"bot export required modes missing");
    for(uint32_t id:referenced) {
        Root profile(ba_public_bots::profiles.at(id));Root definition(ba::get<Obj>(profile.get(),"AIConfigDefinition"));
        require(definition.get()!=nullptr,"bot export profile definition missing");
        Obj choices=ba::get<Obj>(definition.get(),"_decks");const size_t count=size(choices,128);require(count>0,"bot export empty decks");
        std::string decks;
        for(size_t i=0;i<count;++i){if(i)decks+=',';decks+=deck(ba_catalog::arrayAt(choices,i));}
        if(!profileRows.empty())profileRows+=',';
        profileRows+="{\"profile\":"+std::to_string(id)+",\"mode\":"+std::to_string(ba::get<int>(profile.get(),"GameMode"))+
            ",\"decks\":["+decks+"]}";
    }
    std::string names;Root namesConfig(ba::get<Obj>(management.get(),"_nameConfig"));require(namesConfig.get()!=nullptr,"bot export name config missing");
    Obj english=ba::get<Obj>(namesConfig.get(),"_englishNames");const size_t nameCount=size(english,100000);require(nameCount>0,"bot export names missing");
    for(size_t i=0;i<nameCount;++i){if(i)names+=',';names+=ba_catalog::quote(ba_catalog::utf8(ba_catalog::arrayAt(english,i)));}
    Root allowed(ba::get<Obj>(management.get(),"_randomizeCosmeticOptions"));require(allowed.get()!=nullptr,"bot export cosmetic pools missing");
    const auto portraits=integerArray(ba::get<Obj>(allowed.get(),"Portrait"),1024),banners=integerArray(ba::get<Obj>(allowed.get(),"Banner"),1024);
    std::string allCosmetics;Root cosmeticTable(ba_public_bots::cosmetics.get()),elements(ba::call(cosmeticTable.get(),"get_Elements"));
    const size_t cosmeticCount=size(elements.get(),4096);
    for(size_t i=0;i<cosmeticCount;++i) {
        Root id(ba::call(ba_catalog::arrayAt(elements.get(),i),"get_ID"));if(i)allCosmetics+=',';
        allCosmetics+=std::to_string(ba_catalog::unbox<uint32_t>(id.get()));
    }
    std::string strengths;
    for(uint32_t id:{17u,18u,19u}) {
        Root profile(ba_public_bots::profiles.at(id)),definition(ba::get<Obj>(profile.get(),"AIConfigDefinition"));
        require(ba::get<bool>(profile.get(),"Enable") && ba::get<int>(profile.get(),"GameMode")==4,"bot export strength profile mismatch");
        Obj rows=ba::get<Obj>(definition.get(),"_cheatModifiersByRating");require(size(rows,16)==1,"bot export strength row mismatch");
        Root strength(ba::call(ba::get<Obj>(ba_catalog::arrayAt(rows,0),"CheatModifier"),"ToProto"));
        if(!strengths.empty())strengths+=',';
        strengths+="{\"profile\":"+std::to_string(id)+",\"resource_q\":"+std::to_string(ba::get<int64_t>(strength.get(),"resourceMultiplier_"))+
            ",\"damage_q\":"+std::to_string(ba::get<int64_t>(strength.get(),"armyDamageMultiplier_"))+
            ",\"health_q\":"+std::to_string(ba::get<int64_t>(strength.get(),"armyHealthMultiplier_"))+"}";
    }
    const std::string text="{\"schema\":1,\"build\":37822,\"names_language\":\"en\",\"character_names_language\":\"exporting_client_locale\","
        "\"modes\":["+modeRows+"],\"profiles\":["+profileRows+"],\"names\":["+names+"],\"portraits\":"+portraits+
        ",\"banners\":"+banners+",\"cosmetic_ids\":["+allCosmetics+"],\"strengths\":["+strengths+"]}\n";
    require(text.size()<=4*1024*1024,"bot export catalog size limit");return Bytes(text.begin(),text.end());
}
static Bytes exportFile() {
    Bytes result=serialize();require(result==serialize(),"bot export catalog is not repeatable");
    atomicWrite(path(L"bot-catalog.json"),result.data(),result.size());
    note("Bot catalog exported from original mode pools, copied decks, names, cosmetics and difficulty modifiers.");return result;
}
}
