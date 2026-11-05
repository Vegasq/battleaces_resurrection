"""Review the owned preexisting-root control and current native client path watch."""
from __future__ import annotations

import json
from pathlib import Path

from tools.frida_resolved_file_source371 import build_source
from tools.review_d5_connected_pair338 import ROOT, sha
from tools.review_d5_exit_network368 import read, records_for, payloads
from tools.review_d5_socket_exit370 import verify as game_verify

CONTROL = ROOT / 'local/privacy371-root-control02'
CASE = ROOT / 'local/privacy371-connected01'
TRACE = ROOT / 'local/privacy371-prelaunch-root-trace01'


def verify() -> dict:
    request, session, receipt = (read(CONTROL / 'request.json'),
                                 read(CONTROL / 'session.json'),
                                 read(CONTROL / 'positive.json'))
    bundle = read(CONTROL / 'rea-evidence.json')
    assert request['source_sha256'] == sha(CONTROL / 'observer.js')
    assert (CONTROL / 'observer.js').read_text(encoding='utf-8') == build_source(request['config'])
    assert receipt['pid'] == session['pid'] == read(CONTROL / 'pid.json')['pid']
    assert receipt['relative_open_status'] == 0 and receipt['queue_file_untouched'] is True
    assert (CONTROL / 'queue/owned.txt').read_bytes() == b'authored control\n'
    assert (CONTROL / 'pid.json').stat().st_mtime_ns < (CONTROL / 'observer-ready').stat().st_mtime_ns
    assert (CONTROL / 'observer-ready').read_bytes() == b'FRIDA_READY\n'
    loads = records_for(bundle, session['session_id'], 'load_frida_script')
    finals = [row for row in records_for(bundle, session['session_id'], 'frida_session_status')
              if row['normalized_result'].get('state') == 'detached']
    assert len(loads) == len(finals) == 1
    load, final = loads[0], finals[0]
    assert load['evidence_id'] == session['load_evidence_id']
    assert final['evidence_id'] == session['final_evidence_id']
    assert load['normalized_result']['source_sha256'] == sha(CONTROL / 'observer.js')
    early, messages = payloads(load), payloads(final)
    assert messages[:len(early)] == early
    assert [item['kind'] for item in early[-2:]] == ['observer-ready', 'exit-boundary-armed']
    assert early[-2]['data']['errors'] == []
    assert all(item['pid'] == session['pid'] and item['runId'] == request['config']['runId']
               for item in messages)
    tracked = [item['data']['path'] for item in messages if item['kind'] == 'file-operation'
               and item['data']['operation'] == 'NtCreateFile']
    assert any(path.startswith('\\\\?\\') and path.lower().endswith('\\queue\\owned.txt')
               for path in tracked)
    boundary = messages[-1]
    assert boundary['kind'] == 'self-terminate-entry'
    assert boundary['data']['exitStatus'] == 0
    assert boundary['data']['rootResolveCalls'] == 1
    assert boundary['data']['rootResolveFailed'] == 0
    assert boundary['data']['unknownRelativeRoots'] == 0
    assert boundary['data']['errors'] == [] and boundary['data']['overflow'] is False
    assert not any(item['kind'] in ('decode-error', 'budget-exceeded') for item in messages)

    game = game_verify(CASE=CASE, TRACE=TRACE, source_builder=build_source,
                       resolve_roots=True)
    assert game['passed']
    assert all(client['root_resolve_calls'] == 1 and
               client['root_resolve_failed'] == 0 and
               client['unknown_relative_roots'] == 0 for client in game['clients'])
    return dict(passed=True, scope='Selected relative-root NtCreateFile paths resolved in an owned control and two current private-pair native clients; no selected SDK-root event from pre-resume to self-termination entry; preexisting read handles and other APIs remain unqualified',
                control_load_evidence_id=load['evidence_id'],
                control_final_evidence_id=final['evidence_id'],
                control_bundle_sha256=sha(CONTROL / 'rea-evidence.json'),
                game=game, full_d5_qualified=False)


if __name__ == '__main__':
    result = verify()
    output = CASE / 'root-review.json'
    if output.exists():
        assert read(output) == result
    else:
        output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': result['passed'], 'clients': result['game']['clients']}))
