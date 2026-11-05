"""Resolve literal names at direct GetProcAddress sites in Simulation.dll."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
import struct
import subprocess

from tools.extract_descriptors import PE
from tools.review_d5_simulation_imports417 import DLL, SHA
from tools.review_d5_simulation_loader418 import review as review_loader
from tools.review_ads_settings_pair413 import LLVM
from tools.review_d5_connected_pair338 import ROOT

OUT = ROOT / 'local/privacy419-simulation-getproc01'
DYNAMIC_SITES = {0x34e8bf: 0x34e7df, 0x367508: 0x3673b0}
EXPECTED_OWNER_COUNTS = {
    0xf210: 1, 0x28bc30: 3, 0x28c020: 13,
    0x33e70c: 3, 0x33fb68: 40, 0x340ce4: 2,
    0x34e7b0: 1, 0x361bf0: 1, 0x367380: 1,
}
INSTRUCTION = re.compile(r'^([0-9a-f]+): ((?:[0-9a-f]{2} )+)\s+(.+)$')
COMMENT = re.compile(r'# 0x([0-9a-f]+)\s*$')


def review() -> dict:
    prior = review_loader()
    raw = DLL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SHA == prior['simulation_sha256']
    pe = PE(raw)
    getproc_sites = {int(x, 16) for x in prior['import_call_sites']['GetProcAddress']}
    assert len(getproc_sites) == 65
    process = subprocess.Popen([str(LLVM), '-d', '--section=.text',
                                '--x86-asm-syntax=intel', str(DLL)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True)
    assert process.stdout is not None and process.stderr is not None
    window = []
    literals = []
    dynamic = []
    for line in process.stdout:
        match = INSTRUCTION.match(line)
        if not match:
            continue
        site = int(match[1], 16) - pe.base
        code = bytes.fromhex(match[2])
        text = match[3]
        window.append((site, code, text))
        window = window[-5:]
        if site not in getproc_sites:
            continue
        assert code[:2] == b'\xff\x15' and len(code) == 6
        assert site + 6 + struct.unpack_from('<i', code, 2)[0] == 0x385018
        if site in DYNAMIC_SITES:
            assert window[-3][2].startswith('mov\trdx, r13')
            dynamic.append(hex(site))
            continue
        candidates = [(index, row) for index, row in enumerate(window[:-1])
                      if row[2].startswith('lea\trdx, [rip +')]
        assert len(candidates) >= 1
        index, (lea_site, lea_code, lea_text) = candidates[-1]
        assert len(window) - 1 - index in (1, 2, 3)
        assert lea_code[:3] == b'\x48\x8d\x15' and len(lea_code) == 7
        target = lea_site + 7 + struct.unpack_from('<i', lea_code, 3)[0]
        comment = COMMENT.search(lea_text)
        assert comment and int(comment[1], 16) - pe.base == target
        assert all('rdx' not in row[2].split('#', 1)[0] for row in window[index+1:-1])
        offset = pe.offset(pe.base + target, 1)
        name_bytes = raw[offset:offset+120].split(b'\0', 1)[0]
        assert 1 <= len(name_bytes) < 120 and all(32 <= ch < 127 for ch in name_bytes)
        literals.append(dict(site=hex(site), literal_rva=hex(target),
                             name=name_bytes.decode('ascii')))
    assert process.wait() == 0 and process.stderr.read() == ''
    assert len(literals) == 63 and set(dynamic) == {hex(x) for x in DYNAMIC_SITES}
    assert len({row['site'] for row in literals}) == 63
    assert {int(row['site'], 16) for row in literals} | DYNAMIC_SITES.keys() == getproc_sites
    for site, source in DYNAMIC_SITES.items():
        assert raw[pe.offset(pe.base+source, 3):][:3] == b'\x4c\x8b\xea'  # mov r13,rdx
    assert {'SymUnloadModule64', 'CreateToolhelp32Snapshot', 'SymInitialize',
            'WaitOnAddress', 'FlsAlloc', 'CorExitProcess'} <= {row['name'] for row in literals}
    assert not any(token in row['name'].lower() for row in literals
                   for token in ('socket', 'wsas', 'winhttp', 'internet', 'dnsquery',
                                 'connect', 'recv', 'sendto'))
    owners = Counter()
    starts = sorted(pe.function_ends)
    import bisect
    for site in getproc_sites:
        index = bisect.bisect_right(starts, pe.base+site) - 1
        assert index >= 0 and pe.base+site < pe.function_ends[starts[index]]
        owners[starts[index]-pe.base] += 1
    assert dict(owners) == EXPECTED_OWNER_COUNTS
    result = dict(passed=True, simulation_sha256=SHA,
                  direct_getproc_calls=65, literal_names=literals,
                  literal_call_count=len(literals), dynamic_sites=sorted(dynamic),
                  direct_literal_names_have_no_selected_network_api=True,
                  dynamic_names_indirect_calls_and_wire_unresolved=True,
                  full_d5_qualified=False)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps(dict(passed=True, literal_calls=result['literal_call_count'],
                          dynamic_calls=len(result['dynamic_sites']))))
