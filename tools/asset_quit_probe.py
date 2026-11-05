"""Owned234 original asset-completion Quit observation; never packaged."""
import hashlib
import json
import os
from pathlib import Path

from tools.extract_descriptors import PE, checked_input, GAME_ASSEMBLY_SHA256

RVAS = dict(loader=0x1381620, completion=0x166c650, subscribe=0x279ca00,
            applicationQuit=0x5021ad0, wantsQuit=0x3e933f0, assetsQuit=0x3e934b0)
SOURCE = r'''
const cfg=__CONFIG__;
if(Process.id!==cfg.pid)throw new Error('owned PID differs');
const journal=new File(cfg.journal,'w');
const clock=new NativeFunction(Process.getModuleByName('kernel32.dll').getExportByName('GetTickCount64'),'uint64',[]);
let seq=0,observed=null,requested=false,failed=false,inCompletion=false;
const hooks=[];
function emit(kind,data={}){const row={schema:1,sequence:++seq,pid:Process.id,tid:Process.getCurrentThreadId(),tick:Number(clock()),kind,...data};journal.write(JSON.stringify(row)+'\n');journal.flush();send(row);}
function check(value,message){if(!value)throw new Error(message);}
function guard(action){try{action();}catch(e){failed=true;emit('error',{message:String(e)});}}
function handle(p){return {operation:p.readPointer().toString(),version:p.add(8).readS32()};}
function same(a,b){return a.operation===b.operation&&a.version===b.version;}
function install(m){if(m.name.toLowerCase()!=='gameassembly.dll')return;guard(()=>{
  check(m.path.replaceAll('/','\\').toLowerCase()===cfg.module.toLowerCase(),'module path differs');
  for(const e of cfg.entries)check(Checksum.compute('sha256',m.base.add(e.rva).readByteArray(e.size))===e.sha256,'body differs: '+e.name);
  function state(){const k=m.base.add(0x6b42d98).readPointer();check(!k.isNull(),'asset class missing');const s=k.add(0xb8).readPointer();check(!s.isNull(),'asset storage missing');return {count:s.add(8).readS32(),wants:s.add(12).readU8()};}
  const quit=new NativeFunction(m.base.add(cfg.rvas.applicationQuit),'void',['pointer'],{exceptions:'propagate',traps:'all'});
  function requestQuit(){const before=state();check(!failed&&!requested&&before.count>0&&before.wants===0,'unsafe/duplicate request state');requested=true;emit('request-quit',before);quit(ptr(0));emit('request-return',state());}
  const field=new NativeFunction(m.getExportByName('il2cpp_class_get_field_from_name'),'pointer',['pointer','pointer']);
  const offset=new NativeFunction(m.getExportByName('il2cpp_field_get_offset'),'int',['pointer']);
  const cname=new NativeFunction(m.getExportByName('il2cpp_class_get_name'),'pointer',['pointer']);
  const names=['m_InternalOp','m_Version','m_LocationName','m_UnloadSceneOpExcludeReleaseCallback'];
  const strings=names.map(n=>Memory.allocUtf8String(n));
  hooks.push(Interceptor.attach(m.base.add(cfg.rvas.loader),{onEnter(args){guard(()=>{
    if(!args[1].equals(m.base.add(0x6ad8b10).readPointer()))return;
    check(observed===null,'duplicate concrete audio load');
    this.selected=true;
    observed={method:args[1],tid:this.threadId,handle:null,callback:null,subscribed:false};
    emit('loader-enter',{method:args[1].toString()});
  });},onLeave(){guard(()=>{
    if(!this.selected)return;
    check(observed.subscribed&&this.threadId===observed.tid,'loader exit lacks subscription/thread');
    emit('loader-exit',state());
    if(cfg.requestAt==='loader-return')requestQuit();
  });}}));
  hooks.push(Interceptor.attach(m.base.add(0x13817cd),function(){guard(()=>{
    if(!observed||!this.context.rdi.equals(observed.method))return;
    check(this.threadId===observed.tid,'loader thread differs');
    observed.handle=handle(this.context.rax);
    observed.callback=observed.method.add(0x38).readPointer().add(0x30).readPointer();
    check(observed.handle.operation!=='0x0'&&!observed.callback.isNull(),'operation/callback missing');
    emit('load-return',{...state(),handle:observed.handle,callback:observed.callback.toString()});
  });}));
  hooks.push(Interceptor.attach(m.base.add(cfg.rvas.subscribe),{onEnter(args){guard(()=>{
    if(!this.returnAddress.equals(m.base.add(0x1381a06)))return;
    check(observed!==null&&observed.handle!==null,'subscription without load');
    check(this.threadId===observed.tid&&same(handle(args[0]),observed.handle),'subscription identity/thread differs');
    const klass=args[2].add(0x20).readPointer();
    check(cname(klass).readCString()==='AsyncOperationHandle`1','handle class differs');
    const offsets=strings.map(n=>{const f=field(klass,n);check(!f.isNull(),'handle field missing');return offset(f);});
    check(JSON.stringify(offsets)===JSON.stringify([16,24,32,40]),'boxed handle offsets differ');
    observed.subscribed=true;
    emit('subscribe',{...state(),handle:handle(args[0]),boxedFieldOffsets:offsets,unboxedSize:32});
  });}}));
  hooks.push(Interceptor.attach(m.base.add(cfg.rvas.completion),{onEnter(args){guard(()=>{
    check(observed!==null&&observed.callback!==null,'completion without observed load');
    check(args[2].equals(observed.callback),'completion generic context differs');
    check(observed.subscribed&&this.threadId===observed.tid&&same(handle(args[1]),observed.handle),'completion identity/thread differs');
    const before=state();emit('completion-enter',{...before,handle:handle(args[1]),method:args[2].toString()});
    inCompletion=true;
    if(cfg.requestAt==='completion')requestQuit();
    else check(!failed&&requested&&before.count>0&&before.wants===1,'positive-count veto did not precede completion');
  });},onLeave(){guard(()=>{emit('completion-return',state());inCompletion=false;});}}));
  hooks.push(Interceptor.attach(m.base.add(cfg.rvas.applicationQuit),{onEnter(){guard(()=>{emit('application-quit',{...state(),inCompletion,returnRva:this.returnAddress.sub(m.base).toString()});});}}));
  hooks.push(Interceptor.attach(m.base.add(cfg.rvas.wantsQuit),{onEnter(){guard(()=>{emit('wants-enter',state());});},onLeave(r){guard(()=>{emit('wants-return',{...state(),accepted:r.toUInt32()&255});});}}));
  hooks.push(Interceptor.attach(m.base.add(cfg.rvas.assetsQuit),{onEnter(){guard(()=>{emit('assets-quit',state());});}}));
  Interceptor.flush();emit('armed',{counterWrites:0,completionCalls:0,callbackSuppression:0});
});}
const observer=Process.attachModuleObserver({onAdded:install});
emit('observer-ready');
'''


