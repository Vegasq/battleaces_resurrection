"""Review selected native socket handles from pre-resume to self-exit entry."""
from __future__ import annotations

import json
from pathlib import Path

from tools.frida_prelaunch_socket_exit370 import build_source
from tools.review_d5_connected_network341 import review as network_review
from tools.review_d5_connected_pair338 import ROOT, sha
from tools.review_d5_exit_network368 import read, records_for, payloads

CASE = ROOT / 'local/privacy370-connected01'
TRACE = ROOT / 'local/privacy370-prelaunch-socket-trace01'
PACKAGES = ROOT / 'local/privacy358-packages02'
GAME = ROOT / 'local/privacy301-runtime01/game'
ASSETS = ROOT / 'local/s139/assets/build-37822'


def verify(CASE: Path = CASE, TRACE: Path = TRACE,
           source_builder=build_source, resolve_roots: bool = False) -> dict:
    network = network_review(CASE, TRACE, PACKAGES, GAME, ASSETS)
    assert network['passed']
    report, sessions, bundle = (read(CASE / 'verification.json'),
                                read(TRACE / 'sessions.json'),
                                read(TRACE / 'rea-evidence.json'))
    assert report['passed'] and report['prelaunch_observer'] is True
    assert report['forced_cleanup'] is False
    assert report['source_files_unchanged'] and report['package_files_unchanged']
    assert all(row['driver_report']['game_exit_code'] == 0 and
               row['driver_report']['launcher_exit_code'] == 0 for row in report['clients'])
    assert all(row['reaped'] and row['exit_code'] == 0 for row in report['worker_cleanup'])
    assert all(row['active_processes'] == row['total_terminated_processes'] == 0
               for row in report['jobs'])
    assert sessions['case'] == 'local/' + CASE.name
    assert [row['index'] for row in sessions['clients']] == [0, 1]
    clients = []
    for row in sessions['clients']:
        index, pid, session = row['index'], row['pid'], row['session_id']
        client = CASE / f'client-{index}'
        process_path = client / 'game-process.json'
        process = read(process_path)
        gate = client / 'observer-ready'
        assert process['pid'] == pid and process['suspended_for_observer'] is True
        assert gate.read_bytes() == b'FRIDA_READY\n'
        assert process_path.stat().st_mtime_ns < gate.stat().st_mtime_ns
        assert report['prelaunch_resume'][index]['pid'] == pid
        assert report['prelaunch_resume'][index]['tick'] >= process['launch_tick']
        bridge_args = [value for value in process['actual_arguments']
                       if value.startswith('-secure-transport-socket=')]
        assert len(bridge_args) == 1
        bridge = int(bridge_args[0].split('=', 1)[1])
        assert 0 < bridge < 2**32
        handle = hex(bridge)
        config = read(TRACE / f'config-{index}.json')
        assert config['exit_boundary'] is True and config['socket_handles'] is True
        if resolve_roots:
            assert config['resolve_roots'] is True
        assert config['game_sha256'] == sha(GAME / 'Battle Aces.exe')
        observer = TRACE / f'observer-{index}.js'
        assert observer.read_text(encoding='utf-8') == source_builder(config['config'])
        assert config['source_sha256'] == sha(observer)
        loads = records_for(bundle, session, 'load_frida_script')
        finals = [item for item in records_for(bundle, session, 'frida_session_status')
                  if item['normalized_result'].get('state') == 'detached']
        assert len(loads) == len(finals) == 1
        load, final = loads[0], finals[0]
        assert load['normalized_result']['source_sha256'] == sha(observer)
        early, messages = payloads(load), payloads(final)
        assert messages[:len(early)] == early
        assert [item['kind'] for item in early[-2:]] == ['observer-ready', 'exit-boundary-armed']
        assert early[-2]['data']['errors'] == []
        assert all(item['pid'] == pid and item['runId'] == config['config']['runId']
                   for item in messages)
        assert messages[-1]['kind'] == 'self-terminate-entry'
        assert sum(item['kind'] == 'self-terminate-entry' for item in messages) == 1
        assert not any(item['kind'] in ('self-terminate-returned', 'decode-error',
                                        'budget-exceeded', 'file-operation',
                                        'process-create', 'network-operation') for item in messages)
        heartbeats = [item['data'] for item in messages if item['kind'] == 'heartbeat']
        assert len(heartbeats) >= 10
        boundary = messages[-1]['data']
        assert boundary['api'].endswith(':TerminateProcess')
        assert boundary['exitStatus'] == 0 and boundary['transportHoldMs'] == 200
        assert boundary['errors'] == [] and boundary['overflow'] is False
        if resolve_roots:
            assert boundary['unknownRelativeRoots'] == 0
            assert boundary['rootResolveCalls'] > 0
            assert boundary['rootResolveFailed'] == 0
            assert all(snapshot['unknownRelativeRoots'] == 0 and
                       snapshot['rootResolveFailed'] == 0 for snapshot in heartbeats)
        for snapshot in (*heartbeats, boundary):
            for name in ('send', 'recv'):
                count = snapshot['counts']['ws2_32.dll:' + name]
                assert snapshot['socketHandles'][name] == ({handle: count} if count else {})
        counts = boundary['counts']
        assert counts['ws2_32.dll:send'] > 0 and counts['ws2_32.dll:recv'] > 0
        assert all(counts[f'ws2_32.dll:{name}'] == 0 for name in
                   ('connect', 'WSAConnect', 'sendto', 'WSASendTo',
                    'getaddrinfo', 'GetAddrInfoW', 'GetAddrInfoExW'))
        assert counts['winhttp.dll:WinHttpConnect'] == 0
        assert all(counts[key] >= value for key, value in heartbeats[-1]['counts'].items())
        client_result = dict(index=index, pid=pid, session_id=session,
                             bridge_handle=bridge, send=counts['ws2_32.dll:send'],
                             recv=counts['ws2_32.dll:recv'],
                             unknown_relative_roots=boundary['unknownRelativeRoots'],
                             load_evidence_id=load['evidence_id'],
                             final_evidence_id=final['evidence_id'],
                             observer_sha256=sha(observer))
        if resolve_roots:
            client_result.update(root_resolve_calls=boundary['rootResolveCalls'],
                                 root_resolve_failed=boundary['rootResolveFailed'])
        clients.append(client_result)
    return dict(passed=True, scope='Selected native socket send/recv calls on each inherited private bridge handle from pre-main-thread-resume to self-TerminateProcess entry; no whole wire or file/queue claim',
                clients=clients, verification_sha256=sha(CASE / 'verification.json'),
                bundle_sha256=sha(TRACE / 'rea-evidence.json'),
                full_d5_qualified=False)


if __name__ == '__main__':
    result = verify()
    output = CASE / 'socket-exit-review.json'
    if output.exists():
        assert read(output) == result
    else:
        output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
