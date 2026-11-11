"""Pure, explicitly authored initial-cohort fixture; no native/runtime writes.

The ordinary map, unit definitions, globals and selected decks stay intact.
Only five initial CreateEntity actions are appended. Timings below describe a
planned control, not observed movement, collision, readiness or prediction.
"""
from __future__ import annotations

import math
from pathlib import Path
import struct
from types import MappingProxyType

from server.game_data import GameDataError, GameTemplate
from server.protobuf_wire import (field_bytes, field_uint, get_bytes,
                                  get_repeated_bytes, get_uint, replace_fields)


SEED = 20261113
Q32 = 2**32
UNIT_RADIUS_RAW = 3435973888
_HOST = (60.0, 0.0, 60.0)
_GUESTS = ((-81.0, 0.0, -61.0), (-81.0, 0.0, -59.0),
           (-79.0, 0.0, -61.0), (-79.0, 0.0, -59.0))
METADATA = MappingProxyType(dict(
    name='original-gunbot-close-formation-v1', seed=SEED, unit_type=1,
    initial_entity_count=15, host_slot=0, host_id=10, initial_host=_HOST,
    guest_slot=1, guest_ids=(11, 12, 13, 14), initial_guests=_GUESTS,
    unit_radius_raw=UNIT_RADIUS_RAW, unit_radius_meters=UNIT_RADIUS_RAW/Q32,
    initial_square_side_meters=2.0, selection_frame=130,
    approach_physical_frame=180, approach_canonical_frame=181,
    approach_native_target=(-70.0, 0.0, -50.0),
    quiet_baseline_first_frame=280, quiet_baseline_last_frame=299,
    fresh_physical_frame=300, fresh_canonical_frame=301,
    fresh_unity_offset=(0.0, 0.0, 16.0),
    remote_physical_frame=320, remote_canonical_frame=321,
    observation_first_frame=130, observation_last_frame=360,
    ordinary_definitions_unchanged=True, ordinary_globals_unchanged=True,
    timings_are_planned_control=True, runtime_validated=False,
    collision_solver_qualified=False))


def metadata():
    """Return detached JSON-friendly inputs; these are not runtime evidence."""
    def copy(value):
        return [copy(item) for item in value] if isinstance(value, tuple) else value
    return {key: copy(value) for key, value in METADATA.items()}


def _require(ok, message):
    if not ok:
        raise GameDataError('Close formation fixture: ' + message)


def _position_bytes(point):
    # Same original float32 -> signed Q32.32 encoding as normal ground targets.
    values = (struct.unpack('<f', struct.pack('<f', value))[0] for value in point)
    return b''.join(field_uint(index, int(value*Q32) & (2**64-1))
                    for index, value in enumerate(values, 1))


class CloseFormationFixtureTemplate(GameTemplate):
    fixture_metadata = METADATA

    def build_match(self, roster, decks, seed=None, game_name=None, **kwargs):
        _require(kwargs.get('game_mode') in (None, 1), 'requires Custom1v1 topology')
        # Normal builder retains ownership of validation, identities, cosmetics,
        # selected decks, compression and hashes. Only this fixture's seed is fixed.
        match = super().build_match(roster, decks, SEED, game_name, **kwargs)
        _require(all(player.army_id == player.slot and player.ai_profile_id == 0
                     for player in match.roster),
                 'requires two human slots with their ordinary army assignments')
        _require(all(1 in match.decks_by_slot[slot] for slot in (0, 1)),
                 'both human slots must choose legal decks containing Gunbot1')
        return match


def make_template(base: GameTemplate, assets: Path) -> GameTemplate:
    """Append host10 and friendly11..14 without changing any configuration.

    No normal gameplay or native-control result follows from constructing these
    bytes. In particular, a configured radius is not a solver separation bound.
    """
    _require(type(base) is GameTemplate,
             'requires an ordinary source GameTemplate, not an already transformed fixture')
    _require(base.game_mode == 1 and base.player_count == 2,
             'requires the original two-army map')
    assets = Path(assets)
    _require((assets/'unit-catalog.json').is_file() and (assets/'descriptors').is_dir(),
             'requires imported catalog and descriptor paths')
    _require(1 in base.allowed_entity_ids and {12, 14} <= base.entity_abilities.get(1, frozenset()),
             'legal Gunbot1/Move12/Hold14 metadata unavailable')
    initial = list(get_repeated_bytes(base.raw_game_data, 2))
    _require(len(initial) == 10, 'requires the original ten initial map entities')
    for index, action in enumerate(initial):
        entity = get_bytes(action, 2, required=True)
        _require(get_uint(entity, 1) == (3 if index in (0, 5) else 19) and
                 get_uint(entity, 2) == (0 if index < 5 else 1),
                 'initial map entity types/armies differ')
    gunbots = [entity for entity in get_repeated_bytes(base.game_config, 1)
               if get_uint(entity, 1) == 1]
    _require(len(gunbots) == 1 and get_uint(gunbots[0], 2) == UNIT_RADIUS_RAW,
             'requires the original Gunbot1 radius')
    attributes = get_repeated_bytes(gunbots[0], 8)
    for kind, expected in ((4, 600*Q32), (0, 27058294784)):
        values = [get_uint(attribute, 2) for attribute in attributes
                  if get_uint(attribute, 1) == kind]
        _require(values == [expected], 'requires original Gunbot1 health/speed')
    _require(all(get_uint(base.global_config, number) == value for number, value in
                 ((4, 2147483640), (27, 6*Q32), (29, 21474836400))),
             'requires ordinary activation/reveal/command startup')
    for army, points in ((0, (_HOST,)), (1, _GUESTS)):
        sign = 1 if army == 0 else -1
        rotation = (field_uint(2, int(sign*math.sqrt(.5)*Q32) & (2**64-1)) +
                    field_uint(4, int(math.sqrt(.5)*Q32)))
        for point in points:
            create = (field_uint(1, 1) + (field_uint(2, army) if army else b'') +
                      field_bytes(3, _position_bytes(point)) + field_bytes(4, rotation))
            initial.append(field_bytes(2, create))
    raw = replace_fields(base.raw_game_data,
                         {2: [field_bytes(2, action) for action in initial]})
    fixture = CloseFormationFixtureTemplate(raw, catalog_path=assets/'unit-catalog.json',
                                            descriptors_path=assets/'descriptors')
    _require(fixture.game_config == base.game_config and fixture.global_config == base.global_config,
             'configuration changed while appending initial units')
    fixture.set_allowed_entity_ids(base.allowed_entity_ids)
    return fixture
