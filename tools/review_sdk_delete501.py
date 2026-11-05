"""Review direct SDK report deletion edges in the pinned original binary."""
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

TARGETS = {
    0x3547950: ('System.IO.File.Delete', (0x836e9d, 0x83772c)),
    0x837720: ('CacheManager.DeleteFile', (0x83748a, 0x8375af, 0x83764f, 0x8376eb)),
    0x837180: ('CacheManager.RemoveOldestFiles', (0x824ce0, 0x824f37, 0x825087, 0x836ffa, 0x83710a)),
    0x837540: ('CacheManager.RemoveCachedEvent', (0x820a18, 0x820b3c)),
    0x8375e0: ('CacheManager.RemoveCachedSession', (0x820af8, 0x820b66)),
    0x837680: ('CacheManager.RemovePayloadWithID', ()),
}
OWNERS = {
    0x836b50: 'CacheManager.RemoveExpiredPayloads',
    0x837720: 'CacheManager.DeleteFile',
    0x837180: 'CacheManager.RemoveOldestFiles',
    0x837540: 'CacheManager.RemoveCachedEvent',
    0x8375e0: 'CacheManager.RemoveCachedSession',
    0x837680: 'CacheManager.RemovePayloadWithID',
    0x8204c0: 'ProcessCachedItems.MoveNext',
    0x824b60: 'PayloadManager.SendPayloadFailed',
    0x824e20: 'PayloadManager.CacheSession',
    0x824f70: 'PayloadManager.CacheEvent',
    0x836f10: 'CacheManager.SaveSessionToCache',
    0x837020: 'CacheManager.SaveEventToCache',
}


def review():
    raw, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(metadata).hexdigest() == METADATA_SHA
    assert RECIPE_VERSION == 45
    pe, md = PE(raw), Metadata(metadata)
    sdk_count, sdk_table = pe.module('BugsnagUnity.Windows.dll', 1224)
    names = {}
    for image in md.images:
        if md.string(image[0]) != 'BugsnagUnity.Windows.dll':
            continue
        for typ in md.types[image[2]:image[2] + image[3]]:
            if not typ[16]:
                continue
            for method in md.methods_for_type(typ):
                slot = (method[6] & 0xffffff) - 1
                if slot >= sdk_count:
                    continue
                pointer, = struct.unpack_from('<Q', raw, pe.offset(sdk_table + 8 * slot, 8))
                names.setdefault(pointer - pe.base, set()).add(
                    md.string(typ[0]) + '.' + md.string(method[0]))
    for rva, name in OWNERS.items():
        assert rva in names and name.split('.')[-1] in ' '.join(names[rva]), (hex(rva), names.get(rva))
    roots = sorted(pe.function_ends)
    sites = {target: [] for target in TARGETS}
    for address, size, offset in pe.sections:
        if address - pe.base != 0x6af000:
            continue
        code = memoryview(raw)[offset:offset + size]
        for i in range(size - 4):
            if code[i] != 0xe8:
                continue
            target = address + i + 5 + struct.unpack_from('<i', code, i + 1)[0] - pe.base
            if target in sites:
                site = address + i - pe.base
                position = bisect.bisect_right(roots, pe.base + site) - 1
                owner = roots[position] - pe.base if position >= 0 and pe.base + site < pe.function_ends[roots[position]] else None
                if owner in OWNERS:
                    sites[target].append((site, owner))
    decoded = {}
    for target, (_, expected_sites) in TARGETS.items():
        assert tuple(site for site, _ in sites[target]) == expected_sites, (hex(target), sites[target])
        for site, owner in sites[target]:
            assert owner in OWNERS, (hex(site), owner)
            if owner not in decoded:
                end = pe.function_ends[pe.base + owner] - pe.base
                assembly = subprocess.check_output([
                    str(LLVM), '-d', f'--start-address={pe.base + owner:#x}',
                    f'--stop-address={pe.base + end:#x}', '--x86-asm-syntax=intel', str(ORIGINAL)])
                decoded[owner] = parse_assembly(assembly, pe, raw, owner, end)
            instruction = decoded[owner][site]['code']
            assert len(instruction) == 5 and instruction[0] == 0xe8
            assert site + 5 + struct.unpack_from('<i', instruction, 1)[0] == target
    # File.Delete is reached by the short, void CacheManager helper. Bind the
    # exact new guard and the resulting whole patched GameAssembly image.
    delete = decoded[0x837720]
    assert delete[0x837720]['code'] == bytes.fromhex('4883ec38')
    assert delete[0x83772c]['text'].startswith('call ')
    assert delete[0x837738]['code'] == b'\xc3'
    patches = COMPONENTS['GameAssembly.dll'].patches
    guard = [p for p in patches if p.rva == 0x837720]
    assert len(guard) == 1 and guard[0].replacement == b'\xc3'
    assert {0x836b50, 0x8204c0, 0x836f10, 0x837020}.issubset({p.rva for p in patches})
    patched = patch_component('GameAssembly.dll', raw)
    assert patched[pe.offset(pe.base + 0x837720, 1)] == 0xc3
    assert hashlib.sha256(patched).hexdigest() == 'da6f477e91dd6f97c08ecd98068ee100611a99c1da1cf650ff3080add5c9264d'
    return {
        'passed': True, 'recipe': RECIPE_VERSION, 'original_sha256': ORIGINAL_SHA,
        'metadata_sha256': METADATA_SHA, 'patched_sha256': hashlib.sha256(patched).hexdigest(), 'direct_edges': [
            {'target': hex(target), 'name': name,
             'sites': [{'site': hex(site), 'owner': hex(owner), 'owner_name': OWNERS[owner]}
                       for site, owner in sites[target]]}
            for target, (name, _) in TARGETS.items()],
        'guarded_delete_helper': hex(0x837720),
        'scope': 'exact decoded direct rel32 edges and pinned source patch; runtime deletion remains unproved',
    }


if __name__ == '__main__':
    print(json.dumps(review(), indent=2))
