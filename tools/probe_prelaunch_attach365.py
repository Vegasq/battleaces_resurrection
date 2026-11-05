"""Owned inert Windows process gate for a pre-first-instruction Frida attach check."""
from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    assert output.is_relative_to(ROOT/'local') and not output.exists()
    output.mkdir(parents=True)
    marker = output/'child-ran.txt'
    child_code = ('from pathlib import Path;import time;'
                  f'Path({str(marker)!r}).write_text("CHILD_RAN\\n");time.sleep(5)')
    process = subprocess.Popen([sys.executable, '-B', '-c', child_code],
                               creationflags=0x00000004,  # Windows CREATE_SUSPENDED
                               cwd=output, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    report = dict(passed=False, scope=__doc__, pid=process.pid,
                  output=str(output), marker=str(marker))
    (output/'pid.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    try:
        deadline = time.monotonic()+115
        gate = output/'observer-ready'
        while not gate.is_file():
            if time.monotonic() >= deadline:
                raise TimeoutError('prelaunch observer gate was not published')
            if process.poll() is not None:
                raise RuntimeError('suspended process exited before resume')
            time.sleep(.05)
        assert gate.read_bytes() == b'FRIDA_READY\n'
        assert not marker.exists()
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        ntdll = ctypes.WinDLL('ntdll', use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
        ntdll.NtResumeProcess.restype = ctypes.c_long
        handle = kernel.OpenProcess(0x0800, 0, process.pid)
        if not handle:
            raise OSError(ctypes.get_last_error(), 'OpenProcess(PROCESS_SUSPEND_RESUME)')
        try:
            status = ntdll.NtResumeProcess(handle)
            if status != 0:
                raise OSError(status, 'NtResumeProcess')
        finally:
            kernel.CloseHandle(handle)
        code = process.wait(timeout=20)
        assert code == 0 and marker.read_text(encoding='utf-8') == 'CHILD_RAN\n'
        report.update(passed=True, observer_gate_preceded_child=True,
                      child_exit_code=code, child_marker_sha256=__import__('hashlib').sha256(marker.read_bytes()).hexdigest())
    except BaseException as error:
        report['error_type'] = type(error).__name__
        report['error'] = str(error)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
            report['forced_owned_cleanup'] = True
        else:
            report['forced_owned_cleanup'] = False
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'pid': process.pid,
                      'forced_owned_cleanup': report['forced_owned_cleanup']}))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
