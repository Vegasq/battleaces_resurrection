"""Reject export probes that borrow shared settings or stale native evidence."""
import json
from pathlib import Path
import shutil
import unittest
import uuid

from client_patch.transport.launcher import LaunchError
from tools.verify_ai_export import export_command, export_log_evidence, read_export_log


class ExportEvidenceTests(unittest.TestCase):
    game = Path('E:/owned game')
    profile = 'nativestest_export_012345abcdef'

    def log(self, **changes):
        settings = dict(profile=self.profile,
                        path=str(self.game/'.battleaces-resurrection/profiles'/self.profile/'gameconfig-localuser.toml'),
                        beforeNativeLoad=True, isolated=True, writerLock=True)
        settings.update(changes)
        return ('[100] NATIVE SETTINGS path selected: '+json.dumps(settings)+' BA_RESURRECTION_NATIVE_SETTINGS_V1\n'
                f'[101] NATIVE STORAGE path selected: kind=backup profile={self.profile} '
                f'path={self.game/".battleaces-resurrection/profiles"/self.profile/"StorageSyncBackup"} isolated=1 rooted=1 BA_RESURRECTION_NATIVE_STORAGE_V1\n'
                '[102] Server asset export: Waiting for main menu and original game assets. Network adapters and Play are disabled in export mode.\n'
                '[103] Server asset export: COMPLETE: three mode maps, unit/bot/cosmetic catalogs, AI rules and export.json written; no match started. You may close the game.\n')

    def test_export_selects_owned_profile_without_match_automation(self):
        args = export_command(self.game, Path('E:/fresh export'), self.profile, Path('E:/game.log'))
        self.assertIn('-local-profile='+self.profile, args)
        self.assertIn('-server-assets-dir='+str(Path('E:/fresh export')), args)
        self.assertIn('-export-server-assets', args)
        self.assertFalse(any(any(word in arg for word in ('smoke', 'auto-', 'capture', 'surrender')) for arg in args))
        for bad in ('default', 'player', self.profile+'x'):
            with self.subTest(profile=bad), self.assertRaises(AssertionError):
                export_command(self.game, Path('E:/out'), bad, Path('E:/log'))

    def test_native_path_limit_applies_before_export_spawn(self):
        with self.assertRaises(LaunchError):
            export_command(Path('E:/'+('x'*180)), Path('E:/out'), self.profile, Path('E:/log'))

    def test_current_complete_isolated_control_markers(self):
        self.assertTrue(export_log_evidence(self.log(), self.game, self.profile)['settings_path_isolated'])

    def test_shared_or_ambiguous_settings_and_missing_completion_fail(self):
        for log in (self.log(profile='default'), self.log(path='C:/shared/gameconfig-localuser.toml'),
                    self.log(writerLock=False), self.log(beforeNativeLoad=False),
                    self.log()+self.log(), self.log().replace('kind=backup', 'kind=replay'),
                    self.log().replace('COMPLETE:', 'INCOMPLETE:'),
                    self.log()+'[104] Practice requested: mode=4\n',
                    self.log()+'[104] Native storage initialization refused: example\n'):
            with self.subTest(log=log), self.assertRaises(AssertionError):
                export_log_evidence(log, self.game, self.profile)

    def test_reused_pid_and_partial_lines_cannot_supply_export_markers(self):
        base = Path(__file__).resolve().parents[1]/'local'
        folder = base/('export-evidence-'+uuid.uuid4().hex)
        try:
            runtime = folder/'investigation/runtime'
            runtime.mkdir(parents=True)
            (runtime/'dedicated-native-12.log').write_text(
                '[99] stale\n'+self.log()+'[104] partial', encoding='utf-8')
            actual = read_export_log(folder, 12, 100)
            self.assertEqual(actual, self.log())
            self.assertEqual(read_export_log(folder, 12, 104), '\n')
            self.assertEqual(read_export_log(folder, 13, 100), '\n')
        finally:
            folder.resolve().relative_to(base.resolve())
            shutil.rmtree(folder)


if __name__ == '__main__':
    unittest.main()
