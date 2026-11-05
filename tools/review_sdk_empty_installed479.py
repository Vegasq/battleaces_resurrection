"""Bind recipe42 source, owned install, loaded branch, and normal Quit."""
from __future__ import annotations

import hashlib
import json

from client_patch.patcher.patch_client import build_patch
from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, RUNTIME_VALIDATED
from tools.review_sdk_empty_probe478 import ORIGINAL, ORIGINAL_SHA, PE, ROOT, SITE
from tools.sdk_cache_installed_owner479 import owner

GAME, OUT = owner.GAME, owner.OUT
EXPECTED = owner.EXPECTED
BRANCH = bytes.fromhex('e94500000090')


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review():
    assert RECIPE_VERSION == 42 and RUNTIME_VALIDATED is False
    assert read(ROOT / 'local/privacy478-emptyprobe01/review478.json')['passed'] is True
    pristine = ORIGINAL.read_bytes()
    assert hashlib.sha256(pristine).hexdigest() == ORIGINAL_SHA
    pe = PE(pristine)
    original_at = pe.offset(pe.base + SITE, len(BRANCH))
    source_patched = build_patch(pristine, community=True, cosmetics=True)
    assert source_patched[original_at:original_at + len(BRANCH)] == BRANCH
    assert hashlib.sha256(source_patched).hexdigest() == EXPECTED['GameAssembly.dll']
    dry, installed, manifest = (read(path) for path in
        (ROOT / 'local/privacy479-dryrun.json', ROOT / 'local/privacy479-install.json',
         GAME / '.battleaces-resurrection/patch-manifest.json'))
    assert dry == installed == manifest
    assert manifest['telemetry']['recipe_version'] == 42
    assert manifest['telemetry']['runtime_validated'] is False
    assert manifest['components']['GameAssembly.dll']['telemetry_guards'] == 104
    assert manifest['asset_loading']['bundle_count'] == 133
    assert manifest['community']['experimental'] is True
    assert manifest['cosmetics']['experimental'] is True
    for name, digest in EXPECTED.items():
        assert sha(GAME / name) == digest
    assert sha(GAME / '.battleaces-resurrection/original/GameAssembly.dll') == ORIGINAL_SHA
    for name, recipe in COMPONENTS.items():
        item = manifest['components'][name]
        assert item['original_sha256'] == recipe.original_sha256
        assert sha(GAME / name) == item['installed_sha256']
    assert (GAME / 'GameAssembly.dll').read_bytes()[original_at:original_at + len(BRANCH)] == BRANCH
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
    messages = result['messages']
    assert len(messages) == 5 and all(m['type'] == 'send' and
        m['script_id'] == result['scripts'][0]['script_id'] for m in messages)
    rows = [m['payload'] for m in messages]
    assert all(r['schema'] == 1 and r['seq'] == i and r['pid'] == ready['pid'] and
               r['runId'] == ready['run_id'] for i, r in enumerate(rows, 1))
    assert [r['kind'] for r in rows] == ['observer-ready', 'module-hook-ready',
        'empty-array-returned', 'self-terminate-entry', 'self-terminate-entry']
    module, empty = rows[1]['data'], rows[2]['data']
    assert module['assembly'] == ready['assembly'] and module['bytes'] == BRANCH.hex()
    assert int(module['site'], 16) == int(module['base'], 16) + SITE
    assert int(empty['method'], 16) == int(module['base'], 16) + 0x836830
    assert empty['site'] == module['site'] and empty['bytes'] == BRANCH.hex()
    assert empty['length'] == '0' and int(empty['array'], 16) != 0
    assert empty['thread'] == ready['tid']
    assert {r['data']['api'] for r in rows[3:]} == {'kernelbase.dll', 'kernel32.dll'}
    assert all(r['data']['exitCode'] == 0 and r['data']['attempted'] is True and
               r['data']['passed'] is True and r['data']['errors'] == [] for r in rows[3:])
    return dict(passed=True, recipe=42, installed_game_sha256=EXPECTED['GameAssembly.dll'],
                helper_sha256=EXPECTED['BattleAcesOffline.dll'], assets_checked=133,
                nonnull_zero_length_return=True, original_quit=True,
                job=run['tracker']['final_accounting'],
                run_sha256=sha(OUT / 'verification.json'),
                observer_sha256=sha(OUT / 'observer.js'),
                rea_status_sha256=sha(OUT / 'rea-status.json'),
                evidence_id=status['evidence_id'])


if __name__ == '__main__':
    result = review()
    (OUT / 'review479.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
