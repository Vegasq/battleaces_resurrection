"""Directory-metadata/schema guard behavior;actual owned control is separate."""
from copy import deepcopy
import ctypes
import json
import shutil
import subprocess
import struct
import unittest
from unittest.mock import Mock,patch
from tools.frida_attribution_cwd import CWD_READER,build_source,control_request
from tools.attribution_cwd_metadata import resolved
from tests.test_attribution_control import IMAGE,FOLDER,RUN
from tools.owned_suspended_launch import SuspendedChild
from tools.owned_process_directory import snapshot


class CwdAttribution(unittest.TestCase):
    def test_descriptor_and_entry_schema_reject_false_provenance(self):
        config,request=control_request(IMAGE,FOLDER,RUN)
        source=build_source(config,dict(pid=100,pebAddress='0x1000'))
        self.assertIn('Process.id!==cwdProbe.pid',source)
        for forbidden in ('new NativeFunction','Interceptor.replace','NtQueryObject','rpc.exports'):
            self.assertNotIn(forbidden,source)
        compile(request['argv'][3],'<authored cwd control>','exec')
        for descriptor in ({'pid':True,'pebAddress':'0x1000'},{'pid':100,'pebAddress':'0x0'},
                {'pid':100,'pebAddress':'0x1000','root':'guessed'}):
            with self.assertRaises(ValueError):build_source(config,descriptor)
        value=dict(api='ntdll.dll:NtCreateFile',operation='NtCreateFile',phase='entry',rootHandle='0x40',
            relativePath='sim.log',frames=[dict(module='simulation.dll',rva='0x35acdc')],
            rootPath='E:\\owned\\game\\',pebAddress='0x1000',parametersAddress='0x2000',resolution='process-current-directory')
        self.assertEqual(resolved(value,peb_address='0x1000'),value)
        for key,bad in (('rootPath','relative'),('rootPath','E:\\bad\0path'),('parametersAddress','0x0'),
                ('pebAddress','0x1111'),('resolution','launch-cwd'),('phase','return'),('relativePath','..\\private')):
            with self.subTest(key=key):
                broken=deepcopy(value);broken[key]=bad
                with self.assertRaises(ValueError):resolved(broken,peb_address='0x1000')

    @unittest.skipUnless(shutil.which('node'),'Node needed for isolated authored JS behavior')
    def test_reader_matches_live_handle_and_rejects_changes(self):
        harness=r'''
const assert=require('node:assert/strict');
let rootPath='E:\\owned\\game\\',change=false,reads=0,events=[],resolvedCwdRoots=0;
const cwdProbe={pid:100,pebAddress:'0x1000'};
class P {
 constructor(value){this.value=Number(value);}
 add(value){return new P(this.value+value);}
 equals(other){return this.value===other.value;}
 isNull(){return !this.value;}
 toString(){return '0x'+this.value.toString(16);}
 readPointer(){return new P(({0x1020:0x2000,0x2048:0x40,0x2040:0x3000})[this.value]||0);}
 readU16(){return this.value===0x2038?rootPath.length*2:rootPath.length*2+2;}
 readUtf16String(){return change && ++reads===2?'F:\\changed\\':rootPath;}
}
const ptr=value=>new P(value),relevant=value=>true,frames=value=>[{module:'authored.dll',rva:'0x1'}];
function emit(kind,data){events.push({kind,data});}
__READER__
const first=cwdRoot(new P(0x40),{},'ntdll.dll:NtCreateFile','NtCreateFile','sim.log');
assert.equal(first.path,'E:\\owned\\game');assert.equal(events.length,1);
assert.equal(events[0].data.rootPath,rootPath);
assert.equal(cwdRoot(new P(0x50),{},'ntdll.dll:NtCreateFile','NtCreateFile','sim.log'),null);
assert.equal(events.length,1);assert.equal(resolvedCwdRoots,1);
rootPath='F:\\new\\';
assert.equal(cwdRoot(new P(0x40),{},'ntdll.dll:NtCreateFile','NtCreateFile','sim.log').path,'F:\\new');
change=true;reads=0;
assert.throws(()=>cwdRoot(new P(0x40),{},'ntdll.dll:NtCreateFile','NtCreateFile','sim.log'),/changed/);
rootPath='relative';change=false;
assert.throws(()=>cwdRoot(new P(0x40),{},'ntdll.dll:NtCreateFile','NtCreateFile','sim.log'),/absolute/);
console.log(JSON.stringify({passed:true,events:events.length}));
'''.replace('__READER__',CWD_READER)
        result=subprocess.run([shutil.which('node'),'-e',harness],check=True,capture_output=True,text=True)
        self.assertEqual(json.loads(result.stdout),dict(passed=True,events=2))


