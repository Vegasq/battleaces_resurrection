"""Owned suspended diagnostic child with one explicit private bridge socket.

The normal launcher is unchanged. Only a socket supplied by the owner is
inherited through STARTUPINFO's handle list; the primary thread stays suspended
until the owner finishes its observer handshake. No arbitrary PID attachment.
"""
from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess

from server.worker_client import _WindowsJob
from tools.owned_suspended_launch import (CreationFailure, SuspendedChild,
                                          diagnostic_root, job_accounting, kernel_api)


def create_with_bridge(command, *, cwd, bridge, startupinfo=None, owned_root=None):
    """Return the exact SuspendedChild type so existing owner audits apply."""
    if os.name != 'nt' or not isinstance(bridge, socket.socket) or bridge.family != socket.AF_INET or \
            bridge.type != socket.SOCK_STREAM:
        raise ValueError('Owned Windows AF_INET stream bridge required')
    if not isinstance(command, (list, tuple)) or not command or not all(
            isinstance(arg, str) and '\0' not in arg for arg in command):
        raise ValueError('Explicit bounded child arguments required')
    root = diagnostic_root(owned_root)
    image, directory = Path(command[0]).resolve(), Path(cwd).resolve()
    line = subprocess.list2cmdline(command)
    handle = bridge.fileno()
    if not image.is_relative_to(root) or not image.is_file() or not directory.is_relative_to(root) or \
            not directory.is_dir() or len(line) >= 32767 or handle <= 0:
        raise ValueError('Owned image,directory and bounded command required')
    info = startupinfo.copy() if startupinfo is not None else subprocess.STARTUPINFO()
    if info.dwFlags & subprocess.STARTF_USESTDHANDLES or info.lpAttributeList not in (
            None, {}, {'handle_list': []}, {'handle_list': [handle]}):
        raise ValueError('Only the selected bridge handle may be inherited')
    info.lpAttributeList = {'handle_list': [handle]}
    import _winapi
    kernel = kernel_api()
    child = SuspendedChild()
    child.kernel = kernel
    child.handle = child.thread = child.job = None
    child.returncode = None
    child.resumed = False
    child.process = child
    child.receipt = dict(forced_cleanup=False, owned_process_reaped=False,
                         primary_thread_resumed=False, owned_root=str(root),
                         inherited_bridge_handle=handle,
                         create_before_tick=kernel.GetTickCount64())
    original_inheritable = bridge.get_inheritable()
    try:
        bridge.set_inheritable(True)
        hp, ht, child.pid, child.tid = _winapi.CreateProcess(
            str(image), line, None, None, True, subprocess.CREATE_NO_WINDOW | 4,
            None, str(directory), info)
        child.handle, child.thread = hp, ht
    finally:
        bridge.set_inheritable(original_inheritable)
    child.receipt.update(pid=child.pid, tid=child.tid, create_suspended=True,
                         create_return_tick=kernel.GetTickCount64(),
                         bridge_inherit_restored=bridge.get_inheritable() == original_inheritable)
    try:
        child.job = _WindowsJob(child.pid)
        child.receipt.update(job_assigned=job_accounting(child.job),
                             job_assigned_tick=kernel.GetTickCount64())
        child._identity()
        return child
    except BaseException as error:
        child.receipt['creation_error'] = repr(error)
        try:
            child.close()
        except BaseException as cleanup:
            child.receipt['cleanup_error'] = repr(cleanup)
        raise CreationFailure(child.receipt) from error


class BridgeProcess:
    """The launcher's Popen-shaped view over a retained SuspendedChild."""

    def __init__(self, child):
        if type(child) is not SuspendedChild or not child.handle or not child.job:
            raise ValueError('Live owned suspended child required')
        self.child = child
        self.pid = child.pid

    @property
    def returncode(self):
        return self.child.returncode

    def poll(self):
        return self.child.poll()

    def wait(self, timeout=None):
        if timeout is None:
            if self.child.poll() is None:
                raise RuntimeError('Unbounded bridge wait before signaled exit')
            return self.child.returncode
        return self.child.wait(timeout)

    def terminate(self):
        self.child.terminate()

    def close(self):
        self.child.close()
