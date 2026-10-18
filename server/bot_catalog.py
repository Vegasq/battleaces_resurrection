"""Validate locally exported bot data and freeze a profile-compatible selection.

Weighted profile/uniform deck selection, English random names and uniform
supported strength are replacement policy, not the retired service's RNG.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import secrets
from types import MappingProxyType

from .game_data import decode_deck
from .protobuf_wire import field_bytes, field_packed_uint, get_repeated_uint, parse_fields, replace_fields

Q32 = 1 << 32
MAX_CATALOG_BYTES = 4 * 1024 * 1024


def require(condition, message):
    if not condition: raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate bot catalog key')
        result[key] = value
    return result


def uint(value, *, positive=False):
    require(type(value) is int and int(positive) <= value <= 0xffffffff, 'invalid bot catalog integer')
    return value


def values(value, maximum, *, empty=False):
    require(isinstance(value, list) and int(not empty) <= len(value) <= maximum, 'bot catalog collection limit')
    return value


def valid_name(value, maximum=96):
    return (isinstance(value, str) and 0 < len(value.encode('utf-8')) <= maximum and
            not any(ord(c) < 32 or ord(c) == 127 for c in value))


def cosmetic_keys(deck, allowed):
    result = []
    for entitlement in decode_deck(deck)['entitlements']:
        fields = parse_fields(entitlement, max_bytes=4096, max_fields=128)
        require(all((f.number == 1 and f.wire_type == 0 and f.value <= 0xffffffff) or
                    (f.number == 3 and f.wire_type in (0, 2)) for f in fields) and
                sum(f.number == 1 for f in fields) <= 1, 'unsupported bot cosmetic entitlement')
        result.extend(get_repeated_uint(entitlement, 3, max_values=128))
    require(len(result) <= 128 and len(set(result)) == len(result) and set(result) <= allowed,
            'unknown/duplicate bot cosmetic key')
    return tuple(result)


@dataclass(frozen=True)
class BotDeck:
    kind: int
    reference: int
    name: str
    portrait: int
    banner: int
    message: bytes
    units: tuple[int, ...]


@dataclass(frozen=True)
class BotChoice:
    profile: int
    source_mode: int
    name: str
    portrait: int
    banner: int
    deck: BotDeck
    deck_message: bytes
    difficulty: str
    strength: tuple[int, int, int]


class BotCatalog:
    def __init__(self, directory, *, template=None, rules=None):
        path = Path(directory)/'bot-catalog.json'
        require(path.stat().st_size <= MAX_CATALOG_BYTES, 'bot catalog byte limit')
        self.raw = path.read_bytes()
        require(len(self.raw) <= MAX_CATALOG_BYTES, 'bot catalog byte limit')
        data = json.loads(self.raw, object_pairs_hook=unique_object)
        require(isinstance(data, dict) and (data.get('schema'), data.get('build'), data.get('names_language')) ==
                (1, 37822, 'en') and data.get('character_names_language') == 'exporting_client_locale',
                'unsupported bot catalog')
        cosmetics = tuple(uint(v, positive=True) for v in values(data.get('cosmetic_ids'), 4096))
        require(len(set(cosmetics)) == len(cosmetics), 'duplicate installed cosmetic ID')
        self.cosmetic_ids = frozenset(cosmetics)
        self.portraits, self.banners = (tuple(uint(v, positive=True) for v in values(data.get(key), 1024))
                                       for key in ('portraits', 'banners'))
        require(set(self.portraits + self.banners) <= self.cosmetic_ids, 'bot cosmetic pool ID missing')
        names = values(data.get('names'), 100000)
        require(all(isinstance(name, str) and len(name.encode('utf-8')) <= 512 for name in names), 'invalid bot name pool')
        self.names = tuple(name for name in names if valid_name(name, 32))
        require(self.names, 'no usable installed bot names')
        profiles = {}
        for row in values(data.get('profiles'), 256):
            require(isinstance(row, dict), 'invalid bot profile row')
            profile, mode = uint(row.get('profile'), positive=True), row.get('mode')
            require(profile not in profiles and type(mode) is int and mode in (1, 2, 4, 5), 'duplicate/invalid bot profile')
            if rules is not None:
                require(profile in rules.entries and rules.entries[profile]['enabled'] and
                        rules.entries[profile]['mode'] == mode, 'bot catalog/rule profile mismatch')
            decks = []
            for deck in values(row.get('decks'), 128):
                require(isinstance(deck, dict) and type(deck.get('kind')) is int and deck['kind'] in (0, 1, 2),
                        'invalid bot deck kind')
                kind, reference = deck['kind'], uint(deck.get('reference'))
                require((kind == 0) == (reference == 0), 'invalid bot deck reference')
                raw = deck.get('deck_hex')
                require(isinstance(raw, str) and 2 <= len(raw) <= 8192 and len(raw) % 2 == 0 and
                        all(c in '0123456789abcdef' for c in raw), 'invalid bot deck encoding')
                message = bytes.fromhex(raw)
                fields = parse_fields(message, max_bytes=4096, max_fields=128)
                require(all(f.number in (1, 2, 3) and f.wire_type in ((0, 2) if f.number < 3 else (2,)) for f in fields),
                        'unsupported bot deck field')
                decoded = decode_deck(message)
                units, groups = tuple(decoded['units']), tuple(decoded['active_ability_groups'])
                require(len(units) == 8 and len(set(units)) == 8 and all(0 < unit <= 0xffffffff for unit in units)
                        and len(groups) == 4 and all(0 <= group <= 0xffffffff for group in groups), 'invalid bot deck slots')
                if template is not None: template.validate_deck(units)
                keys = cosmetic_keys(message, self.cosmetic_ids)
                portrait, banner = uint(deck.get('portrait')), uint(deck.get('banner'))
                name = deck.get('name')
                if kind == 1:
                    require(valid_name(name) and portrait in keys and banner in keys,
                            'character identity differs from equipped deck')
                else:
                    require(name == '' and portrait == banner == 0 and not keys, 'random deck has unexpected character identity')
                decks.append(BotDeck(kind, reference, name, portrait, banner, message, units))
            profiles[profile] = (mode, tuple(decks))
        modes, referenced = {}, set()
        for row in values(data.get('modes'), 4):
            require(isinstance(row, dict) and type(row.get('mode')) is int and row['mode'] in (1, 2, 4, 5)
                    and row['mode'] not in modes, 'invalid/duplicate bot mode')
            pools = {}
            for role in ('opponents', 'teammates'):
                pool, total = [], 0
                for entry in values(row.get(role), 128, empty=role == 'teammates'):
                    require(isinstance(entry, dict), 'invalid weighted bot entry')
                    profile, weight = uint(entry.get('profile'), positive=True), uint(entry.get('weight'), positive=True)
                    require(profile in profiles and profiles[profile][0] == row['mode'] and
                            profile not in {p for p, _ in pool} and weight <= 1000000, 'invalid bot mode/profile weight')
                    total += weight; require(total <= 1000000, 'bot weight sum limit')
                    pool.append((profile, weight)); referenced.add(profile)
                pools[role] = tuple(pool)
            modes[row['mode']] = MappingProxyType(pools)
        require(set(modes) == {1, 2, 4, 5} and referenced == set(profiles), 'incomplete/unreferenced bot mode inventory')
        strengths = {}
        for row in values(data.get('strengths'), 3):
            require(isinstance(row, dict) and type(row.get('profile')) is int and row['profile'] in (17, 18, 19)
                    and row['profile'] not in strengths, 'invalid difficulty profile')
            strength = tuple(row.get(key) for key in ('resource_q', 'damage_q', 'health_q'))
            require(all(type(v) is int and 0 < v <= 4*Q32 for v in strength), 'difficulty outside supported bounds')
            strengths[row['profile']] = strength
        require(set(strengths) == {17, 18, 19} and strengths[18] == (Q32, Q32, Q32), 'missing difficulty or changed Normal baseline')
        self.profiles, self.modes, self.strengths = map(MappingProxyType, (profiles, modes, strengths))

    def choose(self, mode, *, role='opponents', excluded_names=(), difficulty=None, randbelow=secrets.randbelow):
        require(type(mode) is int and mode in self.modes and role in ('opponents', 'teammates'), 'unsupported bot selection mode/role')
        # Explicit replacement policy: mode5 has no shipped teammate pool. Use
        # the shipped team-mode ally profile, preserving mode5 opponent tactics.
        source_mode = 2 if mode == 5 and role == 'teammates' and not self.modes[5][role] else mode
        pool = self.modes[source_mode][role]
        require(pool, 'mode has no bot pool for this role')
        roll = randbelow(sum(weight for _, weight in pool))
        profile = None
        for candidate, weight in pool:
            if roll < weight: profile = candidate; break
            roll -= weight
        require(profile is not None, 'bot selection random value outside bound')
        excluded = frozenset(excluded_names)
        decks = tuple(deck for deck in self.profiles[profile][1] if deck.kind != 1 or deck.name not in excluded)
        require(decks, 'no distinct character name available')
        deck = decks[randbelow(len(decks))]
        if deck.kind == 1:
            name, portrait, banner, message = deck.name, deck.portrait, deck.banner, deck.message
        else:
            names = tuple(name for name in self.names if name not in excluded)
            require(names, 'no distinct installed bot name available')
            name, portrait, banner = names[randbelow(len(names))], self.portraits[randbelow(len(self.portraits))], self.banners[randbelow(len(self.banners))]
            message = replace_fields(deck.message, {3: [field_bytes(3, field_packed_uint(3, (portrait, banner)))]})
        choices = ('easy', 'normal', 'hard')
        difficulty = choices[randbelow(3)] if difficulty is None else difficulty
        require(difficulty in choices, 'unsupported bot difficulty')
        return BotChoice(profile, source_mode, name, portrait, banner, deck, message, difficulty,
                         self.strengths[17+choices.index(difficulty)])
