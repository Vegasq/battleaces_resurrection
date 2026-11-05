"""Review the installed recipe47 public2 match and packaged Python endpoints."""
from __future__ import annotations

import json

from client_patch.patcher.telemetry import RECIPE_VERSION, RUNTIME_VALIDATED
from tools.package_integrity import verify
from tools.python_socket_audit377 import source
from tools.review_d5_connected_pair338 import ROOT, sha
from tools.review_d5_worker_sockets380 import audit
from tools.review_recipe47_native_install546 import review as review_install

CASE = ROOT / 'local/privacy547-public2-device01'
PACKAGES = ROOT / 'local/privacy512-packages01'
GAME = ROOT / 'local/privacy543-game01'
ASSETS = ROOT / 'local/s139/assets/build-37822'
PINNED_VERIFIER = '1d2211446002c0b43a68bd53eff0a08d9e3853db26ae90259918e2b9f73f7faf'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def review(case=CASE):
    assert review_install()['passed']
    report = read(case / 'verification.json')
    patch = read(GAME / '.battleaces-resurrection/patch-manifest.json')
    assert RECIPE_VERSION == patch['telemetry']['recipe_version'] == 47
    assert RUNTIME_VALIDATED is patch['telemetry']['runtime_validated'] is False
    assert report['passed'] and report['forced_cleanup'] is False
    assert report['packages'] == str(PACKAGES)
    assert report['assets_manifest_sha256'] == sha(ASSETS / 'asset-manifest.json')
    assert report['helper_build']['receipt']['helper_sha256'] == patch['helper_sha256']
    assert report['python_socket_audit'] and report['worker_socket_audit']
    assert report['prelaunch_observer'] and report['rc_open']
    assert report['mode'] == 2 and report['humans'] == 4
    for kind in ('server', 'client'):
        assert verify(PACKAGES / f'battleaces-{kind}-win64', kind)
    for key in ('source_files_unchanged', 'package_files_unchanged', 'assets_unchanged',
                'adapters_unchanged', 'shared_channels_unchanged', 'config_unchanged',
                'fixture_tokens_not_logged', 'temporary_pki_removed'):
        assert report[key] is True, key
    for key in ('tools/verify_packaged_multiplayer.py', 'tools/python_socket_audit377.py'):
        digest = PINNED_VERIFIER if key == 'tools/verify_packaged_multiplayer.py' else sha(ROOT / key)
        assert report['source_sha256_at_start'][key] == digest
        assert report['source_sha256_at_finish'][key] == digest
    match = report['match']
    assert match['mode'] == 2 and match['full_human_group'] is True
    assert sorted(match['human_seats']) == [0, 1, 2, 3] and match['bot_seats'] == []
    assert match['frames'] >= 1200 and match['result']['complete'] is True
    assert len(match['clients']) == len(report['clients']) == 4
    assert all(row['received_frames'] == match['frames'] for row in match['clients'])
    assert all(row['driver_report']['game_exit_code'] ==
               row['driver_report']['launcher_exit_code'] == 0 for row in report['clients'])
    server = report['server']
    assert server['passed'] and server['listener_closed']
    assert server['status_writer_drained'] and server['state_lock_released']
    assert server['final_state']['active_workers'] == 0
    assert len(report['worker_cleanup']) == 2
    assert all(row['reaped'] and row['exit_code'] == 0 for row in report['worker_cleanup'])
    assert [job['total_processes'] for job in report['jobs']] == [5, 2, 2, 2, 2]
    assert all(job['active_processes'] == job['total_terminated_processes'] == 0
               for job in report['jobs'])
    drivers = []
    for index, name in enumerate(('server', 'client-0', 'client-1', 'client-2', 'client-3')):
        folder = case / name
        assert read(folder / 'request.json')['python_socket_audit'] is True
        journal = folder / 'socket-audit.jsonl'
        assert (folder / 'owned-driver.py').read_text(encoding='utf-8').startswith(source(journal))
        drivers.append(dict(name=name, **audit(journal, report['jobs'][index]['pid'], worker=False)))
    request = read(case / 'server/request.json')
    assert request['worker_socket_audit'] and request['python_socket_audit']
    assert server['worker_audit_launches'] == 2
    pids = server['worker_audit_pids']
    assert len(pids) == len(set(pids)) == 2
    assert pids == [row['pid'] for row in server['workers']]
    assert pids == [row['pid'] for row in report['worker_cleanup']]
    assert len(request['worker_audit_sources']) == 2
    workers = []
    for index, pid in enumerate(pids):
        assert server['workers'][index]['exit_code'] == 0
        assert server['workers'][index]['reaped'] and server['workers'][index]['failure'] is None
        journal = case / f'server/worker-{index}/socket-audit.jsonl'
        assert request['worker_audit_sources'][index] == source(journal, positive_probe=True)
        workers.append(dict(index=index, **audit(journal, pid, worker=True)))
    return dict(passed=True, recipe=47, frames=match['frames'],
                drivers=drivers, workers=workers,
                verification_sha256=sha(case / 'verification.json'),
                full_d5_qualified=False)


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))
