"""Prepare one isolated, visible current-build Tutorial01 completion check."""

import hashlib
import json
import secrets
from pathlib import Path

from client_patch.transport.launcher import verify_game
from tools.helper_provenance import validate as validate_helper


ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / 'local/privacy301-runtime01/game'
HELPER = ROOT / 'local/privacy357-helper-build01/BattleAcesOffline.dll'
OUTPUT = ROOT / 'local/privacy437-tutorial-manual01'


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if OUTPUT.exists():
        raise FileExistsError('Manual capsule already exists; preserve its evidence')
    verify_game(GAME, community=True, bridge_version=2, unified=True)
    helper_binding = validate_helper(HELPER, (GAME / 'BattleAcesOffline.dll').read_bytes(), ROOT)
    manifest_path = GAME / '.battleaces-resurrection/patch-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['telemetry']['recipe_version'] == 38
    assert manifest['telemetry']['runtime_validated'] is False
    assert manifest['diagnostics']['native_quit'] is False
    profile = 'manual_tutorial437_' + secrets.token_hex(6)
    assert not (GAME / '.battleaces-resurrection/profiles' / profile).exists()
    OUTPUT.mkdir()
    game_log = OUTPUT / 'game.log'
    exit_file = OUTPUT / 'exit-code.txt'
    command = (
        '@echo off\r\n'
        'setlocal\r\n'
        f'if exist "{game_log}" goto used\r\n'
        f'if exist "{exit_file}" goto used\r\n'
        f'cd /d "{GAME}"\r\n'
        f'"{GAME / "Battle Aces.exe"}" -offline-tutorial -local-profile={profile} '
        '-player-name="Manual Tutorial01 D5" -telemetry-audit '
        f'-screen-fullscreen 0 -screen-width 1280 -screen-height 720 -logFile "{game_log}"\r\n'
        f'echo %errorlevel%>"{exit_file}"\r\n'
        'echo Game exit code was recorded in exit-code.txt.\r\n'
        'pause\r\n'
        'exit /b\r\n'
        ':used\r\n'
        'echo This single-use capsule already has a report. Preserve it and do not rerun.\r\n'
        'pause\r\n'
    )
    launcher = OUTPUT / 'Start Tutorial01.cmd'
    launcher.write_bytes(command.encode('utf-8'))
    readme = (
        'BATTLE ACES - D5 TUTORIAL01 MANUAL CHECK\n\n'
        'This uses the isolated current recipe38 game copy and a fresh profile.\n'
        'No installer, server, administrator access or original account is needed.\n'
        'The game window is visible. This capsule is single-use; leave any\n'
        'failure and its logs in place.\n\n'
        '1. Double-click Start Tutorial01.cmd once. Leave the console open.\n'
        '2. Play the original Tutorial01. The first observed task is to build\n'
        '   one expansion after selecting the HQ; the authored hotkey is Z.\n'
        '   Follow the visible game prompts for placement and later tasks.\n'
        '3. If you finish, use the game\'s own Quit to Desktop control.\n'
        '   If you cannot finish, note the last visible objective and use\n'
        '   the in-game Quit to Desktop control where possible.\n'
        '4. Record what happened, the printed exit code and whether Quit worked.\n'
        '   Keep game.log and exit-code.txt here. Do not rerun this capsule.\n\n'
        'No password, telemetry payload or file upload is requested.\n'
    )
    (OUTPUT / 'READ ME FIRST.txt').write_text(readme, encoding='utf-8')
    plan = {
        'schema': 1,
        'output': str(OUTPUT),
        'game': str(GAME),
        'profile': profile,
        'launcher': str(launcher),
        'game_sha256': sha256(GAME / 'GameAssembly.dll'),
        'unity_sha256': sha256(GAME / 'UnityPlayer.dll'),
        'helper_sha256': sha256(GAME / 'BattleAcesOffline.dll'),
        'manifest_sha256': sha256(manifest_path),
        'helper_binding': helper_binding,
        'launched': False,
    }
    (OUTPUT / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'prepared': True, 'output': str(OUTPUT), 'profile': profile}))


if __name__ == '__main__':
    main()
