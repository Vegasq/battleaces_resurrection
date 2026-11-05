"""Classify Ghidra's third OnAdsIdRequestDone data reference."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import struct

from tools.extract_descriptors import PE

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = Path(os.environ.get('BA_ORIGINAL_GAME_ROOT', ROOT / 'local/pristine-game')) / 'UnityPlayer.dll'
SHA = 'ac144d56d53f07904d52ed27a1539de90bc3290038fe52d73d2f6b268c85d6bc'
CALLBACK = 0xc307c0
UNWIND_ENTRY = 0x1daf5cc
TABLES = (0x1a2afb8, 0x1a2c630)


def verify():
    raw = ORIGINAL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SHA
    pe = PE(raw)
    e_lfanew, = struct.unpack_from('<I', raw, 0x3c)
    assert raw[e_lfanew:e_lfanew+4] == b'PE\x00\x00'
    count, optional_size = struct.unpack_from('<HH', raw, e_lfanew+6)[0], struct.unpack_from('<H', raw, e_lfanew+20)[0]
    sections = []
    for index in range(count):
        offset = e_lfanew + 24 + optional_size + 40*index
        name = raw[offset:offset+8].rstrip(b'\x00').decode('ascii')
        virtual_size, rva, disk_size, disk_offset = struct.unpack_from('<IIII', raw, offset+8)
        sections.append((name, rva, virtual_size, disk_size, disk_offset))
    pdata = [item for item in sections if item[0] == '.pdata']
    assert len(pdata) == 1
    _, start, size, disk_size, _ = pdata[0]
    assert start <= UNWIND_ENTRY < UNWIND_ENTRY+12 <= start+min(size, disk_size)
    entry_offset = pe.offset(pe.base+UNWIND_ENTRY)
    begin, end, unwind = struct.unpack_from('<III', raw, entry_offset)
    assert (begin, end, unwind) == (CALLBACK, 0xc30871, 0x1ab315c)
    assert pe.function_ends[pe.base+CALLBACK] == pe.base+end
    for table in TABLES:
        pointer, = struct.unpack_from('<Q', raw, pe.offset(pe.base+table))
        assert pointer == pe.base+CALLBACK
        assert table < start
    return {'passed': True, 'original_sha256': SHA,
            'third_reference_rva': hex(UNWIND_ENTRY),
            'third_reference_kind': 'PE .pdata RUNTIME_FUNCTION begin address',
            'function_end_rva': hex(end), 'unwind_info_rva': hex(unwind),
            'listener_table_rvas': [hex(item) for item in TABLES]}


if __name__ == '__main__':
    print('PASS', verify())
