"""Original native Custom invite/rematch/Leave/Quit evidence for bundled clients."""
import re
import zlib

from server import community_protocol as c
from server.protobuf_wire import parse_fields,get_uint
from tools.packaged_network_evidence import require
from tools.verify_native_storage import replay_evidence


def replays(files,frozen,counts):
    require(len(files)==len(frozen)==2,'Custom needs two completed native recordings')
    expected={r['game_data_sha256']:r['match'] for r in frozen};result={}
    require(len(expected)==2,'Custom rounds reused native GameData identity')
    for raw in files:
        proof=replay_evidence(raw);match=expected.get(proof['game_data_sha256'])
        require(match is not None and match not in result and proof['input_action_messages']==counts[match],
                'Custom native replay identity/frame count differs')
        fields=parse_fields(zlib.decompress(raw,-15),max_bytes=16*1024*1024,max_fields=16384)
        actions=[f.value for f in fields if f.number==2]
        require([get_uint(a,1) for a in actions]==list(range(counts[match])),'Custom replay frame sequence differs')
        result[match]=proof
    return result


def validate(events,clients,*,frozen,commands):
    require(len(clients)==len(frozen)==2 and len({r['pid'] for r in clients})==2,'two independent Custom clients/rounds required')
    created=[e for e in events if e['event']=='match_created'];completed=[e for e in events if e['event']=='match_completed']
    require(len(created)==len(completed)==2 and all(e['mode']==1 and e['participants']==2 for e in created) and
            all(e['result']['complete'] for e in completed) and [e['match'] for e in created]==[r['match'] for r in frozen] and
            {e['match'] for e in created}=={e['match'] for e in completed},'expected exactly two completed native Custom matches')
    require(not any(e['event'] in ('match_aborted','worker_failed','worker_start_failed','custom_match_setup_error','public_match_offered','public_queue_entered') for e in events),
            'Custom used a public/failure path')
    lobbies=[e for e in events if e['event']=='custom_lobby_created'];invites=[e for e in events if e['event']=='custom_invite_created']
    accepted=[e for e in events if e['event']=='custom_invite_resolved' and e['status']==c.ACCEPTED]
    require(len(lobbies)==len(invites)==len(accepted)==1 and lobbies[0]['host']==invites[0]['sender']==clients[0]['player'] and
            invites[0]['target']==clients[1]['player'] and invites[0]['lobby']==lobbies[0]['lobby'],
            'native directory invite did not establish one owned lobby')
    lobby=lobbies[0]['lobby'];ids=[r['match'] for r in frozen]
    require(len(set(ids))==2 and [r['epoch'] for r in frozen]==[1,2] and all(r['lobby']==lobby for r in frozen),
            'Custom rematch changed lobby or reused an epoch/match')
    require(sum(e['event']=='community_joined' for e in events)==2,'Custom rematch reconnected')
    for kind,profiles in ((c.START,[clients[0]['player']]*2),(c.READY,[clients[1]['player']]*2),
                          (c.RETURN,[r['player'] for r in clients]*2),(c.LEAVE,[clients[1]['player'],clients[0]['player']])):
        rows=[r for r in commands if r['kind']==kind]
        require([r['profile'] for r in rows]==profiles if kind==c.LEAVE else sorted(r['profile'] for r in rows)==sorted(profiles),
                'Custom original Start/Ready/Return/Leave command count or ownership differs')
    for index,round_ in enumerate(frozen):
        require(round_['complete_profiles']==sorted(r['player'] for r in clients) and set(round_['cosmetics'])=={'0','1'} and
                all(p['ai_profile_id']==0 for p in round_['roster']),'Custom lost complete human profiles or admitted AI')
        require(all(round_['humans'][str(i)]==dict(profile=r['player'],name=r['name']) for i,r in enumerate(clients)),
                'Custom native seat/name ownership differs')
        for kind,profile in ((c.START,clients[0]['player']),(c.READY,clients[1]['player'])):
            decisions=[r for r in commands if r['kind']==kind and r['profile']==profile and r.get('lobby')==lobby]
            require(len(decisions)==2 and decisions[index]['perf_counter_ns']<created[index]['perf_counter_ns'],
                    'Custom worker created before both original Start/Ready actions')
    proofs=[]
    for client_index,row in enumerate(clients):
        log=row['log'].replace('\r','')
        joined=list(re.finditer(r'Community native custom match joined: lobby=([0-9a-f]{32}) match=([0-9a-f]{32}) epoch=(\d+) seat=(\d+) session=(\d+)',log))
        require(len(joined)==2 and [m[2] for m in joined]==ids and all(m[1]==lobby and int(m[4])==client_index for m in joined) and
                [int(m[3]) for m in joined]==[1,2] and [int(m[5]) for m in joined]==[1,2],'native Custom join/epoch/session ownership differs')
        require(log.count('Client world acquired:')==log.count('owner=remote nativeIdle=1')==2 and
                log.count('Community native match return:')==log.count('Community native lobby restored:')==
                log.count('COMMUNITY MATCH SMOKE native Continue')==log.count('Community duplicate native start settled without wire replay:')==2 and
                'Public search intent:' not in log and 'Public fallback accepted:' not in log and 'owner=local-practice' not in log,
                'Custom world/result/duplicate callback lifecycle differs')
        passed=log.find('COMMUNITY MATCH SMOKE passed:');leave=log.find('COMMUNITY MATCH SMOKE original post-match Leave dispatched:')
        left=log.find('COMMUNITY MATCH SMOKE post-match leave passed:');gate=log.find('NATIVE QUIT owned gate released:');quit_=log.find('NATIVE QUIT owned menu verified:')
        require(0<=passed<leave<left<gate<quit_,'Custom Quit bypassed two returns and original Leave cleanup')
        require(('COMMUNITY MATCH SMOKE host native picker Invite' if client_index==0 else 'COMMUNITY MATCH SMOKE guest native Accept') in log,
                'native Custom directory invite/accept callback missing')
        per_round=[]
        for index,match in enumerate(ids):
            data=row['matches'][match];frames=[e for e in events if e['event']=='frame_queued' and e.get('match')==match]
            require(len(frames)>=600 and [e['frame'] for e in frames]==list(range(len(frames))),'Custom authoritative frame journal incomplete')
            hashes={e['frame']:e['frame_payload_sha256'] for e in frames};receipt=data['receipts']
            require([int(r['frame']) for r in receipt]==list(range(len(frames))) and
                    all(r['pid']==str(row['pid']) and r['match']==match and r['sha256']==hashes[int(r['frame'])] for r in receipt),
                    'Custom native receipt stream differs from authoritative host')
            native={(e['frame'],e['viewer']):e for e in events if e['event']=='native_snapshot' and e.get('match')==match}
            observed={(int(r['frame']),int(r['viewer'])):r for r in data['audit']};common=native.keys()&observed.keys()
            require(len(common)>=20 and all(native[k]['canonical_fnv1a64']==observed[k]['canonical_fnv1a64'].lower() for k in common),
                    'Custom native observable-state agreement missing')
            section=log[joined[index].start():joined[index+1].start() if index+1<len(joined) else len(log)]
            build=re.findall(r'LAN NORMAL BUILD smoke frame(\d+) slot(\d+)[^\n]*queued=1 commandQueueDelta=1',section)
            require(build==[(str(300+100*client_index),str(client_index))],'Custom ordinary native build did not queue once per round')
            released=[e for e in events if e['event']=='worker_released' and e.get('match')==match]
            require(len(released)==1 and released[0]['worker_pid']==created[index]['worker_pid'],'Custom worker failed to release')
            if index==0:require(released[0]['perf_counter_ns']<created[1]['perf_counter_ns'],'Custom rematch began before previous worker release')
            per_round.append(dict(match=match,frames=len(frames),common_state_samples=len(common)))
        proofs.append(dict(pid=row['pid'],rounds=per_round))
    host=clients[0]['log'];before=re.findall(r'Dedicated deck smoke rematch-before units=\[([\d,]+)\]',host)
    after=re.findall(r'Dedicated deck smoke rematch-after units=\[([\d,]+)\]',host)
    require(len(before)==len(after)==1 and [int(v) for v in before[0].split(',')]==frozen[0]['decks']['0'] and
            [int(v) for v in after[0].split(',')]==frozen[1]['decks']['0'] and before!=after and
            frozen[0]['decks']['1']==frozen[1]['decks']['1'] and 'Dedicated deck smoke rematch-after' not in clients[1]['log'],
            'Custom rematch did not preserve changed host/stable guest native choices')
    require(all(clients[0]['replays'][m]['sha256']==clients[1]['replays'][m]['sha256'] for m in ids),'Custom replay recordings disagree across clients')
    return dict(lobby=lobby,matches=ids,epochs=[1,2],worker_pids=[e['worker_pid'] for e in created],clients=proofs,native_leave_order=['guest','host'],independent_full_state_proof=False)
