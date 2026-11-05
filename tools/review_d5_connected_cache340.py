"""Review a current packaged match with a passive SDK-cache notification watch."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path, PureWindowsPath

from tools.review_d5_connected_pair338 import ROOT, run, sha


def review(case: Path, watch: Path, control: Path, packages: Path,
           game: Path, assets: Path) -> dict:
    connected = run(case, packages, game, assets)
    observed = json.loads((watch / 'watch.json').read_text(encoding='utf-8'))
    positive = json.loads((control / 'watch.json').read_text(encoding='utf-8'))
    source_root = json.loads((ROOT / 'local/privacy269-startup01/verification.json')
                             .read_text(encoding='utf-8'))['sdk_cache_root']
    assert PureWindowsPath(observed['root']) == PureWindowsPath(source_root)
    assert observed['scope'].startswith('Read-only Windows FileSystemWatcher')
    assert observed['stopped_by_sentinel'] is True
    assert observed['buffer_bytes'] == 65536
    assert set(observed['counts']) == {'Created', 'Changed', 'Deleted', 'Renamed', 'Error'}
    assert all(value == 0 for value in observed['counts'].values())
    assert positive['stopped_by_sentinel'] is True
    assert positive['counts']['Created'] >= 1
    assert positive['counts']['Changed'] >= 1
    assert positive['counts']['Deleted'] >= 1
    assert positive['counts']['Error'] == 0
    assert observed['started_utc'] < positive['started_utc']
    observed_seconds = (datetime.fromisoformat(observed['finished_utc']) -
                        datetime.fromisoformat(observed['started_utc'])).total_seconds()
    match_seconds = json.loads((case / 'verification.json').read_text(
        encoding='utf-8'))['elapsed_seconds']
    assert observed_seconds >= match_seconds
    assert (watch / 'ready.txt').exists() and (watch / 'stop.txt').exists()
    assert sha(ROOT / 'tools/watch_sdk_cache_events.ps1')
    return {
        'passed': True,
        'scope': 'Recipe34 private pair connected public1/two-human match; '
                 'zero selected Windows SDK-cache change notifications, '
                 'with positive sensor control; no queue read or complete file/wire claim',
        'connected': connected,
        'watch_sha256': sha(watch / 'watch.json'),
        'watch_script_sha256': sha(ROOT / 'tools/watch_sdk_cache_events.ps1'),
        'positive_control_sha256': sha(control / 'watch.json'),
        'sdk_root': observed['root'],
        'watch_started_utc': observed['started_utc'],
        'watch_finished_utc': observed['finished_utc'],
        'watch_counts': observed['counts'],
        'full_d5_qualified': False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('case', 'watch', 'control', 'packages', 'game', 'assets'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    paths = {key: getattr(args, key).resolve()
             for key in ('case', 'watch', 'control', 'packages', 'game', 'assets')}
    assert all(path.is_relative_to(ROOT / 'local') for path in paths.values())
    result = review(**paths)
    output = paths['case'] / 'cache-review.json'
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': result['passed'], 'review': str(output),
                      'watch_counts': result['watch_counts']}))


if __name__ == '__main__':
    main()
