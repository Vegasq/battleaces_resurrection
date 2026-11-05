"""Bind recipe47's owned prelaunch SDK queue run to current source and bytes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from client_patch.patcher.patch_client import build_patch
from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, RUNTIME_VALIDATED
from tools.helper_provenance import validate as validate_helper
from tools.review_webview_fulltext396 import ORIGINAL, ORIGINAL_SHA
from tools.telemetry_preexisting_seed import literals, snapshot

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / 'local/privacy520-game01'
OUT = ROOT / 'local/privacy520-preexisting04'
BUILD = ROOT / 'local/privacy512-helper-build01'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def review() -> dict:
    assert RECIPE_VERSION == 47 and RUNTIME_VALIDATED is False
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    expected = hashlib.sha256(build_patch(original, community=True, cosmetics=True,
                                           quit_diagnostics=True)).hexdigest()
    manifest_path = GAME / '.battleaces-resurrection/patch-manifest.json'
    manifest = read(manifest_path)
    assert manifest['telemetry']['recipe_version'] == 47
    assert manifest['telemetry']['runtime_validated'] is False
    assert manifest['diagnostics']['native_quit'] is True
    assert manifest['components']['GameAssembly.dll']['telemetry_guards'] == 108
    assert manifest['asset_loading']['bundle_count'] == 133
    assert sha(GAME / 'GameAssembly.dll') == manifest['components']['GameAssembly.dll']['patched_sha256'] == expected
    installed = (GAME / 'GameAssembly.dll').read_bytes()
    startup = [patch for patch in COMPONENTS['GameAssembly.dll'].patches
               if patch.label == 'BugsnagUnity.Bugsnag::Start' or
               patch.label == 'BugsnagUnity.BugsnagAutoInit::OnBeforeSceneLoadRuntimeMethod']
    assert len(startup) == 3
    for patch in startup:
        assert original[patch.offset:patch.offset + len(patch.guard)] == patch.guard
        assert installed[patch.offset:patch.offset + len(patch.replacement)] == patch.replacement == b'\xc3'
    helper = BUILD / 'BattleAcesOffline.dll'
    assert validate_helper(helper, helper.read_bytes(), ROOT)['helper_sha256'] == sha(helper)
    assert sha(GAME / 'BattleAcesOffline.dll') == manifest['helper_sha256'] == sha(helper)

    run = read(OUT / 'verification.json')
    assert run['passed'] and run['mode'] == 'confirm' and run['exit_code'] == 0
    assert '-telemetry-preexisting-queue-probe' in run['command']
    assert run['natural_exit'] and not run['forced_cleanup'] and run['owned_process_reaped']
    assert run['source_files_unchanged'] and run['shared_settings_unchanged']
    assert run['source_sha256_at_start'] == run['source_sha256_at_finish']
    for name in ('tools/verify_native_quit.py', 'tools/telemetry_preexisting_seed.py',
                 'tools/telemetry_current_queue_evidence.py'):
        assert run['source_sha256_at_start'][name] == sha(ROOT / name)
    assert run['helper_sha256'] == sha(helper)
    assert run['helper_build']['sha256'] == sha(BUILD / 'helper-build.json')
    assert run['patch_manifest_sha256'] == sha(manifest_path)
    assert run['telemetry']['passed'] and run['telemetry']['recipe_version'] == 47
    queue = run['telemetry_current_queue']
    assert queue['passed'] and queue['recipe'] == 47 and queue['version'] == 3
    assert queue['authored_seeds'] == 2 and queue['preexisting_before_client']
    assert queue['event_files_returned'] == queue['session_files_returned'] == 0
    assert queue['event_lookup_null'] and queue['session_lookup_null']
    assert queue['guarded_delete_entries_returned'] and queue['seed_identity_and_bytes_unchanged']
    assert not queue['report_delivered'] and not queue['whole_run_privacy_qualified']
    assert not queue['resumed_or_inflight_delivery_qualified']
    assert [row['event'] for row in run['trace']] == [
        'armed', 'Show.dispatch', 'Show.return', 'OnConfirm.dispatch', 'OnConfirm.return',
        'RGameSingleton.OnDestroy.enter', 'RGameInstance.Dispose.enter',
        'RGameInstance.Dispose.return', 'RGameSingleton.OnDestroy.return']
    assert all(row['pid'] == run['pid'] and row['thread'] == queue['thread'] for row in run['trace'])

    folder = GAME / '.battleaces-resurrection/profiles' / run['profile'] / 'qc/Bugsnag'
    for relative, payload in literals().items():
        assert (folder / relative).read_bytes() == payload
    assert run['preexisting_queue_unchanged']
    assert run['preexisting_queue_before'] == run['preexisting_queue_after'] == snapshot(folder)
    log = (OUT / 'native.log').read_text(encoding='utf-8')
    for marker in ('Telemetry audit build verified:', 'TELEMETRY PREEXISTING begin:',
                   'TELEMETRY PREEXISTING ctor passed:', 'TELEMETRY CURRENTQUEUE begin:',
                   'TELEMETRY CURRENTQUEUE probe passed:', 'TELEMETRY CURRENTQUEUE scope restored:'):
        assert log.count(marker) == 1
    assert 'recipeVersion=47 ' in log and 'sdkCacheReaderSignatures=5/5 sdkCacheDirectorySignatures=1/1;' in log
    assert 'ownedFilesBeforeClient=2' in log and 'fileIdentitiesAndBytesUnchanged=2' in log
    assert 'cachedStartReturned=1 deleteEntriesReturned=2' in log
    assert 'seedIdentitiesAndBytesUnchanged=2 reportDelivered=0' in log
    assert 'TELEMETRY CACHE probe failed:' not in log
    return {'passed': True, 'recipe': 47, 'assembly_sha256': expected,
            'helper_sha256': sha(helper), 'verification_sha256': sha(OUT / 'verification.json'),
            'native_log_sha256': sha(OUT / 'native.log'), 'authored_files_retained': 2,
            'original_quit': True, 'ordinary_start_guards': 3,
            'genuine_client_was_opt_in_fixture': True, 'final_privacy_qualified': False}


if __name__ == '__main__':
    print(json.dumps(review(), indent=2))
