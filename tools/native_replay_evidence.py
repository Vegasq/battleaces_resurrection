"""Validate original-codec readback separately from native replay playback."""
import re


def validate(log,replay):
    log=log.replace('\r\n','\n').replace('\r','\n')
    if any(marker in log for marker in ('NATIVE REPLAY codec readback failed:','NATIVE REPLAY decoder managed exception:')):
        raise AssertionError('native replay codec reported a failure')
    pattern=(r'NATIVE REPLAY codec readback passed: frames=(\d+) first=0 last=(\d+) initialActions=(\d+) '
             r'playerBatches=(\d+) build=37822 streamsDisposed=3 fileIdentityPinned=1 canonicalPathCharacters=(\d+) '
             r'sizeLimit=16777216 recursionLimit=64 playbackCalls=0 BA_RESURRECTION_NATIVE_REPLAY_READER_V1')
    matches=list(re.finditer(pattern,log))
    if len(matches)!=1:raise AssertionError('expected exactly one native replay codec readback')
    row=matches[0];frames,last,initial,players,length=map(int,row.groups())
    if not (0<frames<=65536 and last==frames-1 and initial>0 and 0<players<=frames and
            frames==replay['input_action_messages'] and length==replay['canonical_path_characters']):
        raise AssertionError('native replay content/path disagrees with independent file readback')
    returned=log.find('Practice returned: completed=1 ');idle=log.find('NATIVE QUIT owned menu verified:')
    if not 0<=returned<row.start()<idle:raise AssertionError('native replay decode was not between return and idle Quit validation')
    return dict(original_codec=True,frames=frames,first_frame=0,last_frame=last,initial_actions=initial,
                frames_with_player_batches=players,build='37822',streams_disposed=3,file_identity_pinned=True,
                canonical_path_characters=length,size_limit=16777216,recursion_limit=64,native_playback=False)
