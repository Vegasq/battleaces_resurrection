"""Bind recipe47's authored prelaunch queue to a complete passive native trace."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from client_patch.patcher.patch_client import build_patch
from client_patch.patcher.telemetry import RECIPE_VERSION, RUNTIME_VALIDATED
from tools.frida_sdk_queue440 import ENTRIES, GUARDED, build_source
from tools.helper_provenance import validate as validate_helper
from tools.review_d5_exit_network368 import payloads, records_for
from tools.review_unity_post512 import GAME as REVIEWED_GAME, review as review_recipe47
from tools.review_webview_fulltext396 import ORIGINAL, ORIGINAL_SHA
from tools.telemetry_preexisting_seed import literals, snapshot
from tools.extract_descriptors import PE

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / 'local/privacy520-game01'
OUT = ROOT / 'local/privacy523-preexisting01'
TRACE = ROOT / 'local/privacy523-trace01'
BUILD = ROOT / 'local/privacy512-helper-build01'
SESSION = '221e9151-4487-483c-b194-cd6dce5b229a'


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review() -> dict:
    assert RECIPE_VERSION == 47 and RUNTIME_VALIDATED is False
    assert review_recipe47()['passed']
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    expected = hashlib.sha256(build_patch(original, community=True, cosmetics=True,
                                           quit_diagnostics=True)).hexdigest()
    manifest_path = GAME / '.battleaces-resurrection/patch-manifest.json'
    manifest = read(manifest_path)
    assert manifest['telemetry']['recipe_version'] == 47
    assert manifest['diagnostics']['native_quit'] is True
    assert manifest['components']['GameAssembly.dll']['telemetry_guards'] == 108
    assert sha(GAME / 'GameAssembly.dll') == manifest['components']['GameAssembly.dll']['patched_sha256'] == expected
    assert sha(GAME / 'UnityPlayer.dll') == sha(REVIEWED_GAME / 'UnityPlayer.dll')
    helper = BUILD / 'BattleAcesOffline.dll'
    assert validate_helper(helper, helper.read_bytes(), ROOT)['helper_sha256'] == sha(helper)
    assert sha(GAME / 'BattleAcesOffline.dll') == manifest['helper_sha256'] == sha(helper)
    image = PE((GAME / 'GameAssembly.dll').read_bytes())
    for name, (rva, signature) in (GUARDED | ENTRIES).items():
        offset = image.offset(image.base + rva, 16)
        assert image.data[offset:offset + 16].hex() == signature, name

    run = read(OUT / 'verification.json')
    prelaunch = read(OUT / 'prelaunch.json')
    assert run['passed'] and run['prelaunch_observer'] and run['natural_exit']
    assert run['exit_code'] == 0 and not run['forced_cleanup'] and run['owned_process_reaped']
    assert run['mode'] == 'confirm' and run['profile'] == 'nativestest_quit_d5q523a'
    assert run['pid'] == prelaunch['pid'] and prelaunch['suspended_for_observer']
    assert prelaunch['job_assigned'] and prelaunch['launch_tick'] == run['launch_tick']
    gate = OUT / 'observer-ready'
    assert gate.read_bytes() == b'FRIDA_READY\n'
    assert (OUT / 'prelaunch.json').stat().st_mtime_ns < gate.stat().st_mtime_ns
    assert run['prelaunch_resume_tick'] >= run['launch_tick']
    assert '-telemetry-preexisting-queue-probe' in run['command']
    assert run['source_files_unchanged'] and run['shared_settings_unchanged']
    assert run['source_sha256_at_start'] == run['source_sha256_at_finish']
    for name in ('tools/verify_native_quit.py', 'tools/telemetry_preexisting_seed.py',
                 'tools/telemetry_current_queue_evidence.py'):
        assert run['source_sha256_at_start'][name] == sha(ROOT / name)
    assert run['helper_sha256'] == sha(helper)
    assert run['patch_manifest_sha256'] == sha(manifest_path)
    queue = run['telemetry_current_queue']
    assert run['telemetry']['passed'] and run['telemetry']['recipe_version'] == 47
    assert queue['passed'] and queue['version'] == 3 and queue['recipe'] == 47
    assert queue['preexisting_before_client'] and queue['authored_seeds'] == 2
    assert queue['event_files_returned'] == queue['session_files_returned'] == 0
    assert queue['event_lookup_null'] and queue['session_lookup_null']
    assert queue['guarded_delete_entries_returned'] and not queue['report_delivered']
    assert not queue['whole_run_privacy_qualified'] and not queue['resumed_or_inflight_delivery_qualified']
    root = GAME / '.battleaces-resurrection/profiles' / run['profile'] / 'qc/Bugsnag'
    for relative, data in literals().items():
        assert (root / relative).read_bytes() == data
    assert run['preexisting_queue_unchanged']
    assert run['preexisting_queue_before'] == run['preexisting_queue_after'] == snapshot(root)

    config = read(TRACE / 'config.json')
    assert config['profile'] == run['profile']
    assert config['game_sha256'] == sha(GAME / 'Battle Aces.exe')
    assert len(config['config']['fileRoots']) == 2
    assert config['config']['fileRoots'][1] == str(root)
    observer = TRACE / 'observer.js'
    assert observer.read_text(encoding='utf-8') == build_source(config['config'])
    assert config['source_sha256'] == sha(observer)
    bundle = read(TRACE / 'rea-evidence.json')
    loads = records_for(bundle, SESSION, 'load_frida_script')
    finals = [item for item in records_for(bundle, SESSION, 'frida_session_status')
              if item['normalized_result'].get('state') == 'detached']
    assert len(loads) == len(finals) == 1
    load, final = loads[0], finals[0]
    assert load['normalized_result']['source_sha256'] == sha(observer)
    early, messages = payloads(load), payloads(final)
    assert messages[:len(early)] == early and not final['normalized_result']['messages_truncated']
    assert [item['kind'] for item in early[-2:]] == ['observer-ready', 'exit-boundary-armed']
    assert all(item['pid'] == run['pid'] and item['runId'] == config['config']['runId'] for item in messages)
    hooks = [dict(key=key, rva=value[0]) for key, value in ENTRIES.items()]
    ready = [item for item in messages if item['kind'] == 'sdk-module-ready']
    assert len(ready) == 1 and ready[0]['data'] == dict(hooks=hooks, errors=[])
    boundary = [item for item in messages if item['kind'] == 'self-terminate-entry']
    assert len(boundary) == 1 and boundary[0] == messages[-1]
    assert ready[0]['seq'] < boundary[0]['seq']
    data = boundary[0]['data']
    assert data['exitStatus'] == 0 and data['sdkHooks'] == hooks and data['sdkErrors'] == []
    assert data['sdkCounts'] == {key: 0 for key in ENTRIES}
    assert data['errors'] == [] and data['overflow'] is False and data['unknownRelativeRoots'] == 0
    assert not any(item['kind'] in ('sdk-entry', 'network-operation', 'process-create',
                         'budget-exceeded', 'decode-error') for item in messages)
    files = [item['data'] for item in messages if item['kind'] == 'file-operation']
    assert len(files) == 24
    assert all(str(root).lower() in item['path'].lower() for item in files)
    assert all(any(frame['module'] == 'battleacesoffline.dll' for frame in item['frames'])
               for item in files)
    reads = [item for item in files if item['operation'] == 'NtReadFile']
    assert len(reads) == 6 and all(item['returnValue'] == 0 for item in reads)
    assert sum(item['path'].endswith('authored-event-120.event') for item in reads) == 3
    assert sum(item['path'].endswith('authored-session-120.session') for item in reads) == 3
    assert all(item['operation'] in ('NtReadFile', 'NtCreateFile') for item in files)
    unresolved = [item['data'] for item in messages if item['kind'] == 'unresolved-file-operation']
    assert len(unresolved) == 9
    assert all(item['operation'] == 'NtWriteFile' and item['returnValue'] == -1073741816
               for item in unresolved)
    assert all(data['counts'][name] == 0 for name in ('ws2_32.dll:send',
                                                      'ws2_32.dll:recv', 'winhttp.dll:WinHttpConnect'))
    return dict(passed=True, recipe=47, owned_profile=run['profile'],
                verifier_sha256=sha(OUT / 'verification.json'),
                rea_bundle_sha256=sha(TRACE / 'rea-evidence.json'),
                helper_sha256=sha(helper), installed_assembly_sha256=expected,
                watched_file_operations=len(files), helper_origin_reads=len(reads),
                selected_sdk_entry_counts=data['sdkCounts'],
                authored_files_retained=2, original_quit=True,
                real_queue_or_whole_wire_qualified=False, native_ads_provider_resolved=False)


if __name__ == '__main__':
    result = review()
    (OUT / 'review523.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=result['passed'], file_operations=result['watched_file_operations'],
                          helper_reads=result['helper_origin_reads'])))
