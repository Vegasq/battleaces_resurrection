"""Bind recipe44 source, isolated install, loaded getter and original Quit."""
from __future__ import annotations

import hashlib
import json

from client_patch.patcher.patch_client import build_patch
from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, RUNTIME_VALIDATED
from tools.review_reporter_delegate_targets300 import ORIGINAL, OLD_SHA
from tools.extract_descriptors import PE
from tools.sdk_cached_id_owner487 import owner

ROOT = owner.ROOT
GAME = owner.GAME
OUT = ROOT / 'local/privacy488-cached-id-runtime01'
EXPECTED = owner.EXPECTED
ENTRY = bytes.fromhex('31c0c3')


def read(path):
    raw = path.read_bytes()
    return json.loads(raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review():
    assert RECIPE_VERSION == 44 and RUNTIME_VALIDATED is False
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == OLD_SHA
    offset = PE(original).offset(PE(original).base+0x8368b0)
    patched = build_patch(original, community=True, cosmetics=True)
    assert patched[offset:offset+3] == ENTRY
    assert hashlib.sha256(patched).hexdigest() == EXPECTED['GameAssembly.dll']
    dry, installed, manifest = (read(path) for path in (
        ROOT / 'local/privacy487-dryrun.txt', ROOT / 'local/privacy487-install.txt',
        GAME / '.battleaces-resurrection/patch-manifest.json'))
    assert dry == installed == manifest
    assert manifest['telemetry']['recipe_version'] == 44
    assert manifest['telemetry']['runtime_validated'] is False
    assert manifest['components']['GameAssembly.dll']['telemetry_guards'] == 106
    assert manifest['asset_loading']['bundle_count'] == 133
    assert manifest['community']['experimental'] is True
    assert manifest['cosmetics']['experimental'] is True
    for name, digest in EXPECTED.items():
        assert sha(GAME / name) == digest
    assert sha(GAME / '.battleaces-resurrection/original/GameAssembly.dll') == OLD_SHA
    assert (GAME / 'GameAssembly.dll').read_bytes()[offset:offset+3] == ENTRY

    run, ready, status = (read(OUT / name) for name in
                          ('verification.json', 'ready.json', 'rea-status.json'))
    assert run['passed'] is True and run['exit_code'] == 0
    assert run['ready'] == ready and run['images'] == EXPECTED
    assert run['images_unchanged'] is True
    assert run['launch']['pid'] == ready['pid'] and run['launch']['tid'] == ready['tid']
    assert run['launch']['forced_cleanup'] is False and run['launch']['owned_process_reaped'] is True
    assert run['tracker']['complete'] is True
    assert run['tracker']['final_accounting'] == dict(total=1, active=0, terminated=0)
    trace = GAME / '.battleaces-resurrection/profiles' / run['profile'] / 'quit-trace.jsonl'
    events = [json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()]
    assert [e['event'] for e in events] == ['armed', 'Show.dispatch', 'Show.return',
                                           'OnConfirm.dispatch', 'OnConfirm.return']
    assert all(e['pid'] == ready['pid'] and e['thread'] == ready['tid'] for e in events)

    assert status['provider']['id'] == 'frida' and status['confidence'] == 'observed'
    result = status['normalized_result']
    assert result['pid'] == ready['pid'] and result['state'] == 'detached'
    assert result['messages_truncated'] is False and len(result['scripts']) == 1
    rows = [m['payload'] for m in result['messages']]
    assert len(rows) == 5 and all(m['type'] == 'send' and
        m['script_id'] == result['scripts'][0]['script_id'] for m in result['messages'])
    assert all(r['schema'] == 1 and r['seq'] == i and r['pid'] == ready['pid'] and
               r['runId'] == ready['run_id'] for i, r in enumerate(rows, 1))
    assert [r['kind'] for r in rows] == ['observer-ready', 'module-hook-ready',
        'null-returned', 'self-terminate-entry', 'self-terminate-entry']
    module, returned = rows[1]['data'], rows[2]['data']
    assert module['assembly'] == ready['assembly'] and module['bytes'] == ENTRY.hex()
    assert int(module['method'], 16) == int(module['base'], 16) + 0x8368b0
    assert returned['method'] == module['method'] and returned['bytes'] == ENTRY.hex()
    assert returned['value'] == '0x0' and returned['thread'] == ready['tid']
    assert returned['existsCalls'] == returned['readCalls'] == returned['writeCalls'] == 0
    assert {r['data']['api'] for r in rows[3:]} == {'kernelbase.dll', 'kernel32.dll'}
    assert all(r['data']['exitCode'] == 0 and r['data']['attempted'] is True and
               r['data']['passed'] is True and r['data']['errors'] == [] for r in rows[3:])
    return dict(passed=True, recipe=44, installed_game_sha256=EXPECTED['GameAssembly.dll'],
                helper_sha256=EXPECTED['BattleAcesOffline.dll'], assets_checked=133,
                null_return_without_file_calls=True, original_quit=True,
                job=run['tracker']['final_accounting'],
                run_sha256=sha(OUT / 'verification.json'),
                observer_sha256=sha(OUT / 'observer.js'),
                rea_status_sha256=sha(OUT / 'rea-status.json'),
                evidence_id=status['evidence_id'])


if __name__ == '__main__':
    result = review()
    (OUT / 'review488.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
