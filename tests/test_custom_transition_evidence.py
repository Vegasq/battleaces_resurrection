"""Authored C/local/C/public/C native lifecycle fixtures."""
import unittest

from tools.custom_transition_evidence import validate


class CustomTransitionEvidenceTests(unittest.TestCase):
    def fixture(self, role='host'):
        matches = [str(value)*32 for value in (1, 3, 4, 5)]
        lines = []
        for stage in range(1, 6):
            lines.append(f'CUSTOM TRANSITION stage released: stage={stage} role={role}')
            if stage in (1, 3, 5):
                match = matches[{1: 0, 3: 1, 5: 3}[stage]]
                action = 'host native picker Invite' if role == 'host' else 'guest native Accept'
                lines += ['COMMUNITY MATCH SMOKE '+action,
                    f'Client world acquired: generation={stage} owner=remote match={match}',
                    f'Community native custom match joined: lobby=fixture match={match} epoch=1 seat=0',
                    'Dedicated native EndOfGameResponse delivered;',
                    'COMMUNITY MATCH SMOKE native Continue (NOT manual UI input)',
                    f'Client world released: generation={stage} owner=remote nativeIdle=1',
                    f'Community native match return: match={match} lobby=fixture',
                    'Community native lobby restored: lobby=fixture',
                    f'CUSTOM TRANSITION Custom returned: stage={stage} role={role} lobby=fixture party=2 nativeIdle=1',
                    f'CUSTOM TRANSITION original Leave dispatched: stage={stage} role={role}',
                    f'CUSTOM TRANSITION departed: stage={stage} role={role} party=0 prediction=0 pending=0 nativeIdle=1']
            elif stage == 2:
                lines += ['Client world acquired: generation=2 owner=local-practice match=',
                    'Practice requested: match='+'2'*32+' mode=4 standalone=1',
                    'PRACTICE SMOKE original EditDeck mode4 callback:',
                    'Practice native EndOfGameResponse delivered;',
                    'PRACTICE SMOKE native Continue (automated)',
                    'Client world released: generation=2 owner=local-practice nativeIdle=1',
                    'Practice returned: completed=1 mode=4 seat=-1 presenceRetained=0 standalone=1',
                    f'CUSTOM TRANSITION local returned: stage=2 role={role} practiceCompleted=1 nativeIdle=1']
            else:
                lines += ['Public search intent: ticket=1 mode=1 originalSearch=1',
                    f'Public match assignment: ticket=1 match={matches[2]} mode=1',
                    f'Client world acquired: generation=4 owner=remote match={matches[2]}',
                    'Public native match joined:', 'Practice native EndOfGameResponse delivered;',
                    'DEDICATED REMATCH SMOKE automated original MatchResultVM.OnContinue;',
                    'Public result Continue routed: mode=1 source=remote next=End',
                    'Client world released: generation=4 owner=remote nativeIdle=1',
                    'Public native return: ticket=1 match='+matches[2],
                    'Public intent retired: ticket=1 reason=returned nativeIdle=1 disconnect=0',
                    f'CUSTOM TRANSITION public returned: stage=4 role={role} publicCompleted=1 nativeIdle=1']
        lines.append(f'CUSTOM TRANSITION complete: stages=C,local4,C,public1,C role={role} worlds=5 BA_RESURRECTION_CUSTOM_TRANSITION_V1')
        return ''.join(f'[{index+1}] {line}\n' for index, line in enumerate(lines)), matches

    def test_both_original_roles_and_windows_lines(self):
        for role in ('host', 'guest'):
            for newline in ('\n', '\r\n'):
                log, matches = self.fixture(role)
                proof = validate(log.replace('\n', newline), role, matches)
                self.assertEqual(proof['original_continues'], 5)
                self.assertFalse(proof['physical_native_quit_bundled_protected_or_lan_qualified'])

    def test_missing_leave_prediction_teardown_or_original_invite_is_rejected(self):
        for old, new in (('original Leave dispatched: stage=3', 'other Leave: stage=3'),
                         ('party=0 prediction=0 pending=0', 'party=0 prediction=1 pending=0'),
                         ('host native picker Invite', 'direct wire Invite')):
            log, matches = self.fixture()
            with self.subTest(marker=old), self.assertRaises(AssertionError):
                validate(log.replace(old, new), 'host', matches)

    def test_stale_world_duplicate_remote_fallback_and_missing_continue_are_rejected(self):
        for old, new in (('generation=3', 'generation=1'),
                         ('PRACTICE SMOKE native Continue (automated)', 'other local callback'),
                         ('Public result Continue routed:', 'different result path:'),
                         ('CUSTOM TRANSITION complete:', 'Public fallback accepted:')):
            log, matches = self.fixture()
            with self.subTest(marker=old), self.assertRaises(AssertionError):
                validate(log.replace(old, new), 'host', matches)

    def test_reordered_stage_and_wrong_remote_match_are_rejected(self):
        log, matches = self.fixture()
        for change in ('reordered', 'wrong_match'):
            with self.subTest(change=change), self.assertRaises(AssertionError):
                if change == 'reordered':
                    validate(log.replace('stage=3 role=host', 'stage=9 role=host'), 'host', matches)
                else:
                    validate(log, 'host', matches[:3]+['9'*32])

    def test_custom_result_requires_its_original_dedicated_label(self):
        log, matches = self.fixture()
        with self.assertRaises(AssertionError):
            validate(log.replace('Dedicated native EndOfGameResponse delivered;', 'Practice native EndOfGameResponse delivered;'), 'host', matches)


if __name__ == '__main__':
    unittest.main()
