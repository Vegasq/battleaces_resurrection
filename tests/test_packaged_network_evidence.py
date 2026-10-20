import copy
import hashlib
import unittest
import zlib
from server.protobuf_wire import field_bytes,field_uint
from tools.packaged_network_evidence import validate,validate_loading_recovery,validate_running_recovery,validate_replays,validate_worker_shutdown,validate_native_selections,validate_bot_fill
from tools import packaged_network_drivers as drivers


class PackagedNetworkEvidenceTests(unittest.TestCase):
    def fixture(self):
        match='a'*32
        events=[dict(event='public_queue_entered',perf_counter_ns=t) for t in (1000000000,1100000000)]
        events += [dict(event='public_match_offered',match=match,humans=['human0','human1'],fallback=False,perf_counter_ns=2000000000),
                   dict(event='match_created',match=match,mode=1,participants=2,decks={'0':[11]*8,'1':[22]*8}),
                   dict(event='worker_started',match=match,worker_pid=100),
                   dict(event='match_completed',match=match,result={'complete':True}),
                   dict(event='worker_released',match=match,worker_pid=100)]
        events += [dict(event='frame_queued',match=match,frame=f,frame_payload_sha256=f'{f:064x}') for f in range(600)]
        events += [dict(event='native_snapshot',match=match,frame=f,viewer=v,canonical_fnv1a64=f'{f:016x}') for f in range(0,600,20) for v in (0,1)]
        clients=[]
        for seat in (0,1):
            log=('[1000] Native search began: ticket=1 mode=1 nativeStatus=5\n'
                 f'[2000] Public authoritative state: ticket=1 phase=1 mode=1 match={match} elapsedMs=1000\n'
                 f'Public match assignment: ticket=1 match={match} mode=1 count=2 seat={seat} humans=3 \n'
                 'Public native match joined: ticket=1\nClient world acquired: generation=1\n'
                 f'LAN NORMAL BUILD smoke frame{300+100*seat} slot{seat} army{seat} queued=1 commandQueueDelta=1\n'
                 f'Public native return: ticket=1 match={match} aborted=0 nativeIdle=1\n'
                 'Client world released: generation=1 owner=remote nativeIdle=1\n'
                 'PUBLIC QUEUE completed return: completed=1\nNative search timer: ticket=1 seconds=0\n'
                 'NATIVE QUIT owned gate released: fixture\nNATIVE QUIT owned menu verified: fixture\n')
            clients.append(dict(player='human'+str(seat),pid=200+seat,name='Human '+str(seat),log=log,
                receipts=[dict(frame=str(f),sha256=f'{f:064x}',pid=str(200+seat),match=match) for f in range(600)],
                audit=[dict(frame=str(f),viewer=str(seat),canonical_fnv1a64=f'{f:016x}') for f in range(0,600,20)]))
        return events,clients

    def test_verified_transport_observable_state_and_gate_scope(self):
        events,clients=self.fixture();result=validate(events,clients,mode=1)
        self.assertEqual(result['frames'],600);self.assertEqual(result['human_seats'],[0,1])
        self.assertFalse(result['independent_full_state_proof']);self.assertTrue(result['full_human_group'])

    def test_wrong_native_frames_snapshot_identity_or_early_quit(self):
        events,clients=self.fixture()
        for mutate in (lambda c:c[0]['receipts'][20].update(sha256='b'*64),
                       lambda c:c[0]['audit'][0].update(canonical_fnv1a64='b'*16),
                       lambda c:c[0]['receipts'][20].update(pid='wrong'),
                       lambda c:c[0].update(log=c[0]['log'].replace('seat=0','seat=1')),
                       lambda c:c[0].update(log='NATIVE QUIT owned gate released: early\n'+c[0]['log']),
                       lambda c:c[0].update(log=c[0]['log']+'Public fallback accepted: fixture')):
            changed=copy.deepcopy(clients);mutate(changed)
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):validate(events,changed,mode=1)

    def test_partial_group_requires_real_deadline(self):
        events,clients=self.fixture()
        for e in events:
            if e['event']=='public_match_offered':e.update(fallback=True,perf_counter_ns=31000000000)
            if e['event']=='match_created':e.update(mode=2,participants=4)
        for c in clients:c['log']=c['log'].replace('mode=1','mode=2').replace('count=2','count=4').replace('[2000]','[31000]').replace('elapsedMs=1000','elapsedMs=30000')+'Native search timer: ticket=1 seconds=29\n'
        self.assertEqual(validate(events,clients,mode=2)['bot_seats'],[2,3])
        wrong=copy.deepcopy(clients);wrong[0]['log']=wrong[0]['log'].replace('elapsedMs=30000','elapsedMs=29000')
        with self.assertRaises(AssertionError):validate(events,wrong,mode=2)
        next(e for e in events if e['event']=='public_match_offered')['perf_counter_ns']=2000000000
        with self.assertRaises(AssertionError):validate(events,clients,mode=2)

    def test_single_human_requires_full_wait_in_each_public_mode(self):
        for mode,total in ((1,2),(2,4),(5,4)):
            events,clients=self.fixture();clients=clients[:1]
            events=[e for e in events if not(e['event']=='public_queue_entered' and e['perf_counter_ns']==1100000000)]
            for e in events:
                if e['event']=='public_match_offered':e.update(humans=['human0'],fallback=True,perf_counter_ns=31000000000)
                if e['event']=='match_created':e.update(mode=mode,participants=total)
            clients[0]['log']=(clients[0]['log'].replace('mode=1',f'mode={mode}').replace('count=2',f'count={total}')
                .replace('humans=3','humans=1').replace('[2000]','[31000]').replace('elapsedMs=1000','elapsedMs=30000')+
                'Native search timer: ticket=1 seconds=29\n')
            proof=validate(events,clients,mode=mode)
            self.assertEqual(proof['bot_seats'],list(range(1,total)))
            self.assertEqual(proof['real_queue_waits_seconds'],[30.0])
            self.assertFalse(proof['full_human_group'])
            wrong=copy.deepcopy(clients);wrong[0]['log']=wrong[0]['log'].replace('elapsedMs=30000','elapsedMs=29000')
            with self.assertRaises(AssertionError):validate(events,wrong,mode=mode)

    def bot_fixture(self,*,commands=True,timestep=50):
        from server.ai_rules import SUPPORTED_AI_SHA256
        from server.game_data import encode_identity,encode_frame,encode_player_input
        from tests.synthetic import template
        game=template().raw_game_data
        identity=encode_identity(2,'Authored Bot',ai_profile_id=64)
        frames=[]
        for frame in range(2):
            actions=[field_bytes(3,field_uint(1,1))] if frame==0 else ([field_bytes(1,field_uint(1,7))] if commands else [])
            raw=encode_frame(frame,{0:b'',1:encode_player_input(identity,actions)})
            if timestep!=50:raw=raw.replace(field_uint(3,50),field_uint(3,timestep),1)
            frames.append(field_bytes(2,raw))
        replay=zlib.compress(field_bytes(1,game)+b''.join(frames),wbits=-zlib.MAX_WBITS)
        frozen=dict(match='a'*32,game_data_sha256=hashlib.sha256(game).hexdigest(),roster=[
            dict(slot=0,player_id=1,name='Human',ai_profile_id=0),dict(slot=1,player_id=2,name='Authored Bot',ai_profile_id=64)])
        worker=dict(dll_sha256=SUPPORTED_AI_SHA256,bots={'1':64})
        events=[dict(event='native_snapshot',match='a'*32,viewer=1,resources={'1':{'current_supply':10}})]
        return events,frozen,worker,replay

    def test_bot_fill_requires_native_commands_and_own_supply(self):
        events,frozen,worker,replay=self.bot_fixture()
        proof=validate_bot_fill(events,frozen,worker,replay,bot_seats=[1])
        self.assertEqual(proof['bots'][0]['native_commands'],1)
        self.assertEqual(proof['bots'][0]['native_max_supply'],10)
        for event_change in (dict(match='b'*32),dict(viewer=0),dict(resources={'0':{'current_supply':10}})):
            changed=copy.deepcopy(events);changed[0].update(event_change)
            with self.assertRaises(AssertionError):validate_bot_fill(changed,frozen,worker,replay,bot_seats=[1])
        events,frozen,worker,replay=self.bot_fixture(commands=False)
        with self.assertRaises(AssertionError):validate_bot_fill(events,frozen,worker,replay,bot_seats=[1])

    def test_bot_fill_rejects_changed_identity_worker_or_clock(self):
        events,frozen,worker,replay=self.bot_fixture()
        for change in (dict(player_id=3),dict(name='Other'),dict(ai_profile_id=63),dict(player_id=1)):
            changed=copy.deepcopy(frozen);changed['roster'][1].update(change)
            with self.assertRaises(AssertionError):validate_bot_fill(events,changed,worker,replay,bot_seats=[1])
        with self.assertRaises(AssertionError):validate_bot_fill(events,frozen,dict(worker,bots={'0':64}),replay,bot_seats=[1])
        events,frozen,worker,replay=self.bot_fixture(timestep=100)
        with self.assertRaises(AssertionError):validate_bot_fill(events,frozen,worker,replay,bot_seats=[1])

    def test_missing_or_failed_authoritative_lifecycle(self):
        events,clients=self.fixture()
        for kind in ('worker_released','match_completed','frame_queued','native_snapshot'):
            with self.subTest(kind=kind),self.assertRaises(AssertionError):validate([e for e in events if e['event']!=kind],clients,mode=1)
        with self.assertRaises(AssertionError):validate(events+[dict(event='match_aborted')],clients,mode=1)

    def test_external_driver_sources_compile(self):
        for name in ('SERVER_CHECK','SERVER','CLIENT'):compile(getattr(drivers,name),'<owned '+name+' adapter>','exec')

    def four_human_fixture(self):
        events,base=self.fixture();clients=[]
        for seat in range(4):
            prior=seat%2;row=copy.deepcopy(base[prior]);row.update(player='human'+str(seat),pid=200+seat,name='Human '+str(seat),deck_edited=bool(prior))
            row['log']=(row['log'].replace('mode=1','mode=2').replace('count=2','count=4').replace('humans=3','humans=15')
                        .replace(f'seat={prior}',f'seat={seat}').replace(f'slot{prior} army{prior}',f'slot{seat} army{seat}')
                        .replace(f'frame{300+100*prior}',f'frame{300+100*seat}'))
            export=''
            if prior:
                export=('Dedicated deck smoke rematch-before units=[11,11,11,11,11,11,11,11] abilities=[1,0,0,0]\n'
                        'Dedicated deck smoke rematch-after units=[22,22,22,22,22,22,22,22] abilities=[1,0,0,0]\n'
                        'DEDICATED REMATCH SMOKE automated native deck edit: full-valid=1\n')
            row['log']=export+'Public search intent: ticket=1\n'+row['log']
            for receipt in row['receipts']:receipt['pid']=str(row['pid'])
            clients.append(row)
        decks={str(s):[11 if s%2==0 else 22]*8 for s in range(4)}
        for event in events:
            if event['event']=='public_match_offered':event['humans']=[r['player'] for r in clients]
            if event['event']=='match_created':event.update(mode=2,participants=4,decks=copy.deepcopy(decks))
        events += [dict(event='public_queue_entered',perf_counter_ns=t) for t in (1200000000,1300000000)]
        frozen=dict(humans={str(s):dict(profile=r['player'],name=r['name']) for s,r in enumerate(clients)},
                    decks=decks,active_ability_groups={str(s):[1,0,0,0] for s in range(4)})
        return events,clients,frozen

    def test_full_four_humans_keep_independent_native_choices_including_identical_decks(self):
        events,clients,frozen=self.four_human_fixture();choices=validate_native_selections(clients,frozen)
        result=validate(events,clients,mode=2,expected_decks=choices)
        self.assertTrue(result['full_human_group']);self.assertEqual(result['human_seats'],[0,1,2,3]);self.assertEqual(result['bot_seats'],[])
        self.assertEqual(len(choices),4);self.assertEqual(len({tuple(v['units']) for v in choices.values()}),2)
        # Original two-player/distinct-choice proof remains the default contract.
        with self.assertRaises(AssertionError):validate(events,clients,mode=2)

    def test_four_human_binding_rejects_profile_deck_ability_or_identity_mixup(self):
        events,clients,frozen=self.four_human_fixture()
        for change in (lambda f:f['decks']['2'].__setitem__(0,22),
                       lambda f:f['active_ability_groups']['2'].__setitem__(0,9),
                       lambda f:f['humans']['2'].update(profile='human0'),
                       lambda f:f['humans']['3'].update(name='wrong')):
            changed=copy.deepcopy(frozen);change(changed)
            with self.subTest(change=change),self.assertRaises(AssertionError):validate_native_selections(clients,changed)
        choices=validate_native_selections(clients,frozen)
        next(e for e in events if e['event']=='match_created')['decks']['0'][0]=22
        with self.assertRaises(AssertionError):validate(events,clients,mode=2,expected_decks=choices)

    def test_four_human_choices_require_original_saved_before_play_exports(self):
        _,clients,frozen=self.four_human_fixture()
        for change in (lambda c:c[3].update(pid=c[1]['pid']),
                       lambda c:c[1].update(log=c[1]['log'].replace('full-valid=1','full-valid=0')),
                       lambda c:c[3].update(log=c[3]['log'].replace('abilities=[1,0,0,0]','abilities=[0,0,0,0]',1)),
                       lambda c:c[1].update(log='Public search intent: early\n'+c[1]['log']),
                       lambda c:c[1].update(log=c[1]['log']+'Dedicated deck smoke rematch-after units=[22,22,22,22,22,22,22,22] abilities=[1,0,0,0]\n')):
            changed=copy.deepcopy(clients);change(changed)
            with self.subTest(change=change),self.assertRaises(AssertionError):validate_native_selections(changed,frozen)

    def recovery_fixture(self):
        events,clients=self.fixture();old='b'*32
        for event in events:
            if event['event']=='public_queue_entered':event['ticket']=2
            if event['event']=='match_created':event['perf_counter_ns']=50
        events=[dict(event='public_queue_entered',ticket=1),dict(event='public_queue_entered',ticket=1),
                dict(event='public_match_offered',match=old),dict(event='match_created',match=old),
                dict(event='match_aborted',match=old),dict(event='worker_released',match=old,worker_pid=50,perf_counter_ns=20)]+events
        victim=('RECOVERY SMOKE invoking original disconnected modal OnConfirm\nDedicated Reconnect callback queued:\n'
                'RECOVERY SMOKE original OnConfirm returned; modalStillOwned=1 queued=1\n'
                'Dedicated retry modal released on later update: requested=10 current=11\n'
                f'Dedicated session reset: match={old}\n'
                'Client world released: generation=1 owner=remote nativeIdle=1\n'
                'Public intent retired: ticket=1 reason=connection lost after match acceptance nativeIdle=1 disconnect=1\n')
        survivor=(f'Public native return: ticket=1 match={old} aborted=1 nativeIdle=1\n'
                  'Client world released: generation=1 owner=remote nativeIdle=1\nPUBLIC QUEUE completed return: initial\n')
        for index,row in enumerate(clients):
            row['log']=row['log'].replace('ticket=1','ticket=2').replace('generation=1','generation=2')+'Public search intent: ticket=2\n'
            if index==0:row['log']+='Loading notice dismissed: identity=public-error:1 reason=public search restarted\n'
            row['initial_log']=('Public search intent: ticket=1\nPublic native match joined: ticket=1\nClient world acquired: generation=1\n'+
                                (victim if index==0 else survivor)+'PUBLIC QUEUE SMOKE waiting for retry gate: fixture\n')
            row['initial_receipts']=[];row['full_log']=row['initial_log']+row['log']
        fault=dict(stage='loading',room_state='loading',next_frame=0,loaded=[],match=old,worker_pid=50)
        return events,clients,fault

    def test_loading_abort_and_replacement_keep_separate_tickets(self):
        events,clients,fault=self.recovery_fixture();result=validate_loading_recovery(events,clients,fault=fault)
        self.assertEqual(result['aborted_authoritative_frames'],0);self.assertTrue(result['same_native_processes'])
        replacement=[e for e in events if e.get('match')=='a'*32 or e['event']=='public_queue_entered' and e['ticket']==2]
        self.assertEqual(validate(replacement,clients,mode=1,ticket=2)['frames'],600)
        with self.assertRaises(AssertionError):validate(replacement,clients,mode=1)

    def test_recovery_rejects_advanced_frames_reused_match_and_unreleased_worker(self):
        events,clients,fault=self.recovery_fixture()
        for extra in (dict(event='frame_queued',match=fault['match']),dict(event='match_completed',match=fault['match'])):
            with self.subTest(extra=extra),self.assertRaises(AssertionError):validate_loading_recovery(events+[extra],clients,fault=fault)
        changed=copy.deepcopy(events)
        next(e for e in changed if e['event']=='worker_released' and e.get('match')==fault['match'])['perf_counter_ns']=60
        with self.assertRaises(AssertionError):validate_loading_recovery(changed,clients,fault=fault)
        with self.assertRaises(AssertionError):validate_loading_recovery(events,clients,fault=fault|dict(loaded=[0]))

    def test_recovery_requires_deferred_native_modal_and_surviving_connection(self):
        events,clients,fault=self.recovery_fixture()
        for change in (lambda c:c[0].update(initial_log=c[0]['initial_log'].replace('current=11','current=10')),
                       lambda c:c[0].update(initial_receipts=[dict(frame=0)]),
                       lambda c:c[1].update(full_log=c[1]['full_log']+'Dedicated Reconnect callback queued:'),
                       lambda c:c[0].update(log=c[0]['log'].replace('identity=public-error:1','identity=other'))):
            changed=copy.deepcopy(clients);change(changed)
            with self.subTest(change=change),self.assertRaises(AssertionError):validate_loading_recovery(events,changed,fault=fault)

    def test_native_loading_abort_replay_is_distinct_from_completed_recording(self):
        old=field_uint(1,10);new=field_uint(1,20)
        def compress(raw):
            stream=zlib.compressobj(wbits=-15);return stream.compress(raw)+stream.flush()
        empty=compress(field_bytes(1,old));complete=compress(field_bytes(1,new)+field_bytes(2,field_uint(1,0)))
        frozen=[dict(game_data_sha256=hashlib.sha256(game).hexdigest()) for game in (old,new)]
        proof=validate_replays([complete,empty],frozen=frozen,frames=1,loading_abort=True)
        self.assertEqual(proof['completed']['input_action_messages'],1)
        self.assertEqual(proof['aborted_loading']['input_action_messages'],0)
        self.assertFalse(proof['aborted_loading']['native_playback'])
        for files in ([empty],[empty,empty],[complete,complete],[empty,complete,empty]):
            with self.subTest(files=len(files)),self.assertRaises(AssertionError):validate_replays(files,frozen=frozen,frames=1,loading_abort=True)
        with self.assertRaises(AssertionError):validate_replays([empty,complete],frozen=frozen[::-1],frames=1,loading_abort=True)
        wrong=compress(field_bytes(1,new)+field_bytes(2,field_uint(1,7)))
        with self.assertRaises(AssertionError):validate_replays([empty,wrong],frozen=frozen,frames=1,loading_abort=True)

    def running_fixture(self,after_frame=200):
        events,clients,fault=self.recovery_fixture();old=fault['match']
        fault.update(stage='running',room_state='running',next_frame=after_frame+1,loaded=[0,1],peer_seats=[0,1],after_frame=after_frame)
        events += [dict(event='frame_queued',match=old,frame=f,frame_payload_sha256=f'{f:064x}') for f in range(after_frame+20)]
        events += [dict(event='native_snapshot',match=old,frame=f,viewer=s,canonical_fnv1a64=f'{f:016x}') for f in range(0,after_frame+1,20) for s in (0,1)]
        for seat,row in enumerate(clients):
            build=(f'Public match assignment: ticket=1 match={old} mode=1 count=2 seat={seat} humans=3 \n'
                   f'LAN NORMAL BUILD smoke frame{300+100*seat} slot{seat} queued=1 commandQueueDelta=1\n') if after_frame>=600 else ''
            row['initial_log']='Offline world ready; native fixture\n'+build+row['initial_log']
            row['full_log']=row['initial_log']+row['log']
            row['initial_receipts']=[dict(frame=str(f),sha256=f'{f:064x}',pid=str(row['pid']),match=old) for f in range(after_frame+1)]
            row['initial_audit']=[dict(frame=str(f),viewer=str(seat),canonical_fnv1a64=f'{f:016x}') for f in range(0,after_frame+1,20)]
        return events,clients,fault

    def test_later_running_fault_requires_both_original_builds(self):
        events,clients,fault=self.running_fixture(600)
        proof=validate_running_recovery(events,clients,fault=fault)
        self.assertEqual([r['native_build_frame'] for r in proof['aborted_clients']],[300,400])
        clients[1]['initial_log']=clients[1]['initial_log'].replace('queued=1','queued=0')
        with self.assertRaises(AssertionError):validate_running_recovery(events,clients,fault=fault)

    def test_worker_exit_admission_requires_exact_audited_cancelled_fault(self):
        events,_,fault=self.running_fixture()
        worker=dict(pid=50,exit_code=1,failure='CancelledError: ',reaped=True)
        self.assertTrue(validate_worker_shutdown([worker],events,fault=fault)[0]['expected_cancelled_request'])
        self.assertFalse(validate_worker_shutdown([worker|dict(exit_code=0,failure=None)],events)[0]['expected_cancelled_request'])
        for changed in (worker|dict(pid=51),worker|dict(failure='WorkerError: lost'),worker|dict(exit_code=2),worker|dict(reaped=False)):
            with self.subTest(worker=changed),self.assertRaises(AssertionError):validate_worker_shutdown([changed],events,fault=fault)
        for selected,case in ((events,None),(events,fault|dict(stage='loading')),
                              ([e for e in events if e['event']!='worker_released'],fault),
                              (events+[dict(event='match_completed',match=fault['match'])],fault)):
            with self.subTest(fault=case),self.assertRaises(AssertionError):validate_worker_shutdown([worker],selected,fault=case)

    def test_running_abort_requires_verified_authoritative_and_native_prefixes(self):
        events,clients,fault=self.running_fixture();result=validate_running_recovery(events,clients,fault=fault)
        self.assertEqual(result['aborted_authoritative_frames'],220)
        self.assertEqual([r['received_frames'] for r in result['aborted_clients']],[201,201])
        for change in (lambda c:c[0]['initial_receipts'][20].update(sha256='bad'),
                       lambda c:c[0]['initial_receipts'][20].update(pid='bad'),
                       lambda c:c[0]['initial_receipts'].pop(5),
                       lambda c:c[1]['initial_audit'][0].update(canonical_fnv1a64='bad'),
                       lambda c:c[0].update(initial_audit=[]),
                       lambda c:c[0].update(initial_log=c[0]['initial_log'].replace('Offline world ready;','absent'))):
            changed=copy.deepcopy(clients);change(changed)
            with self.subTest(change=change),self.assertRaises(AssertionError):validate_running_recovery(events,changed,fault=fault)

    def test_running_abort_rejects_wrong_stage_unloaded_roster_and_frame_gaps(self):
        events,clients,fault=self.running_fixture()
        for changed in (fault|dict(stage='loading'),fault|dict(next_frame=200),fault|dict(loaded=[0]),fault|dict(peer_seats=[0,2])):
            with self.subTest(fault=changed),self.assertRaises(AssertionError):validate_running_recovery(events,clients,fault=changed)
        changed=[e for e in events if not (e['event']=='frame_queued' and e.get('match')==fault['match'] and e['frame']==20)]
        with self.assertRaises(AssertionError):validate_running_recovery(changed,clients,fault=fault)

    def test_running_abort_replay_requires_nonempty_bounded_contiguous_prefix(self):
        old=field_uint(1,10);new=field_uint(1,20)
        def recording(game,frames):
            raw=field_bytes(1,game)+b''.join(field_bytes(2,field_uint(1,f)) for f in frames)
            stream=zlib.compressobj(wbits=-15);return stream.compress(raw)+stream.flush()
        frozen=[dict(game_data_sha256=hashlib.sha256(game).hexdigest()) for game in (old,new)]
        final=recording(new,range(600));initial=recording(old,range(195))
        proof=validate_replays([initial,final],frozen=frozen,frames=600,running_abort_frames=201)
        self.assertEqual(proof['aborted_running']['input_action_messages'],195)
        self.assertIsNone(proof['aborted_loading']);self.assertFalse(proof['aborted_running']['native_playback'])
        for initial in (recording(old,[]),recording(old,range(202)),recording(old,[0,2]),final):
            with self.subTest(initial=len(initial)),self.assertRaises(AssertionError):
                validate_replays([initial,final],frozen=frozen,frames=600,running_abort_frames=201)
        with self.assertRaises(AssertionError):validate_replays([initial,final],frozen=frozen,frames=600,loading_abort=True,running_abort_frames=201)
