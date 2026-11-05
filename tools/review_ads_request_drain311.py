"""Bind original advertising request -> state predicate -> callback drain path."""
from __future__ import annotations

import hashlib
from pathlib import Path

from tools.extract_descriptors import PE
from tools.review_ads_state_callback296 import ORIGINAL, INSTALLED, ORIGINAL_SHA, INSTALLED_SHA
from tools.review_analytics_listener import parse_assembly


ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / 'local/privacy301-runtime01/game/UnityPlayer.dll'
ASM = ROOT / 'local/privacy311-ads-request01'
BODIES = {
    'request-5fb70': (0x5fb70, 0x5fca2),
    'predicate': (0x3611d0, 0x361251),
    'start': (0x361510, 0x3615e5),
    'drain-one': (0x361260, 0x361504),
}
ANCHORS = {
    'request-5fb70': {
        0x5fbad: 'mov rdi, qword ptr [rip + 0x1bab34c]',
        0x5fc52: 'inc qword ptr [rdi + 0x70]',
        0x5fc6b: 'call 0x1803611d0 <.text+0x3601d0>',
        0x5fc77: 'call 0x180361510 <.text+0x360510>',
    },
    'predicate': {
        0x3611d6: 'cmp byte ptr [rcx + 0x5c], 0x0',
        0x361230: 'mov byte ptr [rbx + 0x5c], 0x0',
        0x361242: 'mov dword ptr [rbx + 0x60], 0x1',
    },
    'start': {
        0x36155c: 'call 0x180361260 <.text+0x360260>',
        0x3615d1: 'mov qword ptr [rsi + 0x70], rbp',
    },
    'drain-one': {
        0x3613f4: 'call rax',
        0x361450: 'call 0x18076f650 <.text+0x76e650>',
    },
}


def verify():
    original, installed, current = ORIGINAL.read_bytes(), INSTALLED.read_bytes(), CURRENT.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(installed).hexdigest() == INSTALLED_SHA
    assert hashlib.sha256(current).hexdigest() == INSTALLED_SHA
    pe, ip = PE(original), PE(installed)
    lengths = {}
    for name, (start, end) in BODIES.items():
        assert pe.function_ends[pe.base + start] == pe.base + end
        rows = parse_assembly((ASM / (name + '.asm')).read_bytes(), pe, original, start, end)
        for rva, expected in ANCHORS[name].items():
            assert rows[rva]['text'] == expected, (name, hex(rva), rows[rva]['text'])
        old_offset, new_offset = pe.offset(pe.base + start, end-start), ip.offset(ip.base + start, end-start)
        assert original[old_offset:old_offset+end-start] == installed[new_offset:new_offset+end-start]
        assert not any('0x180c307c0' in row['text'] or '0x1498]' in row['text']
                       for row in rows.values())
        lengths[name] = len(rows)
    return {'passed': True, 'decoded_instructions': lengths,
            'named_path': '5fb70 -> 3611d0 -> 361510 -> 361260',
            'direct_advertising_callback_or_main1498': False}


if __name__ == '__main__':
    print('PASS', verify())
