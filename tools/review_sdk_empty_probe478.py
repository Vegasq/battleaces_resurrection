"""Review the reversible GetFilesBySuffix empty-array branch probe."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from tools.extract_descriptors import Metadata, PE
from tools.review_webview_fulltext396 import ORIGINAL, ORIGINAL_SHA, METADATA, METADATA_SHA
from tools.sdk_expiry_owner476 import EXPECTED, GAME, ROOT, sha

OUT = ROOT / 'local/privacy478-emptyprobe01'
RVA, SITE, EMPTY = 0x836830, 0x83683a, 0x836884
BEFORE = bytes.fromhex('498bd8488bfa803ddf236106007518')
AFTER = bytes.fromhex('e94500000090')


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def review() -> dict:
    raw, meta = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(meta).hexdigest() == METADATA_SHA
    pe, md = PE(raw), Metadata(meta)
    assert pe.function_ends[pe.base + RVA] - pe.base == 0x8368a5
    assert raw[pe.offset(pe.base + SITE, len(BEFORE)):][:len(BEFORE)] == BEFORE
    assert SITE + 5 + struct.unpack('<i', AFTER[1:5])[0] == EMPTY
    typ = [t for t in md.types if md.string(t[0]) == 'CacheManager' and
           md.string(t[1]) == 'BugsnagUnity']
    assert len(typ) == 1
    methods = [m for m in md.methods_for_type(typ[0]) if md.string(m[0]) == 'GetFilesBySuffix']
    assert len(methods) == 1
    count, table = pe.module('BugsnagUnity.Windows.dll', 1224)
    slot = (methods[0][6] & 0xffffff) - 1
    assert 0 <= slot < count
    assert struct.unpack_from('<Q', raw, pe.offset(table + 8 * slot, 8))[0] - pe.base == RVA
    prior = load(ROOT / 'local/privacy121-cache-contract01/metadata.json')
    contract = [m for m in prior['methods'] if m['name'] == 'GetFilesBySuffix']
    assert len(contract) == 1 and contract[0]['returns'] == 'kind29(0x186bbb8f8)'
    assert contract[0]['rvas'] == [RVA]
    owner, ready, status = (load(OUT / x) for x in
                            ('verification.json', 'ready.json', 'rea-status.json'))
    assert owner['passed'] is True and owner['exit_code'] == 0
    assert owner['ready'] == ready and owner['images'] == EXPECTED
    assert owner['images_unchanged'] is True
    assert all(sha(GAME / name) == digest for name, digest in EXPECTED.items())
    assert owner['launch']['pid'] == ready['pid'] and owner['launch']['tid'] == ready['tid']
    assert owner['launch']['forced_cleanup'] is False and owner['launch']['owned_process_reaped'] is True
    assert owner['tracker']['complete'] is True
    assert owner['tracker']['final_accounting'] == dict(total=1, active=0, terminated=0)
    trace = GAME / '.battleaces-resurrection/profiles' / owner['profile'] / 'quit-trace.jsonl'
    events = [json.loads(x) for x in trace.read_text(encoding='utf-8').splitlines()]
    assert [x['event'] for x in events] == ['armed', 'Show.dispatch', 'Show.return',
                                            'OnConfirm.dispatch', 'OnConfirm.return']
    assert all(x['pid'] == ready['pid'] and x['thread'] == ready['tid'] for x in events)
    assert status['provider']['id'] == 'frida' and status['confidence'] == 'observed'
    result = status['normalized_result']
    assert result['pid'] == ready['pid'] and result['state'] == 'detached'
    assert result['messages_truncated'] is False and len(result['scripts']) == 1
    messages = result['messages']
    assert len(messages) == 6 and all(x['type'] == 'send' and
        x['script_id'] == result['scripts'][0]['script_id'] for x in messages)
    rows = [x['payload'] for x in messages]
    assert all(x['schema'] == 1 and x['seq'] == i and x['pid'] == ready['pid'] and
        x['runId'] == ready['run_id'] for i, x in enumerate(rows, 1))
    assert [x['kind'] for x in rows] == ['observer-ready', 'module-hook-ready',
        'empty-array-returned', 'original-bytes-restored',
        'self-terminate-entry', 'self-terminate-entry']
    module, empty, restored = [x['data'] for x in rows[1:4]]
    assert module['assembly'] == ready['assembly'] and module['original'] == BEFORE[:6].hex()
    assert int(module['site'], 16) == int(module['base'], 16) + SITE
    assert int(empty['method'], 16) == int(module['base'], 16) + RVA
    assert empty['site'] == module['site'] and empty['length'] == '0'
    assert int(empty['array'], 16) != 0 and empty['thread'] == ready['tid']
    assert restored == dict(restored=True, bytes=BEFORE[:6].hex())
    assert {x['data']['api'] for x in rows[4:]} == {'kernelbase.dll', 'kernel32.dll'}
    assert all(x['data']['exitCode'] == 0 and x['data']['attempted'] is True and
        x['data']['passed'] is True and x['data']['restored'] is True and
        x['data']['errors'] == [] for x in rows[4:])
    return dict(passed=True, original_sha256=ORIGINAL_SHA, helper_rva=hex(RVA),
                branch_site=hex(SITE), empty_path=hex(EMPTY), branch_bytes=AFTER.hex(),
                nonnull_zero_length_return=True, original_bytes_restored=True,
                original_quit=True, job=owner['tracker']['final_accounting'],
                owner_sha256=sha(OUT / 'verification.json'),
                observer_sha256=sha(OUT / 'observer.js'),
                rea_status_sha256=sha(OUT / 'rea-status.json'), evidence_id=status['evidence_id'])


if __name__ == '__main__':
    result = review()
    (OUT / 'review478.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
