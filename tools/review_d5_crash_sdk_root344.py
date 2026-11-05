"""Review the named SDK-cache path in a suspended-start native crash trace."""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PureWindowsPath

from tools.review_crash_policy170 import review as crash_review, stream
from tools.review_d5_connected_pair338 import ROOT, sha


def normal(value: str) -> str:
    return str(PureWindowsPath(value)).lower().rstrip('\\')


def under(path: str, root: str) -> bool:
    path = normal(path)
    return path == root or path.startswith(root + '\\')


def review(case: Path) -> dict:
    crash = crash_review(case)
    owner = json.loads((case / 'verification.json').read_text(encoding='utf-8'))
    bundle = json.loads((case / 'evidence.json').read_text(encoding='utf-8'))
    binding = json.loads((ROOT / 'local/privacy293-root-binding01/verification.json')
                         .read_text(encoding='utf-8'))
    source = json.loads((ROOT / 'local/privacy269-startup01/verification.json')
                        .read_text(encoding='utf-8'))
    roots = owner['config']['fileRoots']
    assert len(roots) == 6
    root = normal(roots[-1])
    assert root == normal(source['sdk_cache_root']) and binding['passed'] is True
    game = ROOT / 'local/privacy301-runtime01/game'
    assert sha(game / 'UnityPlayer.dll') == binding['common_unity_sha256']
    session = json.loads((case / 'rea-start.json').read_text(encoding='utf-8'))[
        'structuredContent']['session_id']
    finals = [record for record in bundle['records']
              if record['operation'] == 'frida_session_status'
              and record.get('parameters', {}).get('session_id') == session
              and record.get('normalized_result', {}).get('state') == 'detached']
    assert len(finals) == 1
    events = stream(finals[0]['normalized_result'], owner['pid'], owner['config']['runId'])
    file_events = [event['data'] for event in events if event['kind'] == 'file-operation']
    aggregate_rows = [row for event in events if event['kind'] == 'policy-files'
                      for row in event['data']['rows']]
    assert sum(row['count'] for row in aggregate_rows) == crash['aggregate_operations']
    assert len(aggregate_rows) == crash['aggregate_rows']
    assert all(not under(row.get('path', ''), root) for row in file_events)
    assert all(not under(row.get('path', ''), root) for row in aggregate_rows)
    assert crash['file_operations']['NtCreateFile'] > 0
    assert crash['file_operations']['NtOpenFile'] > 0
    assert crash['file_operations']['NtWriteFile'] > 0
    return {'passed': True,
            'scope': 'Recipe34 owned suspended-start native crash through '
                     'original filter return; selected named SDK-cache root '
                     'file API events zero, not post-filter/whole-program I/O',
            'crash': crash, 'sdk_root': roots[-1],
            'selected_sdk_file_events_outside_policy': 0,
            'selected_sdk_file_aggregate_rows_inside_policy': 0,
            'selected_sdk_file_operations_inside_policy': 0,
            'non_sdk_aggregate_operations_positive': crash['aggregate_operations'],
            'owner_sha256': sha(case / 'verification.json'),
            'evidence_sha256': sha(case / 'evidence.json'),
            'full_d5_qualified': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    args = parser.parse_args()
    case = args.case.resolve()
    assert case.is_relative_to(ROOT / 'local')
    result = review(case)
    output = case / 'sdk-root-review.json'
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': result['passed'], 'review': str(output),
                      'selected_sdk_file_events_outside_policy': 0,
                      'selected_sdk_file_operations_inside_policy': 0}))


if __name__ == '__main__':
    main()
