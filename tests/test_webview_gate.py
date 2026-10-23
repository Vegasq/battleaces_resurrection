import copy,json,shutil,subprocess,unittest
from tools.frida_webview_gate import GATE,build_source

class GateTests(unittest.TestCase):
    def execute(self,mode):
        gate=dict(module=r'E:\owned\VuplexWebViewWindows.dll',childImage='unused',entryRva=0x1bbd0,returnRva=0x1c1d4,sha256='0'*64)
        harness=r'''
const vm=require('vm'),fs=require('fs'),v=JSON.parse(fs.readFileSync(0,'utf8'));
class P{constructor(v){this.v=v;}toUInt32(){return this.v;}add(){return this;}readByteArray(){return new ArrayBuffer(16);}}
const ctx=vm.createContext({Process:{id:17,findModuleByName:()=>({path:v.gate.module,base:new P(0)})},Checksum:{compute:()=>((v.mode==='hash'?'1':'0').repeat(64))},ptr:n=>new P(n)});
vm.runInContext(v.source,ctx);let args=Array.from({length:10},()=>new P(0));if(v.mode==='flags')args[5]=new P(8);
const rec={processMetadata:{expectedChildImageMatches:v.mode!=='image',ownedCacheMatches:v.mode!=='cache',processType:v.mode==='type'?'renderer':null},frames:[{module:'vuplexwebviewwindows.dll',rva:v.mode==='caller'?'0x123':'0x1c1d4'}]};
ctx.args=args;ctx.rec=rec;let error=null;try{vm.runInContext('webviewHoldBrowser(args,rec)',ctx);if(v.mode==='twice')vm.runInContext('webviewHoldBrowser(args,rec)',ctx);}catch(e){error=String(e);}
process.stdout.write(JSON.stringify({flags:args[5].v,rec,error}));
'''
        result=subprocess.run([shutil.which('node'),'-e',harness],input=json.dumps(dict(mode=mode,gate=gate,source=GATE.replace('__GATE__',json.dumps(gate)))),text=True,capture_output=True,check=True,timeout=5)
        return json.loads(result.stdout)
    def test_exact_owned_call_adds_one_explicit_suspension(self):
        r=self.execute('positive');self.assertEqual(r['flags'],4);self.assertIsNone(r['error']);self.assertTrue(r['rec']['ownedChildGate']['externalResumeRequired'])
        self.assertEqual(r['rec']['ownedChildGate']['originalCreationFlags'],0)
    def test_foreign_image_cache_type_and_caller_are_unchanged(self):
        for mode in ('image','cache','type','caller'):
            r=self.execute(mode);self.assertEqual(r['flags'],0);self.assertNotIn('ownedChildGate',r['rec'])
    def test_bad_prefix_flags_and_second_gate_refused(self):
        for mode,flags in (('hash',0),('flags',8),('twice',4)):
            r=self.execute(mode);self.assertIsNotNone(r['error']);self.assertEqual(r['flags'],flags)
    def test_builder_rejects_foreign_or_partial_callsite_before_sdk(self):
        config=dict(image=r'E:\owned\Battle Aces.exe');gate=dict(module='foreign',childImage='foreign',entryRva=0x1bbd0,returnRva=0x1c1d4,sha256='0'*64)
        for g in ({},gate,dict(gate,entryRva=True)):
            with self.assertRaises(ValueError):build_source(config,{},None,cache_path='unused',gate=g)

if __name__=='__main__':unittest.main()
