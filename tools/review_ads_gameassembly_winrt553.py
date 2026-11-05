"""Bound the direct WinRT resolver path in the installed GameAssembly.

This is a direct .text reference census, not a computed alias or D5 closure.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess

from tools.extract_descriptors import PE
from tools.review_ads_manager_cell400 import LLVM
from tools.review_d5_connected_pair338 import ROOT

ORIGINAL = ROOT / 'local/privacy543-game01/.battleaces-resurrection/original/GameAssembly.dll'
INSTALLED = ROOT / 'local/privacy543-game01/GameAssembly.dll'
INSTALL_RECEIPT = ROOT / 'local/privacy543-client-install01/verification.json'
OUT = ROOT / 'local/privacy553-gameassembly-winrt01'
READOBJ = LLVM.with_name('llvm-readobj.exe')
BASE = 0x180000000
RO_NAME = BASE + 0x641cce0
CREATE_NAME = BASE + 0x641cd48
RO_CACHE = BASE + 0x6e46720
CLASS = BASE + 0x6446538
INSTRUCTION = re.compile(rb'^([0-9a-f]+): ((?:[0-9a-f]{2} )+)\s+(.+)$')
COMMENT = re.compile(rb'# 0x([0-9a-f]+)\b')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selected_bytes(pe, data, address, size):
    offset = pe.offset(address, size)
    return data[offset:offset + size]


def review():
    install = json.loads(INSTALL_RECEIPT.read_text(encoding='utf-8'))
    assert install['passed'] and install['recipe'] == 47
    original_hash = sha(ORIGINAL)
    installed_hash = sha(INSTALLED)
    assert original_hash == install['original_component_hashes']['GameAssembly.dll']
    assert installed_hash == install['installed_gameassembly_sha256']
    old, current = ORIGINAL.read_bytes(), INSTALLED.read_bytes()
    pe, ip = PE(old), PE(current)
    assert pe.base == ip.base == BASE
    for start, end in ((0x5d7340, 0x5d73cb), (0x62e780, 0x62e8bc)):
        assert pe.function_ends[BASE + start] == BASE + end
        assert selected_bytes(pe, old, BASE + start, end - start) == selected_bytes(
            ip, current, BASE + start, end - start)

    strings = ((RO_NAME, b'RoGetActivationFactory\0'),
               (CREATE_NAME, b'WindowsCreateStringReference\0'),
               (BASE + 0x641cd00, 'api-ms-win-core-winrt-l1-1-0.dll\0'.encode('utf-16le')),
               (BASE + 0x641cd70, 'api-ms-win-core-winrt-string-l1-1-0.dll\0'.encode('utf-16le')),
               (CLASS, 'Windows.System.DispatcherQueue\0'.encode('utf-16le')))
    for address, value in strings:
        assert selected_bytes(pe, old, address, len(value)) == value
        assert selected_bytes(ip, current, address, len(value)) == value

    imports = subprocess.run([str(READOBJ), '--coff-imports', str(ORIGINAL)],
                             capture_output=True, text=True, check=True).stdout
    kernel = imports.split('Name: KERNEL32.dll', 1)[1].split('}', 1)[0]
    assert 'ImportAddressTableRVA: 0x555D048' in kernel
    symbols = re.findall(r'\bSymbol: (\w+) \(\d+\)', kernel)
    assert symbols[12] == 'GetProcAddress' and symbols[14] == 'GetModuleHandleW'
    assert 'Symbol: RoGetActivationFactory' not in imports
    assert 'Symbol: WindowsCreateStringReference' not in imports

    expected = {
        'ro_name': {0x5d7385}, 'create_name': {0x62e7c5},
        'ro_cache': {0x5d734a, 0x5d736e, 0x5d7395},
        'ro_call': {0x62e81d}, 'class_literal': {0x62e7f0},
        'class_length': {0x62e7eb},
    }
    found = {key: set() for key in expected}
    process = subprocess.Popen([str(LLVM), '-d', '--section=.text',
                                '--x86-asm-syntax=intel', str(ORIGINAL)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None and process.stderr is not None
    for line in process.stdout:
        match = INSTRUCTION.match(line)
        if not match:
            continue
        address = int(match[1], 16)
        site = address - BASE
        code = bytes.fromhex(match[2].decode())
        assembly = match[3]
        comments = {int(value, 16) for value in COMMENT.findall(assembly)}
        categories = set()
        if RO_NAME in comments:
            categories.add('ro_name')
        if CREATE_NAME in comments:
            categories.add('create_name')
        if RO_CACHE in comments:
            categories.add('ro_cache')
        if CLASS in comments:
            categories.add('class_literal')
        if b'call\t0x1805d7340' in assembly:
            categories.add('ro_call')
        if site == 0x62e7eb and b'mov\tedx, 0x1e' in assembly:
            categories.add('class_length')
        for category in categories:
            assert site not in found[category]
            assert selected_bytes(pe, old, address, len(code)) == code
            assert selected_bytes(ip, current, address, len(code)) == code
            found[category].add(site)
    error = process.stderr.read()
    assert process.wait() == 0 and not error, error[:200]
    assert found == expected, {key: (sorted(found[key]), sorted(expected[key]))
                               for key in expected if found[key] != expected[key]}

    result = dict(passed=True, recipe=47, original_sha256=original_hash,
                  installed_sha256=installed_hash, llvm_sha256=sha(LLVM),
                  llvm_readobj_sha256=sha(READOBJ),
                  direct_sites={key: [hex(site) for site in sorted(value)]
                                for key, value in found.items()},
                  resolved_class='Windows.System.DispatcherQueue',
                  only_direct_text_references_checked=True,
                  advertising_provider_resolved=False, full_d5_qualified=False)
    OUT.mkdir(exist_ok=True)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n',
                                           encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps(dict(passed=result['passed'], direct_sites=result['direct_sites'],
                          full_d5_qualified=result['full_d5_qualified']), sort_keys=True))
