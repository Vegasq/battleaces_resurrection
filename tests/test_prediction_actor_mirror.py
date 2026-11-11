"""Authored Core0 mirror controls; no game, worker, DLL or input is executed."""
from copy import deepcopy
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from server.game_data import GameDataError, encode_identity, encode_player_input
from server.protobuf_wire import field_bytes, field_packed_uint, field_uint, get_bytes, get_repeated_bytes, get_uint, replace_fields, signed64
from tests import test_prediction_actor_fixture as actor_tests
from tests.test_prediction_held_click_evidence import fixture as held_fixture, render
from tests import test_prediction_multiplayer_verifier as verifier_tests
from tools import prediction_actor_fixture as fixture
from tools import prediction_held_click_evidence as held
from tools import verify_prediction_multiplayer as verifier


def mirror_held():
    records,episodes=held_fixture()
    frames={'held_checkpoint':152,'dead_hq_retained':154}
    for prefix,row in records:
        row['entity']=0
        if prefix==held.PREFIX:
            row.update(schema=2,slot=0,army=0)
            row['current_exact_entity']=row.pop('current_exact5')
            row['preview_exact_entity']=row.pop('preview_exact5')
            row['current_ids']=[0] if row['current_ids'] else []
            row['preview_ids']=[0] if row['preview_ids'] else []
            if row['click_id']==5:row['click_id']=0
            row['frame']=frames.get(row['event'],row['frame'])
        else:
            row['army']=0
            if row['event']==held.ACTOR_EVENTS[1]:row['frame']=154
    for episode in episodes:
        episode['rows']=[deepcopy(row) for prefix,row in records if prefix=='ACTOR CORRECTION ' and row['match']==episode['match']]
    return records,episodes


def mirror_actor(commit_frame=151):
    source=verifier_tests.ActorCorrectionFixtureTests();source.setUp()
    source.metadata=fixture.metadata(True)
    for row,frame in zip(source.rows,(130,154,158,165)):row.update(entity=0,army=0,frame=frame)
    position=b''.join(field_uint(n,int(value*2**32)&(2**64-1))for n,value in enumerate(source.metadata['target'],1))
    group=field_uint(1,1)+field_uint(2,12)+field_packed_uint(3,[10])
    source.action=field_bytes(1,field_bytes(1,group)+field_bytes(3,field_bytes(3,field_bytes(1,position))))
    source.body=encode_player_input(encode_identity(2,'Owned mirror attacker'),[source.action])
    source.order.update(army=1,frame=150,action_sha256=verifier.digest(source.action))
    source.commits[0].update(slot=1,frame=commit_frame)
    source.authority['frame']=commit_frame;source.bridge[0]['frame']=commit_frame
    source.journal=[dict(frame=commit_frame,players={0:[],1:[source.action]})]
    for row in source.worker:
        frame=row['frame'];row.update(corrections=int(frame>=commit_frame),corrections_delta=int(frame==commit_frame),
            replayed_frames_total=3 if frame>=commit_frame else 0,replayed_frames_delta=3 if frame==commit_frame else 0,
            tick_ms=1000+frame*5 if frame<commit_frame else 2160+(frame-commit_frame)*10)
    source.native=source.native[:44] # Exact metadata range130..173.
    for row in source.native:
        row['core'].update(id=0,army=0,current_damage=0 if row['frame']<142 else 50)
        row['attacker']['army']=1
    source.pool=source.pool.replace('entity=5 ','entity=0 ').replace('oldArmy=1 ','oldArmy=0 ').replace('correctedArmy=1 ','correctedArmy=0 ')
    def evaluate(**changes):
        args=dict(attacker_log=source.attacker_log().replace('speculativeFrame=153','speculativeFrame=151'),
            match=source.match,commits=source.commits,raw_bodies={(source.match,1,2):source.body},
            journal=source.journal,bridge_frames=source.bridge,canonical_payloads={commit_frame:'b'*64},
            canonical_states=source.states,native_states=source.native,worker_states=source.worker,fixture=source.metadata)
        args.update(changes)
        return verifier.actor_correction_evidence(source.victim_log(),**args)
    source.mirror_evaluate=evaluate
    return source


