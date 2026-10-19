"""Keep native refusal fixtures distinct from accidental TOML syntax failures."""
import json
import tomllib
import unittest

from tools.verify_native_deck_inputs import fixtures


class NativeDeckInputFixtureTests(unittest.TestCase):
    def setUp(self):
        self.deck={'SelectedDeck':{'_name':'Authored \'deck\" é\n',
            '_units':[{'_id':n} for n in range(1,9)],
            '_activeAbilities':[{'_id':n} for n in (1,0,0,0)]},'Decks':[]}
        self.seed=('[account]\ndecks = '+json.dumps(json.dumps(self.deck))+'\n[options]\nvolume = 0.5\n').encode()
        self.cases={name:(data,healthy,expected) for name,data,healthy,expected in fixtures(self.seed)}

    def deck_value(self,name):
        return json.loads(tomllib.loads(self.cases[name][0].decode())['account']['decks'])

    def test_every_present_fixture_is_valid_toml(self):
        for name,(data,_,_) in self.cases.items():
            if data is not None:
                with self.subTest(name=name):tomllib.loads(data.decode())

    def test_semantic_id_and_shape_fixtures_reach_the_intended_json_fields(self):
        self.assertEqual(self.deck_value('unknown-unit')['SelectedDeck']['_units'][0]['_id'],0xfffffffe)
        self.assertEqual(self.deck_value('unknown-ability')['SelectedDeck']['_activeAbilities'][0]['_id'],0xfffffffe)
        bad=self.deck_value('bad-saved-shape')
        self.assertEqual(bad['SelectedDeck'],self.deck['SelectedDeck'])
        self.assertEqual(len(bad['Decks'][0]['_units']),7)
        self.assertIsNone(self.deck_value('null-units')['SelectedDeck']['_units'])

    def test_wrong_slot_is_a_permutation_without_duplicate_or_unknown_ids(self):
        changed=self.deck_value('wrong-slot')['SelectedDeck']['_units']
        self.assertCountEqual(changed,self.deck['SelectedDeck']['_units'])
        self.assertNotEqual(changed,self.deck['SelectedDeck']['_units'])

    def test_unfinished_controls_preserve_every_other_slot_and_options(self):
        for name,value in (('healthy-unfinished',0),('healthy-native-empty-sentinel',0xffffffff)):
            data,healthy,expected=self.cases[name]
            table=tomllib.loads(data.decode());deck=json.loads(table['account']['decks'])['SelectedDeck']
            self.assertTrue(healthy)
            self.assertEqual(expected,list(range(1,8))+[value])
            self.assertEqual(deck['_name'],self.deck['SelectedDeck']['_name'])
            self.assertEqual(table['options'],{'volume':0.5})


if __name__=='__main__':unittest.main()
