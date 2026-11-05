"""Reconcile the inert suspended-process Frida prelaunch control."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT/'local/privacy365-prelaunch-control02'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    report_path = CASE/'verification.json'
    evidence_path = CASE/'frida-evidence.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    source = ROOT/'tools/frida_prelaunch_control365.js'
    assert report['passed'] and report['observer_gate_preceded_child']
    assert report['child_exit_code'] == 0 and not report['forced_owned_cleanup']
    assert Path(report['output']).resolve() == CASE
    marker = Path(report['marker']).resolve()
    assert marker == CASE/'child-ran.txt'
    assert sha(marker) == report['child_marker_sha256']
    assert (CASE/'observer-ready').read_bytes() == b'FRIDA_READY\n'
    assert evidence['source_sha256'] == sha(source)
    assert evidence['load_evidence_id'].startswith('ev_')
    assert evidence['evidence_id'].startswith('ev_')
    status = evidence['normalized_result']
    assert status['mode'] == 'attach' and status['state'] == 'detached'
    assert status['pid'] == report['pid'] and not status['messages_truncated']
    assert len(status['scripts']) == 1
    script_id = status['scripts'][0]['script_id']
    assert status['messages'] == [
        dict(script_id=script_id, type='send',
             payload=dict(kind='ready', pid=report['pid'], hook='CreateFileW')),
        dict(script_id=script_id, type='send',
             payload=dict(kind='first-create-file', pid=report['pid'])),
    ]
    result = dict(passed=True, scope='Owned inert suspended Python process: passive CreateFileW hook ready before main-thread resume, positive file call after resume and natural exit; no game/SDK/wire coverage',
                  process_pid=report['pid'], process_report_sha256=sha(report_path),
                  frida_status_sha256=sha(evidence_path), observer_source_sha256=sha(source),
                  frida_load_evidence_id=evidence['load_evidence_id'],
                  frida_status_evidence_id=evidence['evidence_id'],
                  observer_ready_before_resume=True, observed_file_call_after_resume=True,
                  game_process_qualified=False, full_d5_qualified=False)
    output = CASE/'review.json'
    assert not output.exists()
    output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'pid': report['pid']}))


if __name__ == '__main__':
    main()
