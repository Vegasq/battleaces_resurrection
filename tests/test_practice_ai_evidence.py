import json
import unittest

from tools.verify_practice_ai import movement_evidence


def entity(frame, unit_id, unit_type, x):
    return f'Practice AI entity: frame={frame} army=1 id={unit_id} type={unit_type} position=({x},0,0) health=1200'


def order(unit_id, ability):
    # Original DLL output omits entityType for these commands.
    return 'Practice AI protobuf: ' + json.dumps({'executeCommand': {
        'entityTypeData': [{'entityIds': [unit_id], 'abilityId': ability}],
        'commandData': {'targetGroundCommandData': {'position': {'x': '100'}}}}})


class PracticeEvidenceTests(unittest.TestCase):
    def test_default_type_move_and_attack_resolve_owned_entity_ids(self):
        for ability in (12, 88):
            log = '\n'.join((entity(100, 77, 34, 100), order(77, ability), entity(200, 77, 34, 200)))
            self.assertEqual(movement_evidence(log, {34}), ({77}, {77}))

    def test_rally_or_unobserved_id_does_not_qualify_unit_movement(self):
        log = '\n'.join((entity(100, 77, 34, 100), entity(200, 77, 34, 200), order(77, 9), order(78, 88)))
        self.assertEqual(movement_evidence(log, {34}), ({77}, set()))

    def test_order_without_observed_movement_is_not_enough(self):
        log = '\n'.join((entity(100, 77, 34, 100), entity(200, 77, 34, 100), order(77, 88)))
        moved, ordered = movement_evidence(log, {34})
        self.assertFalse(moved & ordered)

    def test_headquarters_or_non_deck_unit_is_excluded(self):
        log = '\n'.join((entity(100, 5, 3, 100), entity(200, 5, 3, 200), order(5, 88)))
        self.assertEqual(movement_evidence(log, {34}), (set(), set()))

    def test_team_order_must_belong_to_that_bot(self):
        positions = '\n'.join(entity(frame, 77, 34, frame).replace('army=1', 'army=3') for frame in (100, 200))
        action = order(77, 88).split('Practice AI protobuf: ', 1)[1]
        wrong = f'Local AI owned action: identity=2 frame=150 protobuf={action}'
        # An unowned legacy line cannot turn a different bot's order into proof.
        self.assertEqual(movement_evidence(positions+'\n'+wrong+'\n'+order(77, 88), {34}, 3), ({77}, set()))
        correct = f'Local AI owned action: identity=4 frame=150 protobuf={action}'
        self.assertEqual(movement_evidence(positions+'\n'+correct, {34}, 3), ({77}, {77}))

    def test_team_position_must_belong_to_the_same_army(self):
        action = order(77, 12).split('Practice AI protobuf: ', 1)[1]
        log = '\n'.join((entity(100, 77, 34, 100), entity(200, 77, 34, 200),
                         f'Local AI owned action: identity=3 frame=150 protobuf={action}'))
        self.assertEqual(movement_evidence(log, {34}, 2), (set(), set()))
