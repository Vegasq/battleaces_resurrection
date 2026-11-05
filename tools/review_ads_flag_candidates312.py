"""Classify the five misleading +0x5c literal writes in Unity lightmap code."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

from tools.extract_descriptors import PE
from tools.review_ads_state_callback296 import ORIGINAL, INSTALLED, ORIGINAL_SHA, INSTALLED_SHA
from tools.review_analytics_listener import parse_assembly


ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / 'local/privacy301-runtime01/game/UnityPlayer.dll'
ASM = ROOT / 'local/privacy312-ads-manager-writers01'
WRITERS = {
    0x1050370: 0x105065c,
    0x1050680: 0x10508ef,
    0x1050910: 0x1050a95,
    0x1050ac0: 0x1050c0c,
    0x1050e10: 0x105109e,
}


def verify():
    original, installed, current = ORIGINAL.read_bytes(), INSTALLED.read_bytes(), CURRENT.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(installed).hexdigest() == INSTALLED_SHA
    assert hashlib.sha256(current).hexdigest() == INSTALLED_SHA
    pe, ip = PE(original), PE(installed)
    counts = {}
    for start, write in WRITERS.items():
        end = pe.function_ends[pe.base + start] - pe.base
        rows = parse_assembly((ASM / f'{start:x}.asm').read_bytes(), pe, original, start, end)
        assert rows[write]['text'] == 'mov byte ptr [rax + 0x5c], 0x1'
        assert rows[write]['code'] == bytes.fromhex('c6405c01')
        assert any('0x5d]' in row['text'] and row['text'].startswith('mov byte ptr [')
                   for row in rows.values())
        old, new = pe.offset(pe.base + start, end-start), ip.offset(ip.base + start, end-start)
        assert original[old:old+end-start] == installed[new:new+end-start]
        assert not any('0x181c0af00' in row['text'] or '0x1803611d0' in row['text']
                       for row in rows.values())
        counts[hex(start)] = len(rows)
    root = parse_assembly((ASM / '1050370.asm').read_bytes(), pe, original,
                          0x1050370, pe.function_ends[pe.base + 0x1050370]-pe.base)
    literal = 0x1a503d0
    code = root[0x1050396]['code']
    assert len(code) == 7 and 0x1050396 + 7 + struct.unpack('<i', code[3:])[0] == literal
    name = b'm_EnlightenSceneMapping\0'
    offset = pe.offset(pe.base + literal, len(name))
    assert original[offset:offset+len(name)] == name
    return {'passed': True, 'decoded_instructions': counts,
            'literal_context': 'm_EnlightenSceneMapping',
            'advertising_manager_writer_identified': False}


if __name__ == '__main__':
    print('PASS', verify())
