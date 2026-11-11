"""Authored controls for a valid-but-no-op setup not proving identity stability."""
from copy import deepcopy
import unittest

from tools.prediction_setup_identity import BASE_LABELS, classify


def observations():
    result = []
    for frame in range(281):
        labels, state, timer = set(BASE_LABELS), 0, None
        if 140 <= frame < 190:
            labels |= {'Immobile', 'SettingUp'}
            state, timer = 11, (frame-140)*0.05
        elif 190 <= frame < 210:
            labels |= {'Immobile', 'Deployed'}
        elif 210 <= frame < 260:
            labels |= {'Immobile', 'UnsettingUp'}
            state, timer = 11, (frame-210)*0.05
        result.append(dict(frame=frame, labels=sorted(labels), state=state,
                           setup_time=timer, identity=[10, 0, 9, 11]))
    return result


class SetupIdentityTests(unittest.TestCase):
    def test_both_successful_native_setup_cycles_can_support_a_scoped_negative(self):
        result = classify(observations(), [140, 210])
        self.assertTrue(result['passed'])
        self.assertFalse(result['identity_changed'])
        self.assertFalse(result['hidden_allocation_identity_proven'])
        self.assertFalse(result['unity_group_coverage'])
        self.assertFalse(result['full_feature_accepted'])

    def test_a_real_observed_identity_change_is_reported_instead_of_hidden(self):
        rows = observations()
        for row in rows[160:]:
            row['identity'] = [10, 0, 69, 12]
        result = classify(rows, [140, 210])
        self.assertTrue(result['identity_changed'])
        self.assertEqual(result['observed_identities'], [[10, 0, 9, 11], [10, 0, 69, 12]])

    def test_unchanged_identity_without_any_setup_effect_is_inconclusive(self):
        rows = observations()
        for row in rows:
            row.update(labels=sorted(BASE_LABELS), state=0, setup_time=None)
        with self.assertRaises(AssertionError):
            classify(rows, [140, 210])

    def test_either_missing_setup_cycle_is_inconclusive(self):
        for first, last in ((140, 210), (210, 281)):
            rows = observations()
            for row in rows[first:last]:
                row.update(labels=sorted(BASE_LABELS), state=0, setup_time=None)
            with self.subTest(first=first), self.assertRaises(AssertionError):
                classify(rows, [140, 210])

    def test_label_names_without_actual_setup_state_or_advancing_timer_are_refused(self):
        for change in ('state', 'missing', 'flat', 'nonfinite'):
            rows = observations()
            for row in rows[140:190]:
                if change == 'state': row['state'] = 0
                else: row['setup_time'] = None if change == 'missing' else 0.25 if change == 'flat' else float('nan')
            with self.subTest(change=change), self.assertRaises(AssertionError):
                classify(rows, [140, 210])

    def test_finished_labels_and_both_timed_windows_are_required(self):
        for change in ('deployed', 'finished', 'forbidden', 'too_short'):
            rows = observations()
            if change == 'deployed': rows[209]['labels'] = sorted(BASE_LABELS)
            elif change == 'finished': rows[-1]['labels'].append('Immobile')
            elif change == 'forbidden': rows[240]['labels'].append('Deployed')
            else:
                for row in rows[165:190]: row.update(labels=sorted(BASE_LABELS | {'Immobile', 'Deployed'}), state=0)
            with self.subTest(change=change), self.assertRaises(AssertionError):
                classify(rows, [140, 210])

    def test_missing_or_forged_identity_and_nonconsecutive_frames_are_refused(self):
        for change in ('missing', 'bool', 'wrong_subject', 'wrong_initial', 'frame_gap', 'duplicate'):
            rows = observations()
            if change == 'missing': rows[170]['identity'] = None
            elif change == 'bool': rows[170]['identity'][3] = True
            elif change == 'wrong_subject': rows[170]['identity'][0] = 12
            elif change == 'wrong_initial': rows[139]['identity'][2] = 69
            elif change == 'frame_gap': rows.pop(170)
            else: rows[170]['frame'] = 169
            with self.subTest(change=change), self.assertRaises(AssertionError):
                classify(rows, [140, 210])

    def test_wrong_command_schedule_or_idle_boundary_is_refused(self):
        for commands in ([139, 210], [140, 211], [140], [140, True]):
            with self.subTest(commands=commands), self.assertRaises(AssertionError):
                classify(observations(), commands)
        rows = observations()
        rows[209]['state'] = 11
        with self.assertRaises(AssertionError):
            classify(rows, [140, 210])

    def test_observed_original_buffer_completion_boundary_keeps_missing_timer_explicit(self):
        rows = observations()
        for row in rows:
            row['labels'].append('OutOfCombat')
        rows[140]['labels'] = sorted(BASE_LABELS | {'OutOfCombat'})
        rows[190].update(labels=sorted(BASE_LABELS | {'OutOfCombat', 'Immobile', 'SettingUp'}), state=11, setup_time=None)
        rows[210]['labels'] = sorted(BASE_LABELS | {'OutOfCombat', 'Immobile', 'Deployed'})
        rows[260].update(labels=sorted(BASE_LABELS | {'OutOfCombat', 'Immobile', 'UnsettingUp'}), state=11, setup_time=None)
        result = classify(rows, [140, 210])
        self.assertFalse(result['identity_changed'])
        self.assertEqual([phase['timer_completion_boundary'] for phase in result['phases']], [[190], [260]])
        self.assertEqual([phase['timed_samples'] for phase in result['phases']], [49, 49])

    def test_unrelated_labels_or_missing_interior_timers_are_not_completion_boundaries(self):
        for change in ('interior', 'two_edges', 'unknown_baseline', 'baseline_changes'):
            rows = observations()
            if change == 'interior': rows[165]['setup_time'] = None
            elif change == 'two_edges':
                for frame in (190, 191):
                    rows[frame].update(labels=sorted(BASE_LABELS | {'Immobile', 'SettingUp'}), state=11, setup_time=None)
            elif change == 'unknown_baseline':
                for row in rows: row['labels'].append('Big')
            else: rows[-1]['labels'].append('OutOfCombat')
            with self.subTest(change=change), self.assertRaises(AssertionError):
                classify(rows, [140, 210])

    def test_interrupted_phase_backward_timer_and_delayed_completion_cannot_qualify_a_negative(self):
        for change in ('interrupted', 'backward', 'delayed_completion'):
            rows = observations()
            if change == 'interrupted': rows[165].update(labels=sorted(BASE_LABELS), state=0, setup_time=None)
            elif change == 'backward': rows[165]['setup_time'] = 0.01
            else: rows[191]['state'] = 11
            with self.subTest(change=change), self.assertRaises(AssertionError):
                classify(rows, [140, 210])


if __name__ == '__main__':
    unittest.main()
