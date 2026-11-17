"""Task-owned Linux systemd cpuset experiments for retained Wine worker replays.

This pins the entire task unit (coordinator, guardian and Wine descendants), not
only the Windows worker. It neither changes shared ancestor policies nor models
a host-wide vCPU allocation. Native execution is an explicit later operation.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import traceback
from types import SimpleNamespace
import uuid

from tools import benchmark_large_armies as b
from tools import capture_snapshot_corpus as c
from tools import summarize_worker_timing as s
from tools import verify_rust_worker as w
from tools import verify_rust_worker_profile as v

ROOT = b.ROOT
SYSTEMCTL = '/usr/bin/systemctl'
SYSTEMD_RUN = '/usr/bin/systemd-run'
BOOTSTRAP = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('tools.benchmark_wine_cpu',run_name='__main__')"
UNIT_RE = re.compile(r'ba-cpu-bench-[0-9a-f]{32}\.service\Z')
PROPERTIES = ('Id', 'Description', 'LoadState', 'ActiveState', 'InvocationID', 'ControlGroup',
              'Result', 'ExecMainCode', 'ExecMainStatus')


def sources():
    names = ('tools/benchmark_wine_cpu.py', 'tools/verify_rust_worker_profile.py')
    return {**w.sources(), **{name: b.digest((ROOT/name).read_bytes()) for name in names}}


def cpus(text):
    b.require(type(text) is str and len(text) <= 65536 and text.strip(), 'CPU list missing/unbounded')
    result = set()
    for token in text.strip().split(','):
        b.require(re.fullmatch(r'[0-9]+(?:-[0-9]+)?', token) is not None, 'invalid CPU list')
        bounds = [int(value) for value in token.split('-')]
        first, last = bounds[0], bounds[-1]
        b.require(0 <= first <= last < 65536, 'CPU range outside bound')
        values = set(range(first, last+1))
        b.require(not result & values, 'duplicate CPU list entries')
        result.update(values)
    return result


def cpu_text(values):
    b.require(values and all(type(value) is int and 0 <= value < 65536 for value in values), 'invalid CPU IDs')
    return ','.join(str(value) for value in sorted(set(values)))


def topology(cpu_root=Path('/sys/devices/system/cpu'), allowed=None):
    online = cpus((cpu_root/'online').read_text())
    allowed = set(os.sched_getaffinity(0) if allowed is None else allowed)
    b.require(allowed and allowed <= online, 'allowed CPUs must be online')
    rows, groups = [], {}
    for cpu in sorted(online):
        directory = cpu_root/f'cpu{cpu}'/'topology'
        package = int((directory/'physical_package_id').read_text())
        core = int((directory/'core_id').read_text())
        siblings = cpus((directory/'thread_siblings_list').read_text())
        b.require(package >= 0 and core >= 0 and cpu in siblings, 'physical topology unavailable')
        rows.append(dict(cpu=cpu, package=package, core=core, thread_siblings=sorted(siblings)))
        groups.setdefault((package, core), []).append(cpu)
    for row in rows:
        b.require(set(groups[(row['package'], row['core'])]) == set(row['thread_siblings']) & online,
                  'inconsistent SMT/physical core topology')
    selected = [min(set(group) & allowed) for _, group in sorted(groups.items()) if set(group) & allowed]
    b.require(len(selected) >= 2, 'two distinct allowed OS-reported physical cores required')
    return dict(source='Linux sysfs package/core IDs and thread_siblings_list', online=sorted(online),
                allowed=sorted(allowed), rows=rows, selected_cpus=selected[:2],
                scope='OS-reported topology; physical hardware dedication/virtual CPU mapping is not established')


def schedule():
    return [(pair, count, False) for pair in range(3)
            for count in ((1, 2) if pair % 2 == 0 else (2, 1))] + [(3, 1, True), (3, 2, True)]


def template_inventory(directory):
    """Bind a private template without following its required Z: root symlink."""
    result, total = {}, 0
    for parent, directories, files in os.walk(directory, followlinks=False):
        for name in sorted(directories+files):
            path = Path(parent)/name
            relative = path.relative_to(directory).as_posix()
            b.require(len(result) < 100000, 'prefix template entry bound exceeded')
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                result[relative] = dict(symlink=os.readlink(path))
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
                b.require(total <= 2*1024**3, 'prefix template byte bound exceeded')
                result[relative] = dict(bytes=info.st_size, sha256=b.digest(w.read_file(path, 128*1024*1024)))
            else:
                b.require(stat.S_ISDIR(info.st_mode), 'unsupported prefix template entry')
    return result


def profile_summary(directory, control, receipt, control_receipt):
    """Strict attribution plus matched control across two distinct owned units."""
    result = s.summarize(directory)
    observed, ordinary = s.load_benchmark(directory), s.load_benchmark(control)
    profile_report, control_report = observed['report'], ordinary['report']
    b.require(control_report.get('profiled') is False, 'CPU profile control must be unprofiled')
    for key in ('source_at_start', 'worker_runtime', 'snapshot_decoder', 'bootstrap_sha256', 'simulation_sha256',
                'asset_manifest_sha256', 'input_journal_sha256', 'frames', 'ai', 'workload', 'paced', 'timestep_ms'):
        b.require(profile_report.get(key) == control_report.get(key), 'CPU profile/control '+key+' differs')
    backends = []
    for report, unit in ((profile_report, receipt), (control_report, control_receipt)):
        backend = dict(report['backend'])
        b.require(backend.get('cgroup_parent') == str(Path(unit['precreate_cpuset']['path'])/'coordinator'),
                  'CPU profile/control cgroup is not its verified task-unit coordinator')
        backend.pop('cgroup_parent')
        backend.pop('wine_version_probe_ms', None)
        backends.append(backend)
    b.require(backends[0] == backends[1], 'CPU profile/control backend identity differs')
    b.require(len(observed['rows']) == len(ordinary['rows']) and all(
        all(actual[key] == expected[key] for key in ('frame', 'phase', 'input_sha256', 'state_sha256'))
        for actual, expected in zip(observed['rows'], ordinary['rows'])), 'CPU profile/control frame identity differs')
    result['control'] = dict(exact_input_and_observable_state_match=True,
        exact_runtime_and_decoder_identity_match=True,
        declared_identity_difference='fresh owned task-unit cgroup_parent; both bound to their own pre-CREATE receipt',
        profiled_cgroup_parent=profile_report['backend']['cgroup_parent'],
        control_cgroup_parent=control_report['backend']['cgroup_parent'],
        phases={phase: dict(profiled_rpc_ms=b.summary([row['step_rpc_ms'] for row in observed['rows'] if row['phase'] == phase]),
                            control_rpc_ms=b.summary([row['step_rpc_ms'] for row in ordinary['rows'] if row['phase'] == phase]))
                for phase in ('setup', 'movement', 'combat')})
    return result


async def stop_client(process, *, drain=False):
    """Bound cleanup of our retained systemd client, never its task service."""
    for action, seconds in (('terminate', 2), ('kill', 3)):
        if process.returncode is not None:
            return
        try:
            getattr(process, action)()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.communicate() if drain else process.wait(), seconds)
            return
        except TimeoutError:
            continue
    raise TimeoutError('owned systemd client did not exit after bounded termination')


async def command(argv, *, timeout=15):
    process = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        # This is only our short-lived systemctl client, never a game/Wine PID.
        await stop_client(process, drain=True)
        raise
    b.require(len(stdout) <= 65536 and len(stderr) <= 65536, 'systemd query output exceeds bound')
    return process.returncode, stdout.decode('utf-8', 'strict'), stderr.decode('utf-8', 'strict')


async def unit_state(unit):
    b.require(UNIT_RE.fullmatch(unit) is not None, 'invalid task unit name')
    code, stdout, stderr = await command([SYSTEMCTL, 'show', unit, '--no-pager',
                                         *['--property='+name for name in PROPERTIES]])
    values = dict(line.split('=', 1) for line in stdout.splitlines() if '=' in line)
    b.require(values.get('LoadState') == 'not-found' or code == 0, 'cannot inspect task unit: '+stderr)
    return values


def description(nonce):
    b.require(re.fullmatch(r'[0-9a-f]{32}', nonce) is not None, 'invalid unit nonce')
    return 'BattleAces owned CPU benchmark '+nonce


def verify_identity(state, unit, nonce, invocation=None):
    b.require(state.get('Id') == unit and state.get('Description') == description(nonce)
              and state.get('LoadState') == 'loaded'
              and re.fullmatch(r'[0-9a-f]{32}', state.get('InvocationID', '')) is not None,
              'task unit ownership identity differs')
    b.require(invocation is None or state['InvocationID'] == invocation, 'task unit invocation changed')
    control = PurePosixPath(state.get('ControlGroup', ''))
    b.require(control.is_absolute() and '..' not in control.parts and control.name == unit,
              'task unit ControlGroup identity differs')
    return state


def launch_argv(unit, nonce, selected, request_path, request_sha256, timeout):
    b.require(UNIT_RE.fullmatch(unit) is not None and unit == 'ba-cpu-bench-'+nonce+'.service', 'unit/nonce differ')
    b.require(type(timeout) in (int, float) and 30 <= timeout <= 1800, 'arm timeout outside bound')
    b.require(Path(request_path).is_absolute() and s.valid_sha(request_sha256), 'absolute hash-bound request required')
    properties = dict(Type='exec', Delegate='yes', DelegateSubgroup='coordinator', KillMode='control-group',
        RuntimeMaxSec=str(int(timeout)+90), TimeoutStopSec='15', Restart='no', UMask='0077',
        AllowedCPUs=cpu_text(selected), WorkingDirectory=str(ROOT), User=str(os.getuid()), Group=str(os.getgid()))
    return [SYSTEMD_RUN, '--unit='+unit, '--description='+description(nonce), '--wait', '--pipe',
            *['--property='+key+'='+value for key, value in properties.items()],
            '--setenv=BA_CPU_BENCH_UNIT='+unit, '--setenv=BA_CPU_BENCH_NONCE='+nonce,
            str(Path(sys.executable).resolve()), '-I', '-S', '-B', '-u', '-c', BOOTSTRAP, str(ROOT),
            '--inner-request', str(request_path), '--request-sha256', request_sha256]


def fd_text(fd, name):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    try:
        raw = os.read(descriptor, 65537)
        b.require(len(raw) <= 65536, 'cgroup field exceeds bound')
        return raw.decode('ascii').strip()
    finally:
        os.close(descriptor)


class UnitCpuset:
    """Retained task-unit cgroup identity and inherited hard cpuset evidence."""
    def __init__(self, path, selected, control_group):
        self.path, self.selected, self.control_group = Path(path), set(selected), control_group
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(self.fd)
        self.identity = (info.st_dev, info.st_ino)
        try:
            self.verify()
        except BaseException:
            self.close()
            raise

    def verify(self):
        info = self.path.lstat()
        b.require((info.st_dev, info.st_ino) == self.identity and stat.S_ISDIR(info.st_mode),
                  'retained task cgroup path identity changed')
        actual = cpus(fd_text(self.fd, 'cpuset.cpus.effective'))
        b.require(actual == self.selected, 'task unit effective hard cpuset differs')
        return dict(effective_cpus=sorted(actual), path=str(self.path), device=self.identity[0],
                    inode=self.identity[1], cpu_max=fd_text(self.fd, 'cpu.max'),
                    cpu_stat=fd_text(self.fd, 'cpu.stat'), pressure=fd_text(self.fd, 'cpu.pressure'))

    def ancestor_limits(self):
        """Read inherited limits; the task's cpu.max alone cannot reveal them."""
        result = []
        for path in self.path.parents:
            if not (path/'cgroup.controllers').is_file():
                break
            entry = dict(path=str(path))
            for name in ('cpu.max', 'cpuset.cpus.effective'):
                try:
                    entry[name] = (path/name).read_text().strip()
                except OSError as error:
                    entry[name+'_unavailable'] = repr(error)
            result.append(entry)
            b.require(len(result) <= 64, 'cgroup ancestor depth exceeds bound')
        return result

    def owned_worker(self, worker):
        self.verify()
        owner = worker._backend_owner
        b.require(owner is not None and owner.process.poll() is None and owner.cgroup._same(),
                  'retained Wine worker ownership unavailable')
        group = owner.cgroup
        b.require(group.fd is not None and group.path.is_relative_to(self.path)
                  and group.path != self.path, 'Wine cgroup escaped task unit')
        expected_prefix = str(PurePosixPath(self.control_group)/group.path.relative_to(self.path).as_posix())
        observations = []

        def visit(fd, relative):
            b.require(len(observations) < 4096, 'owned cgroup tree exceeds bound')
            # A nested cgroup without this controller interface inherits the
            # nearest hard cpuset; unit verification supplies that upper bound.
            try:
                effective = sorted(cpus(fd_text(fd, 'cpuset.cpus.effective')))
            except FileNotFoundError:
                effective = None
            b.require(effective is None or set(effective) == self.selected, 'owned descendant cpuset differs')
            members = fd_text(fd, 'cgroup.procs').split()
            threads, exited = [], []
            b.require(len(members) <= 4096, 'owned process list exceeds bound')
            for member in members:
                b.require(member.isdecimal() and int(member) > 0, 'invalid owned cgroup member')
                process = Path('/proc')/member
                try:
                    entries = list((process/'task').iterdir())
                    b.require(len(entries) <= 4096, 'owned thread list exceeds bound')
                    membership = (process/'cgroup').read_text().strip()
                    b.require(membership == '0::'+expected_prefix+relative,
                              'observed process no longer belongs to retained owned cgroup')
                    for task in entries:
                        status = task.joinpath('status').read_text()
                        values = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
                        mask = cpus(values.get('Cpus_allowed_list', '').strip())
                        b.require(mask == self.selected, 'owned Wine thread effective CPU mask differs')
                        threads.append(dict(pid=int(member), tid=int(task.name), allowed=sorted(mask)))
                except FileNotFoundError:
                    exited.append(int(member))
            observations.append(dict(relative=relative, effective_cpuset=effective,
                inherited_from_task_unit=effective is None, threads=threads, exited_during_observation=exited))
            with os.scandir(fd) as entries:
                children = sorted(entry.name for entry in entries if entry.is_dir(follow_symlinks=False))
            for name in children:
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    visit(child, relative+'/'+name)
                finally:
                    os.close(child)
        visit(group.fd, '')
        b.require(any(row['threads'] for row in observations), 'no live owned Wine thread observed')
        return dict(path=str(group.path), observations=observations, unit=self.verify())

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


