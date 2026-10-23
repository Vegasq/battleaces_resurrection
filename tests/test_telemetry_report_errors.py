"""Reject incomplete or misleading error-reporter evidence and stale guards."""
import unittest
from tools.telemetry_report_error_evidence import validate,ENTRIES
from client_patch.patcher.telemetry import COMPONENTS
from tools.verify_telemetry_audit import verify_lines
from tests.test_telemetry_audit import fixture,SHA


def text():
    lines=['[100] TELEMETRY REPORTERROR begin: version=1 thread=17 genuineClient=1 genuineException=1']
    for index,rva in enumerate(ENTRIES,1):
        lines.append(f'[{100+index}] TELEMETRY REPORTERROR call: version=1 thread=17 index={index} rva={rva:x} returned=1 clientStable=1 exceptionStable=1')
    lines.append('[108] TELEMETRY REPORTERROR probe passed: version=1 thread=17 calls=7 genuineClient=1 genuineException=1 nullOptionalInputs=1 clientFieldsUnchanged=1 globalCallbackHeadsUnchanged=4 originalUnityExceptionLog=1 reportDelivered=0 wholeRunIsolation=0')
    return '\n'.join(lines)

ROWS=[dict(event='OnConfirm.dispatch',thread=17,tick=120)]


class ReportErrorsTests(unittest.TestCase):
    def test_complete_control_remains_bounded(self):
        proof=validate(text(),ROWS)
        self.assertEqual(proof['entries'],list(ENTRIES))
        self.assertFalse(proof['whole_run_privacy_qualified'])
        self.assertFalse(proof['resumed_or_inflight_delivery_qualified'])

    def test_missing_reordered_changed_duplicate_or_incomplete_input_rejects(self):
        lines=text().splitlines()
        invalid=['\n'.join(lines[:i]+lines[i+1:]) for i in range(len(lines))]
        invalid += [text()+'\n'+lines[1],text().replace('rva=815ba0','rva=8157d0'),
                    text().replace('index=4','index=3'),text().replace('clientStable=1','clientStable=0'),
                    text().replace('globalCallbackHeadsUnchanged=4','globalCallbackHeadsUnchanged=3'),
                    text().replace('originalUnityExceptionLog=1','originalUnityExceptionLog=0'),
                    text().replace('reportDelivered=0','reportDelivered=1'),text().replace('[108]','[121]'),
                    text().replace('index=4 rva=8153e0','index=4 rva=814880'),
                    text().replace('version=1 thread=17 index=2','version=1 thread=18 index=2'),
                    '\n'.join([lines[0],lines[2],lines[1],*lines[3:]])]
        for bad in invalid:
            with self.subTest(bad=bad[-90:]),self.assertRaises(AssertionError):validate(bad,ROWS)
        for rows in ([],ROWS*2,[dict(event='OnConfirm.dispatch',thread=17,tick=True)],
                     [dict(event='OnConfirm.dispatch',thread=18,tick=120)]):
            with self.assertRaises(AssertionError):validate(text(),rows)

    def test_all_instance_and_queued_collector_entries_guarded(self):
        patches={p.rva:p for p in COMPONENTS['GameAssembly.dll'].patches}
        for rva in ENTRIES:
            self.assertIn(rva,patches)
            self.assertEqual(patches[rva].replacement,b'\xc3')
        # Local diagnostics and common exception/GC APIs must stay original.
        for rva in (0x502fa60,0x35d90e0,0x848370):self.assertNotIn(rva,patches)

    def test_new_audit_requires_all_report_guards_and_legacy_never_implies_them(self):
        for old in (20,21):
            self.assertFalse(verify_lines(fixture(recipe_version=old),expected_sha256=SHA)['passed'])
            self.assertTrue(verify_lines(fixture(recipe_version=old),expected_sha256=SHA,recipe_version=old)['passed'])
        for replacement in ('',' reportErrorSignatures=6/6',' reportErrorSignatures=8/7'):
            lines=[line.replace(' reportErrorSignatures=7/7',replacement) for line in fixture()]
            self.assertFalse(verify_lines(lines,expected_sha256=SHA)['passed'])
