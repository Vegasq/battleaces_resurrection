"""Original native Custom invite/rematch/Leave/Quit evidence for bundled clients."""
import re
import zlib

from server import community_protocol as c
from server.protobuf_wire import parse_fields,get_uint
from tools.packaged_network_evidence import require
from tools.verify_native_storage import replay_evidence


def replays(files,frozen,counts,*,expected_rounds=2):
    require(expected_rounds in (2,21),'unsupported Custom round count')
    require(len(files)==len(frozen)==expected_rounds,'Custom needs two completed native recordings')
    expected={r['game_data_sha256']:r['match'] for r in frozen};result={}
    require(len(expected)==expected_rounds,'Custom rounds reused native GameData identity')
    for raw in files:
        proof=replay_evidence(raw);match=expected.get(proof['game_data_sha256'])
        require(match is not None and match not in result and proof['input_action_messages']==counts[match],
                'Custom native replay identity/frame count differs')
        fields=parse_fields(zlib.decompress(raw,-15),max_bytes=16*1024*1024,max_fields=16384)
        actions=[f.value for f in fields if f.number==2]
        require([get_uint(a,1) for a in actions]==list(range(counts[match])),'Custom replay frame sequence differs')
        result[match]=proof
    return result


def expected_epochs(rounds,ready_expiry=False):
    require(rounds in (2,21) and (not ready_expiry or rounds==2),'unsupported Custom recovery round count')
    return [3,4] if ready_expiry else list(range(1,rounds+1))


def validate_ready_expiry(proof,clients,commands,lobby):
    require(proof['lobby']==lobby and proof['profile']==clients[1]['player'] and proof['old_epoch']==1 and
            proof['configured_timeout']==10 and proof['held_at']<proof['deadline']<=proof['released_at']<=proof['rejected_at'] and
            proof['rejected_at']-proof['held_at']<20 and proof['rejection']=='start attempt changed',
            'Ready expiry did not use the original deadline and rejection')
    before=proof['before']
    require(before==proof['after'] and before['lobby']==lobby and before['epoch']==3 and before['phase']==c.STARTING and
            before['ready']==[clients[0]['player']] and set(before['members'])=={r['player'] for r in clients} and
            before['room'] is None and before['rooms']==before['matches']==0,
            'old Ready damaged the new start or launched a premature match')
    ready=[r for r in commands if r['kind']==c.READY]
    require([r['epoch'] for r in ready]==[1,3,4] and ready[0]['request']==proof['request'] and
            len({r['request'] for r in ready})==3,'Ready epochs/request identity differ')
    def tick(log,pattern,count=1):
        values=re.findall(r'^\[(\d+)\] '+pattern,log.replace('\r',''),re.M)
        require(len(values)==count and [int(v) for v in values]==sorted(int(v) for v in values),
                'missing or unexpected duplicate native Ready lifecycle event')
        return int(values[0])
    host,guest=(r['log'] for r in clients)
    times=[tick(host,r'Community start transaction dispatched: nativeKind=15 wireKind=48 request=\d+ epoch=3 cancel=0'),
           tick(guest,r'Community native start completed: kind=16 epoch=1 success=0 oldPendingReleased=1'),
           tick(guest,r'Community start transaction dispatched: nativeKind=16 wireKind=49 request=\d+ epoch=3 cancel=0'),
           tick(guest,r'Community native start completed: kind=16 epoch=3 success=1 oldPendingReleased=1',count=2)]
    require(times[0]<times[1]<=times[2]<=times[3] and
            host.count('rejected/timed-out Start rolled back to full native lobby; retry deferred')==1,
            'new host start must precede old guest completion and usable new Ready')
    for row in clients:
        log=row['log'].replace('\r','')
        errors=re.findall(r'Match loading event=error source=custom ticket=\d+ identity=custom:'+lobby+r':1 [^\n]*pending=0 visible=1 nativeVisible=1 rendererFailed=0 reason=Match start was cancelled\. Please try again\.',log)
        require(len(errors)==1,'expired start did not expose its original loading error')
        previous=log.index(errors[0])
        for epoch in (3,4):
            cleared=re.findall(r'Match loading event=ready source=custom ticket=\d+ identity=custom:'+lobby+':'+str(epoch)+r' [^\n]*pending=0 visible=0 nativeVisible=0 rendererFailed=0',log)
            require(len(cleared)==1 and log.index(cleared[0])>previous,'recovered load did not clear its loading notice')
            previous=log.index(cleared[0])
    return dict(server=proof,native_ticks=dict(host_retry=times[0],old_ready_released=times[1],new_ready=times[2],new_ready_accepted=times[3]),
                expected_duplicate_success_callbacks=2,loading_error_and_recovery_both_clients=True)


