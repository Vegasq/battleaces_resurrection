"""Bind the advertising callback's static slots to object lifecycle setup.

This identifies dispatch surfaces, not callers or an upstream ID producer.
"""
from __future__ import annotations

import bisect
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

from tools.ads_connected382 import GAME
from tools.extract_descriptors import PE
from tools.frida_ads_caller import describe_unity
from tools.review_ads_manager_cell400 import LLVM
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/privacy403-ads-callback-slots01'
TARGET = 0xc307c0
SLOTS = (0x1a2afb8, 0x1a2c630)
BASE_TEARDOWN_TABLE = 0x1974f58
EXPECTED_SITES = {0xc2eec9: SLOTS[0], 0xc2f477: SLOTS[0],
                  0xc332ae: SLOTS[1], 0xc66b6e: SLOTS[1]}
LINE = re.compile(rb'^([0-9a-f]+): ((?:[0-9a-f]{2} )+)\s+(.+)# 0x(18[0-9a-f]+)')


def review() -> dict:
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    current = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(original, current)
    pe, cp = PE(original), PE(current)
    pointer = struct.pack('<Q', pe.base + TARGET)
    found = []
    cursor = 0
    while (cursor := original.find(pointer, cursor)) >= 0:
        found.append(pe.address(cursor) - pe.base)
        cursor += 1
    assert tuple(found) == SLOTS
    for slot in SLOTS:
        old = pe.offset(pe.base + slot, 8)
        new = cp.offset(cp.base + slot, 8)
        assert original[old:old+8] == current[new:new+8] == pointer
    base_pointer = struct.unpack_from('<Q', original,
                                      pe.offset(pe.base + BASE_TEARDOWN_TABLE, 8))[0]
    assert base_pointer == pe.base + 0x17fe428
    assert base_pointer != pe.base + TARGET
    assert current[cp.offset(cp.base + BASE_TEARDOWN_TABLE, 8):
                   cp.offset(cp.base + BASE_TEARDOWN_TABLE, 8) + 8] == struct.pack('<Q', base_pointer)

    process = subprocess.Popen([str(LLVM), '-d', '--section=.text',
        '--x86-asm-syntax=intel', str(ORIGINAL)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None and process.stderr is not None
    sites = {}
    for line in process.stdout:
        match = LINE.match(line)
        if not match:
            continue
        target = int(match[4], 16) - pe.base
        if target not in SLOTS:
            continue
        site = int(match[1], 16) - pe.base
        code = bytes.fromhex(match[2].decode())
        assert site not in sites
        assert original[pe.offset(pe.base + site, len(code)):pe.offset(pe.base + site, len(code)) + len(code)] == code
        sites[site] = target
    error = process.stderr.read()
    assert process.wait() == 0 and not error, error[:200]
    assert sites == EXPECTED_SITES

    OUT.mkdir(parents=True, exist_ok=True)
    roots = sorted(pe.function_ends)
    owners = []
    for site, slot in sorted(sites.items()):
        position = bisect.bisect_right(roots, pe.base + site) - 1
        start = roots[position] - pe.base
        end = pe.function_ends[roots[position]] - pe.base
        assert start <= site < end
        size = end - start
        old = original[pe.offset(pe.base + start, size):pe.offset(pe.base + start, size) + size]
        new = current[cp.offset(cp.base + start, size):cp.offset(cp.base + start, size) + size]
        changes = [(start + i, before, after)
                   for i, (before, after) in enumerate(zip(old, new)) if before != after]
        expected_changes = ({0xc2ee90: [(0xc2f402, 1, 0)],
                             0xc33210: [(0xc333e1, 1, 0)]}.get(start, []))
        assert changes == expected_changes
        assembly = subprocess.check_output([str(LLVM), '-d',
            f'--start-address={pe.base + start:#x}',
            f'--stop-address={pe.base + end:#x}',
            '--x86-asm-syntax=intel', str(ORIGINAL)])
        decoded = parse_assembly(assembly, pe, original, start, end)
        assert decoded[site]['text'].startswith('lea rax, [rip +')
        assert decoded[site]['code'] == old[site-start:site-start+len(decoded[site]['code'])]
        assert any(row['text'].startswith(('mov qword ptr [rdi + 0x1498], rax',
                                          'mov qword ptr [rcx + 0x1498], rax',
                                          'mov qword ptr [r14 + 0x1498], rax'))
                   for address, row in decoded.items() if site < address < site + 16)
        if start == 0xc33210:
            assert decoded[0xc33282]['text'].startswith(f'call 0x{pe.base + 0xc2ee90:x}')
            phase = 'derived-construction-after-base'
        elif start == 0xc2ee90:
            phase = 'base-construction'
        elif start == 0xc66b50:
            assert decoded[0xc66bec]['text'].startswith(f'call 0x{pe.base + 0xc2f460:x}')
            phase = 'derived-teardown-before-base'
        else:
            assert start == 0xc2f460
            lead = decoded[0xc2f550]['code']
            assert lead[:3] == b'\x48\x8d\x05'
            assert 0xc2f550 + len(lead) + struct.unpack_from('<i', lead, 3)[0] == BASE_TEARDOWN_TABLE
            assert decoded[0xc2f55a]['text'] == 'mov qword ptr [rbx + 0x1498], rax'
            assert decoded[0xc2f56b]['text'].startswith(f'jmp 0x{pe.base + 0xc33ff0:x}')
            phase = 'base-teardown-replaces-callback-table'
        (OUT / f'{start:x}.asm').write_bytes(assembly)
        owners.append(dict(site=hex(site), slot=hex(slot), owner=hex(start),
                           end=hex(end), instructions=len(decoded), phase=phase,
                           current_differences=[dict(site=hex(a), before=hex(b), after=hex(c))
                                                for a, b, c in changes]))
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  current_sha256=descriptor['fileSha256'], recipe=descriptor['recipe'],
                  absolute_callback_slots=[hex(x) for x in SLOTS],
                  direct_slot_address_references=[dict(site=hex(x), slot=hex(sites[x]))
                                                  for x in sorted(sites)],
                  complete_owners_with_only_known_recipe_differences=owners,
                  slot_address_published_to_object_offset='0x1498',
                  base_teardown_table=hex(BASE_TEARDOWN_TABLE),
                  base_teardown_first_target=hex(base_pointer-pe.base),
                  callback_invocation_or_upstream_producer_resolved=False)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))
