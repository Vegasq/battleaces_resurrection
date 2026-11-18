"""Authored hostile-capture controls; no native execution or private fixtures."""
import copy
from pathlib import Path
import unittest
from tools import summarize_native_systems as s


def fixture():
    config=dict(pid=123,nonce='a'*64,world='0x1000',expected_frames=2,byte_checks=[{}])
    systems=[dict(index=0,object='0x1234',type='.?AVSystemAuthored@@',updateRva='0x10',checksumRva='0x20',
        updateTimed=True,updateEntryHex='48895c',updateReason=None,checksumTimed=False,
        checksumEntryHex='33c0c3',checksumReason='exact immediate-return/return-zero leaf; not instrumented')]
    armed=dict(world='0x1000',moduleBase='0x100',expectedFrames=2,byteChecks=1,ticksPerSecond=1000)
    inventory=dict(world='0x1000',moduleBase='0x100',moduleSize=999,checksumEnabled=0,ticksPerSecond=1000,unit='QPC ticks',systems=systems)
    rows=[dict(frame=i,tid=789,dt=50,checksumEnabled=0,systems=[[1,5,0,None]],stepTicks=8,returnCode=0,countsValid=True) for i in range(2)]
    complete=dict(frames=2,expectedFrames=2,failed=False,inventoryCount=1,capturedThrough=1)
    messages=[dict(type='send',script_id='script',payload=dict(schema=1,nonce=config['nonce'],pid=123,kind=k,data=d))
        for k,d in [('armed',armed),('inventory',inventory),('frames',dict(start=0,rows=rows)),('complete',complete)]]
    load=dict(evidence_id='load',operation='load_frida_script',parameters=dict(session_id='session'),normalized_result=dict(script_id='script',source_kind='file',source_path='sensor.js',source_sha256='sha',messages_truncated=False,messages=copy.deepcopy(messages[:1])))
    final=dict(operation='frida_session_status',evidence_id='evidence',parameters=dict(session_id='session'),normalized_result=dict(session_id='session',state='detached',mode='attach',pid=123,messages_truncated=False,scripts=[dict(script_id='script')],messages=messages))
    return dict(records=[load,final]),config


