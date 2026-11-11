"""Explicit owned actor-retraction fixture; never an ordinary server template.

Authored GameData only: original Core health100, no health-per-supply growth,
activation7sec after the unchanged6sec reveal/~5sec command startup, and one
properly oriented army0 Gunbot near army1's Core. Original default fire kills
Core5 at155; an original Move12 at152..154 prevented it in the retained native
control. This module does not predict new abilities or modify runtime state.
"""
from __future__ import annotations

from pathlib import Path
import math
import struct
from types import MappingProxyType

from server.game_data import GameTemplate,GameDataError
from server.protobuf_wire import (field_bytes,field_uint,get_bytes,get_repeated_bytes,
                                  get_uint,replace_fields,signed64)

SEED=20261110
METADATA=MappingProxyType(dict(
    name='original-gunbot-core-move-v1',victim_slot=1,victim_core_id=5,core_type=3,
    attacker_slot=0,attacker_id=10,attacker_type=1,core_health=100,
    selection_frame=130,escape_physical_frame=152,expected_canonical_frame=153,
    safe_canonical_frames=(152,153,154),baseline_death_frame=155,seed=SEED,
    target=(-69.77999877929688,0.0,-80.8499984741211)))
_CORE_POSITION=(-103.77999877929688,0.0,-80.8499984741211)
MIRROR_SEED=20261112
MIRROR_METADATA=MappingProxyType(dict(METADATA,
    name='original-gunbot-core-move-mirror-v1',victim_slot=0,victim_core_id=0,
    attacker_slot=1,escape_physical_frame=150,expected_canonical_frame=151,
    safe_canonical_frames=(151,),baseline_first_damage_frame=142,baseline_death_frame=153,
    seed=MIRROR_SEED,target=(69.77999877929688,0.0,80.8499984741211)))


def _require(value,message):
    if not value:raise GameDataError('Actor fixture: '+message)


def metadata(mirror=False):
    """Return a fresh JSON-friendly description; no live/native observations."""
    _require(type(mirror) is bool,'mirror option must be Boolean')
    return {key:list(value)if isinstance(value,tuple)else value for key,value in
            (MIRROR_METADATA if mirror else METADATA).items()}


def mirror_metadata():
    return metadata(True)


def _float32(value):
    return struct.unpack('<f',struct.pack('<f',value))[0]


def _position(raw):
    return tuple(_float32(signed64(get_uint(raw,number))/2**32)for number in (1,2,3))


def _position_bytes(values):
    # Original Vector3 ToProto's qualified float32 -> signed Q32.32 rule.
    return b''.join(field_uint(number,int(_float32(value)*2**32)&(2**64-1))
                    for number,value in enumerate(values,1))


class ActorFixtureTemplate(GameTemplate):
    """Normal build_match still owns roster/decks/cosmetics and wire receipts."""
    fixture_metadata=METADATA

    def build_match(self,roster,decks,seed=None,game_name=None,**kwargs):
        # DedicatedServer supplies a random seed positionally. Override ONLY in
        # this explicit fixture, without changing caller-owned decks or roster.
        _require(kwargs.get('game_mode') in (None,1),'requires Custom1v1 topology')
        description=self.fixture_metadata
        match=super().build_match(roster,decks,description['seed'],game_name,**kwargs)
        _require(all(player.army_id==player.slot and player.ai_profile_id==0 for player in match.roster),
                 'requires two human slots with their ordinary army assignments')
        attacker=description['attacker_slot']
        _require(1 in match.decks_by_slot[attacker],f'slot{attacker} must choose a legal deck containing Gunbot1')
        return match


