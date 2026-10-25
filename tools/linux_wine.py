"""Shared Linux helpers for pinned release payloads and isolated Wine commands."""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import zipfile

from tools.package_integrity import PackageError, safe_name, verify


def windows_path(path):
    """Use the standard Z: mapping in our fresh Wine prefixes; never shell eval."""
    return 'Z:' + str(Path(path).resolve()).replace('/', '\\')


def wine_environment(root, *, headless=False):
    environment = os.environ.copy()
    environment.update(WINEPREFIX=str(root / 'wineprefix'), WINEARCH='win64',
                       WINEDLLOVERRIDES='mscoree,mshtml=')
    if headless:
        environment.update(DISPLAY='', WAYLAND_DISPLAY='',
                           WINEDLLOVERRIDES='mscoree,mshtml,winex11.drv,winewayland.drv=')
    return environment


def extract_payload(installer, destination, *, product, installer_bytes,
                    installer_sha256, payload_bytes, payload_sha256):
    """Verify the entire EXE and embedded ZIP before extracting any member."""
    if product not in ('client', 'server'):
        raise ValueError('Unknown installer product')
    if installer.stat().st_size != installer_bytes:
        raise ValueError(f'Expected the release 174 {product} installer (wrong size)')
    data = installer.read_bytes()
    if hashlib.sha256(data).hexdigest() != installer_sha256:
        raise ValueError(f'Release 174 {product} installer SHA256 mismatch')
    start = data.index(b'PK\x03\x04')
    payload = data[start:start + payload_bytes]
    if hashlib.sha256(payload).hexdigest() != payload_sha256:
        raise ValueError('Embedded ZIP SHA256 mismatch')
    package_name = f'battleaces-{product}-win64'
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for item in archive.infolist():
            safe_name(item.filename)
            if not item.filename.startswith(package_name + '/'):
                raise PackageError('Unexpected ZIP root')
        destination.mkdir()
        archive.extractall(destination)
    package = destination / package_name
    verify(package, product)
    return package