def build_source(game, output, pid, *, request_at='loader-return'):
    game, output = Path(game).resolve(), Path(output).resolve()
    root = Path(__file__).resolve().parents[1]
    owned = Path(os.environ['LOCALAPPDATA'])/'BattleAcesDiagnostics/local'
    if not all(p.is_relative_to(owned) for p in (game, output)) or type(pid) is not int or pid <= 0:
        raise ValueError('owned paths and PID required')
    if (output/'asset-quit.jsonl').exists():
        raise ValueError('fresh journal required')
    if request_at not in ('completion','loader-return'):
        raise ValueError('bounded request point required')
    original = checked_input(root.parent.parent/'BattleAcesBeta_untouched/GameAssembly.dll', GAME_ASSEMBLY_SHA256)
    current = (game/'GameAssembly.dll').read_bytes()
    if hashlib.sha256(current).hexdigest() != 'f9e14f0b45134eb96e51c4cd7c3965049ae317a64734a364e43ab8325f35d3fa':
        raise ValueError('qualified installed binary required')
    pe = PE(original)
    entries = []
    for name, rva in RVAS.items():
        size = pe.function_ends[pe.base+rva]-pe.base-rva
        start = pe.offset(pe.base+rva, size)
        body = original[start:start+size]
        if current[start:start+size] != body:
            raise ValueError('original body changed: '+name)
        entries.append(dict(name=name, rva=rva, size=size, sha256=hashlib.sha256(body).hexdigest()))
    cfg = dict(pid=pid, requestAt=request_at, module=str(game/'GameAssembly.dll'), journal=str(output/'asset-quit.jsonl'), rvas=RVAS, entries=entries)
    return SOURCE.replace('__CONFIG__', json.dumps(cfg)), cfg


