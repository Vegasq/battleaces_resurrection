"""Bind SDK web-request send to its declared dispatch/type contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from tools.extract_descriptors import Metadata, PE
from tools.review_webview_fulltext396 import ORIGINAL, METADATA, ORIGINAL_SHA, METADATA_SHA

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/privacy409-sdk-wrapper-contract01'


def review() -> dict:
    raw, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(metadata).hexdigest() == METADATA_SHA
    pe, md = PE(raw), Metadata(metadata)
    matches = [(index, typ) for index, typ in enumerate(md.types)
               if (md.string(typ[1]), md.string(typ[0])) ==
               ('BugsnagNetworking', 'BugsnagUnityWebRequest')]
    assert len(matches) == 1
    index, typ = matches[0]
    assert index == 19953 and typ[2] == 38675 and typ[22] == 1
    children = [n for n, candidate in enumerate(md.types) if candidate[4] == typ[2]]
    assert children == []
    interface_start, interface_size = md.header[34:36]
    assert interface_size % 4 == 0
    declared = struct.unpack_from('<i', metadata, interface_start + typ[13] * 4)[0]
    interfaces = [(n, candidate) for n, candidate in enumerate(md.types)
                  if candidate[2] == declared]
    assert len(interfaces) == 1
    interface_index, interface = interfaces[0]
    assert (md.string(interface[1]), md.string(interface[0])) == ('System', 'IDisposable')
    assert [md.string(method[0]) for method in md.methods_for_type(interface)] == ['Dispose']
    image = next(image for image in md.images
                 if image[2] <= index < image[2] + image[3])
    assert md.string(image[0]) == 'BugsnagUnity.Windows.dll'
    count, table = pe.module('BugsnagUnity.Windows.dll', 88)
    selected = []
    for method in md.methods_for_type(typ):
        name = md.string(method[0])
        if name not in ('SendWebRequest', 'RequestCompleted', 'Get', 'Post', 'Dispose'):
            continue
        slot = (method[6] & 0xffffff) - 1
        assert 0 <= slot < count
        address = struct.unpack_from('<Q', raw, pe.offset(table + slot * 8, 8))[0]
        flags = method[7]
        selected.append(dict(name=name, rva=hex(address - pe.base),
                             token=hex(method[6]), flags=hex(flags),
                             is_virtual=bool(flags & 0x40),
                             is_static=bool(flags & 0x10),
                             vtable_slot=method[9]))
    sends = [row for row in selected if row['name'] == 'SendWebRequest']
    assert sends == [dict(name='SendWebRequest', rva='0x80e920',
                         token='0x6000028', flags='0x86', is_virtual=False,
                         is_static=False, vtable_slot=65535)]
    assert len([row for row in selected if row['name'] == 'RequestCompleted']) == 1
    assert all(not row['is_virtual'] and row['vtable_slot'] == 65535
               for row in selected if row['name'] in ('Get', 'Post', 'RequestCompleted'))
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  metadata_sha256=METADATA_SHA,
                  class_type_definition=index, class_type_index=typ[2],
                  direct_subclasses=children,
                  declared_interface=dict(type_definition=interface_index,
                                          namespace='System', name='IDisposable',
                                          methods=['Dispose']),
                  selected_methods=selected,
                  ordinary_virtual_or_interface_dispatch_to_send=False,
                  reflection_delegate_or_computed_call_excluded=False)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps({key: value for key, value in result.items()
                      if key != 'selected_methods'}, sort_keys=True))
