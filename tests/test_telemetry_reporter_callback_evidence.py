import unittest

from tools.telemetry_reporter_callback_evidence import validate


def sample():
    return '\n'.join([
        '[10] TELEMETRY REPORTCALLBACK begin: version=1 thread=42 guards=3 borrowedUnreadable=1',
        '[11] TELEMETRY REPORTCALLBACK call: version=1 thread=42 index=1 rva=3cc3600 returnedFalse=1',
        '[12] TELEMETRY REPORTCALLBACK call: version=1 thread=42 index=2 rva=3cc5440 returnedFalse=1',
        '[13] TELEMETRY REPORTCALLBACK call: version=1 thread=42 index=3 rva=3cc5df0 returnedFalse=1',
        '[14] TELEMETRY REPORTCALLBACK probe passed: version=1 thread=42 calls=3 guards=3 borrowedUnreadable=1 returnedFalse=3 payloadRead=0 callerRegistrationQualified=0 reportDelivered=0',
    ])


def sample_v2():
    entries=('3cc3600','3cc5440','3cc5df0','3cc6930','3cc6a70','3cc3700','3cc4aa0')
    return '\n'.join([
        '[10] TELEMETRY REPORTCALLBACK begin: version=2 thread=42 guards=7 borrowedUnreadable=1',
        *(f'[{11+i}] TELEMETRY REPORTCALLBACK call: version=2 thread=42 index={i+1} rva={rva} returnedFalse=1'
          for i,rva in enumerate(entries)),
        '[18] TELEMETRY REPORTCALLBACK probe passed: version=2 thread=42 calls=7 guards=7 borrowedUnreadable=1 returnedFalse=7 payloadRead=0 callerRegistrationQualified=0 reportDelivered=0',
    ])


class ReporterCallbackEvidenceTests(unittest.TestCase):
    def test_complete(self):
        result=validate(sample(),[dict(event='OnConfirm.dispatch',thread=42,tick=15)])
        self.assertEqual(result['returned_false'],3)
        self.assertFalse(result['callback_registration_qualified'])

    def test_recipe26_all_seven_complete(self):
        result=validate(sample_v2(),[dict(event='OnConfirm.dispatch',thread=42,tick=19)])
        self.assertEqual((result['version'],result['returned_false'],result['loaded_and_disk_guards']),(2,7,7))

    def test_recipe26_missing_or_wrong_new_entry_rejects(self):
        original=sample_v2()
        for changed in (original.replace('rva=3cc6930','rva=3cc6931'),
                        original.replace('guards=7','guards=3',1),
                        original.replace('version=2 thread=42 index=6','version=1 thread=42 index=6'),
                        '\n'.join(original.splitlines()[:-2]+original.splitlines()[-1:])):
            with self.subTest(changed=changed[-65:]),self.assertRaises(AssertionError):
                validate(changed,[dict(event='OnConfirm.dispatch',thread=42,tick=19)])

    def test_missing_or_changed_entry_rejects(self):
        original=sample()
        for changed in (original.replace('rva=3cc5440','rva=3cc5441'),
                        original.replace('thread=42 index=2','thread=43 index=2'),
                        original.replace('returnedFalse=1','returnedFalse=0',1),
                        '\n'.join(original.splitlines()[:-1])):
            with self.subTest(changed=changed[-65:]),self.assertRaises(AssertionError):
                validate(changed,[dict(event='OnConfirm.dispatch',thread=42,tick=15)])

    def test_late_or_wrong_quit_rejects(self):
        for row in (dict(event='OnConfirm.dispatch',thread=43,tick=15),
                    dict(event='OnConfirm.dispatch',thread=42,tick=13)):
            with self.subTest(row=row),self.assertRaises(AssertionError):
                validate(sample(),[row])
