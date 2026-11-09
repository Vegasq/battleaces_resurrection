"""Authored reader/classification controls; never load a native DLL."""
import struct
import unittest
from types import SimpleNamespace

from server.game_data import encode_frame, encode_identity, encode_player_input
from server.protobuf_wire import field_bytes, field_uint, get_repeated_bytes
from tools.verify_prediction_terminal_drain import continuation_summary, digest, inject_surrender, journal_records


class TerminalProbeTests(unittest.TestCase):
    def frame(self, number):
        return encode_frame(number, {0: b'', 1: b''})

    def test_contiguous_journal_and_truncation(self):
        values = [self.frame(frame) for frame in range(2)]
        raw = b''.join(struct.pack('<I', len(value)) + value for value in values)
        self.assertEqual(journal_records(raw), values)
        for bad in (b'', raw[:-1], raw + b'x', struct.pack('<I', 0), struct.pack('<I', len(values[1])) + values[1]):
            with self.subTest(bad=len(bad)), self.assertRaises(AssertionError):
                journal_records(bad)

    def test_surrender_appends_only_selected_players_action(self):
        identities = {0: encode_identity(7, 'first'), 1: encode_identity(9, 'second')}
        players = [encode_player_input(identities[0], [b'old action']),
                   encode_player_input(identities[1], [b'other action'])]
        original = self.frame(5)
        from server.protobuf_wire import replace_fields
        original = replace_fields(original, {6: [field_bytes(6, value) for value in players]})
        class Validation:
            players = {0: SimpleNamespace(player_id=7), 1: SimpleNamespace(player_id=9)}
            match = SimpleNamespace(identities_by_slot=identities)
            def validate_player_input(self, slot, value):
                self.slot, self.value = slot, value
                return value
        validation = Validation()
        action = field_bytes(1, b'ordinary instant execute')
        changed = inject_surrender(original, slot=0, action=action, validation=validation)
        self.assertEqual(get_repeated_bytes(changed, 6), (players[0] + field_bytes(2, action), players[1]))
        self.assertEqual(validation.slot, 0)
        # Real encode_frame omits all idle player bodies. This was the first
        # prepare-only failure; retain a control for introducing an action.
        idle = inject_surrender(self.frame(5), slot=0, action=action, validation=validation)
        self.assertEqual(get_repeated_bytes(idle, 6), (encode_player_input(identities[0], [action]),))

    def rows(self, advance=True):
        return [dict(request_frame=frame, native_frame=frame if advance else 0,
                     return_codes=dict(process_msg=0, step=0, make_frame=0, get_frame=0),
                     game_time_seconds=0, state=dict(game_state=dict(complete=True))) for frame in range(9)]

    def test_frozen_native_frame_is_not_input_cursor_progress(self):
        summary = continuation_summary(self.rows(False), 0)
        self.assertFalse(summary['native_frame_follows_requests'])
        self.assertTrue(summary['all_postterminal_calls_successful'])
        self.assertTrue(summary['complete_remains_set'])
        self.assertEqual(len(summary['after_complete']), 8)

    def test_advancing_native_frames_and_nonzero_codes_separate(self):
        rows = self.rows()
        self.assertTrue(continuation_summary(rows, 0)['native_frame_follows_requests'])
        rows[5]['return_codes']['step'] = 8
        self.assertFalse(continuation_summary(rows, 0)['all_postterminal_calls_successful'])
        with self.assertRaises(AssertionError):
            continuation_summary(rows[:-1], 0)

    def test_parsed_json_integer_keys_normalize_identically(self):
        self.assertEqual(digest(dict(resources={0: dict(primary=40)})),
                         digest(dict(resources={'0': dict(primary=40)})))


if __name__ == '__main__':
    unittest.main()
