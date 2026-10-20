"""Verify a bounded REA Frida localhost positive control, never game traffic absence.

Reads retained evidence and authored script/target files only. Does not start,
attach, resume, kill or configure anything. On Windows, optionally verifies that
the one recorded local control PID is terminal using a read-only process handle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re

from tools.frida_control_source import build_request, build_source

REQUIRED = frozenset('ws2_32.dll:' + name for name in ('connect', 'send', 'recv'))
MAX_BYTES = 16 * 1024 * 1024


def windows_path(value):
    if not isinstance(value, str) or not PureWindowsPath(value).is_absolute():
        raise ValueError('An absolute Windows target path is required.')
    return str(PureWindowsPath(value)).casefold()


def verify(value, *, script_sha256, target_path, target_sha256, run_id, positive):
    """Reject incomplete/mixed/error evidence; counts remain observed lower bounds."""
    for sha in (script_sha256, target_sha256):
        if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
            raise ValueError('Expected hashes must be lowercase SHA256.')
    target = windows_path(target_path)
    if not isinstance(run_id, str) or not re.fullmatch('[0-9a-f]{32}', run_id):
        raise ValueError('A fresh lowercase 32-hex control run ID is required.')
    errors = []
    def require(condition, code):
        if not condition:
            errors.append(code)
    report = dict(passed=False, scope='Localhost hook positive control only; not game/network/removal qualification.',
                  script_sha256=script_sha256, selected_target_file_sha256=target_sha256,
                  control_run_id=run_id, observed_counts_lower_bounds={}, errors=errors)
    try:
        identity = value['inputs']
        require(type(identity['schema']) is int and identity['schema'] == 1 and identity['run_id'] == run_id and
                identity['target_sha256'] == target_sha256 and identity['script_sha256'] == script_sha256,
                'input_identity_changed')
        arguments, result = value['arguments'], value['result']
        require(not result.get('isError', False), 'rea_error')
        evidence = result['structuredContent']
        require(evidence['operation'] == 'instrument_with_frida' and
                evidence['predicate_type'] == 'rea.frida.instrumentation-observation' and
                evidence['provider']['id'] == 'frida' and evidence['confidence'] == 'observed', 'wrong_provider_operation')
        require(isinstance(evidence['evidence_id'], str) and bool(re.fullmatch('ev_[0-9a-f]{64}', evidence['evidence_id'])),
                'invalid_evidence_id')
        normalized = evidence['normalized_result']
        canonical = build_request(arguments['program'], str(PureWindowsPath(arguments['path']).parent), run_id)
        require(arguments == canonical, 'noncanonical_control_request')
        generated = build_source(arguments['program'])
        require(script_sha256 in {hashlib.sha256(generated.encode('utf-8')).hexdigest(),
                hashlib.sha256(generated.replace('\n', '\r\n').encode('utf-8')).hexdigest()}, 'noncanonical_observer_source')
        parameters = evidence['parameters']
        require(all(parameters[key] == arguments[key] for key in ('mode', 'device_id', 'program', 'argv')) and
                not parameters.get('remote'), 'provider_request_mismatch')
        require(isinstance(normalized['session_id'], str) and bool(normalized['session_id']) and
                parameters['session_id'] == normalized['session_id'], 'mixed_provider_session')
        require(arguments['mode'] == normalized['mode'] == 'spawn' and
                arguments.get('device_id') == normalized['device_id'] == 'local' and
                not arguments.get('remote'), 'not_local_spawn')
        require(windows_path(arguments['program']) == windows_path(normalized['target']) == target, 'wrong_selected_target')
        require(arguments['argv'][:3] == ['-I', '-B', '-c'] and len(arguments['argv']) == 4, 'wrong_control_argv')
        require(type(arguments['duration_ms']) is int and 1 <= arguments['duration_ms'] <= 600000, 'invalid_duration')
        require(arguments['source_kind'] == normalized['source_kind'] == 'file' and
                windows_path(arguments['path']) == windows_path(normalized['source_path']), 'wrong_script_path')
        require(normalized['source_sha256'] == script_sha256, 'wrong_script_hash')
        require(normalized['state'] == 'detached' and normalized['cleanup_error'] is None, 'not_cleanly_detached')
        require(normalized['messages_truncated'] is False, 'truncated_messages')
        pid = normalized['pid']
        require(type(pid) is int and 0 < pid < 2**32, 'invalid_pid')
        scripts = normalized['scripts']
        require(len(scripts) == 1, 'mixed_scripts')
        script_id = scripts[0]['script_id']
        require(isinstance(script_id, str) and bool(script_id), 'invalid_script_id')
        messages = normalized['messages']
        require(isinstance(messages, list) and 0 < len(messages) <= 4096, 'invalid_message_count')
        previous, offsets, elapsed, ready, positive_seen = {}, {}, -1, False, set()
        for message in messages:
            require(message['script_id'] == script_id and message['type'] == 'send', 'script_error_or_mixed_message')
            row = message['payload']
            require(row['schema'] == 1 and type(row['schema']) is int and row['pid'] == pid and type(row['pid']) is int,
                    'mixed_snapshot_identity')
            require(type(row['elapsedMs']) is int and 0 <= row['elapsedMs'] <= 600000 and
                    elapsed <= row['elapsedMs'], 'unordered_snapshot_time')
            elapsed = row['elapsedMs']
            require(row['errors'] == [], 'hook_setup_error')
            installed = row['installed']
            keys = [entry['key'] for entry in installed]
            require(len(set(keys)) == len(keys), 'duplicate_hook_key')
            active = {entry['key'] for entry in installed if entry.get('alias') is not True}
            for entry in installed:
                if entry.get('alias') is True:
                    continue
                key, offset = entry['key'], entry['offset']
                require(isinstance(offset, str) and bool(re.fullmatch('0x[0-9a-f]{1,16}', offset)), 'invalid_hook_offset')
                require(key not in offsets or offsets[key] == offset, 'hook_offset_changed')
                offsets[key] = offset
            counts = row['counts']
            require(isinstance(counts, dict) and set(counts) == active, 'unattached_or_missing_counter')
            for key, count in counts.items():
                require(isinstance(key, str) and type(count) is int and 0 <= count < 2**53 - 1, 'invalid_or_saturated_counter')
                require(key not in previous or count >= previous[key], 'counter_decreased')
            require(set(previous) <= set(counts), 'counter_disappeared')
            if row['kind'] == 'observer-ready':
                require(not ready and REQUIRED <= active and all(counts[key] == 0 for key in REQUIRED), 'invalid_ready_boundary')
                ready = True
            for key in REQUIRED & counts.keys():
                if counts[key] > 0:
                    require(ready, 'positive_before_ready')
                    positive_seen.add(key)
            previous = counts.copy()
        require(ready and positive_seen == REQUIRED, 'missing_network_positive_control')
        require(isinstance(positive, dict) and positive.get('passed') is True and
                type(positive.get('schema')) is int and positive['schema'] == 1 and
                type(positive.get('pid')) is int and positive['pid'] == pid and positive.get('run_id') == run_id and
                type(positive.get('bytes_sent')) is int and positive['bytes_sent'] == 4 and
                type(positive.get('bytes_received')) is int and positive['bytes_received'] == 2,
                'missing_independent_exchange_receipt')
        report.update(evidence_id=evidence['evidence_id'], pid=pid, snapshots=len(messages),
                      nominal_duration_ms=arguments['duration_ms'], last_message_elapsed_ms=elapsed,
                      observed_counts_lower_bounds=previous,
                      provider_artifact_identity_reported=evidence.get('subject') is not None,
                      provider_environment_reported=evidence.get('environment') is not None,
                      process_exit_or_descendant_cleanup_qualified=False)
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        errors.append('malformed_or_incomplete_evidence')
    report['passed'] = not errors
    return report


def terminal_pid(pid):
    """Inspect this local recorded PID only; never terminate or enumerate targets."""
    import ctypes as c
    from ctypes import wintypes as w
    import os
    if os.name != 'nt':
        raise ValueError('Local process-terminal qualification requires Windows.')
    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.WaitForSingleObject.restype = w.DWORD
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    handle = kernel.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE only.
    if not handle:
        error = c.get_last_error()
        return dict(terminal=error == 87, missing=error == 87, windows_error=error)
    try:
        return dict(terminal=kernel.WaitForSingleObject(handle, 0) == 0, missing=False)
    finally:
        kernel.CloseHandle(handle)


def read_json(path):
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Observation exceeds the 16 MiB bound.')
    return json.loads(path.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('evidence', 'script', 'target', 'positive', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--check-process-terminal', action='store_true')
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    verifier_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report = verify(read_json(args.evidence), script_sha256=hashlib.sha256(args.script.read_bytes()).hexdigest(),
                    target_path=str(args.target.resolve()), target_sha256=hashlib.sha256(args.target.read_bytes()).hexdigest(),
                    run_id=args.run_id, positive=read_json(args.positive))
    if args.check_process_terminal and report['passed']:
        report['recorded_process'] = terminal_pid(report['pid'])
        if not report['recorded_process']['terminal']:
            report['errors'].append('recorded_process_not_terminal')
            report['passed'] = False
    report['verifier_source_sha256'] = verifier_sha
    report['verifier_source_unchanged'] = verifier_sha == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if not report['verifier_source_unchanged']:
        report['errors'].append('verifier_source_changed')
        report['passed'] = False
    with args.output.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
