import json
import unittest
from tools.native_replay_playback_evidence import validate


class NativePlaybackEvidenceTests(unittest.TestCase):
    def fixture(self):
        selected='\\\\?\\E:\\owned\\Unicode-\u00e9\\replay.rep';profile='nativestest_replay_0123456789ab'
        digest='1'*64
        native=(f'NATIVE REPLAY playback armed: profile={profile} selected={json.dumps(selected,ensure_ascii=False)} '
                'persistentUnchanged=1 frameStart=-1 frameEnd=-1 capture=0 helperTick=0 BA_RESURRECTION_NATIVE_REPLAY_PLAYBACK_V1\n'
                'NATIVE REPLAY playback entered: originalFsmContext=1 existingState=1 helperContextWrites=0\n'
                f'NATIVE REPLAY playback data: frames=4000 last=3999 gameDataSha256={digest} originalSerialization=1\n'
                'NATIVE REPLAY playback progress: sim=8 presented=4 world=123 speed=16.000 frames=4000 last=3999 observerOnly=1\n'
                'NATIVE REPLAY playback progress: sim=3000 presented=2992 world=123 speed=16.000 frames=4000 last=3999 observerOnly=1\n')
        unity=f'Load replay: {selected}\nstack trace\nCompleted replay: {selected}\n'
        return native,unity,dict(selected=selected,profile=profile,replay=dict(input_action_messages=4000,game_data_sha256=digest),game_exit=0,driver_exit=0)

    def test_native_end_branch_can_follow_last_sample(self):
        native,unity,kwargs=self.fixture();result=validate(native,unity,**kwargs)
        self.assertTrue(result['native_playback']);self.assertTrue(result['original_batch_completed'])
        self.assertFalse(result['independent_determinism']);self.assertFalse(result['rendered_pixels_verified'])
        self.assertEqual(result,validate(native.replace('\n','\r\n'),unity.replace('\n','\r\n'),**kwargs))

    def test_incomplete_ambiguous_or_wrong_path_completion(self):
        native,unity,kwargs=self.fixture()
        for changed in ('',unity.split('Completed replay:')[0],unity+unity,
                        unity.replace('Completed replay: '+kwargs['selected'],'Completed replay: other.rep'),
                        '\n'.join(reversed(unity.splitlines()))):
            with self.subTest(changed=changed),self.assertRaises(AssertionError):validate(native,changed,**kwargs)

    def test_metadata_ownership_ranges_and_progress(self):
        native,unity,kwargs=self.fixture()
        for old,new in (('persistentUnchanged=1','persistentUnchanged=0'),('capture=0','capture=1'),
                        ('originalFsmContext=1','originalFsmContext=0'),('helperContextWrites=0','helperContextWrites=1'),
                        ('helperTick=0','helperTick=1'),('frames=4000','frames=3999'),('last=3999','last=4000'),
                        ('gameDataSha256='+'1'*64,'gameDataSha256='+'2'*64),('world=123','world=0'),
                        ('presented=2992','presented=4'),('sim=3000','sim=3'),('speed=16.000','speed=1.000')):
            with self.subTest(old=old),self.assertRaises(AssertionError):validate(native.replace(old,new),unity,**kwargs)
        with self.assertRaises(AssertionError):validate(native.replace('sim=3000 presented=2992 world=123','sim=3000 presented=2992 world=124'),unity,**kwargs)

    def test_failure_after_completed_or_nonzero_exit_is_not_success(self):
        native,unity,kwargs=self.fixture()
        for error in ('IOException: dispose failed','System.ArgumentException: invalid batch','Desync detected on frame: 7','Native replay observation failed: sample'):
            with self.subTest(error=error),self.assertRaises(AssertionError):validate(native,unity+error,**kwargs)
        for key in ('game_exit','driver_exit'):
            with self.subTest(key=key),self.assertRaises(AssertionError):validate(native,unity,**(kwargs|{key:1}))
