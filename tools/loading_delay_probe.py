"""Owned208 one-shot iterator delay. Diagnostic only; never shipped to players."""
import hashlib
import json
import os
from pathlib import Path
import re

from tools.extract_descriptors import PE, checked_input, GAME_ASSEMBLY_SHA256

ENTRIES = {'joined':0x3e506b0,'create':0x3e67540,'move':0x3dbcf80,
           'complete':0x3e69c70,'cleanup':0x3e51ba0}
QUIT_ENTRIES = {'wantsQuit':0x3e933f0, 'assetsQuit':0x3e934b0,
                'uiQuit':0x3d06f50, 'applicationQuit':0x5021ad0}

SOURCE = r'''
const cfg=__CONFIG__;
if(Process.id!==cfg.pid)throw new Error('owned PID differs');
const clock=new NativeFunction(Process.getModuleByName('kernel32.dll').getExportByName('GetTickCount64'),'uint64',[]);
const journal=new File(cfg.journal,'w');
let sequence=0,server=ptr(0),sim=ptr(0),manager=ptr(0),iterator=ptr(0);
let began=0,released=false,heldCalls=0,lastSample=0,thread=0,original=null,replacement=null;
let quitting=false,assetTypeSlot=ptr(0);
const hooks=[];
function now(){return Number(clock());}
function emit(kind,data={}){
  const row={schema:1,sequence:++sequence,pid:Process.id,tid:Process.getCurrentThreadId(),tick:now(),kind,...data};
  journal.write(JSON.stringify(row)+'\n');journal.flush();send(row);
}
function state(){return {mapLoading:server.isNull()?null:server.add(0xd8).readU8(),
  active:sim.isNull()?null:sim.add(0x1a0).readU8(),world:sim.isNull()?null:!sim.add(0x1a8).readPointer().isNull()};}
function assetState(){
  const klass=assetTypeSlot.readPointer();
  if(klass.isNull())throw new Error('asset class unavailable');
  const fields=klass.add(0xb8).readPointer();
  if(fields.isNull())throw new Error('asset static storage unavailable');
  return {assetLoadingCount:fields.add(8).readS32(),wantsToQuit:fields.add(12).readU8()};
}
function install(module){
  if(module.name.toLowerCase()!=='gameassembly.dll')return;
  try{
    if(module.path.replaceAll('/','\\').toLowerCase()!==cfg.module.toLowerCase())throw new Error('module path differs');
    for(const entry of cfg.entries)
      if(Checksum.compute('sha256',module.base.add(entry.rva).readByteArray(entry.size))!==entry.sha256)
        throw new Error('entry bytes differ: '+entry.name);
    if(cfg.holdUntilQuit){
      assetTypeSlot=module.base.add(cfg.assetTypeSlot);
      for(const name of ['uiQuit','applicationQuit'])
        hooks.push(Interceptor.attach(module.base.add(cfg.rvas[name]),{onEnter(){
          emit(name+'-enter',{...state(),...assetState()});
        }}));
      hooks.push(Interceptor.attach(module.base.add(cfg.rvas.wantsQuit),{onEnter(){
        emit('wants-quit-enter',{...state(),...assetState()});
      },onLeave(result){
        emit('wants-quit-return',{...state(),...assetState(),accepted:result.toUInt32()&255});
      }}));
      hooks.push(Interceptor.attach(module.base.add(cfg.rvas.assetsQuit),{onEnter(){
        quitting=true;emit('assets-quit-enter');
      }}));
    }
    hooks.push(Interceptor.attach(module.base.add(cfg.rvas.joined),{onEnter(args){
      if(server.isNull()){server=args[0];emit('joined-entry');}
    }}));
    hooks.push(Interceptor.attach(module.base.add(cfg.rvas.create),{onEnter(args){
      if(sim.isNull()&&!server.isNull()){
        sim=args[0];
        if(!server.add(0x140).readPointer().equals(sim)){emit('error',{message:'simulation owner differs'});return;}
        manager=sim.add(0x78).readPointer();emit('create-entry',state());
      }
    }}));
    hooks.push(Interceptor.attach(module.base.add(cfg.rvas.complete),{onEnter(){
      emit('complete-enter',state());
    },onLeave(){emit('complete-return',state());}}));
    hooks.push(Interceptor.attach(module.base.add(cfg.rvas.cleanup),{onEnter(args){
      if(args[0].equals(server))emit('cleanup-enter',{...state(),reason:args[1].toInt32(),stay:args[2].toInt32()});
    }}));
    replacement=new NativeCallback(function(self,method){
      try{
        if(!released&&!manager.isNull()&&self.add(0x18).readPointer().equals(manager)){
          if(iterator.isNull()){
            if(self.add(0x10).readS32()!==0||self.add(0x14).readFloat()!==0)throw new Error('first iterator state differs');
            iterator=self;thread=Process.getCurrentThreadId();began=now();emit('hold-start',state());
          }
          if(!iterator.equals(self)||Process.getCurrentThreadId()!==thread)throw new Error('iterator owner/thread changed');
          const tick=now();
          if(cfg.holdUntilQuit||tick-began<cfg.delayMs){
            ++heldCalls;
            if(!quitting&&tick-lastSample>=1000){lastSample=tick;emit('hold-sample',{
              ...state(),...(cfg.holdUntilQuit?assetState():{}),heldCalls});}
            return 1;
          }
          released=true;emit('hold-release',{...state(),heldCalls,elapsedMs:tick-began});
        }
      }catch(error){released=true;emit('error',{message:String(error)});}
      return original(self,method)?1:0;
    },'bool',['pointer','pointer']);
    const trampoline=Interceptor.replaceFast(module.base.add(cfg.rvas.move),replacement);
    original=new NativeFunction(trampoline,'bool',['pointer','pointer'],{exceptions:'propagate'});
    Interceptor.flush();emit('armed',{delayMs:cfg.delayMs,holdUntilQuit:cfg.holdUntilQuit});
  }catch(error){emit('error',{message:String(error)});}
}
const observer=Process.attachModuleObserver({onAdded:install});
'''


