"""Inventory literal direct calls into the SDK UnityWebRequest adapter.

This is a direct rel32 inventory only. Shared generic aliases and virtual calls
cannot be assigned to a concrete class from their target address alone.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import subprocess

from tools.ads_connected382 import GAME
from tools.extract_descriptors import Metadata, PE
from tools.review_sdk_direct_game401 import LLVM
from tools.review_webview_fulltext396 import ORIGINAL, METADATA, ORIGINAL_SHA, METADATA_SHA
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/privacy406-sdk-web-request01'
MODULE = 'BugsnagUnity.Windows.dll'
NAMESPACE = 'BugsnagNetworking'
CLASS = 'BugsnagUnityWebRequest'
SHARED_CTOR = 0x717fb0
SEND = 0x80e920
COMPLETE = 0x80ea30


def review() -> dict:
    raw, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(metadata).hexdigest() == METADATA_SHA
    pe, md = PE(raw), Metadata(metadata)
    images = [image for image in md.images if md.string(image[0]) == MODULE]
    assert len(images) == 1
    image = images[0]
    selected = md.types[image[2]:image[2] + image[3]]
    methods = [method for typ in selected if typ[16]
               for method in md.methods_for_type(typ)]
    count, table = pe.module(MODULE, max(method[6] & 0xffffff for method in methods))
    matching = [typ for typ in selected if md.string(typ[0]) == CLASS
                and md.string(typ[1]) == NAMESPACE]
    assert len(matching) == 1
    routes = []
    for method in md.methods_for_type(matching[0]):
        name = md.string(method[0])
        if name not in ('.ctor', 'Get', 'Post', 'Put', 'Head', 'Delete',
                        'SendWebRequest', 'RequestCompleted'):
            continue
        slot = (method[6] & 0xffffff) - 1
        assert 0 <= slot < count
        address = struct.unpack_from('<Q', raw, pe.offset(table + slot * 8, 8))[0]
        assert address >= pe.base
        routes.append(dict(name=name, rva=address - pe.base, token=method[6]))
    assert len(routes) == 28
    addresses = {row['rva'] for row in routes}
    assert len(addresses) == 28 and SHARED_CTOR in addresses
    assert {row['rva'] for row in routes if row['name'] in ('SendWebRequest',
                                                           'RequestCompleted')} == {SEND, COMPLETE}
    unique = addresses - {SHARED_CTOR}
    raw_hits = {rva: [] for rva in addresses}
    for start, size, offset in pe.sections:
        if start - pe.base not in (0x1000, 0x6af000):
            continue
        code = memoryview(raw)[offset:offset + size]
        for index in range(size - 5):
            if code[index] not in (0xe8, 0xe9):
                continue
            address = start + index
            target = address + 5 + struct.unpack_from('<i', code, index + 1)[0]
            rva = target - pe.base
            if rva in raw_hits:
                raw_hits[rva].append(address - pe.base)
    assert all(not raw_hits[rva] for rva in unique)
    assert len(raw_hits[SHARED_CTOR]) >= 200

    current = (GAME / 'GameAssembly.dll').read_bytes()
    cp = PE(current)
    OUT.mkdir(parents=True, exist_ok=True)
    bodies = []
    for start in (SEND, COMPLETE):
        end = pe.function_ends[pe.base + start] - pe.base
        size = end - start
        old = raw[pe.offset(pe.base + start, size):pe.offset(pe.base + start, size) + size]
        new = current[cp.offset(cp.base + start, size):cp.offset(cp.base + start, size) + size]
        assert old == new
        assembly = subprocess.check_output([str(LLVM), '-d',
            f'--start-address={pe.base + start:#x}',
            f'--stop-address={pe.base + end:#x}',
            '--x86-asm-syntax=intel', str(ORIGINAL)])
        decoded = parse_assembly(assembly, pe, raw, start, end)
        (OUT / f'{start:x}.asm').write_bytes(assembly)
        bodies.append(dict(start=hex(start), end=hex(end), instructions=len(decoded)))
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  metadata_sha256=METADATA_SHA,
                  current_sha256=hashlib.sha256(current).hexdigest(),
                  selected_method_records=len(routes), distinct_targets=len(addresses),
                  targets_without_shared_alias=len(unique),
                  raw_direct_hits_to_distinct_targets=0,
                  raw_shared_constructor_candidates=len(raw_hits[SHARED_CTOR]),
                  complete_unchanged_send_and_completion_bodies=bodies,
                  unique_routes=[dict(name=row['name'], rva=hex(row['rva']))
                                 for row in routes if row['rva'] in unique],
                  shared_constructor_rva=hex(SHARED_CTOR),
                  virtual_or_indirect_acquisition_resolved=False,
                  real_queue_or_wire_excluded=False)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ('unique_routes', 'complete_unchanged_send_and_completion_bodies')},
                     sort_keys=True))
