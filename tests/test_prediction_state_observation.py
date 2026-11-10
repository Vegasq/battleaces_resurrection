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

from client_patch.prediction_worker.observation import CanonicalStateObserver, ObservationError, state_digest
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
