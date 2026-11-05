"""Classify the immediate non-platform calls after Main's ads-vtable store."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.ads_connected382 import GAME
from tools.extract_descriptors import PE
from tools.frida_ads_caller import describe_unity
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/privacy388-ads-constructor-callees01'
CONSTRUCTOR_ASM = ROOT / 'local/privacy383-main-singleton01/c33210.asm'
CALLEES = {
    0xc2cc30: 0xc2d239,
    0xc2d240: 0xc2d879,
    0xc45cb0: 0xc45d10,
    0xc46540: 0xc465d8,
}
CALLS = {
    0xc332dd: 0xc2cc30,
    0xc332e5: 0xc2d240,
    0xc3330d: 0xc2d240,
    0xc332f1: 0xc45cb0,
    0xc332fd: 0xc45cb0,
    0xc3332b: 0xc46540,
    0xc3335b: 0xc46540,
}


def slice_bytes(pe: PE, raw: bytes, start: int, end: int) -> bytes:
    offset = pe.offset(pe.base + start, end - start)
    return raw[offset:offset + end - start]


def review() -> dict:
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    installed = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(original, installed)
    pe, ip = PE(original), PE(installed)
    ctor = parse_assembly(CONSTRUCTOR_ASM.read_bytes(), pe, original, 0xc33210, 0xc33437)
    assert ctor[0xc332b5]['text'] == 'mov qword ptr [r14 + 0x1498], rax'
    assert ctor[0xc33287]['text'] == 'lea rsi, [r14 + 0x1668]'
    assert ctor[0xc332bc]['text'] == 'lea rcx, [rsi + 0x48]'
    assert ctor[0xc332e2]['text'] == 'mov rcx, rsi'
    assert ctor[0xc33302]['text'] == 'mov rcx, rsi'
    assert ctor[0xc332ea]['text'] == 'lea rcx, [rsi + 0xa8]'
    assert ctor[0xc332f6]['text'] == 'lea rcx, [rsi + 0xb8]'
    assert ctor[0xc33319]['text'] == 'lea rdx, [rsi + 0xa8]'
    assert ctor[0xc33320]['text'] == 'lea rcx, [rsi + 0xa8]'
    assert ctor[0xc33334]['text'] == 'lea rdx, [rsi + 0xb8]'
    assert ctor[0xc3333e]['text'] == 'lea rcx, [rsi + 0xb8]'
    for site, target in CALLS.items():
        assert ctor[site]['text'].startswith(f'call 0x{pe.base + target:x} '), hex(site)
    counts = {}
    for start, end in CALLEES.items():
        assert pe.function_ends[pe.base + start] == pe.base + end
        rows = parse_assembly((OUT / f'{start:x}.asm').read_bytes(), pe, original, start, end)
        assert slice_bytes(pe, original, start, end) == slice_bytes(ip, installed, start, end)
        assert not any('0x1498' in row['text'] or '0x180c307c0' in row['text']
                       for row in rows.values())
        if start in (0xc2cc30, 0xc2d240):
            assert any(row['text'].startswith('call 0x18015b680 ') for row in rows.values())
        counts[hex(start)] = len(rows)
    # The two larger calls receive different later Main members and initialize
    # local string/config state. The other two operate on list members.
    assert slice_bytes(ip, installed, 0xc333e1, 0xc333e2) == b'\x00'
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  installed_sha256=descriptor['fileSha256'], recipe=descriptor['recipe'],
                  decoded_callee_instructions=counts,
                  constructor_receivers=['Main+1668', 'Main+16b0', 'Main+1710', 'Main+1720'],
                  direct_ads_callback_registration_in_selected_callees=False,
                  indirect_or_deeper_producer_resolved=False)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))
