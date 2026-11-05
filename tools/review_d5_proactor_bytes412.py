"""Review opt-in packaged Proactor byte counts and reciprocal loopback links."""
from __future__ import annotations

import json

from tools.python_proactor_bytes412 import source as byte_source
from tools.python_socket_audit377 import source as endpoint_source
from tools.review_d5_connected_pair338 import ROOT, run, sha
from tools.review_d5_worker_sockets380 import audit as endpoint_audit

CASE = ROOT / 'local/privacy412-proactor-pair01'
CONTROL = ROOT / 'local/privacy412-proactor-control01/byte-audit.jsonl'
PACKAGES = ROOT / 'local/privacy358-packages02'
GAME = ROOT / 'local/privacy301-runtime01/game'
ASSETS = ROOT / 'local/s139/assets/build-37822'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def review_bytes(path, pid):
    events = rows(path)
    assert [row['event'] for row in events] == ['observer-ready', 'observer-exit']
    assert all(row['pid'] == pid for row in events)
    assert events[0]['data'] == dict(methods=7)
    data = events[1]['data']
    assert data['errors'] == [] and data['overflow'] is False
    stats, peers = data['stats'], data['peers']
    assert stats['send'] > 0 and stats['recv'] + stats['recv_into'] > 0
    assert stats['sendto'] == stats['recvfrom'] == stats['recvfrom_into'] == stats['sendfile'] == 0
    assert stats['unclassified'] == 0
    assert stats['requested_send_bytes'] == stats['completed_send_bytes'] > 0
    assert stats['completed_recv_bytes'] > 0
    assert sum(row['send_calls'] for row in peers) == stats['send']
    assert sum(row['recv_calls'] for row in peers) == stats['recv'] + stats['recv_into']
    assert sum(row['send_bytes'] for row in peers) == stats['completed_send_bytes']
    assert sum(row['recv_bytes'] for row in peers) == stats['completed_recv_bytes']
    assert len(peers) >= 2 and all(row['address'] == '127.0.0.1' and
                                   0 < row['port'] < 65536 for row in peers)
    return dict(pid=pid, stats=stats, peers=peers, sha256=sha(path))


def review() -> dict:
    control = rows(CONTROL)
    assert [row['event'] for row in control] == ['observer-ready', 'observer-exit']
    assert control[-1]['data']['stats']['send'] == 2
    assert control[-1]['data']['stats']['completed_send_bytes'] == 10
    assert control[-1]['data']['stats']['completed_recv_bytes'] == 10
    assert control[-1]['data']['errors'] == [] and control[-1]['data']['overflow'] is False
    connected = run(CASE, PACKAGES, GAME, ASSETS)
    assert connected['passed']
    report = read(CASE / 'verification.json')
    assert report['python_socket_audit'] and report['python_byte_audit']
    assert report['worker_socket_audit'] and report['forced_cleanup'] is False
    for key in ('tools/python_socket_audit377.py', 'tools/python_proactor_bytes412.py',
                'tools/verify_packaged_multiplayer.py'):
        assert report['source_sha256_at_start'][key] == report['source_sha256_at_finish'][key]
        assert report['source_sha256_at_start'][key] == sha(ROOT / key)
    drivers = []
    for index, name in enumerate(('server', 'client-0', 'client-1')):
        folder = CASE / name
        request = read(folder / 'request.json')
        assert request['python_socket_audit'] and request['python_byte_audit']
        script = (folder / 'owned-driver.py').read_text(encoding='utf-8')
        expected = endpoint_source(folder / 'socket-audit.jsonl') + byte_source(folder / 'byte-audit.jsonl')
        assert script.startswith(expected)
        pid = report['jobs'][index]['pid']
        endpoint = endpoint_audit(folder / 'socket-audit.jsonl', pid, worker=False)
        byte = review_bytes(folder / 'byte-audit.jsonl', pid)
        drivers.append(dict(name=name, endpoint=endpoint, byte=byte))
    server_port = read(CASE / 'server/server-ready.json')['address'][1]
    host = drivers[0]['byte']['peers']
    matched = []
    for row in drivers[1:]:
        remote = [peer for peer in row['byte']['peers'] if peer['port'] == server_port]
        assert len(remote) == 1
        adapter = remote[0]
        reciprocal = [peer for peer in host if peer['send_bytes'] == adapter['recv_bytes']
                      and peer['recv_bytes'] == adapter['send_bytes']
                      and peer['send_bytes'] > 0 and peer['recv_bytes'] > 0]
        assert len(reciprocal) == 1
        matched.append(reciprocal[0]['handle'])
    assert len(set(matched)) == 2
    server = report['server']
    request = read(CASE / 'server/request.json')
    assert request['worker_socket_audit'] and len(request['worker_audit_sources']) == 2
    workers = []
    for index, worker in enumerate(server['workers']):
        path = CASE / f'server/worker-{index}/socket-audit.jsonl'
        assert request['worker_audit_sources'][index] == endpoint_source(path, positive_probe=True)
        workers.append(endpoint_audit(path, worker['pid'], worker=True))
    return dict(passed=True, drivers=drivers, workers=workers,
                control_sha256=sha(CONTROL),
                verification_sha256=sha(CASE / 'verification.json'),
                scope='Current private public1 host/two adapters: bounded Python Proactor send/receive byte counts on loopback endpoints with reciprocal host-adapter totals; native/ctypes/kernel/wire/queue/final release remain open',
                full_d5_qualified=False)


if __name__ == '__main__':
    result = review()
    output = CASE / 'proactor-review.json'
    if output.exists():
        assert read(output) == result
    else:
        output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, drivers=[dict(name=row['name'],
        send_bytes=row['byte']['stats']['completed_send_bytes'],
        recv_bytes=row['byte']['stats']['completed_recv_bytes']) for row in result['drivers']])))
