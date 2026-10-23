import copy,json,shutil,subprocess,unittest
from tools.frida_webview_child import PROBE,build_source

class ChildObserverTests(unittest.TestCase):
    def execute(self,mode):
        descriptor=[dict(module=r'E:\owned\VuplexWebViewChromium\Vuplex WebView.vuplex',entries=[dict(name='execute',rva=10,sha256='0'*64,returnKind='int32',exportName=None),dict(name='initialize',rva=30,sha256='0'*64,returnKind='bool-al',exportName=None)])]
        harness=r'''
const vm=require('vm'),fs=require('fs'),v=JSON.parse(fs.readFileSync(0,'utf8')),events=[],hooks=new Map(),timers=[];let handler;
class P{constructor(v){this.v=v;}add(n){return new P(this.v+n);}sub(n){return new P(this.v-n.v);}toString(){return '0x'+this.v.toString(16);}readByteArray(){return new ArrayBuffer(16);}toInt32(){return this.v|0;}toUInt32(){return this.v>>>0;}isNull(){return this.v===0;}}
const module={path:v.descriptors[0].module,name:'Vuplex WebView.vuplex',base:new P(100)};
const host={Process:{findModuleByAddress:()=>module,setExceptionHandler:f=>handler=f,attachModuleObserver:o=>o.onAdded(module)},Checksum:{compute:()=>((v.mode==='bad'?'1':'0').repeat(64))},Interceptor:{attach:(p,c)=>hooks.set(p.v,c)},emit:(kind,data)=>events.push(JSON.parse(JSON.stringify({kind,data}))),frames:()=>[{module:'owned',rva:'0x10'}],setInterval:f=>timers.push(f)};
vm.runInNewContext(v.source,host,{timeout:1000});
if(v.mode!=='bad')for(const [at,hook]of hooks){const receiver={context:{}};hook.onEnter.call(receiver);hook.onLeave.call(receiver,new P(at===110?-1:0x100));}
const handled=handler({type:'access-violation',address:new P(120),memory:{operation:'read'},context:{}});timers[0]();
process.stdout.write(JSON.stringify({events,handled,hooks:hooks.size}));
'''
        result=subprocess.run([shutil.which('node'),'-e',harness],input=json.dumps(dict(mode=mode,descriptors=descriptor,source=PROBE.replace('__PROBE__',json.dumps(descriptor)))),text=True,capture_output=True,check=True,timeout=5)
        return json.loads(result.stdout)
    def test_wrapper_return_types_and_exception_forwarding(self):
        r=self.execute('good');self.assertEqual(r['hooks'],2);self.assertFalse(r['handled'])
        returns=[e['data']['result'] for e in r['events'] if e['kind']=='child-startup-return'];self.assertEqual(returns,[-1,False])
        exception=next(e['data'] for e in r['events'] if e['kind']=='child-native-exception')
        self.assertEqual(exception['pc']['rva'],'0x14');self.assertFalse(exception['handled'])
        self.assertEqual(r['events'][-1]['data']['exceptions'],1)
    def test_hash_failure_installs_no_entry_hooks_and_is_reported(self):
        r=self.execute('bad');self.assertEqual(r['hooks'],0);self.assertTrue(r['events'][-1]['data']['errors'])
    def test_foreign_image_partial_descriptor_and_bool_rva_rejected(self):
        config=dict(image=r'E:\owned\VuplexWebViewChromium\Vuplex WebView.vuplex',runId='1'*32,eventLimit=100,fileRoots=[r'E:\owned'])
        valid=dict(module=config['image'],entries=[dict(name='execute',rva=10,sha256='0'*64,returnKind='int32',exportName=None)])
        for d in ([],[dict(valid,module=r'C:\foreign.dll')],[dict(valid,entries=[dict(valid['entries'][0],rva=True)])]):
            with self.assertRaises(ValueError):build_source(config,dict(pid=17,pebAddress='0x1000'),d)

if __name__=='__main__':unittest.main()
