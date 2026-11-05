"""Reject incomplete authored queue retention records."""
import unittest

from tools.telemetry_current_queue_evidence import validate


def fixture():
    return '\n'.join((
        '[90] TELEMETRY CACHEPATH probe passed: version=1 thread=17 getters=4 originalBodies=1 scopedOwnedRoot=1 icallRestored=1 reportEnumeration=0 reportPayloadRead=0 wholeRunIsolation=0',
        '[91] TELEMETRY CACHECLIENT begin: version=1 thread=17 constructorGuards=6 callbackHeads=4',
        '[92] TELEMETRY CACHECLIENT probe passed: version=1 thread=17 nativeCtorCalls=1 clientCtorCalls=1 genuineNativeInterface=1 configurationRetained=1 coreFieldsPresent=14 dependencyGraphMatched=1 idleDelivery=1 globalCallbackHeadsUnchanged=4 reportingDisabled=1 wholeRunIsolation=0',
        '[93] TELEMETRY CURRENTQUEUE begin: version=1 thread=17 genuineClient=1 authoredSeeds=2',
        '[94] TELEMETRY CURRENTQUEUE probe passed: version=1 thread=17 genuineClient=1 authoredSeeds=2 eventFiles=0 sessionFiles=0 eventNull=1 sessionNull=1 cachedStartReturned=1 deliveryFieldsUnchanged=1 clientFieldsUnchanged=1 seedIdentitiesAndBytesUnchanged=2 reportDelivered=0',
        '[95] TELEMETRY CURRENTQUEUE scope restored: version=1 thread=17 pathRestored=1',
    ))


ROWS = [dict(event='OnConfirm.dispatch', thread=17, tick=120)]
TELEMETRY = dict(passed=True, recipe_version=44)


class CurrentQueueEvidenceTests(unittest.TestCase):
    def test_recipe45_preexisting_requires_constructor_boundary(self):
        lines=fixture().splitlines()
        lines[3]=lines[3].replace('version=1', 'version=3')+' preexistingBeforeClient=1'
        lines[4]=lines[4].replace('version=1', 'version=3').replace(
            'authoredSeeds=2 eventFiles', 'authoredSeeds=2 preexistingBeforeClient=1 eventFiles').replace(
            'cachedStartReturned=1 delivery', 'cachedStartReturned=1 deleteEntriesReturned=2 delivery')
        lines[5]=lines[5].replace('version=1', 'version=3')
        lines.insert(1,'[90] TELEMETRY PREEXISTING begin: version=1 thread=17 ownedFilesBeforeClient=2')
        lines.insert(4,'[92] TELEMETRY PREEXISTING ctor passed: version=1 thread=17 genuineClient=1 fileIdentitiesAndBytesUnchanged=2')
        current='\n'.join(lines)
        audit=dict(passed=True, recipe_version=45)
        result=validate(current, ROWS, audit, preexisting=True)
        self.assertTrue(result['preexisting_before_client'])
        with self.assertRaises(AssertionError):
            validate(current.replace('ownedFilesBeforeClient=2', 'ownedFilesBeforeClient=1'), ROWS, audit, preexisting=True)
        with self.assertRaises(AssertionError):
            validate(current, ROWS, audit)

    def test_recipe45_requires_delete_retention(self):
        current = fixture().replace('CURRENTQUEUE begin: version=1', 'CURRENTQUEUE begin: version=2')
        current = current.replace('CURRENTQUEUE probe passed: version=1', 'CURRENTQUEUE probe passed: version=2')
        current = current.replace('CURRENTQUEUE scope restored: version=1', 'CURRENTQUEUE scope restored: version=2')
        current = current.replace('cachedStartReturned=1 deliveryFieldsUnchanged=1',
                                  'cachedStartReturned=1 deleteEntriesReturned=2 deliveryFieldsUnchanged=1')
        audit = dict(passed=True, recipe_version=45)
        result = validate(current, ROWS, audit)
        self.assertTrue(result['guarded_delete_entries_returned'])
        with self.assertRaises(AssertionError):
            validate(current.replace('deleteEntriesReturned=2', 'deleteEntriesReturned=1'), ROWS, audit)
        with self.assertRaises(AssertionError):
            validate(fixture(), ROWS, audit)

    def test_complete_owned_sequence(self):
        result = validate(fixture(), ROWS, TELEMETRY)
        self.assertTrue(result['passed'])
        self.assertTrue(result['seed_identity_and_bytes_unchanged'])
        self.assertFalse(result['whole_run_privacy_qualified'])

    def test_missing_changed_disk_or_wrong_recipe_rejects(self):
        lines = fixture().splitlines()
        invalid = ['\n'.join(lines[:i] + lines[i + 1:]) for i in range(len(lines))]
        invalid += [fixture().replace('eventFiles=0', 'eventFiles=1'),
                    fixture().replace('seedIdentitiesAndBytesUnchanged=2', 'seedIdentitiesAndBytesUnchanged=1'),
                    fixture().replace('pathRestored=1', 'pathRestored=0'),
                    fixture() + '\n[100] TELEMETRY CACHEREADER probe passed:',
                    '\n'.join((lines[1], lines[0], *lines[2:]))]
        for bad in invalid:
            with self.subTest(bad=bad[-75:]), self.assertRaises(AssertionError):
                validate(bad, ROWS, TELEMETRY)
        with self.assertRaises(AssertionError):
            validate(fixture(), ROWS, dict(passed=True, recipe_version=43))


if __name__ == '__main__':
    unittest.main()
