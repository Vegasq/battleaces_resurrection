"""Exercise the real PowerShell launcher with an authored, non-executable game fixture."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which('powershell') or shutil.which('pwsh')


@unittest.skipUnless(os.name == 'nt' and POWERSHELL, 'Windows PowerShell required')
class OfflinePracticeLauncherTests(unittest.TestCase):
    def setUp(self):
        self.folder = ROOT / 'local' / ('offline-launcher-' + uuid.uuid4().hex)
        self.game = self.folder / 'game'
        state = self.game / '.battleaces-resurrection'
        state.mkdir(parents=True)
        component, helper = b'authored component fixture', b'authored helper fixture'
        (self.game / 'GameAssembly.dll').write_bytes(component)
        (self.game / 'BattleAcesOffline.dll').write_bytes(helper)
        (self.game / 'Battle Aces.exe').write_bytes(b'non-executable authored fixture')
        self.manifest = dict(state='dedicated-prototype-v2', practice={'standalone': True},
            patched_sha256=hashlib.sha256(component).hexdigest(), helper_sha256=hashlib.sha256(helper).hexdigest(),
            call_hooks=[{'name': 'OfflinePracticeAIJoin'}])
        self.manifest_path = state / 'patch-manifest.json'
        self.manifest_path.write_text(json.dumps(self.manifest))
        self.config = self.folder / 'offline.json'
        self.config.write_text(json.dumps(dict(schema=1, game_directory=str(self.game), display_name='Local Tester')))
        self.script = self.folder / 'launch.ps1'
        self.script.write_text('''param([string]$Launcher,[string]$Config)
$ErrorActionPreference='Stop'
$global:practiceLaunches=@()
function Start-Process {
    param($FilePath,$ArgumentList,$WorkingDirectory,$WindowStyle,[switch]$PassThru)
    $global:practiceLaunches += [pscustomobject]@{FilePath=$FilePath;Arguments=$ArgumentList;WindowStyle=$WindowStyle}
    return [pscustomobject]@{Id=123;HasExited=$true}
}
& $Launcher -Config $Config -OfflinePractice -PassThru | Out-Null
ConvertTo-Json -InputObject @($global:practiceLaunches) -Depth 4 -Compress
''')

    def tearDown(self):
        target = self.folder.resolve()
        target.relative_to((ROOT / 'local').resolve())
        shutil.rmtree(target)

    def launch(self):
        return subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(self.script), '-Launcher', str(ROOT / 'client_patch/launcher/Launch-Client.ps1'),
            '-Config', str(self.config)], capture_output=True, text=True, timeout=20)

    def test_no_server_settings_launch_one_visible_game_with_normal_ai(self):
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        launches = json.loads(result.stdout)
        self.assertEqual(len(launches), 1)
        self.assertEqual(Path(launches[0]['FilePath']), self.game / 'Battle Aces.exe')
        self.assertEqual(launches[0]['WindowStyle'], 'Normal')
        args = launches[0]['Arguments']
        self.assertIn('-offline-practice', args)
        self.assertIn('-practice-ai-profile=18', args)
        self.assertFalse(any(a.startswith(('-dedicated', '-offline-lan', '-secure-transport', '-room=',
            '-lan-smoke', '-practice-ai-smoke', '-lan-audit')) for a in args))

    def test_old_helper_is_rejected_before_launch(self):
        self.manifest['practice']['standalone'] = False
        self.manifest_path.write_text(json.dumps(self.manifest))
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('standalone offline practice support', result.stderr)


if __name__ == '__main__':
    unittest.main()
