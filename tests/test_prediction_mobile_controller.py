"""File-only mobile scenario, ordinary compatibility and closed-state gates."""
import argparse
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_prediction_multiplayer_verifier as baseline
from tools import verify_prediction_multiplayer as v


class MobilePreparationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=baseline.PreparationTests('test_default_prepare_never_spawns_and_does_not_mutate_game')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture
        helper=f.game/'BattleAcesOffline.dll'
        helper.write_bytes(helper.read_bytes()+'-prediction-mobile-correction-smoke'.encode('utf-16-le'))
        f.args.expected_helper_sha256=v.sha(helper)
        manifest=f.game/'.battleaces-resurrection/patch-manifest.json'
        data=json.loads(manifest.read_text());data['helper_sha256']=v.sha(helper);manifest.write_text(json.dumps(data))
        receipt=f.args.helper_build_receipt
        data=json.loads(receipt.read_text());data['helper_sha256']=v.sha(helper);receipt.write_text(json.dumps(data))
        self.args=deepcopy(f.args);self.args.scenario='mobile';self.args.mobile_correction=True

    def add_group_markers(self, *, include_recovery=False, include_recall=False, include_focus=False):
        f=self.fixture;helper=f.game/'BattleAcesOffline.dll'
        helper.write_bytes(helper.read_bytes()+b'|'+ '-prediction-mobile-group-intent-smoke'.encode('utf-16-le')+
                           '-prediction-mobile-group-user-edits-smoke'.encode('utf-16-le'))
        if include_recovery:helper.write_bytes(helper.read_bytes()+'-prediction-mobile-recovery-stall-smoke'.encode('utf-16-le'))
        if include_recall:helper.write_bytes(helper.read_bytes()+'-prediction-mobile-recall-smoke'.encode('utf-16-le'))
        if include_focus:helper.write_bytes(helper.read_bytes()+'-prediction-mobile-focus-smoke'.encode('utf-16-le'))
        self.args.expected_helper_sha256=v.sha(helper)
        for path in(f.game/'.battleaces-resurrection/patch-manifest.json',f.args.helper_build_receipt):
            data=json.loads(path.read_text());data['helper_sha256']=v.sha(helper);path.write_text(json.dumps(data))

    def test_mobile_prepare_is_explicit650_and_issues_no_game_process(self):
        with patch.object(v.subprocess,'Popen',side_effect=AssertionError('Native forbidden')):
            plan=v.prepare(self.args)
        self.assertEqual((plan['scenario'],plan['frames'],plan['expected_matches'],plan['surrender_frame']),('mobile',650,2,700))
        self.assertTrue(plan['generic_movement_not_exercised'])
        self.assertFalse(plan['native_executed']);self.assertFalse(plan['full_feature_accepted'])
        for slot in(0,1):
            extra=v.command_extra(plan,slot,self.args.output/'run')
            self.assertIn('-prediction-movement-experimental',extra)
            self.assertIn('-prediction-mobile-correction-smoke',extra)
            self.assertNotIn('-prediction-movement-smoke',extra)
            self.assertFalse(any(x.startswith('-prediction-movement-smoke-')for x in extra))
            self.assertIn('-native-quit-smoke',extra)
            self.assertNotIn('-frame-timing-worlds=2',extra)
            self.assertNotIn('-prediction-mobile-recall-smoke',extra)
            self.assertNotIn('-prediction-mobile-focus-smoke',extra)
        self.assertNotIn('mobile_focus',plan)

    def test_movement_pointer_and_byte_patch_descriptors_are_exact_required_members(self):
        manifest=self.fixture.game/'.battleaces-resurrection/patch-manifest.json'
        original=json.loads(manifest.read_text())
        cases=('no_pointer_key','no_pointer_entry','pointer_inventory','pointer_target','pointer_relocation_guard',
               'no_patch_key','no_patch_entry','patch_inventory','patch_before','patch_after','patch_address')
        for kind in cases:
            with self.subTest(kind=kind):
                data=deepcopy(original)
                if kind=='no_pointer_key':data.pop('pointer_hooks')
                elif kind=='no_pointer_entry':data['pointer_hooks']=[]
                elif kind=='pointer_inventory':data['pointer_hooks']=None
                elif kind=='pointer_target':data['pointer_hooks'][0]['target_rva']+=1
                elif kind=='pointer_relocation_guard':data['pointer_hooks'][0]['relocation_entry_before']='0000'
                elif kind=='no_patch_key':data.pop('patches')
                elif kind=='no_patch_entry':data['patches']=[]
                elif kind=='patch_inventory':data['patches']='not-an-inventory'
                elif kind=='patch_before':data['patches'][0]['before']='909090'
                elif kind=='patch_after':data['patches'][0]['after']='909090'
                else:data['patches'][0]['offset']+=1
                manifest.write_text(json.dumps(data));before=self.fixture.snapshot_game()
                with patch.object(v.subprocess,'Popen',side_effect=AssertionError('Native forbidden')):
                    with self.assertRaisesRegex(AssertionError,'manifest lacks movement '+('pointer hook'if'pointer'in kind else'byte patch')):
                        v.prepare(self.args)
                self.assertFalse(self.args.output.exists());self.assertEqual(before,self.fixture.snapshot_game())

    def test_pointer_export_marker_is_required_even_with_rebound_authored_helper_hash(self):
        from client_patch.patcher import prediction_actor_repair
        helper=self.fixture.game/'BattleAcesOffline.dll'
        marker=prediction_actor_repair.POINTER_HOOKS[0]['name'].encode('ascii')+b'\0'
        raw=helper.read_bytes();self.assertIn(marker,raw)
        helper.write_bytes(raw.replace(marker,marker[:-1]+b'_missing\0'))
        self.args.expected_helper_sha256=v.sha(helper)
        for path in(self.fixture.game/'.battleaces-resurrection/patch-manifest.json',self.args.helper_build_receipt):
            data=json.loads(path.read_text());data['helper_sha256']=v.sha(helper);path.write_text(json.dumps(data))
        before=self.fixture.snapshot_game()
        with patch.object(v.subprocess,'Popen',side_effect=AssertionError('Native forbidden')):
            with self.assertRaisesRegex(AssertionError,'movement/actor/selection exports'):v.prepare(self.args)
        self.assertFalse(self.args.output.exists());self.assertEqual(before,self.fixture.snapshot_game())

    def test_existing_diagnostic_quit_pointer_can_coexist_with_required_movement_pointer(self):
        # Membership is additive. This authored metadata check does not claim
        # an actual Quit/native run or replace the pinned helper/GA digests.
        from client_patch.patcher.patch_client import QUIT_POINTER_HOOKS
        manifest=self.fixture.game/'.battleaces-resurrection/patch-manifest.json'
        data=json.loads(manifest.read_text());data['pointer_hooks']+=deepcopy(QUIT_POINTER_HOOKS)
        manifest.write_text(json.dumps(data));before=self.fixture.snapshot_game()
        with patch.object(v.subprocess,'Popen',side_effect=AssertionError('Native forbidden')):
            plan=v.prepare(self.args)
        self.assertFalse(plan['native_executed']);self.assertEqual(before,self.fixture.snapshot_game())
        self.assertEqual(plan['files']['helper']['sha256'],self.args.expected_helper_sha256)
        self.assertEqual(plan['files']['gameassembly']['sha256'],self.args.expected_gameassembly_sha256)

    def test_mobile_rejects_unqualified_plan_before_creating_output(self):
        cases=[dict(mobile_correction=False),dict(lifecycle='prefix'),dict(frames=600),dict(move_slot=1),
               dict(rtt_ms=(130,474)),dict(actor_correction=True),dict(changing_rtt=True),
               dict(transition_orders=True),dict(native_position_trace='11:1:1:130:220')]
        for changes in cases:
            with self.subTest(changes=changes):
                args=deepcopy(self.args)
                for key,value in changes.items():setattr(args,key,value)
                with self.assertRaises(AssertionError):v.prepare(args)
                self.assertFalse(args.output.exists())

    def test_prepared_mobile_contract_is_revalidated_before_any_future_run(self):
        plan=v.prepare(self.args);v.verify_prepared(self.args.output)
        for changes in (dict(mobile_correction=False),dict(frames=600),dict(expected_matches=1),
                        dict(generic_movement_not_exercised=False),dict(lifecycle='prefix')):
            with self.subTest(changes=changes):
                altered=deepcopy(plan);altered.update(changes)
                (self.args.output/'invocation.json').write_text(json.dumps(altered))
                with self.assertRaisesRegex(AssertionError,'prepared mobile scenario'):
                    v.verify_prepared(self.args.output)

    def test_optional_group_modes_require_markers_and_forward_only_requested_flags(self):
        self.add_group_markers();self.args.mobile_group_intent=True
        for edits in(False,True):
            with self.subTest(user_edits=edits):
                args=deepcopy(self.args);args.mobile_group_user_edits=edits
                args.output=self.fixture.root/f'local/groups-{edits}'
                plan=v.prepare(args);extra=v.command_extra(plan,1,args.output/'run')
                self.assertIn('-prediction-mobile-group-intent-smoke',extra)
                self.assertEqual('-prediction-mobile-group-user-edits-smoke'in extra,edits)
                self.assertNotIn('-prediction-movement-smoke',extra)
                self.assertTrue(plan['mobile_group_intent'])

    def test_group_modes_are_rejected_without_scope_dependency_or_binary_marker(self):
        for changes in(dict(mobile_group_user_edits=True),
                       dict(mobile_group_intent=True,scenario='movement'),dict(mobile_group_intent=True)):
            with self.subTest(changes=changes):
                args=deepcopy(self.args)
                for k,val in changes.items():setattr(args,k,val)
                with self.assertRaises(AssertionError):v.prepare(args)
                self.assertFalse(args.output.exists())

    def test_prepared_group_user_edit_dependency_is_typed_and_rechecked(self):
        plan=v.prepare(self.args)
        for change in(dict(mobile_group_user_edits=True),dict(mobile_group_intent=1)):
            with self.subTest(change=change):
                changed=deepcopy(plan);changed.update(change)
                (self.args.output/'invocation.json').write_text(json.dumps(changed))
                with self.assertRaisesRegex(AssertionError,'group edits'):v.verify_prepared(self.args.output)

    def test_recovery_stall_requires_all_explicit_user_edit_dependencies_and_marker(self):
        for changes in(dict(mobile_recovery_stall=True),dict(mobile_recovery_stall=True,mobile_group_intent=True)):
            with self.subTest(changes=changes):
                args=deepcopy(self.args)
                for key,val in changes.items():setattr(args,key,val)
                with self.assertRaisesRegex(AssertionError,'recovery stall'):v.prepare(args)
        self.add_group_markers();self.args.mobile_group_intent=True;self.args.mobile_group_user_edits=True
        self.args.mobile_recovery_stall=True
        with self.assertRaisesRegex(AssertionError,'helper lacks explicit'):v.prepare(self.args)

    def test_recovery_stall_flag_forwarded_only_after_owned_preflight(self):
        self.add_group_markers(include_recovery=True)
        self.args.mobile_group_intent=self.args.mobile_group_user_edits=self.args.mobile_recovery_stall=True
        plan=v.prepare(self.args);self.assertTrue(plan['mobile_recovery_stall'])
        for slot in(0,1):
            extra=v.command_extra(plan,slot,self.args.output/'run')
            self.assertIn('-prediction-mobile-recovery-stall-smoke',extra)
            self.assertEqual(extra.count('-frame-timing-worlds=2'),1)
            self.assertNotIn('-prediction-movement-smoke',extra)
        plan['publication_source']='post-original-qpc'
        self.assertEqual(v.command_extra(plan,1,self.args.output/'run').count('-frame-timing-worlds=2'),1)
        plan['mobile_group_user_edits']=False
        (self.args.output/'invocation.json').write_text(json.dumps(plan))
        with self.assertRaisesRegex(AssertionError,'group edits'):v.verify_prepared(self.args.output)

    def test_recall_requires_explicit_preserve_scope_and_its_actual_helper_marker(self):
        for changes in(dict(mobile_recall=True),dict(mobile_recall=True,mobile_group_intent=True,scenario='movement'),
                       dict(mobile_recall=True,mobile_group_intent=True,mobile_group_user_edits=True),
                       dict(mobile_recall=True,mobile_group_intent=True,mobile_group_user_edits=True,mobile_recovery_stall=True)):
            with self.subTest(changes=changes):
                args=deepcopy(self.args)
                for key,val in changes.items():setattr(args,key,val)
                with self.assertRaises(AssertionError):v.prepare(args)
                self.assertFalse(args.output.exists())
        self.add_group_markers();self.args.mobile_recall=self.args.mobile_group_intent=True
        with self.assertRaisesRegex(AssertionError,'helper lacks explicit'):v.prepare(self.args)

    def test_recall_flag_is_forwarded_without_adding_edits_stall_or_generic_smoke(self):
        self.add_group_markers(include_recall=True);self.args.mobile_recall=self.args.mobile_group_intent=True
        plan=v.prepare(self.args);self.assertTrue(plan['mobile_recall'])
        for slot in(0,1):
            extra=v.command_extra(plan,slot,self.args.output/'run')
            self.assertIn('-prediction-mobile-recall-smoke',extra)
            for flag in('-prediction-mobile-group-user-edits-smoke','-prediction-mobile-recovery-stall-smoke',
                        '-prediction-movement-smoke','-frame-timing-worlds=2'):
                self.assertNotIn(flag,extra)
        for change in(dict(mobile_recall=1),dict(mobile_group_intent=False),dict(mobile_group_user_edits=True),
                      dict(mobile_recovery_stall=True)):
            with self.subTest(change=change):
                altered=deepcopy(plan);altered.update(change)
                (self.args.output/'invocation.json').write_text(json.dumps(altered))
                with self.assertRaisesRegex(AssertionError,'group edits'):v.verify_prepared(self.args.output)

    def test_focus_requires_explicit_preserve_scope_and_cannot_mix_recall_edits_or_stall(self):
        for changes in(dict(mobile_focus=True),dict(mobile_focus=True,mobile_group_intent=True,scenario='movement'),
                       dict(mobile_focus=True,mobile_group_intent=True,mobile_recall=True),
                       dict(mobile_focus=True,mobile_group_intent=True,mobile_group_user_edits=True),
                       dict(mobile_focus=True,mobile_group_intent=True,mobile_group_user_edits=True,mobile_recovery_stall=True)):
            with self.subTest(changes=changes):
                args=deepcopy(self.args)
                for key,val in changes.items():setattr(args,key,val)
                with self.assertRaises(AssertionError):v.prepare(args)
                self.assertFalse(args.output.exists())
        self.add_group_markers();self.args.mobile_focus=self.args.mobile_group_intent=True
        with self.assertRaisesRegex(AssertionError,'helper lacks explicit'):v.prepare(self.args)

    def test_focus_forwarding_prepared_contract_and_no_ordinary_diagnostic_expansion(self):
        self.add_group_markers(include_focus=True);self.args.mobile_focus=self.args.mobile_group_intent=True
        with patch.object(v.subprocess,'Popen',side_effect=AssertionError('Native forbidden')):
            plan=v.prepare(self.args);v.verify_prepared(self.args.output)
        self.assertTrue(plan['mobile_focus'])
        for slot in(0,1):
            extra=v.command_extra(plan,slot,self.args.output/'run')
            self.assertEqual(extra.count('-prediction-mobile-focus-smoke'),1)
            for flag in('-prediction-mobile-recall-smoke','-prediction-mobile-group-user-edits-smoke',
                        '-prediction-mobile-recovery-stall-smoke','-prediction-movement-smoke','-frame-timing-worlds=2'):
                self.assertNotIn(flag,extra)
        for change in(dict(mobile_focus=1),dict(mobile_group_intent=False),dict(mobile_recall=True),
                      dict(mobile_group_user_edits=True),dict(mobile_recovery_stall=True)):
            with self.subTest(change=change):
                altered=deepcopy(plan);altered.update(change)
                (self.args.output/'invocation.json').write_text(json.dumps(altered))
                with self.assertRaisesRegex(AssertionError,'group edits'):v.verify_prepared(self.args.output)

    def test_ordinary_startup_defaults_and_no_generic_smoke_are_unchanged(self):
        args=deepcopy(self.fixture.args)
        plan=v.prepare(args)
        self.assertEqual((plan['scenario'],plan['frames'],plan['surrender_frame']),('startup',200,260))
        self.assertNotIn('generic_movement_not_exercised',plan)
        extra=v.command_extra(plan,0,args.output/'run')
        self.assertNotIn('-prediction-movement-smoke',extra)
        self.assertNotIn('-prediction-mobile-correction-smoke',extra)

    def test_existing_movement_mobile_option_keeps_old_generic600_behavior(self):
        self.args.scenario='movement'
        plan=v.prepare(self.args)
        self.assertEqual(plan['frames'],600)
        self.assertNotIn('generic_movement_not_exercised',plan)
        for slot,start in((0,440),(1,460)):
            extra=v.command_extra(plan,slot,self.args.output/'run')
            self.assertIn('-prediction-movement-smoke',extra)
            self.assertIn(f'-prediction-movement-smoke-start-frame={start}',extra)
            self.assertIn('-prediction-mobile-correction-smoke',extra)

    def test_existing_hq_and_changing_movement_flags_are_preserved(self):
        for mode in('hq','changing'):
            with self.subTest(mode=mode):
                args=deepcopy(self.fixture.args);args.scenario='movement';args.output=self.fixture.root/f'local/{mode}'
                if mode=='hq':args.actor_correction=True
                else:args.changing_rtt=True
                plan=v.prepare(args);extra=v.command_extra(plan,0,args.output/'run')
                self.assertIn('-prediction-movement-smoke',extra)
                self.assertIn('-prediction-actor-correction-smoke'if mode=='hq'else'-prediction-movement-smoke-distance=48',extra)
                self.assertEqual(plan['frames'],600 if mode=='hq' else 650)

    def test_cli_accepts_named_mobile_scenario_without_executing(self):
        seen=[]
        def prepare(args):
            seen.append(args);return dict(output='authored',scenario=args.scenario)
        names=('game','assets','output','python','module-root','heap-helper','cooperative','helper-build-receipt')
        argv=['--scenario','mobile','--mobile-correction','--mobile-group-intent','--mobile-group-user-edits','--mobile-recovery-stall']
        for name in names:argv+=['--'+name,'authored']
        argv+=['--expected-helper-sha256','a'*64,'--expected-gameassembly-sha256','b'*64]
        with patch.object(v,'prepare',prepare),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(v.main(argv),0)
        self.assertEqual(seen[0].scenario,'mobile');self.assertTrue(seen[0].mobile_correction)
        self.assertTrue(seen[0].mobile_group_intent);self.assertTrue(seen[0].mobile_group_user_edits)
        self.assertTrue(seen[0].mobile_recovery_stall)
        argv=[arg for arg in argv if arg not in('--mobile-group-user-edits','--mobile-recovery-stall')]+['--mobile-recall']
        with patch.object(v,'prepare',prepare),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(v.main(argv),0)
        self.assertTrue(seen[1].mobile_recall);self.assertFalse(seen[1].mobile_group_user_edits)
        argv=[arg for arg in argv if arg!='--mobile-recall']+['--mobile-focus']
        with patch.object(v,'prepare',prepare),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(v.main(argv),0)
        self.assertTrue(seen[2].mobile_focus);self.assertFalse(seen[2].mobile_recall)


