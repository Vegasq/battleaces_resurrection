"""Review passive selected network API counts in two current connected clients."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.frida_attribution_source import API
from tools.review_d5_connected_pair338 import ROOT, run, sha


def review(case: Path, trace: Path, packages: Path, game: Path, assets: Path) -> dict:
    connected = run(case, packages, game, assets)
    manifest = json.loads((trace / 'sessions.json').read_text(encoding='utf-8'))
    bundle = json.loads((trace / 'rea-evidence.json').read_text(encoding='utf-8'))
    assert manifest['case'] == 'local/' + case.name
    assert len(manifest['clients']) == 2
    assert len({row['pid'] for row in manifest['clients']}) == 2
    assert len({row['session_id'] for row in manifest['clients']}) == 2
    summaries = []
    for row in manifest['clients']:
        index, pid, session = row['index'], row['pid'], row['session_id']
        assert index in (0, 1)
        native = json.loads((case / f'client-{index}/game-process.json').read_text(
            encoding='utf-8'))
        assert native['pid'] == pid
        config = json.loads((trace / f'config-{index}.json').read_text(encoding='utf-8'))
        observer = trace / f'observer-{index}.js'
        assert sha(observer) == config['source_sha256']
        assert config['config']['image'] == str((game / 'Battle Aces.exe').resolve())
        assert len(config['config']['fileRoots']) == 1
        records = [item for item in bundle['records']
                   if item.get('parameters', {}).get('session_id') == session]
        loads = [item for item in records if item['operation'] == 'load_frida_script']
        finals = [item for item in records if item['operation'] == 'frida_session_status'
                  and item.get('normalized_result', {}).get('state') == 'detached']
        assert len(loads) == len(finals) == 1
        load, final = loads[0], finals[0]
        assert load['normalized_result']['source_sha256'] == sha(observer)
        assert load['normalized_result']['messages_truncated'] is False
        assert final['normalized_result']['messages_truncated'] is False
        assert final['normalized_result']['pid'] == pid
        messages = final['normalized_result']['messages']
        assert all(message['type'] == 'send' for message in messages)
        assert all(message['payload']['pid'] == pid and
                   message['payload']['runId'] == config['config']['runId']
                   for message in messages)
        assert [message['payload']['seq'] for message in messages] == list(
            range(1, len(messages) + 1))
        ready = [message for message in messages
                 if message['payload']['kind'] == 'observer-ready']
        heartbeats = [message for message in messages
                      if message['payload']['kind'] == 'heartbeat']
        assert len(ready) == 1 and len(heartbeats) >= 10
        assert not any(message['payload']['kind'] in ('decode-error', 'budget-exceeded')
                       for message in messages)
        final_counts = heartbeats[-1]['payload']['data']
        assert final_counts['errors'] == [] and final_counts['overflow'] is False
        installed = {item['key'] for item in final_counts['installed']}
        assert {f'{module}:{name}' for module, names in API.items()
                for name in names if module in ('ws2_32.dll', 'winhttp.dll')} <= installed
        counts = final_counts['counts']
        assert counts['ws2_32.dll:send'] > 0 and counts['ws2_32.dll:recv'] > 0
        zero = ['connect', 'WSAConnect', 'sendto', 'WSASendTo',
                'getaddrinfo', 'GetAddrInfoW', 'GetAddrInfoExW']
        assert all(counts['ws2_32.dll:' + name] == 0 for name in zero)
        assert counts['winhttp.dll:WinHttpConnect'] == 0
        summaries.append({'index': index, 'pid': pid, 'session_id': session,
                          'load_evidence_id': load['evidence_id'],
                          'final_evidence_id': final['evidence_id'],
                          'messages': len(messages), 'heartbeats': len(heartbeats),
                          'send_calls': counts['ws2_32.dll:send'],
                          'recv_calls': counts['ws2_32.dll:recv'],
                          'selected_connect_dns_sendto_winhttp_calls': 0,
                          'unknown_relative_roots': final_counts['unknownRelativeRoots']})
    return {'passed': True,
            'scope': 'Two owned current-package native clients after Frida attach '
                     'through last heartbeat; selected user-mode API counts only, '
                     'not pre-attach, socket-handle, queue, descendant or whole-wire proof',
            'connected': connected, 'bundle_sha256': sha(trace / 'rea-evidence.json'),
            'clients': summaries, 'full_d5_qualified': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('case', 'trace', 'packages', 'game', 'assets'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    paths = {key: getattr(args, key).resolve()
             for key in ('case', 'trace', 'packages', 'game', 'assets')}
    assert all(path.is_relative_to(ROOT / 'local') for path in paths.values())
    result = review(**paths)
    output = paths['case'] / 'network-review.json'
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': result['passed'], 'review': str(output),
                      'clients': result['clients']}))


if __name__ == '__main__':
    main()