def make_template(base:GameTemplate,assets:Path,*,mirror=False)->GameTemplate:
    """Build a separate explicit fixture; never change base or force a deck.

    A whole prepared MatchData, including its gzip/hash fields, comes from the
    normal builder so authority and both clients consume the same bootstrap.
    Assets are existing imported catalog/descriptor inputs, never copied here.
    """
    _require(type(mirror) is bool,'mirror option must be Boolean')
    _require(isinstance(base,GameTemplate)and not isinstance(base,ActorFixtureTemplate),
             'requires an ordinary source GameTemplate, not an already transformed fixture')
    _require(base.game_mode==1 and base.player_count==2,'requires the original two-army map')
    assets=Path(assets)
    _require((assets/'unit-catalog.json').is_file()and(assets/'descriptors').is_dir(),
             'requires imported catalog and descriptor paths')
    _require(1 in base.catalog and 12 in base.entity_abilities.get(1,()),'Gunbot1/Move12 metadata unavailable')
    initial=get_repeated_bytes(base.raw_game_data,2)
    _require(len(initial)==10,'requires the original ten initial map entities')
    for index,action in enumerate(initial):
        entity=get_bytes(action,2,required=True)
        _require(get_uint(entity,1)==(3 if index in (0,5) else 19) and
                 get_uint(entity,2)==(0 if index<5 else 1),'initial map entity IDs/types/armies differ')
    description=MIRROR_METADATA if mirror else METADATA
    victim=get_bytes(initial[description['victim_core_id']],2,required=True)
    position=_position(get_bytes(victim,3,required=True))
    expected=tuple(-value for value in _CORE_POSITION) if mirror else _CORE_POSITION
    _require(position==expected,'original victim Core position differs from the qualified fixture')
    _require(get_uint(base.global_config,27)==6*2**32 and get_uint(base.global_config,29)==21474836400,
             'original reveal/delayed-command startup differs')
    entities=[];core_count=0
    for entity in get_repeated_bytes(base.game_config,1):
        if get_uint(entity,1)==3:
            attributes=[];health_count=0
            for attribute in get_repeated_bytes(entity,8):
                if get_uint(attribute,1)==4:
                    attribute=replace_fields(attribute,{2:[field_uint(2,100*2**32)]});health_count+=1
                attributes.append(attribute)
            _require(health_count==1,'Core requires its unique original health attribute')
            entity=replace_fields(entity,{8:[field_bytes(8,value)for value in attributes]});core_count+=1
        entities.append(entity)
    _require(core_count==1,'requires a unique Core3 definition')
    global_config=replace_fields(base.global_config,{4:[field_uint(4,7*2**32)],22:[]})
    config=replace_fields(base.game_config,{1:[field_bytes(1,value)for value in entities],
                                           3:[field_bytes(3,global_config)]})
    spawn=(position[0]+(-4.0 if mirror else 4.0),position[1],position[2])
    rotation=field_uint(2,int((1 if mirror else -1)*math.sqrt(.5)*2**32)&(2**64-1))+field_uint(4,int(math.sqrt(.5)*2**32))
    create=field_uint(1,1)+(field_uint(2,1)if mirror else b'')+field_bytes(3,_position_bytes(spawn))+field_bytes(4,rotation)
    # Army0 is the protobuf default, matching the proven original fixture bytes.
    extra=field_bytes(2,create)
    raw=replace_fields(base.raw_game_data,{1:[field_bytes(1,config)],
        2:[field_bytes(2,action)for action in (*initial,extra)]})
    fixture=ActorFixtureTemplate(raw,catalog_path=assets/'unit-catalog.json',descriptors_path=assets/'descriptors')
    if mirror:fixture.fixture_metadata=MIRROR_METADATA
    fixture.set_allowed_entity_ids(base.allowed_entity_ids)
    return fixture


# Separate explicit mobile control. The original HQ transform above is unchanged.
MOBILE_SEED=20261111
MOBILE_METADATA=MappingProxyType(dict(
    name='original-gunbot-mobile-move-v1',attacker_slot=0,attacker_id=10,attacker_type=1,
    victim_slot=1,victim_id=11,victim_type=1,unit_type=1,health=100,seed=MOBILE_SEED,
    initial_attacker=(-2.0,0.0,0.0),initial_victim=(2.0,0.0,0.0),
    activation_seconds=7,original_reveal_seconds=6,original_delayed_commands_raw=21474836400,
    selection_frame=130,casting_frame=145,escape_physical_frame=150,expected_canonical_frame=151,
    safe_canonical_frames=(151,152),baseline_first_damage_frame=142,baseline_death_frame=153,
    baseline_absent_frame=154,survivor_through_frame=173,attacker_still_dies_frame=153,
    fresh_move_physical_frame=180,observation_last_frame=220,
    target=(-32.0,0.0,0.0),unchanged_core_health=True))


def mobile_metadata():
    """Fixture inputs and retained control timings, not a new runtime result."""
    return {key:list(value)if isinstance(value,tuple)else value for key,value in MOBILE_METADATA.items()}


def _mobile_require(value,message):
    if not value:raise GameDataError('Mobile fixture: '+message)


