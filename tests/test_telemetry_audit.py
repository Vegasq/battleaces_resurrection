"""Authored log fixtures; no game data, file access, runtime or networking."""
import unittest

from tools.verify_telemetry_audit import DEFAULT_STAGES, verify_lines
from client_patch.patcher.telemetry import RECIPE_VERSION

SHA = 'a' * 64
ORIGINAL = 'ac144d56d53f07904d52ed27a1539de90bc3290038fe52d73d2f6b268c85d6bc'


def fixture(stages=DEFAULT_STAGES,*,recipe_version=RECIPE_VERSION):
    core={3:12,4:14,5:15,6:16,7:18,8:21,9:25,10:27,11:28,12:31,13:40,14:48,15:53,16:53,17:56,18:56,19:56,20:56,21:56,22:56,23:56,24:56,25:56,26:56,27:56,28:56,29:56,30:56,31:56,32:56,33:56,34:56,35:56,36:56,37:56,38:56,39:57,40:58,44:58,45:58,46:58,47:59}[recipe_version]
    crash=4 if recipe_version>=23 else 3
    lines = [f'[100] Telemetry audit build verified: UnityPlayer sha256={SHA} '
             f'normalized={ORIGINAL} crashSignatures={crash}/{crash} coreCandidateSignatures={core}/{core} '
             f'performanceCandidateSignatures=3/3'+(' cacheFailureSignatures=5/5' if recipe_version>=16 else '')+(' serviceIdentitySignatures=2/2' if recipe_version==18 else '')+(f' serviceProfileSignatures=2/2 recipeVersion={recipe_version}' if recipe_version>=19 else '')+(' automaticCollectorSignatures=1/1' if recipe_version>=20 else '')+(' sdkInitializationSignatures=6/6' if recipe_version>=21 else '')+(' reportErrorSignatures=7/7' if recipe_version>=22 else '')+(f' reporterCallbackSignatures={7 if recipe_version>=26 else 3}/{7 if recipe_version>=26 else 3}' if recipe_version>=25 else '')+(' reporterEnabledSignatures=2/2' if recipe_version>=27 else '')+(' reporterRegistrationSignatures=1/1' if recipe_version>=28 else '')+(' networkBreadcrumbSignatures=1/1' if recipe_version>=29 else '')+(' breadcrumbCollectorSignatures=3/3' if recipe_version>=30 else '')+(' breadcrumbFacadeSignatures=2/2' if recipe_version>=31 else '')+(' sdkDataIngressSignatures=10/10' if recipe_version>=32 else '')+(' sdkContextSignatures=2/2' if recipe_version>=33 else '')+(' sdkMetadataMergeSignatures=2/2' if recipe_version>=34 else '')+(' sdkConfigurationIngressSignatures=6/6' if recipe_version>=35 else '')+(' sdkSceneMetadataSignatures=1/1' if recipe_version>=36 else '')+'; READ ONLY, no qualification claim']
    if recipe_version >= 37:
        lines[0] = lines[0].replace('; READ ONLY, no qualification claim',
                                  ' sdkUserCacheSignatures=1/1; READ ONLY, no qualification claim')
    if recipe_version >= 38:
        lines[0] = lines[0].replace('; READ ONLY, no qualification claim',
                                  ' sdkSessionCacheSignatures=1/1; READ ONLY, no qualification claim')
    if recipe_version in (44,45,46,47):
        lines[0] = lines[0].replace('; READ ONLY, no qualification claim',
                                  f' sdkCacheReaderSignatures={5 if recipe_version>=45 else 4}/{5 if recipe_version>=45 else 4}; READ ONLY, no qualification claim')
    if recipe_version >= 46:
        lines[0] = lines[0].replace('; READ ONLY, no qualification claim',
                                  ' sdkCacheDirectorySignatures=1/1; READ ONLY, no qualification claim')
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
    def test_recipe46_requires_cache_directory_guard(self):
        lines=fixture(recipe_version=46)
        self.assertTrue(verify_lines(lines,expected_sha256=SHA,recipe_version=46)['passed'])
        for value in ('', ' sdkCacheDirectorySignatures=0/1', ' sdkCacheDirectorySignatures=1/2'):
            changed=[lines[0].replace(' sdkCacheDirectorySignatures=1/1',value),*lines[1:]]
            with self.subTest(value=value):
                self.assertFalse(verify_lines(changed,expected_sha256=SHA,recipe_version=46)['passed'])

    def test_recipe45_requires_delete_guard(self):
        lines=fixture(recipe_version=45)
        self.assertTrue(verify_lines(lines,expected_sha256=SHA,recipe_version=45)['passed'])
        for value in ('', ' sdkCacheReaderSignatures=4/4', ' sdkCacheReaderSignatures=4/5'):
            changed=[lines[0].replace(' sdkCacheReaderSignatures=5/5',value),*lines[1:]]
            with self.subTest(value=value):
                self.assertFalse(verify_lines(changed,expected_sha256=SHA,recipe_version=45)['passed'])

    def test_current_recipe_requires_cache_reader_guards(self):
        lines=fixture(recipe_version=44)
        self.assertTrue(verify_lines(lines,expected_sha256=SHA,recipe_version=44)['passed'])
        for value in ('', ' sdkCacheReaderSignatures=0/4', ' sdkCacheReaderSignatures=4/5'):
            changed=[lines[0].replace(' sdkCacheReaderSignatures=4/4',value),*lines[1:]]
            with self.subTest(value=value):
                self.assertFalse(verify_lines(changed,expected_sha256=SHA,recipe_version=44)['passed'])

    def test_recipe38_requires_session_cache_guard(self):
        lines=fixture()
        for value in ('', ' sdkSessionCacheSignatures=0/1',
                      ' sdkSessionCacheSignatures=1/2'):
            changed=[lines[0].replace(' sdkSessionCacheSignatures=1/1',value),*lines[1:]]
            with self.subTest(value=value):
                self.assertFalse(verify_lines(changed,expected_sha256=SHA)['passed'])
        self.assertTrue(verify_lines(fixture(recipe_version=37),expected_sha256=SHA,recipe_version=37)['passed'])

    def test_recipe37_requires_user_cache_guard(self):
        lines=fixture()
        for value in ('', ' sdkUserCacheSignatures=0/1',
                      ' sdkUserCacheSignatures=1/2'):
            changed=[lines[0].replace(' sdkUserCacheSignatures=1/1',value),*lines[1:]]
            with self.subTest(value=value):
                self.assertFalse(verify_lines(changed,expected_sha256=SHA)['passed'])
        self.assertTrue(verify_lines(fixture(recipe_version=36),expected_sha256=SHA,recipe_version=36)['passed'])

    def test_recipe36_requires_scene_metadata_guard(self):
        lines=fixture()
        for value in ('', ' sdkSceneMetadataSignatures=0/1',
                      ' sdkSceneMetadataSignatures=1/2'):
            changed=[lines[0].replace(' sdkSceneMetadataSignatures=1/1',value),*lines[1:]]
            with self.subTest(value=value):
                self.assertFalse(verify_lines(changed,expected_sha256=SHA)['passed'])
        self.assertTrue(verify_lines(fixture(recipe_version=35),expected_sha256=SHA,recipe_version=35)['passed'])

    def test_recipe35_requires_six_configuration_ingress_guards(self):
        lines=fixture()
        for value in ('', ' sdkConfigurationIngressSignatures=0/6',
                      ' sdkConfigurationIngressSignatures=5/6',
                      ' sdkConfigurationIngressSignatures=6/5'):
            changed=[lines[0].replace(' sdkConfigurationIngressSignatures=6/6',value),*lines[1:]]
            with self.subTest(value=value):
                self.assertFalse(verify_lines(changed,expected_sha256=SHA)['passed'])
        self.assertTrue(verify_lines(fixture(recipe_version=34),expected_sha256=SHA,recipe_version=34)['passed'])

    def test_recipe34_requires_both_sdk_metadata_merge_guards(self):
        lines=fixture()
        for value in ('', ' sdkMetadataMergeSignatures=0/2',
                      ' sdkMetadataMergeSignatures=1/2',
                      ' sdkMetadataMergeSignatures=2/3'):
            changed=[lines[0].replace(' sdkMetadataMergeSignatures=2/2',value),*lines[1:]]
            with self.subTest(value=value):
                self.assertFalse(verify_lines(changed,expected_sha256=SHA)['passed'])
        self.assertTrue(verify_lines(fixture(recipe_version=33),expected_sha256=SHA,recipe_version=33)['passed'])

    def test_recipe33_requires_both_sdk_context_guards(self):
        lines=fixture()
        for value in ('', ' sdkContextSignatures=0/2',
                      ' sdkContextSignatures=1/2',
                      ' sdkContextSignatures=2/3'):
            changed=[lines[0].replace(' sdkContextSignatures=2/2',value),*lines[1:]]
            with self.subTest(value=value):
                self.assertFalse(verify_lines(changed,expected_sha256=SHA)['passed'])
        self.assertTrue(verify_lines(fixture(recipe_version=32),expected_sha256=SHA,recipe_version=32)['passed'])

    def test_recipe32_requires_all_ten_sdk_data_ingress_guards(self):
        lines=fixture()
        for value in ('', ' sdkDataIngressSignatures=0/10',
                      ' sdkDataIngressSignatures=9/10',
                      ' sdkDataIngressSignatures=10/9'):
            changed=[lines[0].replace(' sdkDataIngressSignatures=10/10',value),*lines[1:]]
            with self.subTest(value=value):
                self.assertFalse(verify_lines(changed,expected_sha256=SHA)['passed'])
        previous=fixture(recipe_version=31)
        self.assertTrue(verify_lines(previous,expected_sha256=SHA,recipe_version=31)['passed'])

    def test_recipe31_requires_both_breadcrumb_facades(self):
        lines=fixture()
        for value in ('', ' breadcrumbFacadeSignatures=0/2',
                      ' breadcrumbFacadeSignatures=1/2',
                      ' breadcrumbFacadeSignatures=2/3'):
            changed=[lines[0].replace(' breadcrumbFacadeSignatures=2/2',value),*lines[1:]]
            with self.subTest(value=value):
                self.assertFalse(verify_lines(changed,expected_sha256=SHA)['passed'])
        previous=fixture(recipe_version=30)
        self.assertTrue(verify_lines(previous,expected_sha256=SHA,recipe_version=30)['passed'])

    def test_recipe30_requires_breadcrumb_collector_guards(self):
        lines=fixture()
        for value in ('', ' breadcrumbCollectorSignatures=0/3',
                      ' breadcrumbCollectorSignatures=2/3',
                      ' breadcrumbCollectorSignatures=3/2'):
            changed=[lines[0].replace(' breadcrumbCollectorSignatures=3/3',value),*lines[1:]]
            with self.subTest(value=value):
                self.assertFalse(verify_lines(changed,expected_sha256=SHA)['passed'])
        previous=fixture(recipe_version=29)
        self.assertTrue(verify_lines(previous,expected_sha256=SHA,recipe_version=29)['passed'])

    def test_recipe29_requires_network_breadcrumb_guard(self):
        lines=fixture()
        for value in ('', ' networkBreadcrumbSignatures=0/1',
                      ' networkBreadcrumbSignatures=1/2'):
            changed=[lines[0].replace(' networkBreadcrumbSignatures=1/1',value),*lines[1:]]
            with self.subTest(value=value):
                self.assertFalse(verify_lines(changed,expected_sha256=SHA)['passed'])
        previous=fixture(recipe_version=28)
        self.assertTrue(verify_lines(previous,expected_sha256=SHA,recipe_version=28)['passed'])

    def test_recipe28_requires_reporter_registration_guard(self):
        lines=fixture()
        for value in ('', ' reporterRegistrationSignatures=0/1',
                      ' reporterRegistrationSignatures=1/2'):
            changed=[lines[0].replace(' reporterRegistrationSignatures=1/1',value),*lines[1:]]
            with self.subTest(value=value):
                self.assertFalse(verify_lines(changed,expected_sha256=SHA)['passed'])
        previous=fixture(recipe_version=27)
        self.assertTrue(verify_lines(previous,expected_sha256=SHA,recipe_version=27)['passed'])

    def test_recipe27_requires_both_reporter_enabled_guards(self):
        lines=fixture()
        for value in ('', ' reporterEnabledSignatures=0/2',
                      ' reporterEnabledSignatures=1/2',
                      ' reporterEnabledSignatures=2/3'):
            changed=[lines[0].replace(' reporterEnabledSignatures=2/2',value),*lines[1:]]
            with self.subTest(value=value):
                self.assertFalse(verify_lines(changed,expected_sha256=SHA)['passed'])
        prior=fixture(recipe_version=26)
        self.assertTrue(verify_lines(prior,expected_sha256=SHA,recipe_version=26)['passed'])

    def test_current_requires_seven_reporter_callback_guards(self):
        lines=fixture()
        for value in ('', ' reporterCallbackSignatures=0/7',
                      ' reporterCallbackSignatures=6/7',
                      ' reporterCallbackSignatures=7/3',
                      ' reporterCallbackSignatures=3/3'):
            changed=[lines[0].replace(' reporterCallbackSignatures=7/7',value),*lines[1:]]
            with self.subTest(value=value):
                self.assertFalse(verify_lines(changed,expected_sha256=SHA)['passed'])
        prior=fixture(recipe_version=25)
        self.assertTrue(verify_lines(prior,expected_sha256=SHA,recipe_version=25)['passed'])
        self.assertFalse(verify_lines(prior,expected_sha256=SHA)['passed'])
        old=fixture(recipe_version=24)
        self.assertTrue(verify_lines(old,expected_sha256=SHA,recipe_version=24)['passed'])
        self.assertFalse(verify_lines(old,expected_sha256=SHA)['passed'])

    def test_current_requires_all_four_crash_guards_and_exact_denominator(self):
        lines=fixture()
        for value in ('3/3','3/4','4/3','4/5','5/4','0/4'):
            changed=[lines[0].replace('crashSignatures=4/4','crashSignatures='+value),*lines[1:]]
            with self.subTest(value=value):
                self.assertFalse(verify_lines(changed,expected_sha256=SHA)['passed'])
        old=fixture(recipe_version=22)
        self.assertTrue(verify_lines(old,expected_sha256=SHA,recipe_version=22)['passed'])
        self.assertFalse(verify_lines(old,expected_sha256=SHA)['passed'])

    def test_legacy_samples_require_explicit_legacy_recipe_and_never_validate_current(self):
        for version in range(3,41):
            old=fixture(recipe_version=version)
            self.assertFalse(verify_lines(old,expected_sha256=SHA)['passed'])
            result=verify_lines(old,expected_sha256=SHA,recipe_version=version)
            self.assertTrue(result['passed']);self.assertEqual(result['recipe_version'],version)
            self.assertFalse(verify_lines(fixture(),expected_sha256=SHA,recipe_version=version)['passed'])
        for version in (True,2,41,42,43,RECIPE_VERSION+1,'4'):
            with self.subTest(version=version),self.assertRaises(ValueError):
                verify_lines(fixture(),expected_sha256=SHA,recipe_version=version)

    def test_current_requires_both_service_profile_guards_and_rejects_downgrade(self):
        lines=fixture()
        for value in ('',' serviceProfileSignatures=0/2',' serviceProfileSignatures=1/2'):
            changed=[lines[0].replace(' serviceProfileSignatures=2/2',value),*lines[1:]]
            self.assertFalse(self.check(changed)['passed'])
        self.assertFalse(verify_lines(lines,expected_sha256=SHA,recipe_version=18)['passed'])

    def test_current_requires_exact_recipe_tag_even_with_same_guard_counts(self):
        lines=fixture()
        for value in ('',' recipeVersion=18',' recipeVersion=19',' recipeVersion=20',' recipeVersion=21',f' recipeVersion={RECIPE_VERSION+1}'):
            changed=[lines[0].replace(f' recipeVersion={RECIPE_VERSION}',value),*lines[1:]]
            self.assertFalse(self.check(changed)['passed'])

    def test_current_requires_automatic_collector_guard_and_legacy19_is_explicit(self):
        lines=fixture()
        for value in ('',' automaticCollectorSignatures=0/1',
                      ' automaticCollectorSignatures=1/2',
                      ' automaticCollectorSignatures=1/1 automaticCollectorSignatures=1/1'):
            changed=[lines[0].replace(' automaticCollectorSignatures=1/1',value),*lines[1:]]
            self.assertFalse(self.check(changed)['passed'])
        old=fixture(recipe_version=19)
        self.assertTrue(verify_lines(old,expected_sha256=SHA,recipe_version=19)['passed'])
        self.assertFalse(self.check(old)['passed'])

    def test_current_requires_every_constructor_guard_and_never_accepts20_implicitly(self):
        lines=fixture()
        for value in ('',' sdkInitializationSignatures=0/6',' sdkInitializationSignatures=5/6',
                      ' sdkInitializationSignatures=6/7',' sdkInitializationSignatures=6/6 sdkInitializationSignatures=6/6'):
            changed=[lines[0].replace(' sdkInitializationSignatures=6/6',value),*lines[1:]]
            self.assertFalse(self.check(changed)['passed'])
        old=fixture(recipe_version=20)
        self.assertTrue(verify_lines(old,expected_sha256=SHA,recipe_version=20)['passed'])
        self.assertFalse(self.check(old)['passed'])

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
        self.rejects([lines[0].replace('59/59', '58/59'), *lines[1:]], 'unsupported_or_partial_build')
        self.rejects([lines[0].replace('59/59', '10/10'), *lines[1:]], 'disabled_or_unrecognized_audit')

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
