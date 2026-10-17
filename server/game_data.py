"""Server-owned match construction and bounded input validation for build37822.

Field numbers come from the embedded protobuf descriptors retained under
investigation/network/descriptors. Untouched trusted-template fields keep their
original wire bytes. This module does not emulate native resource/ownership rules.
"""
from __future__ import annotations

import hashlib
import json
import math
import secrets
import struct
import uuid
import zlib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

try:
    from .protobuf_wire import (WireError, decode_varint, field_bytes, field_float,
                                field_packed_uint, field_uint, get_bytes,
                                get_repeated_bytes, get_repeated_uint, get_uint,
                                parse_fields, replace_fields, signed64)
except ImportError:  # Also support the server's direct-script invocation.
    from protobuf_wire import (WireError, decode_varint, field_bytes, field_float,
                               field_packed_uint, field_uint, get_bytes,
                               get_repeated_bytes, get_repeated_uint, get_uint,
                               parse_fields, replace_fields, signed64)

from .paths import ROOT, ASSETS
DEFAULT_TEMPLATE = ASSETS / "map-1v1.pb.gz"
DEFAULT_CATALOG = ASSETS / "unit-catalog.json"
DEFAULT_DESCRIPTORS = ASSETS / "descriptors"
MAX_RAW_GAME_DATA = 16 * 1024 * 1024
MAX_INPUT_BYTES = 65536
MAX_ACTIONS = 256


class GameDataError(ValueError):
    pass


class InputError(GameDataError):
    pass


def _require(condition, reason):
    if not condition:
        raise GameDataError(reason)


def _uint(value, bits=32):
    _require(type(value) is int and 0 <= value < (1 << bits), f"expected uint{bits}")
    return value


def canonical_gzip(data: bytes) -> bytes:
    """Fixed zero timestamp, absent filename, and OS255; deterministic server bytes."""
    compressor = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    compressed = compressor.compress(data) + compressor.flush()
    return b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff" + compressed + struct.pack(
        "<II", zlib.crc32(data) & 0xFFFFFFFF, len(data) & 0xFFFFFFFF)


def decompress_game_data(data: bytes) -> bytes:
    _require(isinstance(data, bytes) and len(data) <= 2 * 1024 * 1024, "gzip GameData size limit")
    try:
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        raw = decoder.decompress(data, MAX_RAW_GAME_DATA + 1)
        _require(len(raw) <= MAX_RAW_GAME_DATA and not decoder.unconsumed_tail, "expanded GameData size limit")
        _require(decoder.eof and not decoder.unused_data, "truncated gzip or trailing/concatenated data")
        return raw
    except zlib.error as error:
        raise GameDataError("invalid gzip GameData") from error


def encode_identity(player_id: int, name: str, *, is_aliased=True, ai_profile_id=0) -> bytes:
    _uint(player_id, 64)
    _uint(ai_profile_id)
    _require(player_id != 0 and isinstance(name, str), "player identity requires ID and name")
    encoded = name.encode("utf-8")
    _require(0 < len(encoded) <= 96 and not any(ord(c) < 32 for c in name), "invalid player display name")
    handle = field_uint(1, player_id) + (field_uint(2, 1) if is_aliased else b"")
    named = field_bytes(1, handle) + field_bytes(2, encoded) + field_bytes(4, encoded)
    return field_bytes(1, named) + (field_uint(2, ai_profile_id) if ai_profile_id else b"")


def decode_identity(data: bytes) -> dict:
    named = get_bytes(data, 1, required=True)
    handle = get_bytes(named, 1, required=True)
    return {"player_id": get_uint(handle, 1), "is_aliased": bool(get_uint(handle, 2)),
            "ai_profile_id": get_uint(data, 2),
            "name": get_bytes(named, 2).decode("utf-8"),
            "filtered_name": get_bytes(named, 4).decode("utf-8")}


