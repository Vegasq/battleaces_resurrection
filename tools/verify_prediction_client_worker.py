"""Owned Unity transport probe; movement prediction is not enabled.

The game is created suspended, assigned to a retained-handle Job, then resumed.
Only the fresh owned profile and output directory receive diagnostic state.
Forced cleanup is always failure. --self-test never launches a game or DLL.
"""
from __future__ import annotations

import argparse
import csv
import ctypes as C
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from client_patch.prediction_worker.native import SIGNATURES, helper_receipt
from server.worker_client import _WindowsJob

MAX_LOG = 32 * 1024 * 1024
CREATE_SUSPENDED = 0x00000004
# Original field metadata, not inferred from this run: six fields carry
# SimReleaseDebugOnlyAttribute and are skipped by PluginIdx1's loader filter.
# Original RVAs379d16d/379d18c/379d19d; cctor sets index1 at3e68a8d.
DIAGNOSTIC_EXPORTS = frozenset((
    'SimCrashOnCommand', 'SimGetDebugDrawCommandBufferCount',
    'SimGetDebugDrawCommandBufferSize', 'SimGetDebugDrawCommandBuffer',
    'SimClearAllDebugDrawCommandBuffers', 'SimSetDebugDrawCommandListsActive',
))
SHIPPING_EXPORTS = frozenset((
    'SimInit', 'SimDestroy', 'SimSetLogCallBack', 'SimSetLogFlags',
    'SimCreateWorld', 'SimDestroyWorld', 'SimStep', 'SimProcessMsg',
    'SimGetSimFrameBuffer', 'SimMakeSimFrame',
    'SimGetLabelsFrameBufferSize', 'SimGetLabelsFrameBuffer',
    'SimGetConnectedPlayersSizeAndVersion', 'SimGetConnectedPlayers',
    'SimGetMapFrameSize', 'SimGetMapFrame', 'SimGetSystemCount', 'SimGetSystemIDAttributes',
))
assert len(SHIPPING_EXPORTS) == 18 and len(DIAGNOSTIC_EXPORTS) == 6
assert SHIPPING_EXPORTS | DIAGNOSTIC_EXPORTS == set(SIGNATURES)
SOURCES = (
    'tools/verify_prediction_client_worker.py', 'server/worker_client.py',
    'client_patch/src/prediction_worker.cpp', 'client_patch/src/offline_client.cpp',
    'client_patch/src/native_quit_smoke.cpp', 'client_patch/src/native_quit_trace.cpp',
    'client_patch/src/lan_audit.cpp', 'client_patch/src/frame_timing_audit.cpp',
    'client_patch/src/practice_ai.cpp', 'client_patch/src/online_presentation.cpp',
    'client_patch/patcher/prediction_worker.py', 'client_patch/checkpoint/native_api_proxy.hpp',
    'client_patch/checkpoint/native_rpc_backend.hpp', 'client_patch/checkpoint/native_worker_channel.hpp',
    'client_patch/checkpoint/native_worker_wire.hpp',
    'client_patch/prediction_worker/__init__.py', 'client_patch/prediction_worker/__main__.py',
    'client_patch/prediction_worker/wire.py', 'client_patch/prediction_worker/native.py',
    'tools/prediction_native.py', 'tools/prepare_prediction_native.py',
    'tools/prediction_crt_attach.py',
    'client_patch/prediction_worker/checkpoint.py', 'client_patch/prediction_worker/prediction.py',
    'client_patch/prediction_worker/presentation.py',
    'server/native_simulation.py', 'server/simulation_worker.py',
)


def require(value, message):
    if not value:
        raise AssertionError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes():
    return {name: sha(ROOT / name) for name in SOURCES}


def read(path, limit=MAX_LOG):
    path = Path(path)
    if not path.exists():
        return b''
    require(path.stat().st_size <= limit, 'owned diagnostic file exceeds bound: ' + path.name)
    return path.read_bytes()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


