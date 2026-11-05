"""Classify Ghidra's PerformPost/Begin data xrefs against pristine PE unwind data."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import struct

from tools.extract_descriptors import PE

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = Path(os.environ.get('BA_ORIGINAL_GAME_ROOT', ROOT / 'local/pristine-game')) / 'UnityPlayer.dll'
ORIGINAL_SHA = 'ac144d56d53f07904d52ed27a1539de90bc3290038fe52d73d2f6b268c85d6bc'
LOG = ROOT / 'local/d5-ghidra-12.1.4/pdb-perform-post512-final2-console.log'
LOG_SHA = '68fe826092f022ea3b5998ed4e5f3d64ebef297f6ae7bf6e0b38b872afaf891a'
ENTRIES = {
    0x1db13b4: (0xc64e20, 0xc64e9c, 0x1ab3108),
    0x1db13c0: (0xc64ea0, 0xc64f2c, 0x1ab315c),
}
REFS = {
    0xc64e20: ((0x1db13b4, 'DATA'), (0xc59630, 'UNCONDITIONAL_CALL'),
                (0xc56b65, 'UNCONDITIONAL_CALL')),
    0xc64ea0: ((0x1db13c0, 'DATA'), (0xc64e97, 'UNCONDITIONAL_CALL')),
}


def verify() -> dict:
    raw = ORIGINAL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    log = LOG.read_bytes()
    assert hashlib.sha256(log).hexdigest() == LOG_SHA
    pe = PE(raw)
    e_lfanew, = struct.unpack_from('<I', raw, 0x3c)
    assert raw[e_lfanew:e_lfanew + 4] == b'PE\0\0'
    section_count, optional_size = struct.unpack_from('<HH', raw, e_lfanew + 6)[0], struct.unpack_from('<H', raw, e_lfanew + 20)[0]
    pdata = []
    for index in range(section_count):
        offset = e_lfanew + 24 + optional_size + 40 * index
        name = raw[offset:offset + 8].rstrip(b'\0').decode('ascii')
        virtual_size, rva, disk_size = struct.unpack_from('<III', raw, offset + 8)
        if name == '.pdata':
            pdata.append((rva, min(virtual_size, disk_size)))
    assert len(pdata) == 1
    start, size = pdata[0]
    rows = []
    for entry_rva, expected in ENTRIES.items():
        assert start <= entry_rva < entry_rva + 12 <= start + size
        actual = struct.unpack_from('<III', raw, pe.offset(pe.base + entry_rva))
        assert actual == expected
        assert pe.function_ends[pe.base + expected[0]] == pe.base + expected[1]
        rows.append({'entry_rva': hex(entry_rva), 'kind': 'PE .pdata RUNTIME_FUNCTION',
                     'begin_rva': hex(actual[0]), 'end_rva': hex(actual[1]),
                     'unwind_rva': hex(actual[2])})
    text = log.decode('utf-16')
    for target, expected in REFS.items():
        block = re.search(r'TracePerformPost512\.java> FUNCTION 180' + f'{target:x}' +
                          r'\b(.*?)(?=TracePerformPost512\.java> FUNCTION |TracePerformPost512\.java> EXTRA |\Z)',
                          text, re.S)
        assert block is not None
        observed = [(int(address, 16) - 0x180000000, kind)
                    for address, kind in re.findall(
                        r'TracePerformPost512\.java> REF (18[0-9a-f]+) (DATA|UNCONDITIONAL_CALL)',
                        block.group(1))]
        assert sorted(observed) == sorted(expected)
    return {'passed': True, 'original_sha256': ORIGINAL_SHA, 'ghidra_log_sha256': LOG_SHA,
            'entries': rows, 'direct_references': {hex(k): [[hex(a), t] for a, t in v]
                                                 for k, v in REFS.items()},
            'claim': 'Both Ghidra data references are PE unwind entries; reviewed code refs are unchanged.'}


if __name__ == '__main__':
    print(json.dumps(verify(), sort_keys=True))
