"""Verify the Main.Start registered analytics update edge and its current cut."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from client_patch.patcher.telemetry import RECIPE_VERSION, patch_component
from tools.extract_descriptors import PE
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA, INSTALLED_SHA
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
ASM = ROOT/'local/privacy354-start-update01'
CURRENT = ROOT/'local/privacy301-runtime01/game/UnityPlayer.dll'
SLICES = (('base',0xc2f570,0xc2f5dc),('platform',0xc66c20,0xc66fc5),
          ('update',0xc30940,0xc30b22))


def region(pe, raw, start, end):
    off = pe.offset(pe.base+start,end-start)
    return raw[off:off+end-start]


def verify():
    original, installed = ORIGINAL.read_bytes(),CURRENT.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(installed).hexdigest() == INSTALLED_SHA
    assert RECIPE_VERSION == 38
    source = patch_component('UnityPlayer.dll',original)
    pe, cp, sp = PE(original),PE(installed),PE(source)
    assert pe.function_ends[pe.base+0xc2f570] == pe.base+0xc2f5c8
    assert pe.function_ends[pe.base+0xc66c20] == pe.base+0xc66fc5
    assert pe.function_ends[pe.base+0xc30940] == pe.base+0xc30b22
    rows, counts = {},{}
    for name,start,end in SLICES:
        decoded = parse_assembly((ASM/f'{name}.asm').read_bytes(),pe,original,start,end)
        rows.update(decoded);counts[name]=len(decoded)
        expected = bytearray(region(pe,original,start,end))
        if name != 'update': expected[0] = 0xc3
        for descriptor,raw in ((cp,installed),(sp,source)):
            assert region(descriptor,raw,start,end) == bytes(expected)
    for at,target in ((0xc2f5b4,0xc2f5d0),(0xc66c64,0xc2f5d0)):
        assert rows[at]['text'].startswith('lea rax, [rip ')
        displacement = int.from_bytes(rows[at]['code'][3:7],'little',signed=True)
        assert at+len(rows[at]['code'])+displacement == target
    for at,target in ((0xc2f5bb,0x1ce04a0),(0xc66c6b,0x1ce04a0),
                      (0xc2f5d0,0x1d0eb28)):
        assert rows[at]['text'].startswith('mov ')
        displacement = int.from_bytes(rows[at]['code'][-4:],'little',signed=True)
        assert at+len(rows[at]['code'])+displacement == target
    assert rows[0xc2f5d7]['text'].startswith('jmp 0x180c30940 ')
    assert rows[0xc30ae0]['text'].startswith('call 0x180c3dc00 ')
    assert rows[0xc30b0d]['text'].startswith('call 0x180c351a0 ')
    assert not any('0x1498' in row['text'] or '0x180c307c0' in row['text']
                   for at,row in rows.items() if 0xc30940 <= at < 0xc30b22)
    return dict(passed=True,recipe=RECIPE_VERSION,original_sha256=ORIGINAL_SHA,
                installed_sha256=INSTALLED_SHA,instructions=counts,
                start_entries_ret=True,update_registration_skipped_on_fresh_start=True,
                update_body_direct_ads_callback=False,
                upstream_advertising_producer_resolved=False)


if __name__ == '__main__': print(json.dumps(verify(),indent=2))