class RetainedJob(_WindowsJob):
    """_WindowsJob lifetime behavior, assigning only Popen's retained handle.

    The existing constructor accepts a PID and opens it again. This constructor
    deliberately avoids that lookup and runs while this exact child is suspended.
    """
    def __init__(self, process):
        from ctypes import wintypes as W
        self.handle = None

        class Basic(C.Structure):
            _fields_ = [('process_time', C.c_int64), ('job_time', C.c_int64), ('flags', W.DWORD),
                        ('minimum_working_set', C.c_size_t), ('maximum_working_set', C.c_size_t),
                        ('active_processes', W.DWORD), ('affinity', C.c_size_t),
                        ('priority', W.DWORD), ('scheduling', W.DWORD)]

        class IO(C.Structure):
            _fields_ = [(name, C.c_uint64) for name in ('reads','writes','other','read_bytes','write_bytes','other_bytes')]

        class Limits(C.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_memory', C.c_size_t),
                        ('job_memory', C.c_size_t), ('peak_process', C.c_size_t), ('peak_job', C.c_size_t)]

        kernel = C.WinDLL('kernel32', use_last_error=True)
        for name, arguments, result in (
            ('CreateJobObjectW', [C.c_void_p, W.LPCWSTR], W.HANDLE),
            ('SetInformationJobObject', [W.HANDLE, C.c_int, C.c_void_p, W.DWORD], W.BOOL),
            ('AssignProcessToJobObject', [W.HANDLE, W.HANDLE], W.BOOL),
            ('QueryInformationJobObject', [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.c_void_p], W.BOOL),
            ('TerminateJobObject', [W.HANDLE, W.UINT], W.BOOL),
            ('CloseHandle', [W.HANDLE], W.BOOL),
        ):
            function = getattr(kernel, name)
            function.argtypes, function.restype = arguments, result
        self.kernel = kernel
        self.handle = kernel.CreateJobObjectW(None, None)
        require(self.handle, 'CreateJobObject failed')
        try:
            limits = Limits()
            limits.basic.flags = 0x2000
            require(kernel.SetInformationJobObject(self.handle, 9, C.byref(limits), C.sizeof(limits)),
                    'kill-on-close Job limit failed')
            require(kernel.AssignProcessToJobObject(self.handle, C.c_void_p(int(process._handle))),
                    'retained suspended process Job assignment failed')
        except BaseException:
            self.close()
            raise

    def accounting(self):
        class Accounting(C.Structure):
            _fields_ = [('user', C.c_int64), ('kernel', C.c_int64), ('period_user', C.c_int64),
                        ('period_kernel', C.c_int64), ('faults', C.c_uint32), ('total', C.c_uint32),
                        ('active', C.c_uint32), ('terminated', C.c_uint32)]
        value = Accounting()
        require(self.kernel.QueryInformationJobObject(self.handle, 1, C.byref(value), C.sizeof(value), None),
                'owned Job accounting unavailable')
        return {key: int(getattr(value, key)) for key in ('total','active','terminated')}

    def terminate_owned(self):
        require(self.kernel.TerminateJobObject(self.handle, 92), 'owned Job termination failed')


