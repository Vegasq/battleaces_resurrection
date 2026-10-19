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


def validate_faults(log):
    from tools.replay_codec_fixtures import CASES
    log=log.replace('\r\n','\n').replace('\r','\n')
    if 'NATIVE REPLAY codec readback failed:' in log or 'NATIVE REPLAY decoder managed exception:' in log:
        raise AssertionError('native replay fault suite or healthy control failed')
    expected={case:('validate','none') if case=='empty-recording' else
              ('parse','System.IO.IOException' if case=='invalid-deflate' else 'Google.Protobuf.InvalidProtocolBufferException') for case in CASES}
    rows=list(re.finditer(r'NATIVE REPLAY fault rejected: case=([a-z-]+) phase=([a-z]+) exception=([A-Za-z.]+) '
                         r'streamsDisposed=3 cleanupErrors=0 fileIdentityPinned=1 limitsVerified=1 exclusiveReopen=1 playbackCalls=0',log))
    if log.count('NATIVE REPLAY fault rejected:')!=len(CASES) or [row[1] for row in rows]!=list(CASES) or any((row[2],row[3])!=expected[row[1]] for row in rows):
        raise AssertionError('native replay rejection type/phase/cleanup cases differ')
    exceptions=re.findall(r'NATIVE REPLAY fault managed exception: case=([a-z-]+) type=([A-Za-z.]+) detail=',log)
    if log.count('NATIVE REPLAY fault managed exception:')!=5 or exceptions!=[(case,expected[case][1]) for case in CASES if case!='empty-recording']:
        raise AssertionError('expected one original managed parser/decompressor exception per malformed input')
    marker='NATIVE REPLAY fault suite passed: cases=6 originalCodec=1 helperLimits=16777216,64 playbackCalls=0 BA_RESURRECTION_NATIVE_REPLAY_FAULTS_V1'
    healthy=log.find('NATIVE REPLAY codec readback passed:');idle=log.find('NATIVE QUIT owned menu verified:')
    if log.count(marker)!=1 or not 0<=healthy<rows[0].start()<rows[-1].end()<log.index(marker)<idle:
        raise AssertionError('fault suite was not between healthy control and same idle menu revalidation')
    return dict(cases=list(CASES),original_codec=True,streams_disposed_per_case=3,exclusive_reopen_per_case=True,
                size_limit=16777216,recursion_limit=64,native_playback=False)
