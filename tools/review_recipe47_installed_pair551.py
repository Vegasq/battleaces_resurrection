"""Review the actual-installed recipe47 server/client loopback match."""
from __future__ import annotations

import json

from client_patch.patcher.telemetry import RECIPE_VERSION, RUNTIME_VALIDATED
from tools.package_integrity import verify
from tools.python_proactor_bytes412 import source as byte_source
from tools.python_socket_audit377 import source as endpoint_source
from tools.review_d5_connected_pair338 import ROOT, sha
from tools.review_d5_proactor_bytes412 import review_bytes
from tools.review_d5_worker_sockets380 import audit
from tools.review_recipe47_server_native549 import review as review_install

CASE = ROOT / 'local/privacy550-installed-pair01'
PACKAGES = ROOT / 'local/privacy512-packages01'
SERVER = ROOT / 'local/privacy548-server01'
GAME = ROOT / 'local/privacy543-game01'
ASSETS = SERVER / 'assets/build-37822'
PINNED_VERIFIER = '531c05f70e377919b2f049ece9b52df23ae9a144170d8023ce0a17e9756c21ba'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def review():
    assert review_install()['passed']
    report = read(CASE / 'verification.json')
    assert RECIPE_VERSION == 47 and RUNTIME_VALIDATED is False
    assert report['passed'] and not report['forced_cleanup']
    assert report['packages'] == str(PACKAGES)
    assert report['server_package'] == str(SERVER)
    assert report['assets_manifest_sha256'] == sha(ASSETS / 'asset-manifest.json')
    assert report['mode'] == 1 and report['humans'] == 2 and report['rc_open']
    assert report['python_socket_audit'] and report['python_byte_audit']
    assert report['worker_socket_audit'] and not report['prelaunch_observer']
    assert verify(SERVER, 'server')
    assert verify(PACKAGES / 'battleaces-client-win64', 'client')
    assert report['helper_build']['receipt']['helper_sha256'] == sha(GAME / 'BattleAcesOffline.dll')
    for key in ('source_files_unchanged', 'package_files_unchanged',
                'assets_unchanged', 'adapters_unchanged', 'shared_channels_unchanged',
                'config_unchanged', 'fixture_tokens_not_logged', 'temporary_pki_removed'):
        assert report[key] is True, key
    for key in ('tools/verify_packaged_multiplayer.py', 'tools/python_socket_audit377.py',
                'tools/python_proactor_bytes412.py'):
        digest = PINNED_VERIFIER if key == 'tools/verify_packaged_multiplayer.py' else sha(ROOT / key)
        assert report['source_sha256_at_start'][key] == digest
        assert report['source_sha256_at_finish'][key] == digest
    host = read(CASE / 'config/host.json')
    assert host['listen_host'] == '127.0.0.1'
    assert host['assets_directory'] == str(ASSETS)
    assert host['data_directory'] == str(CASE / 'host-data')
    assert report['match']['mode'] == 1 and report['match']['frames'] >= 1200
    assert report['match']['result']['complete'] and len(report['clients']) == 2
    assert all(row['driver_report']['game_exit_code'] ==
               row['driver_report']['launcher_exit_code'] == 0 for row in report['clients'])
    assert report['server']['passed'] and report['server']['listener_closed']
    assert report['server']['status_writer_drained'] and report['server']['state_lock_released']
    assert len(report['server']['workers']) == 2
    assert all(row['reaped'] and row['exit_code'] == 0 for row in report['server']['workers'])
    assert [row['total_processes'] for row in report['jobs']] == [5, 2, 2]
    assert all(row['active_processes'] == row['total_terminated_processes'] == 0
               for row in report['jobs'])
    drivers = []
    for index, name in enumerate(('server', 'client-0', 'client-1')):
        folder = CASE / name
        script = (folder / 'owned-driver.py').read_text(encoding='utf-8')
        assert script.startswith(endpoint_source(folder / 'socket-audit.jsonl') +
                                 byte_source(folder / 'byte-audit.jsonl'))
        endpoint = audit(folder / 'socket-audit.jsonl', report['jobs'][index]['pid'], worker=False)
        bytes_result = review_bytes(folder / 'byte-audit.jsonl', report['jobs'][index]['pid'])
        drivers.append(dict(name=name, endpoint=endpoint, bytes=bytes_result))
    server_port = read(CASE / 'server/server-ready.json')['address'][1]
    host_peers = drivers[0]['bytes']['peers']
    matched = []
    for adapter in drivers[1:]:
        remote = [peer for peer in adapter['bytes']['peers'] if peer['port'] == server_port]
        assert len(remote) == 1
        reciprocal = [peer for peer in host_peers
                      if peer['send_bytes'] == remote[0]['recv_bytes']
                      and peer['recv_bytes'] == remote[0]['send_bytes']
                      and peer['send_bytes'] > 0]
        assert len(reciprocal) == 1
        matched.append(reciprocal[0]['handle'])
    assert len(set(matched)) == 2
    workers = []
    request = read(CASE / 'server/request.json')
    for index, row in enumerate(report['server']['workers']):
        journal = CASE / f'server/worker-{index}/socket-audit.jsonl'
        assert request['worker_audit_sources'][index] == endpoint_source(journal, positive_probe=True)
        workers.append(audit(journal, row['pid'], worker=True))
    return dict(passed=True, recipe=47, actual_installed_pair=True,
                frames=report['match']['frames'], drivers=drivers, workers=workers,
                run_sha256=sha(CASE / 'verification.json'), full_d5_qualified=False)


if __name__ == '__main__':
    result = review()
    output = CASE / 'review551.json'
    if output.exists():
        assert read(output) == result
    else:
        output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=result['passed'], frames=result['frames'],
                          drivers=len(result['drivers']), workers=len(result['workers'])),
                     sort_keys=True))
