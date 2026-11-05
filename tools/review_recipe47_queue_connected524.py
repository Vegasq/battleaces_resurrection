"""Read-only, bounded review of the owned two-client queue run."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.frida_sdk_queue440 import ENTRIES
from tools.telemetry_preexisting_seed import snapshot


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review_case(run: Path, trace: Path) -> dict:
    report_path = run / 'verification.json'
    bundle_path = trace / 'rea-evidence.json'
    report = json.loads(report_path.read_text())
    bundle = json.loads(bundle_path.read_text())
    sessions = json.loads((trace / 'sessions.json').read_text())
    assert report['passed'] is True and report['rc_open'] and report['mode'] == 1
    assert report['humans'] == 2 and report['prelaunch_observer']
    assert report['preexisting_sdk_queue'] and report['preexisting_queue_unchanged']
    assert all(report[key] for key in ('source_files_unchanged',
        'package_files_unchanged', 'assets_unchanged',
        'adapters_unchanged', 'shared_channels_unchanged'))
    assert report['match']['result']['complete'] and len(report['match']['human_seats']) == 2
    assert all(job['active_processes'] == 0 and
               job['total_terminated_processes'] == 0 for job in report['jobs'])
    assert len(report['prelaunch_resume']) == 2
    assert len(report['preexisting_queue_before']) == 2
    assert len(report['preexisting_queue_after']) == 2
    for index in (0, 1):
        client = report['clients'][index]
        session = sessions[str(index)]
        before = report['preexisting_queue_before'][index]
        after = report['preexisting_queue_after'][index]
        config = json.loads((trace / f'config-{index}.json').read_text())
        script = trace / f'observer-{index}.js'
        assert client['pid'] == session['pid']
        assert client['driver_report']['passed']
        assert client['driver_report']['game_exit_code'] == 0
        assert client['driver_report']['launcher_exit_code'] == 0
        assert report['prelaunch_resume'][index]['pid'] == session['pid']
        assert before == after and before['files'] == snapshot(Path(before['root']))
        assert config['profile'] == client['profile']
        assert config['source_sha256'] == sha256(script)
        assert Path(before['root']).resolve() == Path(config['config']['fileRoots'][1]).resolve()
        records = [record for record in bundle['records']
                   if record.get('parameters', {}).get('session_id') == session['session_id']]
        loads = [record for record in records if record['operation'] == 'load_frida_script']
        statuses = [record for record in records if record['operation'] == 'frida_session_status']
        assert len(loads) == len(statuses) == 1
        loaded = loads[0]['normalized_result']
        status = statuses[0]['normalized_result']
        assert loaded['script_id'] == session['script_id']
        assert loaded['source_sha256'] == sha256(script)
        assert status['state'] == 'detached' and not status['messages_truncated']
        assert status['pid'] == session['pid']
        messages = status['messages']
        assert all(message['type'] == 'send' for message in messages)
        assert all(message['payload']['runId'] == config['config']['runId'] for message in messages)
        kinds = [message['payload']['kind'] for message in messages]
        assert kinds.count('observer-ready') == 1
        assert kinds.count('exit-boundary-armed') == 1
        assert kinds.count('sdk-module-ready') == 1
        assert kinds.count('self-terminate-entry') == 1
        assert not any(kind in ('file-operation', 'sdk-entry') for kind in kinds)
        ready = next(message['payload']['data'] for message in messages
                     if message['payload']['kind'] == 'sdk-module-ready')
        assert not ready['errors']
        assert {hook['key'] for hook in ready['hooks']} == set(ENTRIES)
        exit_data = next(message['payload']['data'] for message in messages
                         if message['payload']['kind'] == 'self-terminate-entry')
        assert exit_data['exitStatus'] == 0
        assert not exit_data['sdkErrors'] and not exit_data['overflow']
        assert exit_data['sdkCounts'] == dict.fromkeys(ENTRIES, 0)
        counts = exit_data['counts']
        assert counts['ws2_32.dll:send'] > 0 and counts['ws2_32.dll:recv'] > 0
        assert counts['winhttp.dll:WinHttpConnect'] == 0
        assert exit_data['unresolvedFileOps'] == 9
    return {'passed': True, 'report_sha256': sha256(report_path),
            'bundle_sha256': sha256(bundle_path), 'sessions': 2}


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(review_case(root / 'local/privacy524-public1-queue01',
                                 root / 'local/privacy524-trace01')))


if __name__ == '__main__':
    main()
