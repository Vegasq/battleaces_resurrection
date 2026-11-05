"""Review the reversible SDK JSON-reader null-return branch probe."""
from __future__ import annotations

import hashlib
import json
import struct

from tools.extract_descriptors import Metadata, PE
from tools.review_webview_fulltext396 import ORIGINAL, ORIGINAL_SHA, METADATA, METADATA_SHA
from tools.sdk_cache_installed_owner479 import owner

ROOT = owner.ROOT
OUT = ROOT / 'local/privacy481-directprobe01'
RVA, SITE, NULL_BRANCH = 0x837810, 0x837816, 0x83783a
BEFORE = bytes.fromhex('488bda33d2488bcbe88d02d10284c0')
AFTER = bytes.fromhex('e91f00000090')


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review():
    raw, meta = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(meta).hexdigest() == METADATA_SHA
    pe, md = PE(raw), Metadata(meta)
    assert pe.function_ends[pe.base + RVA] - pe.base == 0x837842
    offset = pe.offset(pe.base + SITE, len(BEFORE))
    assert offset == 0x835e16 and raw[offset:offset + len(BEFORE)] == BEFORE
    assert SITE + 5 + struct.unpack('<i', AFTER[1:5])[0] == NULL_BRANCH
    assert raw[pe.offset(pe.base + NULL_BRANCH, 8):][:8] == bytes.fromhex('33c04883c4305bc3')
    typ = [t for t in md.types if md.string(t[0]) == 'CacheManager' and
           md.string(t[1]) == 'BugsnagUnity']
    assert len(typ) == 1
    methods = [m for m in md.methods_for_type(typ[0]) if md.string(m[0]) == 'GetJsonFromCachePath']
    assert len(methods) == 1
    count, table = pe.module('BugsnagUnity.Windows.dll', 1224)
    slot = (methods[0][6] & 0xffffff) - 1
    assert 0 <= slot < count
    assert struct.unpack_from('<Q', raw, pe.offset(table + 8 * slot, 8))[0] - pe.base == RVA
    prior = read(ROOT / 'local/privacy121-cache-contract01/metadata.json')
    contract = [m for m in prior['methods'] if m['name'] == 'GetJsonFromCachePath']
    assert len(contract) == 1 and contract[0]['returns'] == 'string'
    assert contract[0]['rvas'] == [RVA]
    disasm = (ROOT / 'local/privacy481-json-disasm.txt').read_text(encoding='utf-8-sig')
    assert '000000018083781E: E8 8D 02 D1 02' in disasm
    assert '000000018083782E: E8 6D 08 D1 02' in disasm
    assert '000000018083783A: 33 C0' in disasm
    run, ready, status = (read(OUT / name) for name in
                          ('verification.json', 'ready.json', 'rea-status.json'))
    assert run['passed'] is True and run['exit_code'] == 0
    assert run['ready'] == ready and run['images'] == owner.EXPECTED
    assert run['images_unchanged'] is True
    assert all(sha(owner.GAME / name) == digest for name, digest in owner.EXPECTED.items())
    assert run['launch']['pid'] == ready['pid'] and run['launch']['tid'] == ready['tid']
    assert run['launch']['forced_cleanup'] is False and run['launch']['owned_process_reaped'] is True
    assert run['tracker']['complete'] is True
    assert run['tracker']['final_accounting'] == dict(total=1, active=0, terminated=0)
    trace = owner.GAME / '.battleaces-resurrection/profiles' / run['profile'] / 'quit-trace.jsonl'
    events = [json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()]
    assert [e['event'] for e in events] == ['armed', 'Show.dispatch', 'Show.return',
                                           'OnConfirm.dispatch', 'OnConfirm.return']
    assert all(e['pid'] == ready['pid'] and e['thread'] == ready['tid'] for e in events)
    assert status['provider']['id'] == 'frida' and status['confidence'] == 'observed'
    result = status['normalized_result']
    assert result['pid'] == ready['pid'] and result['state'] == 'detached'
    assert result['messages_truncated'] is False and len(result['scripts']) == 1
    messages = result['messages']
    assert len(messages) == 6 and all(m['type'] == 'send' and
        m['script_id'] == result['scripts'][0]['script_id'] for m in messages)
    rows = [m['payload'] for m in messages]
    assert all(r['schema'] == 1 and r['seq'] == i and r['pid'] == ready['pid'] and
               r['runId'] == ready['run_id'] for i, r in enumerate(rows, 1))
    assert [r['kind'] for r in rows] == ['observer-ready', 'module-hook-ready',
        'null-returned', 'original-bytes-restored', 'self-terminate-entry',
        'self-terminate-entry']
    module, null, restored = [r['data'] for r in rows[1:4]]
    assert module['assembly'] == ready['assembly'] and module['original'] == BEFORE[:6].hex()
    assert int(module['site'], 16) == int(module['base'], 16) + SITE
    assert int(null['method'], 16) == int(module['base'], 16) + RVA
    assert null['site'] == module['site'] and null['value'] == '0x0'
    assert null['existsCalls'] == null['readCalls'] == 0
    assert null['thread'] == ready['tid']
    assert restored == dict(restored=True, bytes=BEFORE[:6].hex())
    assert {r['data']['api'] for r in rows[4:]} == {'kernelbase.dll', 'kernel32.dll'}
    assert all(r['data']['exitCode'] == 0 and r['data']['attempted'] is True and
               r['data']['passed'] is True and r['data']['restored'] is True and
               r['data']['errors'] == [] for r in rows[4:])
    return dict(passed=True, helper_rva=hex(RVA), site=hex(SITE), null_path=hex(NULL_BRANCH),
                branch_bytes=AFTER.hex(), exists_calls=0, read_calls=0,
                original_bytes_restored=True, original_quit=True,
                job=run['tracker']['final_accounting'],
                disassembly_sha256=sha(ROOT / 'local/privacy481-json-disasm.txt'),
                observer_sha256=sha(OUT / 'observer.js'),
                run_sha256=sha(OUT / 'verification.json'),
                rea_status_sha256=sha(OUT / 'rea-status.json'),
                evidence_id=status['evidence_id'])


if __name__ == '__main__':
    result = review()
    (OUT / 'review481.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