def validate(rows, pid):
    def require(ok, why):
        if not ok: raise ValueError(why)
    require(rows and all(r['schema']==1 and r['pid']==pid and r['sequence']==i+1 for i,r in enumerate(rows)), 'journal identity/order differs')
    require(not any(r['kind']=='error' for r in rows), 'probe reported error')
    require(all(a['tick']<=b['tick'] for a,b in zip(rows,rows[1:])), 'clock went backwards')
    def one(kind):
        found=[r for r in rows if r['kind']==kind]
        require(len(found)==1, 'expected one '+kind)
        return found[0]
    armed=one('armed')
    require(all(armed[k]==0 for k in ('counterWrites','completionCalls','callbackSuppression')), 'probe mutation differs')
    load,sub,entry,request,returned,done = [one(k) for k in ('load-return','subscribe','completion-enter','request-quit','request-return','completion-return')]
    require(load['handle']==sub['handle']==entry['handle'] and load['handle']['operation']!='0x0', 'operation identity differs')
    require(sub['boxedFieldOffsets']==[16,24,32,40] and sub['unboxedSize']==32, 'handle ABI differs')
    require(len({r['tid'] for r in (load,sub,entry,request,returned,done)})==1, 'owner thread differs')
    exited=one('loader-exit')
    require(load['sequence']<sub['sequence']<exited['sequence']<request['sequence']<returned['sequence']<entry['sequence']<done['sequence'], 'completion order differs')
    require(load['count']==sub['count']==entry['count']==request['count']==returned['count']==1, 'real positive counter missing')
    require(request['wants']==0 and entry['wants']==1 and done['count']==0, 'request flag/decrement missing')
    calls=[r for r in rows if r['kind']=='application-quit']
    votes=[r for r in rows if r['kind']=='wants-return']
    # Frida's NativeFunction call bypasses its target's entry hook. Its single
    # authored request is journaled explicitly; the untouched callback retry
    # must independently hit the entry hook while the completion is on-stack.
    require(len(calls)==1 and len(votes)==2, 'one automatic retry and two admission results required')
    require(request['sequence']<votes[0]['sequence']<entry['sequence']<calls[0]['sequence']<done['sequence'], 'veto before completion and automatic retry not observed')
    require(calls[0]['sequence']<votes[1]['sequence'], 'retry acceptance order differs')
    require(votes[0]['count']==1 and votes[0]['accepted']==0 and votes[0]['wants']==1, 'positive-count veto missing')
    require(calls[0]['count']==votes[1]['count']==0 and votes[1]['accepted']==1 and calls[0]['wants']==1 and calls[0]['inCompletion'] is True, 'automatic retry admission missing')
    require(all(r['tid']==entry['tid'] for r in calls+votes), 'Quit thread differs')
    assets=one('assets-quit')
    require(assets['sequence']>votes[1]['sequence'], 'teardown preceded acceptance')
    return dict(passed=True, positive_counter_veto=True, original_completion_retry=True,
                physical_input=False, io_stall=False, hung_engine_recovery=False, safe_scene_cancellation=False)
