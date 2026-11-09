"""Pure numbered-input credits; speculation never acts as a server acknowledgement."""
import importlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from server import protocol as p
from server.game_data import encode_identity, encode_player_input, InputValidation
from server.protobuf_wire import field_bytes, field_uint
from tests import test_input_validation as authored
from tests.synthetic import template


def body(name='Pilot', actions=()):
    return encode_player_input(encode_identity(1, name), actions)


class InputCreditPlannerTests(unittest.TestCase):
    def setUp(self): self.api = importlib.import_module('client_patch.transport.prediction_schedule')

    def test_startup_seeds_exact_own_window_and_emits_existing_input_payload(self):
        for window in (6, 12):
            planner = self.api.InputCreditPlanner(window)
            seeded = planner.seed([body()] * window)
            self.assertEqual([item.frame for item in seeded], list(range(window)))
            self.assertEqual(seeded[0].payload, struct.pack('<I', 0) + body())
            self.assertEqual(seeded[-1].payload, struct.pack('<I', window-1) + body())
            self.assertEqual(planner.available_credits, 0)
            self.assertEqual((planner.received_frame, planner.confirmed_frame, planner.predicted_frame), (-1, -1, -1))
            with self.assertRaises(self.api.InputCreditError): planner.submit(body())

    def test_only_one_new_contiguous_authority_receipt_grants_one_credit(self):
        planner = self.api.InputCreditPlanner(6)
        planner.seed([body()] * 6)
        for frame in range(12): planner.mark_predicted(frame)
        self.assertEqual(planner.available_credits, 0)
        planner.observe_authority(0, body())
        self.assertEqual(planner.available_credits, 1)
        planner.mark_confirmed(0)
        self.assertEqual(planner.available_credits, 1)
        planner.mark_predicted(12)
        self.assertEqual(planner.available_credits, 1)
        self.assertEqual(planner.submit(body()).frame, 6)
        self.assertEqual(planner.available_credits, 0)
        with self.assertRaises(self.api.InputCreditError): planner.observe_authority(0, body())
        self.assertEqual(planner.available_credits, 0)

    def test_continuous_own_six_and_twelve_leads_never_overrun_server_future_bound(self):
        for window in (6, 12):
            planner = self.api.InputCreditPlanner(window)
            planner.seed([body()] * window)
            for frame in range(12): planner.mark_predicted(frame)
            for frame in range(200):
                receipt = planner.observe_authority(frame, body())
                self.assertTrue(receipt.matched)
                server_frame = frame + 1  # Publishing F proves server has completed F.
                planner.mark_confirmed(frame)
                planner.mark_predicted(frame + 12)
                scheduled = planner.submit(body())
                self.assertEqual(scheduled.frame, frame + window)
                self.assertLess(scheduled.frame, server_frame + window)
                self.assertEqual(planner.available_credits, 0)
                self.assertEqual(len(planner.pending_inputs), window)

    def test_duplicate_gap_unsent_and_late_frames_do_not_mutate_state_or_credits(self):
        planner = self.api.InputCreditPlanner(6)
        with self.assertRaises(self.api.InputCreditError): planner.observe_authority(0, body())
        planner.seed([body()] * 6)
        for invalid in (True, -1, 1, 7):
            with self.subTest(frame=invalid), self.assertRaises(self.api.InputCreditError):
                planner.observe_authority(invalid, body())
        planner.observe_authority(0, body()); planner.mark_confirmed(0)
        snapshot = planner.metrics
        for operation in (lambda: planner.observe_authority(0, body()),
                          lambda: planner.mark_confirmed(0), lambda: planner.mark_confirmed(2),
                          lambda: planner.submit(body(), frame=5), lambda: planner.submit(body(), frame=7)):
            with self.assertRaises(self.api.InputCreditError): operation()
            self.assertEqual(planner.metrics, snapshot)

    def test_receive_confirm_and_predict_are_distinct_cursors(self):
        planner = self.api.InputCreditPlanner(6)
        planner.seed([body()] * 6)
        planner.mark_predicted(0); planner.mark_predicted(1)
        planner.observe_authority(0, body())
        self.assertEqual((planner.received_frame, planner.confirmed_frame, planner.predicted_frame), (0, -1, 1))
        planner.mark_confirmed(0)
        self.assertEqual((planner.received_frame, planner.confirmed_frame, planner.predicted_frame), (0, 0, 1))
        planner.observe_authority(1, body()); planner.mark_confirmed(1)
        planner.observe_authority(2, body()); planner.mark_confirmed(2)
        self.assertEqual(planner.predicted_frame, 2)

    def test_known_unconfirmed_authority_cannot_be_predicted_as_unknown(self):
        planner = self.api.InputCreditPlanner(6)
        planner.seed([body()] * 6); planner.observe_authority(0, body())
        with self.assertRaises(self.api.InputCreditError): planner.mark_predicted(0)
        planner.mark_confirmed(0); planner.mark_predicted(1)

    def test_prediction_lead_is_bounded_and_rollback_does_not_mint_wire_credit(self):
        planner = self.api.InputCreditPlanner(6, max_prediction_ahead=2)
        planner.seed([body()] * 6)
        planner.mark_predicted(0); planner.mark_predicted(1)
        with self.assertRaises(self.api.InputCreditError): planner.mark_predicted(2)
        planner.observe_authority(0, body()); planner.mark_confirmed(0)
        planner.mark_predicted(2)
        self.assertEqual(planner.rollback_prediction(), 2)
        self.assertEqual(planner.predicted_frame, planner.confirmed_frame)
        self.assertEqual(planner.available_credits, 1)
        planner.mark_predicted(1); self.assertEqual(planner.available_credits, 1)

    def test_identical_input_bodies_are_distinct_frame_assignments(self):
        planner = self.api.InputCreditPlanner(6)
        seeded = planner.seed([body()] * 6)
        first = planner.observe_authority(0, body())
        second = planner.observe_authority(1, body())
        self.assertEqual((first.frame, second.frame), (0, 1))
        self.assertEqual(first.submitted_body, second.submitted_body)
        self.assertEqual(len(planner.pending_inputs), 6)
        planner.mark_confirmed(0); self.assertEqual(planner.pending_inputs[0].frame, seeded[1].frame)

    def test_real_validator_empty_selection_normalization_is_visible_and_not_reidentified(self):
        with tempfile.TemporaryDirectory(prefix='ba-credit-schema-') as directory:
            root = Path(directory)
            for package, messages in [('common_pb', authored.COMMON), ('game_pb', authored.GAME)]:
                (root / (package+'.proto.json')).write_text(json.dumps(dict(package=package, messages=messages)))
            game = template(); game.descriptors_path = root; game.entity_abilities[100] = {7}
            match = game.build_match([dict(slot=i, player_id=i+1, name='Assigned '+str(i)) for i in (0, 1)],
                                     game.default_decks, seed=123)
            validator = InputValidation(match, game, entity_lookup=lambda entity: (0, 100))
            submitted = body(actions=(authored.execute([authored.group()]),))
            canonical = validator.validate_player_input(0, submitted)
            planner = self.api.InputCreditPlanner(6)
            planner.seed([submitted] + [body()] * 5)
            receipt = planner.observe_authority(0, canonical)
            self.assertFalse(receipt.matched); self.assertTrue(receipt.normalized); self.assertTrue(receipt.noop)
            self.assertEqual((receipt.submitted_action_count, receipt.canonical_action_count), (1, 0))
            self.assertEqual(receipt.frame, 0); self.assertEqual(receipt.submitted_body, submitted)
            self.assertEqual(receipt.canonical_body, canonical)
            self.assertEqual(planner.available_credits, 1)

    def test_startup_seed_validation_is_atomic_and_never_invents_missing_inputs(self):
        for supplied in ([body()]*5, [body()]*7, [body()]*5 + [b'\0']):
            planner = self.api.InputCreditPlanner(6)
            with self.assertRaises(self.api.InputCreditError): planner.seed(supplied)
            self.assertEqual(planner.next_input_frame, 0); self.assertEqual(planner.available_credits, 6)
        planner = self.api.InputCreditPlanner(6, max_buffered_bytes=6*len(body())-1)
        with self.assertRaises(self.api.InputCreditError): planner.seed([body()]*6)
        self.assertEqual(planner.pending_inputs, ())

    def test_authority_backlog_and_bytes_are_bounded_before_granting_credit(self):
        planner = self.api.InputCreditPlanner(6, max_authority_backlog=2)
        planner.seed([body()]*6)
        planner.observe_authority(0, body()); planner.observe_authority(1, body())
        before = planner.metrics
        with self.assertRaises(self.api.InputCreditError): planner.observe_authority(2, body())
        self.assertEqual(planner.metrics, before)
        planner.mark_confirmed(0); planner.observe_authority(2, body())
        self.assertEqual(planner.received_frame, 2)

    def test_invalid_body_or_frame_never_spends_credit(self):
        planner = self.api.InputCreditPlanner(6)
        for supplied in (True, b'\0', b'x'*65537, field_uint(1, 1), body()+field_bytes(1, b'duplicate')):
            with self.subTest(size=len(supplied) if isinstance(supplied, bytes) else supplied), self.assertRaises(self.api.InputCreditError):
                planner.submit(supplied)
            self.assertEqual(planner.available_credits, 6)
        for frame in (True, -1, 1):
            with self.assertRaises(self.api.InputCreditError): planner.submit(body(), frame=frame)
        self.assertEqual(planner.pending_inputs, ())

    def test_retired_planner_rejects_late_match_messages_and_releases_retained_bodies(self):
        planner = self.api.InputCreditPlanner(6)
        planner.seed([body()]*6); planner.observe_authority(0, body())
        planner.retire()
        self.assertEqual(planner.available_credits, 0); self.assertEqual(planner.buffered_bytes, 0)
        self.assertEqual(planner.pending_inputs, ()); self.assertEqual(planner.authority_backlog, ())
        for operation in (lambda: planner.submit(body()), lambda: planner.observe_authority(1, body()),
                          lambda: planner.mark_confirmed(0), lambda: planner.mark_predicted(0)):
            with self.assertRaises(self.api.InputCreditError): operation()

    def test_limits_reject_booleans_and_out_of_protocol_windows(self):
        for window in (True, False, None, 1, 13, 6.0):
            with self.assertRaises(ValueError): self.api.InputCreditPlanner(window)
        for key, value in (('max_prediction_ahead', True), ('max_prediction_ahead', 0),
                           ('max_authority_backlog', 0), ('max_authority_backlog', 65), ('max_buffered_bytes', 0)):
            with self.assertRaises(ValueError): self.api.InputCreditPlanner(6, **{key: value})