def encode_deck(units: Sequence[int], active_ability_groups: Sequence[int] = (0, 0, 0, 0)) -> bytes:
    return field_packed_uint(1, units) + field_packed_uint(2, active_ability_groups)


def decode_deck(data: bytes) -> dict:
    return {"units": get_repeated_uint(data, 1, max_values=8),
            "active_ability_groups": get_repeated_uint(data, 2, max_values=4),
            "entitlements": get_repeated_bytes(data, 3)}


def encode_player_input(identity: bytes, actions: Sequence[bytes] = ()) -> bytes:
    return field_bytes(1, identity) + b"".join(field_bytes(2, action) for action in actions)


def decode_player_input(data: bytes) -> dict:
    return {"identity": decode_identity(get_bytes(data, 1, required=True)),
            "actions": get_repeated_bytes(data, 2),
            "debug_client_frame_markers": get_repeated_uint(data, 3, max_values=256)}


def encode_frame(frame: int, inputs_by_slot: Mapping[int, bytes] | Sequence[bytes]) -> bytes:
    """Serialize InputActions; omit empty players exactly as the native bridge does."""
    _require(type(frame) is int and 0 <= frame <= 0x7FFFFFFF, "frame outside int32 range")
    inputs = dict(enumerate(inputs_by_slot)) if not isinstance(inputs_by_slot, Mapping) else inputs_by_slot
    _require(set(inputs) == {0, 1}, "a frame requires both player slots")
    # Protobuf C# omits default GameFrame0 and SpectatorCount0 on serialization.
    result = (field_uint(1, frame) if frame else b"") + field_uint(2, 20) + field_uint(3, 50) + field_float(4, 1.0)
    for slot in (0, 1):
        if inputs[slot] and get_repeated_bytes(inputs[slot], 2):
            result += field_bytes(6, inputs[slot])
    return result


def decode_frame(data: bytes) -> dict:
    speed = [field for field in parse_fields(data) if field.number == 4]
    if len(speed) != 1 or speed[0].wire_type != 5:
        raise WireError("frame requires one fixed32 speed")
    return {"frame": get_uint(data, 1), "frames_per_second": get_uint(data, 2),
            "timestep_ms": get_uint(data, 3), "speed": struct.unpack("<f", speed[0].value)[0],
            "players": get_repeated_bytes(data, 6), "spectator_count": get_uint(data, 7)}


@dataclass(frozen=True)
class PlayerSpec:
    slot: int
    player_id: int
    name: str
    army_id: int


@dataclass(frozen=True)
class MatchData:
    raw_game_data: bytes
    gzip_game_data: bytes
    game_config: bytes
    sha256: str
    raw_sha256: str
    game_name: str
    game_handle: bytes
    seed: int
    roster: tuple[PlayerSpec, ...]
    identities_by_slot: Mapping[int, bytes]
    decks_by_slot: Mapping[int, tuple[int, ...]]
    active_ability_groups_by_slot: Mapping[int, tuple[int, ...]]
    deck_messages_by_slot: Mapping[int, bytes]
    armies_by_slot: Mapping[int, bytes]


