"""Bind the SDK cached-device-ID getter cut to the pinned IL2CPP method."""
from __future__ import annotations

import hashlib
import struct

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.extract_descriptors import Metadata, PE
from tools.review_reporter_delegate_targets300 import ORIGINAL, METADATA, OLD_SHA, MD_SHA


def verify() -> dict:
    original, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(original).hexdigest() == OLD_SHA
    assert hashlib.sha256(metadata).hexdigest() == MD_SHA
    assert RECIPE_VERSION == 44
    pe, md = PE(original), Metadata(metadata)
    method = md.methods[164070]
    typ = md.types[method[1]]
    assert (md.string(typ[1]), md.string(typ[0]), md.string(method[0]),
            method[2], method[-1]) == (
                'BugsnagUnity', 'CacheManager', 'GetCachedDeviceId', 55083, 0)
    count, table = pe.module('BugsnagUnity.Windows.dll', 666)
    slot = (method[6] & 0xffffff) - 1
    assert 0 <= slot < count
    assert struct.unpack_from('<Q', original, pe.offset(table+slot*8, 8))[0] == pe.base+0x8368b0
    assert pe.function_ends[pe.base+0x8368b0] == pe.base+0x836aca

    patches = [p for p in COMPONENTS['GameAssembly.dll'].patches
               if p.label == 'BugsnagUnity.CacheManager::GetCachedDeviceId null']
    assert len(patches) == 1
    patch = patches[0]
    assert (patch.rva, patch.offset, patch.replacement) == (
        0x8368b0, pe.offset(pe.base+0x8368b0), bytes.fromhex('31c0c3'))
    assert original[patch.offset:patch.offset+len(patch.guard)] == patch.guard
    assert original[patch.offset:patch.offset+3] == bytes.fromhex('48895c')
    # The original method can read a saved ID or generate and write a new one.
    # All three calls occur after the patched entry and before its return.
    for rva, target in ((0x83695f, 0x3547ab0),
                        (0x836a46, 0x837740),
                        (0x836a7a, 0x35480a0)):
        offset = pe.offset(pe.base+rva)
        assert original[offset] == 0xe8
        displacement = struct.unpack_from('<i', original, offset+1)[0]
        assert rva+5+displacement == target
    current = patch_component('GameAssembly.dll', original)
    assert current[patch.offset:patch.offset+3] == bytes.fromhex('31c0c3')
    assert all(current[pe.offset(pe.base+rva):pe.offset(pe.base+rva)+5] ==
               original[pe.offset(pe.base+rva):pe.offset(pe.base+rva)+5]
               for rva in (0x83695f, 0x836a46, 0x836a7a))
    return {'passed': True, 'recipe': RECIPE_VERSION,
            'getter_rva': '0x8368b0', 'original_sha256': OLD_SHA,
            'patched_sha256': hashlib.sha256(current).hexdigest(),
            'return_bytes': current[patch.offset:patch.offset+3].hex()}


if __name__ == '__main__':
    print('PASS', verify())
