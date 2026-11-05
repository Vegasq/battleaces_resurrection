"""Bind four-human public2 host/client and both worker socket journals."""
from __future__ import annotations

import json

from tools.python_socket_audit377 import source
from tools.review_d5_connected_pair338 import ROOT, sha
from tools.review_d5_four_humans391 import review as review_drivers
from tools.review_d5_worker_sockets380 import audit

CASE = ROOT / 'local/privacy392-four-human-workers01'


def review(case=CASE) -> dict:
    drivers = review_drivers(case)
    report = json.loads((case / 'verification.json').read_text(encoding='utf-8'))
    assert report['passed'] and report['worker_socket_audit'] is True
    assert report['python_socket_audit'] and report['mode'] == 2 and report['humans'] == 4
    server = report['server']
    assert server['worker_audit_launches'] == 2
    pids = server['worker_audit_pids']
    assert len(pids) == len(set(pids)) == 2
    assert pids == [row['pid'] for row in server['workers']]
    assert all(row['exit_code'] == 0 and row['reaped'] and row['failure'] is None
               for row in server['workers'])
    assert pids == [row['pid'] for row in report['worker_cleanup']]
    request = json.loads((case / 'server/request.json').read_text(encoding='utf-8'))
    assert request['worker_socket_audit'] and request['python_socket_audit']
    assert len(request['worker_audit_sources']) == 2
    workers = []
    for index, pid in enumerate(pids):
        path = case / f'server/worker-{index}/socket-audit.jsonl'
        assert request['worker_audit_sources'][index] == source(path, positive_probe=True)
        workers.append(dict(index=index, **audit(path, pid, worker=True)))
    result = dict(passed=True, scope='private public2 four-human host, four client adapters and two simulation workers: selected CPython socket events from script entry to exit',
                  recipe=38, frames=drivers['frames'], verification_sha256=sha(case / 'verification.json'),
                  driver_review_sha256=sha(case / 'review391.json'),
                  driver_journals=drivers['driver_journals'], worker_journals=workers,
                  full_d5_qualified=False)
    (case / 'review392.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ('driver_journals', 'worker_journals')}, sort_keys=True))