class GameTemplate:
    @classmethod
    def load(cls, path=DEFAULT_TEMPLATE, *, catalog_path=DEFAULT_CATALOG,
             descriptors_path=DEFAULT_DESCRIPTORS):
        compressed = Path(path).read_bytes()
        instance = cls(decompress_game_data(compressed), catalog_path=catalog_path,
                       descriptors_path=descriptors_path)
        instance.source_path = str(Path(path).resolve())
        instance.source_sha256 = hashlib.sha256(compressed).hexdigest()
        return instance

    def __init__(self, raw_game_data: bytes, *, catalog_path=DEFAULT_CATALOG,
                 descriptors_path=DEFAULT_DESCRIPTORS):
        self.raw_game_data = raw_game_data
        self.source_path = None
        self.source_sha256 = None
        self.raw_sha256 = hashlib.sha256(raw_game_data).hexdigest()
        self.game_config = get_bytes(raw_game_data, 1, required=True)
        self.global_config = get_bytes(self.game_config, 3, required=True)
        self.slot_flags = get_repeated_uint(get_bytes(self.global_config, 24, required=True), 1)
        _require(len(self.slot_flags) == 8 and all(self.slot_flags), "template requires eight nonzero slot masks")
        army_messages = get_repeated_bytes(self.game_config, 2)
        self.armies = {get_uint(army, 1): army for army in army_messages}
        _require(len(army_messages) == 2 and set(self.armies) == {0, 1}, "template requires exactly armies0 and1")
        self.template_decks = {army: decode_deck(get_bytes(data, 3, required=True))["units"] for army, data in self.armies.items()}
        self.catalog = {}
        self.entity_abilities = {}
        self.abilities = {}
        self.build_ability_slots = {}
        for entity in get_repeated_bytes(self.game_config, 1):
            entity_id = get_uint(entity, 1)
            _require(entity_id not in self.catalog, "duplicate template entity ID")
            cost, prerequisite = get_bytes(entity, 16), get_bytes(entity, 17)
            flags = get_uint(entity, 21)
            self.catalog[entity_id] = {"id": entity_id, "entity_id": entity_id, "deck_slot_flags": flags,
                "slot_indices": [index for index, mask in enumerate(self.slot_flags) if flags & mask == mask],
                "resource_cost_raw": {"health_percent": signed64(get_uint(cost, 1)),
                                      "primary_resource": signed64(get_uint(cost, 2)),
                                      "secondary_resource": signed64(get_uint(cost, 3))},
                "supply_cost_raw": signed64(get_uint(entity, 4)),
                "prerequisite": {"tech_building": get_uint(prerequisite, 1),
                                 "tech_tier": get_uint(prerequisite, 2),
                                 "label_filter_hex": get_bytes(prerequisite, 3).hex()}}
            self.entity_abilities[entity_id] = frozenset(get_repeated_uint(entity, 7))
        for ability in get_repeated_bytes(self.game_config, 10):
            key = get_uint(ability, 8)
            _require(key not in self.abilities, "duplicate template ability key")
            self.abilities[key] = ability
            if any(field.number == 25 for field in parse_fields(ability)):
                self.build_ability_slots[key] = get_uint(get_bytes(ability, 25), 1)
        self.runtime_catalog = None
        self.allowed_entity_ids = frozenset(key for key, value in self.catalog.items() if value["deck_slot_flags"])
        self.premade_decks = []
        self.default_decks_provisional = True
        if catalog_path is not None and Path(catalog_path).exists():
            runtime = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
            _require(tuple(runtime["slot_flags"]) == self.slot_flags, "runtime/template deck slot mismatch")
            allowed = []
            for unit in runtime["units"]:
                entity_id = unit["id"]
                if entity_id in self.catalog:
                    _require(self.catalog[entity_id]["deck_slot_flags"] == unit["menu_slot_flags"],
                             f"runtime/template entity flags mismatch for {entity_id}")
                    if "active_ability_groups" in unit:
                        groups = unit["active_ability_groups"]
                        _require(isinstance(groups, list) and all(type(group) is int and 0 < group <= 0xFFFFFFFF for group in groups),
                                 f"invalid runtime active groups for unit {entity_id}")
                    self.catalog[entity_id].update(unit)
                if unit["release_deck_playable"] and unit["menu_entity_present"] and entity_id in self.catalog:
                    allowed.append(entity_id)
            self.allowed_entity_ids = frozenset(allowed)
            self.runtime_catalog = runtime
            for preset in runtime.get("premade_decks", []) + runtime.get("recommended_decks", []):
                try:
                    units = self.validate_deck(preset["units"])
                except GameDataError:
                    continue
                groups = tuple(preset.get("active_ability_groups", ()))
                _require(len(groups) <= 4 and all(type(x) is int and 0 <= x <= 0xFFFFFFFF for x in groups), "invalid preset active groups")
                self.premade_decks.append({"name": preset["name"], "units": units, "active_ability_groups": groups})
            self.default_decks_provisional = False
        starter = next((preset for preset in self.premade_decks if preset["name"] == "Starter"), None)
        if starter is None and self.premade_decks:
            starter = self.premade_decks[0]
        if starter:
            default = starter["units"]
        else:
            default = self._complete_template_deck(self.template_decks[0])
        self.default_decks = {0: default, 1: default}
        self.descriptors_path = Path(descriptors_path)

    def _complete_template_deck(self, deck):
        reserved = {value for index, value in enumerate(deck) if value in self.allowed_entity_ids and
                    self.catalog[value]["deck_slot_flags"] & self.slot_flags[index] == self.slot_flags[index]}
        result = []
        for index, mask in enumerate(self.slot_flags):
            value = deck[index] if index < len(deck) else 0
            if value not in reserved or value in result or self.catalog[value]["deck_slot_flags"] & mask != mask:
                value = next((key for key in sorted(self.allowed_entity_ids) if key not in reserved and key not in result
                              and self.catalog[key]["deck_slot_flags"] & mask == mask), None)
            _require(value is not None, "cannot complete template deck")
            result.append(value)
        return self.validate_deck(result)

    def set_allowed_entity_ids(self, entity_ids):
        values = frozenset(entity_ids)
        _require(values and values <= self.allowed_entity_ids, "allowlist may only restrict known playable entities")
        previous = self.allowed_entity_ids
        self.allowed_entity_ids = values
        try:
            for deck in self.default_decks.values():
                self.validate_deck(deck)
        except GameDataError:
            self.allowed_entity_ids = previous
            raise

    def validate_deck(self, deck) -> tuple[int, ...]:
        _require(isinstance(deck, (tuple, list)) and len(deck) == 8, "deck must contain eight unit IDs")
        values = tuple(_uint(value) for value in deck)
        _require(len(set(values)) == 8, "deck unit IDs must be unique")
        for index, entity_id in enumerate(values):
            _require(entity_id in self.allowed_entity_ids, f"unit {entity_id} is not a playable catalog unit")
            mask = self.slot_flags[index]
            _require(self.catalog[entity_id]["deck_slot_flags"] & mask == mask,
                     f"unit {entity_id} is invalid in deck slot {index}")
        if all("active_ability_groups" in self.catalog[entity_id] for entity_id in values):
            groups = {group for entity_id in values for group in self.catalog[entity_id]["active_ability_groups"]}
            _require(len(groups) <= 4, "deck has more than four selectable active ability groups")
        return values

    def catalog_serializable(self):
        return [dict(self.catalog[key]) for key in sorted(self.allowed_entity_ids)]

    def active_groups_for_deck(self, deck) -> tuple[int, ...]:
        units = self.validate_deck(deck)
        matches = [preset["active_ability_groups"] for preset in self.premade_decks if preset["units"] == units]
        if matches:
            _require(all(groups == matches[0] for groups in matches), "ambiguous authored active groups")
            return matches[0]
        if all("active_ability_groups" in self.catalog[entity_id] for entity_id in units):
            # The shipped Deck.GetSelectableAbilities uses a SortedSet. Runtime
            # EntityConfig.GetActiveAbilityGroups provides the exact membership.
            groups = sorted({group for entity_id in units for group in self.catalog[entity_id]["active_ability_groups"]})
            return tuple(groups + [0] * (4 - len(groups)))
        # Older trusted catalog captures lack this runtime method's metadata.
        # Retain template groups instead of inventing a unit-to-group mapping.
        return decode_deck(get_bytes(self.armies[0], 3))["active_ability_groups"]

    def build_match(self, roster, decks, seed=None, game_name=None) -> MatchData:
        _require(isinstance(roster, (tuple, list)) and len(roster) == 2, "two roster entries required")
        players = []
        for index, entry in enumerate(roster):
            if isinstance(entry, PlayerSpec):
                player = entry
            else:
                _require(isinstance(entry, Mapping), "roster entry must be PlayerSpec or mapping")
                slot = entry.get("slot", index)
                player = PlayerSpec(slot, entry.get("player_id", slot + 1),
                                    entry.get("name", f"LAN Player {slot + 1}"), entry.get("army_id", slot))
            _require(type(player.slot) is int and player.slot in (0, 1)
                     and type(player.army_id) is int and player.army_id in self.armies, "invalid player slot/army")
            players.append(player)
        players.sort(key=lambda player: player.slot)
        _require({player.slot for player in players} == {0, 1} and len({player.army_id for player in players}) == 2,
                 "roster needs distinct slots and armies")
        _require(len({player.player_id for player in players}) == 2, "roster needs distinct player IDs")
        selected = dict(enumerate(decks)) if not isinstance(decks, Mapping) else decks
        _require(set(selected) == {0, 1}, "decks required for both slots")
        seed = secrets.randbits(64) if seed is None else _uint(seed, 64)
        game_name = game_name or f"dedicated-{uuid.uuid4().hex}"
        _require(isinstance(game_name, str) and 0 < len(game_name.encode("utf-8")) <= 128
                 and not any(ord(character) < 32 for character in game_name), "invalid game name")
        identities, deck_ids, groups_by_slot, deck_messages, armies_by_slot = {}, {}, {}, {}, {}
        for player in players:
            slot = player.slot
            units = self.validate_deck(selected[slot])
            groups = self.active_groups_for_deck(units)
            identity = encode_identity(player.player_id, player.name)
            deck_message = encode_deck(units, groups)
            army = replace_fields(self.armies[player.army_id], {
                2: [field_bytes(2, identity)], 3: [field_bytes(3, deck_message)],
                4: [field_uint(4, player.army_id)] if player.army_id else []})
            identities[slot], deck_ids[slot], groups_by_slot[slot] = identity, units, groups
            deck_messages[slot], armies_by_slot[slot] = deck_message, army
        global_config = replace_fields(self.global_config, {number: [] for number in (34, 35, 38, 39, 40, 41, 42, 49)})
        by_army = {player.army_id: armies_by_slot[player.slot] for player in players}
        config = replace_fields(self.game_config, {
            2: [field_bytes(2, by_army[army_id]) for army_id in sorted(by_army)],
            3: [field_bytes(3, global_config)], 35: [], 36: [field_uint(36, 1)],
            38: [field_uint(38, seed)] if seed else []})
        raw = replace_fields(self.raw_game_data, {1: [field_bytes(1, config)]})
        compressed = canonical_gzip(raw)
        return MatchData(raw, compressed, config, hashlib.sha256(compressed).hexdigest(),
                         hashlib.sha256(raw).hexdigest(), game_name, field_bytes(1, game_name.encode("utf-8")), seed,
                         tuple(players), MappingProxyType(identities), MappingProxyType(deck_ids),
                         MappingProxyType(groups_by_slot), MappingProxyType(deck_messages), MappingProxyType(armies_by_slot))


