"""Verify the bounded private native listener-count watch and owner lifetime."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.ads_listener_watch472 import EXPECTED, GAME, ROOT
from tools.review_ads_watchpoint471 import review as review_control

FOLDER = ROOT/'local/privacy472-adswatch01'
OBSERVER_SHA = 'c9b78fbeef9709818c29328ef76fb1a2101cc36ead9b75e147c62bed1b52e8db'
REA_SHA = '5bdaf1ed6e1882f2af7a8fd2873ed46dd9f5bd212cb158cd90e7aa254704d713'


def review() -> dict:
    assert review_control()['passed'] is True
    read = lambda name: json.loads((FOLDER/name).read_bytes())
    owner, ready, rea = map(read, ('verification.json','ready.json','rea-status.json'))
    assert owner['passed'] is True and owner['exit_code'] == 0
    assert owner['ready'] == ready and owner['images'] == ready['images'] == EXPECTED
    assert owner['images_unchanged'] is True and owner['game'] == str(GAME)
    assert all(hashlib.sha256((GAME/name).read_bytes()).hexdigest() == digest
               for name,digest in EXPECTED.items())
    assert owner['launch']['pid'] == ready['pid'] and owner['launch']['tid'] == ready['tid']
    assert owner['launch']['forced_cleanup'] is False and owner['launch']['owned_process_reaped'] is True
    assert owner['tracker']['complete'] is True and owner['tracker']['final_accounting'] == \
           dict(total=1,active=0,terminated=0)
    assert (FOLDER/'game.log').is_file() and (FOLDER/'game.log').stat().st_size > 0
    assert hashlib.sha256((FOLDER/'observer.js').read_bytes()).hexdigest() == OBSERVER_SHA
    assert hashlib.sha256((FOLDER/'rea-status.json').read_bytes()).hexdigest() == REA_SHA
    assert rea['provider']['id'] == 'frida' and rea['confidence'] == 'observed'
    assert rea['operation'] == 'frida_session_status'
    result = rea['normalized_result']
    assert result['pid'] == ready['pid'] and result['state'] == 'detached'
    assert result['messages_truncated'] is False and len(result['scripts']) == 1
    messages = result['messages']
    assert len(messages) == 6
    assert all(row['type'] == 'send' and row['script_id'] == result['scripts'][0]['script_id']
               for row in messages)
    rows = [row['payload'] for row in messages]
    assert all(row['schema'] == 1 and row['seq'] == i and row['pid'] == ready['pid'] and
               row['runId'] == ready['run_id'] for i,row in enumerate(rows,1))
    assert [row['kind'] for row in rows] == ['observer-ready','script-ready',
        'constructor-watch-ready','destructor-entry','self-terminate-entry','self-terminate-entry']
    observer, _, constructor, destructor, *terms = [row['data'] for row in rows]
    assert observer['unity'] == ready['unity'] and observer['initial']['global'] is None
    assert observer['exitHooks'] == 2
    assert constructor['initialCount'] == '0' and ready['tid'] in constructor['watchedThreads']
    assert int(constructor['watchAddress'],16) - int(constructor['handler'],16) == 0x80
    assert destructor['state']['global'] == constructor['handler']
    assert destructor['state']['count'] == '0' and destructor['state']['selfLinked'] is True
    assert destructor['owner'] == hex(int(observer['moduleBase'],16)+0x1c0af00)
    assert destructor['hits'] == 0 and ready['tid'] in destructor['watchedThreads']
    assert {row['api'] for row in terms} == {'kernelbase.dll','kernel32.dll'}
    assert all(row['exitCode'] == 0 and row['hits'] == 0 and row['errors'] == [] and
               row['state']['global'] is None and row['watchedThreads'] == [] for row in terms)
    return dict(passed=True,scope='one private recipe39 menu/normal Quit,constructor-return to destructor-entry',
                pid=ready['pid'],watched_threads_at_destructor=len(destructor['watchedThreads']),
                native_listener_count_writes=0,rea_evidence_id=rea['evidence_id'],
                owner_sha256=hashlib.sha256((FOLDER/'verification.json').read_bytes()).hexdigest())


if __name__ == '__main__':
    print(review())
