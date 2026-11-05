"""Bound the direct SDK cached-ID enumeration route in the pinned image."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from client_patch.patcher.telemetry import RECIPE_VERSION, patch_component
from tools.extract_descriptors import Metadata, PE
from tools.review_webview_fulltext396 import METADATA, METADATA_SHA, ORIGINAL, ORIGINAL_SHA


TARGETS = (0x8379D0, 0x837B00, 0x836830)
EXPECTED = {
    0x8379D0: (0x820697, 0x8206CA, 0x83798E, 0x8379BE),
    0x837B00: (0x837A63,),
    0x836830: (0x83679C, 0x83681C),
}


def review() -> dict:
    raw, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(metadata).hexdigest() == METADATA_SHA
    assert RECIPE_VERSION == 44
    pe, md = PE(raw), Metadata(metadata)
    owners = {}
    count, table = pe.module('BugsnagUnity.Windows.dll', 1)
    image, = [image for image in md.images
              if md.string(image[0]) == 'BugsnagUnity.Windows.dll']
    for typ in md.types[image[2]:image[2] + image[3]]:
        if not typ[16]:
            continue
        for method in md.methods_for_type(typ):
            slot = (method[6] & 0xFFFFFF) - 1
            if not 0 <= slot < count:
                continue
            ptr, = struct.unpack_from('<Q', raw, pe.offset(table + 8 * slot))
            rva = ptr - pe.base
            if rva in (0x8204C0, 0x837970, 0x8379A0, *TARGETS,
                       0x836730, 0x8367B0):
                owners[rva] = '.'.join(filter(None, (md.string(typ[1]),
                    md.string(typ[0]), md.string(method[0]))))
    expected_owners = {
        0x8204C0: '<ProcessCachedItems>d__37.MoveNext',
        0x837970: 'BugsnagUnity.CacheManager.GetCachedEventIds',
        0x8379A0: 'BugsnagUnity.CacheManager.GetCachedSessionIds',
        0x8379D0: 'BugsnagUnity.CacheManager.GetPayloadIDsFromDirectory',
        0x837B00: 'BugsnagUnity.CacheManager.GetCreationOrderedFiles',
        0x836730: 'BugsnagUnity.CacheManager.GetCachedEventFiles',
        0x8367B0: 'BugsnagUnity.CacheManager.GetCachedSessionFiles',
        0x836830: 'BugsnagUnity.CacheManager.GetFilesBySuffix',
    }
    assert owners == expected_owners, owners
    hits = {target: [] for target in TARGETS}
    for address, size, offset in pe.sections[:2]:
        end = offset + size - 4
        at = offset
        while at < end:
            call = raw.find(b'\xE8', at, end)
            jump = raw.find(b'\xE9', at, end)
            at = jump if call < 0 else call if jump < 0 else min(call, jump)
            if at < 0:
                break
            site = address + at - offset - pe.base
            target = site + 5 + struct.unpack_from('<i', raw, at + 1)[0]
            if target in hits:
                hits[target].append(site)
            at += 1
    assert {k: tuple(v) for k, v in hits.items()} == EXPECTED
    # GetCreationOrderedFiles applies a generic LINQ OrderBy to the input list.
    order_site = pe.offset(pe.base + 0x837C5E)
    assert raw[order_site:order_site + 5] == bytes.fromhex('e8adeebd00')
    generic_pointers = pe.offset(pe.base + 0x5BCA610)
    assert struct.unpack_from('<Q', raw, generic_pointers + 8 * 217075)[0] == \
        pe.base + 0x1416B10
    generic_table = pe.offset(pe.base + 0x5DB8ED0)
    spec_index, pointer_index, _, _ = struct.unpack_from(
        '<4i', raw, generic_table + 16 * 217559)
    assert (spec_index, pointer_index) == (238736, 217075)
    specs = pe.offset(pe.base + 0x5864110)
    definition, class_index, method_index = struct.unpack_from(
        '<3i', raw, specs + 12 * spec_index)
    assert (definition, class_index, method_index) == (128198, -1, 14054)
    order_owners = [typ for typ in md.types
                    if typ[9] <= definition < typ[9] + typ[16]]
    assert len(order_owners) == 1
    assert (md.string(order_owners[0][1]), md.string(order_owners[0][0]),
            md.string(md.methods[definition][0])) == \
           ('System.Linq', 'Enumerable', 'OrderBy')
    current = patch_component('GameAssembly.dll', raw)
    assert current[pe.offset(pe.base + 0x8204C0):
                   pe.offset(pe.base + 0x8204C0) + 3] == bytes.fromhex('31c0c3')
    assert current[pe.offset(pe.base + 0x83683A):
                   pe.offset(pe.base + 0x83683A) + 6] == bytes.fromhex('e94500000090')
    return {'passed': True, 'recipe': RECIPE_VERSION,
            'original_sha256': ORIGINAL_SHA,
            'metadata_sha256': METADATA_SHA,
            'current_sha256': hashlib.sha256(current).hexdigest(),
            'owners': {hex(k): v for k, v in owners.items()},
            'raw_rel32_sites': {hex(k): [hex(x) for x in v] for k, v in hits.items()},
            'cached_items_entry_guarded': True, 'cache_file_list_guarded': True,
            'creation_order_call': 'System.Linq.Enumerable.OrderBy'}


if __name__ == '__main__':
    result = review()
    out = Path('local/privacy494-cached-id-route01')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'verification.json').write_text(json.dumps(result, indent=2) + '\n',
                                           encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('passed', 'recipe', 'current_sha256',
        'cached_items_entry_guarded', 'cache_file_list_guarded')}, sort_keys=True))
