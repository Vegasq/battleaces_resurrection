"""Synthetic archives test distribution boundaries without downloading runtimes."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest import mock
import zipfile

from tools import build_windows_packages as builder
from tools import package_client, package_server
from tools.package_integrity import verify, PackageError
from tests.test_credentials import private_test_folder, remove_test_folder


class WindowsPackageTests(unittest.TestCase):
    def setUp(self):
        self.root = private_test_folder('packages-')
        self.runtime = self.root / 'authored-runtime.zip'
        self.helper = self.root / 'authored-helper.dll'
        helper = bytearray(256)
        helper[:2] = b'MZ'; struct.pack_into('<I', helper, 0x3c, 0x80)
        struct.pack_into('<4sH', helper, 0x80, b'PE\0\0', 0x8664)
        struct.pack_into('<H', helper, 0x80+22, 0x2000)
        struct.pack_into('<H', helper, 0x80+24, 0x20b)
        helper.extend(b'\0'.join(builder.MARKERS)); self.helper.write_bytes(helper)
        self.server_launcher = self.root/'Start Server.exe'
        executable = bytearray(helper[:512])
        struct.pack_into('<H', executable, 0x80+22, 2)
        struct.pack_into('<H', executable, 0x80+24+68, 3)
        executable.extend(b'BA_RESURRECTION_SERVER_CONSOLE_V1')
        self.server_launcher.write_bytes(executable)
        self.launcher_receipt = self.root/'launcher-build.json'
        self.launcher_receipt.write_text(json.dumps(dict(schema=1,launcher_sha256=builder.sha(executable),
            source_sha256={name:builder.sha(builder.source_file(name)) for name in builder.LAUNCHER_SOURCES},
            argument_tests_passed=True)))
        self.write_runtime()
        self.pins = mock.patch.object(builder, 'PYTHON_ZIP_SHA256', hashlib.sha256(self.runtime.read_bytes()).hexdigest())
        self.pins.start()
        self.revision = mock.patch.object(builder, 'source_revision', return_value={'revision': 'test-authored', 'dirty': False})
        self.revision.start()

    def tearDown(self):
        self.revision.stop(); self.pins.stop(); remove_test_folder(self.root)

    def write_runtime(self, extra=()):
        with zipfile.ZipFile(self.runtime, 'w') as archive:
            for name in ('python.exe', 'python314.dll', 'python314.zip', 'python314._pth', 'LICENSE.txt', '_ssl.pyd', '_ctypes.pyd'):
                archive.writestr(zipfile.ZipInfo(name), b'authored dummy runtime, never executable')
            for name, value in extra:
                if isinstance(name, str):
                    info = zipfile.ZipInfo(name)
                    info.filename = name  # Preserve a hostile raw Windows separator in the archive.
                else: info = name
                archive.writestr(info, value)

    def build(self, name='out'):
        return builder.build(self.runtime, self.helper, self.root / name, server_launcher=self.server_launcher)

    def test_server_console_launcher_must_match_its_tested_current_source_receipt(self):
        receipt = json.loads(self.launcher_receipt.read_text())
        for change in ('digest', 'source', 'tests'):
            altered = json.loads(json.dumps(receipt))
            if change == 'digest': altered['launcher_sha256'] = '0'*64
            elif change == 'source': altered['source_sha256'].pop('server/launcher/launch_args.hpp')
            else: altered['argument_tests_passed'] = False
            self.launcher_receipt.write_text(json.dumps(altered))
            with self.subTest(change=change), self.assertRaisesRegex(PackageError, 'launcher build receipt'):
                self.build()
            self.assertFalse((self.root/'out').exists())
        self.launcher_receipt.write_text(json.dumps(receipt))
        self.build()
        package = self.root/'out/battleaces-server-win64'
        self.assertEqual((package/'Start Server.exe').read_bytes(), self.server_launcher.read_bytes())
        self.assertFalse((package/'Start Server.cmd').exists())

    def test_wrong_runtime_pin_or_unrecognized_helper_creates_no_output(self):
        self.runtime.write_bytes(self.runtime.read_bytes() + b'changed')
        with self.assertRaisesRegex(PackageError, 'pinned'): self.build()
        self.assertFalse((self.root/'out').exists())
        self.write_runtime(); self.helper.write_bytes(b'MZ' + b'original game dummy'*100)
        with self.assertRaises(PackageError): self.build()
        self.assertFalse((self.root/'out').exists())

    def test_archive_paths_and_member_types_are_checked_before_extraction(self):
        link = zipfile.ZipInfo('linked'); link.create_system = 3; link.external_attr = 0o120777 << 16
        for name in ('../outside', '/absolute', 'folder\\outside', 'a:stream', 'NUL.txt', 'trailing.', 'PYTHON.EXE', link):
            self.write_runtime([(name, b'authored')])
            # Only authored synthetic archives override the pin, to exercise
            # defense in depth. The production CLI has no hash override option.
            with mock.patch.object(builder, 'PYTHON_ZIP_SHA256', hashlib.sha256(self.runtime.read_bytes()).hexdigest()):
                with self.subTest(name=str(name)), self.assertRaises(PackageError): self.build()
            self.assertFalse((self.root/'out').exists())

    def test_packages_are_reproducible_allowlisted_and_detect_tampering(self):
        first, second = self.build(), self.build('again')
        self.assertEqual(first, second)
        for product, sources in (('client', builder.CLIENT), ('server', builder.SERVER)):
            folder = self.root / 'out' / ('battleaces-' + product + '-win64')
            inventory = verify(folder, product)
            modules = {name.removeprefix('program/app/') for name in inventory['files'] if name.startswith('program/app/')}
            self.assertEqual(modules, set(sources))
            self.assertFalse(any(Path(name).name.casefold() in ('gameassembly.dll', 'simulation.dll', 'ai.dll', 'global-metadata.dat') for name in inventory['files']))
            self.assertEqual((folder/'program/runtime/python314._pth').read_bytes(), builder.RUNTIME_PTH)
            if product == 'client':
                start = (folder / 'Start Client.cmd').read_text()
                self.assertIn('tools.package_client start %*', start)
                self.assertNotIn('smoke', start)
            else:
                self.assertEqual((folder/'Start Server.exe').read_bytes(), self.server_launcher.read_bytes())
                self.assertFalse((folder/'Start Server.cmd').exists())
            compatibility = json.loads((folder/'compatibility.json').read_bytes())
            self.assertFalse(compatibility['game_files_included'])
            self.assertFalse(compatibility['clean_windows_qualified'])
            with zipfile.ZipFile(self.root/'out'/first['packages'][product]['archive']) as archive:
                self.assertEqual(len(archive.namelist()), len(inventory['files'])+1)
            (folder/'config/personal.json').write_text('{"owner":"local"}')
            verify(folder, product)  # Personal settings are not immutable program.
            target = folder/'program/app/server/protocol.py'
            target.write_bytes(target.read_bytes() + b'\n# changed\n')
            with self.assertRaises(PackageError): verify(folder, product)

    def test_packaged_entry_points_import_outside_checkout_without_site_packages(self):
        self.build()
        foreign = self.root/'foreign-cwd';foreign.mkdir()
        script = ('import importlib,pathlib,sys; root=pathlib.Path(sys.argv[1]).resolve(); '
                  'sys.path.insert(0,str(root)); modules=[importlib.import_module(name) for name in sys.argv[2:]]; '
                  'assert all(pathlib.Path(module.__file__).resolve().is_relative_to(root) for module in modules)')
        for product, modules in (
                ('server', ('tools.package_server','server.host','server.windows_service','server.state_backup',
                            'server.public_matchmaking','server.loadout_protocol','tools.import_assets')),
                ('client', ('tools.package_client','client_patch.transport.client','client_patch.transport.enrollment',
                            'client_patch.patcher.patch_client'))):
            app = self.root/'out'/('battleaces-'+product+'-win64')/'program/app'
            result = subprocess.run([sys.executable,'-I','-S','-B','-c',script,str(app),*modules],
                                    cwd=foreign,capture_output=True,text=True,timeout=30)
            with self.subTest(product=product):self.assertEqual(result.returncode,0,result.stderr[-4000:])

    def test_refuses_dirty_source_existing_outputs_and_unlisted_program_files(self):
        with mock.patch.object(builder, 'source_revision', return_value={'revision': 'test', 'dirty': True}):
            with self.assertRaisesRegex(PackageError, 'Commit'): self.build()
        self.build()
        report = (self.root/'out/build-report.json').read_bytes()
        with self.assertRaisesRegex(PackageError, 'fresh'): self.build()
        self.assertEqual((self.root/'out/build-report.json').read_bytes(), report)
        folder = self.root/'out/battleaces-server-win64'
        (folder/'program/runtime/unlisted.dll').write_bytes(b'authored unwanted file')
        with self.assertRaisesRegex(PackageError, 'unlisted'): verify(folder, 'server')

    def test_asset_output_keeps_checkout_and_bundled_program_clean(self):
        from tools import extract_descriptors as extractor
        bundle = self.root / 'relocated'
        with mock.patch.object(extractor, 'ROOT', bundle / 'program/app'):
            self.assertEqual(extractor.validate_output_directory(bundle / 'assets/build/descriptors'), bundle / 'assets/build/descriptors')
            for path in (bundle / 'program/runtime/assets', bundle / 'program/app/local/assets'):
                with self.assertRaises(extractor.ExtractionError): extractor.validate_output_directory(path)
        with self.assertRaises(extractor.ExtractionError): extractor.validate_output_directory(extractor.ROOT / 'tools/descriptors')


class PackageDispatchTests(unittest.TestCase):
    def test_configure_uses_bundled_python_and_known_system_shell_without_policy_change(self):
        with (mock.patch.object(package_client, 'verify'), mock.patch.object(package_client.subprocess, 'run') as run):
            run.return_value.returncode = 17
            self.assertEqual(package_client.main(['configure', '--config', 'personal config.json']), 17)
            argv = run.call_args.args[0]
            self.assertEqual(Path(argv[0]).name, 'powershell.exe')
            self.assertEqual(argv[1:4], ['-NoProfile', '-STA', '-File'])
            self.assertEqual(Path(argv[4]).name, 'Configure-RCClient.ps1')
            self.assertEqual(argv[5:7], ['-PythonExecutable', package_client.sys.executable])
            self.assertEqual(argv[-2:], ['-ConfigPath', str(Path('personal config.json').resolve())])
            self.assertNotIn('-ExecutionPolicy', argv)
            self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_first_start_opens_setup_and_rc_host_initializes_only_on_start(self):
        with (mock.patch.object(package_client, 'verify'), mock.patch.object(Path, 'exists', return_value=False),
              mock.patch.object(package_client.subprocess, 'run') as run,
              mock.patch('client_patch.transport.client.main') as launch):
            run.return_value.returncode = 0
            self.assertEqual(package_client.main(['start']), 0)
            launch.assert_not_called()
            self.assertEqual(Path(run.call_args.args[0][4]).name, 'Configure-RCClient.ps1')
        with (mock.patch.object(package_server, 'verify'), mock.patch.object(Path, 'exists', return_value=False),
              mock.patch('server.rc_host.initialize') as initialize, mock.patch('server.host.main', return_value=0)):
            self.assertEqual(package_server.main(['check']), 0)
            initialize.assert_not_called()
            self.assertEqual(package_server.main(['start']), 0)
            initialize.assert_called_once_with(package_server.PACKAGE / 'config/host.json', package_server.PACKAGE / 'assets/build-37822')

    def test_install_restore_keep_existing_patcher_transaction_and_no_game_copy(self):
        with mock.patch.object(package_client, 'verify'), mock.patch('client_patch.patcher.patch_client.install', return_value={}) as install, redirect_stdout(io.StringIO()):
            self.assertEqual(package_client.main(['install', '--game', 'working copy', '--dry-run']), 0)
            self.assertIs(install.call_args.kwargs['cosmetics'], True)
            self.assertTrue(install.call_args.kwargs['community'])
            self.assertTrue(install.call_args.kwargs['dry_run'])
            self.assertFalse(install.call_args.kwargs['restore'])
            self.assertEqual(package_client.main(['restore', '--game', 'working copy']), 0)
            self.assertTrue(install.call_args.kwargs['restore'])

    def test_setup_play_uses_the_same_unified_launcher_without_diagnostic_flags(self):
        with mock.patch.object(package_client, 'verify'), mock.patch('client_patch.transport.client.main', return_value=0) as launch:
            self.assertEqual(package_client.main(['launch', '--config', 'personal.json']), 0)
            self.assertEqual(launch.call_args.args[0], ['--config', str(Path('personal.json').resolve())])

    def test_start_client_keeps_game_selection_separate_from_online_enrollment(self):
        with mock.patch.object(package_client, 'verify'), mock.patch('client_patch.transport.client.main', return_value=0) as start:
            self.assertEqual(package_client.main(['start', '--game', 'working copy', '--config', 'local.json']), 0)
            self.assertEqual(start.call_args.args[0], ['--config', str(Path('local.json').resolve()),
                                                     '--game', str(Path('working copy').resolve())])
            self.assertEqual(start.call_args.kwargs['default_game'], package_client.PACKAGE.parent)

    def test_server_check_and_credentials_keep_private_defaults(self):
        with mock.patch.object(package_server, 'verify'), mock.patch('server.host.main', return_value=0) as host:
            self.assertEqual(package_server.main(['check']), 0)
            self.assertEqual(host.call_args.args[0], ['--config', str(package_server.PACKAGE/'config/host.json'), '--check'])
        with mock.patch.object(package_server, 'verify'), mock.patch('server.credentials.main', return_value=0) as credentials:
            self.assertEqual(package_server.main(['credentials', '--store', 'private', 'issue', '--out', 'private/invite.json']), 0)
            self.assertEqual(credentials.call_args.args[0], ['--store', str(Path('private').resolve()), 'issue', '--out', 'private/invite.json'])

    def test_state_commands_forward_only_explicit_paths_to_maintenance(self):
        with mock.patch.object(package_server, 'verify'), mock.patch('server.state_backup.main', return_value=0) as maintenance:
            self.assertEqual(package_server.main(['backup', '--out', 'private snapshot.json']), 0)
            self.assertEqual(maintenance.call_args.args[0], ['backup', '--config', str(package_server.PACKAGE/'config/host.json'),
                '--out', str(Path('private snapshot.json').resolve())])
            self.assertEqual(package_server.main(['restore', '--input', 'snapshot.json', '--destination', 'new data']), 0)
            self.assertEqual(maintenance.call_args.args[0], ['restore', '--config', str(package_server.PACKAGE/'config/host.json'),
                '--input', str(Path('snapshot.json').resolve()), '--destination', str(Path('new data').resolve())])

    def test_service_command_only_generates_reviewable_registration(self):
        with (mock.patch.object(package_server, 'verify'),
              mock.patch('server.windows_service.registration', return_value={'startup':'Manual'}) as registration,
              redirect_stdout(io.StringIO()) as output):
            self.assertEqual(package_server.main(['service-command', '--name', 'FriendsHost', '--config', 'host.json']), 0)
            registration.assert_called_once_with(package_server.PACKAGE, Path('host.json'), 'FriendsHost')
            self.assertEqual(json.loads(output.getvalue()), {'startup':'Manual'})

    def test_bad_cli_arguments_and_integrity_failure_do_not_launch_or_echo_values(self):
        for entry in (package_client.main, package_server.main):
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit): entry(['private-value-must-not-echo'])
            self.assertNotIn('private-value-must-not-echo', output.getvalue())
        with (mock.patch.object(package_client, 'verify', side_effect=PackageError('changed')),
              mock.patch('client_patch.transport.launcher.main') as launch, redirect_stderr(io.StringIO())):
            self.assertEqual(package_client.main(['launch']), 1)
            launch.assert_not_called()


if __name__ == '__main__': unittest.main()