class MobileFixtureTemplate(ActorFixtureTemplate):
    """Fixture marker also prevents composing either transform over the other."""
    fixture_metadata=MOBILE_METADATA

    def build_match(self,roster,decks,seed=None,game_name=None,**kwargs):
        _mobile_require(kwargs.get('game_mode') in (None,1),'requires Custom1v1 topology')
        # Bypass the HQ fixture's different seed; normal MatchData construction
        # still owns identities, selected decks, cosmetics, gzip and hashes.
        match=GameTemplate.build_match(self,roster,decks,MOBILE_SEED,game_name,**kwargs)
        _mobile_require(all(player.army_id==player.slot and player.ai_profile_id==0 for player in match.roster),
                        'requires two human slots with their ordinary army assignments')
        _mobile_require(all(1 in match.decks_by_slot[slot] for slot in (0,1)),
                        'both human slots must choose legal decks containing Gunbot1')
        return match


def make_mobile_template(base:GameTemplate,assets:Path)->GameTemplate:
    """The retained two-Gunbot initial GameData, without runtime state writes.

    Change only Gunbot health and activation time; append IDs10/11 in original
    action order. Core definitions, global22, all other entities and both chosen
    decks remain caller-owned. The explicit mobile seed differs from the HQ
    control. Native-control timing is retained evidence, not asserted by this
    byte transformation or its authored unit tests.
    """
    _mobile_require(isinstance(base,GameTemplate)and not isinstance(base,ActorFixtureTemplate),
                    'requires an ordinary source GameTemplate, not an already transformed fixture')
    _mobile_require(base.game_mode==1 and base.player_count==2,'requires the original two-army map')
    assets=Path(assets)
    _mobile_require((assets/'unit-catalog.json').is_file()and(assets/'descriptors').is_dir(),
                    'requires imported catalog and descriptor paths')
    _mobile_require(1 in base.catalog and 12 in base.entity_abilities.get(1,()),'Gunbot1/Move12 metadata unavailable')
    initial=get_repeated_bytes(base.raw_game_data,2)
    _mobile_require(len(initial)==10,'requires the original ten initial map entities')
    for index,action in enumerate(initial):
        entity=get_bytes(action,2,required=True)
        _mobile_require(get_uint(entity,1)==(3 if index in (0,5) else 19)and
                        get_uint(entity,2)==(0 if index<5 else 1),'initial map entity IDs/types/armies differ')
    _mobile_require(get_uint(base.global_config,27)==6*2**32 and get_uint(base.global_config,29)==21474836400,
                    'original reveal/delayed-command startup differs')
    definitions=[];gunbots=0
    for entity in get_repeated_bytes(base.game_config,1):
        if get_uint(entity,1)==1:
            attributes=[];health=0
            for attribute in get_repeated_bytes(entity,8):
                if get_uint(attribute,1)==4:
                    attribute=replace_fields(attribute,{2:[field_uint(2,100*2**32)]});health+=1
                attributes.append(attribute)
            _mobile_require(health==1,'Gunbot requires its unique original health attribute')
            entity=replace_fields(entity,{8:[field_bytes(8,value)for value in attributes]});gunbots+=1
        definitions.append(entity)
    _mobile_require(gunbots==1,'requires a unique Gunbot1 definition')
    global_config=replace_fields(base.global_config,{4:[field_uint(4,7*2**32)]})
    config=replace_fields(base.game_config,{1:[field_bytes(1,value)for value in definitions],
                                          3:[field_bytes(3,global_config)]})
    for army,point,sign in ((0,(-2.0,0.0,0.0),1),(1,(2.0,0.0,0.0),-1)):
        rotation=field_uint(2,int(sign*math.sqrt(.5)*2**32)&(2**64-1))+field_uint(4,int(math.sqrt(.5)*2**32))
        create=(field_uint(1,1)+(field_uint(2,army)if army else b'')+
                field_bytes(3,_position_bytes(point))+field_bytes(4,rotation))
        initial=(*initial,field_bytes(2,create))
    raw=replace_fields(base.raw_game_data,{1:[field_bytes(1,config)],2:[field_bytes(2,action)for action in initial]})
    fixture=MobileFixtureTemplate(raw,catalog_path=assets/'unit-catalog.json',descriptors_path=assets/'descriptors')
    fixture.set_allowed_entity_ids(base.allowed_entity_ids)
    return fixture
