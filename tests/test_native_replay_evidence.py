import unittest
from tools.native_replay_evidence import validate


class NativeReplayEvidenceTests(unittest.TestCase):
    def fixture(self):
        return ('Practice returned: completed=1 mode=2\n'
                'NATIVE REPLAY codec readback passed: frames=4000 first=0 last=3999 initialActions=4 '
                'playerBatches=3990 build=37822 streamsDisposed=3 fileIdentityPinned=1 canonicalPathCharacters=290 '
                'sizeLimit=16777216 recursionLimit=64 playbackCalls=0 BA_RESURRECTION_NATIVE_REPLAY_READER_V1\n'
                'NATIVE QUIT owned menu verified:',dict(input_action_messages=4000,canonical_path_characters=290))

    def test_valid_original_codec_does_not_claim_playback(self):
        log,replay=self.fixture();result=validate(log,replay)
        self.assertTrue(result['original_codec']);self.assertFalse(result['native_playback'])
        self.assertEqual(result,validate(log.replace('\n','\r\n'),replay))

    def test_wrong_counts_path_build_cleanup_and_frame_end_are_rejected(self):
        log,replay=self.fixture()
        for old,new in (('frames=4000','frames=3999'),('last=3999','last=4000'),('initialActions=4','initialActions=0'),
                        ('playerBatches=3990','playerBatches=0'),('build=37822','build=1'),
                        ('streamsDisposed=3','streamsDisposed=2'),('canonicalPathCharacters=290','canonicalPathCharacters=289'),
                        ('fileIdentityPinned=1','fileIdentityPinned=0'),('playbackCalls=0','playbackCalls=1')):
            with self.subTest(old=old),self.assertRaises(AssertionError):validate(log.replace(old,new),replay)

    def test_failed_duplicate_or_reordered_native_readback_is_rejected(self):
        log,replay=self.fixture()
        for changed in (log+'\nNATIVE REPLAY codec readback failed: fixture',
                        log+'\nNATIVE REPLAY decoder managed exception: fixture',log+'\n'+log,
                        log.replace('Practice returned: completed=1 mode=2\n','')+'\nPractice returned: completed=1 mode=2'):
            with self.subTest(changed=changed[-70:]),self.assertRaises(AssertionError):validate(changed,replay)
