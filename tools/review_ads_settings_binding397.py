"""Bound one Unity Ads settings name/function-table lead in original UnityPlayer.

The table pairing alone is not proof that this separate table is registered or
called by Battle Aces. This tool never invokes a Unity API or reads an ID.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import subprocess

from tools.ads_connected382 import GAME
from tools.extract_descriptors import PE
from tools.frida_ads_caller import describe_unity
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/privacy397-ads-settings01'
LLVM = Path(r'C:\Program Files\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\WebGLSupport\BuildTools\Emscripten\llvm\llvm-objdump.exe')
NAME = b'UnityEngine.Advertisements.UnityAdsSettings::get_enabled\0'
NAME_SLOT, FUNCTION_SLOT = 0x192d090, 0x192d0f0
FUNCTION_START, FUNCTION_END = 0x1f3be0, 0x1f3c2e
REGISTRY_NAMES, REGISTRY_COUNT = 0x18cfac0, 3471


def review() -> dict:
    raw = ORIGINAL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    installed = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(raw, installed)
    pe, ip = PE(raw), PE(installed)
    name_offset = raw.find(NAME)
    assert name_offset >= 0 and raw.find(NAME, name_offset + 1) == -1
    name_va = pe.address(name_offset)
    assert struct.unpack_from('<Q', raw, pe.offset(pe.base + NAME_SLOT, 8))[0] == name_va
    assert struct.unpack_from('<Q', raw, pe.offset(pe.base + FUNCTION_SLOT, 8))[0] == pe.base + FUNCTION_START
    for rva in (NAME_SLOT, FUNCTION_SLOT):
        assert raw[pe.offset(pe.base + rva, 8):pe.offset(pe.base + rva, 8) + 8] == \
               installed[ip.offset(ip.base + rva, 8):ip.offset(ip.base + rva, 8) + 8]
    registry = raw[pe.offset(pe.base + REGISTRY_NAMES, REGISTRY_COUNT * 8):
                   pe.offset(pe.base + REGISTRY_NAMES, REGISTRY_COUNT * 8) + REGISTRY_COUNT * 8]
    assert all(struct.unpack_from('<Q', registry, i * 8)[0] != name_va
               for i in range(REGISTRY_COUNT))
    assert pe.function_ends[pe.base + FUNCTION_START] == pe.base + FUNCTION_END
    size = FUNCTION_END - FUNCTION_START
    assert raw[pe.offset(pe.base + FUNCTION_START, size):pe.offset(pe.base + FUNCTION_START, size) + size] == \
           installed[ip.offset(ip.base + FUNCTION_START, size):ip.offset(ip.base + FUNCTION_START, size) + size]
    assembly = subprocess.check_output([
        str(LLVM), '-d', f'--start-address={pe.base + FUNCTION_START:#x}',
        f'--stop-address={pe.base + FUNCTION_END:#x}', '--x86-asm-syntax=intel',
        str(ORIGINAL)])
    OUT.mkdir(exist_ok=True)
    (OUT / 'get-enabled.asm').write_bytes(assembly)
    decoded = parse_assembly(assembly, pe, raw, FUNCTION_START, FUNCTION_END)
    assert decoded[0x1f3be4]['text'].startswith('mov rcx, qword ptr [rip +')
    assert decoded[0x1f3beb]['text'] == 'add rcx, 0x168'
    assert decoded[0x1f3c12]['text'] == 'call rax'
    assert not any('0x180c307c0' in row['text'] or '0x1498' in row['text']
                   for row in decoded.values())
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  installed_sha256=descriptor['fileSha256'], recipe=descriptor['recipe'],
                  name_slot=hex(NAME_SLOT), function_slot=hex(FUNCTION_SLOT),
                  function=hex(FUNCTION_START), decoded_instructions=len(decoded),
                  name_absent_from_bound_3471_registry=True,
                  direct_advertising_callback_reference=False,
                  other_registry_and_indirect_callee_unresolved=True,
                  producer_resolved=False)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))
