import hashlib,json,shutil,subprocess,unittest
from tools.frida_webview_pipe import PIPE,descriptor

class PipeTests(unittest.TestCase):
    name=r'\\.\pipe\com.vuplex.webview.01234567-89ab-cdef-0123-456789abcdef'
    def execute(self,role,mode='good'):
        image=r'E:\owned\Battle Aces.exe' if role=='parent' else r'E:\owned\VuplexWebViewChromium\Vuplex WebView.vuplex'
        d=descriptor(role,image,'1'*32)
        harness=r'''
const vm=require('vm'),fs=require('fs'),crypto=require('crypto'),v=JSON.parse(fs.readFileSync(0,'utf8')),rows=[],hooks=new Map(),timers=[];
class P{constructor(n,text=null,off=0,event=null){this.n=BigInt(n);this.text=text;this.off=off;this.event=event;}add(n){return new P(this.n+BigInt(n),this.text,this.off+n,this.event);}readU8(){return this.text?.charCodeAt(this.off)||0;}readPointer(){return this.event;}isNull(){return this.n===0n;}equals(p){return this.n===p.n;}toString(){return '0x'+this.n.toString(16);}toUInt32(){return Number(BigInt.asUintN(32,this.n));}readByteArray(){return {rva:Number(this.n-100n)};}}
const api={CreateNamedPipeA:1,ConnectNamedPipe:2,WaitForSingleObject:3,CreateFileA:4};
const ctx={Process:{findModuleByName:()=>({path:v.d.module,base:new P(100)}),attachModuleObserver:o=>o.onAdded({name:'KERNELBASE.dll',findExportByName:n=>new P(api[n])})},Checksum:{compute:(kind,input)=>typeof input==='string'?crypto.createHash('sha256').update(input).digest('hex'):((v.mode==='hash'||input.rva===0x84050)?'0'.repeat(64):v.d.sha256)},Interceptor:{attach:(p,h)=>hooks.set(Number(p.n),h)},ptr:n=>new P(n),frames:c=>c.frames,emit:(kind,data)=>rows.push(JSON.parse(JSON.stringify({kind,data}))),setInterval:f=>timers.push(f)};
vm.runInNewContext(v.source,ctx,{timeout:1000});const nativeName=v.mode==='invalid-name'?'PRIVATE_BAD_PIPE':v.name;
function invoke(apiName,pc,args,value,error){const h=hooks.get(api[apiName]),self={context:{frames:[{module:v.d.role==='parent'?'vuplexwebviewwindows.dll':'vuplex webview.vuplex',rva:v.mode==='foreign'?'0x1':pc}]},lastError:error};h.onEnter.call(self,args);h.onLeave.call(self,value);}
const name=new P(1000,nativeName),zero=new P(0);
if(v.d.role==='parent'){
 invoke('CreateNamedPipeA','0x1b6af',[name,new P(0x40000003),new P(6),new P(255),new P(1048576),new P(1048576),zero,zero],new P(0x444),123);
 if(v.mode==='good'){
  invoke('ConnectNamedPipe','0x1b73f',[new P(0x444),new P(0x777,null,0,new P(0x888))],zero,997);
  invoke('WaitForSingleObject','0x1b772',[new P(0x888),new P(0xffffffff)],zero,123);
 }
}else invoke('CreateFileA','0x840e8',[name,new P(0xc0000000),zero,zero,new P(3),new P(0x40000000),zero],new P(v.mode==='success'?0x555:'0xffffffffffffffff'),v.mode==='bad-error'?undefined:5);
timers[0]();process.stdout.write(JSON.stringify(rows));
'''
        r=subprocess.run([shutil.which('node'),'-e',harness],input=json.dumps(dict(d=d,name=self.name,mode=mode,source=PIPE.replace('__PIPE__',json.dumps(d)))),text=True,capture_output=True,check=True,timeout=5)
        return json.loads(r.stdout)
    def test_cross_process_name_equality_and_original_access_results(self):
        parent=self.execute('parent');child=self.execute('child')
        p=[r['data'] for r in parent if r['kind']=='pipe-operation'];c=[r['data'] for r in child if r['kind']=='pipe-operation']
        self.assertEqual(len(p),3);self.assertEqual(len(c),1)
        expected=hashlib.sha256(json.dumps(['1'*32,self.name],separators=(',',':')).encode()).hexdigest()
        self.assertTrue(all(r['nameSha256']==expected and r['nameLength']==64 for r in p+c))
        self.assertTrue(p[0]['handleValid']);self.assertIsNone(p[0]['lastError']);self.assertEqual(p[0]['openMode'],0x40000003)
        self.assertFalse(p[1]['returned']);self.assertEqual(p[1]['lastError'],997);self.assertEqual(p[2]['waitResult'],0)
        self.assertFalse(c[0]['handleValid']);self.assertEqual(c[0]['lastError'],5);self.assertEqual(c[0]['desiredAccess'],0xc0000000)
        self.assertNotIn(self.name,json.dumps(parent+child));self.assertNotIn('01234567-89ab-cdef',json.dumps(parent+child))
    def test_wrong_caller_does_not_read_or_record_foreign_name(self):
        for role in ('parent','child'):
            rows=self.execute(role,'foreign');self.assertFalse(any(r['kind'] in ('pipe-operation','pipe-probe-error') for r in rows))
            self.assertTrue(all(v==0 for v in rows[-1]['data']['counts'].values()))
    def test_bad_prefix_name_and_missing_error_are_not_qualified(self):
        for mode in ('hash','invalid-name','bad-error'):
            rows=self.execute('child',mode);self.assertFalse(any(r['kind']=='pipe-operation' for r in rows));self.assertTrue(rows[-1]['data']['errors'])
            self.assertNotIn('PRIVATE_BAD_PIPE',json.dumps(rows))
    def test_success_does_not_misreport_stale_last_error(self):
        value=next(r['data'] for r in self.execute('child','success') if r['kind']=='pipe-operation');self.assertTrue(value['handleValid']);self.assertIsNone(value['lastError'])
    def test_invalid_descriptor_role_path_nonce_rejected(self):
        for args in (('unknown',r'E:\owned\Battle Aces.exe','1'*32),('parent','Battle Aces.exe','1'*32),('parent',r'E:\owned\Battle Aces.exe','bad')):
            with self.assertRaises(ValueError):descriptor(*args)

if __name__=='__main__':unittest.main()
