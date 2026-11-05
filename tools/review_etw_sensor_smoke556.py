"""Fail-closed structural review of the synthetic ETW sensor smoke.

This deliberately cannot certify event coverage until a real ETL sample has
been inspected for schema, loss counters and positive-control attribution.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

PROVIDERS = {
    'net': ('{7DD42A49-5329-4832-8DFD-43D979153A88}', '0x30'),
    'file': ('{EDD08927-9CC4-4E65-B970-C2560FB5C289}', '0x1FF0'),
    'proc': ('{22FB2CD6-0E7B-422B-A0C7-2FAD1FD0E716}', '0x470'),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review(folder: Path) -> dict:
    folder = folder.resolve(strict=True)
    capture = json.loads((folder / 'capture.json').read_text(encoding='utf-8-sig'))
    activity = json.loads((folder / 'activity.json').read_text(encoding='utf-8'))
    assert capture['schema'] == 1 and capture['collection_complete'] is True
    assert capture['game_launched'] is False and capture['real_report_queue_touched'] is False
    assert activity['passed'] and activity['loopback_address'] == '127.0.0.1'
    assert len(capture['sessions']) == 3
    assert {row['kind'] for row in capture['sessions']} == set(PROVIDERS)
    assert all(row['name'].startswith('BA_D5_556_') for row in capture['sessions'])
    assert all((row['provider'], row['keyword']) == PROVIDERS[row['kind']]
               for row in capture['sessions'])
    assert all(row.get('exit_code', 0) == 0 for row in capture['commands'] if 'program' in row)
    assert all((folder / Path(row['etl']).name).resolve() == Path(row['etl']).resolve()
               for row in capture['sessions'])
    expected = {row['name']: row for row in capture['files']}
    for name, item in expected.items():
        path = folder / name
        assert path.is_file() and path.stat().st_size == item['bytes']
        assert sha(path) == item['sha256']
    marker = activity['marker']
    assert marker.startswith('BA_ETW_556_')
    for key in ('parent_file', 'child_file'):
        path = Path(activity[key]).resolve()
        assert path.parent == folder and path.is_file()
        assert sha(path) == activity['payload_sha256']

    observations = {}
    for kind in PROVIDERS:
        etl = folder / f'{kind}.etl'
        xml = folder / f'{kind}.xml'
        summary = folder / f'{kind}-summary.txt'
        assert etl.stat().st_size > 0 and summary.stat().st_size > 0
        assert xml.stat().st_size > 0
        ET.parse(xml)
        content = xml.read_text(encoding='utf-8-sig', errors='replace').lower()
        observations[kind] = {
            'etl_bytes': etl.stat().st_size,
            'xml_bytes': xml.stat().st_size,
            'marker_literal_seen': marker.lower() in content,
            'parent_pid_literal_seen': str(activity['parent_pid']) in content,
            'child_pid_literal_seen': str(activity['child_pid']) in content,
            'loopback_port_literal_seen': str(activity['loopback_port']) in content,
        }
    return {
        'structural_capture_passed': True,
        'capture_sha256': sha(folder / 'capture.json'),
        'activity_sha256': sha(folder / 'activity.json'),
        'observations': observations,
        'event_schema_and_loss_review_passed': False,
        'whole_wire_qualified': False,
        'full_d5_qualified': False,
    }


if __name__ == '__main__':
    assert len(sys.argv) == 2
    result = review(Path(sys.argv[1]))
    with (Path(sys.argv[1]) / 'review.json').open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print(json.dumps(result, indent=2))
