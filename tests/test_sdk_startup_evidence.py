import copy
import unittest
from tools.frida_sdk_startup import ENTRIES
from tools.sdk_startup_evidence import validate


class SDKStartupEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.sdk=dict(module=r'E:\owned\GameAssembly.dll',entries=[dict(name=name,rva=rva,sha256='0'*64)
            for name,rva in ENTRIES.items()])
        install=dict(module=self.sdk['module'],entries=self.sdk['entries'],entryEventLimitPerName=8,
            argumentsRead=False,targetApisInvoked=False,sdkRootReplaced=False,generalUnityPathReplaced=False)
        snapshot=dict(sdk=dict(installed=True,counts=dict.fromkeys(ENTRIES,0)),errors=[],overflow=False,unknownRelativeRoots=0)
        items=[('observer-ready',dict(errors=[])),('sdk-installed',install),('heartbeat',snapshot),
               ('process-exit-entry',copy.deepcopy(snapshot)),('process-exit-entry',copy.deepcopy(snapshot))]
        self.rows=[dict(schema=1,seq=i,runId='1'*32,pid=17,tid=18,elapsedMs=i,kind=kind,data=data)
                   for i,(kind,data) in enumerate(items,1)]

    def check(self,rows):return validate(rows,pid=17,run_id='1'*32,sdk=self.sdk)

    def test_quiet_scope_explicitly_cannot_close_full_privacy(self):
        result=self.check(self.rows)
        self.assertTrue(result['selected_sdk_entries_quiet'])
        self.assertFalse(result['full_privacy_qualified'])
        self.assertFalse(result['sdk_root_replaced'])

    def test_missing_or_fabricated_installation_final_entry_and_error_reject(self):
        cases=[]
        for index in (1,4):cases.append(self.rows[:index]+self.rows[index+1:])
        for key,value in [('sdkRootReplaced',True),('targetApisInvoked',True),('argumentsRead',0)]:
            bad=copy.deepcopy(self.rows);bad[1]['data'][key]=value;cases.append(bad)
        bad=copy.deepcopy(self.rows);bad[-1]['data']['errors']=['injected'];cases.append(bad)
        bad=copy.deepcopy(self.rows);del bad[2]['data']['errors'];cases.append(bad)
        bad=copy.deepcopy(self.rows);bad[-1]['data']['overflow']=True;cases.append(bad)
        for bad in cases:
            with self.subTest(bad=bad),self.assertRaises(AssertionError):self.check(bad)

    def test_noninteger_missing_reset_and_unreported_positive_counters_reject(self):
        cases=[]
        for value in (True,-1,1.0,1):
            bad=copy.deepcopy(self.rows);bad[-1]['data']['sdk']['counts']['Client.ctor']=value;cases.append(bad)
        bad=copy.deepcopy(self.rows);del bad[-1]['data']['sdk']['counts']['Client.ctor'];cases.append(bad)
        bad=copy.deepcopy(self.rows);bad[-1]['data']['sdk']['installed']=False;cases.append(bad)
        for bad in cases:
            with self.subTest(bad=bad),self.assertRaises(AssertionError):self.check(bad)

    def test_actual_positive_entry_is_reported_as_activity_not_absence(self):
        rows=copy.deepcopy(self.rows)
        rows.insert(2,dict(schema=1,seq=3,runId='1'*32,pid=17,tid=18,elapsedMs=3,kind='sdk-entry',
            data=dict(name='Client.ctor',call=1,frames=[dict(module='authored.dll',rva='0x1')])))
        for i,row in enumerate(rows,1):
            row['seq']=i;row['elapsedMs']=i
            if 'sdk' in row['data']:row['data']['sdk']['counts']['Client.ctor']=1
        result=self.check(rows)
        self.assertFalse(result['selected_sdk_entries_quiet'])
        self.assertEqual(result['entry_record_count'],1)
        self.assertFalse(result['full_privacy_qualified'])
        for frames in ([],[dict(module='UPPER.dll',rva='0x1')],[dict(module='authored.dll',rva=True)],
                       [dict(module='C:\\foreign.dll',rva='0x1')]):
            bad=copy.deepcopy(rows);bad[2]['data']['frames']=frames
            with self.subTest(frames=frames),self.assertRaises(AssertionError):self.check(bad)
        rows[-1]['data']['sdk']['counts']['Client.ctor']=0
        with self.assertRaises(AssertionError):self.check(rows)