def analyze_log(text, *, pid, profile, launch_tick, practice=False, diagnostic_bindings=False):
    lines = [line for line in text.splitlines()
             if (match := re.match(r'^\[(\d+)\]', line)) and int(match[1]) >= launch_tick]
    text = '\n'.join(lines)
    forbidden = ('Native worker request failed:', 'Native worker shutdown failed:',
                 'Native worker startup refused:', 'Native worker cleanup failed:',
                 'Native Quit probe failed:', 'Local menu initialization failed:',
                 'Offline practice initialization failed:', 'Practice stopped in ', 'LAN audit disabled:')
    require(not any(value in text for value in forbidden), 'native helper reported a transport/lifecycle failure')
    active = re.findall(r'Native worker transport probe active: pid=(\d+) assignedBeforeResume=(\d+) '
                        r'BA_RESURRECTION_NATIVE_WORKER_PROXY_V1; movement prediction is not enabled', text)
    require(len(active) == 1 and int(active[0][1]) == 1 and int(active[0][0]) != pid,
            'one separate Job-owned worker activation required')
    lookups = re.findall(r'Native worker export lookup: name=(\w+) count=(\d+) thread=(\d+)', text)
    expected = SHIPPING_EXPORTS | DIAGNOSTIC_EXPORTS if diagnostic_bindings else SHIPPING_EXPORTS
    require(len(lookups) == len(expected) and {row[0] for row in lookups} == expected and
            [int(row[1]) for row in lookups] == list(range(1, len(expected) + 1)) and
            all(int(row[2]) > 0 for row in lookups),
            'exact original shipping18 export lookups required' if not diagnostic_bindings
            else 'exact shipping18 plus all diagnostic6 export lookups required')
    calls = re.findall(r'Native worker API observed: name=(\w+) thread=(\d+) depth=(\d+) calls=(\d+)', text)
    names = {row[0] for row in calls}
    needed = {'SimSetLogCallBack','SimSetLogFlags','SimInit','SimDestroy'}
    if practice:
        needed |= {'SimCreateWorld','SimDestroyWorld','SimProcessMsg','SimStep',
                   'SimMakeSimFrame','SimGetSimFrameBuffer'}
    require(needed <= names <= set(SIGNATURES) and all(int(row[1]) > 0 and int(row[2]) >= 1 for row in calls),
            'routed native API/caller thread witnesses incomplete')
    closed = re.findall(r'Native worker closed: pid=(\d+) exit=(\d+) natural=(\d+) reaped=(\d+) '
                        r'ioJoined=(\d+) abandoned=(\d+) requests=(\d+) responses=(\d+)', text)
    require(len(closed) == 1, 'one worker shutdown receipt required')
    worker, code, natural, reaped, joined, abandoned, requests, responses = map(int, closed[0])
    require(worker == int(active[0][0]) and code == 0 and natural == reaped == joined == 1 and
            abandoned == 0 and requests == responses and requests > 0,
            'worker did not shut down naturally with complete/reaped I/O')
    require('NATIVE QUIT owned menu verified: profile=' + profile + ' mode=confirm ' in text,
            'fresh owned profile menu Quit witness missing')
    quits = re.findall(r'\[(\d+)\] NATIVE QUIT original confirmation dispatch: thread=(\d+) '
                       r'worldIdle=1 assetLoadingCount=0 naturalExitDeadlineSeconds=60', text)
    require(len(quits) == 1, 'one original native Quit confirmation required')
    require(text.index('Native worker closed:') > text.index('NATIVE QUIT original confirmation dispatch:'),
            'worker must remain alive until the original Quit dispatch')
    if practice:
        returned = 'Practice returned: completed=1 mode=4 seat=-1 presenceRetained=0 standalone=1'
        require(text.count(returned) == 1 and 'Practice native EndOfGameResponse delivered;' in text and
                'PRACTICE SMOKE native Continue (automated)' in text and
                text.index(returned) < text.index('NATIVE QUIT owned menu verified:'),
                'one native practice result/Continue/menu return required')
    return dict(worker_pid=worker, worker_exit_code=code, requests=requests, responses=responses,
                natural_worker_shutdown=True, worker_reaped=True, worker_io_joined=True, worker_io_abandoned=abandoned,
                lookup_names=sorted(row[0] for row in lookups), api_names=sorted(names),
                lookup_policy='explicit-diagnostic24' if diagnostic_bindings else 'shipping-plugin-index1',
                shipping_lookup_names=sorted(SHIPPING_EXPORTS),
                diagnostic_lookup_names=sorted({row[0] for row in lookups} & DIAGNOSTIC_EXPORTS),
                diagnostic_exports_not_exercised=sorted(DIAGNOSTIC_EXPORTS - {row[0] for row in lookups}),
                unity_proxy_caller_tids=sorted({int(row[1]) for row in calls}),
                child_native_api_tids_directly_observed=False,
                quit_tick=int(quits[0][0]), quit_thread=int(quits[0][1]),
                scope='Actual Unity proxy calls plus source-bound single-thread worker transport; no movement prediction')


def practice_artifacts(game, output, pid, tick):
    timing_path = game / 'investigation/runtime' / f'frame-timing-{pid}.tsv'
    raw = read(timing_path)
    require(raw, 'owned frame timing missing')
    rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8')), delimiter='\t'))
    views = [row for row in rows if row['event'] == 'view' and int(row['ms']) >= tick and int(row['presented']) >= 0]
    require(views and max(int(row['presented']) for row in views) >= 1199,
            'original managed presentation counter did not reach1200-frame practice prefix')
    (output / 'frame-timing.tsv').write_bytes(raw)
    audits = list((game / 'investigation/runtime').glob(f'lan-audit-{pid}-*.tsv'))
    require(len(audits) == 1, 'one match-bound owned audit file required')
    raw_audit = read(audits[0])
    samples = list(csv.DictReader(io.StringIO(raw_audit.decode('utf-8')), delimiter='\t'))
    require(samples and all(int(row['pid']) == pid and int(row['thread']) > 0 for row in samples) and
            {int(row['viewer']) for row in samples} == {0, 1} and
            all(max(int(row['frame']) for row in samples if int(row['viewer']) == viewer) >= 1199
                for viewer in (0, 1)), 'both worker-routed observable-state views must reach the native prefix')
    (output / 'lan-audit.tsv').write_bytes(raw_audit)
    return dict(managed_counter_samples=len(views), max_presented=max(int(row['presented']) for row in views),
                distinct_presented=len({int(row['presented']) for row in views}),
                audit_samples=len(samples), audit_viewers=[0, 1], audit_file=audits[0].name,
                timing_sha256=sha(timing_path), audit_sha256=sha(audits[0]),
                scope='Original managed presented counter and sampled native views; no render pixels or full-prefix parity')


