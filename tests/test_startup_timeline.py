import copy
import hashlib
from pathlib import Path
import unittest

from tests.test_startup_tasks import render, trace
from client_patch.patcher import startup_tasks as startup_hooks
from tools import startup_task_evidence
from tools.analyze_startup_trace import analyze, analyze_qualification


class StartupTimelineTests(unittest.TestCase):
    def fixture(self):
        text = render(trace())
        sources = {name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                   for name, module in (('tools/startup_task_evidence.py', startup_task_evidence),
                                        ('client_patch/patcher/startup_tasks.py', startup_hooks))}
        report = dict(passed=True, natural_exit=True, forced_cleanup=False, exit_code=0,
                      source_files_unchanged=True, shared_settings_unchanged=True, launch_tick=50,
                      installed_diagnostics=dict(startup_tasks=True),
                      source_sha256_at_start=sources, source_sha256_at_finish=dict(sources),
                      trace=[dict(thread=17)], startup_tasks=startup_task_evidence.evidence(text, thread=17))
        return text, report

    def test_wraps_known_intervals_and_labels_without_claiming_causality(self):
        text, report = self.fixture()
        result = analyze_qualification(text, report)
        self.assertEqual(result['launch_to_first_hook_ms'], 50)
        self.assertEqual(len(result['wrapped_table_intervals']), 12)
        self.assertEqual(result['wrapped_table_intervals'][0]['label'], 'PlayerInputActionTable')
        self.assertEqual(result['wrapped_table_intervals'][0]['interval_ms'], 1)
        self.assertEqual(result['first_all_succeeded_sample_to_ready_ms'], 1)
        self.assertEqual(result['task_samples'][0]['pending'][12]['label'], 'LoadAll[0]')
        self.assertEqual(result['task_samples'][0]['pending'][-1]['label'], 'PreMenu WhenAll')
        self.assertFalse(result['cause_proven'])
        self.assertFalse(result['task_statuses_are_atomic'])

    def test_rejects_wrong_launch_or_reversed_sample_clock(self):
        for tick in (True, -1, 101):
            with self.subTest(tick=tick), self.assertRaises(AssertionError):
                analyze(render(trace()), launch_tick=tick, thread=17)
        rows = trace()
        next(row for row in rows if row['event'] == 'snapshot')['tick'] = 100
        with self.assertRaises(AssertionError):
            analyze(render(rows), launch_tick=50, thread=17)

    def test_rejects_terminal_task_regression_or_lost_capture(self):
        for status in (-1, 6, 7):
            rows = trace()
            next(row for row in rows if row['event'] == 'snapshot')['status'][0] = status
            # Earlier validator qualifies completion; the timing reader must
            # additionally reject contradictory intermediate Task observations.
            startup_task_evidence.evidence(render(rows), thread=17)
            with self.subTest(status=status), self.assertRaises(AssertionError):
                analyze(render(rows), launch_tick=50, thread=17)

    def test_incomplete_or_failed_native_runs_cannot_be_promoted(self):
        text, report = self.fixture()
        for field, value in (('passed', False), ('natural_exit', False), ('forced_cleanup', True),
                             ('source_files_unchanged', False), ('exit_code', 1)):
            changed = copy.deepcopy(report)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                analyze_qualification(text, changed)
        rows = trace()
        rows[-1]['reason'] = 'deadline'
        with self.assertRaises(AssertionError):
            analyze(render(rows), launch_tick=50, thread=17)

    def test_raw_trace_and_validator_identity_must_match_qualification(self):
        text, report = self.fixture()
        for name in ('tools/startup_task_evidence.py', 'client_patch/patcher/startup_tasks.py'):
            changed = copy.deepcopy(report)
            changed['source_sha256_at_start'][name] = changed['source_sha256_at_finish'][name] = '0'*64
            with self.subTest(source=name), self.assertRaises(AssertionError):
                analyze_qualification(text, changed)
        changed = copy.deepcopy(report)
        changed['startup_tasks']['task_count'] = 1
        with self.assertRaises(AssertionError):
            analyze_qualification(text, changed)


if __name__ == '__main__':
    unittest.main()
