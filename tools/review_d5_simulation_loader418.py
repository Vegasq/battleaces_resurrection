"""Classify direct dynamic-loader DLL names in the owned Simulation.dll."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re
import struct
import subprocess

from tools.extract_descriptors import PE
from tools.review_d5_simulation_imports417 import DLL, SHA, OUT as PRIOR_OUT, review as review_imports
from tools.review_ads_settings_pair413 import LLVM
from tools.review_d5_connected_pair338 import ROOT

OUT = ROOT / 'local/privacy418-simulation-loader01'
IAT = {'GetProcAddress': 0x385018, 'LoadLibraryA': 0x385020,
       'LoadLibraryExW': 0x385258}
LOAD_A = {0xf324, 0x28bc96, 0x28c095, 0x28c0f7, 0x28c155, 0x28c175}
LOAD_EX_W = {0x34e835, 0x34e86d, 0x367420, 0x367474}
EX_W_TABLES = ((0x3c1d50, 3), (0x3c60f0, 21))
LITERAL_REFS = {
    0xf31d: 0x386c70,
    0x28bc67: 0x3b3a88, 0x28bc79: 0x3b3a98,
    0x28c059: 0x3b3cd0, 0x28c06a: 0x3b3ce0,
    0x28c0bb: 0x3b3cd0, 0x28c0cc: 0x3b3d10,
    0x28c119: 0x3b3cd0, 0x28c12a: 0x3b3d40,
    0x28c16e: 0x386c70,
}


def cstr(pe, raw, rva):
    offset = pe.offset(pe.base + rva, 1)
    return raw[offset:offset+120].split(b'\0', 1)[0].decode('ascii')


def wstr(pe, raw, rva):
    offset = pe.offset(pe.base + rva, 2)
    data = raw[offset:offset+240]
    end = next(i for i in range(0, len(data)-1, 2) if data[i:i+2] == b'\0\0')
    return data[:end].decode('utf-16le')


def review() -> dict:
    prior = review_imports()
    assert prior['passed'] and prior['simulation_sha256'] == SHA
    raw = DLL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SHA
    pe = PE(raw)
    assert pe.base == 0x180000000
    imports = (PRIOR_OUT / 'imports.txt').read_text(encoding='utf-8')
    symbols = re.findall(r'^  Symbol: ([^ ]+) ', imports, re.M)
    for name, rva in IAT.items():
        assert 0x385000 + 8 * symbols.index(name) == rva

    process = subprocess.Popen([str(LLVM), '-d', '--section=.text',
                                '--x86-asm-syntax=intel', str(DLL)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True)
    assert process.stdout is not None and process.stderr is not None
    sites = defaultdict(set)
    literal_refs = {}
    line_re = re.compile(r'^([0-9a-f]+): ((?:[0-9a-f]{2} )+).*# 0x([0-9a-f]+)\s*$')
    for line in process.stdout:
        match = line_re.match(line)
        if not match:
            continue
        target = int(match[3], 16) - pe.base
        site = int(match[1], 16) - pe.base
        code = bytes.fromhex(match[2])
        if site in LITERAL_REFS:
            assert target == LITERAL_REFS[site]
            assert site + len(code) + struct.unpack_from('<i', code, 3)[0] == target
            literal_refs[site] = target
        if target not in IAT.values():
            continue
        assert code[:2] == b'\xff\x15' and len(code) == 6
        assert site + 6 + struct.unpack_from('<i', code, 2)[0] == target
        assert raw[pe.offset(pe.base + site, 6):pe.offset(pe.base + site, 6)+6] == code
        sites[target].add(site)
    assert process.wait() == 0 and process.stderr.read() == ''
    assert literal_refs == LITERAL_REFS
    assert sites[IAT['LoadLibraryA']] == LOAD_A
    assert sites[IAT['LoadLibraryExW']] == LOAD_EX_W
    assert len(sites[IAT['GetProcAddress']]) == 65
    for site, code in ((0x34e822, '4d 8b bc f7 50 1d 3c 00'),
                       (0x36740d, '4d 8b b4 f6 f0 60 3c 00')):
        expected = bytes.fromhex(code)
        offset = pe.offset(pe.base+site, len(expected))
        assert raw[offset:offset+len(expected)] == expected

    ascii_names = {rva: cstr(pe, raw, rva) for rva in
                   (0x386c70, 0x3b3a88, 0x3b3a98, 0x3b3cd0,
                    0x3b3ce0, 0x3b3d10, 0x3b3d40)}
    assert ascii_names == {
        0x386c70: 'dbghelp.dll', 0x3b3a88: 'kernel32.dll',
        0x3b3a98: 'tlhelp32.dll', 0x3b3cd0: 'ProgramFiles',
        0x3b3ce0: r'\Debugging Tools for Windows (x64)\dbghelp.dll',
        0x3b3d10: r'\Debugging Tools for Windows\dbghelp.dll',
        0x3b3d40: r'\Debugging Tools for Windows 64-Bit\dbghelp.dll'}
    wide_tables = []
    for base, count in EX_W_TABLES:
        names = []
        for index in range(count):
            address = struct.unpack('<Q', raw[pe.offset(pe.base+base+index*8, 8):][:8])[0]
            assert pe.base <= address < pe.base + 0x500000
            names.append(wstr(pe, raw, address-pe.base))
        wide_tables.append(dict(rva=hex(base), names=names))
    assert wide_tables[0]['names'] == [
        'api-ms-win-core-fibers-l1-1-1', 'api-ms-win-core-synch-l1-2-0', 'kernel32']
    assert len(wide_tables[1]['names']) == 21
    assert wide_tables[1]['names'][0] == 'api-ms-win-core-datetime-l1-1-1'
    assert wide_tables[1]['names'][-1] == 'user32'
    all_names = list(ascii_names.values()) + [name for table in wide_tables for name in table['names']]
    assert not any(token in name.lower() for name in all_names
                   for token in ('ws2_32', 'winhttp', 'wininet', 'websocket'))
    result = dict(passed=True, simulation_sha256=SHA,
                  import_call_sites={name: [hex(x) for x in sorted(sites[rva])]
                                     for name, rva in IAT.items()},
                  direct_ascii_literals={hex(rva): name for rva, name in ascii_names.items()},
                  loadlibraryexw_tables=wide_tables,
                  selected_loader_names_have_no_network_dll=True,
                  getprocaddress_targets_and_indirect_loader_calls_unresolved=True,
                  full_d5_qualified=False)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps(dict(passed=True, call_counts={name: len(sites)
                  for name, sites in result['import_call_sites'].items()},
                  wide_names=sum(len(t['names']) for t in result['loadlibraryexw_tables']))))
