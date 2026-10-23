#pragma once
// Explicit owned diagnostic only; genuine Client/Exception, guarded Notify
// calls and original Unity local exception logging. No original SDK Notify body.
static void guardedReportErrors(CacheClientFixture& client) {
    if(!ba::flag(L"-telemetry-report-error-probe"))return;
    #include "telemetry_report_error_signatures.hpp"
    const auto type=ba::find_class("BugsnagUnity","Client");
    const auto exType=ba::find_class("System","Exception");
    ba_local::Root message(ba::api<Obj(*)(const char*)>("il2cpp_string_new")("authored-report-error165"));
    ba_local::Root exception(ba::api<Obj(*)(Obj)>("il2cpp_object_new")(exType));
    require(message.get() && exception.get(),"report error fixture allocation failed");
    void* ctorArgs[]={message.get()};invoke(method(exType,".ctor",1,0x35d90e0),exception.get(),ctorArgs);
    const auto before=instanceFields(exception.get());
    int severity=1;unsigned calls=0;
    ba::log("TELEMETRY REPORTERROR begin: version=1 thread=%lu genuineClient=1 genuineException=1",GetCurrentThreadId());
    auto call=[&](size_t rva,int count,void** args,const char* name="Notify") {
        invoke(method(type,name,count,rva),client.client(),args);
        client.unchanged();require(instanceFields(exception.get())==before,"guarded Notify changed borrowed exception");
        ba::log("TELEMETRY REPORTERROR call: version=1 thread=%lu index=%u rva=%llx returned=1 clientStable=1 exceptionStable=1",
            GetCurrentThreadId(),++calls,static_cast<unsigned long long>(rva));
    };
    void* named[]={message.get(),message.get(),message.get(),nullptr};call(0x814ef0,4,named);
    void* stack[]={exception.get(),message.get(),nullptr};call(0x815100,3,stack);
    void* basic[]={exception.get(),nullptr};call(0x815390,2,basic);
    void* selected[]={exception.get(),&severity,nullptr};call(0x8153e0,3,selected);
    void* handled[]={exception.get(),nullptr,nullptr};call(0x8154e0,3,handled);
    // Internal serialized exception collection/handled state and nullable log
    // type are deliberately absent. Verified RET must precede any dereference.
    unsigned char logType[8]={};void* collection[]={nullptr,nullptr,nullptr,logType};call(0x8157d0,4,collection);
    void* queued[]={nullptr,nullptr,nullptr,logType,nullptr};call(0x815ba0,5,queued,"NotifyOnMainThread");
    // This is a supported original LOCAL logging path, not SDK collection.
    void* logArgs[]={exception.get()};
    invoke(method(ba::find_class("UnityEngine","Debug"),"LogException",1,0x502fa60),nullptr,logArgs);
    client.unchanged();
    require(calls==7,"report error fixture coverage differs");
    ba::log("TELEMETRY REPORTERROR probe passed: version=1 thread=%lu calls=7 genuineClient=1 genuineException=1 nullOptionalInputs=1 clientFieldsUnchanged=1 globalCallbackHeadsUnchanged=4 originalUnityExceptionLog=1 reportDelivered=0 wholeRunIsolation=0",GetCurrentThreadId());
}
