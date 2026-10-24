"""Publish a closed crash169 gate and fail promptly on an owned probe refusal.

Windows only: os.rename is atomic and refuses an existing destination. Never
expose the final gate while a writer holds it, or replace a prior authorization.
The native reader retains its exact path/content/owner checks and share mode.
"""
import os
from pathlib import Path
import re
import secrets
import time

ROOT = Path(__file__).resolve().parents[1]
ARM_NAME = 'native-crash169.arm'
AUTHORIZATION = b'BA_NATIVE_CRASH169_AUTHORIZED\n'
FAULT = 0xc0000005


def publish_arm(profile):
    if os.name != 'nt':
        raise RuntimeError('Windows no-replacement rename semantics required')
    profile = Path(profile).resolve(strict=True)
    if (not profile.is_relative_to(ROOT / 'local') or
            profile.parent.name != 'profiles' or
            profile.parent.parent.name != '.battleaces-resurrection' or
            not re.fullmatch(r'nativestest_crash169_[0-9a-f]{12}', profile.name)):
        raise ValueError('Existing owned crash169 profile required')
    target = profile / ARM_NAME
    temporary = profile / ('native-crash169-' + secrets.token_hex(16) + '.tmp')
    created = False
    try:
        with temporary.open('xb') as stream:
            created = True
            stream.write(AUTHORIZATION)
            stream.flush()
            os.fsync(stream.fileno())
        # Same directory, closed writer, no os.replace: an existing gate refuses.
        os.rename(temporary, target)
        return target
    finally:
        if created:
            temporary.unlink(missing_ok=True)


def check_refusal(text):
    refusal = re.search(r'NATIVE CRASH refused: [^\r\n]*', text)
    if refusal:
        code = re.search(r'NATIVE CRASH gate open failed: [^\r\n]*', text)
        detail = (code.group(0) + '; ') if code else ''
        raise RuntimeError(detail + refusal.group(0))


def validate_ready(text, thread, *, saved_mode=32769):
    check_refusal(text)
    if type(saved_mode) is not int or not 0 <= saved_mode < 2**32:
        raise ValueError('Typed saved Windows process error mode required')
    pattern = (r'^\[(\d+)\] NATIVE CRASH ready: version=1 thread=(\d+) recipe=23 '
               rf'mode=3 savedMode={saved_mode} expectedMode=3 managerPresent=([01]) '
               r'managerDisabledChecked=([01]) pendingTreeChecked=([01]) managerAbsent=([01]) '
               r'controllerOnCurrentStack=1 ipcInvalid=6 cursorCallbackRva=801fb0 recursion=0 '
               r'breakOnCrash=0 originalWrapperRva=1484d0 gateRequired=1$')
    rows = re.findall(pattern, text, re.M)
    if (type(thread) is not int or not 0 < thread < 2**32 or len(rows) != 1 or
            text.count('NATIVE CRASH ready:') != 1 or int(rows[0][1]) != thread or
            tuple(rows[0][2:]) not in (('1', '1', '1', '0'), ('0', '0', '0', '1'))):
        raise ValueError('One original-thread recipe23 native preflight required')
    return int(rows[0][0])


def validate_trigger(text, thread, *, saved_mode=32769):
    ready_tick = validate_ready(text, thread, saved_mode=saved_mode)
    rows = re.findall(r'^\[(\d+)\] NATIVE CRASH trigger: version=1 thread=(\d+) '
                      r'category=0 wrapperRva=1484d0 nativeCaller=1 mode=3$', text, re.M)
    if (len(rows) != 1 or text.count('NATIVE CRASH trigger:') != 1 or
            int(rows[0][1]) != thread or int(rows[0][0]) < ready_tick):
        raise ValueError('One matching original-thread crash trigger after readiness required')


def ready_saved_mode(text, thread):
    """Bind this launch's prior mode while retaining the full native preflight."""
    modes = re.findall(r'NATIVE CRASH ready: [^\r\n]* savedMode=(\d+) ', text)
    if len(modes) != 1:
        raise ValueError('One saved-mode preflight required')
    mode = int(modes[0])
    validate_ready(text, thread, saved_mode=mode)
    return mode


def wait_for_crash_exit(child, tracker, read_log, *, timeout=60, saved_mode=32769):
    if type(timeout) not in (int, float) or not 0 < timeout <= 60:
        raise ValueError('Bounded crash exit deadline required')
    deadline = time.monotonic() + timeout
    while True:
        tracker.observe()
        check_refusal(read_log())
        code = child.poll()
        if code is not None:
            # Re-read after the retained process handle signals: final log bytes
            # can arrive between the first read and exit. Refusal beats exit code.
            text = read_log()
            check_refusal(text)
            if code != FAULT:
                raise RuntimeError('Natural native exception exit required')
            validate_trigger(text, child.tid, saved_mode=saved_mode)
            return code
        if time.monotonic() >= deadline:
            raise TimeoutError('Native crash exit deadline exceeded')
        time.sleep(.005)
