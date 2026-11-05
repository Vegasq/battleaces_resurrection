"""Bind the two unnamed File.ReadAllText callers through IL2CPP generic tables."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from tools.extract_descriptors import Metadata, PE
from tools.review_webview_fulltext396 import METADATA, METADATA_SHA, ORIGINAL, ORIGINAL_SHA


ROOTS = (0x2630870, 0x2632790)
GENERIC_POINTERS = 0x5BCA610
GENERIC_POINTER_COUNT = 253207
CODE_REGISTRATION = 0x563B7F0  # file offset: count, pointer
METADATA_REGISTRATION = 0x6196090  # file offset


def review() -> dict:
    raw, meta_raw = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(meta_raw).hexdigest() == METADATA_SHA
    pe, md = PE(raw), Metadata(meta_raw)
    qword = lambda offset: struct.unpack_from('<Q', raw, offset)[0]
    assert qword(CODE_REGISTRATION) == GENERIC_POINTER_COUNT
    assert qword(CODE_REGISTRATION + 8) == pe.base + GENERIC_POINTERS

    reg = METADATA_REGISTRATION
    assert qword(reg) == 31432  # generic classes
    assert qword(reg + 16) == 20257  # generic instantiations
    table_count, table = qword(reg + 32), qword(reg + 40)
    spec_count, specs = qword(reg + 64), qword(reg + 72)
    assert (table_count, spec_count) == (253756, 297066)
    table_off, specs_off = pe.offset(table), pe.offset(specs)
    pointer_off = pe.offset(pe.base + GENERIC_POINTERS)

    target_indexes = {}
    for root in ROOTS:
        wanted = pe.base + root
        indexes = [index for index in range(GENERIC_POINTER_COUNT)
                   if qword(pointer_off + 8 * index) == wanted]
        assert len(indexes) == 1, (hex(root), indexes)
        target_indexes[indexes[0]] = root
    assert target_indexes == {174463: ROOTS[0], 174485: ROOTS[1]}

    findings = {root: [] for root in ROOTS}
    for row in range(table_count):
        spec_index, pointer_index, invoker_index, thunk_index = struct.unpack_from(
            '<4i', raw, table_off + 16 * row)
        if pointer_index not in target_indexes:
            continue
        assert 0 <= spec_index < spec_count
        definition, class_index, method_index = struct.unpack_from(
            '<3i', raw, specs_off + 12 * spec_index)
        assert 0 <= definition < len(md.methods)
        owners = [(type_index, typ) for type_index, typ in enumerate(md.types)
                  if typ[9] <= definition < typ[9] + typ[16]]
        assert len(owners) == 1
        type_index, typ = owners[0]
        images = [md.string(image[0]) for image in md.images
                  if image[2] <= type_index < image[2] + image[3]]
        assert images == ['RGame.dll']
        owner = '.'.join(filter(None, (md.string(typ[1]), md.string(typ[0]),
                                      md.string(md.methods[definition][0]))))
        assert owner == 'SteamRemoteFile`2.ReadJsonText'
        findings[target_indexes[pointer_index]].append({
            'table_row': row, 'generic_pointer_index': pointer_index,
            'method_spec_index': spec_index, 'method_definition_index': definition,
            'class_inst_index': class_index, 'method_inst_index': method_index,
            'image': images[0], 'owner': owner,
        })
    assert all(len(rows) == 1 for rows in findings.values())
    return {'passed': True, 'original_sha256': ORIGINAL_SHA,
            'metadata_sha256': METADATA_SHA,
            'generic_pointer_count': GENERIC_POINTER_COUNT,
            'generic_method_table_count': table_count,
            'findings': {hex(root): rows for root, rows in findings.items()},
            'sdk_owner_for_either': False}


if __name__ == '__main__':
    result = review()
    out = Path('local/privacy493-generic-read01')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, sort_keys=True))
