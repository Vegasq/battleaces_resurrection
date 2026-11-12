"""Authored Sync attribution protocol; no original engine/input execution."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import test_prediction_visual_input as inputs
from tests import test_prediction_visual_acquire as acquisition
from tools import prediction_visual_sync as evidence
from tools import verify_prediction_multiplayer as controller


def fixture(*,trigger=True):
    original,poses,bindings=inputs.fixture();records=[]
    for world in (1,2):
        source=next(r for r in original if r['world']==world and r['control']==('nonzero'if trigger else'zero_after'))
        if trigger:source['displayed_ray']=dict(hit=False,identity=None);source['ray_discriminates']=False
        clock=source['query_end_us'];r=dict(schema=1,event='probe'if trigger else'no_trigger',world=world,match=source['match'],
            sequence=1,source=deepcopy(source),point=source['displayed_screen'][:2],point_bits=evidence._bits(source['displayed_screen'][:2]),
            module=None,pre=None,sync={'calls':0},post=None,before=None,after=None,checked_us=clock+100,
            invariants_unchanged=True,selection_writes=0,history_writes=0,physical_input=False)
        if trigger:
            snapshot={k:deepcopy(source[k])for k in ('selector','camera','camera_controller','actor','transform','manager','simulation',
                'thread','owner_thread','frame','revision','joined_us','policy_us','publication_us','alpha','lease','generation',
                'entity','unit_type','army','incarnation','actual','raw','displayed','offset','drag_mode')}
            snapshot.update(handler=hex(world*0x100000+0x1000),projected=deepcopy(source['displayed_screen']),pointer=[480.,270.],
                checked_us=clock+10,history=dict(id=74,mode=0,primary=False,context=False,drag=False,last_up=53.,window=.4),
                current_ids=[74],preview_ids=[],casting_ids=[],pending_commands=0,
                mouse=dict(device=hex(world*0x100000+0x2000),controls=['0x3000','0x4000','0x5000'],
                    actions=['0x6000','0x7000','0x8000'],references=['0x9000','0xa000','0xb000'],
                    primary=False,context=False,session_active=False,session_sequence=4))
            r['before']=snapshot;r['after']=deepcopy(snapshot);r['after']['checked_us']=clock+80
            base=0x7ffe00000000;r['module']=dict(base=hex(base),pe_timestamp=1721777247,pe_image_size=0x1e58000,pe_offset=328,
                resolver='il2cpp_resolve_icall',icall='UnityEngine.Physics::SyncTransforms',target=hex(base+0x1771f0),
                target_rva='0x1771f0',wrapper_hex='e98b1a5600',engine_rva='0x6d8c80')
            r['pre']=dict(begin_us=clock+20,end_us=clock+30,hit=False,identity=None)
            r['sync']=dict(entered_us=clock+40,returned_us=clock+50,calls=1)
            r['post']=dict(begin_us=clock+60,end_us=clock+70,hit=True,
                identity={k:source[k]for k in evidence.queries.IDENTITY})
        records.append(r)
    return records,original,poses,bindings


def log(records):return '\n'.join(evidence.PREFIX+json.dumps(r,separators=(',',':'))for r in records)


def evaluate(records=None,*,trigger=True):
    own,original,poses,bindings=fixture(trigger=trigger)
    return evidence.evaluate(evidence.rows(log(own if records is None else records)),original,poses,bindings)


class VisualSyncProtocol(unittest.TestCase):
    def test_original_miss_stays_failed_and_sync_associated_hit_is_observation_only(self):
        proof=evaluate();self.assertTrue(proof['protocol_valid']);self.assertTrue(proof['triggered']);self.assertFalse(proof['passed'])
        self.assertEqual([w['classification']for w in proof['worlds']],['stable_miss_then_subject_hit_after_sync']*2)
        self.assertFalse(proof['old_stage1_promoted']);self.assertFalse(proof['full_feature_accepted'])

    def test_prevariation_is_not_attributed_to_intervention(self):
        data,_,_,_=fixture();data[0]['pre']['identity']=deepcopy(data[0]['post']['identity'])
        proof=evaluate(data);self.assertEqual(proof['worlds'][0]['classification'],'pre_result_changed_before_sync')
        data[0]['pre']['hit']=True
        self.assertEqual(evaluate(data)['worlds'][0]['classification'],'pre_already_hits_subject')
        data[0]['post']=dict(data[0]['post'],hit=False,identity=None);data[0]['pre']['identity']=None;data[0]['pre']['hit']=False
        self.assertEqual(evaluate(data)['worlds'][0]['classification'],'miss_remains_after_sync')

    def test_no_trigger_is_truthful_incomplete_not_a_pass(self):
        proof=evaluate(trigger=False);self.assertTrue(proof['protocol_valid']);self.assertFalse(proof['triggered'])
        self.assertEqual(proof['status'],'incomplete');self.assertFalse(proof['passed'])

    def test_exact_point_source_runtime_and_single_intervention_are_required(self):
        data,_,_,_=fixture()
        cases=[lambda r:r['point'].__setitem__(0,r['point'][0]+1),lambda r:r['module'].update(target='0x7ffe00177200'),
            lambda r:r['module'].update(wrapper_hex='e900000000'),lambda r:r['module'].update(pe_timestamp=True),
            lambda r:r['sync'].update(calls=2),lambda r:r['source'].update(incarnation=999),
            lambda r:r.update(invariants_unchanged=False),lambda r:r.update(selection_writes=1)]
        for mutate in cases:
            bad=deepcopy(data);mutate(bad[0])
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):evaluate(bad)

    def test_pose_input_selection_and_clock_side_effects_cannot_be_hidden(self):
        data,_,_,_=fixture()
        cases=[lambda r:r['after']['history'].update(mode=1),lambda r:r['after'].update(current_ids=[]),
            lambda r:r['after'].update(pending_commands=1),lambda r:r['after']['mouse'].update(primary=True),
            lambda r:r['before'].update(alpha=False),lambda r:r['after'].update(checked_us=r['source']['joined_us']+50001),
            lambda r:r['sync'].update(entered_us=r['pre']['end_us']-1),
            lambda r:r['post'].update(begin_us=r['sync']['returned_us']-1)]
        for mutate in cases:
            bad=deepcopy(data);mutate(bad[0])
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):evaluate(bad)

    def test_missing_world_duplicate_fields_or_omitted_first_miss_are_refused(self):
        data,original,poses,bindings=fixture()
        with self.assertRaises(AssertionError):evidence.evaluate(evidence.rows(log(data[:1])),original,poses,bindings)
        with self.assertRaisesRegex(AssertionError,'duplicate'):evidence.rows(log(data).replace('"schema":1','"schema":1,"schema":1',1))
        earlier=deepcopy(original[1]);earlier['frontend_ordinal']-=1;earlier['sampled_us']-=1
        with self.assertRaisesRegex(AssertionError,'first eligible'):evidence.evaluate(evidence.rows(log(data)),[earlier,*original],poses,bindings)


class VisualSyncWiring(unittest.TestCase):
    def test_option_requires_acquisition_owner_and_helper_capability(self):
        f=acquisition.VisualAcquirePlan();f.setUp();self.addCleanup(f.doCleanups);args=f.args;args.visual_sync_probe=True
        frames=650;trace=args.native_position_trace;delay=controller.input_delay.option(args,frames,trace)
        self.assertTrue(evidence.option(args,frames,trace,delay))
        args.visual_click_acquire=False
        with self.assertRaises(AssertionError):evidence.option(args,frames,trace,delay)
        evidence.helper(False,b'normal')
        with self.assertRaises(AssertionError):evidence.helper(True,b'normal')

    def test_optional_central_unityplayer_pin_and_subject_flag_preserve_default_plan(self):
        f=acquisition.VisualAcquirePlan();f.setUp();self.addCleanup(f.doCleanups);args=f.args
        original_sha=controller.sha;ordinary=controller.prepare(args);self.assertIn('unityplayer',ordinary['files'])
        ordinary_output=args.output;args.output=ordinary_output.with_name(ordinary_output.name+'-sync-bad')
        args.visual_sync_probe=True;helper=Path(args.game)/'BattleAcesOffline.dll'
        helper.write_bytes(helper.read_bytes()+evidence.MARKER+evidence.PREFIX.encode()+'-prediction-visual-sync-smoke'.encode('utf-16-le'))
        args.expected_helper_sha256=original_sha(helper)
        for path in (Path(args.game)/'.battleaces-resurrection/patch-manifest.json',args.helper_build_receipt):
            value=json.loads(path.read_text());value['helper_sha256']=args.expected_helper_sha256;path.write_text(json.dumps(value))
        player=Path(args.game)/'UnityPlayer.dll';player.write_bytes(b'authored module identity')
        with self.assertRaisesRegex(AssertionError,'UnityPlayer'):controller.prepare(args)
        args.output=ordinary_output.with_name(ordinary_output.name+'-sync-good')
        def sha(path):return evidence.UNITYPLAYER_SHA256 if Path(path)==player else original_sha(path)
        with patch.object(controller,'sha',side_effect=sha):
            plan=controller.prepare(args);self.assertEqual(controller.verify_prepared(args.output),plan)
            subject=controller.command_extra(plan,0,args.output/'run');peer=controller.command_extra(plan,1,args.output/'run')
            self.assertIn('-prediction-visual-sync-smoke',subject);self.assertNotIn('-prediction-visual-sync-smoke',peer)
            self.assertEqual(plan['files']['unityplayer']['sha256'],evidence.UNITYPLAYER_SHA256)
            bad=deepcopy(plan);bad['files']['unityplayer']['sha256']='f'*64
            with self.assertRaises(AssertionError):evidence.validate_plan(bad)


class VisualSyncClosedProof(unittest.TestCase):
    def test_closed_wrapper_and_saved_proof_retain_failed_parent_sources_and_poses(self):
        records,original,poses,bindings=fixture()
        with tempfile.TemporaryDirectory()as directory:
            run=Path(directory)/'run';run.mkdir();player=Path(directory)/'UnityPlayer.dll';player.write_bytes(b'authored module')
            body='\n'.join(evidence.queries.PREFIX+json.dumps(r)for r in original)+'\n'+log(records)+'\n'+\
                '\n'.join(evidence.visual.PREFIX+json.dumps(p)for p in poses)
            (run/'native-0.log').write_text(body);(run/'native-1.log').write_text('')
            source={}
            for name in evidence.PRODUCERS:
                path=run.parent/'source-at-prepare'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('authored '+name)
                source[name]=evidence.motion.sha(path)
            for module in (evidence,evidence.queries,evidence.visual,evidence.motion):source['tools/'+Path(module.__file__).name]=evidence.motion.sha(module.__file__)
            hashes={str(run/name):evidence.motion.sha(run/name)for name in ('native-0.log','native-1.log')}
            report=dict(passed=False,source_unchanged=True,files_unchanged=True,native_position_trace=dict(worlds=[dict(binding=b)for b in bindings]),
                visual_input=dict(passed=False,component_observation_passed=False,input_sha256=hashes,
                    worlds=[dict(binding=b,records=[r for r in original if r['world']==b['world']])for b in bindings]))
            plan=dict(visual_sync_probe=True,files=dict(unityplayer=dict(path=str(player),sha256=evidence.UNITYPLAYER_SHA256)),source_sha256=source)
            report.update(source_sha256_at_start=deepcopy(source),source_sha256_at_finish=deepcopy(source))
            original_sha=evidence.motion.sha
            def sha(path):return evidence.UNITYPLAYER_SHA256 if Path(path)==player else original_sha(path)
            with patch.object(evidence,'validate_plan'),patch.object(evidence.motion,'sha',side_effect=sha):
                evidence.finalize(plan,report,run);self.assertFalse(report['passed']);self.assertTrue(report['visual_sync_observation_valid'])
                proof=report['visual_sync_probe'];self.assertTrue(proof['triggered']);self.assertFalse(proof['original_parent_passed'])
                for key in ('query_records','joined_visual_poses','producer_sha256','runtime_module'):
                    bad=deepcopy(report);bad['visual_sync_probe'].pop(key);self.assertFalse(evidence.gate(plan,bad))
                bad=deepcopy(report);bad['visual_sync_probe']['worlds'][0]['record']['post']['hit']=False
                self.assertFalse(evidence.gate(plan,bad))
                bad=deepcopy(plan);bad['source_sha256'][evidence.PRODUCERS[0]]='f'*64
                with self.assertRaisesRegex(AssertionError,'producer differs'):evidence.analyze(bad,report,run)
                (run/'native-1.log').write_text(evidence.PREFIX+json.dumps(records[0]))
                with self.assertRaisesRegex(AssertionError,'peer'):evidence.analyze(plan,report,run)
        unchanged=dict(passed=True);evidence.finalize({},unchanged,Path('unused'));self.assertEqual(unchanged,dict(passed=True))


if __name__=='__main__':unittest.main()
