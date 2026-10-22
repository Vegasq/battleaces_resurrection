"""Authored metadata schema negatives;actual NtOpenFile control is separate."""
from copy import deepcopy
import unittest
from tools.attribution_path_metadata import unresolved
from tools.frida_attribution_paths import build_source,control_request
from tools.frida_attribution_clock import build_source as clock_source
from tests.test_attribution_control import IMAGE,FOLDER,RUN


class AttributionPaths(unittest.TestCase):
    def test_valid_entry_is_not_a_claim_of_success_or_absolute_root(self):
        value=dict(api='ntdll.dll:NtOpenFile',operation='NtOpenFile',phase='entry',rootHandle='0xab',
                   relativePath='queued.json',frames=[dict(module='python314.dll',rva='0x123')])
        self.assertEqual(unresolved(value),value)
        for field,replacement in (('api','ntdll.dll:NtReadFile'),('phase','return'),('rootHandle','0x0'),
                ('rootHandle','0x'+'1'*17),('relativePath','\\absolute'),('relativePath',''),
                ('relativePath','x'*4097),('relativePath','bad\0name'),('frames',[]),
                ('frames',[dict(module='C:/private.dll',rva='0x1')]),('frames',[dict(module='native.dll',rva=True)])):
            with self.subTest(field=field,replacement=str(replacement)[:30]):
                broken=deepcopy(value);broken[field]=replacement
                with self.assertRaises(ValueError):unresolved(broken)
        broken=deepcopy(value);broken['returnValue']=0
        with self.assertRaises(ValueError):unresolved(broken)

    def test_source_is_opt_in_and_retains_the_unknown_counter(self):
        config,request=control_request(IMAGE,FOLDER,RUN);old=clock_source(config,include_kernel32=True)
        source=build_source(config)
        self.assertNotIn("emit('unresolved-file-root'",old)
        self.assertIn("unknownRelativeRoots++;emit('unresolved-file-root'",source)
        self.assertIn('frames:frames(context)',source)
        self.assertIn('phase:\'entry\'',source)
        for forbidden in ('new NativeFunction','Interceptor.replace','retval.replace','NtQueryObject','rpc.exports'):
            self.assertNotIn(forbidden,source)
        compile(request['argv'][3],'<authored relative-root control>','exec')
        self.assertIn('NtOpenFile(ctypes.byref(opened)',request['argv'][3])
        self.assertIn('DuplicateHandle(current,directory',request['argv'][3])


if __name__=='__main__':unittest.main()
