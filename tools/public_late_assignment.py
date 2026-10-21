"""Owned stale-response delivery and native remote/local/remote evidence."""
import asyncio
import hashlib
import json
import re

from client_patch.transport import bridge
from server import protocol as p, public_protocol as q, loadout_protocol as loadout


def require(value,message):
    if not value:raise AssertionError(message)


def normalized(log):return log.replace('\r\n','\n').replace('\r','\n')
def sha(data):return hashlib.sha256(data).hexdigest()


def preference(path):
    with path.open('rb') as stream:raw=stream.read(257)
    values={b'schema=1\ndifficulty=easy\n':17,b'schema=1\ndifficulty=normal\n':18,b'schema=1\ndifficulty=hard\n':19}
    key=raw.replace(b'\r',b'')
    require(len(raw)<256 and key in values,'late transition requires a valid saved practice preference')
    return dict(profile=values[key],bytes=len(raw),sha256=sha(raw))


class WitnessBridge(bridge.Bridge):
    """Serialize witness records in the same order as the inherited TCP writes."""
    def __init__(self,*args,observe,**kwargs):
        super().__init__(*args,**kwargs)
        self.observe=observe;self.witness_lock=asyncio.Lock();self.sequence=0

    async def send(self,kind,identity,data=b'',*,probe_injection=False):
        async with self.witness_lock:
            wire=bridge.encode(kind,identity,data,version=self.version)
            await super().send(kind,identity,data)
            self.sequence+=1
            if kind!=bridge.DATA or probe_injection:
                self.observe('probe_private_written',sequence=self.sequence,kind=kind,private_session=identity,
                    purpose='late-assignment' if probe_injection else 'control',payload_bytes=len(data),
                    payload_sha256=sha(data),wire_sha256=sha(wire))
            return self.sequence


class Probe:
    def __init__(self,mode,output,observe):
        self.mode=mode;self.output=output;self.observe=observe;self.transport=None
        self.packet=None;self.capture=None;self.injection=None;self.peer=None

    def attach_peer(self,peer):
        if self.peer is not None:
            require(self.peer is peer,'first assignment peer changed');return
        self.peer=peer;send=peer.send
        def observed_send(kind,payload=b''):
            self.capture_assignment(kind,payload)
            return send(kind,payload)
        peer.send=observed_send

    def capture_assignment(self,kind,payload):
        if kind!=loadout.MATCH_LOADOUT or self.packet is not None:return
        value=q.decode_assignment(payload,complete=True)
        require(value['generation']==1 and value['mode']==self.mode and value['slot']==0 and value['human_mask']==1,
                'late response must be the first real owned assignment')
        require(self.transport is not None and self.transport.last_session==1,'first private transport session required')
        self.packet=p.encode(kind,payload)
        require(len(self.packet)<=bridge.CHUNK,'captured assignment exceeds one private chunk')
        self.capture=dict(kind=kind,private_session=1,ticket=1,mode=self.mode,match=value['match'],
                          deck=list(value['deck']),payload_bytes=len(self.packet),payload_sha256=sha(self.packet))
        with (self.output/'captured-assignment.bin').open('xb') as stream:stream.write(self.packet)
        self.observe('probe_assignment_captured',**self.capture)

    async def maybe_inject(self,log):
        if self.injection is not None:return
        log=normalized(log)
        require('Practice returned: completed=1' not in log,'local fallback returned before stale-response injection')
        require('Public search intent: ticket=3 ' not in log,'third intent started before local-world stale delivery')
        cadence=list(re.finditer(r'^\[(\d+)\] Practice AI cadence: sim=(\d+) ',log,re.M))
        if not cadence or int(cadence[-1][2])<100:return
        require(self.packet is not None and self.capture is not None,'no original owned assignment was captured')
        require('Client world acquired: generation=2 owner=local-practice match=' in log and
                'Practice world ready:' in log and f'Local AI all ready: bots={1 if self.mode==1 else 3} ' in log,
                'stale response delivery requires a running owned fallback world')
        require(self.transport.last_session==2,'local fallback must retire the failed second remote intent')
        sequence=await self.transport.send(bridge.DATA,self.capture['private_session'],self.packet,probe_injection=True)
        self.injection=dict(sequence=sequence,native_frame=int(cadence[-1][2]),native_tick=int(cadence[-1][1]),
                            native_log_characters=len(log),old_private_session=1,payload_sha256=sha(self.packet))
        self.observe('probe_late_assignment_injected',**self.injection)


