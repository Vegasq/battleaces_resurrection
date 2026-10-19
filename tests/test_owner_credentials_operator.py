"""Operator lifecycle/report tests with an explicit mocked OS privacy boundary.

These are NOT real Windows DACL acceptance; that requires the external bundled
operator check under the intended normal desktop account.
"""
import json
import unittest
from unittest import mock

from server import credentials as private
from tools import verify_owner_credentials as operator
from tests.test_credentials import private_test_folder,remove_test_folder


class OwnerCredentialOperatorTests(unittest.TestCase):
    def setUp(self):
        self.folder=private_test_folder('owner-operator-');self.directories=set();self.files=set()
        def ensure(path):path.mkdir(parents=True,exist_ok=True);self.directories.add(path.resolve())
        def create(path):
            stream=path.open('x+b');self.files.add(path.resolve());return stream
        def check(path,*,directory=False):
            path=path.resolve()
            valid=path in self.directories if directory else path in self.files or any(path.is_relative_to(p) for p in self.directories)
            if not valid:raise private.CredentialError('mock privacy boundary: unprotected input')
        self.patches=[mock.patch.object(private,'_ensure_private_directory',side_effect=ensure),
                      mock.patch.object(private,'_private_create',side_effect=create),
                      mock.patch.object(private,'_assert_private_path',side_effect=check)]
        for patch in self.patches:patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):patch.stop()
        remove_test_folder(self.folder)

    def test_complete_roundtrip_revokes_and_removes_bearer_handoffs(self):
        report={};operator.exercise(private,self.folder,report)
        self.assertEqual(report['stage'],'complete');self.assertTrue(report['disposable_invites_revoked_and_handoffs_removed'])
        self.assertTrue(report['unprotected_runtime_read_rejected_explicit_import_succeeded'])
        self.assertNotIn('ba1_',json.dumps(report));self.assertFalse((self.folder/'issued.json').exists())
        rows=private.CredentialStore(self.folder/'store').list_public()
        self.assertEqual(len(rows),1);self.assertIsNotNone(rows[0]['revoked_at'])

    def test_failure_still_revokes_issued_invite_and_does_not_collect_exception_text(self):
        report={}
        with mock.patch.object(private.CredentialStore,'authenticate',side_effect=RuntimeError('ba1_never_log_this')):
            with self.assertRaises(RuntimeError):operator.exercise(private,self.folder,report)
        self.assertTrue(report['disposable_invites_revoked_and_handoffs_removed'])
        self.assertNotIn('ba1_',json.dumps(report));self.assertFalse((self.folder/'issued.json').exists())
        self.assertTrue(all(r['revoked_at'] is not None for r in private.CredentialStore(self.folder/'store').list_public()))

    def test_late_import_failure_keeps_cleanup_and_revocation(self):
        report={};original=private.import_credential_file
        def importing(source,output,**kwargs):
            if output.parent.name=='transferred':raise private.CredentialError('injected unavailable destination')
            return original(source,output,**kwargs)
        with mock.patch.object(private,'import_credential_file',side_effect=importing):
            with self.assertRaises(private.CredentialError):operator.exercise(private,self.folder,report)
        self.assertEqual(report['stage'],'unprotected_transfer');self.assertTrue(report['disposable_invites_revoked_and_handoffs_removed'])
        self.assertFalse((self.folder/'unprotected-transfer.json').exists());self.assertFalse((self.folder/'enrolled/invite.json').exists())
