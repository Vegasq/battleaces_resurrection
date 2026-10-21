import unittest

from tests import test_replay_signal_evidence as fixture_module
from tools.replay_menu_evidence import validate, COMPLETE
from tools.replay_binding_evidence import validate as binding


class ReplayMenuEvidenceTests(unittest.TestCase):
    def setUp(self):
        fixture = fixture_module.ReplaySignalEvidenceTests()
        fixture.setUp()
        fixture.value['active_self'] = True
        self.binding = fixture.log().replace('phase=healthy-practice', 'phase=healthy-replay')
        self.replay = dict(input_action_messages=100, game_data_sha256='a'*64)
        self.text = ('[0] NATIVE REPLAY MENU load dispatch: profile=nativestest_replayui_0123456789ab '
                     'mainMenu=1 worldIdle=1 originalLoadReplayFromFile=1 extraPlayCalls=0 fsmWrites=0 helperTicks=0\n'
                     '[1] NATIVE REPLAY MENU loaded: frames=100 gameDataSha256='+'a'*64+
                     ' loadReturned=1 originalPlayInternal=1\n'
                     '[2] Original replay runner update restored: primaryIntegration=1 originalPredicate=1 helperTicks=0\n'+self.binding+
                     '[3] NATIVE REPLAY MENU in-game: world=10 presented=30 originalMainFsm=1 practiceActive=0 frames=100\n'
                     '[4] NATIVE REPLAY MENU exit API dispatch: originalReplayEndGame=1 buttonClicks=0 fsmWrites=0 helperTicks=0\n'
                     '[5] NATIVE REPLAY MENU exit API returned: originalCallbackReturned=1\n'
                     '[6] '+COMPLETE+'\n')

    def test_api_control_does_not_claim_a_bound_button_or_disk_ui(self):
        result = validate(self.text, self.replay)
        self.assertTrue(result['original_file_load_and_internal_play'])
        self.assertTrue(result['original_exit_api'])
        self.assertFalse(result['bound_button_exit_qualified'])
        self.assertFalse(result['user_exposed_disk_selection_qualified'])

    def test_replay_phase_is_not_satisfied_by_practice_marker(self):
        with self.assertRaises(AssertionError):
            validate(self.text.replace('phase=healthy-replay', 'phase=healthy-practice'), self.replay)
        with self.assertRaises(AssertionError):
            binding(self.binding)

    def test_requires_the_production_runner_without_its_failure(self):
        for text in (self.text.replace('Original replay runner update restored:', 'not a runner:'),
                     self.text+'Original replay runner update failed: original runner missing\n'):
            with self.subTest(text=text[-90:]), self.assertRaises(AssertionError):
                validate(text, self.replay)

    def test_rejects_wrong_record_or_nonadvancing_presentation(self):
        for text in (self.text.replace('presented=30', 'presented=0'),
                     self.text.replace('gameDataSha256='+'a'*64, 'gameDataSha256='+'b'*64),
                     self.text.replace('loaded: frames=100', 'loaded: frames=101')):
            self.assertNotEqual(text, self.text)
            with self.subTest(text=text[-80:]), self.assertRaises(AssertionError):
                validate(text, self.replay)

    def test_rejects_extra_play_batch_or_practice(self):
        for text in (self.text.replace('extraPlayCalls=0', 'extraPlayCalls=1'),
                     self.text+'NATIVE REPLAY playback armed:', self.text+'Practice requested:'):
            with self.subTest(text=text[-80:]), self.assertRaises(AssertionError):
                validate(text, self.replay)

    def test_rejects_missing_or_repeated_exit_api_boundary(self):
        for text in (self.text.replace(COMPLETE, ''), self.text+'[7] '+COMPLETE,
                     self.text+'Native replay menu control failed: owner changed'):
            with self.subTest(text=text[-80:]), self.assertRaises(AssertionError):
                validate(text, self.replay)


if __name__ == '__main__':
    unittest.main()
