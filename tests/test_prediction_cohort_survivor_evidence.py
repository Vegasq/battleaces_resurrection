"""Pure survivor-cohort evidence controls, never an engine/runtime proof."""
import copy,json,math,struct,unittest
from pathlib import Path
from tools import prediction_cohort_survivor_evidence as e
from tools import verify_prediction_multiplayer as v
from tools.prediction_mobile_plan import validate_cohort_survivor_plan
from server.game_data import encode_identity,encode_player_input
from tests.test_prediction_multi_unit_evidence import action

f32=lambda x:struct.unpack('<f',struct.pack('<f',x))[0]
bits=lambda p:[struct.unpack('<I',struct.pack('<f',x))[0]for x in p]
def plan():return dict(cohort_survivor=True,scenario='mobile',mobile_correction=True,lifecycle='natural',frames=650,expected_matches=2,move_slot=0,rtt_ms=[130,475],native_position_trace=None,native_cohort_spec='1:1:130:220:8')
class Fixture:
 def __init__(self):
  self.match='a'*32;self.world=1;self.logs={0:[],1:[]};self.hashes={f:e.shared.digest(str(f).encode())for f in range(241)};self.wires={f:e.shared.digest(('w'+str(f)).encode())for f in self.hashes}
  self.target=[-35.,0.,-22.];self.actions={0:action([10],[-32.,0.,0.]),1:action([11,12],self.target)}
  self.raw={(self.match,s,2):encode_player_input(encode_identity(s+1,'human'),[self.actions[s]])for s in(0,1)}
  self.commits=[dict(event='command_batch_committed',match=self.match,slot=s,sequence=2,frame=151 if s==0 else 181)for s in(0,1)]
  self.journal=[dict(frame=f,players={0:[self.actions[0]]if f==151 else[],1:[self.actions[1]]if f==181 else[]})for f in self.hashes]
  self.bridges=[dict(match=self.match,frame=f,received_tick_ms=7820 if f==151 else 9490 if f==181 else f*50+500,payload_sha256=self.wires[f])for f in self.hashes]
  self.receipts={(s,self.match):[dict(frame=f,sha256=self.wires[f])for f in self.hashes]for s in(0,1)}
  self.worker=[];self.native=[];self.authority=[]
  for f in self.hashes:
   tick=f*50 if f<151 else 7890 if f<=152 else 7890+(f-152)*50 if f<181 else 9510+(f-181)*50
   self.worker.append(dict(schema=1,event='confirmed_native_state',world=1,frame=f,parsed_state_sha256=self.hashes[f],confirmed_frontier=152 if f==151 else f,
    corrections=int(f>=151),corrections_delta=int(f==151),replayed_frames_total=8*int(f>=151),replayed_frames_delta=8*int(f==151),tick_ms=tick))
  for f in range(130,221):
   for s in(0,1):
    ev='setup'if s==0 and f==130 else'selected'if f==130 else'native_dead'if s==1 and f==153 else'released'if s==1 and f==154 else'restored'if s==1 and f==161 else'complete'if f==220 else'sample'
    self.emit(s,self.snapshot(s,f,ev))
    if f==(150 if s==0 else 180):self.command(s,f)
    if s==1 and f in(157,190):
     c=151 if f==157 else 181;rr=dict(schema=1,world=1,match=self.match,frame=c,tick_ms=7852 if c==151 else 9502,canonical_sha256='c'*64,wire_sha256=self.wires[c]);self.logs[s].append('MOVEMENT AUTHORITY '+json.dumps(rr))
     self.emit(s,dict(schema=1,event='authority',world=1,match=self.match,slot=s,frame=f,completed_frame=f,tick_ms=rr['tick_ms'],sampled_us=rr['tick_ms']*1000,canonical_frame=c,canonical_sha256='c'*64,wire_sha256=self.wires[c],physicalUI=False))
   entities=[]
   for entity in(11,12):
    if entity==11 and 154<=f<=160:continue
    p=self.position(entity,f);entities.append(dict(id=entity,type=1,army=1,position=p,position_bits=bits(p)))
   self.native.append(dict(schema=1,event='native_cohort_positions',record=len(self.native),world=1,frame=f,revision=0,query_revision=0,checkpoint_base=None,first_divergent_frame=None,cohort_spec=e.SPEC,context_source='same_decoded_native_query',stage='ordinary',head=f-1,confirmed=f-10,received=f-10,corrections=0,replayed_frames=0,
    query_begin_us=f*50000+10,query_end_us=f*50000+20,query_begin_tick_ms=f*50,query_end_tick_ms=f*50+1,status='present',count=len(entities),entities=entities,clock_source='python.perf_counter_ns//1000',query_scope='existing-native-make-get-and-decode'))
   victim=dict(id=11,type=1,army=1,max_health=100,current_damage=0 if f<142 else 50)
   attacker=dict(id=10,type=1,army=0,max_health=100,current_damage=0 if f<142 else 50 if f<153 else 100)if f<=153 else None
   self.authority.append(dict(frame=f,parsed_state_sha256=self.hashes[f],victim=victim,attacker=attacker,survivor=dict(id=12,type=1,army=1,max_health=100,current_damage=0),game_state={'complete':False}))
 def emit(self,s,row):self.logs[s].append(e.PREFIX+json.dumps(row))
 def position(self,entity,f):
  p=[10.,0.,0.]if entity==11 else[-80.,0.,-60.]
  if f>180:
   d=[x-y for x,y in zip(self.target,p)];n=math.sqrt(sum(x*x for x in d));p=[f32(x+(f-180)*.1*y/n)for x,y in zip(p,d)]
  return p
 def snapshot(self,s,f,event):
  members=[]
  for entity in([10]if s==0 else[11,12]):
   absent=(154<=f<=160 if entity==11 else f>=154 if entity==10 else False);dead=f==153 and entity in(10,11);restored=entity==11 and f>=161
   actor=None if absent else 'CC'if restored else str(entity+100)
   live=not absent and not dead;p=self.position(entity,f)if live else None
   members.append(dict(id=entity,unit_type=1,army=s,original_token=entity,incarnation=entity if actor else 0,canonical_token=0 if entity==10 and f>=161 else entity,
    actor=actor,native_present=not absent,native_state=None if absent else 6 if dead else 0,admitted=live,initialized=live,
    original_actor=str(entity+100),original_active=not absent and not restored,original_retained=False,original_dead=dead or absent or restored,original_component=not absent and not restored,
    position=p,position_bits=bits(p)if p else None,position_sampled_us=f*50000 if p else None,jobs_joined=live,current_has_type=not absent,group_has_type=not absent if s else None))
  r=dict(schema=1,event=event,world=1,match=self.match,slot=s,frame=f,completed_frame=f,tick_ms=f*50,sampled_us=f*50000+1000,physicalUI=False,members=members,
   selector='AA',manager='BB',simulation='DD',group_generation=1,current_ids=[11,12]if s else[],preview_ids=[],casting_ids=[],active_caster=None,primary=False,context=False,drag=False,last_click_id=4294967295,click_mode=0,pending_commands=0,
   selection_calls=s,group_assign_calls=s,selection_scope_player_initiated=False if s else None,history_writes=0,current_count=sum(m['current_has_type']for m in members)if s else 0,
   current_all_ids=[11,12]if s else[],current_typed_ids=[12]if s and 154<=f<=160 else[11,12]if s else[],current_frame_owner='EE')
  for k in('group','helper','group_ids','group_count','group_all_ids','group_typed_ids','group_frame_owner','tracked_released_ids','auto_type1'):r[k]=None
  if s:r.update(group='FF',helper='AB',group_ids=[11,12],group_count=r['current_count'],group_all_ids=[11,12],group_typed_ids=r['current_typed_ids'],group_frame_owner='EE',tracked_released_ids=[11]if 154<=f<=160 else[],auto_type1=False)
  return r
 def command(self,s,f):
  src=[10]if s==0 else[11,12];target=[-32.,0.,0.]if s==0 else self.target
  q=dict(schema=1,event='move_queued',world=1,match=self.match,slot=s,frame=f,completed_frame=f,tick_ms=f*50+2,sampled_us=f*50000+2000,source_ids=src,incarnations=src,
   origins=[[0.,0.,0.]]if s==0 else[self.position(i,f)for i in src],origins_sampled_us=[f*50000+1500]*len(src),target=target,target_bits=bits(target),command='AC',command_class='Uncapped.ExecuteTargetGroundCommand',queued=False,ability=12,queue_before=0,queue_after=1,originalCtor=True,original_callback='Uncapped.ExecuteTargetGroundCommand..ctor',enqueue_sampled_us=f*50000+2500,
   local_alliance=s,map_perspective=0,map_perspective_source='Uncapped.Map.GetAlliancePerspective',map_perspective_enum='Uncapped.Map.Perspective',map_perspective_enum_matches_ctor=True,map_perspective_normal=0,map_perspective_flipped=1,map_perspective_value_name='Normal',physicalUI=False)
  self.emit(s,q)
  for ev,extra in(('serialized',dict(command='AC',action='BC',sequence=2,source_next_frame=f+1,action_index=0)),('batch_registered',dict(command='AC',action='BC',sequence=2,speculative_frame=f+1,action_index=0,action_sha256=e.shared.digest(self.actions[s]),body_sha256=e.shared.digest(self.raw[self.match,s,2])))):
   self.emit(s,dict({k:q[k]for k in e.COMMON},event=ev,sampled_us=f*50000+(3000 if ev=='serialized'else 4000),**extra))
  self.logs[s].append(f'Movement local batch registered: sequence=2 speculativeFrame={f+1} tick={f*50+3} match={self.match}')
  body=self.raw[self.match,s,2];self.logs[s].append(f'Original command batch submitted: match={self.match} sequence=2 actions=1 bytes={len(body)} body_sha256={e.shared.digest(body)} sendTick={f*50+4} sourceNextFrame={f+1}')
 def run(self):return e.evaluate('\n'.join(self.logs[1]),attacker_log='\n'.join(self.logs[0]),match=self.match,commits=self.commits,raw_bodies=self.raw,journal=self.journal,
  bridge_frames=self.bridges,canonical_payloads=self.wires,canonical_states=self.hashes,native_states=self.authority,worker_states=self.worker,escape_check=v.actor_escape_evidence,join_check=v.joined_worker_evidence,authority_rows=v.authority_rows,
  cohort_trace=self.native,native_receipts=self.receipts,peer_bridge_frames=self.bridges)

