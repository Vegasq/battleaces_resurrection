"""Authored same-head views/dispatch only; no original DLL or game loads."""
import ctypes as C
import io
from pathlib import Path
import struct
import threading
import unittest
from unittest.mock import patch

from client_patch.prediction_worker import corrections as c, wire, __main__ as main
from client_patch.prediction_worker.native import HostError, NativeSession
from server.game_data import encode_frame
from tests.test_prediction_worker import Raw, command
from tests.test_prediction_worker_ledger_integration import NativeFixture, SnapshotHeap
from tests.test_prediction_command_ledger import body, join, MOVE


def view(frame, positions, *, identities=None, states=None, viewer=0):
    identities = identities if identities is not None else {i: (0, 75) for i in positions}
    states = states if states is not None else {i: 0 for i in identities}
    raw = bytearray(256); root, vt = 128, 32
    struct.pack_into('<I', raw, 0, root)
    struct.pack_into('<HH8H', raw, vt, 20, 36, 4, 8, 12, 16, 20, 0, 0, 32)
    struct.pack_into('<iII', raw, root, root-vt, frame, viewer)
    for field, rows, words in [(2, {i: (v[0],) for i, v in identities.items()}, 1),
                                (3, {i: (v[1],) for i, v in identities.items()}, 1),
                                (4, {i: (v,) for i, v in states.items()}, 1),
                                (7, positions, 3)]:
        vtable = len(raw); raw.extend(struct.pack('<HHHH', 8, 12, 4, 8))
        table = len(raw); raw.extend(struct.pack('<iII', table-vtable, 0, 0))
        struct.pack_into('<I', raw, root+4+field*4, table-(root+4+field*4))
        ids = len(raw); raw.extend(struct.pack('<I', len(rows)))
        for identity in rows: raw.extend(struct.pack('<I', identity))
        values = len(raw); raw.extend(struct.pack('<I', len(rows)))
        for row in rows.values(): raw.extend(struct.pack('<'+('fff' if words == 3 else 'I'), *row))
        struct.pack_into('<II', raw, table+4, ids-table-4, values-table-8)
    return bytes(raw)


def unpack(raw):
    header = c.HEADER.unpack_from(raw)
    return header, [c.ENTRY.unpack_from(raw, c.HEADER.size+i*c.ENTRY.size) for i in range(header[-1])]


ADMISSION = {42: (0, 75, 100), 55: (0, 75, 101), 77: (1, 75, 102)}


