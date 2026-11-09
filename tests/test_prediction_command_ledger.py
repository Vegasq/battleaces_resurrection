"""Authored ordered command fixtures; no native DLL or shipped assets."""
import unittest
import copy
import json
from pathlib import Path
import tempfile

from client_patch.prediction_worker.commands import CommandLedger, CommandLedgerError
from server.game_data import InputValidation, encode_identity, encode_player_input
from server.protobuf_wire import (field_bytes, field_packed_uint, field_uint, get_bytes,
                                  get_repeated_bytes, get_uint)


def join(slot=0, deck=b'local-frozen-deck', cosmetic=7):
    return field_bytes(3, field_uint(1, slot) + field_bytes(2, deck) + field_uint(3, cosmetic))


def group(ability=12, ids=(42,)):
    return field_uint(1, 75) + field_uint(2, ability) + field_packed_uint(3, ids)


def execute(*groups):
    return field_bytes(1, b''.join(field_bytes(1, value) for value in groups) + field_bytes(3, field_bytes(1, b'')))


MOVE = execute(group())
ABILITY_14 = execute(group(14))
BUILD = execute(group(34))
UI = field_bytes(5, field_bytes(1, b''))


def body(actions=(), slot=0, name='authored identity'):
    return encode_player_input(encode_identity(slot + 1, name), actions)


def forecast_actions(raw):
    players = get_repeated_bytes(raw, 6)
    return get_repeated_bytes(players[0], 2) if players else ()