def profile_hashes(folder):
    result = {}
    if folder.exists():
        for path in folder.rglob('*'):
            if path.is_file():
                require(path.resolve().is_relative_to(folder.resolve()), 'owned profile has an external link')
                require(len(result) < 256 and path.stat().st_size <= 8 * 1024 * 1024, 'owned profile exceeds bound')
                result[path.relative_to(folder).as_posix()] = sha(path)
    return result


def quit_trace_evidence(raw, *, pid, launch_tick, transport):
    rows = [json.loads(line) for line in raw.splitlines()]
    require(rows and rows[0]['event'] == 'armed' and all(row['pid'] == pid and
            row['tick'] >= launch_tick and type(row['thread']) is int for row in rows) and
            all(a['tick'] <= b['tick'] for a, b in zip(rows, rows[1:])), 'owned Quit trace identity/order invalid')
    confirms = [row for row in rows if row['event'] == 'OnConfirm.dispatch']
    returned = [row for row in rows if row['event'] == 'OnConfirm.return']
    require(len(confirms) == 1 and confirms[0]['thread'] == transport['quit_thread'] and
            len(returned) == 1 and returned[0]['thread'] == confirms[0]['thread'] and
            # mark() writes/flushes first, log() samples its own later tick,
            # then the original callback runs and mark(return) samples again.
            confirms[0]['tick'] <= transport['quit_tick'] <= returned[0]['tick'] and
            not any(row['event'] in ('probe.failed','OnConfirm.exception') for row in rows),
            'original native Quit trace witness differs')
    return rows


def child_derivation_evidence(data, game):
    from tools.prepare_prediction_native import SUPPORTED_ORIGINAL_SHA256, HEAP_IAT_RVAS
    manifests = list(data.glob('native-worker-*/Simulation.derivation.json'))
    require(len(manifests) == 1, 'one actual child derivation manifest required')
    child = json.loads(read(manifests[0], MAX_LOG))
    original, derived = Path(child['original']).resolve(), Path(child['output']).resolve()
    require(original.is_relative_to(game) and derived.is_relative_to(data) and
            child['original_sha256'] == SUPPORTED_ORIGINAL_SHA256 == sha(original) and
            child['derived_sha256'] == sha(derived) and child['heap_iat_rvas'] == HEAP_IAT_RVAS,
            'actual child source/derived native DLL binding differs')
    return dict(manifest=str(manifests[0]), manifest_sha256=sha(manifests[0]),
                original_sha256=child['original_sha256'], derived_sha256=child['derived_sha256'])


