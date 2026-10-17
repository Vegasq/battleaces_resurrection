"""Installer transaction tests with authored bytes; no shipped game data."""
from contextlib import ExitStack
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

from client_patch.patcher import patch_client as installer
from client_patch.patcher.telemetry import Component


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.test_root = Path(__file__).resolve().parents[1] / 'local/installer-tests'
        self.root = self.test_root / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.addCleanup(self.remove_fixture)
        self.nested = 'Battle Aces_Data/Plugins/x86_64/VuplexWebViewChromium/chrome_elf.dll'
        self.originals = {'GameAssembly.dll': b'authored game fixture',
                          'UnityPlayer.dll': b'authored engine fixture',
                          self.nested: b'authored browser fixture'}
        self.patched = {name: content + b' private patch' for name, content in self.originals.items()}
        for name, content in self.originals.items():
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_bytes(content)
        self.helper = self.root / 'synthetic-helper.dll'
        self.helper.write_bytes(b'MZ authored helper test fixture')
        self.stack.enter_context(patch.object(installer, 'ORIGINAL_SHA256', installer.digest(self.originals['GameAssembly.dll'])))
        self.stack.enter_context(patch.object(installer.telemetry, 'COMPONENTS', {
            name: Component(installer.digest(content), ()) for name, content in self.originals.items()}))
        self.stack.enter_context(patch.object(installer, 'build_patch', side_effect=lambda data, **kwargs: self.patched['GameAssembly.dll']))
        self.stack.enter_context(patch.object(installer.telemetry, 'patch_component', side_effect=lambda name, data: self.patched[name]))
        self.stack.enter_context(patch.object(installer, 'update_checksum', side_effect=lambda data: data))

    def remove_fixture(self):
        target = self.root.resolve()
        self.assertEqual(target.parent, self.test_root.resolve())
        self.assertEqual(len(target.name), 32)
        shutil.rmtree(target)

    def test_install_update_and_restore_all_components_from_verified_backups(self):
        manifest = installer.install(self.root, helper=self.helper)
        self.assertEqual(manifest['schema'], 2)
        for name, content in self.patched.items():
            self.assertEqual((self.root / name).read_bytes(), content)
            self.assertEqual((self.root / '.battleaces-resurrection/original' / name).read_bytes(), self.originals[name])
        self.helper.write_bytes(b'MZ authored helper update')
        installer.install(self.root, helper=self.helper)
        self.assertEqual((self.root / 'BattleAcesOffline.dll').read_bytes(), self.helper.read_bytes())
        restored = installer.install(self.root, restore=True)
        self.assertEqual(restored['state'], 'restored')
        for name, content in self.originals.items():
            self.assertEqual((self.root / name).read_bytes(), content)
            self.assertEqual(restored['components'][name]['installed_sha256'], installer.digest(content))

    def test_last_component_validation_failure_leaves_installation_untouched(self):
        (self.root / self.nested).write_bytes(b'unrecognized browser')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            installer.install(self.root, helper=self.helper)
        self.assertEqual((self.root / 'GameAssembly.dll').read_bytes(), self.originals['GameAssembly.dll'])
        self.assertFalse((self.root / '.battleaces-resurrection').exists())
        self.assertFalse((self.root / 'BattleAcesOffline.dll').exists())

    def test_file_replacement_failure_rolls_back_earlier_components_and_helper(self):
        old_helper = b'MZ previous authored helper'
        (self.root / 'BattleAcesOffline.dll').write_bytes(old_helper)
        write = installer.atomic_write
        def fail_engine(path, data):
            if path == self.root / self.nested:
                raise PermissionError('test: browser is mapped by a running process')
            return write(path, data)
        with patch.object(installer, 'atomic_write', side_effect=fail_engine):
            with self.assertRaises(PermissionError):
                installer.install(self.root, helper=self.helper)
        for name, content in self.originals.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        self.assertEqual((self.root / 'BattleAcesOffline.dll').read_bytes(), old_helper)
        self.assertFalse((self.root / '.battleaces-resurrection/patch-manifest.json').exists())

    def test_modified_target_or_corrupt_backup_cannot_be_overwritten(self):
        installer.install(self.root, helper=self.helper)
        (self.root / 'UnityPlayer.dll').write_bytes(b'other modification')
        with self.assertRaisesRegex(ValueError, 'unexpected DLL changes'):
            installer.install(self.root, restore=True)
        (self.root / 'UnityPlayer.dll').write_bytes(self.patched['UnityPlayer.dll'])
        (self.root / '.battleaces-resurrection/original/UnityPlayer.dll').write_bytes(b'corrupt backup')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            installer.install(self.root, restore=True)
        self.assertEqual((self.root / 'GameAssembly.dll').read_bytes(), self.patched['GameAssembly.dll'])

    def test_dry_run_does_not_create_backups_or_modify_any_component(self):
        installer.install(self.root, helper=self.helper, dry_run=True)
        self.assertFalse((self.root / '.battleaces-resurrection').exists())
        self.assertFalse((self.root / 'BattleAcesOffline.dll').exists())
        for name, content in self.originals.items():
            self.assertEqual((self.root / name).read_bytes(), content)

    def test_component_path_cannot_escape_or_target_backup_state(self):
        component = Component(installer.digest(b'authored path fixture'), ())
        for name in ('../escape.dll', str(self.root.parent / 'escape.dll'),
                     '.battleaces-resurrection/original/escape.dll'):
            with self.subTest(name=name), patch.object(installer.telemetry, 'COMPONENTS', {name: component}):
                with self.assertRaises(ValueError):
                    installer.install(self.root, helper=self.helper)
            self.assertFalse((self.root / '.battleaces-resurrection').exists())
            self.assertFalse((self.root / 'BattleAcesOffline.dll').exists())

    def test_resolved_external_target_or_backup_is_rejected_before_writes(self):
        original_resolve = Path.resolve
        # Exercise path resolution's result; this does not claim a real Windows
        # junction was created in the test environment.
        for relative in ('UnityPlayer.dll', '.battleaces-resurrection',
                         '.battleaces-resurrection/original/UnityPlayer.dll'):
            def external(path, *args, **kwargs):
                if path == self.root / relative:
                    return self.root.parent / 'outside-fixture' / path.name
                return original_resolve(path, *args, **kwargs)
            with self.subTest(relative=relative), patch.object(Path, 'resolve', external):
                with self.assertRaisesRegex(ValueError, 'outside'):
                    installer.install(self.root, helper=self.helper)
            self.assertFalse((self.root / '.battleaces-resurrection').exists())
            self.assertFalse((self.root / 'BattleAcesOffline.dll').exists())
