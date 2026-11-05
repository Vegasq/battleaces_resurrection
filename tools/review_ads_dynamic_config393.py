"""Pin the c69270 configuration callback's immediate lookup/subscription path.

This is a bounded native-source review, not proof that advertising acquisition
is absent elsewhere. Raw disassembly and the receipt stay under ignored local/.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from tools.ads_connected382 import GAME
from tools.extract_descriptors import PE
from tools.frida_ads_caller import describe_unity
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/privacy393-dynamic-config01'
LLVM = Path(r'C:\Program Files\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\WebGLSupport\BuildTools\Emscripten\llvm\llvm-objdump.exe')
BODIES = {0xc42f40: 0xc42fca, 0xc69270: 0xc692f2, 0x56ca40: 0x56cb11}


def review() -> dict:
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    installed = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(original, installed)
    pe, ip = PE(original), PE(installed)
    OUT.mkdir(parents=True, exist_ok=True)
    decoded = {}
    for start, end in BODIES.items():
        assert pe.function_ends[pe.base + start] == pe.base + end
        size = end - start
        assert original[pe.offset(pe.base + start, size):pe.offset(pe.base + start, size) + size] == \
            installed[ip.offset(ip.base + start, size):ip.offset(ip.base + start, size) + size]
        raw = subprocess.check_output([
            str(LLVM), '-d', f'--start-address={pe.base + start:#x}',
            f'--stop-address={pe.base + end:#x}', '--x86-asm-syntax=intel',
            str(ORIGINAL)])
        (OUT / f'{start:x}.asm').write_bytes(raw)
        decoded[start] = parse_assembly(raw, pe, original, start, end)
    lookup, callback, subscribe = (decoded[x] for x in BODIES)
    assert callback[0xc6927a]['text'] == 'mov rdi, qword ptr [rcx + 0x40]'
    assert callback[0xc69286]['text'] == 'lea rdx, [rcx + 0x8]'
    assert callback[0xc6928a]['text'] == 'lea rcx, [rdi + 0x1850]'
    assert callback[0xc69291]['text'].startswith('call 0x180c42f40 ')
    assert callback[0xc692a4]['text'] == 'cmp dword ptr [rdx], 0x9'
    assert callback[0xc692ab]['text'] == 'mov qword ptr [rbx], rcx'
    assert callback[0xc692ae]['text'] == 'movzx eax, byte ptr [rdi + 0x1890]'
    assert callback[0xc692b5]['text'] == 'mov byte ptr [rbx + 0x48], al'
    assert callback[0xc692bd]['text'] == 'mov rdx, qword ptr [rbx + 0x30]'
    assert callback[0xc692d5]['text'].startswith('jmp 0x18056ca40 ')
    assert lookup[0xc42fad]['text'] == 'lea rax, [rdi + 0x48]'
    assert lookup[0xc42fb3]['text'] == 'xor eax, eax'
    assert subscribe[0x56caec]['text'] == 'mov qword ptr [rax + 0x8], rsi'
    assert subscribe[0x56caf7]['text'] == 'xchg qword ptr [rax + 0x40], rcx'
    assert all('0x1498' not in row['text'] and '0x180c307c0' not in row['text']
               for body in decoded.values() for row in body.values())
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  installed_sha256=descriptor['fileSha256'], recipe=descriptor['recipe'],
                  decoded_instructions={hex(key): len(value) for key, value in decoded.items()},
                  selected_path='c69270 -> c42f40 typed lookup -> c56ca40 generic subscription',
                  direct_advertising_callback_or_Main1498_reference=False,
                  upstream_advertising_producer_resolved=False)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))