class PureCorrections(unittest.TestCase):
    def store(self):
        value = c.Corrections(); value.begin(7, 0)
        value.ordinary(7, 4, view(4, {42: (4., 0., 0.)}), admitted=ADMISSION, continuity=True)
        return value

    def repair(self, value, x=1., admission=ADMISSION, continuity=True):
        value.prepare(7, 4)
        value.corrected_head(7, 4, view(4, {42: (x, 0., 0.)}))
        value.finish(7, admitted=admission, continuity=continuity)

    def test_exact_same_head_delta_not_next_frame_normal_motion_and_two_retained_frames(self):
        value = self.store(); self.repair(value)
        raw = view(5, {42: (2., 0., 0.)})
        value.ordinary(7, 5, raw, admitted=ADMISSION, continuity=True)
        response = value.packet(7, 5); header, entries = unpack(response)
        self.assertEqual(header, (1, 7, 5, 4, 1, 1))
        self.assertEqual(entries, [(42, 75, 0, 100, -3., 0., 0.)])
        value.ordinary(7, 6, view(6, {42: (3., 0., 0.)}), admitted=ADMISSION, continuity=True)
        self.assertEqual(value.packet(7, 5), response)
        self.assertEqual(unpack(value.packet(7, 6))[0], (1, 7, 6, -1, 1, 0))
        with self.assertRaises(c.CorrectionError): value.packet(7, 4)
        with self.assertRaises(c.CorrectionError): value.packet(7, 7)

    def test_repeated_repairs_preserve_first_H_baseline_and_final_H(self):
        value = self.store(); self.repair(value, 1.); self.repair(value, 2.)
        value.ordinary(7, 5, view(5, {42: (3., 0., 0.)}), admitted=ADMISSION, continuity=True)
        header, entries = unpack(value.packet(7, 5))
        self.assertEqual(header, (1, 7, 5, 4, 2, 1))
        self.assertEqual(entries[0][-3:], (-2., 0., 0.))

    def test_no_admission_continuity_hidden_dead_or_replacement_is_exposed(self):
        for mode in ('missing', 'new_token', 'new_type', 'dead', 'hidden', 'no_continuity', 'next_death'):
            value = self.store(); admission = dict(ADMISSION)
            value.prepare(7, 4)
            points = {42: (1., 0., 0.)}; identities = {42: (0, 75)}; states = {42: 0}
            if mode == 'missing': admission.pop(42)
            if mode == 'new_token': admission[42] = (0, 75, 999)
            if mode == 'new_type': identities[42] = (0, 76); admission[42] = (0, 76, 100)
            if mode == 'dead': states[42] = 6
            if mode == 'hidden': points = {}; identities = {}; states = {}
            value.corrected_head(7, 4, view(4, points, identities=identities, states=states))
            value.finish(7, admitted=admission, continuity=mode != 'no_continuity')
            value.ordinary(7, 5, view(5, {42: (2., 0., 0.)}, states={42: 6 if mode == 'next_death' else 0}),
                           admitted=ADMISSION, continuity=True)
            with self.subTest(mode=mode): self.assertEqual(unpack(value.packet(7, 5))[0][-2:], (1, 0))

    def test_sorted_visible_own_members_only_and_copied_admission(self):
        value = c.Corrections(); value.begin(7, 0)
        identities = {55: (0, 75), 42: (0, 75), 77: (1, 75), 99: (0, 75)}
        admission = dict(ADMISSION)
        raw = view(4, {i: (4., 0., 0.) for i in identities}, identities=identities)
        value.ordinary(7, 4, raw, admitted=admission, continuity=True)
        admission[42] = (0, 75, 999)  # Must not mutate the cached token.
        value.prepare(7, 4); value.corrected_head(7, 4,
            view(4, {i: (1., 0., 0.) for i in identities}, identities=identities))
        value.finish(7, admitted=ADMISSION, continuity=True)
        value.ordinary(7, 5, view(5, {i: (2., 0., 0.) for i in identities}, identities=identities),
                       admitted=ADMISSION, continuity=True)
        self.assertEqual([r[:4] for r in unpack(value.packet(7, 5))[1]], [(42, 75, 0, 100), (55, 75, 0, 101)])

    def test_malformed_view_bounds_duplicate_owner_and_retirement_fail_closed(self):
        for raw in (view(3, {42: (1., 0., 0.)}), view(4, {42: (1., 0., 0.)}, viewer=1),
                    view(4, {42: (float('nan'), 0., 0.)}), b'bad'):
            with self.subTest(raw=raw[:12]), self.assertRaises((c.CorrectionError, ValueError)):
                c.snapshot(raw, slot=0, frame=4, admitted=ADMISSION, continuity=True)
        from server.native_simulation import _Buffer
        raw = bytearray(view(4, {42: (1., 0., 0.), 55: (2., 0., 0.)}))
        b = _Buffer(bytes(raw)); table = b.table(b.read('I', 0), 2); ids, _ = b.vector(table, 0, 4)
        struct.pack_into('<I', raw, ids+4, 42)
        with self.assertRaisesRegex(c.CorrectionError, 'duplicate'):
            c.snapshot(bytes(raw), slot=0, frame=4, admitted=ADMISSION, continuity=True)
        value = self.store(); value.retire(7)
        with self.assertRaises(c.CorrectionError): value.packet(7, 4)
        value.begin(8, 0)
        with self.assertRaises(c.CorrectionError): value.packet(8, 4)
        value.clear(); self.assertFalse(value.worlds)


class Guard:
    def __init__(self): self.proven = True; self.intervals = []
    def snapshot(self): return (1, 0, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0)
    def begin(self, raw): pass
    def finish(self): pass
    def invalidate_after(self, frame): pass
    def continuity(self, start, end): self.intervals.append((start, end)); return self.proven
    def close(self): pass


class QueryRaw(NativeFixture):
    def call(self, name, *args):
        if name == 'SimMakeSimFrame':
            self.queries.append((self.physical, args[1]))
            self.frame = view(max(0, self.physical), {i: (float(self.physical)-(3. if self.remote and i == 42 else 0.), 0., 0.)
                             for i in self.rows()}, identities=self.rows(), viewer=args[1])
            return Raw.call(self, name, *args)
        previous = self.remote
        result = super().call(name, *args)
        if name == 'SimProcessMsg' and self.next_frame == 0: self.remote = previous
        return result