def reanalyze(run_dir, target):
    """Check recorded menu evidence only; preserve the failed report verbatim.

    This correction is deliberately specific to the retained24-vs18 assertion.
    It cannot excuse any other runtime error, source change or forced cleanup.
    """
    run_dir, target = Path(run_dir).resolve(), Path(target).resolve()
    require(run_dir.is_relative_to(ROOT / 'local') and target.is_relative_to(ROOT / 'local') and
            not os.path.lexists(target), 'fresh ignored reanalysis report required')
    failed_path = run_dir / 'verification.json'
    failed_sha = sha(failed_path)
    old = json.loads(read(failed_path))
    require(old.get('passed') is False and old.get('practice') is False and
            old.get('error') == "AssertionError('exact24 original managed export lookups required')",
            'reanalysis only corrects the retained menu shipping-binding assertion')
    original_tool = run_dir / 'source-at-run/verify_prediction_client_worker.py'
    preservation = json.loads(read(run_dir / 'source-at-run/preservation.json'))
    require(preservation['failed_verification_sha256'] == failed_sha and
            preservation['verifier_sha256'] == sha(original_tool), 'preserved failed report/source changed')
    require(sha(original_tool) == old['source_sha256_at_start']['tools/verify_prediction_client_worker.py'] and
            old['source_sha256_at_start'] == old['source_sha256_at_end'] and old['source_unchanged'] is True,
            'original verifier/runtime source identity is not preserved')
    require(old['exit_code'] == 0 and old['game_reaped'] is True and old['forced_cleanup'] is False and
            old['game_assigned_before_resume'] is True and old['retained_process_handle_used'] is True and
            old['retained_game_handle_closed'] is True and old['job_handle_closed'] is True and
            old['cleanup_errors'] == [] and old['job_before_close']['active'] == 0 and
            old['job_before_close']['terminated'] == 0, 'recorded game/Job exit was not natural and complete')
    for name, expected in old['source_sha256_at_start'].items():
        if name != 'tools/verify_prediction_client_worker.py':
            require(sha(ROOT / name) == expected, 'runtime source differs from recorded run: ' + name)
    for name, info in old['files'].items():
        require(info['sha256'] == old['files_at_end'][name] == sha(info['path']),
                'recorded/current binary identity differs: ' + name)
    game = Path(old['game']).resolve()
    require(game.is_relative_to(ROOT / 'local') and
            sha(game / '.battleaces-resurrection/patch-manifest.json') == old['patch_manifest_sha256'],
            'owned game/manifest identity differs')
    for name, info in old['helpers'].items():
        path, receipt = helper_receipt(info['path'], arena=name == 'heap_helper')
        require(sha(path) == info['sha256'] and receipt == info['receipt'] and
                sha(path.with_name('build.json')) == info['receipt_sha256'], 'recorded helper receipt differs')
    profile = game / '.battleaces-resurrection/profiles' / old['profile']
    require(profile_hashes(profile) == old['owned_profile_sha256'], 'owned profile changed after recorded run')
    transport = analyze_log(read(run_dir / 'native.log').decode('utf-8'), pid=old['pid'],
                            profile=old['profile'], launch_tick=old['launch_tick'])
    require(0 <= old['observed_exit_tick'] - transport['quit_tick'] < 60000,
            'recorded original Quit did not precede natural exit within60s')
    trace = quit_trace_evidence(read(run_dir / 'quit-trace.jsonl', 64 * 1024), pid=old['pid'],
                               launch_tick=old['launch_tick'], transport=transport)
    proof_path = ROOT / 'local/prediction-checkpoint-20261109/shipping-simulation-bindings.json'
    proof = json.loads(read(proof_path))
    require(set(proof['shipping18']) == SHIPPING_EXPORTS and set(proof['diagnostic6']) == DIAGNOSTIC_EXPORTS and
            all(('Uncapped.SimReleaseDebugOnlyAttribute' in row['attributes']) ==
                (row['native_export'] in DIAGNOSTIC_EXPORTS) for row in proof['fields']),
            'independent original field-attribute proof differs')
    report = dict(passed=True, native_launched=False, scope='Recorded menu transport reanalysis only; no practice/prediction claim',
                  corrected_assertion='Original PluginIdx1 selects18 shipping fields; six SimReleaseDebugOnly fields are filtered',
                  original_failed_report=str(failed_path), original_failed_report_sha256=failed_sha,
                  original_verifier_sha256=sha(original_tool), analyzer_sha256=sha(__file__),
                  runtime_source_sha256=old['source_sha256_at_start'],
                  runtime_sources_still_match=True, source_unchanged_during_recorded_run=True,
                  files=old['files'], helpers=old['helpers'], game=str(game), profile=old['profile'],
                  pid=old['pid'], exit_code=old['exit_code'], natural_game_exit=True, forced_cleanup=False,
                  game_reaped=True, job_before_close=old['job_before_close'], transport=transport,
                  quit_trace=trace, child_native_derivation=child_derivation_evidence(run_dir / 'worker-data', game),
                  original_field_filter_evidence=dict(path=str(proof_path), sha256=sha(proof_path),
                    original_gameassembly_sha256=proof['original_gameassembly_sha256'], metadata_sha256=proof['metadata_sha256']),
                  input_sha256={name:sha(run_dir / name) for name in
                                ('verification.json','process.json','native.log','quit-trace.jsonl','game.log','stdout.log','stderr.log')})
    require(sha(failed_path) == failed_sha, 'failed source report changed during reanalysis')
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False);stream.write('\n')
    return report


