"""Authored pure cohort-proof controls; no native process or game assets."""
import copy,json,struct,tempfile,unittest
from pathlib import Path
from server.game_data import encode_identity,encode_player_input
from server.protobuf_wire import field_bytes,field_uint,field_packed_uint
from tools import prediction_multi_unit_evidence as e
from tools import verify_prediction_multiplayer as v

def action(ids,target=(16.,0.,0.)):
 p=b''.join(field_uint(i,int(x*2**32)&(2**64-1))for i,x in enumerate(target,1))
 g=field_uint(1,1)+field_uint(2,12)+field_packed_uint(3,ids)
 return field_bytes(1,field_bytes(1,g)+field_bytes(3,field_bytes(3,field_bytes(1,p))))
def plan():return dict(multi_unit_move=True,scenario='mobile',mobile_correction=True,lifecycle='natural',frames=650,expected_matches=2,
 move_slot=0,rtt_ms=[130,475],native_position_trace=None,native_cohort_spec='1:1:420:520:8')
def order():return dict(sequence=4,source_ids=[11,75],target=[16.,0.,0.],target_bits=[0x41800000,0,0],map_perspective=0,
 map_perspective_source='Uncapped.Map.GetAlliancePerspective',map_perspective_enum_matches_ctor=True,tick_ms=1000,enqueue_sampled_us=1000000)
class Binding:
 def __init__(self):
  self.match='a'*32;self.order=order();self.action=action([11,75]);self.body=encode_player_input(encode_identity(2,'Victim'),[self.action]);self.refresh()
 def refresh(self):
  self.raw={(self.match,1,4):self.body};self.log=f'Movement local batch registered: sequence=4 speculativeFrame=441 tick=1001 match={self.match}\nOriginal command batch submitted: match={self.match} sequence=4 actions=1 bytes={len(self.body)} body_sha256={e.digest(self.body)} sendTick=1002 sourceNextFrame=441\n'
  self.commits=[dict(event='command_batch_committed',match=self.match,slot=1,sequence=4,frame=441)]
  self.journal=[dict(frame=441,players={1:[self.action],0:[]})]
 def run(self):return e.bind_move(self.log,self.order,slot=1,match=self.match,raw_bodies=self.raw,commits=self.commits,journal=self.journal)
