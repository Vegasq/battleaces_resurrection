"""Authored stage1 query receipts; no game, renderer, input or native loads."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_prediction_visual_correction import authored
from tests import test_prediction_input_delay_controller as delay_tests
from tools import prediction_visual_input as evidence, prediction_visual_correction as visual
from tools import prediction_correction_motion as motion, verify_prediction_multiplayer as controller


def fixture():
    inputs=[];poses=[];bindings=[];ordinal=0
    for world in (1,2):
        data=authored(world);bindings.append(data['binding']);poses.extend(data['records'])
        selected=[next(p for p in data['records']if p['event']=='visual_pose'and p['frame']==f and p['alpha']==a)
                  for f,a in ((520,0.),(535,1.),(536,1.),(650,1.))]
        pointers={k:hex(world*0x10000+(index+1)*0x1000)for index,k in enumerate(sorted(evidence.POINTERS))}
        focus_pose=next(p for p in data['records']if p['event']=='visual_pose'and p['frame']==510 and p['alpha']==1.)
        ordinal+=1;focus_ordinal=ordinal;focus_returned=focus_pose['sampled_us']+7000
        for index,p in enumerate(selected):
            ordinal+=1;zero=index in (0,3);offset=motion.sub(p['displayed'],p['raw'])
            target=dict(entity=74,unit_type=1,army=0,incarnation=75,lease=10+world,
                        actor=pointers['actor'],transform=pointers['transform'])
            raw_screen=[600.,360.,80.];screen=motion.vec([600+offset[0]*20,360+offset[2]*20,80.])
            inputs.append(dict(schema=1,event='query',scope='original_frontend_queries',**data['binding'],
                lease=10+world,generation=world+100,revision=0 if index==0 else 2 if index==3 else 1,
                frame=p['frame'],frontend_ordinal=ordinal,policy_us=p['sampled_us'],
                joined_us=p['sampled_us']+1000,sampled_us=p['sampled_us']+6000,
                query_end_us=p['sampled_us']+7000,publication_us=p['publication_us'],alpha=p['alpha'],
                focus_ordinal=focus_ordinal,focus_frame=510,focus_returned_us=focus_returned,thread=1000,owner_thread=1000,
                **pointers,offset=offset,raw=list(p['raw']),displayed=list(p['displayed']),actual=list(p['transform']),
                root_matches_join=True,displayed_screen=screen,raw_screen=raw_screen,viewport=[1280,720],
                displayed_inside=True,raw_inside=True,drag_rect_half_pixels=3,drag_mode=2,
                displayed_ray=dict(hit=True,identity=target),raw_ray=dict(hit=zero,identity=deepcopy(target)if zero else None),
                displayed_drag=True,raw_drag=zero,ray_discriminates=not zero,drag_discriminates=not zero,
                control='zero_before'if index==0 else 'zero_after'if index==3 else 'nonzero',
                physical_input=False,selection_writes=0,sync_transforms=False))
    return inputs,poses,bindings


def focuses(records):
    result=[]
    for world in dict.fromkeys(r['world']for r in records):
        row=next(r for r in records if r['world']==world)
        data=authored(world);p=next(p for p in data['records']if p['event']=='visual_pose'and p['frame']==510 and p['alpha']==1.)
        result.append(dict(schema=1,event='focus_returned',scope='original_camera_acquisition',**data['binding'],
            frame=510,lease=row['lease'],generation=row['generation'],frontend_ordinal=row['focus_ordinal'],
            started_us=p['sampled_us']+6000,returned_us=p['sampled_us']+7000,checked_us=p['sampled_us']+7500,
            joined_us=p['sampled_us']+1000,policy_us=p['sampled_us'],publication_us=p['publication_us'],alpha=p['alpha'],
            thread=1000,owner_thread=1000,**{k:row[k]for k in evidence.POINTERS},
            raw=list(p['raw']),displayed=list(p['displayed']),offset=[0.,0.,0.],actual_before=list(p['transform']),actual_after=list(p['transform']),
            screen_before=[900.,500.,80.],screen_after=[640.,360.,80.],viewport=list(row['viewport']),
            method_token='0x060015ec',method_rva='0x3e9e310',camera_calls=1,settle_us=200000,
            physical_input=False,selection_writes=0,sync_transforms=False))
    return result


def log(rows):
    focus={r['world']:r for r in focuses(rows)};seen=set();lines=[]
    for row in rows:
        if row['world']not in seen:
            lines.append(evidence.FOCUS_PREFIX+json.dumps(focus[row['world']]));seen.add(row['world'])
        lines.append('[1] '+evidence.PREFIX+json.dumps(row,separators=(',',':')))
    return '\n'.join(lines)
def evaluate(rows=None):
    data,poses,bindings=fixture()
    data=data if rows is None else rows
    return evidence.evaluate(evidence.rows(log(data)),poses,bindings,focus_records=evidence.focus_rows(log(data)))


class VisualInputRecords(unittest.TestCase):
    def test_paired_zero_nonzero_zero_queries_join_real_policy_rows(self):
        result=evaluate();self.assertTrue(result['passed']);self.assertEqual(result['status'],'qualified')
        self.assertFalse(result['physical_input_accepted']);self.assertFalse(result['callback_accepted'])
        self.assertFalse(result['commands_accepted']);self.assertFalse(result['full_feature_accepted'])
        self.assertEqual([w['nonzero_queries']for w in result['worlds']],[2,2])
        self.assertTrue(all(w['ray_discriminating_ordinals']and w['drag_discriminating_ordinals']for w in result['worlds']))
        self.assertEqual([w['maximum_query_cost_us']for w in result['worlds']],[1000,1000])

    def test_faithful_misses_false_with_out_unit_and_nondiscrimination(self):
        data,_,_=fixture()
        # Original false bool can still carry an out Unit. Do not rewrite it.
        data[1]['raw_ray']['identity']=deepcopy(data[1]['displayed_ray']['identity'])
        self.assertTrue(evaluate(data)['passed'])
        for row in data:
            if row['control']=='nonzero':
                row['raw_ray']=deepcopy(row['displayed_ray']);row['ray_discriminates']=False
                row['raw_drag']=True;row['drag_discriminates']=False
        proof=evaluate(data);self.assertFalse(proof['passed']);self.assertEqual(proof['status'],'inconclusive')
        self.assertIn('no discriminating nonzero ray comparison',proof['worlds'][0]['missing_gates'])
        data,_,_=fixture();data[1]['displayed_ray']=dict(hit=False,identity=None)
        data[1]['ray_discriminates']=False
        self.assertFalse(evaluate(data)['passed'])

    def test_offscreen_and_incomplete_controls_are_inconclusive_without_threshold_change(self):
        data,_,_=fixture();data[1]['displayed_screen'][0]=2.;data[1]['displayed_inside']=False
        self.assertFalse(evaluate(data)['passed'])
        self.assertFalse(evaluate([r for r in data if r['control']!='zero_after'])['passed'])

    def test_schema_duplicate_types_scope_pointer_and_actual_root_negatives(self):
        data,_,_=fixture()
        mutations=[lambda r:r.update(world=True),lambda r:r.update(frontend_ordinal=True),
            lambda r:r.update(actor='0x0'),lambda r:r.update(manager='0xfffffffffffffffff'),
            lambda r:r.update(transform=r['actor']),lambda r:r.update(physical_input=True),
            lambda r:r.update(selection_writes=True),lambda r:r.update(sync_transforms=True),
            lambda r:r.update(root_matches_join=False),lambda r:r.update(actual=[1.,2.,3.]),
            lambda r:r.update(displayed_inside=False),lambda r:r.update(viewport=[True,720]),
            lambda r:r.update(drag_rect_half_pixels=3.),lambda r:r.update(offset=[float('nan'),0,0]),
            lambda r:r.update(ray_discriminates=False),lambda r:r.update(extra='unknown')]
        mutations.append(lambda r:r['displayed_ray']['identity'].update(lease=0))
        for mutate in mutations:
            bad=deepcopy(data);mutate(bad[1])
            with self.subTest(mutation=mutate),self.assertRaises((AssertionError,ValueError)):
                evidence.rows(log(bad))
        duplicated=log(data).replace('"schema":1','"schema":1,"schema":1',1)
        with self.assertRaisesRegex(AssertionError,'duplicate'):evidence.rows(duplicated)
        with self.assertRaisesRegex(AssertionError,'producer failed'):evidence.rows(log(data)+'\n'+evidence.FAILURE+' original exception')

    def test_clock_freshness_global_order_world_lifetime_and_exact_policy_binding(self):
        data,poses,bindings=fixture()
        for key,value in [('joined_us',data[1]['policy_us']-1),('query_end_us',data[1]['sampled_us']-1),
                          ('sampled_us',data[1]['joined_us']+50001),('frontend_ordinal',data[0]['frontend_ordinal'])]:
            bad=deepcopy(data);bad[1][key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):evidence.rows(log(bad))
        with self.assertRaises(AssertionError):evidence.rows(log([data[0],data[4],data[1]]))
        for mutate in [lambda r:r.update(policy_us=r['policy_us']+1),lambda r:r.update(publication_us=r['publication_us']-1),
                       lambda r:r.update(alpha=.5),lambda r:r.update(generation=999),
                       lambda r:r.update(selector='0xf000'),lambda r:r.update(revision=0)]:
            bad=deepcopy(data);mutate(bad[2])
            with self.subTest(mutation=mutate),self.assertRaises(AssertionError):
                evidence.evaluate(evidence.rows(log(bad)),poses,bindings,focus_records=evidence.focus_rows(log(bad)))

    def test_revision_frame_control_bounds_and_zero_tail(self):
        data,poses,bindings=fixture()
        bad=deepcopy(data);bad[3]['frame']=644
        with self.assertRaises(AssertionError):evidence.rows(log(bad))
        bad=deepcopy(data);bad[1]['offset']=[.499999,0,0]
        with self.assertRaisesRegex(AssertionError,'0.5'):evidence.rows(log(bad))
        bad=deepcopy(data);bad[1]['frame']=bad[0]['frame']
        with self.assertRaises(AssertionError):evidence.evaluate(evidence.rows(log(bad)),poses,bindings,focus_records=evidence.focus_rows(log(bad)))
        # Managed addresses may be reused in a DIFFERENT world; world/token/lease
        # and generation, rather than pointer inequality, own the binding.
        other=deepcopy(data)
        for row in other[4:]:
            for key in evidence.POINTERS:row[key]=data[0][key]
            for name in ('displayed_ray','raw_ray'):
                if row[name]['identity']:
                    for key in ('actor','transform'):row[name]['identity'][key]=data[0][key]
        self.assertTrue(evaluate(other)['passed'])

    def test_existing_visual_parser_ignores_only_new_stage_prefix(self):
        data,poses,_=fixture()
        combined='\n'.join(visual.PREFIX+json.dumps(r)for r in poses)+'\n'+log(data)
        self.assertEqual(len(visual.rows(combined)),len(poses))
        self.assertEqual(len(evidence.rows(combined)),len(data))

    def test_one_original_camera_acquisition_precedes_settled_query_episode(self):
        data,poses,bindings=fixture();foci=evidence.focus_rows(log(data))
        self.assertEqual(len(foci),2);self.assertEqual([r['frame']for r in foci],[510,510])
        result=evidence.evaluate(evidence.rows(log(data)),poses,bindings,focus_records=foci)
        self.assertTrue(result['passed'])
        for world in result['worlds']:
            self.assertEqual(world['focus']['camera_calls'],1)
            self.assertTrue(all(r['sampled_us']-world['focus']['returned_us']>=200000 for r in world['records']))
        self.assertTrue(evidence._saved_focus(result['worlds'][0]))
        broken=deepcopy(result['worlds'][0]);broken.pop('focus')
        with self.assertRaises(KeyError):evidence._saved_focus(broken)
        broken=deepcopy(result['worlds'][0]);broken['records'][0]['focus_returned_us']+=1
        with self.assertRaises(AssertionError):evidence._saved_focus(broken)

    def test_missing_duplicate_or_wrong_original_focus_proof_refuses(self):
        data,poses,bindings=fixture();parsed=evidence.rows(log(data));foci=evidence.focus_rows(log(data))
        for wrong in ([],foci[:1],foci+[foci[0]]):
            with self.assertRaises(AssertionError):evidence.evaluate(parsed,poses,bindings,focus_records=wrong)
        for mutation in (lambda f:f.update(method_token='0x06000000'),lambda f:f.update(camera_calls=2),
                         lambda f:f.update(actual_after=[1.,2.,3.]),lambda f:f.update(frame=512),
                         lambda f:f.update(owner_thread=999),lambda f:f.update(selection_writes=1),
                         lambda f:f.update(offset=[.1,0,0]),lambda f:f.update(physical_input=True)):
            bad=deepcopy(foci);mutation(bad[0])
            with self.subTest(mutation=mutation),self.assertRaises(AssertionError):
                evidence.focus_rows('\n'.join(evidence.FOCUS_PREFIX+json.dumps(f)for f in bad))
        bad=deepcopy(foci);bad[0]['policy_us']+=1
        with self.assertRaises(AssertionError):evidence.evaluate(parsed,poses,bindings,focus_records=bad)

    def test_camera_owner_settle_timestamp_and_focus_ordinal_cannot_be_substituted(self):
        data,poses,bindings=fixture();foci=evidence.focus_rows(log(data))
        for mutation in (lambda r:r.update(focus_returned_us=r['focus_returned_us']+1),
                         lambda r:r.update(focus_ordinal=r['focus_ordinal']+1),
                         lambda r:r.update(camera='0xf000'),lambda r:r.update(focus_frame=511),
                         lambda r:r.update(thread=999),lambda r:r.update(focus_returned_us=r['sampled_us']-199999)):
            bad=deepcopy(data);mutation(bad[0])
            with self.subTest(mutation=mutation),self.assertRaises(AssertionError):
                evidence.evaluate(evidence.rows(log(bad)),poses,bindings,focus_records=foci)


class VisualInputPlan(unittest.TestCase):
    def setUp(self):
        self.fixture=delay_tests.InputDelayPreparationTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        from tests.test_prediction_visual_correction import pin_unityplayer_fixture
        pin_unityplayer_fixture(self,self.fixture.args)
        self.args=self.fixture.args;self.args.visual_correction=True;self.args.visual_input=True
        helper=Path(self.args.game)/'BattleAcesOffline.dll'
        helper.write_bytes(helper.read_bytes()+b'OfflinePredictionVisualJoin\0'+b'PREDICTION VISUAL INPUT '+b'VISUAL INPUT FOCUS '+
            b''.join(flag.encode('utf-16-le')for flag in ('-prediction-visual-correction','-prediction-visual-observe',
                '-prediction-presentation-stages','-prediction-visual-input-smoke')))
        self.args.expected_helper_sha256=controller.sha(helper)
        for path in (Path(self.args.game)/'.battleaces-resurrection/patch-manifest.json',self.args.helper_build_receipt):
            value=json.loads(path.read_text());value['helper_sha256']=self.args.expected_helper_sha256
            path.write_text(json.dumps(value))

    def test_prepare_subject_only_flag_and_prepared_mutation_refusals(self):
        plan=controller.prepare(self.args);self.assertIs(plan['visual_input'],True)
        self.assertEqual(controller.verify_prepared(self.args.output),plan)
        subject=controller.command_extra(plan,0,self.args.output/'run');peer=controller.command_extra(plan,1,self.args.output/'run')
        self.assertIn('-prediction-visual-input-smoke',subject);self.assertNotIn('-prediction-visual-input-smoke',peer)
        baseline=deepcopy(plan);baseline.pop('visual_input')
        self.assertEqual([x for x in subject if x!='-prediction-visual-input-smoke'],controller.command_extra(baseline,0,self.args.output/'run'))
        for change in (dict(visual_input=1),dict(visual_correction=False),dict(move_slot=1),dict(native_position_trace=None)):
            with self.subTest(change=change),self.assertRaises(AssertionError):evidence.validate_plan(dict(plan,**change))
        broken=dict(plan,visual_correction=False)
        (self.args.output/'invocation.json').write_text(json.dumps(broken))
        with self.assertRaises(AssertionError):controller.verify_prepared(self.args.output)

    def test_flag_absent_unchanged_and_missing_visual_or_helper_refused_before_prepare(self):
        self.args.visual_input=False;plan=controller.prepare(self.args);self.assertNotIn('visual_input',plan)
        with self.assertRaises(AssertionError):evidence.helper(True,b'ordinary')
        evidence.helper(False,b'ordinary')
        args=deepcopy(self.args);args.visual_input=True;args.visual_correction=False
        with self.assertRaisesRegex(AssertionError,'visual-correction'):evidence.option(args,650,self.args.native_position_trace,dict(direction='client_to_server',extra_ms=100,duration_ms=250))


class VisualInputFinalization(unittest.TestCase):
    def test_parent_failure_cannot_be_overridden_and_component_rows_are_preserved(self):
        data,_,_=fixture()
        with tempfile.TemporaryDirectory()as folder:
            run=Path(folder);(run/'native-0.log').write_text(log(data));(run/'native-1.log').write_text('')
            report=dict(passed=False,visual_correction=dict(passed=False))
            with patch.object(evidence,'analyze',side_effect=AssertionError('parent failed')):
                evidence.finalize(dict(visual_input=True),report,run)
            self.assertFalse(report['passed']);self.assertEqual(report['visual_input']['preserved_observations'],evidence.rows(log(data)))
            self.assertFalse(evidence.gate(dict(visual_input=True),report))
        report=dict(passed=True);evidence.finalize({},report,Path('unused'));self.assertEqual(report,dict(passed=True))

    def test_parent_visual_native_scope_required_even_for_positive_authored_component(self):
        proof=evaluate();report=dict(passed=True,visual_input=proof)
        self.assertFalse(evidence.gate(dict(visual_input=True,visual_correction=True),report))


if __name__=='__main__':unittest.main()
