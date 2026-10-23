import copy
import json
import shutil
import subprocess
import unittest
from unittest.mock import patch
from tools.frida_attribution_unwind import build_source
from tools.attribution_unwind_metadata import validate


class UnwindTests(unittest.TestCase):
    config=dict(image=r'E:\owned\local\python.exe',runId='1'*32,eventLimit=512,fileRoots=[r'E:\owned\local\queue'])
    cwd=dict(pid=17,pebAddress='0x1000')

    def execute(self, mode):
        source=build_source(self.config,self.cwd)
        harness=r'''
const vm=require('vm'),fs=require('fs'),input=JSON.parse(fs.readFileSync(0,'utf8'));
let tid=18,calls=0;const rows=[];let host;
class P{constructor(v){this.v=Number(v);}sub(p){return new P(this.v-p.v);}toString(){return '0x'+this.v.toString(16);}}
const context=vm.createContext({Process:{arch:'x64',pointerSize:8,id:17,mainModule:{path:input.image},
 getCurrentThreadId:()=>tid,attachModuleObserver:()=>{},findModuleByAddress:()=>({name:'authored.dll',base:new P(0)})},
 ptr:v=>new P(v),Backtracer:{ACCURATE:1},setInterval:()=>0,
 send:r=>rows.push(JSON.parse(JSON.stringify(r))),Thread:{backtrace:()=>{
  calls++;
  if(input.mode==='throw')throw new Error('authored unwind failure');
  if(input.mode==='nested')vm.runInContext("emit('file-operation',{frames:frames({pc:ptr(119)})})",context);
  if(input.mode==='threads' && calls===1){tid=19;vm.runInContext("frames({pc:ptr(120)});emit('other-thread',{})",context);tid=18;}
  return [new P(33)];
 }}});
vm.runInContext(input.source,context,{timeout:1000});
vm.runInContext("emit('control-before',{})",context);
try{vm.runInContext("frames({pc:ptr(34)})",context);}catch(e){vm.runInContext("emit('authored-failure',{})",context);}
vm.runInContext("emit('control-after',{})",context);
process.stdout.write(JSON.stringify({rows,calls}));
'''
        result=subprocess.run([shutil.which('node'),'-e',harness],input=json.dumps(dict(source=source,image=self.config['image'],mode=mode)),
                              text=True,capture_output=True,check=True,timeout=5)
        return json.loads(result.stdout)

    def proof(self, rows):
        return validate(rows,pid=17,run_id=self.config['runId'])

    def test_nested_io_is_marked_without_another_unwind(self):
        result=self.execute('nested');rows=result['rows'];before=copy.deepcopy(rows)
        proof,projected=self.proof(rows)
        self.assertEqual(result['calls'],1)
        nested=[r for r in rows if r['kind']=='file-operation'];self.assertEqual(len(nested),1)
        self.assertEqual(nested[0]['observerUnwind']['depth'],1)
        self.assertEqual(nested[0]['data']['frames'],[dict(module='authored.dll',rva='0x77')])
        self.assertEqual(proof['nested_pc_frame_requests'],1)
        self.assertEqual(len(proof['rows_emitted_during_observer_unwind']),1)
        self.assertEqual(rows,before)
        self.assertEqual([r['data'] for r in rows],[r['data'] for r in projected])
        self.assertEqual([r['seq'] for r in rows],[r['seq'] for r in projected])

    def test_throwing_unwind_drains_scope_and_preserves_failure(self):
        result=self.execute('throw');proof,_=self.proof(result['rows'])
        self.assertEqual(proof['unwinds_started'],1);self.assertEqual(proof['unwinds_completed'],1)
        self.assertTrue(any(r['kind']=='authored-failure' for r in result['rows']))

    def test_scope_is_per_thread_not_a_global_nested_flag(self):
        result=self.execute('threads');proof,_=self.proof(result['rows'])
        self.assertEqual(result['calls'],2);self.assertEqual(proof['nested_pc_frame_requests'],0)
        row=next(r for r in result['rows'] if r['kind']=='other-thread')
        self.assertEqual(row['tid'],19);self.assertEqual(row['observerUnwind']['depth'],0)
        self.assertEqual(row['observerUnwind']['activeScopes'],1)

    def test_missing_false_or_inconsistent_annotations_fail(self):
        original=self.execute('nested')['rows'];cases=[]
        bad=copy.deepcopy(original);del bad[0]['observerUnwind'];cases.append(bad)
        for key,value in [('schema',True),('depth',2),('scopeId',0),('started',0),('completed',999),('activeScopes',0),('nestedPcFrames',False)]:
            bad=copy.deepcopy(original);next(r for r in bad if r['kind']=='file-operation')['observerUnwind'][key]=value;cases.append(bad)
        bad=copy.deepcopy(original);bad[-1]['observerUnwind']['nestedPcFrames']=0;cases.append(bad)
        bad=copy.deepcopy(original);bad[-1]['observerUnwind'].update(depth=1,scopeId=1,activeScopes=1,completed=0);cases.append(bad)
        for bad in cases:
            with self.assertRaises(AssertionError):self.proof(bad)

    def test_no_target_api_or_counter_suppression_added(self):
        source=build_source(self.config,self.cwd)
        for forbidden in ('Interceptor.replace(', 'new NativeFunction(', 'new NativeCallback(', 'Memory.alloc'):
            self.assertNotIn(forbidden,source)
        self.assertIn('counts[key]++;',source)
        self.assertEqual(source.count('Thread.backtrace('),1)
        self.assertIn('finally {observerUnwinds.delete(tid);observerUnwindsCompleted++;}',source)

    def test_sdk_composition_preserves_bounded_events_and_unbounded_counts(self):
        from tests.test_sdk_startup_observer import SDKStartupObserverTests
        driver=SDKStartupObserverTests();driver.setUp()
        with patch('tests.test_sdk_startup_observer.build_source',build_source):
            result=driver.execute('calls')
        proof,rows=validate(result['rows'],pid=17,run_id=driver.config['runId'])
        self.assertEqual(sum(r['kind']=='sdk-entry' for r in rows),8)
        self.assertEqual(rows[-1]['data']['sdk']['counts']['Client.ctor'],10)
        self.assertEqual(proof['unwinds_started'],8)


if __name__=='__main__':unittest.main()
