// Authored contracts around the ACTUAL actor source's original-scope owner.
// No Unity/Simulation/IL2CPP code is loaded; these do not qualify HQ effects.
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include <vector>
#include <string>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <iostream>
#include <set>
#include <type_traits>
#include "../src/prediction_movement.hpp"
struct Model {
    Model* helper=nullptr;
    Model* tracked=nullptr;
    uint32_t id=0;
    bool suspended=false,dirty=false;
    unsigned begins=0,disposes=0,clears=0,notifications=0;
    std::set<uint32_t> ids,rules;
};
static int beginMethod=0,disposeMethod=0,clearMethod=0,removeMethod=0;
static int fakeClass=0,badScope=0;
static bool failBeforeBegin=false,failAfterBegin=false,failClear=false,failDispose=false,badReturn=false;
static void check(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
static void* classMethods(void*,void** iterator){if(*iterator)return nullptr;*iterator=&removeMethod;return &removeMethod;}
static void* classParent(void*){return nullptr;}
static const char* methodName(void*){return "Remove";}
static uint32_t paramCount(void*){return 1;}
static uint32_t token(void*){return 0x060000ad;}
namespace ba {
using Obj=void*;static DWORD initialThread=1;static Obj owner=nullptr;
template<class T>T api(const char* name){
    if(!strcmp(name,"il2cpp_class_get_methods"))return reinterpret_cast<T>(&classMethods);
    if(!strcmp(name,"il2cpp_class_get_parent"))return reinterpret_cast<T>(&classParent);
    if(!strcmp(name,"il2cpp_method_get_name"))return reinterpret_cast<T>(&methodName);
    if(!strcmp(name,"il2cpp_method_get_param_count"))return reinterpret_cast<T>(&paramCount);
    if(!strcmp(name,"il2cpp_method_get_token"))return reinterpret_cast<T>(&token);
    throw std::runtime_error("unexpected authored metadata API");
}
template<class T>T native(uintptr_t value){return reinterpret_cast<T>(value);}
template<class T>T read(Obj object,size_t offset){
    if constexpr(std::is_same_v<T,Obj>){
        if(object==&removeMethod && !offset)return native<Obj>(0x3782570);
        if(offset==0x40)return static_cast<Model*>(object)->helper;
        if(offset==0x10)return static_cast<Model*>(object)->tracked;
    }
    if constexpr(std::is_same_v<T,bool>){if(offset==0x10)return static_cast<Model*>(object)->suspended;}
    if constexpr(std::is_same_v<T,uint32_t>){if(offset==0x38)return static_cast<Model*>(object)->id;}
    throw std::runtime_error("unexpected authored field read");
}
static bool flag(const wchar_t*){return false;}
static void init(){}static void log(const char*,...){}
static Obj klass(Obj){return &fakeClass;}
static Obj find_class(const char*,const char*){throw std::runtime_error("unexpected class lookup");}
static Obj field(Obj,const char*){throw std::runtime_error("unexpected field lookup");}
static Obj call(Obj,const char*,int=0,void** = nullptr){throw std::runtime_error("unexpected named call");}
static Obj make(const char*,const char*){throw std::runtime_error("unexpected managed creation");}
template<class T>T get(Obj,const char*){throw std::runtime_error("unexpected singleton get");}
}
namespace ba_local {
struct Root{void* value;explicit Root(void* pointer):value(pointer){}void* get()const{return value;}};
static int count(void* value){return static_cast<int>(static_cast<Model*>(value)->ids.size());}
static void* invokeMethod(void* method,void* receiver,void** args){
    auto& model=*static_cast<Model*>(receiver);
    if(method==&beginMethod){
        check(args && !*static_cast<bool*>(args[0]),"scope incorrectly marked player initiated");
        if(failBeforeBegin)throw std::runtime_error("before Begin");
        check(!model.helper->suspended,"nested original suspension");
        model.helper->suspended=true;++model.helper->begins;
        if(failAfterBegin)throw std::runtime_error("original finally marked suspended");
        return badReturn?static_cast<void*>(&badScope):model.helper;
    }
    if(method==&clearMethod){
        check(model.helper->suspended,"group cleared outside original suspension");
        if(failClear)throw std::runtime_error("authored Clear failure");
        model.ids.clear();model.helper->dirty=true;++model.clears;return nullptr;
    }
    if(method==&disposeMethod){
        check(model.suspended,"original scope disposed twice/not begun");
        ++model.disposes;model.suspended=false;
        if(model.dirty){++model.notifications;model.dirty=false;}
        if(failDispose)throw std::runtime_error("authored Dispose failure");
        return nullptr;
    }
    if(method==&removeMethod){model.ids.erase(*static_cast<uint32_t*>(args[0]));return nullptr;}
    throw std::runtime_error("unexpected authored original invocation");
}
}
namespace ba_prediction_worker {
bool movementEnabled(){return false;}uint64_t movementWorldId(){return 0;}
const std::string& movementMatchId(){static std::string empty;return empty;}
MovementAdmission movementAdmission(){return {};}
void movementFail(const char*)noexcept{}
}
#include "../src/prediction_actor_repair.cpp"
using Scopes=ba_prediction_actors::GroupChanges;
struct Fixture {
    Model helper,tracked,group,unaffected;
    Fixture(){group.helper=&helper;group.tracked=&tracked;group.id=3;
        group.ids={7,9};group.rules={75};tracked.ids={7,9};unaffected.ids={30};
        failBeforeBegin=failAfterBegin=failClear=failDispose=badReturn=false;}
    void add(Scopes& owner){auto change=std::make_unique<Scopes::Change>(&group);
        change->begin=&beginMethod;change->dispose=&disposeMethod;change->clear=&clearMethod;
        owner.values.push_back(std::move(change));owner.retiredIds={7};}
};
template<class F>static void rejects(F action){bool rejected=false;try{action();}catch(const std::exception&){rejected=true;}check(rejected,"expected authored refusal");}
static void spansOriginalRecreation(){
    Fixture f;Scopes scopes;f.add(scopes);scopes.begin();scopes.mutated=true;
    check(f.helper.suspended && !f.helper.notifications,"original recreation would see an open event helper");
    f.group.ids.insert(7);f.helper.dirty=true; // Authored original autoassignment during recreation.
    check(!f.helper.notifications,"intermediate wrong-incarnation assignment was published");
    scopes.close();scopes.close();
    check(f.group.ids.empty() && f.tracked.ids==std::set<uint32_t>{9},"post-recreation fallback missed IDs");
    check(f.group.rules==std::set<uint32_t>{75} && f.unaffected.ids==std::set<uint32_t>{30},"automatic rules/unaffected group changed");
    check(f.helper.disposes==1 && f.helper.notifications==1 && !f.helper.suspended,"scope not disposed exactly once after filtering");
    // The original rule remains available for an intentionally NEW entity.
    if(f.group.rules.count(75))f.group.ids.insert(8);
    check(f.group.ids==std::set<uint32_t>{8},"fresh later entity lost original automatic rule");
}
static void noMutationPreservesGroup(){Fixture f;{Scopes scopes;f.add(scopes);scopes.begin();}
    check(f.helper.disposes==1 && !f.group.clears && f.group.ids==std::set<uint32_t>({7,9}),"preflight failure cleared unaffected memberships");}
static void failureBeforeOriginalBegin(){Fixture f;Scopes scopes;f.add(scopes);failBeforeBegin=true;rejects([&]{scopes.begin();});scopes.close();check(!f.helper.disposes && !f.group.clears,"unstarted scope was disposed");}
static void originalBeginFinallyStillNeedsDispose(){Fixture f;Scopes scopes;f.add(scopes);failAfterBegin=true;rejects([&]{scopes.begin();});scopes.close();check(f.helper.disposes==1 && !f.group.clears && !f.helper.suspended,"throwing original Begin leaked suspension");}
static void wrongReturnedScopeStillClosesOwnedHelper(){Fixture f;Scopes scopes;f.add(scopes);badReturn=true;rejects([&]{scopes.begin();});scopes.close();check(f.helper.disposes==1 && !f.group.clears,"result guard leaked original scope");}
static void clearFailureStillDisposesOnce(){Fixture f;Scopes scopes;f.add(scopes);scopes.begin();scopes.mutated=true;failClear=true;rejects([&]{scopes.close();});scopes.close();check(f.helper.disposes==1 && !f.helper.suspended,"Clear failure leaked/doubled suspension");}
static void disposeFailureIsNotRetried(){Fixture f;Scopes scopes;f.add(scopes);scopes.begin();scopes.mutated=true;failDispose=true;rejects([&]{scopes.close();});scopes.close();check(f.helper.disposes==1,"throwing Dispose retried original side effects");}
int main(){try{
    spansOriginalRecreation();noMutationPreservesGroup();failureBeforeOriginalBegin();
    originalBeginFinallyStillNeedsDispose();wrongReturnedScopeStillClosesOwnedHelper();
    clearFailureStillDisposesOnce();disposeFailureIsNotRetried();
    std::cout<<"actor lifetime:7 actual-source scope/failure authored groups PASS; no Unity/IL2CPP/native engine execution\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
