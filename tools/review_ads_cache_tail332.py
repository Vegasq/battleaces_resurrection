"""Bind the remaining c32430 identity-cache helper to cached-string reads."""
from __future__ import annotations

import hashlib
from pathlib import Path

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.extract_descriptors import PE
from tools.review_ads_slotc8_cache327 import verify as verify_cache
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA, INSTALLED_SHA
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
ASM = ROOT / 'local/privacy332-cache-tail01/unity-c330e0.asm'
CURRENT = ROOT / 'local/privacy301-runtime01/game/UnityPlayer.dll'
START, END = 0xc330e0, 0xc331b3


def body(pe: PE, raw: bytes, start: int, end: int) -> bytes:
    off = pe.offset(pe.base + start, end-start)
    return raw[off:off+end-start]


def verify() -> dict[str, object]:
    assert RECIPE_VERSION == 34 and verify_cache()['passed']
    original, installed = ORIGINAL.read_bytes(), CURRENT.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(installed).hexdigest() == INSTALLED_SHA
    source = patch_component('UnityPlayer.dll', original)
    pe, cp, sp = PE(original), PE(installed), PE(source)
    assert pe.function_ends[pe.base+START] == pe.base+END
    rows = parse_assembly(ASM.read_bytes(), pe, original, START, END)
    assert len(rows) == 56
    for raw, desc in ((installed, cp), (source, sp)):
        assert body(desc, raw, START, END) == body(pe, original, START, END)
    # This helper receives Main in RCX and its caller's output string in RDX.
    # It either copies the existing Main+14a8 string or the literal unknown.
    anchors = {
        0xc330ef: 'cmp byte ptr [rcx + 0x14c8], 0x1',
        0xc3311e: 'cmp byte ptr [rdi + 0x15c1], 0x0',
        0xc33127: 'cmp byte ptr [rdi + 0x15c2], 0x0',
        0xc33136: 'call qword ptr [rax + 0xf0]',
        0xc33161: 'lea rdx, [rdi + 0x14a8]',
    }
    for rva, expected in anchors.items():
        assert rows[rva]['text'] == expected
    assert rows[0xc3319b]['text'].startswith('call 0x18015b680 ')
    assert rows[0xc33147]['text'].startswith('lea rdx, [rip +')
    assert rows[0xc33147]['code'] == bytes.fromhex('488d155a5ed500')
    assert rows[0xc3314e]['text'] == 'mov byte ptr [rbx], 0x0'
    assert rows[0xc3315b]['text'] == 'mov byte ptr [rbx + 0x20], 0x1'
    assert [rva for rva, row in rows.items() if row['text'].startswith('call ')] == [0xc33136, 0xc3319b]
    assert body(pe, original, 0x1988fa8, 0x1988fb0) == b'unknown\x00'
    # Existing custom-device setter cannot populate Main+14a8 through its
    # original input/conversion path in a current fresh process.
    patch = [p for p in COMPONENTS['UnityPlayer.dll'].patches
             if p.label == 'Unity Analytics custom device identity setter before input conversion']
    assert len(patch) == 1 and patch[0].rva == 0x204cb0 and patch[0].replacement == b'\xc3'
    assert body(cp, installed, 0x204cb0, 0x204cb1) == b'\xc3'
    assert body(sp, source, 0x204cb0, 0x204cb1) == b'\xc3'
    # The reviewed original constructor starts the cached string empty.
    ctor = ROOT / 'local/privacy136-adjacent-source01/unity-c2ee90.asm'
    end = pe.function_ends[pe.base+0xc2ee90]-pe.base
    constructor = parse_assembly(ctor.read_bytes(), pe, original, 0xc2ee90, end)
    assert constructor[0xc2ef03]['text'] == 'mov byte ptr [rdi + 0x14a8], 0x0'
    assert constructor[0xc2ef0f]['text'] == 'mov byte ptr [rdi + 0x14c0], 0x18'
    assert constructor[0xc2ef1b]['text'] == 'mov byte ptr [rdi + 0x14c8], 0x1'
    assert body(cp, installed, 0xc2ee90, 0xc2ef22) == body(pe, original, 0xc2ee90, 0xc2ef22)
    return dict(passed=True, source_recipe=RECIPE_VERSION,
                original_sha256=ORIGINAL_SHA, installed_sha256=INSTALLED_SHA,
                helper_instructions=len(rows), helper_assembly_sha256=hashlib.sha256(ASM.read_bytes()).hexdigest(),
                cached_device_field='Main+14a8', selected_os_query=False,
                other_writers_excluded=False, advertising_callback_producer_resolved=False)


if __name__ == '__main__':
    print('PASS', verify())
