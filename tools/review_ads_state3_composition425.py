"""Check current ads callback retention cut and preserved state-three path."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import subprocess

from client_patch.patcher.telemetry import patch_component, RECIPE_VERSION
from tools.ads_connected382 import GAME
from tools.extract_descriptors import PE
from tools.frida_ads_caller import describe_unity
from tools.review_ads_manager_cell400 import LLVM
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA
from tools.review_analytics_listener import parse_assembly

OUT = Path(__file__).resolve().parents[1] / 'local/privacy425-ads-state3-composition01'
CALLBACK = (0xc307c0, 0xc30871)
COPY = 0xc30838
DIRTY = (0xc3016b, 0xc30273)


def region(raw: bytes, pe: PE, start: int, size: int) -> bytes:
    pos = pe.offset(pe.base + start, size)
    return raw[pos:pos+size]


def review() -> dict:
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    current = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(original, current)
    assert RECIPE_VERSION == 38
    source = patch_component('UnityPlayer.dll', original)
    old, new, src = PE(original), PE(current), PE(source)
    assert old.function_ends[old.base + CALLBACK[0]] == old.base + CALLBACK[1]
    start, end = CALLBACK
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
    size = end - start
    before = region(original, old, start, size)
    after = region(current, new, start, size)
    expected = bytearray(before)
    expected[COPY-start:COPY-start+5] = b'\x90' * 5
    assert after == bytes(expected) == region(source, src, start, size)
    assert region(original, old, COPY, 5) == b'\xe8\x43\xae\x52\xff'

    jumps = []
    for site, target in ((DIRTY[0], 0xc30223), (DIRTY[1], 0xc3077c)):
        code = region(current, new, site, 5)
        assert code[0] == 0xe9
        assert site + 5 + struct.unpack_from('<i', code, 1)[0] == target
        assert code == region(source, src, site, 5)
        jumps.append(dict(site=hex(site), target=hex(target), bytes=code.hex()))
    assert region(current, new, 0xc3024f, 6) == region(original, old, 0xc3024f, 6)
    assert region(current, new, 0xc3024f, 6) == b'\xff\x90\xb0\x00\x00\x00'
    assert region(current, new, 0xc3077c, 58) == region(original, old, 0xc3077c, 58)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'callback.asm').write_bytes(asm)
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  current_sha256=descriptor['fileSha256'], recipe=descriptor['recipe'],
                  callback_instructions=len(rows),
                  callback_only_change='five-byte retained-ID copy call to NOP',
                  state3_conditional_call_to_c300f0_preserved=True,
                  dirty_identity_conversion_redirects=jumps,
                  virtual_b0_drain_preserved=True,
                  unclassified_queued_or_inflight_delivery_unresolved=True,
                  upstream_advertising_producer_resolved=False,
                  full_d5_qualified=False)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps(dict(passed=True, callback_instructions=result['callback_instructions'],
                          preserved_drain=result['virtual_b0_drain_preserved'])))
