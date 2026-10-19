"""Atomic profile loadouts. Installed catalogs validate every cosmetic slot."""
from __future__ import annotations

import json
from pathlib import Path
import os
import secrets
import stat
from dataclasses import dataclass

from .cosmetics import CosmeticSnapshot

try:
    from .protocol import KEY, require
except ImportError:
    from protocol import KEY, require


MAX_PROFILE_BYTES = 4096


def profile_key(value):
    require(isinstance(value, str) and KEY.fullmatch(value), 'invalid profile key')
    reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {prefix+str(i) for prefix in ('COM', 'LPT') for i in range(1, 10)}
    require(value.upper() not in reserved, 'reserved profile key')
    return value


@dataclass(frozen=True, slots=True)
class ProfileState:
    deck: tuple[int, ...]
    cosmetics: CosmeticSnapshot | None


def cosmetic_state(catalog, selection=None):
    if catalog is None:
        require(selection is None, 'cosmetic catalog required for profile loadout')
        return None
    if selection is None: return catalog.normalize_local()
    if isinstance(selection, CosmeticSnapshot):
        require(selection.catalog_sha256 == catalog.sha256, 'profile cosmetic catalog mismatch')
        selection = selection.slots
    return catalog.validate_selection(selection)


def parse_profile_state(raw, profile_id, template, *, catalog=None):
    """Validate both formats without rewriting a legacy file on read."""
    profile_key(profile_id)
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_PROFILE_BYTES, 'profile size limit')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate profile field')
            result[key] = value
        return result
    try: value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError): raise ValueError('invalid saved profile JSON') from None
    require(isinstance(value, dict) and type(value.get('schema')) is int and value['schema'] in (1, 2)
        and set(value) == ({'schema', 'profile_id', 'deck'} | ({'cosmetics'} if value['schema'] == 2 else set()))
        and value['profile_id'] == profile_id, 'invalid saved profile schema or identity')
    deck = template.validate_deck(value['deck'])
    selection = None
    if value['schema'] == 2:
        saved = value['cosmetics']
        require(catalog is not None, 'cosmetic catalog required to load saved profile')
        require(type(saved) is dict and set(saved) == {'catalog_sha256', 'slots'}
                and saved['catalog_sha256'] == catalog.sha256, 'profile cosmetic catalog mismatch')
        # Keep pair input: converting to a dict would erase duplicate slots.
        selection = saved['slots']
        require(type(selection) is list, 'invalid profile cosmetic slot collection')
    return ProfileState(tuple(deck), cosmetic_state(catalog, selection))


def parse_profile(raw, profile_id, template, *, catalog=None):
    return list(parse_profile_state(raw, profile_id, template, catalog=catalog).deck)


def read_profile_state(path, profile_id, template, *, catalog=None):
    information = path.lstat()
    require(stat.S_ISREG(information.st_mode) and not getattr(information, 'st_file_attributes', 0) & 0x400,
            'profile must be a regular local file')
    require(0 < information.st_size <= MAX_PROFILE_BYTES, 'profile size limit')
    with path.open('rb') as stream: raw = stream.read(MAX_PROFILE_BYTES+1)
    return parse_profile_state(raw, profile_id, template, catalog=catalog)


def read_profile(path, profile_id, template, *, catalog=None):
    return list(read_profile_state(path, profile_id, template, catalog=catalog).deck)


def profile_bytes(profile_id, deck, template, *, catalog=None, cosmetics=None):
    profile_key(profile_id)
    deck = template.validate_deck(deck)
    snapshot = cosmetic_state(catalog, cosmetics)
    value = dict(schema=2 if snapshot else 1, profile_id=profile_id, deck=list(deck))
    if snapshot:
        value['cosmetics'] = dict(catalog_sha256=snapshot.catalog_sha256, slots=snapshot.slots)
    raw = (json.dumps(value, separators=(',', ':'))+'\n').encode('utf-8')
    require(len(raw) <= MAX_PROFILE_BYTES, 'profile size limit')
    return raw


class ProfileStore:
    def __init__(self, path, template, *, catalog=None):
        self.path, self.template, self.catalog = Path(path), template, catalog
        self.path.mkdir(parents=True, exist_ok=True)

    def _path(self, profile_id):
        profile_key(profile_id)
        return self.path / (profile_id + ".json")

    def load(self, profile_id, fallback):
        return list(self.load_state(profile_id, fallback).deck)

    def load_state(self, profile_id, fallback):
        path = self._path(profile_id)
        try:
            return read_profile_state(path, profile_id, self.template, catalog=self.catalog)
        except FileNotFoundError:
            return ProfileState(tuple(self.template.validate_deck(fallback)), cosmetic_state(self.catalog))

    def save(self, profile_id, deck, *, cosmetics=None):
        # Old deck-only callers preserve the complete saved cosmetic state. A
        # corrupt/mismatched file must not be silently replaced by that path.
        deck = self.template.validate_deck(deck)
        previous = self.load_state(profile_id, deck)
        if cosmetics is None: cosmetics = previous.cosmetics
        data = profile_bytes(profile_id, deck, self.template, catalog=self.catalog, cosmetics=cosmetics)
        path = self._path(profile_id)
        temporary = self.path / ('.profile-'+secrets.token_hex(16)+'.tmp')
        created = False
        try:
            with temporary.open('xb') as stream:
                created = True
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if created:
                try: temporary.unlink(missing_ok=True)
                except OSError: pass  # Keep previous profile; never alter permissions.
