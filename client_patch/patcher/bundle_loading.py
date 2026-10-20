"""Verify local content once and avoid Unity's repeated whole-bundle CRC reads.

Only the supported catalog's CRC numbers change. Bundle bytes and original load
Tasks stay intact. The launch receipt detects ordinary file changes; it is not
a security boundary against an owner editing both content and local receipts.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
from pathlib import Path
import re
import stat
import sys

from . import build37822_bundles as BUILD

CATALOG = 'Battle Aces_Data/StreamingAssets/aa/catalog.json'
BUNDLE_DIR = 'Battle Aces_Data/StreamingAssets/aa/StandaloneWindows64'
BACKUP = '.battleaces-resurrection/original/' + CATALOG
RECEIPT = '.battleaces-resurrection/bundle-verification.json'
MAX_CATALOG = 8 * 1024 * 1024
MAX_RECEIPT = 128 * 1024
FINGERPRINT_KEYS = frozenset(('size', 'mtime_ns', 'ctime_ns', 'device', 'file_id'))


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode('utf-8')


def _unique(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError('Duplicate game verification fields')
    return result


def _path(root, relative):
    from .patch_client import contained_path
    return contained_path(root, relative)


def _checked_path(root, relative, *, missing_ok=False):
    # Check unresolved parents too: resolve() alone would hide an internal link.
    candidate = root / relative
    for item in (candidate, *candidate.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            if missing_ok:
                continue
            raise
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Game content verification does not accept linked paths')
        if item == root:
            break
    return _path(root, relative)


def _ordinary_file(root, relative):
    path = _checked_path(root, relative)
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('A required game content file is not a regular file')
    return path


def _read(root, relative, limit):
    path = _ordinary_file(root, relative)
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Game verification file exceeds its supported size')
    return raw


def inventory_sha256():
    return _sha(_json_bytes(dict(catalog=BUILD.CATALOG_SHA256, bundles=BUILD.BUNDLES)))


def descriptor(*, restored=False):
    return dict(schema=1, enabled=not restored, verification='sha256-at-install',
                catalog_sha256=BUILD.CATALOG_SHA256 if restored else BUILD.CATALOG_PATCHED_SHA256,
                original_catalog_sha256=BUILD.CATALOG_SHA256,
                inventory_sha256=inventory_sha256(), bundle_count=len(BUILD.BUNDLES), receipt=RECEIPT)


def patch_catalog(original):
    if len(original) > MAX_CATALOG or _sha(original) != BUILD.CATALOG_SHA256:
        raise ValueError('Original local catalog does not match the supported build')
    catalog = json.loads(original, object_pairs_hook=_unique)
    old = catalog['m_ExtraDataString']
    data = base64.b64decode(old, validate=True)
    changed = bytearray(data)
    seen = set()
    # The pinned catalog stores these literal JSON records as UTF16 in its
    # binary extra-data buffer. Keep every record length/offset unchanged.
    for match in re.finditer(rb'\{\x00(?:[^\}\x00]\x00|\x00[^\x00])*\}\x00', data):
        text = match[0].decode('utf-16-le')
        value = json.loads(text, object_pairs_hook=_unique)
        bundle_hash = value.get('m_Hash')
        if not isinstance(bundle_hash, str):
            raise ValueError('Local bundle catalog hash is missing')
        name = bundle_hash + '.bundle'
        if (name not in BUILD.BUNDLES or name in seen or type(value.get('m_Crc')) is not int
                or not 0 < value['m_Crc'] <= 0xffffffff
                or value.get('m_BundleSize') != BUILD.BUNDLES[name][0]
                or value.get('m_UseUWRForLocalBundles') is not False):
            raise ValueError('Local bundle catalog records differ from the supported build')
        replacement, count = re.subn(r'("m_Crc"\s*:\s*)([0-9]+)',
                                    lambda m: m[1] + '0' + ' ' * (len(m[2]) - 1), text)
        encoded = replacement.encode('utf-16-le')
        if (count != 1 or len(encoded) != len(match[0])
                or json.loads(replacement, object_pairs_hook=_unique) != dict(value, m_Crc=0)):
            raise ValueError('Local bundle CRC rewrite changed unrelated catalog data')
        changed[match.start():match.end()] = encoded
        seen.add(name)
    if seen != BUILD.BUNDLES.keys():
        raise ValueError('Local bundle catalog inventory is incomplete')
    new = base64.b64encode(changed)
    old_bytes = old.encode('ascii')
    if len(new) != len(old_bytes) or original.count(old_bytes) != 1:
        raise ValueError('Local bundle catalog encoding differs')
    patched = original.replace(old_bytes, new, 1)
    if (len(patched) != len(original) or _sha(patched) != BUILD.CATALOG_PATCHED_SHA256
            or json.loads(patched, object_pairs_hook=_unique) != dict(catalog, m_ExtraDataString=new.decode('ascii'))):
        raise ValueError('Patched local catalog hash differs')
    return patched


def _fingerprint(info):
    return dict(size=info.st_size, mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns,
                device=info.st_dev, file_id=info.st_ino)


def _valid_receipt(value):
    if (not isinstance(value, dict) or set(value) != {'schema', 'inventory_sha256', 'files'}
            or type(value['schema']) is not int or value['schema'] != 1
            or value['inventory_sha256'] != inventory_sha256()
            or not isinstance(value['files'], dict) or value['files'].keys() != BUILD.BUNDLES.keys()):
        return False
    for name, item in value['files'].items():
        if (not isinstance(item, dict) or set(item) != {'sha256', 'fingerprint'}
                or item['sha256'] != BUILD.BUNDLES[name][1] or not isinstance(item['fingerprint'], dict)
                or item['fingerprint'].keys() != FINGERPRINT_KEYS
                or any(type(v) is not int or not 0 <= v < 2**128 for v in item['fingerprint'].values())):
            return False
    return True


def verify_bundles(root, *, previous=None, progress=None):
    """Hash every file at install; rehash only changed fingerprints at launch."""
    root = Path(root).resolve()
    cached = previous['files'] if _valid_receipt(previous) else {}
    files, hashed = {}, 0
    for index, (name, (size, expected)) in enumerate(sorted(BUILD.BUNDLES.items())):
        path = _ordinary_file(root, BUNDLE_DIR + '/' + name)
        before = _fingerprint(path.stat())
        if before['size'] != size:
            raise ValueError('Installed bundle size differs; repair the supported game files')
        if not cached or cached[name]['fingerprint'] != before:
            if progress is not None:
                progress(index, len(BUILD.BUNDLES))
            with path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if _fingerprint(path.stat()) != before:
                raise ValueError('Game content changed during verification')
            if actual != expected:
                raise ValueError('Installed bundle hash differs; repair the supported game files')
            hashed += 1
        files[name] = dict(sha256=expected, fingerprint=before)
    # Do not publish a receipt if a previously checked file changed mid-pass.
    for name, item in files.items():
        if _fingerprint(_ordinary_file(root, BUNDLE_DIR + '/' + name).stat()) != item['fingerprint']:
            raise ValueError('Game content changed during verification')
    if hashed and progress is not None:
        progress(len(BUILD.BUNDLES), len(BUILD.BUNDLES))
    return dict(schema=1, inventory_sha256=inventory_sha256(), files=files), hashed


@dataclass(frozen=True)
class CatalogPlan:
    target: Path
    backup: Path
    original: bytes
    current: bytes
    installed: bytes
    receipt_path: Path
    receipt_before: bytes | None
    receipt_after: bytes | None


def prepare_install(root, *, previous=None, restore=False, progress=None):
    root = Path(root).resolve()
    if restore and not (root / BACKUP).exists():
        if isinstance(previous, dict) and 'asset_loading' in previous:
            raise ValueError('Original local catalog backup is missing')
        return None  # Legacy installs never changed this file.
    target, backup, receipt = (_checked_path(root, name, missing_ok=True) for name in (CATALOG, BACKUP, RECEIPT))
    if target == backup or target == receipt or backup == receipt:
        raise ValueError('Catalog and recovery paths must be separate')
    current = _read(root, CATALOG, MAX_CATALOG)
    original = _read(root, BACKUP, MAX_CATALOG) if backup.exists() else current
    patched = patch_catalog(original)
    if _sha(current) not in (BUILD.CATALOG_SHA256, BUILD.CATALOG_PATCHED_SHA256):
        raise ValueError('Refusing to overwrite unexpected local catalog changes')
    receipt_before = _read(root, RECEIPT, MAX_RECEIPT) if receipt.exists() else None
    receipt_after = None
    if not restore:
        verified, _ = verify_bundles(root, progress=progress)
        receipt_after = _json_bytes(verified)
    return CatalogPlan(target, backup, original, current, original if restore else patched,
                       receipt, receipt_before, receipt_after)


def verify_installed(root, value, *, progress=None):
    root = Path(root).resolve()
    if (not isinstance(value, dict) or value != descriptor() or type(value.get('schema')) is not int
            or type(value.get('enabled')) is not bool or type(value.get('bundle_count')) is not int):
        raise ValueError('Local bundle optimization manifest differs; reinstall the client patch')
    if _sha(_read(root, CATALOG, MAX_CATALOG)) != BUILD.CATALOG_PATCHED_SHA256:
        raise ValueError('Local catalog differs; reinstall the client patch')
    receipt_path = _checked_path(root, RECEIPT, missing_ok=True)
    if receipt_path.exists():
        _ordinary_file(root, RECEIPT)
    try:
        previous = json.loads(_read(root, RECEIPT, MAX_RECEIPT), object_pairs_hook=_unique)
    except (OSError, ValueError):
        previous = None
    verified, hashed = verify_bundles(root, previous=previous, progress=progress)
    if hashed:
        from .patch_client import atomic_write
        atomic_write(receipt_path, _json_bytes(verified))


def console_progress(done, total):
    if done == 0 or done == total or done % 16 == 0:
        # Keep CLI stdout as one machine-readable JSON document for setup/tools.
        print(f'Checking game files ({done}/{total})...', file=sys.stderr, flush=True)
