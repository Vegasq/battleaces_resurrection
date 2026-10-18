"""Detect missing/changed portable-package files; not a code-signing boundary."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys


class PackageError(ValueError):
    pass


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, 'Invalid command or arguments; use --help.\n')


def safe_name(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or '\0' in name:
        raise PackageError('Invalid package member name')
    parts = name.split('/')
    reserved = {'con', 'prn', 'aux', 'nul'} | {f'{prefix}{i}' for prefix in ('com', 'lpt') for i in range(1, 10)}
    if any(not part or part in ('.', '..') or part[-1] in ' .' or
           part.split('.')[0].casefold() in reserved or any(ord(c) < 32 or c in '<>"|?*' for c in part)
           for part in parts):
        raise PackageError('Invalid package member name')
    if PurePosixPath(name).is_absolute(): raise PackageError('Absolute package member')
    return name


def ordinary_file(root, name):
    safe_name(name)
    path = root / name
    try:
        for item in (path, *path.parents):
            information = item.lstat()
            if stat.S_ISLNK(information.st_mode) or getattr(information, 'st_file_attributes', 0) & 0x400:
                raise PackageError('Package paths may not be links or reparse points')
            if item == root: break
        if not path.is_file(): raise PackageError('Package member is not a regular file')
    except OSError:
        raise PackageError('Package file is missing or inaccessible') from None
    return path


def verify(root, product):
    root = Path(root).absolute()
    manifest = ordinary_file(root, 'package-manifest.json')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value: raise PackageError('Duplicate package manifest field')
            value[key] = item
        return value
    try:
        with manifest.open('rb') as stream: raw = stream.read(1024*1024+1)
        if len(raw) > 1024*1024: raise PackageError('Package manifest exceeds its bound')
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
        if not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1 or value.get('product') != product:
            raise PackageError('Wrong package manifest')
        files = value['files']
        if not isinstance(files, dict) or not 1 <= len(files) <= 2048: raise PackageError('Invalid package file inventory')
        folded = set()
        for name, expected in files.items():
            safe_name(name)
            if name.casefold() in folded: raise PackageError('Ambiguous package paths')
            folded.add(name.casefold())
            if not isinstance(expected, dict) or set(expected) != {'bytes', 'sha256'} or type(expected['bytes']) is not int:
                raise PackageError('Invalid package digest')
            if not isinstance(expected['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', expected['sha256']):
                raise PackageError('Invalid package digest')
            path = ordinary_file(root, name)
            if path.stat().st_size != expected['bytes']: raise PackageError('Package file size mismatch: ' + name)
            with path.open('rb') as stream: actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != expected['sha256']: raise PackageError('Package file hash mismatch: ' + name)
        # Data, assets and personal config are deliberately outside this check.
        # No additional modules/DLLs may be planted beside the bundled program.
        for path in (root / 'program').rglob('*'):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise PackageError('Program contains a link or reparse point')
            if path.is_file() and path.relative_to(root).as_posix() not in files:
                raise PackageError('Program contains an unlisted file')
        return value
    except PackageError:
        raise
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, RecursionError):
        raise PackageError('Cannot verify package manifest') from None
