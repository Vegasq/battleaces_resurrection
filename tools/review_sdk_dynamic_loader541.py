"""Check direct SDK calls to imported Windows dynamic loader functions."""
from __future__ import annotations

import hashlib
import json
import bisect
import re
import struct
import subprocess

from tools.review_sdk_file_io503 import (
    LLVM, METADATA, METADATA_SHA, ORIGINAL, ORIGINAL_SHA, Metadata, PE, named_methods,
)
from tools.review_sdk_winsock_import535 import refs
from tools.review_sdk_disk_inheritance531 import review as review_installed
from tools.review_unity_post512 import ROOT


NAMES = ('GetProcAddress', 'LoadLibraryW', 'LoadLibraryExW',
         'GetModuleHandleW', 'GetModuleHandleExW')


def import_slots() -> dict[str, int]:
    imports = subprocess.check_output([str(LLVM), '-p', str(ORIGINAL)], text=True)
    before, after = imports.split('DLL Name: KERNEL32.dll', 1)
    low = int(re.search(r'addr ([0-9a-f]{8})', before.rsplit('lookup ', 1)[-1]).group(1), 16)
    block = after.split('lookup ', 1)[0]
    names = [match.group(1) for line in block.splitlines()
             if (match := re.search(r'^\s*\d+\s+(\S+)', line))]
    assert low == 0x555d048 and len(names) == 151
    slots = {name: low + names.index(name) * 8 for name in NAMES}
    assert slots == {'GetProcAddress': 0x555d0a8, 'LoadLibraryW': 0x555d0f8,
                     'LoadLibraryExW': 0x555d3f8, 'GetModuleHandleW': 0x555d0b8,
                     'GetModuleHandleExW': 0x555d3e8}
    return slots


def selected_refs(raw: bytes, pe: PE, owners: list[int], slots: dict[str, int]) -> list[tuple[int, int, int]]:
    found = []
    for owner in owners:
        end = pe.function_ends[pe.base + owner] - pe.base
        off = pe.offset(pe.base + owner, end-owner)
        found += [row for row in refs(raw[off:off+end-owner], owner,
                                      min(slots.values()), max(slots.values())+8)
                  if row[1] in slots.values()]
    return found


def direct_calls_to(raw: bytes, pe: PE, owners: list[int], targets: set[int]) -> list[tuple[int, int]]:
    found = []
    for owner in owners:
        end = pe.function_ends[pe.base + owner] - pe.base
        off = pe.offset(pe.base + owner, end-owner)
        code = raw[off:off+end-owner]
        for match in re.finditer(b'\xe8....', code, re.S):
            site = owner + match.start()
            target = site + 5 + struct.unpack_from('<i', code, match.start()+1)[0]
            if target in targets:
                found.append((site, target))
    return found


def review() -> dict:
    raw, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(metadata).hexdigest() == METADATA_SHA
    slots = import_slots()
    pe, md = PE(raw), Metadata(metadata)
    owners = named_methods(pe, md, raw, 'BugsnagUnity.Windows.dll', lambda *_: True)
    assert len(owners) == 735
    assert not selected_refs(raw, pe, owners, slots)

    controls = []
    for base, size, off in pe.sections:
        if base-pe.base not in (0x1000, 0x6af000):
            continue
        controls += [row for row in refs(raw[off:off+size], base-pe.base,
                                         min(slots.values()), max(slots.values())+8)
                     if row[1] in slots.values()]
    assert len(controls) == 37
    assert {target for _, target, _ in controls} == set(slots.values())
    assert all(kind == 0x15 for _, _, kind in controls)
    for site in (0x5b85fb, 0x5d72f5, 0x67fe7d):
        assert any(row[0] == site for row in controls)
        asm = subprocess.check_output([str(LLVM), '-d',
            f'--start-address={pe.base+site:#x}',
            f'--stop-address={pe.base+site+6:#x}',
            '--x86-asm-syntax=intel', str(ORIGINAL)], text=True)
        assert re.search(r'call\s+qword ptr \[rip', asm)

    starts = sorted(addr-pe.base for addr in pe.function_ends)
    loader_owners = set()
    for site, _, _ in controls:
        owner = starts[bisect.bisect_right(starts, site)-1]
        assert site < pe.function_ends[pe.base+owner]-pe.base
        loader_owners.add(owner)
    assert len(loader_owners) == 17
    assert not direct_calls_to(raw, pe, owners, loader_owners)
    all_callers = []
    for base, size, off in pe.sections:
        if base-pe.base not in (0x1000, 0x6af000):
            continue
        code = raw[off:off+size]
        for match in re.finditer(b'\xe8....', code, re.S):
            site = base-pe.base+match.start()
            target = site+5+struct.unpack_from('<i', code, match.start()+1)[0]
            if target in loader_owners:
                all_callers.append((site, target))
    assert len(all_callers) == 68
    assert (0x5b0b33, 0x5b85b0) in all_callers
    asm = subprocess.check_output([str(LLVM), '-d',
        f'--start-address={pe.base+0x5b0b33:#x}',
        f'--stop-address={pe.base+0x5b0b38:#x}',
        '--x86-asm-syntax=intel', str(ORIGINAL)], text=True)
    assert re.search(r'call\s+0x', asm)

    bound = review_installed()
    installed = (ROOT/'local/privacy512-game01/GameAssembly.dll').read_bytes()
    assert bound['passed'] and hashlib.sha256(installed).hexdigest() == bound['installed_sha256']
    current_pe = PE(installed)
    assert not selected_refs(installed, current_pe, owners, slots)
    assert not direct_calls_to(installed, current_pe, owners, loader_owners)
    return dict(passed=True, original_sha256=ORIGINAL_SHA,
                current_installed_sha256=bound['installed_sha256'],
                sdk_native_bodies=len(owners), imported_loader_slots=slots,
                sdk_direct_loader_calls_or_jumps=0,
                sdk_direct_calls_to_loader_owners=0,
                loader_owner_bodies=len(loader_owners),
                whole_image_direct_loader_positive_controls=len(controls),
                whole_image_direct_loader_owner_call_candidates=len(all_callers),
                scope='RIP-relative FF15/FF25 direct IAT sites in named SDK native bodies; '
                      'one-hop direct E8 calls into their17 owners; '
                      'indirect/delegated/BCL/other-module routes and wire remain open')


if __name__ == '__main__':
    result = review()
    out = ROOT/'local/privacy541-sdk-loader.json'
    out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, sort_keys=True))
