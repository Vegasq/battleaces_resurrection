"""Reject stale-process and malformed-file native persistence evidence."""
import json
from pathlib import Path
import shutil
import unittest
import uuid

from tools.verify_unified_startup import native_settings_evidence


class NativeSettingsEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.game = Path(__file__).resolve().parents[1]/'local'/('native-settings-evidence-'+uuid.uuid4().hex)
        self.game.mkdir(parents=True)
        self.addCleanup(self.cleanup_fixture)
        self.output = self.game/'evidence'
        self.output.mkdir()
        self.runtime = self.game/'investigation/runtime'
        self.runtime.mkdir(parents=True)
        self.target = self.game/'.battleaces-resurrection/profiles/example/gameconfig-localuser.toml'
        self.target.parent.mkdir(parents=True)
        self.deck = {'_units': [{'_id': n} for n in range(1, 9)],
                     '_activeAbilities': [{'_id': n} for n in (1, 0, 0, 0)]}
        self.write_deck()
        self.write_log()

    def cleanup_fixture(self):
        self.game.resolve().relative_to(Path(__file__).resolve().parents[1]/'local')
        shutil.rmtree(self.game)

    def write_deck(self):
        self.target.write_text("[account]\ndecks = '"+json.dumps({'SelectedDeck': self.deck})+"'\n", encoding='utf-8')

    def write_log(self, verified_tick=102, selected_tick=100):
        selected = {'profile': 'example', 'path': str(self.target), 'beforeNativeLoad': True,
                    'isolated': True, 'writerLock': True}
        self.log = (f'[{selected_tick}] NATIVE SETTINGS path selected: '+json.dumps(selected)+
                    ' BA_RESURRECTION_NATIVE_SETTINGS_V1\n'
                    '[101] Offline initial state reached after game initialization. PID=12\n'
                    f'[{verified_tick}] NATIVE SETTINGS path verified: profile=example staticField=1 getterCalled=0 isolated=1\n')
        (self.runtime/'dedicated-native-12.log').write_text(self.log, encoding='utf-8')

    def proof(self):
        return native_settings_evidence(self.game, self.output, 12, 100, 'example')

    def test_actual_native_file_matches_current_process(self):
        result = self.proof()
        self.assertEqual(result['selected_deck']['units'], list(range(1, 9)))
        self.assertEqual((self.output/'isolated-localuser.toml').read_bytes(), self.target.read_bytes())

    def test_reused_pid_cannot_borrow_prior_static_field_proof(self):
        self.write_log(verified_tick=99)
        with self.assertRaises(AssertionError): self.proof()

    def test_path_must_precede_current_startup(self):
        self.write_log(selected_tick=102)
        with self.assertRaises(AssertionError): self.proof()

    def test_missing_or_boolean_units_are_not_native_identifiers(self):
        for value in (0, -1, True, '1', 0x100000000):
            with self.subTest(value=value):
                self.deck['_units'][0]['_id'] = value
                self.write_deck()
                with self.assertRaises(AssertionError): self.proof()

    def test_ability_group_zero_is_valid_but_boolean_or_negative_is_not(self):
        for value in (False, -1, '0', 0x100000000):
            with self.subTest(value=value):
                self.deck['_activeAbilities'][0]['_id'] = value
                self.write_deck()
                with self.assertRaises(AssertionError): self.proof()


if __name__ == '__main__':
    unittest.main()
