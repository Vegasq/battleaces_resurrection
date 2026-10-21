"""Require completed native matches on both sides of a lost final RETURN ACK."""
import re


def require(value,message):
    if not value:raise AssertionError(message)


def validate(log,mode,matches,events):
    log=log.replace('\r\n','\n').replace('\r','\n')
    require(mode in (1,2,5) and len(matches)==2,'two completed public matches required')
    ids=[row['match'] for row in matches]
    require(len(set(ids))==2 and all(re.fullmatch('[0-9a-f]{32}',key) for key in ids),
            'distinct owned match identities required')
    require([row['ticket'] for row in matches]==[1,2] and
            all(row['result']['complete'] and row['received_frames']>=600 for row in matches),
            'both queued matches must finish with authoritative receipts')
    require(not any(value in log for value in ('identity=public-error:','owner=local-practice',
            'Public fallback accepted:','Public client failure:','Client lifecycle invariant failed:',
            'Public result Continue routing failed:')),'completed-match ACK loss produced an error or fallback')

    def one(pattern):
        found=list(re.finditer(r'^\[(\d+)\] '+pattern+'$',log,re.M))
        require(len(found)==1,'missing/duplicate native RETURN retry evidence: '+pattern)
        return found[0]

    continue_rows=list(re.finditer(r'^\[(\d+)\] Public result Continue routed: mode='+str(mode)+
        r' source=remote next=End rewards=0 progressionUnchanged=1 publicModePreserved=1$',log,re.M))
    require(len(continue_rows)==2 and log.count('Public result Continue routed:')==2,
            'both original native Continue actions required')
    sequence=[]
    count=2 if mode==1 else 4
    for ticket,key in enumerate(ids,1):
        sequence.extend([
            one(rf'Public search intent: ticket={ticket} mode={mode} originalSearch=1 deadlineMs=30000 BA_RESURRECTION_PUBLIC_QUEUE_V1'),
            one(rf'Client world acquired: generation={ticket} owner=remote match={key}'),
            one(rf'Public native match joined: ticket={ticket} match={key} mode={mode} participants={count} seat=0 remoteWorld=1'),
            continue_rows[ticket-1],
            one(rf'Client world released: generation={ticket} owner=remote nativeIdle=1'),
            one(rf'Public native return: ticket={ticket} match={key} aborted=0 nativeIdle=1'),
        ])
        if ticket==1:
            sequence.append(one(r'Public intent retired: ticket=1 reason=connection lost after return nativeIdle=1 disconnect=1'))
        else:
            sequence.extend([
                one(rf'PUBLIC QUEUE completed return: match={key} completed=1 seatReleased=1'),
                one(r'Public intent retired: ticket=2 reason=returned nativeIdle=1 disconnect=0'),
            ])
    offsets=[row.start() for row in sequence]
    require(offsets==sorted(set(offsets)),'next Play/world preceded first completed idle retirement')
    require(log.count('Public search intent:')==log.count('Client world acquired:')==
            log.count('Client world released:')==log.count('Public native match joined:')==
            log.count('Public native return:')==2,'duplicate or missing native match lifecycle')
    require(log.count('PUBLIC QUEUE completed return:')==1 and
            not re.search(r'Public ACK: ticket=1 kind=61 request=\d+ success=1 ',log),
            'first final RETURN acknowledgement was not lost')

    def rows(event):return [(index,row) for index,row in enumerate(events) if row['event']==event]
    completed=rows('match_completed');requests=rows('probe_return_request');dropped=rows('probe_drop_return_ack')
    require([row['match'] for _,row in completed]==ids and
            [row['result'] for _,row in completed]==[row['result'] for row in matches],
            'server completed different matches or results')
    require(len(requests)==2 and [(row['ticket'],row['match']) for _,row in requests]==list(enumerate(ids,1)),
            'both exact owned RETURN requests required')
    require(len(dropped)==1 and dropped[0][1].get('success') is True and dropped[0][1]['request']==requests[0][1]['request'] and
            completed[0][0]<requests[0][0]<dropped[0][0]<requests[1][0] and completed[1][0]<requests[1][0],
            'lost ACK must follow first completion/RETURN and precede second RETURN')
    retired=rows('public_ticket_retired')
    require([(row['ticket'],row['reason']) for _,row in retired]==[(1,'returned to menu'),(2,'returned to menu')] and
            requests[0][0]<retired[0][0]<dropped[0][0] and requests[1][0]<retired[1][0],
            'both completed server RETURN requests must be accepted before retirement')
    require([row['ticket'] for _,row in rows('public_queue_entered')]==[1,2] and
            [(row['tickets'],row['match']) for _,row in rows('public_match_offered')]==[([1],ids[0]),([2],ids[1])],
            'retry did not preserve two distinct authoritative searches')
    require([row['match'] for _,row in rows('match_created')]==ids and
            [row['match'] for _,row in rows('worker_started')]==ids and not rows('match_aborted'),
            'unexpected worker/world or aborted finished match')
    return dict(matches=ids,completed_matches=2,original_continue_actions=2,quiet_first_retirement=True,
                second_play_after_idle_retirement=True,remote_worlds=2,
                received_frames=[row['received_frames'] for row in matches],dropped_request=requests[0][1]['request'])
