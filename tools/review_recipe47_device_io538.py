"""Review recipe47 connected queue, Python audit, and native device I/O."""
from __future__ import annotations

import json
from pathlib import Path

from tools.frida_device_io410 import build_source
from tools.python_proactor_bytes412 import source as byte_source
from tools.python_socket_audit377 import source as endpoint_source
from tools.review_d5_connected_pair338 import ROOT, run
from tools.review_d5_proactor_bytes412 import review_bytes
from tools.review_d5_worker_sockets380 import audit as endpoint_audit
from tools.review_recipe47_queue_connected524 import sha256
from tools.telemetry_preexisting_seed import snapshot

CASE = ROOT/'local/privacy538-public1-device01'
TRACE = ROOT/'local/privacy538-trace01'
PACKAGES = ROOT/'local/privacy512-packages01'
GAME = ROOT/'local/privacy512-game01'
ASSETS = ROOT/'local/s139/assets/build-37822'
BRIDGE_CODES = {'0x12043', '0x12037', '0x1203b', '0x120bf',
                '0x12047', '0x1201f', '0x12017'}


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def review() -> dict:
    assert run(CASE, PACKAGES, GAME, ASSETS)['passed']
    report, sessions, bundle = read(CASE/'verification.json'), read(TRACE/'sessions.json'), read(TRACE/'rea-evidence.json')
    assert report['passed'] and report['prelaunch_observer'] and report['preexisting_sdk_queue']
    assert report['preexisting_queue_unchanged'] and not report['forced_cleanup']
    assert report['mode'] == 1 and report['humans'] == 2 and report['rc_open']
    assert report['python_socket_audit'] and report['python_byte_audit'] and report['worker_socket_audit']
    assert all(report[key] for key in ('source_files_unchanged','package_files_unchanged',
        'assets_unchanged','adapters_unchanged','shared_channels_unchanged'))
    assert report['match']['frames'] >= 1200 and report['match']['result']['complete']
    assert all(job['active_processes'] == job['total_terminated_processes'] == 0 for job in report['jobs'])
    assert sessions['case'] == 'local/'+CASE.name and len(sessions['clients']) == 2
    native = []
    for item in sessions['clients']:
        i, pid, sid = item['index'], item['pid'], item['session_id']
        assert i in (0,1) and report['clients'][i]['pid'] == pid
        assert report['clients'][i]['driver_report']['game_exit_code'] == 0
        assert report['clients'][i]['driver_report']['launcher_exit_code'] == 0
        before, after = report['preexisting_queue_before'][i], report['preexisting_queue_after'][i]
        assert before == after and before['files'] == snapshot(Path(before['root']))
        process = read(CASE/f'client-{i}/game-process.json')
        gate = CASE/f'client-{i}/observer-ready'
        assert process['pid'] == pid and process['suspended_for_observer']
        assert gate.read_bytes() == b'FRIDA_READY\n'
        assert (CASE/f'client-{i}/game-process.json').stat().st_mtime_ns < gate.stat().st_mtime_ns
        assert report['prelaunch_resume'][i]['pid'] == pid
        assert report['prelaunch_resume'][i]['tick'] >= process['launch_tick']
        bridge_args = [arg for arg in process['actual_arguments']
                       if arg.startswith('-secure-transport-socket=')]
        assert len(bridge_args) == 1
        bridge = hex(int(bridge_args[0].split('=',1)[1]))
        config = read(TRACE/f'config-{i}.json')
        source_path = TRACE/f'observer-{i}.js'
        assert config['device_io'] and config['source_sha256'] == sha256(source_path)
        assert config['game_sha256'] == sha256(GAME/'Battle Aces.exe')
        assert source_path.read_text(encoding='utf-8') == build_source(config['config'])
        records = [row for row in bundle['records']
                   if row.get('parameters',{}).get('session_id') == sid]
        loads = [row for row in records if row['operation'] == 'load_frida_script']
        finals = [row for row in records if row['operation'] == 'frida_session_status'
                  and row['normalized_result']['state'] == 'detached']
        assert len(loads) == len(finals) == 1
        assert loads[0]['normalized_result']['source_sha256'] == sha256(source_path)
        status = finals[0]['normalized_result']
        assert status['pid'] == pid and not status['messages_truncated']
        messages = status['messages']
        assert all(row['type'] == 'send' and row['payload']['runId'] == config['config']['runId']
                   and row['payload']['pid'] == pid for row in messages)
        assert [row['payload']['seq'] for row in messages] == list(range(1,len(messages)+1))
        kinds = [row['payload']['kind'] for row in messages]
        assert all(kinds.count(kind) == 1 for kind in
                   ('device-io-armed','observer-ready','exit-boundary-armed','self-terminate-entry'))
        assert not any(kind in ('decode-error','budget-exceeded','file-operation',
                                'network-operation','process-create') for kind in kinds)
        boundary = next(row['payload']['data'] for row in messages
                        if row['payload']['kind'] == 'self-terminate-entry')
        assert boundary['exitStatus'] == 0 and not boundary['errors'] and not boundary['overflow']
        assert boundary['unresolvedFileOps'] == 9
        counts = boundary['counts']
        assert counts['ws2_32.dll:send'] > 0 and counts['ws2_32.dll:recv'] > 0
        assert all(counts['ws2_32.dll:'+name] == 0 for name in
                   ('connect','WSAConnect','sendto','WSASendTo','getaddrinfo','GetAddrInfoW','GetAddrInfoExW'))
        assert counts['winhttp.dll:WinHttpConnect'] == 0
        device = boundary['deviceIo']
        assert not device['errors'] and not device['overflow']
        codes = device['codes']
        assert len(codes) == 25 and device['calls'] == sum(row['calls'] for row in codes.values())
        assert {code for code in codes if code.startswith('0x120')} == BRIDGE_CODES
        for code, row in codes.items():
            assert row['calls'] == row['success'] + row['pending'] + row['failure']
            if code in BRIDGE_CODES:
                assert row['uniqueHandles'] == 1 and row['firstHandles'] == [bridge]
                assert row['pending'] == 0
        assert codes['0x1201f']['calls'] == counts['ws2_32.dll:send']
        assert codes['0x12017']['calls'] == counts['ws2_32.dll:recv']
        assert all(codes[c]['calls'] == 1 for c in BRIDGE_CODES-{'0x1201f','0x12017'})
        native.append(dict(index=i,pid=pid,bridge_handle=bridge,
                           device_io_calls=device['calls'],control_codes=len(codes),
                           bridge_send=codes['0x1201f']['calls'],
                           bridge_recv=codes['0x12017']['calls'],
                           load_evidence_id=loads[0]['evidence_id'],
                           final_evidence_id=finals[0]['evidence_id']))
    drivers=[]
    for i,name in enumerate(('server','client-0','client-1')):
        folder=CASE/name
        script=(folder/'owned-driver.py').read_text(encoding='utf-8')
        assert script.startswith(endpoint_source(folder/'socket-audit.jsonl')+
                                 byte_source(folder/'byte-audit.jsonl'))
        endpoint_audit(folder/'socket-audit.jsonl',report['jobs'][i]['pid'],worker=False)
        drivers.append(review_bytes(folder/'byte-audit.jsonl',report['jobs'][i]['pid']))
    server_port=read(CASE/'server/server-ready.json')['address'][1]
    host_peers=drivers[0]['peers']
    matched=[]
    for adapter in drivers[1:]:
        remote=[p for p in adapter['peers'] if p['port']==server_port]
        assert len(remote)==1
        reciprocal=[p for p in host_peers if p['send_bytes']==remote[0]['recv_bytes']
                    and p['recv_bytes']==remote[0]['send_bytes'] and p['send_bytes']>0]
        assert len(reciprocal)==1
        matched.append(reciprocal[0]['handle'])
    assert len(set(matched))==2
    for i,worker in enumerate(report['server']['workers']):
        endpoint_audit(CASE/f'server/worker-{i}/socket-audit.jsonl',worker['pid'],worker=True)
    return dict(passed=True,recipe=47,clients=native,
                worker_count=len(report['server']['workers']),
                report_sha256=sha256(CASE/'verification.json'),
                bundle_sha256=sha256(TRACE/'rea-evidence.json'),
                scope='current owned public1 authored queue, native device-I/O and packaged Python audit; other native APIs/kernel wire/real produced queue/P9/final pair unresolved')


if __name__ == '__main__':
    print(json.dumps(review(),sort_keys=True))
