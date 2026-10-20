"""Summarize a completed passive startup trace without inferring a cause.

Wrapped call intervals include entry-observer work. Task statuses are sampled
sequentially; pump rows are selected samples, not every dispatch. Time before
the first hook is unobserved. Failed/incomplete captures stay unqualified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from client_patch.patcher.startup_tasks import TABLES
from tools import startup_task_evidence


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def task_label(index):
    if index < 12:
        return TABLES[index][0]
    return 'PreMenu WhenAll' if index == 49 else f'LoadAll[{index-12}]'


def analyze(text, *, launch_tick, thread):
    require(type(launch_tick) is int and launch_tick >= 0, 'invalid launch clock')
    proof = startup_task_evidence.evidence(text, thread=thread)
    rows = [json.loads(line.split('STARTUP TASKS ', 1)[1]) for line in text.splitlines()
            if re.match(r'^\[\d+\] STARTUP TASKS \{', line)]
    require(all(row['tick'] >= launch_tick for row in rows) and
            all(a['tick'] <= b['tick'] for a, b in zip(rows, rows[1:])),
            'startup timing precedes launch or reverses its clock')
    by_event = {name: next(row for row in rows if row['event'] == name)
                for name in ('premenu_enter', 'premenu_return', 'other_enter', 'other_return',
                             'whenall_enter', 'whenall_return', 'end')}
    phases = []
    for name in ('premenu', 'other', 'whenall'):
        enter, returned = by_event[name+'_enter'], by_event[name+'_return']
        phases.append(dict(name=name, enter_tick=enter['tick'], return_tick=returned['tick'],
                           interval_ms=returned['tick']-enter['tick']))
    tables = []
    for index in range(12):
        enter = next(row for row in rows if row['event'] == 'table_enter' and row['index'] == index)
        returned = next(row for row in rows if row['event'] == 'table_return' and row['index'] == index)
        tables.append(dict(index=index, label=task_label(index), enter_tick=enter['tick'],
                           return_tick=returned['tick'], interval_ms=returned['tick']-enter['tick']))
    terminals, samples, first_all_succeeded = {}, [], None
    for row in rows:
        if row['event'] != 'snapshot':
            continue
        require(row['phase'] < 6 or all(status >= 0 for status in row['status']),
                'startup sample lost an already captured Task')
        for index, status in enumerate(row['status']):
            require(index not in terminals or status == terminals[index],
                    'startup terminal Task status changed between samples')
            if status >= 5:
                terminals[index] = status
        pending = [dict(index=index, label=task_label(index), status=status)
                   for index, status in enumerate(row['status']) if 0 <= status < 5]
        samples.append(dict(tick=row['tick'], phase=row['phase'], pump=row['pump'], pending=pending))
        if row['status'] == [5]*50 and first_all_succeeded is None:
            first_all_succeeded = row['tick']
    pumps, entering = [], None
    for row in rows:
        if row['event'] == 'pump_enter':
            entering = row
        elif row['event'] == 'pump_return':
            pumps.append(dict(pump=entering['pump'], enter_tick=entering['tick'],
                              return_tick=row['tick'], interval_ms=row['tick']-entering['tick']))
            entering = None
    return dict(scope=__doc__, cause_proven=False, task_statuses_are_atomic=False,
                launch_to_first_hook_ms=by_event['premenu_enter']['tick']-launch_tick,
                instrumented_window_ms=by_event['end']['tick']-by_event['premenu_enter']['tick'],
                after_whenall_return_to_ready_ms=by_event['end']['tick']-by_event['whenall_return']['tick'],
                first_all_succeeded_sample_tick=first_all_succeeded,
                first_all_succeeded_sample_to_ready_ms=by_event['end']['tick']-first_all_succeeded,
                wrapped_call_intervals=phases, wrapped_table_intervals=tables,
                selected_pump_intervals=pumps, task_samples=samples, validated_observation=proof)


def analyze_qualification(text, report):
    require(all(report.get(name) is True for name in
                ('passed', 'natural_exit', 'source_files_unchanged', 'shared_settings_unchanged')) and
            report.get('forced_cleanup') is False and report.get('exit_code') == 0 and
            report.get('installed_diagnostics', {}).get('startup_tasks') is True,
            'completed original startup/Quit qualification required')
    validator_sha = hashlib.sha256(Path(startup_task_evidence.__file__).read_bytes()).hexdigest()
    require(report.get('source_sha256_at_start') == report.get('source_sha256_at_finish') and
            report.get('source_sha256_at_finish', {}).get('tools/startup_task_evidence.py') == validator_sha,
            'startup validator differs from the actual qualification')
    trace = report.get('trace')
    require(isinstance(trace, list) and trace and type(trace[0].get('thread')) is int,
            'qualified original thread is missing')
    result = analyze(text, launch_tick=report.get('launch_tick'), thread=trace[0]['thread'])
    require(result['validated_observation'] == report.get('startup_tasks'),
            'raw startup trace differs from qualified observation')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True, help='completed verify_native_quit output directory')
    parser.add_argument('--output', type=Path, required=True, help='fresh JSON file; existing files are refused')
    args = parser.parse_args()
    report_raw = (args.run/'verification.json').read_bytes()
    native_raw = (args.run/'native.log').read_bytes()
    result = analyze_qualification(native_raw.decode('utf-8'), json.loads(report_raw))
    result['inputs'] = dict(verification_sha256=hashlib.sha256(report_raw).hexdigest(),
                           native_sha256=hashlib.sha256(native_raw).hexdigest(),
                           analyzer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    with args.output.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(result, indent=2)+'\n')
    print(json.dumps({key: result[key] for key in
                     ('cause_proven', 'launch_to_first_hook_ms', 'instrumented_window_ms')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
