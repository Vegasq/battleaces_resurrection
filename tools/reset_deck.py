"""Explicit, backed-up reset of the selected native deck, preserving other saves."""
from contextlib import contextmanager
import copy
import ctypes
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tomllib

from client_patch.patcher.patch_client import atomic_write
from client_patch.transport import client, launcher


def reset_bytes(raw):
    if len(raw) > 1024*1024: raise ValueError('Local settings exceed the supported size')
    text = raw.decode('utf-8-sig')
    table = tomllib.loads(text)
    account = table.get('account', {})
    if 'decks' not in account: return raw
    document = json.loads(account['decks'])
    if not isinstance(document, dict) or 'SelectedDeck' not in document:
        raise ValueError('Selected deck is invalid; original save preserved')
    selected = document['SelectedDeck']
    if not isinstance(selected, dict): raise ValueError('Selected deck is invalid; original save preserved')
    # The original selector recognizes an empty selection and loads its own
    # shipped starter deck. Do not hardcode a player's or an AI preset's deck.
    updated = copy.deepcopy(document)
    updated['SelectedDeck'].update(_units=[{'_id':0} for _ in range(8)],
                                  _activeAbilities=[{'_id':0} for _ in range(4)])
    # Accept only the native serializer's single-line assignment. Validate the
    # ENTIRE resulting TOML so a comment/string/other section cannot be edited.
    pattern = re.compile(r'^([ \t]*decks[ \t]*=[ \t]*)([^\r\n]*)(\r?)$', re.M)
    matches = list(pattern.finditer(text))
    if len(matches) != 1: raise ValueError('Settings use an unsupported deck layout; original save preserved')
    match = matches[0]
    replacement = json.dumps(json.dumps(updated, separators=(',', ':'), ensure_ascii=True))
    after = text[:match.start(2)] + replacement + text[match.end(2):]
    expected = copy.deepcopy(table); expected['account']['decks'] = json.dumps(updated, separators=(',', ':'), ensure_ascii=True)
    if tomllib.loads(after) != expected: raise ValueError('Cannot isolate the selected deck; original save preserved')
    return (b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'') + after.encode('utf-8')


def ordinary(path, directory=False):
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            or (not directory and info.st_nlink != 1)):
        raise ValueError('Local profile paths must be ordinary files and folders')


@contextmanager
def profile_lock(folder):
    # Same file and Windows sharing boundary used by the native game's Session.
    # A running game holds it for its entire lifetime, including Quit saves.
    if os.name != 'nt': raise ValueError('Deck reset requires Windows')
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = create(str(folder/'native-settings.lock'), 0xC0000000, 0, None, 4, 0x200080, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ValueError('Close Battle Aces before resetting its deck')
    try:
        ordinary(folder/'native-settings.lock')
        yield
    finally: kernel.CloseHandle(handle)


def reset(game):
    game = Path(game).absolute()
    ordinary(game, True)
    config_path = game/'.battleaces-resurrection/client-config.json'
    for folder in (config_path.parent,): ordinary(folder, True)
    ordinary(config_path)
    settings = client.local_settings(launcher.read_json(config_path, 32768), config_path)
    if settings['game_directory'] != game.resolve(): raise ValueError('Client config belongs to another game folder')
    folder = game/'.battleaces-resurrection/profiles'/settings['local_profile']
    if not folder.exists(): return dict(reset=False, reason='Profile already starts with the default deck')
    ordinary(folder.parent, True); ordinary(folder, True)
    target = folder/'gameconfig-localuser.toml'
    with profile_lock(folder):
        if not target.exists(): return dict(reset=False, reason='Profile already starts with the default deck')
        ordinary(target)
        raw = target.read_bytes(); after = reset_bytes(raw)
        if after == raw: return dict(reset=False, reason='Profile already starts with the default deck')
        backups = folder/'deck-reset-backups'
        backups.mkdir(exist_ok=True); ordinary(backups, True)
        backup = backups/(secrets.token_hex(12)+'.toml')
        with backup.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        if target.read_bytes() != raw: raise ValueError('Settings changed during reset; original save preserved')
        atomic_write(target, after)
    return dict(reset=True, backup=str(backup), saved_decks_preserved=True,
                options_cosmetics_identity_preserved=True, starter_source='original game selector on next launch')
