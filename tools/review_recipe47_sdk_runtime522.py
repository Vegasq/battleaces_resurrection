"""Review recipe47 public1 SDK entry/file/network attribution from prelaunch."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.extract_descriptors import PE
from tools.frida_sdk_queue440 import ENTRIES, GUARDED, build_source
from tools.review_d5_exit_network368 import payloads, records_for
from tools.review_unity_post512 import GAME, ROOT, review as review_recipe47

CASE = ROOT / 'local/privacy522-public1-01'
TRACE = ROOT / 'local/privacy522-trace01'


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review() -> dict:
    source = review_recipe47()
    assert source['passed'] and source['recipe'] == 47
    report = read(CASE / 'verification.json')
    sessions = read(TRACE / 'sessions.json')
    bundle = read(TRACE / 'rea-evidence.json')
    assert report['passed'] and report['prelaunch_observer'] is True
    assert not report['forced_cleanup'] and (report['mode'], report['humans'], report['rc_open']) == (1, 2, True)
    assert not report['real_credentials'] and report['match']['frames'] >= 1200
    assert report['match']['result']['complete'] is True
    assert all(row['reaped'] and row['exit_code'] == 0 for row in report['worker_cleanup'])
    assert len(report['jobs']) == 3
    assert all(row['active_processes'] == row['total_terminated_processes'] == 0
               for row in report['jobs'])
    assert report['server']['listener_closed'] and report['server']['state_lock_released']
    assert all(report[key] is True for key in (
        'package_files_unchanged', 'assets_unchanged', 'shared_channels_unchanged',
        'source_files_unchanged', 'temporary_pki_removed'))
    assert sessions['case'] == 'local/' + CASE.name
    assert [row['index'] for row in sessions['clients']] == [0, 1]
    image = PE((GAME / 'GameAssembly.dll').read_bytes())
    for name, (rva, expected) in (GUARDED | ENTRIES).items():
        offset = image.offset(image.base + rva, 16)
        assert image.data[offset:offset + 16].hex() == expected, name
    expected_hooks = [dict(key=key, rva=entry[0]) for key, entry in ENTRIES.items()]
    clients = []
    for row in sessions['clients']:
        index, pid, session = row['index'], row['pid'], row['session_id']
        client = report['clients'][index]
        assert client['pid'] == pid and client['driver_report']['passed']
        assert client['driver_report']['game_exit_code'] == 0
        assert client['driver_report']['launcher_exit_code'] == 0
        assert [event['event'] for event in client['trace']] == [
            'armed', 'Show.dispatch', 'Show.return', 'OnConfirm.dispatch', 'OnConfirm.return']
        process = read(CASE / f'client-{index}/game-process.json')
        gate = CASE / f'client-{index}/observer-ready'
        assert process['pid'] == pid and process['suspended_for_observer'] is True
        assert gate.read_bytes() == b'FRIDA_READY\n' and process['pid'] == report['prelaunch_resume'][index]['pid']
        assert (CASE / f'client-{index}/game-process.json').stat().st_mtime_ns < gate.stat().st_mtime_ns
        config = read(TRACE / f'config-{index}.json')
        assert config['sdk_queue'] and config['unresolved_file_status'] and config['exit_boundary']
        assert config['game_sha256'] == sha(GAME / 'Battle Aces.exe')
        observer = TRACE / f'observer-{index}.js'
        assert observer.read_text(encoding='utf-8') == build_source(config['config'])
        assert config['source_sha256'] == sha(observer)
        loads = records_for(bundle, session, 'load_frida_script')
        finals = [item for item in records_for(bundle, session, 'frida_session_status')
                  if item['normalized_result'].get('state') == 'detached']
        assert len(loads) == len(finals) == 1
        load, final = loads[0], finals[0]
        assert load['normalized_result']['source_sha256'] == sha(observer)
        early, messages = payloads(load), payloads(final)
        assert messages[:len(early)] == early and not final['normalized_result']['messages_truncated']
        assert [item['kind'] for item in early[-2:]] == ['observer-ready', 'exit-boundary-armed']
        assert all(item['pid'] == pid and item['runId'] == config['config']['runId'] for item in messages)
        ready = [item for item in messages if item['kind'] == 'sdk-module-ready']
        assert len(ready) == 1 and ready[0]['data'] == dict(hooks=expected_hooks, errors=[])
        boundary = [item for item in messages if item['kind'] == 'self-terminate-entry']
        assert len(boundary) == 1 and boundary[0] == messages[-1]
        assert ready[0]['seq'] < boundary[0]['seq']
        data = boundary[0]['data']
        assert data['exitStatus'] == 0 and data['sdkHooks'] == expected_hooks and data['sdkErrors'] == []
        assert data['sdkCounts'] == {key: 0 for key in ENTRIES}
        assert data['errors'] == [] and data['overflow'] is False and data['unknownRelativeRoots'] == 0
        assert data['counts']['ws2_32.dll:send'] > 0 and data['counts']['ws2_32.dll:recv'] > 0
        assert not any(item['kind'] in ('sdk-entry', 'file-operation', 'network-operation',
                         'process-create', 'budget-exceeded', 'decode-error') for item in messages)
        unresolved = [item for item in messages if item['kind'] == 'unresolved-file-operation']
        assert len(unresolved) == 9
        assert all(item['data']['operation'] == 'NtWriteFile' and
                   item['data']['returnValue'] == -1073741816 for item in unresolved)
        clients.append(dict(index=index, pid=pid, sdk_counts=data['sdkCounts'],
                            bridge_send=data['counts']['ws2_32.dll:send'],
                            bridge_recv=data['counts']['ws2_32.dll:recv'],
                            unresolved_failed_invalid_handle_writes=9))
    return dict(passed=True, recipe=47, scope='owned public1 pre-resume through self-exit',
                clients=clients, source_review_passed=True,
                verifier_sha256=sha(CASE / 'verification.json'),
                rea_bundle_sha256=sha(TRACE / 'rea-evidence.json'),
                guarded_entry_bytes_checked=len(GUARDED), hooked_active_entries=len(ENTRIES),
                real_sdk_queue_observed=False, whole_wire_observed=False,
                native_ads_provider_resolved=False, final_installed=False)


if __name__ == '__main__':
    result = review()
    (CASE / 'sdk-route-review522.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, clients=len(result['clients']),
                          guarded=result['guarded_entry_bytes_checked'],
                          hooks=result['hooked_active_entries'])))
