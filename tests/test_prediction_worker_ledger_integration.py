"""Authored worker/ABI coordination only; no original native DLL is loaded."""
import ctypes as C
import struct
import unittest

from client_patch.prediction_worker import wire as w
from client_patch.prediction_worker.commands import CommandLedger, CommandLedgerError
from client_patch.prediction_worker.native import NativeSession
from server.game_data import encode_frame
from server.protobuf_wire import get_repeated_bytes, get_uint
from tests.test_native_prediction_adapter import Heap
from tests.test_prediction_command_ledger import body, join, execute, group, MOVE, BUILD
from tests.test_prediction_worker import Raw, command


def view(frame, rows, viewer=0):
    data = bytearray(128)
    struct.pack_into('<I', data, 0, 32)
    struct.pack_into('<HHHHHH', data, 8, 12, 20, 4, 8, 12, 16)
    struct.pack_into('<iIIII', data, 32, 24, frame, viewer, 28, 40)
    struct.pack_into('<HHHH', data, 56, 8, 12, 4, 8)
    struct.pack_into('<HHHH', data, 64, 8, 12, 4, 8)
    struct.pack_into('<i', data, 72, 16)
    struct.pack_into('<i', data, 88, 24)
    for table, component in ((72, 0), (88, 1)):
        offsets = []
        for values in (list(rows), [value[component] for value in rows.values()]):
            offsets.append(len(data))
            data.extend(struct.pack('<I', len(values)))
            for value in values:
                data.extend(struct.pack('<I', value))
        struct.pack_into('<II', data, table + 4, offsets[0] - table - 4, offsets[1] - table - 8)
    return bytes(data)


class NativeFixture(Raw):
    def __init__(self):
        super().__init__()
        self.physical, self.next_frame, self.remote, self.view_alliance = -1, -1, False, None
        self.inputs, self.queries = [], []
        self.rows = lambda: {0: (0, 3), 42: (0, 75), 77:(1,75), **({79: (1 if self.remote else 0, 75)} if self.physical >= 1 else {})}

    def call(self, name, *args):
        if name == 'SimProcessMsg':
            raw = C.string_at(args[1], args[2])
            self.inputs.append(raw)
            self.next_frame = get_uint(raw, 1)
            # An authored remote action changes the identity at the same ID.
            from client_patch.prediction_worker.commands import player_slot
            for player in get_repeated_bytes(raw, 6):
                if player_slot(player) == 1 and get_repeated_bytes(player, 2):
                    self.remote = True
        if name == 'SimStep':
            self.physical = self.next_frame
        if name == 'SimMakeSimFrame':
            self.queries.append((self.physical, args[1]))
            self.frame = view(max(0, self.physical), self.rows(), args[1] if self.view_alliance is None else self.view_alliance)
        return super().call(name, *args)


class SnapshotHeap(Heap):
    def __init__(self, raw):
        super().__init__(); self.raw, self.states = raw, {}
    def capture(self):
        token = super().capture()
        self.states[token] = self.raw.physical, self.raw.next_frame, self.raw.remote
        return token
    def restore(self, token):
        super().restore(token)
        self.raw.physical, self.raw.next_frame, self.raw.remote = self.states[token]
    def drop(self, token):
        super().drop(token); self.states.pop(token)


