"""Check direct Bugsnag calls/jumps to GameAssembly's Winsock import table."""
from __future__ import annotations

import hashlib
import json
import re
import struct
import subprocess

from tools.review_sdk_file_io503 import (
    LLVM, METADATA, METADATA_SHA, ORIGINAL, ORIGINAL_SHA, Metadata, PE,
    named_methods,
)
from tools.review_sdk_disk_inheritance531 import review as review_installed
from tools.review_unity_post512 import ROOT

EXPECTED_CONTROL_SITES = (0x4518a80, 0x4518e5c, 0x4541bb3, 0x4542aa0)


def refs(code: bytes, start: int, low: int, high: int) -> list[tuple[int, int, int]]:
    found = []
    for match in re.finditer(b'\xff[\x15\x25]....', code, re.S):
        site = start + match.start()
        target = site + 6 + struct.unpack_from('<i', code, match.start()+2)[0]
        if low <= target < high:
            found.append((site, target, code[match.start()+1]))
    return found


def review() -> dict:
    raw, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(metadata).hexdigest() == METADATA_SHA
    pe, md = PE(raw), Metadata(metadata)
    imports = subprocess.check_output([str(LLVM), '-p', str(ORIGINAL)], text=True)
    ws = imports.split('DLL Name: WS2_32.dll', 1)
    assert len(ws) == 2
    prefix = ws[0].rsplit('lookup ', 1)[-1]
    match = re.search(r'addr ([0-9a-f]{8})', prefix)
    assert match
    low = int(match.group(1), 16)
    block = ws[1].split('lookup ', 1)[0]
    slots = [line for line in block.splitlines()
             if line.strip() and line.strip()[0].isdigit()]
    assert low == 0x555d5b0 and len(slots) == 37
    high = low + 8 * len(slots)
    sdk = named_methods(pe, md, raw, 'BugsnagUnity.Windows.dll', lambda *_: True)
    assert len(sdk) == 735
    sdk_refs = []
    for owner in sdk:
        end = pe.function_ends[pe.base+owner] - pe.base
        offset = pe.offset(pe.base+owner, end-owner)
        sdk_refs += refs(raw[offset:offset+end-owner], owner, low, high)
    assert not sdk_refs
    address, size, offset = next((a, s, o) for a, s, o in pe.sections
                                 if a-pe.base == 0x6af000)
    all_refs = refs(raw[offset:offset+size], address-pe.base, low, high)
    assert tuple(site for site, _, _ in all_refs) == EXPECTED_CONTROL_SITES
    assert all(kind == 0x15 and target == 0x555d640 for _, target, kind in all_refs)
    for site, _, _ in all_refs:
        asm = subprocess.check_output([str(LLVM), '-d',
            f'--start-address={pe.base+site:#x}',
            f'--stop-address={pe.base+site+6:#x}',
            '--x86-asm-syntax=intel', str(ORIGINAL)], text=True)
        assert re.search(r'call\s+qword ptr \[rip', asm)
    installed = review_installed()
    current = (ROOT/'local/privacy512-game01/GameAssembly.dll').read_bytes()
    assert installed['passed'] and installed['installed_sha256'] == hashlib.sha256(current).hexdigest()
    cur_pe = PE(current)
    assert not any(refs(current[cur_pe.offset(cur_pe.base+owner, end-owner):][:end-owner],
                        owner, low, high)
                   for owner in sdk
                   for end in (pe.function_ends[pe.base+owner]-pe.base,))
    cur_address, cur_size, cur_offset = next((a, s, o) for a, s, o in cur_pe.sections
                                             if a-cur_pe.base == 0x6af000)
    assert refs(current[cur_offset:cur_offset+cur_size], cur_address-cur_pe.base,
                low, high) == all_refs
    return {'passed': True, 'original_sha256': ORIGINAL_SHA,
            'current_installed_sha256': installed['installed_sha256'],
            'winsock_import_slots': len(slots), 'sdk_methods_with_bodies': len(sdk),
            'sdk_direct_iat_calls_or_jumps': len(sdk_refs),
            'whole_image_positive_calls': [hex(site) for site, _, _ in all_refs],
            'scope': 'direct RIP-relative call/jump into the WS2_32 IAT; indirect, computed, other module and actual wire routes unresolved'}


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))
