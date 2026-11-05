"""Bind ordinary installed startup/restart to a passive SDK-root watcher."""
from __future__ import annotations

import json

from tools.review_d5_installed_package386 import GAME, ROOT, review as installed_review, sha
from tools.verify_d5_ordinary_sdk395 import OUT, SDK_SOURCE, WATCH_SCRIPT

FAILED = ROOT / 'local/privacy395-ordinary-sdk01'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def review():
    installed = installed_review()
    failed = read(FAILED / 'verification.json')
    assert failed['passed'] is False and 'error' in failed
    assert not (FAILED / 'fresh/verification.json').exists()
    assert installed['passed'] and installed['recipe'] == 38
    report = read(OUT / 'verification.json')
    assert report['passed'] and not report.get('error') and not report.get('watch_error')
    assert report['watcher_source_sha256'] == sha(WATCH_SCRIPT)
    assert report['verifier_source_sha256'] == sha(ROOT / 'tools/verify_packaged_startup.py')
    assert report['source_witness_sha256'] == sha(SDK_SOURCE)
    assert report['sdk_root'] == read(SDK_SOURCE)['sdk_cache_root']
    watch = report['watch_result']
    assert watch['root'] == report['sdk_root'] and watch['stopped_by_sentinel']
    assert watch['buffer_bytes'] == 65536
    assert watch['counts'] == dict(Created=0, Changed=0, Deleted=0, Renamed=0, Error=0)
    assert watch['started_utc'] <= report['fresh']['started_utc']
    assert report['fresh']['finished_utc'] <= report['existing']['started_utc']
    assert report['existing']['finished_utc'] <= watch['finished_utc']
    profiles = []
    for name in ('fresh', 'existing'):
        item = report[name]
        session = read(OUT / name / 'verification.json')
        assert item['verification_sha256'] == sha(OUT / name / 'verification.json')
        assert item['exit_code'] == 0 and session['passed']
        assert session['installed_launcher'] and session['window_close_requested']
        assert session['window_close_exit_zero'] and session['forced_cleanup'] is False
        assert session['wrapper_reaped'] and session['game_reaped']
        assert session['source_files_unchanged'] and session['package_files_unchanged']
        assert session['config_unchanged'] and session['shared_settings_unchanged']
        assert session['game'] == str(GAME) and session['package'] == str(
            GAME / '.battleaces-resurrection/client-runtime' / installed['runtime_identity'])
        assert session['profile'] == item['profile']
        assert session['menu_ready_seconds'] == item['menu_ready_seconds']
        assert session['idle_seconds_observed'] == item['idle_seconds'] >= 30
        assert 'Start Battle Aces.cmd' in session['command']
        profiles.append(session['profile'])
    assert profiles[0] == profiles[1]
    result = dict(passed=True, scope='current private installed launcher fresh/existing menu idle and WM_CLOSE; read-only SDK root metadata change watch only',
                  recipe=38, profile=profiles[0], watcher_counts=watch['counts'],
                  fresh_sha256=sha(OUT / 'fresh/verification.json'),
                  existing_sha256=sha(OUT / 'existing/verification.json'),
                  orchestration_sha256=sha(OUT / 'verification.json'),
                  failed_prelaunch_sha256=sha(FAILED / 'verification.json'),
                  full_d5_qualified=False)
    (OUT / 'review.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))