async def precreate_unit(request):
    unit, nonce = request['unit'], request['nonce']
    b.require(os.environ.get('BA_CPU_BENCH_UNIT') == unit and os.environ.get('BA_CPU_BENCH_NONCE') == nonce,
              'task unit environment nonce differs')
    state = verify_identity(await unit_state(unit), unit, nonce, os.environ.get('INVOCATION_ID', ''))
    membership = Path('/proc/self/cgroup').read_text().strip()
    b.require(membership == '0::'+state['ControlGroup']+'/coordinator',
              'coordinator is not in the exact delegated task subgroup')
    from server.wine_worker_cgroup import current_cgroup
    current = current_cgroup()
    b.require(current.name == 'coordinator' and current.parent.name == unit, 'task cgroup mount binding differs')
    handle = UnitCpuset(current.parent, request['cpus'], state['ControlGroup'])
    try:
        b.require(set(os.sched_getaffinity(0)) == set(request['cpus']), 'coordinator actual CPU mask differs')
        return handle, dict(identity=state, precreate_cpuset=handle.verify(), before_wine_launch=True,
                            inherited_ancestor_limits=handle.ancestor_limits())
    except BaseException:
        handle.close()
        raise


async def inner(request_path, expected_sha):
    raw = w.read_file(request_path, 1024*1024)
    b.require(s.valid_sha(expected_sha) and b.digest(raw) == expected_sha, 'inner request hash differs')
    request = json.loads(raw)
    b.require(request['source'] == sources(), 'inner source differs from pinned outer source')
    handle, receipt = await precreate_unit(request)  # Before backend construction or Wine --version.
    receipt_path = Path(request['receipt'])
    c.write_json(receipt_path, receipt)
    options = v.arm_options(SimpleNamespace(**{key: Path(value) if key in
        ('assets', 'journal', 'library', 'output', *v.WINE_OPTIONS) and value is not None else value
        for key, value in request['config'].items()}), request['profiled'])
    options.output = Path(request['arm_output'])
    options.wine_cgroup_parent = None  # Existing backend discovers our delegated coordinator leaf.
    original = b.create_worker
    used = False

    async def create(args, data, output, *, ai=None, backend=None):
        nonlocal used
        b.require(not used and b.create_worker is create and backend is not None and ai is None,
                  'unexpected owned Wine CPU benchmark launch')
        b.create_worker = original
        used = True
        handle.verify()
        worker = await original(args, data, output, ai=ai, backend=backend)
        try:
            receipt['after_create'] = handle.owned_worker(worker)
        except BaseException:
            await worker.close()
            raise
        close = worker.close

        async def verified_close():
            try:
                receipt['before_close'] = handle.owned_worker(worker)
            finally:
                await close()
        worker.close = verified_close
        return worker

    b.create_worker = create
    try:
        b.validate_args(options)
        code = await b.run(options)
        b.require(code == 0 and used and 'before_close' in receipt, 'Wine CPU replay arm failed')
        receipt['after_worker_cleanup'] = handle.verify()
        receipt['source_at_finish'] = sources()
        b.require(receipt['source_at_finish'] == request['source'], 'inner source changed')
        receipt['passed'] = True
        return 0
    except BaseException as error:
        receipt.update(passed=False, error=repr(error), traceback=traceback.format_exc())
        raise
    finally:
        if b.create_worker is create:
            b.create_worker = original
        handle.close()
        c.write_json(receipt_path.with_suffix('.complete.json'), receipt)


