import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from server import host_audit
from tools.audit_stage_probe import AuditStages,GCWindows,review_stages
from tools.timing_probe import TimingObservations


class Tests(unittest.TestCase):
    def test_gc_windows_observe_without_changing_runtime_or_other_callbacks(self):
        sentinel=object();clock=[1_000_000_000]
        fake=SimpleNamespace(callbacks=[sentinel],isenabled=lambda:True,get_threshold=lambda:(700,10,10))
        with mock.patch('tools.audit_stage_probe.gc',fake):
            observer=GCWindows(clock=lambda:clock[0],capacity=1)
            observer.observe('start',dict(generation=2));clock[0]+=500_000_000
            observer.observe('stop',dict(generation=2,collected=3,uncollectable=0))
            observer.observe('start',dict(generation=0));clock[0]+=1
            observer.observe('stop',dict(generation=0,collected=0,uncollectable=0))
            result=observer.detach()
        self.assertEqual(fake.callbacks,[sentinel])
        self.assertEqual(result['before'],result['after'])
        self.assertTrue(result['callbacks_preserved']);self.assertEqual(result['dropped'],1)
        self.assertEqual(result['rows'][0]['finished_ns']-result['rows'][0]['started_ns'],500_000_000)

    def test_gc_mismatch_and_external_callback_change_are_not_hidden(self):
        first,second=object(),object()
        fake=SimpleNamespace(callbacks=[first],isenabled=lambda:True,get_threshold=lambda:(700,10,10))
        with mock.patch('tools.audit_stage_probe.gc',fake):
            observer=GCWindows();observer.observe('stop',dict(generation=2))
            fake.callbacks.append(second);result=observer.detach()
        self.assertEqual(fake.callbacks,[first,second])
        self.assertFalse(result['callbacks_preserved']);self.assertEqual(result['errors'],['unmatched GC stop'])

    def test_arbitrary_original_field_names_are_forwarded(self):
        with tempfile.TemporaryDirectory() as folder:
            audit=host_audit.HostAudit(folder,max_bytes=65536,backups=1)
            probe=TimingObservations();stages=AuditStages(audit,host_audit,probe)
            fields=dict(kind='custom',operation='build',metadata={'value':1})
            try:stages.call('original',**fields)
            finally:audit.close();stages.detach()
            row=json.loads((Path(folder)/'events.jsonl').read_bytes())
            self.assertTrue(all(row[key]==value for key,value in fields.items()))

    def test_actual_rotation_utf8_omission_and_bytes_match_original(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);probe=TimingObservations();results=[]
            original_json=host_audit.json
            fixed_datetime=SimpleNamespace(now=lambda zone:SimpleNamespace(isoformat=lambda:'fixed'))
            with mock.patch.object(host_audit,'datetime',fixed_datetime),mock.patch.object(host_audit,'time',SimpleNamespace(perf_counter_ns=lambda:123)):
                for observed in (False,True):
                    audit=host_audit.HostAudit(root/str(observed),max_bytes=65536,backups=2,diagnostics=True)
                    audit.session='fixed';stages=AuditStages(audit,host_audit,probe) if observed else None
                    try:
                        call=stages.call if stages else audit
                        for index in range(100):call('row',index=index,label='界'*900)
                        call('oversized',text='x'*70000)
                    finally:
                        audit.close()
                        if stages:stages.detach()
                    results.append({p.name:p.read_bytes() for p in (root/str(observed)).iterdir()})
            self.assertEqual(results[0],results[1])
            self.assertIs(host_audit.json,original_json)
            self.assertNotIn('_rotate',audit.__dict__)
            review=review_stages(probe.report())
            self.assertEqual(review['calls'],101)
            self.assertGreater(review['stages']['audit_rotate']['count'],0)
            self.assertEqual(review['stages']['audit_json']['count'],102)
            self.assertEqual(review['stages']['audit_write']['count'],101)

    def test_original_quiet_filter_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            audit=host_audit.HostAudit(folder,max_bytes=65536,backups=1)
            probe=TimingObservations();stages=AuditStages(audit,host_audit,probe)
            try:
                stages.call('frame_queued',frame=0)
                self.assertEqual([row['kind'] for row in probe.rows],['audit'])
                stages.call('match_completed',match='test')
            finally:audit.close();stages.detach()
            self.assertEqual(review_stages(probe.report())['stages']['audit_write']['count'],1)

    def test_write_window_separated_and_error_identity_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            audit=host_audit.HostAudit(folder,max_bytes=65536,backups=1,diagnostics=True)
            clock=[1_000_000_000];probe=TimingObservations(clock=lambda:clock[0])
            original=audit.stream;error=OSError('original write refusal');fail=[False];received=[]
            class Stream:
                def write(self,value):
                    received.append(value);clock[0]+=500_000_000
                    if fail[0]:raise error
                    return original.write(value)
                def close(self):return original.close()
            audit.stream=Stream();stages=AuditStages(audit,host_audit,probe)
            try:
                stages.call('frame_queued',match='test',frame=0)
                result=review_stages(probe.report())
                self.assertEqual(result['stages']['audit_write']['maximum_ms'],500)
                self.assertEqual(result['stages']['audit_json']['maximum_ms'],0)
                payload=b'original object'
                stages.audit.stream.write(payload)
                self.assertIs(received[-1],payload)
                fail[0]=True
                with self.assertRaises(OSError) as caught:stages.call('frame_queued',match='test',frame=1)
                self.assertIs(caught.exception,error)
                self.assertIsNone(stages.current)
            finally:audit.close();stages.detach()

    def test_missing_child_overflow_and_parent_identity_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            audit=host_audit.HostAudit(folder,max_bytes=65536,backups=1,diagnostics=True)
            probe=TimingObservations();stages=AuditStages(audit,host_audit,probe)
            try:stages.call('frame_queued',match='test',frame=0)
            finally:audit.close();stages.detach()
            original=probe.report();self.assertTrue(review_stages(original)['passed'])
            for mutation in ('missing','overflow','identity','outside'):
                raw=copy.deepcopy(original)
                child=next(row for row in raw['rows'] if row['kind']=='audit_write')
                if mutation=='missing':raw['rows'].remove(child)
                elif mutation=='overflow':raw['dropped']=1
                elif mutation=='identity':child['frame']=99
                else:child['started_ns']=1
                with self.subTest(mutation=mutation),self.assertRaises(ValueError):review_stages(raw)


if __name__=='__main__':unittest.main()
