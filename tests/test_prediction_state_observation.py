"""Authored observer/dispatcher tests; no original native DLL/game is loaded."""
from copy import deepcopy
import io
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from client_patch.prediction_worker.observation import CanonicalStateObserver, ObservationError, PositionTraceSpec, state_digest
from client_patch.prediction_worker.native import HostError, NativeSession
from server.game_data import encode_frame
from server.native_simulation import decode_snapshot
from tests.test_prediction_worker import command
from tests.test_prediction_worker_ledger_integration import NativeFixture, SnapshotHeap, view
from tests.test_prediction_command_ledger import body, join, MOVE


def state(frame, **extra):
    return dict(frame=frame, viewer=31, entities=[dict(id=42, army=0, type=75)], raw_sha256='opaque', **extra)


class ObserverTests(unittest.TestCase):
    def observer(self, **kwargs):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'canonical-state.jsonl'
        value = CanonicalStateObserver(path, tick=lambda: 12345, **kwargs)
        self.addCleanup(value.close)
        value.begin_world(7)
        return value, path

    def rows(self, path):
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_digest_exactly_matches_existing_authority_normalization(self):
        from tools.verify_high_latency_clients import state_digest as authority_digest
        value = state(0, byte_count=123, resources={0: {'supply': 2}})
        self.assertEqual(state_digest(value), authority_digest(value))
        other = dict(value, raw_sha256='different opaque native bytes')
        self.assertEqual(state_digest(value), state_digest(other))
        other['byte_count'] += 1
        self.assertNotEqual(state_digest(value), state_digest(other))

    def test_only_contiguous_confirmed_frames_are_written_and_flushed(self):
        observer, path = self.observer()
        for frame in range(4): observer.record(7, frame, state(frame))
        self.assertEqual(path.read_bytes(), b'')
        observer.promote(7, 1, dict(corrections=0, replayed_frames=0))
        self.assertEqual([r['frame'] for r in self.rows(path)], [0, 1])
        self.assertEqual(set(observer.pending), {2, 3})
        self.assertTrue(all(r['confirmed_frontier'] == 1 and r['world'] == 7 for r in self.rows(path)))

    def test_restore_invalidates_future_candidates_before_replacement(self):
        observer, path = self.observer()
        for frame in range(4): observer.record(7, frame, state(frame, branch='wrong'))
        observer.promote(7, 0, dict(corrections=0, replayed_frames=0))
        observer.invalidate_after(7, 0)
        self.assertFalse(observer.pending)
        for frame in range(1, 4): observer.record(7, frame, state(frame, branch='correct'))
        observer.promote(7, 3, dict(corrections=1, replayed_frames=3))
        self.assertEqual(self.rows(path)[-1]['parsed_state_sha256'], state_digest(state(3, branch='correct')))
        self.assertEqual([r['replayed_frames_delta'] for r in self.rows(path)], [0, 3, 0, 0])

    def test_published_history_cannot_be_replaced_or_invalidated(self):
        observer, path = self.observer(); observer.record(7, 0, state(0))
        observer.promote(7, 0, dict(corrections=0, replayed_frames=0)); before = path.read_bytes()
        for operation in (lambda: observer.invalidate_after(7, -1), lambda: observer.record(7, 0, state(0))):
            with self.assertRaises(ObservationError): operation()
        self.assertEqual(path.read_bytes(), before)

    def test_missing_candidate_and_row_budget_fail_before_any_promotion_write(self):
        observer, path = self.observer(max_rows=1)
        observer.record(7, 1, state(1))
        with self.assertRaisesRegex(ObservationError, 'missing candidate'):
            observer.promote(7, 1, dict(corrections=0, replayed_frames=0))
        observer.record(7, 0, state(0))
        with self.assertRaisesRegex(ObservationError, 'row budget'):
            observer.promote(7, 1, dict(corrections=0, replayed_frames=0))
        self.assertEqual((path.read_bytes(), observer.rows, observer.published), (b'', 0, -1))

    def test_pending_budget_and_conflicting_duplicate_are_strict(self):
        observer, _ = self.observer(max_pending=1)
        observer.record(7, 0, state(0))
        with self.assertRaisesRegex(ObservationError, 'pending-frame budget'): observer.prepare_frame(7, 1)
        with self.assertRaisesRegex(ObservationError, 'changed without checkpoint'):
            observer.record(7, 0, state(0, branch='different'))
        self.assertEqual(len(observer.pending), 1)

    def test_world_retirement_discards_tail_and_rematch_begins_new_prefix(self):
        observer, path = self.observer()
        observer.record(7, 0, state(0)); observer.record(7, 1, state(1))
        observer.promote(7, 0, dict(corrections=3, replayed_frames=8))
        observer.finish_world(7); self.assertFalse(observer.pending)
        observer.begin_world(8); observer.record(8, 0, state(0))
        observer.promote(8, 0, dict(corrections=0, replayed_frames=0))
        self.assertEqual([(r['world'], r['frame']) for r in self.rows(path)], [(7, 0), (8, 0)])

    def test_wrong_world_view_frame_and_missing_entities_are_rejected(self):
        observer, _ = self.observer()
        for world, frame, actual in ((8, 0, state(0)), (7, 0, state(1)),
                                    (7, 0, dict(state(0), viewer=0)), (7, 0, dict(frame=0, viewer=31))):
            with self.subTest(world=world, state=actual), self.assertRaises(ObservationError):
                observer.record(world, frame, actual)
        self.assertFalse(observer.pending)

    def test_foreign_thread_cannot_record_or_mutate_published_state(self):
        observer, path = self.observer(); errors = []
        def foreign():
            try: observer.record(7, 0, state(0))
            except Exception as error: errors.append(error)
        thread = threading.Thread(target=foreign); thread.start(); thread.join()
        self.assertEqual(len(errors), 1); self.assertIsInstance(errors[0], ObservationError)
        self.assertEqual(path.read_bytes(), b''); self.assertFalse(observer.pending)

    def test_existing_failure_file_is_never_overwritten(self):
        observer, path = self.observer()
        with self.assertRaises(FileExistsError): CanonicalStateObserver(path, tick=lambda: 0)
        self.assertFalse(observer.closed)


