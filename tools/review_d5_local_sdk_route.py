"""Review one owned local match's passive SDK cache and selected route evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tools.frida_browser_activation import review, stream


ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normal(value: str) -> str:
    if value.startswith('\\??\\'):
        value = value[4:]
    return value.replace('/', '\\').lower().rstrip('\\')


def run(folder: Path, game: Path) -> dict:
    owner_path = folder / 'verification.json'
    owner = json.loads(owner_path.read_text(encoding='utf-8'))
    start = json.loads((folder / 'rea-start.json').read_text(encoding='utf-8'))['structuredContent']
    bundle = json.loads((folder / 'rea-evidence.json').read_text(encoding='utf-8'))
    binding = json.loads((ROOT / 'local/privacy293-root-binding01/verification.json').read_text(encoding='utf-8'))
    manifest = json.loads((game / '.battleaces-resurrection/patch-manifest.json').read_text(encoding='utf-8'))

    assert owner['passed'] and len(owner['requested_modes']) == 1
    assert owner['requested_modes'][0] in (1, 2, 4, 5)
    assert owner['exit_code'] == 0 and owner['native_lifecycle_complete']
    assert owner['launch']['forced_cleanup'] is False and owner['source_files_unchanged']
    assert owner['tracker']['complete'] and owner['tracker']['final_accounting'] == {
        'total': 1, 'active': 0, 'terminated': 0}
    assert owner['telemetry']['passed'] and owner['telemetry']['complete_snapshots'] >= 7
    assert owner['remote_connections'] == owner['invite_reads'] == 0
    assert start['pid'] == owner['pid'] and start['mode'] == 'attach'
    assert owner['observer_sha256'] == sha(folder / 'observer.js')
    assert owner['helper_sha256'] == sha(game / 'BattleAcesOffline.dll') == manifest['helper_sha256']
    assert sha(game / 'GameAssembly.dll') == manifest['patched_sha256']
    assert binding['passed'] and sha(game / 'UnityPlayer.dll') == binding['common_unity_sha256']

    config = owner['config']
    assert len(config['fileRoots']) == 3
    assert hashlib.sha256(config['fileRoots'][2].replace('\\', '/').encode('utf-16le')).hexdigest() == binding['normalized_root_utf16le_sha256']
    observer = (folder / 'observer.js').read_text(encoding='utf-8')
    marker = 'const config='
    assert marker in observer and ', api=' in observer
    embedded = json.loads(observer.split(marker, 1)[1].split(', api=', 1)[0])
    assert embedded == config

    records = [row for row in bundle['records'] if row.get('parameters', {}).get('session_id') == start['session_id']]
    loads = [row for row in records if row['operation'] == 'load_frida_script']
    finals = [row for row in records if row['operation'] == 'frida_session_status'
              and row['normalized_result'].get('state') == 'detached']
    assert len(loads) == len(finals) == 1
    load, final = loads[0], finals[0]
    assert load['normalized_result']['source_sha256'] == owner['observer_sha256']
    assert load['normalized_result']['messages_truncated'] is False
    assert not any(row['type'] == 'error' for row in load['normalized_result']['messages'])
    normalized = final['normalized_result']
    assert normalized['pid'] == owner['pid'] and normalized['messages_truncated'] is False
    assert len(normalized['scripts']) == 1
    rows = stream(normalized, owner['pid'], config['runId'])
    route = review(normalized, owner)
    assert route['passed'] and route['no_selected_browser_activation']
    assert route['no_selected_process_or_shell_call']

    files = [row['data'] for row in rows if row['kind'] == 'file-operation']
    assert files and all(row['pending'] is False for row in files)
    roots = [normal(value) for value in config['fileRoots']]
    counts = [0, 0, 0]
    for row in files:
        path = normal(row['path'])
        matches = [i for i, root in enumerate(roots) if path == root or path.startswith(root + '\\')]
        assert len(matches) == 1, f'unclassified or overlapping selected file root: {row["path"]}'
        counts[matches[0]] += 1
    assert counts[0] > 0 and counts[1] > 0 and counts[2] == 0
    terminal = rows[-1]['data']
    assert terminal['errors'] == [] and terminal['overflow'] is False
    assert terminal['unknownRelativeRoots'] == 0 and terminal['resolvedCwdRoots'] == 2

    bridge = [value for value in owner['client_arguments'] if value.startswith('-secure-transport-socket=')]
    assert len(bridge) == 1
    handle = int(bridge[0].split('=', 1)[1])
    assert owner['launch']['inherited_bridge_handle'] == handle
    network = [row['data'] for row in rows if row['kind'] == 'network-operation']
    assert len(network) == 5 and all(int(row['socket'], 16) == handle for row in network)
    selected = {key: value for key, value in terminal['counts'].items()
                if key.startswith(('ws2_32.dll:', 'winhttp.dll:'))}
    assert selected['ws2_32.dll:send'] == 2 and selected['ws2_32.dll:recv'] == 3
    assert all(value == 0 for key, value in selected.items()
               if key not in ('ws2_32.dll:send', 'ws2_32.dll:recv'))

    return {
        'passed': True,
        'scope': f'Owned recipe34 local public mode{owner["requested_modes"][0]} through original result, Continue and Quit; selected user-mode APIs and three passive file roots only',
        'owner_sha256': sha(owner_path),
        'bundle_sha256': sha(folder / 'rea-evidence.json'),
        'observer_sha256': owner['observer_sha256'],
        'final_evidence_id': final['evidence_id'],
        'observer_events': len(rows),
        'selected_file_events': len(files),
        'selected_file_root_counts': {'owned_output': counts[0], 'owned_profile': counts[1], 'sdk_cache': counts[2]},
        'selected_network_counts': selected,
        'selected_network_bridge_calls': len(network),
        'no_selected_browser_activation': True,
        'no_selected_process_or_shell_call': True,
        'native_telemetry_snapshots': owner['telemetry']['complete_snapshots'],
        'job': owner['tracker']['final_accounting'],
        'unknown_relative_roots': terminal['unknownRelativeRoots'],
        'overflow': terminal['overflow'],
        'full_privacy_qualified': False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--game', type=Path, required=True)
    args = parser.parse_args()
    folder, game = args.case.resolve(), args.game.resolve()
    assert folder.is_relative_to(ROOT / 'local') and game.is_relative_to(ROOT / 'local')
    result = run(folder, game)
    path = folder / 'route-review.json'
    path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'review': str(path),
                      'events': result['observer_events'],
                      'sdk_cache_events': result['selected_file_root_counts']['sdk_cache']}))


if __name__ == '__main__':
    main()
