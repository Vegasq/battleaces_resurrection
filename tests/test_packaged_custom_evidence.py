import copy
import hashlib
import unittest
import zlib

from server import community_protocol as c
from server.protobuf_wire import field_bytes,field_uint
from tools.packaged_custom_evidence import validate,replays


class PackagedCustomEvidenceTests(unittest.TestCase):
    def fixture(self):
        lobby='c'*32;ids=['a'*32,'b'*32];clients=[];events=[];frozen=[];commands=[];counts=dict.fromkeys(ids,600)
        for i in range(2):clients.append(dict(pid=100+i,player=f'human{i}',name=f'Human {i}',log='',matches={}))
        events.extend([dict(event='community_joined'),dict(event='community_joined'),
            dict(event='custom_lobby_created',lobby=lobby,host='human0'),
            dict(event='custom_invite_created',lobby=lobby,sender='human0',target='human1'),
            dict(event='custom_invite_resolved',status=c.ACCEPTED)])
        raw=[]
        for index,match in enumerate(ids):
            game=field_uint(1,11+index);encoded=field_bytes(1,game)+b''.join(field_bytes(2,field_uint(1,f)) for f in range(600))
            stream=zlib.compressobj(wbits=-15);raw.append(stream.compress(encoded)+stream.flush())
            decks={'0':[11 if index==0 else 33]*8,'1':[22]*8}
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
                if i==0 and index==0:
                    row['log']+=('Dedicated deck smoke rematch-before units=[11,11,11,11,11,11,11,11]\n'
                                 'Dedicated deck smoke rematch-after units=[33,33,33,33,33,33,33,33]\n')
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
            row['replays']=replays(raw,frozen,counts)
        return events,clients,frozen,commands,raw,counts

    def test_two_original_human_rounds_same_lobby_leave_and_quit(self):
        events,clients,frozen,commands,_,_=self.fixture();r=validate(events,clients,frozen=frozen,commands=commands)
        self.assertEqual(r['epochs'],[1,2]);self.assertEqual(r['worker_pids'],[200,201]);self.assertFalse(r['independent_full_state_proof'])
        self.assertEqual([r['rounds'][1]['frames'] for r in r['clients']],[600,600])

    def test_wrong_start_ready_ownership_duplicate_wire_or_early_worker_rejected(self):
        events,clients,frozen,commands,_,_=self.fixture()
        for change in (lambda rows:rows[0].update(profile='human1'),lambda rows:rows.append(copy.deepcopy(rows[1])),
                       lambda rows:rows[1].update(perf_counter_ns=3000),lambda rows:rows.reverse()):
            changed=copy.deepcopy(commands);change(changed)
            with self.subTest(change=change),self.assertRaises(AssertionError):validate(events,clients,frozen=frozen,commands=changed)
        wrong=copy.deepcopy(events);next(e for e in wrong if e['event']=='worker_released')['perf_counter_ns']=3000
        with self.assertRaises(AssertionError):validate(wrong,clients,frozen=frozen,commands=commands)

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
