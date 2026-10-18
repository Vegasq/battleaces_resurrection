"""Build source-allowlisted Windows previews from a pinned local Python ZIP.

No downloads, game-directory traversal, credentials, assets or captures enter
these packages. Import proprietary runtime assets separately on the owner's PC.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
import stat
import struct
import subprocess
import zipfile

from .audit_repository import inspect_content
from .package_integrity import safe_name, ordinary_file, PackageError, verify

ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = '3.14.8'
PYTHON_ZIP_SHA256 = 'a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310'
PYTHON_URL = 'https://www.python.org/ftp/python/3.14.8/python-3.14.8-embed-amd64.zip'
PACKAGE_VERSION = '0.2.0-dev'
RUNTIME_PTH = b'python314.zip\n.\n../app\n'
COMMON = (
    'server/__init__.py', 'server/protocol.py', 'server/credentials.py',
    'server/admission.py', 'server/tls_transport.py',
    'tools/__init__.py', 'tools/package_integrity.py',
)
SERVER = COMMON + (
    'server/assets.py', 'server/community.py', 'server/community_protocol.py',
    'server/configuration.py', 'server/dedicated_server.py', 'server/game_data.py',
    'server/host.py', 'server/host_audit.py', 'server/native_simulation.py',
    'server/paths.py', 'server/profiles.py', 'server/protobuf_wire.py',
    'server/simulation_worker.py', 'server/tls_listener.py', 'server/worker_client.py',
    'tools/extract_descriptors.py', 'tools/import_assets.py', 'tools/package_server.py',
)
CLIENT = COMMON + (
    'client_patch/__init__.py', 'client_patch/patcher/__init__.py',
    'client_patch/patcher/patch_client.py', 'client_patch/patcher/pe_imports.py',
    'client_patch/patcher/telemetry.py', 'client_patch/transport/__init__.py',
    'client_patch/transport/bridge.py', 'client_patch/transport/launcher.py',
    'client_patch/launcher/ClientConfig.ps1', 'client_patch/launcher/Launch-Client.ps1',
    'tools/package_client.py',
)
MARKERS = (
    b'BA_RESURRECTION_RECOVERY_V1', b'BA_RESURRECTION_TLS_BRIDGE_V1',
    b'BA_RESURRECTION_GAME_PROTOCOL_3', b'BA_RESURRECTION_COMMUNITY_V1',
    b'BA_RESURRECTION_COMMUNITY_ROSTER_V1', b'BA_RESURRECTION_COMMUNITY_INVITES_V1',
    b'BA_RESURRECTION_COMMUNITY_MATCH_V1', b'BA_RESURRECTION_OFFLINE_PRACTICE_V1',
    b'BA_RESURRECTION_PRACTICE_SETTINGS_V1', b'BA_RESURRECTION_MATCH_LOADING_V1',
)


def sha(data): return hashlib.sha256(data).hexdigest()


def json_bytes(value): return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode('utf-8')


def read_runtime(path):
    path = Path(path)
    if not 1 <= path.stat().st_size <= 32*1024*1024: raise PackageError('Unexpected Python archive size')
    data = path.read_bytes()
    if sha(data) != PYTHON_ZIP_SHA256: raise PackageError('Python ZIP does not match the pinned official SHA256')
    files, names = {}, set()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if not 1 <= len(infos) <= 128 or sum(i.file_size for i in infos) > 96*1024*1024:
            raise PackageError('Unexpected runtime archive inventory')
        for info in infos:
            safe_name(info.orig_filename)
            if info.orig_filename != info.filename: raise PackageError('Runtime member name was normalized')
            safe_name(info.filename)
            mode = info.external_attr >> 16
            if info.is_dir() or (stat.S_IFMT(mode) and not stat.S_ISREG(mode)) or info.flag_bits & 1:
                raise PackageError('Unexpected runtime archive member type')
            if info.filename.casefold() in names: raise PackageError('Ambiguous runtime archive paths')
            names.add(info.filename.casefold())
            files[info.filename] = archive.read(info)
    required = {'python.exe', 'python314.dll', 'python314.zip', 'python314._pth', 'LICENSE.txt', '_ssl.pyd', '_ctypes.pyd'}
    if not required <= files.keys(): raise PackageError('Runtime archive lacks required components')
    # Isolated paths, no site customization, no installation/global PATH dependency.
    files['python314._pth'] = RUNTIME_PTH
    return {'program/runtime/' + name: data for name, data in files.items()}


def read_helper(path):
    path = Path(path)
    if not 256 <= path.stat().st_size <= 8*1024*1024: raise PackageError('Unexpected helper size')
    data = path.read_bytes()
    try:
        offset, = struct.unpack_from('<I', data, 0x3c)
        signature, machine = struct.unpack_from('<4sH', data, offset)
        flags, = struct.unpack_from('<H', data, offset+22)
        magic, = struct.unpack_from('<H', data, offset+24)
        if data[:2] != b'MZ' or signature != b'PE\0\0' or machine != 0x8664 or magic != 0x20b or not flags & 0x2000:
            raise ValueError()
    except (ValueError, struct.error): raise PackageError('Expected our AMD64 helper DLL') from None
    if any(marker not in data for marker in MARKERS): raise PackageError('Helper is missing required feature/protocol markers')
    return data


def source_file(name):
    path = ordinary_file(ROOT, name)
    data = path.read_bytes()
    reasons = inspect_content(name, data)
    if reasons: raise PackageError('Source audit rejected ' + name + ': ' + '; '.join(reasons))
    return data


def source_revision():
    revision = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = bool(subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain', '--untracked-files=normal'], text=True).strip())
    return dict(revision=revision, dirty=dirty)


def wrapper(product):
    # The quoted executable/module root are independent of the user's cwd. The
    # sole forwarded values are the user's own command arguments, never secrets.
    return ('@echo off\r\nsetlocal\r\n'
        'if "%~1"=="" (\r\n'
        f'  "%~dp0program\\runtime\\python.exe" -I -B -m tools.package_{product} --help\r\n'
        '  echo.\r\n  echo Read QUICKSTART.txt for first-time setup.\r\n  pause\r\n  exit /b 0\r\n)\r\n'
        f'"%~dp0program\\runtime\\python.exe" -I -B -m tools.package_{product} %*\r\n'
        'exit /b %errorlevel%\r\n').encode('ascii')


def write_zip(path, files, prefix):
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(prefix + '/' + name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0x20  # Windows archive file, not a Unix symlink.
            archive.writestr(info, data, compresslevel=9)


def build(runtime_zip, helper, output, *, allow_dirty=False):
    output = Path(output).absolute()
    # Developer outputs stay in ignored roots; never write archives into source
    # or over an existing package. Failed builds remain for inspection.
    resolved = output.resolve()
    if resolved.is_relative_to(ROOT) and not any(resolved.is_relative_to(ROOT / name) for name in ('local', 'dist')):
        raise PackageError('Build output inside the checkout must use local/ or dist/')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise PackageError('Choose a fresh empty output directory')
    runtime, helper_data, source = read_runtime(runtime_zip), read_helper(helper), source_revision()
    if source['dirty'] and not allow_dirty: raise PackageError('Commit source changes or explicitly use --allow-dirty for a local preview')
    versions = dict(package=PACKAGE_VERSION, game_build=37822, game_protocol=3, community_protocol=1,
                    asset_format=1, patch_schema=2, python=PYTHON_VERSION, platform='windows-amd64')
    plans = {}
    for product, sources in (('server', SERVER), ('client', CLIENT)):
        files = dict(runtime)
        for name in sources: files['program/app/' + name] = source_file(name)
        files['BattleAces-' + product.title() + '.cmd'] = wrapper(product)
        files['QUICKSTART.txt'] = source_file('docs/windows-' + product + '-quickstart.txt')
        compatibility = dict(schema=1, product=product, versions=versions, source=source,
            maturity='development-preview', clean_windows_qualified=False,
            runtime=dict(url=PYTHON_URL, sha256=PYTHON_ZIP_SHA256, path_file_modified=True),
            helper_sha256=sha(helper_data) if product == 'client' else None,
            game_files_included=False)
        files['compatibility.json'] = json_bytes(compatibility)
        if product == 'server':
            files['config/host.example.json'] = source_file('server/host-config.example.json')
            files['assets/IMPORT.txt'] = b'Import your local build37822 assets here; see QUICKSTART.txt. No game files are included.\n'
            files['data/README.txt'] = b'Writable host data belongs here. Stop the host before backup; keep credentials private.\n'
        else:
            files['program/client-helper/BattleAcesOffline.dll'] = helper_data
            files['config/client.example.json'] = source_file('client_patch/launcher/secure-client-config.example.json')
            files['config/practice.example.json'] = source_file('client_patch/launcher/offline-practice.example.json')
        manifest = dict(schema=1, product=product, versions=versions, source=source,
            files={name: dict(bytes=len(data), sha256=sha(data)) for name, data in sorted(files.items())})
        files['package-manifest.json'] = json_bytes(manifest)
        if len({safe_name(name).casefold() for name in files}) != len(files): raise PackageError('Duplicate output path')
        plans[product] = files
    output.mkdir(parents=True, exist_ok=True)
    report = dict(versions=versions, source=source, packages={})
    for product, files in plans.items():
        label = 'battleaces-' + product + '-win64'
        folder = output / label
        folder.mkdir()
        for name, data in sorted(files.items()):
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream: stream.write(data)
        verify(folder, product)
        archive = output / (label + '.zip')
        write_zip(archive, files, label)
        with archive.open('rb') as stream: digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        report['packages'][product] = dict(archive=archive.name, sha256=digest, bytes=archive.stat().st_size, files=len(files))
    (output / 'build-report.json').write_bytes(json_bytes(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-zip', type=Path, required=True)
    parser.add_argument('--helper', type=Path, required=True, help='our compiled BattleAcesOffline.dll, never a game DLL')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-dirty', action='store_true', help='local development preview with exact source hashes recorded')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(args.python_zip, args.helper, args.output, allow_dirty=args.allow_dirty), indent=2))
        return 0
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print('Package build failed: ' + str(error))
        return 1


if __name__ == '__main__': raise SystemExit(main())
