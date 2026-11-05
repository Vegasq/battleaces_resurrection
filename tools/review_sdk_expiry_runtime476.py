"""Review recipe41 installed expiry cut, owned probe and original Quit."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.review_sdk_expiry_guard476 import review as review_source
from tools.sdk_expiry_owner476 import EXPECTED, GAME, OUT, ROOT, sha


def load(path: Path, encoding: str = 'utf-8') -> dict:
    return json.loads(path.read_text(encoding=encoding))


def review() -> dict:
    source = review_source()
    assert source['passed'] is True
    dryrun = load(ROOT / 'local/privacy476-dryrun.json', 'utf-16')
    installed = load(ROOT / 'local/privacy476-install.json', 'utf-16')
    manifest = load(GAME / '.battleaces-resurrection/patch-manifest.json')
    for row in (dryrun, installed, manifest):
        assert row['telemetry']['recipe_version'] == 41
        assert row['telemetry']['runtime_validated'] is False
        assert row['components']['GameAssembly.dll']['telemetry_guards'] == 103
        assert row['components']['GameAssembly.dll']['installed_sha256'] == EXPECTED['GameAssembly.dll']
    assert all(sha(GAME / name) == digest for name, digest in EXPECTED.items())
    assert sha(GAME / 'GameAssembly.dll') == installed['components']['GameAssembly.dll']['installed_sha256']
    owner, ready, status = (load(OUT / name) for name in
                            ('verification.json', 'ready.json', 'rea-status.json'))
    assert owner['passed'] is True and owner['exit_code'] == 0
    assert owner['images_unchanged'] is True and owner['images'] == EXPECTED
    assert owner['ready'] == ready and owner['game'] == str(GAME)
    assert owner['launch']['pid'] == ready['pid'] and owner['launch']['tid'] == ready['tid']
    assert owner['launch']['forced_cleanup'] is False and owner['launch']['owned_process_reaped'] is True
    assert owner['tracker']['complete'] is True
    assert owner['tracker']['final_accounting'] == dict(total=1, active=0, terminated=0)
    trace = GAME / '.battleaces-resurrection/profiles' / owner['profile'] / 'quit-trace.jsonl'
    events = [json.loads(x) for x in trace.read_text(encoding='utf-8').splitlines()]
    assert [x['event'] for x in events] == ['armed', 'Show.dispatch', 'Show.return',
                                            'OnConfirm.dispatch', 'OnConfirm.return']
    assert all(x['pid'] == ready['pid'] and x['thread'] == ready['tid'] for x in events)
    assert [x['tick'] for x in events] == sorted(x['tick'] for x in events)
    assert (OUT / 'game.log').stat().st_size > 0
    assert status['provider']['id'] == 'frida' and status['confidence'] == 'observed'
    result = status['normalized_result']
    assert result['pid'] == ready['pid'] and result['state'] == 'detached'
    assert result['messages_truncated'] is False and len(result['scripts']) == 1
    messages = result['messages']
    assert len(messages) == 4
    assert all(x['type'] == 'send' and x['script_id'] == result['scripts'][0]['script_id']
               for x in messages)
    rows = [x['payload'] for x in messages]
    assert all(x['schema'] == 1 and x['seq'] == i and x['pid'] == ready['pid'] and
               x['runId'] == ready['run_id'] for i, x in enumerate(rows, 1))
    assert [x['kind'] for x in rows] == ['observer-ready', 'expiry-null-receiver-returned',
                                       'self-terminate-entry', 'self-terminate-entry']
    assert rows[0]['data'] == dict(game=ready['game'], assembly=ready['assembly'], exitHooks=2)
    call = rows[1]['data']
    assert call['assembly'] == ready['assembly'] and call['thread'] == ready['tid']
    assert int(call['entry'], 16) == int(call['base'], 16) + 0x836b50
    assert call['bytes'] == 'c3895c2408488974241048897c241841'
    assert {x['data']['api'] for x in rows[2:]} == {'kernelbase.dll', 'kernel32.dll'}
    assert all(x['data']['exitCode'] == 0 and x['data']['called'] is True and
               x['data']['errors'] == [] for x in rows[2:])
    return dict(passed=True, recipe=41, installed_gameassembly_sha256=EXPECTED['GameAssembly.dll'],
                loaded_null_receiver_call_returned=True, original_quit_confirm=True,
                exit_code=0, job=owner['tracker']['final_accounting'],
                source_review=source, observer_sha256=sha(OUT / 'observer.js'),
                owner_sha256=sha(OUT / 'verification.json'),
                rea_status_sha256=sha(OUT / 'rea-status.json'), evidence_id=status['evidence_id'])


if __name__ == '__main__':
    result = review()
    (OUT / 'review476.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