class PositionTraceTests(unittest.TestCase):
    def observer(self, *, spec=None, maximum=8192):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        canonical=Path(folder.name)/'canonical-state.jsonl'
        value=CanonicalStateObserver(canonical,tick=lambda:12345,position_trace=spec,
                                     max_position_records=maximum)
        self.addCleanup(value.close);value.begin_world(7)
        return value,canonical,canonical.with_name('native-positions.jsonl')

    @staticmethod
    def spec(first=0,last=10):return PositionTraceSpec(42,75,0,first,last)

    @staticmethod
    def context(frame, *, stage='ordinary', head=None, at=100, **extra):
        return dict(dict(stage=stage,head=frame-1 if head is None else head,confirmed=-1,received=-1,
            corrections=0,replayed_frames=0,query_begin_us=at,query_end_us=at+4),**extra)

    @staticmethod
    def actual(frame, *, entities=None, position=None):
        if entities is None:
            entities=[dict(id=42,army=0,type=75,position=position if position is not None else [1.5,-0.0,-2.25])]
        return dict(state(frame),entities=entities)

    @staticmethod
    def rows(path):return [json.loads(line)for line in path.read_text().splitlines()]

    def test_optional_trace_keeps_canonical_bytes_identical_and_disabled_has_no_child_file(self):
        plain,p1,absent=self.observer();watched,p2,trace=self.observer(spec=self.spec())
        for frame in range(3):
            actual=self.actual(frame)
            plain.record(7,frame,actual)
            watched.record(7,frame,actual,context=self.context(frame,at=100+frame*10))
        for value in (plain,watched):value.promote(7,1,dict(corrections=0,replayed_frames=0))
        self.assertEqual(p1.read_bytes(),p2.read_bytes());self.assertFalse(absent.exists())
        self.assertEqual(trace.read_bytes(),b'')
        watched.finish_world(7)
        self.assertEqual([row['frame']for row in self.rows(trace)],[0,1,2])
        self.assertEqual([row['frame']for row in self.rows(p2)],[0,1])  # No speculative promotion.

    def test_cached_same_head_before_restore_and_actual_replayed_head_are_distinct_copies(self):
        observer,_,path=self.observer(spec=self.spec())
        for frame in range(4):observer.record(7,frame,self.actual(frame,position=[float(frame),0.,0.]),context=self.context(frame,at=100+frame*10))
        observer.invalidate_after(7,0)
        self.assertEqual(set(observer.pending),{0});self.assertEqual(path.read_bytes(),b'')
        for frame in range(1,4):
            observer.record(7,frame,self.actual(frame,position=[-float(frame),0.,0.]),
                context=self.context(frame,stage='replay',head=3,at=200+frame*10,replayed_frames=frame-1))
        observer.finish_world(7);rows=self.rows(path)
        before=next(row for row in rows if row['event']=='before_restore_cached_head')
        after=next(row for row in rows if row['event']=='after_replay_same_head')
        self.assertEqual((before['frame'],before['cached_physical_head'],before['head']),(3,3,2))
        self.assertEqual((before['checkpoint_base'],before['first_divergent_frame'],before['revision'],before['query_revision']),(0,1,1,0))
        self.assertEqual(before['position'],[3.,0.,0.]);self.assertEqual(after['position'],[-3.,0.,0.])
        self.assertEqual((after['frame'],after['head'],after['revision'],after['first_divergent_frame']),(3,3,1,1))
        self.assertEqual(before['query_end_us'],134)  # Original query clock, not invented invalidation time.
        self.assertEqual(rows[before['cached_from_record']]['position'],[3.,0.,0.])

    def test_native_float32_bits_are_exact_and_source_vectors_are_copied(self):
        observer,_,path=self.observer(spec=self.spec());actual=self.actual(0)
        observer.record(7,0,actual,context=self.context(0));actual['entities'][0]['position'][0]=99.
        observer.close();row=self.rows(path)[0]
        self.assertEqual(row['position'],[1.5,-0.0,-2.25])
        self.assertEqual(row['position_bits'],list(struct.unpack('<III',struct.pack('<fff',1.5,-0.0,-2.25))))
        self.assertEqual(row['position_bits'][1],0x80000000)
        self.assertEqual(row['clock_source'],'python.perf_counter_ns//1000')
        self.assertEqual(row['query_scope'],'existing-native-make-get-and-decode')

    def test_absent_partial_and_wrong_native_identity_never_create_zero_or_rebound_position(self):
        observer,_,path=self.observer(spec=self.spec())
        entities=[[],[dict(id=42,army=0,type=75)],
                  [dict(id=42,army=1,type=76,position=[1.,2.,3.])]]
        for frame,rows in enumerate(entities):observer.record(7,frame,self.actual(frame,entities=rows),context=self.context(frame,at=100+frame*10))
        observer.finish_world(7);rows=self.rows(path)
        self.assertEqual([row['status']for row in rows],['absent','partial','identity_mismatch'])
        self.assertTrue(all(row['position']is None and row['position_bits']is None for row in rows))
        self.assertTrue(all(row['watched_identity']==dict(id=42,type=75,army=0)for row in rows))
        self.assertEqual(rows[-1]['observed_identity'],dict(id=42,army=1,type=76))

    def test_ambiguous_nonfinite_or_non_float32_position_refuses_before_candidate_mutation(self):
        bad=[self.actual(0,entities=[dict(id=42),dict(id=42)]),self.actual(0,position=[float('nan'),0.,0.]),
             self.actual(0,position=[float('inf'),0.,0.]),self.actual(0,position=[1e300,0.,0.]),
             self.actual(0,position=[.1,0.,0.])]
        for actual in bad:
            observer,_,path=self.observer(spec=self.spec())
            with self.subTest(actual=actual),self.assertRaises(ObservationError):
                observer.record(7,0,actual,context=self.context(0))
            self.assertFalse(observer.pending);self.assertEqual(path.read_bytes(),b'')

    def test_context_clocks_stage_frame_and_metrics_are_required_and_monotone(self):
        bad=[None,dict(stage='ordinary'),self.context(0,head=0),self.context(0,stage='unknown'),
             self.context(0,stage='replay',head=3),self.context(0,query_begin_us=True),
             self.context(0,query_end_us=99),self.context(0,confirmed=2,received=1)]
        for context in bad:
            observer,_,_=self.observer(spec=self.spec())
            with self.subTest(context=context),self.assertRaises(ObservationError):observer.record(7,0,self.actual(0),context=context)
            self.assertFalse(observer.pending)
        observer,_,_=self.observer(spec=self.spec());observer.record(7,0,self.actual(0),context=self.context(0,corrections=2,replayed_frames=4))
        for context in (self.context(1,at=103,corrections=2,replayed_frames=4),self.context(1,at=120,corrections=1,replayed_frames=4)):
            with self.assertRaisesRegex(ObservationError,'regressed'):observer.record(7,1,self.actual(1),context=context)
        observer.invalidate_after(7,0)
        with self.assertRaisesRegex(ObservationError,'actual decoded frame'):
            observer.record(7,0,self.actual(0),context=self.context(0,stage='replay',head=2,at=130,corrections=2,replayed_frames=4))

    def test_outside_window_or_incomplete_replay_cache_cannot_be_claimed_as_same_head(self):
        observer,_,path=self.observer(spec=self.spec(1,2))
        self.assertFalse(observer.position_active(7,0));self.assertTrue(observer.position_active(7,1))
        observer.record(7,0,self.actual(0));observer.invalidate_after(7,-1)
        observer.record(7,1,self.actual(1),context=self.context(1,stage='replay',head=2))
        observer.invalidate_after(7,0)
        observer.record(7,1,self.actual(1),context=self.context(1,stage='replay',head=2,at=120))
        observer.record(7,2,self.actual(2),context=self.context(2,stage='replay',head=2,at=140))
        observer.record(7,3,self.actual(3));observer.invalidate_after(7,2);observer.finish_world(7)
        rows=self.rows(path);before=[row for row in rows if row['event']=='before_restore_cached_head']
        self.assertEqual([row['status']for row in before],['outside_window','cached_frame_not_head','outside_window'])
        self.assertTrue(all(row['cached_physical_head']is None for row in before))
        self.assertFalse(any(row['event']=='after_replay_same_head'for row in rows))

    def test_budget_refusal_precedes_invalidation_and_rematch_has_distinct_world_revision(self):
        observer,_,path=self.observer(spec=self.spec(),maximum=2)
        for frame in range(2):observer.record(7,frame,self.actual(frame),context=self.context(frame,at=100+10*frame))
        before=dict(observer.pending)
        with self.assertRaisesRegex(ObservationError,'budget'):observer.invalidate_after(7,0)
        self.assertEqual(observer.pending,before);self.assertEqual(path.read_bytes(),b'')
        observer.finish_world(7);observer.begin_world(8)
        with self.assertRaisesRegex(ObservationError,'budget'):observer.record(8,0,self.actual(0),context=self.context(0,at=200))
        observer2,_,path2=self.observer(spec=self.spec())
        observer2.record(7,0,self.actual(0),context=self.context(0));observer2.finish_world(7);observer2.begin_world(8)
        observer2.record(8,0,self.actual(0),context=self.context(0,at=200));observer2.finish_world(8)
        self.assertEqual([(r['world'],r['revision'])for r in self.rows(path2)],[(7,0),(8,0)])

    def test_owner_world_file_and_lifecycle_fail_closed(self):
        observer,_,path=self.observer(spec=self.spec());errors=[]
        def foreign():
            try:observer.invalidate_after(7,0)
            except Exception as error:errors.append(error)
        thread=threading.Thread(target=foreign);thread.start();thread.join()
        self.assertIsInstance(errors[0],ObservationError);self.assertEqual(path.read_bytes(),b'')
        with self.assertRaises(ObservationError):observer.record(8,0,self.actual(0),context=self.context(0))
        with self.assertRaises(ObservationError):observer.begin_world(8)
        observer.finish_world(7);observer.begin_world(8)
        observer.record(8,0,self.actual(0),context=self.context(0));observer.finish_world(8)
        with self.assertRaises(FileExistsError):
            CanonicalStateObserver(path.with_name('other-canonical.jsonl'),tick=lambda:0,position_trace=self.spec())

    def test_spec_requires_explicit_native_identity_and_bounded_frame_window(self):
        for values in ((42,0,0,0,1),(True,75,0,0,1),(42,75,-1,0,1),(42,75,0,2,1),
                       (42,75,0,0,4096),(42,75,0,0,True)):
            with self.subTest(values=values),self.assertRaises(ObservationError):PositionTraceSpec(*values)
        with self.assertRaises(TypeError):PositionTraceSpec(42,75,0)
        self.assertEqual(PositionTraceSpec(0,1,0,0,4095).last_frame,4095)

    def test_new_world_keeps_real_query_clock_monotone_and_failed_record_atomic(self):
        observer,_,path=self.observer(spec=self.spec())
        observer.record(7,0,self.actual(0),context=self.context(0,at=500));observer.finish_world(7);observer.begin_world(8)
        with self.assertRaisesRegex(ObservationError,'regressed'):
            observer.record(8,0,self.actual(0),context=self.context(0,at=100))
        self.assertFalse(observer.pending)
        observer.record(8,0,self.actual(0),context=self.context(0,at=600));observer.finish_world(8)
        self.assertEqual([row['query_begin_us']for row in self.rows(path)],[500,600])

    def test_failed_flush_is_preserved_without_retry_and_all_streams_close(self):
        observer,_,_=self.observer(spec=self.spec())
        observer.record(7,0,self.actual(0),context=self.context(0))
        observer._positions.stream.close()
        class Broken:
            writes=0;closed=False
            def write(self,data):self.writes+=1;raise OSError('authored disk failure')
            def flush(self):raise AssertionError('failed write must not flush/retry')
            def close(self):self.closed=True
        broken=Broken();observer._positions.stream=broken
        with self.assertRaisesRegex(OSError,'disk failure'):observer.finish_world(7)
        with self.assertRaisesRegex(ObservationError,'closed/failed'):observer.record(7,11,self.actual(11))
        observer.close()
        self.assertEqual(broken.writes,1);self.assertTrue(broken.closed)
        self.assertTrue(observer.closed and observer.stream.closed and observer._positions.closed)

    def test_disabled_trace_never_consumes_position_context_or_creates_position_output(self):
        observer,_,path=self.observer()
        class Unreadable(dict):
            def __iter__(self):raise AssertionError('disabled trace consulted context')
            def __getitem__(self,key):raise AssertionError('disabled trace consulted context')
        observer.record(7,0,self.actual(0),context=Unreadable())
        observer.invalidate_after(7,-1);observer.finish_world(7);observer.close()
        self.assertFalse(path.exists())