async def stop_owned(unit, nonce, invocation=None):
    state = await unit_state(unit)
    if state.get('LoadState') == 'not-found':
        return dict(unit_absent=True)
    verify_identity(state, unit, nonce, invocation)
    code, _, stderr = await command([SYSTEMCTL, 'stop', unit], timeout=25)
    b.require(code == 0, 'owned unit stop failed: '+stderr)
    after = await unit_state(unit)
    b.require(after.get('LoadState') == 'not-found' or after.get('ActiveState') in ('inactive', 'failed'),
              'task unit remains active after stop')
    return dict(unit_absent=after.get('LoadState') == 'not-found', final_state=after,
                stopped_owned_invocation=state['InvocationID'])


async def launch_arm(request, request_path, logs):
    b.require((await unit_state(request['unit'])).get('LoadState') == 'not-found', 'task unit already exists')
    request_sha = c.write_json(request_path, request)
    argv = launch_argv(request['unit'], request['nonce'], request['cpus'], request_path,
                       request_sha, request['config']['timeout_seconds'])
    process = None
    identity = None
    outcome = dict(argv=argv, request_sha256=request_sha)
    try:
        with logs.open('xb') as log:
            process = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.DEVNULL,
                stdout=log, stderr=asyncio.subprocess.STDOUT)
            outcome['systemd_run_exit'] = await asyncio.wait_for(process.wait(), request['config']['timeout_seconds']+110)
        b.require(outcome['systemd_run_exit'] == 0, 'owned systemd-run arm failed; retain log')
        receipt, receipt_sha = s.read_json(Path(request['receipt']).with_suffix('.complete.json'))
        identity = verify_identity(receipt['identity'], request['unit'], request['nonce'])
        b.require(receipt.get('passed') is True and receipt.get('before_wine_launch') is True
                  and receipt.get('source_at_finish') == request['source'], 'inner cpuset receipt incomplete')
        outcome.update(receipt=receipt, receipt_sha256=receipt_sha)
        return outcome
    finally:
        if identity is None and Path(request['receipt']).exists():
            try:
                receipt, _ = s.read_json(Path(request['receipt']))
                identity = verify_identity(receipt['identity'], request['unit'], request['nonce'])
            except BaseException as error:
                # A corrupt receipt must never bypass nonce-verified cleanup.
                outcome['receipt_error'] = repr(error)
        cleanup = asyncio.create_task(stop_owned(request['unit'], request['nonce'],
            identity['InvocationID'] if identity is not None else None))
        try:
            outcome['unit_cleanup'] = await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            outcome['unit_cleanup'] = await cleanup
            raise
        finally:
            if process is not None and process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), 20)
                except TimeoutError:
                    # Only our retained systemd-run client; task-unit cleanup
                    # above is authoritative for all native descendants.
                    await stop_client(process)
            if identity is not None:
                group_path = Path(receipt['precreate_cpuset']['path'])
                b.require(not group_path.exists(), 'task unit cgroup was not removed after owned stop')
            c.write_json(request_path.with_suffix('.launch.json'), outcome)


