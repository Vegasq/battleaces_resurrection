"""Actual observer-produced synthetic traces; no DLL/game/native execution."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from client_patch.prediction_worker.observation import CanonicalStateObserver, PositionTraceSpec
from tools.prediction_position_trace import MAX_BYTES, TraceError, analyze, read_trace


IDENTITY = dict(id=42, type=75, army=0)
BINDINGS = [dict(world=world, match=letter*32, entity=42, unit_type=75, army=0, incarnation=incarnation)
            for world, letter, incarnation in ((7, 'a', 101), (8, 'b', 102))]


class AnalyzerTests(unittest.TestCase):
    def fixture(self, *, changed=True, unavailable=None, missing_after=False, clipped=False):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        canonical=Path(folder.name)/'canonical-state.jsonl'
        spec=PositionTraceSpec(42,75,0,4,5 if clipped else 8)
        observer=CanonicalStateObserver(canonical,tick=lambda:0,position_trace=spec)
        self.addCleanup(observer.close)
        def actual(frame,stage):
            entity=dict(IDENTITY,position=[float(frame),-0.0,0.])
            if stage=='replay' and changed:entity['position']=[float(frame)-3.,-0.0,4.]
            if unavailable and stage=='ordinary' and frame==6:
                if unavailable=='absent':entities=[]
                elif unavailable=='partial':entities=[dict(IDENTITY)]
                else:entities=[dict(entity,type=76)]
            else:entities=[entity]
            return dict(frame=frame,viewer=31,entities=entities)
        for world,offset in ((7,1000),(8,2000)):
            observer.begin_world(world)
            for frame in range(7):
                context=dict(stage='ordinary',head=frame-1,confirmed=-1,received=-1,corrections=0,
                    replayed_frames=0,query_begin_us=offset+frame*10,query_end_us=offset+frame*10+4)
                observer.record(world,frame,actual(frame,'ordinary'),context=context if observer.position_active(world,frame)else None)
            observer.invalidate_after(world,3)
            for frame in range(4,6 if missing_after else 7):
                context=dict(stage='replay',head=6,confirmed=-1,received=4,corrections=0,
                    replayed_frames=frame-4,query_begin_us=offset+100+frame*10,query_end_us=offset+100+frame*10+4)
                observer.record(world,frame,actual(frame,'replay'),context=context if observer.position_active(world,frame)else None)
            observer.finish_world(world)
        observer.close()
        self.path=canonical.with_name('native-positions.jsonl')
        return read_trace(self.path)

    def check(self, rows=None, **kwargs):
        return analyze(self.fixture() if rows is None else rows,identity=IDENTITY,worlds=BINDINGS,**kwargs)

    def test_true_copied_same_head_pairs_bind_two_actual_external_worlds(self):
        rows=self.fixture();before=deepcopy(rows);result=self.check(rows)
        self.assertTrue(result['passed']);self.assertTrue(result['all_episodes_qualified'])
        self.assertEqual(rows,before)
        for world,binding in zip(result['worlds'],BINDINGS):
            self.assertEqual(world['binding'],binding);self.assertEqual(world['observed_frame_window'],[4,6])
            self.assertEqual(world['positive_same_head_pairs'],1)
            episode=world['episodes'][0]
            self.assertEqual(episode['physical_head'],6)
            self.assertEqual(episode['delta'],[-3.,0.,4.]);self.assertEqual(episode['magnitude'],5)
            self.assertEqual(rows[episode['before_record']]['head'],5)  # Query-time H, not invented restore-time H.
            self.assertEqual(rows[episode['after_record']]['head'],6)
        self.assertFalse(result['full_feature_accepted'])
        self.assertIn('cross-process QPC',result['scope'])
        self.assertFalse(any('incarnation'in row for row in rows))

    def test_absent_partial_mismatched_clipped_and_missing_pairs_never_become_zero_deltas(self):
        for flags in (dict(unavailable='absent'),dict(unavailable='partial'),dict(unavailable='mismatch'),
                      dict(clipped=True),dict(missing_after=True)):
            result=self.check(self.fixture(**flags))
            with self.subTest(flags=flags):
                self.assertFalse(result['passed']);self.assertFalse(result['all_episodes_qualified'])
                self.assertTrue(all(not e['qualified'] and e['delta']is None and e['magnitude']is None
                                    for world in result['worlds']for e in world['episodes']))

    def test_genuine_zero_is_reported_but_not_a_changed_correction_witness(self):
        result=self.check(self.fixture(changed=False))
        self.assertFalse(result['passed']);self.assertTrue(result['all_episodes_qualified'])
        self.assertTrue(all(e['qualified'] and not e['changed'] and e['delta']==[0.,0.,0.] and e['magnitude']==0
                            for world in result['worlds']for e in world['episodes']))

    def test_one_positive_world_cannot_substitute_for_missing_second_world(self):
        rows=[row for row in self.fixture()if row['world']==7]
        result=self.check(rows)
        self.assertTrue(result['worlds'][0]['passed']);self.assertFalse(result['worlds'][1]['passed'])
        self.assertFalse(result['passed']);self.assertFalse(result['all_episodes_qualified'])
        self.assertEqual(result['worlds'][1]['observed_frame_window'],None)
        self.assertFalse(self.check([])['passed'])

    def test_cached_query_reference_timestamp_position_revision_and_head_are_exact(self):
        original=self.fixture();index=next(i for i,r in enumerate(original)if r['event']=='before_restore_cached_head')
        for changes in (dict(cached_from_record=0),dict(query_begin_us=1),dict(query_revision=1),
                        dict(cached_physical_head=7),dict(frame=True),dict(first_divergent_frame=5)):
            rows=deepcopy(original);rows[index].update(changes)
            with self.subTest(changes=changes),self.assertRaises(TraceError):self.check(rows)
        rows=deepcopy(original);rows[index]['position']=[7.,-0.,0.]
        rows[index]['position_bits']=[0x40e00000,0x80000000,0]
        with self.assertRaisesRegex(TraceError,'changed before restore'):self.check(rows)

    def test_actual_replay_after_must_have_same_F_H_revision_and_D(self):
        original=self.fixture();index=next(i for i,r in enumerate(original)if r['event']=='after_replay_same_head')
        for changes in (dict(frame=7,head=7),dict(head=7),dict(revision=2),dict(checkpoint_base=2),
                        dict(event='native_position'),dict(stage='ordinary')):
            rows=deepcopy(original);rows[index].update(changes)
            with self.subTest(changes=changes),self.assertRaises(TraceError):self.check(rows)

    def test_clock_metrics_world_order_serial_and_bounds_are_not_silently_fixed(self):
        original=self.fixture()
        for changes in (dict(record=True),dict(world=9),dict(clock_source='GetTickCount64'),dict(query_scope='DLL-only'),
                        dict(query_begin_us=-1),dict(query_end_us=0),dict(position=[float('nan'),0,0]),
                        dict(position_bits=[0,0,0]),dict(watched_identity=dict(IDENTITY,army=1)),dict(incarnation=101)):
            rows=deepcopy(original);rows[0].update(changes)
            with self.subTest(changes=changes),self.assertRaises(TraceError):self.check(rows)
        rows=deepcopy(original);rows[-1]['replayed_frames']=0
        with self.assertRaisesRegex(TraceError,'metrics regressed'):self.check(rows)
        rows=deepcopy(original);rows[7]['query_begin_us']=1;rows[7]['query_end_us']=5
        with self.assertRaisesRegex(TraceError,'clock/metrics'):self.check(rows)
        rows=original[7:]+original[:7]
        for i,row in enumerate(rows):row=dict(row,record=i);rows[i]=row
        with self.assertRaisesRegex(TraceError,'out of order'):self.check(rows)
        with self.assertRaisesRegex(TraceError,'record bound'):self.check(original*1000)

    def test_external_FEEL_bindings_are_validated_and_only_decorate_native_data(self):
        rows=self.fixture()
        for changes in (dict(entity=43),dict(unit_type=76),dict(army=1),dict(incarnation=True),dict(match='bad')):
            bindings=deepcopy(BINDINGS);bindings[0].update(changes)
            with self.subTest(changes=changes),self.assertRaises(TraceError):analyze(rows,identity=IDENTITY,worlds=bindings)
        with self.assertRaisesRegex(TraceError,'exactly two'):analyze(rows,identity=IDENTITY,worlds=BINDINGS[:1])
        bindings=deepcopy(BINDINGS);bindings[0]['incarnation']=999
        result=analyze(rows,identity=IDENTITY,worlds=bindings)
        self.assertEqual(result['worlds'][0]['binding']['incarnation'],999)
        self.assertEqual(result['worlds'][0]['episodes'][0]['delta'],[-3.,0.,4.])


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'native-positions.jsonl'

    def test_closed_bounded_file_is_required_and_empty_file_is_explicit(self):
        self.path.write_bytes(b'');self.assertEqual(read_trace(self.path),[])
        for raw in (b'{"x":1}',b'{}\n{',b'\xff\n',b'{}\n'*8193,b' '*4097+b'\n'):
            self.path.write_bytes(raw)
            with self.subTest(bytes=len(raw)),self.assertRaises(TraceError):read_trace(self.path)
        self.path.write_bytes(b'{}\n')
        with patch.object(Path,'read_bytes',return_value=b''),self.assertRaisesRegex(TraceError,'partial/changed'):read_trace(self.path)
        self.path.write_bytes(b'x'*(MAX_BYTES+1))
        with self.assertRaisesRegex(TraceError,'byte bound'):read_trace(self.path)

    def test_duplicate_JSON_fields_and_nonfinite_constants_are_rejected(self):
        for raw in (b'{"id":1,"id":2}\n',b'{"position":[NaN,0,0]}\n',b'{"x":Infinity}\n'):
            self.path.write_bytes(raw)
            with self.subTest(raw=raw),self.assertRaises(TraceError):read_trace(self.path)


if __name__=='__main__':
    unittest.main()
