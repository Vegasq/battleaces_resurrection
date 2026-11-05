"""Review recipe46 prelaunch cached files against the owned run and sources."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from client_patch.patcher.patch_client import build_patch
from client_patch.patcher.telemetry import RECIPE_VERSION, RUNTIME_VALIDATED
from tools.helper_provenance import validate as validate_helper
from tools.review_preexisting_queue502 import literal
from tools.review_sdk_directory504 import review as review_directory
from tools.review_webview_fulltext396 import ORIGINAL, ORIGINAL_SHA
from tools.telemetry_preexisting_seed import snapshot

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / 'local/privacy504-game01'
BUILD = ROOT / 'local/privacy504-helper-build02'
OUT = ROOT / 'local/privacy505-preexisting01'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def review() -> dict:
    assert RECIPE_VERSION == 46 and RUNTIME_VALIDATED is False
    assert review_directory()['passed'] is True
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    manifest_path = GAME / '.battleaces-resurrection/patch-manifest.json'
    manifest = read(manifest_path)
    assert manifest['telemetry']['recipe_version'] == 46
    assert manifest['telemetry']['runtime_validated'] is False
    assert manifest['diagnostics']['native_quit'] is True
    assert manifest['components']['GameAssembly.dll']['telemetry_guards'] == 108
    assert manifest['asset_loading']['bundle_count'] == 133
    expected_assembly = hashlib.sha256(build_patch(original, community=True,
            cosmetics=True, quit_diagnostics=True)).hexdigest()
    assert sha(GAME / 'GameAssembly.dll') == expected_assembly
    assert manifest['components']['GameAssembly.dll']['patched_sha256'] == expected_assembly
    helper = BUILD / 'BattleAcesOffline.dll'
    provenance = validate_helper(helper, helper.read_bytes(), ROOT)
    assert provenance['helper_sha256'] == sha(helper) == sha(GAME / 'BattleAcesOffline.dll')
    assert manifest['helper_sha256'] == sha(helper)

    run = read(OUT / 'verification.json')
    assert run['passed'] and run['mode'] == 'confirm' and run['exit_code'] == 0
    assert run['natural_exit'] and not run['forced_cleanup'] and run['owned_process_reaped']
    assert run['source_files_unchanged'] and run['shared_settings_unchanged']
    assert run['source_sha256_at_start'] == run['source_sha256_at_finish']
    for name in ('tools/verify_native_quit.py', 'tools/telemetry_preexisting_seed.py',
                 'tools/telemetry_current_queue_evidence.py'):
        assert run['source_sha256_at_start'][name] == sha(ROOT / name)
    verifier_source = (ROOT / 'tools/verify_native_quit.py').read_text(encoding='utf-8')
    assert verifier_source.index('preexisting_root,preexisting_before=seed(game,profile)') < \
           verifier_source.index('subprocess.Popen(command')
    assert run['helper_sha256'] == sha(helper)
    assert run['helper_build']['sha256'] == sha(BUILD / 'helper-build.json')
    assert run['patch_manifest_sha256'] == sha(manifest_path)
    assert run['telemetry']['passed'] and run['telemetry']['recipe_version'] == 46
    queue = run['telemetry_current_queue']
    assert queue['passed'] and queue['version'] == 3 and queue['authored_seeds'] == 2
    assert queue['preexisting_before_client'] and queue['seed_identity_and_bytes_unchanged']
    assert queue['guarded_delete_entries_returned']
    assert queue['event_files_returned'] == queue['session_files_returned'] == 0
    assert queue['event_lookup_null'] and queue['session_lookup_null']
    assert not queue['resumed_or_inflight_delivery_qualified']
    assert [row['event'] for row in run['trace']] == [
        'armed', 'Show.dispatch', 'Show.return', 'OnConfirm.dispatch', 'OnConfirm.return',
        'RGameSingleton.OnDestroy.enter', 'RGameInstance.Dispose.enter',
        'RGameInstance.Dispose.return', 'RGameSingleton.OnDestroy.return']
    assert all(row['pid'] == run['pid'] and row['thread'] == queue['thread'] for row in run['trace'])

    source = (ROOT / 'client_patch/src/telemetry_cache_probe.cpp').read_text(encoding='utf-8')
    folder = GAME / '.battleaces-resurrection/profiles' / run['profile'] / 'qc/Bugsnag'
    event = folder / 'Events/authored-event-120.event'
    session = folder / 'Sessions/authored-session-120.session'
    assert event.read_bytes() == literal(source, 'eventFixture')
    assert session.read_bytes() == literal(source, 'sessionFixture')
    assert sorted(path.relative_to(folder).as_posix() for path in folder.rglob('*') if path.is_file()) == [
        'Events/authored-event-120.event', 'Sessions/authored-session-120.session']
    assert run['preexisting_queue_unchanged']
    assert run['preexisting_queue_before'] == run['preexisting_queue_after'] == snapshot(folder)
    log = (OUT / 'native.log').read_text(encoding='utf-8')
    assert len(re.findall(r'Telemetry audit build verified: .*recipeVersion=46 .*sdkCacheReaderSignatures=5/5 sdkCacheDirectorySignatures=1/1;', log)) == 1
    for marker in ('TELEMETRY CACHECLIENT probe passed:', 'TELEMETRY CURRENTQUEUE begin:',
                   'TELEMETRY CURRENTQUEUE probe passed:', 'TELEMETRY CURRENTQUEUE scope restored:',
                   'TELEMETRY PREEXISTING begin:', 'TELEMETRY PREEXISTING ctor passed:'):
        assert log.count(marker) == 1
    assert 'ownedFilesBeforeClient=2' in log and 'fileIdentitiesAndBytesUnchanged=2' in log
    assert 'cachedStartReturned=1 deleteEntriesReturned=2' in log
    assert 'seedIdentitiesAndBytesUnchanged=2 reportDelivered=0' in log
    assert 'TELEMETRY CACHE probe failed:' not in log
    return dict(passed=True, recipe=46, assembly_sha256=expected_assembly,
                helper_sha256=sha(helper), verification_sha256=sha(OUT / 'verification.json'),
                native_log_sha256=sha(OUT / 'native.log'),
                event_sha256=sha(event), session_sha256=sha(session),
                preexisting_before_process_and_client=True, authored_files_retained=2,
                original_quit=True, final_privacy_qualified=False)


if __name__ == '__main__':
    print(json.dumps(review(), indent=2))
