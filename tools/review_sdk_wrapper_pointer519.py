"""Bound pristine SDK wrapper method-pointer census; no game execution."""
from __future__ import annotations

import hashlib
import json
import struct

from tools.extract_descriptors import PE
from tools.review_webview_fulltext396 import ORIGINAL, ORIGINAL_SHA


def review() -> dict:
    raw = ORIGINAL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    pe = PE(raw)
    count, table = pe.module('BugsnagUnity.Windows.dll', 88)
    assert count == 1224
    assert table - pe.base == 0x6a380f0
    methods = {}
    for name, rva, slot in (
        ('BugsnagUnityWebRequest.SendWebRequest', 0x80e920, 39),
        ('BugsnagUnityWebRequest.RequestCompleted', 0x80ea30, 40),
    ):
        pointer = struct.pack('<Q', pe.base + rva)
        hits = []
        cursor = 0
        while (hit := raw.find(pointer, cursor)) >= 0:
            hits.append(pe.address(hit) - pe.base)
            cursor = hit + 1
        expected = table - pe.base + slot * 8
        assert hits == [expected], (name, hits, expected)
        methods[name] = {'rva': hex(rva), 'absolute_pointer_sites': [hex(hits[0])],
                         'module_method_slot': slot}
    return {'passed': True, 'original_sha256': ORIGINAL_SHA,
            'module': 'BugsnagUnity.Windows.dll', 'module_method_count': count,
            'module_table_rva': hex(table - pe.base), 'methods': methods}


if __name__ == '__main__':
    print(json.dumps(review(), indent=2))
