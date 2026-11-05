"""Review owned prelaunch SDK wrapper/core entry observation in public1."""
from __future__ import annotations

import json

from tools.frida_sdk_send408 import build_source
from tools.review_d5_connected_pair338 import ROOT, sha
from tools.review_d5_exit_network368 import payloads, read, records_for
from tools.review_d5_socket_exit370 import verify as network_verify

CASE = ROOT / 'local/privacy408-sdk-send02'
TRACE = ROOT / 'local/privacy408-sdk-send-trace02'


def review() -> dict:
    network = network_verify(CASE, TRACE, build_source, True)
    report, sessions, bundle = (read(CASE / 'verification.json'),
                                read(TRACE / 'sessions.json'),
                                read(TRACE / 'rea-evidence.json'))
    assert report['passed'] and report['mode'] == 1 and report['humans'] == 2
    assert report['match']['frames'] >= 1200
    assert report['forced_cleanup'] is False
    clients = []
    for row in sessions['clients']:
        index, pid, sid = row['index'], row['pid'], row['session_id']
        config = read(TRACE / f'config-{index}.json')
        assert config['sdk_send'] is True and config['source_sha256'] == sha(TRACE / f'observer-{index}.js')
        loads = records_for(bundle, sid, 'load_frida_script')
        finals = [event for event in records_for(bundle, sid, 'frida_session_status')
                  if event['normalized_result'].get('state') == 'detached']
        assert len(loads) == len(finals) == 1
        messages = payloads(finals[0])
        ready = [event for event in messages if event['kind'] == 'sdk-module-ready']
        assert len(ready) == 1
        assert ready[0]['data'] == dict(module='gameassembly.dll',
            hooks=[dict(key='wrapper', rva=0x80e920), dict(key='core', rva=0x53dd0d0)], errors=[])
        assert ready[0]['seq'] < messages[-1]['seq']
        boundary = messages[-1]
        assert boundary['kind'] == 'self-terminate-entry'
        assert boundary['data']['sdkHooks'] == ready[0]['data']['hooks']
        assert boundary['data']['sdkErrors'] == []
        assert boundary['data']['sdkCounts'] == dict(wrapper=0, core=0)
        clients.append(dict(index=index, pid=pid, session_id=sid,
                            sdk_counts=boundary['data']['sdkCounts'],
                            load_evidence_id=loads[0]['evidence_id'],
                            final_evidence_id=finals[0]['evidence_id']))
    return dict(passed=True, clients=clients, network_review=network,
                verification_sha256=sha(CASE / 'verification.json'),
                bundle_sha256=sha(TRACE / 'rea-evidence.json'),
                scope='Current private public1 two-human entry observation from pre-main-thread resume to self-termination entry; indirect SDK wrapper and shared Unity send not invoked in either client; other paths, queue, wire and final installed release remain open',
                full_d5_qualified=False)


if __name__ == '__main__':
    result = review()
    output = CASE / 'sdk-send-review.json'
    if output.exists():
        assert json.loads(output.read_text(encoding='utf-8')) == result
    else:
        output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, clients=result['clients'])))
