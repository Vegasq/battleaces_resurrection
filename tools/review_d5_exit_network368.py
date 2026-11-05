"""Review the owned prelaunch-to-self-termination selected API observation."""
from __future__ import annotations

import json
from pathlib import Path

from tools.frida_attribution_source import API
from tools.review_d5_connected_network341 import review as network_review
from tools.review_d5_connected_pair338 import ROOT, sha

CASE = ROOT / 'local/privacy368-connected01'
TRACE = ROOT / 'local/privacy368-prelaunch-exit-trace01'
CONTROL = ROOT / 'local/privacy367-exit-control01'
PACKAGES = ROOT / 'local/privacy358-packages02'
GAME = ROOT / 'local/privacy301-runtime01/game'
ASSETS = ROOT / 'local/s139/assets/build-37822'


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def records_for(bundle: dict, session: str, operation: str) -> list[dict]:
    return [row for row in bundle['records'] if row['operation'] == operation
            and row.get('parameters', {}).get('session_id') == session]


def payloads(record: dict) -> list[dict]:
    assert record['normalized_result']['messages_truncated'] is False
    messages = record['normalized_result']['messages']
    assert all(row['type'] == 'send' for row in messages)
    result = [row['payload'] for row in messages]
    assert [row['seq'] for row in result] == list(range(1, len(result) + 1))
    return result


