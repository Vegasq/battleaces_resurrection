"""Bound original SDK cache readers and delivery acquisition against current recipe."""
from __future__ import annotations

import hashlib
import struct

from client_patch.patcher.telemetry import RECIPE_VERSION, patch_component
from tools.extract_descriptors import Metadata, PE
from tools.review_webview_fulltext396 import METADATA, ORIGINAL, METADATA_SHA, ORIGINAL_SHA


TARGETS = {
    0x836730: (0x8206bc, 0x824de6, 0x82504c, 0x836c3f, 0x8370cf, 0x837562, 0x83797b, 0x837d32),
    0x8367b0: (0x820689, 0x824c9d, 0x824efc, 0x836ca2, 0x836fbf, 0x837602, 0x8379ab, 0x837dd2),
    0x836b50: (0x8129e5,),
    0x837810: (0x837d7f, 0x837e1f),
    0x837d10: (0x82092b,),
    0x837db0: (0x820904,),
}
NAMES = {
    0x836730: 'GetCachedEventFiles',
    0x8367b0: 'GetCachedSessionFiles',
    0x836b50: 'RemoveExpiredPayloads',
    0x837810: 'GetJsonFromCachePath',
    0x837d10: 'GetCachedEvent',
    0x837db0: 'GetCachedSession',
}
DELIVERY_TARGETS = {
    0x81c6a0: (0x81480a, 0x8209f0, 0x820a59, 0x82718a),
    0x81cf00: (),
    0x81f730: (0x81346a, 0x817376, 0x8211d2),
    0x81f8b0: (),
    0x81f950: (0x8202c7, 0x820371),
}
DELIVERY_NAMES = {
    0x81c6a0: 'Deliver',
    0x81cf00: 'PushToServer',
    0x81f730: 'StartDeliveringCachedPayloads',
    0x81f8b0: 'DeliverCachedPayloads',
    0x81f950: 'ProcessCachedItems',
}


def review() -> dict:
    raw, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(metadata).hexdigest() == METADATA_SHA
    assert RECIPE_VERSION == 43
    pe, md = PE(raw), Metadata(metadata)
    count, table = pe.module('BugsnagUnity.Windows.dll', 1224)
    selected_types = [t for t in md.types if md.string(t[0]) in ('CacheManager', 'Delivery')
                      and md.string(t[1]) == 'BugsnagUnity']
    assert len(selected_types) == 2
    pointers = {}
    for typ in selected_types:
        for method in md.methods_for_type(typ):
            slot = (method[6] & 0xffffff) - 1
            assert 0 <= slot < count
            rva = struct.unpack_from('<Q', raw, pe.offset(table + 8*slot, 8))[0] - pe.base
            pointers[rva] = md.string(method[0])
    for target, name in (NAMES | DELIVERY_NAMES).items():
        assert pointers[target] == name
        assert pe.base + target in pe.function_ends
    expected_calls = TARGETS | DELIVERY_TARGETS
    found = {rva: [] for rva in expected_calls}
    for address, size, offset in pe.sections:
        for i in range(size - 4):
            if raw[offset+i] != 0xe8:
                continue
            target = address + i + 5 + struct.unpack_from('<i', raw, offset+i+1)[0] - pe.base
            if target in found:
                found[target].append(address+i-pe.base)
    for target, expected in expected_calls.items():
        assert tuple(found[target]) == expected, (hex(target), found[target])
    current = patch_component('GameAssembly.dll', raw)
    def same(rva, expected):
        at = pe.offset(pe.base+rva, len(expected))
        assert current[at:at+len(expected)] == expected
    same(0x8201f0, bytes.fromhex('31c0c3'))
    same(0x8204c0, bytes.fromhex('31c0c3'))
    same(0x820de0, bytes.fromhex('31c0c3'))
    same(0x8147e0, b'\xc3')
    same(0x826b40, b'\xc3')
    same(0x81c6a0, b'\xc3')
    same(0x81f730, b'\xc3')
    same(0x836b50, b'\xc3')
    same(0x83683a, bytes.fromhex('e94500000090'))
    same(0x837816, bytes.fromhex('e91f00000090'))
    same(0x8129db, bytes.fromhex('909090909033d2488bcb9090909090'))
    # The save entries return;the two pending-owner handlers retain their
    # cleanup and use interior bypasses rather than entry returns.
    for rva in (0x836f10, 0x837020):
        same(rva, b'\xc3')
    same(0x824e50, bytes.fromhex('e9e700000090909090909090'))
    same(0x824fa0, bytes.fromhex('e9e700000090909090909090'))
    return {'passed': True, 'recipe': RECIPE_VERSION,
            'original_sha256': ORIGINAL_SHA,
            'recipe_gameassembly_sha256': hashlib.sha256(current).hexdigest(),
            'reader_direct_calls': {NAMES[k]: [hex(x) for x in found[k]] for k in NAMES},
            'delivery_direct_calls': {DELIVERY_NAMES[k]: [hex(x) for x in found[k]]
                                      for k in DELIVERY_NAMES}}


if __name__ == '__main__':
    print(review())
