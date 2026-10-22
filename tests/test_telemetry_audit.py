"""Authored log fixtures; no game data, file access, runtime or networking."""
import unittest

from tools.verify_telemetry_audit import DEFAULT_STAGES, verify_lines
from client_patch.patcher.telemetry import RECIPE_VERSION

SHA = 'a' * 64
ORIGINAL = 'ac144d56d53f07904d52ed27a1539de90bc3290038fe52d73d2f6b268c85d6bc'


def fixture(stages=DEFAULT_STAGES,*,recipe_version=RECIPE_VERSION):
    core={3:12,4:14,5:15,6:16,7:18,8:21,9:25,10:27,11:28}[recipe_version]
    lines = [f'[100] Telemetry audit build verified: UnityPlayer sha256={SHA} '
             f'normalized={ORIGINAL} crashSignatures=3/3 coreCandidateSignatures={core}/{core} '
             'performanceCandidateSignatures=3/3; READ ONLY, no qualification claim']
    for sequence, stage in enumerate(stages, 1):
        prefix = f'[{100 + sequence}] Telemetry audit {sequence}'
        lines.extend([
            f'{prefix}/17 stage={stage} retained main=1 session=1 performance=1 callbackHooks main=0 performance=0',
            f'{prefix} main: state_8=0 init_e10_nonzero=0 archiveFlush_480_nonzero=0 worker_4e0_present=0 '
            'registered_15c0=0 registered_1650=0 enabled_1651=0 deviceStats_15c3=0 preinitQueueCount=0',
            f'{prefix} session: registered_8=0 state_c_nonzero=0 value_10_nonzero=0 value_20_nonzero=0',
            f'{prefix} performance: registered_0=0 enabled_9=0',
            f'{prefix} snapshotEnd singletonPointersStable=1; scalar observations are not atomic or network evidence',
        ])
    return lines


