"""Review owned packaged driver Job assignment before first thread resume."""
from __future__ import annotations

import inspect
import json

from tools.review_d5_client_jobs374 import source_policy
from tools.review_d5_connected_pair338 import ROOT, run, sha
from tools.verify_packaged_multiplayer import Child

CASE = ROOT / 'local/privacy376-job-launch01'
PACKAGES = ROOT / 'local/privacy358-packages02'
GAME = ROOT / 'local/privacy301-runtime01/game'
ASSETS = ROOT / 'local/s139/assets/build-37822'


def review() -> dict:
    source = ROOT / 'tools/verify_packaged_multiplayer.py'
    body = inspect.getsource(Child.__init__)
    steps = ('creationflags=0x00000004', 'self.job=_WindowsJob(self.process.pid)',
             'status=ntdll.NtResumeProcess(self.process._handle)',
             "require(status==0,'owned packaged driver resume failed')")
    positions = [body.index(step) for step in steps]
    assert positions == sorted(positions)
    policy = source_policy()
    connected = run(CASE, PACKAGES, GAME, ASSETS)
    assert connected['passed']
    report = json.loads((CASE / 'verification.json').read_text(encoding='utf-8'))
    pinned_source = '8e0bf170286b7b20a431e74f3e56aeedc756375d072e996707650ec1ecd8b5b2'
    assert report['source_sha256_at_start']['tools/verify_packaged_multiplayer.py'] == pinned_source
    assert report['source_sha256_at_finish']['tools/verify_packaged_multiplayer.py'] == pinned_source
    assert report['source_sha256_at_start'][policy['path']] == policy['sha256']
    assert report['source_sha256_at_finish'][policy['path']] == policy['sha256']
    assert len(report['jobs']) == 3
    assert [job['total_processes'] for job in report['jobs']] == [5, 2, 2]
    launches = []
    for index, job in enumerate(report['jobs']):
        launch = job['launch']
        assert launch['pid'] == job['pid']
        assert launch['created_suspended'] and launch['job_attached_before_resume']
        assert launch['create_return_tick'] <= launch['job_assigned_tick'] <= launch['resumed_tick']
        assert job['active_processes'] == job['total_terminated_processes'] == 0
        folder = CASE / ('server' if index == 0 else f'client-{index - 1}')
        assert (folder / 'job-ready').read_bytes() == b'owned job attached\n'
        if index:
            native = json.loads((folder / 'game-process.json').read_text(encoding='utf-8'))
            assert native['pid'] == report['clients'][index - 1]['pid'] != job['pid']
            assert (folder / 'job-ready').stat().st_mtime_ns < (folder / 'game-process.json').stat().st_mtime_ns
        launches.append(launch)
    return dict(passed=True, scope='One current private public1 match: owned packaged driver created suspended, assigned to no-breakaway Job before resume; client jobs accounted driver and game through normal Quit. External broker and other modes remain open.',
                source_sha256=pinned_source, job_policy=policy,
                verification_sha256=sha(CASE / 'verification.json'),
                launches=launches, full_p8_qualified=False, full_d5_qualified=False)


if __name__ == '__main__':
    result = review()
    output = CASE / 'job-launch-review.json'
    if output.exists():
        assert json.loads(output.read_text(encoding='utf-8')) == result
    else:
        output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'jobs': len(result['launches'])}))
