"""Authored four-point attribution receipts; no original input/native execution."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import test_prediction_visual_click as clicks
from tools import prediction_visual_aim as evidence
from tools import verify_prediction_multiplayer as controller


def fixture():
    callbacks,poses,bindings,focuses = clicks.fixture()
    result = []
    for world in (1,2):
        sequence = 0
        for episode in (1,2):
            original = [r for r in callbacks if r['world'] == world and r['episode'] == episode]
            down = original[2]
            p = list(down['pointer'])
            q = [evidence.single(x-y) for x,y in zip(p,[2.4129638671875,1.53607177734375])]
            r = [evidence.single(x+(0 if episode == 1 else shift)) for x,shift in zip(q,[24.,15.])]
            delta = [evidence.single(x-y) for x,y in zip(p,q)]
            m = [evidence.single(x+y) for x,y in zip(r,delta)]
            points = dict(zip(evidence.KINDS,[p,q,r,m]))
            for phase,source in zip(evidence.PHASES,(original[2],original[3],original[4])):
                sequence += 1
                row = {k:deepcopy(source[k]) for k in evidence.click.COMMON}
                row.update(event='probe',sequence=sequence,phase=phase,ticket_serial=down['ticket_serial'],
                    down_method_info=down['method_info'],context_pointer=down['context_pointer'],
                    sample_end_us=source['sampled_us']+90,root_screen=[*q,400.],raw_root_screen=[*r,400.],
                    relative_offset=delta,relative_offset_bits=evidence.bits(delta),points=deepcopy(points),
                    point_bits={k:evidence.bits(v) for k,v in points.items()},viewport=[1280,720],queries=[],unchanged=True)
                target = {k:source[k] for k in evidence.queries.IDENTITY}
                for index,kind in enumerate(evidence.KINDS):
                    point = points[kind]
                    hit = episode == 1 or kind == 'consumed' or (kind == 'displayed_root' and phase == 'process_returned')
                    row['queries'].append(dict(point_kind=kind,begin_us=source['sampled_us']+10+index*20,
                        end_us=source['sampled_us']+20+index*20,point=list(point),inside=True,
                        hit=hit,identity=deepcopy(target) if hit else None))
                result.append(row)
    return result,callbacks,poses,bindings,focuses


def log(records):
    return '\n'.join(evidence.PREFIX+json.dumps(r,separators=(',',':')) for r in records)


def evaluate(records=None,callbacks=None):
    data,old,poses,bindings,focuses = fixture()
    return evidence.evaluate(evidence.rows(log(data if records is None else records)),
        evidence.click.rows(clicks.log(old if callbacks is None else callbacks)),poses,bindings,focus_records=focuses)


class VisualAimRecords(unittest.TestCase):
    def test_independent_spatial_phase_and_matched_counterfactual_results(self):
        result = evaluate();self.assertTrue(result['protocol_valid']);self.assertFalse(result['old_stage1_promoted'])
        self.assertFalse(result['physical_input_accepted']);self.assertFalse(result['full_feature_accepted'])
        for world in result['worlds']:
            zero,nonzero = world['episodes']
            self.assertFalse(any(r['consumed_vs_root_different'] for r in zero['spatial_comparisons']))
            self.assertTrue(nonzero['spatial_comparisons'][0]['consumed_vs_root_different'])
            self.assertTrue(nonzero['spatial_comparisons'][0]['consumed_vs_matched_raw_different'])
            self.assertEqual(nonzero['phase_comparisons'][1]['changed_point_kinds'],['displayed_root'])

    def test_all_misses_are_preserved_as_protocol_valid_not_filtered_acceptance(self):
        data,_,_,_,_ = fixture()
        for row in data:
            for q in row['queries']: q.update(hit=False,identity=None)
        result = evaluate(data)
        self.assertTrue(result['protocol_valid'])
        self.assertTrue(all(not q['hit'] for w in result['worlds'] for e in w['episodes'] for p in e['records'] for q in p['queries']))

    def test_single_subtraction_then_addition_not_fused_arithmetic(self):
        row = deepcopy(fixture()[0][0])
        p = row['points']['consumed'];q = [100000000.,100000000.];r = list(q)
        delta = [evidence.single(a-b) for a,b in zip(p,q)]
        m = [evidence.single(a+b) for a,b in zip(r,delta)]
        points = dict(zip(evidence.KINDS,[p,q,r,m]))
        row.update(root_screen=[*q,400.],raw_root_screen=[*r,400.],relative_offset=delta,
            relative_offset_bits=evidence.bits(delta),points=points,point_bits={k:evidence.bits(v) for k,v in points.items()})
        for kind,query in zip(evidence.KINDS,row['queries']):
            query.update(point=points[kind],inside=all(3 <= x <= end-3 for x,end in zip(points[kind],row['viewport'])))
        # Force a nonexact consumed operand, retaining it as an actual Single.
        p[0]=evidence.single(600.1);row['pointer']=list(p);row['queued_point']=list(p)
        delta=[evidence.single(a-b)for a,b in zip(p,q)];m=[evidence.single(a+b)for a,b in zip(r,delta)]
        row['relative_offset']=delta;row['relative_offset_bits']=evidence.bits(delta)
        row['points']['matched_raw']=m
        row['point_bits']={k:evidence.bits(v)for k,v in row['points'].items()}
        for query in row['queries']:query['point']=list(row['points'][query['point_kind']])
        self.assertEqual(len(evidence.rows(log([row]))),1)
        fused=[evidence.single(a+b-c)for a,b,c in zip(r,p,q)]
        self.assertNotEqual(evidence.bits(fused),evidence.bits(m))
        bad=deepcopy(row);bad['points']['matched_raw']=fused;bad['point_bits']['matched_raw']=evidence.bits(fused)
        bad['queries'][3]['point']=fused
        with self.assertRaisesRegex(AssertionError,'arithmetic'):evidence.rows(log([bad]))

    def test_bits_query_order_clock_and_readonly_adversaries(self):
        data,_,_,_,_ = fixture()
        mutations=[lambda r:r['point_bits']['matched_raw'].__setitem__(0,r['point_bits']['matched_raw'][0]+1),
            lambda r:r['relative_offset_bits'].__setitem__(0,True),lambda r:r['queries'].reverse(),
            lambda r:r['queries'][1].update(begin_us=r['queries'][0]['end_us']-1),
            lambda r:r.update(sample_end_us=r['queries'][-1]['end_us']-1),lambda r:r.update(unchanged=False),
            lambda r:r.update(physical_input=True),lambda r:r.update(selection_writes=1),
            lambda r:r.update(extra='unrecognized'),lambda r:r.update(relative_offset=[float('nan'),0])]
        for mutate in mutations:
            bad=deepcopy(data);mutate(bad[0])
            with self.subTest(mutate=mutate),self.assertRaises((AssertionError,ValueError)):evidence.rows(log(bad))
        duplicate=log(data).replace('"schema":1','"schema":1,"schema":1',1)
        with self.assertRaisesRegex(AssertionError,'duplicate'):evidence.rows(duplicate)

    def test_phase_identity_common_snapshot_and_callback_return_bounds(self):
        data,callbacks,_,_,_ = fixture()
        for mutate in (lambda r:r.update(ticket_serial=99),lambda r:r.update(down_method_info='0xf000'),
                       lambda r:r.update(context_pointer='0xf000'),lambda r:r.update(incarnation=99),
                       lambda r:r.update(sampled_us=r['sampled_us']+1),lambda r:r['pose'].update(policy_us=r['pose']['policy_us']+1)):
            bad=deepcopy(data);mutate(bad[1])
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):evaluate(bad)
        bad=deepcopy(data);bad[2]['sample_end_us']=callbacks[5]['sampled_us']+1
        with self.assertRaisesRegex(AssertionError,'Down return'):evaluate(bad)
        bad=deepcopy(data);bad[0]['queries'][0]['identity']['lease']=0
        # Out identities may be unknown; changing an observed output is retained,
        # not promoted to the current subject by the attribution checker.
        self.assertTrue(evaluate(bad)['protocol_valid'])

    def test_missing_phase_and_crossworld_interleaving_never_pass(self):
        data,_,_,_,_ = fixture()
        self.assertFalse(evaluate(data[:-1])['protocol_valid'])
        bad=deepcopy(data);bad[1]['phase']='process_returned'
        with self.assertRaises(AssertionError):evaluate(bad)
        with self.assertRaises(AssertionError):evidence.rows(log([data[0],data[6],data[1]]))


class VisualAimPlan(unittest.TestCase):
    def setUp(self):
        self.fixture=clicks.VisualClickPlan();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.args=self.fixture.args;self.args.visual_click_spatial=True
        helper=Path(self.args.game)/'BattleAcesOffline.dll'
        helper.write_bytes(helper.read_bytes()+evidence.MARKER+b'\0'+evidence.PREFIX.encode()+
                           '-prediction-visual-click-spatial'.encode('utf-16-le'))
        self.args.expected_helper_sha256=controller.sha(helper)
        for path in (Path(self.args.game)/'.battleaces-resurrection/patch-manifest.json',self.args.helper_build_receipt):
            value=json.loads(path.read_text());value['helper_sha256']=self.args.expected_helper_sha256
            path.write_text(json.dumps(value))

    def test_optional_subject_only_spatial_flag_and_strict_dependencies(self):
        plan=controller.prepare(self.args);self.assertIs(plan['visual_click_spatial'],True)
        self.assertEqual(controller.verify_prepared(self.args.output),plan)
        subject=controller.command_extra(plan,0,self.args.output/'run');peer=controller.command_extra(plan,1,self.args.output/'run')
        self.assertIn('-prediction-visual-click-spatial',subject);self.assertNotIn('-prediction-visual-click-spatial',peer)
        for change in (dict(visual_click_spatial=1),dict(visual_click=False),dict(visual_input=False),dict(visual_correction=False)):
            with self.subTest(change=change),self.assertRaises(AssertionError):evidence.validate_plan(dict(plan,**change))
        old=deepcopy(plan);old.pop('visual_click_spatial')
        self.assertEqual([a for a in subject if a!='-prediction-visual-click-spatial'],controller.command_extra(old,0,self.args.output/'run'))
        with self.assertRaises(AssertionError):evidence.helper(True,b'ordinary')
        evidence.helper(False,b'ordinary')


class VisualAimParents(unittest.TestCase):
    def test_closed_source_wrapper_preserves_failed_stage1_and_requires_protocol_snapshot(self):
        records,callbacks,poses,bindings,focuses=fixture()
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder)/'run';run.mkdir()
            body='\n'.join(evidence.visual.PREFIX+json.dumps(r) for r in poses)+'\n'+clicks.log(callbacks)+'\n'+log(records)+'\n'+\
                '\n'.join(evidence.queries.FOCUS_PREFIX+json.dumps(f) for f in focuses)
            (run/'native-0.log').write_text(body,encoding='utf-8');(run/'native-1.log').write_text('',encoding='utf-8')
            source={}
            for name in evidence.PRODUCERS:
                path=run.parent/'source-at-prepare'/name;path.parent.mkdir(parents=True,exist_ok=True)
                raw=('authored source '+name).encode();path.write_bytes(raw)
                source[name]=evidence.hashlib.sha256(raw).hexdigest()
            for module in (evidence,evidence.click,evidence.queries,evidence.visual,evidence.motion):
                source['tools/'+Path(module.__file__).name]=evidence.motion.sha(module.__file__)
            old=clicks.evaluate();old['input_sha256']={str(run/name):evidence.motion.sha(run/name) for name in ('native-0.log','native-1.log')}
            report=dict(passed=False,visual_input=dict(passed=False),visual_click=old,
                native_position_trace=dict(worlds=[dict(binding=b) for b in bindings]))
            plan=dict(visual_click_spatial=True,source_sha256=source)
            with patch.object(evidence,'validate_plan'):
                result=evidence.analyze(plan,report,run)
                self.assertTrue(result['protocol_valid']);self.assertFalse(result['passed'])
                self.assertEqual(result['status'],'parent_unqualified');self.assertFalse(report['passed'])
                protocol=run.parent/'source-at-prepare'/evidence.PRODUCERS[-1]
                protocol.write_bytes(b'changed Single implementation')
                with self.assertRaisesRegex(AssertionError,'producer differs'):evidence.analyze(plan,report,run)
                protocol.unlink()
                with self.assertRaises(OSError):evidence.analyze(plan,report,run)

    def test_saved_attribution_requires_full_phases_source_and_derived_summary(self):
        proof=evaluate();old=clicks.evaluate()
        source={name:'a'*64 for name in evidence.PRODUCERS}
        hashes={'native-0.log':'0'*64,'native-1.log':'1'*64}
        proof.update(input_sha256=deepcopy(hashes),producer_sha256=deepcopy(source),parent_gates_passed=True)
        old['input_sha256']=hashes
        report=dict(passed=True,visual_click=old,visual_click_spatial=proof)
        plan=dict(visual_click_spatial=True,source_sha256=source)
        with patch.object(evidence,'validate_plan'),patch.object(evidence.click,'gate',return_value=True):
            self.assertTrue(evidence.gate(plan,report))
            for field in ('input_sha256','producer_sha256','worlds'):
                bad=deepcopy(report);bad['visual_click_spatial'].pop(field)
                self.assertFalse(evidence.gate(plan,bad))
            bad=deepcopy(report);bad['visual_click_spatial']['worlds'][0]['records'].pop()
            self.assertFalse(evidence.gate(plan,bad))
            bad=deepcopy(report);bad['visual_click_spatial']['worlds'][0]['episodes'][1]['phase_comparisons'][1]['changed_point_kinds']=[]
            self.assertFalse(evidence.gate(plan,bad))
            bad=deepcopy(report);bad['visual_click_spatial']['scope']='physics cause accepted'
            self.assertFalse(evidence.gate(plan,bad))

    def test_protocol_observations_cannot_promote_a_failed_old_parent(self):
        proof=evaluate();proof.update(passed=False,parent_gates_passed=False,status='parent_unqualified')
        report=dict(passed=False,visual_input=dict(passed=False),visual_click=dict(passed=False))
        with patch.object(evidence,'analyze',return_value=proof):
            evidence.finalize(dict(visual_click_spatial=True),report,Path('unused'))
        self.assertTrue(report['visual_click_spatial_observation_valid']);self.assertFalse(report['passed'])
        self.assertFalse(report['visual_click_spatial_witness_passed'])
        self.assertFalse(evidence.gate(dict(visual_click_spatial=True),report))
        untouched=dict(passed=True);evidence.finalize({},untouched,Path('unused'))
        self.assertEqual(untouched,dict(passed=True));self.assertTrue(evidence.gate({},untouched))


if __name__=='__main__':unittest.main()
