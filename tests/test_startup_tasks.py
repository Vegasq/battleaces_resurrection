"""Authored trace corruption controls; actual native qualification is separate."""
import copy
import json
import unittest

from tools.startup_task_evidence import evidence


def trace():
    rows = []
    def add(event, phase, roots, **extra):
        row = dict(event=event, tick=100+len(rows), seq=len(rows)+1,
                   thread=17, phase=phase, roots=roots, pump=0)
        row.update(extra)
        rows.append(row)
        return row
    begin = add('premenu_enter', 1, 1, object='1000')
    for i in range(12):
        enter = add('table_enter', 1, i+1, index=i, object='2000', method='1234')
        add('table_return', 1, i+2, index=i, object='3000', method='1234', entry=enter['tick'])
    add('premenu_return', 2, 14, object='4000', entry=begin['tick'])
    other = add('other_enter', 3, 14, object='1000')
    add('other_return', 4, 52, object='5000', entry=other['tick'])
    aggregate = add('whenall_enter', 5, 52, object='4000')
    add('whenall_return', 6, 53, object='6000', entry=aggregate['tick'])
    pump = add('pump_enter', 6, 53, pump=1)
    add('snapshot', 6, 53, pump=1, status=[1]*50)
    add('pump_return', 6, 53, pump=1, entry=pump['tick'])
    add('snapshot', 7, 53, pump=1, status=[5]*50)
    add('end', 7, 0, pump=1, reason='startup_ready', table_returns=12)
    return rows


def render(rows):
    return '\n'.join('[999] STARTUP TASKS '+json.dumps(row) for row in rows)


class StartupTaskEvidenceTests(unittest.TestCase):
    def test_bounded_forwarding_trace_qualifies_observation_only(self):
        result = evidence(render(trace()), thread=17)
        self.assertEqual(result['task_count'], 50)
        self.assertEqual(result['selected_pump_pairs'], 1)
        self.assertTrue(result['roots_released'])
        self.assertFalse(result['root_cause_proven'])
        self.assertEqual(result['pending_samples'][0]['indices'], list(range(50)))

    def test_corrupt_and_incomplete_observations_cannot_qualify(self):
        def matching(rows, event):
            return next(row for row in rows if row['event'] == event)
        changes = {
            'root leak': lambda r: r[-1].update(roots=1),
            'deadline': lambda r: r[-1].update(reason='deadline'),
            'observer failure': lambda r: r[-1].update(reason='observer_error'),
            'missing table': lambda r: matching(r, 'table_return').update(event='lost'),
            'changed MethodInfo': lambda r: matching(r, 'table_return').update(method='5678'),
            'null MethodInfo': lambda r: matching(r, 'table_enter').update(method='0000'),
            'early return': lambda r: matching(r, 'table_return').update(tick=1),
            'wrong thread': lambda r: matching(r, 'pump_enter').update(thread=21),
            'lost pump return': lambda r: matching(r, 'pump_return').update(event='lost'),
            'sequence loss': lambda r: matching(r, 'snapshot').update(seq=99),
            'wrong input list': lambda r: matching(r, 'whenall_enter').update(object='9999'),
            'incomplete aggregate': lambda r: r[-2]['status'].__setitem__(49, 1),
            'faulted table': lambda r: r[-2]['status'].__setitem__(0, 7),
            'unobserved other table': lambda r: r[-2]['status'].__setitem__(40, -1),
            'missing status': lambda r: r[-2].update(status=[5]*49),
            'excess roots': lambda r: matching(r, 'snapshot').update(roots=54),
        }
        for label, change in changes.items():
            with self.subTest(label=label):
                rows = copy.deepcopy(trace())
                change(rows)
                with self.assertRaises((AssertionError, ValueError, RuntimeError)):
                    evidence(render(rows), thread=17)

    def test_readiness_inside_original_exec_pairs_without_reading_released_tasks(self):
        rows = trace()
        returned = rows.pop(-3)
        returned.update(seq=rows[-1]['seq']+1, tick=rows[-1]['tick']+1, roots=0)
        for index, row in enumerate(rows):
            row['seq'] = index+1
        returned['seq'] = len(rows)+1
        rows.append(returned)
        self.assertTrue(evidence(render(rows), thread=17)['roots_released'])
        rows[-1]['event'] = 'snapshot'
        rows[-1]['status'] = [5]*50
        with self.assertRaises((AssertionError, ValueError, RuntimeError)):
            evidence(render(rows), thread=17)
