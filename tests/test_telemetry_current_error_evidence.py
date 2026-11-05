"""Reject incomplete recipe44 SDK Client/error fixture records."""
import unittest

from tests.test_telemetry_report_errors import text as errors
from tools.telemetry_current_error_evidence import validate


def fixture():
    return '\n'.join((
        '[90] TELEMETRY CACHEPATH probe passed: version=1 thread=17 getters=4 originalBodies=1 scopedOwnedRoot=1 icallRestored=1 reportEnumeration=0 reportPayloadRead=0 wholeRunIsolation=0',
        '[91] TELEMETRY CACHECLIENT begin: version=1 thread=17 constructorGuards=6 callbackHeads=4',
        '[92] TELEMETRY CACHECLIENT probe passed: version=1 thread=17 nativeCtorCalls=1 clientCtorCalls=1 genuineNativeInterface=1 configurationRetained=1 coreFieldsPresent=14 dependencyGraphMatched=1 idleDelivery=1 globalCallbackHeadsUnchanged=4 reportingDisabled=1 wholeRunIsolation=0',
        errors(),
        '[109] TELEMETRY CURRENTERROR probe passed: version=1 thread=17 genuineClient=1 inMemoryInputs=1 originalCacheReads=0 pathRestored=1 reportDelivered=0',
    ))


ROWS = [dict(event='OnConfirm.dispatch', thread=17, tick=120)]
TELEMETRY = dict(passed=True, recipe_version=44)
REPORT = dict(passed=True, calls=7, thread=17, local_exception_log_retained=True)


class CurrentErrorEvidenceTests(unittest.TestCase):
    def test_recipe45_keeps_current_error_mode_available(self):
        result = validate(fixture(), ROWS, dict(passed=True, recipe_version=45), REPORT)
        self.assertTrue(result['passed'])
        self.assertEqual(result['recipe'], 45)

    def test_complete_owned_sequence(self):
        result = validate(fixture(), ROWS, TELEMETRY, REPORT)
        self.assertTrue(result['passed'])
        self.assertEqual(result['original_cache_reads'], 0)
        self.assertFalse(result['whole_run_privacy_qualified'])

    def test_missing_reordered_disk_or_wrong_recipe_rejects(self):
        lines = fixture().splitlines()
        invalid = ['\n'.join(lines[:i] + lines[i + 1:]) for i in (0, 1, 2, len(lines) - 1)]
        invalid += [fixture().replace('pathRestored=1', 'pathRestored=0'),
                    fixture().replace('inMemoryInputs=1', 'inMemoryInputs=0'),
                    fixture() + '\n[110] TELEMETRY CACHEREADER probe passed:',
                    '\n'.join((lines[1], lines[0], *lines[2:]))]
        for bad in invalid:
            with self.subTest(bad=bad[-75:]), self.assertRaises(AssertionError):
                validate(bad, ROWS, TELEMETRY, REPORT)
        with self.assertRaises(AssertionError):
            validate(fixture(), ROWS, dict(passed=True, recipe_version=40), REPORT)
        with self.assertRaises(AssertionError):
            validate(fixture(), ROWS, TELEMETRY, dict(REPORT, calls=6))


if __name__ == '__main__':
    unittest.main()