def run(args):
    game, output = args.game.resolve(), args.output.resolve()
    require(os.name == 'nt' and game.is_relative_to(ROOT / 'local') and output.is_relative_to(ROOT / 'local'),
            'owned ignored Windows game/output paths required')
    require(not os.path.lexists(args.output), 'output must be fresh before any writes')
    require(30 <= args.timeout <= 120 and args.module_root.resolve() == ROOT, 'bounded timeout and this module root required')
    for value in (args.expected_helper_sha256, args.expected_gameassembly_sha256):
        require(re.fullmatch('[0-9a-f]{64}', value), 'explicit lowercase SHA256 required')
    paths = dict(game_exe=game / 'Battle Aces.exe', helper=game / 'BattleAcesOffline.dll',
                 gameassembly=game / 'GameAssembly.dll', python=args.python.resolve())
    identities = {name: dict(path=str(path), sha256=sha(path)) for name, path in paths.items()}
    require(identities['helper']['sha256'] == args.expected_helper_sha256 and
            identities['gameassembly']['sha256'] == args.expected_gameassembly_sha256,
            'owned installed helper/GameAssembly differs from explicit identities')
    manifest_path = game / '.battleaces-resurrection/patch-manifest.json'
    manifest = json.loads(read(manifest_path, 4 * 1024 * 1024))
    require(any(row.get('name') == 'OfflinePredictionGetProcAddress' and row.get('rva') == 0x379d260
                for row in manifest.get('call_hooks', [])), 'owned GameAssembly lacks explicit worker probe CALL hook')
    helpers = {}
    for name in ('heap_helper','cooperative'):
        path, receipt = helper_receipt(getattr(args, name), arena=name == 'heap_helper')
        helpers[name] = dict(path=str(path), sha256=sha(path), receipt=receipt,
                             receipt_sha256=sha(path.with_name('build.json')))
    profile = 'nativestest_pw_' + secrets.token_hex(6)
    profile_dir = game / '.battleaces-resurrection/profiles' / profile
    require(not profile_dir.exists(), 'fresh independent owned profile required')
    output.mkdir(parents=True, exist_ok=False)
    data = output / 'worker-data';data.mkdir()
    command = [str(paths['game_exe']), '-offline-practice', '-practice-ai-experimental', '-local-profile=' + profile,
               '-player-name=WorkerProbe', '-native-quit-smoke', '-native-quit-mode=confirm',
               '-screen-fullscreen', '0', '-screen-width', '960', '-screen-height', '540',
               '-logFile', str(output / 'game.log'), '-prediction-native-worker-probe',
               '-prediction-worker-python=' + str(paths['python']), '-prediction-worker-module-root=' + str(ROOT),
               '-prediction-worker-heap-helper=' + helpers['heap_helper']['path'],
               '-prediction-worker-cooperative=' + helpers['cooperative']['path'],
               '-prediction-worker-data-dir=' + str(data)]
    if args.practice:
        command += ['-practice-ai-smoke', '-practice-ai-smoke-matches=1', '-practice-ai-smoke-frames=1200',
                    '-native-quit-after-practice', '-lan-smoke', '-lan-audit']
    report = dict(passed=False, scope=__doc__, practice=args.practice, command=command,
                  game=str(game), output=str(output), profile=profile, files=identities,
                  helpers=helpers, patch_manifest_sha256=sha(manifest_path),
                  source_sha256_at_start=source_hashes(), natural_game_exit=False, forced_cleanup=False,
                  game_assigned_before_resume=False, retained_process_handle_used=True)
    process = job = None
    clock = C.WinDLL('kernel32').GetTickCount64;clock.restype = C.c_uint64
    native_log = trace_path = None
    started = time.monotonic()
    try:
        info = subprocess.STARTUPINFO();info.dwFlags |= subprocess.STARTF_USESHOWWINDOW;info.wShowWindow = 0
        report['launch_tick'] = int(clock())
        with (output / 'stdout.log').open('wb') as stdout, (output / 'stderr.log').open('wb') as stderr:
            process = subprocess.Popen(command, cwd=game, startupinfo=info, stdout=stdout, stderr=stderr,
                                       close_fds=True, creationflags=CREATE_SUSPENDED | subprocess.CREATE_NO_WINDOW)
            report['pid'] = process.pid
            native_log = game / 'investigation/runtime' / f'dedicated-native-{process.pid}.log'
            trace_path = profile_dir / 'quit-trace.jsonl'
            require(not native_log.exists() and not trace_path.exists(), 'owned PID/profile diagnostic paths are not fresh')
            job = RetainedJob(process)
            report['game_assigned_before_resume'] = True
            ntdll = C.WinDLL('ntdll', use_last_error=True)
            ntdll.NtResumeProcess.argtypes, ntdll.NtResumeProcess.restype = [C.c_void_p], C.c_long
            require(ntdll.NtResumeProcess(C.c_void_p(int(process._handle))) == 0, 'retained owned process resume failed')
            report['resume_tick'] = int(clock());write(output / 'process.json', report)
            while process.poll() is None:
                require(time.monotonic() - started < args.timeout, 'owned game deadline exceeded')
                text = read(native_log).decode('utf-8', errors='strict')
                require(not any(value in text for value in ('Native worker startup refused:', 'Native worker request failed:',
                                                            'Native Quit probe failed:', 'Practice stopped in ')),
                        'owned native helper reported failure')
                time.sleep(0.1)
            process.wait(timeout=1)
        report['exit_code'] = process.returncode
        report['observed_exit_tick'] = int(clock())
        report['natural_game_exit'] = process.returncode == 0 and not report['forced_cleanup']
        require(process.returncode == 0, 'original game did not exit naturally with code0')
        text = read(native_log).decode('utf-8', errors='strict')
        report['transport'] = analyze_log(text, pid=process.pid, profile=profile,
                                          launch_tick=report['launch_tick'], practice=args.practice)
        require(0 <= report['observed_exit_tick'] - report['transport']['quit_tick'] < 60000,
                'native game exit did not follow original confirmation within60s')
        rows = quit_trace_evidence(read(trace_path, 64 * 1024), pid=process.pid,
                                   launch_tick=report['launch_tick'], transport=report['transport'])
        report['quit_trace'] = rows
        if args.practice:
            report['practice_evidence'] = practice_artifacts(game, output, process.pid, report['launch_tick'])
        report['child_native_derivation'] = child_derivation_evidence(data, game)
        deadline = time.monotonic() + 5
        while job.accounting()['active'] and time.monotonic() < deadline:
            time.sleep(0.05)
        report['job_after_natural_exit'] = job.accounting()
        require(report['job_after_natural_exit']['active'] == report['job_after_natural_exit']['terminated'] == 0,
                'owned descendants did not all exit naturally')
        report['natural_game_exit'] = True
        report['passed'] = True
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        cleanup_errors = []
        if process is not None:
            if process.poll() is None:
                report['forced_cleanup'] = True
                try:
                    if job is not None:
                        job.terminate_owned()
                    else:
                        process.terminate()  # Popen retains this exact suspended child's handle.
                except BaseException as error:
                    cleanup_errors.append('owned termination: ' + repr(error))
            try:
                process.wait(timeout=10)
                report['game_reaped'] = True;report['exit_code'] = process.returncode
            except subprocess.TimeoutExpired:
                report['game_reaped'] = False
        if job is not None:
            try:
                report['job_before_close'] = job.accounting()
                if report['job_before_close']['active']:
                    report['forced_cleanup'] = True
                job.close();report['job_handle_closed'] = True
            except BaseException as error:
                cleanup_errors.append('Job cleanup: ' + repr(error))
        if process is not None:
            if not report.get('game_reaped'):
                try:
                    process.wait(timeout=5);report['game_reaped'] = True;report['exit_code'] = process.returncode
                except BaseException as error:
                    cleanup_errors.append('owned process reap: ' + repr(error))
            process._handle.Close();report['retained_game_handle_closed'] = True
        for path, target, limit in ((native_log,'native.log',MAX_LOG),(trace_path,'quit-trace.jsonl',64*1024)):
            try:
                if path and path.exists():(output / target).write_bytes(read(path,limit))
            except BaseException as error:
                cleanup_errors.append(target + ': ' + repr(error))
        try:
            report['owned_profile_sha256'] = profile_hashes(profile_dir)
            report['source_sha256_at_end'] = source_hashes()
            report['files_at_end'] = {name: sha(path) for name, path in paths.items()}
            report['source_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_end']
            report['game_files_unchanged'] = all(report['files_at_end'][name] == value['sha256']
                                                  for name, value in identities.items())
        except BaseException as error:
            cleanup_errors.append('final identity capture: ' + repr(error))
        report['cleanup_errors'] = cleanup_errors
        report['natural_game_exit'] = bool(report.get('exit_code') == 0 and report.get('game_reaped') and
                                          not report['forced_cleanup'])
        report['passed'] = bool(report['passed'] and report.get('source_unchanged') and report.get('game_files_unchanged') and
                                not report['forced_cleanup'] and report.get('game_reaped') and not cleanup_errors)
        report['elapsed_seconds'] = time.monotonic() - started
        write(output / 'verification.json', report)
    return report


