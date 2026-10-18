"""Windows secure client launcher: settings/paths on CLI, never invite tokens."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess

from .bridge import Bridge, Remote, RemoteUnavailable, CONFIG_FAILURE
from server.credentials import CredentialError, read_credential_file
from server import tls_transport as tls


class LaunchError(ValueError):
    pass


def read_json(path, maximum):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value: raise LaunchError('Duplicate JSON setting')
            value[key] = item
        return value
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(maximum + 1)
        if len(raw) > maximum: raise LaunchError('JSON file exceeds size limit')
        return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique)
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise LaunchError('Cannot read a bounded valid JSON file') from None


def load_config(path):
    path = Path(path).resolve()
    return validate_config(read_json(path, 32768), path)


def validate_config(value, path):
    """Validate authored settings before writing them as well as during launch."""
    path = Path(path).resolve()
    keys = {'schema', 'game_directory', 'server_host', 'server_port', 'server_name',
            'ca_bundle', 'credential_file', 'display_name', 'room'}
    if (not isinstance(value, dict) or set(value) != keys or type(value['schema']) is not int
            or value['schema'] != 2):
        raise LaunchError('Secure client requires the exact schema2 settings')
    value = value.copy()
    if any(not isinstance(value[key], str) or not value[key] or '\0' in value[key]
           for key in keys - {'schema', 'server_port'}):
        raise LaunchError('Invalid secure client text setting')
    if type(value['server_port']) is not int or not 1 <= value['server_port'] <= 65535:
        raise LaunchError('Server port must be in1..65535')
    tls.normalize_server_name(value['server_host'])
    value['server_name'] = tls.normalize_server_name(value['server_name'])
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', value['room']):
        raise LaunchError('Invalid room name')
    name = value['display_name']
    if not 1 <= len(name) <= 32 or any(ord(c) < 32 or c in '\x7f"\\' for c in name):
        raise LaunchError('Invalid display name')
    for key in ('game_directory', 'ca_bundle', 'credential_file'):
        selected = Path(value[key]).expanduser()
        value[key] = (selected if selected.is_absolute() else path.parent / selected).resolve()
    if value['game_directory'].name.casefold() == 'battleacesbeta_untouched':
        raise LaunchError('Use the working game copy; untouched recovery files are read only')
    return value


class RemoteConfigResolver:
    """Reload validated connection settings on OPEN, without changing the game.

    File access stays in the parent. Cancelling the awaiting session discards a
    pending read result; no network connection is made in the reader thread.
    """
    def __init__(self, path, game_directory):
        self.path = Path(path).resolve()
        self.game_directory = Path(game_directory).resolve()

    def read(self):
        try:
            if not self.path.is_file(): raise RemoteUnavailable()
            config = load_config(self.path)
            if config['game_directory'] != self.game_directory:
                raise RemoteUnavailable(CONFIG_FAILURE)
            if not config['ca_bundle'].is_file() or not config['credential_file'].is_file():
                raise RemoteUnavailable()
            context = tls.load_client_context(config['ca_bundle'], config['server_name'])
            credential = read_credential_file(config['credential_file'])
            return Remote(config['server_host'], config['server_port'], context,
                          credential['player_id'], credential['token'])
        except RemoteUnavailable:
            raise
        except (OSError, ValueError):
            # Never send file paths, credential contents or parser errors to IPC.
            raise RemoteUnavailable(CONFIG_FAILURE) from None

    async def __call__(self):
        return await asyncio.to_thread(self.read)


def verify_game(root, *, community=False, bridge_version=1, unified=False):
    from client_patch.patcher.patch_client import contained_path
    if type(bridge_version) is not int or bridge_version not in (1, 2):
        raise LaunchError('Unsupported private transport version')
    if unified and (not community or bridge_version != 2):
        raise LaunchError('Unified client requires community integration and private transport ABI2')
    root = Path(root).resolve()
    manifest = read_json(root / '.battleaces-resurrection/patch-manifest.json', 131072)
    if not isinstance(manifest, dict) or manifest.get('state') == 'restored':
        raise LaunchError('Install the supported patch before launching')
    if community and manifest.get('community', {}).get('native_scope') != 'custom-match-prototype':
        raise LaunchError('Install the experimental community match patch into an isolated copy')
    components = manifest.get('components')
    if not isinstance(components, dict) or 'GameAssembly.dll' not in components:
        raise LaunchError('A current multi-component patch manifest is required')
    checks = [('BattleAcesOffline.dll', manifest.get('helper_sha256'))]
    for name, component in components.items():
        if not isinstance(component, dict): raise LaunchError('Invalid patch manifest')
        checks.append((name, component.get('installed_sha256')))
    for relative, expected in checks:
        if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
            raise LaunchError('Invalid patch hash')
        try:
            with contained_path(root, relative).open('rb') as stream:
                if relative == 'BattleAcesOffline.dll':
                    helper = stream.read(8 * 1024 * 1024 + 1)
                    if len(helper) > 8 * 1024 * 1024 or b'BA_RESURRECTION_TLS_BRIDGE_V1' not in helper:
                        raise LaunchError('Install a helper supporting secure transport ABI1')
                    if bridge_version == 2 and b'BA_RESURRECTION_TLS_BRIDGE_V2' not in helper:
                        raise LaunchError('Install a helper supporting secure transport ABI2')
                    if unified and b'BA_RESURRECTION_UNIFIED_CLIENT_V1' not in helper:
                        raise LaunchError('Install a helper supporting the unified client lifecycle')
                    if b'BA_RESURRECTION_GAME_PROTOCOL_3' not in helper:
                        raise LaunchError('Install the protocol3 client helper for configurable buffering')
                    if community and b'BA_RESURRECTION_COMMUNITY_MATCH_V1' not in helper:
                        raise LaunchError('Install a helper supporting community match ABI1')
                    actual = hashlib.sha256(helper).hexdigest()
                else:
                    actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        except LaunchError:
            raise
        except (OSError, ValueError):
            raise LaunchError('A patched component is unavailable') from None
        if actual != expected: raise LaunchError('Patched component differs from its manifest')
    if not (root / 'Battle Aces.exe').is_file(): raise LaunchError('Game executable is missing')


def game_arguments(config, player_id, handle, args):
    run_name = args.run_name
    if not re.fullmatch('[A-Za-z0-9_-]{1,48}', run_name): raise LaunchError('Invalid run name')
    root = config['game_directory']
    runtime = root / 'investigation/runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    unified = getattr(args, 'unified_experimental', False)
    dynamic = unified or getattr(args, 'dynamic_identity_experimental', False)
    log_identity = f'session-{os.getpid()}-{handle}' if dynamic else player_id
    result = [str(root / 'Battle Aces.exe'), '-offline-lan',
        f"-dedicated-server={config['server_host']}:{config['server_port']}",
        f'-secure-transport-socket={handle}',
        '-player-name=' + config['display_name'], '-room=' + config['room'],
        '-screen-fullscreen', '0', '-screen-width', '960', '-screen-height', '540',
        '-logFile', str(runtime / (run_name + '-' + log_identity + '.log'))]
    if dynamic: result.append('-secure-transport-version=2')
    else: result.append(f'-player-id={player_id}')
    if unified: result.append('-unified-client')
    switches = dict(auto_ready='-dedicated-auto-ready', smoke='-lan-smoke', deck_smoke='-dedicated-deck-smoke',
                    surrender_smoke='-dedicated-surrender-smoke', telemetry_audit='-telemetry-audit', audit='-lan-audit')
    for option, flag in switches.items():
        if getattr(args, option, False): result.append(flag)
    if unified or getattr(args, 'community_experimental', False):
        if getattr(args, 'auto_ready', False) or getattr(args, 'rematch_smoke', False):
            raise LaunchError('Use native Custom Game Invite/Start instead of automatic queue readiness')
        result.append('-dedicated-community')
    if getattr(args, 'rematch_smoke', False): result.extend(['-dedicated-rematch-smoke', '-dedicated-auto-rematch'])
    if getattr(args, 'recovery_smoke', False): result.append('-dedicated-recovery-smoke')
    if getattr(args, 'postgame_recovery_smoke', False): result.append('-dedicated-postgame-recovery-smoke')
    if getattr(args, 'quit_smoke', False): result.append('-dedicated-quit-smoke')
    return result


def spawn_game(config, remote, args, child_socket):
    if os.name != 'nt': raise LaunchError('The client launcher requires Windows')
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 1  # Normal interactive game window.
    startup.lpAttributeList = {'handle_list': [child_socket.fileno()]}
    dynamic = getattr(args, 'unified_experimental', False) or getattr(args, 'dynamic_identity_experimental', False)
    player_id = None if dynamic else remote.player_id
    argv = game_arguments(config, player_id, child_socket.fileno(), args)
    try:
        child_socket.set_inheritable(True)
        return subprocess.Popen(argv, cwd=config['game_directory'], close_fds=True, startupinfo=startup)
    finally:
        child_socket.set_inheritable(False)


async def launch(config, remote, args):
    """Own the private stream for the game's lifetime; remote sessions authenticate.

    Version1 uses a Remote from verified local settings/private handoff. The
    opt-in version2 also accepts an async resolver and receives identity per OPEN.
    This API also permits controlled in-memory credentials in integration tests;
    there is no public bypass flag or token argument.
    """
    unified = getattr(args, 'unified_experimental', False)
    version = 2 if unified or getattr(args, 'dynamic_identity_experimental', False) else 1
    verify_game(config['game_directory'], community=unified or getattr(args, 'community_experimental', False),
                bridge_version=version, unified=unified)
    parent, child = socket.socketpair(socket.AF_INET)
    parent.setblocking(False)
    writer = task = None
    try:
        reader, writer = await asyncio.open_connection(sock=parent)
        game = spawn_game(config, remote, args, child)
        child.close()
        print(f'Secure client started (PID {game.pid}); transport owns the private invite', flush=True)
        task = asyncio.create_task(Bridge(reader, writer, remote, version=version).run())
        reported = False
        # Poll without occupying a shared executor thread that could block
        # interpreter shutdown after an interrupted launcher.
        while game.poll() is None:
            if task.done() and not reported:
                print('Secure transport ended; close the game before relaunching', flush=True)
                reported = True
            await asyncio.sleep(.2)
        return game.wait()
    finally:
        child.close()
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if writer is not None:
            writer.close()
            try: await asyncio.wait_for(writer.wait_closed(), 2)
            except (OSError, TimeoutError): writer.transport.abort()
        else:
            parent.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--run-name', default='secure-client')
    parser.add_argument('--community-experimental', action='store_true', help='use native Custom Game on an experimental patched copy')
    parser.add_argument('--dynamic-identity-experimental', action='store_true',
                        help='reload connection settings per session with private bridge ABI2')
    parser.add_argument('--unified-experimental', action='store_true',
                        help='use local menu/practice with optional authenticated Custom presence')
    for flag in ('auto-ready', 'smoke', 'deck-smoke', 'surrender-smoke', 'rematch-smoke', 'recovery-smoke', 'postgame-recovery-smoke', 'quit-smoke', 'telemetry-audit', 'audit'):
        parser.add_argument('--' + flag, action='store_true', help='optional development diagnostic')
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.unified_experimental or args.dynamic_identity_experimental:
            remote = RemoteConfigResolver(args.config, config['game_directory'])
        else:
            context = tls.load_client_context(config['ca_bundle'], config['server_name'])
            credential = read_credential_file(config['credential_file'])
            remote = Remote(config['server_host'], config['server_port'], context, credential['player_id'], credential['token'])
        return asyncio.run(launch(config, remote, args))
    except (LaunchError, CredentialError, tls.TLSConfigurationError):
        # These application exceptions carry only explicitly safe messages.
        print('Secure launch failed: check schema2 settings, trusted CA, private invite and installed patch')
        return 1
    except (OSError, ValueError):
        print('Secure launch failed: a required local resource or process is unavailable')
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__': raise SystemExit(main())
