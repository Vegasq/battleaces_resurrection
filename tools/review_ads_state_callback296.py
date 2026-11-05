"""Bounded original Main.Start connection-state callback review."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import struct

from tools.extract_descriptors import PE
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT.parent.parent / 'BattleAcesBeta_untouched/UnityPlayer.dll'
INSTALLED = ROOT / 'local/privacy291-runtime01/game/UnityPlayer.dll'
EVIDENCE = ROOT / 'local/privacy296-start-state01'
ORIGINAL_SHA = 'ac144d56d53f07904d52ed27a1539de90bc3290038fe52d73d2f6b268c85d6bc'
INSTALLED_SHA = 'a53b0c613a86c737b7caa7588c7c93ae20d5d5700f9321a406df9dcca8e32a7f'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def region(pe, raw, start, end):
    return raw[pe.offset(pe.base + start, end - start):][:end - start]


def review():
    original, installed = ORIGINAL.read_bytes(), INSTALLED.read_bytes()
    require(sha(original) == ORIGINAL_SHA and sha(installed) == INSTALLED_SHA,
            'Unity image identity differs')
    pe, ip = PE(original), PE(installed)
    sources = {
        0xc2f570: (0xc2f5c8, ROOT / 'local/privacy109-adsidentity01/unity-c2f570.asm'),
        0xc66c20: (0xc66fc5, ROOT / 'local/privacy183-dispatch01/unity-c66c20.asm'),
        0xc2f640: (0xc2f786, EVIDENCE / 'unity-c2f640.asm'),
    }
    rows, files = {}, {}
    for start, (end, path) in sources.items():
        require(pe.function_ends.get(pe.base + start) == pe.base + end,
                f'unwind extent differs at {start:x}')
        data = path.read_bytes()
        rows.update(parse_assembly(data, pe, original, start, end))
        files[path.name] = sha(data)
    path = EVIDENCE / 'unity-c343d0-c34430.asm'
    data = path.read_bytes()
    selected = []
    for line in data.decode('utf-8').splitlines():
        match = re.match(r'^([0-9a-f]+): ', line)
        if match and 0xc343d0 <= int(match[1], 16) - pe.base < 0xc3442b:
            selected.append(line)
    require(pe.function_ends.get(pe.base + 0xc343d0) == pe.base + 0xc3442b,
            'state helper unwind extent differs')
    rows.update(parse_assembly(('\n'.join(selected) + '\n').encode(), pe, original,
                               0xc343d0, 0xc3442b))
    files[path.name] = sha(data)
    anchors = {
        0xc2f589: 'lea r8, [rip + 0xb0]',
        0xc2f59c: 'call 0x18035b140',
        0xc66c39: 'lea r8, [rip - 0x37600]',
        0xc66c4c: 'call 0x18035b140',
        0xc2f64f: 'test edx, edx',
        0xc2f657: 'cmp edx, 0x2',
        0xc2f667: 'mov qword ptr [rcx + 0xf38], r8',
        0xc2f67f: 'mov qword ptr [rcx + 0xf40], rax',
        0xc2f730: 'mov rax, qword ptr [rbx]',
        0xc2f736: 'call qword ptr [rax + 0x38]',
        0xc2f73c: 'call 0x180c30df0',
        0xc2f757: 'jmp 0x180c3b990',
        0xc2f770: 'jmp 0x180c343d0',
        0xc2f778: 'call qword ptr [rax + 0x38]',
        0xc343db: 'cmp byte ptr [rbx + 0xc4], cl',
        0xc34413: 'call qword ptr [rax + 0xa0]',
    }
    for rva, expected in anchors.items():
        require(rows.get(rva, {}).get('text', '').split(' <', 1)[0] == expected,
                f'anchor differs at {rva:x}: {rows.get(rva)}')
    require(not any('0x180c307c0' in rows[rva]['text']
                    for rva in rows if 0xc2f640 <= rva < 0xc2f786),
            'direct advertising callback call found in state callback')
    for table in (0x1a2aec0, 0x1a2c538):
        for slot, target in ((0x38, 0xc34430), (0xa0, 0xc3d120)):
            address = struct.unpack('<Q', region(pe, original, table + slot,
                                                  table + slot + 8))[0]
            require(address == pe.base + target,
                    f'vtable {table:x}+{slot:x} differs')
    for start, end in ((0xc2f570, 0xc2f5c8), (0xc66c20, 0xc66fc5)):
        old, new = region(pe, original, start, end), region(ip, installed, start, end)
        require(new == b'\xc3' + old[1:], f'Start guard/tail differs at {start:x}')
    for start, end in ((0xc2f640, 0xc2f786), (0xc343d0, 0xc3442b)):
        require(region(pe, original, start, end) == region(ip, installed, start, end),
                f'callback/helper differs at {start:x}')
    return {
        'passed': True,
        'scope': 'Two named fresh Start registrations and immediate connection-state callback only',
        'original_sha256': sha(original), 'installed_sha256': sha(installed),
        'asm_sha256': files, 'decoded_instructions': len(rows),
        'semantic_anchors': len(anchors),
        'base_and_derived_start_entry_ret': True,
        'callback_and_state_helper_unchanged': True,
        'both_main_vtables_slot38': 'c34430',
        'both_main_vtables_slot_a0': 'c3d120',
        'upstream_advertising_producer_resolved': False,
        'retained_or_other_registrations_excluded': False,
        'full_privacy_qualified': False,
    }


if __name__ == '__main__':
    result = review()
    output = EVIDENCE / 'verification.json'
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print('PASS', output)