def build_source(game, output, pid, *, delay_ms=130000, pending_quit=False):
    game,output=Path(game).resolve(),Path(output).resolve()
    root=Path(__file__).resolve().parents[1]
    local=Path(os.environ.get('LOCALAPPDATA',''))/'BattleAcesDiagnostics/local'
    roots=[root/'local']+([local.resolve()] if local.is_absolute() else [])
    if not all(any(path.is_relative_to(base) for base in roots) for path in (game,output)) or \
            type(pid) is not int or pid<=0 or delay_ms!=130000 or type(pending_quit) is not bool:
        raise ValueError('exact owned diagnostic paths/PID/130s delay required')
    data=checked_input(root.parent.parent/'BattleAcesBeta_untouched/GameAssembly.dll',GAME_ASSEMBLY_SHA256)
    installed=(game/'GameAssembly.dll').read_bytes();pe=PE(data);entries=[]
    if hashlib.sha256(installed).hexdigest()!='f9e14f0b45134eb96e51c4cd7c3965049ae317a64734a364e43ab8325f35d3fa':
        raise ValueError('exact qualified recipe23 installed GameAssembly required')
    if (output/'loading-delay.jsonl').exists():raise ValueError('fresh owned delay journal required')
    rvas=ENTRIES | (QUIT_ENTRIES if pending_quit else {})
    if pending_quit:
        from tools.review_scene_release import review_quit_admission
        review_quit_admission(root.parent.parent/'BattleAcesBeta_untouched',game,root/'local/native-quit-contract01')
    for name,rva in rvas.items():
        end=pe.function_ends[pe.base+rva];size=end-pe.base-rva;offset=pe.offset(pe.base+rva,size)
        raw=data[offset:offset+size];patched=installed[offset:offset+size]
        changed=[rva+i for i,(a,b) in enumerate(zip(raw,patched)) if a!=b]
        allowed={'joined':list(range(0x3e50db7,0x3e50dbb)),
                 'cleanup':list(range(0x3e51d95,0x3e51d99))}.get(name,[])
        if changed!=allowed:raise ValueError('installed delay/observation body differs: '+name)
        entries.append(dict(name=name,rva=rva,size=size,sha256=hashlib.sha256(patched).hexdigest(),
                            original_sha256=hashlib.sha256(raw).hexdigest(),changed_offsets=changed))
    config=dict(pid=pid,module=str(game/'GameAssembly.dll'),journal=str(output/'loading-delay.jsonl'),
                delayMs=None if pending_quit else delay_ms,holdUntilQuit=pending_quit,
                assetTypeSlot=0x6b42d98 if pending_quit else None,rvas=rvas,entries=entries)
    return SOURCE.replace('__CONFIG__',json.dumps(config)),config


