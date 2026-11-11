"""Authored transformation contracts only; no native/client execution."""
import unittest
from server.game_data import GameDataError
from server.protobuf_wire import get_bytes,get_repeated_bytes,get_uint,parse_fields
from tests import test_prediction_mobile_fixture as mobile_authored
from tools import prediction_actor_fixture as f


class MobileSurvivorFixtureTests(unittest.TestCase):
    def setUp(self):
        self.source=mobile_authored.MobileFixtureTests();self.source.setUp();self.addCleanup(self.source.doCleanups)
        self.base=self.source.base;self.assets=self.source.assets

    def test_only_one_initial_unit_appended_existing_duel_and_configuration_unchanged(self):
        mobile=f.make_mobile_template(self.base,self.assets)
        survivor=f.make_mobile_survivor_template(self.base,self.assets)
        self.assertIsInstance(survivor,f.MobileSurvivorFixtureTemplate)
        before=get_repeated_bytes(mobile.raw_game_data,2);after=get_repeated_bytes(survivor.raw_game_data,2)
        self.assertEqual(after[:12],before);self.assertEqual(len(after),13)
        self.assertEqual([x.raw for x in parse_fields(mobile.raw_game_data)if x.number!=2],
                         [x.raw for x in parse_fields(survivor.raw_game_data)if x.number!=2])
        entity=get_bytes(after[12],2,required=True)
        self.assertEqual(get_uint(entity,1),1);self.assertEqual(get_uint(entity,2),1)
        self.assertEqual(f._position(get_bytes(entity,3,required=True)),(-80.,0.,-60.))
        self.assertEqual(get_bytes(entity,4,required=True),get_bytes(get_bytes(before[11],2,required=True),4,required=True))

    def test_ordinary_and_prior_fixture_bytes_and_allowed_decks_are_not_mutated(self):
        before=self.base.raw_game_data;mobile=f.make_mobile_template(self.base,self.assets).raw_game_data
        hq=f.make_template(self.base,self.assets).raw_game_data
        survivor=f.make_mobile_survivor_template(self.base,self.assets)
        self.assertEqual(self.base.raw_game_data,before)
        self.assertEqual(f.make_mobile_template(self.base,self.assets).raw_game_data,mobile)
        self.assertEqual(f.make_template(self.base,self.assets).raw_game_data,hq)
        self.assertEqual(survivor.default_decks,self.base.default_decks)
        self.assertEqual(survivor.allowed_entity_ids,self.base.allowed_entity_ids)

    def test_normal_builder_owns_roster_seed_decks_and_appended_entity_bytes(self):
        survivor=f.make_mobile_survivor_template(self.base,self.assets)
        match=survivor.build_match(self.source.roster,self.source.decks,999,'authored-survivor',game_mode=1)
        self.assertEqual(match.seed,f.MOBILE_SEED)
        self.assertEqual(dict(match.decks_by_slot),self.source.decks)
        self.assertEqual(get_repeated_bytes(match.raw_game_data,2),get_repeated_bytes(survivor.raw_game_data,2))
        self.assertEqual([p.name for p in match.roster],[p['name']for p in self.source.roster])

    def test_all_composed_fixtures_and_nonhuman_or_noncustom_topologies_refuse(self):
        variants=[f.make_template(self.base,self.assets),f.make_mobile_template(self.base,self.assets),
                  f.make_mobile_survivor_template(self.base,self.assets)]
        for prior in variants:
            with self.subTest(prior=type(prior).__name__),self.assertRaises(GameDataError):
                f.make_mobile_survivor_template(prior,self.assets)
        survivor=variants[-1]
        with self.assertRaises(GameDataError):survivor.build_match(self.source.roster,self.source.decks,game_mode=4)
        roster=[self.source.roster[0],dict(self.source.roster[1],ai_profile_id=1)]
        with self.assertRaises(GameDataError):survivor.build_match(roster,self.source.decks)

    def test_metadata_is_distinct_detached_and_does_not_claim_client_acceptance(self):
        before=f.mobile_metadata();meta=f.mobile_survivor_metadata()
        self.assertEqual(meta['selected_ids'],[11,12]);self.assertEqual(meta['initial_entity_count'],13)
        self.assertEqual(meta['initial_survivor'],[-80.,0.,-60.]);self.assertTrue(meta['selection_is_preactivation'])
        self.assertNotEqual(meta['name'],before['name'])
        meta['selected_ids'].clear();meta['initial_survivor'][0]=0
        self.assertEqual(f.mobile_survivor_metadata()['selected_ids'],[11,12])
        self.assertEqual(f.mobile_survivor_metadata()['initial_survivor'],[-80.,0.,-60.])
        self.assertEqual(f.mobile_metadata(),before)


if __name__=='__main__':unittest.main()
