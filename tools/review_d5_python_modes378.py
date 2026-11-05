"""Review current private public2, public5, and Custom CPython socket journals."""
from __future__ import annotations

import json

from client_patch.patcher.telemetry import RECIPE_VERSION, RUNTIME_VALIDATED
from tools.package_integrity import verify
from tools.python_socket_audit377 import source
from tools.review_d5_connected_modes363 import check as mode_check
from tools.review_d5_connected_pair338 import ROOT, sha
from tools.review_d5_python_sockets377 import CONTROL, EVENTS, rows

PACKAGES = ROOT / 'local/privacy358-packages02'
GAME = ROOT / 'local/privacy301-runtime01/game'
ASSETS = ROOT / 'local/s139/assets/build-37822'
HELPER = ROOT / 'local/privacy357-helper-build01/helper-build.json'
CASES = ((ROOT / 'local/privacy378-python-mode2', 2, False),
         (ROOT / 'local/privacy378-python-mode5', 5, False),
         (ROOT / 'local/privacy378-python-custom', 1, True))


def check(case, mode, custom):
    report = json.loads((case / 'verification.json').read_text(encoding='utf-8'))
    manifest = json.loads((GAME / '.battleaces-resurrection/patch-manifest.json').read_text(encoding='utf-8'))
    assert report['passed'] and report['forced_cleanup'] is False
    assert report['python_socket_audit'] and report['rc_open']
    assert report['mode'] == mode and report['humans'] == 2 and report['custom_rematch'] is custom
    assert report['packages'] == str(PACKAGES)
    assert report['assets_manifest_sha256'] == sha(ASSETS / 'asset-manifest.json')
    assert manifest['telemetry']['recipe_version'] == RECIPE_VERSION == 38
    assert manifest['telemetry']['runtime_validated'] is RUNTIME_VALIDATED is False
    assert sha(GAME / 'GameAssembly.dll') == manifest['patched_sha256']
    assert sha(GAME / 'BattleAcesOffline.dll') == manifest['helper_sha256']
    assert report['helper_build']['receipt']['helper_sha256'] == manifest['helper_sha256']
    assert sha(PACKAGES / 'battleaces-client-win64/program/client-helper/BattleAcesOffline.dll') == manifest['helper_sha256']
    assert all(verify(PACKAGES / f'battleaces-{kind}-win64',kind) for kind in ('server','client'))
    for key in ('source_files_unchanged','shared_channels_unchanged','adapters_unchanged',
                'config_unchanged','package_files_unchanged','assets_unchanged',
                'fixture_tokens_not_logged','temporary_pki_removed'):
        assert report[key] is True, key
    pinned_sources={'tools/python_socket_audit377.py':'9a8a12a7bd22313fc0f81deae89b75551bebc3851b991188f74e4769035c8acd',
                    'tools/verify_packaged_multiplayer.py':'8b4b562b78dad12d5bc6052bfef488e38a10b2a71c175099e4adc5f5e32b6944'}
    for source_key,digest in pinned_sources.items():
        assert report['source_sha256_at_start'][source_key] == digest
        assert report['source_sha256_at_finish'][source_key] == digest
    if custom:
        assert len(report['custom']['matches']) == len(report['custom']['worker_pids']) == 2
        assert report['custom']['epochs'] == [1,2]
        assert report['custom']['native_leave_order'] == ['guest','host']
        assert [job['total_processes'] for job in report['jobs']] == [7,2,2]
        assert len(report['server']['frozen_matches']) == 2
    else:
        assert mode_check(case,mode,PACKAGES,GAME,ASSETS,HELPER)['mode'] == mode
    assert all(row['driver_report']['game_exit_code'] == row['driver_report']['launcher_exit_code'] == 0
               for row in report['clients'])
    assert all(row['reaped'] and row['exit_code'] == 0 for row in report['worker_cleanup'])
    assert all(job['active_processes'] == job['total_terminated_processes'] == 0 for job in report['jobs'])
    summaries = []
    for index,name in enumerate(('server','client-0','client-1')):
        folder = case / name
        request = json.loads((folder / 'request.json').read_text(encoding='utf-8'))
        assert request['python_socket_audit'] is True
        assert (folder / 'owned-driver.py').read_text(encoding='utf-8').startswith(source(folder / 'socket-audit.jsonl'))
        audit = folder / 'socket-audit.jsonl'
        events = rows(audit)
        assert events[0]['event'] == 'observer-ready' and events[-1]['event'] == 'observer-exit'
        assert not any(row['event'] == 'overflow' for row in events)
        assert all(row['event'] in EVENTS | {'observer-ready','observer-exit'} for row in events)
        assert len(events) < 4098 and all(row['pid'] == report['jobs'][index]['pid'] for row in events)
        assert [row['tick_ns'] for row in events] == sorted(row['tick_ns'] for row in events)
        assert sum(row['event'] == 'socket.bind' for row in events) >= 1
        assert sum(row['event'] == 'socket.connect' for row in events) >= 1
        for row in events:
            if row['event'] in ('socket.bind','socket.connect','socket.sendto','socket.sendmsg'):
                assert type(row['address']) is list and row['address'][0] == '127.0.0.1'
            elif row['event'] in EVENTS:
                assert row['address'] in ('localhost','127.0.0.1')
        summaries.append(dict(name=name,pid=report['jobs'][index]['pid'],events=len(events),
                              binds=sum(row['event']=='socket.bind' for row in events),
                              connects=sum(row['event']=='socket.connect' for row in events),
                              sha256=sha(audit)))
    return dict(mode=mode,custom=custom,verification_sha256=sha(case/'verification.json'),
                drivers=summaries)


def review():
    control = rows(CONTROL)
    assert [row['event'] for row in control] == ['observer-ready','socket.getaddrinfo','socket.bind','observer-exit']
    assert control[1]['address'] == 'localhost' and control[2]['address'] == ['127.0.0.1',0]
    return dict(passed=True,scope='Current private public2/public5/Custom CPython driver socket endpoints from script entry through normal interpreter exit; only loopback observed. Native,worker,other configurations,wire and full D5 remain open.',
                control_sha256=sha(CONTROL),cases=[check(*item) for item in CASES],full_d5_qualified=False)


if __name__ == '__main__':
    result = review()
    output = ROOT / 'local/privacy378-python-modes-review.json'
    if output.exists():
        assert json.loads(output.read_text(encoding='utf-8')) == result
    else:
        output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':True,'modes':[(row['mode'],row['custom']) for row in result['cases']]}))
