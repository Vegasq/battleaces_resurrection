"""Bound direct references to the native AdsIdHandler runtime static."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from client_patch.patcher.telemetry import RECIPE_VERSION, patch_component
from tools.extract_descriptors import PE
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA


GLOBAL = 0x1C0AF00
DESCRIPTOR = 0x1C0AF60
EXPECTED_RIP_SITES = (0x17951, 0x5FBAE)


def review() -> dict:
    raw = ORIGINAL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert RECIPE_VERSION == 44
    pe = PE(raw)
    target = pe.base + GLOBAL
    start, size, offset = next(section for section in pe.sections
                               if section[0] == pe.base + 0x1000)
    sites = []
    for index in range(size - 6):
        if raw[offset + index] not in (0x89, 0x8B, 0x8D):
            continue
        if raw[offset + index + 1] & 0xC7 != 0x05:
            continue
        at = start + index
        if at + 6 + struct.unpack_from('<i', raw, offset + index + 2)[0] == target:
            sites.append(at - pe.base)
    assert tuple(sites) == EXPECTED_RIP_SITES
    assert raw[pe.offset(pe.base + 0x17950):pe.offset(pe.base + 0x17950) + 7] == \
        bytes.fromhex('488d0da935bf01')
    assert raw[pe.offset(pe.base + 0x5FBAD):pe.offset(pe.base + 0x5FBAD) + 7] == \
        bytes.fromhex('488b3d4cb3ba01')

    # The one absolute qword reference is the runtime-static descriptor's
    # self pointer,followed by its initializer and destructor pointers.
    needle = struct.pack('<Q', target)
    absolute = []
    at = 0
    while True:
        at = raw.find(needle, at)
        if at < 0:
            break
        absolute.append(at)
        at += 1
    assert absolute == [pe.offset(pe.base + DESCRIPTOR)]
    descriptor = struct.unpack_from('<3Q', raw, absolute[0])
    assert descriptor == (target, pe.base + 0x361870, pe.base + 0x3617C0)

    current = patch_component('UnityPlayer.dll', raw)
    assert current[pe.offset(pe.base + 0x361870)] == 0xC3
    assert current[pe.offset(pe.base + 0x5FB70):
                   pe.offset(pe.base + 0x5FB70) + 3] == bytes.fromhex('31c0c3')
    return {'passed': True, 'recipe': RECIPE_VERSION,
            'original_sha256': ORIGINAL_SHA,
            'current_sha256': hashlib.sha256(current).hexdigest(),
            'selected_mov_lea_rip_sites': [hex(x) for x in sites],
            'absolute_qword_references': [hex(DESCRIPTOR)],
            'descriptor_rvas': [hex(x - pe.base) for x in descriptor],
            'initializer_guarded': True, 'public_request_guarded': True,
            'independent_provider_resolved': False}


if __name__ == '__main__':
    result = review()
    out = Path('local/privacy495-handler-global01')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'verification.json').write_text(json.dumps(result, indent=2) + '\n',
                                           encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('passed', 'recipe',
        'selected_mov_lea_rip_sites', 'absolute_qword_references',
        'initializer_guarded', 'public_request_guarded')}, sort_keys=True))
