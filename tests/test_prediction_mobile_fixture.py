"""Authored protobuf/source contracts only; no native behavior is asserted."""
import hashlib
import math
from pathlib import Path
import unittest

from server.game_data import GameDataError,decompress_game_data
from server.protobuf_wire import (field_bytes,field_packed_uint,field_uint,get_bytes,
                                  get_repeated_bytes,get_uint,parse_fields,replace_fields,signed64)
from tests import test_prediction_actor_fixture as authored
from tests.synthetic import template
from tools import prediction_actor_fixture as fixture


Q32=2**32


class MobileFixtureTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing authored catalog/map source, not private assets.
        self.source=authored.ActorFixtureTests();self.source.setUp();self.addCleanup(self.source.doCleanups)
        self.assets=self.source.assets;self.roster=self.source.roster
        definitions=[]
        for entity in get_repeated_bytes(self.source.base.game_config,1):
            if get_uint(entity,1)==1:
                health=field_uint(1,4)+field_uint(2,300*Q32)+field_uint(3,123)
                damage=field_uint(1,5)+field_uint(2,50*Q32)
                entity=replace_fields(entity,{8:[field_bytes(8,health),field_bytes(8,damage)]})
            definitions.append(entity)
        config=replace_fields(self.source.base.game_config,{1:[field_bytes(1,e)for e in definitions]})
        self.base=self.source.load(replace_fields(self.source.base.raw_game_data,{1:[field_bytes(1,config)]}))
        self.decks={slot:(1,*range(101,108))for slot in (0,1)}

    def changed(self,definitions=None,global_config=None,initial=None):
        changes={}
        if definitions is not None:changes[1]=[field_bytes(1,e)for e in definitions]
        if global_config is not None:changes[3]=[field_bytes(3,global_config)]
        config=replace_fields(self.base.game_config,changes)
        replacements={1:[field_bytes(1,config)]}
        if initial is not None:replacements[2]=[field_bytes(2,a)for a in initial]
        return self.source.load(replace_fields(self.base.raw_game_data,replacements))

    def test_separate_mobile_transform_preserves_base_defaults_and_old_HQ_bytes(self):
        original=(self.base.raw_game_data,self.base.global_config,dict(self.base.default_decks),self.base.allowed_entity_ids)
        hq=fixture.make_template(self.base,self.assets).raw_game_data
        hq_metadata=fixture.metadata()
        mobile=fixture.make_mobile_template(self.base,self.assets)
        self.assertIsInstance(mobile,fixture.MobileFixtureTemplate)
        self.assertEqual(original,(self.base.raw_game_data,self.base.global_config,self.base.default_decks,self.base.allowed_entity_ids))
        self.assertEqual(mobile.default_decks,self.base.default_decks)
        self.assertEqual(mobile.allowed_entity_ids,self.base.allowed_entity_ids)
        self.assertEqual(fixture.make_template(self.base,self.assets).raw_game_data,hq)
        self.assertEqual(fixture.metadata(),hq_metadata)
        self.assertEqual(self.base.build_match(self.roster,self.decks,123).seed,123)
        self.assertEqual(fixture.make_template(self.base,self.assets).build_match(self.roster,self.decks,123).seed,20261110)

    def test_only_Gunbot_health_and_activation_change_Core_global22_and_other_wire_fields_preserved(self):
        mobile=fixture.make_mobile_template(self.base,self.assets)
        before=get_repeated_bytes(self.base.game_config,1);after=get_repeated_bytes(mobile.game_config,1)
        self.assertEqual(len(before),len(after))
        for original,transformed in zip(before,after):
            if get_uint(original,1)!=1:self.assertEqual(original,transformed);continue
            self.assertEqual([f.raw for f in parse_fields(original)if f.number!=8],
                             [f.raw for f in parse_fields(transformed)if f.number!=8])
            attrs=get_repeated_bytes(transformed,8);original_attrs=get_repeated_bytes(original,8)
            self.assertEqual(get_uint(attrs[0],1),4);self.assertEqual(get_uint(attrs[0],2),100*Q32)
            self.assertEqual(get_uint(attrs[0],3),123);self.assertEqual(attrs[1:],original_attrs[1:])
        core=next(e for e in after if get_uint(e,1)==3)
        self.assertEqual(get_uint(get_repeated_bytes(core,8)[0],2),900*Q32)
        self.assertEqual(get_uint(mobile.global_config,4),7*Q32)
        self.assertEqual([f.raw for f in parse_fields(mobile.global_config)if f.number!=4],
                         [f.raw for f in parse_fields(self.base.global_config)if f.number!=4])
        self.assertEqual(get_uint(mobile.global_config,22),10*Q32)
        self.assertEqual([f.raw for f in parse_fields(mobile.game_config)if f.number not in (1,3)],
                         [f.raw for f in parse_fields(self.base.game_config)if f.number not in (1,3)])

    def test_original_initial_ten_unchanged_then_two_opposing_Gunbots_with_correct_order(self):
        mobile=fixture.make_mobile_template(self.base,self.assets)
        actions=get_repeated_bytes(mobile.raw_game_data,2)
        self.assertEqual(actions[:10],get_repeated_bytes(self.base.raw_game_data,2));self.assertEqual(len(actions),12)
        for index,army,x,sign in ((10,0,-2.,1),(11,1,2.,-1)):
            create=get_bytes(actions[index],2,required=True)
            self.assertEqual(get_uint(create,1),1);self.assertEqual(get_uint(create,2),army)
            self.assertEqual(any(f.number==2 for f in parse_fields(create)),bool(army))
            self.assertEqual(fixture._position(get_bytes(create,3,required=True)),(x,0.,0.))
            rotation=get_bytes(create,4,required=True)
            self.assertEqual([f.number for f in parse_fields(rotation)],[2,4])
            self.assertEqual(signed64(get_uint(rotation,2)),int(sign*math.sqrt(.5)*Q32))
            self.assertEqual(get_uint(rotation,4),int(math.sqrt(.5)*Q32))

    def test_match_uses_only_mobile_seed_and_normal_builder_selected_roster_decks_hashes(self):
        mobile=fixture.make_mobile_template(self.base,self.assets)
        source=(list(map(dict,self.roster)),dict(self.decks))
        match=mobile.build_match(self.roster,self.decks,999,'authored-mobile',game_mode=1)
        self.assertEqual(match.seed,20261111);self.assertEqual(get_uint(match.game_config,38),20261111)
        self.assertEqual(dict(match.decks_by_slot),self.decks)
        self.assertEqual([p.name for p in match.roster],[p['name']for p in self.roster])
        self.assertEqual((self.roster,self.decks),source)
        self.assertEqual(get_repeated_bytes(match.raw_game_data,2),get_repeated_bytes(mobile.raw_game_data,2))
        self.assertEqual(decompress_game_data(match.gzip_game_data),match.raw_game_data)
        self.assertEqual(hashlib.sha256(match.raw_game_data).hexdigest(),match.raw_sha256)
        self.assertEqual(hashlib.sha256(match.gzip_game_data).hexdigest(),match.sha256)

    def test_requires_Gunbot_in_both_chosen_decks_without_forcing_them(self):
        mobile=fixture.make_mobile_template(self.base,self.assets)
        for slot in (0,1):
            chosen=dict(self.decks);chosen[slot]=self.base.default_decks[slot];before=dict(chosen)
            with self.subTest(slot=slot),self.assertRaisesRegex(GameDataError,'both human slots'):
                mobile.build_match(self.roster,chosen)
            self.assertEqual(chosen,before)

    def test_metadata_is_fresh_and_distinguishes_control_timings_from_new_runtime_requests(self):
        description=fixture.mobile_metadata()
        self.assertEqual((description['attacker_id'],description['victim_id'],description['unit_type']),(10,11,1))
        self.assertEqual(description['seed'],20261111)
        self.assertEqual(description['safe_canonical_frames'],[151,152])
        self.assertEqual((description['baseline_death_frame'],description['baseline_absent_frame']),(153,154))
        self.assertEqual(description['survivor_through_frame'],173)
        self.assertEqual((description['fresh_move_physical_frame'],description['observation_last_frame']),(180,220))
        self.assertTrue(description['unchanged_core_health'])
        description['target'][0]=999;description['safe_canonical_frames'].clear()
        self.assertEqual(fixture.mobile_metadata()['target'],[-32.,0.,0.])
        self.assertEqual(fixture.mobile_metadata()['safe_canonical_frames'],[151,152])
        with self.assertRaises(TypeError):fixture.MOBILE_METADATA['seed']=1

    def test_composition_topology_and_nonhuman_assignment_fail_explicitly(self):
        mobile=fixture.make_mobile_template(self.base,self.assets);hq=fixture.make_template(self.base,self.assets)
        for builder in (fixture.make_template,fixture.make_mobile_template):
            for prior in (mobile,hq):
                with self.subTest(builder=builder,prior=type(prior)),self.assertRaisesRegex(GameDataError,'already transformed'):
                    builder(prior,self.assets)
        with self.assertRaisesRegex(GameDataError,'Custom1v1'):mobile.build_match(self.roster,self.decks,game_mode=4)
        for roster in ([dict(p,army_id=1-p['army_id'])for p in self.roster],
                       [self.roster[0],dict(self.roster[1],ai_profile_id=1)]):
            with self.assertRaisesRegex(GameDataError,'two human slots'):mobile.build_match(roster,self.decks)
        with self.assertRaisesRegex(GameDataError,'two-army map'):fixture.make_mobile_template(template(2),self.assets)

    def test_missing_or_duplicated_health_and_missing_original_move_metadata_fail(self):
        definitions=get_repeated_bytes(self.base.game_config,1)
        for mode in ('missing','duplicate','move'):
            changed=[]
            for entity in definitions:
                if get_uint(entity,1)==1:
                    attrs=get_repeated_bytes(entity,8)
                    if mode=='missing':entity=replace_fields(entity,{8:[field_bytes(8,attrs[1])]})
                    if mode=='duplicate':entity=replace_fields(entity,{8:[field_bytes(8,a)for a in (*attrs,attrs[0])]})
                    if mode=='move':entity=replace_fields(entity,{7:[field_packed_uint(7,(14,88))]})
                changed.append(entity)
            with self.subTest(mode=mode),self.assertRaises(GameDataError):
                fixture.make_mobile_template(self.changed(definitions=changed),self.assets)

    def test_changed_initial_entity_layout_or_startup_cannot_be_silently_reused(self):
        initial=get_repeated_bytes(self.base.raw_game_data,2)
        for actions in (initial[:-1],(*initial,initial[-1]),(*initial[:5],initial[0],*initial[6:])):
            with self.subTest(count=len(actions)),self.assertRaises(GameDataError):
                fixture.make_mobile_template(self.changed(initial=actions),self.assets)
        for number,value in ((27,5*Q32),(29,0)):
            changed=replace_fields(self.base.global_config,{number:[field_uint(number,value)]})
            with self.assertRaisesRegex(GameDataError,'startup differs'):
                fixture.make_mobile_template(self.changed(global_config=changed),self.assets)


if __name__=='__main__':
    unittest.main()
