"""Review endpoint-only CPython audit in current packaged host/client drivers."""
from __future__ import annotations

import json

from client_patch.patcher.telemetry import RECIPE_VERSION, RUNTIME_VALIDATED
from tools.python_socket_audit377 import source
from tools.review_d5_connected_pair338 import ROOT, run, sha

CASE = ROOT / 'local/privacy377-python-sockets01'
CONTROL = ROOT / 'local/privacy377-control01/client-0/socket-audit.jsonl'
PACKAGES = ROOT / 'local/privacy358-packages02'
GAME = ROOT / 'local/privacy301-runtime01/game'
ASSETS = ROOT / 'local/s139/assets/build-37822'
EVENTS = {'socket.bind', 'socket.connect', 'socket.sendto', 'socket.sendmsg',
          'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr',
          'socket.getnameinfo'}


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def review() -> dict:
    control = rows(CONTROL)
    assert [row['event'] for row in control] == [
        'observer-ready', 'socket.getaddrinfo', 'socket.bind', 'observer-exit']
    assert control[1]['address'] == 'localhost'
    assert control[2]['address'] == ['127.0.0.1', 0]
    assert len({row['pid'] for row in control}) == 1
    connected = run(CASE, PACKAGES, GAME, ASSETS)
    assert connected['passed']
    report = json.loads((CASE / 'verification.json').read_text(encoding='utf-8'))
    manifest = json.loads((GAME / '.battleaces-resurrection/patch-manifest.json').read_text(encoding='utf-8'))
    assert report['passed'] and report['python_socket_audit'] is True
    assert report['forced_cleanup'] is False and report['source_files_unchanged']
    assert report['package_files_unchanged'] and report['adapters_unchanged']
    assert manifest['telemetry']['recipe_version'] == RECIPE_VERSION == 38
    assert manifest['telemetry']['runtime_validated'] is RUNTIME_VALIDATED is False
    source_key = 'tools/python_socket_audit377.py'
    assert report['source_sha256_at_start'][source_key] == '9a8a12a7bd22313fc0f81deae89b75551bebc3851b991188f74e4769035c8acd'
    assert report['source_sha256_at_finish'][source_key] == report['source_sha256_at_start'][source_key]
    summaries = []
    for index, name in enumerate(('server', 'client-0', 'client-1')):
        folder = CASE / name
        request = json.loads((folder / 'request.json').read_text(encoding='utf-8'))
        assert request['python_socket_audit'] is True
        driver = (folder / 'owned-driver.py').read_text(encoding='utf-8')
        assert driver.startswith(source(folder / 'socket-audit.jsonl'))
        audit_path = folder / 'socket-audit.jsonl'
        events = rows(audit_path)
        pid = report['jobs'][index]['pid']
        assert len(events) < 4098 and all(row['pid'] == pid for row in events)
        assert [events[0]['event'], events[-1]['event']] == ['observer-ready', 'observer-exit']
        assert not any(row['event'] == 'overflow' for row in events)
        assert all(row['event'] in EVENTS | {'observer-ready', 'observer-exit'} for row in events)
        assert [row['tick_ns'] for row in events] == sorted(row['tick_ns'] for row in events)
        assert sum(row['event'] == 'socket.bind' for row in events) >= 1
        assert sum(row['event'] == 'socket.connect' for row in events) >= 1
        for row in events:
            if row['event'] in ('socket.connect', 'socket.bind', 'socket.sendto', 'socket.sendmsg'):
                assert type(row['address']) is list and row['address'][0] == '127.0.0.1'
            elif row['event'] in ('socket.getaddrinfo', 'socket.gethostbyname',
                                  'socket.gethostbyaddr', 'socket.getnameinfo'):
                assert row['address'] in ('localhost', '127.0.0.1')
        summaries.append(dict(name=name,pid=pid,events=len(events),
                              binds=sum(row['event'] == 'socket.bind' for row in events),
                              connects=sum(row['event'] == 'socket.connect' for row in events),
                              audit_sha256=sha(audit_path)))
    return dict(passed=True,scope='One current private public1 match: CPython socket audit from packaged driver script entry through normal interpreter exit; all observed endpoint events were loopback. Native/socket library bypasses, worker processes, kernel/wire and full D5 remain open.',
                control_sha256=sha(CONTROL),verification_sha256=sha(CASE / 'verification.json'),
                drivers=summaries,full_d5_qualified=False)


if __name__ == '__main__':
    result = review()
    output = CASE / 'python-socket-review.json'
    if output.exists():
        assert json.loads(output.read_text(encoding='utf-8')) == result
    else:
        output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':True,'drivers':result['drivers']}))
