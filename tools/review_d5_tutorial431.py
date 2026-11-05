"""Review the current recipe38 Tutorial01 mission and selected privacy route."""
from __future__ import annotations

import json

from tools.frida_unresolved_file_status373 import build_source
from tools.review_d5_connected_pair338 import ROOT, sha
from tools.review_d5_exit_network368 import payloads, read, records_for

CASE = ROOT / 'local/privacy431-tutorial02'
TRACE = ROOT / 'local/privacy431-tutorial-trace02'
GAME = ROOT / 'local/privacy301-runtime01/game'
NETWORK_ZERO = ('connect', 'WSAConnect', 'send', 'recv', 'sendto',
                'WSASendTo', 'getaddrinfo', 'GetAddrInfoW', 'GetAddrInfoExW')


def review() -> dict:
    report = read(CASE / 'verification.json')
    assert report['passed'] and report['recipe'] == 38
    assert report['through_mission'] and report['window_close']
    assert report['prelaunch_observer'] and report['tutorial_entry']
    assert report['mission_started'] and report['original_objective_entered']
    assert report['window_close_exit_zero'] and report['entry_audit']['passed']
    assert report['entry_audit']['observed_stages'] == [
        'startup-after-engine-init', 'tutorial', 'tutorial']
    assert report['components_before'] == report['components_after']
    assert report['shared_before'] == report['shared_after']
    assert report['source_before'] == report['source_after']
    assert report['launch']['owned_process_reaped']
    assert report['launch']['exit_code'] == 0
    assert report['launch']['forced_cleanup'] is False
    assert report['launch']['job_final'] == dict(
        total_processes=1, active_processes=0, total_terminated_processes=0)
    assert report['command'][0] == str(GAME / 'Battle Aces.exe')
    assert '-offline-tutorial' in report['command']
    assert '-local-profile=' + report['profile'] in report['command']
    process = read(CASE / 'game-process.json')
    gate = CASE / 'observer-ready'
    assert process['pid'] == report['pid']
    assert process['actual_arguments'] == report['command']
    assert process['suspended_for_observer'] is True
    assert gate.read_bytes() == b'FRIDA_READY' + bytes([10])
    assert (CASE / 'game-process.json').stat().st_mtime_ns < gate.stat().st_mtime_ns
    sessions, bundle = read(TRACE / 'sessions.json'), read(TRACE / 'rea-evidence.json')
    assert sessions['case'] == 'local/' + CASE.name
    assert len(sessions['clients']) == 1
    session = sessions['clients'][0]
    assert session['index'] == 0 and session['pid'] == report['pid']
    sid = session['session_id']
    config = read(TRACE / 'config-0.json')
    observer = TRACE / 'observer-0.js'
    assert config['exit_boundary'] and config['socket_handles']
    assert config['resolve_roots'] and config['resolve_existing_files']
    assert config['unresolved_file_status']
    assert config['game_sha256'] == sha(GAME / 'Battle Aces.exe')
    assert config['source_sha256'] == sha(observer)
    assert observer.read_text(encoding='utf-8') == build_source(config['config'])
    loads = records_for(bundle, sid, 'load_frida_script')
    finals = [row for row in records_for(bundle, sid, 'frida_session_status')
              if row['normalized_result'].get('state') == 'detached']
    assert len(loads) == len(finals) == 1
    load, final = loads[0], finals[0]
    assert load['normalized_result']['source_sha256'] == sha(observer)
    early, messages = payloads(load), payloads(final)
    assert messages[:len(early)] == early
    assert [row['kind'] for row in early[-2:]] == [
        'observer-ready', 'exit-boundary-armed']
    assert early[-2]['data']['errors'] == []
    assert all(row['pid'] == report['pid'] and
               row['runId'] == config['config']['runId'] for row in messages)
    assert messages[-1]['kind'] == 'self-terminate-entry'
    assert sum(row['kind'] == 'self-terminate-entry' for row in messages) == 1
    assert not any(row['kind'] in ('self-terminate-returned', 'decode-error',
                                   'budget-exceeded', 'network-operation',
                                   'process-create', 'file-operation') for row in messages)
    boundary = messages[-1]['data']
    assert boundary['exitStatus'] == 0 and boundary['transportHoldMs'] == 200
    assert boundary['errors'] == [] and boundary['overflow'] is False
    assert boundary['unknownRelativeRoots'] == 0
    assert boundary['rootResolveCalls'] > 0 and boundary['rootResolveFailed'] == 0
    assert all(boundary['counts']['ws2_32.dll:' + key] == 0 for key in NETWORK_ZERO)
    assert boundary['counts']['winhttp.dll:WinHttpConnect'] == 0
    unresolved = [row['data'] for row in messages
                  if row['kind'] == 'unresolved-file-operation']
    assert len(unresolved) == boundary['unresolvedFileOps'] == 9
    assert all(row == dict(api='ntdll.dll:NtWriteFile', fileType=0,
                           handle='0xffffffffffffffff', operation='NtWriteFile',
                           returnValue=-1073741816) for row in unresolved)
    return dict(passed=True, pid=report['pid'], profile=report['profile'],
                selected_network_calls=0, selected_sdk_root_file_operations=0,
                failed_invalid_handle_writes=len(unresolved),
                verification_sha256=sha(CASE / 'verification.json'),
                bundle_sha256=sha(TRACE / 'rea-evidence.json'),
                load_evidence_id=load['evidence_id'],
                final_evidence_id=final['evidence_id'],
                scope='Current recipe38 Tutorial01 first objective and owned WM_CLOSE with selected native file/network API observation from suspended start to first self-termination entry; objective completion, in-game Quit, other APIs/roots, queue and whole wire remain open',
                full_d5_qualified=False)


if __name__ == '__main__':
    result = review()
    output = CASE / 'tutorial-review.json'
    if output.exists():
        assert read(output) == result
    else:
        output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