class TelemetryAuditTests(unittest.TestCase):
    def test_legacy_samples_require_explicit_legacy_recipe_and_never_validate_current(self):
        for version in (3,4,5,6,7,8,9,10):
            old=fixture(recipe_version=version)
            self.assertFalse(verify_lines(old,expected_sha256=SHA)['passed'])
            result=verify_lines(old,expected_sha256=SHA,recipe_version=version)
            self.assertTrue(result['passed']);self.assertEqual(result['recipe_version'],version)
            self.assertFalse(verify_lines(fixture(),expected_sha256=SHA,recipe_version=version)['passed'])
        for version in (True,2,12,'4'):
            with self.subTest(version=version),self.assertRaises(ValueError):
                verify_lines(fixture(),expected_sha256=SHA,recipe_version=version)

    def test_pre_quit_must_be_a_single_final_snapshot(self):
        path=DEFAULT_STAGES+('pre-quit-confirm',)
        self.assertTrue(verify_lines(fixture(path),expected_sha256=SHA,required_stages=path)['passed'])
        for stages in (path+('menu',),path+('pre-quit-confirm',)):
            result=verify_lines(fixture(stages),expected_sha256=SHA,required_stages=path)
            self.assertFalse(result['passed'])
            self.assertIn('duplicate_or_nonfinal_quit_boundary',[error['code'] for error in result['errors']])

    def check(self, lines):
        return verify_lines(lines, expected_sha256=SHA)

    def rejects(self, lines, code):
        report = self.check(lines)
        self.assertFalse(report['passed'])
        self.assertIn(code, [error['code'] for error in report['errors']])

    def test_complete_ordered_rematch_and_repeated_samples(self):
        stages = tuple(stage for stage in DEFAULT_STAGES for _ in range(2) if stage != 'startup-after-engine-init')
        report = self.check(['Unrelated game log\n', *fixture(('startup-after-engine-init',) + stages)])
        self.assertTrue(report['passed'])
        self.assertEqual(report['complete_snapshots'], 13)
        self.assertEqual(report['observed_entries'], list(DEFAULT_STAGES))

    def test_two_final_result_samples_do_not_prove_two_results(self):
        self.rejects(fixture(('startup-after-engine-init', 'menu', 'menu', 'menu', 'postgame', 'postgame')),
                     'missing_ordered_stage_coverage')

    def test_missing_truncated_duplicate_and_orphan_components(self):
        lines = fixture()
        self.rejects(lines[:3] + lines[4:], 'missing_component')
        self.rejects(lines[:-1], 'incomplete_final_snapshot')
        self.rejects(lines[:3] + [lines[2]] + lines[3:], 'duplicate_component')
        self.rejects([lines[0], lines[2], *lines[1:]], 'orphan_component')
        self.rejects(lines[:3] + lines[6:], 'unfinished_snapshot')

    def test_wrong_hash_partial_guard_group_and_old_recipe(self):
        lines = fixture()
        self.rejects([lines[0].replace(SHA, 'b' * 64), *lines[1:]], 'unsupported_or_partial_build')
        self.rejects([lines[0].replace(ORIGINAL, 'b' * 64), *lines[1:]], 'unsupported_or_partial_build')
        self.rejects([lines[0].replace('28/28', '27/28'), *lines[1:]], 'unsupported_or_partial_build')
        self.rejects([lines[0].replace('28/28', '10/10'), *lines[1:]], 'disabled_or_unrecognized_audit')

    def test_unavailable_nonzero_or_missing_fields_and_objects(self):
        lines = fixture()
        for before, after, code in (
            ('preinitQueueCount=0', 'preinitQueueCount=-1', 'unavailable_or_nondefault_main'),
            ('deviceStats_15c3=0', 'deviceStats_15c3=1', 'unavailable_or_nondefault_main'),
            (' registered_15c0=0', '', 'unavailable_or_nondefault_main'),
            ('registered_0=0 enabled_9=0', 'unavailable (read failed)', 'unavailable_or_nondefault_performance'),
            ('retained main=1', 'retained main=0', 'missing_object_or_active_hook'),
            ('callbackHooks main=0', 'callbackHooks main=1', 'missing_object_or_active_hook'),
            ('singletonPointersStable=1', 'singletonPointersStable=0', 'unstable_singletons'),
        ):
            with self.subTest(after=after):
                self.rejects([line.replace(before, after) for line in lines], code)

    def test_disabling_late_duplicate_build_and_empty_logs_fail(self):
        lines = fixture()
        self.rejects([*lines, '[200] Telemetry audit disabled: thread changed'], 'disabled_or_unrecognized_audit')
        self.rejects([*lines, lines[0].replace('[100]', '[200]')], 'duplicate_or_late_build')
        self.rejects([], 'missing_or_multiple_builds')
        self.rejects(lines[1:], 'snapshot_order_or_budget')

    def test_sequence_time_stage_and_budget_failures(self):
        lines = fixture()
        self.rejects([line.replace('audit 2', 'audit 9') for line in lines], 'snapshot_order_or_budget')
        self.rejects([line.replace('[102]', '[99]') for line in lines], 'timestamp_regression')
        self.rejects([line.replace('stage=ingame', 'stage=unknown') for line in lines], 'invalid_stage')
        self.rejects(fixture(DEFAULT_STAGES + tuple('menu' if i % 2 else 'postgame' for i in range(11))),
                     'snapshot_order_or_budget')

    def test_same_timestamp_transitions_are_accepted(self):
        import re
        lines = [re.sub(r'^\[\d+\]', '[100]', line) for line in fixture()]
        self.assertTrue(self.check(lines)['passed'])

    def test_bounds_and_unrecognized_rows_fail_without_echoing_raw_content(self):
        secret = 'authored-private-placeholder'
        report = self.check([f'[100] Telemetry audit unknown={secret}'])
        self.assertFalse(report['passed'])
        self.assertNotIn(secret, str(report))
        self.rejects(['Telemetry audit ' + 'x' * 2048], 'audit_line_limit')
        self.rejects(['Telemetry audit unknown'] * 129, 'audit_row_limit')

    def test_explicit_tutorial_path_and_invalid_policy(self):
        path = ('startup-after-engine-init', 'menu', 'tutorial', 'menu')
        self.assertTrue(verify_lines(fixture(path), expected_sha256=SHA, required_stages=path)['passed'])
        for path in ((), ('menu',), ('startup-after-engine-init', 'unknown'),
                     ('startup-after-engine-init', 'menu', 'menu')):
            with self.subTest(path=path), self.assertRaises(ValueError):
                verify_lines([], expected_sha256=SHA, required_stages=path)
        with self.assertRaises(ValueError):
            verify_lines([], expected_sha256='invalid')


if __name__ == '__main__':
    unittest.main()
