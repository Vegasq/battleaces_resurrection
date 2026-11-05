"""Review suspended-start current-package native network observation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.frida_attribution_source import API
from tools.review_d5_connected_network341 import review as network_review
from tools.review_d5_connected_pair338 import ROOT, sha

CASE = ROOT/'local/privacy366-connected01'
TRACE = ROOT/'local/privacy366-prelaunch-trace01'
PACKAGES = ROOT/'local/privacy358-packages02'
GAME = ROOT/'local/privacy301-runtime01/game'
ASSETS = ROOT/'local/s139/assets/build-37822'


def main() -> None:
    reviewed = network_review(CASE, TRACE, PACKAGES, GAME, ASSETS)
    report = json.loads((CASE/'verification.json').read_text(encoding='utf-8'))
    sessions = json.loads((TRACE/'sessions.json').read_text(encoding='utf-8'))
    bundle = json.loads((TRACE/'rea-evidence.json').read_text(encoding='utf-8'))
    assert report['passed'] and report['prelaunch_observer'] is True
    assert report['forced_cleanup'] is False and len(report['prelaunch_resume']) == 2
    assert report['source_files_unchanged'] and report['package_files_unchanged']
    assert sessions['case'] == 'local/'+CASE.name
    records = bundle['records']
    clients = []
    for item in sessions['clients']:
        index, pid, session = (item[key] for key in ('index', 'pid', 'session_id'))
        assert index in (0, 1)
        client_dir = CASE/f'client-{index}'
        process_path = client_dir/'game-process.json'
        process = json.loads(process_path.read_text(encoding='utf-8'))
        gate = client_dir/'observer-ready'
        assert process['pid'] == pid and process['suspended_for_observer'] is True
        assert gate.read_bytes() == b'FRIDA_READY\n'
        assert process_path.stat().st_mtime_ns < gate.stat().st_mtime_ns
        assert report['prelaunch_resume'][index]['pid'] == pid
        assert report['prelaunch_resume'][index]['tick'] >= process['launch_tick']
        config = json.loads((TRACE/f'config-{index}.json').read_text(encoding='utf-8'))
        observer = TRACE/f'observer-{index}.js'
        assert config['source_sha256'] == sha(observer)
        assert config['game_sha256'] == sha(GAME/'Battle Aces.exe')
        assert config['config']['image'] == str((GAME/'Battle Aces.exe').resolve())
        assert config['config']['fileRoots'] == [str(Path.home()/'AppData/LocalLow/Uncapped Games/Battle Aces/Bugsnag')]
        loads = [row for row in records if row['operation'] == 'load_frida_script'
                 and row['parameters'].get('session_id') == session]
        finals = [row for row in records if row['operation'] == 'frida_session_status'
                  and row['parameters'].get('session_id') == session
                  and row['normalized_result']['state'] == 'detached']
        assert len(loads) == len(finals) == 1
        load, final = loads[0], finals[0]
        assert load['normalized_result']['source_sha256'] == sha(observer)
        assert load['normalized_result']['source_path'] == str(observer)
        assert load['normalized_result']['messages_truncated'] is False
        early = [message['payload'] for message in load['normalized_result']['messages']]
        assert [row['seq'] for row in early] == list(range(1,len(early)+1))
        assert early[-1]['kind'] == 'observer-ready'
        assert all(row['pid'] == pid and row['runId'] == config['config']['runId'] for row in early)
        assert early[-1]['data']['errors'] == []
        installed = {entry['key'] for entry in early[-1]['data']['installed']}
        required = {f'{module}:{name}' for module,names in API.items()
                    for name in names if module in ('ntdll.dll','ws2_32.dll','kernelbase.dll','advapi32.dll','winhttp.dll')}
        assert required <= installed
        messages = [message['payload'] for message in final['normalized_result']['messages']]
        assert messages[:len(early)] == early
        assert final['normalized_result']['messages_truncated'] is False
        assert not any(row['kind'] in ('decode-error','budget-exceeded','file-operation','process-create','network-operation')
                       for row in messages)
        heartbeats = [row for row in messages if row['kind']=='heartbeat']
        assert len(heartbeats)>=10
        last = heartbeats[-1]['data']
        assert last['errors'] == [] and last['overflow'] is False
        assert last['counts']['ws2_32.dll:send'] > 0 and last['counts']['ws2_32.dll:recv'] > 0
        assert last['unknownRelativeRoots'] >= 0
        clients.append(dict(index=index,pid=pid,load_evidence_id=load['evidence_id'],
                            final_evidence_id=final['evidence_id'],
                            source_sha256=sha(observer),initial_hooks=len(installed),
                            messages=len(messages),heartbeats=len(heartbeats),
                            selected_network_calls={name:last['counts'][f'ws2_32.dll:{name}']
                                                    for name in ('connect','WSAConnect','send','recv','sendto','WSASendTo','getaddrinfo','GetAddrInfoW','GetAddrInfoExW')},
                            winhttp_connect_calls=last['counts']['winhttp.dll:WinHttpConnect'],
                            selected_sdk_root_events=0,
                            unresolved_relative_file_roots=last['unknownRelativeRoots']))
    assert [row['index'] for row in clients] == [0,1]
    assert all(row['selected_network_calls'][name] == 0 for row in clients
               for name in ('connect','WSAConnect','sendto','WSASendTo','getaddrinfo','GetAddrInfoW','GetAddrInfoExW'))
    assert all(row['winhttp_connect_calls'] == 0 for row in clients)
    result = dict(passed=True,scope='Two owned recipe38 native clients observed with selected user-mode API hooks ready before suspended main-thread resume through final heartbeat; no whole wire, relative-file, descendant, or final-suffix claim',
                  connected_report_sha256=sha(CASE/'verification.json'),
                  network_review_sha256=sha(CASE/'network-review.json'),
                  rea_bundle_sha256=sha(TRACE/'rea-evidence.json'),
                  package_build_sha256=sha(PACKAGES/'build-report.json'),
                  clients=clients,gameplay_qualified=reviewed['passed'],
                  prelaunch_selected_hooks_ready=True,
                  all_file_reads_qualified=False,all_network_qualified=False,
                  whole_process_exit_suffix_qualified=False,full_d5_qualified=False)
    output = CASE/'prelaunch-review.json'
    assert not output.exists()
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':True,'clients':len(clients)}))


if __name__=='__main__':main()
