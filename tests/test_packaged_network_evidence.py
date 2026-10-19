import copy
import hashlib
import unittest
import zlib
from server.protobuf_wire import field_bytes,field_uint
from tools.packaged_network_evidence import validate,validate_loading_recovery,validate_replays
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

    def test_missing_or_failed_authoritative_lifecycle(self):
        events,clients=self.fixture()
        for kind in ('worker_released','match_completed','frame_queued','native_snapshot'):
            with self.subTest(kind=kind),self.assertRaises(AssertionError):validate([e for e in events if e['event']!=kind],clients,mode=1)
        with self.assertRaises(AssertionError):validate(events+[dict(event='match_aborted')],clients,mode=1)

    def test_external_driver_sources_compile(self):
        for name in ('SERVER','CLIENT'):compile(getattr(drivers,name),'<owned '+name+' adapter>','exec')

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
