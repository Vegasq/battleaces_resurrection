#pragma once
// Build 37822 only. Exact caller hooks preserve every other settings control.
// The real Region model stays observed by its native VM. Only the two model
// reads in RefreshViewModel receive a private, never-bound display projection.
namespace ba_practice_settings_ui {
using ba::Obj;using ba_local::Root;
static const char* titleText="AI Difficulty";
static const char* helpText="Choose the opponent for Try Deck vs AI. Changes apply to your next match.";
static const char* saveFailureText="AI difficulty changed for this session, but could not be saved.";
static unsigned releases=0;
static bool smokePassed=false,smokeFailed=false,errorReported=false;
static auto& blockedRow=*new std::unique_ptr<Root>();
static auto& blockedModel=*new std::unique_ptr<Root>();
static void require(bool value,const char* why) {if(!value)throw std::runtime_error(why);}
static bool exact(Obj value,const char* ns,const char* name) {return value && ba::klass(value)==ba::find_class(ns,name);}
static bool unityThread() {
    // Options initialize during the original initial->menu transition, before
    // offlineUpdate records the later session-thread identity.
    return ba::initialThread && ba::initialThread==GetCurrentThreadId() &&
        (!ba_dedicated_session::unityThread || ba_dedicated_session::unityThread==ba::initialThread);
}
static int integer(Obj boxed) {
    require(boxed!=nullptr,"practice settings boxed value missing");
    return *ba::api<int*(*)(Obj)>("il2cpp_object_unbox")(boxed);
}
static size_t arrayCount(Obj array,size_t limit) {
    require(array!=nullptr,"practice settings array missing");
    const auto count=ba::api<uintptr_t(*)(Obj)>("il2cpp_array_length")(array);
    require(count<=limit,"practice settings array capacity");return count;
}
static Obj arrayItem(Obj array,size_t index) {return ba::read<Obj>(array,0x20+index*sizeof(Obj));}
static Obj item(Obj list,int index) {void* args[]={&index};return ba::call(list,"get_Item",1,args);}
static void persistentTarget(Obj event,Obj expected,const char* method) {
    // Public editor inspection helpers were stripped from this player. Read
    // its retained serialized call record without changing/invoking the event.
    Root group(ba::get<Obj>(event,"m_PersistentCalls"));
    Root calls(ba::get<Obj>(group.get(),"m_Calls"));
    require(calls.get() && ba_local::count(calls.get())==1,"practice persistent event count");
    Root call(item(calls.get(),0));
    require(ba::get<Obj>(call.get(),"m_Target")==expected &&
        ba_catalog::utf8(ba::get<Obj>(call.get(),"m_MethodName"))==method &&
        ba::get<int>(call.get(),"m_CallState")!=0,"practice persistent event target mismatch");
}
static Obj reflectedType(const char* ns,const char* name) {
    Obj type=ba::api<Obj(*)(Obj)>("il2cpp_class_get_type")(ba::find_class(ns,name));
    return ba::api<Obj(*)(Obj)>("il2cpp_type_get_object")(type);
}
static Obj component(Obj source,const char* ns,const char* name) {
    Root type(reflectedType(ns,name));return ba::native<Obj(*)(Obj,Obj,Obj)>(0x50856a0)(source,type.get(),nullptr);
}
static Obj gameObject(Obj source) {return ba::native<Obj(*)(Obj,Obj)>(0x6ec1a0)(source,nullptr);}
static Obj findChild(Obj source,const char* path) {
    Root transform(ba::call(source,"get_transform")),name(ba::str(path));void* args[]={name.get()};
    return ba::call(transform.get(),"Find",1,args);
}
static std::string objectName(Obj object) {Root name(ba::call(object,"get_name"));return ba_catalog::utf8(name.get());}
static bool active(Obj object) {
    Root go(gameObject(object));return go.get() && ba::native<bool(*)(Obj,Obj)>(0x508a650)(go.get(),nullptr);
}
static void report(const char* where,const std::exception& error) {
    if(!errorReported)ba::log("Practice settings UI failed in %s: %s",where,error.what());
    errorReported=true;if(ba::flag(L"-practice-settings-smoke"))smokeFailed=true;
}
struct TextBinding {
    Root localizer,reference,text;
    TextBinding(Obj l,Obj r,Obj t):localizer(l),reference(r),text(t){}
};
struct Row {
    Root vm,model,owner,screen,receiver,projection;
    std::unique_ptr<TextBinding> title,help;
    bool detaching=false,releasing=false,failed=false,saved=true,originalInteractable=true;
    Row(Obj v,Obj m,Obj o,Obj s,Obj r,Obj p):vm(v),model(m),owner(o),screen(s),receiver(r),projection(p){}
};
static auto& row=*new std::unique_ptr<Row>();
static void textReference(TextBinding& binding,Obj reference) {
    ba::native<void(*)(Obj,Obj,Obj)>(0x47f5cb0)(binding.localizer.get(),reference,nullptr);
    require(ba::get<Obj>(binding.localizer.get(),"m_StringReference")==reference,"practice text reference readback");
}
static void textValue(TextBinding& binding,const char* text) {
    Root value(ba::str(text));ba::native<void(*)(Obj,Obj,Obj)>(0x47f5f50)(binding.localizer.get(),value.get(),nullptr);
    Root actual(ba::call(binding.text.get(),"get_text"));
    require(ba_catalog::utf8(actual.get())==text,"practice text receiver readback");
}
static std::unique_ptr<TextBinding> localText(Obj parent,const char* childName,int64_t entry) {
    Root child(findChild(parent,childName));require(child.get()!=nullptr,"practice text child missing");
    Root localizer(component(child.get(),"UnityEngine.Localization.Components","LocalizeStringEvent"));
    Root text(component(child.get(),"TMPro","TMP_Text"));
    require(exact(localizer.get(),"UnityEngine.Localization.Components","LocalizeStringEvent") && text.get(),"practice text component mismatch");
    Root reference(ba::get<Obj>(localizer.get(),"m_StringReference"));
    require(exact(reference.get(),"UnityEngine.Localization","LocalizedString"),"practice text localization type mismatch");
    Root key(ba::call(reference.get(),"get_TableEntryReference"));
    require(ba::get<int64_t>(key.get(),"m_KeyId")==entry,"practice text localization key mismatch");
    Root event(ba::get<Obj>(localizer.get(),"m_UpdateString"));
    Root count(ba::call(event.get(),"GetPersistentEventCount"));require(integer(count.get())==1,"practice text event count");
    persistentTarget(event.get(),text.get(),"set_text");
    return std::make_unique<TextBinding>(localizer.get(),reference.get(),text.get());
}
static Obj receiverFor(Obj vm) {
    Root receiver(component(vm,"Uncapped.UI","TMPDropdownEnumBindReceiver"));
    require(exact(receiver.get(),"Uncapped.UI","TMPDropdownEnumBindReceiver"),"practice enum receiver missing");
    Root collection(ba::get<Obj>(vm,"_bindings"));
    require(collection.get() && ba::get<bool>(collection.get(),"_initialized"),"practice settings bindings unavailable");
    Root bindings(ba::get<Obj>(collection.get(),"_bindings"));const int count=ba_local::count(bindings.get());
    require(count<=32,"practice settings binding capacity");unsigned current=0,whitelist=0;
    for(int i=0;i<count;++i) {
        Root binding(item(bindings.get(),i)),source(ba::get<Obj>(binding.get(),"_source"));
        Root value(ba::get<Obj>(source.get(),"BindyValue"));if(!value.get() || ba::get<Obj>(value.get(),"Target")!=vm)continue;
        const auto name=ba_catalog::utf8(ba::get<Obj>(value.get(),"VariableName"));
        const bool isCurrent=name=="CurrentDropdownItem",isWhitelist=name=="WhiteListedEnumValues";
        if(!isCurrent && !isWhitelist)continue;
        Root targets(ba::get<Obj>(binding.get(),"_targets"));require(ba_local::count(targets.get())==1,"practice enum binding target count");
        Root target(item(targets.get(),0)),destination(ba::get<Obj>(target.get(),"BindyValue"));
        require(destination.get() && ba::get<Obj>(destination.get(),"Target")==receiver.get() &&
            ba_catalog::utf8(ba::get<Obj>(destination.get(),"VariableName"))==(isCurrent?"SelectedEnumValue":"WhitelistDropdownOptions"),
            "practice enum binding target mismatch");
        if(isCurrent)++current;else ++whitelist;
    }
    require(current==1 && whitelist==1,"practice enum binding source count");
    Root enumType(ba::get<Obj>(receiver.get(),"<EnumType>k__BackingField"));Root type(ba::call(enumType.get(),"get_Type"));
    Root region(reflectedType("CommonPb","Region"));require(type.get()==region.get(),"practice dropdown enum type mismatch");
    Root event(ba::get<Obj>(receiver.get(),"EnumValueChanged"));Root eventCount(ba::call(event.get(),"GetPersistentEventCount"));
    require(integer(eventCount.get())==1,"practice dropdown callback count");
    persistentTarget(event.get(),vm,"OnSettingChanged");
    return receiver.get();
}
static Obj boxRegion(uint32_t value) {
    require(value>=17 && value<=19,"practice difficulty outside supported range");int number=static_cast<int>(value);
    return ba::api<Obj(*)(Obj,void*)>("il2cpp_value_box")(ba::find_class("CommonPb","Region"),&number);
}
static void project(Row& target) {
    const auto selected=ba_practice_settings::selection();
    Root previous(ba::get<Obj>(target.projection.get(),"<OptionEnumDropdownSavedItem>k__BackingField"));
    if(!previous.get() || integer(previous.get())!=static_cast<int>(selected)) {
        Root value(boxRegion(selected));ba::set<Obj>(target.projection.get(),"<OptionEnumDropdownSavedItem>k__BackingField",value.get());
    }
}
static Row* acquire(Obj vm,Obj original) {
    if(!exact(vm,"Uncapped.UI","OptionEnumDropdownVM") || ba::get<int>(vm,"_optionSettingElement")!=22 ||
       ba::get<int>(vm,"_optionSettingIntKey")!=22 || !exact(original,"Uncapped.UI","RegionSettingModel"))return nullptr;
    // The main menu has a distinct Region row sharing this same model. Its
    // owner is PlayScreenVM/prefab1; only Settings/General is repurposed here.
    Root owner(ba::get<Obj>(vm,"<Owner>k__BackingField"));
    if(!owner.get() || ba::get<int>(owner.get(),"<PrefabType>k__BackingField")!=4)return nullptr;
    Root screen(ba::get<Obj>(owner.get(),"<Root>k__BackingField"));
    if(!exact(screen.get(),"Uncapped.UI","UIOptionsMenu"))return nullptr;
    // Mark this exact original model before deeper validation, so an error can
    // never send a synthetic difficulty value to Region.ApplyChange.
    if(blockedRow)require(blockedRow->get()==vm && blockedModel->get()==original,"multiple practice Region rows");
    else {blockedRow=std::make_unique<Root>(vm);blockedModel=std::make_unique<Root>(original);}
    require(unityThread(),"practice settings callback outside Unity thread");
    if(row) {
        require(row->vm.get()==vm && row->model.get()==original,"practice settings model owner changed");
        if(row->releasing || row->failed)return nullptr;project(*row);return row.get();
    }
    require(ba::get<bool>(vm,"_isInitialized") && ba::get<Obj>(vm,"_model")==original,"practice settings VM lifecycle mismatch");
    require(exact(screen.get(),"Uncapped.UI","UIOptionsMenu") && ba::get<Obj>(screen.get(),"<Owner>k__BackingField")==owner.get(),"practice settings screen mismatch");
    Root items(ba::get<Obj>(screen.get(),"_generalTabSettingItems"));bool found=false;
    for(size_t i=0,n=arrayCount(items.get(),64);i<n;++i)if(arrayItem(items.get(),i)==vm){require(!found,"practice duplicate Region row");found=true;}
    require(found,"practice Region row outside General items");
    Root receiver(receiverFor(vm)),transform(ba::call(vm,"get_transform")),parent(ba::call(transform.get(),"get_parent"));
    require(parent.get() && objectName(parent.get())=="RegionContainer" && objectName(vm)=="RegionDropdown","practice Region hierarchy mismatch");
    auto title=localText(parent.get(),"RegionText",71470908507430912LL);
    auto help=localText(parent.get(),"RegionInfoText",71471914653851648LL);
    Root projection(ba::make("Uncapped.UI","RegionSettingModel"));
    Root values(ba::api<Obj(*)(Obj,uintptr_t)>("il2cpp_array_new")(ba::find_class("System","Enum"),3));
    for(uint32_t i=0;i<3;++i) {
        Root value(boxRegion(17+i));Obj* slot=reinterpret_cast<Obj*>(static_cast<char*>(values.get())+0x20+i*sizeof(Obj));
        ba::api<void(*)(Obj,Obj*,Obj)>("il2cpp_gc_wbarrier_set_field")(values.get(),slot,value.get());
    }
    ba::set<Obj>(projection.get(),"<WhiteListedEnumValues>k__BackingField",values.get());
    row=std::make_unique<Row>(vm,original,owner.get(),screen.get(),receiver.get(),projection.get());
    row->title=std::move(title);row->help=std::move(help);project(*row);
    Root dropdown(component(vm,"TMPro","TMP_Dropdown")),interactable(ba::call(dropdown.get(),"get_interactable"));
    row->originalInteractable=*ba::api<bool*(*)(Obj)>("il2cpp_object_unbox")(interactable.get());
    // Every pointer and persistent event was checked before the first mutation.
    row->detaching=true;textReference(*row->title,nullptr);textReference(*row->help,nullptr);
    textValue(*row->title,titleText);textValue(*row->help,helpText);
    ba::log("Practice settings row acquired: key=22 originalModel=RegionSettingModel projectionOnly=1 title=AI Difficulty options=Easy,Normal,Hard");
    return row.get();
}
static Obj optionData(const char* label) {
    Obj parent=ba::find_class("TMPro","TMP_Dropdown"),found=nullptr;void* iter=nullptr;
    while(Obj candidate=ba::api<Obj(*)(Obj,void**)>("il2cpp_class_get_nested_types")(parent,&iter)) {
        if(strcmp(ba::api<const char*(*)(Obj)>("il2cpp_class_get_name")(candidate),"OptionData"))continue;
        require(found==nullptr,"practice duplicate TMP OptionData type");found=candidate;
    }
    require(found!=nullptr,"practice TMP OptionData type missing");ba::api<void(*)(Obj)>("il2cpp_runtime_class_init")(found);
    Root value(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(found));ba::invoke(found,value.get(),".ctor",0);
    Root text(ba::str(label));ba::set<Obj>(value.get(),"m_Text",text.get());return value.get();
}
static void populate(Row& target,int selected,int* selectedIndex) {
    require(unityThread() && selectedIndex && !target.failed,"practice dropdown populate ownership");
    Root dropdown(ba::get<Obj>(target.receiver.get(),"_tmpDropdown"));
    require(exact(dropdown.get(),"TMPro","TMP_Dropdown") && component(target.vm.get(),"TMPro","TMP_Dropdown")==dropdown.get(),"practice dropdown component mismatch");
    Root options(ba::call(dropdown.get(),"get_options")),values(ba::get<Obj>(target.receiver.get(),"_dropdownEnumValues"));
    require(options.get() && values.get(),"practice dropdown native lists missing");
    // Construct all labels before touching either native list. The original
    // outer method retains its listener and SetValue(index,false)/caption work.
    Root easy(optionData("Easy")),normal(optionData("Normal")),hard(optionData("Hard"));
    ba::call(options.get(),"Clear");ba::call(values.get(),"Clear");Obj labels[]={easy.get(),normal.get(),hard.get()};
    for(int i=0;i<3;++i) {
        ba_local::addItem(options.get(),labels[i]);int value=17+i;void* args[]={&value};ba::call(values.get(),"Add",1,args);
    }
    require(selected>=17 && selected<=19,"practice dropdown projected enum value");*selectedIndex=selected-17;
}
static void disableRow() {
    if(!row)return;row->failed=true;
    try {Root dropdown(component(row->vm.get(),"TMPro","TMP_Dropdown"));bool value=false;void* args[]={&value};ba::call(dropdown.get(),"set_interactable",1,args);}catch(...){}
}
static void restore(Row& target) {
    require(unityThread() && ba::get<Obj>(target.vm.get(),"_model")==target.model.get(),"practice settings release ownership");
    target.releasing=true;
    // At the caller tail the original model is already unobserved, but still
    // present and bindings are live. Refresh now forwards both reads/populate
    // to the original path, resetting only the transient native row fields.
    bool okay=true;
    try {ba::native<void(*)(Obj,Obj)>(0x3d19540)(target.vm.get(),nullptr);}
    catch(const std::exception& e){okay=false;ba::log("Practice settings original enum restoration failed: %s",e.what());}
    if(target.detaching) {
        // Attempt each independent restore even if an earlier one failed.
        try{textReference(*target.title,target.title->reference.get());}
        catch(const std::exception& e){okay=false;ba::log("Practice settings title restoration failed: %s",e.what());}
        try{textReference(*target.help,target.help->reference.get());}
        catch(const std::exception& e){okay=false;ba::log("Practice settings help restoration failed: %s",e.what());}
    }
    try {Root dropdown(component(target.vm.get(),"TMPro","TMP_Dropdown"));void* args[]={&target.originalInteractable};ba::call(dropdown.get(),"set_interactable",1,args);}
    catch(const std::exception& e){okay=false;ba::log("Practice settings interactability restoration failed: %s",e.what());}
    require(okay,"practice settings release restoration incomplete");target.detaching=false;
}
static void released(Obj vm) {
    if(row && row->vm.get()==vm) {restore(*row);row.reset();++releases;ba::log("Practice settings row released: original localization and enum presentation restored");}
    if(blockedRow && blockedRow->get()==vm) {blockedRow.reset();blockedModel.reset();}
}
static void update(Obj front);
static bool smokeComplete() {return smokePassed;}
}