def validate(log,mode,matches,events,capture,injection,practice_profile=19):
    """Prove active local play survives replay,then an ordered fresh TLS session drains it."""
    log=normalized(log)
    require(isinstance(capture,dict) and isinstance(injection,dict),'a real assignment capture and active-local delivery are required')
    require(mode in (1,2,5) and len(matches)==2 and [row['ticket'] for row in matches]==[1,3],
            'two completed remote matches on tickets1/3 required')
    ids=[row['match'] for row in matches]
    require(len(set(ids))==2 and all(re.fullmatch('[0-9a-f]{32}',key) for key in ids) and capture['ticket']==1 and capture['mode']==mode and capture['match']==ids[0] and
            capture['private_session']==injection['old_private_session']==1 and
            capture['payload_sha256']==injection['payload_sha256'],'replay differs from the original owned response')
    require(all(row['result']['complete'] and row['received_frames']>=600 for row in matches),
            'both remote worlds must complete with authoritative receipts')
    require(not any(text in log for text in ('identity=public-error:','Public client failure:',
            'Client lifecycle invariant failed:','Practice stopped in ','Offline loop stopped in ')),
            'late assignment interrupted the client or fallback world')

    def one(pattern):
        found=list(re.finditer(r'^\[(\d+)\] '+pattern+'$',log,re.M))
        require(len(found)==1,'missing/duplicate late-assignment native evidence: '+pattern)
        return found[0]

    sequence=[];count=2 if mode==1 else 4
    for ticket,generation,key in ((1,1,ids[0]),(3,3,ids[1])):
        sequence.extend([
            one(rf'Public search intent: ticket={ticket} mode={mode} originalSearch=1 deadlineMs=30000 BA_RESURRECTION_PUBLIC_QUEUE_V1'),
            one(rf'Client world acquired: generation={generation} owner=remote match={key}'),
            one(rf'Public native match joined: ticket={ticket} match={key} mode={mode} participants={count} seat=0 remoteWorld=1'),
            one(rf'Client world released: generation={generation} owner=remote nativeIdle=1'),
            one(rf'Public native return: ticket={ticket} match={key} aborted=0 nativeIdle=1'),
            one(rf'Public intent retired: ticket={ticket} reason='+
                ('connection lost after return nativeIdle=1 disconnect=1' if ticket==1 else 'returned nativeIdle=1 disconnect=0')),
        ])
    local=[
        one(rf'Public search intent: ticket=2 mode={mode} originalSearch=1 deadlineMs=30000 BA_RESURRECTION_PUBLIC_QUEUE_V1'),
        one(rf'Public fallback accepted: ticket=2 mode={mode} beforeAmbiguousCommit=1 elapsedMs=\d+ reason=.+'),
        one(r'Client world acquired: generation=2 owner=local-practice match='),
        one(r'Practice world ready: humanWorld=\d+ aiWorld=\d+'),
        one(r'Client world released: generation=2 owner=local-practice nativeIdle=1'),
        one(rf'Practice returned: completed=1 mode={mode} seat=-1 presenceRetained=0 standalone=1'),
    ]
    ordered=sequence[:6]+local+sequence[6:]
    offsets=[row.start() for row in ordered]
    require(offsets==sorted(set(offsets)),'remote/local/remote ownership overlapped or regressed')
    initial_preference=one(rf'PUBLIC LATE ASSIGNMENT SMOKE maxIntents=3 practiceProfile={practice_profile} BA_RESURRECTION_LATE_ASSIGNMENT_V2')
    retained_preference=one(rf'PUBLIC LATE ASSIGNMENT SMOKE preference preserved before intent3: profile={practice_profile}')
    require(initial_preference.start()<sequence[0].start() and local[-1].end()<retained_preference.start()<sequence[6].start() and
            'Practice difficulty selected:' not in log,'configured practice preference changed across the transition')
    require(log.count('Client world acquired:')==log.count('Client world released:')==3 and
            log.count('Public search intent:')==3 and log.count('Public native match joined:')==2 and
            'Public READY sent: ticket=2' not in log and 'Public match assignment: ticket=2' not in log,
            'fallback acquired a remote world or committed READY')
    start=injection['native_log_characters']
    require(local[3].end()<=start<local[4].start() and injection['native_frame']>=100,
            'stale response was not delivered inside the active local world')
    later=[int(value) for value in re.findall(r'Practice AI cadence: sim=(\d+) ',log[start:local[4].start()])]
    require(later and max(later)>injection['native_frame']+100,'local simulation did not progress after stale delivery')
    require(log.count(f'Public result Continue routed: mode={mode} source=remote ')==2 and
            log.count(f'Public result Continue routed: mode={mode} source=local ')==1 and
            log.count('PRACTICE SMOKE native Continue (automated)')==1,'all three original Continue actions required')

    def rows(event):return [row for row in events if row['event']==event]
    captured=rows('probe_assignment_captured')
    require(len(captured)==1 and all(captured[0][key]==value for key,value in capture.items()),
            'capture metadata differs from the original event')
    require(len(rows('probe_late_assignment_injected'))==1 and
            all(rows('probe_late_assignment_injected')[0][key]==value for key,value in injection.items()),
            'injection metadata differs from the delivered event')
    require([row['match'] for row in rows('match_created')]==ids and
            [row['match'] for row in rows('match_completed')]==ids and
            [row['match'] for row in rows('worker_started')]==ids and not rows('match_aborted'),
            'late response created,aborted or replaced a server match')
    require([row['ticket'] for row in rows('public_queue_entered')]==[1,3] and
            [(row['tickets'],row['match']) for row in rows('public_match_offered')]==[([1],ids[0]),([3],ids[1])],
            'local fallback ticket entered the server queue')
    wire=rows('probe_private_written');sent=[row for row in wire if row['purpose']=='late-assignment']
    ready=[row for row in wire if row['kind']==bridge.READY]
    require(len(sent)==1 and sent[0]['sequence']==injection['sequence'] and
            sent[0]['kind']==bridge.DATA and sent[0]['private_session']==1 and
            sent[0]['payload_sha256']==capture['payload_sha256'] and sent[0]['payload_bytes']==capture['payload_bytes'],
            'captured assignment was not written intact into the old private session')
    require([row['private_session'] for row in ready]==[1,3] and
            ready[0]['sequence']<sent[0]['sequence']<ready[1]['sequence'] and
            [row['sequence'] for row in wire]==sorted({row['sequence'] for row in wire}),
            'fresh authenticated READY was not ordered behind the old assignment bytes')
    require([(row['ticket'],row['reason']) for row in rows('public_ticket_retired')]==[(1,'returned to menu'),(3,'returned to menu')],
            'both real remote results must return normally')
    return dict(remote_matches=ids,local_world_generation=2,world_order=['remote','local-practice','remote'],
        old_private_session=1,fresh_private_session=3,replayed_payload_sha256=capture['payload_sha256'],
        injection_native_frame=injection['native_frame'],later_local_frame=max(later),
        ordered_private_stream_barrier=True,local_world_preserved=True,original_continue_actions=3,practice_profile_preserved=practice_profile)


