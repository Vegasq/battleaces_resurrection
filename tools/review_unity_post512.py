"""Bind recipe47's Unity Analytics post cut to private installed compatibility."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from client_patch.patcher.patch_client import build_patch, update_checksum
from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, RUNTIME_VALIDATED, patch_component
from tools.helper_provenance import validate as validate_helper
from tools.package_integrity import verify
from tools.review_ads_state_callback296 import ORIGINAL as UNITY, ORIGINAL_SHA as UNITY_SHA
from tools.review_webview_fulltext396 import ORIGINAL as GAME_ORIGINAL, ORIGINAL_SHA as GAME_SHA
from tools.extract_descriptors import PE

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / 'local/privacy512-game01'
PACKAGES = ROOT / 'local/privacy512-packages01'
HELPER = ROOT / 'local/privacy512-helper-build01/BattleAcesOffline.dll'
STARTUP = ROOT / 'local/privacy512-startup01/verification.json'
MATCH = ROOT / 'local/privacy512-public1-01/verification.json'
LOG = ROOT / 'local/d5-ghidra-12.1.4/pdb-perform-post512-final2-console.log'
LOG_SHA = '68fe826092f022ea3b5998ed4e5f3d64ebef297f6ae7bf6e0b38b872afaf891a'


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def review() -> dict:
    assert RECIPE_VERSION == 47 and RUNTIME_VALIDATED is False
    assert sha(LOG) == LOG_SHA
    ghidra = LOG.read_text(encoding='utf-16')
    assert 'FUNCTION 180c64e20 UnityEngine::Analytics::WebRequestRestClient::PerformPost' in ghidra
    assert 'FUNCTION 180c64ea0 UnityEngine::Analytics::WebRequestRestClient::Begin' in ghidra
    assert 'bool __thiscall' in ghidra and 'if (!bVar2) {' in ghidra
    assert 'REF 180c59630 UNCONDITIONAL_CALL OWNER 180c59350 DispatcherService::FetchAndSaveConfigFromServer' in ghidra
    assert 'REF 180c56b65 UNCONDITIONAL_CALL OWNER 180c565f0 UnityEngine::Analytics::DataDispatcher::PerformWebDispatch' in ghidra
    assert 'REF 180c64e97 UNCONDITIONAL_CALL OWNER 180c64e20 UnityEngine::Analytics::WebRequestRestClient::PerformPost' in ghidra
    assert sha(UNITY) == UNITY_SHA and sha(GAME_ORIGINAL) == GAME_SHA
    original_unity = UNITY.read_bytes()
    pe = PE(original_unity)
    for site, target, opcode in ((0xc59630, 0xc64e20, 0xe8),
                                 (0xc56b65, 0xc64e20, 0xe9),
                                 (0xc64e97, 0xc64ea0, 0xe9)):
        off = pe.offset(pe.base + site)
        assert original_unity[off] == opcode
        assert site + 5 + struct.unpack_from('<i', original_unity, off + 1)[0] == target
    assert sha(GAME / '.battleaces-resurrection/original/UnityPlayer.dll') == UNITY_SHA
    installed_unity = update_checksum(patch_component('UnityPlayer.dll', original_unity))
    assert (GAME / 'UnityPlayer.dll').read_bytes() == installed_unity
    offset = 0xc64220
    guard = bytes.fromhex('40534883ec20488bd9e8e2f4ffff84')
    assert original_unity[offset:offset + len(guard)] == guard
    assert installed_unity[offset:offset + 3] == bytes.fromhex('31c0c3')
    guards = {item.rva: item for item in COMPONENTS['UnityPlayer.dll'].patches}
    assert len(guards) == 66 and guards[0xc64e20].replacement == bytes.fromhex('31c0c3')
    assert sha(GAME / '.battleaces-resurrection/original/GameAssembly.dll') == GAME_SHA
    assert (GAME / 'GameAssembly.dll').read_bytes() == build_patch(GAME_ORIGINAL.read_bytes(), community=True, cosmetics=True)
    manifest = read(GAME / '.battleaces-resurrection/patch-manifest.json')
    assert manifest['telemetry']['recipe_version'] == 47
    assert manifest['telemetry']['runtime_validated'] is False
    assert manifest['components']['UnityPlayer.dll']['telemetry_guards'] == 66
    assert manifest['components']['GameAssembly.dll']['telemetry_guards'] == 108
    validate_helper(HELPER, HELPER.read_bytes(), ROOT)
    assert sha(GAME / 'BattleAcesOffline.dll') == sha(HELPER) == manifest['helper_sha256']
    build = read(PACKAGES / 'build-report.json')
    assert build['source']['dirty'] is True
    for kind in ('client', 'server'):
        package = PACKAGES / f'battleaces-{kind}-win64'
        verify(package, kind)
        info = build['packages'][kind]
        assert sha(PACKAGES / info['archive']) == info['sha256']
        assert sha(package / 'program/client-helper/BattleAcesOffline.dll') == sha(HELPER)
        assert sha(package / 'program/app/client_patch/patcher/telemetry.py') == sha(ROOT / 'client_patch/patcher/telemetry.py')
    startup = read(STARTUP)
    assert startup['passed'] and startup['installed_launcher'] and startup['window_close_exit_zero']
    assert startup['idle_seconds_observed'] >= 30 and startup['forced_cleanup'] is False
    assert startup['package_files_unchanged'] and startup['source_files_unchanged']
    match = read(MATCH)
    assert match['passed'] and match['rc_open'] and match['mode'] == 1 and match['humans'] == 2
    assert match['forced_cleanup'] is False and match['match']['frames'] >= 1200
    assert match['match']['result']['complete'] is True and len(match['clients']) == 2
    assert all(c['driver_report']['passed'] and c['driver_report']['game_exit_code'] == 0 for c in match['clients'])
    assert len(match['jobs']) == 3 and all(j['active_processes'] == j['total_terminated_processes'] == 0 for j in match['jobs'])
    assert all(w['exit_code'] == 0 and w['reaped'] for w in match['worker_cleanup'])
    assert all(match[k] for k in ('package_files_unchanged', 'assets_unchanged', 'shared_channels_unchanged',
                                   'source_files_unchanged', 'temporary_pki_removed'))
    return dict(passed=True, recipe=47, installed_unity_sha256=sha(GAME / 'UnityPlayer.dll'),
                helper_sha256=sha(HELPER), startup_sha256=sha(STARTUP), match_sha256=sha(MATCH),
                match_frames=match['match']['frames'], post_guard_rva='0xc64e20',
                full_d5_qualified=False)


if __name__ == '__main__':
    print(json.dumps(review(), indent=2))