def review() -> dict:
    prior = network_review(CASE, TRACE, PACKAGES, GAME, ASSETS)
    assert prior['passed']
    verification = read(CASE / 'verification.json')
    assert verification['passed'] and verification['prelaunch_observer'] is True
    assert verification['forced_cleanup'] is False
    assert verification['source_files_unchanged'] and verification['package_files_unchanged']
    assert all(row['driver_report']['game_exit_code'] == 0 and
               row['driver_report']['launcher_exit_code'] == 0
               for row in verification['clients'])
    assert all(row['reaped'] and row['exit_code'] == 0 for row in verification['worker_cleanup'])
    assert all(row['active_processes'] == row['total_terminated_processes'] == 0
               for row in verification['jobs'])

    control_session = read(CONTROL / 'session.json')
    control_request = read(CONTROL / 'request.json')
    control_bundle = read(CONTROL / 'rea-evidence.json')
    control_loads = records_for(control_bundle, control_session['session_id'], 'load_frida_script')
    control_finals = [row for row in records_for(control_bundle, control_session['session_id'],
                                                'frida_session_status')
                      if row['normalized_result'].get('state') == 'detached']
    assert len(control_loads) == len(control_finals) == 1
    control_load, control_final = control_loads[0], control_finals[0]
    assert control_load['evidence_id'] == control_session['load_evidence_id']
    assert control_final['evidence_id'] == control_session['final_evidence_id']
    assert control_load['normalized_result']['source_sha256'] == sha(CONTROL / 'observer.js') == control_request['source_sha256']
    control_messages = payloads(control_final)
    assert control_messages[-1]['kind'] == 'self-terminate-entry'
    assert control_messages[-1]['data']['exitStatus'] == 0
    assert control_messages[-1]['data']['api'].endswith(':TerminateProcess')
    assert control_messages[-1]['data']['errors'] == []
    assert control_messages[-1]['data']['overflow'] is False
    assert sum(row['kind'] == 'self-terminate-entry' for row in control_messages) == 1
    assert sum(row['kind'] == 'exit-boundary-armed' for row in control_messages) == 1
    assert not any(row['kind'] == 'self-terminate-returned' for row in control_messages)

    sessions = read(TRACE / 'sessions.json')
    bundle = read(TRACE / 'rea-evidence.json')
    assert sessions['case'] == 'local/' + CASE.name
    assert [row['index'] for row in sessions['clients']] == [0, 1]
    clients = []
    for row in sessions['clients']:
        index, pid, session = row['index'], row['pid'], row['session_id']
        process_path = CASE / f'client-{index}/game-process.json'
        process = read(process_path)
        gate = CASE / f'client-{index}/observer-ready'
        assert process['pid'] == pid and process['suspended_for_observer'] is True
        assert gate.read_bytes() == b'FRIDA_READY\n'
        assert process_path.stat().st_mtime_ns < gate.stat().st_mtime_ns
        assert verification['prelaunch_resume'][index]['pid'] == pid
        assert verification['prelaunch_resume'][index]['tick'] >= process['launch_tick']
        config = read(TRACE / f'config-{index}.json')
        observer = TRACE / f'observer-{index}.js'
        assert config['exit_boundary'] is True
        assert config['source_sha256'] == sha(observer)
        assert config['game_sha256'] == sha(GAME / 'Battle Aces.exe')
        assert config['config']['image'] == str((GAME / 'Battle Aces.exe').resolve())
        loads = records_for(bundle, session, 'load_frida_script')
        finals = [item for item in records_for(bundle, session, 'frida_session_status')
                  if item['normalized_result'].get('state') == 'detached']
        assert len(loads) == len(finals) == 1
        load, final = loads[0], finals[0]
        assert load['normalized_result']['source_sha256'] == sha(observer)
        early, messages = payloads(load), payloads(final)
        assert messages[:len(early)] == early
        assert [item['kind'] for item in early[-2:]] == ['observer-ready', 'exit-boundary-armed']
        assert all(item['pid'] == pid and item['runId'] == config['config']['runId']
                   for item in messages)
        installed = {item['key'] for item in early[-2]['data']['installed']}
        required = {f'{module}:{name}' for module, names in API.items()
                    for name in names if module in ('ntdll.dll', 'ws2_32.dll',
                                                     'kernelbase.dll', 'advapi32.dll', 'winhttp.dll')}
        assert required <= installed and early[-2]['data']['errors'] == []
        assert messages[-1]['kind'] == 'self-terminate-entry'
        assert sum(item['kind'] == 'self-terminate-entry' for item in messages) == 1
        assert not any(item['kind'] in ('self-terminate-returned', 'decode-error',
                                        'budget-exceeded', 'file-operation',
                                        'process-create', 'network-operation') for item in messages)
        heartbeats = [item for item in messages if item['kind'] == 'heartbeat']
        assert len(heartbeats) >= 10
        last, boundary = heartbeats[-1]['data'], messages[-1]['data']
        assert boundary['api'].endswith(':TerminateProcess')
        assert boundary['exitStatus'] == 0 and boundary['transportHoldMs'] == 200
        assert boundary['errors'] == [] and boundary['overflow'] is False
        assert boundary['unknownRelativeRoots'] >= 0
        assert all(boundary['counts'][key] >= value for key, value in last['counts'].items())
        counts = boundary['counts']
        assert counts['ws2_32.dll:send'] > 0 and counts['ws2_32.dll:recv'] > 0
        assert all(counts[f'ws2_32.dll:{name}'] == 0 for name in
                   ('connect', 'WSAConnect', 'sendto', 'WSASendTo',
                    'getaddrinfo', 'GetAddrInfoW', 'GetAddrInfoExW'))
        assert counts['winhttp.dll:WinHttpConnect'] == 0
        clients.append(dict(index=index, pid=pid, session_id=session,
                            load_evidence_id=load['evidence_id'],
                            final_evidence_id=final['evidence_id'],
                            source_sha256=sha(observer), messages=len(messages),
                            heartbeats=len(heartbeats), send=counts['ws2_32.dll:send'],
                            recv=counts['ws2_32.dll:recv'],
                            unknown_relative_roots=boundary['unknownRelativeRoots']))
    return dict(passed=True, scope='Selected native client API entries from before main-thread resume through original self-TerminateProcess entry; 200ms exit transport hold and other threads remain outside a complete exit claim',
                control_load_evidence_id=control_load['evidence_id'],
                control_final_evidence_id=control_final['evidence_id'],
                control_bundle_sha256=sha(CONTROL / 'rea-evidence.json'),
                game_bundle_sha256=sha(TRACE / 'rea-evidence.json'),
                verification_sha256=sha(CASE / 'verification.json'),
                network_review_sha256=sha(CASE / 'network-review.json'),
                clients=clients, full_d5_qualified=False)


if __name__ == '__main__':
    result = review()
    output = CASE / 'exit-review.json'
    if output.exists():
        assert read(output) == result
    else:
        output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'clients': result['clients']}))
