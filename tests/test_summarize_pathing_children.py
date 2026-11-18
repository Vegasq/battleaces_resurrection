"""Authored nested timing and hostile schema2 capture controls; no native execution."""
import copy
from pathlib import Path
import unittest
from tests.test_summarize_native_systems import fixture as base_fixture
from tools import summarize_pathing_children as s


def fixture():
    bundle,config=base_fixture();final=bundle['records'][1]['normalized_result']
    for message in final['messages']:
        message['payload'].update(schema=2,sensorKind='pathing-children-v1')
    inv=final['messages'][1]['payload']['data']
    systems=[dict(index=i,object=hex(0x1000+i*8),vtableRva='0x100',updateRva='0x200',checksumRva='0x300') for i in range(41)]
    systems[23].update(vtableRva='0x391280',updateRva='0xf9540',type='.?AVSystemPathing@Uncapped@@')
    children=[dict(index=0,object='0x555',vtableRva='0x10',type='.?AVAuthoredChild@@',updateRva='0x20',updateEntryHex='48895c',updateTimed=True,reason=None,expectedTimedCallsPerPositiveStep=2),
        dict(index=1,object='0x556',vtableRva='0x30',type='.?AVAuthoredStub@@',updateRva='0x40',updateEntryHex='c30000',updateTimed=False,
             reason='exact immediate-return/return-zero leaf; no hook/count observation',expectedTimedCallsPerPositiveStep=0)]
    inv.pop('checksumEnabled');inv.pop('systems');inv.update(systems=systems,systemCount=41,pathing=copy.deepcopy(systems[23]),children=children,
        systemVectorBegin='0x10000',systemVectorEnd=hex(0x10000+41*8),childVectorBegin='0x20000',childVectorEnd='0x20010',
        finalPassRva='0xf8f40',parentEntryHex='48895c',finalPassEntryHex='405348',parentReturnRva='0x346d8',childReturnRva='0xf97a9',finalReturnRva='0xf97c8',
        expectedSubpasses=2,cellLayout=['observedCount','inclusiveTicksOrNull'])
    rows=final['messages'][2]['payload']['data']['rows']
    for row in rows:
        row.pop('checksumEnabled');row.pop('systems');row.update(pathing=[1,5],children=[[2,2],[0,None]],finalPass=[1,1],budgetValid=True)
    complete=final['messages'][-1]['payload']['data'];complete.pop('inventoryCount');complete.update(systemCount=41,childCount=2)
    bundle['records'][0]['normalized_result']['messages']=copy.deepcopy(final['messages'][:1])
    return bundle,config