class MobileStateFixture:
    def __init__(self):
        self.matches=['a'*32,'b'*32]
        self.plan=dict(scenario='mobile',mobile_correction=True,lifecycle='natural',frames=650,expected_matches=2)
        self.states={m:{f:v.digest(f'{m}:{f}'.encode())for f in range(650+i)}for i,m in enumerate(self.matches)}
        self.workers={};self.logs={}
        for slot in(0,1):
            self.workers[slot]=[];ready=[]
            for i,match in enumerate(self.matches):
                world=slot*100+i+41
                ready.append(f'Movement prediction ready: generation={i+1} match={match} world={world} slot={slot} original=1')
                for f,h in self.states[match].items():
                    self.workers[slot].append(dict(schema=1,event='confirmed_native_state',world=world,frame=f,
                        parsed_state_sha256=h,confirmed_frontier=f,corrections=0,corrections_delta=0,
                        replayed_frames_total=0,replayed_frames_delta=0,tick_ms=i*10000+f))
            self.logs[slot]='\n'.join(ready)
        self.report=dict(scoped_observation_passed=False,mobile_input_witness_passed=False,
            movement_feel_witness_passed=False,full_feature_accepted=False,source_unchanged=True,files_unchanged=True,
            forced_cleanup=False,cleanup_errors=[],game_cleanup=[dict(natural_game_exit=True)for _ in(0,1)],
            matches=[dict(match=m,canonical_frames=650,exact_bridge_and_native_authority_receipts=True)for m in self.matches],
            clients=[dict(index=s,matches=self.matches,natural_worker_shutdown=True)for s in(0,1)],
            mobile_correction=dict(passed=True,episodes=[dict(match=m,world=141+i,passed=True)for i,m in enumerate(self.matches)]))

    def finalize(self):
        v.finalize_mobile_observation(self.report,self.plan,states=self.states,worker_state_rows=self.workers,client_logs=self.logs)
        return self.report