class Survivor(unittest.TestCase):
 def test_exclusive_plan_forwarding(self):
  validate_cohort_survivor_plan({});validate_cohort_survivor_plan(plan())
  p=plan();p.update(files={k:{'path':k}for k in('python','heap_helper','cooperative')},module_root='root',surrender_frame=700)
  self.assertIn('-prediction-cohort-survivor-smoke',v.command_extra(p,0,Path('run')))
  self.assertIn('-prediction-movement-observe-cohort=1:1:130:220:8',v.command_extra(p,1,Path('run')))
  self.assertFalse(any('observe-cohort'in x for x in v.command_extra(p,0,Path('run'))))
  for k,value in(('cohort_survivor',1),('mobile_correction',False),('frames',600),('rtt_ms',[475,130]),('multi_unit_move',True),('mobile_group_intent',True),('mobile_focus',True)):
   x=plan();x[k]=value
   with self.subTest(k=k),self.assertRaises(AssertionError):validate_cohort_survivor_plan(x)
 def test_complete_source_contract_pair_proof(self):
  r=Fixture().run();self.assertTrue(r['passed']);self.assertEqual(r['absent_count'],1);self.assertEqual(r['restored_count'],2);self.assertEqual(len(r['members']),2)
 def test_absent_count_is_observed_has_type_not_numeric_intent_length(self):
  f=Fixture();r=f.snapshot(1,154,'released');e.snapshot(r,1);self.assertEqual(r['current_ids'],[11,12]);self.assertEqual(r['current_count'],1)
  r['current_count']=2
  with self.assertRaises(AssertionError):e.snapshot(r,1)
 def test_unavailable_pose_survivor_loss_wrong_tokens_and_schema_refuse(self):
  for kind in('pose','survivor','token','type','scope','missing','has_type','typed_cache'):
   f=Fixture();r=f.snapshot(1,154,'released')
   if kind=='pose':r['members'][0].update(position=[0,0,0],position_bits=[0,0,0],position_sampled_us=7700000,jobs_joined=True)
   elif kind=='survivor':r['members'][1]['actor']='BAD'
   elif kind=='token':r['members'][0]['canonical_token']=99
   elif kind=='type':r['members'][1]['unit_type']=2
   elif kind=='scope':r['selection_scope_player_initiated']=True
   elif kind=='missing':r.pop('group_frame_owner')
   elif kind=='has_type':r['members'][0]['current_has_type']=True
   else:r['group_typed_ids']=[]
   with self.subTest(kind=kind),self.assertRaises(AssertionError):e.snapshot(r,1)
 def test_missing_release_reselection_wrong_body_phase_hash_and_replay_fail(self):
  for kind in('release','reselect','body','phase','hash','replay','tail','motion'):
   f=Fixture()
   if kind=='release':f.logs[1]=[x for x in f.logs[1]if '"event": "released"'not in x]
   elif kind=='reselect':f.logs[1]=[x.replace('"selection_calls": 1','"selection_calls": 2')for x in f.logs[1]]
   elif kind=='body':f.raw[f.match,1,2]=encode_player_input(encode_identity(2,'human'),[action([11],f.target)])
   elif kind=='phase':f.commits[1]['frame']=183;f.journal[181]['players'][1]=[];f.journal[183]['players'][1]=[f.actions[1]]
   elif kind=='hash':f.worker[181]['parsed_state_sha256']='f'*64
   elif kind=='replay':
    for r in f.worker:r.update(corrections=0,corrections_delta=0,replayed_frames_total=0,replayed_frames_delta=0)
   elif kind=='tail':f.worker=f.worker[:195]
   else:
    for r in f.native:
     next(m for m in r['entities']if m['id']==12).update(position=[-80.,0.,-60.],position_bits=bits([-80.,0.,-60.]))
   with self.subTest(kind=kind),self.assertRaises(AssertionError):f.run()
 def test_two_world_outer_finalization_requires_complete_survivor_proof(self):
  from copy import deepcopy
  from tests.test_prediction_mobile_controller import MobileStateFixture
  result=Fixture().run();f=MobileStateFixture();f.plan.update(plan())
  episodes=[dict(deepcopy(result),match=m,world=141+i)for i,m in enumerate(f.matches)]
  f.report['mobile_correction']=dict(passed=True,episodes=episodes);e.decorate(f.report,episodes)
  self.assertTrue(v.mobile_final_gate(f.plan,f.finalize()))
  self.assertIn('two-ID Move180 without reselection',f.report['mobile_scope'])
  self.assertFalse(f.report['movement_feel_witness_passed']);self.assertFalse(f.report['full_mobile_controls_accepted'])
  for kind in('missing','failed','wrong_world','reselect','lease','hash'):
   changed=deepcopy(f.report)
   if kind=='missing':changed['cohort_survivor']['episodes'].pop()
   elif kind=='failed':changed['cohort_survivor']['passed']=False
   elif kind=='wrong_world':changed['cohort_survivor']['episodes'][1]['world']=141
   elif kind=='reselect':changed['cohort_survivor']['episodes'][1]['reselection_calls']=1
   elif kind=='lease':changed['cohort_survivor']['episodes'][1]['survivor_lease_preserved']=False
   else:changed['mobile_state_parity']['passed']=False
   self.assertFalse(v.mobile_final_gate(f.plan,changed),kind)
   if kind!='hash':
    with self.assertRaises(AssertionError):v.finalize_mobile_observation(changed,f.plan,states=f.states,worker_state_rows=f.workers,client_logs=f.logs)
if __name__=='__main__':unittest.main()
