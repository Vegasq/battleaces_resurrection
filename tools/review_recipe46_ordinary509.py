"""Review recipe46 installed fresh/restart launcher and SDK-root watch."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from client_patch.patcher.patch_client import build_patch
from client_patch.patcher.telemetry import RECIPE_VERSION, RUNTIME_VALIDATED
from tools.frida_ads_caller import describe_unity
from tools.game_installer import launcher_bytes, replay_launcher_bytes
from tools.package_integrity import verify
from tools.review_webview_fulltext396 import ORIGINAL, ORIGINAL_SHA

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/privacy509-ordinary01'
GAME = ROOT / 'local/privacy509-game01'
PAIR = ROOT / 'local/privacy506-packages01'
PACKAGE = PAIR / 'battleaces-client-win64'
SDK_SOURCE = ROOT / 'local/privacy269-startup01/verification.json'


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def review() -> dict:
    assert RECIPE_VERSION == 46 and RUNTIME_VALIDATED is False
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    build = read(PAIR / 'build-report.json')
    archive = PAIR / build['packages']['client']['archive']
    assert sha(archive) == build['packages']['client']['sha256']
    inventory = verify(PACKAGE, 'client')
    identity = sha(PACKAGE / 'package-manifest.json')[:20]
    relative = '.battleaces-resurrection/client-runtime/' + identity
    runtime = GAME / relative
    assert verify(runtime, 'client') == inventory
    assert (GAME / 'Start Battle Aces.cmd').read_bytes() == launcher_bytes(relative)
    assert (GAME / 'Watch Replay.cmd').read_bytes() == replay_launcher_bytes()
    config = read(GAME / '.battleaces-resurrection/client-config.json')
    assert config['schema'] == 4 and Path(config['game_directory']).resolve() == GAME.resolve()
    assert config['server_host'] == '127.0.0.1'
    patch = read(GAME / '.battleaces-resurrection/patch-manifest.json')
    assert patch['telemetry']['recipe_version'] == 46
    assert patch['telemetry']['runtime_validated'] is False
    assert patch['components']['GameAssembly.dll']['telemetry_guards'] == 108
    expected_game = build_patch(original, community=True, cosmetics=True)
    assert (GAME / 'GameAssembly.dll').read_bytes() == expected_game
    helper_hash = sha(GAME / 'BattleAcesOffline.dll')
    assert helper_hash == patch['helper_sha256'] == sha(runtime / 'program/client-helper/BattleAcesOffline.dll')
    unity = describe_unity((GAME / '.battleaces-resurrection/original/UnityPlayer.dll').read_bytes(),
                           (GAME / 'UnityPlayer.dll').read_bytes())
    assert unity['recipe'] == 46

    report = read(OUT / 'verification.json')
    assert report['passed'] and not report.get('error') and not report.get('watch_error')
    assert report['watcher_source_sha256'] == sha(ROOT / 'tools/watch_sdk_cache_events.ps1')
    assert report['verifier_source_sha256'] == sha(ROOT / 'tools/verify_packaged_startup.py')
    assert report['source_witness_sha256'] == sha(SDK_SOURCE)
    assert report['sdk_root'] == read(SDK_SOURCE)['sdk_cache_root']
    assert report['installed_runtime'] == str(runtime)
    watch = report['watch_result']
    assert watch['root'] == report['sdk_root'] and watch['stopped_by_sentinel']
    assert watch['counts'] == dict(Created=0, Changed=0, Deleted=0, Renamed=0, Error=0)
    assert watch['started_utc'] <= report['fresh']['started_utc']
    assert report['fresh']['finished_utc'] <= report['existing']['started_utc']
    assert report['existing']['finished_utc'] <= watch['finished_utc']
    profiles = []
    for name in ('fresh', 'existing'):
        item = report[name]
        session = read(OUT / name / 'verification.json')
        assert item['verification_sha256'] == sha(OUT / name / 'verification.json')
        assert item['exit_code'] == 0 and session['passed']
        assert session['installed_launcher'] and session['window_close_requested']
        assert session['window_close_exit_zero'] and session['forced_cleanup'] is False
        assert session['wrapper_reaped'] and session['game_reaped']
        assert session['source_files_unchanged'] and session['package_files_unchanged']
        assert session['config_unchanged'] and session['shared_settings_unchanged']
        assert session['game'] == str(GAME) and session['package'] == str(runtime)
        assert session['profile'] == item['profile']
        assert session['menu_ready_seconds'] == item['menu_ready_seconds']
        assert session['idle_seconds_observed'] == item['idle_seconds'] >= 30
        assert 'Start Battle Aces.cmd' in session['command']
        profiles.append(session['profile'])
    assert profiles[0] == profiles[1]
    return dict(passed=True, recipe=46, profile=profiles[0], runtime_identity=identity,
                watcher_counts=watch['counts'], archive_sha256=sha(archive),
                helper_sha256=helper_hash, unity_sha256=unity['fileSha256'],
                installed_gameassembly_sha256=sha(GAME / 'GameAssembly.dll'),
                orchestration_sha256=sha(OUT / 'verification.json'),
                fresh_sha256=sha(OUT / 'fresh/verification.json'),
                existing_sha256=sha(OUT / 'existing/verification.json'),
                full_d5_qualified=False)


if __name__ == '__main__':
    print(json.dumps(review(), indent=2))
