"""One bounded context/stack observation of an exact retained owned child.

Suspends one validated thread once and always attempts the matching single
resume. Does not attach a debugger, terminate, enumerate targets, or follow
arbitrary pointers. Stack words classified inside a supplied module are only
candidates, not an unwound call stack. Caller retains Popen/Job ownership.
"""
from __future__ import annotations

import ctypes as C
import os
import struct
import subprocess


def capture_native_context(process, job, thread_id, module_base, *, module_size=0x49B000, stack_bytes=4096):
    if (os.name != 'nt' or C.sizeof(C.c_void_p) != 8 or not isinstance(process, subprocess.Popen)
            or process.poll() is not None or not getattr(job, 'handle', None)
            or type(thread_id) is not int or not 0 < thread_id <= 0xffffffff
            or type(module_base) is not int or not 0 < module_base < 2**63
            or not 1 <= module_size <= 16*1024*1024 or not 128 <= stack_bytes <= 8192):
        raise ValueError('exact live owned Popen/Job, thread and bounded module/stack required')
    kernel = C.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'GetProcessId': ([C.c_void_p], C.c_ulong),
        'IsProcessInJob': ([C.c_void_p, C.c_void_p, C.POINTER(C.c_int)], C.c_int),
        'OpenThread': ([C.c_ulong, C.c_int, C.c_ulong], C.c_void_p),
        'GetProcessIdOfThread': ([C.c_void_p], C.c_ulong),
        'GetThreadId': ([C.c_void_p], C.c_ulong),
        'SuspendThread': ([C.c_void_p], C.c_ulong),
        'ResumeThread': ([C.c_void_p], C.c_ulong),
        'GetThreadContext': ([C.c_void_p, C.c_void_p], C.c_int),
        'ReadProcessMemory': ([C.c_void_p, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)], C.c_int),
        'CloseHandle': ([C.c_void_p], C.c_int),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    owner = int(process._handle)
    inside = C.c_int()
    if kernel.GetProcessId(owner) != process.pid or not kernel.IsProcessInJob(owner, job.handle, C.byref(inside)) or not inside.value:
        raise RuntimeError('retained process/job identity differs')
    thread = kernel.OpenThread(0x4A, False, thread_id)
    if not thread:
        raise C.WinError(C.get_last_error())
    receipt = dict(pid=process.pid, thread_id=thread_id, module_base=hex(module_base), module_size=module_size,
                   suspend_attempted=False, resume_attempted=False, owned_job_validated=True)
    suspended = False
    def read(address, size):
        buffer, copied = C.create_string_buffer(size), C.c_size_t()
        ok = kernel.ReadProcessMemory(owner, address, buffer, size, C.byref(copied))
        return dict(address=hex(address), requested=size, bytes=copied.value,
                    hex=buffer.raw[:copied.value].hex(), success=bool(ok), error=0 if ok else C.get_last_error())
    try:
        if kernel.GetProcessIdOfThread(thread) != process.pid or kernel.GetThreadId(thread) != thread_id:
            raise RuntimeError('owned child thread identity differs')
        receipt['suspend_attempted'] = True
        previous = kernel.SuspendThread(thread)
        receipt['suspend_previous_count'] = previous
        if previous == 0xffffffff:
            raise C.WinError(C.get_last_error())
        suspended = True
        if previous != 0:
            raise RuntimeError('owned child thread was already suspended')
        allocation = C.create_string_buffer(1232+15)
        address = (C.addressof(allocation)+15) & ~15
        C.memset(address, 0, 1232)
        C.c_ulong.from_address(address+48).value = 0x100003  # AMD64 CONTROL|INTEGER.
        if not kernel.GetThreadContext(thread, address):
            raise C.WinError(C.get_last_error())
        fields = ('rax','rcx','rdx','rbx','rsp','rbp','rsi','rdi','r8','r9','r10','r11','r12','r13','r14','r15','rip')
        registers = dict(zip(fields, struct.unpack_from('<17Q', C.string_at(address, 1232), 120)))
        receipt['registers'] = {name: hex(value) for name,value in registers.items()}
        rip, rsp = registers['rip'], registers['rsp']
        receipt['rip_native_rva'] = hex(rip-module_base) if module_base <= rip < module_base+module_size else None
        receipt['code'] = read(max(0, rip-32), 128)
        receipt['stack'] = read(rsp, stack_bytes)
        raw = bytes.fromhex(receipt['stack']['hex'])
        receipt['native_stack_candidates'] = [dict(stack_offset=hex(offset), rva=hex(value-module_base))
            for offset in range(0, len(raw)-7, 8)
            if module_base <= (value := struct.unpack_from('<Q',raw,offset)[0]) < module_base+module_size]
        receipt['limitation'] = 'One register sample and bounded raw stack/code; candidate stack words are not unwound frames.'
    except BaseException as error:
        receipt['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        if suspended:
            receipt['resume_attempted'] = True
            receipt['resume_previous_count'] = kernel.ResumeThread(thread)
            receipt['resume_balanced'] = receipt['resume_previous_count'] == receipt['suspend_previous_count']+1
        kernel.CloseHandle(thread)
    return receipt
