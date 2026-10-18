"""Local profile deck persistence. Paths never derive from arbitrary input."""
from __future__ import annotations

import json
from pathlib import Path
import os
import secrets
import stat

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


def parse_profile(raw, profile_id, template):
    """A single bounded saved deck; use the same rules for load and restore."""
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
    require(isinstance(value, dict) and set(value) == {'schema', 'profile_id', 'deck'}
        and type(value['schema']) is int and value['schema'] == 1
        and value['profile_id'] == profile_id, 'invalid saved profile schema or identity')
    return list(template.validate_deck(value['deck']))


def read_profile(path, profile_id, template):
    information = path.lstat()
    require(stat.S_ISREG(information.st_mode) and not getattr(information, 'st_file_attributes', 0) & 0x400,
            'profile must be a regular local file')
    require(0 < information.st_size <= MAX_PROFILE_BYTES, 'profile size limit')
    with path.open('rb') as stream: raw = stream.read(MAX_PROFILE_BYTES+1)
    return parse_profile(raw, profile_id, template)


def profile_bytes(profile_id, deck, template):
    profile_key(profile_id)
    deck = template.validate_deck(deck)
    return (json.dumps(dict(schema=1, profile_id=profile_id, deck=list(deck)), separators=(',', ':'))+'\n').encode('utf-8')


class ProfileStore:
    def __init__(self, path, template):
        self.path, self.template = Path(path), template
        self.path.mkdir(parents=True, exist_ok=True)

    def _path(self, profile_id):
        profile_key(profile_id)
        return self.path / (profile_id + ".json")

    def load(self, profile_id, fallback):
        path = self._path(profile_id)
        try:
            return read_profile(path, profile_id, self.template)
        except FileNotFoundError:
            return list(fallback)

    def save(self, profile_id, deck):
        data = profile_bytes(profile_id, deck, self.template)
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
