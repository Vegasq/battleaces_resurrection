"""Validate the passive authored crash control; not a game-crash qualification."""
from __future__ import annotations
import re

FAULT = 0xc0000005
ROW = re.compile(r'(before-mode|ready|native-invoke|original-filter) pid=(\d+) thread=(\d+) '
                 r'mainThread=(\d+) code=(\d+) errorMode=(\d+)')


def validate_control(report, final, *, expected_target_sha256):
    """Require an original filter, native caller, per-process policy and real exit."""
    def need(value, reason):
        if not value:
            raise ValueError(reason)
    def integer(value, low=0, high=2**32-1):
        return type(value) is int and low <= value <= high
    need(isinstance(report, dict) and isinstance(final, dict), 'Control records required')
    need(isinstance(expected_target_sha256, str) and re.fullmatch('[0-9a-f]{64}', expected_target_sha256),
         'Explicit authored executable hash required')
    need(report.get('passed') is True and report.get('target_sha256') == expected_target_sha256,
         'Authored executable or owner result differs')
    config = report.get('config', {})
    pid, thread, run_id = config.get('pid'), config.get('mainThread'), config.get('runId')
    need(integer(pid, 1) and integer(thread, 1) and isinstance(run_id, str) and
         re.fullmatch('[0-9a-f]{32}', run_id), 'Owned control identity differs')
    need(report.get('os_error_mode_changed') is True and report.get('exception_filter_replaced_by_probe') is False
         and report.get('game_started') is False, 'Control scope differs')
    sources = report.get('source_before', {})
    need(isinstance(sources, dict) and len(sources) == 4 and sources == report.get('source_after') and
         all(isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v) for v in sources.values()),
         'Control sources changed or are unbound')
    launch = report.get('launch', {})
    need(isinstance(launch, dict), 'Launch receipt required')
    need(launch.get('pid') == pid and launch.get('tid') == thread and
         type(launch.get('resume_previous_count')) is int and launch['resume_previous_count'] == 1 and
         launch.get('forced_cleanup') is False and launch.get('owned_process_reaped') is True and
         launch.get('exit_code') == FAULT and type(launch['exit_code']) is int and
         report.get('exit_code') == FAULT and type(report['exit_code']) is int,
         'Original native termination or launch ownership unproven')
    tracker = report.get('tracker', {})
    need(isinstance(tracker, dict), 'Tracker receipt required')
    need(tracker.get('complete') is True and tracker.get('errors') == [] and
         tracker.get('final_accounting') == {'total': 1, 'active': 0, 'terminated': 0},
         'Complete empty owned job without reporter child required')
    need(all(integer(tracker['final_accounting'][k]) for k in ('total', 'active', 'terminated')),
         'Job counts must be integers')
    records = tracker.get('records', [])
    need(isinstance(records, list) and len(records) == 1, 'Unexpected or missing descendant identity')
    record = records[0]
    need(record.get('pid') == pid and record.get('image') == config.get('image') and
         record.get('image_sha256') == expected_target_sha256 and record.get('in_owned_job') is True and
         integer(record.get('creation_filetime'), 1, 2**64-1), 'Retained original process identity differs')
    exit_ = record.get('exit', {})
    need(isinstance(exit_, dict), 'Retained native exit required')
    need(exit_.get('wait_signaled') is True and exit_.get('exit_code') == FAULT and
         integer(exit_.get('exit_filetime'), record['creation_filetime'], 2**64-1), 'Native exit handle evidence differs')
    log = report.get('native_log')
    need(isinstance(log, str) and len(log) <= 1024, 'Bounded original control journal required')
    rows = [ROW.fullmatch(line) for line in log.splitlines()]
    need(len(rows) == 4 and all(rows), 'Original filter journal incomplete or unexpected return')
    need([row[1] for row in rows] == ['before-mode', 'ready', 'native-invoke', 'original-filter'],
         'Native journal order differs')
    modes = []
    for index, row in enumerate(rows):
        values = [int(row[i]) for i in range(2, 7)]
        need(values[:3] == [pid, thread, thread] and values[3] == (FAULT if index == 3 else 0),
             'Original native journal thread/code differs')
        modes.append(values[4])
    need(all(integer(v) for v in modes) and modes[0] & 2 == 0 and
         modes[1:] == [modes[0] | 2] * 3, 'Only process-local reporting-disable bit may change')
    need(final.get('isError') is not True, 'REA status failed')
    evidence = final.get('structuredContent', {})
    value = evidence.get('normalized_result', {})
    need(evidence.get('operation') == 'frida_session_status' and value.get('pid') == pid and
         value.get('mode') == 'attach' and value.get('state') == 'detached' and
         value.get('messages_truncated') is False, 'Terminal passive observation required')
    messages = value.get('messages', [])
    need(isinstance(messages, list) and len(messages) == 3 and all(m.get('type') == 'send' for m in messages),
         'Unexpected, missing or failed observer events')
    payloads = [m.get('payload', {}) for m in messages]
    need([p.get('kind') for p in payloads] == ['control-ready', 'trigger', 'raise-entry'], 'Observer event order differs')
    for index, payload in enumerate(payloads, 1):
        need(type(payload.get('seq')) is int and payload['seq'] == index and type(payload.get('schema')) is int and payload['schema'] == 1 and
             payload.get('pid') == pid and payload.get('runId') == run_id, 'Observer identity/order differs')
        if index > 1:
            need(payload.get('thread') == thread, 'Observer native main thread differs')
    ready, trigger, raised = [p.get('data', {}) for p in payloads]
    need(ready.get('mainThread') == thread and ready.get('handlerReplaced') is False and
         ready.get('errorModeChangedByObserver') is False and ready.get('targetApisInvoked') is False,
         'Observer is not passive')
    need(trigger == {'target': 'CrashControlInvoke', 'nativeCaller': True, 'mainThread': thread} and
         raised == {'code': FAULT, 'flags': 0, 'count': 0, 'nullArguments': True}, 'Original native exception differs')
    need(trigger['nativeCaller'] is True and integer(trigger['mainThread'], 1) and
         all(integer(raised[k]) for k in ('code', 'flags', 'count')) and raised['nullArguments'] is True,
         'Native exception scalar types differ')
    return dict(passed=True, scope='authored passive original-filter control only', pid=pid,
                native_main_thread=thread, exit_code=FAULT, original_filter_observed=True,
                reporting_disable_bit=2, reporter_children=0, forced_cleanup=False,
                game_crash_qualified=False, full_privacy_qualified=False)
