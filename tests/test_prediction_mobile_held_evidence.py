"""Authored real-input evidence boundaries; no native DLL/process is used."""
from copy import deepcopy
import json
import unittest

from tests.test_prediction_mobile_evidence import Fixture
from tools import prediction_mobile_held_evidence as held


class HeldFixture(Fixture):
    def __init__(self, world=1):
        super().__init__();old=self.match;self.match=('a'if world==1 else'b')*32
        self.bodies={(self.match,s,n):v for(_,s,n),v in self.bodies.items()}
        for rows in (self.rows,self.receipts,self.bridges,self.commits,self.poses):
            for r in rows:
                if 'match'in r:r['match']=self.match
                if 'world'in r:r['world']=world
        for r in self.worker:r['world']=world
        for r in (self.order,self.escape):r.update(match=self.match,world=world)
        self.commits[1]['frame']=185
        self.journal[185]['players'][1]=self.journal[181]['players'][1];self.journal[181]['players'][1]=[]
        self.wires[185]=self.wires.pop(181)
        for r in self.receipts+self.bridges:
            if r['frame']==181:r['frame']=185
        for r in self.worker:
            if 181<=r['frame']<=186:
                r.update(confirmed_frontier=186 if r['frame']==185 else r['frame'],
                    tick_ms=1710 if r['frame']>=185 else 1000+(r['frame']-181)*20)
        self.fresh_assigned=185;self.order['frame']=184
        self.rows[5].update(frame=183,sampled_us=1494000,tick_ms=1494,selection_scope_player_initiated=None)
        self.rows[2]['selected_ids']=[11]
        self.rows[3]['selected_ids']=self.rows[4]['selected_ids']=[11]
        for i,r in enumerate(self.rows):
            if i:
                r.update(focus_group=-1,focus_actor='0',live_click_id=11,
                    left_held=i in (1,2)or i==3 and world==1,
                    preview_ids=[11])
                for key in tuple(r):
                    if key.startswith('focus_')and key not in ('focus_group','focus_actor','focus_lookup_source'):
                        r[key]=False if key=='focus_lookup_id_present'else None
            if r['native_state']is not None and r['native_state']!=6:r['native_state']=0
        for index in (5,6):self.rows[index]['preview_ids']=[]
        if world==2:self.rows[3]['preview_ids']=[]
        for r in self.poses:
            r.update(frame=184 if r['baseline']else 185,presented_frame=184 if r['baseline']else 185,
                completed_frame=185)
        branch=('restored','release_queued','released','input_closed')if world==1 else(
            'release_queued','released','input_closed','restored')
        events=(*held.FIRST,*branch,*held.FRESH)
        frames=dict(setup=130,position_queued=148,position_observed=150,press_queued=150,pressed=151,
            held_checkpoint=152,native_dead=153,natural_release=154,restored=163,
            release_queued=165 if world==1 else 154,released=166 if world==1 else 155,
            input_closed=166 if world==1 else 155,fresh_position_queued=178,fresh_position_observed=180,
            fresh_press_queued=180,fresh_pressed=181,fresh_release_queued=182,fresh_released=183,
            fresh_input_closed=183,fresh_move_queued=184,complete=260)
        times=dict(setup=100100,position_queued=150000,position_observed=160000,press_queued=170000,
            pressed=180000,held_checkpoint=190000,native_dead=200100,natural_release=220100,
            restored=350100,release_queued=400000 if world==1 else 220200,
            released=410000 if world==1 else 230000,input_closed=410100 if world==1 else 230100,
            fresh_position_queued=1450000,fresh_position_observed=1490001,fresh_press_queued=1490100,
            fresh_pressed=1492000,fresh_release_queued=1493000,fresh_released=1494100,
            fresh_input_closed=1494200,fresh_move_queued=1502000,complete=6000100)
        active={'pressed','held_checkpoint','native_dead','natural_release','release_queued',
            'fresh_pressed','fresh_release_queued'}|({'restored'}if world==1 else set())
        absent={'natural_release'}|({'release_queued','released','input_closed'}if world==2 else set())
        self.held=[]
        for n,event in enumerate(events,1):
            session=2 if event in held.FRESH else 1
            closed=event in ('input_closed','fresh_input_closed','fresh_move_queued','complete')or event=='restored'and world==2
            seq=(1 if event in held.FRESH[:2]else 2 if event in held.FRESH[2:4]else 3)if session==2 else(
                0 if event=='setup'else 1 if event in held.FIRST[1:3]else 3 if event in ('release_queued','released','input_closed')or
                event=='restored'and world==2 else 2)
            down,up,fresh_down,fresh_up=(10,11,13,14)if world==1 else(26,27,28,29)
            serial=(0 if n<events.index('pressed')+1 else down if n<events.index('released')+1 else
                up if n<events.index('fresh_pressed')+1 else fresh_down if n<events.index('fresh_released')+1 else fresh_up)
            ledger_completed=serial in(down,fresh_down)or world==2 and serial==up
            ledger_serial=serial+(1 if serial and not ledger_completed else 0)
            selected=[11]
            empty_preview=(event in('setup','position_queued','fresh_position_queued','fresh_released','fresh_input_closed','complete')or
                world==1 and event in('released','input_closed')or world==2 and event=='restored')
            preview=[]if empty_preview else[11]
            self.held.append(dict(schema=3,event=event,sequence=n,world=world,match=self.match,slot=1,entity=11,
                unit_type=1,army=1,frame=frames[event],tick_ms=times[event]//1000,sampled_us=times[event],
                session=session,input_sequence=seq,selector='abc',action='def',control='123',device='456',
                input_closed=closed,owned_button=None if closed else event in active,click_id=11 if serial else 0,
                mode=1 if event in active else 0,primary=event in active,context=False,drag=False,
                original_token=7,current_token=0 if event in absent else 7,canonical_token=7,current_ids=selected,
                preview_ids=preview,current_count=0 if event in absent else 1,
                preview_count=0 if event in absent else len(preview),casting_ids=[],native_present=event not in absent,
                native_state=None if event in absent else 6 if event=='native_dead'else 0,current_admitted=event not in absent,
                returned_serial=serial,returned_down=serial in(down,fresh_down),returned_up=serial in(up,fresh_up),
                ledger_completed=ledger_completed,ledger_serial=ledger_serial,
                pending_commands=1 if event=='fresh_move_queued'else 0,selection_writes=0,history_writes=0,physicalUI=False))
        self.clock_offset=10000*(world-1);self.prior_log=''
        for rows in (self.rows,self.receipts,self.worker,self.poses,self.held):
            for r in rows:
                if 'tick_ms'in r:r['tick_ms']+=self.clock_offset
                if 'sampled_us'in r:r['sampled_us']+=1000*self.clock_offset
        for r in self.bridges:r['received_tick_ms']+=self.clock_offset
        for r in (self.order,self.escape):
            r['tick_ms']+=self.clock_offset
            for key in ('sampled_us','origin_sampled_us','enqueue_sampled_us'):r[key]+=1000*self.clock_offset

    def sender(self,slot,order,assigned,tick):
        return super().sender(slot,order,assigned,tick+self.clock_offset)

    def log(self):
        rows=[(r['sampled_us'],'MOBILE CORRECTION ',r)for r in self.rows]+[(r['sampled_us'],held.PREFIX,r)for r in self.held]
        for name in ('pressed','fresh_pressed'):
            r=self.by_event(name)
            rows.append((r['sampled_us']-1,'',dict(marker=f'Prediction input Single observed: world={r["world"]} generation=1 '
                f'serial={r["returned_serial"]} entity=11 originalDown=1 originalProcess=1 completedCallback=1 dispatchVerified=1 repairAuthorized=0')))
        return (self.prior_log+'\n'.join(p+json.dumps(r)if p else r['marker']for _,p,r in sorted(rows,key=lambda item:item[0]))+'\n'+
            '\n'.join('MOBILE FEEL '+json.dumps(r)for r in self.poses)+'\n'+self.sender(1,self.order,self.fresh_assigned,1501))

    def by_event(self,name):return next(r for r in self.held if r['event']==name)


