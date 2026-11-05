"""Bind direct SDK File/Directory/StreamReader/Writer calls and current cuts."""
from __future__ import annotations

import bisect
import hashlib
import json
import struct
import subprocess

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.extract_descriptors import Metadata, PE
from tools.review_analytics_listener import parse_assembly
from tools.review_sdk_direct_game401 import LLVM
from tools.review_webview_fulltext396 import METADATA, METADATA_SHA, ORIGINAL, ORIGINAL_SHA

CLASSES = {'File', 'Directory', 'FileStream', 'StreamReader', 'StreamWriter',
           'DirectoryInfo', 'FileInfo'}
EXPECTED = (
    (0x81fd0d, 0x81fc00, 'Delivery.SerializeObject', 0x35339c0, 'StreamReader..ctor'),
    (0x81fd88, 0x81fc00, 'Delivery.SerializeObject', 0x3538a70, 'StreamWriter..ctor'),
    (0x8245ae, 0x824450, 'PayloadManager.AddPendingPayload', 0x35339c0, 'StreamReader..ctor'),
    (0x82462c, 0x824450, 'PayloadManager.AddPendingPayload', 0x3538a70, 'StreamWriter..ctor'),
    (0x83687c, 0x836830, 'CacheManager.GetFilesBySuffix', 0x3544a60, 'Directory.GetFiles'),
    (0x83695f, 0x8368b0, 'CacheManager.GetCachedDeviceId', 0x3547ab0, 'File.Exists'),
    (0x836a7a, 0x8368b0, 'CacheManager.GetCachedDeviceId', 0x35480a0, 'File.ReadAllText'),
    (0x836d84, 0x836b50, 'CacheManager.RemoveExpiredPayloads', 0x3547d60, 'File.GetCreationTimeUtc'),
    (0x836e9d, 0x836b50, 'CacheManager.RemoveExpiredPayloads', 0x3547950, 'File.Delete'),
    (0x83772c, 0x837720, 'CacheManager.DeleteFile', 0x3547950, 'File.Delete'),
    (0x837755, 0x837740, 'CacheManager.WriteFile', 0x3547840, 'File.Create'),
    (0x83781e, 0x837810, 'CacheManager.GetJsonFromCachePath', 0x3547ab0, 'File.Exists'),
    (0x83782e, 0x837810, 'CacheManager.GetJsonFromCachePath', 0x35480a0, 'File.ReadAllText'),
    (0x837896, 0x837850, 'CacheManager.CheckForDirectoryCreation', 0x3544970, 'Directory.Exists'),
    (0x8378c0, 0x837850, 'CacheManager.CheckForDirectoryCreation', 0x35447d0, 'Directory.CreateDirectory'),
    (0x8378e6, 0x837850, 'CacheManager.CheckForDirectoryCreation', 0x3544970, 'Directory.Exists'),
    (0x837910, 0x837850, 'CacheManager.CheckForDirectoryCreation', 0x35447d0, 'Directory.CreateDirectory'),
    (0x837936, 0x837850, 'CacheManager.CheckForDirectoryCreation', 0x3544970, 'Directory.Exists'),
    (0x837960, 0x837850, 'CacheManager.CheckForDirectoryCreation', 0x35447d0, 'Directory.CreateDirectory'),
)
MEMORY_STREAM_CTOR = 0x352e9a0
MEMORY_CTORS = {0x81fc00: 0x81fcb8, 0x824450: 0x824550}


def named_methods(pe, md, raw, module, selected):
    image = [image for image in md.images if md.string(image[0]) == module]
    assert len(image) == 1
    types = md.types[image[0][2]:image[0][2] + image[0][3]]
    methods = [method for typ in types if typ[16] for method in md.methods_for_type(typ)]
    count, table = pe.module(module, max(method[6] & 0xffffff for method in methods))
    result = {}
    for typ in types:
        if not typ[16] or not selected(md.string(typ[1]), md.string(typ[0])):
            continue
        for method in md.methods_for_type(typ):
            slot = (method[6] & 0xffffff) - 1
            if not 0 <= slot < count:
                continue
            pointer, = struct.unpack_from('<Q', raw, pe.offset(table + 8 * slot, 8))
            if pointer and (module != 'BugsnagUnity.Windows.dll' or pointer in pe.function_ends):
                name = md.string(typ[0]) + '.' + md.string(method[0])
                result.setdefault(pointer - pe.base, set()).add(name)
    return result


