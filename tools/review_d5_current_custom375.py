"""Bind a current private Custom rematch to its prelaunch native observation."""
from __future__ import annotations

import json

from client_patch.patcher.telemetry import RECIPE_VERSION, RUNTIME_VALIDATED
from tools.frida_unresolved_file_status373 import build_source
from tools.package_integrity import verify
from tools.review_d5_connected_pair338 import ROOT, sha
from tools.review_d5_exit_network368 import payloads, read, records_for

CASE = ROOT / 'local/privacy375-custom01'
TRACE = ROOT / 'local/privacy375-custom-trace01'
PACKAGES = ROOT / 'local/privacy358-packages02'
GAME = ROOT / 'local/privacy301-runtime01/game'
ASSETS = ROOT / 'local/s139/assets/build-37822'


def review() -> dict:
    report = read(CASE / 'verification.json')
    manifest = read(GAME / '.battleaces-resurrection/patch-manifest.json')
    build = read(PACKAGES / 'build-report.json')
    assert report['passed'] and report['custom_rematch'] and report['prelaunch_observer']
    assert report['rc_open'] and report['mode'] == 1 and report['humans'] == 2
    assert report['forced_cleanup'] is False and report['packages'] == str(PACKAGES)
    assert report['assets_manifest_sha256'] == sha(ASSETS / 'asset-manifest.json')
    assert manifest['telemetry']['recipe_version'] == RECIPE_VERSION == 38
    assert manifest['telemetry']['runtime_validated'] is RUNTIME_VALIDATED is False
    assert sha(GAME / 'GameAssembly.dll') == manifest['patched_sha256']
    assert sha(GAME / 'BattleAcesOffline.dll') == manifest['helper_sha256']
    assert report['helper_build']['receipt']['helper_sha256'] == manifest['helper_sha256']
    assert sha(PACKAGES / 'battleaces-client-win64/program/client-helper/BattleAcesOffline.dll') == manifest['helper_sha256']
    for kind in ('client', 'server'):
        assert verify(PACKAGES / f'battleaces-{kind}-win64', kind)
        entry = build['packages'][kind]
        assert sha(PACKAGES / entry['archive']) == entry['sha256']
    for key in ('source_files_unchanged', 'shared_channels_unchanged',
                'adapters_unchanged', 'config_unchanged', 'package_files_unchanged',
                'assets_unchanged', 'fixture_tokens_not_logged', 'temporary_pki_removed'):
        assert report[key] is True, key
    custom = report['custom']
    assert len(custom['matches']) == len(custom['worker_pids']) == 2
    assert custom['epochs'] == [1, 2] and custom['native_leave_order'] == ['guest', 'host']
    assert len(report['server']['frozen_matches']) == 2
    assert [job['total_processes'] for job in report['jobs']] == [7, 2, 2]
    assert all(job['active_processes'] == job['total_terminated_processes'] == 0
               for job in report['jobs'])
    assert all(row['reaped'] and row['exit_code'] == 0 for row in report['worker_cleanup'])
    assert all(row['driver_report']['game_exit_code'] == 0 and
               row['driver_report']['launcher_exit_code'] == 0 for row in report['clients'])
    assert report['server']['listener_closed'] and report['server']['state_lock_released']
    assert report['server']['final_state']['lobbies'] == []

    sessions, bundle = read(TRACE / 'sessions.json'), read(TRACE / 'rea-evidence.json')
    clients = []
    for index in range(2):
        session = sessions[f'client{index}']
        pid, sid = session['pid'], session['session_id']
        process = read(CASE / f'client-{index}/game-process.json')
        gate = CASE / f'client-{index}/observer-ready'
        assert process['pid'] == pid == report['clients'][index]['pid']
        assert process['suspended_for_observer'] is True
        assert gate.read_bytes() == b'FRIDA_READY\n'
        assert (CASE / f'client-{index}/game-process.json').stat().st_mtime_ns < gate.stat().st_mtime_ns
        assert report['prelaunch_resume'][index]['pid'] == pid
        bridge_args = [arg for arg in process['actual_arguments']
                       if arg.startswith('-secure-transport-socket=')]
        assert len(bridge_args) == 1
        bridge = hex(int(bridge_args[0].split('=', 1)[1]))
        config = read(TRACE / f'config-{index}.json')
        observer = TRACE / f'observer-{index}.js'
        assert all(config[key] is True for key in ('exit_boundary', 'socket_handles',
                    'resolve_roots', 'resolve_existing_files', 'unresolved_file_status'))
        assert config['game_sha256'] == sha(GAME / 'Battle Aces.exe')
        assert observer.read_text(encoding='utf-8') == build_source(config['config'])
        assert config['source_sha256'] == sha(observer)
        loads = records_for(bundle, sid, 'load_frida_script')
        finals = [row for row in records_for(bundle, sid, 'frida_session_status')
                  if row['normalized_result'].get('state') == 'detached']
        assert len(loads) == len(finals) == 1
        load, final = loads[0], finals[0]
        assert load['normalized_result']['script_id'] == session['script_id']
        assert load['normalized_result']['source_sha256'] == sha(observer)
        early, events = payloads(load), payloads(final)
        assert events[:len(early)] == early
        assert [row['kind'] for row in early[-2:]] == ['observer-ready', 'exit-boundary-armed']
        assert early[-2]['data']['errors'] == []
        assert all(row['pid'] == pid and row['runId'] == config['config']['runId'] for row in events)
        assert not any(row['kind'] in ('decode-error', 'budget-exceeded', 'file-operation',
                       'process-create', 'network-operation') for row in events)
        assert events[-1]['kind'] == 'self-terminate-entry'
        boundary = events[-1]['data']
        assert boundary['exitStatus'] == 0 and boundary['api'].endswith(':TerminateProcess')
        assert boundary['errors'] == [] and boundary['overflow'] is False
        assert boundary['unknownRelativeRoots'] == boundary['rootResolveFailed'] == 0
        assert boundary['rootResolveCalls'] > 0
        assert boundary['socketHandles']['send'] == {bridge: boundary['counts']['ws2_32.dll:send']}
        assert boundary['socketHandles']['recv'] == {bridge: boundary['counts']['ws2_32.dll:recv']}
        assert all(boundary['counts'][f'ws2_32.dll:{name}'] == 0 for name in
                   ('connect', 'WSAConnect', 'sendto', 'WSASendTo',
                    'getaddrinfo', 'GetAddrInfoW', 'GetAddrInfoExW'))
        assert boundary['counts']['winhttp.dll:WinHttpConnect'] == 0
        unresolved = [row['data'] for row in events if row['kind'] == 'unresolved-file-operation']
        assert len(unresolved) == boundary['unresolvedFileOps'] == 9
        assert all(row == dict(operation='NtWriteFile', handle='0xffffffffffffffff',
                               fileType=0, api='ntdll.dll:NtWriteFile',
                               returnValue=-1073741816) for row in unresolved)
        clients.append(dict(index=index, pid=pid, bridge=bridge,
                            send=boundary['counts']['ws2_32.dll:send'],
                            recv=boundary['counts']['ws2_32.dll:recv'],
                            failed_invalid_handle_writes=len(unresolved),
                            root_resolve_calls=boundary['rootResolveCalls'],
                            file_resolve_calls=boundary['fileResolveCalls'],
                            load_evidence_id=load['evidence_id'],
                            final_evidence_id=final['evidence_id']))
    return dict(passed=True, scope='Current recipe38 private Custom two-match selected native APIs from suspended prelaunch to self-termination entry; no full queue/wire/P9/final-installed claim',
                clients=clients, verification_sha256=sha(CASE / 'verification.json'),
                bundle_sha256=sha(TRACE / 'rea-evidence.json'), full_d5_qualified=False)


if __name__ == '__main__':
    result = review()
    output = CASE / 'custom-review.json'
    if output.exists():
        assert read(output) == result
    else:
        output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'clients': result['clients']}))