class LedgerTests(unittest.TestCase):
    def ready(self, **limits):
        ledger = CommandLedger(0, **limits)
        ledger.register(1, body([join()]), 0)
        ledger.observe_authority(0, body([join(deck=b'authoritative-frozen-deck')], name='canonical identity'))
        return ledger

    def snapshot(self, ledger):
        return ledger.pending, ledger.metrics, ledger.canonical_identity

    def atomic_reject(self, ledger, function):
        before = self.snapshot(ledger)
        with self.assertRaises(ValueError):
            function()
        self.assertEqual(self.snapshot(ledger), before)

    def test_initial_join_deck_exception_and_canonical_identity(self):
        ledger = self.ready()
        self.assertEqual(ledger.received_frame, 0)
        self.assertFalse(ledger.pending)
        ledger.register(2, body([MOVE]), 3)
        raw = ledger.forecast(3)
        self.assertEqual(get_uint(raw, 1), 3)
        self.assertEqual((get_uint(raw, 2), get_uint(raw, 3)), (20, 50))
        self.assertEqual(get_bytes(get_repeated_bytes(raw, 6)[0], 1), ledger.canonical_identity)
        self.assertEqual(forecast_actions(raw), (MOVE,))
        self.atomic_reject(ledger, lambda: ledger.observe_authority(1, body([], name='changed canonical')))

    def test_identical_repeated_orders_retire_by_ordinal_and_remove_future_guess(self):
        ledger = self.ready()
        ledger.register(2, body([MOVE]), 5)
        ledger.register(3, body([MOVE]), 5)
        self.assertEqual([item.ordinal for item in ledger.pending], [(2, 0), (3, 0)])
        self.assertEqual(forecast_actions(ledger.forecast(5)), (MOVE, MOVE))
        first = ledger.observe_authority(1, body([MOVE], name='canonical identity'))
        self.assertEqual([item.ordinal for item in first.retired], [(2, 0)])
        self.assertEqual(forecast_actions(ledger.forecast(5)), (MOVE,))
        second = ledger.observe_authority(2, body([MOVE], name='canonical identity'))
        self.assertEqual([item.ordinal for item in second.retired], [(3, 0)])
        self.assertEqual(forecast_actions(ledger.forecast(5)), ())

    def test_merged_whole_batches_preserve_all_actions_and_build_not_predicted(self):
        ledger = self.ready()
        ledger.register(2, body([BUILD, MOVE]), 4)
        ledger.register(3, body([UI, ABILITY_14]), 4)
        self.assertEqual(forecast_actions(ledger.forecast(4)), (MOVE, ABILITY_14))
        receipt = ledger.observe_authority(1, body([BUILD, MOVE, UI, ABILITY_14], name='canonical identity'))
        self.assertEqual([item.ordinal for item in receipt.retired], [(2, 0), (2, 1), (3, 0), (3, 1)])
        self.assertFalse(ledger.pending)

    def test_nonpredictive_prefix_cannot_be_skipped_to_later_move(self):
        ledger = self.ready()
        ledger.register(2, body([BUILD]), 4)
        ledger.register(3, body([MOVE]), 4)
        self.atomic_reject(ledger, lambda: ledger.observe_authority(1, body([MOVE], name='canonical identity')))
        self.assertEqual(forecast_actions(ledger.forecast(4)), (MOVE,))

    def test_empty_groups_normalize_exactly_and_send_bytes_are_original(self):
        ledger = self.ready()
        raw = body([execute(group(ids=()), group()), execute(group(ids=()))])
        registered = ledger.register(2, raw, 3)
        self.assertIs(registered.send_body, raw)
        self.assertEqual(registered.locally_elided_noops, 1)
        self.assertEqual([item.body for item in registered.normalized_actions], [MOVE])
        self.assertEqual(forecast_actions(ledger.forecast(3)), (MOVE,))
        ledger.observe_authority(1, body([MOVE], name='canonical identity'))
        empty = ledger.register(3, body([execute(group(ids=()))]), 4)
        self.assertFalse(empty.normalized_actions)
        self.assertFalse(ledger.pending)
        self.assertEqual(ledger.next_sequence, 4)
        self.assertEqual(ledger.metrics['locally_elided_noops'], 2)
        self.assertNotIn('accepted_batches', ledger.metrics)

    def test_unknown_late_action_reanchors_once_without_drop_or_duplicate(self):
        ledger = self.ready()
        ledger.register(2, body([MOVE]), 2)
        self.assertEqual(forecast_actions(ledger.forecast(2)), (MOVE,))
        ledger.observe_authority(1, b'')
        self.assertEqual(forecast_actions(ledger.forecast(2)), (MOVE,))
        changed = ledger.observe_authority(2, b'')
        self.assertEqual(changed.reanchored, ((2, 0),))
        self.assertEqual(forecast_actions(ledger.forecast(3)), (MOVE,))
        self.assertEqual(forecast_actions(ledger.forecast(4)), ())
        ledger.observe_authority(3, b'')
        self.assertEqual(forecast_actions(ledger.forecast(4)), (MOVE,))
        ledger.observe_authority(4, body([MOVE], name='canonical identity'))
        self.assertFalse(ledger.pending)
        self.assertEqual(forecast_actions(ledger.forecast(5)), ())

    def test_invalid_join_context_and_exception_scope(self):
        ledger = CommandLedger(0)
        self.atomic_reject(ledger, lambda: ledger.register(1, body([MOVE]), 0))
        self.atomic_reject(ledger, lambda: ledger.register(1, body([join(slot=1)]), 0))
        self.atomic_reject(ledger, lambda: ledger.register(1, body([join(), join()]), 0))
        ledger.register(1, body([join()]), 0)
        self.atomic_reject(ledger, lambda: ledger.observe_authority(0, body([join(cosmetic=9)])))
        self.atomic_reject(ledger, lambda: ledger.observe_authority(0, body([])))
        ledger.observe_authority(0, body([join(deck=b'validated-server-deck')]))
        self.atomic_reject(ledger, lambda: ledger.register(2, body([join()]), 1))
        self.atomic_reject(ledger, lambda: ledger.observe_authority(1, body([join()])))

    def test_bad_identity_order_size_and_batch_prefix_are_atomic(self):
        ledger = self.ready()
        self.atomic_reject(ledger, lambda: ledger.register(3, body([MOVE]), 1))
        self.atomic_reject(ledger, lambda: ledger.register(2, body([MOVE], slot=1), 1))
        self.atomic_reject(ledger, lambda: ledger.register(2, b'x' * 65537, 1))
        self.atomic_reject(ledger, lambda: ledger.register(2, body([MOVE]), True))
        ledger.register(2, body([MOVE, ABILITY_14]), 3)
        self.atomic_reject(ledger, lambda: ledger.register(3, body([MOVE]), 2))
        self.atomic_reject(ledger, lambda: ledger.observe_authority(2, body([], name='canonical identity')))
        self.atomic_reject(ledger, lambda: ledger.observe_authority(1, body([MOVE, BUILD], name='canonical identity')))
        self.atomic_reject(ledger, lambda: ledger.observe_authority(1, body([MOVE], name='canonical identity')))
        ledger.observe_authority(1, body([MOVE, ABILITY_14], name='canonical identity'))
        self.atomic_reject(ledger, lambda: ledger.register(2, body([MOVE]), 3))

    def test_pending_capacity_failure_has_no_partial_registration(self):
        ledger = self.ready(max_pending_actions=1)
        ledger.register(2, body([MOVE]), 1)
        self.atomic_reject(ledger, lambda: ledger.register(3, body([ABILITY_14]), 2))
        bytes_limited = self.ready(max_pending_bytes=max(len(join()), len(MOVE)))
        bytes_limited.register(2, body([MOVE]), 1)
        self.atomic_reject(bytes_limited, lambda: bytes_limited.register(3, body([ABILITY_14]), 2))

    def test_revision_snapshot_immutable_and_known_frames_never_forecast(self):
        ledger = self.ready()
        ledger.register(2, body([MOVE]), 2)
        plan = ledger.revision_plan(1, 3)
        before = dict(plan)
        with self.assertRaises(TypeError): plan[1] = b'changed'
        ledger.observe_authority(1, body([MOVE], name='canonical identity'))
        self.assertEqual(dict(plan), before)
        self.assertFalse(forecast_actions(ledger.forecast(2)))
        with self.assertRaises(CommandLedgerError): ledger.forecast(1)
        with self.assertRaises(CommandLedgerError): ledger.revision_plan(2, 14)

    def test_mixed_ability_execute_is_not_partially_predicted(self):
        ledger = self.ready()
        mixed = execute(group(), group(34))
        ledger.register(2, body([mixed]), 2)
        self.assertFalse(forecast_actions(ledger.forecast(2)))
        ledger.observe_authority(1, body([mixed], name='canonical identity'))
        self.assertFalse(ledger.pending)

    def test_ui_and_target_cases_follow_server_opaque_one_field_contract(self):
        ledger = self.ready()
        # Shipped UI: ping1, emote2, spray3, camera4. Preserve all payloads;
        # a future one-field form is left to the real descriptor validator.
        ui = [field_bytes(5, field_bytes(case, b'opaque original payload')) for case in (1, 2, 3, 4)]
        ui.append(field_bytes(5, field_uint(99, 7)))
        # Shipped CommandData cases1/2/3, plus an opaque future one-field form.
        targets = [field_bytes(case, b'') for case in (1, 2, 3)] + [field_uint(99, 7)]
        commands = [field_bytes(1, field_bytes(1, group(34)) + field_bytes(3, target)) for target in targets]
        actions = ui + commands
        ledger.register(2, body(actions), 3)
        self.assertEqual([item.body for item in ledger.pending], actions)
        self.assertFalse(forecast_actions(ledger.forecast(3)))
        ledger.observe_authority(1, body(actions, name='canonical identity'))
        self.assertFalse(ledger.pending)
        self.atomic_reject(ledger, lambda: ledger.register(3, body([field_bytes(5, b'')]), 4))
        self.atomic_reject(ledger, lambda: ledger.register(3, body([field_bytes(5, field_uint(1, 1) + field_uint(2, 2))]), 4))
        bad_target = field_bytes(1, field_bytes(1, group(34)) + field_bytes(3, field_uint(1, 1) + field_uint(2, 2)))
        self.atomic_reject(ledger, lambda: ledger.register(3, body([bad_target]), 4))

    def test_normalization_agrees_with_actual_server_validator(self):
        from tests import test_input_validation as authored
        from tests.synthetic import template
        with tempfile.TemporaryDirectory(prefix='ba-ledger-contract-') as folder:
            messages = copy.deepcopy(authored.GAME)
            action = next(row for row in messages if row['name'] == 'InputAction')
            action['fields'].append(authored.field('join_army', 3, 11, message='.game_pb.JoinArmy', oneof=0))
            messages.extend([
                authored.message('JoinArmy', authored.field('army_id', 1, 13),
                    authored.field('deck', 2, 11, message='.game_pb.Deck')),
                authored.message('Deck', authored.field('units', 1, 13, repeated=True),
                    authored.field('groups', 2, 13, repeated=True), authored.field('entitlements', 3, 12, repeated=True)),
            ])
            directory = Path(folder)
            for package, definitions in (('common_pb', authored.COMMON), ('game_pb', messages)):
                (directory / (package + '.proto.json')).write_text(json.dumps(dict(package=package, messages=definitions)))
            source = template()
            source.descriptors_path = directory
            source.entity_abilities = {100: {12}}
            match = source.build_match([dict(slot=slot, player_id=slot + 1, name='author ' + str(slot)) for slot in (0, 1)],
                                       source.default_decks, seed=17)
            validation = InputValidation(match, source, entity_lookup={42: (0, 100)}.get)
            ledger = CommandLedger(0)
            local_join = field_bytes(3, field_uint(1, 0) + field_bytes(2, match.deck_messages_by_slot[0] + field_bytes(3, b'local entitlement')))
            raw_join = encode_player_input(match.identities_by_slot[0], [local_join])
            ledger.register(1, raw_join, 0)
            canonical_join = validation.validate_player_input(0, raw_join)
            self.assertNotEqual(canonical_join, raw_join)
            ledger.observe_authority(0, canonical_join)
            raw = encode_player_input(match.identities_by_slot[0], [
                authored.execute([authored.group((), entity_type=100, ability=12, explicit_empty=True),
                                  authored.group((42,), entity_type=100, ability=12)]),
                authored.execute([authored.group((), entity_type=100, ability=12)]),
            ])
            registered = ledger.register(2, raw, 2)
            actual = validation.validate_player_input(0, raw)
            self.assertEqual(tuple(item.body for item in registered.normalized_actions), get_repeated_bytes(actual, 2))
            self.assertEqual(forecast_actions(ledger.forecast(2)), get_repeated_bytes(actual, 2))
            ledger.observe_authority(1, actual)
            self.assertFalse(ledger.pending)


if __name__ == '__main__':
    unittest.main()
