"""Validate copied hosts and explicitly relocate standard Windows deployments."""
import json
import os
from pathlib import Path, PureWindowsPath
import secrets

from server.configuration import load_config
from tools.package_integrity import ordinary_file

PATH_FIELDS = ('assets_directory', 'data_directory', 'certificate_file',
               'private_key_file', 'credential_directory')


def read_config(host):
    path = ordinary_file(host, 'config/host.json')
    with path.open('rb') as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError('Host configuration exceeds16 KiB')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value: raise ValueError('Duplicate host configuration field')
            value[key] = item
        return value
    try: value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique)
    except RecursionError: raise ValueError('Host configuration is nested too deeply') from None
    if not isinstance(value, dict): raise ValueError('Expected a host configuration object')
    return path, raw, value


def check_paths(config):
    required = [('asset manifest', config.assets_directory / 'asset-manifest.json'),
                ('certificate_file', config.certificate_file), ('private_key_file', config.private_key_file)]
    for name, path in required:
        if path is not None and not path.is_file():
            raise ValueError(f'Missing {name}: {path}; restore the copied file or correct config/host.json')
    if config.data_directory.exists() and not config.data_directory.is_dir():
        raise ValueError('Configured data_directory is not a directory')
    if config.credential_directory and not config.credential_directory.is_dir():
        raise ValueError('Missing credential_directory; restore the existing invite store')


def preflight(host):
    path, _, value = read_config(host)
    for name in PATH_FIELDS:
        item = value.get(name)
        if isinstance(item, str) and PureWindowsPath(item).drive:
            raise ValueError(f'{name} contains a Windows drive path; stop the host and run '
                             'tools.linux_server relocate --host-dir <copied-host> first')
    config = load_config(path)
    check_paths(config)
    return config


def relocate(host):
    """No file/identity discovery: map only paths inside one standard old host root.

    Caller must stop the host first. Linux advisory locks do not establish that
    a Wine Windows byte-range lock is held, so do not claim cross-OS exclusion.
    """
    host = Path(host).resolve()
    path, raw, value = read_config(host)
    if not isinstance(value.get('assets_directory'), str):
        raise ValueError('Invalid assets_directory')
    old_assets = PureWindowsPath(value['assets_directory'])
    if not old_assets.drive:
        preflight(host)
        return None
    if (not old_assets.is_absolute() or old_assets.drive.startswith('\\\\')
            or tuple(p.lower() for p in old_assets.parts[-2:]) != ('assets', 'build-37822')):
        raise ValueError('Cannot infer a standard Windows host root; correct custom paths explicitly')
    old_root = old_assets.parent.parent
    for name in PATH_FIELDS:
        item = value.get(name)
        if item is None: continue
        if not isinstance(item, str): raise ValueError('Invalid path field: ' + name)
        windows = PureWindowsPath(item)
        if windows.drive:
            try: relative = windows.relative_to(old_root)
            except ValueError:
                raise ValueError(f'{name} is outside the old host; copy and configure it explicitly') from None
            if '..' in relative.parts: raise ValueError('Parent traversal in ' + name)
            target = host.joinpath(*relative.parts)
        else:
            target = path.parent.joinpath(*windows.parts)
        target = target.resolve()
        if not target.is_relative_to(host): raise ValueError('Path escapes copied host: ' + name)
        # Require actual copied data too: never silently start with a new empty profile store.
        if not target.exists(): raise ValueError('Missing copied ' + name + ': ' + str(target))
        value[name] = os.path.relpath(target, path.parent).replace(os.sep, '/')
    suffix = secrets.token_hex(12)
    temporary = path.with_name('.relocate-' + suffix + '.tmp')
    backup = path.with_name('host.json.before-relocate-' + suffix)
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2); stream.write('\n')
            stream.flush(); os.fsync(stream.fileno())
        check_paths(load_config(temporary))
        if ordinary_file(host, 'config/host.json').read_bytes() != raw:
            raise ValueError('Host configuration changed; retry with the host stopped')
        with backup.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return backup