def read_rows(path):
    raw=Path(path).read_bytes()
    if len(raw)>256*1024:raise ValueError('delay journal exceeds bound')
    end=raw.rfind(b'\n')
    return [json.loads(line) for line in raw[:end+1].splitlines()]


def armed(rows,pid):
    if any(r.get('kind')=='error' for r in rows):raise ValueError('native delay probe reported an error')
    return any(r.get('kind')=='armed' and r.get('pid')==pid for r in rows)


def validate(rows,log,pid):
    def require(value,message):
        if not value:raise ValueError(message)
    require(rows and all(r['schema']==1 and r['pid']==pid and r['sequence']==i+1 for i,r in enumerate(rows)),
            'delay journal identity/order differs')
    require(armed(rows,pid),'delay probe not armed')
    require(all(a['tick']<=b['tick'] for a,b in zip(rows,rows[1:])),'delay clock went backwards')
    def single(kind):
        selected=[r for r in rows if r['kind']==kind]
        require(len(selected)==1,'one '+kind+' required');return selected[0]
    start,release=single('hold-start'),single('hold-release')
    require(release['tick']-start['tick']>=130000 and 130000<=release['elapsedMs']<140000,
            'real130s hold missing')
    samples=[r for r in rows if r['kind']=='hold-sample']
    require(len(samples)>=120 and release['heldCalls']>=120 and
            all(r['tid']==start['tid'] and r['mapLoading']==1 and r['active']==0 and r['world'] is False for r in samples),
            'Unity-thread pumping/pending-world evidence differs')
    require(all(b['tick']-a['tick']<5000 for a,b in zip(samples,samples[1:])),
            'native loader stopped pumping during hold')
    deadline=re.findall(r'^\[(\d+)\] Dedicated cleanup exceeded 120s; retaining native state, process restart required',log,re.M)
    require(len(deadline)==1 and start['tick']+120000<=int(deadline[0])<release['tick'],
            'real120s recovery diagnostic not crossed while held')
    complete=[r for r in rows if r['kind']=='complete-return']
    cleanup=[r for r in rows if r['kind']=='cleanup-enter']
    require(complete and cleanup and release['sequence']<complete[0]['sequence']<cleanup[0]['sequence'] and
            complete[0]['mapLoading']==0 and complete[0]['active']==1 and complete[0]['world'] is True,
            'original callback did not finish before cleanup')
    require(all(r['mapLoading']==0 for r in cleanup) and cleanup[0]['reason']==1,
            'cleanup ran while map loading or with wrong reason')
    require(all(r['tick']>=release['tick'] for r in rows if r['kind'] in ('complete-enter','cleanup-enter')),
            'world callback or cleanup ran during hold')
    require('Public intent retired: ticket=2 reason=returned nativeIdle=1 disconnect=0' in log,
            'replacement match did not return to idle')
    return dict(passed=True,held_calls=release['heldCalls'],samples=len(samples),held_ms=release['elapsedMs'],
                original_callback_before_cleanup=True,cleanup_while_loading=False,real120s_diagnostic=True)


