"""Validate bounded, passive original startup observations from one native run.

Task states are sequential observations, not an atomic snapshot. Pump entry
without normal return is ambiguous (exception, stall, logging or process loss).
This validator qualifies instrumentation; it does not diagnose a loading cause.
"""
import json
import re

from tools.verify_custom_lobby import require


def evidence(text, *, thread):
    rows = [json.loads(line.split('STARTUP TASKS ', 1)[1])
            for line in text.splitlines() if re.match(r'^\[\d+\] STARTUP TASKS \{', line)]
    require(1 <= len(rows) <= 1602, 'startup trace absent or over budget')
    require([row.get('seq') for row in rows] == list(range(1, len(rows)+1)), 'startup trace sequence incomplete')
    require(all(row.get('thread') == thread and type(row.get('tick')) is int and
                type(row.get('roots')) is int and 0 <= row['roots'] <= 53 for row in rows),
            'startup trace thread/root/tick contract differs')
    ends = [row for row in rows if row.get('event') == 'end']
    require(len(ends) == 1 and ends[0].get('reason') == 'startup_ready' and
            ends[0].get('phase') == 7 and ends[0]['roots'] == 0 and ends[0].get('table_returns') == 12,
            'startup observer did not release all roots at original readiness')
    names = ('premenu_enter', 'premenu_return', 'other_enter', 'other_return', 'whenall_enter', 'whenall_return')
    stages = []
    for phase, name in enumerate(names, 1):
        found = [row for row in rows if row.get('event') == name]
        require(len(found) == 1 and found[0].get('phase') == phase, 'startup original phase incomplete: '+name)
        stages.append(found[0])
    require([row['seq'] for row in stages] == sorted(row['seq'] for row in stages), 'startup phase order differs')
    require(stages[2]['object'] == stages[0]['object'] and stages[4]['object'] == stages[1]['object'],
            'startup original batch/list identities differ')
    for index, (enter, returned) in enumerate(zip(stages[::2], stages[1::2])):
        require(returned.get('entry') == enter['tick'] and returned['tick'] >= enter['tick'],
                'startup original return timing differs: '+str(index))
    table_rows = [row for row in rows if row.get('event') in ('table_enter', 'table_return')]
    require(len(table_rows) == 24, 'startup dispatch/return pairs incomplete')
    for i in range(12):
        enter, returned = table_rows[2*i:2*i+2]
        require(enter.get('event') == 'table_enter' and returned.get('event') == 'table_return' and
                enter.get('index') == returned.get('index') == i and
                enter.get('phase') == returned.get('phase') == 1 and
                stages[0]['seq'] < enter['seq'] < returned['seq'] < stages[1]['seq'] and
                returned.get('entry') == enter['tick'] and returned['tick'] >= enter['tick'] and
                returned.get('method') == enter.get('method') and
                bool(re.fullmatch(r'[0-9A-Fa-f]+', enter.get('method', ''))) and int(enter['method'], 16) != 0 and
                returned['roots'] == i+2,
                'startup table ABI/identity/timing/root evidence differs: '+str(i))
    snapshots = [row for row in rows if row.get('event') == 'snapshot']
    require(snapshots and all(isinstance(row.get('status'), list) and len(row['status']) == 50 and
                all(type(status) is int and -1 <= status <= 7 for status in row['status']) for row in snapshots),
            'startup Task status vector malformed')
    final = snapshots[-1]
    require(final.get('phase') == 7 and final['roots'] == 53 and final['status'] == [5]*50 and
            final['seq'] < ends[0]['seq'], 'startup original tasks/aggregate not all complete before root release')
    # Selected pump entries are persisted before original Exec; exits only after
    # normal return. Readiness may be reached within the final sampled Exec.
    pending_pump = None
    pairs = 0
    for row in rows:
        if row.get('event') == 'pump_enter':
            require(pending_pump is None and row['seq'] > stages[0]['seq'], 'startup pump reentrancy/order differs')
            pending_pump = row
        elif row.get('event') == 'pump_return':
            require(pending_pump is not None and row.get('entry') == pending_pump['tick'] and
                    row['tick'] >= pending_pump['tick'] and row.get('pump') == pending_pump.get('pump'),
                    'startup original pump return missing/mismatched')
            pending_pump = None
            pairs += 1
    require(pairs > 0 and pending_pump is None, 'startup existing pump cadence not qualified')
    require(all(row['event'] == 'pump_return' and row['roots'] == 0 for row in rows if row['seq'] > ends[0]['seq']),
            'startup observer reads persisted after release')
    return dict(scope=__doc__, rows=len(rows), thread=thread, task_count=50, roots_released=True,
                selected_pump_pairs=pairs, elapsed_seconds=(ends[0]['tick']-stages[0]['tick'])/1000,
                stages=[dict(event=row['event'], tick=row['tick'], seq=row['seq']) for row in stages],
                pending_samples=[dict(tick=row['tick'], phase=row['phase'], pump=row['pump'],
                                      indices=[i for i, status in enumerate(row['status']) if 0 <= status < 5])
                                 for row in snapshots if any(0 <= status < 5 for status in row['status'])],
                final_status=final['status'], root_cause_proven=False)
