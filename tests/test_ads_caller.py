"""Executable authored controls for the isolated caller witness; no game run."""
import copy
import json
import shutil
import subprocess
import unittest
from unittest.mock import patch

from tools.frida_ads_caller import build_source, validate, describe_unity, RECIPE_VERSION


HARNESS = r'''
const fs=require('fs'),vm=require('vm'),input=JSON.parse(fs.readFileSync(0,'utf8'));
const rows=[],reads=[],hooks=new Map();let observer,detached=0,observerDetached=0;
let bodyBad=input.mode==='body',guardBad=input.mode==='guard';
class P{
 constructor(v){this.v=v;}
 add(v){return new P(this.v+v);}
 sub(p){return new P(this.v-p.v);}
 toString(){return '0x'+this.v.toString(16);}
 readByteArray(n){
  reads.push({address:this.v,size:n});
  if(this.v===0x180c307c0&&n===177)return new Uint8Array(n).buffer;
  if(this.v===0x180c30838&&n===5)return new Uint8Array(5).fill(guardBad?0:144).buffer;
  throw new Error('unexpected memory read');
 }
}
const module={name:'UnityPlayer.dll',path:input.config.image.replace('Battle Aces.exe','UnityPlayer.dll'),base:new P(0x180000000),size:0x2000000};
if(input.mode==='path')module.path='C:\\foreign\\UnityPlayer.dll';
if(input.mode==='size')module.size=16;
const host={Process:{arch:'x64',pointerSize:8,id:input.config.pid,mainModule:{path:input.config.image},
 getCurrentThreadId:()=>29,attachModuleObserver:o=>{observer=o;if(input.mode!=='missing')o.onAdded(module);return{detach(){observerDetached++;}};},
 findModuleByAddress:p=>p.v>=0x180000000&&p.v<0x182000000?module:null},
 Thread:{backtrace:()=>{if(input.mode==='backtrace')throw new Error('unwind unavailable');return[new P(0x180345678),new P(17)];}},
 Backtracer:{ACCURATE:1},Checksum:{compute:()=>bodyBad?'f'.repeat(64):input.config.unity.bodySha256},
 Interceptor:{attach:(p,h)=>{hooks.set(p.v,h);return{detach(){detached++;}};}},
 send:r=>rows.push(JSON.parse(JSON.stringify(r))),rpc:{exports:{}}};
if(input.mode==='pid')host.Process.id++;
let error=null;
try{
 vm.runInNewContext(input.source,host,{timeout:1000});
 if(hooks.size){
  const invocation={context:{},returnAddress:new P(input.mode==='unknown'?17:0x180123456)};
  Object.defineProperty(invocation,'args',{get(){throw new Error('arguments read');}});
  for(let i=0;i<input.calls;i++)hooks.get(0x180c307c0).onEnter.call(invocation);
 }
 if(input.mode==='reload')observer.onAdded(module);
 if(input.mode==='unload')observer.onRemoved(module);
 if(input.mode==='final-guard')guardBad=true;
 const before=host.rpc.exports.snapshot();
 const final=host.rpc.exports.finish();
 let repeatedRejected=false;
 try{host.rpc.exports.finish();}catch(_){repeatedRejected=true;}
 process.stdout.write(JSON.stringify({rows,reads,hookCount:hooks.size,detached,observerDetached,before,final,repeatedRejected}));
}catch(e){process.stdout.write(JSON.stringify({rows,reads,hookCount:hooks.size,error:String(e)}));}
'''


