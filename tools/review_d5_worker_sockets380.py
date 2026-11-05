"""Bind both packaged simulation workers to endpoint-only CPython audits."""
from __future__ import annotations

import json

from tools.python_socket_audit377 import source
from tools.review_d5_connected_pair338 import ROOT, run, sha
from tools.review_d5_python_sockets377 import EVENTS, rows

FAILED = ROOT / 'local/privacy379-worker-sockets01'
CASE = ROOT / 'local/privacy380-worker-sockets02'
PACKAGES = ROOT / 'local/privacy358-packages02'
GAME = ROOT / 'local/privacy301-runtime01/game'
ASSETS = ROOT / 'local/s139/assets/build-37822'
PINNED = {
    'tools/python_socket_audit377.py':'e7e76699c8d0e592e1108e6d8c17b2ef58b6c746896d57eeae236f66243af8a8',
    'tools/verify_packaged_multiplayer.py':'c4ba72720f1dffd260c11205b7e46e26ce9a63f9e11d8341fff706c3237941ad',
    'tools/packaged_network_drivers.py':'b708df4f13499eaaffcba32747efb3f38211a2cdb6135ca8107bace9cdb41828',
}


def audit(path, pid, *, worker):
    events = rows(path)
    assert all(row['pid'] == pid for row in events)
    assert len(events) < 4098 and events[0]['event'] == 'observer-ready'
    assert events[-1]['event'] == 'observer-exit'
    assert not any(row['event'] == 'overflow' for row in events)
    assert [row['tick_ns'] for row in events] == sorted(row['tick_ns'] for row in events)
    assert all(row['event'] in EVENTS | {'observer-ready','observer-exit'} for row in events)
    if worker:
        assert [row['event'] for row in events] == [
            'observer-ready','socket.getaddrinfo','observer-exit']
        assert events[1]['address'] == 'localhost'
    else:
        assert sum(row['event'] == 'socket.bind' for row in events) >= 1
        assert sum(row['event'] == 'socket.connect' for row in events) >= 1
        for row in events:
            if row['event'] in ('socket.bind','socket.connect','socket.sendto','socket.sendmsg'):
                assert type(row['address']) is list and row['address'][0] == '127.0.0.1'
            elif row['event'] in EVENTS:
                assert row['address'] in ('localhost','127.0.0.1')
    return dict(pid=pid,events=len(events),sha256=sha(path))


def review():
    failed = json.loads((FAILED / 'verification.json').read_text(encoding='utf-8'))
    assert failed['passed'] is False and failed['forced_cleanup'] is True
    assert (FAILED / 'server/worker-0/socket-audit.jsonl').is_file()
    assert not (FAILED / 'server/worker-1/socket-audit.jsonl').exists()
    connected = run(CASE,PACKAGES,GAME,ASSETS)
    assert connected['passed']
    report = json.loads((CASE / 'verification.json').read_text(encoding='utf-8'))
    assert report['passed'] and report['forced_cleanup'] is False
    assert report['python_socket_audit'] and report['worker_socket_audit']
    assert report['source_files_unchanged'] and report['package_files_unchanged']
    assert all(report['source_sha256_at_start'][key] == digest and
               report['source_sha256_at_finish'][key] == digest
               for key,digest in PINNED.items())
    server = report['server']
    assert server['worker_audit_launches'] == 2
    pids = server['worker_audit_pids']
    assert len(pids) == len(set(pids)) == 2
    assert pids == [row['pid'] for row in server['workers']]
    assert all(row['exit_code'] == 0 and row['reaped'] and row['failure'] is None
               for row in server['workers'])
    request = json.loads((CASE / 'server/request.json').read_text(encoding='utf-8'))
    assert request['worker_socket_audit'] and request['python_socket_audit']
    assert len(request['worker_audit_sources']) == 2
    workers = []
    for index,pid in enumerate(pids):
        path = CASE / f'server/worker-{index}/socket-audit.jsonl'
        assert request['worker_audit_sources'][index] == source(path,positive_probe=True)
        workers.append(dict(index=index,**audit(path,pid,worker=True)))
    drivers = []
    for index,name in enumerate(('server','client-0','client-1')):
        folder = CASE / name
        script = (folder / 'owned-driver.py').read_text(encoding='utf-8')
        assert script.startswith(source(folder / 'socket-audit.jsonl'))
        drivers.append(dict(name=name,**audit(folder / 'socket-audit.jsonl',
                                              report['jobs'][index]['pid'],worker=False)))
    assert all(job['active_processes'] == job['total_terminated_processes'] == 0
               for job in report['jobs'])
    return dict(passed=True,scope='One current private public1: both separate packaged simulation workers observed from -c bootstrap through normal interpreter exit with positive localhost lookup; no other CPython socket event. Native/ctypes/OS/wire and full D5 remain open.',
                failed_attempt_sha256=sha(FAILED / 'verification.json'),
                verification_sha256=sha(CASE / 'verification.json'),
                workers=workers,drivers=drivers,full_d5_qualified=False)


if __name__ == '__main__':
    result = review()
    output = CASE / 'worker-socket-review.json'
    if output.exists():
        assert json.loads(output.read_text(encoding='utf-8')) == result
    else:
        output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':True,'worker_pids':[row['pid'] for row in result['workers']]}))
