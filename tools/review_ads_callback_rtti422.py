"""Inspect type metadata and leading methods of ads callback tables."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from tools.extract_descriptors import PE
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA
from tools.review_ads_callback_slots403 import SLOTS, TARGET, review as prior_review

OUT = Path(__file__).resolve().parents[1] / 'local/privacy422-ads-callback-rtti01'


def u64(raw: bytes, pe: PE, rva: int) -> int:
    return struct.unpack_from('<Q', raw, pe.offset(pe.base + rva, 8))[0]


def review() -> dict:
    assert prior_review()['passed']
    raw = ORIGINAL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    pe = PE(raw)
    tables = []
    expected_second = {SLOTS[0]: 0xc46a44, SLOTS[1]: 0xc68184}
    for table in SLOTS:
        preceding = u64(raw, pe, table - 8) - pe.base
        targets = [u64(raw, pe, table + i * 8) - pe.base for i in range(2)]
        assert preceding == 0xc33490
        assert targets == [TARGET, expected_second[table]]
        tables.append(dict(vtable=hex(table), preceding_function=hex(preceding),
                           msvc_rtti_col_at_preceding_qword=False,
                           first_two_methods=[hex(x) for x in targets]))
    result = dict(passed=True, original_sha256=ORIGINAL_SHA, tables=tables,
                  upstream_identifier_producer_resolved=False)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(review(), indent=2))
