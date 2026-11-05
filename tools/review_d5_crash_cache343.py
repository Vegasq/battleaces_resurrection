"""Bind an owned native crash lifetime to a passive SDK-cache change watch."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath

from tools.review_d5_connected_pair338 import ROOT, sha


def filetime(value: int) -> datetime:
    assert type(value) is int and value > 0
    return datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=value // 10)


def review(case: Path, watch: Path, control: Path, game: Path, helper: Path) -> dict:
    result = json.loads((case / 'verification.json').read_text(encoding='utf-8'))
    observed = json.loads((watch / 'watch.json').read_text(encoding='utf-8'))
    positive = json.loads((control / 'watch.json').read_text(encoding='utf-8'))
    source_root = json.loads((ROOT / 'local/privacy269-startup01/verification.json')
                             .read_text(encoding='utf-8'))['sdk_cache_root']
    manifest = json.loads((game / '.battleaces-resurrection/patch-manifest.json')
                          .read_text(encoding='utf-8'))
    assert result['passed'] is True and result['exit_code'] == 0xC0000005
    assert result['instrumentation'] is False and result['full_privacy_qualified'] is False
    assert result['game'] == str(game)
    assert result['launch']['forced_cleanup'] is False
    assert result['launch']['owned_process_reaped'] is True
    assert result['tracker']['complete'] is True
    assert result['tracker']['final_accounting'] == {'total': 1, 'active': 0, 'terminated': 0}
    assert result['source_before'] == result['source_after']
    assert result['components_before'] == result['components_after']
    assert result['shared_before'] == result['shared_after']
    assert manifest['telemetry']['recipe_version'] == 34
    assert sha(game / 'BattleAcesOffline.dll') == sha(helper) == manifest['helper_sha256']
    assert PureWindowsPath(observed['root']) == PureWindowsPath(source_root)
    assert observed['stopped_by_sentinel'] is True and observed['buffer_bytes'] == 65536
    assert set(observed['counts']) == {'Created', 'Changed', 'Deleted', 'Renamed', 'Error'}
    assert all(value == 0 for value in observed['counts'].values())
    assert positive['stopped_by_sentinel'] is True and positive['counts']['Error'] == 0
    assert all(positive['counts'][name] >= 1 for name in ('Created', 'Changed', 'Deleted'))
    assert (watch / 'ready.txt').exists() and (watch / 'stop.txt').exists()
    records = result['tracker']['records']
    assert len(records) == 1 and records[0]['pid'] == result['pid']
    created = filetime(records[0]['creation_filetime'])
    exited = filetime(records[0]['exit']['exit_filetime'])
    started = datetime.fromisoformat(observed['started_utc'])
    finished = datetime.fromisoformat(observed['finished_utc'])
    assert started <= created < exited <= finished
    return {'passed': True,
            'scope': 'Owned recipe34 uninstrumented original native crash '
                     'creation through c0000005 exit; named SDK cache root '
                     'change notifications only, no read/queue/wire claim',
            'crash_report_sha256': sha(case / 'verification.json'),
            'watch_sha256': sha(watch / 'watch.json'),
            'watch_script_sha256': sha(ROOT / 'tools/watch_sdk_cache_events.ps1'),
            'positive_control_sha256': sha(control / 'watch.json'),
            'pid': result['pid'], 'process_created_utc': created.isoformat(),
            'process_exited_utc': exited.isoformat(),
            'watch_started_utc': started.isoformat(),
            'watch_finished_utc': finished.isoformat(),
            'watch_counts': observed['counts'],
            'full_d5_qualified': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('case', 'watch', 'control', 'game', 'helper'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    paths = {key: getattr(args, key).resolve()
             for key in ('case', 'watch', 'control', 'game', 'helper')}
    assert all(path.is_relative_to(ROOT / 'local') for path in paths.values())
    result = review(**paths)
    output = paths['case'] / 'cache-review.json'
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': result['passed'], 'review': str(output),
                      'watch_counts': result['watch_counts']}))


if __name__ == '__main__':
    main()