class NativeBoundaryTests(unittest.TestCase):
    def setup_worker(self, *, observe=True, ledger=True):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'canonical-state.jsonl'
        class Raw(NativeFixture):
            def call(self, name, *args):
                previous = self.remote
                result = super().call(name, *args)
                # The shared fixture treats ANY remote action as its authored
                # state-change marker. Both real startup joins must not already
                # apply the later remote-Move branch we are testing here.
                if name == 'SimProcessMsg' and self.next_frame == 0:
                    self.remote = previous
                return result
        self.raw = Raw(); self.heap = SnapshotHeap(self.raw)
        self.session = NativeSession(self.raw, arena=self.heap)
        self.addCleanup(self.session.close)
        if observe:
            with patch('client_patch.prediction_worker.observation.windows_tick', return_value=lambda: 900):
                self.session.enable_movement_observation(self.path)
        self.session.dispatch(command(1, b'\0'))
        _, raw = self.session.dispatch(command(5, b'authored'))
        self.key, = struct.unpack('<Q', raw)
        self.dispatch(64, struct.pack('<II', 12, 1024*1024))
        if ledger: self.dispatch(67, struct.pack('<Q', 1) + body([join()]))

    def dispatch(self, opcode, tail=b''):
        return self.session.dispatch(command(opcode, struct.pack('<Q', self.key) + tail))

    def authority(self, frame, remote=()):
        own = [join(deck=b'server-frozen')] if frame == 0 else []
        other = [join(1)] if frame == 0 else remote
        self.dispatch(65, encode_frame(frame, {0: body(own), 1: body(other, slot=1)}))

    def process(self, frame): self.dispatch(7, encode_frame(frame, {0: b'', 1: b''}))
    def step(self): self.dispatch(8, struct.pack('<Ii', 50, -1))
    def query(self): self.dispatch(9, struct.pack('<II', 0, 0))
    def advance(self, frame): self.process(frame); self.step(); self.query()
    def rows(self): return [json.loads(line) for line in self.path.read_text().splitlines()]

    def test_default_and_explicit_no_ledger_paths_add_no_native_query(self):
        for enabled, ledger in ((False, True), (True, False)):
            with self.subTest(enabled=enabled, ledger=ledger):
                self.setup_worker(observe=enabled, ledger=ledger)
                self.authority(0); self.advance(0)
                self.assertEqual(self.raw.queries, [(0, 0)])
                if enabled: self.assertEqual(self.path.read_bytes(), b'')
                self.session.close()

    def test_ordinary_capture_is_after_guard_finish_before_later_checkpoint(self):
        self.setup_worker(); self.authority(0)
        events = []
        class Guard:
            def begin(self, raw): events.append('begin')
            def finish(self): events.append('finish')
            def snapshot(self): return (0,) * 12
            def continuity(self, first, last): return True
            def invalidate_after(self, frame): events.append('invalidate')
            def close(self): pass
        self.session.entity_guards[self.key] = Guard()
        call, capture = self.raw.call, self.heap.capture
        def recorded(name, *args):
            if name == 'SimMakeSimFrame': events.append(('view', args[1]))
            return call(name, *args)
        def checkpoint(): events.append(('capture', self.raw.physical)); return capture()
        self.raw.call, self.heap.capture = recorded, checkpoint
        self.advance(0); self.process(1)
        self.assertLess(events.index('finish'), events.index(('view', 31)))
        self.assertLess(events.index(('view', 31)), events.index(('capture', 0)))
        self.assertEqual([r['frame'] for r in self.rows()], [0])

    def test_late_byte_matched_authority_promotes_cached_head_without_query(self):
        self.setup_worker(); self.authority(0); self.advance(0); self.advance(1)
        before = list(self.raw.queries)
        self.authority(1); self.process(2)
        self.assertEqual(self.raw.queries, before)
        self.assertEqual([r['frame'] for r in self.rows()], [0, 1])
        self.assertEqual(self.rows()[-1]['replayed_frames_total'], 0)

    def test_every_replayed_step_replaces_invalidated_candidates_before_capture(self):
        self.setup_worker(); self.authority(0); self.advance(0)
        for frame in (1, 2, 3): self.advance(frame)
        observer = self.session.movement_observer
        old = dict(observer.pending); before = len(self.raw.queries)
        restore = self.heap.restore
        def checked_restore(token):
            self.assertFalse(observer.pending)  # CP0 invalidated BEFORE arena mutation.
            restore(token)
        self.heap.restore = checked_restore
        self.authority(1, remote=[MOVE]); self.process(4)
        self.assertEqual(self.raw.queries[before:], [(1, 31), (1, 0), (2, 31), (3, 31)])
        self.assertNotEqual(observer.pending[2], old[2]); self.assertNotEqual(observer.pending[3], old[3])
        self.assertEqual([r['frame'] for r in self.rows()], [0, 1])
        self.assertEqual(self.rows()[-1]['replayed_frames_delta'], 3)
        self.assertEqual(self.rows()[-1]['corrections'], 1)
        self.step()

    def test_65_67_metrics_end_and_checkpoint_capture_add_no_view_queries(self):
        self.setup_worker(); self.authority(0); self.advance(0)
        before = list(self.raw.queries), len(self.raw.calls)
        self.dispatch(67, struct.pack('<Q', 2) + body([]))
        self.authority(1); self.dispatch(66); self.dispatch(68); self.dispatch(70)
        adapter = self.session.prediction_adapters[self.key]
        token = adapter.capture(0); adapter.drop(token)
        self.dispatch(69, struct.pack('<i', 1))
        self.assertEqual((self.raw.queries, len(self.raw.calls)), before)

    def test_pending_budget_is_checked_before_the_extra_native_pair(self):
        self.setup_worker(); self.authority(0); self.advance(0); self.advance(1)
        self.session.movement_observer.max_pending = 1
        self.process(2); before = len(self.raw.queries)
        with self.assertRaisesRegex(ObservationError, 'pending-frame budget'): self.step()
        self.assertEqual(len(self.raw.queries), before)

    def test_checkpoint_older_than_published_state_refuses_before_arena_restore(self):
        self.setup_worker(); self.authority(0); self.advance(0)
        self.authority(1); self.advance(1)
        adapter = self.session.prediction_adapters[self.key]
        old = next(token for token, (_, frame) in adapter.tokens.items() if frame == 0)
        before = list(self.heap.events), self.path.read_bytes()
        # Existing identity guards independently reject this stale base too.
        # Isolate the new observer's own pre-mutation refusal here.
        with patch.dict(self.session.identity_histories, {}, clear=True), \
                patch.dict(self.session.active_identity_histories, {}, clear=True), \
                self.assertRaisesRegex(ObservationError, 'cannot invalidate published'):
            adapter.restore(old)
        self.assertEqual((self.heap.events, self.path.read_bytes()), before)

    def test_observer_bypasses_copied_terminal_mask_and_uses_full31_decoder(self):
        self.setup_worker(); self.authority(0)
        with patch('client_patch.prediction_worker.presentation.confirmed_terminal_view',
                   side_effect=AssertionError('observer must not mask/copy terminal state')), \
                patch('server.native_simulation.decode_snapshot', wraps=decode_snapshot) as decode:
            self.process(0); self.step()
        decode.assert_called_once()
        self.assertEqual(decode.call_args.args[1], 31)
        self.assertEqual(decode.call_args.kwargs, dict(include_entities=True))
        self.assertEqual(self.rows()[0]['parsed_state_sha256'], state_digest(decode_snapshot(decode.call_args.args[0], 31, include_entities=True)))

    def test_retirement_discards_unconfirmed_tail_and_closes_writer(self):
        self.setup_worker(); self.authority(0); self.advance(0); self.advance(1)
        observer = self.session.movement_observer
        self.assertEqual(set(observer.pending), {1})
        self.dispatch(6)
        self.assertFalse(observer.pending); self.assertIsNone(observer.world)
        self.assertEqual([r['frame'] for r in self.rows()], [0])
        self.session.close(); self.assertTrue(observer.closed)


