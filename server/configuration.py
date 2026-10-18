"""Strict host configuration with paths relative to its own file, not the cwd."""
from __future__ import annotations
from dataclasses import dataclass
import ipaddress
import json
from pathlib import Path

from .paths import ROOT
from .protocol import MIN_INPUT_WINDOW, MAX_INPUT_WINDOW


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class HostConfig:
    source: Path
    listen_host: str
    listen_port: int
    assets_directory: Path
    data_directory: Path
    certificate_file: Path | None
    private_key_file: Path | None
    credential_directory: Path | None
    max_rooms: int
    input_window: int
    diagnostic_audit: bool
    log_max_bytes: int
    log_backups: int
    allow_insecure_loopback: bool


def load_config(path):
    path = Path(path).resolve()
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ConfigurationError('Duplicate configuration field')
            result[key] = value
        return result
    try:
        with path.open('rb') as source: raw = source.read(16385)
        if len(raw) > 16384: raise ConfigurationError('Configuration exceeds16 KiB')
        value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=pairs)
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise ConfigurationError('Cannot read a bounded valid host configuration') from None
    fields = set(HostConfig.__dataclass_fields__) - {'source'}
    if not isinstance(value, dict) or set(value) != fields | {'schema'} or type(value['schema']) is not int or value['schema'] != 1:
        raise ConfigurationError('Expected host configuration schema1 and its exact fields')
    for name, minimum, maximum in (('listen_port', 1, 65535), ('max_rooms', 1, 64),
            ('input_window', MIN_INPUT_WINDOW, MAX_INPUT_WINDOW), ('log_max_bytes', 65536, 64*1024*1024), ('log_backups', 1, 16)):
        if type(value[name]) is not int or not minimum <= value[name] <= maximum:
            raise ConfigurationError(f'{name} must be an integer in {minimum}..{maximum}')
    for name in ('diagnostic_audit', 'allow_insecure_loopback'):
        if type(value[name]) is not bool: raise ConfigurationError(name + ' must be true or false')
    try:
        if not isinstance(value['listen_host'], str): raise ValueError()
        address = ipaddress.IPv4Address(value['listen_host'])
    except ValueError:
        raise ConfigurationError('listen_host must be a numeric IPv4 bind address') from None
    if value['allow_insecure_loopback'] and not address.is_loopback:
        raise ConfigurationError('Development plaintext is restricted to numeric loopback')
    for name in ('assets_directory', 'data_directory', 'certificate_file', 'private_key_file', 'credential_directory'):
        item = value[name]
        optional = name in ('certificate_file', 'private_key_file', 'credential_directory')
        if optional and item is None: continue
        if not isinstance(item, str) or not item.strip() or '\0' in item or item.startswith(('\\\\', '//')):
            raise ConfigurationError(name + ' must be a nonempty local path')
        value[name] = (path.parent / item).resolve()
    secure = [value[name] is not None for name in ('certificate_file', 'private_key_file', 'credential_directory')]
    if any(secure) != all(secure) or (not all(secure) and not value['allow_insecure_loopback']):
        raise ConfigurationError('Certificate, private key and credential directory are required together')
    if all(secure) and value['allow_insecure_loopback']:
        raise ConfigurationError('Choose TLS or explicit development loopback, not both')
    assets, data = value['assets_directory'], value['data_directory']
    if assets.is_relative_to(data) or data.is_relative_to(assets):
        raise ConfigurationError('Assets and writable server data must be separate directories')
    credentials = value['credential_directory']
    if credentials and (credentials.is_relative_to(assets) or assets.is_relative_to(credentials)):
        raise ConfigurationError('Credential storage must be separate from game assets')
    # The bundle's runtime and application tree are both immutable. A checkout
    # still permits its existing ignored local/ development directory.
    bundled = ROOT.name == 'app' and ROOT.parent.name == 'program'
    program = ROOT.parent if bundled else ROOT
    for name in ('assets_directory', 'data_directory', 'credential_directory'):
        item = value[name]
        if item and item.is_relative_to(program) and (bundled or not item.is_relative_to(ROOT / 'local')):
            raise ConfigurationError(name + ' must be outside program files or under local/ in a checkout')
    if bundled and (path.is_relative_to(program) or any(value[name] and value[name].is_relative_to(program)
                     for name in ('certificate_file', 'private_key_file'))):
        raise ConfigurationError('Keep configuration and TLS files outside the bundled program directory')
    for name in ('certificate_file', 'private_key_file'):
        item = value[name]
        if item and (item.is_relative_to(data) or item.is_relative_to(assets)):
            raise ConfigurationError('Keep TLS files in config, separate from game assets and server data')
    if path.is_relative_to(data) or path.is_relative_to(assets):
        raise ConfigurationError('Keep host configuration separate from assets and writable data')
    value.pop('schema')
    return HostConfig(source=path, **value)
