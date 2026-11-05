"""Bind recipe41's direct SDK expiry cut to the original void method."""
from __future__ import annotations

import hashlib
import struct

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.extract_descriptors import Metadata, PE
from tools.review_webview_fulltext396 import METADATA, METADATA_SHA, ORIGINAL, ORIGINAL_SHA

RVA = 0x836b50
OFFSET = 0x835150
ORIGINAL_ENTRY = bytes.fromhex('48895c2408488974241048897c241841')


def review() -> dict:
    assert RECIPE_VERSION == 41
    raw, meta = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(meta).hexdigest() == METADATA_SHA
    pe, md = PE(raw), Metadata(meta)
    assert pe.offset(pe.base + RVA, len(ORIGINAL_ENTRY)) == OFFSET
    assert raw[OFFSET:OFFSET + len(ORIGINAL_ENTRY)] == ORIGINAL_ENTRY
    assert pe.base + RVA in pe.function_ends and pe.function_ends[pe.base + RVA] - pe.base == 0x836f01
    typ = [t for t in md.types if md.string(t[0]) == 'CacheManager' and
           md.string(t[1]) == 'BugsnagUnity']
    assert len(typ) == 1
    count, table = pe.module('BugsnagUnity.Windows.dll', 1224)
    methods = []
    for method in md.methods_for_type(typ[0]):
        if md.string(method[0]) != 'RemoveExpiredPayloads':
            continue
        slot = (method[6] & 0xffffff) - 1
        assert 0 <= slot < count
        pointer = struct.unpack_from('<Q', raw, pe.offset(table + 8 * slot, 8))[0]
        assert pointer - pe.base == RVA
        methods.append(method)
    assert len(methods) == 1
    patch = [p for p in COMPONENTS['GameAssembly.dll'].patches if p.rva == RVA]
    assert len(patch) == 1 and patch[0].offset == OFFSET
    assert patch[0].guard == ORIGINAL_ENTRY and patch[0].replacement == b'\xc3'
    current = patch_component('GameAssembly.dll', raw)
    assert len(current) == len(raw) and current[OFFSET:OFFSET + len(ORIGINAL_ENTRY)] == b'\xc3' + ORIGINAL_ENTRY[1:]
    return dict(passed=True, recipe=RECIPE_VERSION, original_sha256=ORIGINAL_SHA,
                recipe_gameassembly_sha256=hashlib.sha256(current).hexdigest(),
                method='BugsnagUnity.CacheManager::RemoveExpiredPayloads',
                rva=hex(RVA), original_function_end=hex(pe.function_ends[pe.base + RVA] - pe.base),
                entry_replacement='c3')


if __name__ == '__main__':
    print(review())