def validate_start_rejection(proof,clients,commands,frozen,lobby):
    require(proof['lobby']==lobby and proof['profile']==clients[0]['player'] and
            proof['epoch']==0 and proof['phase']==c.OPEN and proof['rooms']==proof['matches']==0 and
            proof['reason']=='qualification: host start rejected','Start rejection was not before commitment')
    starts=[r for r in commands if r['kind']==c.START]
    require(len(starts)==3 and starts[0]['request']==proof['request'] and len({r['request'] for r in starts})==3,
            'Start rejection/retry request correlation missing')
    def appearance(value):
        slots=value['slots'];pairs=slots.items() if isinstance(slots,dict) else slots
        pairs=list(pairs)
        require(len(pairs)==17 and {int(k) for k,v in pairs}==set(range(1,18)),'complete pre-rejection selection missing')
        return value['catalog_sha256'],sorted((int(k),v) for k,v in pairs)
    require(set(proof['selections'])=={r['player'] for r in clients},'pre-rejection human selections missing')
    for index,row in enumerate(clients):
        selected=proof['selections'][row['player']]
        require(selected['full'] is True and selected['deck']==frozen[0]['decks'][str(index)] and
                appearance(selected['cosmetics'])==appearance(frozen[0]['cosmetics'][str(index)]),
                'Start rejection/retry changed the frozen human loadout')
    host=clients[0]['log'].replace('\r','')
    def event(pattern):
        matches=list(re.finditer(pattern,host,re.M));require(len(matches)==1,'Start rejection native callback evidence differs')
        return matches[0]
    rejected=event(r'Community native start completed: kind=15 epoch=1 success=0 oldPendingReleased=1')
    retry=event(r'Community start transaction dispatched: nativeKind=15 wireKind=48 request='+str(starts[1]['request'])+r' epoch=1 cancel=0')
    accepted=event(r'Community native start completed: kind=15 epoch=1 success=1 oldPendingReleased=1')
    error=event(r'Match loading event=error source=custom ticket=(\d+) identity=custom:'+lobby+r':1 [^\n]*pending=0 visible=1 nativeVisible=1 rendererFailed=0 reason=The server could not start this match\. Please try again\.')
    ready=event(r'Match loading event=ready source=custom ticket=(\d+) identity=custom:'+lobby+r':1 [^\n]*pending=0 visible=0 nativeVisible=0 rendererFailed=0')
    require(error.start()<rejected.start()<retry.start()<accepted.start()<ready.start() and error[1]!=ready[1] and
            host.count('rejected/timed-out Start rolled back to full native lobby; retry deferred')==1,
            'rejected Start did not release its old loading ticket before usable native retry')
    require('Match loading event=error' not in clients[1]['log'],'host rejection incorrectly failed the guest')
    return dict(server=proof,old_loading_ticket=int(error[1]),recovered_loading_ticket=int(ready[1]),
                original_negative_callback_released=True,pre_rejection_loadouts_preserved=True)


