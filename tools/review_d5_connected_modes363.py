"""Bind current private recipe38 public 2vAI/2v2 runs to their artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from client_patch.patcher.telemetry import RECIPE_VERSION, RUNTIME_VALIDATED
from tools.package_integrity import verify
from tools.review_d5_connected_pair338 import ROOT, sha


def check(case: Path, mode: int, packages: Path, game: Path,
          assets: Path, helper_receipt: Path) -> dict:
    report_path = case / 'verification.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    manifest = json.loads((game / '.battleaces-resurrection/patch-manifest.json').read_text(encoding='utf-8'))
    receipt = json.loads(helper_receipt.read_text(encoding='utf-8'))
    assert report['passed'] and report['forced_cleanup'] is False
    assert report['rc_open'] and report['mode'] == mode and report['humans'] == 2
    assert Path(report['packages']).resolve() == packages
    assert report['assets_manifest_sha256'] == sha(assets / 'asset-manifest.json')
    assert report['helper_build']['sha256'] == sha(helper_receipt)
    assert report['helper_build']['receipt']['helper_sha256'] == receipt['helper_sha256']
    assert manifest['telemetry']['recipe_version'] == RECIPE_VERSION == 38
    assert manifest['telemetry']['runtime_validated'] is RUNTIME_VALIDATED is False
    assert manifest['helper_sha256'] == receipt['helper_sha256']
    assert sha(game / 'BattleAcesOffline.dll') == receipt['helper_sha256']
    assert sha(game / 'GameAssembly.dll') == manifest['patched_sha256']
    assert sha(packages / 'battleaces-client-win64/program/client-helper/BattleAcesOffline.dll') == receipt['helper_sha256']
    for kind in ('client', 'server'):
        assert verify(packages / f'battleaces-{kind}-win64', kind)
    for key in ('source_files_unchanged', 'shared_channels_unchanged',
                'adapters_unchanged', 'config_unchanged', 'package_files_unchanged',
                'assets_unchanged', 'fixture_tokens_not_logged', 'temporary_pki_removed'):
        assert report[key] is True, key
    match = report['match']
    assert match['mode'] == mode and match['full_human_group'] is (mode == 5)
    assert match['human_seats'] == ([0, 1] if mode == 2 else [0, 2])
    assert match['bot_seats'] == ([2, 3] if mode == 2 else [1, 3])
    assert match['frames'] >= 1200 and match['result']['complete']
    assert len(match['clients']) == len(report['clients']) == 2
    assert all(client['driver_report']['passed'] and
               client['driver_report']['launcher_exit_code'] == 0 and
               client['driver_report']['game_exit_code'] == 0
               for client in report['clients'])
    server = report['server']
    assert server['passed'] and server['listener_closed']
    assert server['state_lock_released'] and server['status_writer_drained']
    assert len(server['workers']) == 2
    assert all(worker['exit_code'] == 0 and worker['reaped'] and worker['failure'] is None
               for worker in server['workers'])
    for key in ('active_workers', 'rooms', 'retired', 'entries', 'offers',
                'cleanup', 'sessions'):
        assert server['final_state'][key] == 0, key
    assert server['final_state']['lobbies'] == []
    assert [job['total_processes'] for job in report['jobs']] == [5, 2, 2]
    assert all(job['active_processes'] == job['total_terminated_processes'] == 0
               for job in report['jobs'])
    return dict(mode=mode, report_sha256=sha(report_path), frames=match['frames'],
                client_exit_codes=[client['driver_report']['game_exit_code']
                                   for client in report['clients']],
                worker_exit_codes=[worker['exit_code'] for worker in server['workers']],
                jobs=[{key: job[key] for key in ('total_processes', 'active_processes',
                                                 'total_terminated_processes')}
                      for job in report['jobs']])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('mode-five', 'mode-two', 'packages', 'game', 'assets',
                 'helper-receipt', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    paths = {name.replace('-', '_'): getattr(args, name.replace('-', '_')).resolve()
             for name in ('mode-five', 'mode-two', 'packages', 'game', 'assets',
                          'helper-receipt', 'output')}
    assert all(path.is_relative_to(ROOT / 'local') for path in paths.values())
    packages, game, assets, helper_receipt = (paths[key] for key in
                                               ('packages', 'game', 'assets', 'helper_receipt'))
    build_path = packages / 'build-report.json'
    build = json.loads(build_path.read_text(encoding='utf-8'))
    assert build['versions']['game_build'] == 37822
    for kind in ('client', 'server'):
        entry = build['packages'][kind]
        assert sha(packages / entry['archive']) == entry['sha256']
    result = dict(passed=True, scope='Current private recipe38 packaged connected public5 and public2 native match and normal shutdown; no queue, wire, advertising or final release privacy claim',
                  package_build_sha256=sha(build_path), helper_receipt_sha256=sha(helper_receipt),
                  game_assembly_sha256=sha(game / 'GameAssembly.dll'),
                  assets_manifest_sha256=sha(assets / 'asset-manifest.json'),
                  modes=[check(paths['mode_five'], 5, packages, game, assets, helper_receipt),
                         check(paths['mode_two'], 2, packages, game, assets, helper_receipt)],
                  privacy_file_wire_qualified=False, full_d5_qualified=False)
    output = paths['output']
    assert not output.exists()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'modes': [row['mode'] for row in result['modes']]}))


if __name__ == '__main__':
    main()
