"""Independently bind the recipe44 in-memory SDK error run to source and Quit."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from client_patch.patcher.patch_client import build_patch
from client_patch.patcher.telemetry import RECIPE_VERSION, RUNTIME_VALIDATED
from tools.helper_provenance import validate as validate_helper
from tools.review_reporter_delegate_targets300 import ORIGINAL, OLD_SHA


ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / 'local/privacy498-game01'
OUT = ROOT / 'local/privacy499-error01'
BUILD = ROOT / 'local/privacy499-helper-build01'
ENTRIES = (0x814ef0, 0x815100, 0x815390, 0x8153e0,
           0x8154e0, 0x8157d0, 0x815ba0)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def review() -> dict:
    assert RECIPE_VERSION == 44 and RUNTIME_VALIDATED is False
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == OLD_SHA
    manifest = read(GAME / '.battleaces-resurrection/patch-manifest.json')
    assert manifest['telemetry']['recipe_version'] == 44
    assert manifest['telemetry']['runtime_validated'] is False
    assert manifest['diagnostics'] == dict(native_quit=True, startup_tasks=False,
                                           dlss_enabled=False)
    assert manifest['components']['GameAssembly.dll']['telemetry_guards'] == 106
    assert manifest['asset_loading']['bundle_count'] == 133
    patched = build_patch(original, community=True, cosmetics=True,
                          quit_diagnostics=True)
    assembly_hash = hashlib.sha256(patched).hexdigest()
    assert assembly_hash == sha(GAME / 'GameAssembly.dll')
    assert assembly_hash == manifest['components']['GameAssembly.dll']['patched_sha256']
    assert sha(GAME / '.battleaces-resurrection/original/GameAssembly.dll') == OLD_SHA
    helper = BUILD / 'BattleAcesOffline.dll'
    provenance = validate_helper(helper, helper.read_bytes(), ROOT)
    assert provenance['helper_sha256'] == sha(helper) == sha(GAME / 'BattleAcesOffline.dll')
    assert manifest['helper_sha256'] == sha(helper)

    run = read(OUT / 'verification.json')
    assert run['passed'] is True and run['mode'] == 'confirm'
    assert run['exit_code'] == 0 and run['natural_exit'] is True
    assert run['forced_cleanup'] is False and run['owned_process_reaped'] is True
    assert run['source_files_unchanged'] is True and run['shared_settings_unchanged'] is True
    assert run['source_sha256_at_start'] == run['source_sha256_at_finish']
    assert run['helper_sha256'] == sha(helper)
    assert run['helper_build']['sha256'] == sha(BUILD / 'helper-build.json')
    assert run['patch_manifest_sha256'] == sha(GAME / '.battleaces-resurrection/patch-manifest.json')
    assert run['telemetry']['passed'] is True and run['telemetry']['recipe_version'] == 44
    assert run['telemetry']['observed_stages'] == ['startup-after-engine-init', 'menu', 'pre-quit-confirm']
    assert run['telemetry_current_error']['passed'] is True
    assert run['telemetry_current_error']['original_cache_reads'] == 0
    assert run['telemetry_current_error']['whole_run_privacy_qualified'] is False
    assert run['telemetry_report_errors']['entries'] == list(ENTRIES)
    assert run['telemetry_report_errors']['local_exception_log_retained'] is True
    assert run['telemetry_report_errors']['resumed_or_inflight_delivery_qualified'] is False
    assert 'Exception: authored-report-error165' in (OUT / 'game.log').read_text(encoding='utf-8')
    assert [row['event'] for row in run['trace']] == [
        'armed', 'Show.dispatch', 'Show.return', 'OnConfirm.dispatch', 'OnConfirm.return',
        'RGameSingleton.OnDestroy.enter', 'RGameInstance.Dispose.enter',
        'RGameInstance.Dispose.return', 'RGameSingleton.OnDestroy.return']
    assert all(row['pid'] == run['pid'] and
               row['thread'] == run['telemetry_report_errors']['thread'] for row in run['trace'])

    log = (OUT / 'native.log').read_text(encoding='utf-8')
    build = re.findall(r'Telemetry audit build verified: .*recipeVersion=44 .*sdkCacheReaderSignatures=4/4;', log)
    calls = re.findall(r'TELEMETRY REPORTERROR call: version=1 thread=(\d+) index=(\d+) rva=([0-9a-f]+) returned=1 clientStable=1 exceptionStable=1', log)
    assert len(build) == 1 and len(calls) == 7
    assert [int(row[1]) for row in calls] == list(range(1, 8))
    assert tuple(int(row[2], 16) for row in calls) == ENTRIES
    assert all(int(row[0]) == run['telemetry_report_errors']['thread'] for row in calls)
    assert log.count('TELEMETRY CACHECLIENT probe passed:') == 1
    assert log.count('TELEMETRY CURRENTERROR probe passed:') == 1
    assert 'originalCacheReads=0 pathRestored=1 reportDelivered=0' in log
    assert 'TELEMETRY CACHE probe failed:' not in log
    assert 'TELEMETRY CACHEREAD ' not in log and 'TELEMETRY CACHEREADER' not in log
    folder = GAME / '.battleaces-resurrection/profiles' / run['profile'] / 'qc'
    assert folder.is_dir()
    assert not any(path.is_file() for path in folder.rglob('*'))
    return dict(passed=True, recipe=44, assembly_sha256=assembly_hash,
                helper_sha256=sha(helper), run_sha256=sha(OUT / 'verification.json'),
                native_log_sha256=sha(OUT / 'native.log'), original_cache_reads=0,
                genuine_client=True, guarded_error_calls=7, original_quit=True,
                final_privacy_qualified=False)


if __name__ == '__main__':
    result = review()
    (OUT / 'review499.json').write_text(json.dumps(result, indent=2) + '\n',
                                        encoding='utf-8')
    print(json.dumps(result, sort_keys=True))
