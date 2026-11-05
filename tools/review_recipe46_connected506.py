"""Bind the private recipe46 pair to one connected match and normal exits."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from client_patch.patcher.patch_client import build_patch
from client_patch.patcher.telemetry import RECIPE_VERSION, RUNTIME_VALIDATED
from tools.helper_provenance import validate as validate_helper
from tools.package_integrity import verify
from tools.review_webview_fulltext396 import ORIGINAL, ORIGINAL_SHA

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / 'local/privacy506-game01'
PACKAGES = ROOT / 'local/privacy506-packages01'
RUN = ROOT / 'local/privacy506-public1-01'
HELPER = ROOT / 'local/privacy504-helper-build02/BattleAcesOffline.dll'
TELEMETRY_SOURCE = ROOT / 'client_patch/patcher/telemetry.py'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def review() -> dict:
    assert RECIPE_VERSION == 46 and RUNTIME_VALIDATED is False
    report = load(RUN / 'verification.json')
    build = load(PACKAGES / 'build-report.json')
    manifest_path = GAME / '.battleaces-resurrection/patch-manifest.json'
    manifest = load(manifest_path)
    assert sha(ORIGINAL) == ORIGINAL_SHA
    original = ORIGINAL.read_bytes()
    assert sha(GAME / '.battleaces-resurrection/original/GameAssembly.dll') == ORIGINAL_SHA
    expected_assembly = build_patch(original, community=True, cosmetics=True)
    assert expected_assembly == (GAME / 'GameAssembly.dll').read_bytes()
    assert manifest['telemetry']['recipe_version'] == 46
    assert manifest['telemetry']['runtime_validated'] is False
    assert manifest['diagnostics']['native_quit'] is False
    assert manifest['components']['GameAssembly.dll']['telemetry_guards'] == 108
    assert manifest['components']['GameAssembly.dll']['installed_sha256'] == sha(GAME / 'GameAssembly.dll')
    helper_provenance = validate_helper(HELPER, HELPER.read_bytes(), ROOT)
    assert helper_provenance['helper_sha256'] == sha(HELPER)
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
    assert report['source_sha256_at_start'] == report['source_sha256_at_finish']
    assert report['source_sha256_at_start']['client_patch/patcher/telemetry.py'] == sha(TELEMETRY_SOURCE)
    return dict(passed=True, recipe=46, match_frames=report['match']['frames'],
                report_sha256=sha(RUN / 'verification.json'),
                installed_gameassembly_sha256=sha(GAME / 'GameAssembly.dll'),
                helper_sha256=sha(HELPER), package_sha256=archives,
                client_exits=[c['driver_report']['game_exit_code'] for c in report['clients']],
                worker_exits=[w['exit_code'] for w in report['worker_cleanup']],
                final_privacy_qualified=False)


if __name__ == '__main__':
    print(json.dumps(review(), indent=2))
