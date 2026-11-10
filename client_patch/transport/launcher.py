"""Windows secure client launcher: settings/paths on CLI, never invite tokens."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import socket
import subprocess
from dataclasses import dataclass

from .bridge import Bridge, Remote, RemoteUnavailable, CONFIG_FAILURE
from server.credentials import CredentialError, read_credential_file
from server import tls_transport as tls


class LaunchError(ValueError):
    pass


@dataclass(frozen=True)
class PredictionWorkerOptions:
    """Explicit private launch resources; never read from ordinary settings."""
    python: Path
    module_root: Path
    heap_helper: Path
    cooperative: Path
    data_directory: Path


def prediction_worker_options(args, selected=None):
    """Validate before filesystem/IPC/process work; no diagnostics are implied."""
    supplied = getattr(args, 'prediction_worker', None)
    if selected is not None and supplied is not None and selected != supplied:
        raise LaunchError('Conflicting prediction worker launch options')
    value = selected if selected is not None else supplied
    if value is None:
        return None
    if type(value) is not PredictionWorkerOptions:
        raise LaunchError('Prediction worker requires typed private launch options')
    if (getattr(args, 'unified_experimental', False) is not True or
            getattr(args, 'original_command_scheduling_experimental', False) is not True or
            getattr(args, 'replay', None) is not None):
        raise LaunchError('Prediction worker requires unified Custom command scheduling without replay')
    from tools.package_integrity import PackageError, ordinary_file
    resolved = {}
    for name in ('python', 'module_root', 'heap_helper', 'cooperative', 'data_directory'):
        path = getattr(value, name)
        if (not isinstance(path, Path) or not path.is_absolute() or
                (path.drive and not re.fullmatch('[A-Za-z]:', path.drive)) or
                len(str(path)) > 32000 or any(ord(c) < 32 or c == '"' for c in str(path))):
            raise LaunchError('Prediction worker resources require absolute local paths')
        # Inspect original spelling before resolve so links/reparse points do
        # not become a trusted different resource merely through normalization.
        try:
            if name in ('module_root', 'data_directory'):
                import stat
                for parent in (path, *path.parents):
                    info = parent.lstat()
                    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                        raise LaunchError('Prediction worker paths cannot use links or reparse points')
                if not path.is_dir():
                    raise LaunchError('Prediction worker directory is unavailable')
            else:
                anchor = Path(path.anchor)
                ordinary_file(anchor, path.relative_to(anchor).as_posix())
        except (OSError, PackageError):
            raise LaunchError('Prediction worker resource is unavailable or not an ordinary local path') from None
        resolved[name] = path.resolve()
    if (resolved['python'].name.casefold() != 'python.exe' or
            resolved['heap_helper'].name != 'BAHeap.dll' or
            resolved['cooperative'].name != 'PredictionCooperative.dll'):
        raise LaunchError('Prediction worker resource names do not match the private profile')
    try:
        ordinary_file(resolved['module_root'], 'client_patch/prediction_worker/__main__.py')
    except PackageError:
        raise LaunchError('Prediction worker module closure is unavailable') from None
    if resolved['data_directory'] in {resolved['module_root'], resolved['python'].parent,
                                      resolved['heap_helper'].parent, resolved['cooperative'].parent}:
        raise LaunchError('Prediction worker data must be separate from immutable program resources')
    return PredictionWorkerOptions(**resolved)


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
    def __init__(self, path, game_directory, *, config_loader=None):
        self.path = Path(path).resolve()
        self.game_directory = Path(game_directory).resolve()
        self.config_loader = config_loader or load_config

    def read(self):
        try:
            if not self.path.is_file(): raise RemoteUnavailable()
            config = self.config_loader(self.path)
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


def verify_game(root, *, community=False, bridge_version=1, unified=False, player_features=False, replay=False,
                original_command_scheduling_experimental=False):
    from client_patch.patcher.patch_client import contained_path
    if type(bridge_version) is not int or bridge_version not in (1, 2):
        raise LaunchError('Unsupported private transport version')
    if unified and (not community or bridge_version != 2):
        raise LaunchError('Unified client requires community integration and private transport ABI2')
    if player_features and not unified:
        raise LaunchError('Player features require the unified client')
    if original_command_scheduling_experimental and (not unified or not community or bridge_version != 2):
        raise LaunchError('Original command scheduling requires the unified client with community transport ABI2')
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
                    if unified and b'BA_RESURRECTION_SOLO_AI_HOST_V1' not in helper:
                        raise LaunchError('Install a helper supporting configurable local solo AI hosting')
                    if original_command_scheduling_experimental and b'BA_RESURRECTION_ORIGINAL_COMMAND_SCHEDULING_V1' not in helper:
                        raise LaunchError('Install the matching experimental client helper to use original command scheduling')
                    if replay and b'BA_RESURRECTION_REPLAY_ENTRY_V1' not in helper:
                        raise LaunchError('Install the current client patch to watch replay files')
                    if player_features:
                        markers = (b'BA_RESURRECTION_PUBLIC_QUEUE_V1', b'BA_RESURRECTION_COSMETICS_UNLOCK_V1',
                                   b'BA_RESURRECTION_COSMETICS_PERSIST_V1', b'BA_RESURRECTION_NATIVE_DECK_INPUT_V1',
                                   b'BA_RESURRECTION_NATIVE_SETTINGS_ATOMIC_V1', b'BA_RESURRECTION_NATIVE_STORAGE_V1',
                                   b'BA_RESURRECTION_NATIVE_BACKUP_GUARD_V1', b'BA_RESURRECTION_NATIVE_REPLAY_LONG_PATH_V2')
                        appearance = manifest.get('cosmetics', {})
                        settings = manifest.get('local_settings', {})
                        storage = manifest.get('local_storage', {})
                        if (any(marker not in helper for marker in markers) or not isinstance(appearance, dict)
                                or appearance.get('experimental') is not True or appearance.get('persistence') is not True
                                or not isinstance(settings, dict) or settings.get('deck_input_guard') is not True
                                or settings.get('write_publication') != 'original-serializer-flush-handle-rename'
                                or not isinstance(storage, dict) or storage.get('isolated') is not True
                                or storage.get('steam_file_sync') != 'local-only'
                                or storage.get('autosave_exception_boundary') is not True
                                or storage.get('backup_input_guard') is not True
                                or storage.get('replay_path_api') != 'extended-local-drive'
                                or storage.get('backup_publication') != 'original-json-text-flush-handle-rename'
                                or type(storage.get('autosave_call_sites')) is not int or storage['autosave_call_sites'] != 4):
                            raise LaunchError('Install the current complete client patch with public play, cosmetics and protected settings')
                    if b'BA_RESURRECTION_GAME_PROTOCOL_3' not in helper:
                        raise LaunchError('Install the protocol3 client helper for configurable buffering')
                    if community and b'BA_RESURRECTION_COMMUNITY_MATCH_V1' not in helper:
                        raise LaunchError('Install a helper supporting community match ABI1')
                    local_settings, hooks = manifest.get('local_settings'), manifest.get('call_hooks')
                    if (b'BA_RESURRECTION_NATIVE_SETTINGS_V1' not in helper or b'OfflineLocalUserConfigPath\0' not in helper
                            or not isinstance(local_settings, dict) or local_settings.get('isolated') is not True
                            or not isinstance(hooks, list)
                            or not any(hook.get('name') == 'OfflineLocalUserConfigPath' for hook in hooks if isinstance(hook, dict))):
                        raise LaunchError('Install the current patch with native local-user settings isolation')
                    actual = hashlib.sha256(helper).hexdigest()
                else:
                    actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        except LaunchError:
            raise
        except (OSError, ValueError):
            raise LaunchError('A patched component is unavailable') from None
        if actual != expected: raise LaunchError('Patched component differs from its manifest')
    if not (root / 'Battle Aces.exe').is_file(): raise LaunchError('Game executable is missing')
    if player_features and 'asset_loading' not in manifest:
        raise LaunchError('Install the current client patch with verified local bundle loading')
    if 'asset_loading' in manifest:
        from client_patch.patcher import bundle_loading
        try:
            bundle_loading.verify_installed(root, manifest['asset_loading'], progress=bundle_loading.console_progress)
        except (OSError, ValueError):
            raise LaunchError('Game content verification failed. Repair the supported game files or reinstall the client patch.') from None


def native_storage_preflight(config):
    """Reject known native loader limits before starting the game or opening IPC.

    The backup's fixed filename is longer than the native settings filename and
    bounded save temporaries. Replay filenames use a separate extended-path API
    and may exceed this limit; do not constrain them here.
    """
    from .client import profile_key
    profile = profile_key(config.get('local_profile', 'default'))
    root = PureWindowsPath(str(config['game_directory']))
    if not root.is_absolute() or not re.fullmatch('[A-Za-z]:', root.drive) or '..' in root.parts:
        raise LaunchError('Use an absolute local Windows drive path for the working game.')
    backup = root / '.battleaces-resurrection' / 'profiles' / profile / 'StorageSyncBackup' / 'A3079428-5DC5-4617-AF2D-0C8656DA760B'
    try:
        units = len(str(backup).encode('utf-16-le')) // 2
    except UnicodeError:
        raise LaunchError('The game folder contains an invalid Windows path.') from None
    if units >= 260:
        raise LaunchError('The game folder and local profile make native save paths too long. '
                          'Move the working game to a shorter folder and update game_directory in your client config.')
    return profile


def game_arguments(config, player_id, handle, args, *, prediction_worker=None):
    prediction = prediction_worker_options(args, prediction_worker)
    run_name = args.run_name
    if not re.fullmatch('[A-Za-z0-9_-]{1,48}', run_name): raise LaunchError('Invalid run name')
    unified = getattr(args, 'unified_experimental', False)
    original_commands = getattr(args, 'original_command_scheduling_experimental', False)
    if original_commands and not unified:
        raise LaunchError('Original command scheduling requires the unified client')
    if unified:
        from .client import solo_ai_host
        ai_host = solo_ai_host(config.get('solo_ai_host', 'local'))
    profile = native_storage_preflight(config)
    root = config['game_directory']
    runtime = root / 'investigation/runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    dynamic = unified or getattr(args, 'dynamic_identity_experimental', False)
    log_identity = f'session-{os.getpid()}-{handle}' if dynamic else player_id
    result = [str(root / 'Battle Aces.exe'), '-offline-lan',
        f"-dedicated-server={config['server_host']}:{config['server_port']}",
        f'-secure-transport-socket={handle}',
        '-player-name=' + config['display_name'], '-room=' + config['room'],
        '-logFile', str(runtime / (run_name + '-' + log_identity + '.log'))]
    if config.get('fullscreen', True): result.extend(('-screen-fullscreen', '1'))
    else: result.extend(('-screen-fullscreen', '0', '-screen-width', '960', '-screen-height', '540'))
    if dynamic: result.append('-secure-transport-version=2')
    else: result.append(f'-player-id={player_id}')
    result.append('-local-profile=' + profile)
    if unified: result.extend(('-unified-client', '-solo-ai-host=' + ai_host))
    if original_commands: result.append('-original-command-scheduling-experimental')
    if prediction is not None:
        result.append('-prediction-movement-experimental')
        for flag, value in (('python', prediction.python), ('module-root', prediction.module_root),
                            ('heap-helper', prediction.heap_helper), ('cooperative', prediction.cooperative),
                            ('data-dir', prediction.data_directory)):
            result.append('-prediction-worker-' + flag + '=' + str(value))
    replay = getattr(args, 'replay', None)
    if replay is not None:
        if not unified or not isinstance(replay, str) or len(replay) > 32000 or any(ord(c) < 32 for c in replay):
            raise LaunchError('Replay selection requires a valid local filename and the unified client')
        result.append('-replay-file=' + replay if replay else '-replay-select')
    if getattr(args, 'player_features', False):
        if not unified: raise LaunchError('Player features require the unified client')
        result.extend(('-public-queue-experimental', '-local-cosmetics-experimental'))
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


def spawn_game(config, remote, args, child_socket, *, prediction_worker=None):
    if os.name != 'nt': raise LaunchError('The client launcher requires Windows')
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 1  # Normal interactive game window.
    startup.lpAttributeList = {'handle_list': [child_socket.fileno()]}
    dynamic = getattr(args, 'unified_experimental', False) or getattr(args, 'dynamic_identity_experimental', False)
    player_id = None if dynamic else remote.player_id
    argv = game_arguments(config, player_id, child_socket.fileno(), args, prediction_worker=prediction_worker)
    try:
        child_socket.set_inheritable(True)
        return subprocess.Popen(argv, cwd=config['game_directory'], close_fds=True, startupinfo=startup)
    finally:
        child_socket.set_inheritable(False)


async def launch(config, remote, args, *, prediction_worker=None):
    """Own the private stream for the game's lifetime; remote sessions authenticate.

    Version1 uses a Remote from verified local settings/private handoff. The
    opt-in version2 also accepts an async resolver and receives identity per OPEN.
    This API also permits controlled in-memory credentials in integration tests;
    there is no public bypass flag or token argument.
    """
    prediction = prediction_worker_options(args, prediction_worker)
    unified = getattr(args, 'unified_experimental', False)
    version = 2 if unified or getattr(args, 'dynamic_identity_experimental', False) else 1
    native_storage_preflight(config)
    verify_game(config['game_directory'], community=unified or getattr(args, 'community_experimental', False),
                bridge_version=version, unified=unified, player_features=getattr(args, 'player_features', False),
                replay=getattr(args, 'replay', None) is not None,
                original_command_scheduling_experimental=getattr(args, 'original_command_scheduling_experimental', False))
    parent, child = socket.socketpair(socket.AF_INET)
    parent.setblocking(False)
    writer = task = None
    try:
        reader, writer = await asyncio.open_connection(sock=parent)
        if prediction is None:
            game = spawn_game(config, remote, args, child)
        else:
            game = spawn_game(config, remote, args, child, prediction_worker=prediction)
        child.close()
        print(f'Client started (PID {game.pid}).' if unified else
              f'Secure client started (PID {game.pid}); transport owns the private invite', flush=True)
        task = asyncio.create_task(Bridge(reader, writer, remote, version=version).run())
        reported = False
        # Poll without occupying a shared executor thread that could block
        # interpreter shutdown after an interrupted launcher.
        while game.poll() is None:
            if task.done() and not reported:
                print('Secure transport ended; close the game before relaunching', flush=True)
                reported = True
            await asyncio.sleep(.2)
        code = game.wait()
        if code == 78:
            raise LaunchError('Game startup failed. Close programs using the game folder, check file access, '
                              'and repair the supported game files if needed, then start the client again. '
                              'See the local game log for details.')
        return code
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
