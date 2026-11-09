"""Authored command fixtures; no game exports or native runtime are required."""
import json
from pathlib import Path
import tempfile
import unittest

from server.game_data import (InputError, InputValidation, MAX_INPUT_BYTES,
                              encode_player_input)
from server.protobuf_wire import (field_bytes, field_packed_uint, field_uint,
                                  get_bytes, get_repeated_bytes)
from tests.synthetic import template


def field(name, number, kind, *, repeated=False, message=None, oneof=None):
    result = dict(name=name, number=number, type=kind, label=3 if repeated else 1)
    if message is not None:
        result['type_name'] = message
    if oneof is not None:
        result['oneof_index'] = oneof
    return result


def message(name, *fields):
    return dict(name=name, fields=list(fields))


# Narrow, hand-authored wire contracts for the command forms exercised here.
# These field numbers/types match the public adapter contract, but this fixture
# intentionally contains no exported descriptor file or proprietary payload.
COMMON = [
    message('PlayerHandle', field('steam_id', 1, 4), field('is_aliased', 2, 8)),
    message('PlayerHandleWithName',
            field('player_handle', 1, 11, message='.common_pb.PlayerHandle'),
            field('player_name', 2, 9), field('filtered_name', 4, 9)),
    message('PlayerGameHandle',
            field('player_handle_with_name', 1, 11, message='.common_pb.PlayerHandleWithName'),
            field('ai_profile_id', 2, 13)),
]
GAME = [
    message('InputActionsByPlayer',
            field('player_handle', 1, 11, message='.common_pb.PlayerGameHandle'),
            field('actions', 2, 11, repeated=True, message='.game_pb.InputAction')),
    message('InputAction',
            field('execute_command', 1, 11, message='.game_pb.ExecuteCommand', oneof=0)),
    message('ExecuteCommand',
            field('entity_type_data', 1, 11, repeated=True,
                  message='.game_pb.ExecuteCommandEntityTypeData'),
            field('queued', 2, 8), field('command_data', 3, 11, message='.game_pb.CommandData')),
    message('ExecuteCommandEntityTypeData', field('entity_type', 1, 13),
            field('ability_id', 2, 13), field('entity_ids', 3, 13, repeated=True)),
    message('CommandData',
            field('instant_command_data', 1, 11, message='.game_pb.InstantCommandData', oneof=0),
            field('target_unit_command_data', 2, 11, message='.game_pb.TargetUnitCommandData', oneof=0)),
    message('InstantCommandData'),
    message('TargetUnitCommandData', field('target_entity_id', 1, 13),
            field('is_focus_fire', 2, 8), field('is_sticky_priority_target', 3, 8)),
]


def group(ids=(), *, entity_type=100, ability=7, explicit_empty=False):
    result = field_uint(1, entity_type) + field_uint(2, ability)
    if ids or explicit_empty:
        result += field_packed_uint(3, ids)
    return result


def execute(groups, *, queued=False, target=None):
    if target is None:
        target = field_bytes(1, b'')
    payload = b''.join(field_bytes(1, value) for value in groups)
    payload += field_uint(2, int(queued)) + field_bytes(3, target)
    return field_bytes(1, payload)


class InputCommandValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory(prefix='ba-input-schema-')
        cls.addClassCleanup(directory.cleanup)
        cls.descriptors = Path(directory.name)
        for package, messages in [('common_pb', COMMON), ('game_pb', GAME)]:
            (cls.descriptors / (package + '.proto.json')).write_text(
                json.dumps(dict(package=package, messages=messages)), encoding='utf-8')

    def setUp(self):
        self.template = template()
        self.template.descriptors_path = self.descriptors
        self.template.entity_abilities = {100: {7}, 101: {8}, 108: {7}}
        self.template.catalog[108] = dict(deck_slot_flags=1)
        roster = [dict(slot=i, player_id=i + 1, name=f'Authored player {i}') for i in (0, 1)]
        self.match = self.template.build_match(roster, self.template.default_decks, seed=123)
        # 99 represents an owned unit retained by entity_history after death.
        self.owners = {42: (0, 100), 43: (0, 100), 44: (0, 101),
                       90: (1, 100), 99: (0, 100)}
        self.validator = InputValidation(self.match, self.template, entity_lookup=self.owners.get)

    def validate(self, actions):
        return self.validator.validate_player_input(
            0, encode_player_input(self.match.identities_by_slot[0], actions))

    def test_all_empty_entity_groups_are_a_noop_player_input(self):
        for explicit in (False, True):
            with self.subTest(explicit_empty_packed_field=explicit):
                action = execute([group(explicit_empty=explicit)], queued=True)
                result = self.validate([action])
                self.assertEqual(result, encode_player_input(self.match.identities_by_slot[0]))

    def test_multiple_empty_groups_do_not_emit_an_empty_execute(self):
        self.assertEqual(self.validate([execute([group(), group(entity_type=101, ability=8)])]),
                         encode_player_input(self.match.identities_by_slot[0]))

    def test_mixed_groups_preserve_valid_groups_action_order_queue_and_target(self):
        before = execute([group([42])])
        target = field_bytes(2, field_uint(1, 90) + field_uint(2, 1) + field_uint(3, 1))
        valid = [group([42, 43]), group([44], entity_type=101, ability=8)]
        mixed = execute([group(), valid[0], group(entity_type=101, ability=8), valid[1]],
                        queued=True, target=target)
        after = execute([group([43])], queued=True)
        result = self.validate([before, execute([group()]), mixed, after])
        expected = (before, execute(valid, queued=True, target=target), after)
        self.assertEqual(get_repeated_bytes(result, 2), expected)
        self.assertEqual(get_bytes(result, 1), self.match.identities_by_slot[0])

    def test_ordinary_nonempty_command_bytes_are_unchanged(self):
        action = execute([group([42, 43]), group([44], entity_type=101, ability=8)], queued=True)
        self.assertEqual(get_repeated_bytes(self.validate([action]), 2), (action,))

    def test_empty_group_does_not_hide_later_foreign_entity(self):
        with self.assertRaisesRegex(InputError, 'not owned by this player/type'):
            self.validate([execute([group(), group([90])])])

    def test_empty_group_does_not_hide_later_unknown_ability(self):
        with self.assertRaisesRegex(InputError, 'ability is not configured'):
            self.validate([execute([group(), group([42], ability=999)])])

    def test_empty_group_does_not_hide_later_entity_type_missing_from_deck(self):
        with self.assertRaisesRegex(InputError, 'absent from selected deck'):
            self.validate([execute([group(), group([42], entity_type=108)])])

    def test_empty_group_still_requires_a_configured_ability_and_selected_type(self):
        for value, reason in [(group(ability=999), 'ability is not configured'),
                              (group(entity_type=108), 'absent from selected deck')]:
            with self.subTest(reason=reason), self.assertRaisesRegex(InputError, reason):
                self.validate([execute([value])])

    def test_duplicate_entity_ids_remain_rejected(self):
        with self.assertRaisesRegex(InputError, 'unique uint32 list'):
            self.validate([execute([group([42, 42])])])

    def test_uint32_overflow_remains_rejected_before_command_normalization(self):
        with self.assertRaisesRegex(InputError, 'uint32 input overflow'):
            self.validate([execute([group(), group([1 << 32])])])

    def test_oversized_entity_lists_remain_rejected_before_normalization(self):
        with self.assertRaisesRegex(InputError, 'packed scalar count limit'):
            self.validate([execute([group(), group([42] * 4097)])])

    def test_split_packed_entity_lists_cannot_bypass_total_count_limit(self):
        # Each packed occurrence individually fits the descriptor bound.
        # The aggregate list must still obey the command's4096-value limit.
        oversized = group([42] * 4096) + field_packed_uint(3, [42])
        with self.assertRaisesRegex(InputError, 'packed scalar count limit'):
            self.validate([execute([group(), oversized])])

    def test_excessive_group_and_action_counts_remain_rejected(self):
        with self.assertRaisesRegex(InputError, 'bounded entity groups'):
            self.validate([execute([group()] * 257)])
        with self.assertRaisesRegex(InputError, 'too many input actions'):
            self.validate([execute([group()])] * 257)

    def test_input_size_bound_remains_enforced(self):
        with self.assertRaisesRegex(InputError, 'invalid input slot/size'):
            self.validator.validate_player_input(0, b'\0' * (MAX_INPUT_BYTES + 1))

    def test_retained_dead_owned_unit_is_still_accepted(self):
        action = execute([group([99])])
        self.assertEqual(get_repeated_bytes(self.validate([action]), 2), (action,))


if __name__ == '__main__':
    unittest.main()
