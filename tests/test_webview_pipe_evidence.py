"""Asset-free fixtures reproduce alias completion order and pending native waits."""
from copy import deepcopy
import unittest
from tools.frida_webview_pipe import descriptor
from tools.webview_pipe_evidence import ARGUMENTS, CALLERS, validate


def fixture(role='parent'):
    image=r'E:\owned\Battle Aces.exe' if role=='parent' else r'E:\owned\VuplexWebViewChromium\Vuplex WebView.vuplex'
    witness=descriptor(role,image,'1'*32)
    names=list(ARGUMENTS)[:3] if role=='parent' else ['CreateFileA']
    bindings=['kernel32.dll:'+n for n in names]+['kernelbase.dll:'+n for n in names if n!='CreateNamedPipeA']
    rows=[]
    def row(kind,data):
        rows.append(dict(schema=1,seq=len(rows)+1,runId='2'*32,pid=123,tid=456,elapsedMs=len(rows)*10,kind=kind,data=data,
                         otherAnnotation=dict(retained=True)))
    def snapshot(counts):row('pipe-probe-snapshot',dict(role=role,counts=counts,errors=[],nameValuesRetained=False))
    def operation(name,call,module='kernel32.dll',result=None,error=None):
        data=dict(api=module+':'+name,operation=name,frames=[dict(module=CALLERS[name][0],rva=CALLERS[name][1])],
                  nameLength=64,nameSha256='4'*64,fixedPrefixMatched=True,call=call,lastError=error,**ARGUMENTS[name])
        key='waitResult' if name=='WaitForSingleObject' else 'returned' if name=='ConnectNamedPipe' else 'handleValid'
        data[key]=result
        row('pipe-operation',data)
    row('observer-ready',dict(legacy='retained'))
    row('pipe-probe-ready',dict(role=role,descriptor=witness,bindings=bindings,errors=[],nameValuesRetained=False,apiResultsReplaced=False))
    # An unrelated gap/diagnostic is deliberately retained and not qualified here.
    row('decode-error',dict(api='ntdll.dll:NtOpenFile',unresolvedRoot=True))
    snapshot({n:0 for n in names})
    if role=='parent':
        operation('CreateNamedPipeA',1,result=True)
        operation('ConnectNamedPipe',2,'kernelbase.dll',False,997)
        operation('ConnectNamedPipe',1,result=False,error=997)
        snapshot(dict(CreateNamedPipeA=1,ConnectNamedPipe=2,WaitForSingleObject=2))
        operation('WaitForSingleObject',2,'kernelbase.dll',0)
        operation('WaitForSingleObject',1,result=0)
        snapshot(dict(CreateNamedPipeA=1,ConnectNamedPipe=2,WaitForSingleObject=2))
    else:
        operation('CreateFileA',2,'kernelbase.dll',False,5)
        operation('CreateFileA',1,result=False,error=5)
        snapshot(dict(CreateFileA=2))
    return rows,dict(pid=123,run_id='2'*32,role=role,witness=deepcopy(witness))