class MobileFinalGateTests(unittest.TestCase):
    def setUp(self):self.f=MobileStateFixture()

    def test_two_real_begin_mappings_and_all_closed_hashes_qualify_only_mobile_scope(self):
        r=self.f.finalize()
        self.assertTrue(r['mobile_input_witness_passed']);self.assertTrue(r['scoped_observation_passed'])
        self.assertEqual(r['mobile_state_parity']['checked_frames'],2602)
        self.assertTrue(r['generic_movement_not_exercised']);self.assertFalse(r['movement_feel_witness_passed'])
        self.assertFalse(r['full_mobile_controls_accepted']);self.assertFalse(r['full_feature_accepted'])
        self.assertTrue(v.mobile_final_gate(self.f.plan,r))

    def test_partial_missing_match_or_worker_never_qualifies_final_scope(self):
        for kind in('world','client','prefix','tail'):
            with self.subTest(kind=kind):
                f=MobileStateFixture()
                if kind=='world':f.workers[1]=[r for r in f.workers[1]if r['world']==141]
                elif kind=='client':f.workers.pop(0)
                elif kind=='prefix':f.report['matches'][0]['canonical_frames']=649
                else:f.workers[0].pop()
                with self.assertRaises(AssertionError):f.finalize()
                self.assertFalse(v.mobile_final_gate(f.plan,f.report))
                self.assertFalse(f.report['mobile_input_witness_passed'])

    def test_mobile_failure_or_wrong_episode_world_remains_final_red(self):
        for changes in('failed','missing','wrong_world'):
            with self.subTest(changes=changes):
                f=MobileStateFixture()
                if changes=='failed':f.report['mobile_correction']['passed']=False
                elif changes=='missing':f.report['mobile_correction']['episodes'].pop()
                else:f.report['mobile_correction']['episodes'][0]['world']=41
                with self.assertRaises(AssertionError):f.finalize()
                self.assertFalse(v.mobile_final_gate(f.plan,f.report))

    def test_any_closed_hash_mismatch_including_outside_mobile_window_or_prefix_fails(self):
        for frame in(0,140,649,650):
            with self.subTest(frame=frame):
                f=MobileStateFixture();world=142 if frame==650 else 141
                next(r for r in f.workers[1]if r['world']==world and r['frame']==frame)['parsed_state_sha256']='0'*64
                with self.assertRaisesRegex(AssertionError,'hashes differ'):f.finalize()
                self.assertFalse(v.mobile_final_gate(f.plan,f.report))

    def test_native_begin_slot_match_and_world_binding_is_not_inferred_from_row_order(self):
        for kind in('slot','match','world'):
            with self.subTest(kind=kind):
                f=MobileStateFixture()
                if kind=='slot':f.logs[1]=f.logs[1].replace('slot=1','slot=0')
                elif kind=='match':f.logs[1]=f.logs[1].replace('a'*32,'c'*32)
                else:f.logs[1]=f.logs[1].replace('world=142','world=141')
                with self.assertRaises(AssertionError):f.finalize()

    def test_final_gate_stays_red_for_force_source_error_or_generic_claim(self):
        f=self.f;r=f.finalize()
        for change in(dict(forced_cleanup=True),dict(source_unchanged=False),dict(files_unchanged=False),
                      dict(error='partial'),dict(movement_feel_witness_passed=True),dict(full_mobile_controls_accepted=True),
                      dict(mobile_input_witness_passed=False),dict(cleanup_errors=['failed cleanup'])):
            with self.subTest(change=change):
                altered=deepcopy(r);altered.update(change)
                self.assertFalse(v.mobile_final_gate(f.plan,altered))
        r['game_cleanup'][0]['natural_game_exit']=False
        self.assertFalse(v.mobile_final_gate(f.plan,r))

    def test_optional_group_gate_is_mandatory_only_when_requested_and_binds_both_rounds(self):
        f=self.f;self.assertTrue(v.mobile_final_gate(f.plan,f.finalize()))
        f.plan['mobile_group_intent']=True
        with self.assertRaisesRegex(AssertionError,'group intent witness'):f.finalize()
        self.assertFalse(v.mobile_final_gate(f.plan,f.report))
        f.report.update(group_intent_witness_passed=True,mobile_group_intent=dict(passed=True,user_edits=False,
            episodes=[dict(passed=True,match=m,world=141+i)for i,m in enumerate(f.matches)]))
        self.assertTrue(v.mobile_final_gate(f.plan,f.finalize()))
        for kind in('round','failed','mode','world'):
            with self.subTest(kind=kind):
                altered=deepcopy(f.report)
                if kind=='round':altered['mobile_group_intent']['episodes'].pop()
                elif kind=='failed':altered['mobile_group_intent']['passed']=False
                elif kind=='mode':altered['mobile_group_intent']['user_edits']=True
                else:altered['mobile_group_intent']['episodes'][0]['world']=999
                with self.assertRaises(AssertionError):
                    v.finalize_mobile_observation(altered,f.plan,states=f.states,worker_state_rows=f.workers,client_logs=f.logs)
                self.assertFalse(v.mobile_final_gate(f.plan,altered))

    def recovery_fixture(self):
        f=self.f
        f.plan.update(mobile_group_intent=True,mobile_group_user_edits=True,mobile_recovery_stall=True)
        for row in f.workers[1]:row['world']-=140
        f.logs[1]=f.logs[1].replace('world=141','world=1').replace('world=142','world=2')
        for row in f.report['mobile_correction']['episodes']:row['world']-=140
        f.report.update(group_intent_witness_passed=True,mobile_group_intent=dict(passed=True,user_edits=True,
            episodes=[dict(passed=True,match=match,world=i+1)for i,match in enumerate(f.matches)]))
        return f

    def test_recovery_gate_is_additive_and_mandatory_only_for_requested_stall(self):
        f=self.recovery_fixture()
        with self.assertRaisesRegex(AssertionError,'recovery stall witness'):f.finalize()
        self.assertFalse(v.mobile_final_gate(f.plan,f.report))
        f.report.update(recovery_stall_witness_passed=True,mobile_recovery_stall=dict(passed=True,world=2,match=f.matches[1]))
        self.assertTrue(v.mobile_final_gate(f.plan,f.finalize()))
        for change in(dict(passed=False),dict(world=1),dict(match=f.matches[0])):
            with self.subTest(change=change):
                altered=deepcopy(f.report);altered['mobile_recovery_stall'].update(change)
                with self.assertRaises(AssertionError):
                    v.finalize_mobile_observation(altered,f.plan,states=f.states,worker_state_rows=f.workers,client_logs=f.logs)
                self.assertFalse(v.mobile_final_gate(f.plan,altered))

    def test_observed_stall_cannot_override_body_phase_group_or_hash_failure(self):
        f=self.recovery_fixture()
        f.report.update(recovery_stall_witness_passed=True,mobile_recovery_stall=dict(passed=True,world=2,match=f.matches[1]))
        f.report['mobile_correction']['passed']=False
        with self.assertRaises(AssertionError):f.finalize()
        self.assertTrue(f.report['recovery_stall_witness_passed']);self.assertFalse(v.mobile_final_gate(f.plan,f.report))
        f.report['mobile_correction']['passed']=True
        f.workers[1][181]['parsed_state_sha256']='0'*64
        with self.assertRaises(AssertionError):f.finalize()
        self.assertFalse(v.mobile_final_gate(f.plan,f.report))

    def recall_fixture(self):
        f=self.f;f.plan.update(mobile_group_intent=True,mobile_recall=True)
        f.report.update(group_intent_witness_passed=True,mobile_group_intent=dict(passed=True,user_edits=False,
            episodes=[dict(passed=True,match=match,world=141+i)for i,match in enumerate(f.matches)]))
        return f

    def test_recall_gate_is_additive_requires_both_actual_rounds_and_preserve_scope(self):
        f=self.recall_fixture()
        with self.assertRaisesRegex(AssertionError,'recall witness'):f.finalize()
        self.assertFalse(v.mobile_final_gate(f.plan,f.report))
        f.report.update(recall_witness_passed=True,mobile_recall=dict(passed=True,
            episodes=[dict(passed=True,match=m,world=141+i)for i,m in enumerate(f.matches)]))
        self.assertTrue(v.mobile_final_gate(f.plan,f.finalize()))
        for kind in('missing','failed','world','match','edits','stall'):
            with self.subTest(kind=kind):
                altered=deepcopy(f.report);plan=deepcopy(f.plan)
                if kind=='missing':altered['mobile_recall']['episodes'].pop()
                elif kind=='failed':altered['mobile_recall']['episodes'][0]['passed']=False
                elif kind=='world':altered['mobile_recall']['episodes'][0]['world']=999
                elif kind=='match':altered['mobile_recall']['episodes'][0]['match']='c'*32
                elif kind=='edits':plan['mobile_group_user_edits']=True
                else:plan['mobile_recovery_stall']=True
                with self.assertRaises(AssertionError):
                    v.finalize_mobile_observation(altered,plan,states=f.states,worker_state_rows=f.workers,client_logs=f.logs)
                self.assertFalse(v.mobile_final_gate(plan,altered))

    def test_recall_witness_cannot_override_mobile_body_phase_or_closed_hash_failure(self):
        f=self.recall_fixture()
        f.report.update(recall_witness_passed=True,mobile_recall=dict(passed=True,
            episodes=[dict(passed=True,match=m,world=141+i)for i,m in enumerate(f.matches)]))
        f.report['mobile_correction']['passed']=False
        with self.assertRaises(AssertionError):f.finalize()
        self.assertFalse(v.mobile_final_gate(f.plan,f.report))
        f.report['mobile_correction']['passed']=True;f.workers[1][181]['parsed_state_sha256']='0'*64
        with self.assertRaisesRegex(AssertionError,'hashes differ'):f.finalize()
        self.assertFalse(v.mobile_final_gate(f.plan,f.report))

    def focus_fixture(self):
        f=self.f;f.plan.update(mobile_group_intent=True,mobile_focus=True)
        f.report.update(group_intent_witness_passed=True,mobile_group_intent=dict(passed=True,user_edits=False,
            episodes=[dict(passed=True,match=match,world=141+i)for i,match in enumerate(f.matches)]))
        return f

    def test_requested_focus_is_fail_closed_without_both_actual_world_envelopes(self):
        f=self.focus_fixture()
        with self.assertRaisesRegex(AssertionError,'focus witness'):f.finalize()
        self.assertFalse(v.mobile_final_gate(f.plan,f.report))
        # Authored final-envelope contract only; no actual event evaluator is
        # substituted by these synthetic rows.
        f.report.update(focus_witness_passed=True,mobile_focus=dict(passed=True,
            episodes=[dict(passed=True,match=m,world=141+i)for i,m in enumerate(f.matches)]))
        self.assertTrue(v.mobile_final_gate(f.plan,f.finalize()))
        for kind in('missing','failed','world','match','recall','edits','stall'):
            with self.subTest(kind=kind):
                altered=deepcopy(f.report);plan=deepcopy(f.plan)
                if kind=='missing':altered['mobile_focus']['episodes'].pop()
                elif kind=='failed':altered['mobile_focus']['episodes'][0]['passed']=False
                elif kind=='world':altered['mobile_focus']['episodes'][0]['world']=999
                elif kind=='match':altered['mobile_focus']['episodes'][0]['match']='c'*32
                elif kind=='recall':plan['mobile_recall']=True
                elif kind=='edits':plan['mobile_group_user_edits']=True
                else:plan['mobile_recovery_stall']=True
                with self.assertRaises(AssertionError):
                    v.finalize_mobile_observation(altered,plan,states=f.states,worker_state_rows=f.workers,client_logs=f.logs)
                self.assertFalse(v.mobile_final_gate(plan,altered))

    def test_focus_envelope_cannot_override_old_body_phase_or_all_closed_state_failure(self):
        f=self.focus_fixture()
        f.report.update(focus_witness_passed=True,mobile_focus=dict(passed=True,
            episodes=[dict(passed=True,match=m,world=141+i)for i,m in enumerate(f.matches)]))
        f.report['mobile_correction']['passed']=False
        with self.assertRaises(AssertionError):f.finalize()
        self.assertFalse(v.mobile_final_gate(f.plan,f.report))
        f.report['mobile_correction']['passed']=True;f.workers[1][181]['parsed_state_sha256']='0'*64
        with self.assertRaisesRegex(AssertionError,'hashes differ'):f.finalize()
        self.assertFalse(v.mobile_final_gate(f.plan,f.report))


if __name__=='__main__':unittest.main()
