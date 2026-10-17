#pragma once
// Optional read-only export of loaded shipped assets. Include after ba_local.
// Call ba_catalog::exportOnce() after initial tables and localization complete.
// It is inert unless -export-unit-catalog is present. No game/profile mutations.
namespace ba_catalog {
using ba::Obj;using ba_local::Root;
static std::string utf8(Obj value) {
    if(!value)return {};
    const wchar_t* chars=ba::api<const wchar_t*(*)(Obj)>("il2cpp_string_chars")(value);
    const int length=ba::api<int(*)(Obj)>("il2cpp_string_length")(value);
    int bytes=WideCharToMultiByte(CP_UTF8,0,chars,length,nullptr,0,nullptr,nullptr);
    std::string result(bytes,'\0');if(bytes)WideCharToMultiByte(CP_UTF8,0,chars,length,&result[0],bytes,nullptr,nullptr);return result;
}
static std::string quote(const std::string& value) {
    std::string result="\"";char escape[8];
    for(unsigned char ch:value) {
        if(ch=='\"' || ch=='\\'){result+='\\';result+=ch;}
        else if(ch<32){sprintf_s(escape,"\\u%04x",static_cast<unsigned>(ch));result+=escape;}
        else result+=ch;
    }
    return result+'\"';
}
template<class T> static T unbox(Obj obj) {
    if(!obj)throw std::runtime_error("catalog boxed value missing");
    return *ba::api<T*(*)(Obj)>("il2cpp_object_unbox")(obj);
}
static size_t length(Obj array) {return array?ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(array):0;}
static Obj arrayAt(Obj array,size_t i) {return ba::read<Obj>(array,0x20+i*sizeof(Obj));}
static Obj interfaceCall(Obj object,const char* ns,const char* type,const char* name) {
    Obj contract=ba::find_class(ns,type);
    Obj method=ba::api<Obj(*)(Obj,const char*,int)>("il2cpp_class_get_method_from_name")(contract,name,0);
    method=ba::api<Obj(*)(Obj,Obj)>("il2cpp_object_get_virtual_method")(object,method);
    return ba_local::invokeMethod(method,object,nullptr);
}
static void abilityGroups(FILE* out,Obj entity) {
    fputc('[',out);size_t written=0;
    if(entity) {
        Root groups(ba::call(entity,"GetActiveAbilityGroups"));
        if(groups.get()) {
            Root enumerator(interfaceCall(groups.get(),"System.Collections","IEnumerable","GetEnumerator"));
            while(unbox<bool>(interfaceCall(enumerator.get(),"System.Collections","IEnumerator","MoveNext"))) {
                Root group(interfaceCall(enumerator.get(),"System.Collections","IEnumerator","get_Current"));
                if(group.get())fprintf(out,"%s%u",written++?",":"",unbox<uint32_t>(ba::call(group.get(),"get_ID")));
                if(written>64)throw std::runtime_error("catalog unreasonable active ability group count");
            }
        }
    }
    fputc(']',out);
}
static void ints(FILE* out,Obj array) {
    fputc('[',out);for(size_t i=0;i<length(array);++i)fprintf(out,"%s%u",i?",":"",ba::read<uint32_t>(array,0x20+4*i));fputc(']',out);
}
static std::string localized(Obj value) {
    if(!value)return {};
    try {Root text(ba::call(value,"GetLocalizedString"));return utf8(text.get());}
    catch(const std::exception&){return {};}
}
static Obj table(const char* name) {
    Obj type=ba::api<Obj(*)(Obj)>("il2cpp_class_get_type")(ba::find_class("Uncapped",name));
    Root reflected(ba::api<Obj(*)(Obj)>("il2cpp_type_get_object")(type));void* args[]={reflected.get()};
    return ba::invoke(ba::find_class("Uncapped","StaticTables"),nullptr,"GetTable",1,args);
}
static void deck(FILE* out,Obj value,const std::string& name) {
    fprintf(out,"{\"name\":%s,\"units\":",quote(name).c_str());ints(out,ba::get<Obj>(value,"_units"));
    fprintf(out,",\"active_ability_groups\":");ints(out,ba::get<Obj>(value,"_activeAbilities"));fputc('}',out);
}
static bool available() {
    if(!ba::owner)return false;
    Obj provider=ba::get<Obj>(ba::owner,"_menuStaticGameDataProvider");
    Obj data=provider?ba::get<Obj>(provider,"_localMenuStaticGameData"):nullptr;
    Obj global=data?ba::get<Obj>(data,"_globalConfig"):nullptr;
    Obj deck=global?ba::get<Obj>(global,"DeckConfiguration"):nullptr;
    if(!deck || length(ba::get<Obj>(deck,"_deck"))!=8)return false;
    Obj config=ba::get<Obj>(ba::owner,"_clientGlobalConfig");
    if(!config || !length(ba::get<Obj>(config,"PremadeDecks")))return false;
    Root units(table("UnitTable"));
    if(!units.get())return false;
    Root elements(ba::call(units.get(),"get_Elements"));
    return length(elements.get())!=0;
}
static void exportFile(const wchar_t* path) {
    if(!available())throw std::runtime_error("catalog assets are not loaded");
    std::wstring temporary=std::wstring(path)+L".tmp";
    FILE* output=nullptr;
    try {
        output=_wfsopen(temporary.c_str(),L"wb",_SH_DENYNO);if(!output)throw std::runtime_error("catalog output open failed");
        Obj provider=ba::get<Obj>(ba::owner,"_menuStaticGameDataProvider");
        Obj staticData=provider?ba::get<Obj>(provider,"_localMenuStaticGameData"):nullptr;
        Obj global=staticData?ba::get<Obj>(staticData,"_globalConfig"):nullptr;
        Obj deckConfig=global?ba::get<Obj>(global,"DeckConfiguration"):nullptr;
        fprintf(output,"{\"schema\":1,\"source\":\"loaded shipped UnitTable / UnitDefinition / ClientGlobalConfigDefinition\",\"pid\":%lu,\"slot_flags\":",GetCurrentProcessId());
        ints(output,deckConfig?ba::get<Obj>(deckConfig,"_deck"):nullptr);
        fprintf(output,",\"units\":[");
        Root unitTable(table("UnitTable"));if(!unitTable.get())throw std::runtime_error("loaded UnitTable missing");
        Root elements(ba::call(unitTable.get(),"get_Elements"));
        size_t written=0;
        for(size_t index=0;index<length(elements.get());++index) {
            Obj unit=arrayAt(elements.get(),index);if(!unit)continue;
            Obj definition=ba::get<Obj>(unit,"_unitDefinition");if(!definition)continue;
            Root idObject(ba::call(unit,"get_ID"));uint32_t id=unbox<uint32_t>(idObject.get());
            std::string internal=utf8(ba::get<Obj>(unit,"_name"));
            Root name(ba::call(definition,"get_Name"));std::string display=localized(name.get());
            const uint32_t definitionFlags=ba::get<uint32_t>(definition,"_deckSlotFlags");
            Obj cost=ba::get<Obj>(definition,"_resourceCost"),prereq=ba::get<Obj>(definition,"_prerequisite");
            Obj entity=nullptr;
            if(staticData){void* args[]={&id};entity=ba::call(staticData,"GetEntityConfig",1,args);}
            const uint32_t configFlags=entity?ba::get<uint32_t>(entity,"DeckSlotFlags"):0;
            Root playable(ba::call(definition,"get_IsReleaseDeckPlayable"));
            fprintf(output,"%s{\"id\":%u,\"internal_name\":%s,\"name\":%s,\"definition_slot_flags\":%u,\"menu_entity_present\":%s,\"menu_slot_flags\":%u,\"release_deck_playable\":%s,\"display_order\":%d,\"entitlement_id\":%u,\"primary_cost\":%d,\"secondary_cost\":%d,\"supply_cost\":%.9g,\"tech_building\":%d,\"tech_tier\":%d,\"active_ability_groups\":",
                written++?",":"",id,quote(internal).c_str(),quote(display).c_str(),definitionFlags,entity?"true":"false",configFlags,
                unbox<bool>(playable.get())?"true":"false",ba::get<int>(definition,"DisplayOrder"),ba::get<uint32_t>(definition,"EntitlementKey"),
                cost?ba::get<int>(cost,"_primaryResource"):0,cost?ba::get<int>(cost,"_secondaryResource"):0,
                static_cast<double>(ba::get<float>(definition,"SupplyCost")),prereq?ba::get<int>(prereq,"_techBuilding"):0,prereq?ba::get<int>(prereq,"_techTier"):0);
            abilityGroups(output,entity);fputc('}',output);
        }
        fprintf(output,"],\"premade_decks\":[");
        Obj config=ba::get<Obj>(ba::owner,"_clientGlobalConfig");Obj premade=config?ba::get<Obj>(config,"PremadeDecks"):nullptr;
        size_t deckCount=0;
        for(size_t i=0;i<length(premade);++i){Obj value=arrayAt(premade,i);if(!value)continue;if(deckCount++)fputc(',',output);deck(output,value,utf8(ba::get<Obj>(value,"_name")));}
        fprintf(output,"],\"recommended_decks\":[");Obj recommended=config?ba::get<Obj>(config,"RecommendedDecks"):nullptr;
        size_t recommendationCount=0;
        for(size_t i=0;i<length(recommended);++i){Obj item=arrayAt(recommended,i);if(!item)continue;Obj value=ba::get<Obj>(item,"Deck");if(!value)continue;if(recommendationCount++)fputc(',',output);deck(output,value,localized(ba::get<Obj>(item,"DeckName")));}
        fprintf(output,"]}\n");
        const bool writeFailed=ferror(output)!=0 || fflush(output)!=0;
        const int closeResult=fclose(output);output=nullptr;
        if(writeFailed || closeResult)throw std::runtime_error("catalog output write failed");
        if(!MoveFileExW(temporary.c_str(),path,MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH))throw std::runtime_error("catalog output rename failed");
        ba::log("Exported shipped unit catalog: %llu units, %llu premade decks, %llu recommended decks -> %ls",static_cast<unsigned long long>(written),static_cast<unsigned long long>(deckCount),static_cast<unsigned long long>(recommendationCount),path);
    } catch(...) {if(output)fclose(output);DeleteFileW(temporary.c_str());throw;}
}
static void exportOnce() {
    static bool completed=false;
    if(completed || !wcsstr(GetCommandLineW(),L"-export-unit-catalog") || !ba::owner)return;
    try {
        if(!available())return;
        completed=true;
        wchar_t path[32768];GetModuleFileNameW(ba::module,path,32768);wchar_t* slash=wcsrchr(path,L'\\');
        if(!slash)throw std::runtime_error("catalog module path missing");*(slash+1)=0;
        wcscat_s(path,L"investigation\\dedicated\\unit-catalog-runtime.json");
        exportFile(path);
    } catch(const std::exception& e) {completed=true;ba::log("Unit catalog export failed: %s",e.what());}
}
}
