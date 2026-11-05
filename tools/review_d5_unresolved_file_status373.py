"""Review preexisting-file control and failed unclassified file calls in a current match."""
from __future__ import annotations

import json

from tools.frida_preexisting_file_source372 import build_source as control_source
from tools.frida_unresolved_file_status373 import build_source as game_source
from tools.review_d5_connected_pair338 import ROOT, sha
from tools.review_d5_exit_network368 import read, records_for, payloads
from tools.review_d5_socket_exit370 import verify as game_verify

CONTROL = ROOT / 'local/privacy372-read-control01'
CASE = ROOT / 'local/privacy373-connected01'
TRACE = ROOT / 'local/privacy373-unresolved-trace01'


def review() -> dict:
    request, session, receipt = (read(CONTROL / 'request.json'),
                                 read(CONTROL / 'session.json'),
                                 read(CONTROL / 'positive.json'))
    bundle = read(CONTROL / 'rea-evidence.json')
    assert request['mode'] == 'attach'
    assert request['source_sha256'] == sha(CONTROL / 'observer.js')
    assert (CONTROL / 'observer.js').read_text(encoding='utf-8') == control_source(request['config'])
    assert receipt['pid'] == session['pid'] == read(CONTROL / 'pid.json')['pid']
    assert receipt['authored_content_matched'] is True and receipt['read_bytes'] == 17
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
    assert [row['kind'] for row in early[-2:]] == ['observer-ready', 'exit-boundary-armed']
    assert early[-2]['data']['errors'] == []
    reads = [row['data'] for row in messages if row['kind'] == 'file-operation'
             and row['data']['operation'] == 'NtReadFile']
    assert len(reads) == 1 and reads[0]['returnValue'] == 0
    assert reads[0]['path'].startswith('\\\\?\\')
    assert reads[0]['path'].lower().endswith('\\queue\\owned.txt')
    boundary = messages[-1]
    assert boundary['kind'] == 'self-terminate-entry'
    assert boundary['data']['exitStatus'] == 0
    assert boundary['data']['fileResolveCalls'] == 1
    assert boundary['data']['fileResolveFailed'] == 0
    assert boundary['data']['unresolvedFileOps'] == 0
    assert boundary['data']['errors'] == [] and boundary['data']['overflow'] is False
    assert not any(row['kind'] in ('decode-error', 'budget-exceeded') for row in messages)

    game = game_verify(CASE=CASE, TRACE=TRACE, source_builder=game_source,
                       resolve_roots=True)
    assert game['passed']
    sessions, game_bundle = read(TRACE / 'sessions.json'), read(TRACE / 'rea-evidence.json')
    summaries = []
    for client in sessions['clients']:
        index, pid, sid = client['index'], client['pid'], client['session_id']
        config = read(TRACE / f'config-{index}.json')
        assert config['resolve_existing_files'] and config['unresolved_file_status']
        finals = [row for row in records_for(game_bundle, sid, 'frida_session_status')
                  if row['normalized_result'].get('state') == 'detached']
        assert len(finals) == 1
        events = payloads(finals[0])
        assert all(row['pid'] == pid and row['runId'] == config['config']['runId']
                   for row in events)
        unresolved = [row['data'] for row in events
                      if row['kind'] == 'unresolved-file-operation']
        assert len(unresolved) == 9
        assert all(row == dict(operation='NtWriteFile', handle='0xffffffffffffffff',
                               fileType=0, api='ntdll.dll:NtWriteFile',
                               returnValue=-1073741816) for row in unresolved)
        last = events[-1]
        assert last['kind'] == 'self-terminate-entry'
        data = last['data']
        assert data['rootResolveCalls'] == 1 and data['rootResolveFailed'] == 0
        assert data['unknownRelativeRoots'] == 0
        assert data['fileResolveFailed'] == 1
        assert data['unresolvedFileOps'] == len(unresolved)
        assert data['fileResolveCalls'] > 1
        assert data['errors'] == [] and data['overflow'] is False
        assert not any(row['kind'] in ('file-operation', 'decode-error',
                                       'budget-exceeded') for row in events)
        summaries.append(dict(index=index, pid=pid,
                              successful_unclassified_selected_file_ops=0,
                              failed_invalid_handle_writes=len(unresolved),
                              file_resolve_calls=data['fileResolveCalls'],
                              load_evidence_id=game['clients'][index]['load_evidence_id'],
                              final_evidence_id=game['clients'][index]['final_evidence_id']))
    return dict(passed=True, scope='Selected native file APIs from pre-main-thread-resume to self-termination entry in two current private-pair clients; one owned preexisting-file positive control; unclassified operations are only failed invalid-handle writes; other APIs/aliases/processes and full D5 remain open',
                control_load_evidence_id=load['evidence_id'],
                control_final_evidence_id=final['evidence_id'],
                control_bundle_sha256=sha(CONTROL / 'rea-evidence.json'),
                game_bundle_sha256=sha(TRACE / 'rea-evidence.json'),
                game=game, clients=summaries, full_d5_qualified=False)


if __name__ == '__main__':
    result = review()
    output = CASE / 'file-status-review.json'
    if output.exists():
        assert read(output) == result
    else:
        output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'clients': result['clients']}))
