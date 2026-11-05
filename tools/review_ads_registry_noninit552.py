"""Bind all direct registry-head refs and classify the nine non-static owners."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess

from tools.extract_descriptors import PE
from tools.review_ads_manager_cell400 import LLVM
from tools.review_d5_connected_pair338 import ROOT

ORIGINAL = ROOT / 'local/privacy543-game01/.battleaces-resurrection/original/UnityPlayer.dll'
INSTALLED = ROOT / 'local/privacy543-game01/UnityPlayer.dll'
GHIDRA = ROOT / 'local/d5-ghidra-12.1.4/pdb-registry-refs532-console.log'
DECOMPILE = ROOT / 'local/d5-ghidra-12.1.4/pdb-registry-noninit552-console.log'
SCRIPT = ROOT / 'local/d5-ghidra-12.1.4/scripts/TraceRegistryNonInit552.java'
OUT = ROOT / 'local/privacy552-registry-noninit01'
ORIGINAL_SHA = 'ac144d56d53f07904d52ed27a1539de90bc3290038fe52d73d2f6b268c85d6bc'
INSTALLED_SHA = '935c78e7a1b7fae3f0bc6892e390d521e5d24cf40539112559d64312df6107e4'
LLVM_SHA = '5e7a457bf23033b6ec4a959d2276f09d44c024092529684d7eeb687d38da700d'
OTHER = {
    0x36db4c: 'ThreadSpecificValue<int>::ThreadSpecificValue<int>',
    0x36db6d: 'ThreadSpecificValue<int>::ThreadSpecificValue<int>',
    0x67ead5: 'RegisterRuntimeInitializeAndCleanup::ExecuteInitializations',
    0x6a5d8e: 'FileSystem::FileSystem',
    0x6a5dc7: 'FileSystem::FileSystem',
    0x5c585d: 'RuntimeCleanup',
    0x9e1476: 'LocalFileSystemWindowsShared::~LocalFileSystemWindowsShared',
    0xc094e8: 'GlobalContext',
    0xc09489: 'GlobalContext',
}
COMMENT = re.compile(rb'^([0-9a-f]+): ((?:[0-9a-f]{2} )+)\s+.+# 0x181d0cd60\b')
XREF = re.compile(r'XREF (18[0-9a-f]{7}) (READ|WRITE|DATA) (18[0-9a-f]{7}) (.+?) \(GhidraScript\)')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review():
    assert sha(ORIGINAL) == ORIGINAL_SHA and sha(INSTALLED) == INSTALLED_SHA
    assert sha(LLVM) == LLVM_SHA
    old, current = ORIGINAL.read_bytes(), INSTALLED.read_bytes()
    pe, ip = PE(old), PE(current)
    log = GHIDRA.read_text(encoding='utf-16')
    block = log.split('TARGET 1d0cd60', 1)[1].split('COUNT 1d0cd60', 1)[0]
    refs = {}
    for line in block.splitlines():
        match = XREF.search(line)
        if match:
            site = int(match[1], 16) - pe.base
            assert site not in refs
            refs[site] = dict(kind=match[2], owner=match[4])
    assert len(refs) == 2878
    assert sum('dynamic_initializer' in row['owner'] for row in refs.values()) == 1908
    assert sum('dynamic_atexit' in row['owner'] for row in refs.values()) == 961
    other = {site: row for site, row in refs.items()
             if not any(word in row['owner'] for word in ('dynamic_initializer', 'dynamic_atexit'))}
    assert set(other) == set(OTHER)
    assert all(OTHER[site] in row['owner'] for site, row in other.items())
    process = subprocess.Popen([str(LLVM), '-d', '--section=.text',
                                '--x86-asm-syntax=intel', str(ORIGINAL)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None and process.stderr is not None
    decoded = set()
    for line in process.stdout:
        match = COMMENT.match(line)
        if not match:
            continue
        address = int(match[1], 16)
        site = address - pe.base
        code = bytes.fromhex(match[2].decode())
        assert site in refs and site not in decoded
        assert old[pe.offset(address, len(code)):pe.offset(address, len(code)) + len(code)] == code
        assert current[ip.offset(address, len(code)):ip.offset(address, len(code)) + len(code)] == code
        decoded.add(site)
    error = process.stderr.read()
    assert process.wait() == 0 and not error, error[:200]
    assert decoded == set(refs)
    decompiled = DECOMPILE.read_text(encoding='utf-16')
    expected_owners = (0x36daf0, 0x67eac0, 0x6a5c30, 0x5c5830, 0x9e1440, 0xc09430)
    assert all(f'TraceRegistryNonInit552.java> OWNER {rva:x} ' in decompiled
               for rva in expected_owners)
    assert 'TraceRegistryNonInit552.java> ERROR ' not in decompiled
    assert 'TraceRegistryNonInit552.java> BODY_LENGTH ' in decompiled
    assert decompiled.count('TraceRegistryNonInit552.java> REF_INS ') == 9
    assert 'RegisterRuntimeInitializeAndCleanup::s_LastRegistered' in decompiled
    assert 'RuntimeStaticBase::InitializeImpl' in decompiled
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  installed_sha256=INSTALLED_SHA, raw_and_ghidra_sites=len(refs),
                  static_initializer_sites=1908, static_atexit_sites=961,
                  non_static_sites={hex(site): row for site, row in sorted(other.items())},
                  only_two_generic_invocation_walkers_identified=True,
                  computed_aliases_and_ads_provider_resolved=False,
                  ghidra_log_sha256=sha(GHIDRA), decompile_log_sha256=sha(DECOMPILE),
                  script_sha256=sha(SCRIPT), llvm_sha256=LLVM_SHA)
    OUT.mkdir(exist_ok=True)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n',
                                           encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps(dict(passed=result['passed'], sites=result['raw_and_ghidra_sites'],
                          non_static_sites=len(result['non_static_sites'])), sort_keys=True))
