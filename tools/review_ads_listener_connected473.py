"""Review the two-client recipe39 listener-count watch as a bounded D5 result."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.build_ads_listener_connected473 import GAME, OUT, SOURCE
from tools.review_ads_watchpoint471 import review as review_control
from tools.verify_historical_pair473 import PACKAGES, PRIOR, RECEIPT, digest, pinned_receipt


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def review() -> dict:
    assert review_control()['passed'] is True
    report = load(OUT / 'verification.json')
    assert report['passed'] is True and report['forced_cleanup'] is False
    assert report['prelaunch_observer'] is True and report['rc_open'] is True
    assert report['mode'] == 1 and report['humans'] == 2 and report['match']['frames'] >= 1200
    assert report['packages'] == str(PACKAGES) and report['helper_build'] == pinned_receipt(GAME.parent, RECEIPT)
    assert report['helper_build']['prior_report_sha256'] == digest(PRIOR)
    assert all(report[k] is True for k in ('adapters_unchanged', 'config_unchanged',
        'package_files_unchanged', 'assets_unchanged', 'shared_channels_unchanged',
        'source_files_unchanged', 'temporary_pki_removed'))
    assert len(report['jobs']) == 3
    assert [(x['total_processes'], x['active_processes'], x['total_terminated_processes'])
            for x in report['jobs']] == [(5, 0, 0), (2, 0, 0), (2, 0, 0)]
    assert len(report['clients']) == len(report['prelaunch_resume']) == 2
    assert all(c['driver_report']['passed'] is True and
               c['driver_report']['game_exit_code'] == 0 for c in report['clients'])
    baseline = SOURCE.read_text(encoding='utf-8')
    results = []
    for index in (0, 1):
        folder = OUT / f'client-{index}'
        process = load(folder / 'game-process.json')
        binding = load(folder / 'listener-watch-binding.json')
        status = load(folder / 'rea-status.json')
        pid = report['clients'][index]['pid']
        assert process['pid'] == pid == binding['pid'] == report['prelaunch_resume'][index]['pid']
        assert process['actual_arguments'][0] == str(GAME)
        assert binding['game_sha256'] == digest(GAME)
        assert binding['source_sha256'] == digest(SOURCE)
        script = (folder / 'listener-watch.js').read_text(encoding='utf-8')
        expected = baseline.replace(
            "const expectedPid=49300,runId='4a015a7f4456323dccaf8bcbc70f470d';",
            f"const expectedPid={pid},runId='{binding['run_id']}';")
        assert script == expected and binding['script_sha256'] == digest(folder / 'listener-watch.js')
        assert (folder / 'observer-ready').read_bytes() == b'FRIDA_READY\n'
        assert status['provider']['id'] == 'frida' and status['confidence'] == 'observed'
        result = status['normalized_result']
        assert result['pid'] == pid and result['state'] == 'detached'
        assert result['messages_truncated'] is False and len(result['scripts']) == 1
        messages = result['messages']
        assert len(messages) == 6
        assert all(m['type'] == 'send' and m['script_id'] == result['scripts'][0]['script_id']
                   for m in messages)
        rows = [m['payload'] for m in messages]
        assert all(x['schema'] == 1 and x['seq'] == n and x['pid'] == pid and
                   x['runId'] == binding['run_id'] for n, x in enumerate(rows, 1))
        assert [x['kind'] for x in rows] == ['observer-ready', 'script-ready',
            'constructor-watch-ready', 'destructor-entry', 'self-terminate-entry', 'self-terminate-entry']
        ready, _, constructor, destructor, *terms = [x['data'] for x in rows]
        assert ready['initial']['global'] is None and ready['exitHooks'] == 2
        assert constructor['initialCount'] == '0' and len(constructor['watchedThreads']) >= 4
        assert int(constructor['watchAddress'], 16) - int(constructor['handler'], 16) == 0x80
        assert destructor['state']['global'] == constructor['handler']
        assert destructor['state']['count'] == '0' and destructor['state']['selfLinked'] is True
        assert destructor['owner'] == hex(int(ready['moduleBase'], 16) + 0x1c0af00)
        assert destructor['hits'] == 0 and len(destructor['watchedThreads']) >= 4
        assert {x['api'] for x in terms} == {'kernelbase.dll', 'kernel32.dll'}
        assert all(x['exitCode'] == 0 and x['hits'] == 0 and x['errors'] == [] and
                   x['state']['global'] is None for x in terms)
        results.append(dict(pid=pid, watched_threads_at_destructor=len(destructor['watchedThreads']),
                            native_listener_count_writes=0, evidence_id=status['evidence_id'],
                            script_sha256=binding['script_sha256'], status_sha256=digest(folder / 'rea-status.json')))
    return dict(passed=True, scope='recipe39 private public1 two-human match,constructor-return to destructor-entry',
                verifier_sha256=digest(OUT / 'verification.json'),
                wrapper_sha256=digest(Path(__file__).with_name('verify_historical_pair473.py')),
                clients=results)


if __name__ == '__main__':
    result = review()
    (OUT / 'review473.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
