"""Bind recipe36's SDK scene callback cut to its original metadata write."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import struct

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.extract_descriptors import Metadata, PE
from tools.review_analytics_listener import parse_assembly
from tools.review_reporter_delegate_targets300 import ORIGINAL, METADATA, OLD_SHA, MD_SHA

ASM = Path('local/privacy347-scene-metadata01')
METHODS = (
    (163549, 'BugsnagUnity', 'Client', 'ListenForSceneLoad', 0, 0x814740, 0x8147da),
    (163591, 'BugsnagUnity', 'Client', '<ListenForSceneLoad>b__47_0', 2, 0x818cf0, 0x818f56),
    (164478, 'BugsnagUnity.Payload', 'Metadata', 'AddMetadata', 3, 0x848c40, 0x848d2c),
)
PREVIOUS_SHA = 'eb016205270a729cf36300e7d8bd64fb5115b26afd8c51d9291e3f377c7a8b33'
CURRENT_SHA = 'ba894975597777edd2e7544ea2df9aafb59101800885734e7decb0b66660ff92'
LATEST_SHA = '89b6da75d36009ec3824859c6583cf29650e7db6d23dd804ac6100fa30ef30fd'
NEWEST_SHA = 'cd71b66d3249985e820fc75c3597034c3e2bcfdfa01da96c8844c19e0df8db08'
GUARD_LABEL = 'BugsnagUnity.Client::<ListenForSceneLoad>b__47_0'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def parse(path, pe, original, start, end):
    raw = b''.join(line for line in path.read_bytes().splitlines(keepends=True)
                   if (match := re.match(rb'^([0-9a-f]+): ', line)) and
                   start <= int(match[1], 16)-pe.base < end)
    return parse_assembly(raw, pe, original, start, end)


def verify():
    original, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert (sha(original), sha(metadata)) == (OLD_SHA, MD_SHA) and RECIPE_VERSION in (36, 37, 38)
    pe, md = PE(original), Metadata(metadata)
    count, table = pe.module('BugsnagUnity.Windows.dll', 666)
    pointers = {}
    for index, namespace, type_name, name, argc, start, end in METHODS:
        method = md.methods[index]
        typ = md.types[method[1]]
        token = method[6]
        assert (md.string(typ[1]), md.string(typ[0]), md.string(method[0]),
                method[2], method[-1]) == (namespace, type_name, name, 59011, argc)
        slot = (token & 0xffffff)-1
        assert 0 <= slot < count
        assert struct.unpack_from('<Q', original, pe.offset(table+slot*8, 8))[0] == pe.base+start
        assert pe.function_ends[pe.base+start] == pe.base+end
        pointers[name] = start
    listen = parse(ASM/'814740.asm', pe, original, 0x814740, 0x8147da)
    callback = parse(ASM/'818cf0.asm', pe, original, 0x818cf0, 0x818f56)
    assert listen[0x8147d5]['text'].startswith('jmp 0x1850ae830')
    assert callback[0x818f08]['text'].startswith('call 0x180848c40')
    assert callback[0x818f08]['code'] == b'\xe8\x33\xfd\x02\x00'
    assert callback[0x818f08]['text'].startswith(f"call 0x{pe.base+pointers['AddMetadata']:x}")
    assert callback[0x818eba]['text'] == 'mov rdi, qword ptr [rdi + 0x20]'
    assert callback[0x818efc]['text'] == 'mov rcx, rdi'
    patches = [patch for patch in COMPONENTS['GameAssembly.dll'].patches if patch.label == GUARD_LABEL]
    assert len(patches) == 1
    patch = patches[0]
    offset = pe.offset(pe.base+0x818cf0)
    assert (patch.rva, patch.offset, patch.replacement) == (0x818cf0, offset, b'\xc3')
    assert original[offset:offset+len(patch.guard)] == patch.guard
    candidate = patch_component('GameAssembly.dll', original)
    if RECIPE_VERSION == 38:
        assert sha(candidate) == NEWEST_SHA
        normalized = bytearray(candidate)
        session = pe.offset(pe.base+0x826b40)
        assert normalized[session] == 0xc3
        normalized[session] = original[session]
        candidate = bytes(normalized)
    if RECIPE_VERSION >= 37:
        assert sha(candidate) == LATEST_SHA
        normalized = bytearray(candidate)
        cache = pe.offset(pe.base+0x81428e)
        assert normalized[cache:cache+7] == bytes.fromhex('e9260000009090')
        normalized[cache:cache+7] = original[cache:cache+7]
        candidate = bytes(normalized)
    assert sha(candidate) == CURRENT_SHA
    assert candidate[offset:offset+0x818f56-0x818cf0] == b'\xc3'+original[offset+1:offset+0x818f56-0x818cf0]
    previous = bytearray(candidate)
    previous[offset] = original[offset]
    assert sha(previous) == PREVIOUS_SHA
    return dict(passed=True, recipe=RECIPE_VERSION, guarded_callback=hex(0x818cf0),
                original_instructions=len(listen)+len(callback),
                metadata_writer=hex(pointers['AddMetadata']),
                previous_sha256=PREVIOUS_SHA, current_sha256=CURRENT_SHA)


if __name__ == '__main__':
    print('PASS', verify())
