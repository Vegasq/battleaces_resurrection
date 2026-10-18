"""Enrollment transactions and real TLS, with the OS privacy boundary explicit.

Logic tests mock only private file/directory creation and DACL inspection. The
opt-in Windows case below uses the real boundary and never relaxes permissions.
All credentials and PKI are generated under ignored local/ and are test-only.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import ssl
import unittest
from unittest import mock
import uuid

from client_patch.transport import enrollment as e, launcher
from server import admission as a, credentials as c, tls_transport as tls
from server.dedicated_server import DedicatedServer
from server.profiles import ProfileStore
from tests.synthetic import template as synthetic_template
from tests.test_admission import Store
from tests.test_credentials import private_test_folder, remove_test_folder
from tests.test_tls_transport import generate_test_pki, remove_test_pki
from tools import package_client

ROOT = Path(__file__).resolve().parents[1]


def handoff():
    return dict(schema=1, player_id='p_'+secrets.token_hex(16),
                invite_id='i_'+secrets.token_hex(16), token='ba1_'+secrets.token_urlsafe(32))


def request(folder, ca, invite):
    return dict(schema=1, game_directory=str(folder/'working game'), server_host='127.0.0.1',
        server_port=47623, server_name='LOCALHOST', display_name='Player', room='friends',
        ca_source=str(ca), invite_source=str(invite),
        expected_ca_sha256=hashlib.sha256(ca.read_bytes()).hexdigest(), expected_config_sha256=None)


class EnrollmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pki_folder = ROOT/'local'/('enrollment-pki-'+uuid.uuid4().hex)
        cls.pki = generate_test_pki(cls.pki_folder)

    @classmethod
    def tearDownClass(cls):
        remove_test_pki(cls.pki_folder)

    def setUp(self):
        self.folder = private_test_folder('enrollment-')
        self.config = self.folder/'client.json'
        self.source = self.folder/'downloaded-invite.json'
        self.handoff = handoff()
        self.source.write_text(json.dumps(self.handoff))
        self.request = request(self.folder, self.pki['ca'], self.source)
        self.patches = [
            mock.patch.object(c, '_ensure_private_directory', side_effect=lambda path: path.mkdir(parents=True, exist_ok=True)),
            mock.patch.object(c, '_assert_private_path'),
            mock.patch.object(c, '_private_create', side_effect=lambda path: path.open('x+b')),
        ]
        self.boundaries = [patch.start() for patch in self.patches]

    def tearDown(self):
        for patch in reversed(self.patches): patch.stop()
        remove_test_folder(self.folder)

    def test_import_preserves_transfer_and_requires_private_readback(self):
        raw = self.source.read_bytes()
        target = self.folder/'protected'/'invite.json'
        public = c.import_credential_file(self.source, target)
        self.assertEqual(set(public), {'player_id', 'invite_id'})
        self.assertNotIn(self.handoff['token'], json.dumps(public))
        self.assertEqual(c.read_credential_file(target), self.handoff)
        self.assertEqual(self.source.read_bytes(), raw)
        self.boundaries[1].assert_any_call(target)
        self.assertFalse(any(call.args[0] == self.source for call in self.boundaries[1].call_args_list))
        # Direct runtime reads still require the privacy check.
        with mock.patch.object(c, '_assert_private_path', side_effect=c.CredentialError('not private')):
            with self.assertRaises(c.CredentialError): c.read_credential_file(self.source)
            failed = self.folder/'protected'/'failed.json'
            with self.assertRaises(c.CredentialError): c.import_credential_file(self.source, failed)
            self.assertFalse(failed.exists())

    def test_import_never_replaces_existing_file_or_changes_source(self):
        target = self.folder/'existing.json'; target.write_bytes(b'preserve this')
        original = self.source.read_bytes()
        for destination in (target, self.source):
            with self.assertRaises(c.CredentialError): c.import_credential_file(self.source, destination)
        self.assertEqual(target.read_bytes(), b'preserve this')
        self.assertEqual(self.source.read_bytes(), original)
        with self.assertRaises(c.CredentialError):
            c.import_credential_file(self.source, self.folder/'new.json', expected_sha256='0'*64)
        self.assertFalse((self.folder/'new.json').exists())

    def test_untrusted_invite_is_bounded_strict_and_never_echoed(self):
        valid = self.source.read_bytes()
        invalid = (b'', b'x'*(c.MAX_CREDENTIAL_BYTES+1), b'[]',
            valid[:-1]+b', "schema":1}', json.dumps(dict(self.handoff, extra='unknown')).encode(),
            json.dumps(dict(self.handoff, token='not a token')).encode())
        for raw in invalid:
            self.source.write_bytes(raw)
            with self.assertRaises(c.CredentialError) as error:
                c.import_credential_file(self.source, self.folder/'new.json')
            self.assertNotIn(self.handoff['token'], str(error.exception))
            self.assertFalse((self.folder/'new.json').exists())

    def test_enroll_binds_exact_ca_creates_private_copies_and_returns_no_secret(self):
        source_before = self.source.read_bytes()
        result = e.enroll(self.request, self.config)
        loaded = launcher.load_config(self.config)
        self.assertEqual(loaded['server_name'], 'localhost')
        self.assertEqual(loaded['ca_bundle'].read_bytes(), self.pki['ca'].read_bytes())
        self.assertEqual(c.read_credential_file(loaded['credential_file']), self.handoff)
        self.assertEqual(loaded['ca_bundle'].parent, loaded['credential_file'].parent)
        self.assertTrue(loaded['credential_file'].is_relative_to(self.folder/'private'))
        self.assertEqual(self.source.read_bytes(), source_before)
        self.assertEqual(result['ca_sha256'], self.request['expected_ca_sha256'])
        exposed = json.dumps(result)+self.config.read_text()+json.dumps(e.setup_data(self.config))
        self.assertNotIn(self.handoff['token'], exposed)
        self.assertNotIn('token', self.config.read_text())
        self.assertEqual(tls.load_client_context(loaded['ca_bundle'], loaded['server_name']).context.verify_mode, ssl.CERT_REQUIRED)

    def test_bad_trust_or_settings_create_no_private_destination(self):
        for changes in (dict(expected_ca_sha256=''), dict(expected_ca_sha256='0'*64),
                        dict(server_port=True), dict(room='../room'), dict(server_host='https://host')):
            with self.assertRaises((e.EnrollmentError, launcher.LaunchError, tls.TLSConfigurationError)):
                e.enroll(dict(self.request, **changes), self.config)
            self.assertFalse(self.config.exists())
            self.assertFalse((self.folder/'private').exists())
        with mock.patch.object(e, 'ROOT', self.folder/'program/app'):
            (self.folder/'program').mkdir()
            with self.assertRaises(e.EnrollmentError): e.config_destination(self.folder/'program/client.json')

    def test_ca_file_accepts_only_public_certificates_and_hashes_exact_bytes(self):
        selected = self.folder/'ca.pem'
        raw = self.pki['ca'].read_bytes()
        for bad in (raw+self.pki['key'].read_bytes(), raw+b'unknown trailing content', b'not PEM'):
            selected.write_bytes(bad)
            with self.assertRaises(e.EnrollmentError): e.ca_fingerprint(selected)
        selected.write_bytes(raw+b'\n')
        self.assertNotEqual(e.ca_fingerprint(selected)[1], e.ca_fingerprint(self.pki['ca'])[1])

    def test_commit_failure_preserves_old_config_and_profile(self):
        e.enroll(self.request, self.config)
        before = self.config.read_bytes()
        old_files = {p.relative_to(self.folder):p.read_bytes() for p in (self.folder/'private').rglob('*') if p.is_file()}
        update = dict(self.request, expected_config_sha256=hashlib.sha256(before).hexdigest(), display_name='Changed')
        with mock.patch.object(e.os, 'replace', side_effect=PermissionError('authored failure')):
            with self.assertRaises(OSError): e.enroll(update, self.config)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(old_files, {p.relative_to(self.folder):p.read_bytes() for p in (self.folder/'private').rglob('*') if p.is_file()})
        self.assertEqual(list(self.folder.glob('.client-config-*.tmp')), [])

    def test_stale_or_simultaneous_setup_does_not_overwrite_success(self):
        def save():
            try: return e.enroll(self.request, self.config)
            except e.EnrollmentError: return None
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: save(), range(2)))
        self.assertEqual(sum(item is not None for item in results), 1)
        before = self.config.read_bytes()
        with self.assertRaises(e.EnrollmentError): e.enroll(self.request, self.config)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(len(list((self.folder/'private').glob('enrollment-*'))), 1)

    def test_existing_unrelated_json_is_not_overwritten(self):
        self.config.write_bytes(b'{"unrelated":"preserve"}')
        with self.assertRaises(launcher.LaunchError): e.enroll(self.request, self.config)
        self.assertEqual(self.config.read_bytes(), b'{"unrelated":"preserve"}')

    def test_settings_reopen_can_recover_removed_ca_without_trusting_replacement(self):
        self.assertIsNone(e.setup_data(self.config)['expected_config_sha256'])
        e.enroll(self.request, self.config)
        loaded = launcher.load_config(self.config)
        loaded['ca_bundle'].unlink()
        values = e.setup_data(self.config)
        self.assertEqual(values['expected_ca_sha256'], '')
        self.assertEqual(values['expected_config_sha256'], hashlib.sha256(self.config.read_bytes()).hexdigest())
        self.assertEqual(values['invite_source'], str(loaded['credential_file']))

    def test_packaged_enrollment_and_errors_do_not_echo_secrets(self):
        request_file = self.folder/'request.json'; request_file.write_text(json.dumps(self.request))
        output, errors = io.StringIO(), io.StringIO()
        with mock.patch.object(package_client, 'verify'), redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(package_client.main(['enroll', '--request', str(request_file), '--config', str(self.config)]), 0)
        self.assertTrue(json.loads(output.getvalue())['ok'])
        self.assertNotIn(self.handoff['token'], output.getvalue()+errors.getvalue())
        # Unexpected OS messages must not be reflected into the UI/console.
        output = io.StringIO()
        with (mock.patch.object(package_client, 'verify'), redirect_stdout(output),
              mock.patch.object(e, 'setup_data', side_effect=OSError(self.handoff['token']))):
            self.assertEqual(package_client.main(['setup-data', '--config', str(self.config)]), 1)
        self.assertFalse(json.loads(output.getvalue())['ok'])
        self.assertNotIn(self.handoff['token'], output.getvalue())


class ConnectionCheckTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = ROOT/'local'/('enrollment-tls-'+uuid.uuid4().hex)
        cls.pki = generate_test_pki(cls.folder)

    @classmethod
    def tearDownClass(cls):
        remove_test_pki(cls.folder)

    async def asyncSetUp(self):
        self.store = Store()
        template = synthetic_template()
        self.server = DedicatedServer(template, ProfileStore(self.folder/uuid.uuid4().hex, template),
            tls_context=tls.load_server_context(self.pki['cert'], self.pki['key']),
            admission=a.AdmissionController(self.store))
        port = (await self.server.start('127.0.0.1', 0))[1]
        self.invite = self.folder/(uuid.uuid4().hex+'.json')
        self.invite.write_text(json.dumps(dict(handoff(), player_id=self.store.player, token=self.store.token)))
        self.config = self.folder/(uuid.uuid4().hex+'.json')
        self.settings = dict(schema=2, game_directory=str(self.folder/'working'), server_host='127.0.0.1',
            server_port=port, server_name='localhost', ca_bundle=str(self.pki['ca']),
            credential_file=str(self.invite), display_name='Player', room='friends')
        self.privacy = mock.patch.object(c, '_assert_private_path'); self.privacy.start()

    async def asyncTearDown(self):
        await self.server.close()
        self.privacy.stop()

    async def check(self):
        self.config.write_text(json.dumps(self.settings))
        return await e.check_connection(self.config)

    async def test_real_tls_authenticates_and_closes_without_game_or_room(self):
        result = await self.check()
        self.assertTrue(result['authenticated'])
        self.assertEqual(result['player_id'], self.store.player)
        self.assertIn(result['tls'], ('TLSv1.2', 'TLSv1.3'))
        self.assertEqual(self.store.calls, 1)
        self.assertEqual(self.server.rooms, {})
        self.assertEqual(len(self.server.peers), 0)
        self.assertNotIn(self.store.token, json.dumps(result))

    async def test_bad_ca_or_name_never_sends_invite(self):
        for change in (dict(server_name='wrong.invalid'), dict(ca_bundle=str(self.pki['unrelated_ca']))):
            before = self.settings.copy(); self.settings.update(change)
            with self.assertRaises(ssl.SSLCertVerificationError): await self.check()
            self.settings = before
        self.assertEqual(self.store.calls, 0)
        self.assertEqual(self.server.rooms, {})

    async def test_revoked_invite_and_identity_mismatch_fail_without_room(self):
        self.store.revoked = True
        with self.assertRaises(a.AdmissionError): await self.check()
        self.store.revoked = False
        changed = json.loads(self.invite.read_bytes()); changed['player_id'] = 'p_'+secrets.token_hex(16)
        self.invite.write_text(json.dumps(changed))
        with self.assertRaises(e.EnrollmentError): await self.check()
        self.assertEqual(self.server.rooms, {})
        self.assertEqual(len(self.server.peers), 0)


@unittest.skipUnless(os.name == 'nt' and os.environ.get('BA_RUN_PRIVATE_ACL_TESTS') == '1',
                     'real enrollment DACL test requires explicit BA_RUN_PRIVATE_ACL_TESTS=1 on Windows')
class WindowsEnrollmentPrivacyTests(unittest.TestCase):
    def test_real_private_transfer_enrollment_and_authenticated_tls(self):
        folder = ROOT/'local'/('enrollment-real-acl-'+uuid.uuid4().hex)
        pki = generate_test_pki(folder)
        try:
            try:
                store = c.CredentialStore(folder/'host-private')
                output = folder/'host-private'/'issued.json'
                public = store.issue_to_file(output)
                source = folder/'transferred.json'; source.write_bytes(output.read_bytes())
                config = folder/'client.json'
                result = e.enroll(request(folder, pki['ca'], source), config)
                loaded = launcher.load_config(config)
                self.assertEqual(result['player_id'], public['player_id'])
                copied = c.read_credential_file(loaded['credential_file'])
                self.assertEqual(store.authenticate(copied['token']), public['player_id'])
                for path in (config, loaded['ca_bundle'], loaded['credential_file']):
                    self.assertEqual(c._windows().inspect(path), c._windows().sddl())
                for path in (folder/'private', loaded['credential_file'].parent):
                    self.assertEqual(c._windows().inspect(path), c._windows().sddl(True))
                with self.assertRaises(c.CredentialError): c.read_credential_file(source)
                self.assertTrue(output.read_bytes() == source.read_bytes())
                async def authenticated_check():
                    template = synthetic_template()
                    server = DedicatedServer(template, ProfileStore(folder/'profiles', template),
                        tls_context=tls.load_server_context(pki['cert'], pki['key']),
                        admission=a.AdmissionController(store))
                    try:
                        port = (await server.start('127.0.0.1', 0))[1]
                        settings = json.loads(config.read_bytes()); settings['server_port'] = port
                        config.write_text(json.dumps(settings))
                        connected = await e.check_connection(config)
                        self.assertTrue(connected['authenticated'])
                        self.assertEqual(connected['player_id'], public['player_id'])
                        self.assertEqual(server.rooms, {})
                    finally: await server.close()
                asyncio.run(authenticated_check())
            except c.CredentialError as error:
                if any(word in str(error) for word in ('inaccessible', 'unavailable', 'cannot create private')):
                    self.skipTest('observed restricted-token/private-DACL limitation: '+str(error))
                raise
        finally:
            try: remove_test_pki(folder)
            except PermissionError: pass  # Retain private files; never alter ACLs.


if __name__ == '__main__': unittest.main()