def validate_pending_quit(rows, log, pid, *, game_exit, launcher_exit, forced_cleanup):
    """Qualify a held pre-scene iterator, never a permanently hung Unity engine."""
    def require(value, message):
        if not value:raise ValueError(message)
    require(rows and all(r['schema']==1 and r['pid']==pid and r['sequence']==i+1 for i,r in enumerate(rows)),
            'pending Quit journal identity/order differs')
    require(armed(rows,pid), 'pending Quit probe not armed')
    require(all(a['tick']<=b['tick'] for a,b in zip(rows,rows[1:])), 'pending Quit clock went backwards')
    def single(kind):
        selected=[r for r in rows if r['kind']==kind]
        require(len(selected)==1, 'one '+kind+' required')
        return selected[0]
    arm=single('armed')
    require(arm.get('holdUntilQuit') is True and arm.get('delayMs') is None,
            'hold must not release on a timer')
    start=single('hold-start')
    ui, application, enter, returned = [single(k) for k in
        ('uiQuit-enter','applicationQuit-enter','wants-quit-enter','wants-quit-return')]
    require(start['sequence']<ui['sequence']<application['sequence']<enter['sequence']<returned['sequence'],
            'original pending Quit route order differs')
    require(not any(r['kind'] in ('hold-release','complete-enter','complete-return') for r in rows),
            'held load was released or completed')
    samples=[r for r in rows if r['kind']=='hold-sample' and r['sequence']<ui['sequence']]
    require(len(samples)>=120 and samples[-1]['heldCalls']>=120, 'real pending load samples missing')
    pending=[start,*samples,ui,application,enter,returned]
    require(all(r['tid']==start['tid'] and r['mapLoading']==1 and r['active']==0 and r['world'] is False
                for r in pending), 'pending Quit owner/thread/world differs')
    require(all(0<=b['tick']-a['tick']<5000 for a,b in zip([start,*samples], [*samples,ui])),
            'pending loader stopped pumping before Quit')
    require(all(type(r.get('assetLoadingCount')) is int and r.get('wantsToQuit') in (0,1)
                for r in [*samples,ui,application,enter,returned]), 'asset counter observation missing')
    require(enter['wantsToQuit']==0 and returned['wantsToQuit']==1 and
            returned['accepted'] in (0,1) and
            returned['accepted']==int(returned['assetLoadingCount']<=0), 'native asset veto observation differs')
    deadline=re.findall(r'^\[(\d+)\] Dedicated cleanup exceeded 120s; retaining native state, process restart required',log,re.M)
    require(len(deadline)==1 and start['tick']+120000<=int(deadline[0])<ui['tick'],
            'real120s diagnostic missing before pending Quit')
    require(log.count('PENDING LOAD QUIT SMOKE BA_RESURRECTION_PENDING_LOAD_QUIT_V1: blocked=1 mapLoading=1 ')==1 and
            log.count('QUIT SMOKE invoking original disconnected modal OnCancel (NOT manual UI input)')==1,
            'original disconnected-modal diagnostic dispatch missing')
    require(not any('Public intent retired: ticket=2' in line or 'RECOVERY SMOKE' in line for line in log.splitlines()),
            'unexpected recovery/replacement match')
    accepted=returned['accepted']==1
    cleanups=[r for r in rows if r['kind']=='cleanup-enter']
    require(all(accepted and r['sequence']>returned['sequence'] for r in cleanups),
            'cleanup preceded native Quit admission')
    quitting=[r for r in rows if r['kind']=='assets-quit-enter']
    require((len(quitting)==1 and quitting[0]['sequence']>returned['sequence']) if accepted else not quitting,
            'asset quitting callback contradicts admission')
    normal_exit=type(game_exit) is int and type(launcher_exit) is int and game_exit==launcher_exit==0
    require(type(forced_cleanup) is bool, 'explicit cleanup disposition required')
    return dict(passed=accepted and normal_exit and not forced_cleanup, admission_observed=True,
                original_quit_accepted=accepted, asset_loading_count=returned['assetLoadingCount'],
                held_until_quit=True, samples=len(samples), held_ms=ui['tick']-start['tick'],
                normal_exit=normal_exit, forced_cleanup=forced_cleanup,
                cleanup_after_admission=len(cleanups), positive_counter_recovery_proved=False,
                safe_cancellation_proved=False, hung_engine_recovery_proved=False)
