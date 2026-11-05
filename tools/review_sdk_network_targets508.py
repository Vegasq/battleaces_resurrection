"""Inventory decoded direct SDK calls into System.Net and UnityWebRequest APIs."""
from __future__ import annotations

import bisect
import hashlib
import json
import struct
import subprocess

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION
from tools.review_sdk_file_io503 import (LLVM, METADATA, METADATA_SHA,
                                         ORIGINAL, ORIGINAL_SHA, Metadata, PE,
                                         named_methods, parse_assembly)

EXPECTED_ROWS_SHA256 = '450d78738fc95258c981f260dd44e7874d5805c864dc19e56fe770e2cbb6b5a7'
SYSTEM_SITES = {0x80f5fb: 0x3591f20, 0x820a97: 0x717fb0}
SEND_SITES = {0x80e9cf: 0x80e920, 0x821cab: 0x820de0}


def review() -> dict:
    raw, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(metadata).hexdigest() == METADATA_SHA
    assert RECIPE_VERSION == 46
    pe, md = PE(raw), Metadata(metadata)
    sdk = named_methods(pe, md, raw, 'BugsnagUnity.Windows.dll', lambda *_: True)
    system = named_methods(pe, md, raw, 'System.dll',
                           lambda namespace, cls: namespace.startswith('System.Net'))
    for module in ('mscorlib.dll', 'System.Core.dll'):
        assert not named_methods(pe, md, raw, module,
                                 lambda namespace, cls: namespace.startswith('System.Net'))
    unity = {}
    for module in ('UnityEngine.UnityWebRequestModule.dll',
                   'UnityEngine.UnityWebRequestAssetBundleModule.dll'):
        unity.update(named_methods(pe, md, raw, module,
                     lambda namespace, cls: namespace.startswith('UnityEngine.Networking')))
    starts = sorted(sdk)
    rows = []
    for address, size, offset in pe.sections:
        if address - pe.base != 0x6af000:
            continue
        code = memoryview(raw)[offset:offset + size]
        for index in range(size - 4):
            if code[index] != 0xe8:
                continue
            target = address + index + 5 + struct.unpack_from('<i', code, index + 1)[0] - pe.base
            if target not in system and target not in unity:
                continue
            site = address + index - pe.base
            position = bisect.bisect_right(starts, site) - 1
            owner = starts[position] if position >= 0 else None
            if owner is None or pe.base + site >= pe.function_ends[pe.base + owner]:
                continue
            rows.append((site, owner, target, 'sys' if target in system else 'unity'))
    assert len(rows) == 54
    assert hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest() == EXPECTED_ROWS_SHA256
    assert {site: target for site, _, target, kind in rows if kind == 'sys'} == SYSTEM_SITES
    assert {site: owner for site, owner, target, kind in rows
            if kind == 'unity' and 'UnityWebRequest.SendWebRequest' in unity[target]} == SEND_SITES
    assert 'ProtocolViolationException..ctor' in system[0x3591f20]
    assert 0x8204c0 in [owner for site, owner, target, kind in rows if site == 0x820a97]
    assert all(any(name.startswith('BugsnagUnityWebRequest.') for name in sdk[owner])
               or owner in (0x8181f0, 0x8204c0, 0x820de0)
               for _, owner, _, _ in rows)
    decoded = {}
    for site, owner, target, _ in rows:
        if owner not in decoded:
            end = pe.function_ends[pe.base + owner] - pe.base
            assembly = subprocess.check_output([
                str(LLVM), '-d', f'--start-address={pe.base + owner:#x}',
                f'--stop-address={pe.base + end:#x}', '--x86-asm-syntax=intel', str(ORIGINAL)])
            decoded[owner] = parse_assembly(assembly, pe, raw, owner, end)
        instruction = decoded[owner][site]['code']
        assert len(instruction) == 5 and instruction[0] == 0xe8
        assert site + 5 + struct.unpack_from('<i', instruction, 1)[0] == target
    patches = {patch.rva: patch for patch in COMPONENTS['GameAssembly.dll'].patches}
    for owner in (0x8181f0, 0x8204c0, 0x820de0):
        assert patches[owner].replacement in (b'\xc3', b'\x31\xc0\xc3')
    assert 0x80e920 not in patches
    return dict(passed=True, recipe=46, original_sha256=ORIGINAL_SHA,
                metadata_sha256=METADATA_SHA, selected_targets=dict(system=len(system), unity=len(unity)),
                direct_calls=len(rows), system_net_direct_calls=len(SYSTEM_SITES),
                unity_networking_direct_calls=len(rows) - len(SYSTEM_SITES),
                direct_shared_send_sites=[hex(site) for site in SEND_SITES],
                guarded_network_breadcrumb=True, guarded_cached_delivery=True,
                sdk_web_request_send_entry_active=True,
                rows_sha256=EXPECTED_ROWS_SHA256,
                rows=[dict(site=hex(site), owner=hex(owner), target=hex(target), family=kind)
                      for site, owner, target, kind in rows],
                scope='selected direct SDK System.Net/UnityEngine.Networking calls; indirect wrapper/native/OS/wire excluded')


if __name__ == '__main__':
    print(json.dumps(review(), indent=2))