def config(args, assets, journal, output):
    return SimpleNamespace(assets=Path(assets).resolve(), journal=Path(journal).resolve(), library=args.library.resolve(),
        library_sha256=args.library_sha256, output=output, timeout_seconds=args.timeout_seconds,
        thread_sample_interval=0, wine_executable=args.wine_executable.resolve(),
        windows_python=args.windows_python.resolve(), wine_prefix_template=args.wine_prefix_template.resolve(),
        wine_cgroup_parent=None)


async def run(args):
    b.require(sys.platform.startswith('linux'), 'Linux systemd/cgroup-v2 environment required')
    b.require(len(args.workload) == 2 and {row[0] for row in args.workload} == {'wasp', 'crab'},
              'exactly one retained wasp and crab workload required')
    b.require(args.output.is_absolute() and not os.path.lexists(args.output), 'fresh absolute local output required')
    b.require(args.library.is_absolute() and not args.library.is_symlink()
              and args.wine_prefix_template.is_absolute() and not args.wine_prefix_template.is_symlink(),
              'explicit unredirected library and private prefix template required')
    host = topology()
    configs = [(name, config(args, assets, journal, args.output/name)) for name, assets, journal in args.workload]
    for _, options in configs:
        v.validate_args(options)
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(schema=1, passed=False, topology=host, source_at_start=sources(), workloads=[],
        scope=__doc__, environment_notes=args.environment_notes,
        limitations=['entire task-unit cpuset includes coordinator/guardian/Wine; distinct from Windows worker-only affinity',
                     'OS-reported physical core IDs do not establish dedicated underlying physical hardware',
                     'host CPU quotas, clock/boost/power/thermal state and external contention can limit results',
                     'unit cpu.stat/pressure and cpu.max are context, not proof of an idle or dedicated host',
                     'a host-wide one-vCPU limit is distinct; effective cpuset cannot create a second permitted CPU',
                     'separate profiled pair attributes native cost; primary whole-STEP results remain unprofiled',
                     'no end-to-end20Hz, AI generation, hosting recommendation or rollout qualification'],
        performance_acceptance_evaluated=False)
    bindings, references = {}, []
    runtime = None
    try:
        report['prefix_template_at_start'] = template_inventory(args.wine_prefix_template.resolve())
        for path in (args.library.resolve(), Path(sys.executable).resolve(), args.wine_executable.resolve(),
                     args.windows_python.resolve(), Path(SYSTEMCTL), Path(SYSTEMD_RUN)):
            w.remember(path, 128*1024*1024, bindings, args.library_sha256 if path == args.library.resolve() else None)
        for name, options in configs:
            _, _, rows, _, _, reference = c.load_reference(options)
            b.require(1 <= len(rows) <= v.MAX_FRAMES, 'reference frame bound exceeded')
            references.append((options, reference))
            for filename, digest in reference['journal_files'].items():
                w.remember(options.journal/filename, c.JOURNAL_LIMITS[filename], bindings, digest)
            result = dict(name=name, reference=reference, arms=[], profile_summaries={})
            report['workloads'].append(result)
            controls = {}
            for pair, count, profiled in schedule():
                nonce = uuid.uuid4().hex
                arm = args.output/name/f'{"profile" if profiled else "pair"}{pair+1}-cores{count}'
                request = dict(unit='ba-cpu-bench-'+nonce+'.service', nonce=nonce,
                    cpus=host['selected_cpus'][:count], source=report['source_at_start'], profiled=profiled,
                    arm_output=str(arm), receipt=str(args.output/(nonce+'.cpuset.json')),
                    config={key: str(value) if isinstance(value, Path) else value for key, value in vars(options).items()})
                launched = await launch_arm(request, args.output/(nonce+'.request.json'), args.output/(nonce+'.log'))
                loaded = s.load_benchmark(arm)
                checked = v.verify_arm(loaded, reference, rows, options, profiled, True, b.source_hashes())
                if runtime is None:
                    runtime = checked['runtime']
                b.require(runtime == checked['runtime'], 'worker runtime changed between arms')
                checked.update(cores=count, pair=pair+1, unit=launched,
                    whole_step_ms={phase: b.summary([row['step_rpc_ms'] for row in loaded['rows'] if row['phase'] == phase])
                                   for phase in ('setup', 'movement', 'combat')})
                for filename, digest in loaded['evidence_sha256'].items():
                    w.remember(arm/filename, c.JOURNAL_LIMITS.get(filename, v.MAX_JSON), bindings, digest)
                if profiled:
                    control_path, control_receipt = controls[count]
                    result['profile_summaries'][str(count)] = profile_summary(arm, control_path,
                        launched['receipt'], control_receipt)
                    w.remember(arm/'worker-profile.json', 128*1024*1024, bindings, loaded['report']['worker_profile_sha256'])
                else:
                    controls.setdefault(count, (arm, launched['receipt']))
                result['arms'].append(checked)
                (args.output/'progress.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
        report['passed'] = True
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        errors = []
        try:
            report['source_at_finish'] = sources()
            b.require(report['source_at_start'] == report['source_at_finish'], 'source changed')
            b.require(topology() == host, 'topology/outer allowed masks changed')
            b.require(template_inventory(args.wine_prefix_template.resolve()) == report['prefix_template_at_start'],
                      'private prefix template changed')
        except BaseException as error:
            errors.append(repr(error))
        for path, identity in bindings.items():
            try:
                b.require(b.digest(w.read_file(Path(path), identity['limit'])) == identity['sha256'], 'digest changed')
            except BaseException as error:
                errors.append(path+': '+repr(error))
        for options, reference in references:
            try:
                c.check_stability(options, reference)
            except BaseException as error:
                errors.append('reference: '+repr(error))
        report.update(bindings=bindings, stability_errors=errors, passed=report['passed'] and not errors)
        c.write_json(args.output/'wine-cpu-experiment.json', report)
    return 0 if report['passed'] else 1


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inner-request', type=Path)
    parser.add_argument('--request-sha256')
    parser.add_argument('--workload', nargs=3, action='append', metavar=('NAME', 'ASSETS', 'JOURNAL'))
    for name in ('library', 'output', 'wine-executable', 'windows-python', 'wine-prefix-template'):
        parser.add_argument('--'+name, type=Path)
    parser.add_argument('--library-sha256')
    parser.add_argument('--timeout-seconds', type=float, default=600)
    parser.add_argument('--environment-notes', default='Clock/power/thermal state and external contention unqualified.')
    args = parser.parse_args(argv)
    if args.inner_request is not None:
        b.require(args.inner_request.is_absolute() and s.valid_sha(args.request_sha256), 'explicit hash-bound inner request required')
    else:
        b.require(args.workload is not None and all(getattr(args, name) is not None for name in
            ('library', 'output', 'wine_executable', 'windows_python', 'wine_prefix_template', 'library_sha256')),
            'all outer workload/runtime/library/output options are required')
    return args


if __name__ == '__main__':
    arguments_ = arguments()
    raise SystemExit(asyncio.run(inner(arguments_.inner_request, arguments_.request_sha256)
        if arguments_.inner_request is not None else run(arguments_)))
