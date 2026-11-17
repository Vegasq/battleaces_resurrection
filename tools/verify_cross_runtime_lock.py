"""Opt-in Linux/Wine lock-only diagnostic; never starts a host or native game.

Use native Linux Python with --windows-python /path/to/embedded/python.exe and
--output /new/private/probe-directory. A fresh Wine prefix lives inside output;
no existing prefix, server state or lock file is accepted. The unchanged
server.state_lock.exclusive_state runs in both interpreters. A completed probe
can FAIL exclusion: measurement completion is distinct from the acceptance gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ("import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
             "runpy.run_module('tools.verify_cross_runtime_lock',run_name='__main__')")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def actor(state, result, release, lifetime):
    """Hold the production lock until an owned command or finite deadline."""
    from server.state_lock import exclusive_state, StateBusyError
    state, result, release = map(Path, (state, result, release))
    record = dict(pid=os.getpid(), os_name=os.name, python=platform.python_version())
    try:
        with exclusive_state(state):
            write_json(result, record | dict(acquired=True, busy=False))
            deadline = time.monotonic() + lifetime
            while time.monotonic() < deadline:
                if release.exists():
                    command = release.read_text(encoding='ascii')
                    if command == 'crash':
                        os._exit(73)  # Deliberate owned actor crash; no finally/unlock.
                    if command != 'release':
                        raise ValueError('invalid actor release command')
                    return 0
                time.sleep(.01)
            return 4  # Watchdog exit never counts as a graceful release.
    except StateBusyError:
        write_json(result, record | dict(acquired=False, busy=True))
        return 2
    except BaseException as error:
        write_json(result, record | dict(acquired=False, busy=False, error=repr(error)))
        return 3


def command(python, root, state, result, release, lifetime, *, wine=None):
    arguments = [str(python), '-I', '-B', '-u', '-c', BOOTSTRAP, str(root),
                 '--actor', str(state), str(result), str(release), str(lifetime)]
    return ([str(wine)] if wine else []) + arguments


def wine_path(path):
    path = Path(path).resolve()
    if not path.as_posix().startswith('/'):
        raise ValueError('Wine mapping requires an absolute Linux path')
    return 'Z:' + str(path).replace('/', '\\')


def wine_environment(prefix):
    environment = os.environ.copy()
    environment.update(WINEPREFIX=str(prefix), WINEARCH='win64', WINEDEBUG='-all',
                       WINEDLLOVERRIDES='mscoree,mshtml=',
                       DISPLAY='', WAYLAND_DISPLAY='')
    return environment


class PipeLog:
    """Drain both Windows stdio pipes continuously into one bounded local log."""
    def __init__(self, path, *, limit=1024*1024):
        self.log = Path(path).open('xb')
        self.remaining, self.dropped = limit, 0
        self.lock, self.threads, self.streams, self.errors = threading.Lock(), [], [], []

    def attach(self, stream):
        def drain():
            try:
                while data := stream.read(4096):
                    with self.lock:
                        length = min(self.remaining, len(data))
                        self.remaining -= length
                        self.dropped += len(data)-length
                        try:
                            self.log.write(data[:length])
                            self.log.flush()
                        except OSError as error:
                            # Even a failed evidence write must not block the child.
                            if not self.errors:
                                self.errors.append(repr(error))
            except OSError as error:
                with self.lock:
                    self.errors.append(repr(error))
        self.streams.append(stream)
        thread = threading.Thread(target=drain, daemon=True, name='lock-probe-pipe')
        self.threads.append(thread)
        thread.start()

    def close(self, timeout):
        deadline = time.monotonic()+timeout
        for thread in self.threads:
            thread.join(max(0, deadline-time.monotonic()))
        if any(thread.is_alive() for thread in self.threads):
            raise TimeoutError('owned actor stdio pipe did not close')
        for stream in self.streams:
            stream.close()
        self.log.close()
        if self.errors:
            raise OSError('actor log drain failed: '+self.errors[0])


def start_process(args, log_path, environment):
    log = PipeLog(log_path)
    try:
        # Wine9 + embedded Python3.14 can reject inherited regular-file stdio
        # handles at init_sys_streams. Keep the verified DEVNULL/PIPE/PIPE setup;
        # the parent alone owns the regular evidence file.
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=environment, close_fds=True,
                                   start_new_session=True)
    except BaseException:
        log.close(0)
        raise
    log.attach(process.stdout)
    log.attach(process.stderr)
    return process, log


def verdict(cases):
    completed = len(cases) == 8
    controls = [c for c in cases if c['owner'] == c['contender']]
    cross = [c for c in cases if c['owner'] != c['contender']]
    exclusion = lambda rows: bool(rows) and all(c['blocked'] for c in rows)
    recovery = bool(cases) and all(c['reacquired'] and c['lock_preserved'] for c in cases)
    return dict(measurement_completed=completed, same_runtime_exclusion=exclusion(controls),
                cross_runtime_exclusion=exclusion(cross), recovery=recovery,
                passed=completed and exclusion(controls) and exclusion(cross) and recovery)


class Probe:
    def __init__(self, args):
        self.args = args
        self.output = args.output.resolve()
        self.prefix = self.output / 'wine-prefix'
        self.environment = wine_environment(self.prefix)
        self.actors = []

    def start(self, runtime, state, label, *, startup_timeout=None):
        result, release = self.output/(label+'.json'), self.output/(label+'.release')
        args = command(sys.executable, ROOT, state, result, release, self.args.actor_lifetime)
        if runtime == 'wine':
            args = command(self.args.windows_python, wine_path(ROOT), wine_path(state),
                           wine_path(result), wine_path(release), self.args.actor_lifetime,
                           wine=self.args.wine)
        process, log = start_process(args, self.output/(label+'.log'), self.environment)
        entry = dict(process=process, result=result, release=release, log=log,
                     label=label, runtime=runtime)
        self.actors.append(entry)
        deadline = time.monotonic() + (startup_timeout or self.args.timeout)
        while not result.exists():
            if process.poll() is not None:
                raise RuntimeError(f'{label} exited before publishing its result')
            if time.monotonic() >= deadline:
                raise TimeoutError(f'{label} startup exceeded deadline')
            time.sleep(.01)
        if result.stat().st_size > 4096:
            raise ValueError('actor result exceeds bound')
        entry['record'] = json.loads(result.read_text(encoding='utf-8'))
        record = entry['record']
        if record.get('os_name') != ('nt' if runtime == 'wine' else 'posix') or record.get('error'):
            raise ValueError(f'{label} returned an invalid actor result')
        if type(record.get('acquired')) is not bool or record.get('busy') is not (not record['acquired']):
            raise ValueError(f'{label} did not report a lock outcome')
        return entry

    def finish(self, entry, *, crash=False):
        acquired = entry['record']['acquired']
        if acquired:
            if entry['process'].poll() is not None:
                raise RuntimeError('lock owner died before requested release')
            entry['release'].write_text('crash' if crash else 'release', encoding='ascii')
        code = entry['process'].wait(timeout=self.args.timeout)
        expected = (73 if crash else 0) if acquired else 2
        if code != expected:
            raise RuntimeError(f"{entry['label']} exited {code}, expected {expected}")
        entry['exit_code'] = code

    def case(self, owner, contender, *, crash):
        label = f'{owner}-{contender}-' + ('crash' if crash else 'release')
        state = self.output / label
        state.mkdir()
        first = self.start(owner, state, label+'-owner')
        if not first['record']['acquired']:
            raise RuntimeError('fresh lock was unexpectedly busy')
        path = state/'.host.lock'
        inode, original = path.stat().st_ino, path.read_bytes()
        other = self.start(contender, state, label+'-contender')
        if first['process'].poll() is not None:
            raise RuntimeError('owner exited during contention measurement')
        blocked = other['record']['busy']
        self.finish(other)
        self.finish(first, crash=crash)
        recovered = self.start(contender, state, label+'-recovered')
        reacquired = recovered['record']['acquired']
        self.finish(recovered)
        return dict(owner=owner, contender=contender, termination='crash' if crash else 'release',
                    blocked=blocked, reacquired=reacquired,
                    lock_preserved=original == b'\0' == path.read_bytes() and path.stat().st_ino == inode,
                    actor_labels=[e['label'] for e in (first, other, recovered)])

    def cleanup(self):
        # Request normal release first. Actor watchdogs are an additional bound.
        for entry in self.actors:
            if entry['process'].poll() is None and not entry['release'].exists():
                entry['release'].write_text('release', encoding='ascii')
        # Wine may retain prefix services after the last actor. This is always a
        # newly created prefix under our newly created output, never a supplied
        # or default prefix. No unscoped/global wineserver command is permitted.
        if self.prefix.exists():
            with (self.output/'wine-cleanup.log').open('ab') as log:
                subprocess.run([self.args.wineserver, '-k'], env=self.environment,
                               stdout=log, stderr=log, timeout=self.args.timeout, check=True)
                subprocess.run([self.args.wineserver, '-w'], env=self.environment,
                               stdout=log, stderr=log, timeout=self.args.timeout, check=True)
        for entry in self.actors:
            process = entry['process']
            if process.poll() is None:
                try:
                    process.wait(timeout=self.args.timeout)
                except subprocess.TimeoutExpired:
                    process.kill()  # Only this diagnostic's retained Popen handle.
                    process.wait(timeout=self.args.timeout)
            entry['log'].close(self.args.timeout)

    def run(self):
        self.output.mkdir(parents=True, exist_ok=False)
        self.prefix.mkdir()
        source = ROOT/'server/state_lock.py'
        report = dict(passed=False, measurement_completed=False, cases=[],
                      source_sha256=digest(source), platform=platform.platform(),
                      native_python=sys.version, windows_python_sha256=digest(self.args.windows_python),
                      wine_prefix=str(self.prefix), scope=__doc__)
        try:
            report['wine_version'] = subprocess.check_output([self.args.wine, '--version'],
                env=self.environment, timeout=self.args.timeout, text=True).strip()
            state = self.output/'warmup'; state.mkdir()
            for runtime in ('linux', 'wine'):
                entry = self.start(runtime, state, runtime+'-warmup', startup_timeout=120)
                if not entry['record']['acquired']:
                    raise RuntimeError('warmup failed to acquire fresh state')
                self.finish(entry)
            # Same-prefix Win32 checks exercise Wine's internal registry, while
            # the two cross-runtime directions exercise actual Unix exclusion.
            for owner, contender in (('linux', 'linux'), ('wine', 'wine'), ('linux', 'wine'), ('wine', 'linux')):
                for crash in (False, True):
                    report['cases'].append(self.case(owner, contender, crash=crash))
            report.update(verdict(report['cases']))
        except BaseException as error:
            report.update(passed=False, error=repr(error), traceback=traceback.format_exc())
        finally:
            try:
                self.cleanup()
                report['cleanup_completed'] = True
            except BaseException as error:
                report.update(passed=False, cleanup_completed=False, cleanup_error=repr(error))
            report['actors'] = [dict(label=e['label'], runtime=e['runtime'],
                                    exit_code=e['process'].poll(), record=e.get('record'),
                                    log_bytes_dropped=e['log'].dropped,
                                    log_drainers_finished=all(not t.is_alive() for t in e['log'].threads))
                                for e in self.actors]
            report['source_unchanged'] = digest(source) == report['source_sha256']
            report['passed'] &= report['source_unchanged']
            write_json(self.output/'verification.json', report)
        return report


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == '--actor':
        if len(argv) != 5 or not 1 <= float(argv[4]) <= 300:
            raise ValueError('invalid private actor arguments')
        return actor(*argv[1:4], float(argv[4]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows-python', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--wine', default='wine')
    parser.add_argument('--wineserver', default='wineserver')
    parser.add_argument('--timeout', type=float, default=15)
    parser.add_argument('--actor-lifetime', type=float, default=60)
    args = parser.parse_args(argv)
    if not sys.platform.startswith('linux'):
        parser.error('run the coordinator probe with native Linux Python')
    args.windows_python = args.windows_python.resolve()
    if not args.windows_python.is_file() or args.output.exists():
        parser.error('require existing Windows Python and a new output directory')
    if not 1 <= args.timeout <= 30 or not args.timeout*3 < args.actor_lifetime <= 300:
        parser.error('timeout must be1..30s and actor lifetime>3*timeouts, at most300s')
    for name in ('wine', 'wineserver'):
        executable = shutil.which(getattr(args, name))
        if not executable:
            parser.error(f'{name} executable unavailable')
        setattr(args, name, executable)
    report = Probe(args).run()
    print(json.dumps({k: report[k] for k in ('passed', 'measurement_completed', 'cross_runtime_exclusion',
                                            'same_runtime_exclusion', 'cleanup_completed', 'error') if k in report}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