extern "C" __declspec(dllexport) void* OfflinePracticeSettingsModel(void* object,void* method) {
    ba::init();ba_local::Root original(ba::native<ba::Obj(*)(ba::Obj,ba::Obj)>(0x29b92d0)(object,method));
    if(!ba::offlinePractice() || !original.get())return original.get();
    try {if(auto* row=ba_practice_settings_ui::acquire(object,original.get()))return row->projection.get();}
    catch(const std::exception& e){ba_practice_settings_ui::disableRow();ba_practice_settings_ui::report("model projection",e);}
    return original.get();
}
extern "C" __declspec(dllexport) void OfflinePracticeSettingsApply(void* model,int value,void* vm) {
    ba::init();using namespace ba_practice_settings_ui;
    if(ba::offlinePractice() && blockedRow && blockedRow->get()==vm) {
        try {
            require(unityThread() && blockedModel && blockedModel->get()==model && row && row->model.get()==model && !row->releasing && !row->failed,"practice selection owner unavailable");
            require(value>=17 && value<=19,"practice selection value outside difficulty range");
            row->saved=ba_practice_settings::choose(static_cast<uint32_t>(value));project(*row);
            ba::native<void(*)(Obj,Obj)>(0x3d19540)(row->vm.get(),nullptr);
            textValue(*row->help,row->saved?helpText:saveFailureText);
        }catch(const std::exception& e){
            if(row && !row->failed && !row->releasing)try {
                project(*row);ba::native<void(*)(Obj,Obj)>(0x3d19540)(row->vm.get(),nullptr);
            }catch(...){}
            disableRow();report("selection",e);
        }
        return; // Never persist difficulty IDs through the original Region model.
    }
    require(model!=nullptr,"settings original ApplyChange model missing");
    Obj klass=ba::klass(model);
    ba::read<void(*)(Obj,int,Obj)>(klass,0x208)(model,value,ba::read<Obj>(klass,0x210));
}
extern "C" __declspec(dllexport) void OfflinePracticeSettingsOptions(void* receiver,int selected,int* index,void* method) {
    ba::init();using namespace ba_practice_settings_ui;
    if(ba::offlinePractice() && row && row->receiver.get()==receiver && !row->releasing) {
        try{populate(*row,selected,index);}catch(const std::exception& e){if(index)*index=0;disableRow();report("options",e);}return;
    }
    ba::native<void(*)(Obj,int,int*,Obj)>(0x3c92340)(receiver,selected,index,method);
}
extern "C" __declspec(dllexport) void OfflinePracticeSettingsRelease(void* object,void* method) {
    ba::init();if(ba::offlinePractice())try{ba_practice_settings_ui::released(object);}
    catch(const std::exception& e){ba_practice_settings_ui::report("release",e);}
    // Also executed on a restoration error; retaining roots then prevents the
    // helper from treating a partially restored pooled row as newly owned.
    ba::native<void(*)(ba::Obj,ba::Obj)>(0x3d69a50)(object,method);
}

