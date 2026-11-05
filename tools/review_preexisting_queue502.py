"""Independently bind recipe45's prelaunch cached-queue run to source and bytes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from client_patch.patcher.patch_client import build_patch
from client_patch.patcher.telemetry import RECIPE_VERSION, RUNTIME_VALIDATED
from tools.helper_provenance import validate as validate_helper
from tools.telemetry_preexisting_seed import snapshot
from tools.review_reporter_delegate_targets300 import ORIGINAL, OLD_SHA


ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / 'local/privacy502-game01'
OUT = ROOT / 'local/privacy502-preexisting02'
BUILD = ROOT / 'local/privacy502-helper-build01'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def literal(source: str, name: str) -> bytes:
    start = f'static constexpr const char* {name}=R"('
    assert source.count(start) == 1
    tail = source.split(start, 1)[1]
    assert ')";' in tail
    return tail.split(')";', 1)[0].encode('utf-8')


def review() -> dict:
    assert RECIPE_VERSION == 45 and RUNTIME_VALIDATED is False
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == OLD_SHA
    manifest_path = GAME / '.battleaces-resurrection/patch-manifest.json'
    manifest = read(manifest_path)
    assert manifest['telemetry']['recipe_version'] == 45
    assert manifest['telemetry']['runtime_validated'] is False
    assert manifest['diagnostics'] == dict(native_quit=False, startup_tasks=False,
                                           dlss_enabled=False)
    assert manifest['components']['GameAssembly.dll']['telemetry_guards'] == 107
    assert manifest['asset_loading']['bundle_count'] == 133
    expected_assembly = hashlib.sha256(build_patch(original, community=True,
            cosmetics=True, quit_diagnostics=False)).hexdigest()
    assert sha(GAME / 'GameAssembly.dll') == expected_assembly
    assert manifest['components']['GameAssembly.dll']['patched_sha256'] == expected_assembly
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
    for name in ('tools/verify_native_quit.py','tools/telemetry_preexisting_seed.py',
                 'tools/telemetry_current_queue_evidence.py'):
        assert run['source_sha256_at_start'][name] == sha(ROOT / name)
    verifier_source=(ROOT / 'tools/verify_native_quit.py').read_text(encoding='utf-8')
    assert verifier_source.index('preexisting_root,preexisting_before=seed(game,profile)') < \
           verifier_source.index('subprocess.Popen(command')
    assert run['helper_sha256'] == sha(helper)
    assert run['helper_build']['sha256'] == sha(BUILD / 'helper-build.json')
    assert run['patch_manifest_sha256'] == sha(manifest_path)
    assert run['telemetry']['passed'] is True and run['telemetry']['recipe_version'] == 45
    assert run['telemetry_current_queue']['passed'] is True
    assert run['telemetry_current_queue']['authored_seeds'] == 2
    assert run['telemetry_current_queue']['event_files_returned'] == 0
    assert run['telemetry_current_queue']['session_files_returned'] == 0
    assert run['telemetry_current_queue']['event_lookup_null'] is True
    assert run['telemetry_current_queue']['session_lookup_null'] is True
    assert run['telemetry_current_queue']['seed_identity_and_bytes_unchanged'] is True
    assert run['telemetry_current_queue']['guarded_delete_entries_returned'] is True
    assert run['telemetry_current_queue']['version'] == 3
    assert run['telemetry_current_queue']['preexisting_before_client'] is True
    assert run['telemetry_current_queue']['resumed_or_inflight_delivery_qualified'] is False
    assert [row['event'] for row in run['trace']] == [
        'armed', 'Show.dispatch', 'Show.return', 'OnConfirm.dispatch', 'OnConfirm.return']
    assert all(row['pid'] == run['pid'] and
               row['thread'] == run['telemetry_current_queue']['thread'] for row in run['trace'])

    source = (ROOT / 'client_patch/src/telemetry_cache_probe.cpp').read_text(encoding='utf-8')
    folder = GAME / '.battleaces-resurrection/profiles' / run['profile'] / 'qc/Bugsnag'
    event = folder / 'Events/authored-event-120.event'
    session = folder / 'Sessions/authored-session-120.session'
    assert event.read_bytes() == literal(source, 'eventFixture')
    assert session.read_bytes() == literal(source, 'sessionFixture')
    assert sorted(path.relative_to(folder).as_posix() for path in folder.rglob('*') if path.is_file()) == [
        'Events/authored-event-120.event', 'Sessions/authored-session-120.session']
    assert run['preexisting_queue_unchanged'] is True
    assert run['preexisting_queue_before'] == run['preexisting_queue_after'] == snapshot(folder)

    log = (OUT / 'native.log').read_text(encoding='utf-8')
    assert len(re.findall(r'Telemetry audit build verified: .*recipeVersion=45 .*sdkCacheReaderSignatures=5/5;', log)) == 1
    assert log.count('TELEMETRY CACHECLIENT probe passed:') == 1
    assert log.count('TELEMETRY CURRENTQUEUE begin:') == 1
    assert log.count('TELEMETRY CURRENTQUEUE probe passed:') == 1
    assert log.count('TELEMETRY CURRENTQUEUE scope restored:') == 1
    assert log.count('TELEMETRY PREEXISTING begin:') == 1
    assert log.count('TELEMETRY PREEXISTING ctor passed:') == 1
    assert 'ownedFilesBeforeClient=2' in log
    assert 'fileIdentitiesAndBytesUnchanged=2' in log
    assert 'version=3 thread=' in log
    assert 'preexistingBeforeClient=1' in log
    assert 'authoredSeeds=2 preexistingBeforeClient=1 eventFiles=0 sessionFiles=0 eventNull=1 sessionNull=1' in log
    assert 'cachedStartReturned=1 deleteEntriesReturned=2' in log
    assert 'seedIdentitiesAndBytesUnchanged=2 reportDelivered=0' in log
    assert 'TELEMETRY CACHE probe failed:' not in log
    assert 'TELEMETRY CACHEREAD ' not in log and 'TELEMETRY CACHEREADER' not in log
    return dict(passed=True, recipe=45, assembly_sha256=expected_assembly,
                helper_sha256=sha(helper), run_sha256=sha(OUT / 'verification.json'),
                native_log_sha256=sha(OUT / 'native.log'),
                event_sha256=sha(event), session_sha256=sha(session),
                authored_files_retained=2, preexisting_before_process_and_client=True,
                guarded_delete_entries_returned=2, original_quit=True,
                final_privacy_qualified=False)


if __name__ == '__main__':
    result = review()
    (OUT / 'review502.json').write_text(json.dumps(result, indent=2) + '\n',
                                        encoding='utf-8')
    print(json.dumps(result, sort_keys=True))