class MirrorFixtureTests(unittest.TestCase):
    def setUp(self):
        self.host=actor_tests.ActorFixtureTests();self.host.setUp();self.addCleanup(self.host.doCleanups)
        initial=list(get_repeated_bytes(self.host.base.raw_game_data,2))
        core=get_bytes(initial[0],2)
        core=replace_fields(core,{3:[field_bytes(3,fixture._position_bytes((103.77999877929688,0,80.8499984741211)))]})
        initial[0]=field_bytes(2,core)
        self.base=self.host.load(replace_fields(self.host.base.raw_game_data,{2:[field_bytes(2,a)for a in initial]}))

    def test_metadata_v3_keeps_safe_margin_and_records_ready_subject_build_without_changing_default(self):
        old=fixture.metadata();mirror=fixture.mirror_metadata()
        self.assertEqual(mirror,fixture.metadata(True))
        self.assertEqual((mirror['victim_core_id'],mirror['victim_slot'],mirror['attacker_slot'],mirror['seed']),(0,0,1,20261112))
        self.assertEqual(mirror['name'],'original-gunbot-core-move-mirror-v3')
        self.assertEqual(mirror['normal_build_frames'],[250,400])
        self.assertEqual(mirror['ready_subject_frames'],[420,440])
        self.assertEqual(mirror['safe_canonical_frames'],[151,152]);self.assertEqual(mirror['expected_canonical_frame'],151)
        self.assertEqual(mirror['baseline_first_damage_frame'],142)
        self.assertEqual(mirror['baseline_death_frame'],153)
        mirror['safe_canonical_frames'].append(153);self.assertEqual(fixture.metadata(True)['safe_canonical_frames'],[151,152])
        self.assertEqual(fixture.metadata(),old)
        self.assertEqual(old['name'],'original-gunbot-core-move-v1')
        self.assertEqual(old['safe_canonical_frames'],[152,153,154])

    def test_mirror_keeps_initial_entities_and_changes_only_extra_spawn_vs_default(self):
        before=self.base.raw_game_data
        legacy=fixture.make_template(self.base,self.host.assets)
        mirrored=fixture.make_template(self.base,self.host.assets,mirror=True)
        old=get_repeated_bytes(legacy.raw_game_data,2);new=get_repeated_bytes(mirrored.raw_game_data,2)
        self.assertEqual(new[:-1],get_repeated_bytes(before,2));self.assertEqual(new[:-1],old[:-1])
        self.assertEqual(legacy.game_config,mirrored.game_config);self.assertEqual(self.base.raw_game_data,before)
        create=get_bytes(new[-1],2);self.assertEqual((get_uint(create,1),get_uint(create,2)),(1,1))
        self.assertEqual(fixture._position(get_bytes(create,3)),(99.77999877929688,0,80.8499984741211))
        rotation=get_bytes(create,4)
        self.assertEqual(signed64(get_uint(rotation,2)),int(math.sqrt(.5)*2**32))
        self.assertEqual(get_uint(rotation,4),int(math.sqrt(.5)*2**32))
        self.assertEqual(legacy.raw_game_data,fixture.make_template(self.base,self.host.assets,mirror=False).raw_game_data)

    def test_normal_roster_and_decks_own_match_with_attacker_legality_and_mirror_seed(self):
        result=fixture.make_template(self.base,self.host.assets,mirror=True)
        decks={0:tuple(range(100,108)),1:(1,*range(101,108))};before=deepcopy(decks)
        match=result.build_match(self.host.roster,decks,9,'authored mirror',game_mode=1)
        self.assertEqual(match.seed,20261112);self.assertEqual(dict(match.decks_by_slot),before);self.assertEqual(decks,before)
        self.assertEqual(result.fixture_metadata,fixture.MIRROR_METADATA)
        with self.assertRaisesRegex(GameDataError,'slot1.*Gunbot1'):
            result.build_match(self.host.roster,self.host.decks)

    def test_wrong_core0_position_or_nonboolean_mirror_refuses(self):
        for value in (1,'true',None):
            with self.subTest(value=value),self.assertRaisesRegex(GameDataError,'Boolean'):
                fixture.make_template(self.base,self.host.assets,mirror=value)
        with self.assertRaisesRegex(GameDataError,'victim Core position'):
            fixture.make_template(self.host.base,self.host.assets,mirror=True)


