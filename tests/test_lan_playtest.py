"""LAN address, real TLS construction, and fail-closed owner-preflight controls.

Certificate construction explicitly mocks only file privacy; it proves neither
Windows DACL access nor real protected provisioning. Actual owner setup is separate.
"""
from contextlib import redirect_stdout
import ast
import io
import json
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
import zipfile
from unittest import mock

from server import credentials as private
from client_patch.transport import client, launcher
from tests.test_credentials import private_test_folder, remove_test_folder
from tests.test_tls_transport import find_openssl
from tools import prepare_lan_playtest as lan


class LANTests(unittest.TestCase):
    def test_coordinator_project_imports_exist_in_client_package(self):
        from tools.build_windows_packages import CLIENT
        required=set()
        for node in ast.walk(ast.parse(Path(lan.__file__).read_text())):
            modules=[]
            if isinstance(node,ast.Import):modules=[alias.name for alias in node.names]
            elif isinstance(node,ast.ImportFrom) and node.module:
                modules=[node.module]+[node.module+'.'+alias.name for alias in node.names]
            for module in modules:
                if not module.startswith(('server.','client_patch.','tools.')) and module not in ('server','client_patch','tools'):
                    continue
                base=module.replace('.','/')
                for name in (base+'.py',base+'/__init__.py'):
                    if (lan.ROOT/name).is_file():required.add(name)
        self.assertTrue(required)
        self.assertFalse(required-set(CLIENT),'Coordinator imports omitted from the client runtime: '+str(required-set(CLIENT)))

    def test_generated_host_paths_pass_real_config_and_tls_in_data_is_rejected(self):
        from server.configuration import load_config, ConfigurationError
        folder = private_test_folder('lan-config-')
        try:
            server = folder/'server'; (server/'config').mkdir(parents=True)
            example = lan.ROOT/'server/host-config.example.json'
            (server/'config/host.example.json').write_bytes(example.read_bytes())
            value, pki = lan.host_settings(server, '192.168.68.66', 47623)
            config = server/'config/host.json'
            lan.write_new(config, value)
            actual = load_config(config)
            self.assertEqual(actual.certificate_file, pki/'server.pem')
            self.assertEqual(actual.private_key_file, pki/'server.key')
            self.assertFalse(pki.is_relative_to(actual.data_directory))
            self.assertEqual(actual.credential_directory, server.resolve()/'data/private/credentials')
            # Reproduce the previous owner setup's exact directory relationship.
            value['certificate_file'] = str(actual.data_directory/'private/lan-playtest-tls/server.pem')
            value['private_key_file'] = str(actual.data_directory/'private/lan-playtest-tls/server.key')
            config.write_text(json.dumps(value), encoding='utf-8')
            with self.assertRaisesRegex(ConfigurationError, 'Keep TLS files in config'):
                load_config(config)
        finally:
            remove_test_folder(folder)

    def test_only_explicit_lan_ipv4_addresses_accepted(self):
        for value in ('192.168.68.66', '10.23.4.5', '172.16.1.2', '172.31.255.254'):
            self.assertEqual(lan.lan_address(value), value)
        for value in ('0.0.0.0', '127.0.0.1', '8.8.8.8', '100.116.1.1', '169.254.1.1',
                      '172.32.1.1', '192.168.01.2', '192.168.1.2\n', '::1', 'host.example', '1.2.3.4&exit'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                lan.lan_address(value)

    def test_real_certificate_covers_selected_ip_and_rejects_wrong_name(self):
        folder = private_test_folder('lan-pki-')
        try:
            with (mock.patch.object(private, '_ensure_private_directory', side_effect=lambda p: p.mkdir()),
                  mock.patch.object(private, '_private_create', side_effect=lambda p: p.open('x+b')),
                  mock.patch.object(private, '_assert_private_path')):
                version = lan.make_pki(folder/'pki', find_openssl(), '192.168.68.66')
            self.assertIn(version, ('TLSv1.2', 'TLSv1.3'))
            self.assertTrue((folder/'pki/server.key').stat().st_size > 0)
        finally:
            remove_test_folder(folder)

    def test_handoff_archive_rejects_extra_private_files_and_changed_programs(self):
        folder = private_test_folder('lan-archive-'); player = folder/'client'; player.mkdir()
        try:
            (player/'program.txt').write_bytes(b'authored program')
            (player/'package-manifest.json').write_bytes(b'authored manifest')
            archive = folder/'battleaces-client-win64.zip'
            manifest = dict(files={'program.txt': {}})
            for case in ('valid', 'extra-private-file', 'changed-program'):
                with zipfile.ZipFile(archive, 'w') as bundle:
                    bundle.writestr('battleaces-client-win64/package-manifest.json', b'authored manifest')
                    bundle.writestr('battleaces-client-win64/program.txt',
                        b'changed' if case == 'changed-program' else b'authored program')
                    if case == 'extra-private-file':
                        bundle.writestr('battleaces-client-win64/host-private.txt', b'authored forbidden fixture')
                sha = hashlib.sha256(archive.read_bytes()).hexdigest()
                if case == 'valid':
                    self.assertEqual(lan.read_client_archive(player, manifest, sha), archive.read_bytes())
                    with self.assertRaises(ValueError): lan.read_client_archive(player, manifest, '0'*64)
                else:
                    with self.assertRaises(ValueError): lan.read_client_archive(player, manifest, sha)
        finally:
            remove_test_folder(folder)


@unittest.skipUnless(os.name == 'nt', 'Windows owner preflight contract')
class OwnerPreflightTests(unittest.TestCase):
    def setUp(self):
        self.folder = private_test_folder('lan-preflight-')
        self.server = self.folder/'server'; self.player = self.folder/'client'; self.game = self.folder/'game'
        for path in (self.server, self.player):
            (path/'config').mkdir(parents=True)
            (path/'program/app/server').mkdir(parents=True)
            (path/'program/app/server/credentials.py').write_text('authored synthetic source')
        (self.player/'program/client-helper').mkdir()
        (self.player/'program/client-helper/BattleAcesOffline.dll').write_bytes(b'authored helper')
        self.game.mkdir(); (self.game/'BattleAcesOffline.dll').write_bytes(b'authored helper')
        (self.server/'assets/build-37822').mkdir(parents=True)
        (self.server/'assets/build-37822/asset-manifest.json').write_text('{}')
        self.openssl = self.folder/'not-executable.txt'; self.openssl.write_text('must not launch')
        self.args = SimpleNamespace(server_package=self.server, client_package=self.player, game=self.game,
            openssl=self.openssl, report=self.folder/'report.json', host_ip='192.168.68.66', port=47623,
            expected_source_sha256=lan.digest(lan.__file__), preflight_only=False)
        self.args.expected_client_archive_sha256 = 'a'*64
        self.patches = [mock.patch('tools.package_integrity.verify', return_value={'synthetic': 'inventory'}),
            mock.patch('client_patch.transport.launcher.verify_game'),
            mock.patch.object(private, '__file__', str(self.player/'program/app/server/credentials.py')),
            mock.patch.object(client, '__file__', str(self.player/'program/app/client_patch/transport/client.py')),
            mock.patch.object(launcher, '__file__', str(self.player/'program/app/client_patch/transport/launcher.py')),
            mock.patch.object(lan.sys, 'executable', str(self.player/'program/runtime/python.exe'))]
        self.patches.append(mock.patch.object(lan, 'read_client_archive', return_value=b'authored fixture'))
        for patch in self.patches: patch.start()

    def tearDown(self):
        for patch in reversed(self.patches): patch.stop()
        remove_test_folder(self.folder)

    def test_restricted_owner_does_not_attempt_private_operations_or_spawn(self):
        with (mock.patch.object(lan, 'restricted_token', return_value=True),
              mock.patch.object(private, '_ensure_private_directory') as create,
              mock.patch.object(private, 'CredentialStore') as store,
              mock.patch.object(lan.subprocess, 'run') as spawn, redirect_stdout(io.StringIO())):
            self.assertEqual(lan.prepare(self.args), 2)
        create.assert_not_called(); store.assert_not_called(); spawn.assert_not_called()
        report = json.loads(self.args.report.read_bytes())
        self.assertFalse(report['passed'])
        self.assertFalse(report['protected_operations_attempted'])
        self.assertEqual(report['stage'], 'normal_desktop_account_required')
        self.assertFalse((self.server/'data').exists())
        self.assertFalse((self.player/'config/client.json').exists())

    def test_existing_configuration_or_changed_source_refuses_before_private_work(self):
        for case in ('config', 'source'):
            with self.subTest(case=case):
                if case == 'config':
                    config = self.server/'config/host.json'; config.write_bytes(b'owner bytes')
                else:
                    self.args.expected_source_sha256 = '0'*64
                with (mock.patch.object(lan, 'restricted_token') as token,
                      mock.patch.object(private, '_ensure_private_directory') as create,
                      self.assertRaises(ValueError)):
                    lan.prepare(self.args)
                token.assert_not_called(); create.assert_not_called()
                if case == 'config':
                    self.assertEqual(config.read_bytes(), b'owner bytes'); config.unlink()
                self.assertFalse(self.args.report.exists())


if __name__ == '__main__':
    unittest.main()
