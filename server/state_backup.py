"""Offline profiles/invitation snapshots and non-destructive fresh-location restore.

No game assets, client invite tokens, logs or TLS private keys enter a snapshot.
An explicit restore treats a transferred snapshot as untrusted bounded input.
"""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time

from . import credentials as private, protocol
from .assets import verify_assets
from .configuration import load_config, ConfigurationError
from .game_data import GameTemplate
from .profiles import ProfileStore, profile_key, read_profile
from .state_lock import exclusive_state, StateBusyError
from .paths import ROOT

MAX_BACKUP_BYTES = 4*1024*1024
MAX_PROFILES = 4096
HASH = re.compile(r'[0-9a-f]{64}\Z')
TEMP_PROFILE = re.compile(r'(?:\.profile-[0-9a-f]{32}|[A-Za-z0-9_-]{1,48}\.json)\.tmp\Z')


class BackupError(ValueError):
    """Fixed operator-facing messages; never serialize raw state in errors."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def digest(raw): return hashlib.sha256(raw).hexdigest()


def output_path(value):
    path = private._local_path(value)
    if (ROOT.name.casefold() == 'app' and ROOT.parent.name.casefold() == 'program'
            and path.is_relative_to(ROOT.parent)):
        raise BackupError('Keep snapshots and restored state outside the bundled program directory')
    return path


def load_inputs(config):
    manifest = verify_assets(config.assets_directory)
    template = GameTemplate.load(config.assets_directory/'map-1v1.pb.gz',
        catalog_path=config.assets_directory/'unit-catalog.json', descriptors_path=config.assets_directory/'descriptors')
    identity = dict(game_build=manifest['game_build'], asset_format=manifest['asset_format'],
        game_protocol=protocol.VERSION, original_gameassembly_sha256=manifest['original_gameassembly_sha256'],
        simulation_sha256=manifest['simulation_sha256'], asset_files_sha256=digest(canonical(manifest['files'])))
    return template, identity


def regular_file(path, maximum):
    information = path.lstat()
    if (not stat.S_ISREG(information.st_mode) or getattr(information, 'st_file_attributes', 0) & 0x400
            or not 0 < information.st_size <= maximum):
        raise BackupError('Snapshot input must be a bounded regular local file')
    with path.open('rb') as stream: raw = stream.read(maximum+1)
    if not 0 < len(raw) <= maximum: raise BackupError('Snapshot exceeds its size limit')
    return raw


def saved_profiles(directory, template):
    directory = Path(directory)
    if not directory.exists(): return {}
    information = directory.lstat()
    if not stat.S_ISDIR(information.st_mode) or getattr(information, 'st_file_attributes', 0) & 0x400:
        raise BackupError('Profiles must be a regular local directory')
    profiles = {}
    seen, count = set(), 0
    for path in directory.iterdir():
        count += 1
        if count > MAX_PROFILES*2: raise BackupError('Profile directory entry limit')
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise BackupError('Unexpected non-file profile entry')
        if TEMP_PROFILE.fullmatch(path.name): continue  # Not a committed saved deck.
        if path.suffix != '.json': raise BackupError('Unexpected file in the profile directory')
        key = profile_key(path.stem)
        if key.casefold() in seen or len(profiles) >= MAX_PROFILES:
            raise BackupError('Duplicate profile identity or profile count limit')
        seen.add(key.casefold())
        profiles[key] = read_profile(path, key, template)
    return profiles


def validate_snapshot(raw, template, identity, *, secure):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BACKUP_BYTES:
        raise BackupError('Snapshot size limit')
    try:
        envelope = private._json(raw)
    except private.CredentialError: raise BackupError('Snapshot must be bounded duplicate-free JSON') from None
    if (not isinstance(envelope, dict) or set(envelope) != {'schema', 'payload', 'sha256'}
            or type(envelope['schema']) is not int or envelope['schema'] != 1
            or not isinstance(envelope['sha256'], str) or not HASH.fullmatch(envelope['sha256'])):
        raise BackupError('Unsupported snapshot envelope')
    payload = envelope['payload']
    if not isinstance(payload, dict) or set(payload) != {'created_at', 'compatibility', 'profiles', 'credentials'}:
        raise BackupError('Unsupported snapshot payload')
    if digest(canonical(payload)) != envelope['sha256']:
        raise BackupError('Snapshot integrity check failed')
    if (type(payload['created_at']) is not int or not 0 <= payload['created_at'] < 1 << 63
            or canonical(payload['compatibility']) != canonical(identity)):
        raise BackupError('Snapshot is incompatible with the selected assets or has an invalid date')
    profiles = payload['profiles']
    if not isinstance(profiles, dict) or len(profiles) > MAX_PROFILES:
        raise BackupError('Snapshot profile count limit')
    seen = set()
    for key, deck in profiles.items():
        profile_key(key)
        if key.casefold() in seen: raise BackupError('Snapshot contains duplicate Windows profile names')
        seen.add(key.casefold())
        template.validate_deck(deck)
    if secure != (payload['credentials'] is not None):
        raise BackupError('Snapshot and destination must use the same TLS/authentication mode')
    if secure: private.parse_store_snapshot(canonical(payload['credentials']))
    return payload


def public_summary(payload):
    records = payload['credentials']['invites'] if payload['credentials'] else []
    return dict(created_at=payload['created_at'], profiles=len(payload['profiles']), invites=len(records),
        players=len({row['player_id'] for row in records}), revoked=sum(row['revoked_at'] is not None for row in records))


def backup(config, output):
    output = output_path(output)
    if not config.data_directory.is_dir(): raise BackupError('Configured server data directory does not exist')
    if (output.is_relative_to(config.data_directory) or output.is_relative_to(config.assets_directory)
            or (config.credential_directory and output.is_relative_to(config.credential_directory))):
        raise BackupError('Store snapshots separately from live data and imported assets')
    template, identity = load_inputs(config)
    with exclusive_state(config.data_directory):
        profiles = saved_profiles(config.data_directory/'profiles', template)
        credentials = None
        if not config.allow_insecure_loopback:
            credentials = json.loads(private.CredentialStore(config.credential_directory).export_snapshot())
        payload = dict(created_at=int(time.time()), compatibility=identity, profiles=profiles, credentials=credentials)
        raw = canonical(dict(schema=1, payload=payload, sha256=digest(canonical(payload))))+b'\n'
        validate_snapshot(raw, template, identity, secure=not config.allow_insecure_loopback)
        private._ensure_private_directory(output.parent)
        created = False
        try:
            with private._private_create(output) as stream:
                created = True
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            copied = private._read_file(output, MAX_BACKUP_BYTES)
            if copied != raw: raise BackupError('Snapshot readback did not match')
        except (OSError, ValueError):
            if created:
                try: output.unlink()
                except OSError: pass  # A private partial snapshot may remain; never relax ACLs.
            raise BackupError('Snapshot creation failed; existing output and server state were preserved') from None
        return dict(path=str(output), bytes=len(raw), sha256=digest(raw), **public_summary(payload))


def verify_snapshot(config, source):
    template, identity = load_inputs(config)
    raw = regular_file(private._local_path(source), MAX_BACKUP_BYTES)
    payload = validate_snapshot(raw, template, identity, secure=not config.allow_insecure_loopback)
    return dict(verified=True, sha256=digest(raw), **public_summary(payload))


def restore(config, source, destination):
    """Create new data and commit a new host.json last; never alter the live config.

    The source config supplies trusted asset/TLS paths and host settings. Snapshot
    input cannot select local paths. Failed fresh destinations are kept for
    inspection without a runnable host.json; the caller chooses a new retry path.
    """
    template, identity = load_inputs(config)
    raw = regular_file(private._local_path(source), MAX_BACKUP_BYTES)
    payload = validate_snapshot(raw, template, identity, secure=not config.allow_insecure_loopback)
    destination = output_path(destination)
    forbidden = [config.data_directory, config.assets_directory]
    if config.credential_directory: forbidden.append(config.credential_directory)
    if any(destination.is_relative_to(path) for path in forbidden):
        raise BackupError('Restore into a new location outside existing data, credentials and assets')
    if not destination.parent.is_dir(): raise BackupError('Restore parent directory must already exist')
    # Atomic exclusive mkdir claims a new output; even an empty existing folder
    # is refused, and no cleanup ever recursively deletes a user's directory.
    destination.mkdir(exist_ok=False)
    temporary, final = destination/'.host-config.tmp', destination/'host.json'
    try:
        data = destination/'data'
        profiles = ProfileStore(data/'profiles', template)
        for key, deck in payload['profiles'].items():
            profiles.save(key, deck)
            if profiles.load(key, []) != deck: raise BackupError('Restored profile readback failed')
        credential_dir = None
        if payload['credentials'] is not None:
            credential_dir = data/'private/credentials'
            private.CredentialStore(credential_dir).import_snapshot(canonical(payload['credentials']))
        settings = asdict(config); settings.pop('source')
        settings.update(schema=1, data_directory=data, credential_directory=credential_dir)
        settings = {key:str(value) if isinstance(value, Path) else value for key,value in settings.items()}
        private._write_file(temporary, canonical(settings)+b'\n')
        restored_config = load_config(temporary)
        if restored_config.data_directory != data: raise BackupError('Restored configuration readback failed')
        # Windows rename refuses an existing destination. Elsewhere hard-link
        # publication provides the same exclusive behavior for source tests.
        if os.name == 'nt': temporary.rename(final)
        else:
            os.link(temporary, final)
            try: temporary.unlink()
            except OSError: pass
        return dict(config=str(final), data_directory=str(data), **public_summary(payload))
    except (OSError, ValueError):
        try: temporary.unlink(missing_ok=True)
        except OSError: pass
        raise BackupError('Restore failed; the new incomplete folder was retained and the original server was unchanged') from None


def main(argv=None):
    parser = private._Parser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for action in ('backup', 'verify-backup', 'restore'):
        sub = commands.add_parser(action)
        sub.add_argument('--config', type=Path, required=True)
        if action == 'backup': sub.add_argument('--out', type=Path, required=True)
        else: sub.add_argument('--input', type=Path, required=True)
        if action == 'restore': sub.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == 'backup': result = backup(config, args.out)
        elif args.command == 'verify-backup': result = verify_snapshot(config, args.input)
        else: result = restore(config, args.input, args.destination)
        print(json.dumps(result))
        return 0
    except (BackupError, StateBusyError, ConfigurationError, private.CredentialError) as error:
        print('Server state command failed: '+str(error), file=sys.stderr)
    except (OSError, ValueError):
        print('Server state command failed: check the snapshot, supported assets, local paths and permissions.', file=sys.stderr)
    return 1


if __name__ == '__main__': raise SystemExit(main())
