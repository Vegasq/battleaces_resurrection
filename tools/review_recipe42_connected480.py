"""Independently bind the private recipe42 pair to its connected match."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from client_patch.patcher.patch_client import build_patch
from client_patch.patcher.telemetry import RECIPE_VERSION, RUNTIME_VALIDATED
from tools.package_integrity import verify
from tools.review_sdk_empty_installed479 import review as review_installed
from tools.review_webview_fulltext396 import ORIGINAL, ORIGINAL_SHA

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / 'local/privacy479-game01'
PACKAGES = ROOT / 'local/privacy480-packages01'
RUN = ROOT / 'local/privacy480-connected01'
HELPER = ROOT / 'local/privacy461-helper-build01/BattleAcesOffline.dll'
TELEMETRY_SOURCE = ROOT / 'client_patch/patcher/telemetry.py'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def review() -> dict:
    assert review_installed()['passed'] is True
    assert RECIPE_VERSION == 42 and RUNTIME_VALIDATED is False
    report = load(RUN / 'verification.json')
    build = load(PACKAGES / 'build-report.json')
    manifest = load(GAME / '.battleaces-resurrection/patch-manifest.json')
    assert sha(ORIGINAL) == ORIGINAL_SHA
    original = ORIGINAL.read_bytes()
    assert sha(GAME / '.battleaces-resurrection/original/GameAssembly.dll') == ORIGINAL_SHA
    expected_assembly = build_patch(original, community=True, cosmetics=True)
    assert hashlib.sha256(expected_assembly).hexdigest() == sha(GAME / 'GameAssembly.dll')
    assert expected_assembly == (GAME / 'GameAssembly.dll').read_bytes()
    assert manifest['telemetry']['recipe_version'] == 42
    assert manifest['telemetry']['runtime_validated'] is False
    assert manifest['components']['GameAssembly.dll']['telemetry_guards'] == 104
    assert manifest['components']['GameAssembly.dll']['installed_sha256'] == sha(GAME / 'GameAssembly.dll')
    assert sha(GAME / 'BattleAcesOffline.dll') == sha(HELPER) == manifest['helper_sha256']
    assert build['source']['dirty'] is True and build['versions']['game_build'] == 37822
    archives = {}
    for kind in ('client', 'server'):
        package = PACKAGES / f'battleaces-{kind}-win64'
        verify(package, kind)
        info = build['packages'][kind]
        archive = PACKAGES / info['archive']
        assert sha(archive) == info['sha256']
        assert sha(package / 'program/client-helper/BattleAcesOffline.dll') == sha(HELPER)
        assert sha(package / 'program/app/client_patch/patcher/telemetry.py') == sha(TELEMETRY_SOURCE)
        archives[kind] = info['sha256']
    assert report['passed'] is True and report['forced_cleanup'] is False
    assert report['packages'] == str(PACKAGES.resolve())
    assert report['rc_open'] is True and report['mode'] == 1 and report['humans'] == 2
    assert report['match']['frames'] >= 1200 and report['match']['result']['complete'] is True
    assert len(report['clients']) == 2
    for client in report['clients']:
        assert client['driver_report']['passed'] is True
        assert client['driver_report']['game_exit_code'] == 0
        assert [event['event'] for event in client['trace']] == [
            'armed', 'Show.dispatch', 'Show.return', 'OnConfirm.dispatch', 'OnConfirm.return']
    assert all(worker['exit_code'] == 0 and worker['reaped'] for worker in report['worker_cleanup'])
    assert len(report['jobs']) == 3
    assert all(job['active_processes'] == job['total_terminated_processes'] == 0
               for job in report['jobs'])
    assert report['server']['listener_closed'] is True and report['server']['state_lock_released'] is True
    assert all(report[key] is True for key in ('package_files_unchanged', 'assets_unchanged',
        'shared_channels_unchanged', 'source_files_unchanged', 'temporary_pki_removed'))
    return dict(passed=True, recipe=42, match_frames=report['match']['frames'],
                report_sha256=sha(RUN / 'verification.json'),
                installed_gameassembly_sha256=sha(GAME / 'GameAssembly.dll'),
                helper_sha256=sha(HELPER), package_sha256=archives,
                client_exits=[c['driver_report']['game_exit_code'] for c in report['clients']],
                worker_exits=[w['exit_code'] for w in report['worker_cleanup']])


if __name__ == '__main__':
    result = review()
    (RUN / 'review480.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
