"""Bind one owned current-recipe connected match to its package and lifecycle."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(case: Path, packages: Path, game: Path, assets: Path) -> dict:
    report_path = case / 'verification.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    build = json.loads((packages / 'build-report.json').read_text(encoding='utf-8'))
    manifest = json.loads((game / '.battleaces-resurrection/patch-manifest.json').read_text(encoding='utf-8'))
    assert report['passed'] and report['forced_cleanup'] is False
    assert report['rc_open'] and report['mode'] == 1 and report['humans'] == 2
    assert Path(report['packages']).resolve() == packages
    assert report['assets_manifest_sha256'] == sha(assets / 'asset-manifest.json')
    assert report['helper_build']['receipt']['helper_sha256'] == manifest['helper_sha256']
    assert sha(game / 'BattleAcesOffline.dll') == manifest['helper_sha256']
    assert sha(game / 'GameAssembly.dll') == manifest['patched_sha256']
    assert build['versions']['game_build'] == 37822 and build['versions']['platform'] == 'windows-amd64'
    archives = {}
    for kind in ('client', 'server'):
        entry = build['packages'][kind]
        actual = sha(packages / entry['archive'])
        assert actual == entry['sha256']
        archives[kind] = actual
    assert sha(ROOT / 'client_patch/patcher/telemetry.py') == sha(
        packages / 'battleaces-client-win64/program/app/client_patch/patcher/telemetry.py')
    for key in ('source_files_unchanged', 'shared_channels_unchanged',
                'adapters_unchanged', 'config_unchanged', 'package_files_unchanged',
                'assets_unchanged', 'fixture_tokens_not_logged', 'temporary_pki_removed'):
        assert report[key] is True, key

    match = report['match']
    assert match['mode'] == 1 and match['full_human_group']
    assert match['human_seats'] == [0, 1] and match['bot_seats'] == []
    assert match['frames'] >= 1200 and match['result']['complete']
    assert len(match['clients']) == len(report['clients']) == 2
    for client in report['clients']:
        driver = client['driver_report']
        assert driver['passed'] and driver['launcher_exit_code'] == 0
        assert driver['game_exit_code'] == 0
    server = report['server']
    assert server['passed'] and server['listener_closed']
    assert server['state_lock_released'] and server['status_writer_drained']
    assert len(server['workers']) == 2
    assert all(w['exit_code'] == 0 and w['reaped'] and w['failure'] is None
               for w in server['workers'])
    for key in ('active_workers', 'rooms', 'retired', 'entries', 'offers',
                'cleanup', 'sessions'):
        assert server['final_state'][key] == 0, key
    assert server['final_state']['lobbies'] == []
    assert len(report['jobs']) == 3
    assert [job['total_processes'] for job in report['jobs']] == [5, 2, 2]
    assert all(job['active_processes'] == job['total_terminated_processes'] == 0
               for job in report['jobs'])

    return {
        'passed': True,
        'scope': 'Owned recipe34 private package pair, RC-open loopback public1 two-human match and normal shutdown; no privacy file or wire capture',
        'report_sha256': sha(report_path),
        'package_archives_sha256': archives,
        'game_helper_sha256': manifest['helper_sha256'],
        'game_assembly_sha256': manifest['patched_sha256'],
        'game_unity_sha256': sha(game / 'UnityPlayer.dll'),
        'mode': match['mode'],
        'human_clients': len(report['clients']),
        'frames': match['frames'],
        'match_complete': match['result']['complete'],
        'client_game_exit_codes': [client['driver_report']['game_exit_code'] for client in report['clients']],
        'worker_exit_codes': [worker['exit_code'] for worker in server['workers']],
        'jobs': [{key: job[key] for key in ('total_processes', 'active_processes',
                                             'total_terminated_processes')}
                 for job in report['jobs']],
        'source_and_shared_unchanged': True,
        'privacy_file_wire_qualified': False,
        'full_d5_qualified': False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('case', 'packages', 'game', 'assets'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in ('case', 'packages', 'game', 'assets')}
    assert all(path.is_relative_to(ROOT / 'local') for path in paths.values())
    result = run(**paths)
    output = paths['case'] / 'review.json'
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': result['passed'], 'review': str(output),
                      'frames': result['frames'], 'jobs': result['jobs']}))


if __name__ == '__main__':
    main()
