"""Bind direct caller names passed to Simulation.dll's two API-set resolvers."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re
import struct
import subprocess

from tools.extract_descriptors import PE
from tools.review_d5_simulation_imports417 import DLL, SHA
from tools.review_d5_simulation_getproc419 import review as review_getproc
from tools.review_ads_settings_pair413 import LLVM
from tools.review_d5_connected_pair338 import ROOT

OUT = ROOT / 'local/privacy420-simulation-resolver-callers01'
RESOLVERS = {0x34e7b0: 5, 0x367380: 28}
EXPECTED_NAMES = {
    'FlsAlloc', 'FlsFree', 'FlsGetValue', 'FlsSetValue',
    'InitializeCriticalSectionEx', 'AppPolicyGetProcessTerminationMethod',
    'AppPolicyGetThreadInitializationType', 'AreFileApisANSI',
    'CompareStringEx', 'EnumSystemLocalesEx', 'GetDateFormatEx',
    'GetLocaleInfoEx', 'GetTimeFormatEx', 'GetUserDefaultLocaleName',
    'IsValidLocaleName', 'LCIDToLocaleName', 'LCMapStringEx',
    'LocaleNameToLCID', 'RoInitialize', 'RoUninitialize',
}
INSTRUCTION = re.compile(r'^([0-9a-f]+): ((?:[0-9a-f]{2} )+)\s+(.+)$')
COMMENT = re.compile(r'# 0x([0-9a-f]+)\s*$')


def review() -> dict:
    prior = review_getproc()
    raw = DLL.read_bytes()
    assert prior['passed'] and hashlib.sha256(raw).hexdigest() == SHA
    assert set(prior['dynamic_sites']) == {'0x34e8bf', '0x367508'}
    pe = PE(raw)
    process = subprocess.Popen([str(LLVM), '-d', '--section=.text',
                                '--x86-asm-syntax=intel', str(DLL)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True)
    assert process.stdout is not None and process.stderr is not None
    window = []
    hits = defaultdict(list)
    for line in process.stdout:
        match = INSTRUCTION.match(line)
        if not match:
            continue
        site = int(match[1], 16) - pe.base
        code = bytes.fromhex(match[2])
        instruction = match[3]
        window.append((site, code, instruction))
        window = window[-5:]
        if not instruction.startswith(('call\t0x', 'jmp\t0x')):
            continue
        target_match = re.match(r'^(?:call|jmp)\t0x([0-9a-f]+)', instruction)
        assert target_match
        target = int(target_match[1], 16) - pe.base
        if target not in RESOLVERS:
            continue
        assert code[0] in (0xe8, 0xe9) and len(code) == 5
        assert site + 5 + struct.unpack_from('<i', code, 1)[0] == target
        candidates = [(index, row) for index, row in enumerate(window[:-1])
                      if row[2].startswith('lea\trdx, [rip +')]
        assert candidates
        index, (lea_site, lea_code, lea_text) = candidates[-1]
        assert len(window) - 1 - index in (1, 2, 3)
        assert lea_code[:3] == b'\x48\x8d\x15' and len(lea_code) == 7
        name_rva = lea_site + 7 + struct.unpack_from('<i', lea_code, 3)[0]
        comment = COMMENT.search(lea_text)
        assert comment and int(comment[1], 16) - pe.base == name_rva
        assert all('rdx' not in row[2].split('#', 1)[0] for row in window[index+1:-1])
        offset = pe.offset(pe.base+name_rva, 1)
        text = raw[offset:offset+120].split(b'\0', 1)[0]
        assert 1 <= len(text) < 120 and all(32 <= ch < 127 for ch in text)
        name = text.decode('ascii')
        hits[target].append(dict(site=hex(site), name_rva=hex(name_rva), name=name,
                                 tail_jump=code[0] == 0xe9))
    assert process.wait() == 0 and process.stderr.read() == ''
    assert {target: len(rows) for target, rows in hits.items()} == RESOLVERS
    assert len({row['site'] for rows in hits.values() for row in rows}) == 33
    assert {row['name'] for rows in hits.values() for row in rows} == EXPECTED_NAMES
    assert sum(row['tail_jump'] for rows in hits.values() for row in rows) == 1
    result = dict(passed=True, simulation_sha256=SHA,
                  resolver_direct_callers={hex(target): sorted(rows, key=lambda row: int(row['site'], 16))
                                           for target, rows in hits.items()},
                  direct_callers=33, distinct_function_names=len(EXPECTED_NAMES),
                  direct_caller_names_have_no_network_api=True,
                  indirect_resolver_callers_and_wire_unresolved=True,
                  full_d5_qualified=False)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps(dict(passed=True, direct_callers=result['direct_callers'],
                          distinct_names=result['distinct_function_names'])))