class _Descriptors:
    def __init__(self, directory):
        self.messages, self.enums = {}, {}
        def add_messages(messages, prefix):
            for message in messages:
                name = prefix + "." + message["name"]
                self.messages[name] = message
                for enum in message.get("enums", []):
                    self.enums[name + "." + enum["name"]] = {value["number"] for value in enum["values"]}
                add_messages(message.get("nested_messages", []), name)
        for path in Path(directory).glob("*.proto.json"):
            descriptor = json.loads(path.read_text(encoding="utf-8"))
            prefix = "." + descriptor.get("package", "")
            add_messages(descriptor.get("messages", []), prefix)
            for enum in descriptor.get("enums", []):
                self.enums[prefix + "." + enum["name"]] = {value["number"] for value in enum["values"]}

    def validate(self, data, name, *, depth=0, budget=None):
        if budget is None:
            budget = [16384]
        if depth > 16 or name not in self.messages:
            raise InputError("input schema/depth unsupported")
        definitions = {field["number"]: field for field in self.messages[name].get("fields", [])}
        seen, oneofs = set(), set()
        for field in parse_fields(data, max_bytes=MAX_INPUT_BYTES, max_fields=4096):
            budget[0] -= 1
            if budget[0] < 0:
                raise InputError("input field complexity limit")
            definition = definitions.get(field.number)
            if definition is None:
                raise InputError(f"unknown field {field.number} in {name}")
            repeated = definition.get("label") == 3
            if not repeated and field.number in seen:
                raise InputError("duplicate singular input field")
            seen.add(field.number)
            if "oneof_index" in definition:
                oneof = definition["oneof_index"]
                if oneof in oneofs:
                    raise InputError("multiple input oneof alternatives")
                oneofs.add(oneof)
            kind = definition["type"]
            expected = 1 if kind in (1, 6, 16) else 5 if kind in (2, 7, 15) else 2 if kind in (9, 11, 12) else 0
            if repeated and kind not in (9, 11, 12) and field.wire_type == 2:
                value_bytes, offset, count = field.value, 0, 0
                while offset < len(value_bytes):
                    if expected == 0:
                        value, offset = decode_varint(value_bytes, offset)
                    else:
                        size = 8 if expected == 1 else 4
                        if offset + size > len(value_bytes):
                            raise InputError("truncated packed fixed scalar")
                        value = value_bytes[offset:offset + size]
                        offset += size
                    self._scalar(kind, value, definition)
                    count += 1
                    if count > 4096:
                        raise InputError("packed scalar count limit")
            elif field.wire_type != expected:
                raise InputError("input field wire type mismatch")
            elif kind == 11:
                self.validate(field.value, definition["type_name"], depth=depth + 1, budget=budget)
            elif kind == 9:
                if len(field.value) > 256:
                    raise InputError("input string size limit")
                field.value.decode("utf-8")
            elif kind != 12:
                self._scalar(kind, field.value, definition)

    def _scalar(self, kind, value, definition):
        if kind in (1, 2) and not math.isfinite(struct.unpack("<d" if kind == 1 else "<f", value)[0]):
            raise InputError("nonfinite input float")
        if kind == 8 and value not in (0, 1):
            raise InputError("noncanonical boolean")
        if kind in (13, 17) and value > 0xFFFFFFFF:
            raise InputError("uint32 input overflow")
        if kind == 5 and not -(1 << 31) <= signed64(value) < (1 << 31):
            raise InputError("int32 input overflow")
        if kind == 14 and signed64(value) not in self.enums.get(definition["type_name"], set()):
            raise InputError("unknown input enum value")


