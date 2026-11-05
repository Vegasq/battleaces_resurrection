"""Bind recipe46 SDK cache-directory guard to its direct callers and owned run."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import struct

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION
from tools.review_sdk_file_io503 import METADATA, ORIGINAL, Metadata, PE, named_methods

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / 'local/privacy504-game01'
SOURCE = ROOT / 'local/privacy502-game01'
RUN = ROOT / 'local/privacy504-directory02'
HELPER = ROOT / 'local/privacy504-helper-build02'
ENTRY = 0x837850
GUARD = bytes.fromhex('4883ec38803dd2136106007518488d')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review() -> dict:
    assert RECIPE_VERSION == 46
    patch = next(p for p in COMPONENTS['GameAssembly.dll'].patches if p.rva == ENTRY)
    assert patch.guard == GUARD and patch.replacement == b'\xc3' and patch.offset == 0x835e50
    raw = ORIGINAL.read_bytes()
    pe, md = PE(raw), Metadata(METADATA.read_bytes())
    assert raw[patch.offset:patch.offset + len(GUARD)] == GUARD
    sdk = named_methods(pe, md, raw, 'BugsnagUnity.Windows.dll', lambda *_: True)
    assert 'CacheManager.CheckForDirectoryCreation' in sdk[ENTRY]
    callers = []
    for address, size, offset in pe.sections:
        if address - pe.base != 0x6af000:
            continue
        code = memoryview(raw)[offset:offset + size]
        for index in range(size - 4):
            if code[index] != 0xe8:
                continue
            target = address + index + 5 + struct.unpack_from('<i', code, index + 1)[0] - pe.base
            if target == ENTRY:
                callers.append(address + index - pe.base)
    assert callers == [0x8129db, 0x836713]
    assert 'Client..ctor' in sdk[0x812690] and 'CacheManager..ctor' in sdk[0x836660]

    manifest_path = GAME / '.battleaces-resurrection/patch-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assembly = GAME / 'GameAssembly.dll'
    component = manifest['components']['GameAssembly.dll']
    assert component['telemetry_guards'] == 108
    assert digest(assembly) == component['patched_sha256']
    assert assembly.read_bytes()[patch.offset:patch.offset + 1] == b'\xc3'
    assert digest(GAME / '.battleaces-resurrection/original/GameAssembly.dll') == component['original_sha256']
    helper = HELPER / 'BattleAcesOffline.dll'
    helper_receipt = json.loads((HELPER / 'helper-build.json').read_text(encoding='utf-8'))
    assert digest(helper) == helper_receipt['helper_sha256'] == manifest['helper_sha256']
    assert digest(GAME / 'BattleAcesOffline.dll') == digest(helper)

    report = json.loads((RUN / 'verification.json').read_text(encoding='utf-8'))
    assert report['passed'] and report['natural_exit'] and not report['forced_cleanup']
    assert report['owned_process_reaped'] and report['source_files_unchanged']
    assert report['shared_settings_unchanged'] and report['telemetry']['passed']
    assert report['telemetry']['recipe_version'] == 46
    assert report['telemetry_current_error']['passed'] and report['telemetry_current_error']['genuine_client']
    assert report['patch_manifest_sha256'] == digest(manifest_path)
    assert report['helper_sha256'] == digest(helper)
    assert report['source_sha256_at_start'] == report['source_sha256_at_finish']
    profile = report['profile']
    assert re.fullmatch(r'nativestest_quit_[0-9a-f]{12}', profile)
    assert not (SOURCE / '.battleaces-resurrection/profiles' / profile).exists()
    root = GAME / '.battleaces-resurrection/profiles' / profile / 'qc'
    assert root.is_dir() and not (root / 'Bugsnag').exists()
    log = (RUN / 'native.log').read_text(encoding='utf-8')
    assert len(re.findall(r'Telemetry audit build verified: .*recipeVersion=46 .*sdkCacheReaderSignatures=5/5 sdkCacheDirectorySignatures=1/1;', log)) == 1
    assert len(re.findall(r'TELEMETRY CACHECLIENT probe passed: .*genuineNativeInterface=1 .*reportingDisabled=1', log)) == 1
    assert 'TELEMETRY CACHE probe failed:' not in log
    return dict(passed=True, recipe=46, direct_caller_sites=[hex(site) for site in callers],
                manifest_sha256=digest(manifest_path), helper_sha256=digest(helper),
                verification_sha256=digest(RUN / 'verification.json'), profile=profile,
                owned_sdk_directory_absent_after_exit=True,
                scope='fresh owned profile with genuine SDK Client and normal Quit; no whole-run file/wire claim')


if __name__ == '__main__':
    print(json.dumps(review(), indent=2))