class CliTests(unittest.TestCase):
    def test_enable_is_after_open_before_streams_and_absent_by_default(self):
        from client_patch.prediction_worker import __main__ as main
        for enabled in (False, True):
            events = []
            class Session:
                def enable_movement_observation(self, path): events.append(('enable', path))
                def close(self): events.append('close')
            session = Session()
            def opened(**kwargs): events.append('open'); return session
            def streams(source, sink, backend): events.append('streams'); return 0
            args = ['--original-dll', 'original', '--heap-helper', 'heap', '--cooperative', 'coop', '--data-dir', '.']
            if enabled: args.append('--movement-observe')
            with patch.object(main.NativeSession, 'open', side_effect=opened), \
                    patch.object(main, 'run_streams', side_effect=streams), \
                    patch('server.simulation_worker.isolate_protocol_stdout', return_value=io.BytesIO()):
                self.assertEqual(main.main(args), 0)
            self.assertEqual([e[0] if isinstance(e, tuple) else e for e in events],
                             ['open', 'enable', 'streams'] if enabled else ['open', 'streams'])
            if enabled: self.assertTrue(events[1][1].is_absolute())

    def test_observer_startup_refusal_closes_the_already_open_native_owner(self):
        from client_patch.prediction_worker import __main__ as main
        events = []
        class Session:
            def enable_movement_observation(self, path):
                events.append('enable'); raise FileExistsError('preserved diagnostic file')
            def close(self): events.append('close')
        args = ['--original-dll', 'original', '--heap-helper', 'heap', '--cooperative', 'coop',
                '--data-dir', '.', '--movement-observe']
        with patch.object(main.NativeSession, 'open', return_value=Session()), \
                patch.object(main, 'run_streams') as streams, \
                patch('server.simulation_worker.isolate_protocol_stdout', return_value=io.BytesIO()), \
                patch.object(main.sys, 'stderr', io.StringIO()):
            self.assertEqual(main.main(args), 1)
        streams.assert_not_called()
        self.assertEqual(events, ['enable', 'close'])


if __name__ == '__main__':
    unittest.main()
