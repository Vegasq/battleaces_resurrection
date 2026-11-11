"""Authored Instant binding and moving-to-stopped controls; no DLL is loaded."""
from copy import deepcopy
import json
import unittest

from server.game_data import encode_identity,encode_player_input
from server.protobuf_wire import field_bytes,field_uint,field_packed_uint
from tools import prediction_context_hold_evidence as hold,prediction_mobile_evidence as mobile


class ContextHoldEvidenceTests(unittest.TestCase):
    def pose(self,us,x,frame=198):
        return dict(schema=1,event='transform',world=1,match='a'*32,entity=11,unit_type=1,army=1,incarnation=7,
            move_id=1,frame=frame,presented_frame=frame,completed_frame=frame,baseline=False,
            position=[x,0.,0.],sampled_us=us,tick_ms=us//1000,source='UnityEngine.Transform.get_position',
            jobsJoined=True,physicalUI=False)

    def mapping(self):
        return dict(index=5,present=True,button_class='Uncapped.AbilityButtonAction',slot=5,valid_button=True,
            mapped_ids=[11],mapped_count=1,has_mapped_casters=True,group_present=True,group_class='Uncapped.AbilityGroup',
            group_unity_truth=True,panel_group_matches=True,group_kind=0,cast_type=2,cast_type_method_token=0x06000177,
            smart_casting=False,config_lookup_performed=True,config_present=True,config_id=14,candidate=False,
            candidate_reason='ineligible_mapping',config_key_observation=dict(declaring_class='Uncapped.AbilityConfig',
                field_name='Key',field_offset=52,declared_class='Uncapped.IntKey`1',boxed_class='Uncapped.IntKey`1',
                declared_boxed_class_equal=True,value_size=4,getter_token=0x0600151a,getter_rva_guarded=False,
                field_token_source='static_original_metadata',closed_argument_source='original_AbilityConfig.Key_metadata'))

    def records_fixture(self):
        common=dict(schema=1,world=1,match='a'*32,generation=1,selector='abc',manager='def',simulation='123',server='456',thread=1,
            slot=1,entity=11,unit_type=1,army=1,incarnation=7,current_token=7,canonical_token=7,actor='789',button='aaa',panel='bbb',
            source_set='ccc',mapped_set='ddd',group='eee',activation='fff',activation_serial=1,mapping=self.mapping(),
            activation_type=1,activation_count=1,from_hotkey=True,held=False,primary=False,context=False,drag=False,active_caster=None,
            casting_ids=[],current_ids=[11],preview_ids=[],current_count=1,position=[5.4,0.,0.],context_input_closed=True,
            move_command='dad',originalCtor=False,original_callback='Uncapped.AbilityButtonAction.PerformButtonAction',
            selection_writes=0,history_writes=0,physicalUI=False)
        rows=[dict(deepcopy(common),event=event,sequence=i+1,frame=198 if i<2 else 260,tick_ms=us//1000,
            sampled_us=us,position_sampled_us=us-1,perform_calls=bool(i)*1,pending_commands=1 if i==1 else 0,
            command=None if i==0 else 'cad',command_class=None if i==0 else 'Uncapped.ExecuteInstantCommand',queued=None if i==0 else False)
            for i,(event,us) in enumerate((('before',1000000),('returned',1001000),('complete',2001000)))]
        normal=dict(schema=1,world=1,match='a'*32,generation=1,selector='abc',manager='def',thread=1,activation_serial=1,
            frame=198,source_next_frame=199,sequence=3,command='cad',action='bae',tick_ms=1001,sampled_us=1001100,physicalUI=False)
        context=dict(world=1,match='a'*32,token=7,order=dict(command='dad'),serialized=dict(sequence=2),
            callbacks=[dict(generation=1,manager='def',simulation='123',server='456',thread=1)],
            events=dict(context_closed=dict(selector='abc',sampled_us=800000),complete=dict(frame=260,sampled_us=2000000)))
        def log():
            lines=[]
            for row in rows:
                lines+=['MOBILE FEEL '+json.dumps(self.pose(row['position_sampled_us'],5.4,row['frame'])),hold.PREFIX+json.dumps(row)]
                if row['event']=='returned':lines.append(hold.SERIALIZED_PREFIX+json.dumps(normal))
            return '\n'.join(lines)
        return rows,normal,context,log

    def test_strict_actual_activation_and_normal_command_pointer_are_joined(self):
        rows,normal,context,log=self.records_fixture();saved=deepcopy(rows)
        result=hold.records(log(),'a'*32,context=context)
        self.assertEqual(result['rows'],rows);self.assertEqual(rows,saved)
        normal['command']='bad'
        with self.assertRaisesRegex(AssertionError,'serialization owner'):hold.records(log(),'a'*32,context=context)
        normal['command']='cad';rows[0]['mapping']['mapped_count']=0
        with self.assertRaises(AssertionError):hold.records(log(),'a'*32,context=context)

    def test_standalone_nulls_are_explicit_and_cannot_relabel_context_evidence(self):
        rows,normal,context,log=self.records_fixture()
        for row in rows:row.update(context_input_closed=None,move_command=None)
        result=hold.records(log(),'a'*32,original_hold=True)
        self.assertEqual(result['scope'],'scripted_move_original_button')
        self.assertNotIn('context',result)
        with self.assertRaises(AssertionError):hold.records(log(),'a'*32,context=context)
        with self.assertRaises(AssertionError):hold.records(log(),'a'*32,original_hold=1)
        for prefix in ('CONTEXT INPUT ','CONTEXT CALLBACK ','CONTEXT ORDER ','CONTEXT SERIALIZED '):
            with self.subTest(prefix=prefix),self.assertRaises(AssertionError):
                hold.records(log()+'\n'+prefix+'{}','a'*32,original_hold=True)
        rows[0]['context_input_closed']=True
        with self.assertRaises(AssertionError):hold.records(log(),'a'*32,original_hold=True)

    def test_instant_body_original_eligibility_sender_phase_and_exact_occurrence(self):
        match='a'*32;rows,normal,context,log=self.records_fixture();w=hold.records(log(),match,context=context)
        group=field_uint(1,1)+field_uint(2,14)+field_packed_uint(3,[11])
        def body(target=field_bytes(1,b'')):
            action=field_bytes(1,field_bytes(1,group)+field_bytes(3,target))
            return action,encode_player_input(encode_identity(2,'Victim'),[action])
        action,raw=body();bodies={(match,1,3):raw}
        sender=lambda: f'Movement local batch registered: sequence=3 speculativeFrame=199 tick=1002 match={match}\nOriginal command batch submitted: match={match} sequence=3 actions=1 bytes={len(raw)} body_sha256={mobile.digest(raw)} sendTick=1003 sourceNextFrame=199\n'
        args=dict(commits=[dict(event='command_batch_committed',match=match,slot=1,sequence=3,frame=199)],raw_bodies=bodies,
            journal=[dict(frame=199,players={0:[],1:[action]})])
        result=hold.binding(sender(),w,**args);self.assertTrue(result['prediction_eligible']);self.assertTrue(result['instant'])
        for change in ('ground','sequence','duplicate'):
            altered=deepcopy(args);changed=deepcopy(w)
            if change=='ground':altered['raw_bodies'][match,1,3]=body(field_bytes(3,b''))[1]
            elif change=='sequence':changed['serialized']['sequence']=4
            else:altered['journal'][0]['players'][1]*=2
            with self.subTest(change=change),self.assertRaises(AssertionError):hold.binding(sender(),changed,**altered)

    def test_stop_requires_actual_moving_prefix_and_a_whole_stable_window_before_both_receipts(self):
        poses=[self.pose(us,5.+i*.1,194+i) for i,us in enumerate(range(800000,1000001,50000))]
        poses += [self.pose(us,5.5,199+i) for i,us in enumerate(range(1020000,1170001,50000))]
        witness=dict(world=1,match='a'*32,token=7,rows=[dict(sampled_us=1000001,position_sampled_us=1000000,position=[5.4,0.,0.]),
            dict(sampled_us=1001000),{}])
        order=dict(origin=[5.,0.,0.],target=[21.,0.,0.])
        def run(rows,bridge=1200):
            return hold.stop('\n'.join('MOBILE FEEL '+json.dumps(x) for x in rows),witness,order,
                dict(tick_ms=1200),dict(received_tick_ms=bridge))
        self.assertTrue(run(poses)['passed'])
        for change in ('static_before','still_moving','late_bridge','missing_span'):
            altered=deepcopy(poses)
            if change=='static_before':
                for p in altered[:5]:p['position']=[5.4,0.,0.]
            elif change=='still_moving':
                for i,p in enumerate(altered[5:]):p['position']=[5.5+i*.1,0.,0.]
            elif change=='missing_span':altered=altered[:-2]
            with self.subTest(change=change),self.assertRaises(AssertionError):run(altered,1100 if change=='late_bridge' else 1200)


if __name__=='__main__':unittest.main()