def review():
    raw, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(metadata).hexdigest() == METADATA_SHA
    assert RECIPE_VERSION in (45, 46)
    pe, md = PE(raw), Metadata(metadata)
    io = named_methods(pe, md, raw, 'mscorlib.dll',
                       lambda namespace, cls: namespace == 'System.IO' and cls in CLASSES)
    sdk = named_methods(pe, md, raw, 'BugsnagUnity.Windows.dll', lambda *_: True)
    assert MEMORY_STREAM_CTOR in named_methods(pe, md, raw, 'mscorlib.dll',
                         lambda namespace, cls: namespace == 'System.IO' and cls == 'MemoryStream')
    starts = sorted(sdk)
    found = []
    for address, size, offset in pe.sections:
        if address - pe.base != 0x6af000:
            continue
        code = memoryview(raw)[offset:offset + size]
        for index in range(size - 4):
            if code[index] != 0xe8:
                continue
            target = address + index + 5 + struct.unpack_from('<i', code, index + 1)[0] - pe.base
            if target not in io:
                continue
            site = address + index - pe.base
            position = bisect.bisect_right(starts, site) - 1
            owner = starts[position] if position >= 0 else None
            if owner is None or pe.base + site >= pe.function_ends[pe.base + owner]:
                continue
            found.append((site, owner, target))
    assert tuple((site, owner, target) for site, owner, target in found) == \
           tuple((site, owner, target) for site, owner, _, target, _ in EXPECTED)
    decoded = {}
    for site, owner, target in found:
        expected = next(row for row in EXPECTED if row[0] == site)
        assert expected[2] in sdk[owner] and expected[4] in io[target]
        if owner not in decoded:
            end = pe.function_ends[pe.base + owner] - pe.base
            assembly = subprocess.check_output([
                str(LLVM), '-d', f'--start-address={pe.base + owner:#x}',
                f'--stop-address={pe.base + end:#x}', '--x86-asm-syntax=intel', str(ORIGINAL)])
            decoded[owner] = parse_assembly(assembly, pe, raw, owner, end)
        instruction = decoded[owner][site]['code']
        assert len(instruction) == 5 and instruction[0] == 0xe8
        assert site + 5 + struct.unpack_from('<i', instruction, 1)[0] == target
    for owner, site in MEMORY_CTORS.items():
        instruction = decoded[owner][site]['code']
        assert len(instruction) == 5 and instruction[0] == 0xe8
        assert site + 5 + struct.unpack_from('<i', instruction, 1)[0] == MEMORY_STREAM_CTOR
        assert decoded[owner][site - 3]['text'] == 'mov rcx, rax'
        assert decoded[owner][site + 5]['text'].startswith('mov qword ptr [rsp +')
    stream_arguments = {
        0x81fc00: {0x81fcb0: 'mov rbx, rax',
                   0x81fcd4: 'mov rdi, qword ptr [rsp + 0x40]',
                   0x81fd07: 'mov rdx, rdi',
                   0x81fd7f: 'mov r8, rdi'},
        0x824450: {0x824548: 'mov rbx, rax',
                   0x824572: 'mov rdi, qword ptr [rsp + 0xe8]',
                   0x8245a8: 'mov rdx, rdi',
                   0x8245c7: 'mov r14, qword ptr [rsp + 0xe8]',
                   0x824626: 'mov rdx, r14'},
    }
    for owner, anchors in stream_arguments.items():
        for site, expected in anchors.items():
            assert decoded[owner][site]['text'] == expected, \
                (hex(owner), hex(site), expected, decoded[owner][site]['text'])
    patches = {patch.rva: patch for patch in COMPONENTS['GameAssembly.dll'].patches}
    assert {0x824450, 0x83683a, 0x8368b0, 0x836b50, 0x837720, 0x837740,
            0x837816}.issubset(patches)
    if RECIPE_VERSION == 46:
        assert 0x837850 in patches
    patched = patch_component('GameAssembly.dll', raw)
    expected_patched = {
        45: 'da6f477e91dd6f97c08ecd98068ee100611a99c1da1cf650ff3080add5c9264d',
        46: 'acbb42d7dfe31d52c661211df93e83ec88dc6aca778c58fa4424e519cd0c9468',
    }
    assert hashlib.sha256(patched).hexdigest() == expected_patched[RECIPE_VERSION]
    return dict(passed=True, original_sha256=ORIGINAL_SHA,
                metadata_sha256=METADATA_SHA, recipe=RECIPE_VERSION,
                patched_sha256=hashlib.sha256(patched).hexdigest(),
                direct_calls=[dict(site=hex(site), owner=hex(owner), owner_name=expected[2],
                                   target=hex(target), target_name=expected[4])
                              for site, owner, target in found
                              for expected in EXPECTED if expected[0] == site],
                memory_stream_ctor_sites=[hex(site) for site in MEMORY_CTORS.values()],
                scope='selected direct System.IO classes in named SDK methods; indirect and native OS I/O excluded')


if __name__ == '__main__':
    print(json.dumps(review(), indent=2))
