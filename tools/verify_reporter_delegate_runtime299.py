"""Reconcile one owned menu-time reporter delegate-slot observation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/privacy299-reporter-delegates01'
GAME = ROOT / 'local/privacy291-runtime01/game'
EXPECTED = (('6b42af0', '0x60003437'), ('6b42b08', '0x60003439'),
            ('6b42ad0', '0x60003419'), ('6b42ad8', '0x6000341d'),
            ('6b42ac8', '0x60003429'), ('6b42ae8', '0x60003417'))
ASSEMBLY_SHA = 'c6e4480475e515e71a46e9579ee48d4db1a7f22062db5282d73c314a204d6b4e'


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def review():
    report = json.loads((OUT / 'verification.json').read_text(encoding='utf-8'))
    status = json.loads((OUT / 'frida-status.json').read_text(encoding='utf-8'))
    pid = report['pid']
    require(report['passed'] is True and report['exit_code'] == 0 and
            report['launch']['forced_cleanup'] is False and
            report['launch']['owned_process_reaped'] is True and
            report['launch']['primary_thread_resumed'] is True,
            'normal owned process lifetime differs')
    require(report['job']['complete'] is True and not report['job']['errors'] and
            report['job']['final_accounting']['active'] == 0 and
            report['job']['final_accounting']['terminated'] == 0,
            'owned job did not drain naturally')
    require(report['game'] == str(GAME) and
            hashlib.sha256((GAME / 'GameAssembly.dll').read_bytes()).hexdigest() == ASSEMBLY_SHA,
            'installed GameAssembly differs')
    normalized = status['normalized_result']
    require(status['provider']['id'] == 'frida' and
            normalized['state'] == 'detached' and normalized['mode'] == 'attach' and
            normalized['device_id'] == 'local' and normalized['pid'] == pid and
            normalized['messages_truncated'] is False,
            'Frida session boundary differs')
    messages = normalized['messages']
    require(len(messages) == 2 and all(item['type'] == 'send' for item in messages),
            'unexpected Frida messages')
    observed = messages[1]['payload']
    require(observed['kind'] == 'direct' and
            observed['module'].lower() == str(GAME / 'GameAssembly.dll').lower() and
            [(row['rva'], row['value']) for row in observed['slots']] == list(EXPECTED),
            'six method slots differ from original encoded values')
    trace = GAME / '.battleaces-resurrection/profiles' / report['profile'] / 'quit-trace.jsonl'
    rows = [json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines() if line]
    require([row['event'] for row in rows] ==
            ['armed', 'Show.dispatch', 'Show.return', 'OnConfirm.dispatch', 'OnConfirm.return'] and
            all(row['pid'] == pid for row in rows), 'original Quit trace differs')
    return dict(passed=True, scope='One owned recipe25 menu-time sample of six method slots; no callback invocation or queue census',
                pid=pid, gameassembly_sha256=ASSEMBLY_SHA,
                report_sha256=hashlib.sha256((OUT / 'verification.json').read_bytes()).hexdigest(),
                frida_status_sha256=hashlib.sha256((OUT / 'frida-status.json').read_bytes()).hexdigest(),
                frida_evidence_id=status['evidence_id'],
                slots_original_encoded=6, slots_resolved=0,
                original_quit=True, forced_cleanup=False,
                producer_or_other_registration_excluded=False, p7_complete=False)


if __name__ == '__main__':
    result = review()
    path = OUT / 'review.json'
    with path.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print('PASS', path)
