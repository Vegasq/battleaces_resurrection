"""Watch SDK-root metadata during fresh/restarted ordinary installed startup."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from tools.verify_d5_running_cache359 import ROOT, WATCH_SCRIPT, start_watch, stop_watch

GAME = ROOT / 'local/privacy301-runtime01/game'
PACKAGE = GAME / '.battleaces-resurrection/client-runtime/389395b034cedd1a41d5'
SHARED = ROOT.parent / '.battleaces-resurrection/profiles/default/gameconfig-localuser.toml'
SDK_SOURCE = ROOT / 'local/privacy269-startup01/verification.json'
OUT = ROOT / 'local/privacy395-ordinary-sdk02'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run() -> dict:
    assert sys.platform == 'win32' and not OUT.exists()
    sdk = Path(json.loads(SDK_SOURCE.read_text(encoding='utf-8'))['sdk_cache_root'])
    assert sdk.is_dir() and GAME.is_dir() and PACKAGE.is_dir() and SHARED.is_file()
    OUT.mkdir()
    report = dict(passed=False, scope=__doc__, sdk_root=str(sdk),
                  watcher_source_sha256=sha(WATCH_SCRIPT),
                  verifier_source_sha256=sha(ROOT / 'tools/verify_packaged_startup.py'),
                  source_witness_sha256=sha(SDK_SOURCE), started_utc=now())
    watcher = stdout = stderr = None
    try:
        watcher, stdout, stderr = start_watch(sdk, OUT / 'observer')
        report['watch_ready_utc'] = now()
        for name in ('fresh', 'existing'):
            command = [sys.executable, '-m', 'tools.verify_packaged_startup',
                       '--package', str(PACKAGE), '--game', str(GAME),
                       '--output', str(OUT / name), '--shared-settings', str(SHARED),
                       '--installed-launcher', '--window-close', '--idle-seconds', '30',
                       '--timeout', '180']
            if name == 'existing':
                command += ['--existing-profile', report['fresh']['profile']]
            began = now()
            with (OUT / f'{name}-stdout.txt').open('wb') as out, \
                 (OUT / f'{name}-stderr.txt').open('wb') as err:
                code = subprocess.run(command, cwd=ROOT, stdout=out, stderr=err).returncode
            finished = now()
            result_path = OUT / name / 'verification.json'
            assert code == 0 and result_path.is_file(), f'{name} verifier exited {code} before its report'
            result = json.loads(result_path.read_text(encoding='utf-8'))
            report[name] = dict(started_utc=began, finished_utc=finished,
                                exit_code=code, profile=result['profile'],
                                verification_sha256=sha(OUT / name / 'verification.json'),
                                menu_ready_seconds=result.get('menu_ready_seconds'),
                                idle_seconds=result.get('idle_seconds_observed'),
                                window_close_exit_zero=result.get('window_close_exit_zero'),
                                forced_cleanup=result.get('forced_cleanup'))
            assert code == 0 and result['passed'] and result['forced_cleanup'] is False
            assert result['window_close_exit_zero'] and result['installed_launcher'] is True
            assert result['profile'] == report['fresh']['profile'] if name == 'existing' else \
                re.fullmatch(r'packageprobe_[0-9a-f]{12}', result['profile']) is not None
            assert result['source_files_unchanged'] and result['package_files_unchanged']
            assert result['config_unchanged'] and result['shared_settings_unchanged']
        report['verifier_finished_utc'] = now()
        report['passed'] = True
    except BaseException as error:
        report['error'] = f'{type(error).__name__}: {error}'
    finally:
        if watcher is not None:
            try:
                report['watch_result'] = stop_watch(watcher, stdout, stderr, OUT / 'observer')
            except BaseException as error:
                report['passed'] = False
                report['watch_error'] = f'{type(error).__name__}: {error}'
        if 'watch_result' in report:
            watch = report['watch_result']
            if not (watch['stopped_by_sentinel'] and
                    all(count == 0 for count in watch['counts'].values()) and
                    watch['started_utc'] <= report.get('fresh', {}).get('started_utc', '') and
                    watch['finished_utc'] >= report.get('verifier_finished_utc', 'z')):
                report['passed'] = False
                report['watch_error'] = 'watch interval, stop or zero-event condition differs'
        report['finished_utc'] = now()
        (OUT / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    result = run()
    print(json.dumps({key: result.get(key) for key in ('passed', 'error', 'watch_error')}))
    raise SystemExit(0 if result['passed'] else 1)