class MultiUnit(unittest.TestCase):
 def test_exclusive_plan_and_default_are_distinct(self):
  e.validate_plan({});e.validate_plan(plan())
  for k,value in [('scenario','movement'),('mobile_correction',False),('frames',600),('expected_matches',1),('rtt_ms',[475,130]),('mobile_group_intent',True),('mobile_context_move',True),('multi_unit_move',1)]:
   p=plan();p[k]=value
   with self.subTest(k=k),self.assertRaises(AssertionError):e.validate_plan(p)
 def test_controller_forwards_only_explicit_cohort(self):
  p=plan();p.update(surrender_frame=700,files={k:{'path':k}for k in ('python','heap_helper','cooperative')},module_root='root')
  argv=v.command_extra(p,1,Path('run'))
  self.assertIn('-prediction-cohort-smoke',argv);self.assertIn('-frame-timing-worlds=2',argv);self.assertNotIn('-prediction-movement-smoke',argv)
  self.assertEqual(argv.count('-prediction-movement-observe-cohort=1:1:420:520:8'),1)
  self.assertFalse(any(x.startswith('-prediction-movement-observe-cohort=')for x in v.command_extra(p,0,Path('run'))))
  self.assertNotIn('-prediction-mobile-group-intent-smoke',argv)
  p.pop('multi_unit_move');ordinary=v.command_extra(p,1,Path('run'));self.assertNotIn('-prediction-cohort-smoke',ordinary)
  self.assertFalse(any(x.startswith('-prediction-movement-observe-cohort=')for x in ordinary))
 def test_observer_forwarding_refuses_missing_or_changed_prepared_spec(self):
  for spec in(None,'1:0:420:520:8','1:1:420:521:8'):
   p=plan();p.update(surrender_frame=700,files={k:{'path':k}for k in('python','heap_helper','cooperative')},module_root='root')
   if spec is None:p.pop('native_cohort_spec')
   else:p['native_cohort_spec']=spec
   with self.subTest(spec=spec),self.assertRaises(AssertionError):v.command_extra(p,1,Path('run'))
 def test_real_two_id_wire_binding_and_phase(self):
  f=Binding();self.assertEqual(f.run()['assigned_minus_canonical'],0)
  for kind in ('one_member','duplicate_member','wrong_target','two_actions','late_phase','duplicate_commit','wrong_hash','duplicated_canonical'):
   f=Binding()
   if kind=='one_member':f.action=action([11]);f.body=encode_player_input(encode_identity(2,'Victim'),[f.action]);f.refresh()
   elif kind=='duplicate_member':f.action=action([11,11]);f.body=encode_player_input(encode_identity(2,'Victim'),[f.action]);f.refresh()
   elif kind=='wrong_target':f.action=action([11,75],(17.,0.,0.));f.body=encode_player_input(encode_identity(2,'Victim'),[f.action]);f.refresh()
   elif kind=='two_actions':f.body=encode_player_input(encode_identity(2,'Victim'),[f.action,f.action]);f.refresh()
   elif kind=='late_phase':f.commits[0]['frame']=443;f.journal[0]['frame']=443
   elif kind=='duplicate_commit':f.commits*=2
   elif kind=='wrong_hash':f.log=f.log.replace(e.digest(f.body),'0'*64)
   else:f.journal.append(copy.deepcopy(f.journal[0]))
   with self.subTest(kind=kind),self.assertRaises(AssertionError):f.run()
 def test_flipped_target_is_bound_to_original_map_not_army(self):
  f=Binding();f.order['map_perspective']=1;f.action=action([11,75],(-16.,0.,0.));f.body=encode_player_input(encode_identity(2,'Victim'),[f.action]);f.refresh()
  self.assertEqual(f.run()['protocol_target'],[-16.,0.,-0.])
 def test_each_render_member_needs_quiet_baseline_and_own_motion(self):
  o=order();member=dict(position=[0.,0.,0.]);receipt=dict(tick_ms=1500);bridge=dict(received_tick_ms=1490)
  samples=[dict(sampled_us=t,tick_ms=t//1000,position=p)for t,p in [(700000,[0,0,0]),(850000,[0,0,0]),(990000,[0,0,0]),(1040000,[.1,0,0])]]
  self.assertEqual(e.rendered_response(samples,o,member=member,receipt=receipt,bridge=bridge)['response_ms'],40)
  for kind in ('unmoving','wrong_direction','preexisting_motion','late','missing_baseline'):
   s=copy.deepcopy(samples)
   if kind=='unmoving':s[-1]['position']=[0,0,0]
   elif kind=='wrong_direction':s[-1]['position']=[-.1,0,0]
   elif kind=='preexisting_motion':s[0]['position']=[-.1,0,0]
   elif kind=='late':s[-1]['tick_ms']=1490
   else:s=s[2:]
   with self.subTest(kind=kind),self.assertRaises(AssertionError):e.rendered_response(s,o,member=member,receipt=receipt,bridge=bridge)
 def test_native_response_uses_actual_query_end_tick_not_inferred_qpc(self):
  def row(n,f,x,t):return dict(event='native_cohort_positions',stage='ordinary',record=n,frame=f,query_begin_us=900000+n*200000,
   query_end_us=910000+n*200000,query_end_tick_ms=t,entities=[dict(id=11,position=[x,0,0])])
  rows=[row(0,440,0,999),row(1,441,.1,1040)];b=dict(assigned_frame=441,protocol_target=[16,0,0])
  self.assertEqual(e.native_response(rows,order(),b,entity=11,receipt={'tick_ms':1500},bridge={'received_tick_ms':1490})['motion_frame'],441)
  rows[1]['query_end_tick_ms']=1490
  with self.assertRaises(AssertionError):e.native_response(rows,order(),b,entity=11,receipt={'tick_ms':1500},bridge={'received_tick_ms':1490})
 def test_closed_trace_no_duplicate_keys_or_partial_record(self):
  with tempfile.TemporaryDirectory()as d:
   p=Path(d)/'trace';p.write_text('{"record":0,"record":0}\n')
   with self.assertRaises(AssertionError):e.read_cohort_trace(p)
   p.write_text('{}')
   with self.assertRaises(AssertionError):e.read_cohort_trace(p)

class CompleteFixture:
 """Synthetic full two-world journals through the real pure join functions."""
 def __init__(self):
  from tools import prediction_mobile_evidence as mobile
  self.contexts=[];self.base=[];self.native=[];self.worker=[];self.receipts={};self.peer=[];self.logs={0:[],1:[]}
  for world in(1,2):
   match=str(world)*32;offset=(world-1)*100000;hashes={f:e.digest(f'{match}:{f}'.encode())for f in range(541)};wire={f:e.digest(f'wire{match}:{f}'.encode())for f in hashes}
   aa={0:action([10],(-32,0,0)),1:action([11],(21,0,0))};multi=action([11,75]);remote=action([74],(108,0,0))
   builds={s:field_bytes(1,field_bytes(1,field_uint(1,3)+field_uint(2,200+s)+field_packed_uint(3,[5 if s else 0])))for s in(0,1)}
   raw={(match,0,2):encode_player_input(encode_identity(1,'host'),[aa[0]]),(match,1,2):encode_player_input(encode_identity(2,'guest'),[aa[1]])}
   raw.update({(match,s,3):encode_player_input(encode_identity(s+1,'human'),[builds[s]])for s in(0,1)})
   raw.update({(match,1,4):encode_player_input(encode_identity(2,'guest'),[multi]),(match,0,4):encode_player_input(encode_identity(1,'host'),[remote])})
   journal=[dict(frame=f,players={0:[],1:[]})for f in hashes]
   for f,s,a in ((151,0,aa[0]),(181,1,aa[1]),(252,0,builds[0]),(259,1,builds[1]),(441,1,multi),(461,0,remote)):journal[f]['players'][s].append(a)
   commits=[dict(event='command_batch_committed',match=match,slot=s,sequence=seq,frame=f)for s,seq,f in((0,2,151),(1,2,181),(0,3,252),(1,3,259),(1,4,441),(0,4,461))]
   bridges=[dict(match=match,frame=f,received_tick_ms=offset+f*100+500,payload_sha256=wire[f])for f in hashes];self.peer+=copy.deepcopy(bridges)
   for s in(0,1):self.receipts[s,match]=[dict(frame=f,sha256=wire[f])for f in hashes]
   self.base.append(dict(passed=True,world=world,match=match,escape={'action_sha256':e.digest(aa[0])},fresh={'action_sha256':e.digest(aa[1])}))
   for f in hashes:
    self.worker.append(dict(schema=1,event='confirmed_native_state',world=world,frame=f,parsed_state_sha256=hashes[f],confirmed_frontier=f,
     corrections=int(f>=461),corrections_delta=int(f==461),replayed_frames_total=7*int(f>=461),replayed_frames_delta=7*int(f==461),tick_ms=offset+f*100+(800 if f>=441 else 0)))
   for s in(0,1):
    self.emit(s,self.snapshot(world,match,s,249,'prebuild',offset))
    self.logs[s].append(f'LAN NORMAL BUILD smoke frame250 slot{s} army{s} HQ{5 if s else 0} deckSlot0 unitType1 ability{200+s} cost=(100,0) prerequisite=1 queued=1 commandQueueDelta=1 presentedFrame={258 if s else 251}')
    bf=259 if s else 252;bb=raw[match,s,3]
    self.logs[s].append(f'Movement local batch registered: sequence=3 speculativeFrame={bf} tick={offset+bf*100} match={match}')
    self.logs[s].append(f'Original command batch submitted: match={match} sequence=3 actions=1 bytes={len(bb)} body_sha256={e.digest(bb)} sendTick={offset+bf*100+1} sourceNextFrame=250')
    self.emit(s,self.snapshot(world,match,s,420,'selected',offset))
    at=440 if s else 460;target=[16.,0.,0.]if s else[108.,0.,0.];src=[11,75]if s else[74]
    for f in range(421,521):
     self.emit(s,self.snapshot(world,match,s,f,'complete'if f==520 else'sample',offset))
     if f==at:
      q=dict(schema=1,event='move_queued',world=world,match=match,slot=s,frame=f,completed_frame=f,tick_ms=offset+f*100,sampled_us=(offset+f*100)*1000+1,
       source_ids=src,incarnations=src,origins=[[0.,0.,0.],[2.,0.,0.]]if s else[[100.,0.,0.]],origins_sampled_us=[(offset+f*100)*1000]*len(src),
       target=target,target_bits=[struct.unpack('<I',struct.pack('<f',x))[0]for x in target],command='AA',command_class='Uncapped.ExecuteTargetGroundCommand',queued=False,ability=12,queue_before=0,queue_after=1,
       originalCtor=True,original_callback='Uncapped.ExecuteTargetGroundCommand..ctor',enqueue_sampled_us=(offset+f*100)*1000+2,physicalUI=False,
       local_alliance=s,map_perspective=0,map_perspective_source='Uncapped.Map.GetAlliancePerspective',map_perspective_enum='Uncapped.Map.Perspective',map_perspective_enum_matches_ctor=True,
       map_perspective_normal=0,map_perspective_flipped=1,map_perspective_value_name='Normal')
      self.emit(s,q)
      for ev,more in [('serialized',dict(command='AA',action='BB',sequence=4,source_next_frame=f+1,action_index=0)),('batch_registered',dict(command='AA',action='BB',sequence=4,speculative_frame=f+1,action_index=0,action_sha256=e.digest(multi if s else remote),body_sha256=e.digest(raw[match,s,4])))]:
       self.emit(s,dict({k:q[k]for k in e.COMMON},event=ev,sampled_us=q['sampled_us']+(3 if ev=='serialized'else 4),physicalUI=False,**more))
      self.logs[s].append(f'Movement local batch registered: sequence=4 speculativeFrame={f+1} tick={offset+f*100+1} match={match}')
      body=raw[match,s,4];self.logs[s].append(f'Original command batch submitted: match={match} sequence=4 actions=1 bytes={len(body)} body_sha256={e.digest(body)} sendTick={offset+f*100+2} sourceNextFrame={f+1}')
     if s==1 and f in(446,466):
      c=f-5;rr=dict(schema=1,world=world,match=match,frame=c,tick_ms=offset+f*100,canonical_sha256='c'*64,wire_sha256=wire[c]);self.logs[s].append('MOVEMENT AUTHORITY '+json.dumps(rr))
      self.emit(s,dict(schema=1,event='authority',world=world,match=match,slot=1,frame=f,completed_frame=f,tick_ms=offset+f*100,sampled_us=(offset+f*100)*1000,canonical_frame=c,canonical_sha256='c'*64,wire_sha256=wire[c],physicalUI=False))
   for f in range(420,521):
    self.native.append(dict(schema=1,event='native_cohort_positions',record=len(self.native),world=world,frame=f,revision=0,query_revision=0,checkpoint_base=None,first_divergent_frame=None,
     cohort_spec=dict(type=1,army=1,first_frame=420,last_frame=520,max_entities=8),context_source='same_decoded_native_query',stage='ordinary',head=f-1,confirmed=f-10,received=f-10,corrections=0,replayed_frames=0,
     query_begin_us=(offset+f*100)*1000+10,query_end_us=(offset+f*100)*1000+20,query_begin_tick_ms=offset+f*100,query_end_tick_ms=offset+f*100+1,
     status='present',count=2,entities=[self.native_entity(i,f)for i in(11,75)],clock_source='python.perf_counter_ns//1000',query_scope='existing-native-make-get-and-decode'))
   self.contexts.append(dict(match=match,raw_bodies=raw,commits=commits,journal=journal,canonical_states=hashes,canonical_payloads=wire,bridge_frames=bridges))
  for ctx in self.contexts:ctx.update(log='\n'.join(self.logs[1]),attacker_log='\n'.join(self.logs[0]))
 def emit(self,s,r):self.logs[s].append('COHORT '+json.dumps(r))
 def native_entity(self,i,f):
  x=0. if i==11 else 2.;x+=max(0,min(f-440,80))*.1;x=struct.unpack('<f',struct.pack('<f',x))[0]
  return dict(id=i,type=1,army=1,position=[x,0.,0.],position_bits=[struct.unpack('<I',struct.pack('<f',x))[0],0,0])
 def snapshot(self,w,m,s,f,event,offset):
  ids=([11]if s else[])if event=='prebuild'else([11,75]if s else[74]);members=[]
  for i in ids:
   p=self.native_entity(i,f)['position']if s else[100.,0.,0.]
   poses=event!='prebuild';members.append(dict(id=i,unit_type=1,army=s,incarnation=i,canonical_token=i,actor=f'{w*1000+i:X}',native_state=0,admitted=True,initialized=True,
    position=p if poses else None,position_bits=[struct.unpack('<I',struct.pack('<f',x))[0]for x in p]if poses else None,position_sampled_us=(offset+f*100)*1000 if poses else None,jobs_joined=poses))
  selected=s==1 and event!='prebuild';r=dict(schema=1,event=event,world=w,match=m,slot=s,frame=f,completed_frame=f,tick_ms=offset+f*100,sampled_us=(offset+f*100)*1000,members=members,
   selector='1A',manager='2A',simulation='3A',group_generation=w,current_ids=ids if selected else[],preview_ids=[],casting_ids=[],active_caster=None,primary=False,context=False,
   selection_calls=int(selected),group_assign_calls=int(selected),selection_scope_player_initiated=False if selected else None,history_writes=0,physicalUI=False,drag=False,last_click_id=4294967295,click_mode=0)
  for k in('current_count','current_all_ids','current_typed_ids','group','helper','frame_owner','group_ids','group_count','group_all_ids','group_typed_ids','tracked_released_ids','auto_type1'):r[k]=None
  if selected:r.update(current_count=2,current_all_ids=ids,current_typed_ids=ids,group='4A',helper='5A',frame_owner='6A',group_ids=ids,group_count=2,group_all_ids=ids,group_typed_ids=ids,tracked_released_ids=[],auto_type1=False)
  return r
 def run(self):return e.evaluate(contexts=self.contexts,cohort_trace=self.native,worker_states=self.worker,mobile_episodes=self.base,
  native_receipts=self.receipts,peer_bridge_frames=self.peer,authority_rows=v.authority_rows,join_check=v.joined_worker_evidence)

class Pipeline(unittest.TestCase):
 def test_actual_selection_scope_field_is_strictly_typed_and_seat_scoped(self):
  f=CompleteFixture()
  for slot,frame,event in((1,249,'prebuild'),(1,420,'selected'),(0,420,'selected')):
   row=f.snapshot(1,'1'*32,slot,frame,event,0)
   e.validate_snapshot(row,slot=slot,poses=event!='prebuild')
   for bad in(True,0,'false','missing'):
    altered=copy.deepcopy(row)
    if bad=='missing':altered.pop('selection_scope_player_initiated')
    else:altered['selection_scope_player_initiated']=bad
    with self.subTest(slot=slot,event=event,bad=bad),self.assertRaises(AssertionError):e.validate_snapshot(altered,slot=slot,poses=event!='prebuild')
  row=f.snapshot(1,'1'*32,1,420,'selected',0);row['selection_scope_player_initiated']=None
  with self.assertRaises(AssertionError):e.validate_snapshot(row,slot=1,poses=True)
  row=f.snapshot(1,'1'*32,0,420,'selected',0);row['selection_scope_player_initiated']=False
  with self.assertRaises(AssertionError):e.validate_snapshot(row,slot=0,poses=True)
 def test_build_request_source_is250_but_actual_presented_and_canonical_are_independent(self):
  r=CompleteFixture().run();self.assertTrue(r['passed'])
  self.assertEqual([(b['presented_after_return'],b['canonical_frame'])for b in r['episodes'][0]['builds']],[(251,252),(258,259)])
 def test_build_normal_sequence_body_source_phase_readiness_and_uniqueness_are_required(self):
  for bad in('sequence','body','source','phase','late','duplicate'):
   f=CompleteFixture();ctx=f.contexts[0]
   if bad=='sequence':ctx['log']=ctx['log'].replace('sequence=3 ','sequence=30 ')
   elif bad=='body':
    h=e.digest(ctx['raw_bodies'][ctx['match'],1,3]);ctx['log']=ctx['log'].replace('body_sha256='+h,'body_sha256='+'0'*64)
   elif bad=='source':ctx['log']=ctx['log'].replace('sourceNextFrame=250','sourceNextFrame=251')
   elif bad=='phase':ctx['log']=ctx['log'].replace('speculativeFrame=259','speculativeFrame=261')
   elif bad=='late':
    a=ctx['journal'][259]['players'][1].pop();ctx['journal'][421]['players'][1].append(a)
    next(r for r in ctx['commits']if r['slot']==1 and r['sequence']==3)['frame']=421
    ctx['log']=ctx['log'].replace('speculativeFrame=259','speculativeFrame=421')
   else:ctx['journal'][260]['players'][1].extend(ctx['journal'][259]['players'][1])
   with self.subTest(bad=bad),self.assertRaises(AssertionError):f.run()
 def test_complete_two_world_pipeline(self):self.assertTrue(CompleteFixture().run()['passed'])
 def test_unmoving_member_extra_input_wrong_native_and_cache_loss_refuse(self):
  for kind in('native_unmoving','render_unmoving','extra_action','wrong_wire','wrong_hash','cache_loss','reselection','early_remote'):
   f=CompleteFixture()
   if kind=='native_unmoving':
    for r in f.native:
     r['entities'][1].update(position=[2.,0.,0.],position_bits=[0x40000000,0,0])
   elif kind=='render_unmoving':
    f.contexts[0]['log']=f.contexts[0]['log'].replace('"position": [2.0999999046325684, 0.0, 0.0]','"position": [2.0, 0.0, 0.0]')
    # A real stale member body is not silently normalized: its raw bits now disagree.
   elif kind=='extra_action':f.contexts[0]['journal'][450]['players'][0].append(action([74]))
   elif kind=='wrong_wire':f.receipts[1,'1'*32][441]['sha256']='f'*64
   elif kind=='wrong_hash':f.worker[441]['parsed_state_sha256']='f'*64
   elif kind=='cache_loss':f.contexts[0]['log']=f.contexts[0]['log'].replace('"current_typed_ids": [11, 75]','"current_typed_ids": [11]')
   elif kind=='reselection':f.contexts[0]['log']=f.contexts[0]['log'].replace('"selection_calls": 1','"selection_calls": 2')
   else:f.contexts[0]['commits'][-1]['frame']=151
   with self.subTest(kind=kind),self.assertRaises(AssertionError):f.run()

if __name__=='__main__':unittest.main()
