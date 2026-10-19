"""Native public-match evidence for a bundled host and independently launched clients."""
import re


def require(value,message):
    if not value:raise AssertionError(message)


def native_queue_timing(log,*,full):
    starts=re.findall(r'\[(\d+)\] Native search began: ticket=1 ',log)
    offers=re.findall(r'\[(\d+)\] Public authoritative state: ticket=1 phase=1 [^\n]*elapsedMs=(\d+)',log)
    require(len(starts)==1 and offers,'native search/offer clock witnesses missing')
    elapsed=int(offers[0][0])-int(starts[0]);server_elapsed=int(offers[0][1])
    require(0<=elapsed<5000 if full else 29900<=elapsed<=35000 and server_elapsed>=30000,
            'native original search did not retain its complete public wait budget')
    return dict(native_offer_elapsed_ms=elapsed,authoritative_offer_elapsed_ms=server_elapsed)


def validate(events,clients,*,mode):
    from server.public_protocol import MODES
    total,slots=MODES[mode];humans=slots[:len(clients)]
    offers=[e for e in events if e['event']=='public_match_offered']
    matches=[e for e in events if e['event']=='match_created']
    completed=[e for e in events if e['event']=='match_completed']
    entered=[e for e in events if e['event']=='public_queue_entered']
    require(len(offers)==len(matches)==len(completed)==1 and len(entered)==len(clients),'expected one bundled multiplayer match')
    require(not any(e['event'] in ('match_aborted','worker_start_failed','worker_failed') for e in events),'bundled host reported a match failure')
    match=matches[0]['match'];offer=offers[0]
    require(match==offer['match']==completed[0]['match'] and matches[0]['mode']==mode and matches[0]['participants']==total,'bundled match identity/topology differs')
    require(set(offer['humans'])=={row['player'] for row in clients},'bundled identities split across offers')
    full=len(clients)==len(slots)
    waits=[(offer['perf_counter_ns']-row['perf_counter_ns'])/1e9 for row in entered]
    require(offer['fallback']==(not full) and (0<=max(waits)<5 if full else 29<=max(waits)<=33),'real public queue deadline policy differs')
    frames={e['frame']:e['frame_payload_sha256'] for e in events if e['event']=='frame_queued' and e.get('match')==match}
    require(len(frames)>=600 and sorted(frames)==list(range(len(frames))),'authoritative frame journal incomplete')
    started=[e for e in events if e['event']=='worker_started' and e.get('match')==match]
    released=[e for e in events if e['event']=='worker_released' and e.get('match')==match]
    require(len(started)==len(released)==1 and started[0]['worker_pid']==released[0]['worker_pid'],'match worker did not release normally')
    native_states={(e['frame'],e['viewer']):e for e in events if e['event']=='native_snapshot' and e.get('match')==match}
    assignments=[];comparisons=[]
    for row in clients:
        log=row['log'].replace('\r','')
        assignments_=re.findall(r'Public match assignment: ticket=1 match=([0-9a-f]{32}) mode=(\d+) count=(\d+) seat=(\d+) humans=(\d+) ',log)
        require(len(assignments_)==1,'native public assignment missing/duplicated')
        key,actual_mode,count,seat,mask=assignments_[0];seat=int(seat);assignments.append(seat)
        require(key==match and int(actual_mode)==mode and int(count)==total and seat in humans and int(mask)==sum(1<<s for s in humans),'native assigned topology differs')
        require(log.count('Public native match joined:')==log.count('PUBLIC QUEUE completed return:')==1 and
                'Public fallback accepted:' not in log and 'owner=local-practice' not in log,'native match bypassed remote ownership')
        require(f'Public native return: ticket=1 match={match} aborted=0 nativeIdle=1' in log and
                log.count('Client world acquired:')==log.count('owner=remote nativeIdle=1')==1,'native world was not returned exactly once')
        build=re.findall(r'LAN NORMAL BUILD smoke frame(\d+) slot(\d+)[^\n]*queued=1 commandQueueDelta=1',log)
        require(len(build)==1 and int(build[0][1])==seat and int(build[0][0])==300+100*seat,'ordinary native build did not queue')
        receipt=row['receipts'];require([int(r['frame']) for r in receipt]==list(range(len(frames))),'native receipt journal incomplete/out of order')
        require(all(r['pid']==str(row['pid']) and r['match']==match and r['sha256']==frames[int(r['frame'])] for r in receipt),'native frames differ from authoritative host')
        sample={(int(r['frame']),int(r['viewer'])):r for r in row['audit']};common=sorted(native_states.keys()&sample.keys())
        require(len(common)>=20,'insufficient common native/client observable-state samples')
        for key in common:
            actual=sample[key];expected=native_states[key]
            require(actual['canonical_fnv1a64'].lower()==expected['canonical_fnv1a64'],'native observable state disagrees with host')
        seconds=[int(value) for ticket,value in re.findall(r'Native search timer: ticket=(\d+) seconds=(\d+)',log) if ticket=='1']
        require(seconds and seconds[0]==0 and seconds==sorted(seconds) and (full or max(seconds)>=25),'native queue timer differs')
        end=log.index('PUBLIC QUEUE completed return:');gate=log.find('NATIVE QUIT owned gate released:')
        quit_=log.find('NATIVE QUIT owned menu verified:')
        require(end<gate<quit_,'native Quit bypassed completed match/idle gate')
        timing=native_queue_timing(log,full=full)
        comparisons.append(dict(seat=seat,name=row['name'],received_frames=len(receipt),common_state_samples=len(common),native_search_seconds=seconds,**timing))
    require(sorted(assignments)==sorted(humans),'duplicate/missing native human seat')
    require(len({tuple(deck) for seat,deck in matches[0]['decks'].items() if int(seat) in humans})==len(clients),'independent native human deck selection was lost')
    return dict(match=match,mode=mode,human_seats=list(humans),bot_seats=sorted(set(range(total))-set(humans)),
                full_human_group=full,real_queue_waits_seconds=waits,frames=len(frames),clients=comparisons,
                result=completed[0]['result'],worker_pid=started[0]['worker_pid'],independent_full_state_proof=False)