def local_evidence(log,mode,injection,expected_units,cosmetic_keys):
    from tools.verify_practice_ai import movement_evidence
    log=normalized(log)
    local_start=log.index('Public fallback accepted: ticket=2 ')
    end=log.index('Client world released: generation=2 owner=local-practice nativeIdle=1')
    local_log=log[local_start:end]
    armies=[json.loads(line.split('Practice army snapshot: ',1)[1]) for line in local_log.splitlines() if 'Practice army snapshot: ' in line]
    count=2 if mode==1 else 4
    require(len(armies)==count and [row.get('armyId',0) for row in armies]==list(range(count)) and
            [row.get('allianceId',0) for row in armies]==[seat%2 for seat in range(count)],'local fallback roster changed')
    human=armies[0]
    frozen=[json.loads(line.split('HUMAN COSMETICS frozen message: ',1)[1]) for line in local_log.splitlines()
            if 'HUMAN COSMETICS frozen message: ' in line]
    require(len(frozen)==2 and human['deck']==frozen[0]['deck']==frozen[1]['deck'] and
            human['deck']['units']==expected_units and
            human['deck']['entitlements']==[dict(cosmeticAssetKeys=cosmetic_keys)] and
            'HUMAN COSMETICS SimPlayer passed:' in log,'local human selected deck/full appearance changed')
    identity=human['players'][0]
    require(identity.get('aiProfileId',0)==0 and identity['playerHandleWithName']['playerName']=='Public Config Player',
            'local fallback human identity changed')
    after=log[injection['native_log_characters']:end]
    bots=[]
    for seat,army in enumerate(armies[1:],1):
        moved,ordered=movement_evidence(after,set(army['deck']['units']),seat)
        require(moved & ordered,'local bot did not produce,order and move units after stale delivery: '+str(seat))
        require(log.count(f'Practice native JoinArmy validated: army={seat} ')==1 and
                any('Public AI identity binding: phase=result ' in line and line.endswith(f'army={seat}') for line in log.splitlines()),
                'local bot original join/result identity missing')
        bots.append(dict(seat=seat,profile=army['players'][0]['aiProfileId'],ordered_moving_units=sorted(moved & ordered)))
    return dict(human_deck=human['deck'],bots_after_injection=bots,full_human_appearance=True)
