"""Review four-human packaged Python journals and native bridge sockets."""
from __future__ import annotations

import json
from pathlib import Path

from tools.frida_attribution_source import API
from tools.frida_prelaunch_socket_exit370 import build_source
from tools.review_d5_connected_pair338 import ROOT, sha
from tools.review_d5_exit_network368 import payloads, records_for
from tools.review_d5_four_human_workers392 import review as review_python

CASE = ROOT / 'local/privacy394-four-human-native01'
TRACE = ROOT / 'local/privacy394-four-human-native-trace01'
GAME = ROOT / 'local/privacy301-runtime01/game'


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def review() -> dict:
    python = review_python(CASE)
    report, sessions, bundle = (read(CASE / 'verification.json'),
                                read(TRACE / 'sessions.json'),
                                read(TRACE / 'rea-evidence.json'))
    assert python['passed'] and report['prelaunch_observer'] is True
    assert report['passed'] and report['forced_cleanup'] is False
    assert sessions['case'] == 'local/' + CASE.name
    assert [row['index'] for row in sessions['clients']] == list(range(4))
    assert len({row['pid'] for row in sessions['clients']}) == 4
    assert len({row['session_id'] for row in sessions['clients']}) == 4
    assert len(report['prelaunch_resume']) == 4
    required = {f'{module}:{name}' for module, names in API.items()
                for name in names if module in ('ntdll.dll', 'ws2_32.dll',
                                                 'kernelbase.dll', 'advapi32.dll', 'winhttp.dll')}
    clients = []
    for row in sessions['clients']:
        index, pid, sid = row['index'], row['pid'], row['session_id']
        folder = CASE / f'client-{index}'
        process_path = folder / 'game-process.json'
        process, config = read(process_path), read(TRACE / f'config-{index}.json')
        gate, observer = folder / 'observer-ready', TRACE / f'observer-{index}.js'
        assert process['pid'] == pid and process['suspended_for_observer'] is True
        assert gate.read_bytes() == b'FRIDA_READY\n'
        assert process_path.stat().st_mtime_ns < gate.stat().st_mtime_ns
        assert report['prelaunch_resume'][index]['pid'] == pid
        assert report['prelaunch_resume'][index]['tick'] >= process['launch_tick']
        bridge_args = [arg for arg in process['actual_arguments']
                       if arg.startswith('-secure-transport-socket=')]
        assert len(bridge_args) == 1
        bridge = int(bridge_args[0].split('=', 1)[1])
        assert 0 < bridge < 2**32
        handle = hex(bridge)
        assert config['exit_boundary'] is True and config['socket_handles'] is True
        assert config['game_sha256'] == sha(GAME / 'Battle Aces.exe')
        assert config['source_sha256'] == sha(observer)
        assert config['config']['image'] == str((GAME / 'Battle Aces.exe').resolve())
        assert observer.read_text(encoding='utf-8') == build_source(config['config'])
        loads = records_for(bundle, sid, 'load_frida_script')
        finals = [item for item in records_for(bundle, sid, 'frida_session_status')
                  if item['normalized_result'].get('state') == 'detached']
        assert len(loads) == len(finals) == 1
        load, final = loads[0], finals[0]
        assert load['normalized_result']['source_sha256'] == sha(observer)
        assert final['normalized_result']['pid'] == pid
        early, messages = payloads(load), payloads(final)
        assert messages[:len(early)] == early
        assert [item['kind'] for item in early[-2:]] == ['observer-ready', 'exit-boundary-armed']
        assert early[-2]['data']['errors'] == []
        assert required <= {item['key'] for item in early[-2]['data']['installed']}
        assert all(item['pid'] == pid and item['runId'] == config['config']['runId']
                   for item in messages)
        assert messages[-1]['kind'] == 'self-terminate-entry'
        assert sum(item['kind'] == 'self-terminate-entry' for item in messages) == 1
        assert not any(item['kind'] in ('self-terminate-returned', 'decode-error',
                                        'budget-exceeded', 'network-operation',
                                        'file-operation', 'process-create') for item in messages)
        heartbeats = [item['data'] for item in messages if item['kind'] == 'heartbeat']
        assert len(heartbeats) >= 10
        boundary = messages[-1]['data']
        assert boundary['api'].endswith(':TerminateProcess')
        assert boundary['exitStatus'] == 0 and boundary['transportHoldMs'] == 200
        assert boundary['errors'] == [] and boundary['overflow'] is False
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
        clients.append(dict(index=index, pid=pid, bridge_handle=bridge,
                            send=counts['ws2_32.dll:send'], recv=counts['ws2_32.dll:recv'],
                            unknown_relative_roots=boundary['unknownRelativeRoots'],
                            messages=len(messages), heartbeats=len(heartbeats),
                            load_evidence_id=load['evidence_id'],
                            final_evidence_id=final['evidence_id'],
                            observer_sha256=sha(observer)))
    result = dict(passed=True, scope='One current private public2 four-human match: selected native client socket APIs from pre-resume to self-exit entry and seven packaged Python endpoint journals; not whole wire or queue proof',
                  frames=python['frames'], clients=clients,
                  python_review_sha256=sha(CASE / 'review392.json'),
                  verification_sha256=sha(CASE / 'verification.json'),
                  bundle_sha256=sha(TRACE / 'rea-evidence.json'),
                  full_d5_qualified=False)
    (CASE / 'review394.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps({key: value for key, value in result.items() if key != 'clients'}, sort_keys=True))