class AdsCallerTests(unittest.TestCase):
    def setUp(self):
        game = r'E:\owned\local\adscaller_0123456789ab'
        profile = 'nativestest_adscaller_0123456789ab'
        self.config = dict(image=game+r'\Battle Aces.exe',profile=game+'\\.battleaces-resurrection\\profiles\\'+profile,
            argv=[game+r'\Battle Aces.exe','-local-profile='+profile],pid=123,runId='1'*32,
            unity=dict(recipe=RECIPE_VERSION,fileSha256='2'*64,bodySha256='3'*64))

    def run_js(self, mode='', calls=0):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node is required for executable observer controls')
        result = subprocess.run([node,'-e',HARNESS],input=json.dumps(dict(source=build_source(self.config),config=self.config,mode=mode,calls=calls)),
                                text=True,capture_output=True,check=True,timeout=5)
        return json.loads(result.stdout)

    def test_owned_configuration_and_audit_conflicts_reject(self):
        variants=[]
        for key,value in [('pid',True),('runId','bad'),('profile',r'Z:\fixture\profile'),('image',r'Z:\fixture\Battle Aces.exe'),('unity',{}),('argv',[])]:
            bad=copy.deepcopy(self.config);bad[key]=value;variants.append(bad)
        for flag in ('-telemetry-audit','-TELEMETRY-AUDIT=1','-telemetry-device-probe','-local-profile=manual'):
            bad=copy.deepcopy(self.config);bad['argv'].append(flag);variants.append(bad)
        bad=copy.deepcopy(self.config);bad['unity']['recipe']=True;variants.append(bad)
        bad=copy.deepcopy(self.config);bad['extra']=1;variants.append(bad)
        for bad in variants:
            with self.subTest(bad=bad),self.assertRaises(ValueError):build_source(bad)

    def test_real_original_identity_is_required_before_description(self):
        with self.assertRaises(ValueError):describe_unity(b'not the original',b'installed')
        with patch('tools.frida_ads_caller.patch_component',return_value=b'expected'), \
                patch('tools.frida_ads_caller.update_checksum',side_effect=lambda b:b):
            with self.assertRaisesRegex(ValueError,'complete current recipe'):
                describe_unity(b'original',b'different')

    def test_positive_callers_and_counts_survive_record_budget(self):
        result=self.run_js(calls=13)
        self.assertNotIn('error',result)
        report=validate(result['rows'],self.config)
        self.assertEqual((report['calls'],report['caller_records'],report['suppressed']),(13,8,5))
        self.assertFalse(report['producer_resolved'])
        self.assertFalse(report['full_privacy_qualified'])
        self.assertFalse(report['whole_process_coverage'])
        entry=result['rows'][2]['data']
        self.assertEqual(entry['caller'],dict(module='unityplayer.dll',rva='0x123456'))
        self.assertEqual(entry['frames'],[dict(module='unityplayer.dll',rva='0x345678'),dict(module=None,rva=None)])
        self.assertEqual((result['hookCount'],result['detached'],result['observerDetached']),(1,1,1))
        self.assertTrue(result['repeatedRejected'])
        self.assertEqual(result['reads'],[dict(address=0x180c307c0,size=177),dict(address=0x180c30838,size=5),dict(address=0x180c30838,size=5)])

    def test_quiet_interval_and_unknown_caller_do_not_become_absence_proof(self):
        quiet=validate(self.run_js()['rows'],self.config)
        self.assertEqual(quiet['calls'],0)
        self.assertFalse(quiet['whole_process_coverage'])
        rows=self.run_js('unknown',1)['rows']
        self.assertEqual(rows[2]['data']['caller'],dict(module=None,rva=None))
        self.assertEqual(validate(rows,self.config)['calls'],1)

    def test_path_body_guard_and_size_mismatch_install_no_hook(self):
        for mode in ('path','body','guard','size','pid','missing'):
            with self.subTest(mode=mode):
                result=self.run_js(mode)
                self.assertEqual(result['hookCount'],0)
                with self.assertRaises(ValueError):validate(result['rows'],self.config)

    def test_reload_unload_unwind_and_final_guard_failure_reject(self):
        for mode in ('reload','unload','backtrace','final-guard'):
            with self.subTest(mode=mode):
                result=self.run_js(mode,1)
                self.assertEqual(result['detached'],1)
                self.assertTrue(any(row['kind']=='ads-error' for row in result['rows']))
                with self.assertRaises(ValueError):validate(result['rows'],self.config)

    def test_lost_reordered_forged_and_noninteger_evidence_rejects(self):
        rows=self.run_js(calls=3)['rows'];bad_rows=[]
        bad_rows.extend([rows[:-1],rows[1:],rows[:2]+rows[3:]])
        for index,key,value in [(0,'pid',True),(0,'tid',0),(2,'elapsedMs',-1),(2,'runId','f'*32)]:
            bad=copy.deepcopy(rows);bad[index][key]=value;bad_rows.append(bad)
        for key,value in [('calls',True),('records',True),('guardIntact',1),('hookDetached',False),('failed',True),('suppressed',1),('calls',4)]:
            bad=copy.deepcopy(rows);bad[-1]['data'][key]=value;bad_rows.append(bad)
        for key,value in [('caller',dict(module='C:\\private\\id',rva='0x1')),('call',True),('frames',[dict(module=None,rva=None)]*9),('payload','unexpected')]:
            bad=copy.deepcopy(rows);bad[2]['data'][key]=value;bad_rows.append(bad)
        bad=copy.deepcopy(rows);bad[1]['data']['descriptor']['fileSha256']='a'*64;bad_rows.append(bad)
        bad=copy.deepcopy(rows);bad[0]['data']['argumentsRead']=0;bad_rows.append(bad)
        for bad in bad_rows:
            with self.subTest(bad=bad),self.assertRaises(ValueError):validate(bad,self.config)


if __name__=='__main__':unittest.main()