class IntegrationTests(unittest.TestCase):
    def setup_worker(self, slot=0):
        raw = NativeFixture(); heap = SnapshotHeap(raw)
        session = NativeSession(raw, arena=heap)
        session.dispatch(command(1, b'\0'))
        _, data = session.dispatch(command(5, b'authored-game'))
        key, = struct.unpack('<Q', data)
        session.dispatch(command(64, struct.pack('<QII', key, 12, 1024*1024)))
        self.addCleanup(session.close)
        self.raw, self.s, self.key, self.slot = raw, session, key, slot

    def dispatch(self, opcode, payload=b''):
        return self.s.dispatch(command(opcode, payload))

    def batch(self, sequence, actions, slot=None):
        return self.dispatch(67, struct.pack('<QQ', self.key, sequence) + body(actions, slot=self.slot if slot is None else slot))

    def authority(self, number, own=(), remote=()):
        values = {self.slot: body(own, slot=self.slot), 1-self.slot: body(remote, slot=1-self.slot)}
        return self.dispatch(65, struct.pack('<Q', self.key) + encode_frame(number, values))

    def process(self, number):
        return self.dispatch(7, struct.pack('<Q', self.key) + encode_frame(number, {0:b'', 1:b''}))

    def step(self):
        return self.dispatch(8, struct.pack('<QIi', self.key, 50, -1))

    def query(self, viewer=None):
        return self.dispatch(9, struct.pack('<QII', self.key, self.slot if viewer is None else viewer, 0))

    def ready(self):
        self.setup_worker()
        self.batch(1, [join()])
        self.authority(0, [join(deck=b'server-frozen')], [join(1)])
        self.process(0); self.step(); self.query()

    def test_private_codecs_and_startup_inflight_assignment_are_pure(self):
        self.setup_worker()
        before = len(self.raw.calls), tuple(self.s.arena.events)
        self.assertEqual(self.batch(1, [join()]), (0, struct.pack('<Qi', 1, 0)))
        self.assertEqual((len(self.raw.calls), tuple(self.s.arena.events)), before)
        self.assertEqual(self.dispatch(68, struct.pack('<Q',self.key)), (0, struct.pack('<iI',-1,0)))
        self.authority(0, [join(deck=b'server')], [join(1)])
        self.process(0)  # Frame0 already in native ProcessMsg, Step not yet done.
        self.assertEqual(self.batch(2, []), (0, struct.pack('<Qi',2,1)))
        self.step(); self.query()
        self.process(1)
        self.assertEqual(self.batch(3, [MOVE]), (0, struct.pack('<Qi',3,2)))
        self.step()
        self.assertFalse(get_repeated_bytes(self.raw.inputs[-1],6))
        self.process(2); self.step()
        self.assertEqual(get_repeated_bytes(get_repeated_bytes(self.raw.inputs[-1],6)[0],2),(MOVE,))

    def test_startup_required_before_authority_and_slot_is_immutable(self):
        self.setup_worker()
        self.authority(0)  # Foundation path remains legal without any ledger.
        with self.assertRaises(ValueError): self.batch(1,[join()])
        self.assertFalse(self.s.command_ledgers)
        self.setup_worker(slot=1)
        self.batch(1,[join(1)])
        self.assertEqual(self.s.command_ledgers[self.key].slot,1)
        before = self.s.command_ledgers[self.key].metrics
        with self.assertRaises(ValueError): self.batch(2,[],slot=0)
        self.assertEqual(self.s.command_ledgers[self.key].metrics,before)

    def test_confirmed_entity_admission_rejects_unknown_wrong_army_type_atomically(self):
        self.ready()
        self.process(1); self.step(); self.query()
        ledger = self.s.command_ledgers[self.key]
        for action in (execute(group(ids=(79,))), execute(group(ids=(12345,))),
                       execute(group(ids=(77,))), execute(group(ids=(0,))), execute(group(ids=(42,)) + b'\x08\x4c')):
            before = ledger.metrics, ledger.pending, len(self.raw.calls)
            with self.subTest(action=action), self.assertRaises(ValueError): self.batch(2,[action])
            self.assertEqual((ledger.metrics,ledger.pending,len(self.raw.calls)),before)
        self.assertEqual(self.batch(2,[MOVE,BUILD])[0],0)

    def test_authority_stages_ledger_and_reconciler_atomically_rejects_duplicates(self):
        self.ready(); self.batch(2,[MOVE])
        ledger = self.s.command_ledgers[self.key]
        before = ledger.pending, ledger.metrics, self.s.predictions[self.key].received_frame
        invalid = encode_frame(1,{0:body([BUILD]),1:b''})
        duplicate = encode_frame(1,{0:body([MOVE]),1:body([MOVE])})
        for raw in (invalid, duplicate):
            with self.assertRaises(ValueError): self.dispatch(65,struct.pack('<Q',self.key)+raw)
            self.assertEqual((ledger.pending,ledger.metrics,self.s.predictions[self.key].received_frame),before)
        self.s.predictions[self.key].max_journal_bytes=1
        with self.assertRaises(Exception): self.authority(1,[MOVE])
        self.assertIs(self.s.command_ledgers[self.key],ledger)
        self.assertEqual((ledger.pending,ledger.metrics),before[:2])

    def test_replay_refreshes_only_latest_received_identity_view_before_promotion(self):
        self.ready()
        for number in (1,2,3): self.process(number); self.step(); self.query()
        history = self.s.identity_histories[self.key]
        active = self.s.active_identity_histories[self.key]
        self.assertIsNone(history.lookup(79))
        self.assertNotIn(79,active.active)
        queries = len(self.raw.queries)
        events = tuple(self.s.arena.events); native=len(self.raw.calls)
        self.authority(1,remote=[MOVE])
        self.assertEqual((tuple(self.s.arena.events),len(self.raw.calls)),(events,native))
        self.process(4)
        self.assertEqual(self.raw.queries[queries:],[(1,0)])
        self.assertEqual((history.promoted_frame,history.lookup(79)),(1,(1,75)))
        self.assertNotIn(2,history.views);self.assertNotIn(3,history.views)
        self.assertEqual(active.active[79][:2],(1,75))
        self.assertNotIn(2,active.views);self.assertNotIn(3,active.views)
        with self.assertRaises(ValueError): self.batch(2,[execute(group(ids=(79,)))])
        self.step()

    def test_terminal_finish_cancels_pending_and_end_is_pure_strict(self):
        self.ready(); self.batch(2,[MOVE,BUILD])
        before=len(self.raw.calls),tuple(self.s.arena.events)
        with self.assertRaises(ValueError): self.dispatch(69,struct.pack('<Qi',self.key,1))
        self.assertEqual(self.dispatch(69,struct.pack('<Qi',self.key,0)),(0,struct.pack('<I',2)))
        self.assertEqual((len(self.raw.calls),tuple(self.s.arena.events)),before)
        for call in (lambda:self.batch(3,[]),lambda:self.authority(1),
                     lambda:self.dispatch(69,struct.pack('<Qi',self.key,0))):
            with self.assertRaises(ValueError):call()
        self.process(1);self.step()
        self.assertFalse(get_repeated_bytes(self.raw.inputs[-1],6))

    def test_early_server_commit_removes_own_order_from_later_physical_guess(self):
        self.ready(); self.process(1)
        self.assertEqual(self.batch(2,[MOVE]),(0,struct.pack('<Qi',2,2)))
        self.step();self.process(2);self.step()
        # Server placed this whole batch in1; prediction had already used it
        # in2. Reconciliation must put it in1 and remove it from physical2.
        count=len(self.raw.inputs)
        self.authority(1,[MOVE]); self.process(3)
        recent=self.raw.inputs[count:]
        self.assertEqual([get_uint(raw,1) for raw in recent],[1,2,3])
        def actions(raw):
            return tuple(action for player in get_repeated_bytes(raw,6) for action in get_repeated_bytes(player,2))
        self.assertEqual([actions(raw) for raw in recent],[(MOVE,),(),()])
        self.assertFalse(self.s.command_ledgers[self.key].pending)
        self.assertEqual(self.s.predictions[self.key].metrics['revised_frames'],1)
        self.step()

    def test_dead_confirmed_entities_remain_admissible_and_build_not_predicted(self):
        self.ready()
        self.raw.rows=lambda:{0:(0,3)}
        self.authority(1);self.process(1);self.step();self.query()
        self.assertEqual(self.s.identity_histories[self.key].lookup(42),(0,75))
        self.batch(2,[BUILD])
        self.process(2);self.step()
        self.assertFalse(get_repeated_bytes(self.raw.inputs[-1],6))
        self.assertEqual(len(self.s.command_ledgers[self.key].pending),1)

    def test_only_consistent_own_view_promotes_entity_admission(self):
        self.setup_worker();self.batch(1,[join()]);self.authority(0,[join()],[join(1)])
        self.process(0);self.step()
        self.query(31);self.query(1)
        history=self.s.identity_histories[self.key]
        self.assertEqual((history.promoted_frame,history.known),(-1,{}))
        self.raw.view_alliance=1
        with self.assertRaisesRegex(RuntimeError,'alliance'):self.query(0)
        self.assertFalse(history.known)
        self.raw.view_alliance=None;self.query(0)
        self.assertEqual((history.promoted_frame,history.lookup(42)),(0,(0,75)))

    def test_root_guard_precedes_history_invalidation_and_invalidation_precedes_restore(self):
        self.ready()
        adapter=self.s.prediction_adapters[self.key]
        token=adapter.capture(0)
        history=self.s.identity_histories[self.key]
        history.observe(view(1,{79:(0,75)}),physical_frame=1)
        active=self.s.active_identity_histories[self.key]
        active.observe(view(1,{79:(0,75)}),physical_frame=1)
        before=dict(history.views);binding=self.s.arena.binding
        active_before=dict(active.views)
        self.s.arena.binding=(9,9,9)
        with self.assertRaisesRegex(RuntimeError,'differs'):adapter.restore(token)
        self.assertEqual(history.views,before)
        self.assertEqual(active.views,active_before)
        self.assertNotIn(('restore',token),self.s.arena.events)
        self.s.arena.binding=binding
        original=self.s.arena.restore
        def checked_restore(value):
            self.assertNotIn(1,history.views)
            self.assertNotIn(1,active.views)
            return original(value)
        self.s.arena.restore=checked_restore
        adapter.restore(token)
        self.assertEqual(adapter.tokens[token],(binding,0))

    def test_finished_and_failed_worlds_do_not_admit_more_commands_and_rematch_is_fresh(self):
        self.ready();old=self.key
        self.dispatch(6,struct.pack('<Q',old))
        self.assertFalse(self.s.command_ledgers);self.assertFalse(self.s.identity_histories)
        with self.assertRaises(RuntimeError):self.dispatch(68,struct.pack('<Q',old))
        _,data=self.dispatch(5,b'fresh-game');self.key=struct.unpack('<Q',data)[0]
        self.assertNotEqual(self.key,old)
        self.dispatch(64,struct.pack('<QII',self.key,12,1024*1024))
        self.assertEqual(self.batch(1,[join()]),(0,struct.pack('<Qi',1,0)))
        self.assertFalse(self.s.identity_histories[self.key].known)
        self.s.predictions[self.key]._failed=True
        before=self.s.command_ledgers[self.key].metrics,len(self.raw.calls)
        for call in (lambda:self.batch(2,[]),lambda:self.dispatch(68,struct.pack('<Q',self.key))):
            with self.assertRaises(RuntimeError):call()
        self.assertEqual((self.s.command_ledgers[self.key].metrics,len(self.raw.calls)),before)


class FinishTests(unittest.TestCase):
    def test_finish_is_atomic_and_forecasts_empty_after_canceling_never_committed_orders(self):
        ledger=CommandLedger(0);ledger.register(1,body([join()]),0)
        before=ledger.metrics,ledger.pending
        with self.assertRaises(CommandLedgerError):ledger.finish(-1)
        self.assertEqual((ledger.metrics,ledger.pending),before)
        ledger.observe_authority(0,body([join(deck=b'server')]))
        ledger.register(2,body([MOVE,BUILD]),1)
        self.assertEqual(ledger.finish(0),2)
        self.assertFalse(get_repeated_bytes(ledger.forecast(1),6))
        self.assertFalse(ledger.pending)
        for action in (lambda:ledger.finish(0),lambda:ledger.register(3,body(),1),
                       lambda:ledger.observe_authority(1,b'')):
            with self.assertRaises(CommandLedgerError):action()


if __name__=='__main__':unittest.main()
