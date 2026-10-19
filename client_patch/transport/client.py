"""Start the patched client with local play and optional authenticated networking."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import re

from . import launcher
from .bridge import RemoteUnavailable

KEYS = frozenset(('schema', 'game_directory', 'display_name', 'server_host',
                 'server_port', 'server_name', 'ca_bundle', 'credential_file', 'room', 'local_profile'))
LOCAL_KEYS = frozenset(('schema', 'game_directory', 'display_name'))
REMOTE_KEYS = KEYS - {'local_profile'}


def profile_key(value):
    reserved = {'con', 'prn', 'aux', 'nul'} | {f'{prefix}{i}' for prefix in ('com', 'lpt') for i in range(1, 10)}
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9_-]{1,48}', value) or value in reserved:
        raise launcher.LaunchError('Local profile must contain 1..48 lowercase letters, digits, underscores or hyphens')
    return value


def defaults(game):
    return dict(schema=3, game_directory=str(Path(game).resolve()), display_name='Player', local_profile='default',
                server_host='', server_port=47623, server_name='', ca_bundle='',
                credential_file='', room='community')


def local_settings(value, path):
    """Only local settings are prerequisites for starting the game.

    Online settings are checked separately on every connection attempt. They are
    never used to open sockets, load trust, or read invites during local setup.
    """
    if (not isinstance(value, dict) or type(value.get('schema')) is not int
            or value['schema'] not in (2, 3) or not LOCAL_KEYS <= value.keys()
            or not value.keys() <= KEYS or (value['schema'] == 2 and not REMOTE_KEYS <= value.keys())):
        raise launcher.LaunchError('Client settings require schema3 local fields or an existing schema2 configuration')
    name, game = value['display_name'], value['game_directory']
    if (not isinstance(name, str) or not 1 <= len(name) <= 32
            or any(ord(c) < 32 or c in '\x7f"\\' for c in name)):
        raise launcher.LaunchError('Invalid display name')
    if not isinstance(game, str) or not game or any(ord(c) < 32 or c == '"' for c in game):
        raise launcher.LaunchError('Invalid game directory')
    selected = Path(game).expanduser()
    root = (selected if selected.is_absolute() else Path(path).resolve().parent / selected).resolve()
    if root.name.casefold() == 'battleacesbeta_untouched':
        raise launcher.LaunchError('Use the working game copy; untouched recovery files are read only')
    # ABI2 carries the actual remote route in the parent only. These placeholders
    # satisfy the legacy argv shape; secure transport never opens a plaintext link.
    room = value.get('room', 'community')
    if not isinstance(room, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', room): room = 'community'
    return dict(game_directory=root, display_name=name, room=room, local_profile=profile_key(value.get('local_profile', 'default')),
                server_host='127.0.0.1', server_port=47623)


def connection_settings(value, path):
    """Keep the launch-frozen local identity out of the strict online schema."""
    local_settings(value, path)
    candidate = defaults(Path(path).parent)
    candidate.update(value)
    candidate.pop('local_profile')
    candidate['schema'] = 2
    return candidate


def load_connection(path):
    """Adapt optional settings to the existing strict TLS/identity validator."""
    value = launcher.read_json(path, 32768)
    candidate = connection_settings(value, path)
    if any(candidate[key] == '' for key in ('server_host', 'server_name', 'ca_bundle', 'credential_file')):
        raise RemoteUnavailable()
    return launcher.validate_config(candidate, path)


def prepare_settings(path, game=None, *, default_game=None):
    """Create public defaults once; an existing configuration is never overwritten."""
    path = Path(path).resolve()
    if path.exists():
        value = launcher.read_json(path, 32768)
    else:
        selected = Path(game or default_game or Path.cwd()).resolve()
        value = defaults(selected)
        local_settings(value, path)
        if not (selected / 'Battle Aces.exe').is_file():
            raise launcher.LaunchError('Select your patched working game with --game on the first launch')
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', encoding='utf-8') as stream:
                stream.write(json.dumps(value, indent=2) + '\n')
        except FileExistsError:
            value = launcher.read_json(path, 32768)
        except OSError:
            # A read-only config destination must not prevent local deck testing.
            print('Client settings could not be saved; using local defaults for this launch.')
    config = local_settings(value, path)
    if game is not None and config['game_directory'] != Path(game).resolve():
        raise launcher.LaunchError('The requested game differs from the saved configuration')
    return config


def player_options():
    """The single ordinary entry point enables the complete player capability set."""
    return argparse.Namespace(run_name='client', unified_experimental=True, player_features=True)


def main(argv=None, *, default_game=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path.cwd() / 'client.json')
    parser.add_argument('--game', type=Path, help='working game directory for first launch without a configuration')
    args = parser.parse_args(argv)
    try:
        config = prepare_settings(args.config, args.game, default_game=default_game)
        remote = launcher.RemoteConfigResolver(args.config, config['game_directory'], config_loader=load_connection)
        return asyncio.run(launcher.launch(config, remote, player_options()))
    except launcher.LaunchError as error:
        print('Client could not start: ' + str(error))
        return 1
    except (OSError, ValueError):
        print('Client could not start: check local settings and the supported patched game installation.')
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__': raise SystemExit(main())
