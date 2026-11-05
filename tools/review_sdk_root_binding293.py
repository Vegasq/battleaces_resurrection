"""Bind the retained passive SDK cache watch to the later original getter result."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / 'local/privacy269-startup01'
LIVE = ROOT / 'local/privacy284-live-root01'
OUT = ROOT / 'local/privacy293-root-binding01'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run() -> dict:
    old_path, watch_path, live_path = OLD / 'verification.json', OLD / 'sdk-root-review.json', LIVE / 'verification.json'
    require(sha(old_path) == '409ee75fd2039886ec73c3f638afdd3550d0c50102d562ea2e5636738a861427', '269 report changed')
    require(sha(watch_path) == '7ac598c4f6398612ef69dccc342fb0b62a82d9718f6ae3e0d73485e4b517c552', '269 watch review changed')
    require(sha(live_path) == '5247b417d1ac358bfa3350b1a3f1954afaccb92269faf669f913547e5ff2b093', '284 report changed')
    old, watch, live = (json.loads(path.read_bytes()) for path in (old_path, watch_path, live_path))
    require(old['passed'] and old['exit_code'] == 0 and old['tracker_closed']['complete'] and
            old['tracker_closed']['job_empty'], '269 owned lifetime incomplete')
    require(old['before']['components'] == old['after']['components'] and
            old['observer_sha256'] == sha(OLD / 'observer.js'), '269 components or observer changed')
    require(watch['passed'] and watch['no_root_replacement'] and not watch['overflow'] and
            watch['unknown_relative_roots'] == 0 and watch['selected_sdk_root_file_events'] == 0,
            '269 passive root watch incomplete')
    observer = (OLD / 'observer.js').read_text(encoding='utf-8')
    require('const config=' in observer and ', api=' in observer, '269 observer configuration missing')
    config = json.loads(observer[observer.index('const config=') + len('const config='):observer.index(', api=')])
    watched = old['sdk_cache_root']
    require(watched in config['fileRoots'], '269 reported root was not observed')
    result = live['telemetry_cache_live_root']
    require(live['passed'] and live['natural_exit'] and not live['forced_cleanup'] and live['exit_code'] == 0 and
            result['passed'] and result['original_getters'] == 3 and not result['root_override'] and
            not result['queue_enumerated'] and not result['payload_read'], '284 live getter qualification incomplete')
    require(old['before']['components']['UnityPlayer.dll'] ==
            live['telemetry']['expected_unity_sha256'], '269 and 284 Unity images differ')
    normalized = watched.replace('\\', '/')
    require(normalized == result['expected_root'].replace('\\', '/'), 'different SDK cache roots')
    digest = hashlib.sha256(normalized.encode('utf-16le')).hexdigest()
    require(digest == result['root_sha256'], 'live getter hash differs from watched root')
    return {
        'passed': True,
        'scope': 'Cross-run exact SDK cache path binding; no new game launch or queue access.',
        'passive_report_sha256': sha(old_path),
        'passive_review_sha256': sha(watch_path),
        'live_getter_report_sha256': sha(live_path),
        'common_unity_sha256': live['telemetry']['expected_unity_sha256'],
        'normalized_root_utf16le_sha256': digest,
        'watch_events': watch['observer_events'],
        'selected_file_events': watch['selected_file_events'],
        'selected_sdk_root_file_events': watch['selected_sdk_root_file_events'],
        'same_run': False,
        'full_privacy_qualified': False,
    }


def main() -> None:
    result = run()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'verification.json'
    path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('PASS', path)


if __name__ == '__main__':
    main()
