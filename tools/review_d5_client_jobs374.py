"""Review inherited client-job descendants in current private public matches."""
from __future__ import annotations

import ast
import json
from pathlib import Path

from tools.review_d5_connected_modes363 import check as mode_check
from tools.review_d5_connected_pair338 import ROOT, sha
from tools.review_d5_unresolved_file_status373 import review as current_review

PACKAGES = ROOT / 'local/privacy358-packages02'
GAME = ROOT / 'local/privacy301-runtime01/game'
ASSETS = ROOT / 'local/s139/assets/build-37822'
HELPER = ROOT / 'local/privacy357-helper-build01/helper-build.json'
CASES = ((ROOT / 'local/privacy361-connected05', 5),
         (ROOT / 'local/privacy362-connected02', 2),
         (ROOT / 'local/privacy373-connected01', 1))


def source_policy() -> dict:
    path = ROOT / 'server/worker_client.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    jobs = [node for node in tree.body if isinstance(node, ast.ClassDef)
            and node.name == '_WindowsJob']
    assert len(jobs) == 1
    init = [node for node in jobs[0].body if isinstance(node, ast.FunctionDef)
            and node.name == '__init__']
    assert len(init) == 1
    flags = [node for node in ast.walk(init[0]) if isinstance(node, ast.Assign)
             and len(node.targets) == 1 and isinstance(node.targets[0], ast.Attribute)
             and node.targets[0].attr == 'flags']
    assert len(flags) == 1 and isinstance(flags[0].value, ast.Constant)
    assert flags[0].value.value == 0x2000
    calls = [node.func.attr for node in ast.walk(init[0]) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)]
    assert calls.count('SetInformationJobObject') == 1
    assert calls.count('AssignProcessToJobObject') == 1
    return dict(path='server/worker_client.py',sha256=sha(path),
                job_limit_flags='0x2000',breakaway_flags_set=False)


def verify() -> dict:
    policy = source_policy()
    assert current_review()['passed']
    summaries = []
    for case, mode in CASES:
        if mode in (2, 5):
            assert mode_check(case, mode, PACKAGES, GAME, ASSETS, HELPER)['mode'] == mode
        report = json.loads((case / 'verification.json').read_text(encoding='utf-8'))
        assert report['passed'] and report['forced_cleanup'] is False
        assert report['source_files_unchanged'] and report['package_files_unchanged']
        assert report['source_sha256_at_start'][policy['path']] == policy['sha256']
        assert report['source_sha256_at_finish'][policy['path']] == policy['sha256']
        assert len(report['clients']) == 2 and len(report['jobs']) == 3
        assert [job['total_processes'] for job in report['jobs']] == [5, 2, 2]
        assert all(job['active_processes'] == job['total_terminated_processes'] == 0
                   for job in report['jobs'])
        clients = []
        for index, client in enumerate(report['clients']):
            job = report['jobs'][index + 1]
            native = json.loads((case / f'client-{index}/game-process.json').read_text(
                encoding='utf-8'))
            gate = case / f'client-{index}/job-ready'
            assert gate.read_bytes() == b'owned job attached\n'
            assert gate.stat().st_mtime_ns < (case / f'client-{index}/game-process.json').stat().st_mtime_ns
            assert client['pid'] == native['pid'] and client['pid'] != job['pid']
            assert client['driver_report']['game_exit_code'] == 0
            assert client['driver_report']['launcher_exit_code'] == 0
            clients.append(dict(index=index,driver_pid=job['pid'],game_pid=native['pid'],
                                job_total=job['total_processes'],job_active=job['active_processes']))
        summaries.append(dict(mode=mode,verification_sha256=sha(case / 'verification.json'),
                              clients=clients))
    return dict(passed=True,
                scope='Three current private-pair public modes: each owned client job accounted only the packaged driver and native game; no additional job-inheriting client child process during these runs. External broker/WMI paths and other modes remain unqualified.',
                job_policy=policy, modes=summaries, full_p8_qualified=False,
                full_d5_qualified=False)


if __name__ == '__main__':
    result = verify()
    output = ROOT / 'local/privacy374-client-jobs01/review.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        assert json.loads(output.read_text(encoding='utf-8')) == result
    else:
        output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'modes': [row['mode'] for row in result['modes']]}))
