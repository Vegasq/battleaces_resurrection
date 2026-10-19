from contextlib import contextmanager
import shutil
import unittest
import uuid
import zlib
from pathlib import Path
from server.protobuf_wire import decode_varint
from tools import replay_codec_fixtures as fixtures
from tools.native_replay_evidence import validate_faults


@contextmanager
def owned_directory():
    root=Path(__file__).resolve().parents[1]/'local'
    root.mkdir(exist_ok=True)
    folder=root/('codec-fixture-unit-'+uuid.uuid4().hex);folder.mkdir()
    try:yield folder
    finally:
        if folder.resolve().is_relative_to(root.resolve()):shutil.rmtree(folder)


class ReplayCodecFixtureTests(unittest.TestCase):
    def test_authored_inputs_exercise_distinct_codec_conditions(self):
        payloads=fixtures.payloads();self.assertEqual(list(payloads),list(fixtures.CASES))
        self.assertTrue(all(0<len(raw)<=64*1024 for raw in payloads.values()))
        with self.assertRaises(zlib.error):zlib.decompress(payloads['invalid-deflate'],-15)
        raw={case:zlib.decompress(value,-15) for case,value in payloads.items() if case!='invalid-deflate'}
        self.assertEqual(raw['invalid-wire'],b'\x0f');self.assertEqual(raw['truncated-field'],b'\x0a\x01')
        self.assertEqual(raw['recursion-limit'],b'\x7b'*66+b'\x7c'*66)
        self.assertEqual(raw['empty-recording'],b'')
        blob=raw['size-limit'];self.assertEqual(blob[0],0x7a)
        length,offset=decode_varint(blob,1)
        self.assertEqual(length,fixtures.LIMIT+1);self.assertEqual(len(blob)-offset,length)
        self.assertEqual(blob[offset:],bytes(length))

    def test_owned_preparation_refuses_reuse_and_detects_mutation(self):
        with owned_directory() as temporary:
            root=Path(temporary);folder=root/'nativestest_packaged_0123456789ab/AutoSaveReplays'
            fixture=fixtures.prepare(folder,root)
            self.assertEqual(fixtures.verify(folder,fixture),dict(files=6,all_bytes_unchanged=True))
            with self.assertRaises(AssertionError):fixtures.prepare(folder,root)
            (folder/next(iter(fixture['files']))).write_bytes(b'changed')
            with self.assertRaises(AssertionError):fixtures.verify(folder,fixture)
            with self.assertRaises(AssertionError):fixtures.prepare(root/'ordinary/AutoSaveReplays',root)

    def log(self):
        lines=['Practice returned: completed=1','NATIVE REPLAY codec readback passed: healthy']
        for case in fixtures.CASES:
            exception='none' if case=='empty-recording' else 'System.IO.IOException' if case=='invalid-deflate' else 'Google.Protobuf.InvalidProtocolBufferException'
            phase='validate' if case=='empty-recording' else 'parse'
            if exception!='none':lines.append(f'NATIVE REPLAY fault managed exception: case={case} type={exception} detail=authored')
            lines.append(f'NATIVE REPLAY fault rejected: case={case} phase={phase} exception={exception} streamsDisposed=3 cleanupErrors=0 fileIdentityPinned=1 limitsVerified=1 exclusiveReopen=1 playbackCalls=0')
        lines+=['NATIVE REPLAY fault suite passed: cases=6 originalCodec=1 helperLimits=16777216,64 playbackCalls=0 BA_RESURRECTION_NATIVE_REPLAY_FAULTS_V1',
                'NATIVE QUIT owned menu verified: healthy idle']
        return '\n'.join(lines)

    def test_all_native_rejections_and_cleanup_precede_idle_quit(self):
        log=self.log();result=validate_faults(log)
        self.assertEqual(result['cases'],list(fixtures.CASES));self.assertFalse(result['native_playback'])
        self.assertEqual(result,validate_faults(log.replace('\n','\r\n')))

    def test_missing_ambiguous_wrong_phase_type_or_cleanup_is_rejected(self):
        log=self.log()
        for old,new in (('streamsDisposed=3','streamsDisposed=2'),('cleanupErrors=0','cleanupErrors=1'),
                        ('exclusiveReopen=1','exclusiveReopen=0'),('phase=parse','phase=validate'),
                        ('System.IO.IOException','System.IO.InvalidDataException'),('playbackCalls=0','playbackCalls=1'),
                        ('size-limit','wrong-case'),('NATIVE REPLAY codec readback passed:','healthy missing:'),
                        ('NATIVE QUIT owned menu verified:','idle missing:')):
            with self.subTest(old=old),self.assertRaises(AssertionError):validate_faults(log.replace(old,new))
        for changed in (log+'\n'+log,log+'\nNATIVE REPLAY codec readback failed: fixture',
                        log+'\nNATIVE REPLAY decoder managed exception: fixture',
                        log+'\nNATIVE REPLAY fault rejected: incomplete',
                        log.replace('NATIVE QUIT owned menu verified: healthy idle','')+'\nNATIVE REPLAY codec readback passed: late'):
            with self.subTest(changed=changed[-80:]),self.assertRaises(AssertionError):validate_faults(changed)
