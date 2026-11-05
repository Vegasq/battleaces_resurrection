import copy
import unittest

from tools.verify_video_previews import validate_cases


def evidence():
    rows = []
    for index, (item, name) in enumerate([(11, 'Fatality_Default'), (12, 'Fatality_Warpout'), (11, 'Fatality_Default')]):
        for sample, phase in enumerate(['loaded', 'play-return', 'progress', 'progress']):
            rows.append(dict(index=index, item=item, phase=phase, tick=1000+1000*index+100*sample,
                clip_name=name, clip_id=100+item, player_id=200, frame=sample*5, seconds=sample/6,
                model_clip_present=True, player_clip_present=True, clip_binding_matches=True,
                vm_initialized=True, vm_active=True, target_present=True, playing=True,
                prepared=True, pending_play=False, disabled_clip_present=False))
    back = dict(rows[-1], phase='back', tick=4000, clip_id=0, clip_name='',
                playing=False, model_clip_present=False, player_clip_present=False,
                vm_initialized=False, vm_active=False)
    rows.append(back)
    return dict(schema=1, visual_audio_verified=False, physical_input_tested=False,
                loadout_unchanged=True, observations=rows), copy.deepcopy(back)


class VideoEvidenceTests(unittest.TestCase):
    def test_complete_sequence(self):
        validate_cases(*evidence())

    def test_playing_flag_without_advancement(self):
        proof, back = evidence()
        for row in proof['observations']:
            row['frame'] = 0
            row['seconds'] = 0
        back['frame'] = back['seconds'] = 0
        with self.assertRaisesRegex(AssertionError, 'did not advance'):
            validate_cases(proof, back)

    def test_wrong_clip_after_switch(self):
        proof, back = evidence()
        for row in proof['observations']:
            if row['index'] == 1:
                row['clip_name'] = 'Fatality_Default'
        with self.assertRaisesRegex(AssertionError, 'binding differs'):
            validate_cases(proof, back)

    def test_missing_return_to_first(self):
        proof, back = evidence()
        proof['observations'] = [r for r in proof['observations'] if r['index'] != 2]
        with self.assertRaisesRegex(AssertionError, 'switch and return'):
            validate_cases(proof, back)

    def test_hiding_without_clip_release(self):
        proof, back = evidence()
        proof['observations'][-1]['disabled_clip_present'] = True
        back['disabled_clip_present'] = True
        with self.assertRaisesRegex(AssertionError, 'retained playback'):
            validate_cases(proof, back)

    def test_unrelated_back_player(self):
        proof, back = evidence()
        proof['observations'][-1]['player_id'] = 999
        back['player_id'] = 999
        with self.assertRaisesRegex(AssertionError, 'ownership evidence'):
            validate_cases(proof, back)

    def test_fake_visual_acceptance(self):
        proof, back = evidence()
        proof['visual_audio_verified'] = True
        with self.assertRaisesRegex(AssertionError, 'scope'):
            validate_cases(proof, back)


if __name__ == '__main__':
    unittest.main()
