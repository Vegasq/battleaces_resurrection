import copy
import json
import shutil
import subprocess
import unittest
from tools.frida_sdk_startup import build_source,ENTRIES


class SDKStartupObserverTests(unittest.TestCase):
    def setUp(self):
        self.config=dict(image=r'E:\owned\local\game\Battle Aces.exe',runId='1'*32,eventLimit=4096,
            fileRoots=[r'E:\owned\shared',r'E:\owned\local\game\.battleaces-resurrection\profiles\nativestest_authored'])
        self.cwd=dict(pid=17,pebAddress='0x1000')
        self.sdk=dict(module=r'E:\owned\local\game\GameAssembly.dll',
            entries=[dict(name=k,rva=v,sha256='0'*64) for k,v in ENTRIES.items()])

    def test_foreign_partial_duplicate_unknown_and_noninteger_witnesses_reject(self):
        cases=[]
        for field,value in [('module',r'C:\foreign\GameAssembly.dll'),('entries',self.sdk['entries'][:-1])]:
            bad=copy.deepcopy(self.sdk);bad[field]=value;cases.append(bad)
        for field,value in [('rva',True),('name','unknown'),('sha256','invalid')]:
            bad=copy.deepcopy(self.sdk);bad['entries'][0][field]=value;cases.append(bad)
        bad=copy.deepcopy(self.sdk);bad['entries'][-1]=bad['entries'][0];cases.append(bad)
        for bad in cases:
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                build_source(self.config,self.cwd,bad)

    def test_ordinary_profile_has_no_root_or_target_api_replacement(self):
        source=build_source(self.config,self.cwd,self.sdk)
        for forbidden in ('Interceptor.replace(', 'new NativeFunction(', 'new NativeCallback(',
                          'Memory.alloc', 'makeString(', 'cacheInstall('):
            self.assertNotIn(forbidden,source)
        self.assertIn('sdkRootReplaced:false',source)
        self.assertEqual(source.count('sdk:sdkSnapshot()'),3)
        self.assertIn('Thread.sleep(0.2)',source)

    def execute(self,mode):
        source=build_source(self.config,self.cwd,self.sdk)
        harness=r'''
const fs=require('fs'),vm=require('vm'),input=JSON.parse(fs.readFileSync(0,'utf8'));
const rows=[],hooks=new Map(),timers=[];
class P{constructor(v){this.v=Number(v);}add(v){return new P(this.v+v);}toString(){return '0x'+this.v.toString(16);}readByteArray(n){return new ArrayBuffer(n);}}
const module={name:'GameAssembly.dll',path:input.sdk.module,base:new P(0)};
const host={Process:{arch:'x64',pointerSize:8,id:17,mainModule:{path:input.config.image},
 getCurrentThreadId:()=>18,attachModuleObserver:o=>{o.onAdded(module);if(input.mode==='reload')o.onAdded(module);},findModuleByAddress:()=>null},
 Thread:{backtrace:()=>[]},Backtracer:{ACCURATE:1},Checksum:{compute:()=>((input.mode==='hash'?'f':'0').repeat(64))},
 Interceptor:{attach:(p,h)=>hooks.set(p.v,h)},send:r=>rows.push(JSON.parse(JSON.stringify(r))),
 setInterval:f=>timers.push(f)};
vm.runInNewContext(input.source,host,{timeout:1000});
if(input.mode==='calls')for(let i=0;i<10;i++)hooks.get(input.sdk.entries[0].rva).onEnter.call({context:{}});
timers[0]();process.stdout.write(JSON.stringify({rows,hookCount:hooks.size}));
'''
        result=subprocess.run([shutil.which('node'),'-e',harness],input=json.dumps(dict(
            source=source,config=self.config,sdk=self.sdk,mode=mode)),
            text=True,capture_output=True,check=True,timeout=5)
        return json.loads(result.stdout)

    def test_actual_callback_code_counts_beyond_bounded_entry_events(self):
        value=self.execute('calls');rows=value['rows']
        self.assertEqual(value['hookCount'],len(ENTRIES))
        self.assertFalse(any(r['kind']=='decode-error' for r in rows))
        self.assertEqual(sum(r['kind']=='sdk-entry' for r in rows),8)
        last=rows[-1]['data']['sdk'];self.assertTrue(last['installed'])
        self.assertEqual(last['counts']['Client.ctor'],10)
        self.assertEqual(set(last['counts']),set(ENTRIES))
        self.assertTrue(all(last['counts'][name]==0 for name in set(ENTRIES)-{'Client.ctor'}))

    def test_bad_entry_hash_installs_no_sdk_hooks_and_records_error(self):
        value=self.execute('hash')
        self.assertEqual(value['hookCount'],0)
        self.assertEqual(sum(r['kind']=='sdk-installed' for r in value['rows']),0)
        self.assertFalse(value['rows'][-1]['data']['sdk']['installed'])
        self.assertTrue(value['rows'][-1]['data']['errors'])

    def test_same_module_reloaded_cannot_silently_rearm_counts(self):
        value=self.execute('reload')
        self.assertEqual(sum(r['kind']=='sdk-installed' for r in value['rows']),1)
        self.assertEqual(sum(r['kind']=='decode-error' for r in value['rows']),1)
        self.assertTrue(value['rows'][-1]['data']['errors'])
