"""Bind the private recipe44 pair to public2/public5/Custom mode reports."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.review_recipe44_connected490 import PACKAGES, ROOT, review as review_public1


RUNS = {
    'public2': (ROOT / 'local/privacy496-public2-01', 2, 4, False),
    'public5': (ROOT / 'local/privacy496-public5-01', 5, 2, False),
    'custom': (ROOT / 'local/privacy496-custom-01', 1, 2, True),
}
QUIT_EVENTS = ['armed', 'Show.dispatch', 'Show.return',
               'OnConfirm.dispatch', 'OnConfirm.return']


def review() -> dict:
    bound = review_public1()
    assert bound['passed'] and bound['recipe'] == 44
    findings = {}
    for name, (folder, mode, humans, custom) in RUNS.items():
        path = folder / 'verification.json'
        raw = path.read_bytes()
        report = json.loads(raw)
        assert report['passed'] is True and report['forced_cleanup'] is False
        assert report['packages'] == str(PACKAGES.resolve())
        assert (report['mode'], report['humans'], report['rc_open'],
                report['custom_rematch']) == (mode, humans, True, custom)
        assert report['real_credentials'] is False
        assert len(report['clients']) == humans
        for client in report['clients']:
            assert client['driver_report']['passed'] is True
            assert client['driver_report']['game_exit_code'] == 0
            assert [event['event'] for event in client['trace']] == QUIT_EVENTS
        if custom:
            result = report['custom']
            assert result['epochs'] == [1, 2] and len(result['matches']) == 2
            assert len(result['clients']) == humans
            for client in result['clients']:
                assert [round_['match'] for round_ in client['rounds']] == result['matches']
                assert all(round_['frames'] >= 1200 for round_ in client['rounds'])
            frames = [round_['frames'] for round_ in result['clients'][0]['rounds']]
        else:
            assert report['match']['frames'] >= 1200
            assert report['match']['result']['complete'] is True
            frames = [report['match']['frames']]
        assert all(worker['exit_code'] == 0 and worker['reaped']
                   for worker in report['worker_cleanup'])
        assert len(report['jobs']) == humans + 1
        assert all(job['active_processes'] == job['total_terminated_processes'] == 0
                   for job in report['jobs'])
        assert report['server']['listener_closed'] is True
        assert report['server']['state_lock_released'] is True
        assert all(report[key] is True for key in (
            'package_files_unchanged', 'assets_unchanged',
            'shared_channels_unchanged', 'source_files_unchanged',
            'temporary_pki_removed'))
        findings[name] = {'report_sha256': hashlib.sha256(raw).hexdigest(),
                          'frames': frames, 'client_exit_codes': [0] * humans,
                          'worker_count': len(report['worker_cleanup'])}
    return {'passed': True, 'recipe': 44,
            'public1_report_sha256': bound['report_sha256'],
            'package_sha256': bound['package_sha256'],
            'installed_gameassembly_sha256': bound['installed_gameassembly_sha256'],
            'runs': findings,
            'privacy_queue_or_wire_proved': False}


if __name__ == '__main__':
    result = review()
    out = ROOT / 'local/privacy496-modes-review01.json'
    out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, sort_keys=True))
