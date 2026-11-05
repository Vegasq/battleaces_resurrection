import copy
import hashlib
import unittest
import zlib

from server import community_protocol as c
from server.protobuf_wire import field_bytes,field_uint
from tools.packaged_custom_evidence import validate,replays


class PackagedCustomEvidenceTests(unittest.TestCase):
    def fixture(self,rounds=2):
        lobby='c'*32;ids=[f'{index+1:032x}' for index in range(rounds)];clients=[];events=[];frozen=[];commands=[];counts=dict.fromkeys(ids,600)
        for i in range(2):clients.append(dict(pid=100+i,player=f'human{i}',name=f'Human {i}',log='',matches={}))
        events.extend([dict(event='community_joined'),dict(event='community_joined'),
            dict(event='custom_lobby_created',lobby=lobby,host='human0'),
            dict(event='custom_invite_created',lobby=lobby,sender='human0',target='human1'),
            dict(event='custom_invite_resolved',status=c.ACCEPTED)])
        raw=[]
        for index,match in enumerate(ids):
            game=field_uint(1,11+index);encoded=field_bytes(1,game)+b''.join(field_bytes(2,field_uint(1,f)) for f in range(600))
            stream=zlib.compressobj(wbits=-15);raw.append(stream.compress(encoded)+stream.flush())
            decks={'0':[11 if index%2==0 else 33]*8,'1':[22]*8}
            frozen.append(dict(match=match,lobby=lobby,epoch=index+1,decks=decks,
                game_data_sha256=hashlib.sha256(game).hexdigest(),complete_profiles=['human0','human1'],cosmetics={'0':{},'1':{}},
                humans={str(i):dict(profile=r['player'],name=r['name']) for i,r in enumerate(clients)},
                roster=[dict(ai_profile_id=0),dict(ai_profile_id=0)]))
            events.extend([dict(event='match_created',match=match,mode=1,participants=2,perf_counter_ns=1000+1000*index,worker_pid=200+index),
                dict(event='match_completed',match=match,result={'complete':True}),
                dict(event='worker_released',match=match,worker_pid=200+index,perf_counter_ns=1500+1000*index)])
            events.extend(dict(event='frame_queued',match=match,frame=f,frame_payload_sha256=f'{f:064x}') for f in range(600))
            events.extend(dict(event='native_snapshot',match=match,frame=f,viewer=v,canonical_fnv1a64=f'{f:016x}') for f in range(0,600,20) for v in (0,1))
            for i,row in enumerate(clients):
                row['log']+=(f'Community native custom match joined: lobby={lobby} match={match} epoch={index+1} seat={i} session={index+1}\n'
                    'Client world acquired: owner=remote\n'
                    f'LAN NORMAL BUILD smoke frame{300+100*i} slot{i} queued=1 commandQueueDelta=1\n'
                    'Client world released: owner=remote nativeIdle=1\n'
                    'Community native match return: fixture\nCommunity native lobby restored: fixture\n'
                    'COMMUNITY MATCH SMOKE native Continue fixture\nCommunity duplicate native start settled without wire replay: fixture\n')
                if i==0 and index+1<rounds:
                    row['log']+=(f'Dedicated deck smoke rematch-before units=[{",".join([str(11 if index%2==0 else 33)]*8)}]\n'
                                 f'Dedicated deck smoke rematch-after units=[{",".join([str(33 if index%2==0 else 11)]*8)}]\n')
                row['matches'][match]=dict(receipts=[dict(pid=str(row['pid']),match=match,frame=str(f),sha256=f'{f:064x}') for f in range(600)],
                    audit=[dict(frame=str(f),viewer=str(i),canonical_fnv1a64=f'{f:016x}') for f in range(0,600,20)])
            commands.extend([dict(kind=c.START,profile='human0',lobby=lobby,perf_counter_ns=100+1000*index),
                dict(kind=c.READY,profile='human1',lobby=lobby,epoch=index+1,perf_counter_ns=200+1000*index),
                dict(kind=c.RETURN,profile='human0'),dict(kind=c.RETURN,profile='human1')])
        commands.extend([dict(kind=c.LEAVE,profile='human1'),dict(kind=c.LEAVE,profile='human0')])
        for i,row in enumerate(clients):
            row['log']+=('COMMUNITY MATCH SMOKE host native picker Invite\n' if i==0 else 'COMMUNITY MATCH SMOKE guest native Accept\n')
            row['log']+=('COMMUNITY MATCH SMOKE passed: fixture\nCOMMUNITY MATCH SMOKE original post-match Leave dispatched: fixture\n'
                         'COMMUNITY MATCH SMOKE post-match leave passed: fixture\nNATIVE QUIT owned gate released: fixture\nNATIVE QUIT owned menu verified: fixture\n')
            row['replays']=replays(raw,frozen,counts,expected_rounds=rounds)
        return events,clients,frozen,commands,raw,counts

    def test_two_original_human_rounds_same_lobby_leave_and_quit(self):
        events,clients,frozen,commands,_,_=self.fixture();r=validate(events,clients,frozen=frozen,commands=commands)
        self.assertEqual(r['epochs'],[1,2]);self.assertEqual(r['worker_pids'],[200,201]);self.assertFalse(r['independent_full_state_proof'])
        self.assertEqual([r['rounds'][1]['frames'] for r in r['clients']],[600,600])

    def expiry_fixture(self):
        events,clients,frozen,commands,_,_=self.fixture()
        lobby=frozen[0]['lobby']
        for index,row in enumerate(frozen):row['epoch']=index+3
        for row in clients:
            row['log']=row['log'].replace('epoch=1','epoch=3').replace('epoch=2','epoch=4')
        for index,row in enumerate(r for r in commands if r['kind']==c.READY):
            row.update(epoch=index+3,request=index+3)
        commands[:0]=[dict(kind=c.START,profile='human0',lobby=lobby,request=1,perf_counter_ns=1),
                     dict(kind=c.READY,profile='human1',lobby=lobby,epoch=1,request=2,perf_counter_ns=2)]
        clients[0]['log']=('[100] Community start transaction dispatched: nativeKind=15 wireKind=48 request=4 epoch=3 cancel=0\n'
            'COMMUNITY MATCH SMOKE rejected/timed-out Start rolled back to full native lobby; retry deferred\n'
            'Community duplicate native start settled without wire replay: expired host\n'+clients[0]['log'])
        clients[1]['log']=('[110] Community native start completed: kind=16 epoch=1 success=0 oldPendingReleased=1 next=0\n'
            '[110] Community start transaction dispatched: nativeKind=16 wireKind=49 request=3 epoch=3 cancel=0\n'
            '[120] Community native start completed: kind=16 epoch=3 success=1 oldPendingReleased=1 next=0\n'
            '[120] Community native start completed: kind=16 epoch=3 success=1 oldPendingReleased=1 next=0\n'+clients[1]['log'])
        for row in clients:
            row['log']+=(f'Match loading event=error source=custom ticket=1 identity=custom:{lobby}:1 stage=waiting pending=0 visible=1 nativeVisible=1 rendererFailed=0 reason=Match start was cancelled. Please try again.\n'
                f'Match loading event=ready source=custom ticket=2 identity=custom:{lobby}:3 stage=starting pending=0 visible=0 nativeVisible=0 rendererFailed=0\n'
                f'Match loading event=ready source=custom ticket=3 identity=custom:{lobby}:4 stage=starting pending=0 visible=0 nativeVisible=0 rendererFailed=0\n')
        before=dict(lobby=lobby,epoch=3,phase=c.STARTING,ready=['human0'],members=['human0','human1'],
                    room=None,rooms=0,matches=0)
        proof=dict(lobby=lobby,profile='human1',request=2,old_epoch=1,configured_timeout=10,
                   held_at=1,deadline=11,released_at=11.3,rejected_at=11.31,rejection='start attempt changed',
                   before=before,after=copy.deepcopy(before))
        return events,clients,frozen,commands,proof

    def test_expiry_requires_new_epoch_and_old_pending_release_before_recovery(self):
        events,clients,frozen,commands,proof=self.expiry_fixture()
        result=validate(events,clients,frozen=frozen,commands=commands,ready_expiry=proof)
        self.assertEqual(result['epochs'],[3,4])
        self.assertEqual(result['ready_expiry']['native_ticks']['old_ready_released'],110)
        with self.assertRaises(AssertionError):validate(events,clients,frozen=frozen,commands=commands)
        for change in (lambda p:p.update(configured_timeout=.05),lambda p:p.update(released_at=10),
                       lambda p:p['after'].update(epoch=4),lambda p:p['before'].update(matches=1),
                       lambda p:p.update(profile='human0'),lambda p:p.update(request=8)):
            wrong=copy.deepcopy(proof);change(wrong)
            with self.subTest(change=change),self.assertRaises(AssertionError):
                validate(events,clients,frozen=frozen,commands=commands,ready_expiry=wrong)
        for old,new in (('[110]','[90]'),('oldPendingReleased=1','oldPendingReleased=0'),('epoch=3 success=1','epoch=1 success=1'),
                        ('pending=0 visible=0','pending=1 visible=1'),('rendererFailed=0','rendererFailed=1')):
            wrong=copy.deepcopy(clients);wrong[1]['log']=wrong[1]['log'].replace(old,new)
            with self.subTest(change=new),self.assertRaises(AssertionError):
                validate(events,wrong,frozen=frozen,commands=commands,ready_expiry=proof)

    def test_wrong_start_ready_ownership_duplicate_wire_or_early_worker_rejected(self):
        events,clients,frozen,commands,_,_=self.fixture()
        for change in (lambda rows:rows[0].update(profile='human1'),lambda rows:rows.append(copy.deepcopy(rows[1])),
                       lambda rows:rows[1].update(perf_counter_ns=3000),lambda rows:rows.reverse()):
            changed=copy.deepcopy(commands);change(changed)
            with self.subTest(change=change),self.assertRaises(AssertionError):validate(events,clients,frozen=frozen,commands=changed)
        wrong=copy.deepcopy(events);next(e for e in wrong if e['event']=='worker_released')['perf_counter_ns']=3000
        with self.assertRaises(AssertionError):validate(wrong,clients,frozen=frozen,commands=commands)

    def test_start_rejection_preserves_intent_and_releases_loading_before_retry(self):
        events,clients,frozen,commands,_,_=self.fixture();lobby=frozen[0]['lobby']
        for row in clients:row['log']=row['log'].replace('Community duplicate native start settled without wire replay: fixture\n','')
        starts=[r for r in commands if r['kind']==c.START]
        for index,row in enumerate(starts):row['request']=index+3
        commands.insert(0,dict(kind=c.START,profile='human0',lobby=lobby,request=2,perf_counter_ns=1))
        selections={}
        for index,row in enumerate(clients):
            cosmetics=dict(catalog_sha256='a'*64,slots=[[slot,slot+index] for slot in range(1,18)])
            frozen[0]['cosmetics'][str(index)]=copy.deepcopy(cosmetics)
            selections[row['player']]=dict(deck=frozen[0]['decks'][str(index)],full=True,cosmetics=cosmetics)
        proof=dict(lobby=lobby,profile='human0',request=2,epoch=0,phase=c.OPEN,rooms=0,matches=0,
                   reason='qualification: host start rejected',selections=selections)
        clients[0]['log']=(f'Match loading event=error source=custom ticket=1 identity=custom:{lobby}:1 stage=waiting pending=0 visible=1 nativeVisible=1 rendererFailed=0 reason=The server could not start this match. Please try again.\n'
            'Community native start completed: kind=15 epoch=1 success=0 oldPendingReleased=1\n'
            'COMMUNITY MATCH SMOKE rejected/timed-out Start rolled back to full native lobby; retry deferred\n'
            'Community start transaction dispatched: nativeKind=15 wireKind=48 request=3 epoch=1 cancel=0\n'
            'Community native start completed: kind=15 epoch=1 success=1 oldPendingReleased=1\n'
            f'Match loading event=ready source=custom ticket=2 identity=custom:{lobby}:1 stage=starting pending=0 visible=0 nativeVisible=0 rendererFailed=0\n'+clients[0]['log'])
        result=validate(events,clients,frozen=frozen,commands=commands,start_rejection=proof)
        self.assertEqual(result['epochs'],[1,2]);self.assertTrue(result['start_rejection']['pre_rejection_loadouts_preserved'])
        for change in (lambda p:p.update(epoch=1),lambda p:p.update(rooms=1),lambda p:p.update(profile='human1'),
                       lambda p:p.update(request=999),lambda p:p['selections']['human0'].update(full=False),
                       lambda p:p['selections']['human1']['cosmetics']['slots'].pop()):
            wrong=copy.deepcopy(proof);change(wrong)
            with self.subTest(change=change),self.assertRaises(AssertionError):
                validate(events,clients,frozen=frozen,commands=commands,start_rejection=wrong)
        for old,new in (('oldPendingReleased=1','oldPendingReleased=0'),('ticket=2','ticket=1'),
                        ('request=3 epoch=1','request=2 epoch=1'),('pending=0 visible=0','pending=1 visible=1')):
            wrong=copy.deepcopy(clients);wrong[0]['log']=wrong[0]['log'].replace(old,new)
            with self.subTest(change=new),self.assertRaises(AssertionError):
                validate(events,wrong,frozen=frozen,commands=commands,start_rejection=proof)

    def test_native_frames_state_world_and_quit_must_agree(self):
        events,clients,frozen,commands,_,_=self.fixture();match=frozen[0]['match']
        for change in (lambda rows:rows[0]['matches'][match]['receipts'][10].update(sha256='bad'),
                       lambda rows:rows[1]['matches'][match]['audit'][0].update(canonical_fnv1a64='bad'),
                       lambda rows:rows[0].update(log='NATIVE QUIT owned gate released: early\n'+rows[0]['log']),
                       lambda rows:rows[1].update(log=rows[1]['log'].replace('post-match leave passed:','not left:')),
                       lambda rows:rows[0]['replays'][match].update(sha256='bad')):
            changed=copy.deepcopy(clients);change(changed)
            with self.subTest(change=change),self.assertRaises(AssertionError):validate(events,changed,frozen=frozen,commands=commands)

    def test_human_only_invite_rematch_decks_and_identity_required(self):
        events,clients,frozen,commands,_,_=self.fixture()
        for change in (lambda rows:rows[1]['roster'][1].update(ai_profile_id=60),lambda rows:rows[1].update(epoch=1),
                       lambda rows:rows[1]['decks'].update({'0':rows[0]['decks']['0']}),
                       lambda rows:rows[1]['humans']['1'].update(name='wrong'),lambda rows:rows[1].update(complete_profiles=[])):
            changed=copy.deepcopy(frozen);change(changed)
            with self.subTest(change=change),self.assertRaises(AssertionError):validate(events,clients,frozen=changed,commands=commands)
        with self.assertRaises(AssertionError):validate(events+[dict(event='public_match_offered')],clients,frozen=frozen,commands=commands)
        wrong=copy.deepcopy(events);next(e for e in wrong if e['event']=='custom_invite_created')['target']='wrong'
        with self.assertRaises(AssertionError):validate(wrong,clients,frozen=frozen,commands=commands)

    def test_replay_round_hash_count_and_contiguous_records_required(self):
        _,_,frozen,_,raw,counts=self.fixture()
        for files in (raw[:1],[raw[0],raw[0]],raw+[raw[1]]):
            with self.subTest(files=len(files)),self.assertRaises(AssertionError):replays(files,frozen,counts)
        with self.assertRaises(AssertionError):replays(raw,frozen,{m:n+1 for m,n in counts.items()})

    def test_twenty_rematches_validate_every_round_and_worker_boundary(self):
        events,clients,frozen,commands,_,_=self.fixture(21)
        result=validate(events,clients,frozen=frozen,commands=commands,expected_rounds=21)
        self.assertEqual(result['epochs'],list(range(1,22)))
        for index in (2,10,19,20):
            match=frozen[index]['match']
            changed=copy.deepcopy(clients)
            changed[1]['matches'][match]['receipts'][10]['sha256']='bad'
            with self.subTest(round=index+1),self.assertRaises(AssertionError):
                validate(events,changed,frozen=frozen,commands=commands,expected_rounds=21)
        changed=copy.deepcopy(events)
        next(row for row in changed if row['event']=='worker_released' and row['match']==frozen[19]['match'])['perf_counter_ns']=999999
        with self.assertRaises(AssertionError):validate(changed,clients,frozen=frozen,commands=commands,expected_rounds=21)

    def test_two_round_report_cannot_satisfy_twenty_rematches(self):
        events,clients,frozen,commands,raw,counts=self.fixture()
        with self.assertRaises(AssertionError):validate(events,clients,frozen=frozen,commands=commands,expected_rounds=21)
        with self.assertRaises(AssertionError):replays(raw,frozen,counts,expected_rounds=21)
