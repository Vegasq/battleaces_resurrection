"""Authored one-first-nonzero callback contract; no native/input execution."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import test_prediction_visual_click as clicks
from tests import test_prediction_visual_input as inputs
from tools import prediction_visual_acquire as evidence
from tools import verify_prediction_multiplayer as controller


def fixture():
    old,poses,bindings,focuses=clicks.fixture();records=[]
    for world in (1,2):
        own=[r for r in old if r['world']==world and r['control']=='nonzero']
        for sequence,item in enumerate(own,1):
            row=deepcopy(item);row.update(episode=1,sequence=sequence)
            if sequence<=8:row['current_ids']=[];row['casting_ids']=[];row['preview_ids']=[74]
            row['mouse']['queued_sequence']+=1
            if sequence==1:row['pointer']=[640.,360.]
            if sequence<=2:row['history']['last_up']=9.5
            # Existing original history may retain74 even with empty selection.
            records.append(row)
    return records,poses,bindings,focuses


def log(records):return '\n'.join(evidence.PREFIX+json.dumps(r,separators=(',',':'))for r in records)


def preparations(records):
    query_records,_,_=inputs.fixture();prepared=[]
    for world in (1,2):
        position=next(r for r in records if r['world']==world)
        zero=next(r for r in query_records if r['world']==world and r['control']=='zero_before')
        for sequence,event in enumerate(('queued','consumed'),1):
            row=deepcopy(position);row.update(event=event,episode=0,control='neutral',sequence=sequence,
                frontend_ordinal=position['frontend_ordinal']-3+sequence,
                sampled_us=zero['policy_us']+(8500 if sequence==1 else 12000),frame=zero['frame'],
                viewport=zero['viewport'],queued_us=zero['policy_us']+8000,
                queued_ordinal=position['frontend_ordinal']-2,primary_callback_count=0,roots_retained=15,
                pointer=[0.,539.]if sequence==1 else[640.,360.],queued_point=[640.,360.])
            row['history'].update(now=9.75 if sequence==1 else 9.8)
            row['mouse'].update(queued_sequence=1)
            row['pose']={k:deepcopy(zero[k])for k in ('frame','revision','joined_us','policy_us','publication_us','alpha','raw','displayed','offset','actual','root_matches_join')}
            prepared.append(row)
    return prepared,query_records


def preparation_log(records):return '\n'.join(evidence.PREPOSITION_PREFIX+json.dumps(r)for r in records)


def evaluate(records=None,poses=None,prepared=None):
    data,original,bindings,focuses=fixture()
    data=data if records is None else records
    neutral,query_records=preparations(data)
    return evidence.evaluate(evidence.rows(log(data)),original if poses is None else poses,bindings,focus_records=focuses,
        preposition_records=evidence.preposition_rows(preparation_log(neutral if prepared is None else prepared)),query_records=query_records)


class VisualAcquireRecords(unittest.TestCase):
    def test_genuine_one_episode_empty_through_up_then_subject_selected(self):
        proof=evaluate();self.assertTrue(proof['passed'])
        self.assertFalse(proof['actual_zero_click_claimed']);self.assertFalse(proof['legacy_two_click_proof_claimed'])
        self.assertFalse(proof['physical_input_accepted'])
        for world in proof['worlds']:
            e=world['episode'];self.assertEqual((e['episode'],e['control']),(1,'nonzero'))
            self.assertEqual(e['initial_current_ids'],[]);self.assertEqual(e['before_up_current_ids'],[])
            self.assertEqual(e['after_up_current_ids'],[74]);self.assertGreaterEqual(e['minimum_offset'],.5)
            self.assertEqual(world['records'][2]['history']['id'],74)
            self.assertEqual([r['mouse']['queued_sequence']for r in world['records']],[2,3,3,3,3,3,4,4,4,4])
            self.assertEqual(world['preposition']['point'],[640.,360.])

    def test_explicit_parser_contract_never_relaxes_legacy_or_fabricates_zero(self):
        data,poses,bindings,focuses=fixture()
        self.assertEqual(evidence.click.rows(log(data)),[])
        wrong='\n'.join(evidence.click.PREFIX+json.dumps(r)for r in data)
        with self.assertRaises(AssertionError):evidence.click.rows(wrong)
        with self.assertRaises(AssertionError):evidence.click.rows(log(data),contract='anything')
        parsed=evidence.rows(log(data))
        with self.assertRaises(AssertionError):evidence.click._episode(parsed[:10])
        bad=deepcopy(data);bad[0]['control']='zero'
        with self.assertRaises(AssertionError):evidence.rows(log(bad))

    def test_every_pre_up_committed_set_is_empty_but_preview_is_allowed(self):
        data,_,_,_=fixture()
        for index in range(8):
            bad=deepcopy(data);bad[index]['current_ids']=[74]
            with self.subTest(index=index),self.assertRaisesRegex(AssertionError,'empty'):evaluate(bad)
        bad=deepcopy(data);bad[7]['casting_ids']=[74]
        with self.assertRaises(AssertionError):evaluate(bad)
        for index in (8,9):
            bad=deepcopy(data);bad[index]['current_ids']=[]
            with self.subTest(index=index),self.assertRaises(AssertionError):evaluate(bad)

    def test_release_offset_never_uses_only_the_old_down_threshold(self):
        data,poses,_,_=fixture();bad=deepcopy(data)
        p=deepcopy(next(p for p in poses if p['event']=='visual_pose'and p['world']==1 and p['sampled_us']==bad[7]['pose']['policy_us']))
        p['sampled_us']+=2000;p['displayed']=evidence.motion.vec(evidence.motion.add(p['raw'],[.49,0,0]))
        p['transform']=list(p['displayed']);p['output']=list(p['displayed'])
        for r in bad[7:10]:
            r['pose'].update(policy_us=p['sampled_us'],joined_us=p['sampled_us']+1000,displayed=list(p['displayed']),
                actual=list(p['displayed']),offset=[.49,0,0])
        with self.assertRaisesRegex(AssertionError,'0.5'):evaluate(bad,poses=poses+[p])

    def test_actual_phase_ticket_point_roots_and_join_guards_are_reused(self):
        data,_,_,_=fixture()
        cases=[(2,lambda r:r.update(ticket_serial=999)),(4,lambda r:r.update(context_pointer='0xf000')),
            (5,lambda r:r.update(single_accepted=False)),(8,lambda r:r['mouse'].update(primary=True)),
            (9,lambda r:r.update(roots_after=1)),(1,lambda r:r['queued_point'].__setitem__(0,r['queued_point'][0]+1)),
            (2,lambda r:r.update(incarnation=999)),(2,lambda r:r.update(owner_thread=999))]
        for index,mutate in cases:
            bad=deepcopy(data);mutate(bad[index])
            with self.subTest(index=index),self.assertRaises(AssertionError):evaluate(bad)

    def test_partial_miss_and_nondiscrimination_remain_unqualified(self):
        data,_,_,_=fixture();self.assertFalse(evaluate(data[:-1])['passed'])
        bad=deepcopy(data);bad[2]['hit_test']['raw']=deepcopy(bad[2]['hit_test']['displayed']);bad[2]['hit_test']['discriminates']=False
        self.assertFalse(evaluate(bad)['passed'])
        duplicate=log(data).replace('"schema":1','"schema":1,"schema":1',1)
        with self.assertRaisesRegex(AssertionError,'duplicate'):evidence.rows(duplicate)

    def test_neutral_consumption_cannot_be_inferred_from_queue_or_retargeted(self):
        data,_,_,_=fixture();prepared,_=preparations(data)
        cases=[(1,lambda r:r.update(pointer=[639.,360.])),(0,lambda r:r.update(primary_callback_count=1)),
            (1,lambda r:r.update(frontend_ordinal=r['queued_ordinal'])),
            (1,lambda r:r.update(sampled_us=r['queued_us']+250001)),
            (1,lambda r:r['history'].update(last_up=9.6)),(1,lambda r:r.update(current_ids=[74])),
            (1,lambda r:r['mouse'].update(device='0xff0000')),(1,lambda r:r.update(roots_retained=14)),
            (1,lambda r:r.update(pending_commands=2)),(0,lambda r:r.update(queued_point=[640.5,360.])),
            (1,lambda r:r.update(viewport=[1282,720]))]
        for index,mutate in cases:
            bad=deepcopy(prepared);mutate(bad[index])
            with self.subTest(index=index),self.assertRaises(AssertionError):evaluate(prepared=bad)
        with self.assertRaises(AssertionError):evaluate(prepared=prepared[1:])
        bad=deepcopy(data);bad[0]['pointer']=[0.,539.]
        with self.assertRaisesRegex(AssertionError,'neutral center'):evaluate(bad)

    def test_preparation_pending_may_change_after_consumed_and_legacy_queue_is_rejected(self):
        data,_,_,_=fixture();prepared,_=preparations(data)
        for r in prepared:r['pending_commands']=0
        self.assertTrue(evaluate(prepared=prepared)['passed'])
        bad=deepcopy(data)
        for r in bad:r['mouse']['queued_sequence']-=1
        with self.assertRaisesRegex(AssertionError,'queue receipts'):evaluate(bad)

    def test_neutral_delivery_deadline_is_inclusive_without_refreshing_queue_clock(self):
        data,_,_,_=fixture();prepared,query_records=preparations(data)
        own=data[:10];neutral=prepared[:2];zero=query_records[0]
        neutral[1]['sampled_us']=neutral[0]['queued_us']+250000
        self.assertEqual(evidence._preposition(neutral,own,zero)['delivery_us'],250000)
        neutral[1]['sampled_us']+=1
        with self.assertRaisesRegex(AssertionError,'chronology'):evidence._preposition(neutral,own,zero)


class VisualAcquirePlan(unittest.TestCase):
    def setUp(self):
        self.fixture=inputs.VisualInputPlan();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.args=self.fixture.args;self.args.visual_click_acquire=True
        helper=Path(self.args.game)/'BattleAcesOffline.dll'
        helper.write_bytes(helper.read_bytes()+evidence.MARKER+b'\0'+evidence.PREFIX.encode()+evidence.PREPOSITION_MARKER+evidence.PREPOSITION_PREFIX.encode()+
            '-prediction-visual-click-acquire'.encode('utf-16-le'))
        self.args.expected_helper_sha256=controller.sha(helper)
        for path in (Path(self.args.game)/'.battleaces-resurrection/patch-manifest.json',self.args.helper_build_receipt):
            value=json.loads(path.read_text());value['helper_sha256']=self.args.expected_helper_sha256
            path.write_text(json.dumps(value))

    def test_only_explicit_subject_variant_and_no_empty_or_legacy_mixing(self):
        plan=controller.prepare(self.args);self.assertEqual(controller.verify_prepared(self.args.output),plan)
        self.assertIs(plan['visual_click_acquire'],True)
        subject=controller.command_extra(plan,0,self.args.output/'run');peer=controller.command_extra(plan,1,self.args.output/'run')
        self.assertIn('-prediction-visual-click-acquire',subject);self.assertNotIn('-prediction-visual-click-acquire',peer)
        old=deepcopy(plan);old.pop('visual_click_acquire')
        self.assertEqual([s for s in subject if s!='-prediction-visual-click-acquire'],controller.command_extra(old,0,self.args.output/'run'))
        for change in (dict(visual_click_acquire=1),dict(visual_input=False),dict(visual_click=True),dict(visual_click_spatial=True),dict(visual_click_empty=True)):
            with self.subTest(change=change),self.assertRaises(AssertionError):evidence.validate_plan(dict(plan,**change))
        with self.assertRaises(AssertionError):evidence.helper(True,b'ordinary')
        with self.assertRaises(AssertionError):evidence.helper(True,evidence.MARKER+evidence.PREFIX.encode()+
            '-prediction-visual-click-acquire'.encode('utf-16-le'))
        evidence.helper(False,b'ordinary')


class VisualAcquireParents(unittest.TestCase):
    def test_closed_wrapper_binds_source_and_rejects_peer_or_mixed_legacy(self):
        records,poses,bindings,focuses=fixture()
        prepared,query_records=preparations(records)
        with tempfile.TemporaryDirectory()as folder:
            run=Path(folder)/'run';run.mkdir()
            body='\n'.join(evidence.visual.PREFIX+json.dumps(r)for r in poses)+'\n'+log(records)+'\n'+preparation_log(prepared)+'\n'+\
                '\n'.join(evidence.queries.PREFIX+json.dumps(r)for r in query_records)+'\n'+\
                '\n'.join(evidence.queries.FOCUS_PREFIX+json.dumps(f)for f in focuses)
            (run/'native-0.log').write_text(body,encoding='utf-8');(run/'native-1.log').write_text('',encoding='utf-8')
            source={}
            for name in evidence.PRODUCERS:
                path=run.parent/'source-at-prepare'/name;path.parent.mkdir(parents=True,exist_ok=True)
                raw=('authored source '+name).encode();path.write_bytes(raw)
                source[name]=evidence.hashlib.sha256(raw).hexdigest()
            for module in (evidence,evidence.click,evidence.queries,evidence.visual,evidence.motion):
                source['tools/'+Path(module.__file__).name]=evidence.motion.sha(module.__file__)
            hashes={str(run/name):evidence.motion.sha(run/name)for name in ('native-0.log','native-1.log')}
            report=dict(passed=True,visual_input_witness_passed=True,
                visual_input=dict(input_sha256=hashes,worlds=[dict(focus=f,records=[r for r in query_records if r['world']==f['world']])for f in focuses]),
                native_position_trace=dict(worlds=[dict(binding=b)for b in bindings]))
            plan=dict(visual_click_acquire=True,source_sha256=source)
            with patch.object(evidence,'validate_plan'),patch.object(evidence.visual,'parent_gate'),\
                 patch.object(evidence.queries,'gate',return_value=True):
                proof=evidence.analyze(plan,report,run);self.assertTrue(proof['passed'])
                self.assertFalse(proof['actual_zero_click_claimed'])
                wrong=deepcopy(source);wrong[evidence.PRODUCERS[-1]]='f'*64
                with self.assertRaisesRegex(AssertionError,'producer differs'):evidence.analyze(dict(plan,source_sha256=wrong),report,run)
                wrong_report=deepcopy(report);wrong_report['visual_input']['input_sha256'][str(run/'native-0.log')]='f'*64
                mismatch=evidence.analyze(plan,wrong_report,run);self.assertFalse(mismatch['passed'])
                self.assertTrue(mismatch['component_observation_passed'])
                (run/'native-1.log').write_text(evidence.PREFIX+json.dumps(records[0]),encoding='utf-8')
                with self.assertRaisesRegex(AssertionError,'peer'):evidence.analyze(plan,report,run)
                (run/'native-1.log').write_text('',encoding='utf-8')
                (run/'native-0.log').write_text(body+'\n'+evidence.click.PREFIX+'{}',encoding='utf-8')
                with self.assertRaisesRegex(AssertionError,'mixed'):evidence.analyze(plan,report,run)

    def test_parent_failure_cannot_be_promoted_or_invent_old_zero_click(self):
        proof=evaluate();proof.update(passed=False,parent_gates_passed=False,status='parent_unqualified')
        report=dict(passed=False)
        with patch.object(evidence,'analyze',return_value=proof):evidence.finalize(dict(visual_click_acquire=True),report,Path('unused'))
        self.assertFalse(report['passed']);self.assertFalse(report['visual_click_acquire_witness_passed'])
        self.assertFalse(report['visual_click_acquire']['actual_zero_click_claimed'])
        untouched=dict(passed=True);evidence.finalize({},untouched,Path('unused'));self.assertEqual(untouched,dict(passed=True))

    def test_saved_gates_require_actual_current_source_and_focus(self):
        proof=evaluate();hashes={'native-0.log':'0'*64,'native-1.log':'1'*64};source={name:'a'*64 for name in evidence.PRODUCERS}
        proof.update(parent_gates_passed=True,input_sha256=deepcopy(hashes),producer_sha256=deepcopy(source))
        report=dict(passed=True,visual_click_acquire=proof,visual_correction=dict(worlds=[dict(binding=w['binding'])for w in proof['worlds']]),
            visual_input=dict(input_sha256=hashes,worlds=[dict(focus=deepcopy(f),records=[r for r in proof['query_records']if r['world']==f['world']])for f in proof['focus_records']]))
        plan=dict(visual_click_acquire=True,source_sha256=source)
        with patch.object(evidence,'validate_plan'),patch.object(evidence.visual,'parent_gate'),patch.object(evidence.queries,'gate',return_value=True):
            self.assertTrue(evidence.gate(plan,report))
            for field in ('joined_visual_poses','input_sha256','producer_sha256','focus_records','preposition_records','query_records'):
                bad=deepcopy(report);bad['visual_click_acquire'].pop(field);self.assertFalse(evidence.gate(plan,bad))
            bad=deepcopy(report);bad['visual_click_acquire']['worlds'][0]['records'][7]['current_ids']=[74]
            self.assertFalse(evidence.gate(plan,bad))
            bad=deepcopy(report);bad['visual_click_acquire']['preposition_records'][1]['pointer']=[641.,360.]
            self.assertFalse(evidence.gate(plan,bad))
            bad=deepcopy(report);bad['visual_click_acquire']['query_records'][0]['query_end_us']+=10000
            self.assertFalse(evidence.gate(plan,bad))


if __name__=='__main__':unittest.main()
