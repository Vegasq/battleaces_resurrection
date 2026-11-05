"""Review selected state-three entries over one owned recipe38 match."""
from __future__ import annotations

import json

from tools.frida_state3_entry427 import build_source
from tools.review_d5_connected_network341 import review as network_review
from tools.review_d5_connected_pair338 import ROOT, sha
from tools.review_d5_exit_network368 import payloads, read, records_for
from tools.review_d5_socket_exit370 import PACKAGES, GAME, ASSETS

CASE = ROOT / 'local/privacy427-state3-entry02'
TRACE = ROOT / 'local/privacy427-state3-entry-trace02'
EXPECTED = dict(worker=0xc402d0, setter=0xc3c5d0,
                caller=0xc300d0, dispatcher=0xc3b990)


def review() -> dict:
    network = network_review(CASE, TRACE, PACKAGES, GAME, ASSETS)
    assert network['passed']
    report, sessions, bundle = (read(CASE / 'verification.json'),
                                read(TRACE / 'sessions.json'),
                                read(TRACE / 'rea-evidence.json'))
    assert report['passed'] and report['mode'] == 1 and report['humans'] == 2
    assert report['prelaunch_observer'] and not report['forced_cleanup']
    assert report['source_files_unchanged'] and report['package_files_unchanged']
    assert all(row['driver_report']['game_exit_code'] == 0 and
               row['driver_report']['launcher_exit_code'] == 0
               for row in report['clients'])
    assert all(row['reaped'] and row['exit_code'] == 0
               for row in report['worker_cleanup'])
    assert all(row['active_processes'] == row['total_terminated_processes'] == 0
               for row in report['jobs'])
    assert sessions['case'] == 'local/' + CASE.name
    clients = []
    for row in sessions['clients']:
        index, pid, sid = row['index'], row['pid'], row['session_id']
        config = read(TRACE / f'config-{index}.json')
        observer = TRACE / f'observer-{index}.js'
        assert config['state3_entry'] is True and config['source_sha256'] == sha(observer)
        assert observer.read_text(encoding='utf-8') == build_source(config['config'])
        process = read(CASE / f'client-{index}/game-process.json')
        gate = CASE / f'client-{index}/observer-ready'
        assert process['pid'] == pid and process['suspended_for_observer'] is True
        assert gate.read_bytes() == b'FRIDA_READY' + bytes([10])
        assert process['launch_tick'] <= report['prelaunch_resume'][index]['tick']
        assert process['pid'] == report['prelaunch_resume'][index]['pid']
        assert (CASE / f'client-{index}/game-process.json').stat().st_mtime_ns < gate.stat().st_mtime_ns
        loads = records_for(bundle, sid, 'load_frida_script')
        finals = [item for item in records_for(bundle, sid, 'frida_session_status')
                  if item['normalized_result'].get('state') == 'detached']
        assert len(loads) == len(finals) == 1
        load, final = loads[0], finals[0]
        assert load['normalized_result']['source_sha256'] == sha(observer)
        messages, early = payloads(final), payloads(load)
        assert messages[:len(early)] == early
        assert all(item['pid'] == pid and item['runId'] == config['config']['runId']
                   for item in messages)
        assert [item['kind'] for item in early[-3:]] == [
            'state3-module-ready', 'observer-ready', 'exit-boundary-armed']
        ready = early[-3]['data']
        assert ready == dict(module='unityplayer.dll', hooks=[
            dict(key=key, rva=rva) for key, rva in EXPECTED.items()], errors=[])
        exits = [item for item in messages if item['kind'] == 'self-terminate-entry']
        assert len(exits) == 1
        boundary = exits[0]
        assert boundary['data']['exitStatus'] == 0
        assert boundary['data']['api'].endswith(':TerminateProcess')
        assert boundary['data']['transportHoldMs'] == 200
        assert boundary['data']['state3Counts'] == dict.fromkeys(EXPECTED, 0)
        assert boundary['data']['state3First'] == dict.fromkeys(EXPECTED, [])
        assert boundary['data']['state3Hooks'] == ready['hooks']
        assert boundary['data']['state3Errors'] == []
        assert boundary['data']['errors'] == [] and boundary['data']['overflow'] is False
        assert not any(item['kind'] in ('self-terminate-returned', 'decode-error',
                                        'budget-exceeded') for item in messages)
        suffix = messages[messages.index(boundary) + 1:]
        assert all(item['kind'] == 'heartbeat' and item['data']['errors'] == []
                   for item in suffix)
        clients.append(dict(index=index, pid=pid, session_id=sid,
                            state3_counts=boundary['data']['state3Counts'],
                            load_evidence_id=load['evidence_id'],
                            final_evidence_id=final['evidence_id']))
    return dict(passed=True, clients=clients, network_review=network,
                verification_sha256=sha(CASE / 'verification.json'),
                bundle_sha256=sha(TRACE / 'rea-evidence.json'),
                scope='Selected four UnityPlayer entries in current private public1 two-human match from suspended start to first original self-TerminateProcess entry; other routes, state writers, queue, whole wire and final installed release remain open',
                full_d5_qualified=False)


if __name__ == '__main__':
    result = review()
    output = CASE / 'state3-review.json'
    if output.exists():
        assert json.loads(output.read_text(encoding='utf-8')) == result
    else:
        output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, clients=result['clients'])))
