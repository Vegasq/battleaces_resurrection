"""Authored closed lifetime logs; no game, GC handle or native execution."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from pathlib import Path

from tools import prediction_visual_lifetime as lifetime
from tools import prediction_visual_correction as visual


MATCHES=['a'*32,'b'*32]


def record(world, client=0):
    return dict(schema=1,event='retired',world=world,match=MATCHES[world-1],frame=725,
        reason='drained',trigger='drain_complete',sampled_us=world*20_000_000+client*100,
        thread=1000+client,owner_thread=1000+client,entries_before=1,pulses_before=0,roots_before=5,
        entries_after=0,pulses_after=0,roots_after=0,movement_world=world,movement_match=MATCHES[world-1],
        worker_world=world,worker_match=MATCHES[world-1],prepared=True,pacing_started=True,
        failed=False,visual_failed=False,end_sent=True,drained=True,match_ended=True,
        abort_pending=False,connected=True)


def world_lines(row):
    match=row['match'];world=row['world']
    return [f'Movement pacing START: match={match} world={world} waitSteadyFrame=1 budget=12',
        f'Movement terminal drain complete: match={match} confirmed=722 physical=725 presented=725 target=725',
        lifetime.PREFIX+json.dumps(row)]


def fixture():
    records=[[record(w,c)for w in (1,2)]for c in (0,1)]
    logs=['\n'.join(line for row in client for line in world_lines(row))for client in records]
    poses=[dict(event='visual_pose',world=w,match=MATCHES[w-1],sampled_us=w*20_000_000-1000)for w in (1,2)]
    return logs,poses


def evaluate(logs=None, poses=None):
    original,original_poses=fixture()
    return lifetime.evaluate(original if logs is None else logs,MATCHES,
                             visual_records=original_poses if poses is None else poses,pids=[4000,5000])


class VisualLifetimeTests(unittest.TestCase):
    def test_both_clients_two_worlds_release_all_roots_before_rematch_and_exit(self):
        result=evaluate();self.assertTrue(result['passed']);self.assertEqual(result['retirements'],4)
        self.assertFalse(result['full_feature_accepted']);self.assertFalse(result['physical_input_accepted'])
        self.assertEqual([c['pid']for c in result['clients']],[4000,5000])
        for client in result['clients']:
            self.assertEqual([w['match']for w in client['worlds']],MATCHES)
            self.assertTrue(all(w['roots_after']==w['entries_after']==w['pulses_after']==0 for w in client['worlds']))

    def test_legitimate_inactive_join_and_frontend_triggers_still_require_drained(self):
        for trigger in ('frontend','publication_inactive','join_inactive'):
            logs,poses=fixture();logs=[s.replace('"drain_complete"',json.dumps(trigger))for s in logs]
            self.assertTrue(evaluate(logs,poses)['passed'])

    def test_missing_duplicate_wrong_thread_and_nonzero_after_counts_refuse(self):
        logs,_=fixture()
        for mutate in [lambda r:r.update(thread=999),lambda r:r.update(owner_thread=0),
            lambda r:r.update(roots_after=1),lambda r:r.update(entries_after=1),lambda r:r.update(pulses_after=1),
            lambda r:r.update(entries_before=True),lambda r:r.update(roots_before=3),
            lambda r:r.update(pulses_before=17),lambda r:r.update(world=True),lambda r:r.update(connected=1),
            lambda r:r.update(extra='unknown')]:
            row=record(1);mutate(row);bad=['\n'.join(world_lines(row)+world_lines(record(2))),logs[1]]
            with self.subTest(mutation=mutate),self.assertRaises(AssertionError):evaluate(bad)
        for bad in (['\n'.join(world_lines(record(1))),logs[1]],[logs[0],logs[1]+'\n'+world_lines(record(2,1))[-1]]):
            with self.assertRaises(AssertionError):evaluate(bad)

    def test_END_and_matchEnded_without_actual_drain_must_keep_visual_owner(self):
        row=record(1);row.update(drained=False)
        self.assertEqual(lifetime.reason(row),'keep')
        with self.assertRaisesRegex(AssertionError,'prematurely'):
            lifetime.rows('\n'.join(world_lines(row)))
        row['reason']='keep'
        with self.assertRaises(AssertionError):lifetime.rows('\n'.join(world_lines(row)))

    def test_fallback_world_disconnect_failure_cannot_substitute_for_normal_retirement(self):
        logs,_=fixture()
        changes=[dict(worker_world=3,worker_match='c'*32),dict(movement_world=3,movement_match='c'*32),
                 dict(prepared=False),dict(pacing_started=False),dict(failed=True),dict(visual_failed=True),
                 dict(abort_pending=True),dict(connected=False),dict(trigger='new_world'),dict(end_sent=False)]
        for change in changes:
            row=record(1);row.update(change);row['reason']=lifetime.reason(row)
            bad=['\n'.join(world_lines(row)+world_lines(record(2))),logs[1]]
            with self.subTest(change=change),self.assertRaises(AssertionError):evaluate(bad)

    def test_stale_clock_old_world_after_new_start_and_drain_order_refuse(self):
        logs,poses=fixture()
        row=record(1);row['sampled_us']=poses[0]['sampled_us']-1
        with self.assertRaises(AssertionError):evaluate(['\n'.join(world_lines(row)+world_lines(record(2))),logs[1]],poses)
        first=world_lines(record(1));second=world_lines(record(2))
        with self.assertRaises(AssertionError):evaluate(['\n'.join(first[:2]+second[:1]+first[2:]+second[1:]),logs[1]])
        with self.assertRaises(AssertionError):evaluate(['\n'.join([first[0],first[2],first[1],*second]),logs[1]])
        bad=record(2);bad['owner_thread']=bad['thread']=999
        with self.assertRaises(AssertionError):evaluate(['\n'.join(first+world_lines(bad)),logs[1]])

    def test_duplicate_json_strict_types_and_finite_schema(self):
        logs,_=fixture()
        with self.assertRaisesRegex(AssertionError,'duplicate'):
            lifetime.rows(logs[0].replace('"schema": 1','"schema": 1, "schema": 1',1))
        with self.assertRaises(AssertionError):lifetime.rows(logs[0].replace('"sampled_us": 20000000','"sampled_us": NaN',1))
        with self.assertRaises(AssertionError):evaluate(['ordinary no lifetime',logs[1]])

    def test_visual_gate_failure_is_not_overridden_by_other_positive_components(self):
        report=dict(passed=True)
        with patch.object(visual,'analyze',side_effect=AssertionError('prediction visual lifetime: missing retirement')):
            visual.finalize(dict(visual_correction=True),report,Path('unused'))
        self.assertFalse(report['passed']);self.assertIn('missing retirement',report['visual_correction']['error'])
        report=dict(passed=False)
        with patch.object(visual,'analyze',return_value=dict(passed=True,lifetime=evaluate())):
            visual.finalize(dict(visual_correction=True),report,Path('unused'))
        self.assertFalse(report['passed'])


if __name__=='__main__':unittest.main()
