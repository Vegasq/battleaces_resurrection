"""Review recipe47's authored native advertising callback progress fixture."""
from __future__ import annotations

import json
from pathlib import Path
import re

from tools.review_unity_post512 import ROOT, review as review_current
from tools.review_recipe47_queue_connected524 import sha256
from tools.extract_descriptors import PE

CASE = ROOT / 'local/privacy533-ads-callback01'
GAME = ROOT / 'local/privacy520-game01'
MARKER = re.compile(
    r'^\[(\d+)\] TELEMETRY ADS probe passed: version=1 thread=(\d+) '
    r'calls=1 authoredInput=1 retainedEmpty=1 tracking=1 dirty=1 state=0 '
    r'borrowedUnchanged=1 retainedPayloadRead=0$', re.M)


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def review() -> dict:
    bound = review_current()
    assert bound['passed'] and bound['recipe'] == 47
    report = read(CASE / 'verification.json')
    assert report['passed'] and report['mode'] == 'confirm' and report['visible']
    assert report['natural_exit'] and report['exit_code'] == 0
    assert report['owned_process_reaped'] and not report['forced_cleanup']
    assert report['source_files_unchanged'] and report['shared_settings_unchanged']
    assert report['source_sha256_at_start'] == report['source_sha256_at_finish']
    assert report['telemetry']['passed'] and report['telemetry']['recipe_version'] == 47
    assert report['telemetry']['ads_callback_copy_guard_and_progress_qualified']
    assert report['telemetry']['same_original_quit_thread']
    assert report['telemetry']['expected_unity_sha256'] == sha256(GAME / 'UnityPlayer.dll')
    assert sha256(GAME / 'UnityPlayer.dll') == bound['installed_unity_sha256']
    assert report['patch_manifest_sha256'] == sha256(
        GAME / '.battleaces-resurrection/patch-manifest.json')
    assert report['helper_sha256'] == sha256(GAME / 'BattleAcesOffline.dll')
    command = report['command']
    assert '-telemetry-audit' in command and '-telemetry-device-probe' in command
    assert '-local-profile=' + report['profile'] in command
    assert report['profile'].startswith('nativestest_')
    unity = (GAME / 'UnityPlayer.dll').read_bytes()
    pe = PE(unity)
    offset = pe.offset(pe.base + 0xc30838, 5)
    assert unity[offset:offset + 5] == b'\x90' * 5
    log = (CASE / 'native.log').read_text(encoding='utf-8', errors='replace')
    matches = list(MARKER.finditer(log))
    assert len(matches) == 1
    assert 'TELEMETRY ADS probe failed:' not in log
    assert len(re.findall(r'TELEMETRY ADS probe passed:', log)) == 1
    assert len(re.findall(r'TELEMETRY IDENTITY probe passed:', log)) == 1
    assert report['telemetry']['pre_confirm_tick'] >= int(matches[0][1])
    return {'passed': True, 'recipe': 47,
            'report_sha256': sha256(CASE / 'verification.json'),
            'native_log_sha256': sha256(CASE / 'native.log'),
            'installed_unity_sha256': sha256(GAME / 'UnityPlayer.dll'),
            'scope': 'one owned authored callback on disabled state0: copy cut keeps retained ID empty while progress flags update; original Quit0,not upstream acquisition proof'}


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))
