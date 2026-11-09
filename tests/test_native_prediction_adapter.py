"""Injected ABI tests for root validation before native snapshot mutation."""
import ctypes as C
import unittest

from client_patch.prediction_worker.checkpoint import CheckpointAdapter
from client_patch.prediction_worker.native import Arena, HostError


class RootTests(unittest.TestCase):
    def subject(self):
        arena = Arena.__new__(Arena)
        arena._bindings = (7, 0, 1, 2, 100, 200, 300)
        arena._bindings_revision, arena._bindings_changed = 0, False
        arena.value, arena.reads = arena._bindings, 0
        def read():
            arena.reads += 1
            if isinstance(arena.value, Exception):
                raise arena.value
            return arena.value
        arena._read_bindings = read
        return arena

    def test_same_roots_produce_immutable_binding_token(self):
        arena = self.subject()
        self.assertEqual(arena.root_bindings(), (7, 0, 1, 2, 100, 200, 300, 0))

    def test_observed_root_change_cannot_recover_through_ABA(self):
        arena = self.subject()
        original = arena.value
        arena.value = original[:-1] + (301,)
        with self.assertRaises(HostError):arena.root_bindings()
        arena.value = original
        with self.assertRaises(HostError):arena.root_bindings()
        self.assertEqual((arena._bindings_revision, arena.reads), (1, 1))

    def test_unreadable_binding_is_also_sticky(self):
        arena = self.subject()
        arena.value = HostError('root is null')
        with self.assertRaisesRegex(HostError, 'root is null'):arena.root_bindings()
        arena.value = arena._bindings
        with self.assertRaisesRegex(HostError, 'checkpoints invalid'):arena.root_bindings()
        self.assertEqual(arena.reads, 1)


class Heap:
    def __init__(self):
        self.binding, self.next, self.events, self.change_on_capture = (1, 2, 3), 1, [], False
    def root_bindings(self):
        if isinstance(self.binding, Exception):raise self.binding
        return self.binding
    def healthy(self):return {}
    def forget_baseline(self):self.events.append(('forget',0))
    def capture(self):
        token = self.next;self.next += 1
        self.events.append(('capture', token))
        if self.change_on_capture:self.binding = HostError('changed root')
        return token
    def restore(self, token):self.events.append(('restore', token))
    def drop(self, token):self.events.append(('drop', token))


class Session:
    def __init__(self):self.arena, self.calls, self.failure = Heap(), [], None
    def _world(self, key):
        if key != 1:raise HostError('stale world')
        return 0x12340000
    def healthy(self):pass
    def _call(self, name, *args):
        self.calls.append((name, args))
        if name == 'SimProcessMsg':
            self.last_raw = C.string_at(args[1], args[2])
        return 1 if name == self.failure else 0


class AdapterTests(unittest.TestCase):
    def test_changed_binding_rejects_before_native_restore(self):
        session = Session();adapter = CheckpointAdapter(session, 1)
        token = adapter.capture(10)
        session.arena.binding = (1, 2, 4)
        with self.assertRaisesRegex(HostError, 'differs'):adapter.restore(token)
        self.assertNotIn(('restore', token), session.arena.events)
        adapter.close()
        self.assertEqual(session.arena.events[-1], ('drop', token))

    def test_capture_failure_releases_new_snapshot(self):
        session = Session();adapter = CheckpointAdapter(session, 1)
        session.arena.change_on_capture = True
        with self.assertRaisesRegex(HostError, 'changed root'):adapter.capture(10)
        self.assertEqual(session.arena.events, [('capture', 1), ('drop', 1)])
        self.assertFalse(adapter.tokens)

    def test_exact_native_replay_has_no_presentation_queries(self):
        session = Session();adapter = CheckpointAdapter(session, 1)
        adapter.process_frame(b'original InputActions', 50)
        self.assertEqual(session.last_raw, b'original InputActions')
        self.assertEqual([name for name, _ in session.calls], ['SimProcessMsg', 'SimStep'])
        self.assertEqual(session.calls[-1][1][:2], (0x12340000, 50))
        session.failure = 'SimProcessMsg';session.calls.clear()
        with self.assertRaises(HostError):adapter.process_frame(b'rejected', 50)
        self.assertEqual([name for name, _ in session.calls], ['SimProcessMsg'])

    def test_unknown_or_retired_tokens_never_reach_native_helper(self):
        session = Session();adapter = CheckpointAdapter(session, 1)
        token = adapter.capture(0);adapter.drop(token)
        for method in (adapter.restore, adapter.drop):
            with self.assertRaises(HostError):method(token)
        self.assertEqual(session.arena.events, [('capture', 1), ('drop', 1)])


class WorkerBoundaryTests(unittest.TestCase):
    def setup_worker(self):
        from tests.test_prediction_worker import world_session, command
        from client_patch.prediction_worker import wire as w
        import struct
        raw, session, key = world_session(arena=Heap())
        session.dispatch(command(w.Op.PREDICTION_BEGIN, struct.pack('<QII', key, 6, 1024*1024)))
        self.addCleanup(session.close)
        return raw, session, key

    def test_authority_enqueues_without_native_calls_and_replays_at_next_frame(self):
        from tests.test_prediction_worker import command
        from tests.test_native_prediction_reconciler import frame, move
        from client_patch.prediction_worker import wire as w
        import struct
        raw, session, key = self.setup_worker()
        def advance(body):
            session.dispatch(command(w.Op.PROCESS_MSG, struct.pack('<Q',key)+body))
            session.dispatch(command(w.Op.STEP, struct.pack('<QIi',key,50,-1)))
        for number in range(4):advance(frame(number))
        calls, events = len(raw.calls), list(session.arena.events)
        for number in range(4):
            authority = frame(number, remote=(move(2,99),)) if number == 2 else frame(number)
            session.dispatch(command(w.Op.PREDICTION_AUTHORITY,struct.pack('<Q',key)+authority))
        self.assertEqual(len(raw.calls),calls)
        self.assertEqual(session.arena.events,events)
        advance(frame(4))
        stats = session.predictions[key].metrics
        self.assertEqual((stats['restores'],stats['replayed_frames'],stats['confirmed_frame'],stats['predicted_frame']),
                         (1,2,3,4))
        self.assertTrue(any(name == 'restore' for name,_ in session.arena.events))
        code,data = session.dispatch(command(w.Op.PREDICTION_METRICS,struct.pack('<Q',key)))
        self.assertEqual((code,len(data),struct.unpack_from('<iiiI',data)),(0,80,(3,4,3,0)))
        session.close()
        self.assertFalse(session.predictions)
        self.assertFalse(session.prediction_adapters)

    def test_begin_is_forbidden_after_any_native_message(self):
        from tests.test_prediction_worker import world_session, command
        from client_patch.prediction_worker import wire as w
        import struct
        raw, session, key = world_session(arena=Heap());self.addCleanup(session.close)
        session.dispatch(command(w.Op.PROCESS_MSG,struct.pack('<Q',key)+b'original message'))
        before = len(raw.calls)
        with self.assertRaisesRegex(HostError, 'before first native frame'):
            session.dispatch(command(w.Op.PREDICTION_BEGIN,struct.pack('<QII',key,6,1024*1024)))
        self.assertEqual(len(raw.calls),before)


if __name__ == '__main__':unittest.main()