class NativeCorrections(unittest.TestCase):
    def setup(self, enabled=True):
        self.raw = QueryRaw(); self.session = NativeSession(self.raw, arena=SnapshotHeap(self.raw))
        self.addCleanup(self.session.close)
        if enabled: self.session.enable_movement_corrections()
        self.session.dispatch(command(1, b'\0'))
        _, raw = self.session.dispatch(command(5, b'authored'))
        self.key, = struct.unpack('<Q', raw)
        self.dispatch(64, struct.pack('<II', 12, 1024*1024))
        self.guard = Guard(); self.session.entity_guards[self.key] = self.guard
        self.dispatch(67, struct.pack('<Q', 1)+body([join()]))
        # A native/bootstrap own-view query before physical0 must remain legal
        # and must not fabricate a correction response/cache for frame-1.
        self.dispatch(9, struct.pack('<II', 0, 0))
        if enabled:
            self.assertIsNone(self.session.movement_corrections.worlds[self.key]['latest'])
        self.authority(0)
        for frame in range(5): self.advance(frame)

    def dispatch(self, op, tail=b''):
        return self.session.dispatch(command(op, struct.pack('<Q', self.key)+tail))

    def authority(self, frame, remote=False):
        own = [join(deck=b'server')] if frame == 0 else []
        other = [join(1)] if frame == 0 else [MOVE] if remote else []
        return self.dispatch(65, encode_frame(frame, {0: body(own), 1: body(other, slot=1)}))

    def advance(self, frame):
        self.dispatch(7, encode_frame(frame, {0: b'', 1: b''}))
        self.dispatch(8, struct.pack('<Ii', 50, -1))
        result = self.dispatch(9, struct.pack('<II', 0, 0))
        self.assertEqual(result[1][12:], self.raw.frame)  # Exact original copied bytes.
        return result

    def test_one_new_own_head_query_not_per_replay_step_and_control_is_query_free(self):
        self.setup(); self.authority(1, remote=True); before = len(self.raw.queries)
        self.advance(5)
        self.assertEqual(self.raw.queries[before:], [(1, 0), (4, 0), (5, 0)])
        calls = list(self.raw.calls); queries = list(self.raw.queries)
        _, raw = self.dispatch(77, struct.pack('<i', 5)); header, records = unpack(raw)
        self.assertEqual(header[:4], (1, self.key, 5, 4))
        self.assertEqual([r[-3:] for r in records if r[0] == 42], [(-3., 0., 0.)])
        self.assertEqual(self.dispatch(77, struct.pack('<i', 5)), (0, raw))
        self.assertEqual((self.raw.calls, self.raw.queries), (calls, queries))
        self.assertFalse(any(viewer == 31 for _, viewer in self.raw.queries))
        self.advance(6); self.assertEqual(self.dispatch(77, struct.pack('<i', 5)), (0, raw))
        self.session._retire_prediction(self.key)
        self.assertFalse(self.session.movement_corrections.worlds)

    def test_existing_received_head_query_is_reused_and_default_has_no_new_query(self):
        for enabled, received_at_head in ((True, True), (False, False)):
            self.setup(enabled)
            for frame in range(1, 5 if received_at_head else 2): self.authority(frame, remote=frame == 1)
            before = len(self.raw.queries); self.advance(5)
            self.assertEqual(self.raw.queries[before:], [(4 if received_at_head else 1, 0), (5, 0)])
            if not enabled:
                with self.assertRaises(HostError): self.dispatch(77, struct.pack('<i', 5))
            self.session.close()

    def test_missing_continuity_does_not_fabricate_native_delta(self):
        self.setup(); self.guard.proven = False; self.authority(1, remote=True); self.advance(5)
        self.assertEqual(unpack(self.dispatch(77, struct.pack('<i', 5))[1])[1], [])

    def test_wrong_owner_future_stale_and_disabled_startup_are_refused(self):
        self.setup()
        for frame in (-1, 2, 5):
            with self.subTest(frame=frame), self.assertRaises((ValueError, wire.ProtocolError)):
                self.dispatch(77, struct.pack('<i', frame))
        with self.assertRaises(HostError): self.session.enable_movement_corrections()
        with self.assertRaises(HostError):
            self.session.dispatch(command(77, struct.pack('<Qi', self.key+1, 4)))
        errors = []; before = list(self.raw.calls)
        def foreign():
            try: self.dispatch(77, struct.pack('<i', 4))
            except Exception as error: errors.append(error)
        thread = threading.Thread(target=foreign); thread.start(); thread.join()
        self.assertEqual(len(errors), 1); self.assertIsInstance(errors[0], HostError)
        self.assertEqual(self.raw.calls, before)


class WireAndCli(unittest.TestCase):
    def test_exact_opcode77_request_shape(self):
        encoded = wire.encode_request(77, 1, struct.pack('<Qi', 7, 4))
        self.assertEqual(wire.read_request(io.BytesIO(encoded), 1)[1].args, (7, 4))
        for payload in (b'', struct.pack('<Qi', 0, 4), struct.pack('<Qi', 7, -1), struct.pack('<Qi', 7, 4)+b'x'):
            with self.assertRaises(wire.ProtocolError): wire.encode_request(77, 1, payload)
        self.assertEqual((c.HEADER.size, c.ENTRY.size), (32, 32))

    def test_cli_flag_is_explicit_and_does_not_enable_diagnostic_queries(self):
        args = ['--original-dll', 'original', '--heap-helper', 'heap', '--cooperative', 'coop', '--data-dir', '.']
        for enabled in (False, True):
            calls = []
            class Session:
                def enable_movement_corrections(self): calls.append('corrections')
                def enable_movement_observation(self, *a, **kw): raise AssertionError('not requested')
            with patch.object(main.NativeSession, 'open', return_value=Session()), \
                    patch.object(main, 'run_streams', return_value=0), \
                    patch('server.simulation_worker.isolate_protocol_stdout', return_value=io.BytesIO()):
                self.assertEqual(main.main(args+(['--movement-corrections'] if enabled else [])), 0)
            self.assertEqual(calls, ['corrections'] if enabled else [])


if __name__ == '__main__': unittest.main()
