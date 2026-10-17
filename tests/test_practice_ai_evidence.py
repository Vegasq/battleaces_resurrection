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
