"""Authored CLI/receipt controls, never original input or game acceptance."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import test_prediction_visual_input as input_tests
from tools import prediction_visual_click as evidence
from tools import verify_prediction_multiplayer as controller
from tools import prediction_visual_correction as visual


def fixture():
    inputs,poses,bindings = input_tests.fixture()
    focuses = input_tests.focuses(inputs)
    records = []
    for world in (1,2):
        sequence = 0
        own = [r for r in inputs if r['world'] == world]
        for episode,source in ((1,own[0]),(2,own[1])):
            down_ticket = 2*episode-1
            point = source['displayed_screen'][:2]
            for index,event in enumerate(evidence.EVENTS):
                sequence += 1
                queued = 1 if index == 0 else 2 if index < 6 else 3
                ordinal = world*100+episode*10+(1 if index == 0 else 2 if index < 6 else 3 if index < 9 else 4)
                held = 2 <= index <= 6
                history_held = 3 <= index <= 7
                row = dict(schema=1,event=event,world=world,match=source['match'],episode=episode,
                    control='zero' if episode == 1 else 'nonzero',sequence=sequence,frontend_ordinal=ordinal,
                    sampled_us=source['policy_us']+3000+index*500,frame=source['frame'],
                    **{k:source[k] for k in ('entity','unit_type','army','incarnation','lease','generation',
                        'thread','owner_thread','focus_ordinal','focus_returned_us',*evidence.POINTERS)},
                    pending_commands=1,current_ids=[source['entity']],preview_ids=[],casting_ids=[],
                    pointer=list(point),queued_point=list(point),physical_input=False,selection_writes=0,
                    history_writes=0,sync_transforms=False,
                    history=dict(id=source['entity'],mode=1 if history_held else 0,primary=history_held,
                        context=False,drag=False,now=10.,last_up=9.5 if 2 <= index <= 7 else 10.,window=.25),
                    mouse=dict(action=hex(world*0x100000+episode*0x1000+0x100),
                        control=hex(world*0x100000+episode*0x1000+0x200),device=hex(world*0x100000+episode*0x1000+0x300),
                        queued_sequence=queued,primary=held,context=False),
                    pose=dict(frame=source['frame'],revision=source['revision'],joined_us=source['joined_us'],
                        policy_us=source['policy_us'],publication_us=source['publication_us'],alpha=source['alpha'],
                        raw=deepcopy(source['raw']),displayed=deepcopy(source['displayed']),offset=deepcopy(source['offset']),
                        actual=deepcopy(source['actual']),root_matches_join=True))
                if event.startswith('callback_'):
                    kind = 'Down' if index < 6 else 'Up'
                    before = event == 'callback_before'
                    row.update(kind=kind,ticket_serial=down_ticket if kind == 'Down' else down_ticket+1,
                        ledger_serial=down_ticket if kind == 'Down' and not before else 0,
                        ledger_completed=None if before else kind == 'Down',single_accepted=kind == 'Down' and not before,
                        method_info=hex(world*0x1000000+(0x1000 if kind == 'Down' else 0x2000)),
                        dispatch_thunk=hex(0x180010000 if kind == 'Down' else 0x180020000),
                        method_token=evidence.METHODS[kind][0],method_rva=evidence.METHODS[kind][1],
                        context_pointer=hex(world*0x1000000+(0x3000 if kind == 'Down' else 0x4000)))
                    if index == 2:
                        row['hit_test'] = dict(point=list(point),raw_point=source['raw_screen'][:2],viewport=source['viewport'],
                            inside=True,raw_inside=True,displayed=deepcopy(source['displayed_ray']),
                            raw=deepcopy(source['raw_ray']),discriminates=source['ray_discriminates'])
                if event.startswith('process_'):
                    row.update(ticket_serial=down_ticket,down_method_info=hex(world*0x1000000+0x1000),
                        method_info='0x0',method_rva='0x3bf4a60',original_entry='0x143bf4a60',
                        context_pointer=hex(world*0x1000000+0x3000))
                if event == 'closed': row.update(roots_before=15,roots_after=0,balanced=True)
                records.append(row)
    return records,poses,bindings,focuses


def log(records):
    return '\n'.join('[1] '+evidence.PREFIX+json.dumps(r,separators=(',',':')) for r in records)


def evaluate(records=None,poses=None):
    data,original,bindings,focuses = fixture()
    return evidence.evaluate(evidence.rows(log(data if records is None else records)),
        original if poses is None else poses,bindings,focus_records=focuses)


class VisualClickPlan(unittest.TestCase):
    def setUp(self):
        self.fixture = input_tests.VisualInputPlan()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.args = self.fixture.args
        self.args.visual_click = True
        helper = Path(self.args.game)/'BattleAcesOffline.dll'
        helper.write_bytes(helper.read_bytes()+evidence.MARKER+b'\0'+evidence.PREFIX.encode()+
                           '-prediction-visual-click-smoke'.encode('utf-16-le'))
        self.args.expected_helper_sha256 = controller.sha(helper)
        for path in (Path(self.args.game)/'.battleaces-resurrection/patch-manifest.json',self.args.helper_build_receipt):
            value = json.loads(path.read_text()); value['helper_sha256'] = self.args.expected_helper_sha256
            path.write_text(json.dumps(value))

    def test_explicit_click_flag_is_subject_only_and_prepared_roundtrip_is_strict(self):
        plan = controller.prepare(self.args)
        self.assertIs(plan['visual_click'],True)
        self.assertEqual(controller.verify_prepared(self.args.output),plan)
        subject = controller.command_extra(plan,0,self.args.output/'run')
        peer = controller.command_extra(plan,1,self.args.output/'run')
        self.assertEqual(subject.count('-prediction-visual-click-smoke'),1)
        self.assertNotIn('-prediction-visual-click-smoke',peer)
        old = deepcopy(plan); old.pop('visual_click')
        self.assertEqual([a for a in subject if a != '-prediction-visual-click-smoke'],
                         controller.command_extra(old,0,self.args.output/'run'))
        for change in (dict(visual_click=1),dict(visual_input=False),dict(visual_correction=False),dict(move_slot=1)):
            with self.subTest(change=change), self.assertRaises(AssertionError): evidence.validate_plan(dict(plan,**change))
        broken = dict(plan,visual_input=False)
        (self.args.output/'invocation.json').write_text(json.dumps(broken))
        with self.assertRaises(AssertionError): controller.verify_prepared(self.args.output)

    def test_absent_click_preserves_default_argv_and_missing_capability_fails(self):
        self.args.visual_click = False
        plan = controller.prepare(self.args)
        self.assertNotIn('visual_click',plan)
        self.assertNotIn('-prediction-visual-click-smoke',controller.command_extra(plan,0,self.args.output/'run'))
        evidence.helper(False,b'ordinary')
        for value in (b'ordinary',evidence.MARKER,evidence.MARKER+evidence.PREFIX.encode()):
            with self.subTest(value=value), self.assertRaises(AssertionError): evidence.helper(True,value)
        args = deepcopy(self.args); args.visual_click = True; args.visual_input = False
        with self.assertRaisesRegex(AssertionError,'visual-input'):
            evidence.option(args,650,args.native_position_trace,dict(direction='client_to_server',extra_ms=100,duration_ms=250))


class VisualClickRecords(unittest.TestCase):
    def test_genuine_zero_and_nonzero_callbacks_process_returns_up_and_balanced_close(self):
        result = evaluate()
        self.assertTrue(result['passed'])
        self.assertEqual(result['status'],'qualified')
        self.assertFalse(result['physical_input_accepted'])
        self.assertFalse(result['commands_accepted'])
        self.assertFalse(result['full_feature_accepted'])
        for world in result['worlds']:
            self.assertEqual([e['control'] for e in world['episodes']],['zero','nonzero'])
            for episode in world['episodes']:
                self.assertTrue(episode['original_process_returned'])
                self.assertFalse(episode['up_ledger_completed'])
                self.assertFalse(episode['up_single_accepted'])
                self.assertEqual((episode['roots_before'],episode['roots_after']),(15,0))

    def test_missing_closed_or_nested_process_is_never_qualified(self):
        data,_,_,_ = fixture()
        self.assertFalse(evaluate(data[:-1])['passed'])
        missing = [r for r in data if r['event'] not in ('process_before','process_returned')]
        for world in (1,2):
            for sequence,row in enumerate([r for r in missing if r['world'] == world],1): row['sequence'] = sequence
        self.assertFalse(evaluate(missing)['passed'])

    def test_wrong_method_borrowed_context_mouse_root_and_selection_refusals(self):
        data,_,_,_ = fixture()
        cases = [(2,lambda r:r.update(method_token='0x06000000')),
                 (3,lambda r:r.update(method_info='0x1000')),
                 (4,lambda r:r.update(context_pointer='0x8000')),
                 (5,lambda r:r.update(ledger_completed=False)),
                 (5,lambda r:r.update(ledger_serial=999)),
                 (5,lambda r:r.update(single_accepted=False)),
                 (5,lambda r:r['mouse'].update(primary=False)),
                 (8,lambda r:r.update(current_ids=[0])),
                 (8,lambda r:r['mouse'].update(primary=True)),
                 (9,lambda r:r.update(roots_after=1)),
                 (9,lambda r:r['history'].update(drag=True))]
        for index,mutate in cases:
            bad = deepcopy(data); mutate(bad[index])
            with self.subTest(index=index,mutation=mutate),self.assertRaises(AssertionError): evaluate(bad)

    def test_down_before_released_expired_single_precondition_and_delivered_up(self):
        data,_,_,_ = fixture()
        cases = [(2,lambda r:r['history'].update(primary=True)),
                 (2,lambda r:r['history'].update(context=True)),
                 (2,lambda r:r['history'].update(drag=True)),
                 (2,lambda r:r['history'].update(last_up=r['history']['now'])),
                 (2,lambda r:r['history'].update(last_up=r['history']['now']-.25)),
                 (2,lambda r:r['mouse'].update(primary=False)),
                 (7,lambda r:r['mouse'].update(primary=True))]
        for index,mutate in cases:
            bad = deepcopy(data);mutate(bad[index])
            with self.subTest(index=index,mutation=mutate),self.assertRaises(AssertionError): evaluate(bad)

    def test_queue_receipts_are_not_delivery_and_callback_queue_delta_is_exact(self):
        data,_,_,_ = fixture()
        for index,key,value in ((2,'sampled_us',data[1]['sampled_us']),
                                (6,'frontend_ordinal',data[1]['frontend_ordinal']),
                                (9,'frontend_ordinal',data[6]['frontend_ordinal']),
                                (7,'ticket_serial',data[2]['ticket_serial']),
                                (5,'pending_commands',2)):
            bad = deepcopy(data); bad[index][key] = value
            with self.subTest(index=index,key=key),self.assertRaises(AssertionError): evaluate(bad)
        bad = deepcopy(data); bad[2]['mouse']['queued_sequence'] = 1
        with self.assertRaises(AssertionError): evaluate(bad)
        bad = deepcopy(data); bad[7]['queued_point'][0] += 1
        with self.assertRaises(AssertionError): evaluate(bad)

    def test_press_cannot_retarget_the_already_consumed_position_event(self):
        data,_,_,_ = fixture()
        # Actual86's logged original position event and newly reprojected press.
        consumed = [499.18545532226562,282.197265625]
        retargeted = [499.34808349609375,282.3006591796875]
        bad = deepcopy(data)
        bad[0]['queued_point'] = consumed
        bad[1]['pointer'] = consumed
        for row in bad[1:10]: row['queued_point'] = list(retargeted)
        for row in bad[2:10]: row['pointer'] = list(retargeted)
        bad[2]['hit_test']['point'] = list(retargeted)
        bad[2]['hit_test']['raw_point'] = list(retargeted)
        # Every callback can otherwise be internally consistent with the new
        # point; it still is not the position event actually consumed first.
        with self.assertRaisesRegex(AssertionError,'position|immutable'):
            evaluate(bad)

    def test_callback_time_pose_identity_lease_clock_and_original_join_are_exact(self):
        data,_,_,_ = fixture()
        cases = [lambda r:r.update(incarnation=999),lambda r:r.update(lease=999),
            lambda r:r.update(owner_thread=999),lambda r:r.update(actor='0xf000'),
            lambda r:r.update(focus_ordinal=999),lambda r:r['pose'].update(policy_us=r['pose']['policy_us']+1),
            lambda r:r['pose'].update(publication_us=r['pose']['publication_us']-1),
            lambda r:r['pose'].update(alpha=.5),lambda r:r['pose'].update(actual=[0.,0.,0.]),
            lambda r:r.update(sampled_us=r['pose']['joined_us']+50001)]
        for mutate in cases:
            bad = deepcopy(data); mutate(bad[12])
            with self.subTest(mutation=mutate),self.assertRaises(AssertionError): evaluate(bad)

    def test_faithful_offscreen_miss_or_nondiscrimination_is_inconclusive(self):
        data,_,_,_ = fixture()
        bad = deepcopy(data); hit=bad[12]['hit_test']
        hit['raw_point'][0] = 2.;hit['raw_inside'] = False
        self.assertFalse(evaluate(bad)['passed'])
        # False bool with a retained out-object is a legitimate raw observation.
        bad = deepcopy(data);bad[12]['hit_test']['raw']['identity'] = deepcopy(bad[12]['hit_test']['displayed']['identity'])
        self.assertTrue(evaluate(bad)['passed'])
        bad = deepcopy(data); hit=bad[12]['hit_test']
        hit['raw'] = deepcopy(hit['displayed']); hit['discriminates'] = False
        self.assertFalse(evaluate(bad)['passed'])
        bad = deepcopy(data); hit=bad[12]['hit_test']
        hit['displayed'] = dict(hit=False,identity=None);hit['discriminates'] = False
        self.assertFalse(evaluate(bad)['passed'])

    def test_strict_fields_booleans_global_world_order_and_duplicate_json(self):
        data,_,_,_ = fixture()
        cases = [lambda r:r.update(physical_input=True),lambda r:r.update(selection_writes=1),
            lambda r:r.update(history_writes=1),lambda r:r.update(sync_transforms=True),
            lambda r:r.update(sequence=True),lambda r:r.update(thread=True),
            lambda r:r.update(extra='unknown'),lambda r:r['pose'].update(offset=[float('nan'),0,0])]
        for mutate in cases:
            bad = deepcopy(data);mutate(bad[2])
            with self.subTest(mutation=mutate),self.assertRaises((AssertionError,ValueError)): evidence.rows(log(bad))
        with self.assertRaisesRegex(AssertionError,'duplicate'):
            evidence.rows(log(data).replace('"schema":1','"schema":1,"schema":1',1))
        with self.assertRaises(AssertionError): evidence.rows(log([data[0],data[20],data[1]]))
        with self.assertRaises(AssertionError): evidence.rows(log(data)+'\n'+evidence.FAILURE+' rejected')


class VisualClickFinalization(unittest.TestCase):
    def test_closed_wrapper_binds_actual_capture_hashes_source_snapshots_and_peer_exclusion(self):
        records,poses,bindings,focuses = fixture()
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)/'run';run.mkdir()
            body = '\n'.join(visual.PREFIX+json.dumps(r) for r in poses)+'\n'+log(records)+'\n'+\
                '\n'.join(evidence.queries.FOCUS_PREFIX+json.dumps(r) for r in focuses)
            (run/'native-0.log').write_text(body,encoding='utf-8');(run/'native-1.log').write_text('',encoding='utf-8')
            source = {}
            for name in evidence.PRODUCERS:
                path = run.parent/'source-at-prepare'/name;path.parent.mkdir(parents=True,exist_ok=True)
                raw = ('authored producer '+name).encode();path.write_bytes(raw)
                source[name] = evidence.hashlib.sha256(raw).hexdigest()
            for module in (evidence,evidence.queries,visual,evidence.motion):
                source['tools/'+Path(module.__file__).name] = evidence.motion.sha(module.__file__)
            hashes = {str(run/name):evidence.motion.sha(run/name) for name in ('native-0.log','native-1.log')}
            report = dict(passed=True,native_position_trace=dict(worlds=[dict(binding=b) for b in bindings]),
                          visual_input_witness_passed=True,visual_input=dict(input_sha256=hashes))
            plan = dict(visual_click=True,source_sha256=source)
            with patch.object(evidence,'validate_plan'),patch.object(visual,'parent_gate'),\
                 patch.object(evidence.queries,'gate',return_value=True):
                result = evidence.analyze(plan,report,run)
                self.assertTrue(result['passed']);self.assertEqual(result['input_sha256'],hashes)
                self.assertEqual(result['producer_sha256'],{k:source[k] for k in evidence.PRODUCERS})
                wrong = deepcopy(source);wrong[evidence.PRODUCERS[0]]='f'*64
                with self.assertRaisesRegex(AssertionError,'producer differs'):
                    evidence.analyze(dict(plan,source_sha256=wrong),report,run)
                (run/'native-1.log').write_text(evidence.PREFIX+json.dumps(records[0]),encoding='utf-8')
                with self.assertRaisesRegex(AssertionError,'peer'):
                    evidence.analyze(plan,report,run)

    def test_parent_failure_preserves_observations_and_default_path_is_unchanged(self):
        data,_,_,_ = fixture()
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder);(run/'native-0.log').write_text(log(data));(run/'native-1.log').write_text('')
            report = dict(passed=False)
            with patch.object(evidence,'analyze',side_effect=AssertionError('parent failed')):
                evidence.finalize(dict(visual_click=True),report,run)
            self.assertFalse(report['passed']);self.assertFalse(report['visual_click_witness_passed'])
            self.assertEqual(report['visual_click']['preserved_observations'],evidence.rows(log(data)))
        report = dict(passed=True);evidence.finalize({},report,Path('unused'))
        self.assertEqual(report,dict(passed=True));self.assertTrue(evidence.gate({},report))

    def test_persisted_proof_requires_nested_callbacks_and_unchanged_parents(self):
        proof = evaluate();proof.update(parent_gates_passed=True)
        logs = {'native-0.log':'0'*64,'native-1.log':'1'*64}
        source = {name:'a'*64 for name in evidence.PRODUCERS}
        proof.update(input_sha256=logs,producer_sha256=source)
        report = dict(passed=True,visual_click=proof,visual_correction=dict(worlds=[dict(binding=w['binding']) for w in proof['worlds']]),
            visual_input=dict(input_sha256=deepcopy(logs),worlds=[dict(focus=deepcopy(f)) for f in proof['focus_records']]))
        plan = dict(visual_click=True,visual_input=True,visual_correction=True,source_sha256=source)
        with patch.object(evidence,'validate_plan'),patch.object(visual,'parent_gate'),patch.object(evidence.queries,'gate',return_value=True):
            self.assertTrue(evidence.gate(plan,report))
            for remove in ('records','episodes','binding'):
                bad = deepcopy(report);bad['visual_click']['worlds'][0].pop(remove)
                self.assertFalse(evidence.gate(plan,bad))
            bad = deepcopy(report);bad['visual_click'].pop('joined_visual_poses')
            self.assertFalse(evidence.gate(plan,bad))
            for field in ('input_sha256','producer_sha256','focus_records'):
                bad=deepcopy(report);bad['visual_click'].pop(field)
                self.assertFalse(evidence.gate(plan,bad))
            bad=deepcopy(report);bad['visual_click']['input_sha256']['native-0.log']='f'*64
            self.assertFalse(evidence.gate(plan,bad))
            bad=deepcopy(report);bad['visual_click']['focus_records'][0]['frontend_ordinal']+=1
            self.assertFalse(evidence.gate(plan,bad))
        self.assertFalse(evidence.gate(plan,report))


if __name__ == '__main__': unittest.main()
