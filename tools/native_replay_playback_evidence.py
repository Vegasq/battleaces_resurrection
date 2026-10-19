"""Bounded original replay-batch evidence; no pixel or determinism claim."""
import json
import re


def validate(native, unity, *, selected, profile, replay, game_exit, driver_exit):
    native=native.replace('\r\n','\n').replace('\r','\n')
    unity=unity.replace('\r\n','\n').replace('\r','\n')
    if game_exit!=0 or driver_exit!=0:
        raise AssertionError('original replay batch/production launcher did not exit0')
    # Check the entire retained run, including disposal after Completed replay.
    failures=('Native replay startup refused:','Native replay observation failed:',
              'Local menu initialization failed:','Offline loop stopped in ',
              'Desync detected on frame:','NullReferenceException','ArgumentOutOfRangeException',
              'IndexOutOfRangeException','InvalidDataException','IOException','InvalidOperationException',
              'AccessViolationException','UnauthorizedAccessException','FileNotFoundException',
              'EndOfStreamException','StackOverflowException','OutOfMemoryException',
              'ExecutionEngineException','NotSupportedException','Failed to load replay',
              'Could not load replay','Crash!!!')
    combined=native+'\n'+unity
    if any(value.casefold() in combined.casefold() for value in failures) or re.search(r'(?m)^(?:[A-Za-z_][\w]*\.)*[A-Za-z_][\w]*Exception\s*:',combined):
        raise AssertionError('native replay batch reported an error or desync')
    armed=(f'NATIVE REPLAY playback armed: profile={profile} selected={json.dumps(selected,ensure_ascii=False,separators=(",",":"))} '
           'persistentUnchanged=1 frameStart=-1 frameEnd=-1 capture=0 helperTick=0 BA_RESURRECTION_NATIVE_REPLAY_PLAYBACK_V1')
    if native.count(armed)!=1 or native.count('NATIVE REPLAY playback armed:')!=1:
        raise AssertionError('owned full-range noncapture replay arming missing')
    entered='NATIVE REPLAY playback entered: originalFsmContext=1 existingState=1 helperContextWrites=0'
    if native.count(entered)!=1 or native.index(armed)>=native.index(entered):
        raise AssertionError('original FSM did not enter the existing replay state')
    # Unity may append stack traces after each message; match full message lines.
    loads=re.findall(r'^Load replay: (.+)$',unity,re.M)
    completed=re.findall(r'^Completed replay: (.+)$',unity,re.M)
    if loads!=[selected] or completed!=[selected] or unity.index('Load replay: ')>=unity.index('Completed replay: '):
        raise AssertionError('original selected-file load/completion pair missing or ambiguous')
    metadata=list(re.finditer(r'NATIVE REPLAY playback data: frames=(\d+) last=(\d+) gameDataSha256=([0-9a-f]{64}) originalSerialization=1',native))
    if len(metadata)!=1:raise AssertionError('original loaded replay metadata missing or repeated')
    count,last,digest=metadata[0].groups();count,last=int(count),int(last)
    if not (0<count<=65536 and last==count-1 and count==replay['input_action_messages'] and digest==replay['game_data_sha256']):
        raise AssertionError('original loaded replay disagrees with recorded file')
    if native.index(entered)>=metadata[0].start():raise AssertionError('replay metadata preceded native state entry')
    rows=[]
    for row in re.finditer(r'NATIVE REPLAY playback progress: sim=(-?\d+) presented=(-?\d+) world=(\d+) speed=([0-9.]+) frames=(\d+) last=(-?\d+) observerOnly=1',native):
        sim,presented,world,speed,frames,end=row.groups()
        values=dict(sim=int(sim),presented=int(presented),world=int(world),speed=float(speed))
        if not (row.start()>metadata[0].start() and values['world']>0 and -1<=values['presented']<=last and
                values['sim']>=values['presented'] and int(frames)==count and int(end)==last):
            raise AssertionError('replay progress identity/range invalid')
        rows.append(values)
    if len(rows)<2 or len(rows)>512 or len({r['world'] for r in rows})!=1:
        raise AssertionError('replay lacks one stable advancing native world')
    if any(a['sim']>b['sim'] or a['presented']>=b['presented'] for a,b in zip(rows,rows[1:])):
        raise AssertionError('replay simulation/presentation did not advance monotonically')
    if rows[-1]['sim']<=max(0,rows[0]['sim']) or rows[-1]['presented']<=max(0,rows[0]['presented']) or not any(r['speed']==16 for r in rows):
        raise AssertionError('original full-range replay did not advance at native batch speed')
    return dict(native_playback=True,original_batch_completed=True,frames=count,last_frame=last,
                game_data_sha256=digest,world=rows[0]['world'],progress_samples=rows,
                no_reported_desync=True,independent_determinism=False,rendered_pixels_verified=False,
                helper_ticks=0,original_batch_exit_code=game_exit)
