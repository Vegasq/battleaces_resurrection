"""RC1 setup: a server address and automatic local player identity, no CA/invite."""
from __future__ import annotations
import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import time

from . import launcher
from .bridge import Remote, RemoteUnavailable
from server import tls_transport as tls
from server.admission import authenticate_client, rc_player_id

KEYS = frozenset(('schema', 'game_directory', 'display_name', 'local_profile',
                  'server_host', 'server_port', 'room'))


def settings(value, path):
    from . import client
    if not isinstance(value, dict) or set(value) != KEYS or type(value['schema']) is not int or value['schema'] != 4:
        raise launcher.LaunchError('RC client settings require schema4 and its exact fields')
    local = client.local_settings(value, path)
    host, port = value['server_host'], value['server_port']
    if host != '': host = tls.normalize_server_name(host)
    if type(port) is not int or not 1 <= port <= 65535:
        raise launcher.LaunchError('Server port must be in1..65535')
    if value['room'] != local['room']: raise launcher.LaunchError('Invalid room name')
    return dict(value, game_directory=local['game_directory'], server_host=host)


def digest(path):
    path = Path(path)
    if not path.exists(): return None
    launcher.read_json(path, 32768)
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def configuration_lock(parent):
    # Public settings lock; no owner-only invite store is needed in RC mode.
    lock = parent / '.rc-setup.lock'
    try:
        with lock.open('xb') as stream: stream.write(b'\0')
    except FileExistsError: pass
    stream = lock.open('r+b')
    acquired = False
    try:
        deadline = time.monotonic() + 2
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
                if time.monotonic() >= deadline: raise launcher.LaunchError('Another setup is saving settings') from None
                time.sleep(.02)
        yield
    finally:
        if acquired:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def save(request, path):
    from . import client
    path = Path(path).resolve()
    fields = {'game_directory', 'display_name', 'server_host', 'expected_config_sha256'}
    if not isinstance(request, dict) or set(request) != fields:
        raise launcher.LaunchError('Invalid RC setup request')
    if not isinstance(request['server_host'], str):
        raise launcher.LaunchError('Server address must be text')
    path.parent.mkdir(parents=True, exist_ok=True)
    with configuration_lock(path.parent):
        if digest(path) != request['expected_config_sha256']:
            raise launcher.LaunchError('Settings changed; reopen setup before saving')
        previous = launcher.read_json(path, 32768) if path.exists() else {}
        if previous: client.local_settings(previous, path)  # Never discard unknown/corrupt settings.
        value = dict(schema=4, game_directory=request['game_directory'], display_name=request['display_name'],
                     local_profile=previous.get('local_profile', 'default'), server_host=request['server_host'].strip(),
                     server_port=previous.get('server_port', 47623), room=previous.get('room', 'community'))
        validated = settings(value, path)
        if not (validated['game_directory'] / 'Battle Aces.exe').is_file():
            raise launcher.LaunchError('Choose the working Battle Aces game folder')
        value.update(game_directory=str(validated['game_directory']), server_host=validated['server_host'])
        temporary = path.with_name('.rc-settings-' + secrets.token_hex(12) + '.tmp')
        try:
            with temporary.open('x', encoding='utf-8') as stream:
                stream.write(json.dumps(value, indent=2) + '\n'); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally: temporary.unlink(missing_ok=True)
    return setup_data(path)


def setup_data(path):
    from . import client
    path = Path(path).resolve()
    value = launcher.read_json(path, 32768) if path.exists() else {}
    local = client.local_settings(value, path) if value else None
    return dict(game_directory=str(local['game_directory']) if local else '',
                display_name=local['display_name'] if local else 'Player',
                server_host=value.get('server_host', ''), expected_config_sha256=digest(path))


def remote(config, path):
    if not config['server_host']: raise RemoteUnavailable()
    # Separate identities per route/profile; display-name edits never reset saves.
    route = f"{config['server_host']}:{config['server_port']}/{config['local_profile']}"
    directory = Path(path).resolve().parent / 'rc-identities'
    directory.mkdir(parents=True, exist_ok=True)
    identity = directory / (hashlib.sha256(route.encode('utf-8')).hexdigest() + '.json')
    with configuration_lock(directory):
        if not identity.exists():
            token = 'ba1_' + secrets.token_urlsafe(32)
            value = dict(player_id=rc_player_id(token), token=token)
            temporary = directory / ('.identity-' + secrets.token_hex(12) + '.tmp')
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump(value, stream); stream.flush(); os.fsync(stream.fileno())
                os.replace(temporary, identity)
            finally: temporary.unlink(missing_ok=True)
        value = launcher.read_json(identity, 4096)
        if (not isinstance(value, dict) or set(value) != {'player_id', 'token'}
                or value['player_id'] != rc_player_id(value['token'])):
            raise launcher.LaunchError('Local RC identity is damaged; restore its backup')
    return Remote(config['server_host'], config['server_port'], tls.rc_client_context(config['server_host']),
                  value['player_id'], value['token'])


class Resolver:
    def __init__(self, path, game): self.path, self.game = Path(path), Path(game)

    def read(self):
        from . import client
        value = launcher.read_json(self.path, 32768)
        if value.get('schema') != 4:
            return launcher.RemoteConfigResolver(self.path, self.game, config_loader=client.load_connection).read()
        config = settings(value, self.path)
        if config['game_directory'] != self.game: raise launcher.LaunchError('Game binding changed')
        return remote(config, self.path)

    async def __call__(self):
        from .bridge import CONFIG_FAILURE
        try: return await asyncio.to_thread(self.read)
        except RemoteUnavailable: raise
        except (OSError, ValueError): raise RemoteUnavailable(CONFIG_FAILURE) from None


async def check(path):
    config = settings(launcher.read_json(path, 32768), path)
    target = await asyncio.to_thread(remote, config, path)
    reader, writer = await tls.open_verified_connection(target.host, target.port, target.tls)
    try:
        player = await authenticate_client(reader, writer, target.token, rc_open=True)
        if player != target.player_id: raise launcher.LaunchError('Server returned a different RC identity')
        return dict(connected=True, player_id=player, tls=writer.get_extra_info('ssl_object').version(),
                    certificate_verified=False)
    finally: await tls.close_tls_stream(writer)
