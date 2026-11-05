"""Review the combined owned SDK queue and packaged Python network audits."""
from __future__ import annotations

import json

from tools.python_proactor_bytes412 import source as byte_source
from tools.python_socket_audit377 import source as endpoint_source
from tools.review_d5_connected_pair338 import ROOT, run
from tools.review_d5_proactor_bytes412 import review_bytes
from tools.review_d5_worker_sockets380 import audit as endpoint_audit
from tools.review_recipe47_queue_connected524 import review_case, sha256

CASE = ROOT / 'local/privacy526-public1-wire01'
TRACE = ROOT / 'local/privacy526-trace01'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def review():
    queue = review_case(CASE, TRACE)
    connected = run(CASE, ROOT / 'local/privacy512-packages01',
                    ROOT / 'local/privacy512-game01',
                    ROOT / 'local/s139/assets/build-37822')
    assert connected['passed']
    report = read(CASE / 'verification.json')
    assert report['passed'] and report['python_socket_audit']
    assert report['python_byte_audit'] and report['worker_socket_audit']
    assert report['forced_cleanup'] is False
    drivers = []
    for index, name in enumerate(('server', 'client-0', 'client-1')):
        folder = CASE / name
        request = read(folder / 'request.json')
        assert request['python_socket_audit'] and request['python_byte_audit']
        script = (folder / 'owned-driver.py').read_text(encoding='utf-8')
        assert script.startswith(endpoint_source(folder / 'socket-audit.jsonl') +
                                 byte_source(folder / 'byte-audit.jsonl'))
        pid = report['jobs'][index]['pid']
        endpoint_audit(folder / 'socket-audit.jsonl', pid, worker=False)
        drivers.append(review_bytes(folder / 'byte-audit.jsonl', pid))
    server_port = read(CASE / 'server/server-ready.json')['address'][1]
    host_peers = drivers[0]['peers']
    host_handles = []
    for adapter in drivers[1:]:
        remote = [peer for peer in adapter['peers'] if peer['port'] == server_port]
        assert len(remote) == 1
        reciprocal = [peer for peer in host_peers
                      if peer['send_bytes'] == remote[0]['recv_bytes']
                      and peer['recv_bytes'] == remote[0]['send_bytes']
                      and peer['send_bytes'] > 0 and peer['recv_bytes'] > 0]
        assert len(reciprocal) == 1
        host_handles.append(reciprocal[0]['handle'])
    assert len(set(host_handles)) == 2
    server_request = read(CASE / 'server/request.json')
    assert server_request['worker_socket_audit']
    assert len(server_request['worker_audit_sources']) == 2
    for index, worker in enumerate(report['server']['workers']):
        path = CASE / f'server/worker-{index}/socket-audit.jsonl'
        assert server_request['worker_audit_sources'][index] == endpoint_source(
            path, positive_probe=True)
        endpoint_audit(path, worker['pid'], worker=True)
    return {'passed': True, 'queue': queue,
            'driver_bytes': [{'pid': item['pid'],
                              'send': item['stats']['completed_send_bytes'],
                              'recv': item['stats']['completed_recv_bytes']}
                             for item in drivers],
            'worker_count': 2, 'report_sha256': sha256(CASE / 'verification.json'),
            'bundle_sha256': sha256(TRACE / 'rea-evidence.json')}


if __name__ == '__main__':
    print(json.dumps(review()))
