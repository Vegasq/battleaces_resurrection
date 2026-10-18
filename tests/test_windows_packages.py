"""Synthetic archives test distribution boundaries without downloading runtimes."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import struct
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
        return builder.build(self.runtime, self.helper, self.root / name)

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
            self.assertEqual(argv[5:7], ['-PythonExecutable', package_client.sys.executable])
            self.assertEqual(argv[-2:], ['-ConfigPath', str(Path('personal config.json').resolve())])
            self.assertNotIn('-ExecutionPolicy', argv)
            self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_install_restore_keep_existing_patcher_transaction_and_no_game_copy(self):
        with mock.patch.object(package_client, 'verify'), mock.patch('client_patch.patcher.patch_client.install', return_value={}) as install, redirect_stdout(io.StringIO()):
            self.assertEqual(package_client.main(['install', '--game', 'working copy', '--dry-run']), 0)
            self.assertTrue(install.call_args.kwargs['community'])
            self.assertTrue(install.call_args.kwargs['dry_run'])
            self.assertFalse(install.call_args.kwargs['restore'])
            self.assertEqual(package_client.main(['restore', '--game', 'working copy']), 0)
            self.assertTrue(install.call_args.kwargs['restore'])

    def test_secure_launch_receives_config_path_and_no_diagnostic_flags(self):
        with mock.patch.object(package_client, 'verify'), mock.patch('client_patch.transport.launcher.main', return_value=0) as launch:
            self.assertEqual(package_client.main(['launch', '--config', 'personal.json']), 0)
            self.assertEqual(launch.call_args.args[0], ['--config', str(Path('personal.json').resolve()), '--community-experimental'])

    def test_server_check_and_credentials_keep_private_defaults(self):
        with mock.patch.object(package_server, 'verify'), mock.patch('server.host.main', return_value=0) as host:
            self.assertEqual(package_server.main(['check']), 0)
            self.assertEqual(host.call_args.args[0], ['--config', str(package_server.PACKAGE/'config/host.json'), '--check'])
        with mock.patch.object(package_server, 'verify'), mock.patch('server.credentials.main', return_value=0) as credentials:
            self.assertEqual(package_server.main(['credentials', '--store', 'private', 'issue', '--out', 'private/invite.json']), 0)
            self.assertEqual(credentials.call_args.args[0], ['--store', str(Path('private').resolve()), 'issue', '--out', 'private/invite.json'])

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
