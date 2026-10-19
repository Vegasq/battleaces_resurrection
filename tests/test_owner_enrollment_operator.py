"""Real loopback enrollment/TLS lifecycle, with an EXPLICIT mocked OS privacy boundary.

These tests do not qualify Windows DACLs. The external operator must run through
the actual client bundle from the normal desktop account for that acceptance.
"""
import json
import asyncio
import sys
import unittest
import uuid
from unittest import mock

from client_patch.transport import enrollment
from server import credentials as private
from tests.synthetic import template
from tests.test_credentials import private_test_folder,remove_test_folder
from tests.test_tls_transport import ROOT,generate_test_pki,remove_test_pki
from tools import verify_owner_enrollment as operator
from tools.owner_enrollment_host import Host


class OwnerEnrollmentOperatorTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.pki_folder=ROOT/'local'/('owner-enrollment-pki-'+uuid.uuid4().hex)
        cls.pki=generate_test_pki(cls.pki_folder)

    @classmethod
    def tearDownClass(cls):remove_test_pki(cls.pki_folder)

    def setUp(self):
        self.folder=private_test_folder('owner-enrollment-')
        self.patches=[mock.patch.object(private,'_ensure_private_directory',side_effect=lambda path:path.mkdir(parents=True,exist_ok=True)),
            mock.patch.object(private,'_private_create',side_effect=lambda path:path.open('x+b')),
            mock.patch.object(private,'_assert_private_path')]
        for patch in self.patches:patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):patch.stop()
        remove_test_folder(self.folder)

    async def asyncSetUp(self):
        self.host=Host(self.folder/'host',self.pki,template());await self.host.start()

    async def asyncTearDown(self):await self.host.close()

    def assert_cleanup(self,report):
        self.assertTrue(report['disposable_invites_revoked_and_handoffs_removed'])
        self.assertTrue(report['listener_sessions_and_admission_released'])
        self.assertFalse((self.folder/'host/host-private/issued.json').exists())
        self.assertFalse((self.folder/'setup/client.json').exists())
        self.assertFalse(list((self.folder/'setup/private').glob('enrollment-*/private-invite.json')))
        self.assertTrue(all(row['revoked_at'] is not None for row in private.CredentialStore(self.folder/'host/host-private').list_public()))
        self.assertNotIn('ba1_',json.dumps(report))

    async def test_full_enrollment_tls_refusals_revocation_and_release(self):
        report={};await operator.exercise(self.folder,self.pki,report,self.host)
        self.assertEqual(report['stage'],'complete')
        for key in ('protected_enrollment_and_profile_preserved','wrong_fingerprint_and_stale_save_preserve_config',
            'verified_tls_authentication_without_game','wrong_ca_and_server_name_rejected',
            'authenticated_identity_mismatch_rejected','revoked_invite_rejected_over_tls','no_room_profile_or_worker_created'):
            self.assertTrue(report[key],key)
        self.assert_cleanup(report)

    async def test_connection_failure_still_releases_and_revokes(self):
        report={}
        with mock.patch.object(enrollment,'check_connection',side_effect=RuntimeError('ba1_never_publish_exception')):
            with self.assertRaises(RuntimeError):await operator.exercise(self.folder,self.pki,report,self.host)
        self.assertEqual(report['stage'],'verified_tls_authentication');self.assert_cleanup(report)

    async def test_failure_after_enrollment_commit_removes_created_bearer(self):
        report={};original=enrollment.enroll
        def committed_then_failed(*args):
            original(*args);raise OSError('ba1_never_publish_exception')
        with mock.patch.object(enrollment,'enroll',side_effect=committed_then_failed):
            with self.assertRaises(OSError):await operator.exercise(self.folder,self.pki,report,self.host)
        self.assertEqual(report['stage'],'enrollment');self.assert_cleanup(report)


class HostProcessControlTests(unittest.IsolatedAsyncioTestCase):
    """Real stdio/child lifecycle with an explicit protocol fixture, not server proof."""
    def setUp(self):self.folder=private_test_folder('owner-host-control-')
    def tearDown(self):remove_test_folder(self.folder)

    async def run_fixture(self,*,successful):
        driver=self.folder/'driver.py'
        driver.write_text('''import hashlib,json,sys
from pathlib import Path
print(json.dumps(dict(ready=True,port=12345,metadata=dict(server_driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))),flush=True)
for line in sys.stdin:
    command=json.loads(line)['command']
    if command=='close':
        print(json.dumps(dict(closed=True,passed=SUCCESS,cleanup=dict(listener_sessions_and_admission_released=True,disposable_invites_revoked_and_handoffs_removed=True,server_package_and_assets_unchanged=True),metadata={})),flush=True)
        break
    print(json.dumps(dict(ok=True,revoked=True,no_room_profile_or_worker_created=True)),flush=True)
raise SystemExit(0 if SUCCESS else 2)
'''.replace('SUCCESS',repr(successful)),encoding='utf-8')
        host=operator.HostProcess(self.folder,self.folder/'host',self.folder,self.folder,driver)
        spawn=asyncio.create_subprocess_exec
        async def fixture(*args,**kwargs):
            # Only this explicit test substitutes executable/driver argv. The
            # real child pipes/drain/close/wait and adapter are exercised.
            return await spawn(sys.executable,'-I','-B',str(driver),**kwargs)
        with mock.patch.object(operator.asyncio,'create_subprocess_exec',side_effect=fixture):
            try:await host.start()
            except PermissionError as error:
                if getattr(error,'winerror',None)==5 and host.process is None:
                    self.skipTest('restricted token cannot create Windows asyncio overlapped pipe; normal-owner process acceptance pending')
                raise
            self.assertTrue((await host.settled())['no_room_profile_or_worker_created'])
            self.assertTrue((await host.revoke())['revoked'])
            report=await host.close()
        self.assertIsNotNone(host.process.returncode)
        self.assertEqual(report['server_process_natural_exit'],successful)
        self.assertEqual(all(report.values()),successful)
        self.assertIs(await host.close(),report)

    async def test_successful_reply_and_natural_exit(self):await self.run_fixture(successful=True)
    async def test_failed_cleanup_reply_is_not_promoted(self):await self.run_fixture(successful=False)
