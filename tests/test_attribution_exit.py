"""Execute generated callbacks against an authored JS host;runtime control separate."""
import json
import shutil
import subprocess
import unittest
from copy import deepcopy
from tools.attribution_exit_metadata import validate,validate_cache
from tools.frida_cache_startup import OBSERVED
from tools.frida_attribution_exit import build_source
from tools.frida_attribution_cwd import build_source as legacy


class ExitObservation(unittest.TestCase):
    def test_aliases_self_status_and_foreign_request_are_distinct(self):
        config=dict(image=r'E:\owned\local\game\Battle Aces.exe',runId='1'*32,
                    eventLimit=1000,fileRoots=[r'E:\owned\local\game'])
        cwd=dict(pid=17,pebAddress='0x1000')
        before=legacy(config,cwd)
        source=build_source(config,cwd)
        self.assertEqual(legacy(config,cwd),before)
        node=shutil.which('node')
        self.assertIsNotNone(node,'Node required for executable callback test')
        harness=r'''
const fs=require('fs'),vm=require('vm'),input=JSON.parse(fs.readFileSync(0,'utf8'));
const messages=[],sleeps=[],hooks=new Map();
class P {
 constructor(v){this.v=String(v);}
 toString(){return this.v;}
 equals(p){return this.v===p.v;}
 toUInt32(){return Number(this.v)>>>0;}
}
const modules=['kernelbase.dll','kernel32.dll'].map(name=>({name,path:name,
 findExportByName(n){return new P(n==='TerminateProcess'?'shared-terminate':name+':'+n);}}));
const host={Process:{arch:'x64',pointerSize:8,id:17,mainModule:{path:input.config.image},
 getCurrentThreadId:()=>18,attachModuleObserver:o=>modules.forEach(m=>o.onAdded(m)),
 findModuleByAddress:()=>null},Thread:{backtrace:()=>[new P('0x1111')],sleep:s=>sleeps.push(s)},
 Backtracer:{ACCURATE:1},Interceptor:{attach:(p,c)=>hooks.set(p.toString(),c)},
 ptr:v=>new P(v),send:m=>messages.push(JSON.parse(JSON.stringify(m))),setInterval:()=>{}};
vm.runInNewContext(input.source,host,{timeout:1000});
const hook=hooks.get('shared-terminate'),self=[new P('0xffffffffffffffff'),new P('7')],
 other=[new P('0'),new P('9')];
hook.onEnter.call({context:{}},other);
hook.onEnter.call({context:{}},self);
process.stdout.write(JSON.stringify({messages,sleeps,args:[self.map(p=>p.v),other.map(p=>p.v)]}));
'''
        result=subprocess.run([node,'-e',harness],input=json.dumps(dict(config=config,source=source)),
                              text=True,capture_output=True,check=True,timeout=5)
        value=json.loads(result.stdout);rows=value['messages']
        self.assertFalse(any(r['kind']=='decode-error' for r in rows))
        terminal=[r['data'] for r in rows if r['kind']=='process-exit-entry']
        foreign=[r['data'] for r in rows if r['kind']=='termination-request']
        self.assertEqual(len(terminal),1);self.assertEqual(len(foreign),1)
        self.assertEqual(terminal[0]['exitStatus'],7)
        self.assertEqual(terminal[0]['boundaryApi'],'kernelbase.dll:TerminateProcess')
        self.assertTrue(terminal[0]['currentProcessPseudoHandle'])
        self.assertEqual(terminal[0]['counts']['kernelbase.dll:TerminateProcess'],2)
        self.assertEqual(terminal[0]['errors'],[])
        self.assertFalse(foreign[0]['currentProcessPseudoHandle'])
        self.assertEqual(foreign[0]['exitStatus'],9)
        self.assertEqual(value['sleeps'],[0.2])
        self.assertEqual(value['args'],[['0xffffffffffffffff','7'],['0','9']])
        proof=validate(terminal[0],expected_status=7)
        self.assertEqual(proof['exit_status'],7)
        for key,bad in [('exitStatus',0),('exitStatus',True),('currentProcessPseudoHandle',False),
                        ('transportHoldMs',0),('boundaryApi','ntdll.dll:RtlExitUserProcess'),
                        ('counts',{}),('errors',['injected']),('frames',[]),('overflow',True),
                        ('unknownRelativeRoots',False)]:
            value=deepcopy(terminal[0]);value[key]=bad
            with self.subTest(key=key,bad=bad),self.assertRaises(ValueError):validate(value,expected_status=7)
        with self.assertRaises(ValueError):validate(terminal[0],expected_status=7,expected_caller=dict(module='unityplayer.dll',rva='0x80547e'))
        for alias in (False,'kernel32.dll:TerminateProcess','kernelbase.dll:CreateProcessW','missing:TerminateProcess'):
            value=deepcopy(terminal[0]);value['installed'][-1]['aliasOf']=alias
            with self.subTest(alias=alias),self.assertRaises(ValueError):validate(value,expected_status=7)

    def test_sdk_snapshot_rejects_booleans_as_integer_counters(self):
        value=dict(installed=True,calls=4,gcHandles=4,counts=dict.fromkeys(OBSERVED,0))
        self.assertEqual(validate_cache(value),value)
        for name in OBSERVED:
            bad=deepcopy(value);bad['counts'][name]=False
            with self.subTest(name=name),self.assertRaises(ValueError):validate_cache(bad)
        for name,bad_value in [('installed',1),('calls',True),('gcHandles',True),('gcHandles',5)]:
            bad=deepcopy(value);bad[name]=bad_value
            with self.subTest(name=name),self.assertRaises(ValueError):validate_cache(bad)
