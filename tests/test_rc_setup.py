"""RC address-only setup, persistent identity and actual unverified TLS admission."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import shutil
import ssl
import unittest
import uuid
from unittest import mock

from client_patch.transport import client, rc_setup, launcher, bridge
from server import admission, rc_host, tls_transport as tls
from server.configuration import load_config, ConfigurationError

ROOT = Path(__file__).resolve().parents[1]


class RCSetupTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / 'local' / ('rc-setup-' + uuid.uuid4().hex)
        self.game = self.root / 'working game'
        self.game.mkdir(parents=True)
        (self.game / 'Battle Aces.exe').write_bytes(b'authored fixture')
        self.path = self.root / 'config/client.json'

    def tearDown(self):
        self.root.resolve().relative_to((ROOT / 'local').resolve())
        shutil.rmtree(self.root)

    def save(self, host='127.0.0.1', name='Player'):
        return rc_setup.save(dict(game_directory=str(self.game), display_name=name, server_host=host,
                                 expected_config_sha256=rc_setup.digest(self.path)), self.path)

    def test_address_only_save_is_offline_and_identity_is_stable_across_name_edits(self):
        with mock.patch('socket.create_connection', side_effect=AssertionError('no networking during save')):
            self.save()
            value = launcher.read_json(self.path, 32768)
            self.assertEqual(set(value), rc_setup.KEYS)
            self.assertFalse({'ca_bundle', 'credential_file', 'server_name'} & value.keys())
            self.assertEqual(client.prepare_settings(self.path)['game_directory'], self.game)
        first = rc_setup.Resolver(self.path, self.game).read()
        self.assertFalse(first.tls.verify_certificate)
        self.save(name='Renamed')
        second = rc_setup.Resolver(self.path, self.game).read()
        self.assertEqual((first.player_id, first.token), (second.player_id, second.token))
        self.save(host='localhost')
        self.assertNotEqual(first.player_id, rc_setup.Resolver(self.path, self.game).read().player_id)

    def test_blank_server_stays_offline_and_bad_addresses_stale_edits_refuse(self):
        self.save(host='')
        self.assertEqual(client.prepare_settings(self.path)['display_name'], 'Player')
        with self.assertRaises(bridge.RemoteUnavailable): rc_setup.Resolver(self.path, self.game).read()
        before = self.path.read_bytes()
        for host in ('https://example.test', 'host:123', 'bad host'):
            with self.assertRaises(ValueError): self.save(host=host)
            self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'changed'):
            rc_setup.save(dict(game_directory=str(self.game), display_name='Player', server_host='',
                               expected_config_sha256=None), self.path)

    def test_existing_local_profile_survives_upgrade_and_corrupt_identity_is_not_replaced(self):
        self.path.parent.mkdir()
        old = dict(client.defaults(self.game), local_profile='friends_02')
        self.path.write_text(json.dumps(old))
        self.save()
        self.assertEqual(client.prepare_settings(self.path)['local_profile'], 'friends_02')
        rc_setup.Resolver(self.path, self.game).read()
        identity, = (self.path.parent / 'rc-identities').glob('*.json')
        identity.write_text('{}')
        with self.assertRaises(ValueError): rc_setup.Resolver(self.path, self.game).read()
        self.assertEqual(identity.read_text(), '{}')

    def test_rc_server_configuration_requires_tls_and_explicit_mode(self):
        value = json.loads((ROOT / 'server/host-config.example.json').read_text())
        value.update(schema=2, access_mode='rc-open', credential_directory=None)
        for key in ('assets_directory', 'data_directory'):
            value[key] = str(self.root / key)
        self.path.parent.mkdir()
        self.path.write_text(json.dumps(value))
        self.assertEqual(load_config(self.path).access_mode, 'rc-open')
        for key, invalid in (('access_mode', 'anything'), ('private_key_file', None),
                             ('allow_insecure_loopback', True), ('credential_directory', '../credentials')):
            self.path.write_text(json.dumps(dict(value, **{key: invalid})))
            with self.assertRaises(ConfigurationError): load_config(self.path)


@unittest.skipUnless(os.name == 'nt', 'RC host uses built-in Windows cryptography')
class RCTLSIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ROOT / 'local' / ('rc-tls-' + uuid.uuid4().hex)
        cls.root.mkdir()
        certificate, key = rc_host.generate_certificate()
        cls.cert, cls.key = cls.root / 'server.pem', cls.root / 'server.key'
        cls.cert.write_bytes(certificate); cls.key.write_bytes(key)

    @classmethod
    def tearDownClass(cls):
        cls.root.resolve().relative_to((ROOT / 'local').resolve())
        shutil.rmtree(cls.root)

    async def test_real_self_signed_server_accepts_address_only_identity_and_keeps_it_on_reconnect(self):
        gate = admission.AdmissionController(None, rc_open=True)
        errors, peers, tasks = [], [], set()
        async def handle(reader, writer):
            tasks.add(asyncio.current_task())
            try:
                peers.append(await gate.authenticate(reader, writer))
                await reader.read()
            except admission.AdmissionError as error: errors.append(error.category)
            finally:
                await tls.close_tls_stream(writer)
                tasks.discard(asyncio.current_task())
        listener = await tls.start_tls_server(handle, '127.0.0.1', 0, tls.load_server_context(self.cert, self.key))
        port = listener.sockets[0].getsockname()[1]
        token = 'ba1_' + secrets.token_urlsafe(32)
        try:
            for _ in range(2):
                reader, writer = await tls.open_verified_connection('127.0.0.1', port, tls.rc_client_context('127.0.0.1'))
                try:
                    self.assertEqual(await admission.authenticate_client(reader, writer, token, rc_open=True), admission.rc_player_id(token))
                    self.assertIn(writer.get_extra_info('ssl_object').version(), ('TLSv1.2', 'TLSv1.3'))
                finally: await tls.close_tls_stream(writer)
            # The older verified mode still refuses this certificate/identity.
            with self.assertRaises(ssl.SSLCertVerificationError):
                await tls.open_verified_connection('127.0.0.1', port, tls.load_client_context(self.cert, 'wrong.invalid'))
            self.assertEqual(peers, [admission.rc_player_id(token)] * 2)
            self.assertFalse(errors)
        finally:
            listener.close(); await listener.wait_closed()
            if tasks: await asyncio.gather(*list(tasks), return_exceptions=True)
            await gate.close()

    async def test_open_protocol_is_rejected_by_invite_server(self):
        store = mock.Mock()
        gate = admission.AdmissionController(store)
        failures, tasks = [], set()
        async def handle(reader, writer):
            tasks.add(asyncio.current_task())
            try: await gate.authenticate(reader, writer)
            except admission.AdmissionError as error: failures.append(error.category)
            finally:
                await tls.close_tls_stream(writer)
                tasks.discard(asyncio.current_task())
        listener = await tls.start_tls_server(handle, '127.0.0.1', 0, tls.load_server_context(self.cert, self.key))
        try:
            reader, writer = await tls.open_verified_connection('127.0.0.1', listener.sockets[0].getsockname()[1], tls.rc_client_context('127.0.0.1'))
            try:
                with self.assertRaises(admission.AdmissionError):
                    await admission.authenticate_client(reader, writer, 'ba1_' + secrets.token_urlsafe(32), rc_open=True)
            finally: await tls.close_tls_stream(writer)
            self.assertEqual(failures, ['protocol'])
            store.authenticate.assert_not_called()
        finally:
            listener.close(); await listener.wait_closed()
            if tasks: await asyncio.gather(*list(tasks), return_exceptions=True)
            await gate.close()


if __name__ == '__main__': unittest.main()
