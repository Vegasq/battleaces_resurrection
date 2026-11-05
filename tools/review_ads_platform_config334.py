"""Classify the constructor's platform analytics configuration handoff."""
from __future__ import annotations

import hashlib
from pathlib import Path

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.extract_descriptors import PE
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA, INSTALLED_SHA
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / 'local/privacy301-runtime01/game/UnityPlayer.dll'
ASM = ROOT / 'local/privacy334-platform-config01'
BOUNDS = ((0xc67360, 0xc673a5), (0xc673b0, 0xc676e1),
          (0xc311d0, 0xc312ad))


def region(pe: PE, raw: bytes, a: int, b: int) -> bytes:
    off = pe.offset(pe.base+a, b-a)
    return raw[off:off+b-a]


def verify() -> dict[str, object]:
    assert RECIPE_VERSION == 34
    original, installed = ORIGINAL.read_bytes(), CURRENT.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(installed).hexdigest() == INSTALLED_SHA
    source = patch_component('UnityPlayer.dll', original)
    pe, cp, sp = PE(original), PE(installed), PE(source)
    rows, counts = {}, {}
    for a,b in BOUNDS:
        assert pe.function_ends[pe.base+a] == pe.base+b
        parsed = parse_assembly((ASM/f'unity-{a:x}.asm').read_bytes(), pe, original, a, b)
        rows.update(parsed); counts[hex(a)] = len(parsed)
        for raw,desc in ((installed,cp),(source,sp)):
            assert region(desc,raw,a,b) == region(pe,original,a,b)
    assert rows[0xc67393]['text'].startswith('call 0x180c673b0 ')
    assert rows[0xc673a0]['text'].startswith('jmp 0x180c2fbc0 ')
    assert rows[0xc673b7]['text'] == 'cmp byte ptr [rcx + 0x1651], 0x0'
    assert rows[0xc673c3]['text'] == 'cmp byte ptr [rcx + 0x1660], 0x0'
    assert rows[0xc673d8]['text'] == 'cmp byte ptr [rax + 0xa8], 0x0'
    assert rows[0xc673e6]['text'] == 'xor edi, edi'
    assert rows[0xc673f6]['text'].startswith('lea rdx, [rip +')
    assert region(pe,original,0x1a2ac10,0x1a2ac1a) == b'analytics\x00'
    assert rows[0xc67416]['text'] == 'movzx r8d, dil'
    assert rows[0xc6741f]['text'] == 'mov rcx, rbx'
    assert rows[0xc67422]['text'].startswith('call 0x180c311d0 ')
    assert rows[0xc311e8]['text'] == 'mov eax, dword ptr [rcx + 0x1630]'
    assert rows[0xc31200]['text'] == 'add rsi, qword ptr [rcx + 0x1628]'
    assert rows[0xc31238]['text'] == 'mov r8, r15'
    assert rows[0xc31247]['text'].startswith('call 0x180628060 ')
    assert rows[0xc31273]['text'] == 'mov dword ptr [rbx], 0xfffffffe'
    assert not any('0x1498' in row['text'] or '0x180c307c0' in row['text']
                   for row in rows.values())
    # The constructor's named c673b0 handoff remains,with only the existing
    # device-statistics default changed in this complete constructor body.
    start, end = 0xc33210, 0xc33437
    assert pe.function_ends[pe.base+start] == pe.base+end
    before = region(pe,original,start,end)
    patch = [p for p in COMPONENTS['UnityPlayer.dll'].patches if p.rva == 0xc333da]
    assert len(patch) == 1 and patch[0].replacement == bytes.fromhex('41c6865116000000')
    expected = bytearray(before); expected[0xc333e1-start] = 0
    assert bytes(expected) == region(cp,installed,start,end) == region(sp,source,start,end)
    assert region(pe,original,0xc333e2,0xc333e7) == bytes.fromhex('e8c93f0300')
    return dict(passed=True, source_recipe=RECIPE_VERSION,
                original_sha256=ORIGINAL_SHA, installed_sha256=INSTALLED_SHA,
                decoded_instructions=counts, constructor_changed_byte='0xc333e1',
                configuration_key='analytics', direct_callback_registration=False,
                upstream_advertising_producer_resolved=False)


if __name__ == '__main__':
    import json
    print(json.dumps(verify(), indent=2))