class MirrorHeldTests(unittest.TestCase):
    def setUp(self):self.records,self.episodes=mirror_held()
    def row(self,phase,world=1):return next(r for p,r in self.records if p==held.PREFIX and r['event']==phase and r['world']==world)
    def evaluate(self,**changes):
        args=dict(actor_episodes=self.episodes,expected_matches=['a'*32,'b'*32],fixture=fixture.metadata(True));args.update(changes)
        return held.evaluate(render(self.records),**args)

    def test_two_explicit_mirror_episodes_and_original_up_identity_zero_pass(self):
        result=self.evaluate();self.assertTrue(result['passed']);self.assertEqual(result['fixture'],fixture.metadata(True))
        self.assertTrue(all(r['canonical_identity_preserved'] and r['genuine_original_up_confirmed']for r in result['episodes']))
        self.assertEqual(self.row('complete')['current_ids'],[0]);self.assertEqual(self.row('complete')['preview_ids'],[])

    def test_schema_and_explicit_metadata_cannot_cross_legacy_mirror(self):
        for description in (None,fixture.metadata()):
            with self.subTest(description=description),self.assertRaises(AssertionError):self.evaluate(fixture=description)
        old,actors=held_fixture()
        with self.assertRaises(AssertionError):held.evaluate(render(old),actor_episodes=actors,expected_matches=['a'*32,'b'*32],fixture=fixture.metadata(True))
        malformed=fixture.metadata(True);malformed['safe_canonical_frames']=[150,151,152]
        with self.assertRaisesRegex(AssertionError,'unqualified'):self.evaluate(fixture=malformed)

    def test_exact_field_schema_and_role_mismatches_refuse(self):
        original=deepcopy(self.records)
        for key,value in (('army',1),('army',False),('slot',1),('entity',5),('schema',1),('current_exact5',True)):
            self.records=deepcopy(original);self.row('pressed')[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(AssertionError):self.evaluate()
        self.records=deepcopy(original);del self.row('pressed')['army']
        with self.assertRaises(AssertionError):self.evaluate()

    def test_finite_predeath_and_observed_death_restore_contract(self):
        original=deepcopy(self.records)
        for phase,frame in (('pressed',153),('held_checkpoint',154),('dead_hq_retained',155),
                ('hq_restored',154),('hq_restored',165),('release_queued',164),('released',168)):
            self.records=deepcopy(original);self.row(phase)['frame']=frame
            with self.subTest(phase=phase,frame=frame),self.assertRaises(AssertionError):self.evaluate()

    def test_raw_cache_token_serial_noop_and_actual_up_still_required(self):
        original=deepcopy(self.records)
        for phase,key,value in (('pressed','current_exact_entity',False),('preview_ready','preview_ids',[0,5]),
                ('hq_restored','current_token',0),('hq_restored','current_token',72),
                ('preview_ready','accepted_down_serial',3),('preview_ready','selectionWritesAfterPress',1),
                ('released','primary',True),('released','current_ids',[]),('released','preview_empty',False)):
            self.records=deepcopy(original);self.row(phase)[key]=value
            with self.subTest(phase=phase,key=key),self.assertRaises(AssertionError):self.evaluate()

    def test_source_actor_role_cannot_be_relabelled_by_held_rows(self):
        for row in self.episodes[0]['rows']:row.update(entity=5,army=1)
        for prefix,row in self.records:
            if prefix=='ACTOR CORRECTION ' and row['world']==1:row.update(entity=5,army=1)
        with self.assertRaisesRegex(AssertionError,'HQ proof'):self.evaluate()


class MirrorActorEvidenceTests(unittest.TestCase):
    def test_real_actor_journal_native67_72_65_and_replay_twenty_are_bound(self):
        for frame in (151,152):
            with self.subTest(frame=frame):
                source=mirror_actor(frame);result=source.mirror_evaluate()
                self.assertTrue(result['passed']);self.assertEqual(result['escape']['canonical_commit_frame'],frame)
                self.assertEqual(result['escape']['target'],fixture.metadata(True)['target'])
                self.assertEqual(result['continuation_frames'],20)

    def test_unobserved_commit_margin_frames_do_not_pass(self):
        for frame in (150,153):
            source=mirror_actor(frame)
            with self.subTest(frame=frame),self.assertRaisesRegex(AssertionError,'qualified margin'):source.mirror_evaluate()

    def test_mirror_v1_metadata_is_not_silently_upgraded(self):
        source=mirror_actor(152)
        old=dict(source.metadata,name='original-gunbot-core-move-mirror-v1',safe_canonical_frames=[151])
        with self.assertRaisesRegex(AssertionError,'unqualified actor fixture metadata'):
            source.mirror_evaluate(fixture=old)

    def test_default_or_wrong_hero_army_and_wrong_damage_onset_refuse(self):
        for kind in ('metadata','army','damage'):
            source=mirror_actor()
            if kind=='metadata':source.metadata=fixture.metadata()
            elif kind=='army':source.native[0]['attacker']['army']=0
            else:source.native[12]['core']['current_damage']=0
            with self.subTest(kind=kind),self.assertRaises(AssertionError):source.mirror_evaluate()

    def test_positive_target_is_exact_even_when_action_hash_is_rebound(self):
        source=mirror_actor()
        position=b''.join(field_uint(n,int(-value*2**32)&(2**64-1))for n,value in enumerate(source.metadata['target'],1))
        group=field_uint(1,1)+field_uint(2,12)+field_packed_uint(3,[10])
        source.action=field_bytes(1,field_bytes(1,group)+field_bytes(3,field_bytes(3,field_bytes(1,position))))
        source.body=encode_player_input(encode_identity(2,'Owned mirror attacker'),[source.action])
        source.order['action_sha256']=verifier.digest(source.action)
        source.journal[0]['players'][1]=[source.action]
        with self.assertRaisesRegex(AssertionError,'ToProto target'):source.mirror_evaluate()


class MirrorVerifierTests(unittest.TestCase):
    def setUp(self):
        self.host=verifier_tests.PreparationTests();self.host.setUp();self.addCleanup(self.host.doCleanups)

    def enable(self,marker=True):
        args=self.host.args;args.scenario='movement';args.actor_correction=True;args.held_click=True;args.actor_mirror=True;args.rtt_ms=(475,130)
        helper=self.host.game/'BattleAcesOffline.dll'
        helper.write_bytes(helper.read_bytes()+'-prediction-held-click-smoke'.encode('utf-16-le')+
            ('-prediction-actor-mirror-smoke'.encode('utf-16-le')if marker else b''))
        args.expected_helper_sha256=verifier.sha(helper)
        for path in (self.host.game/'.battleaces-resurrection/patch-manifest.json',args.helper_build_receipt):
            value=json.loads(path.read_text());value['helper_sha256']=args.expected_helper_sha256;path.write_text(json.dumps(value))
        return args

    def test_explicit_prepare_freezes_roles_rtt_and_flag_both_clients_without_spawning(self):
        args=self.enable()
        with patch.object(verifier.subprocess,'Popen',side_effect=AssertionError('must not spawn')):plan=verifier.prepare(args)
        self.assertEqual(plan['actor_fixture'],fixture.metadata(True));self.assertIs(plan['actor_mirror'],True)
        self.assertEqual(plan['rtt_ms'],[475,130]);self.assertEqual(plan['move_slot'],0)
        self.assertEqual(verifier.verify_prepared(args.output),plan)
        for slot in (0,1):self.assertIn('-prediction-actor-mirror-smoke',verifier.command_extra(plan,slot,args.output/'run'))

    def test_wrong_marker_refuses_before_output(self):
        args=self.enable(False)
        with self.assertRaisesRegex(AssertionError,'helper lacks explicit -prediction-actor-mirror-smoke'):verifier.prepare(args)
        self.assertFalse(args.output.exists())

    def test_ready_subject_build_requires_exact_mirror_plan_and_successful_original_enqueue(self):
        plan=dict(actor_mirror=True,actor_fixture=fixture.metadata(True))
        subject='LAN NORMAL BUILD smoke frame250 slot0 army0 HQ0 deckSlot0 unitType1 ability34 cost=(50,0) prerequisite=1 queued=1 commandQueueDelta=1 presentedFrame=258'
        legacy=subject.replace('frame250','frame300')
        peer=subject.replace('frame250','frame400').replace('slot0','slot1').replace('army0','army1').replace('unitType1','unitType6')
        self.assertEqual(verifier.planned_normal_build_units(subject,0,plan),[1])
        self.assertEqual(verifier.normal_build_units(subject,0),[])
        self.assertEqual(verifier.planned_normal_build_units(legacy,0,plan),[])
        self.assertEqual(verifier.planned_normal_build_units(legacy,0,{}),[1])
        self.assertEqual(verifier.planned_normal_build_units(peer,1,plan),[6])
        for old,new in (('prerequisite=1','prerequisite=0'),('queued=1','queued=0'),('commandQueueDelta=1','commandQueueDelta=0')):
            self.assertEqual(verifier.planned_normal_build_units(subject.replace(old,new),0,plan),[])
        for description in (None,fixture.metadata(),dict(fixture.metadata(True),normal_build_frames=[300,400])):
            with self.subTest(description=description),self.assertRaisesRegex(AssertionError,'mirror fixture changed'):
                verifier.planned_normal_build_units(subject,0,dict(plan,actor_fixture=description))
        for slot in (-1,2,True,'0'):
            with self.subTest(slot=slot),self.assertRaises(AssertionError):verifier.planned_normal_build_units(subject,slot,plan)
        for frame in (0,249,251,True,'250'):
            with self.subTest(frame=frame),self.assertRaises(AssertionError):verifier.normal_build_units(subject,0,expected_frame=frame)

    def test_admitted_activation_does_not_substitute_for_original_native_readiness(self):
        state=dict(frame=440,entities=[dict(id=75,army=0,type=1)])
        args=dict(frame=440,slot=0,entity=75,unit_type=1)
        self.assertEqual(verifier.validate_ready_subject(state,{75:0},**args)['native_state'],0)
        for mode in (None,1,6,7,9,12):
            with self.subTest(mode=mode),self.assertRaisesRegex(AssertionError,'not native IDLE'):
                verifier.validate_ready_subject(state,{}if mode is None else {75:mode},**args)
        for changed in (dict(state,frame=420),dict(state,entities=[]),dict(state,entities=[dict(id=75,army=1,type=1)]),
                dict(state,entities=[dict(id=75,army=0,type=6)])):
            with self.subTest(changed=changed),self.assertRaises(AssertionError):verifier.validate_ready_subject(changed,{75:0},**args)

    def test_cli_mirror_is_explicit_and_metadata_tamper_refuses_prepared_plan(self):
        base=[]
        for name in ('game','assets','output','python','module-root','heap-helper','cooperative','helper-build-receipt'):
            base+=['--'+name,str(self.host.root/name)]
        base+=['--expected-helper-sha256','a'*64,'--expected-gameassembly-sha256','b'*64]
        with patch.object(verifier,'prepare',return_value=dict(output='owned',scenario='movement')) as prepared,patch('builtins.print'):
            verifier.main(base+['--scenario','movement','--actor-correction','--held-click','--actor-mirror'])
            self.assertIs(prepared.call_args[0][0].actor_mirror,True)
            verifier.main(base);self.assertIs(prepared.call_args[0][0].actor_mirror,False)
        args=self.enable();verifier.prepare(args)
        path=args.output/'invocation.json';plan=json.loads(path.read_text());plan['actor_fixture']['safe_canonical_frames']=[150,151,152]
        path.write_text(json.dumps(plan))
        with self.assertRaisesRegex(AssertionError,'metadata changed'):verifier.verify_prepared(args.output)

    def test_scope_and_metadata_are_closed_not_just_swapped_rtt(self):
        args=self.enable();plan=dict(actor_mirror=True,held_click=True,actor_correction=True,scenario='movement',lifecycle='natural',frames=650,expected_matches=2,move_slot=0,rtt_ms=[475,130],actor_fixture=fixture.metadata(True))
        verifier.validate_held_click_plan(plan)
        for key,value in (('actor_mirror',1),('held_click',False),('actor_correction',False),('rtt_ms',[130,475]),
                ('move_slot',1),('expired_click',True),('mobile_correction',True),('frames',600),('actor_fixture',fixture.metadata())):
            changed=dict(plan);changed[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):verifier.validate_held_click_plan(changed)
        args.actor_mirror='yes'
        with self.assertRaisesRegex(AssertionError,'Boolean'):verifier.prepare(args)

    def test_context_uses_victim_zero_log_wire_and_explicit_metadata(self):
        plan=dict(actor_mirror=True,actor_fixture=fixture.metadata(True),frames=650)
        clients=[dict(log='victim0',wire=['wire0']),dict(log='attacker1',wire=['wire1'])]
        with patch('tools.verify_original_command_scheduling.read_journal',return_value=['journal']) as read:
            context=verifier.actor_context_for_match(plan,clients,match='a'*32,events=[],raw_bodies={},run=Path('owned'),states={'a'*32:{}},native_states={'a'*32:[]})
        self.assertEqual((context['log'],context['attacker_log'],context['bridge_frames']),('victim0','attacker1',['wire0']))
        self.assertEqual(context['fixture'],fixture.metadata(True));read.assert_called_once_with(Path('owned'),'a'*32,650)

    def test_only_explicit_mirror_routes_template_and_keeps_default_call_signature(self):
        base=object();product=object()
        with patch.object(fixture,'make_template',return_value=product) as make:
            self.assertIs(verifier.match_template(base,Path('assets'),actor_correction=True,actor_mirror=True),product)
            make.assert_called_once_with(base,Path('assets'),mirror=True)

    def test_held_finalize_preserves_two_actor_checks_and_rejects_legacy_proof(self):
        records,actors=mirror_held();matches=[a['match']for a in actors];log=render(records)
        plan=dict(actor_mirror=True,held_click=True,actor_correction=True,scenario='movement',lifecycle='natural',frames=650,expected_matches=2,move_slot=0,rtt_ms=[475,130],actor_fixture=fixture.metadata(True))
        contexts=[dict(match=m,log=log,fixture=fixture.metadata(True))for m in matches]
        report=dict(matches=[dict(match=m)for m in matches],actor_correction=dict(passed=True))
        with patch.object(verifier,'actor_correction_evidence',side_effect=lambda **kw:{k:v for k,v in actors[matches.index(kw['match'])].items()if k!='match'}) as evaluate:
            verifier.finalize_held_click_observation(report,plan,contexts=contexts,worker_states={})
        self.assertEqual(evaluate.call_count,2);self.assertTrue(verifier.held_click_final_gate(plan,report))
        report['held_click'].pop('fixture');self.assertFalse(verifier.held_click_final_gate(plan,report))


if __name__=='__main__':unittest.main()
