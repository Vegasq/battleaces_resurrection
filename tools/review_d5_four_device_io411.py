"""Review four owned public2 clients' native bridge device-I/O codes."""
from __future__ import annotations

import json

from tools.frida_attribution_source import API
from tools.frida_device_io410 import build_source
from tools.review_d5_connected_pair338 import ROOT, sha
from tools.review_d5_exit_network368 import payloads, records_for
from tools.review_d5_four_human_workers392 import review as review_python
from tools.review_d5_device_io410 import BRIDGE_CODES

CASE = ROOT / 'local/privacy411-device-io-four01'
TRACE = ROOT / 'local/privacy411-device-io-four-trace01'
GAME = ROOT / 'local/privacy301-runtime01/game'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def review() -> dict:
    python = review_python(CASE)
    report, sessions, bundle = (read(CASE / 'verification.json'),
                                read(TRACE / 'sessions.json'),
                                read(TRACE / 'rea-evidence.json'))
    assert python['passed'] and report['passed'] and report['prelaunch_observer']
    assert report['forced_cleanup'] is False and report['mode'] == 2 and report['humans'] == 4
    assert sessions['case'] == 'local/' + CASE.name
    assert [row['index'] for row in sessions['clients']] == list(range(4))
    assert len({row['pid'] for row in sessions['clients']}) == 4
    assert len({row['session_id'] for row in sessions['clients']}) == 4
    required = {f'{module}:{name}' for module, names in API.items()
                for name in names if module in ('ntdll.dll', 'ws2_32.dll',
                                                 'kernelbase.dll', 'advapi32.dll', 'winhttp.dll')}
    clients = []
    for row in sessions['clients']:
        index, pid, sid = row['index'], row['pid'], row['session_id']
        folder, observer = CASE / f'client-{index}', TRACE / f'observer-{index}.js'
        process, config = read(folder / 'game-process.json'), read(TRACE / f'config-{index}.json')
        gate = folder / 'observer-ready'
        assert process['pid'] == pid and process['suspended_for_observer'] is True
        assert gate.read_bytes() == b'FRIDA_READY\n'
        assert (folder / 'game-process.json').stat().st_mtime_ns < gate.stat().st_mtime_ns
        assert report['prelaunch_resume'][index]['pid'] == pid
        assert report['prelaunch_resume'][index]['tick'] >= process['launch_tick']
        bridge_args = [arg for arg in process['actual_arguments']
                       if arg.startswith('-secure-transport-socket=')]
        assert len(bridge_args) == 1
        bridge = hex(int(bridge_args[0].split('=', 1)[1]))
        assert config['device_io'] is True and config['unresolved_file_status'] is True
        assert config['game_sha256'] == sha(GAME / 'Battle Aces.exe')
        assert config['source_sha256'] == sha(observer)
        assert observer.read_text(encoding='utf-8') == build_source(config['config'])
        loads = records_for(bundle, sid, 'load_frida_script')
        finals = [item for item in records_for(bundle, sid, 'frida_session_status')
                  if item['normalized_result'].get('state') == 'detached']
        assert len(loads) == len(finals) == 1
        assert loads[0]['normalized_result']['source_sha256'] == sha(observer)
        assert finals[0]['normalized_result']['pid'] == pid
        early, messages = payloads(loads[0]), payloads(finals[0])
        assert messages[:len(early)] == early
        assert [item['kind'] for item in early[-3:]] == [
            'device-io-armed', 'observer-ready', 'exit-boundary-armed']
        assert early[-3]['data'] == dict(api='ntdll.dll:NtDeviceIoControlFile')
        assert early[-2]['data']['errors'] == []
        assert required <= {item['key'] for item in early[-2]['data']['installed']}
        assert all(item['pid'] == pid and item['runId'] == config['config']['runId']
                   for item in messages)
        assert not finals[0]['normalized_result']['messages_truncated']
        assert messages[-1]['kind'] == 'self-terminate-entry'
        assert sum(item['kind'] == 'self-terminate-entry' for item in messages) == 1
        assert not any(item['kind'] in ('self-terminate-returned', 'decode-error',
            'budget-exceeded', 'file-operation', 'network-operation', 'process-create')
            for item in messages)
        boundary = messages[-1]['data']
        assert boundary['exitStatus'] == 0 and boundary['errors'] == []
        assert boundary['overflow'] is False and boundary['unknownRelativeRoots'] == 0
        assert boundary['rootResolveFailed'] == 0
        counts = boundary['counts']
        for name in ('send', 'recv'):
            count = counts['ws2_32.dll:' + name]
            assert count > 0 and boundary['socketHandles'][name] == {bridge: count}
        assert all(counts[f'ws2_32.dll:{name}'] == 0 for name in
                   ('connect', 'WSAConnect', 'sendto', 'WSASendTo',
                    'getaddrinfo', 'GetAddrInfoW', 'GetAddrInfoExW'))
        assert counts['winhttp.dll:WinHttpConnect'] == 0
        device = boundary['deviceIo']
        assert device['errors'] == [] and device['overflow'] is False
        codes = device['codes']
        assert len(codes) == 25 and device['calls'] == sum(item['calls'] for item in codes.values())
        assert {code for code in codes if code.startswith('0x120')} == BRIDGE_CODES
        for code, item in codes.items():
            assert item['calls'] == item['success'] + item['pending'] + item['failure']
            if code in BRIDGE_CODES:
                assert item['uniqueHandles'] == 1 and item['firstHandles'] == [bridge]
                assert item['pending'] == 0
                if code != '0x12017':
                    assert item['failure'] == 0
        assert codes['0x1201f']['calls'] == counts['ws2_32.dll:send']
        assert codes['0x12017']['calls'] == counts['ws2_32.dll:recv']
        assert all(codes[code]['calls'] == 1 for code in BRIDGE_CODES - {'0x1201f', '0x12017'})
        clients.append(dict(index=index, pid=pid, bridge_handle=bridge,
                            device_io_calls=device['calls'], control_codes=len(codes),
                            selected_send=codes['0x1201f']['calls'],
                            selected_recv=codes['0x12017']['calls'],
                            load_evidence_id=loads[0]['evidence_id'],
                            final_evidence_id=finals[0]['evidence_id']))
    return dict(passed=True, clients=clients,
                verification_sha256=sha(CASE / 'verification.json'),
                bundle_sha256=sha(TRACE / 'rea-evidence.json'),
                scope='Current private four-human public2: all observed 0x120xx NtDeviceIoControlFile codes on each inherited bridge handle; selected send/recv counts match Winsock; other APIs/kernel/wire/queue/final release remain open',
                full_d5_qualified=False)


if __name__ == '__main__':
    result = review()
    output = CASE / 'device-io-review.json'
    if output.exists():
        assert read(output) == result
    else:
        output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, clients=result['clients'])))
