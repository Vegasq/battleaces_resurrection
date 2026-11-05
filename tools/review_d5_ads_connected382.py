"""Independently review the bounded current connected advertising caller interval."""
from __future__ import annotations

import json
from pathlib import Path

from client_patch.patcher.telemetry import RECIPE_VERSION, RUNTIME_VALIDATED
from tools.ads_connected382 import GAME, ROOT, ORIGINAL, sha, source_for
from tools.frida_ads_caller import CALLBACK_RVA, CALLBACK_SIZE, EVENT_LIMIT, describe_unity
from tools.package_integrity import verify

CASE = ROOT / 'local/privacy382-ads-connected01'
TRACE = ROOT / 'local/privacy382-ads-connected-trace01'
PACKAGES = ROOT / 'local/privacy358-packages02'
ASSETS = ROOT / 'local/s139/assets/build-37822'


def read(path: Path):
    return json.loads(path.read_bytes())


def review():
    report, prepare, evidence = (read(path) for path in
        (CASE / 'verification.json', TRACE / 'prepare.json', TRACE / 'rea-evidence.json'))
    manifest = read(GAME / '.battleaces-resurrection/patch-manifest.json')
    descriptor = describe_unity(ORIGINAL.read_bytes(), (GAME / 'UnityPlayer.dll').read_bytes())
    assert report['passed'] is True and report['forced_cleanup'] is False
    assert report['prelaunch_observer'] is True and report['rc_open'] is True
    assert report['mode'] == 1 and report['humans'] == 2 and report['custom_rematch'] is False
    assert report['packages'] == str(PACKAGES)
    assert report['assets_manifest_sha256'] == sha(ASSETS / 'asset-manifest.json')
    assert manifest['telemetry']['recipe_version'] == RECIPE_VERSION == descriptor['recipe'] == 38
    assert manifest['telemetry']['runtime_validated'] is RUNTIME_VALIDATED is False
    assert sha(GAME / 'GameAssembly.dll') == manifest['patched_sha256']
    assert sha(GAME / 'BattleAcesOffline.dll') == manifest['helper_sha256']
    assert report['helper_build']['receipt']['helper_sha256'] == manifest['helper_sha256']
    assert sha(PACKAGES / 'battleaces-client-win64/program/client-helper/BattleAcesOffline.dll') == manifest['helper_sha256']
    assert prepare['prepared'] is True and prepare['diagnostic_only'] is True
    assert prepare['case'] == str(CASE) and prepare['game'] == str(GAME)
    assert prepare['descriptor'] == descriptor and evidence['schema'] == 1
    assert len(report['clients']) == len(prepare['clients']) == len(evidence['clients']) == 2
    assert [job['total_processes'] for job in report['jobs']] == [5, 2, 2]
    assert all(job['active_processes'] == job['total_terminated_processes'] == 0 for job in report['jobs'])
    assert all(row['reaped'] and row['exit_code'] == 0 for row in report['worker_cleanup'])
    for key in ('source_files_unchanged', 'shared_channels_unchanged',
                'adapters_unchanged', 'config_unchanged', 'package_files_unchanged',
                'assets_unchanged', 'fixture_tokens_not_logged', 'temporary_pki_removed'):
        assert report[key] is True, key
    for kind in ('client', 'server'):
        assert verify(PACKAGES / f'battleaces-{kind}-win64', kind)
    clients = []
    for index in range(2):
        config = read(TRACE / f'config-{index}.json')
        process = read(CASE / f'client-{index}/game-process.json')
        row = evidence['clients'][index]
        start, loaded, final = (row[name] for name in ('start', 'load', 'final'))
        pid, sid = process['pid'], start['session_id']
        assert process['suspended_for_observer'] is True
        assert pid == config['pid'] == report['clients'][index]['pid'] == prepare['clients'][index]['pid']
        assert report['prelaunch_resume'][index]['pid'] == pid
        assert process['actual_arguments'] == config['argv'] and config['image'] == str(GAME / 'Battle Aces.exe')
        assert config['unity'] == descriptor
        assert (CASE / f'client-{index}/observer-ready').read_bytes() == b'FRIDA_READY\n'
        assert (CASE / f'client-{index}/game-process.json').stat().st_mtime_ns < (CASE / f'client-{index}/observer-ready').stat().st_mtime_ns
        script = TRACE / f'observer-{index}.js'
        assert script.read_text(encoding='utf-8') == source_for(config)
        assert sha(script) == prepare['clients'][index]['script_sha256']
        assert start['pid'] == pid and start['mode'] == 'attach' and start['device_id'] == 'local'
        assert loaded['operation'] == 'load_frida_script' and loaded['parameters']['session_id'] == sid
        assert loaded['normalized_result']['source_sha256'] == sha(script)
        assert loaded['normalized_result']['source_path'] == str(script)
        assert final['operation'] == 'frida_session_status' and final['parameters']['session_id'] == sid
        assert final['normalized_result']['state'] == 'detached' and final['normalized_result']['pid'] == pid
        assert final['normalized_result']['messages_truncated'] is False
        messages = final['normalized_result']['messages']
        assert loaded['normalized_result']['messages'] == messages[:3]
        assert len(messages) == 5 and all(m['type'] == 'send' and m['script_id'] == loaded['normalized_result']['script_id'] for m in messages)
        payloads = [m['payload'] for m in messages]
        assert [p['kind'] for p in payloads] == ['ads-ready', 'ads-installed', 'ads-exit-armed', 'ads-finished', 'ads-exit-entry']
        assert all(p['pid'] == pid and p['runId'] == config['runId'] for p in payloads)
        assert [p['seq'] for p in (payloads[0], payloads[1], payloads[3])] == [1, 2, 3]
        assert [p['elapsedMs'] for p in payloads] == sorted(p['elapsedMs'] for p in payloads)
        assert payloads[0]['data'] == dict(profile='ads-caller180-v1', fieldAuditCompatible=False,
                                            argumentsRead=False, targetApisInvoked=False)
        assert payloads[1]['data'] == dict(module=str(GAME / 'UnityPlayer.dll'), descriptor=descriptor,
                                            callbackRva=CALLBACK_RVA, bodySize=CALLBACK_SIZE,
                                            eventLimit=EVENT_LIMIT)
        assert payloads[2]['data']['exports'] == 2 and payloads[2]['data']['uniqueHooks'] in (1, 2)
        assert payloads[2]['data']['transportHoldMs'] == 200
        assert payloads[3]['data'] == dict(installed=True, failed=False, finished=True,
                                            calls=0, records=0, suppressed=0, guardIntact=True,
                                            hookDetached=True)
        assert payloads[4]['data']['exitStatus'] == 0
        assert payloads[4]['data']['currentProcessPseudoHandle'] is True
        assert payloads[4]['data']['callerFinished'] is True
        assert payloads[4]['data']['transportHoldMs'] == 200
        assert report['clients'][index]['driver_report']['game_exit_code'] == 0
        assert report['clients'][index]['driver_report']['launcher_exit_code'] == 0
        clients.append(dict(index=index, pid=pid, calls=0, session_id=sid,
                            load_evidence_id=loaded['evidence_id'], final_evidence_id=final['evidence_id']))
    return dict(passed=True, clients=clients, verification_sha256=sha(CASE / 'verification.json'),
                evidence_sha256=sha(TRACE / 'rea-evidence.json'),
                scope='Current recipe38 private public1 two-client callback interval from prelaunch script installation to first self-TerminateProcess entry',
                producer_resolved=False, whole_process_coverage=False, full_d5_qualified=False)


if __name__ == '__main__':
    result = review()
    (CASE / 'ads-review.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