namespace ba_practice_settings_ui {
struct RegionSnapshot {
    Root variable,current,persistent;int currentValue,persistentValue;
    explicit RegionSnapshot(Obj value):variable(value),current(ba::get<Obj>(value,"_var")),persistent(ba::get<Obj>(value,"_varToSave")),
        currentValue(integer(current.get())),persistentValue(integer(persistent.get())){}
    void verify() const {
        require(ba::get<Obj>(variable.get(),"_var")==current.get() && ba::get<Obj>(variable.get(),"_varToSave")==persistent.get() &&
            integer(current.get())==currentValue && integer(persistent.get())==persistentValue,"practice settings changed original Region");
    }
};
struct CloseCheck {
    Root screen,title,titleReference,help,helpReference;unsigned generation;
    explicit CloseCheck(const Row& value):screen(value.screen.get()),title(value.title->localizer.get()),titleReference(value.title->reference.get()),
        help(value.help->localizer.get()),helpReference(value.help->reference.get()),generation(releases){}
    bool complete() const {
        if(releases<=generation || ba::get<bool>(screen.get(),"_isInitialized") || row || blockedRow)return false;
        require(ba::get<Obj>(title.get(),"m_StringReference")==titleReference.get() &&
            ba::get<Obj>(help.get(),"m_StringReference")==helpReference.get(),"practice settings close did not restore original localization");
        return true;
    }
};
static auto& regionSnapshot=*new std::unique_ptr<RegionSnapshot>();
static auto& closeCheck=*new std::unique_ptr<CloseCheck>();
static unsigned smokeStage=0;
static ULONGLONG smokeDue=0,smokeDeadline=0;
static Obj flowController() {
    Root menu(ba::get<Obj>(ba::owner,"<UIMenuController>k__BackingField"));
    require(menu.get()!=nullptr,"practice settings menu owner missing");
    Obj flow=ba::get<Obj>(menu.get(),"_menuFlowGraph");
    require(exact(flow,"Uncapped.UI","MenuFlowController") && ba::get<Obj>(ba::owner,"_menuFlowController")==flow,"practice settings menu flow ownership");return flow;
}
static Obj settingsScreen() {
    Root flow(flowController()),graph(ba::get<Obj>(flow.get(),"_flowGraph"));
    Root node(ba::get<Obj>(graph.get(),"ActiveNode"));if(!exact(node.get(),"Uncapped.UI","ShowUIObjectNode"))return nullptr;
    Root descriptors(ba::get<Obj>(node.get(),"ShowUIObject")),views(ba::get<Obj>(node.get(),"_uiObject"));
    if(!descriptors.get() || !views.get())return nullptr;
    const auto count=arrayCount(descriptors.get(),32);if(arrayCount(views.get(),32)!=count)return nullptr;
    Obj found=nullptr;
    for(size_t i=0;i<count;++i) {
        Obj descriptor=arrayItem(descriptors.get(),i);if(!descriptor || ba::get<int>(descriptor,"_prefabKey")!=4)continue;
        require(found==nullptr,"practice settings duplicate acquired screen");found=arrayItem(views.get(),i);
    }
    if(!found || !ba::get<bool>(found,"_isInitialized"))return nullptr;
    require(exact(found,"Uncapped.UI","UIOptionsMenu"),"practice settings acquired class mismatch");
    Root owner(ba::get<Obj>(found,"<Owner>k__BackingField"));if(!owner.get() || !ba::get<bool>(owner.get(),"<IsInitialized>k__BackingField"))return nullptr;
    require(ba::get<int>(owner.get(),"<PrefabType>k__BackingField")==4 && ba::get<Obj>(owner.get(),"<Root>k__BackingField")==found &&
        ba::get<Obj>(owner.get(),"_pool")==ba::get<Obj>(node.get(),"_pool"),"practice settings acquired lifetime mismatch");
    Obj container=ba::get<Obj>(owner.get(),"_uiContainer");
    if(!container || !ba::native<bool(*)(Obj,Obj)>(0x88a350)(container,nullptr) || !active(found))return nullptr;
    require(ba::get<Obj>(graph.get(),"ActiveNode")==node.get(),"practice settings graph changed during resolve");return found;
}
static bool selectable(Obj value) {
    return value && active(value) && ba::native<bool(*)(Obj,Obj)>(0x5084710)(value,nullptr) &&
        ba::native<bool(*)(Obj,Obj)>(0x53af310)(value,nullptr) && !ba::read<bool>(value,0x198);
}
static void checkButton(Obj button,const char* name) {
    require(exact(button,"Doozy.Runtime.UIManager.Components","UIButton"),"practice settings native button type");
    Root id(ba::get<Obj>(button,"Id"));
    require(id.get() && !ba::get<bool>(id.get(),"Custom") && ba_catalog::utf8(ba::get<Obj>(id.get(),"Category"))=="MainMenu" &&
        ba_catalog::utf8(ba::get<Obj>(id.get(),"Name"))==name,"practice settings button ID mismatch");
}
static bool openSettings() {
    Root menu(ba::get<Obj>(ba::owner,"<UIMenuController>k__BackingField")),main(ba::get<Obj>(menu.get(),"_mainMenu"));
    if(!main.get() || !ba::get<bool>(main.get(),"_isInitialized") || !active(main.get()))return false;
    require(exact(main.get(),"Uncapped.UI","PlayScreenVM"),"practice settings MainMenu type mismatch");
    Root owner(ba::get<Obj>(main.get(),"<Owner>k__BackingField"));
    require(owner.get() && ba::get<Obj>(owner.get(),"<Root>k__BackingField")==main.get() &&
        ba::get<bool>(owner.get(),"<IsInitialized>k__BackingField"),"practice settings MainMenu lifetime mismatch");
    Root transform(findChild(main.get(),"OptionsButtonParent/OptionsButton"));require(transform.get()!=nullptr,"practice settings opener hierarchy missing");
    Root button(component(transform.get(),"Doozy.Runtime.UIManager.Components","UIButton"));checkButton(button.get(),"OptionMenu");
    if(!selectable(button.get()))return false;
    ba::native<void(*)(Obj,Obj)>(0x89fe30)(button.get(),nullptr);
    ba::log("PRACTICE SETTINGS SMOKE original MainMenu/OptionMenu button Click (automated native callback; not mouse input)");return true;
}
static bool selectGeneral(Obj screen,bool mayToggle) {
    Root tab(ba::get<Obj>(screen,"_generalTab")),transform(findChild(screen,"GameObject/Top Expanded/Tabs/GeneralTab"));
    require(exact(tab.get(),"Doozy.Runtime.UIManager.Components","UITab") && transform.get() &&
        component(transform.get(),"Doozy.Runtime.UIManager.Components","UITab")==tab.get(),"practice General tab hierarchy mismatch");
    if(!selectable(tab.get()) || !ba::read<bool>(tab.get(),0x1e1) || !ba::get<bool>(tab.get(),"<isConnectedToContainer>k__BackingField"))return false;
    Root container(ba::get<Obj>(tab.get(),"TargetContainer")),group(ba::get<Obj>(tab.get(),"ToggleGroup"));
    require(container.get() && gameObject(container.get())==ba::get<Obj>(screen,"_generalTabContainer") && group.get(),"practice General tab target mismatch");
    if(!ba::read<bool>(group.get(),0x230))return false;
    Root toggles(ba::read<Obj>(group.get(),0x228));const int count=ba_local::count(toggles.get());require(count<=16,"practice settings tab group capacity");unsigned matches=0;
    for(int i=0;i<count;++i)if(item(toggles.get(),i)==tab.get())++matches;require(matches==1,"practice General group membership mismatch");
    if(!ba::native<bool(*)(Obj,Obj)>(0x8b58f0)(tab.get(),nullptr)) {
        if(mayToggle && !ba::read<bool>(tab.get(),0x1e0))ba::native<void(*)(Obj,Obj)>(0x8b6070)(tab.get(),nullptr);
        return false;
    }
    return ba::get<int>(screen,"_activeTab")==4 && ba::native<bool(*)(Obj,Obj)>(0x88a350)(container.get(),nullptr);
}
static void verify(uint32_t expected) {
    require(row && !row->failed && !row->releasing && row->screen.get()==settingsScreen() &&
        ba::get<bool>(row->vm.get(),"_isInitialized") && ba::get<bool>(row->vm.get(),"<IsModelSet>k__BackingField"),"practice settings smoke row unavailable");
    require(ba::get<Obj>(row->vm.get(),"_model")==row->model.get() && row->model.get()!=row->projection.get(),"practice settings replaced the observed native model");
    require(ba_practice_settings::selection()==expected,"practice settings selection mismatch");
    Root value(ba::get<Obj>(row->vm.get(),"_currentDropdownItem")),receiverValue(ba::get<Obj>(row->receiver.get(),"_selectedEnumValue"));
    require(integer(value.get())==static_cast<int>(expected) && integer(receiverValue.get())==static_cast<int>(expected),"practice settings bound enum mismatch");
    Root dropdown(ba::get<Obj>(row->receiver.get(),"_tmpDropdown"));require(active(dropdown.get()),"practice difficulty dropdown hidden");
    Root options(ba::call(dropdown.get(),"get_options")),values(ba::get<Obj>(row->receiver.get(),"_dropdownEnumValues"));
    require(ba_local::count(options.get())==3 && ba_local::count(values.get())==3,"practice difficulty option count mismatch");
    const char* labels[]={"Easy","Normal","Hard"};
    for(int i=0;i<3;++i) {
        Root option(item(options.get(),i)),label(ba::call(option.get(),"get_text")),key(item(values.get(),i));
        require(ba_catalog::utf8(label.get())==labels[i] && integer(key.get())==17+i,"practice difficulty option/mapping mismatch");
    }
    require(ba::get<int>(dropdown.get(),"m_Value")==static_cast<int>(expected)-17,"practice difficulty selected index mismatch");
    Root caption(ba::get<Obj>(dropdown.get(),"m_CaptionText")),captionText(ba::call(caption.get(),"get_text"));
    Root title(ba::call(row->title->text.get(),"get_text")),help(ba::call(row->help->text.get(),"get_text"));
    require(ba_catalog::utf8(captionText.get())==labels[expected-17] && ba_catalog::utf8(title.get())==titleText &&
        ba_catalog::utf8(help.get())==helpText && active(row->title->text.get()) && active(row->help->text.get()),"practice difficulty rendered text mismatch");
    require(!ba::get<Obj>(row->title->localizer.get(),"m_StringReference") && !ba::get<Obj>(row->help->localizer.get(),"m_StringReference"),"practice difficulty localizer still subscribed");
    require(row->saved,"practice settings smoke persistence failed");regionSnapshot->verify();
    ba::log("PRACTICE SETTINGS SMOKE readback: title=AI Difficulty options=Easy,Normal,Hard profile=%u selected=%s caption=%s region=%d persistentRegion=%d originalModel=1",
        expected,ba_practice_settings::name(expected),labels[expected-17],regionSnapshot->currentValue,regionSnapshot->persistentValue);
}
static void selectDifficulty(uint32_t value) {
    require(row && !row->failed && value>=17 && value<=19,"practice smoke selection ownership");
    Root dropdown(ba::get<Obj>(row->receiver.get(),"_tmpDropdown"));require(active(dropdown.get()),"practice smoke dropdown inactive");
    int index=static_cast<int>(value)-17;void* args[]={&index};ba::call(dropdown.get(),"set_value",1,args);
    ba::log("PRACTICE SETTINGS SMOKE original TMP dropdown set_value: index=%d profile=%u",index,value);
}
static bool closeSettings() {
    Root screen(settingsScreen());if(!screen.get())return false;
    require(row && row->screen.get()==screen.get(),"practice settings close row ownership");
    Root transform(findChild(screen.get(),"GameObject/Bottom Buttons/BackButton"));require(transform.get()!=nullptr,"practice settings Back hierarchy missing");
    Root button(component(transform.get(),"Doozy.Runtime.UIManager.Components","UIButton"));checkButton(button.get(),"Back");
    if(!selectable(button.get()))return false;closeCheck=std::make_unique<CloseCheck>(*row);
    ba::native<void(*)(Obj,Obj)>(0x89fe30)(button.get(),nullptr);
    ba::log("PRACTICE SETTINGS SMOKE original Settings Back button Click (automated native callback)");return true;
}
static void next(unsigned stage,ULONGLONG now) {smokeStage=stage;smokeDue=now+350;smokeDeadline=now+30000;}
static void update(Obj front) {
    if(!ba::offlinePractice() || !ba::flag(L"-practice-settings-smoke") || smokePassed || smokeFailed)return;
    try {
        require(unityThread(),"practice settings smoke outside Unity thread");
        if(!ba_practice::offlineInitialized || ba_practice::active())return;
        require(ba_dedicated_session::inMenu() && ba_dedicated_session::worldIdle(ba::read<Obj>(front,0xd8)),"practice settings smoke requires idle menu");
        const auto now=GetTickCount64();
        if(!smokeDeadline){smokeDue=now+2500;smokeDeadline=now+30000;return;}
        if(now<smokeDue)return;require(now<smokeDeadline,"practice settings smoke stage deadline");
        if(smokeStage==0) {
            if(!regionSnapshot) {
                Root variables(ba::native<Obj(*)(Obj)>(0x3b0a670)(nullptr));
                regionSnapshot=std::make_unique<RegionSnapshot>(ba::get<Obj>(variables.get(),"_region"));
            }
            if(openSettings())next(1,now);
        } else if(smokeStage==1 || smokeStage==7) {
            Root screen(settingsScreen());if(!screen.get() || !selectGeneral(screen.get(),true))return;
            next(smokeStage==1?2:8,now);
        } else if(smokeStage==2) {
            verify(ba_practice_settings::selection());selectDifficulty(17);next(3,now);
        } else if(smokeStage==3) {
            verify(17);selectDifficulty(19);next(4,now);
        } else if(smokeStage==4) {
            verify(19);selectDifficulty(18);next(5,now);
        } else if(smokeStage==5) {
            verify(18);if(closeSettings())next(6,now);
        } else if(smokeStage==6) {
            if(!closeCheck || !closeCheck->complete())return;regionSnapshot->verify();
            if(openSettings()){closeCheck.reset();next(7,now);}
        } else if(smokeStage==8) {
            verify(18);if(closeSettings())next(9,now);
        } else if(smokeStage==9) {
            if(!closeCheck || !closeCheck->complete())return;regionSnapshot->verify();closeCheck.reset();
            smokePassed=true;ba::log("PRACTICE SETTINGS SMOKE passed: choices=17,19,18 reopened=normal profile=18 regionUnchanged=1 localizationRestored=1 nativeCallbacks=1");
        }
    } catch(const std::exception& e) {
        smokeFailed=true;ba::log("PRACTICE SETTINGS SMOKE failed: stage=%u reason=%s",smokeStage,e.what());
    }
}
}