class OwnedDirectoryChecks(unittest.TestCase):
    def fixture(self,handle=0x40):
        path='E:\\owned\\game\\';encoded=path.encode('utf-16-le')
        child=SuspendedChild();child.handle=11;child.job=Mock();child.pid=21;child.poll=Mock(return_value=None)
        kernel=Mock();native=Mock();kernel.GetProcessId.return_value=21
        basic=bytearray(48);struct.pack_into('<Q',basic,8,0x1000);struct.pack_into('<Q',basic,32,21)
        def query(process,kind,buffer,length,returned):
            ctypes.memmove(buffer,bytes(basic),48);returned._obj.value=48;return 0
        native.NtQueryInformationProcess.side_effect=query
        metadata={0x1020:struct.pack('<Q',0x2000),0x2038:struct.pack('<HH4xQQ',len(encoded),len(encoded)+2,0x3000,handle),0x3000:encoded}
        def read(process,address,buffer,length,returned):
            data=metadata[address];ctypes.memmove(buffer,data,length);returned._obj.value=length;return True
        kernel.ReadProcessMemory.side_effect=read
        def duplicate(source,handle,target,output,*unused):output._obj.value=41;return True
        kernel.DuplicateHandle.side_effect=duplicate
        def final(handle,buffer,length,flags):buffer.value='\\\\?\\E:\\owned\\game';return len(buffer.value)
        kernel.GetFinalPathNameByHandleW.side_effect=final
        return child,kernel,native,metadata

    @unittest.skipUnless(hasattr(ctypes,'WinDLL'),'Windows metadata reader')
    def test_string_and_handle_must_agree_and_duplicate_is_closed(self):
        child,kernel,native,_=self.fixture()
        with patch.object(ctypes,'WinDLL',side_effect=lambda name,**kw:kernel if name=='kernel32' else native):
            self.assertTrue(snapshot(child)['viewsAgree'])
            def wrong(handle,buffer,length,flags):buffer.value='\\\\?\\F:\\other';return len(buffer.value)
            kernel.GetFinalPathNameByHandleW.side_effect=wrong
            with self.assertRaisesRegex(RuntimeError,'disagree'):snapshot(child)
        self.assertEqual(kernel.CloseHandle.call_count,2)

    @unittest.skipUnless(hasattr(ctypes,'WinDLL'),'Windows metadata reader')
    def test_uninitialized_handle_is_explicitly_unproven(self):
        child,kernel,native,_=self.fixture(handle=0)
        with patch.object(ctypes,'WinDLL',side_effect=lambda name,**kw:kernel if name=='kernel32' else native):
            with self.assertRaisesRegex(RuntimeError,'not initialized'):snapshot(child)
            value=snapshot(child,allow_uninitialized=True)
        self.assertFalse(value['viewsAgree']);self.assertEqual(value['rootHandle'],'0x0')
        kernel.DuplicateHandle.assert_not_called()

    @unittest.skipUnless(hasattr(ctypes,'WinDLL'),'Windows metadata reader')
    def test_changed_header_cannot_be_accepted_after_handle_query(self):
        child,kernel,native,metadata=self.fixture()
        def final(handle,buffer,length,flags):
            buffer.value='\\\\?\\E:\\owned\\game';metadata[0x2038]=b'\0'*24;return len(buffer.value)
        kernel.GetFinalPathNameByHandleW.side_effect=final
        with patch.object(ctypes,'WinDLL',side_effect=lambda name,**kw:kernel if name=='kernel32' else native):
            with self.assertRaisesRegex(RuntimeError,'changed'):snapshot(child)
        kernel.CloseHandle.assert_called_once();self.assertEqual(kernel.CloseHandle.call_args.args[0].value,41)

    @unittest.skipUnless(hasattr(ctypes,'WinDLL'),'Windows metadata reader')
    def test_handle_identity_mismatch_never_reads_process_memory(self):
        child,kernel,native,_=self.fixture();kernel.GetProcessId.return_value=999
        with patch.object(ctypes,'WinDLL',side_effect=lambda name,**kw:kernel if name=='kernel32' else native):
            with self.assertRaisesRegex(ValueError,'identity'):snapshot(child)
        kernel.ReadProcessMemory.assert_not_called();kernel.DuplicateHandle.assert_not_called()


if __name__=='__main__':unittest.main()
