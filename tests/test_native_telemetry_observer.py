import copy
import json
import shutil
import subprocess
import unittest
from tools.frida_native_telemetry import build_source,ENTRIES,OBSERVED


class NativeTelemetryObserver(unittest.TestCase):
    def setUp(self):
        self.config=dict(image=r'E:\owned\local\game\Battle Aces.exe',runId='1'*32,eventLimit=4096,
            fileRoots=[r'E:\owned\shared',r'E:\owned\local\game\.battleaces-resurrection\profiles\nativestest_authored'])
        self.cwd=dict(pid=17,pebAddress='0x1000')
        self.native=dict(module=r'E:\owned\local\game\UnityPlayer.dll',
            entries=[dict(name=k,rva=v,sha256='0'*64) for k,v in ENTRIES.items()])

    def test_foreign_partial_ambiguous_and_noninteger_witnesses_reject(self):
        for field,value in [('module',r'C:\foreign\UnityPlayer.dll'),('entries',self.native['entries'][:-1])]:
            bad=copy.deepcopy(self.native);bad[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):build_source(self.config,self.cwd,bad)
        for field,value in [('rva',True),('name','unknown'),('sha256','invalid')]:
            bad=copy.deepcopy(self.native);bad['entries'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):build_source(self.config,self.cwd,bad)
        bad=copy.deepcopy(self.native);bad['entries'][-1]=bad['entries'][0]
        with self.assertRaises(ValueError):build_source(self.config,self.cwd,bad)

    def test_executable_counter_survives_caller_event_budget(self):
        source=build_source(self.config,self.cwd,self.native)
        harness=r'''
const fs=require('fs'),vm=require('vm'),input=JSON.parse(fs.readFileSync(0,'utf8'));
const rows=[],hooks=new Map(),timers=[];
class P{constructor(v){this.v=Number(v);}add(v){return new P(this.v+v);}toString(){return '0x'+this.v.toString(16);}readByteArray(n){return new ArrayBuffer(n);}}
const module={name:'UnityPlayer.dll',path:input.native.module,base:new P(0)};
const host={Process:{arch:'x64',pointerSize:8,id:17,mainModule:{path:input.config.image},
 getCurrentThreadId:()=>18,attachModuleObserver:o=>o.onAdded(module),findModuleByAddress:()=>null},
 Thread:{backtrace:()=>[]},Backtracer:{ACCURATE:1},Checksum:{compute:()=>('0'.repeat(64))},
 Interceptor:{attach:(p,h)=>hooks.set(p.v,h)},send:r=>rows.push(JSON.parse(JSON.stringify(r))),
 setInterval:f=>timers.push(f)};
vm.runInNewContext(input.source,host,{timeout:1000});
for(let i=0;i<10;i++)hooks.get(input.native.entries.find(e=>e.name===input.observed[0]).rva).onEnter.call({context:{}});
timers[0]();process.stdout.write(JSON.stringify({rows,hookCount:hooks.size}));
'''
        result=subprocess.run([shutil.which('node'),'-e',harness],input=json.dumps(dict(source=source,config=self.config,native=self.native,observed=sorted(OBSERVED))),
                              text=True,capture_output=True,check=True,timeout=5)
        value=json.loads(result.stdout);rows=value['rows']
        self.assertEqual(value['hookCount'],len(OBSERVED))
        self.assertFalse(any(r['kind']=='decode-error' for r in rows))
        self.assertEqual(sum(r['kind']=='native-telemetry-entry' for r in rows),8)
        last=rows[-1]['data']['nativeTelemetry'];self.assertTrue(last['installed'])
        self.assertEqual(last['counts'][sorted(OBSERVED)[0]],10)
        self.assertEqual(set(last['counts']),OBSERVED)
        self.assertTrue(all(last['counts'][name]==0 for name in OBSERVED-{sorted(OBSERVED)[0]}))
