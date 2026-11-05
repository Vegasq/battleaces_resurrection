"""Inventory direct rel32 calls to two advertising-manager state routines.

This is a bounded call-form inventory, not an indirect-call or acquisition proof.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from tools.extract_descriptors import PE
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA
from tools.frida_ads_caller import describe_unity
from tools.ads_connected382 import GAME
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
ASM = ROOT / 'local/privacy311-ads-request01/request-5fb70.asm'
OUT = ROOT / 'local/privacy385-ads-manager-calls01'
TARGETS = {0x3611d0: 0x5fc6b, 0x361510: 0x5fc77}


def verify():
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    pe = PE(original)
    installed = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(original, installed)
    ip = PE(installed)
    start, size, offset = next(s for s in pe.sections if s[0] == pe.base + 0x1000)
    found = {target: [] for target in TARGETS}
    for index in range(size - 4):
        if original[offset + index] != 0xe8:
            continue
        at = start + index
        destination = at + 5 + struct.unpack_from('<i', original, offset + index + 1)[0]
        rva = destination - pe.base
        if rva in found:
            found[rva].append(at - pe.base)
    assert found == {target: [site] for target, site in TARGETS.items()}, found
    rows = parse_assembly(ASM.read_bytes(), pe, original, 0x5fb70, 0x5fca2)
    for target, site in TARGETS.items():
        assert rows[site]['text'].startswith(f'call 0x{pe.base + target:x} ')
        assert rows[site]['code'][0] == 0xe8 and len(rows[site]['code']) == 5
        old, new = pe.offset(pe.base + site, 5), ip.offset(ip.base + site, 5)
        assert original[old:old + 5] == installed[new:new + 5]
    result = {
        'passed': True,
        'original_sha256': ORIGINAL_SHA,
        'installed_sha256': descriptor['fileSha256'],
        'installed_recipe': descriptor['recipe'],
        'direct_rel32_calls': {hex(target): [hex(site) for site in sites]
                               for target, sites in found.items()},
        'selected_calls_byte_identical_in_current_image': True,
        'indirect_or_other_producer_resolved': False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(verify(), sort_keys=True))
