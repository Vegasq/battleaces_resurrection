"""Local startup and optional remote configuration have independent failure paths."""
import asyncio
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import unittest
from unittest import mock
import uuid
import shutil

from client_patch.transport import client, launcher, bridge, enrollment

ROOT = Path(__file__).resolve().parents[1]


class UnifiedLauncherTests(unittest.TestCase):
    def setUp(self):
        self.folder = ROOT / 'local' / ('unified-launcher-' + uuid.uuid4().hex)
        self.game = self.folder / 'working game'
        self.game.mkdir(parents=True)
        (self.game / 'Battle Aces.exe').write_bytes(b'authored non-executable fixture')
        self.path = self.folder / 'settings/client.json'

    def tearDown(self):
        self.folder.resolve().relative_to((ROOT / 'local').resolve())
        shutil.rmtree(self.folder)

    def save(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(value), encoding='utf-8')

    def test_first_launch_creates_editable_local_defaults_without_reading_invites(self):
        with (mock.patch.object(launcher, 'read_credential_file', side_effect=AssertionError('must not read invite')),
              mock.patch.object(launcher.tls, 'load_client_context', side_effect=AssertionError('must not load trust')),
              mock.patch('client_patch.transport.player_name.getpass.getuser', return_value='LAN\\QA!Tester')):
            result = client.prepare_settings(self.path, self.game)
            self.assertEqual(result['game_directory'], self.game)
            self.assertEqual(result['display_name'], 'QA Tester')
            self.assertEqual(json.loads(self.path.read_text())['schema'], 3)
            with self.assertRaises(bridge.RemoteUnavailable) as failure: client.load_connection(self.path)
            self.assertEqual(failure.exception.reason, bridge.UNCONFIGURED_FAILURE)

    def test_bad_online_settings_do_not_prevent_local_play_or_silently_connect(self):
        value = client.defaults(self.game)
        value.update(display_name='Local Player', server_host='bad host', server_name='localhost',
                     server_port=True, ca_bundle='missing-ca.pem', credential_file='missing-private.json')
        self.save(value)
        self.assertEqual(client.prepare_settings(self.path)['display_name'], 'Local Player')
        resolver = launcher.RemoteConfigResolver(self.path, self.game, config_loader=client.load_connection)
        with self.assertRaises(bridge.RemoteUnavailable) as failure: asyncio.run(resolver())
        self.assertEqual(failure.exception.reason, bridge.CONFIG_FAILURE)
        setup = enrollment.setup_data(self.path)
        self.assertEqual(setup['game_directory'], str(self.game))
        self.assertEqual(setup['display_name'], 'Local Player')
        self.assertEqual(setup['expected_ca_sha256'], '')

    def test_schema2_is_accepted_without_credentials_and_remains_unchanged(self):
        value = client.defaults(self.game)
        value.update(schema=2, server_host='127.0.0.1', server_name='localhost',
                     ca_bundle='absent-ca.pem', credential_file='absent-invite.json')
        self.save(value)
        before = self.path.read_bytes()
        self.assertEqual(client.prepare_settings(self.path)['game_directory'], self.game)
        self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaises(bridge.RemoteUnavailable) as failure:
            launcher.RemoteConfigResolver(self.path, self.game, config_loader=client.load_connection).read()
        self.assertEqual(failure.exception.reason, bridge.UNCONFIGURED_FAILURE)

    def test_invalid_local_settings_and_unknown_secrets_are_rejected(self):
        for key, value in (('schema', True), ('schema', 1), ('display_name', 'bad\nname'),
                           ('token', 'do not accept inline secrets'), ('game_directory', 'BattleAcesBeta_untouched')):
            config = client.defaults(self.game);config[key] = value
            with self.subTest(key=key), self.assertRaises(launcher.LaunchError):
                client.local_settings(config, self.path)
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"schema":3,"schema":3}')
        with self.assertRaises(launcher.LaunchError): client.prepare_settings(self.path)

    def test_existing_game_binding_and_relative_paths(self):
        self.save(dict(schema=3, game_directory='../working game', display_name='Config Name'))
        self.assertEqual(client.prepare_settings(self.path)['game_directory'], self.game)
        with self.assertRaises(launcher.LaunchError): client.prepare_settings(self.path, self.folder / 'different')
        missing = self.folder / 'absent/client.json'
        with self.assertRaises(launcher.LaunchError): client.prepare_settings(missing, self.folder / 'missing game')
        self.assertFalse(missing.exists())

    def test_profile_key_is_independent_of_display_name_and_online_schema(self):
        config = client.defaults(self.game)
        config.update(local_profile='friends_02', display_name='First Name', server_host='127.0.0.1',
                      server_name='localhost', ca_bundle='ca.pem', credential_file='invite.json')
        for schema in (2, 3):
            config['schema'] = schema
            self.save(config)
            self.assertEqual(client.prepare_settings(self.path)['local_profile'], 'friends_02')
            self.assertNotIn('local_profile', client.load_connection(self.path))
            config['display_name'] = 'Renamed Player'
            self.assertEqual(client.local_settings(config, self.path)['local_profile'], 'friends_02')
        config.pop('local_profile')
        self.assertEqual(client.local_settings(config, self.path)['local_profile'], 'default')
        for key in ('', 'UPPER', '../escape', 'a/b', 'a\\b', 'a b', 'a' * 49, 'con', 'lpt9', True, None):
            with self.subTest(key=key), self.assertRaises(launcher.LaunchError):
                client.local_settings(dict(config, local_profile=key), self.path)

    def test_unwritable_new_config_keeps_local_launch_available(self):
        original = Path.open
        def open_file(path, *args, **kwargs):
            if path == self.path and args and args[0] == 'x': raise PermissionError('authored denial')
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, 'open', open_file), redirect_stdout(io.StringIO()):
            self.assertEqual(client.prepare_settings(self.path, self.game)['game_directory'], self.game)
        self.assertFalse(self.path.exists())

    def test_start_uses_unified_transport_without_diagnostic_actions(self):
        async def launch(config, remote, args):
            argv = launcher.game_arguments(config, None, 1234, args)
            self.assertIn('-unified-client', argv)
            self.assertIn('-secure-transport-version=2', argv)
            self.assertIn('-local-profile=default', argv)
            self.assertIn('-public-queue-experimental', argv)
            self.assertIn('-local-cosmetics-experimental', argv)
            self.assertFalse(any('smoke' in value or 'audit' in value or 'auto-' in value for value in argv))
            with self.assertRaises(bridge.RemoteUnavailable): await remote()
            return 17
        with mock.patch.object(launcher, 'launch', side_effect=launch):
            self.assertEqual(client.main(['--config', str(self.path), '--game', str(self.game)]), 17)


if __name__ == '__main__': unittest.main()
