"""Local controls for the opt-in Linux/Wine lock diagnostic; no Wine needed."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from server.state_lock import exclusive_state, StateBusyError
from tools import verify_cross_runtime_lock as probe


class CrossRuntimeLockProbeTests(unittest.TestCase):
    def test_child_lock_contention_and_crash_recovery_use_actual_production_lock(self):
        with tempfile.TemporaryDirectory(prefix='ba-lock-probe-') as folder:
            root = Path(folder)
            state, result, release = root/'state', root/'result.json', root/'release'
            child = subprocess.Popen(probe.command(sys.executable, probe.ROOT, state, result, release, 10),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while not result.exists() and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(result.exists(), 'actor failed before publishing readiness')
                self.assertEqual(json.loads(result.read_text())['acquired'], True)
                with self.assertRaises(StateBusyError):
                    with exclusive_state(state):
                        self.fail('actor did not retain the production lock')
                release.write_text('crash', encoding='ascii')
                stdout, stderr = child.communicate(timeout=5)
                self.assertEqual(child.returncode, 73, (stdout, stderr))
                with exclusive_state(state):
                    pass
                self.assertEqual(b'\0', (state/'.host.lock').read_bytes())
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=5)

    def test_actor_reports_busy_distinct_from_runtime_failure(self):
        with tempfile.TemporaryDirectory(prefix='ba-lock-busy-') as folder:
            root = Path(folder)
            state, result, release = root/'state', root/'result.json', root/'release'
            with exclusive_state(state):
                completed = subprocess.run(probe.command(sys.executable, probe.ROOT, state, result, release, 10),
                                           capture_output=True, timeout=5)
            self.assertEqual(completed.returncode, 2, completed.stderr)
            record = json.loads(result.read_text())
            self.assertEqual((record['acquired'], record['busy']), (False, True))
            self.assertNotIn('error', record)

    def test_actor_normal_release_preserves_existing_empty_lock_file(self):
        with tempfile.TemporaryDirectory(prefix='ba-lock-release-') as folder:
            root = Path(folder)
            state, result, release = root/'state', root/'result.json', root/'release'
            state.mkdir(); (state/'.host.lock').touch()
            release.write_text('release', encoding='ascii')
            self.assertEqual(probe.actor(state, result, release, 1), 0)
            self.assertEqual((state/'.host.lock').read_bytes(), b'\0')
            with exclusive_state(state):
                pass

    def test_actor_invalid_command_is_error_and_releases_lock(self):
        with tempfile.TemporaryDirectory(prefix='ba-lock-command-') as folder:
            root = Path(folder)
            release = root/'release'
            release.write_text('unexpected', encoding='ascii')
            self.assertEqual(probe.actor(root/'state', root/'result.json', release, 1), 3)
            record = json.loads((root/'result.json').read_text())
            self.assertFalse(record['busy'])
            self.assertIn('invalid actor release command', record['error'])
            with exclusive_state(root/'state'):
                pass

    def test_command_does_not_shell_parse_spaced_unicode_paths(self):
        args = probe.command('/owned/Python space/python.exe', r'Z:\owned\source 한글',
                             r'Z:\owned\state space', r'Z:\owned\ready', r'Z:\owned\release', 60,
                             wine='/usr/bin/wine')
        self.assertEqual(args[:2], ['/usr/bin/wine', '/owned/Python space/python.exe'])
        self.assertIn(r'Z:\owned\source 한글', args)
        self.assertEqual(args[-4:], [r'Z:\owned\state space', r'Z:\owned\ready', r'Z:\owned\release', '60'])

    def test_fresh_prefix_overrides_inherited_production_prefix_and_display(self):
        with mock.patch.dict(os.environ, WINEPREFIX='/production/prefix', DISPLAY=':0', WAYLAND_DISPLAY='wayland-0'):
            environment = probe.wine_environment(Path('/owned/probe/wine-prefix'))
        self.assertEqual(environment['WINEPREFIX'], str(Path('/owned/probe/wine-prefix')))
        self.assertEqual(environment['DISPLAY'], '')
        self.assertEqual(environment['WAYLAND_DISPLAY'], '')
        self.assertEqual(environment['WINEARCH'], 'win64')
        self.assertEqual(environment['WINEDLLOVERRIDES'], 'mscoree,mshtml=')

    def test_actor_uses_separate_pipes_and_drains_both_beyond_pipe_capacity(self):
        with tempfile.TemporaryDirectory(prefix='ba-lock-pipes-') as folder:
            output = Path(folder)/'actor.log'
            code = "import sys;sys.stdout.buffer.write(b'o'*1500000);sys.stdout.flush();sys.stderr.buffer.write(b'e'*1500000);sys.stderr.flush()"
            with mock.patch.object(probe.subprocess, 'Popen', wraps=subprocess.Popen) as launch:
                child, log = probe.start_process([sys.executable, '-I', '-B', '-c', code], output, os.environ.copy())
            try:
                self.assertEqual(child.wait(timeout=5), 0)
            finally:
                if child.poll() is None:
                    child.kill(); child.wait(timeout=5)
                log.close(5)
            self.assertEqual(launch.call_args.kwargs['stdin'], subprocess.DEVNULL)
            self.assertEqual(launch.call_args.kwargs['stdout'], subprocess.PIPE)
            self.assertEqual(launch.call_args.kwargs['stderr'], subprocess.PIPE)
            self.assertEqual(output.stat().st_size, 1024*1024)
            self.assertEqual(log.dropped, 3000000-1024*1024)
            self.assertTrue(all(not t.is_alive() for t in log.threads))

    def test_completed_negative_measurement_is_not_acceptance(self):
        cases = [dict(owner=owner, contender=contender, blocked=owner == contender,
                      reacquired=True, lock_preserved=True)
                 for owner in ('linux', 'wine') for contender in ('linux', 'wine') for _ in (0, 1)]
        result = probe.verdict(cases)
        self.assertTrue(result['measurement_completed'])
        self.assertTrue(result['same_runtime_exclusion'])
        self.assertFalse(result['cross_runtime_exclusion'])
        self.assertFalse(result['passed'])
        for case in cases:
            case['blocked'] = True
        self.assertTrue(probe.verdict(cases)['passed'])
        cases[-1]['lock_preserved'] = False
        self.assertFalse(probe.verdict(cases)['passed'])
        self.assertFalse(probe.verdict(cases[:-1])['measurement_completed'])

    def test_invalid_private_actor_arguments_never_touch_files(self):
        with mock.patch.object(probe, 'actor') as actor:
            for lifetime in ('0', '301', 'nan'):
                with self.subTest(lifetime=lifetime), self.assertRaises(ValueError):
                    probe.main(['--actor', 'state', 'result', 'release', lifetime])
            actor.assert_not_called()


if __name__ == '__main__':
    unittest.main()
