"""Explicit local friend enrollment, with verified CA identity and private copies."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import stat
import time

from server import credentials as private
from server import tls_transport as tls
from . import launcher, client

ROOT = Path(__file__).resolve().parents[2]
MAX_REQUEST = 32768
MAX_CA = 4*1024*1024
CERTIFICATE = re.compile(rb'-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----')


class EnrollmentError(ValueError):
    """Contains fixed messages only; no invite, key or unexpected input contents."""


def local_input(path, maximum):
    path = private._local_path(path)
    try:
        information = path.lstat()
        if not stat.S_ISREG(information.st_mode) or not 0 < information.st_size <= maximum:
            raise EnrollmentError('Select a bounded regular local input file')
        with path.open('rb') as stream: raw = stream.read(maximum+1)
        if not 0 < len(raw) <= maximum: raise EnrollmentError('Input file exceeds the permitted size')
        return raw
    except OSError: raise EnrollmentError('A selected local input file is unavailable') from None


def ca_fingerprint(path):
    """Hash the exact public CA file, without importing it into Windows trust."""
    raw = local_input(path, MAX_CA)
    parts = CERTIFICATE.findall(raw)
    if not 1 <= len(parts) <= 16 or CERTIFICATE.sub(b'', raw).strip():
        raise EnrollmentError('Select a PEM file containing only public certificates')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try: context.load_verify_locations(cadata=raw.decode('ascii'))
    except (ValueError, UnicodeError, OSError): raise EnrollmentError('Cannot read the selected CA certificates') from None
    return raw, hashlib.sha256(raw).hexdigest()


def config_destination(path):
    path = private._local_path(path)
    if path.suffix.casefold() != '.json' or not path.parent.is_dir():
        raise EnrollmentError('Choose a JSON config in an existing local directory')
    if ROOT.name == 'app' and ROOT.parent.name == 'program' and path.is_relative_to(ROOT.parent):
        raise EnrollmentError('Keep personal configuration outside program files')
    return path


def configuration_digest(path):
    if not path.exists(): return None
    raw = local_input(path, MAX_REQUEST)
    value = launcher.read_json(path, MAX_REQUEST)
    if isinstance(value, dict) and value.get('schema') == 3:
        client.local_settings(value, path)
    else:
        launcher.validate_config(client.connection_settings(value, path), path)  # Unknown JSON is never silently replaced.
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def _configuration_lock(directory):
    path = directory / 'configuration.lock'
    try: private._write_file(path, b'\0')
    except FileExistsError: private._assert_private_path(path)
    stream = path.open('r+b')
    acquired = False
    try:
        deadline = time.monotonic()+2
        while not acquired:
            try:
                if os.name == 'nt':
                    import msvcrt
                    stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                if time.monotonic() >= deadline: raise EnrollmentError('Another setup operation is using this configuration') from None
                time.sleep(.02)
        yield
    finally:
        if acquired:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def enroll(request, config_path):
    """Commit config only after both new local trust/invite copies validate.

    The request contains paths and public settings, never a token or private key.
    A stale edit fails. Prior config/enrollments and incoming files are preserved.
    Returning public metadata does not prove the server accepts this invite.
    """
    fields = {'schema', 'game_directory', 'server_host', 'server_port', 'server_name',
              'display_name', 'room', 'ca_source', 'invite_source', 'expected_ca_sha256', 'expected_config_sha256'}
    if not isinstance(request, dict) or set(request) != fields or type(request.get('schema')) is not int or request['schema'] != 1:
        raise EnrollmentError('Setup request has an unsupported format')
    for name in ('expected_ca_sha256', 'expected_config_sha256'):
        value = request[name]
        if name == 'expected_config_sha256' and value is None: continue
        if not isinstance(value, str) or not re.fullmatch('[A-Fa-f0-9]{64}', value):
            raise EnrollmentError('A complete SHA256 fingerprint is required')
    for name in ('ca_source', 'invite_source'):
        if not isinstance(request[name], str) or not request[name] or '\0' in request[name]:
            raise EnrollmentError('Choose the public CA and transferred invite files')
    destination = config_destination(config_path)
    if configuration_digest(destination) != (request['expected_config_sha256'].lower() if request['expected_config_sha256'] else None):
        raise EnrollmentError('Configuration changed; reopen setup before saving')
    raw_ca, fingerprint = ca_fingerprint(request['ca_source'])
    if fingerprint != request['expected_ca_sha256'].lower():
        raise EnrollmentError('CA fingerprint differs from the value supplied by your host')
    # Validate all public settings before creating any destination files.
    candidate = {name: request[name] for name in ('game_directory', 'server_host', 'server_port', 'server_name', 'display_name', 'room')}
    candidate.update(schema=2, ca_bundle=request['ca_source'], credential_file=request['invite_source'])
    validated = launcher.validate_config(candidate, destination)
    raw_invite = local_input(request['invite_source'], private.MAX_CREDENTIAL_BYTES)
    private.parse_credential_handoff(raw_invite)
    invite_digest = hashlib.sha256(raw_invite).hexdigest()
    folder = destination.parent / 'private'
    private._ensure_private_directory(folder)
    with _configuration_lock(folder):
        if configuration_digest(destination) != (request['expected_config_sha256'].lower() if request['expected_config_sha256'] else None):
            raise EnrollmentError('Configuration changed; reopen setup before saving')
        profile = folder / ('enrollment-'+secrets.token_hex(16))
        private._ensure_private_directory(profile)
        ca = profile/'owner-ca.pem'; invite = profile/'private-invite.json'
        temporary = destination.parent / ('.client-config-'+secrets.token_hex(16)+'.tmp')
        created = []
        committed = False
        try:
            # These files are private at creation. Runtime readers retain their
            # strict DACL checks; enrollment never chmods existing user files.
            with private._private_create(ca) as stream:
                created.append(ca); stream.write(raw_ca); stream.flush(); os.fsync(stream.fileno())
            private._assert_private_path(ca)
            tls.load_client_context(ca, validated['server_name'])
            public = private.import_credential_file(request['invite_source'], invite, expected_sha256=invite_digest)
            created.append(invite)
            candidate.update(game_directory=str(validated['game_directory']), server_name=validated['server_name'],
                ca_bundle=ca.relative_to(destination.parent).as_posix(), credential_file=invite.relative_to(destination.parent).as_posix())
            launcher.validate_config(candidate, destination)
            # Enrollment changes only online identity/trust. Keep an explicitly
            # selected local cosmetic profile across server/name changes.
            if destination.exists():
                previous = launcher.read_json(destination, MAX_REQUEST)
                if 'local_profile' in previous:
                    candidate['local_profile'] = client.profile_key(previous['local_profile'])
            with private._private_create(temporary) as stream:
                created.append(temporary)
                stream.write((json.dumps(candidate, indent=2)+'\n').encode('utf-8'))
                stream.flush(); os.fsync(stream.fileno())
            private._assert_private_path(temporary)
            if configuration_digest(destination) != (request['expected_config_sha256'].lower() if request['expected_config_sha256'] else None):
                raise EnrollmentError('Configuration changed; reopen setup before saving')
            os.replace(temporary, destination)
            committed = True
            return dict(config=str(destination), ca_sha256=fingerprint, **public)
        finally:
            if not committed:
                # Only paths created in this transaction are eligible. No
                # recursive cleanup, existing-file deletion or permission change.
                for path in reversed(created):
                    try: path.unlink(missing_ok=True)
                    except OSError: pass  # Any leftover is private; do not relax its DACL.
                try: profile.rmdir()
                except OSError: pass


async def check_connection(config_path):
    """Authenticate one verified TLS session, then close it without a game/room."""
    from server.admission import authenticate_client
    config = client.load_connection(config_path)
    trust = tls.load_client_context(config['ca_bundle'], config['server_name'])
    credential = private.read_credential_file(config['credential_file'])
    reader, writer = await tls.open_verified_connection(config['server_host'], config['server_port'], trust)
    try:
        player = await authenticate_client(reader, writer, credential['token'])
        if player != credential['player_id']: raise EnrollmentError('The server returned a different player identity')
        return dict(authenticated=True, player_id=player,
                    tls=writer.get_extra_info('ssl_object').version())
    finally: await tls.close_tls_stream(writer)


def setup_data(config_path):
    """Expose only public settings to the configuration window."""
    path = config_destination(config_path)
    expected = configuration_digest(path)
    if expected is None:
        return dict(game_directory='', server_host='', server_port=47623, server_name='',
            display_name='Player', room='friends', ca_source='', invite_source='', expected_ca_sha256='',
            expected_config_sha256=None)
    value = launcher.read_json(path, MAX_REQUEST)
    if value.get('schema') == 3:
        local = client.local_settings(value, path)
        # Incomplete online settings remain editable, without reading an invite.
        result = dict(game_directory=str(local['game_directory']), display_name=local['display_name'],
            server_host='', server_name='', server_port=47623, room=local['room'],
            ca_source='', invite_source='', expected_ca_sha256='', expected_config_sha256=expected)
        for key in ('server_host', 'server_name'):
            if isinstance(value.get(key), str): result[key] = value[key]
        if type(value.get('server_port')) is int and 1 <= value['server_port'] <= 65535:
            result['server_port'] = value['server_port']
        for source, target in (('ca_bundle', 'ca_source'), ('credential_file', 'invite_source')):
            selected = value.get(source, '')
            if isinstance(selected, str) and selected and not any(ord(c) < 32 for c in selected):
                selected = Path(selected).expanduser()
                result[target] = str((selected if selected.is_absolute() else path.parent / selected).resolve())
        if result['ca_source']:
            try: result['expected_ca_sha256'] = ca_fingerprint(result['ca_source'])[1]
            except (EnrollmentError, private.CredentialError, OSError): pass
        return result
    config = launcher.validate_config(client.connection_settings(value, path), path)
    # A removed/relocated CA must not trap the player in an uneditable profile.
    # Leave trust confirmation empty until they select and confirm a replacement.
    try: _, fingerprint = ca_fingerprint(config['ca_bundle'])
    except (EnrollmentError, private.CredentialError, OSError): fingerprint = ''
    return dict(game_directory=str(config['game_directory']), server_host=config['server_host'],
        server_port=config['server_port'], server_name=config['server_name'], display_name=config['display_name'],
        room=config['room'], ca_source=str(config['ca_bundle']), invite_source=str(config['credential_file']),
        expected_ca_sha256=fingerprint, expected_config_sha256=expected)
