"""Review the current private four-human public2 match and endpoint journals."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from client_patch.patcher.telemetry import RECIPE_VERSION, RUNTIME_VALIDATED
from tools.package_integrity import verify
from tools.python_socket_audit377 import source
from tools.review_d5_python_sockets377 import CONTROL, EVENTS, rows
from tools.review_d5_connected_pair338 import ROOT, sha

CASE = ROOT / 'local/privacy391-four-human02'
PACKAGES = ROOT / 'local/privacy358-packages02'
GAME = ROOT / 'local/privacy301-runtime01/game'
ASSETS = ROOT / 'local/s139/assets/build-37822'
PINNED391 = {
    'tools/verify_packaged_multiplayer.py': '6978e31584ac404c2a44f948ffeee82068e1d16544105716776ce6e627b401dc',
    'tools/python_socket_audit377.py': 'a081f3375c74b881e60f0f3919d45cb04fb5d9712943cb5ebf138293f08b6216',
}
PINNED392 = {
    'tools/verify_packaged_multiplayer.py': '33979a01f9007a63378b6f86869427c414bdb9cee1e674a0c416fbe251c816df',
    'tools/python_socket_audit377.py': 'a081f3375c74b881e60f0f3919d45cb04fb5d9712943cb5ebf138293f08b6216',
}


def review(case: Path = CASE) -> dict:
    report = json.loads((case / 'verification.json').read_text(encoding='utf-8'))
    patch = json.loads((GAME / '.battleaces-resurrection/patch-manifest.json').read_text(encoding='utf-8'))
    assert report['passed'] and report['forced_cleanup'] is False
    assert report['python_socket_audit'] and report['rc_open']
    assert report['mode'] == 2 and report['humans'] == 4 and not report['custom_rematch']
    assert report['packages'] == str(PACKAGES)
    assert report['assets_manifest_sha256'] == sha(ASSETS / 'asset-manifest.json')
    assert patch['telemetry']['recipe_version'] == RECIPE_VERSION == 38
    assert patch['telemetry']['runtime_validated'] is RUNTIME_VALIDATED is False
    assert sha(GAME / 'GameAssembly.dll') == patch['patched_sha256']
    assert sha(GAME / 'BattleAcesOffline.dll') == patch['helper_sha256']
    assert report['helper_build']['receipt']['helper_sha256'] == patch['helper_sha256']
    assert sha(PACKAGES / 'battleaces-client-win64/program/client-helper/BattleAcesOffline.dll') == patch['helper_sha256']
    for kind in ('server', 'client'):
        assert verify(PACKAGES / f'battleaces-{kind}-win64', kind)
    for key in ('source_files_unchanged', 'shared_channels_unchanged', 'adapters_unchanged',
                'config_unchanged', 'package_files_unchanged', 'assets_unchanged',
                'fixture_tokens_not_logged', 'temporary_pki_removed'):
        assert report[key] is True, key
    for key in ('tools/verify_packaged_multiplayer.py', 'tools/python_socket_audit377.py'):
        historical = PINNED391 if case == CASE else PINNED392 if case.name == 'privacy392-four-human-workers01' else None
        digest = historical[key] if historical else hashlib.sha256((ROOT / key).read_bytes()).hexdigest()
        assert report['source_sha256_at_start'][key] == report['source_sha256_at_finish'][key] == digest
    match = report['match']
    assert match['mode'] == 2 and match['full_human_group'] is True
    assert sorted(match['human_seats']) == [0, 1, 2, 3] and match['bot_seats'] == []
    assert match['frames'] >= 1200 and match['result']['complete'] is True
    assert len(match['clients']) == len(report['clients']) == 4
    assert all(row['received_frames'] == match['frames'] for row in match['clients'])
    assert all(row['driver_report']['game_exit_code'] == row['driver_report']['launcher_exit_code'] == 0
               for row in report['clients'])
    assert report['server']['passed'] and report['server']['listener_closed']
    assert report['server']['status_writer_drained'] and report['server']['state_lock_released']
    assert report['server']['final_state']['active_workers'] == 0
    assert len(report['worker_cleanup']) == 2 and all(
        item['reaped'] and item['exit_code'] == 0 for item in report['worker_cleanup'])
    assert [job['total_processes'] for job in report['jobs']] == [5, 2, 2, 2, 2]
    assert all(job['active_processes'] == job['total_terminated_processes'] == 0
               for job in report['jobs'])
    control = rows(CONTROL)
    assert [row['event'] for row in control] == [
        'observer-ready', 'socket.getaddrinfo', 'socket.bind', 'observer-exit']
    assert control[1]['address'] == 'localhost' and control[2]['address'] == ['127.0.0.1', 0]
    summaries = []
    for index, name in enumerate(('server', 'client-0', 'client-1', 'client-2', 'client-3')):
        folder = case / name
        request = json.loads((folder / 'request.json').read_text(encoding='utf-8'))
        assert request['python_socket_audit'] is True
        assert (folder / 'owned-driver.py').read_text(encoding='utf-8').startswith(
            source(folder / 'socket-audit.jsonl'))
        audit = folder / 'socket-audit.jsonl'
        events = rows(audit)
        assert 2 < len(events) < 4098
        assert [events[0]['event'], events[-1]['event']] == ['observer-ready', 'observer-exit']
        assert all(row['pid'] == report['jobs'][index]['pid'] for row in events)
        assert all(row['event'] in EVENTS | {'observer-ready', 'observer-exit'} for row in events)
        assert [row['tick_ns'] for row in events] == sorted(row['tick_ns'] for row in events)
        assert not any(row['event'] == 'overflow' for row in events)
        binds = sum(row['event'] == 'socket.bind' for row in events)
        connects = sum(row['event'] == 'socket.connect' for row in events)
        assert binds >= 1 and connects >= 1
        for row in events:
            if row['event'] in ('socket.bind', 'socket.connect', 'socket.sendto', 'socket.sendmsg'):
                assert type(row['address']) is list and row['address'][0] == '127.0.0.1'
            elif row['event'] in EVENTS:
                assert row['address'] in ('localhost', '127.0.0.1')
        summaries.append(dict(name=name, events=len(events), binds=binds, connects=connects,
                              sha256=sha(audit)))
    result = dict(passed=True, scope='private public2 four-human match and five CPython driver endpoint journals',
                  recipe=38, frames=match['frames'], clients=4,
                  verification_sha256=sha(case / 'verification.json'),
                  control_sha256=sha(CONTROL), driver_journals=summaries,
                  full_d5_qualified=False)
    (case / 'review391.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps({key: value for key, value in result.items() if key != 'driver_journals'}, sort_keys=True))
