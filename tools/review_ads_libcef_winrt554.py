"""Bound the installed Chromium WinRT activation lead to its direct import call."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

from tools.extract_descriptors import PE

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / 'local/privacy543-game01/Battle Aces_Data/Plugins/x86_64/VuplexWebViewChromium/libcef.dll'
OUT = ROOT / 'local/privacy554-libcef-winrt01/verification.json'
SHA = 'fbf89a54e550e8021f992a2919cdc2a6d3261dda9df6c2be7912f2a95b97ec22'
LLVM_READOBJ = Path(r'C:\Program Files\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\WebGLSupport\BuildTools\Emscripten\llvm\llvm-readobj.exe')
IAT_RVA = 0xc505318
CALL_RVA = 0x134f0f9
CLASS_RVA = 0xb0e55b0
CLASS = 'Windows.UI.ViewManagement.UIViewSettings'


def review() -> dict:
    data = IMAGE.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    assert digest == SHA
    pe = PE(data)
    assert pe.base == 0x180000000

    imports = subprocess.run([str(LLVM_READOBJ), '--coff-imports', str(IMAGE)],
                             capture_output=True, text=True, check=True).stdout
    block = next(b for b in re.findall(r'DelayImport \{\n(.*?)(?=\nDelayImport \{|\Z)', imports, re.S)
                 if 'Name: api-ms-win-core-winrt-l1-1-0.dll' in b)
    assert 'ImportAddressTable: 0xC505310' in block
    symbols = re.findall(r'Symbol: ([^\n]+)', block)
    assert symbols[:2] == ['RoActivateInstance (0)', 'RoGetActivationFactory (0)']
    assert 0xc505310 + 8 * symbols.index('RoGetActivationFactory (0)') == IAT_RVA

    # Exhaustive byte scan of the installed executable section for the direct
    # x64 call-qword-ptr-[RIP+disp32] form targeting this import slot.
    text_va, text_size, text_off = pe.sections[0]
    assert text_va == pe.base + 0x1000
    hits = []
    cursor = text_off
    while True:
        cursor = data.find(b'\xff\x15', cursor, text_off + text_size)
        if cursor < 0 or cursor + 6 > text_off + text_size:
            break
        site = text_va - pe.base + cursor - text_off
        target = site + 6 + struct.unpack_from('<i', data, cursor + 2)[0]
        if target == IAT_RVA:
            hits.append(site)
        cursor += 1
    assert hits == [CALL_RVA]

    def code(rva: int, expected: str) -> None:
        raw = bytes.fromhex(expected)
        off = pe.offset(pe.base + rva, len(raw))
        assert data[off:off + len(raw)] == raw, hex(rva)

    code(0x134f0c3, '488d05e664d909')  # class literal -> RAX
    code(0x134f0ca, '488d542440')      # stack descriptor -> RDX
    code(0x134f0cf, '488902')          # descriptor string pointer
    code(0x134f0d2, '48c7420828000000')  # 0x28 UTF-16 code units
    code(0x134f0dd, 'e8ee590000')      # HSTRING construction helper
    code(0x134f0ee, '488b4f08')        # resulting HSTRING -> RCX
    code(CALL_RVA, 'ff1519621b0b')    # RoGetActivationFactory import
    assert 0x134f0c3 + 7 + struct.unpack('<i', bytes.fromhex('e664d909'))[0] == CLASS_RVA
    literal = data[pe.offset(pe.base + CLASS_RVA, len(CLASS) * 2):]
    assert literal[:len(CLASS) * 2].decode('utf-16le') == CLASS
    assert literal[len(CLASS) * 2:len(CLASS) * 2 + 2] == b'\0\0'
    assert len(CLASS) == 0x28

    return {
        'passed': True,
        'image': str(IMAGE.relative_to(ROOT)),
        'sha256': digest,
        'direct_import': 'RoGetActivationFactory',
        'iat_rva': hex(IAT_RVA),
        'direct_ff15_call_rvas': [hex(x) for x in hits],
        'direct_class': CLASS,
        'direct_advertising_manager_class': False,
        'indirect_or_computed_routes_qualified': False,
        'full_d5_qualified': False,
    }


if __name__ == '__main__':
    result = review()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
