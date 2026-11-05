"""Bind the native custom-device getter to its cached Main field."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

from client_patch.patcher.telemetry import RECIPE_VERSION, patch_component
from tools.extract_descriptors import PE
from tools.review_ads_cache_tail332 import verify as verify_tail
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA, INSTALLED_SHA
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / 'local/privacy301-runtime01/game/UnityPlayer.dll'
ASM = ROOT / 'local/privacy333-device-field01/unity-204c60.asm'
START, END = 0x204c60, 0x204cae
NAME = b'UnityEngine.Analytics.AnalyticsSessionInfo::get_customDeviceIdInternal\x00'


def body(pe: PE, raw: bytes, start: int, end: int) -> bytes:
    off = pe.offset(pe.base+start, end-start)
    return raw[off:off+end-start]


def verify() -> dict[str, object]:
    assert RECIPE_VERSION == 34 and verify_tail()['passed']
    original, installed = ORIGINAL.read_bytes(), CURRENT.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(installed).hexdigest() == INSTALLED_SHA
    source = patch_component('UnityPlayer.dll', original)
    pe, cp, sp = PE(original), PE(installed), PE(source)
    assert pe.function_ends[pe.base+START] == pe.base+END
    rows = parse_assembly(ASM.read_bytes(), pe, original, START, END)
    assert body(pe, original, START, END) == body(cp, installed, START, END)
    assert body(pe, original, START, END) == body(sp, source, START, END)
    # Indexed native binding is index63,between named getter/setter siblings.
    fn_slot, name_slot = 0x192ff50+8*63, 0x1930280+8*63
    for raw, desc in ((original, pe), (installed, cp), (source, sp)):
        fn = struct.unpack_from('<Q', raw, desc.offset(desc.base+fn_slot, 8))[0]
        name = struct.unpack_from('<Q', raw, desc.offset(desc.base+name_slot, 8))[0]
        assert fn == desc.base+START
        assert raw[desc.offset(name, len(NAME)):][:len(NAME)] == NAME
    assert rows[0x204c64]['text'].startswith('mov rcx, qword ptr [rip +')
    assert '# 0x181d0eb28' in ASM.read_text().split('180204c64:')[1].splitlines()[0]
    assert rows[0x204c6b]['text'] == 'add rcx, 0x14a8'
    assert rows[0x204c72]['text'] == 'cmp byte ptr [rcx + 0x20], 0x1'
    assert rows[0x204c85]['text'] == 'mov edx, dword ptr [rcx + 0x10]'
    assert rows[0x204c88]['text'] == 'mov rcx, qword ptr [rcx]'
    assert rows[0x204c92]['text'] == 'call rax'
    assert rows[0x204c9e]['text'].startswith('call qword ptr [rip +')
    # c330e0 returns the cached value through a separate route;this getter
    # itself makes no direct OS/device API call. Its indirect callees are not
    # classified as a whole-program acquisition proof here.
    return dict(passed=True, source_recipe=RECIPE_VERSION,
                original_sha256=ORIGINAL_SHA, installed_sha256=INSTALLED_SHA,
                function_rva=hex(START), native_registration_index=63,
                assembly_sha256=hashlib.sha256(ASM.read_bytes()).hexdigest(),
                instructions=len(rows), cached_field='Main+14a8',
                indirect_callees_classified=False,
                other_writers_excluded=False, advertising_producer_resolved=False)


if __name__ == '__main__':
    import json
    print(json.dumps(verify(), indent=2))
