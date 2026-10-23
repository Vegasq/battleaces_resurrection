import copy
import hashlib
import json
import shutil
import subprocess
import unittest
from tools.frida_webview_pipe import PIPE, descriptor
from tools.frida_webview_pipe_security import NEW, OLD, READY, select_handle
from tools.frida_attribution_clock import replace_once


class HandleWitnessTests(unittest.TestCase):
    def capture(self, result='0x444', caller='0x1b6af'):
        witness = descriptor('parent', r'E:\owned\Battle Aces.exe', '2'*32)
        harness = r'''
const vm=require('vm'),fs=require('fs'),crypto=require('crypto'),v=JSON.parse(fs.readFileSync(0,'utf8')),rows=[],hooks=new Map();
class P{constructor(n,text=null,off=0){this.n=BigInt(n);this.text=text;this.off=off;}add(n){return new P(this.n+BigInt(n),this.text,this.off+n);}readU8(){return this.text?.charCodeAt(this.off)||0;}isNull(){return this.n===0n;}equals(p){return this.n===p.n;}toString(){return '0x'+this.n.toString(16);}toUInt32(){return Number(BigInt.asUintN(32,this.n));}readByteArray(){return {};}}
const ctx={Process:{findModuleByName:()=>({path:v.witness.module,base:new P(100)}),attachModuleObserver:o=>o.onAdded({name:'KERNELBASE.dll',findExportByName:n=>new P({CreateNamedPipeA:1,ConnectNamedPipe:2,WaitForSingleObject:3}[n])})},Checksum:{compute:(k,s)=>typeof s==='string'?crypto.createHash('sha256').update(s).digest('hex'):v.witness.sha256},Interceptor:{attach:(p,h)=>hooks.set(Number(p.n),h)},ptr:n=>new P(n),frames:c=>c.frames,emit:(kind,data)=>rows.push(JSON.parse(JSON.stringify({kind,data}))),setInterval:()=>{}};
vm.runInNewContext(v.source,ctx,{timeout:1000});
const h=hooks.get(1),self={context:{frames:[{module:'vuplexwebviewwindows.dll',rva:v.caller}]},lastError:5},z=new P(0);
h.onEnter.call(self,[new P(1000,v.name),new P(0x40000003),new P(6),new P(255),new P(1048576),new P(1048576),z,z]);h.onLeave.call(self,new P(v.result));
process.stdout.write(JSON.stringify(rows));
'''
        name = r'\\.\pipe\com.vuplex.webview.01234567-89ab-cdef-0123-456789abcdef'
        source = replace_once(PIPE, OLD, NEW).replace('__PIPE__', json.dumps(witness)) + READY
        completed = subprocess.run([shutil.which('node'), '-e', harness], input=json.dumps(
            dict(source=source, witness=witness, name=name, result=result, caller=caller)),
            text=True, capture_output=True, check=True, timeout=5)
        rows = [dict(schema=1, seq=i, runId='3'*32, pid=100, tid=200,
                     elapsedMs=i, **row) for i, row in enumerate(json.loads(completed.stdout), 1)]
        return rows, witness, name

    def validate(self, rows, witness):
        return select_handle(rows, pid=100, run_id='3'*32, witness=witness)

    def test_actual_composed_js_emits_correlated_success_without_name(self):
        rows, witness, name = self.capture()
        before = copy.deepcopy(rows)
        result = self.validate(rows, witness)
        self.assertEqual(result['observation']['handle'], '0x444')
        self.assertEqual(result['observation']['name_sha256'], hashlib.sha256(
            json.dumps(['2'*32, name], separators=(',', ':')).encode()).hexdigest())
        self.assertNotIn(name, json.dumps(rows))
        self.assertEqual(rows, before)
        self.assertFalse(result['live_object_identity_qualified'])

    def test_failed_api_and_foreign_caller_do_not_emit_handle(self):
        for kwargs in (dict(result='0xffffffffffffffff'), dict(caller='0x1')):
            rows, witness, _ = self.capture(**kwargs)
            self.assertFalse(any(r['kind'] == 'owned-pipe-handle' for r in rows))
            with self.assertRaises(AssertionError):
                self.validate(rows, witness)

    def test_correlation_types_handles_and_envelope_corruptions_rejected(self):
        original, witness, _ = self.capture()
        ix = next(i for i, r in enumerate(original) if r['kind'] == 'owned-pipe-handle')
        mutations = [('handle', '0x0'), ('handle', '0xffffffffffffffff'),
                     ('handle', '0x0444'), ('handle', '0x10000000000000000'),
                     ('call', True), ('call', 2), ('api', 'kernel32.dll:CreateNamedPipeA'),
                     ('schema', True), ('role', 'child'), ('nameSha256', '0'*64),
                     ('frames', []), ('unexpected', 'secret')]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                rows = copy.deepcopy(original)
                rows[ix]['data'][key] = value
                with self.assertRaises(AssertionError):
                    self.validate(rows, witness)
        for key, value in [('tid', 201), ('pid', 101), ('seq', 100)]:
            rows = copy.deepcopy(original)
            rows[ix][key] = value
            with self.assertRaises(AssertionError):
                self.validate(rows, witness)

    def test_duplicate_and_unknown_extension_refused(self):
        rows, witness, _ = self.capture()
        duplicate = copy.deepcopy(next(r for r in rows if r['kind'] == 'owned-pipe-handle'))
        rows.append(dict(duplicate, seq=len(rows)+1, elapsedMs=len(rows)+1))
        with self.assertRaises(AssertionError):
            self.validate(rows, witness)
        rows, witness, _ = self.capture()
        next(r for r in rows if r['kind'] == 'owned-pipe-handle')['kind'] = 'owned-pipe-unknown'
        with self.assertRaises(AssertionError):
            self.validate(rows, witness)


if __name__ == '__main__':
    unittest.main()
