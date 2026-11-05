"""Bind connected native socket calls to each packaged inherited bridge handle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.frida_socket_handles import build_source
from tools.review_d5_connected_network341 import ROOT, review as network_review
from tools.review_d5_connected_pair338 import sha


def review(case: Path, trace: Path, packages: Path, game: Path, assets: Path) -> dict:
    network = network_review(case, trace, packages, game, assets)
    bundle = json.loads((trace / 'rea-evidence.json').read_text(encoding='utf-8'))
    manifest = json.loads((trace / 'sessions.json').read_text(encoding='utf-8'))
    handles = []
    for row in manifest['clients']:
        index, session = row['index'], row['session_id']
        native = json.loads((case / f'client-{index}/game-process.json').read_text(
            encoding='utf-8'))
        bridge = [argument for argument in native['actual_arguments']
                  if argument.startswith('-secure-transport-socket=')]
        assert len(bridge) == 1
        numeric = int(bridge[0].split('=', 1)[1])
        assert 0 < numeric < 2**32
        expected = hex(numeric)
        config = json.loads((trace / f'config-{index}.json').read_text(
            encoding='utf-8'))['config']
        observer = trace / f'observer-{index}.js'
        assert observer.read_bytes() == build_source(config).encode('utf-8')
        finals = [record for record in bundle['records']
                  if record['operation'] == 'frida_session_status'
                  and record.get('parameters', {}).get('session_id') == session
                  and record.get('normalized_result', {}).get('state') == 'detached']
        assert len(finals) == 1
        messages = finals[0]['normalized_result']['messages']
        heartbeats = [message['payload']['data'] for message in messages
                      if message['payload']['kind'] == 'heartbeat']
        assert len(heartbeats) >= 10
        for snapshot in heartbeats:
            calls = snapshot['counts']
            by_handle = snapshot['socketHandles']
            for name in ('send', 'recv'):
                count = calls['ws2_32.dll:' + name]
                assert by_handle[name] == ({expected: count} if count else {})
        last = heartbeats[-1]
        assert last['socketHandles']['send'][expected] > 0
        assert last['socketHandles']['recv'][expected] > 0
        handles.append({'index': index, 'pid': row['pid'],
                        'inherited_bridge_handle': numeric,
                        'send_calls_on_bridge': last['socketHandles']['send'][expected],
                        'recv_calls_on_bridge': last['socketHandles']['recv'][expected],
                        'other_send_recv_handles': 0,
                        'heartbeats': len(heartbeats),
                        'observer_sha256': sha(observer)})
    return {'passed': True,
            'scope': 'Current private pair connected public1/two-human match; '
                     'both native clients post-attach through last heartbeat, '
                     'selected send/recv entries only on inherited bridge handle; '
                     'not startup, final seconds, other APIs/processes or wire',
            'network_review': network, 'handles': handles,
            'socket_handle_source_sha256': sha(ROOT / 'tools/frida_socket_handles.py'),
            'full_d5_qualified': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('case', 'trace', 'packages', 'game', 'assets'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    paths = {key: getattr(args, key).resolve()
             for key in ('case', 'trace', 'packages', 'game', 'assets')}
    assert all(path.is_relative_to(ROOT / 'local') for path in paths.values())
    result = review(**paths)
    output = paths['case'] / 'socket-review.json'
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': result['passed'], 'review': str(output),
                      'handles': result['handles']}))


if __name__ == '__main__':
    main()
