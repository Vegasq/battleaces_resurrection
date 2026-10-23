import copy,json,shutil,subprocess,unittest
from tools.frida_unity_log_scope import build_source
from tools.unity_log_scope_metadata import validate
from tools.attribution_symbol_metadata import validate as symbol_validate
from tools.attribution_unwind_metadata import validate as unwind_validate


class LogScopeTests(unittest.TestCase):
    config=dict(image=r'E:\owned\local\python.exe',runId='1'*32,eventLimit=512,fileRoots=[r'E:\owned\local\queue'])
    cwd=dict(pid=17,pebAddress='0x1000')
    entry=dict(module=r'E:\owned\local\UnityPlayer.dll',rva=16,sha256='a'*64)
    def execute(self,mode='calls',bad_hash=False):
        harness=r'''
const fs=require('fs'),vm=require('vm'),input=JSON.parse(fs.readFileSync(0,'utf8')),rows=[],hooks=new Map();
class P{constructor(v){this.v=Number(v);}add(v){return new P(this.v+v);}sub(p){return new P(this.v-p.v);}equals(p){return this.v===p.v;}toString(){return '0x'+this.v.toString(16);}toUInt32(){return this.v;}readByteArray(n){return new ArrayBuffer(n);}}
const names=['SymInitialize','SymCleanup','SymFromAddr','StackWalk64','SymLoadModule64'];
const dbg={name:'dbghelp.dll',path:'C:\\Windows\\System32\\dbghelp.dll',base:new P(4096),size:4096,findExportByName:n=>new P(4096+32+32*names.indexOf(n))};
const unity={name:'UnityPlayer.dll',path:input.entry.module,base:new P(16384),size:4096};
const host={Process:{arch:'x64',pointerSize:8,id:17,mainModule:{path:input.image},getCurrentThreadId:()=>18,
 attachModuleObserver:o=>{o.onAdded(dbg);o.onAdded(unity);},findModuleByAddress:()=>({name:'caller.dll',base:new P(8192)})},
 Thread:{backtrace:()=>[]},Backtracer:{ACCURATE:1},Checksum:{compute:()=>((input.badHash?'b':'a').repeat(64))},setInterval:()=>0,
 Interceptor:{attach:(a,h)=>hooks.set(a.v,h)},send:r=>rows.push(JSON.parse(JSON.stringify(r)))};
const c=vm.createContext(host);vm.runInContext(input.source,c,{timeout:1000});
const enter=a=>{const s={returnAddress:new P(8208)};hooks.get(a).onEnter.call(s);return s;};
const leave=(a,s)=>hooks.get(a).onLeave.call(s),log=16400,load=dbg.findExportByName('SymLoadModule64').v;
if(!input.badHash){
 if(input.mode==='bad-return'){const a=enter(log),b=enter(log);leave(log,a);}
 else for(let i=0;i<10;i++){const a=enter(log),b=enter(load);vm.runInContext("emit('file-operation',{api:'authored',path:'module.pdb'})",c);leave(load,b);leave(log,a);}
}
vm.runInContext("emit('heartbeat',{counts:{}})",c);process.stdout.write(JSON.stringify(rows));
'''
        r=subprocess.run([shutil.which('node'),'-e',harness],input=json.dumps(dict(source=build_source(self.config,self.cwd,entry=self.entry),entry=self.entry,image=self.config['image'],mode=mode,badHash=bad_hash)),text=True,capture_output=True,check=True,timeout=5)
        return json.loads(r.stdout)
    def proof(self,rows):return validate(rows,pid=17,run_id=self.config['runId'],entry=self.entry)
    def test_native_scope_metadata_and_all_projections_preserve_operations(self):
        rows=self.execute();before=copy.deepcopy(rows);p,view=self.proof(rows)
        self.assertEqual((p['entries'],p['returns']),(10,10));self.assertEqual(len(p['history']),8)
        self.assertEqual(len(p['rows_emitted_in_log_scope']),10)
        self.assertTrue(all(r['active'][0]['caller']==dict(module='caller.dll',rva='0x10') for r in p['rows_emitted_in_log_scope']))
        self.assertEqual(rows,before)
        self.assertEqual([{k:v for k,v in r.items() if k!='unityLogScope'} for r in rows],view)
        s,view=symbol_validate(view,pid=17,run_id=self.config['runId'],include_module_load=True)
        self.assertEqual(s['entries'],10);unwind_validate(view,pid=17,run_id=self.config['runId'])
    def test_bad_prefix_and_out_of_order_returns_reject(self):
        for rows in (self.execute(bad_hash=True),self.execute('bad-return')):
            with self.assertRaises(AssertionError):self.proof(rows)
    def test_corrupt_code_scope_counters_and_histories_reject(self):
        good=self.execute();cases=[]
        for key,value in [('entered',True),('returned',999),('errors',['bad']),('module',None),('history',[])]:
            bad=copy.deepcopy(good);bad[-1]['unityLogScope'][key]=value;cases.append(bad)
        for field,value in [('rva',True),('sha256','b'*64),('path',r'E:\foreign\UnityPlayer.dll')]:
            bad=copy.deepcopy(good);bad[-1]['unityLogScope']['module'][field]=value;cases.append(bad)
        for bad in cases:
            with self.assertRaises(AssertionError):self.proof(bad)
    def test_entry_requires_exact_code_identity(self):
        for entry in ({},dict(self.entry,rva=True),dict(self.entry,sha256='bad'),dict(self.entry,module='UnityPlayer.dll')):
            with self.assertRaises(ValueError):build_source(self.config,self.cwd,entry=entry)


if __name__=='__main__':unittest.main()
