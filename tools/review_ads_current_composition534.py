"""Bind the full advertising callback and state-three handoff to recipe47."""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess

from client_patch.patcher.telemetry import RECIPE_VERSION, patch_component
from tools.extract_descriptors import PE
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA
from tools.review_ads_state3_composition425 import CALLBACK, COPY, DIRTY, LLVM, region
from tools.review_unity_post512 import ROOT, review as review_current
from tools.review_recipe47_queue_connected524 import sha256
from tools.review_analytics_listener import parse_assembly

GAME = ROOT / 'local/privacy520-game01'


def review() -> dict:
    bound = review_current()
    assert bound['passed'] and bound['recipe'] == RECIPE_VERSION == 47
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    installed = (GAME / 'UnityPlayer.dll').read_bytes()
    assert sha256(GAME / 'UnityPlayer.dll') == bound['installed_unity_sha256']
    generated = patch_component('UnityPlayer.dll', original)
    old, new, src = PE(original), PE(installed), PE(generated)
    start, end = CALLBACK
    assert old.function_ends[old.base + start] == old.base + end
    asm = subprocess.check_output([str(LLVM), '-d',
        f'--start-address={old.base+start:#x}',
        f'--stop-address={old.base+end:#x}',
        '--x86-asm-syntax=intel', str(ORIGINAL)])
    rows = parse_assembly(asm, old, original, start, end)
    assert rows[COPY]['text'].startswith(f'call 0x{old.base+0x15b680:x}')
    assert rows[0xc3083d]['text'] == 'mov byte ptr [rbx + 0x188], dil'
    assert rows[0xc30846]['text'] == 'mov byte ptr [rbx + 0x189], 0x1'
    assert rows[0xc30855]['text'] == 'cmp eax, 0x3'
    assert rows[0xc3085a]['text'] == 'lea rcx, [rbx - 0x1498]'
    assert rows[0xc30861]['text'].startswith(f'call 0x{old.base+0xc300f0:x}')
    assert not any('rdx' in row['text'] or 'r8' in row['text'] or 'r9' in row['text']
                   for site, row in rows.items() if COPY < site <= 0xc30870)
    before = region(original, old, start, end-start)
    expected = bytearray(before)
    expected[COPY-start:COPY-start+5] = b'\x90' * 5
    assert region(installed, new, start, end-start) == bytes(expected)
    assert region(generated, src, start, end-start) == bytes(expected)
    redirects = []
    for site, target in ((DIRTY[0], 0xc30223), (DIRTY[1], 0xc3077c)):
        code = region(installed, new, site, 5)
        assert code[0] == 0xe9
        assert site + 5 + struct.unpack_from('<i', code, 1)[0] == target
        assert code == region(generated, src, site, 5)
        redirects.append([hex(site), hex(target)])
    assert region(installed, new, 0xc3024f, 6) == b'\xff\x90\xb0\x00\x00\x00'
    assert region(installed, new, 0xc3077c, 58) == region(original, old, 0xc3077c, 58)
    return {'passed': True, 'recipe': 47,
            'installed_unity_sha256': sha256(GAME / 'UnityPlayer.dll'),
            'callback_instructions': len(rows),
            'only_callback_change': 'retained-ID copy call replaced with five NOPs',
            'dirty_identity_redirects': redirects,
            'conditional_state3_handoff_preserved': True,
            'virtual_b0_drain_preserved': True,
            'upstream_provider_resolved': False, 'full_d5_qualified': False}


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))