class InputValidation:
    def __init__(self, match: MatchData, template: GameTemplate, *, entity_lookup=None):
        self.match, self.template, self.entity_lookup = match, template, entity_lookup
        self.descriptors = _Descriptors(template.descriptors_path)
        self.players = {player.slot: player for player in match.roster}

    def validate_player_input(self, slot: int, blob: bytes) -> bytes:
        try:
            if slot not in self.players or not isinstance(blob, bytes) or len(blob) > MAX_INPUT_BYTES:
                raise InputError("invalid input slot/size")
            if not blob:
                return encode_player_input(self.match.identities_by_slot[slot])
            self.descriptors.validate(blob, ".game_pb.InputActionsByPlayer")
            if any(field.number == 3 for field in parse_fields(blob)):
                raise InputError("client debug frame markers are not accepted")
            parsed = decode_player_input(blob)
            identity, expected = parsed["identity"], self.players[slot]
            if identity["player_id"] != expected.player_id or not identity["is_aliased"] or identity["ai_profile_id"]:
                raise InputError("player identity does not match assigned slot")
            actions = parsed["actions"]
            if len(actions) > MAX_ACTIONS:
                raise InputError("too many input actions")
            actions = tuple(self._action(slot, action) for action in actions)
            # Ignore sender-controlled display strings after validating UTF8;
            # use the exact authoritative match identity for both clients/native.
            return encode_player_input(self.match.identities_by_slot[slot], actions)
        except (WireError, UnicodeError) as error:
            raise InputError(str(error)) from error

    def _action(self, slot, action):
        fields = parse_fields(action)
        if len(fields) != 1 or fields[0].wire_type != 2:
            raise InputError("InputAction requires exactly one action case")
        kind, payload = fields[0].number, fields[0].value
        if kind in (2, 4):
            raise InputError("client CreateEntity/debug/config mutations are forbidden")
        if kind == 3:
            return field_bytes(3, self._join(slot, payload))
        elif kind == 1:
            self._execute(slot, payload)
        elif kind == 5:
            if len(parse_fields(payload)) != 1:
                raise InputError("UICommand requires exactly one command case")
        else:
            raise InputError("unsupported input action case")
        return action

    def _join(self, slot, payload):
        if get_uint(payload, 1) != self.players[slot].army_id:
            raise InputError("JoinArmy may not change assigned army")
        deck = decode_deck(get_bytes(payload, 2, required=True))
        if deck["units"] != self.match.decks_by_slot[slot] or deck["active_ability_groups"] != self.match.active_ability_groups_by_slot[slot]:
            raise InputError("JoinArmy deck differs from frozen selected deck")
        army = self.match.armies_by_slot[slot]
        if get_uint(payload, 3) != get_uint(army, 5) or get_uint(payload, 4) != get_uint(army, 6):
            raise InputError("JoinArmy cosmetics differ from server assignment")
        # Shipped Deck.ToProtoRuntime adds CosmeticsUtils entitlement metadata.
        # It is not a unit selection: retain strict units/groups/army validation,
        # then use the server's frozen deck for both native simulation and peers.
        return replace_fields(payload, {2: [field_bytes(2, self.match.deck_messages_by_slot[slot])]})

    def _execute(self, slot, payload):
        groups = get_repeated_bytes(payload, 1)
        if not 1 <= len(groups) <= 256:
            raise InputError("ExecuteCommand needs bounded entity groups")
        command_data = get_bytes(payload, 3, required=True)
        if len(parse_fields(command_data)) != 1:
            raise InputError("CommandData requires exactly one target case")
        for group in groups:
            entity_type, ability = get_uint(group, 1), get_uint(group, 2)
            if entity_type not in self.template.entity_abilities or ability not in self.template.entity_abilities[entity_type]:
                raise InputError("ability is not configured for submitted entity type")
            if self.template.catalog[entity_type]["deck_slot_flags"] and entity_type not in self.match.decks_by_slot[slot]:
                raise InputError("command entity type is absent from selected deck")
            ids = get_repeated_uint(group, 3, max_values=4096)
            if not ids or len(ids) != len(set(ids)) or any(entity_id > 0xFFFFFFFF for entity_id in ids):
                raise InputError("entity IDs must be a bounded unique uint32 list")
            if self.entity_lookup is not None:
                for entity_id in ids:
                    if self.entity_lookup(entity_id) != (self.players[slot].army_id, entity_type):
                        raise InputError("entity is not owned by this player/type")
            if ability in self.template.build_ability_slots:
                deck_slot = self.template.build_ability_slots[ability]
                if not 0 <= deck_slot < len(self.match.decks_by_slot[slot]):
                    raise InputError("build ability targets invalid deck slot")

    def encode_frame(self, frame, inputs_by_slot):
        inputs = dict(enumerate(inputs_by_slot)) if not isinstance(inputs_by_slot, Mapping) else inputs_by_slot
        return encode_frame(frame, {slot: self.validate_player_input(slot, inputs[slot]) for slot in (0, 1)})