class PathingTests(unittest.TestCase):
    def parse(self,b,c):return s.validate_capture(b,'evidence','session',c,'sha',Path('sensor.js'),2,50)
    def test_valid_nested_null(self):
        b,c=fixture();inv,rows=self.parse(b,c);self.assertEqual(len(inv['systems']),41);self.assertIsNone(rows[0]['children'][1][1])
    def test_adversarial(self):
        mutations=[
            ('schema',lambda n:n['messages'][2]['payload'].update(schema=1)),
            ('sensorkind',lambda n:n['messages'][2]['payload'].update(sensorKind='wrong')),
            ('lateerror',lambda n:n['messages'].append(dict(type='error',description='late'))),
            ('captureerror',lambda n:n['messages'][-1]['payload'].update(kind='capture-error')),
            ('truncated',lambda n:n.update(messages_truncated=True)),
            ('wrongPID',lambda n:n.update(pid=42)),
            ('nonce',lambda n:n['messages'][2]['payload'].update(nonce='wrong')),
            ('wrongscript',lambda n:n['messages'][2].update(script_id='wrong')),
            ('frame',lambda n:n['messages'][2]['payload']['data']['rows'][1].update(frame=0)),
            ('omission',lambda n:n['messages'][2]['payload']['data']['rows'].pop()),
            ('dt',lambda n:n['messages'][2]['payload']['data']['rows'][0].update(dt=51)),
            ('world',lambda n:n['messages'][1]['payload']['data'].update(world='0x2')),
            ('chunk',lambda n:n['messages'][2]['payload']['data'].update(start=1)),
            ('schemaextra',lambda n:n['messages'][2]['payload']['data']['rows'][0].update(extra=1)),
            ('nan',lambda n:n['messages'][2]['payload']['data']['rows'][0].update(stepTicks=float('nan'))),
            ('inf',lambda n:n['messages'][2]['payload']['data']['rows'][0]['pathing'].__setitem__(1,float('inf'))),
            ('budget',lambda n:n['messages'][2]['payload']['data']['rows'][0].update(budgetValid=False)),
            ('counts',lambda n:n['messages'][2]['payload']['data']['rows'][0].update(countsValid=False)),
            ('nativefailed',lambda n:n['messages'][2]['payload']['data']['rows'][0].update(returnCode=1)),
            ('parentcount',lambda n:n['messages'][2]['payload']['data']['rows'][0]['pathing'].__setitem__(0,2)),
            ('finalcount',lambda n:n['messages'][2]['payload']['data']['rows'][0]['finalPass'].__setitem__(0,0)),
            ('childcount',lambda n:n['messages'][2]['payload']['data']['rows'][0]['children'][0].__setitem__(0,1)),
            ('excludedelapsed',lambda n:n['messages'][2]['payload']['data']['rows'][0]['children'][1].__setitem__(1,0)),
            ('excludedcount',lambda n:n['messages'][2]['payload']['data']['rows'][0]['children'][1].__setitem__(0,2)),
            ('childconservation',lambda n:n['messages'][2]['payload']['data']['rows'][0]['children'][0].__setitem__(1,5)),
            ('parentconservation',lambda n:n['messages'][2]['payload']['data']['rows'][0]['pathing'].__setitem__(1,9)),
            ('bound',lambda n:n['messages'][2]['payload']['data']['rows'][0].update(stepTicks=120001)),
            ('parentcaller',lambda n:n['messages'][1]['payload']['data'].update(parentReturnRva='0x1')),
            ('childcaller',lambda n:n['messages'][1]['payload']['data'].update(childReturnRva='0x1')),
            ('finalcaller',lambda n:n['messages'][1]['payload']['data'].update(finalReturnRva='0x1')),
            ('subpasses',lambda n:n['messages'][1]['payload']['data'].update(expectedSubpasses=1)),
            ('duplicatechild',lambda n:n['messages'][1]['payload']['data']['children'][1].update(object='0x555')),
            ('duplicateindex',lambda n:n['messages'][1]['payload']['data']['children'][1].update(index=0)),
            ('fakeexclude',lambda n:n['messages'][1]['payload']['data']['children'][0].update(updateTimed=False)),
            ('wrongcallmeta',lambda n:n['messages'][1]['payload']['data']['children'][0].update(expectedTimedCallsPerPositiveStep=1)),
            ('vectorstride',lambda n:n['messages'][1]['payload']['data'].update(childVectorEnd='0x20011')),
            ('emptychildren',lambda n:n['messages'][1]['payload']['data'].update(children=[])),
            ('incomplete',lambda n:n['messages'][-1]['payload']['data'].update(frames=1)),
            ('completefailed',lambda n:n['messages'][-1]['payload']['data'].update(failed=True)),
        ]
        for name,mutate in mutations:
            with self.subTest(name=name):
                b,c=fixture();mutate(b['records'][1]['normalized_result'])
                with self.assertRaises((ValueError,KeyError,TypeError)):self.parse(b,c)
    def test_each_exact_excluded_leaf(self):
        for entry in ('c30000','c20000','33c0c3','31c0c3'):
            b,c=fixture();b['records'][1]['normalized_result']['messages'][1]['payload']['data']['children'][1]['updateEntryHex']=entry
            self.parse(b,c)
    def test_dt_zero_is_unobserved(self):
        b,c=fixture()
        for row in b['records'][1]['normalized_result']['messages'][2]['payload']['data']['rows']:
            row.update(dt=0,pathing=[0,0],finalPass=[0,0],children=[[0,0],[0,None]])
        s.validate_capture(b,'evidence','session',c,'sha',Path('sensor.js'),2,0)
    def test_exact_image_guards(self):
        b,c=fixture();inv,_=self.parse(b,c)
        from unittest.mock import patch
        class FakePE:
            size=999
            def at(self,*args):return b'\0'*args[1]
        with patch.object(s.common,'PE',return_value=FakePE()):
            with self.assertRaisesRegex(ValueError,'required STEP'):s.validate_image(inv,{'byte_checks':[]},b'authored')
            with self.assertRaisesRegex(ValueError,'exact image'):s.validate_image(inv,{'byte_checks':[dict(rva=0x14180,hex='ffffff')]},b'authored')
    def test_bad_script_source_hash(self):
        b,c=fixture();b['records'][0]['normalized_result']['source_sha256']='changed'
        with self.assertRaisesRegex(ValueError,'script source'):self.parse(b,c)


if __name__=='__main__':unittest.main()