class MobileHeldEvidenceTests(unittest.TestCase):
    def test_both_real_input_outcomes_keep_full_native_wire_replay_and_fresh_move_checks(self):
        fixtures=[HeldFixture(1),HeldFixture(2)]
        episodes=[f.evaluate(mobile_held_click=True)for f in fixtures]
        result=held.evaluate('\n'.join(f.log()for f in fixtures),attacker_log='',mobile_episodes=episodes,
            expected_matches=[f.match for f in fixtures])
        self.assertTrue(result['passed']);self.assertEqual([r['release_while_absent']for r in result['episodes']],[False,True])
        for f,r in zip(fixtures,episodes):
            self.assertEqual(r['rows'],f.rows);self.assertTrue(r['same_confirmed_token'])
            self.assertEqual(r['fresh']['order']['frame'],184);self.assertTrue(r['fresh_motion']['passed'])
            self.assertEqual(r['escape_native_replay']['continuation_frames'],20)
            self.assertEqual(r['fresh_native_confirmation']['continuation_frames'],20)

    def test_idle_default_still_refuses_real_held_rows(self):
        with self.assertRaises(AssertionError):HeldFixture().evaluate()

    def test_returned_down_alone_cannot_replace_the_original_accepted_single_marker(self):
        for change in ('missing','wrong_serial','wrong_entity','not_completed'):
            f=HeldFixture();original=f.log
            def changed_log():
                log=original()
                if change=='missing':return '\n'.join(line for line in log.splitlines()if 'Prediction input Single observed:'not in line)
                if change=='wrong_serial':return log.replace('generation=1 serial=10','generation=1 serial=999')
                if change=='wrong_entity':return log.replace('entity=11 originalDown=1','entity=12 originalDown=1')
                return log.replace('completedCallback=1','completedCallback=0')
            f.log=changed_log
            with self.subTest(change=change),self.assertRaisesRegex(AssertionError,'actual original accepted'):
                f.evaluate(mobile_held_click=True)

    def test_strict_new_schema_rejects_old_fields_duplicate_keys_and_noncanonical_pointer(self):
        f=HeldFixture();f.by_event('setup')['selector']='0xabc'
        with self.assertRaises(AssertionError):f.evaluate(mobile_held_click=True)
        f=HeldFixture();row=f.by_event('setup');row['accepted_serial']=row.pop('returned_serial')
        with self.assertRaises(AssertionError):f.evaluate(mobile_held_click=True)
        f=HeldFixture();original=f.log
        f.log=lambda:original().replace(held.PREFIX+'{"schema": 3',held.PREFIX+'{"schema": 3,"schema": 3',1)
        with self.assertRaisesRegex(AssertionError,'duplicate JSON'):f.evaluate(mobile_held_click=True)

    def test_schema3_refuses_v1_v2_and_the_refuted_pre_up_empty_set_hypothesis(self):
        for change in ('v1','v2','empty_release','empty_pending_up','empty_restored'):
            f=HeldFixture(2 if change=='empty_pending_up'else 1)
            if change in('v1','v2'):
                for row in f.held:row['schema']=1 if change=='v1'else 2
            else:
                event={'empty_release':'natural_release','empty_pending_up':'release_queued','empty_restored':'restored'}[change]
                f.by_event(event).update(current_ids=[],preview_ids=[])
            with self.subTest(change=change),self.assertRaises(AssertionError):f.evaluate(mobile_held_click=True)

    def test_complete_world2_rejects_empty_raw_ids_or_wrong_original_resolution_counts(self):
        # A diagnostic can finish and retain all actual records yet remain RED.
        for event,changes in (('released',dict(current_ids=[])),('released',dict(preview_ids=[])),
                ('input_closed',dict(current_count=1)),('restored',dict(current_ids=[])),
                ('restored',dict(current_count=0)),('restored',dict(preview_ids=[11],preview_count=1))):
            f=HeldFixture(2);f.by_event(event).update(changes)
            with self.subTest(event=event,changes=changes),self.assertRaises(AssertionError):
                f.evaluate(mobile_held_click=True)

    def test_primary_return_is_separate_from_unchanged_ledger_authorization(self):
        for world,event,changes in ((1,'released',dict(ledger_completed=True,ledger_serial=11)),
                (1,'fresh_released',dict(ledger_completed=True,ledger_serial=14)),
                (2,'released',dict(ledger_completed=False,ledger_serial=28)),
                (2,'fresh_released',dict(ledger_completed=True,ledger_serial=29)),
                (1,'pressed',dict(ledger_completed=False,ledger_serial=11))):
            f=HeldFixture(world);f.by_event(event).update(changes)
            with self.subTest(world=world,event=event),self.assertRaises(AssertionError):
                f.evaluate(mobile_held_click=True)

    def test_stale_down_or_returned_position_cannot_stand_in_for_real_primary_up(self):
        for world,event in ((1,'released'),(1,'fresh_released'),(2,'fresh_released')):
            f=HeldFixture(world);down=f.by_event('fresh_pressed'if event.startswith('fresh_')else'pressed')
            f.by_event(event).update({k:down[k]for k in ('returned_serial','returned_down','returned_up','ledger_completed','ledger_serial')})
            with self.subTest(world=world,event=event),self.assertRaises(AssertionError):f.evaluate(mobile_held_click=True)
        f=HeldFixture()
        for event in ('fresh_position_observed','fresh_press_queued'):
            f.by_event(event).update(returned_serial=12,returned_down=False,
                returned_up=False,ledger_completed=True,ledger_serial=12)
        with self.assertRaisesRegex(AssertionError,'overwrote'):f.evaluate(mobile_held_click=True)

    def test_native_dead_counts_are_observed_and_absent_count0_does_not_delete_raw_ids(self):
        for world in (1,2):
            f=HeldFixture(world);f.by_event('native_dead').update(current_count=0,preview_count=0)
            r=f.evaluate(mobile_held_click=True)
            absent=next(row for row in r['mobile_held_click']['rows']if row['event']=='natural_release')
            self.assertEqual(absent['current_ids'],[11]);self.assertEqual(absent['preview_ids'],[11])
            self.assertEqual((absent['current_count'],absent['preview_count']),(0,0))

    def test_world2_retained_idle_reference_requires_the_same_prior_balanced_selector(self):
        first,second=HeldFixture(1),HeldFixture(2)
        second.rows[0]['live_click_id']=11
        for r in second.held[:4]:r['click_id']=11
        with self.assertRaisesRegex(AssertionError,'prior completed'):second.evaluate(mobile_held_click=True)
        second.prior_log=first.log()
        result=second.evaluate(mobile_held_click=True)
        self.assertEqual(result['rows'][0]['live_click_id'],11)
        second.held[0]['selector']='789'
        with self.assertRaises(AssertionError):second.evaluate(mobile_held_click=True)

    def test_strict_held_prefix_rejects_unbalanced_input_owner_token_and_natural_removal(self):
        cases=(('released',{'returned_up':False}),('released',{'returned_serial':1}),
            ('fresh_pressed',{'returned_serial':2}),('input_closed',{'input_closed':False}),
            ('input_closed',{'owned_button':False}),('held_checkpoint',{'device':'bad0'}),
            ('restored',{'canonical_token':8}),('natural_release',{'current_ids':[]}),
            ('fresh_move_queued',{'selection_writes':1}),('fresh_move_queued',{'pending_commands':0}),
            ('fresh_released',{'history_writes':1}),('restored',{'current_ids':[]}))
        for event,changes in cases:
            with self.subTest(event=event,changes=changes):
                f=HeldFixture();f.by_event(event).update(changes)
                with self.assertRaises(AssertionError):f.evaluate(mobile_held_click=True)

    def test_world2_up_after_restoration_or_wrong_same_callback_snapshot_is_refused(self):
        for change in ('late_up','selected','wrong_snapshot','fake_scope','no_fresh_up'):
            with self.subTest(change=change):
                f=HeldFixture(2)
                if change=='late_up':f.by_event('released')['frame']=164
                elif change=='selected':f.by_event('released')['current_ids']=[]
                elif change=='wrong_snapshot':f.rows[2]['preview_ids']=[]
                elif change=='fake_scope':f.rows[5]['selection_scope_player_initiated']=False
                else:f.held.remove(f.by_event('fresh_released'))
                with self.assertRaises(AssertionError):f.evaluate(mobile_held_click=True)

    def test_missing_canonical_wire_native_replay_or_continuations_cannot_be_replaced_by_held_prefix(self):
        for change in ('canonical','wire','native','replay','continuations','sender','journal'):
            with self.subTest(change=change):
                f=HeldFixture()
                if change=='canonical':f.commits=[]
                elif change=='wire':f.bridges=[]
                elif change=='native':f.native[0]['parsed_state_sha256']='0'*64
                elif change=='replay':
                    for r in f.worker:r.update(replayed_frames_delta=0,replayed_frames_total=0)
                elif change=='continuations':f.worker=[r for r in f.worker if r['frame']!=205]
                elif change=='sender':f.fresh_assigned=190
                else:f.journal[185]['players'][1]=[]
                with self.assertRaises(AssertionError):f.evaluate(mobile_held_click=True)

    def test_second_episode_and_independent_full_mobile_proof_are_required(self):
        fs=[HeldFixture(1),HeldFixture(2)];episodes=[f.evaluate(mobile_held_click=True)for f in fs]
        log='\n'.join(f.log()for f in fs);matches=[f.match for f in fs]
        for change in ('missing','attacker','nativeproof','rewritten'):
            altered=deepcopy(episodes);own_log=log;attacker=''
            if change=='missing':own_log=fs[0].log()
            elif change=='attacker':attacker=fs[0].log()
            elif change=='nativeproof':altered[1]['fresh_native_confirmation']['continuation_frames']=0
            else:altered[0]['mobile_held_click']['rows'][0]['device']='beef'
            with self.subTest(change=change),self.assertRaises(AssertionError):
                held.evaluate(own_log,attacker_log=attacker,mobile_episodes=altered,expected_matches=matches)


if __name__=='__main__':unittest.main()
