"""Bind Unity's fallback device ID to the shared getter and guarded analytics calls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from client_patch.patcher.telemetry import RECIPE_VERSION, patch_component
from tools.extract_descriptors import PE
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA


ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / 'local/d5-ghidra-12.1.4/pdb-device-fallback497b-console.log'
SCRIPT = ROOT / 'local/d5-ghidra-12.1.4/scripts/TraceDeviceFallback497.java'
GETTER = 0x9FB910
FALLBACK = 0x9FB3E0
GETTER_CALLS = (0x10E274, 0x592161, 0xC2F7DE, 0xC2FC09, 0xC32468)


def direct_calls(pe: PE, raw: bytes, target: int) -> tuple[int, ...]:
    start, size, offset = next(section for section in pe.sections
                               if section[0] == pe.base + 0x1000)
    found = []
    at = offset
    while True:
        at = raw.find(b'\xE8', at, offset + size - 4)
        if at < 0:
            break
        site = start + at - offset - pe.base
        if site + 5 + struct.unpack_from('<i', raw, at + 1)[0] == target:
            found.append(site)
        at += 1
    return tuple(found)


def review() -> dict:
    raw = ORIGINAL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert RECIPE_VERSION == 44
    pe = PE(raw)
    assert direct_calls(pe, raw, GETTER) == GETTER_CALLS
    assert direct_calls(pe, raw, FALLBACK) == (0x9FBDBA,)
    log = LOG.read_text(encoding='utf-16')
    assert 'FUNCTION 9fb3e0 GetDeviceIdFallback' in log
    assert 'FUNCTION 9fb910 systeminfo::GetDeviceUniqueIdentifier' in log
    assert 'RegCreateKeyExW' in log and 'RegQueryValueExW' in log
    assert 'RegOpenKeyExW' in log and 'RegSetValueExW' in log
    assert 'Software\\\\Unity Technologies' in log and 'L"DeviceId"' in log
    assert 'REF 1809fbdba UNCONDITIONAL_CALL OWNER 1809fb910' in log
    for site in GETTER_CALLS:
        assert f'REF {pe.base + site:x} UNCONDITIONAL_CALL OWNER' in log
    assert 'REPORT: Save succeeded for processed file: /UnityPlayer.dll' in log
    current = patch_component('UnityPlayer.dll', raw)
    guards = {
        0xC2F790: bytes.fromhex('e95b090000'),
        0xC2FC09: bytes.fromhex('e902000000'),
        0xC32468: bytes.fromhex('e902000000'),
    }
    for rva, expected in guards.items():
        offset = pe.offset(pe.base + rva)
        assert current[offset:offset + len(expected)] == expected
    return {'passed': True, 'recipe': RECIPE_VERSION,
            'original_sha256': ORIGINAL_SHA,
            'current_sha256': hashlib.sha256(current).hexdigest(),
            'ghidra_log_sha256': hashlib.sha256(LOG.read_bytes()).hexdigest(),
            'ghidra_script_sha256': hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
            'getter_direct_call_sites': [hex(x) for x in GETTER_CALLS],
            'fallback_direct_call_site': hex(0x9FBDBA),
            'analytics_named_calls_guarded': True,
            'shared_systeminfo_and_rng_calls_untouched': True,
            'advertising_id_producer_resolved': False}


if __name__ == '__main__':
    result = review()
    out = ROOT / 'local/privacy497-device-fallback01'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'verification.json').write_text(json.dumps(result, indent=2) + '\n',
                                           encoding='utf-8')
    print(json.dumps(result, sort_keys=True))