def self_test():
    profile='nativestest_pw_authored';lines=[
        '[100] Native worker transport probe active: pid=2 assignedBeforeResume=1 BA_RESURRECTION_NATIVE_WORKER_PROXY_V1; movement prediction is not enabled']
    lines += [f'[101] Native worker export lookup: name={name} count={index} thread=7'
              for index, name in enumerate(sorted(SHIPPING_EXPORTS), 1)]
    lines += [f'[102] Native worker API observed: name={name} thread=7 depth=1 calls={index}'
              for index, name in enumerate(('SimSetLogCallBack','SimSetLogFlags','SimInit','SimDestroy'),1)]
    lines += [f'[104] NATIVE QUIT owned menu verified: profile={profile} mode=confirm navigationCount=0',
              '[105] NATIVE QUIT original confirmation dispatch: thread=7 worldIdle=1 assetLoadingCount=0 naturalExitDeadlineSeconds=60',
              '[106] Native worker closed: pid=2 exit=0 natural=1 reaped=1 ioJoined=1 abandoned=0 requests=7 responses=7']
    good='\n'.join(lines)
    analyze_log(good,pid=1,profile=profile,launch_tick=100)
    invalid = [good.replace('natural=1','natural=0'),good.replace('reaped=1','reaped=0'),
               good.replace('ioJoined=1','ioJoined=0'),good.replace('abandoned=0','abandoned=1'),
               good.replace('responses=7','responses=6'),good.replace('assignedBeforeResume=1','assignedBeforeResume=0'),
               good.replace('pid=2 exit=0','pid=3 exit=0'),good.replace('name=SimInit ','name=Unknown '),
               '\n'.join(lines[:1]+lines[2:])]
    # Every required field is independently required; duplicates cannot hide a
    # missing field, and optional diagnostic names are never a shipping subset.
    for name in SHIPPING_EXPORTS:
        invalid.append('\n'.join(line for line in lines if f'export lookup: name={name} ' not in line))
        other=next(value for value in SHIPPING_EXPORTS if value!=name)
        invalid.append(good.replace(f'export lookup: name={name} ',f'export lookup: name={other} '))
    for name in DIAGNOSTIC_EXPORTS | {'UnknownExport'}:
        invalid.append(good+'\n'+f'[107] Native worker export lookup: name={name} count=19 thread=7')
    full_lines=[lines[0]]+[f'[101] Native worker export lookup: name={name} count={index} thread=7'
                           for index,name in enumerate(sorted(SIGNATURES),1)]+lines[19:]
    full='\n'.join(full_lines)
    analyze_log(full,pid=1,profile=profile,launch_tick=100,diagnostic_bindings=True)
    invalid.append(full)  # A complete diagnostic set still needs explicit mode.
    # The nominal menu witness must never qualify a practice prefix.
    for text in invalid:
        try:
            analyze_log(text,pid=1,profile=profile,launch_tick=100)
        except AssertionError:
            continue
        raise AssertionError('authored failed transport receipt accepted')
    trace=[dict(pid=1,thread=7,tick=100,event='armed'),
           dict(pid=1,thread=7,tick=104,event='OnConfirm.dispatch'),
           dict(pid=1,thread=7,tick=106,event='OnConfirm.return')]
    transport=analyze_log(good,pid=1,profile=profile,launch_tick=100)
    quit_trace_evidence('\n'.join(json.dumps(row) for row in trace).encode(),pid=1,launch_tick=100,transport=transport)
    bad_traces=[trace[:-1]+[dict(trace[-1],tick=104)],
                trace[:-1]+[dict(trace[-1],thread=8)],trace+[trace[1]]]
    for rows in bad_traces:
        try:
            quit_trace_evidence('\n'.join(json.dumps(row) for row in rows).encode(),pid=1,launch_tick=100,transport=transport)
        except AssertionError:
            continue
        raise AssertionError('authored failed Quit boundary accepted')
    try:
        analyze_log(good,pid=1,profile=profile,launch_tick=100,practice=True)
    except AssertionError:
        return dict(passed=True,native_launched=False,cases=len(invalid)+7)
    raise AssertionError('menu witness accepted as practice')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--expected-helper-sha256');parser.add_argument('--expected-gameassembly-sha256')
    parser.add_argument('--python',type=Path);parser.add_argument('--module-root',type=Path)
    parser.add_argument('--heap-helper',type=Path);parser.add_argument('--cooperative',type=Path)
    parser.add_argument('--practice',action='store_true');parser.add_argument('--timeout',type=float,default=120)
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--reanalyze',type=Path,help='Reanalyze preserved menu01 evidence without launching')
    parser.add_argument('--reanalysis-output',type=Path,help='Fresh separate JSON result for --reanalyze')
    args=parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test()));return 0
    if args.reanalyze:
        if args.reanalysis_output is None:parser.error('--reanalysis-output is required for --reanalyze')
        report=reanalyze(args.reanalyze,args.reanalysis_output)
        print(json.dumps({key:report.get(key) for key in ('passed','native_launched','natural_game_exit','pid')},indent=2))
        return 0 if report['passed'] else 1
    for name in ('game','output','expected_helper_sha256','expected_gameassembly_sha256','python','module_root','heap_helper','cooperative'):
        if getattr(args,name) is None:parser.error('--'+name.replace('_','-')+' is required')
    report=run(args)
    print(json.dumps({key:report.get(key) for key in ('passed','output','pid','natural_game_exit','forced_cleanup','error')},indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
