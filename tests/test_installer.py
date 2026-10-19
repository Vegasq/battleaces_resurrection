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
        self.helper.write_bytes(b'MZ authored helper test fixture BA_RESURRECTION_RECOVERY_V1 OfflineMatchResultContinue\0 BA_RESURRECTION_NATIVE_SETTINGS_V1 OfflineLocalUserConfigPath\0 BA_RESURRECTION_NATIVE_SETTINGS_ERRORS_V1 OfflineLocalUserLoadTable\0 OfflineLocalUserSaveTable\0 BA_RESURRECTION_NATIVE_DECK_INPUT_V1 OfflineLocalDeckStorageLoad\0 BA_RESURRECTION_NATIVE_SETTINGS_ATOMIC_V1 BA_RESURRECTION_NATIVE_BACKUP_GUARD_V1 OfflineBackupInitialRead\0 OfflineBackupWriteText\0 BA_RESURRECTION_NATIVE_STORAGE_V1 OfflineBackupStoragePath\0 OfflineReplayStoragePath\0 OfflineCleanupAutoSaveReplay\0')
        self.helper.write_bytes(self.helper.read_bytes()+b' BA_RESURRECTION_NATIVE_REPLAY_LONG_PATH_V2')
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
        self.assertTrue(manifest['local_storage']['isolated'])
        self.assertEqual(manifest['local_storage']['autosave_call_sites'],4)
        self.assertEqual(manifest['local_storage']['steam_file_sync'],'local-only')
        self.assertEqual(manifest['local_storage']['replay_path_api'],'extended-local-drive')
        for name, content in self.patched.items():
            self.assertEqual((self.root / name).read_bytes(), content)
            self.assertEqual((self.root / '.battleaces-resurrection/original' / name).read_bytes(), self.originals[name])
        self.helper.write_bytes(b'MZ authored helper update BA_RESURRECTION_RECOVERY_V1 OfflineMatchResultContinue\0 BA_RESURRECTION_NATIVE_SETTINGS_V1 OfflineLocalUserConfigPath\0 BA_RESURRECTION_NATIVE_SETTINGS_ERRORS_V1 OfflineLocalUserLoadTable\0 OfflineLocalUserSaveTable\0 BA_RESURRECTION_NATIVE_DECK_INPUT_V1 OfflineLocalDeckStorageLoad\0 BA_RESURRECTION_NATIVE_SETTINGS_ATOMIC_V1 BA_RESURRECTION_NATIVE_BACKUP_GUARD_V1 OfflineBackupInitialRead\0 OfflineBackupWriteText\0 BA_RESURRECTION_NATIVE_STORAGE_V1 OfflineBackupStoragePath\0 OfflineReplayStoragePath\0 OfflineCleanupAutoSaveReplay\0')
        self.helper.write_bytes(self.helper.read_bytes()+b' BA_RESURRECTION_NATIVE_REPLAY_LONG_PATH_V2')
        installer.install(self.root, helper=self.helper)
        self.assertEqual((self.root / 'BattleAcesOffline.dll').read_bytes(), self.helper.read_bytes())
        restored = installer.install(self.root, restore=True)
        self.assertEqual(restored['state'], 'restored')
        self.assertFalse(restored['local_storage']['isolated'])
        self.assertFalse(restored['local_storage']['autosave_exception_boundary'])
        self.assertEqual(restored['local_storage']['autosave_call_sites'],0)
        self.assertEqual(restored['local_storage']['steam_file_sync'],'original-restored')
        self.assertIsNone(restored['local_storage']['replay_path_api'])
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

    def test_helper_without_new_recovery_abi_rejected_before_component_writes(self):
        self.helper.write_bytes(b'MZ older authored helper fixture')
        with self.assertRaisesRegex(ValueError, 'recovery ABI1'):
            installer.install(self.root, helper=self.helper)
        for name, original in self.originals.items():
            self.assertEqual((self.root / name).read_bytes(), original)
        self.assertFalse((self.root / '.battleaces-resurrection').exists())

    def test_helper_without_result_continue_export_rejected_before_writes(self):
        self.helper.write_bytes(b'MZ authored older helper BA_RESURRECTION_RECOVERY_V1')
        with self.assertRaisesRegex(ValueError, 'public result Continue hook'):
            installer.install(self.root, helper=self.helper)
        for name, original in self.originals.items():
            self.assertEqual((self.root / name).read_bytes(), original)
        self.assertFalse((self.root / '.battleaces-resurrection').exists())

    def test_helper_without_early_settings_isolation_is_rejected_before_writes(self):
        self.helper.write_bytes(b'MZ authored old helper BA_RESURRECTION_RECOVERY_V1 OfflineMatchResultContinue\0')
        with self.assertRaisesRegex(ValueError, 'native local-user settings isolation'):
            installer.install(self.root, helper=self.helper)
        for name, original in self.originals.items():
            self.assertEqual((self.root / name).read_bytes(), original)
        self.assertFalse((self.root / '.battleaces-resurrection').exists())

    def test_helper_without_native_settings_result_hooks_is_rejected_before_writes(self):
        self.helper.write_bytes(b'MZ authored old helper BA_RESURRECTION_RECOVERY_V1 OfflineMatchResultContinue\0 BA_RESURRECTION_NATIVE_SETTINGS_V1 OfflineLocalUserConfigPath\0')
        with self.assertRaisesRegex(ValueError, 'native local-user settings error hooks'):
            installer.install(self.root, helper=self.helper)
        for name, original in self.originals.items():
            self.assertEqual((self.root / name).read_bytes(), original)
        self.assertFalse((self.root / '.battleaces-resurrection').exists())

    def test_optional_quit_recipe_requires_diagnostic_helper_before_writes(self):
        with self.assertRaisesRegex(ValueError, 'owned native Quit diagnostic helper'):
            installer.install(self.root, helper=self.helper, quit_diagnostics=True)
        for name, original in self.originals.items():
            self.assertEqual((self.root / name).read_bytes(), original)
        self.assertFalse((self.root / '.battleaces-resurrection').exists())

    def test_startup_recipe_requires_marker_and_all_exports_before_writes(self):
        from client_patch.patcher import startup_tasks
        original_helper = self.helper.read_bytes()
        required = [b'BA_RESURRECTION_STARTUP_TASKS_V1'] + [
            h['name'].encode()+b'\0' for h in startup_tasks.CALL_HOOKS+startup_tasks.TAIL_HOOKS]
        for missing in required:
            with self.subTest(missing=missing):
                self.helper.write_bytes(original_helper+b' '.join(item for item in required if item != missing))
                with self.assertRaisesRegex(ValueError, 'owned startup task diagnostic helper'):
                    installer.install(self.root, helper=self.helper, startup_diagnostics=True)
                for name, original in self.originals.items():
                    self.assertEqual((self.root / name).read_bytes(), original)
                self.assertFalse((self.root / '.battleaces-resurrection').exists())
        self.helper.write_bytes(original_helper+b' '.join(required))
        manifest = installer.install(self.root, helper=self.helper, startup_diagnostics=True)
        self.assertTrue(manifest['diagnostics']['startup_tasks'])
        self.assertTrue(all(h in manifest['call_hooks'] for h in startup_tasks.CALL_HOOKS))
        self.assertTrue(all(h in manifest['tail_hooks'] for h in startup_tasks.TAIL_HOOKS))
        ordinary = installer.install(self.root, helper=self.helper)
        self.assertFalse(ordinary['diagnostics']['startup_tasks'])
        self.assertFalse(any(h['name'].startswith('OfflineStartupTable') for h in ordinary['call_hooks']))
        self.assertFalse(any(h['name'] == 'OfflineStartupPump' for h in ordinary['tail_hooks']))

    def test_helper_without_persisted_deck_guard_is_rejected_before_writes(self):
        self.helper.write_bytes(self.helper.read_bytes().replace(b'BA_RESURRECTION_NATIVE_DECK_INPUT_V1',b'authored_previous_helper'))
        with self.assertRaisesRegex(ValueError,'native persisted deck validation'):
            installer.install(self.root,helper=self.helper)
        for name,original in self.originals.items():
            self.assertEqual((self.root/name).read_bytes(),original)
        self.assertFalse((self.root/'.battleaces-resurrection').exists())

    def test_helper_without_native_write_publication_is_rejected_before_writes(self):
        self.helper.write_bytes(self.helper.read_bytes().replace(b'BA_RESURRECTION_NATIVE_SETTINGS_ATOMIC_V1',b'authored_previous_helper'))
        with self.assertRaisesRegex(ValueError,'native settings write publication'):
            installer.install(self.root,helper=self.helper)
        for name,original in self.originals.items():
            self.assertEqual((self.root/name).read_bytes(),original)
        self.assertFalse((self.root/'.battleaces-resurrection').exists())

    def test_missing_native_storage_capabilities_refused_before_writes(self):
        original_helper = self.helper.read_bytes()
        for marker in (b'BA_RESURRECTION_NATIVE_STORAGE_V1', b'OfflineBackupStoragePath\0',
                       b'OfflineReplayStoragePath\0', b'OfflineCleanupAutoSaveReplay\0'):
            with self.subTest(marker=marker):
                self.helper.write_bytes(original_helper.replace(marker,b'authored_previous_helper'))
                with self.assertRaisesRegex(ValueError,'native replay and backup storage isolation'):
                    installer.install(self.root,helper=self.helper)
                for name,original in self.originals.items():
                    self.assertEqual((self.root/name).read_bytes(),original)
                self.assertFalse((self.root/'.battleaces-resurrection').exists())

    def test_diagnostic_only_replay_helper_refused_before_writes(self):
        self.helper.write_bytes(self.helper.read_bytes().replace(b'BA_RESURRECTION_NATIVE_REPLAY_LONG_PATH_V2',
                                                               b'BA_RESURRECTION_NATIVE_REPLAY_LONG_PATH_V1'))
        with self.assertRaisesRegex(ValueError,'ordinary extended replay paths'):
            installer.install(self.root,helper=self.helper)
        for name,original in self.originals.items():self.assertEqual((self.root/name).read_bytes(),original)
        self.assertFalse((self.root/'.battleaces-resurrection').exists())

    def test_quit_recipe_is_opt_in_and_records_exact_disposal_call(self):
        default = installer.install(self.root, helper=self.helper, dry_run=True)
        self.assertFalse(default['diagnostics']['native_quit'])
        self.assertNotIn('OfflineNativeQuitDispose', {h['name'] for h in default['call_hooks']})
        self.assertEqual(default['pointer_hooks'], [])
        self.helper.write_bytes(self.helper.read_bytes()+b' BA_RESURRECTION_NATIVE_QUIT_TRACE_V1 OfflineNativeQuitDispose\0 OfflineNativeQuitAIDispose\0 OfflineNativeQuitOnDestroy\0')
        diagnostic = installer.install(self.root, helper=self.helper, quit_diagnostics=True, dry_run=True)
        self.assertTrue(diagnostic['diagnostics']['native_quit'])
        self.assertEqual([h for h in diagnostic['call_hooks'] if h['name'].startswith('OfflineNativeQuit')], installer.QUIT_CALL_HOOKS)
        self.assertEqual(diagnostic['pointer_hooks'],installer.QUIT_POINTER_HOOKS)

    def test_missing_backup_admission_or_publication_refused_before_writes(self):
        original_helper=self.helper.read_bytes()
        for marker in (b'BA_RESURRECTION_NATIVE_BACKUP_GUARD_V1',b'OfflineBackupInitialRead\0',b'OfflineBackupWriteText\0'):
            with self.subTest(marker=marker):
                self.helper.write_bytes(original_helper.replace(marker,b'authored_previous_helper'))
                with self.assertRaisesRegex(ValueError,'native backup input and publication protection'):
                    installer.install(self.root,helper=self.helper)
                for name,original in self.originals.items():
                    self.assertEqual((self.root/name).read_bytes(),original)
                self.assertFalse((self.root/'.battleaces-resurrection').exists())

    def test_backup_protection_manifest_and_restore(self):
        installed=installer.install(self.root,helper=self.helper)
        self.assertTrue(installed['local_storage']['backup_input_guard'])
        self.assertEqual(installed['local_storage']['backup_publication'],'original-json-text-flush-handle-rename')
        restored=installer.install(self.root,restore=True)
        self.assertFalse(restored['local_storage']['backup_input_guard'])
        self.assertIsNone(restored['local_storage']['backup_publication'])

    def test_default_blocks_dlss_vendor_init_and_original_comparison_is_explicit(self):
        default = installer.install(self.root, helper=self.helper, dry_run=True)
        self.assertFalse(default['diagnostics']['dlss_enabled'])
        self.assertEqual(default['graphics']['dlss_setup'],'unavailable-before-native-init')
        self.assertTrue(default['graphics']['original_shutdown'])
        self.assertEqual([p for p in default['patches'] if p['offset']==0x4b281e0],installer.DLSS_PRIVACY_PATCHES)
        control = installer.install(self.root, helper=self.helper, allow_dlss_diagnostics=True, dry_run=True)
        self.assertTrue(control['diagnostics']['dlss_enabled'])
        self.assertEqual(control['graphics']['dlss_setup'],'original-owned-diagnostic')
        self.assertFalse(any(p['offset']==0x4b281e0 for p in control['patches']))

    def test_experimental_community_requires_matching_helper_before_writes(self):
        with self.assertRaisesRegex(ValueError, 'community ABI1'):
            installer.install(self.root, helper=self.helper, community=True)
        for name, original in self.originals.items():
            self.assertEqual((self.root / name).read_bytes(), original)
        self.assertFalse((self.root / '.battleaces-resurrection').exists())
        self.helper.write_bytes(self.helper.read_bytes() + b' BA_RESURRECTION_COMMUNITY_V1')
        with self.assertRaisesRegex(ValueError, 'community roster ABI1'):
            installer.install(self.root, helper=self.helper, community=True)
        self.assertFalse((self.root / '.battleaces-resurrection').exists())
        self.helper.write_bytes(self.helper.read_bytes() + b' BA_RESURRECTION_COMMUNITY_ROSTER_V1')
        with self.assertRaisesRegex(ValueError, 'community invitation ABI1'):
            installer.install(self.root, helper=self.helper, community=True)
        self.assertFalse((self.root / '.battleaces-resurrection').exists())
        self.helper.write_bytes(self.helper.read_bytes() + b' BA_RESURRECTION_COMMUNITY_INVITES_V1')
        with self.assertRaisesRegex(ValueError, 'community match ABI1'):
            installer.install(self.root, helper=self.helper, community=True)
        self.assertFalse((self.root / '.battleaces-resurrection').exists())
        self.helper.write_bytes(self.helper.read_bytes() + b' BA_RESURRECTION_COMMUNITY_MATCH_V1')
        manifest = installer.install(self.root, helper=self.helper, community=True)
        self.assertTrue(manifest['community']['experimental'])
        self.assertTrue(any(h['name'] == 'OfflineCommunityEnqueue' for h in manifest['call_hooks']))
        self.assertTrue(any(h['name'] == 'OfflineCommunityJoinGame' for h in manifest['call_hooks']))
        self.assertTrue(any(h['name'] == 'OfflineCommunityRosterRelease' for h in manifest['tail_hooks']))
        normal = installer.install(self.root, helper=self.helper)
        self.assertFalse(normal['community']['experimental'])
        self.assertFalse(any(h['name'] == 'OfflineCommunityEnqueue' for h in normal['call_hooks']))
        self.assertFalse(any(h['name'] == 'OfflineCommunityJoinGame' for h in normal['call_hooks']))
        self.assertFalse(any(h['name'] == 'OfflineCommunityRosterRelease' for h in normal['tail_hooks']))

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
