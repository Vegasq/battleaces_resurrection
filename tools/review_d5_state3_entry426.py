"""Discover direct/static entries into the native analytics state-three worker."""
from __future__ import annotations

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

OUT = Path(__file__).resolve().parents[1] / 'local/privacy426-state3-entry01'
TARGETS = {0xc2e5a0, 0xc300d0, 0xc3b990, 0xc3c5d0, 0xc402d0}
LINE = re.compile(r'^([0-9a-f]+): ((?:[0-9a-f]{2} )+)\s+(.+)$')
COMMENT = re.compile(r'# 0x([0-9a-f]+)')


def review() -> dict:
    raw = ORIGINAL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    current = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(raw, current)
    pe, cp = PE(raw), PE(current)
    assert raw[pe.offset(pe.base+0xc3c5e7, 11):][:11] == bytes.fromhex(
        'b8030000004533e4874108')
    assert current[cp.offset(cp.base+0xc3c5e7, 11):][:11] == bytes.fromhex(
        'b8030000004533e4874108')
    process = subprocess.Popen([str(LLVM), '-d', '--section=.text',
                                '--x86-asm-syntax=intel', str(ORIGINAL)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert process.stdout is not None and process.stderr is not None
    direct = []
    rip_refs = []
    for line in process.stdout:
        match = LINE.match(line)
        if match is None:
            continue
        site = int(match[1], 16) - pe.base
        code = bytes.fromhex(match[2])
        instruction = match[3]
        target_match = re.match(r'^(call|jmp)\t0x([0-9a-f]+)', instruction)
        if target_match:
            target = int(target_match[2], 16) - pe.base
            if target in TARGETS:
                assert code[0] in (0xe8, 0xe9) and len(code) == 5
                assert site + 5 + struct.unpack_from('<i', code, 1)[0] == target
                offset = cp.offset(cp.base+site, 5)
                direct.append(dict(site=hex(site), target=hex(target),
                                   kind=target_match[1], current_bytes=current[offset:offset+5].hex(),
                                   original_bytes=code.hex()))
        comment = COMMENT.search(instruction)
        if comment:
            target = int(comment[1], 16) - pe.base
            if target in TARGETS:
                rip_refs.append(dict(site=hex(site), target=hex(target),
                                     instruction=instruction.strip()))
    assert process.wait() == 0 and process.stderr.read() == ''
    expected_direct = {
        (0xc2e629, 0xc3b990, 'jmp'),
        (0xc2f757, 0xc3b990, 'jmp'),
        (0xc300d9, 0xc3c5d0, 'call'),
    }
    assert {(int(hit['site'], 16), int(hit['target'], 16), hit['kind'])
            for hit in direct} == expected_direct
    assert all(hit['current_bytes'] == hit['original_bytes'] for hit in direct)
    assert {(int(hit['site'], 16), int(hit['target'], 16))
            for hit in rip_refs} == {(0xc40352, 0xc2e5a0)}
    pointer_hits = {}
    for target in TARGETS:
        needle = struct.pack('<Q', pe.base + target)
        positions = []
        cursor = raw.find(needle)
        while cursor >= 0:
            positions.append(dict(file_offset=hex(cursor), rva=hex(pe.address(cursor)-pe.base)))
            cursor = raw.find(needle, cursor+1)
        pointer_hits[hex(target)] = positions
    expected_pointers = {
        0xc2e5a0: set(),
        0xc300d0: {0x1a2af50, 0x1a2c5c8},
        0xc3b990: set(),
        0xc3c5d0: {0x1a2ae70},
        0xc402d0: {0x1a2ade8, 0x1a2aec8, 0x1a2c540},
    }
    for target, expected in expected_pointers.items():
        assert {int(hit['rva'], 16) for hit in pointer_hits[hex(target)]} == expected
        for slot in expected:
            current_offset = cp.offset(cp.base + slot, 8)
            assert current[current_offset:current_offset+8] == struct.pack('<Q', cp.base + target)
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  current_sha256=descriptor['fileSha256'], recipe=descriptor['recipe'],
                  state3_exchange_current=True,
                  direct_branches=direct, rip_address_references=rip_refs,
                  preferred_base_pointer_file_offsets=pointer_hits,
                  computed_or_external_entries_unresolved=True,
                  full_d5_qualified=False)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps(dict(passed=True, direct=result['direct_branches'],
                          rip=result['rip_address_references'],
                          pointers=result['preferred_base_pointer_file_offsets']), indent=2))
