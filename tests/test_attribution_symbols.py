import copy
import json
import shutil
import subprocess
import unittest
from unittest.mock import patch
from tools.frida_attribution_symbols import build_source
from tools.attribution_symbol_metadata import validate
from tools.attribution_unwind_metadata import validate as unwind_validate


class SymbolTests(unittest.TestCase):
    config=dict(image=r'E:\owned\local\python.exe',runId='1'*32,eventLimit=512,fileRoots=[r'E:\owned\local\queue'])
    cwd=dict(pid=17,pebAddress='0x1000')

    def execute(self, mode):
        harness=r'''
const fs=require('fs'),vm=require('vm'),input=JSON.parse(fs.readFileSync(0,'utf8'));
const rows=[],hooks=new Map(),names=['SymInitialize','SymCleanup','SymFromAddr','StackWalk64'];
class P{constructor(v){this.v=Number(v);}add(v){return new P(this.v+v);}sub(p){return new P(this.v-p.v);}equals(p){return this.v===p.v;}toString(){return '0x'+this.v.toString(16);}toUInt32(){return this.v;}readByteArray(n){return new ArrayBuffer(n);}}
const module={name:'dbghelp.dll',path:'C:\\Windows\\System32\\dbghelp.dll',base:new P(4096),size:4096,
 findExportByName:n=>new P(4096+32+32*names.indexOf(n))};
const host={Process:{arch:'x64',pointerSize:8,id:17,mainModule:{path:input.image},getCurrentThreadId:()=>18,
 attachModuleObserver:o=>o.onAdded(module),findModuleByAddress:()=>({name:'caller.dll',base:new P(8192)})},
 Thread:{backtrace:()=>[]},Backtracer:{ACCURATE:1},Checksum:{compute:()=>('a'.repeat(64))},setInterval:()=>0,
 Interceptor:{attach:(a,h)=>hooks.set(a.v,h)},send:r=>rows.push(JSON.parse(JSON.stringify(r)))};
const c=vm.createContext(host);vm.runInContext(input.source,c,{timeout:1000});
const enter=n=>{const state={returnAddress:new P(8208)};hooks.get(module.findExportByName(n).v).onEnter.call(state);return state;};
const leave=(n,s)=>hooks.get(module.findExportByName(n).v).onLeave.call(s);
if(input.mode==='nested'){
 const first=enter('SymInitialize');const second=enter('StackWalk64');
 vm.runInContext("emit('file-operation',{api:'authored',path:'local-symbol.pdb'})",c);
 leave('StackWalk64',second);leave('SymInitialize',first);
} else if(input.mode==='calls')for(let i=0;i<10;i++){const s=enter('SymInitialize');leave('SymInitialize',s);}
else if(input.mode==='bad-return'){const s=enter('SymInitialize');const t=enter('StackWalk64');leave('SymInitialize',s);}
vm.runInContext("emit('heartbeat',{counts:{}})",c);process.stdout.write(JSON.stringify(rows));
'''
        r=subprocess.run([shutil.which('node'),'-e',harness],input=json.dumps(dict(source=build_source(self.config,self.cwd),image=self.config['image'],mode=mode)),
                         text=True,capture_output=True,check=True,timeout=5)
        return json.loads(r.stdout)

    def proof(self,rows):return validate(rows,pid=17,run_id=self.config['runId'])

    def test_nested_native_extents_bind_direct_callers_and_preserve_rows(self):
        rows=self.execute('nested');before=copy.deepcopy(rows);proof,projected=self.proof(rows)
        self.assertEqual((proof['entries'],proof['returns']),(2,2))
        scoped=proof['rows_emitted_in_native_symbol_scope'];self.assertEqual(len(scoped),1)
        self.assertEqual([x['api'] for x in scoped[0]['active']],['SymInitialize','StackWalk64'])
        self.assertEqual(scoped[0]['active'][0]['caller'],dict(module='caller.dll',rva='0x10'))
        self.assertEqual(rows,before)
        self.assertEqual([r['data'] for r in rows],[r['data'] for r in projected])
        unwind_validate(projected,pid=17,run_id=self.config['runId'])

    def test_bounded_history_does_not_stop_counts(self):
        proof,_=self.proof(self.execute('calls'));m=proof['modules'][0]
        self.assertEqual(proof['entries'],10);self.assertEqual(m['counts']['SymInitialize'],10)
        self.assertEqual(len(m['history']),8)

    def test_mismatched_native_returns_fail(self):
        with self.assertRaises(AssertionError):self.proof(self.execute('bad-return'))

    def test_corrupt_module_scope_and_counts_reject(self):
        original=self.execute('nested');cases=[]
        for key,value in [('schema',True),('entered',False),('returned',999),('errors',['authored error'])]:
            bad=copy.deepcopy(original);bad[-1]['nativeSymbols'][key]=value;cases.append(bad)
        bad=copy.deepcopy(original);bad[-1]['nativeSymbols']['modules'][0]['counts']['SymInitialize']=0;cases.append(bad)
        bad=copy.deepcopy(original);bad[-1]['nativeSymbols']['modules'][0]['exports'][0]['sha256']='bad';cases.append(bad)
        bad=copy.deepcopy(original);bad[-1]['nativeSymbols']['modules'][0]['path']='changed';cases.append(bad)
        bad=copy.deepcopy(original);next(r for r in bad if r['kind']=='file-operation')['nativeSymbols']['active'][0]['moduleId']=99;cases.append(bad)
        for bad in cases:
            with self.assertRaises(AssertionError):self.proof(bad)

    def test_sdk_counts_survive_both_annotation_projections(self):
        from tests.test_sdk_startup_observer import SDKStartupObserverTests
        driver=SDKStartupObserverTests();driver.setUp()
        with patch('tests.test_sdk_startup_observer.build_source',build_source):result=driver.execute('calls')
        symbol,rows=validate(result['rows'],pid=17,run_id=driver.config['runId'])
        _,rows=unwind_validate(rows,pid=17,run_id=driver.config['runId'])
        self.assertEqual(symbol['entries'],0)
        self.assertEqual(rows[-1]['data']['sdk']['counts']['Client.ctor'],10)
        self.assertEqual(sum(r['kind']=='sdk-entry' for r in rows),8)


if __name__=='__main__':unittest.main()
