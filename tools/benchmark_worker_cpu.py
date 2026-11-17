"""Private owned-worker one/two-core replay experiment on native Windows.

Three alternating unprofiled pairs per retained Wasp/Crab journal measure whole
STEP. A separate one/two-core instrumented pair attributes native simulation;
its timings never replace the primary observations. No listeners or live games.
Linux/Wine cpuset qualification and host-wide vCPU scaling remain separate.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import os
from pathlib import Path
import platform
import sys
import traceback
from types import SimpleNamespace

from server.worker_affinity import WindowsWorkerAffinity, host_topology
from server.worker_client import SimulationWorker
from tools import benchmark_large_armies as b
from tools import capture_snapshot_corpus as c
from tools import profile_worker_timing as p
from tools import summarize_worker_timing as s
from tools import verify_rust_worker as w
from tools import verify_rust_worker_profile as v

ROOT = b.ROOT


def sources():
    names = ('tools/benchmark_worker_cpu.py', 'tools/verify_rust_worker_profile.py',
             'server/worker_affinity.py')
    return {**w.sources(), **{name: b.digest((ROOT/name).read_bytes()) for name in names}}


def schedule():
    return [(pair, count, False) for pair in range(3)
            for count in ((1, 2) if pair % 2 == 0 else (2, 1))] + [(3, 1, True), (3, 2, True)]


def whole_step_summary(rows):
    return {phase: b.summary([row['step_rpc_ms'] for row in rows if row['phase'] == phase])
            for phase in ('setup', 'movement', 'combat')}


def system_observation():
    """Read-only host counters; activity is context, not isolation evidence."""
    from ctypes import wintypes as wt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetSystemTimes.argtypes = [ctypes.POINTER(wt.FILETIME)] * 3
    kernel.GetSystemTimes.restype = wt.BOOL
    idle, privileged, user = wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
    result = dict(scope='host-wide cumulative CPU ticks; includes this experiment and unrelated activity')
    if kernel.GetSystemTimes(ctypes.byref(idle), ctypes.byref(privileged), ctypes.byref(user)):
        ticks = lambda value: (value.dwHighDateTime << 32) | value.dwLowDateTime
        result['cpu_100ns'] = dict(idle=ticks(idle), kernel=ticks(privileged), user=ticks(user))
    else:
        result['cpu_counter_error'] = ctypes.get_last_error()
    class Power(ctypes.Structure):
        _fields_ = [('ac', wt.BYTE), ('battery_flags', wt.BYTE), ('battery_percent', wt.BYTE),
                    ('saver', wt.BYTE), ('battery_life_seconds', wt.DWORD), ('full_life_seconds', wt.DWORD)]
    kernel.GetSystemPowerStatus.argtypes = [ctypes.POINTER(Power)]
    kernel.GetSystemPowerStatus.restype = wt.BOOL
    power = Power()
    if kernel.GetSystemPowerStatus(ctypes.byref(power)):
        result['power_status'] = dict(ac_line_status=power.ac, battery_flags=power.battery_flags,
                                     battery_percent=power.battery_percent, battery_saver=power.saver)
    else:
        result['power_status_error'] = ctypes.get_last_error()
    result['clock_and_power_limits'] = 'CPU frequency/boost/thermal state and active power policy are not sampled'
    return result


async def run_owned_arm(options, cpus):
    """Replace only the benchmark's next launch; all ownership stays in client.

    The callback restores itself synchronously before its first await, like the
    established profiler's one-launch adapter. It neither changes Popen globally
    nor reaches another worker. Verification failure still closes the worker.
    """
    original = b.create_worker
    receipts = []
    used = False

    async def create(args, data, output, *, ai=None, backend=None):
        nonlocal used
        b.require(not used and b.create_worker is create, 'CPU benchmark launch ownership changed')
        b.create_worker = original
        used = True
        b.require(ai is None and backend is None, 'CPU experiment requires native recorded-input worker')
        policy = WindowsWorkerAffinity(cpus)
        kwargs = dict(working_directory=output, ai=None, startup_timeout=120, request_timeout=10,
                      close_timeout=3, owned_cpu_affinity=policy,
                      snapshot_decoder_library=args.snapshot_decoder_library,
                      snapshot_decoder_sha256=args.snapshot_decoder_sha256)
        if args.profile_worker:
            worker = await p.create_profiled_worker(data, args.assets/'Simulation.dll',
                profile_path=args.output/'worker-profile.json', max_records=20000,
                thread_sample_interval=0, **kwargs)
        else:
            worker = await SimulationWorker.create(data, args.assets/'Simulation.dll', **kwargs)
        try:
            receipt = dict(before_replay=dict(worker.affinity_info), after_create_mask=policy.verify())
        except BaseException:
            # create() has transferred ownership to this callback, but b.run has
            # not yet received the object. Do not leave that narrow gap unowned.
            await worker.close()
            raise
        receipts.append(receipt)
        close = worker.close

        async def verified_close():
            try:
                receipt['before_close_mask'] = policy.verify()
            finally:
                await close()
        worker.close = verified_close
        return worker

    b.create_worker = create
    try:
        code = await b.run(options)
    finally:
        if b.create_worker is create:
            b.create_worker = original
    b.require(code == 0 and used and len(receipts) == 1, 'CPU arm failed; retain original arm output')
    expected = sum(1 << cpu for cpu in cpus)
    receipt = receipts[0]
    b.require(receipt['before_replay']['before_create'] is True
              and receipt['before_replay']['actual_mask'] == expected
              and receipt['after_create_mask'] == receipt['before_close_mask'] == expected,
              'CPU arm affinity verification incomplete')
    return receipt


def workload_args(args, name, assets, journal):
    return SimpleNamespace(assets=Path(assets), journal=Path(journal), library=args.library,
        library_sha256=args.library_sha256, output=args.output/name,
        timeout_seconds=args.timeout_seconds, thread_sample_interval=0,
        **{field: None for field in v.WINE_OPTIONS})


def validate(args):
    b.require(os.name == 'nt' and sys.platform == 'win32',
              'native Windows only; Wine pre-CREATE owned-descendant cpuset is not yet supported')
    b.require(len(args.workload) == 2 and {row[0] for row in args.workload} == {'wasp', 'crab'},
              'exactly one retained wasp and crab workload are required')
    b.require(args.output.is_absolute() and not os.path.lexists(args.output), 'fresh absolute private output required')
    local = (ROOT/'local').resolve()
    b.require(args.output.resolve().is_relative_to(local) and args.output.resolve() != local,
              'output must be inside ignored local directory')
    for name, assets, journal in args.workload:
        v.validate_args(workload_args(args, name, assets, journal))


async def run(args):
    validate(args)
    topology = host_topology()  # Refuse inadequate/ambiguous topology before any spawn.
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(schema=1, passed=False, scope=__doc__, topology=topology, workloads=[],
        environment=dict(platform=platform.platform(), python=sys.version, executable=sys.executable,
                         operator_notes=args.environment_notes),
        limitations=['OS-reported physical core topology; virtualization/hardware dedication is not established',
                     'clock frequency, thermal throttling, power plan and external contention are uncontrolled unless operator evidence says otherwise',
                     'actual process masks verified before CREATE, after CREATE and before close; no continuous scheduler trace',
                     'worker-only affinity is not a host-wide one-vCPU versus two-vCPU experiment',
                     'native Windows results do not qualify Linux, Wine or cloud sizing',
                     'Linux requires an owned pre-CREATE cpuset covering task-owned Wine descendants with effective-mask and guardian/cgroup/prefix cleanup proof',
                     'recorded AI replay does not qualify fresh AI generation or20Hz publication'],
        performance_acceptance_evaluated=False)
    bindings, references = {}, []
    try:
        report['source_at_start'] = sources()
        benchmark_sources = b.source_hashes()
        w.remember(args.library.resolve(), w.MAX_LIBRARY, bindings, args.library_sha256)
        w.remember(Path(sys.executable).resolve(), 128*1024*1024, bindings)
        runtime = None
        for name, assets, journal in args.workload:
            config = workload_args(args, name, assets, journal)
            config.assets, config.journal = config.assets.resolve(), config.journal.resolve()
            _, _, expected_rows, _, _, reference = c.load_reference(config)
            b.require(1 <= len(expected_rows) <= v.MAX_FRAMES, 'reference frame bound exceeded')
            references.append((config, reference))
            for filename, digest in reference['journal_files'].items():
                w.remember(config.journal/filename, c.JOURNAL_LIMITS[filename], bindings, digest)
            for filename, limit in (('asset-manifest.json', 4*1024*1024), ('Simulation.dll', 128*1024*1024)):
                w.remember(config.assets/filename, limit, bindings)
            result = dict(name=name, reference=reference, arms=[], profile_summaries={})
            report['workloads'].append(result)
            controls = {}
            for pair, count, profiled in schedule():
                options = v.arm_options(config, profiled)
                options.output = args.output/name/f'{"profile" if profiled else "pair"}{pair+1}-cores{count}'
                b.validate_args(options)
                host_before = system_observation()
                receipt = await run_owned_arm(options, topology['selected_logical_cpus'][:count])
                host_after = system_observation()
                loaded = s.load_benchmark(options.output)
                checked = v.verify_arm(loaded, reference, expected_rows, config, profiled, False, benchmark_sources)
                if runtime is None:
                    runtime = checked['runtime']
                b.require(checked['runtime'] == runtime, 'worker runtime changed between CPU arms')
                checked.update(pair=pair+1, cores=count, affinity=receipt,
                               host_before=host_before, host_after=host_after,
                               directory=str(options.output), whole_step_ms=whole_step_summary(loaded['rows']))
                for filename, digest in loaded['evidence_sha256'].items():
                    w.remember(options.output/filename, c.JOURNAL_LIMITS.get(filename, v.MAX_JSON), bindings, digest)
                if profiled:
                    summary = s.summarize(options.output, controls[count])
                    b.require(summary['passed'] is True, 'native timing profile failed validation')
                    result['profile_summaries'][str(count)] = summary
                    w.remember(options.output/'worker-profile.json', 128*1024*1024, bindings,
                               loaded['report']['worker_profile_sha256'])
                else:
                    controls.setdefault(count, options.output)
                result['arms'].append(checked)
                (args.output/'progress.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        report['passed'] = True
    except BaseException as error:
        report.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        errors = []
        try:
            report['source_at_finish'] = sources()
            report['source_unchanged'] = report['source_at_start'] == report['source_at_finish']
            b.require(report['source_unchanged'], 'source changed during experiment')
            b.require(host_topology() == topology, 'host topology/allowed mask changed')
        except BaseException as error:
            errors.append('source/topology stability: '+repr(error))
        for path, identity in bindings.items():
            try:
                b.require(b.digest(w.read_file(Path(path), identity['limit'])) == identity['sha256'], 'digest changed')
            except BaseException as error:
                errors.append('bound file '+path+': '+repr(error))
        for config, reference in references:
            try:
                c.check_stability(config, reference)
            except BaseException as error:
                errors.append('reference stability: '+repr(error))
        report['bindings'] = bindings
        report['stability_errors'] = errors
        report['passed'] = report['passed'] and not errors
        c.write_json(args.output/'cpu-experiment.json', report)
    return 0 if report['passed'] else 1


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workload', nargs=3, action='append', required=True, metavar=('NAME', 'ASSETS', 'JOURNAL'))
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--library-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout-seconds', type=float, default=600)
    parser.add_argument('--environment-notes', default='No operator clock/power/contention evidence supplied; limited worker-affinity scope only.')
    return parser.parse_args(argv)


if __name__ == '__main__':
    raise SystemExit(asyncio.run(run(arguments())))
