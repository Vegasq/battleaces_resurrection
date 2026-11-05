"""Review prelaunch native advertising entry witnesses on recipe47 modes."""
from __future__ import annotations

import json
from pathlib import Path

from tools.frida_ads_caller import describe_unity
from tools.frida_ads_connected527 import build_source
from tools.review_ads_callback_slots403 import ORIGINAL
from tools.review_unity_post512 import ROOT, review as review_public1
from tools.review_recipe47_queue_connected524 import sha256

PACKAGES = ROOT / 'local/privacy512-packages01'
GAME = ROOT / 'local/privacy512-game01'
ASSETS = ROOT / 'local/s139/assets/build-37822'


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def review_case(case: Path, trace: Path, mode: int, humans: int,
                custom: bool = False) -> dict:
    bound = review_public1()
    assert bound['passed'] and bound['recipe'] == 47
    report = read(case / 'verification.json')
    assert report['passed'] and report['rc_open'] and report['prelaunch_observer']
    assert report['packages'] == str(PACKAGES.resolve())
    assert report['mode'] == mode and report['humans'] == humans
    assert report['custom_rematch'] is custom
    assert report['forced_cleanup'] is False
    assert all(report[key] is True for key in
               ('package_files_unchanged', 'assets_unchanged',
                'source_files_unchanged', 'shared_channels_unchanged'))
    if custom:
        assert report['custom']['epochs'] == [1, 2]
        assert len(report['custom']['matches']) == 2
        assert all(len(client['rounds']) == 2 for client in report['custom']['clients'])
    else:
        assert report['match']['result']['complete']
    assert all(job['active_processes'] == job['total_terminated_processes'] == 0
               for job in report['jobs'])
    assert len(report['clients']) == len(report['prelaunch_resume']) == humans
    unity = describe_unity(ORIGINAL.read_bytes(), (GAME / 'UnityPlayer.dll').read_bytes())
    bundle = read(trace / 'rea-evidence.json')
    sessions = read(trace / 'sessions.json')
    for index in range(humans):
        client = report['clients'][index]
        session = sessions[str(index)]
        cfg = read(trace / f'config-{index}.json')
        path = trace / f'observer-{index}.js'
        assert client['pid'] == session['pid'] == cfg['config']['pid']
        assert client['driver_report']['passed']
        assert client['driver_report']['game_exit_code'] == 0
        assert report['prelaunch_resume'][index]['pid'] == session['pid']
        assert cfg['config']['bodySha256'] == unity['bodySha256']
        assert cfg['config']['image'] == str(GAME / 'Battle Aces.exe')
        assert cfg['config']['unity'] == str(GAME / 'UnityPlayer.dll')
        assert path.read_bytes() == build_source(cfg['config']).encode()
        assert cfg['source_sha256'] == sha256(path)
        records = [record for record in bundle['records']
                   if record.get('parameters', {}).get('session_id') == session['session_id']]
        loads = [record['normalized_result'] for record in records
                 if record['operation'] == 'load_frida_script']
        statuses = [record['normalized_result'] for record in records
                    if record['operation'] == 'frida_session_status']
        assert len(loads) == len(statuses) == 1
        assert loads[0]['script_id'] == session['script_id']
        assert loads[0]['source_sha256'] == sha256(path)
        status = statuses[0]
        assert status['state'] == 'detached' and not status['messages_truncated']
        assert status['pid'] == session['pid']
        messages = status['messages']
        assert all(message['type'] == 'send' for message in messages)
        assert all(message['payload']['runId'] == cfg['config']['runId']
                   for message in messages)
        assert [message['payload']['kind'] for message in messages] == [
            'observer-ready', 'script-ready', 'self-terminate-entry']
        ready = messages[0]['payload']['data']
        assert ready['handler'] == '0x0' and ready['exitHooks'] >= 1
        assert ready['bodySha256'] == unity['bodySha256']
        end = messages[-1]['payload']['data']
        assert end['exitCode'] == 0 and end['handler'] == '0x0'
        assert end['constructorCalls'] == end['callbackCalls'] == end['sendRequestCalls'] == 0
        assert end['errors'] == []
    return {'passed': True, 'mode': mode, 'humans': humans, 'custom': custom,
            'report_sha256': sha256(case / 'verification.json'),
            'bundle_sha256': sha256(trace / 'rea-evidence.json'),
            'unity_sha256': unity['fileSha256']}


if __name__ == '__main__':
    cases = (
        ('public1', 'privacy530-public1-ads01', 'privacy530-trace01', 1, 2, False),
        ('public2', 'privacy527-public2-ads01', 'privacy527-trace01', 2, 4, False),
        ('public5', 'privacy528-public5-ads01', 'privacy528-trace01', 5, 2, False),
        ('custom', 'privacy529-custom-ads01', 'privacy529-trace01', 1, 2, True),
    )
    results = {name: review_case(ROOT / 'local' / case, ROOT / 'local' / trace,
                                 mode, humans, custom)
               for name, case, trace, mode, humans, custom in cases}
    print(json.dumps({'passed': True, 'runs': results}, sort_keys=True))
