"""Secure launch configuration and exact local patch compatibility boundaries."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

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

    def install(self, *, secure=True, protocol3=True):
        root = self.folder / 'working-game'
        state = root / '.battleaces-resurrection'
        state.mkdir(parents=True)
        helper = b'authored helper fixture ' + (b'BA_RESURRECTION_TLS_BRIDGE_V1' if secure else b'old helper')
        helper += b' BA_RESURRECTION_NATIVE_SETTINGS_V1 OfflineLocalUserConfigPath\0'
        if protocol3: helper += b' BA_RESURRECTION_GAME_PROTOCOL_3'
        component = b'authored component fixture'
        (root / 'BattleAcesOffline.dll').write_bytes(helper)
        (root / 'GameAssembly.dll').write_bytes(component)
        (root / 'Battle Aces.exe').write_bytes(b'authored non-executable fixture')
        manifest = dict(schema=2, state='dedicated-prototype-v2', helper_sha256=hashlib.sha256(helper).hexdigest(),
                        local_settings={'isolated': True}, call_hooks=[{'name': 'OfflineLocalUserConfigPath'}],
                        components={'GameAssembly.dll': {'installed_sha256': hashlib.sha256(component).hexdigest()}})
        path = state / 'patch-manifest.json'
        path.write_text(json.dumps(manifest), encoding='utf-8')
        return root, path, manifest

    def test_native_settings_isolation_requires_manifest_and_early_hook(self):
        root, path, manifest = self.install()
        launch.verify_game(root)
        for key, value in (('local_settings', None), ('local_settings', {'isolated': False}),
                           ('call_hooks', []), ('call_hooks', None)):
            previous = manifest[key]
            manifest[key] = value
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(launch.LaunchError, 'native local-user settings isolation'):
                launch.verify_game(root)
            manifest[key] = previous

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

    def test_secure_helper_with_old_game_protocol_rejected_before_spawn(self):
        root, _, _ = self.install(protocol3=False)
        with self.assertRaisesRegex(launch.LaunchError, 'protocol3'):
            launch.verify_game(root)

    def test_dynamic_identity_requires_v2_helper_before_spawn(self):
        root, path, manifest = self.install()
        with self.assertRaisesRegex(launch.LaunchError, 'ABI2'):
            launch.verify_game(root, bridge_version=2)
        helper = root / 'BattleAcesOffline.dll'
        helper.write_bytes(helper.read_bytes() + b' BA_RESURRECTION_TLS_BRIDGE_V2')
        manifest['helper_sha256'] = hashlib.sha256(helper.read_bytes()).hexdigest()
        path.write_text(json.dumps(manifest))
        launch.verify_game(root, bridge_version=2)
        for version in (True, 0, 3):
            with self.assertRaises(launch.LaunchError): launch.verify_game(root, bridge_version=version)

    def test_dynamic_arguments_have_no_startup_identity_or_private_settings(self):
        config = self.load()
        argv = launch.game_arguments(config, None, 1234,
            argparse.Namespace(run_name='test', dynamic_identity_experimental=True))
        self.assertIn('-secure-transport-version=2', argv)
        self.assertFalse(any(argument.startswith('-player-id=') for argument in argv))
        self.assertIn('-player-name=Player With Spaces', argv)
        self.assertNotIn(str(config['credential_file']), argv)
        self.assertNotIn(str(config['ca_bundle']), argv)

    def test_unified_launch_requires_new_helper_and_selects_both_adapters(self):
        root, path, manifest = self.install()
        manifest['community'] = dict(native_scope='custom-match-prototype')
        helper = root / 'BattleAcesOffline.dll'
        helper.write_bytes(helper.read_bytes() + b' BA_RESURRECTION_TLS_BRIDGE_V2 BA_RESURRECTION_COMMUNITY_MATCH_V1')
        manifest['helper_sha256'] = hashlib.sha256(helper.read_bytes()).hexdigest()
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(launch.LaunchError, 'unified client lifecycle'):
            launch.verify_game(root, community=True, bridge_version=2, unified=True)
        helper.write_bytes(helper.read_bytes() + b' BA_RESURRECTION_UNIFIED_CLIENT_V1')
        manifest['helper_sha256'] = hashlib.sha256(helper.read_bytes()).hexdigest()
        path.write_text(json.dumps(manifest))
        launch.verify_game(root, community=True, bridge_version=2, unified=True)
        argv = launch.game_arguments(self.load(), None, 1234, argparse.Namespace(run_name='test', unified_experimental=True))
        for flag in ('-unified-client', '-secure-transport-version=2', '-dedicated-community'):
            self.assertIn(flag, argv)
        self.assertNotIn('-offline-practice', argv)
        self.assertFalse(any(argument.startswith('-player-id=') for argument in argv))

    @patch('client_patch.patcher.bundle_loading.verify_installed')
    def test_ordinary_player_requires_complete_helper_and_installed_feature_recipe(self, verify_bundles):
        root, path, manifest = self.install()
        helper = root / 'BattleAcesOffline.dll'
        helper.write_bytes(helper.read_bytes()+b' BA_RESURRECTION_TLS_BRIDGE_V2 BA_RESURRECTION_UNIFIED_CLIENT_V1 BA_RESURRECTION_COMMUNITY_MATCH_V1')
        manifest['community'] = dict(native_scope='custom-match-prototype')
        manifest['helper_sha256'] = hashlib.sha256(helper.read_bytes()).hexdigest()
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(launch.LaunchError, 'complete client patch'):
            launch.verify_game(root, community=True, bridge_version=2, unified=True, player_features=True)
        helper.write_bytes(helper.read_bytes()+b' BA_RESURRECTION_PUBLIC_QUEUE_V1 BA_RESURRECTION_COSMETICS_UNLOCK_V1 BA_RESURRECTION_COSMETICS_PERSIST_V1 BA_RESURRECTION_NATIVE_DECK_INPUT_V1 BA_RESURRECTION_NATIVE_SETTINGS_ATOMIC_V1 BA_RESURRECTION_NATIVE_STORAGE_V1 BA_RESURRECTION_NATIVE_BACKUP_GUARD_V1')
        manifest['helper_sha256'] = hashlib.sha256(helper.read_bytes()).hexdigest()
        helper.write_bytes(helper.read_bytes()+b' BA_RESURRECTION_NATIVE_REPLAY_LONG_PATH_V2')
        manifest['helper_sha256'] = hashlib.sha256(helper.read_bytes()).hexdigest()
        manifest['cosmetics'] = dict(experimental=True, persistence=True)
        manifest['local_settings'].update(deck_input_guard=True, write_publication='original-serializer-flush-handle-rename')
        manifest['local_storage'] = dict(isolated=True, steam_file_sync='local-only', autosave_exception_boundary=True, autosave_call_sites=4, backup_input_guard=True, backup_publication='original-json-text-flush-handle-rename',replay_path_api='extended-local-drive')
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(launch.LaunchError, 'verified local bundle loading'):
            launch.verify_game(root, community=True, bridge_version=2, unified=True, player_features=True)
        from client_patch.patcher import bundle_loading
        manifest['asset_loading'] = bundle_loading.descriptor()
        path.write_text(json.dumps(manifest))
        launch.verify_game(root, community=True, bridge_version=2, unified=True, player_features=True)
        verify_bundles.assert_called_once_with(root, manifest['asset_loading'], progress=bundle_loading.console_progress)
        for storage in (None, {}, dict(isolated=False, steam_file_sync='local-only', autosave_exception_boundary=True),
                        dict(isolated=True, steam_file_sync='cloud', autosave_exception_boundary=True),
                        dict(isolated=True, steam_file_sync='local-only', autosave_exception_boundary=False),
                        dict(isolated=True, steam_file_sync='local-only', autosave_exception_boundary=True, autosave_call_sites=1)):
            manifest['local_storage'] = storage;path.write_text(json.dumps(manifest))
            with self.subTest(storage=storage), self.assertRaisesRegex(launch.LaunchError,'complete client patch'):
                launch.verify_game(root, community=True, bridge_version=2, unified=True, player_features=True)
        manifest['local_storage'] = dict(isolated=True, steam_file_sync='local-only', autosave_exception_boundary=True, autosave_call_sites=4, backup_input_guard=True, backup_publication='original-json-text-flush-handle-rename',replay_path_api='extended-local-drive')
        complete_storage=dict(manifest['local_storage'])
        for field,value in (('backup_input_guard',False),('backup_publication',None),('backup_publication','in-place'),
                            ('replay_path_api',None),('replay_path_api','diagnostic-only')):
            manifest['local_storage']=dict(complete_storage,**{field:value});path.write_text(json.dumps(manifest))
            with self.subTest(field=field,value=value),self.assertRaisesRegex(launch.LaunchError,'complete client patch'):
                launch.verify_game(root,community=True,bridge_version=2,unified=True,player_features=True)
        manifest['local_storage']=complete_storage
        for changed in (dict(experimental=False, persistence=True), dict(experimental=True, persistence=False), None):
            manifest['cosmetics'] = changed;path.write_text(json.dumps(manifest))
            with self.subTest(recipe=changed), self.assertRaisesRegex(launch.LaunchError, 'complete client patch'):
                launch.verify_game(root, community=True, bridge_version=2, unified=True, player_features=True)

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

    def test_community_launch_requires_matching_patch_and_helper(self):
        root, path, manifest = self.install()
        with self.assertRaisesRegex(launch.LaunchError, 'experimental community'):
            launch.verify_game(root, community=True)
        manifest['community'] = dict(native_scope='custom-match-prototype')
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(launch.LaunchError, 'community match ABI1'):
            launch.verify_game(root, community=True)
        helper = root / 'BattleAcesOffline.dll'
        helper.write_bytes(helper.read_bytes() + b' BA_RESURRECTION_COMMUNITY_MATCH_V1')
        manifest['helper_sha256'] = hashlib.sha256(helper.read_bytes()).hexdigest()
        path.write_text(json.dumps(manifest))
        launch.verify_game(root, community=True)
        config = self.load()
        normal = launch.game_arguments(config, 'p_' + '1' * 32, 1234, argparse.Namespace(run_name='test'))
        custom = launch.game_arguments(config, 'p_' + '1' * 32, 1234,
            argparse.Namespace(run_name='test', community_experimental=True))
        self.assertNotIn('-dedicated-community', normal)
        self.assertIn('-dedicated-community', custom)
        with self.assertRaises(launch.LaunchError):
            launch.game_arguments(config, 'p_' + '1' * 32, 1234,
                argparse.Namespace(run_name='test', community_experimental=True, auto_ready=True))

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
