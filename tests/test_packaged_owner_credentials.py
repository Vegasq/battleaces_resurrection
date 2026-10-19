"""Real credential/enrollment lifecycle with an EXPLICIT mocked OS privacy boundary.

Not Windows DACL or native multiplayer acceptance;the operator run is separate.
"""
import unittest
import json
import subprocess
import uuid
from unittest import mock

from server import credentials as private
from client_patch.transport import client,enrollment
from tools.packaged_owner_credentials import OwnerCredentials
from tests.test_credentials import private_test_folder,remove_test_folder
from tests.test_tls_transport import ROOT,generate_test_pki,remove_test_pki


class PackagedOwnerCredentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pki_folder=ROOT/'local'/('packaged-owner-pki-'+uuid.uuid4().hex)
        cls.pki=generate_test_pki(cls.pki_folder)

    @classmethod
    def tearDownClass(cls):remove_test_pki(cls.pki_folder)

    def setUp(self):
        self.folder=private_test_folder('packaged-owner-');(self.folder/'config').mkdir()
        self.owner=OwnerCredentials(self.folder)
        self.patches=[mock.patch.object(private,'_ensure_private_directory',side_effect=lambda path:path.mkdir(parents=True,exist_ok=True)),
            mock.patch.object(private,'_private_create',side_effect=lambda path:path.open('x+b')),
            mock.patch.object(private,'_assert_private_path')]
        for patch in self.patches:patch.start()

    def tearDown(self):
        self.owner.dispose()
        for patch in reversed(self.patches):patch.stop()
        remove_test_folder(self.folder)

    def config(self,index):return self.folder/'config'/f'client-{index}.json'

    def settings(self,index):
        result=client.defaults(self.folder/'no-game-started')
        result.update(local_profile=f'owner_test_{index}',display_name=f'Owner {index}')
        return result

    def assert_revoked_removed(self):
        self.assertTrue(self.owner.dispose()['disposable_invites_revoked_and_handoffs_removed'])
        self.assertTrue(all(row['revoked_at'] is not None for row in self.owner.store.list_public()))
        self.assertFalse(any(p.exists() for p in self.owner.handoffs+self.owner.enrolled))
        self.assertFalse(list((self.folder/'config/private').glob('enrollment-*/private-invite.json')))

    def test_two_enrolled_identities_keep_profiles_then_revoke_and_remove(self):
        identities=self.owner.issue(2)
        self.assertNotEqual(identities[0]['player_id'],identities[1]['player_id'])
        for index,value in enumerate(identities):
            path=self.owner.enroll(index,self.config(index),self.settings(index),self.pki['ca'],12345)
            self.assertEqual(private.read_credential_file(path),value)
            self.assertEqual(self.owner.store.authenticate(value['token']),value['player_id'])
            self.assertNotIn(value['token'].encode(),self.config(index).read_bytes())
            self.assertEqual(client.prepare_settings(self.config(index))['local_profile'],f'owner_test_{index}')
        self.assert_revoked_removed();self.assert_revoked_removed()
        for value in identities:
            with self.assertRaises(private.AuthenticationError):self.owner.store.authenticate(value['token'])

    def test_partial_issuance_failure_remains_disposable(self):
        original=private.CredentialStore.issue_to_file;calls=0
        def issue(*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==2:raise private.CredentialError('injected unavailable destination')
            return original(*args,**kwargs)
        with mock.patch.object(private.CredentialStore,'issue_to_file',autospec=True,side_effect=issue):
            with self.assertRaises(private.CredentialError):self.owner.issue(2)
        self.assert_revoked_removed()

    def test_failure_after_enrollment_commit_removes_unreturned_handoff(self):
        self.owner.issue(2)
        def committed_then_failed(command,**kwargs):
            request=json.loads((self.folder/'config/enrollment-request-0.json').read_text())
            enrollment.enroll(request,self.config(0))
            return subprocess.CompletedProcess(command,1,b'',b'fixed backend failure')
        with mock.patch('tools.packaged_owner_credentials.subprocess.run',side_effect=committed_then_failed):
            with self.assertRaises(AssertionError):self.owner.enroll(0,self.config(0),self.settings(0),self.pki['ca'],12345,client_package=self.folder/'package')
        self.assertEqual(self.owner.enrolled,[]);self.assert_revoked_removed()
        self.assertFalse((self.folder/'config/enrollment-request-0.json').exists())

    def test_packaged_dispatch_keeps_tokens_out_of_request_and_arguments(self):
        identities=self.owner.issue(2)
        def source_backend(command,**kwargs):
            raw=(self.folder/'config/enrollment-request-0.json').read_text()
            for identity in identities:
                self.assertNotIn(identity['token'],raw);self.assertNotIn(identity['token'],' '.join(command))
            self.assertEqual(command[1:6],['-I','-B','-m','tools.package_client','enroll'])
            self.assertEqual(kwargs['stdin'],subprocess.DEVNULL)
            result=enrollment.enroll(json.loads(raw),self.config(0))
            return subprocess.CompletedProcess(command,0,json.dumps(dict(ok=True,result=result)).encode(),b'')
        # Explicit execution seam only for this source test; real owner
        # qualification must run the actual bundled executable/CLI.
        with mock.patch('tools.packaged_owner_credentials.subprocess.run',side_effect=source_backend):
            path=self.owner.enroll(0,self.config(0),self.settings(0),self.pki['ca'],12345,client_package=self.folder/'package')
        self.assertEqual(private.read_credential_file(path),identities[0])
        self.assertEqual(len(self.owner.commands),1)
        self.assertFalse((self.folder/'config/enrollment-request-0.json').exists())
        self.assert_revoked_removed()
