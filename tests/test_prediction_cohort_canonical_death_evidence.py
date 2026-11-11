"""Authored partial-purge refusal controls; no original engine is executed."""
import copy,json,unittest
from pathlib import Path
from tools import prediction_cohort_canonical_death_evidence as e
from tools import prediction_cohort_survivor_evidence as survivor
from tools import verify_prediction_multiplayer as v
from tools.prediction_mobile_plan import validate_cohort_survivor_plan,cohort_evidence
from server.game_data import encode_identity,encode_player_input
from tests import test_prediction_cohort_survivor_evidence as prior
from tests.test_prediction_multi_unit_evidence import action

def plan():return dict(prior.plan(),cohort_canonical_death=True)

class Fixture(prior.Fixture):
    def command(self,s,f):
        if s==1:super().command(s,f)

    def __init__(self):
        super().__init__()
        self.actions[1]=action([12],self.target)
        self.raw[self.match,1,2]=encode_player_input(encode_identity(2,'human'),[self.actions[1]])
        self.commits=[x for x in self.commits if x['slot']==1]
        for r in self.journal:r['players']={0:[],1:[self.actions[1]]if r['frame']==181 else[]}
        for r in self.worker:r.update(corrections=0,corrections_delta=0,replayed_frames_total=0,replayed_frames_delta=0)
        for r in self.native:
            if r['frame']>=154:r['entities']=[x for x in r['entities']if x['id']==12];r['count']=len(r['entities'])
        for r in self.authority:
            if r['frame']>=154:r['victim']=None
            elif r['frame']==153:r['victim']['current_damage']=100
        self.bridges[153]['received_tick_ms']=8130
        for slot in(0,1):
            out=[]
            for line in self.logs[slot]:
                if survivor.PREFIX not in line:
                    if 'Original command batch submitted:'in line:
                        body=self.raw[self.match,1,2]
                        line=f'Original command batch submitted: match={self.match} sequence=2 actions=1 bytes={len(body)} body_sha256={e.shared.digest(body)} sendTick=9004 sourceNextFrame=181'
                    out.append(line);continue
                r=json.loads(line.split(survivor.PREFIX,1)[1]);f=r['frame']
                if r['event']in survivor.EVENTS-{'move_queued','serialized','batch_registered','authority'}:
                    r['confirmed_frame']=max(0,f-10)
                    for k in('group_raw_has_victim','group_helper_suspended','group_victim_intent_pending'):r[k]=None
                    if slot==1:
                        if r['event']=='restored':r['event']='sample'
                        r.update(group_raw_has_victim=f<163,group_helper_suspended=False,group_victim_intent_pending=154<=f<163)
                        r['group_ids']=r['group_all_ids']=r['group_typed_ids']=[11,12]if f<163 else[12]
                        if f>=154:
                            r['current_count']=r['group_count']=1
                            r['members'][0].update(actor=None,incarnation=0,canonical_token=11 if f<163 else 0,native_present=False,native_state=None,
                                admitted=False,initialized=False,original_active=False,original_retained=False,original_dead=True,original_component=False,
                                position=None,position_bits=None,position_sampled_us=None,jobs_joined=False,current_has_type=False,group_has_type=False)
                        if f==154:out.append(f'Prediction group intent retained: world=1 match={self.match} group=4 entity=11 token=11 originalMemberUnchanged=1 readd=0')
                        if f==163:
                            receipt=dict(schema=1,event='authority',world=1,match=self.match,slot=1,frame=163,completed_frame=163,
                                canonical_frame=153,tick_ms=8131,sampled_us=8131000,canonical_sha256='c'*64,wire_sha256=self.wires[153],physicalUI=False)
                            out.append(e.PREFIX+json.dumps(receipt))
                            out.append(f'Prediction group intent purged: world=1 match={self.match} group=4 entity=11 originalAPI=1 rawBuckets=1 rawCacheChanged=1 readd=0')
                            r['event']='confirmed_loss';out.append(e.PREFIX+json.dumps(r))
                            r=dict(r,event='purge_observed',sampled_us=r['sampled_us']+100)
                elif r['event']=='move_queued':
                    r.update(source_ids=[12],incarnations=[12],origins=[r['origins'][1]],origins_sampled_us=[r['origins_sampled_us'][1]])
                elif r['event']=='batch_registered':
                    r.update(action_sha256=e.shared.digest(self.actions[1]),body_sha256=e.shared.digest(self.raw[self.match,1,2]))
                out.append(e.PREFIX+json.dumps(r))
            self.logs[slot]=out

    def run(self):
        return e.evaluate('\n'.join(self.logs[1]),attacker_log='\n'.join(self.logs[0]),match=self.match,commits=self.commits,raw_bodies=self.raw,
            journal=self.journal,bridge_frames=self.bridges,canonical_payloads=self.wires,canonical_states=self.hashes,native_states=self.authority,
            worker_states=self.worker,escape_check=v.actor_escape_evidence,join_check=v.joined_worker_evidence,authority_rows=v.authority_rows,
            cohort_trace=self.native,native_receipts=self.receipts,peer_bridge_frames=self.bridges)

