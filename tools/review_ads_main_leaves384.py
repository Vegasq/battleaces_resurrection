"""Resolve the thirteen Main singleton references in six short code gaps."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.ads_connected382 import GAME
from tools.extract_descriptors import PE
from tools.review_ads_main_global383 import ROOT, verify as verify_global
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA, INSTALLED_SHA
from tools.review_analytics_listener import parse_assembly

OUT = ROOT / 'local/privacy384-main-leaves01'
WINDOWS = ((0x1fb086, 0x1fb0d0), (0x1fc977, 0x1fc9a0),
           (0x1fcdc2, 0x1fce40), (0x207828, 0x2078d0),
           (0x207a1c, 0x207a80), (0xc2f5c8, 0xc2f5e0))
PATCH_BYTES = {0x2078b0: 0x31, 0x207a60: 0x31}


def region(pe, raw, start, end):
    offset = pe.offset(pe.base + start, end - start)
    return raw[offset:offset + end - start]


def verify():
    prior = verify_global()
    raw, installed = ORIGINAL.read_bytes(), (GAME / 'UnityPlayer.dll').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(installed).hexdigest() == INSTALLED_SHA
    pe, ip = PE(raw), PE(installed)
    remaining = {int(site, 16) for site in prior['leaf_or_unwind_gap_sites']}
    assert len(remaining) == 13
    result = {}
    for start, end in WINDOWS:
        rows = parse_assembly((OUT / f'{start:x}.asm').read_bytes(), pe, raw, start, end)
        assert rows and min(rows) == start and max(rows) < end
        assert not any('0x1498' in row['text'] or '0x180c307c0' in row['text']
                       for row in rows.values())
        original = region(pe, raw, start, end)
        expected = bytearray(original)
        for site, value in PATCH_BYTES.items():
            if start <= site < end:
                expected[site - start] = value
        assert region(ip, installed, start, end) == bytes(expected)
        found = sorted(site for site in remaining if start <= site < end)
        for site in found:
            row = rows.get(site)
            if row is None:
                row = rows.get(site - 1)
            assert row and row['text'].startswith(('mov ', 'lea ')) and '[rip ' in row['text']
            remaining.remove(site)
        result[hex(start)] = dict(end=hex(end), decoded_instructions=len(rows),
                                  singleton_sites=[hex(site) for site in found],
                                  current_byte_changes=[hex(site) for site in PATCH_BYTES if start <= site < end])
    assert not remaining
    assert prior['direct_ads_body_roots'] == ['0xc33210']
    output = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  installed_sha256=INSTALLED_SHA, recipe=prior['recipe'],
                  short_window_sites=13, gap_windows=result,
                  direct_ads_callback_or_field_in_windows=False,
                  whole_program_alias_or_producer_resolved=False)
    (OUT / 'verification.json').write_text(json.dumps(output, indent=2) + '\n', encoding='utf-8')
    return output


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
