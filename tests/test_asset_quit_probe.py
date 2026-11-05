"""Admission evidence must distinguish a deferred request from a real veto."""
import copy
import json
import os
from pathlib import Path
import unittest

from tools.asset_quit_probe import validate


def fixture():
    rows=[]
    def add(kind, **kw):
        rows.append(dict(schema=1,pid=99,tid=7,sequence=len(rows)+1,tick=100+len(rows),kind=kind,**kw))
    handle=dict(operation='0x1234',version=3)
    add('armed',counterWrites=0,completionCalls=0,callbackSuppression=0)
    add('load-return',handle=handle,count=1,wants=0)
    add('subscribe',handle=handle,count=1,wants=0,boxedFieldOffsets=[16,24,32,40],unboxedSize=32)
    add('loader-exit',count=1,wants=0)
    add('request-quit',count=1,wants=0)
    add('request-return',count=1,wants=0)
    add('wants-return',count=1,wants=1,accepted=0)
    add('completion-enter',handle=handle,count=1,wants=1)
    add('application-quit',count=0,wants=1,inCompletion=True)
    add('completion-return',count=0,wants=1)
    add('wants-return',count=0,wants=1,accepted=1)
    add('assets-quit',count=0,wants=1)
    return rows


class AssetQuitEvidenceTests(unittest.TestCase):
    def test_scoped_chain(self):
        result=validate(fixture(),99)
        self.assertTrue(result['positive_counter_veto'])
        for key in ('physical_input','io_stall','hung_engine_recovery','safe_scene_cancellation'):
            self.assertFalse(result[key])

    def test_refuses_false_positive_variants(self):
        for kind,field,value in [('completion-enter','wants',0),('completion-enter','count',0),
                                 ('completion-enter','tid',8),('subscribe','boxedFieldOffsets',[0,8,16,24]),
                                 ('completion-return','count',1),('armed','counterWrites',1),
                                 ('application-quit','inCompletion',False)]:
            with self.subTest(kind=kind,field=field):
                rows=copy.deepcopy(fixture());next(r for r in rows if r['kind']==kind)[field]=value
                with self.assertRaises(ValueError):validate(rows,99)

    def test_refuses_deferred_admission(self):
        rows=fixture();vote=rows.pop(6);rows.insert(10,vote)
        for i,r in enumerate(rows):r.update(sequence=i+1,tick=100+i)
        with self.assertRaises(ValueError):validate(rows,99)

    def test_refuses_other_handle_version(self):
        rows=copy.deepcopy(fixture());rows[7]['handle']=dict(operation='0x1234',version=4)
        with self.assertRaises(ValueError):validate(rows,99)

    def test_refuses_missing_retry(self):
        rows=fixture();rows.pop(8)
        for i,r in enumerate(rows):r['sequence']=i+1
        with self.assertRaises(ValueError):validate(rows,99)

    def test_refuses_error_or_wrong_pid(self):
        rows=fixture();rows[-1]['kind']='error'
        with self.assertRaises(ValueError):validate(rows,99)
        with self.assertRaises(ValueError):validate(fixture(),100)


@unittest.skipUnless(os.environ.get('BA_ASSET_QUIT_RUNS'), 'owned retained traces required')
class RetainedAssetQuitTests(unittest.TestCase):
    def read(self,name):
        folder=Path(os.environ['BA_ASSET_QUIT_RUNS'])/name
        report=json.loads((folder/'verification.json').read_bytes())
        rows=[json.loads(line) for line in (folder/'asset-quit.jsonl').read_text().splitlines()]
        return report,rows

    def test_original_deferred_request_stays_failed(self):
        report,rows=self.read('native01')
        self.assertFalse(report['passed'])
        self.assertTrue(report['natural_exit'])
        self.assertFalse(report['owned_child']['forced_cleanup'])
        with self.assertRaises(ValueError):validate(rows,report['owned_child']['pid'])

    def test_earlier_request_has_real_veto_and_retry(self):
        report,rows=self.read('native02')
        self.assertTrue(validate(rows,report['owned_child']['pid'])['passed'])
        for field in ('passed','natural_exit','settings_parsed_unchanged','shared_unchanged','identities_unchanged','source_unchanged'):
            self.assertTrue(report[field],field)
        self.assertFalse(report['owned_child']['forced_cleanup'])
        self.assertEqual(report['owned_child']['exit_code'],0)
        self.assertEqual(report['owned_child']['job_final']['active_processes'],0)


if __name__=='__main__':unittest.main()