class CanonicalDeath(unittest.TestCase):
    def test_child_plan_requires_parent_and_forwards_exact_flag(self):
        p=plan();validate_cohort_survivor_plan(p);self.assertIs(cohort_evidence(p),e)
        p.update(files={k:{'path':k}for k in('python','heap_helper','cooperative')},module_root='root',surrender_frame=700)
        for slot in(0,1):self.assertIn('-prediction-cohort-canonical-death-smoke',v.command_extra(p,slot,Path('run')))
        for k,value in(('cohort_survivor',False),('cohort_canonical_death',1),('multi_unit_move',True),('mobile_group_intent',True)):
            x=plan();x[k]=value
            with self.subTest(k=k),self.assertRaises(AssertionError):validate_cohort_survivor_plan(x)

    def test_original_partial_purge_then_survivor_move_passes(self):
        r=Fixture().run();self.assertTrue(r['passed']);self.assertEqual(r['remaining_group_ids'],[12])
        self.assertEqual(r['fresh']['assigned_minus_canonical'],0);self.assertFalse(r['independent_correction_exercised'])

    def test_missing_mutation_ghost_whole_group_loss_and_reselection_refuse(self):
        for kind in('marker','no_change','reselect','ghost','survivor','pending','scope','missing_loss','premature'):
            f=Fixture();changed=[]
            for line in f.logs[1]:
                if kind=='marker'and 'intent purged:'in line:continue
                if kind=='no_change':line=line.replace('rawCacheChanged=1','rawCacheChanged=0')
                if line.startswith(e.PREFIX):
                    r=json.loads(line[len(e.PREFIX):])
                    if kind=='missing_loss'and r['event']=='confirmed_loss':continue
                    if r['event']=='purge_observed':
                        if kind=='ghost':r['group_typed_ids']=[11,12]
                        elif kind=='survivor':r['group_ids']=r['group_all_ids']=r['group_typed_ids']=[]
                        elif kind=='pending':r['group_victim_intent_pending']=True
                        elif kind=='scope':r['group_helper_suspended']=True
                        elif kind=='reselect':r['selection_calls']=2
                    if kind=='premature'and r['event']=='released':r['group_ids']=r['group_all_ids']=r['group_typed_ids']=[12];r['group_raw_has_victim']=False
                    line=e.PREFIX+json.dumps(r)
                changed.append(line)
            f.logs[1]=changed
            with self.subTest(kind=kind),self.assertRaises(AssertionError):f.run()

    def test_dead_command_source_changed_lease_hash_motion_and_extra_escape_refuse(self):
        for kind in('body','lease','hash','motion','escape'):
            f=Fixture()
            if kind=='body':f.raw[f.match,1,2]=encode_player_input(encode_identity(2,'human'),[action([11,12],f.target)])
            elif kind=='lease':f.logs[1]=[x.replace('"incarnations": [12]','"incarnations": [99]')for x in f.logs[1]]
            elif kind=='hash':f.worker[190]['parsed_state_sha256']='f'*64
            elif kind=='escape':f.journal[151]['players'][0]=[f.actions[0]]
            else:
                for r in f.native:
                    next(x for x in r['entities']if x['id']==12).update(position=[-80.,0.,-60.],position_bits=prior.bits([-80.,0.,-60.]))
            with self.subTest(kind=kind),self.assertRaises(AssertionError):f.run()

    def test_two_world_outer_gate_requires_named_partial_purge_witness(self):
        from tests.test_prediction_mobile_controller import MobileStateFixture
        r=Fixture().run();f=MobileStateFixture();f.plan.update(plan())
        episodes=[dict(copy.deepcopy(r),match=m,world=141+i)for i,m in enumerate(f.matches)]
        f.report['mobile_correction']=dict(passed=True,episodes=episodes);e.decorate(f.report,episodes)
        self.assertTrue(v.mobile_final_gate(f.plan,f.finalize()));self.assertNotIn('survivor_witness_passed',f.report)
        self.assertIn('canonical death',f.report['mobile_scope'])
        for kind in('missing','failed','ghost','reselect','borrowed','parity'):
            changed=copy.deepcopy(f.report)
            if kind=='missing':changed['cohort_canonical_death']['episodes'].pop()
            elif kind=='failed':changed['partial_canonical_purge_witness_passed']=False
            elif kind=='ghost':changed['cohort_canonical_death']['episodes'][1]['remaining_group_ids']=[11,12]
            elif kind=='reselect':changed['cohort_canonical_death']['episodes'][1]['reselection_calls']=1
            elif kind=='borrowed':changed['survivor_witness_passed']=True
            else:changed['mobile_state_parity']['passed']=False
            self.assertFalse(v.mobile_final_gate(f.plan,changed),kind)

    def test_death_receipt_uses_actual_dense65_and_independent_wires(self):
        for kind in('missing','duplicate','wire','native','wrong_world','sparse_substitute'):
            f=Fixture()
            lines=[x for x in f.logs[1]if x.startswith(e.PREFIX)and json.loads(x[len(e.PREFIX):]).get('canonical_frame')==153]
            self.assertEqual(len(lines),1);line=lines[0]
            if kind in('missing','sparse_substitute'):
                f.logs[1].remove(line)
                if kind=='sparse_substitute':
                    r=json.loads(line[len(e.PREFIX):]);f.logs[1].append('MOVEMENT AUTHORITY '+json.dumps(dict(schema=1,world=1,match=f.match,frame=153,
                        tick_ms=r['tick_ms'],canonical_sha256=r['canonical_sha256'],wire_sha256=r['wire_sha256'])))
            elif kind=='duplicate':f.logs[1].insert(f.logs[1].index(line),line)
            elif kind=='native':f.receipts[1,f.match][153]['sha256']='f'*64
            else:
                r=json.loads(line[len(e.PREFIX):]);r['wire_sha256'if kind=='wire'else'world']='f'*64 if kind=='wire'else 2
                f.logs[1][f.logs[1].index(line)]=e.PREFIX+json.dumps(r)
            with self.subTest(kind=kind),self.assertRaises(AssertionError):f.run()

if __name__=='__main__':unittest.main()
