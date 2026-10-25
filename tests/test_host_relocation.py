"""Copied-host preservation and Linux CLI controls; Wine execution is mocked."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest import mock

from server import rc_host
from server.configuration import load_config
from tools import host_relocation as migration, linux_server as linux

ROOT = Path(__file__).resolve().parents[1]


class RelocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.host = self.root / 'copied host'
        self.path = self.host / 'config/host.json'
        self.tls = self.host / 'config/private/original-identity'
        self.tls.mkdir(parents=True)
        (self.tls/'server.pem').write_bytes(b'authored certificate placeholder')
        (self.tls/'server.key').write_bytes(b'authored key placeholder')
        (self.host/'assets/build-37822').mkdir(parents=True)
        (self.host/'assets/build-37822/asset-manifest.json').write_text('{}')
        (self.host/'data/profiles').mkdir(parents=True)
        (self.host/'data/profiles/keep').write_bytes(b'preserved player state')
        self.value = json.loads((ROOT/'server/host-config.example.json').read_text())
        self.value.update(schema=2, access_mode='rc-open', credential_directory=None,
                          assets_directory='C:/Example/Desktop/host/assets/build-37822',
                          data_directory='C:/Example/Desktop/host/data',
                          certificate_file='C:/Example/Desktop/host/config/private/original-identity/server.pem',
                          private_key_file='C:/Example/Desktop/host/config/private/original-identity/server.key',
                          listen_port=47891, dashboard_port=8080)
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.value, indent=2)+'\n')

    def test_relocation_preserves_identity_data_options_and_exact_backup(self):
        raw = self.path.read_bytes()
        protected = {p:p.read_bytes() for p in (self.tls/'server.pem', self.tls/'server.key',
                                              self.host/'data/profiles/keep')}
        backup = migration.relocate(self.host)
        self.assertEqual(backup.read_bytes(), raw)
        c = migration.preflight(self.host)
        self.assertEqual(c.data_directory, self.host/'data')
        self.assertEqual(c.certificate_file, self.tls/'server.pem')
        self.assertEqual((c.listen_port, c.dashboard_port), (47891, 8080))
        self.assertEqual(protected, {p:p.read_bytes() for p in protected})
        self.assertIsNone(migration.relocate(self.host))
        self.assertEqual(len(list(self.path.parent.glob('host.json.before-relocate-*'))), 1)

    def test_stale_paths_fail_preflight_with_repair_command(self):
        with self.assertRaisesRegex(ValueError, 'relocate --host-dir'):
            migration.preflight(self.host)

    def test_missing_copied_identity_or_profiles_never_creates_replacement(self):
        for field in ('private_key_file', 'data_directory'):
            with self.subTest(field=field):
                self.value[field] += '-missing'; self.save(); before=self.path.read_bytes()
                with self.assertRaisesRegex(ValueError, 'Missing copied'):
                    migration.relocate(self.host)
                self.assertEqual(self.path.read_bytes(), before)
                self.assertFalse(list(self.path.parent.glob('host.json.before-relocate-*')))
                self.value[field] = self.value[field].removesuffix('-missing')

    def test_custom_outside_and_traversal_paths_are_not_guessed(self):
        for item in ('D:/custom/server.key', 'C:/Example/Desktop/host/../elsewhere/key'):
            self.value['private_key_file']=item;self.save();before=self.path.read_bytes()
            with self.assertRaises(ValueError): migration.relocate(self.host)
            self.assertEqual(self.path.read_bytes(), before)

    def test_schema_duplicates_and_invalid_options_preserve_config(self):
        self.value['listen_port']=True;self.save()
        for raw in (self.path.read_bytes(), b'{"schema":2,"schema":2}', b'{broken'):
            self.path.write_bytes(raw)
            with self.assertRaises(ValueError): migration.relocate(self.host)
            self.assertEqual(self.path.read_bytes(), raw)
            self.assertFalse(list(self.path.parent.glob('.relocate-*')))
            self.assertFalse(list(self.path.parent.glob('host.json.before-relocate-*')))

    def test_changed_config_and_replace_failure_preserve_originals(self):
        raw=self.path.read_bytes(); original_load=migration.load_config
        def competing_edit(path):
            c=original_load(path)
            self.path.write_bytes(raw+b' ')
            return c
        with mock.patch.object(migration, 'load_config', side_effect=competing_edit):
            with self.assertRaisesRegex(ValueError, 'changed'): migration.relocate(self.host)
        self.assertEqual(self.path.read_bytes(), raw+b' ')
        with mock.patch.object(migration.os, 'replace', side_effect=OSError('authored refusal')):
            with self.assertRaises(OSError): migration.relocate(self.host)
        self.assertEqual(self.path.read_bytes(), raw+b' ')
        self.assertEqual(next(self.path.parent.glob('host.json.before-relocate-*')).read_bytes(), raw+b' ')
        self.assertFalse(list(self.path.parent.glob('.relocate-*')))

    def test_preflight_reports_missing_relative_file(self):
        migration.relocate(self.host)
        (self.tls/'server.key').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing private_key_file'):
            migration.preflight(self.host)

    def test_persistent_prefix_and_generated_launcher_select_copied_host(self):
        migration.relocate(self.host)
        deployment=self.root/'persistent wine'
        def wine(command, **kwargs):
            self.assertEqual(command, ['wine','cmd','/c','echo','BA_WINE_READY'])
            self.assertEqual(kwargs['env']['WINEPREFIX'], str(deployment/'wineprefix'))
            self.assertEqual(kwargs['env']['WINEARCH'], 'win64')
            prefix=deployment/'wineprefix';prefix.mkdir();(prefix/'system.reg').write_text('authored')
            kwargs['stdout'].write(b'display warnings\nBA_WINE_READY\r\n')
            return NS(returncode=0)
        with mock.patch.object(linux, 'verify'), mock.patch.object(linux.subprocess, 'run', side_effect=wine):
            linux.prepare_prefix(deployment, self.host)
        launcher=(deployment/'Start Server.sh').read_text()
        self.assertIn('--host-dir', launcher)
        self.assertIn(str(self.host), launcher)
        with mock.patch.object(linux, 'verify'), mock.patch.object(linux.subprocess, 'run') as run:
            with self.assertRaises(FileExistsError): linux.prepare_prefix(deployment, self.host)
            run.assert_not_called()

    def test_prefix_failure_preserves_log_without_launcher(self):
        migration.relocate(self.host)
        for mode in ('nonzero', 'no-marker', 'timeout'):
            deployment=self.root/mode
            def wine(command, **kwargs):
                kwargs['stdout'].write(b'authored failure\n')
                if mode=='timeout': raise subprocess.TimeoutExpired(command, 120)
                return NS(returncode=1 if mode=='nonzero' else 0)
            with self.subTest(mode=mode), mock.patch.object(linux, 'verify'), \
                 mock.patch.object(linux.subprocess, 'run', side_effect=wine):
                with self.assertRaises(ValueError): linux.prepare_prefix(deployment, self.host)
            self.assertEqual((deployment/'prefix-check.log').read_bytes(), b'authored failure\n')
            self.assertFalse((deployment/'Start Server.sh').exists())

    def test_prefix_refuses_overlapping_host_before_wine(self):
        for root in (self.host, self.host/'prefix', self.root):
            with self.subTest(root=root), mock.patch.object(linux.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'separate'): linux.prepare_prefix(root, self.host)
                run.assert_not_called()

    def test_start_rejects_stale_config_before_exec(self):
        with mock.patch.object(linux.sys, 'platform', 'linux'), mock.patch.object(linux.shutil, 'which', return_value='found'), \
             mock.patch.object(linux, 'verify'), mock.patch.object(linux.os, 'execvpe') as execute, \
             mock.patch.object(linux, 'initialize_config') as initialize:
            self.assertEqual(linux.main(['start','--host-dir',str(self.host),'--root',str(self.root/'wine')]),1)
        execute.assert_not_called();initialize.assert_not_called()

    def test_new_windows_host_paths_are_portable_and_existing_config_is_preserved(self):
        self.path.unlink()
        with mock.patch.object(rc_host, 'generate_certificate', return_value=(b'certificate', b'key')), \
             mock.patch.object(rc_host, 'load_server_context'), \
             mock.patch.object(rc_host.private, '_ensure_private_directory', side_effect=lambda p:p.mkdir(parents=True,exist_ok=True)), \
             mock.patch.object(rc_host.private, '_write_file', side_effect=lambda p,b:p.write_bytes(b)):
            config=rc_host.initialize(self.path, self.host/'assets/build-37822')
        self.assertEqual(config.assets_directory, self.host/'assets/build-37822')
        value=json.loads(self.path.read_bytes())
        for name in migration.PATH_FIELDS:
            if value[name] is not None:
                self.assertFalse(Path(value[name]).is_absolute())
                self.assertNotIn('\\',value[name])
        before=self.path.read_bytes()
        with mock.patch.object(rc_host, 'generate_certificate', side_effect=AssertionError('no replacement')):
            rc_host.initialize(self.path, self.host/'assets/build-37822')
        self.assertEqual(self.path.read_bytes(),before)
        self.assertFalse(list(self.path.parent.glob('.rc-host-*')))

    def test_start_and_check_use_selected_persistent_prefix_and_copied_host(self):
        migration.relocate(self.host)
        root=self.root/'deployment';(root/'wineprefix').mkdir(parents=True)
        (root/'wineprefix/system.reg').write_text('authored')
        for action in ('start', 'check'):
            with self.subTest(action=action), mock.patch.object(linux.sys, 'platform', 'linux'), \
                 mock.patch.object(linux.shutil, 'which', return_value='found'), \
                 mock.patch.object(linux, 'verify'), mock.patch.object(linux.os, 'chdir') as chdir, \
                 mock.patch.object(linux.os, 'execvpe') as execute:
                linux.main([action,'--root',str(root),'--host-dir',str(self.host)])
            chdir.assert_called_once_with(self.host)
            name,command,environment=execute.call_args.args
            self.assertEqual(name,'wine')
            self.assertEqual(environment['WINEPREFIX'],str(root/'wineprefix'))
            self.assertEqual(command, ['wine',str(self.host/'Start Server.exe')] if action=='start'
                             else linux.runtime_command(self.host,'check'))


if __name__ == '__main__': unittest.main()
