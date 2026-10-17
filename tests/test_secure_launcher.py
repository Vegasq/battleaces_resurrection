"""Secure launch configuration and exact local patch compatibility boundaries."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import unittest
import uuid

from client_patch.transport import launcher as launch
from tools.audit_repository import inspect_content

ROOT = Path(__file__).resolve().parents[1]


class SecureLauncherTests(unittest.TestCase):
    def setUp(self):
        self.folder = ROOT / 'local' / ('secure-launcher-' + uuid.uuid4().hex)
        self.folder.mkdir(parents=True)
        self.config = dict(schema=2, game_directory='working-game', server_host='127.0.0.1', server_port=47623,
            server_name='Game.Example.', ca_bundle='owner-ca.pem', credential_file='private-invite.json',
            display_name='Player With Spaces', room='friends')
        self.path = self.folder / 'secure-client-config.json'

    def tearDown(self):
        resolved = self.folder.resolve()
        resolved.relative_to((ROOT / 'local').resolve())
        shutil.rmtree(resolved)

    def load(self):
        self.path.write_text(json.dumps(self.config), encoding='utf-8')
        return launch.load_config(self.path)

    def install(self, *, secure=True):
        root = self.folder / 'working-game'
        state = root / '.battleaces-resurrection'
        state.mkdir(parents=True)
        helper = b'authored helper fixture ' + (b'BA_RESURRECTION_TLS_BRIDGE_V1' if secure else b'old helper')
        component = b'authored component fixture'
        (root / 'BattleAcesOffline.dll').write_bytes(helper)
        (root / 'GameAssembly.dll').write_bytes(component)
        (root / 'Battle Aces.exe').write_bytes(b'authored non-executable fixture')
        manifest = dict(schema=2, state='dedicated-prototype-v2', helper_sha256=hashlib.sha256(helper).hexdigest(),
                        components={'GameAssembly.dll': {'installed_sha256': hashlib.sha256(component).hexdigest()}})
        path = state / 'patch-manifest.json'
        path.write_text(json.dumps(manifest), encoding='utf-8')
        return root, path, manifest

    def test_explicit_trust_identity_and_paths_resolve_from_config_directory(self):
        config = self.load()
        self.assertEqual(config['server_host'], '127.0.0.1')
        self.assertEqual(config['server_name'], 'game.example')
        self.assertEqual(config['ca_bundle'], self.folder / 'owner-ca.pem')
        self.assertEqual(config['credential_file'], self.folder / 'private-invite.json')

    def test_embedded_token_self_reported_id_and_ambiguous_json_rejected(self):
        for key in ('token', 'player_id', 'disable_certificate_validation'):
            self.config[key] = 'not allowed'
            with self.assertRaises(launch.LaunchError): self.load()
            del self.config[key]
        self.path.write_text('{"schema":2,"schema":2}')
        with self.assertRaises(launch.LaunchError): launch.load_config(self.path)

    def test_bad_port_name_and_recovery_target_rejected(self):
        for key, value in (('server_port', True), ('server_port', 0), ('room', '../escape'),
                           ('display_name', 'bad\nname'), ('game_directory', 'BattleAcesBeta_untouched')):
            previous = self.config[key]
            self.config[key] = value
            with self.assertRaises(launch.LaunchError): self.load()
            self.config[key] = previous

    def test_helper_without_bridge_cannot_fall_back_to_plaintext(self):
        root, _, _ = self.install(secure=False)
        with self.assertRaises(launch.LaunchError): launch.verify_game(root)

    def test_component_hash_restore_and_path_escape_fail_before_spawn(self):
        root, path, manifest = self.install()
        launch.verify_game(root)
        manifest['state'] = 'restored'
        path.write_text(json.dumps(manifest))
        with self.assertRaises(launch.LaunchError): launch.verify_game(root)
        manifest['state'] = 'dedicated-prototype-v2'
        manifest['components']['../outside.dll'] = {'installed_sha256': '0' * 64}
        path.write_text(json.dumps(manifest))
        with self.assertRaises(launch.LaunchError): launch.verify_game(root)
        del manifest['components']['../outside.dll']
        path.write_text(json.dumps(manifest))
        (root / 'GameAssembly.dll').write_bytes(b'changed')
        with self.assertRaises(launch.LaunchError): launch.verify_game(root)

    def test_game_arguments_have_only_public_identity_and_handle(self):
        config = self.load()
        argv = launch.game_arguments(config, 'p_' + '1' * 32, 1234, argparse.Namespace(run_name='test'))
        self.assertIn('-player-name=Player With Spaces', argv)
        self.assertIn('-secure-transport-socket=1234', argv)
        self.assertNotIn(str(config['credential_file']), argv)
        self.assertNotIn(str(config['ca_bundle']), argv)
        self.assertFalse(any(argument.startswith('-lan-slot=') for argument in argv))

    def test_publication_audit_catches_an_invite_handoff(self):
        authored_token = 'ba1_' + 'a' * 43
        reasons = inspect_content('client_patch/launcher/accidental.json', json.dumps({'token': authored_token}).encode())
        self.assertIn('player invite credential', reasons)


if __name__ == '__main__': unittest.main()