def validate(events,clients,*,frozen,commands,expected_rounds=2,ready_expiry=None,start_rejection=None):
    require(expected_rounds in (2,21),'unsupported Custom round count')
    require(ready_expiry is None or expected_rounds==2,'expiry requires exactly two recovered rounds')
    require(start_rejection is None or expected_rounds==2 and ready_expiry is None,'Start rejection requires its separate two-round case')
    epochs=expected_epochs(expected_rounds,ready_expiry is not None)
    attempts=expected_rounds+(ready_expiry is not None)
    require(len(clients)==2 and len(frozen)==expected_rounds and len({r['pid'] for r in clients})==2,'two independent Custom clients/rounds required')
    created=[e for e in events if e['event']=='match_created'];completed=[e for e in events if e['event']=='match_completed']
    require(len(created)==len(completed)==expected_rounds and all(e['mode']==1 and e['participants']==2 for e in created) and
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
    require(len(set(ids))==expected_rounds and [r['epoch'] for r in frozen]==epochs and all(r['lobby']==lobby for r in frozen),
            'Custom rematch changed lobby or reused an epoch/match')
    require(sum(e['event']=='community_joined' for e in events)==2,'Custom rematch reconnected')
    for kind,profiles in ((c.START,[clients[0]['player']]*(attempts+(start_rejection is not None))),(c.READY,[clients[1]['player']]*attempts),
                          (c.RETURN,[r['player'] for r in clients]*expected_rounds),(c.LEAVE,[clients[1]['player'],clients[0]['player']])):
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
            if ready_expiry is not None or start_rejection is not None and kind==c.START:decisions=decisions[1:]
            require(len(decisions)==expected_rounds and decisions[index]['perf_counter_ns']<created[index]['perf_counter_ns'],
                    'Custom worker created before both original Start/Ready actions')
    proofs=[]
    for client_index,row in enumerate(clients):
        log=row['log'].replace('\r','')
        joined=list(re.finditer(r'Community native custom match joined: lobby=([0-9a-f]{32}) match=([0-9a-f]{32}) epoch=(\d+) seat=(\d+) session=(\d+)',log))
        require(len(joined)==expected_rounds and [m[2] for m in joined]==ids and all(m[1]==lobby and int(m[4])==client_index for m in joined) and
                [int(m[3]) for m in joined]==epochs and [int(m[5]) for m in joined]==list(range(1,expected_rounds+1)),'native Custom join/epoch/session ownership differs')
        require(log.count('Client world acquired:')==log.count('owner=remote nativeIdle=1')==expected_rounds and
                log.count('Community native match return:')==log.count('Community native lobby restored:')==
                log.count('COMMUNITY MATCH SMOKE native Continue')==expected_rounds and
                log.count('Community duplicate native start settled without wire replay:')==(0 if start_rejection is not None else expected_rounds+int(ready_expiry is not None and client_index==0)) and
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
            if index+1<expected_rounds:require(released[0]['perf_counter_ns']<created[index+1]['perf_counter_ns'],'Custom rematch began before previous worker release')
            per_round.append(dict(match=match,frames=len(frames),common_state_samples=len(common)))
        proofs.append(dict(pid=row['pid'],rounds=per_round))
    host=clients[0]['log'];before=re.findall(r'Dedicated deck smoke rematch-before units=\[([\d,]+)\]',host)
    after=re.findall(r'Dedicated deck smoke rematch-after units=\[([\d,]+)\]',host)
    require(len(before)==len(after)==expected_rounds-1 and 'Dedicated deck smoke rematch-after' not in clients[1]['log'],
            'Custom native deck edit count differs')
    for index,(old,new) in enumerate(zip(before,after)):
        require([int(v) for v in old.split(',')]==frozen[index]['decks']['0'] and
                [int(v) for v in new.split(',')]==frozen[index+1]['decks']['0'] and old!=new and
                frozen[index]['decks']['1']==frozen[index+1]['decks']['1'],
                'Custom rematch did not preserve changed host/stable guest native choices')
    require(all(clients[0]['replays'][m]['sha256']==clients[1]['replays'][m]['sha256'] for m in ids),'Custom replay recordings disagree across clients')
    result=dict(lobby=lobby,matches=ids,epochs=epochs,worker_pids=[e['worker_pid'] for e in created],clients=proofs,native_leave_order=['guest','host'],independent_full_state_proof=False)
    if ready_expiry is not None:result['ready_expiry']=validate_ready_expiry(ready_expiry,clients,commands,lobby)
    if start_rejection is not None:result['start_rejection']=validate_start_rejection(start_rejection,clients,commands,frozen,lobby)
    return result
