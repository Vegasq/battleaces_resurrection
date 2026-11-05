"""Review selected native device-I/O codes against the private bridge sockets."""
from __future__ import annotations

import json

from tools.frida_device_io410 import build_source
from tools.review_d5_connected_pair338 import ROOT, sha
from tools.review_d5_exit_network368 import payloads, read, records_for
from tools.review_d5_socket_exit370 import verify as network_verify

CASE = ROOT / 'local/privacy410-device-io02'
TRACE = ROOT / 'local/privacy410-device-io-trace02'
BRIDGE_CODES = {'0x12043', '0x12037', '0x1203b', '0x120bf',
                '0x12047', '0x1201f', '0x12017'}


def review() -> dict:
    network = network_verify(CASE, TRACE, build_source, True)
    report, sessions, bundle = (read(CASE / 'verification.json'),
                                read(TRACE / 'sessions.json'),
                                read(TRACE / 'rea-evidence.json'))
    assert report['passed'] and report['forced_cleanup'] is False
    assert report['mode'] == 1 and report['humans'] == 2
    assert report['match']['frames'] >= 1200
    clients = []
    for row in sessions['clients']:
        index, pid, sid = row['index'], row['pid'], row['session_id']
        config = read(TRACE / f'config-{index}.json')
        assert config['device_io'] is True
        assert config['source_sha256'] == sha(TRACE / f'observer-{index}.js')
        process = read(CASE / f'client-{index}/game-process.json')
        bridge_args = [arg for arg in process['actual_arguments']
                       if arg.startswith('-secure-transport-socket=')]
        assert len(bridge_args) == 1
        bridge = hex(int(bridge_args[0].split('=', 1)[1]))
        assert bridge == hex(network['clients'][index]['bridge_handle'])
        loads = records_for(bundle, sid, 'load_frida_script')
        finals = [event for event in records_for(bundle, sid, 'frida_session_status')
                  if event['normalized_result'].get('state') == 'detached']
        assert len(loads) == len(finals) == 1
        early, messages = payloads(loads[0]), payloads(finals[0])
        assert messages[:len(early)] == early
        armed = [event for event in early if event['kind'] == 'device-io-armed']
        assert len(armed) == 1 and armed[0]['data'] == dict(api='ntdll.dll:NtDeviceIoControlFile')
        boundary = [event for event in messages if event['kind'] == 'self-terminate-entry']
        assert len(boundary) == 1 and armed[0]['seq'] < boundary[0]['seq']
        device = boundary[0]['data']['deviceIo']
        assert device['errors'] == [] and device['overflow'] is False
        codes = device['codes']
        assert len(codes) == 25 and device['calls'] == sum(row['calls'] for row in codes.values())
        assert {code for code in codes if code.startswith('0x120')} == BRIDGE_CODES
        for code, detail in codes.items():
            assert detail['calls'] == detail['success'] + detail['pending'] + detail['failure']
            assert detail['uniqueHandles'] >= len(detail['firstHandles']) >= 1
            if code in BRIDGE_CODES:
                assert detail['uniqueHandles'] == 1 and detail['firstHandles'] == [bridge]
                assert detail['pending'] == 0
                if code != '0x12017':
                    assert detail['failure'] == 0
        assert codes['0x1201f']['calls'] == network['clients'][index]['send']
        assert codes['0x12017']['calls'] == network['clients'][index]['recv']
        assert all(codes[code]['calls'] == 1 for code in BRIDGE_CODES - {'0x1201f', '0x12017'})
        clients.append(dict(index=index, pid=pid, bridge_handle=bridge,
                            device_io_calls=device['calls'],
                            control_codes=len(codes),
                            selected_bridge_codes=sorted(BRIDGE_CODES),
                            selected_send=codes['0x1201f']['calls'],
                            selected_recv=codes['0x12017']['calls'],
                            load_evidence_id=loads[0]['evidence_id'],
                            final_evidence_id=finals[0]['evidence_id']))
    return dict(passed=True, clients=clients,
                verification_sha256=sha(CASE / 'verification.json'),
                bundle_sha256=sha(TRACE / 'rea-evidence.json'),
                scope='One private public1 two-human run: all observed 0x120xx NtDeviceIoControlFile codes use only each client inherited bridge handle; selected send/recv code counts match selected Winsock counts; other I/O APIs/kernel/wire/processes remain open',
                full_d5_qualified=False)


if __name__ == '__main__':
    result = review()
    output = CASE / 'device-io-review.json'
    if output.exists():
        assert json.loads(output.read_text(encoding='utf-8')) == result
    else:
        output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, clients=result['clients'])))
