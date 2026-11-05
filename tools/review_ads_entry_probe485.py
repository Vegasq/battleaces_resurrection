"""Review the reversible native advertising callback entry-return probe."""
from __future__ import annotations

import hashlib
import json
import struct

from tools.extract_descriptors import PE
from tools.review_ads_callback_slots403 import ORIGINAL, ORIGINAL_SHA
from tools.ads_callback_owner485 import installed

owner = installed.owner
ROOT, OUT = owner.ROOT, owner.OUT
RVA = 0xc307c0
BEFORE = bytes.fromhex('48895c2408574883ec20418079200141')


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review():
    raw = ORIGINAL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    pe = PE(raw)
    assert pe.function_ends[pe.base + RVA] - pe.base == 0xc30871
    offset = pe.offset(pe.base + RVA, len(BEFORE))
    assert offset == 0xc2fbc0 and raw[offset:offset + len(BEFORE)] == BEFORE
    for slot in (0x1a2afb8, 0x1a2c630):
        assert struct.unpack_from('<Q', raw, pe.offset(pe.base + slot, 8))[0] - pe.base == RVA
    decompile = (ROOT / 'local/d5-ghidra-12.1.4/pdb-handler-console.log').read_text(encoding='utf-16')
    assert 'FUNCTION c307c0 AnalyticsCoreStats::OnAdsIdRequestDone' in decompile
    assert 'public: virtual void __cdecl AnalyticsCoreStats::OnAdsIdRequestDone' in decompile
    assert 'HandleRequestToSendAdsId(this + -0x1498)' in decompile
    assert sha(owner.GAME / 'UnityPlayer.dll') == owner.EXPECTED['UnityPlayer.dll']
    assert (owner.GAME / 'UnityPlayer.dll').read_bytes()[offset:offset + len(BEFORE)] == BEFORE
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
    assert len(messages) == 7 and all(m['type'] == 'send' and
        m['script_id'] == result['scripts'][0]['script_id'] for m in messages)
    rows = [m['payload'] for m in messages]
    assert all(r['schema'] == 1 and r['seq'] == i and r['pid'] == ready['pid'] and
               r['runId'] == ready['run_id'] for i, r in enumerate(rows, 1))
    assert [r['kind'] for r in rows] == ['unity-ready', 'observer-ready',
        'module-hook-ready', 'callback-returned', 'original-byte-restored',
        'self-terminate-entry', 'self-terminate-entry']
    unity, callback, restored = rows[0]['data'], rows[3]['data'], rows[4]['data']
    assert unity['path'] == str(owner.GAME / 'UnityPlayer.dll')
    assert int(unity['site'], 16) == int(unity['base'], 16) + RVA
    assert unity['original'] == '48'
    assert callback['site'] == unity['site'] and callback['temporaryByte'] == 'c3'
    assert callback['thread'] == ready['tid']
    assert restored == dict(restored=True, byte='48')
    assert {r['data']['api'] for r in rows[5:]} == {'kernelbase.dll', 'kernel32.dll'}
    assert all(r['data']['exitCode'] == 0 and r['data']['attempted'] is True and
               r['data']['passed'] is True and r['data']['restored'] is True and
               r['data']['errors'] == [] for r in rows[5:])
    return dict(passed=True, callback_rva=hex(RVA), original_sha256=ORIGINAL_SHA,
                reversible_entry_return=True, original_bytes_restored=True,
                original_quit=True, job=run['tracker']['final_accounting'],
                observer_sha256=sha(OUT / 'observer.js'),
                run_sha256=sha(OUT / 'verification.json'),
                rea_status_sha256=sha(OUT / 'rea-status.json'),
                evidence_id=status['evidence_id'])


if __name__ == '__main__':
    result = review()
    (OUT / 'review485.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
