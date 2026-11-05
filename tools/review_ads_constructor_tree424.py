"""Bind omitted Main constructor +1750 tree-root initializer."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess

from tools.ads_connected382 import GAME
from tools.extract_descriptors import PE
from tools.frida_ads_caller import describe_unity
from tools.review_ads_manager_cell400 import LLVM
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA
from tools.review_analytics_listener import parse_assembly

OUT = Path(__file__).resolve().parents[1] / 'local/privacy424-ads-constructor-tree01'
CONSTRUCTOR = (0xc33210, 0xc33437)
INITIALIZER = (0xc45ac0, 0xc45b1e)


def review() -> dict:
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    current = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(original, current)
    old, new = PE(original), PE(current)
    assert old.function_ends[old.base + INITIALIZER[0]] == old.base + INITIALIZER[1]
    assert old.function_ends[old.base + CONSTRUCTOR[0]] == old.base + CONSTRUCTOR[1]
    decoded = {}
    OUT.mkdir(parents=True, exist_ok=True)
    for label, (start, end) in [('constructor', CONSTRUCTOR), ('initializer', INITIALIZER)]:
        asm = subprocess.check_output([str(LLVM), '-d',
            f'--start-address={old.base+start:#x}',
            f'--stop-address={old.base+end:#x}',
            '--x86-asm-syntax=intel', str(ORIGINAL)])
        rows = parse_assembly(asm, old, original, start, end)
        decoded[label] = rows
        (OUT / f'{label}.asm').write_bytes(asm)
    constructor, initializer = decoded['constructor'], decoded['initializer']
    direct_calls = {site: int(re.match(r'call 0x([0-9a-f]+)', row['text'])[1], 16) - old.base
                    for site, row in constructor.items()
                    if row['text'].startswith('call 0x')}
    assert direct_calls == {
        0xc3325a: 0x3576d0, 0xc33282: 0xc2ee90,
        0xc332dd: 0xc2cc30, 0xc332e5: 0xc2d240,
        0xc332f1: 0xc45cb0, 0xc332fd: 0xc45cb0,
        0xc3330d: 0xc2d240, 0xc3332b: 0xc46540,
        0xc3335b: 0xc46540, 0xc333a0: 0xc45ac0,
        0xc333e2: 0xc673b0,
    }
    assert constructor[0xc3336e]['text'] == 'lea rcx, [r14 + 0x1750]'
    assert constructor[0xc333a0]['text'].startswith(f'call 0x{old.base+INITIALIZER[0]:x}')
    assert initializer[0xc45ac6]['text'] == 'mov rbx, rcx'
    assert initializer[0xc45ae3]['text'] == 'mov qword ptr [rbx], rcx'
    assert initializer[0xc45ae9]['text'] == 'mov qword ptr [rbx + 0x8], rcx'
    assert initializer[0xc45b01]['text'] == 'mov qword ptr [rax], rax'
    assert initializer[0xc45b04]['text'] == 'mov qword ptr [rax + 0x8], rax'
    assert initializer[0xc45b08]['text'] == 'mov qword ptr [rax + 0x10], rax'
    assert initializer[0xc45b12]['text'] == 'mov qword ptr [rbx], rax'
    assert not any('0x1498' in row['text'] or '0x180c307c0' in row['text']
                   for row in initializer.values())
    for start, end in (INITIALIZER, CONSTRUCTOR):
        size = end - start
        a, b = old.offset(old.base + start, size), new.offset(new.base + start, size)
        changes = [(start + i, before, after)
                   for i, (before, after) in enumerate(zip(original[a:a+size],
                                                           current[b:b+size])) if before != after]
        assert changes == ([(0xc333e1, 1, 0)] if start == CONSTRUCTOR[0] else [])
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  current_sha256=descriptor['fileSha256'], recipe=descriptor['recipe'],
                  constructor_site='0xc333a0', receiver='Main+0x1750',
                  initializer='0xc45ac0', initializer_instructions=len(initializer),
                  constructor_direct_calls={hex(site): hex(target)
                                            for site, target in direct_calls.items()},
                  initializer_body_byte_identical=True,
                  direct_ads_callback_or_field_use=False,
                  upstream_identifier_producer_resolved=False)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps(dict(passed=True, receiver=result['receiver'],
                          instructions=result['initializer_instructions'])))
