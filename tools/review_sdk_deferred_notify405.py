"""Bind two deferred SDK notify adapters to current guarded collector entries."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import subprocess

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.ads_connected382 import GAME
from tools.extract_descriptors import Metadata, PE
from tools.review_analytics_listener import parse_assembly
from tools.review_sdk_direct_game401 import LLVM
from tools.review_webview_fulltext396 import ORIGINAL, METADATA, ORIGINAL_SHA, METADATA_SHA

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/privacy405-sdk-deferred01'
SOURCE_SHA = 'cd71b66d3249985e820fc75c3597034c3e2bcfdfa01da96c8844c19e0df8db08'
ROUTES = (
    dict(name='BugsnagUnity.Client::MultiThreadedNotify',
         caller=0x814820, site=0x814862, callee=0x814880,
         callee_name='BugsnagUnity.Client::NotifyFromUnityLog',
         callee_label='BugsnagUnity.Client::NotifyFromUnityLog'),
    dict(name='.<>c__DisplayClass56_0::<Notify>b__0',
         caller=0x819310, site=0x819347, callee=0x815ba0,
         callee_name='BugsnagUnity.Client::NotifyOnMainThread',
         callee_label='BugsnagUnity.Client::NotifyOnMainThread queued collector'),
)


def method_addresses(raw: bytes, metadata: bytes) -> dict[str, int]:
    pe, md = PE(raw), Metadata(metadata)
    result = {}
    for image in md.images:
        module = md.string(image[0])
        if module != 'BugsnagUnity.Windows.dll':
            continue
        selected = md.types[image[2]:image[2] + image[3]]
        methods = [method for typ in selected if typ[16]
                   for method in md.methods_for_type(typ)]
        count, table = pe.module(module, max(method[6] & 0xffffff for method in methods))
        for typ in selected:
            for method in md.methods_for_type(typ) if typ[16] else ():
                slot = (method[6] & 0xffffff) - 1
                assert 0 <= slot < count
                address = struct.unpack_from('<Q', raw, pe.offset(table + slot * 8, 8))[0]
                if address:
                    name = f'{md.string(typ[1])}.{md.string(typ[0])}::{md.string(method[0])}'
                    result[name] = address - pe.base
    return result


def review() -> dict:
    raw, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(metadata).hexdigest() == METADATA_SHA
    assert RECIPE_VERSION == 38
    pe = PE(raw)
    names = method_addresses(raw, metadata)
    source = patch_component('GameAssembly.dll', raw)
    assert hashlib.sha256(source).hexdigest() == SOURCE_SHA
    current = (GAME / 'GameAssembly.dll').read_bytes()
    cp = PE(current)
    patches = COMPONENTS['GameAssembly.dll'].patches
    OUT.mkdir(exist_ok=True)
    results = []
    for route in ROUTES:
        caller, site, callee = route['caller'], route['site'], route['callee']
        assert names[route['name']] == caller
        assert names[route['callee_name']] == callee
        end = pe.function_ends[pe.base + caller] - pe.base
        size = end - caller
        old = raw[pe.offset(pe.base + caller, size):pe.offset(pe.base + caller, size) + size]
        new = current[cp.offset(cp.base + caller, size):cp.offset(cp.base + caller, size) + size]
        assert old == new
        assembly = subprocess.check_output([str(LLVM), '-d',
            f'--start-address={pe.base + caller:#x}',
            f'--stop-address={pe.base + end:#x}',
            '--x86-asm-syntax=intel', str(ORIGINAL)])
        decoded = parse_assembly(assembly, pe, raw, caller, end)
        instruction = decoded[site]
        assert len(instruction['code']) == 5 and instruction['code'][0] == 0xe8
        assert site + 5 + struct.unpack_from('<i', instruction['code'], 1)[0] == callee
        assert instruction['text'].startswith(f'call 0x{pe.base + callee:x}')
        guard = [patch for patch in patches if patch.rva == callee]
        assert len(guard) == 1 and guard[0].label == route['callee_label']
        patch = guard[0]
        assert patch.replacement == b'\xc3'
        original_offset = pe.offset(pe.base + callee, len(patch.guard))
        current_offset = cp.offset(cp.base + callee, len(patch.replacement))
        assert raw[original_offset:original_offset + len(patch.guard)] == patch.guard
        assert source[original_offset:original_offset + 1] == b'\xc3'
        assert current[current_offset:current_offset + 1] == b'\xc3'
        (OUT / f'{caller:x}.asm').write_bytes(assembly)
        results.append(dict(name=route['name'], caller=hex(caller), end=hex(end),
                            site=hex(site), callee=hex(callee),
                            callee_label=route['callee_label'],
                            decoded_instructions=len(decoded), installed_guard='c3'))
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  metadata_sha256=METADATA_SHA,
                  source_sha256=SOURCE_SHA,
                  current_sha256=hashlib.sha256(current).hexdigest(),
                  recipe=RECIPE_VERSION, routes=results,
                  indirect_caller_or_real_queue_excluded=False,
                  full_d5_qualified=False)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))