class CaptureTests(unittest.TestCase):
    def parse(self,b,c):return s.validate_capture(b,'evidence','session',c,'sha',Path('sensor.js'),2,50)
    def test_valid_and_null_exclusion(self):
        b,c=fixture();inventory,frames=self.parse(b,c);self.assertIsNone(frames[0]['systems'][0][3]);self.assertEqual(len(inventory['systems']),1)
    def test_adversarial_mutations(self):
        mutations=[
            ('truncated',lambda n:n.update(messages_truncated=True)),
            ('pid',lambda n:n.update(pid=999)),
            ('wrongsession',lambda n:n.update(session_id='wrong')),
            ('running',lambda n:n.update(state='running')),
            ('script',lambda n:n['messages'][2].update(script_id='wrong')),
            ('nonce',lambda n:n['messages'][2]['payload'].update(nonce='wrong')),
            ('schema',lambda n:n['messages'][2]['payload'].update(schema=2)),
            ('world',lambda n:n['messages'][1]['payload']['data'].update(world='0x2')),
            ('chunkstart',lambda n:n['messages'][2]['payload']['data'].update(start=1)),
            ('omission',lambda n:n['messages'][2]['payload']['data']['rows'].pop()),
            ('duplicate',lambda n:n['messages'][2]['payload']['data']['rows'][1].update(frame=0)),
            ('dt',lambda n:n['messages'][2]['payload']['data']['rows'][0].update(dt=1)),
            ('tid',lambda n:n['messages'][2]['payload']['data']['rows'][1].update(tid=999)),
            ('count',lambda n:n['messages'][2]['payload']['data']['rows'][0]['systems'][0].__setitem__(0,0)),
            ('excludedcount',lambda n:n['messages'][2]['payload']['data']['rows'][0]['systems'][0].__setitem__(2,1)),
            ('excludedelapsed',lambda n:n['messages'][2]['payload']['data']['rows'][0]['systems'][0].__setitem__(3,0)),
            ('nonfinite',lambda n:n['messages'][2]['payload']['data']['rows'][0].update(stepTicks=float('nan'))),
            ('negative',lambda n:n['messages'][2]['payload']['data']['rows'][0].update(stepTicks=-1)),
            ('nonconservation',lambda n:n['messages'][2]['payload']['data']['rows'][0].update(stepTicks=4)),
            ('return',lambda n:n['messages'][2]['payload']['data']['rows'][0].update(returnCode=1)),
            ('countsvalid',lambda n:n['messages'][2]['payload']['data']['rows'][0].update(countsValid=False)),
            ('failed',lambda n:n['messages'][-1]['payload']['data'].update(failed=True)),
            ('completedcoverage',lambda n:n['messages'][-1]['payload']['data'].update(frames=1)),
            ('fakeexclusion',lambda n:n['messages'][1]['payload']['data']['systems'][0].update(updateTimed=False)),
            ('unknownkind',lambda n:n['messages'][2]['payload'].update(kind='capture-error')),
            ('latererror',lambda n:n['messages'].append(dict(type='error',script_id='script',description='late'))),
            ('captureerroraftercomplete',lambda n:n['messages'].append(copy.deepcopy(n['messages'][2]))),
        ]
        for name,mutation in mutations:
            with self.subTest(name=name):
                b,c=fixture();mutation(b['records'][1]['normalized_result'])
                with self.assertRaises((ValueError,KeyError,TypeError)):self.parse(b,c)
    def test_script_binding(self):
        for key,value in [('source_sha256','other'),('source_path','other'),('script_id','other'),('messages_truncated',True)]:
            with self.subTest(key=key):
                b,c=fixture();b['records'][0]['normalized_result'][key]=value
                with self.assertRaises(ValueError):self.parse(b,c)
    def test_duplicate_evidence(self):
        b,c=fixture();b['records'].append(copy.deepcopy(b['records'][1]))
        with self.assertRaises(ValueError):self.parse(b,c)
    def test_checksum_timed_enabled(self):
        b,c=fixture();n=b['records'][1]['normalized_result'];inv=n['messages'][1]['payload']['data'];inv['checksumEnabled']=1
        inv['systems'][0].update(checksumTimed=True,checksumEntryHex='48895c',checksumReason=None)
        for row in n['messages'][2]['payload']['data']['rows']:row.update(checksumEnabled=1,systems=[[1,5,1,2]])
        self.parse(b,c)
        n['messages'][2]['payload']['data']['rows'][0]['systems'][0][2]=0
        with self.assertRaises(ValueError):self.parse(b,c)
    def test_zero_dt_requires_no_update(self):
        b,c=fixture()
        for row in b['records'][1]['normalized_result']['messages'][2]['payload']['data']['rows']:row.update(dt=0,systems=[[0,0,0,None]])
        s.validate_capture(b,'evidence','session',c,'sha',Path('sensor.js'),2,0)
    def test_json_strictness(self):
        for raw in ('{"a":1,"a":2}','{"a":NaN}','{"a":Infinity}'):
            with self.assertRaises(ValueError):s.strict_json(raw)
    def test_stats(self):
        self.assertEqual(s.stats([3,1,2])['p50'],2)
        with self.assertRaises(ValueError):s.stats([float('inf')])
    def test_unknown_image_method_rejected(self):
        from unittest.mock import patch
        b,c=fixture();inventory,_=self.parse(b,c)
        class FakePE:
            size=999;base=100
            def at(self,rva,size):return b'\0'*size
        inventory['systems'][0]['vtableRva']='0x30'
        with patch.object(s,'PE',return_value=FakePE()):
            with self.assertRaisesRegex(ValueError,'changed vtable'):s.validate_inventory_image(inventory,{**c,'byte_checks':[]},b'authored')


if __name__ == '__main__':unittest.main()

