"""Bound the three direct callees of the Main.Start periodic update body."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from client_patch.patcher.telemetry import RECIPE_VERSION, patch_component
from tools.extract_descriptors import PE
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA, INSTALLED_SHA
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
ASM = ROOT / 'local/privacy381-update-callees01'
CURRENT = ROOT / 'local/privacy301-runtime01/game/UnityPlayer.dll'
SLICES = ((0xc3dc00, 0xc3e2b0), (0xc1e1c0, 0xc1e9e9),
          (0xc351a0, 0xc35303))


def region(pe, raw, start, end):
    off = pe.offset(pe.base + start, end - start)
    return raw[off:off + end - start]


def verify():
    original, installed = ORIGINAL.read_bytes(), CURRENT.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(installed).hexdigest() == INSTALLED_SHA
    assert RECIPE_VERSION == 38
    source = patch_component('UnityPlayer.dll', original)
    pe, ip, sp = PE(original), PE(installed), PE(source)
    update = parse_assembly((ROOT / 'local/privacy354-start-update01/update.asm').read_bytes(),
                            pe, original, 0xc30940, 0xc30b22)
    assert update[0xc30ae0]['text'].startswith('call 0x180c3dc00 ')
    assert update[0xc30afe]['text'].startswith('call 0x180c1e1c0 ')
    assert update[0xc30b0d]['text'].startswith('call 0x180c351a0 ')
    result = {}
    for start, end in SLICES:
        assert pe.function_ends[pe.base + start] == pe.base + end
        rows = parse_assembly((ASM / f'{start:x}.asm').read_bytes(),
                              pe, original, start, end)
        assert rows and min(rows) == start and max(rows) < end
        expected = region(pe, original, start, end)
        assert region(sp, source, start, end) == expected
        assert region(ip, installed, start, end) == expected
        # This is a direct-body claim only. Indirect dispatches and deeper
        # direct callees are deliberately retained as unresolved edges.
        assert not any('0x180c307c0' in row['text'] or
                       '0x1498' in row['text'] for row in rows.values())
        indirect = [hex(at) for at, row in rows.items()
                    if row['text'].startswith(('callq *', 'call *'))]
        result[hex(start)] = dict(instructions=len(rows), bytes=len(expected),
                                  indirect_call_sites=indirect)
    return dict(passed=True, recipe=RECIPE_VERSION,
                original_sha256=ORIGINAL_SHA, installed_sha256=INSTALLED_SHA,
                bodies=result, direct_ads_callback_or_field=False,
                producer_or_indirect_dispatch_resolved=False)


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