class PipeEvidenceTests(unittest.TestCase):
    def reject(self,rows,args,change):
        modified=deepcopy(rows);change(modified)
        with self.assertRaises(AssertionError):validate(modified,**args)

    def test_alias_callbacks_out_of_order_and_original_rows_untouched(self):
        digests=[]
        for role in ('parent','child'):
            rows,args=fixture(role);before=deepcopy(rows);report=validate(rows,**args)
            self.assertTrue(report['passed']);self.assertEqual(rows,before)
            self.assertFalse(report['rows_projected']);self.assertFalse(report['full_P8_qualified']);self.assertFalse(report['full_privacy_qualified'])
            self.assertTrue(report['last_snapshot_after_operations']);self.assertTrue(all(not v for v in report['pending_entered_call_ids'].values()))
            self.assertEqual(report['operations'][1 if role=='parent' else 0]['call'],2)
            digests.append(report['digests'])
        self.assertEqual(digests[0],digests[1])

    def test_pending_wait_entries_are_not_fabricated_completed(self):
        rows,args=fixture();rows=rows[:8]
        report=validate(rows,**args)
        self.assertEqual(report['last_snapshot_entered']['WaitForSingleObject'],2)
        self.assertEqual(report['completed_counts']['WaitForSingleObject'],0)
        self.assertEqual(report['pending_entered_call_ids']['WaitForSingleObject'],[1,2])
        self.assertNotIn('complete',report)

    def test_snapshot_before_later_returns_exposed_not_resequenced(self):
        rows,args=fixture();rows.pop()
        report=validate(rows,**args)
        self.assertFalse(report['last_snapshot_after_operations']);self.assertEqual(report['completed_call_ids']['WaitForSingleObject'],[1,2])

    def test_every_envelope_checked_even_unrelated_legacy_kind(self):
        rows,args=fixture()
        for field,value in [('schema',True),('seq',4),('pid',True),('pid',999),('runId','3'*32),('tid',False),('elapsedMs',-1),('elapsedMs',999999)]:
            with self.subTest(field=field,value=value):self.reject(rows,args,lambda r:r[2].__setitem__(field,value))

    def test_descriptor_binding_inventory_and_redaction_refusal(self):
        rows,args=fixture()
        changes=[lambda r:r[1]['data']['descriptor'].__setitem__('nonce','3'*32),
                 lambda r:r[1]['data']['descriptor'].__setitem__('prefixRva',0x84050),
                 lambda r:r[1]['data'].__setitem__('nameValuesRetained',True),
                 lambda r:r[1]['data'].__setitem__('apiResultsReplaced',True),
                 lambda r:r[1]['data']['bindings'].append('kernel32.dll:CreateNamedPipeA'),
                 lambda r:r[1]['data']['bindings'].append('foreign.dll:CreateNamedPipeA'),
                 lambda r:r[1]['data'].__setitem__('errors',['install']),
                 lambda r:r[1]['data'].__setitem__('role','child')]
        for change in changes:
            with self.subTest(change=change):self.reject(rows,args,change)
        bad=deepcopy(args);bad['witness']['sha256']='f'*64
        with self.assertRaises(AssertionError):validate(rows,**bad)

    def test_extra_raw_uuid_key_namefacts_and_stack_mutations_refused(self):
        rows,args=fixture('child')
        for field,value in [('name','PRIVATE_UUID'),('nameLength',True),('nameLength',63),('nameSha256','g'*64),('fixedPrefixMatched',1),('call',True),('api','kernelbase.dll:ConnectNamedPipe')]:
            with self.subTest(field=field):self.reject(rows,args,lambda r:r[4]['data'].__setitem__(field,value))
        self.reject(rows,args,lambda r:r[4]['data']['frames'][0].__setitem__('rva','0x84050'))
        self.reject(rows,args,lambda r:r[4]['data']['frames'][0].__setitem__('module','wrong.dll'))
        self.reject(rows,args,lambda r:r[4]['data']['frames'][0].__setitem__('raw','PRIVATE_UUID'))

    def test_win64_argument_types_and_original_values_refused(self):
        for role,index,field,value in [('parent',4,'openMode',3),('parent',4,'maxInstances',True),('parent',5,'overlappedNull',True),
                                       ('parent',8,'timeout',1000),('child',4,'desiredAccess',0),('child',4,'flags',False)]:
            rows,args=fixture(role)
            with self.subTest(field=field):self.reject(rows,args,lambda r:r[index]['data'].__setitem__(field,value))

    def test_duplicate_call_ids_refused_across_distinct_alias_labels(self):
        rows,args=fixture();self.reject(rows,args,lambda r:r[6]['data'].__setitem__('call',2))
        self.reject(rows,args,lambda r:r[8]['data'].__setitem__('call',0))
        self.reject(rows,args,lambda r:r[8]['data'].__setitem__('call',33))

    def test_last_error_and_wait_result_semantics(self):
        rows,args=fixture('child')
        for field,value in [('lastError',None),('lastError',True),('lastError',-1),('handleValid',1)]:
            with self.subTest(field=field):self.reject(rows,args,lambda r:r[4]['data'].__setitem__(field,value))
        self.reject(rows,args,lambda r:r[4]['data'].__setitem__('handleValid',True))
        rows,args=fixture()
        self.reject(rows,args,lambda r:r[4]['data'].__setitem__('lastError',123))
        self.reject(rows,args,lambda r:r[8]['data'].__setitem__('waitResult',42))
        self.reject(rows,args,lambda r:r[8]['data'].__setitem__('waitResult',0xffffffff))
        rows[8]['data'].update(waitResult=0xffffffff,lastError=5)
        self.assertTrue(validate(rows,**args)['passed'])

    def test_counter_errors_roles_and_regressions_refused(self):
        rows,args=fixture()
        for change in [lambda r:r[7]['data']['counts'].__setitem__('ConnectNamedPipe',1),
                       lambda r:r[7]['data']['counts'].__setitem__('WaitForSingleObject',True),
                       lambda r:r[7]['data']['counts'].__setitem__('WaitForSingleObject',33),
                       lambda r:r[7]['data']['counts'].__setitem__('CreateFileA',0),
                       lambda r:r[-1]['data']['counts'].__setitem__('WaitForSingleObject',1),
                       lambda r:r[7]['data'].__setitem__('errors',['return'])]:
            with self.subTest(change=change):self.reject(rows,args,change)
        self.reject(rows,args,lambda r:r[7].update(kind='pipe-probe-error',data=dict(phase='entry',operation='WaitForSingleObject')))
        self.reject(rows,args,lambda r:r[7].update(kind='pipe-unrecognized'))


if __name__=='__main__':unittest.main()
