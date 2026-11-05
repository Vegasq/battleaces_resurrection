"""Independently bind the recipe44 authored queue run to source and bytes."""
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
GAME = ROOT / 'local/privacy500-game01'
OUT = ROOT / 'local/privacy500-queue01'
BUILD = ROOT / 'local/privacy500-helper-build01'


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
    assert RECIPE_VERSION == 44 and RUNTIME_VALIDATED is False
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == OLD_SHA
    manifest_path = GAME / '.battleaces-resurrection/patch-manifest.json'
    manifest = read(manifest_path)
    assert manifest['telemetry']['recipe_version'] == 44
    assert manifest['telemetry']['runtime_validated'] is False
    assert manifest['diagnostics'] == dict(native_quit=True, startup_tasks=False,
                                           dlss_enabled=False)
    assert manifest['components']['GameAssembly.dll']['telemetry_guards'] == 106
    assert manifest['asset_loading']['bundle_count'] == 133
    expected_assembly = hashlib.sha256(build_patch(original, community=True,
            cosmetics=True, quit_diagnostics=True)).hexdigest()
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
    assert run['helper_sha256'] == sha(helper)
    assert run['helper_build']['sha256'] == sha(BUILD / 'helper-build.json')
    assert run['patch_manifest_sha256'] == sha(manifest_path)
    assert run['telemetry']['passed'] is True and run['telemetry']['recipe_version'] == 44
    assert run['telemetry_current_queue']['passed'] is True
    assert run['telemetry_current_queue']['authored_seeds'] == 2
    assert run['telemetry_current_queue']['event_files_returned'] == 0
    assert run['telemetry_current_queue']['session_files_returned'] == 0
    assert run['telemetry_current_queue']['event_lookup_null'] is True
    assert run['telemetry_current_queue']['session_lookup_null'] is True
    assert run['telemetry_current_queue']['seed_identity_and_bytes_unchanged'] is True
    assert run['telemetry_current_queue']['resumed_or_inflight_delivery_qualified'] is False
    assert [row['event'] for row in run['trace']] == [
        'armed', 'Show.dispatch', 'Show.return', 'OnConfirm.dispatch', 'OnConfirm.return',
        'RGameSingleton.OnDestroy.enter', 'RGameInstance.Dispose.enter',
        'RGameInstance.Dispose.return', 'RGameSingleton.OnDestroy.return']
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

    log = (OUT / 'native.log').read_text(encoding='utf-8')
    assert len(re.findall(r'Telemetry audit build verified: .*recipeVersion=44 .*sdkCacheReaderSignatures=4/4;', log)) == 1
    assert log.count('TELEMETRY CACHECLIENT probe passed:') == 1
    assert log.count('TELEMETRY CURRENTQUEUE begin:') == 1
    assert log.count('TELEMETRY CURRENTQUEUE probe passed:') == 1
    assert log.count('TELEMETRY CURRENTQUEUE scope restored:') == 1
    assert 'authoredSeeds=2 eventFiles=0 sessionFiles=0 eventNull=1 sessionNull=1' in log
    assert 'seedIdentitiesAndBytesUnchanged=2 reportDelivered=0' in log
    assert 'TELEMETRY CACHE probe failed:' not in log
    assert 'TELEMETRY CACHEREAD ' not in log and 'TELEMETRY CACHEREADER' not in log
    return dict(passed=True, recipe=44, assembly_sha256=expected_assembly,
                helper_sha256=sha(helper), run_sha256=sha(OUT / 'verification.json'),
                native_log_sha256=sha(OUT / 'native.log'),
                event_sha256=sha(event), session_sha256=sha(session),
                authored_files_retained=2, original_quit=True,
                final_privacy_qualified=False)


if __name__ == '__main__':
    result = review()
    (OUT / 'review500.json').write_text(json.dumps(result, indent=2) + '\n',
                                        encoding='utf-8')
    print(json.dumps(result, sort_keys=True))
