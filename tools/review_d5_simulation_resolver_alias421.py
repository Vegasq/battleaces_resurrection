"""Bound static alias check for two Simulation.dll API-set resolvers."""
from __future__ import annotations

import hashlib
import json
import re
import struct
import subprocess

from tools.extract_descriptors import PE
from tools.review_ads_settings_pair413 import LLVM
from tools.review_d5_connected_pair338 import ROOT
from tools.review_d5_simulation_imports417 import DLL, SHA
from tools.review_d5_simulation_resolver_callers420 import RESOLVERS, review as review_callers

OUT = ROOT / 'local/privacy421-simulation-resolver-alias01'
COMMENT = re.compile(r'^([0-9a-f]+): ((?:[0-9a-f]{2} )+)\s+(.+)# 0x([0-9a-f]+)\s*$')


def review() -> dict:
    assert review_callers()['passed']
    raw = DLL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SHA
    pe = PE(raw)
    pointer_hits = {}
    for rva in RESOLVERS:
        value = struct.pack('<Q', pe.base + rva)
        positions = []
        cursor = raw.find(value)
        while cursor >= 0:
            positions.append(hex(cursor))
            cursor = raw.find(value, cursor + 1)
        pointer_hits[hex(rva)] = positions

    process = subprocess.Popen(
        [str(LLVM), '-d', '--section=.text', '--x86-asm-syntax=intel', str(DLL)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert process.stdout is not None and process.stderr is not None
    rip_hits = {}
    for line in process.stdout:
        match = COMMENT.match(line)
        if match is None:
            continue
        target = int(match[4], 16) - pe.base
        if target not in RESOLVERS:
            continue
        site = int(match[1], 16) - pe.base
        code = bytes.fromhex(match[2])
        instruction = match[3].strip()
        assert raw[pe.offset(pe.base + site, len(code)):][:len(code)] == code
        rip_hits[hex(site)] = dict(target=hex(target), instruction=instruction,
                                  bytes=code.hex())
    assert process.wait() == 0 and process.stderr.read() == ''

    result = dict(passed=True, simulation_sha256=SHA,
                  preferred_base_pointer_hits=pointer_hits,
                  disassembled_text_comment_refs=rip_hits,
                  direct_callers_bound_by_420=33,
                  computed_or_rebased_indirect_calls_unresolved=True,
                  full_d5_qualified=False)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n',
                                          encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps(dict(passed=True,
                          pointer_hits=result['preferred_base_pointer_hits'],
                          rip_refs=result['disassembled_text_comment_refs'])))
