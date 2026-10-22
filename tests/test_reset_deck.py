import copy
import json
from pathlib import Path
from contextlib import contextmanager
import tomllib
import unittest
from unittest import mock
from tools import reset_deck as resetter
from tests.test_credentials import private_test_folder, remove_test_folder


@contextmanager
def temporary():
    folder=private_test_folder('reset-deck-')
    try: yield folder
    finally: remove_test_folder(folder)


class ResetDeckTests(unittest.TestCase):
    def seed(self):
        selected = dict(_name='SelectedDeck', _units=[{'_id':i+1} for i in range(8)],
                        _activeAbilities=[{'_id':i} for i in range(4)])
        deck = dict(SelectedDeck=selected, Decks=[copy.deepcopy(selected)])
        return ('# native settings\r\n[account]\r\ndecks = '+json.dumps(json.dumps(deck))+
                '\r\nmenuuistates = "unchanged"\r\n[options]\r\nRegion = 4\r\n').encode()

    def test_resets_selection_preserves_saved_decks_and_other_settings(self):
        raw=self.seed(); before=tomllib.loads(raw.decode()); after=tomllib.loads(resetter.reset_bytes(raw).decode())
        original=json.loads(before['account']['decks']); changed=json.loads(after['account']['decks'])
        self.assertEqual(changed['Decks'],original['Decks'])
        self.assertEqual([x['_id'] for x in changed['SelectedDeck']['_units']],[0]*8)
        self.assertEqual([x['_id'] for x in changed['SelectedDeck']['_activeAbilities']],[0]*4)
        before['account'].pop('decks'); after['account'].pop('decks'); self.assertEqual(before,after)
        self.assertEqual(resetter.reset_bytes(b'[account]\n'),b'[account]\n')

    def test_ambiguous_or_malformed_input_is_refused(self):
        for raw in (b'[account\n',b'[account]\ndecks = "bad json"', self.seed()+b'[another]\ndecks = "x"\n'):
            with self.assertRaises((ValueError,KeyError)): resetter.reset_bytes(raw)

    def test_actual_file_has_exact_backup_and_game_lock_refuses_reset(self):
        with temporary() as root:
            game=Path(root).resolve(); base=game/'.battleaces-resurrection'; folder=base/'profiles/default'
            folder.mkdir(parents=True)
            config=base/'client-config.json'
            config.write_text(json.dumps(dict(schema=3,game_directory=str(game),display_name='Player')))
            target=folder/'gameconfig-localuser.toml'; raw=self.seed(); target.write_bytes(raw)
            result=resetter.reset(game)
            self.assertEqual(Path(result['backup']).read_bytes(),raw)
            self.assertEqual(target.read_bytes(),resetter.reset_bytes(raw))
            with resetter.profile_lock(folder):
                with self.assertRaisesRegex(ValueError,'Close Battle Aces'): resetter.reset(game)
            self.assertEqual(len(list((folder/'deck-reset-backups').glob('*'))),1)

    def test_publish_failure_retains_original_and_recoverable_backup(self):
        with temporary() as root:
            game=Path(root).resolve(); base=game/'.battleaces-resurrection'; folder=base/'profiles/default'
            folder.mkdir(parents=True)
            (base/'client-config.json').write_text(json.dumps(dict(schema=3,game_directory=str(game),display_name='Player')))
            target=folder/'gameconfig-localuser.toml'; raw=self.seed(); target.write_bytes(raw)
            with mock.patch.object(resetter,'atomic_write',side_effect=PermissionError):
                with self.assertRaises(PermissionError): resetter.reset(game)
            self.assertEqual(target.read_bytes(),raw)
            self.assertEqual(next((folder/'deck-reset-backups').glob('*')).read_bytes(),raw)
