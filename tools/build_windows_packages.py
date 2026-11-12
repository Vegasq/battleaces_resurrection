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
from dataclasses import dataclass
import re

from .audit_repository import inspect_content
from .package_integrity import safe_name, ordinary_file, PackageError, verify
from server.client_compatibility import CLIENT_REVISION

ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = '3.14.8'
PYTHON_ZIP_SHA256 = 'a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310'
PYTHON_URL = 'https://www.python.org/ftp/python/3.14.8/python-3.14.8-embed-amd64.zip'
PACKAGE_VERSION = '0.4.0'
RUNTIME_PTH = b'python314.zip\n.\n../app\n'
COMMON = (
    'server/__init__.py', 'server/protocol.py', 'server/client_compatibility.py', 'server/credentials.py',
    'server/admission.py', 'server/tls_transport.py',
    'tools/__init__.py', 'tools/package_integrity.py',
)
SERVER = COMMON + (
    'server/ai_rules.py', 'server/native_ai.py', 'server/worker_ai.py', 'server/bot_catalog.py',
    'server/assets.py', 'server/community.py', 'server/community_protocol.py',
    'server/cosmetics.py', 'server/loadout_protocol.py', 'server/public_protocol.py', 'server/public_matchmaking.py',
    'server/configuration.py', 'server/dedicated_server.py', 'server/latency_policy.py', 'server/command_scheduling.py', 'server/game_data.py',
    'server/host.py', 'server/host_audit.py', 'server/diagnostics.py', 'server/native_simulation.py',
    'server/web_dashboard.py', 'server/web_dashboard_page.py',
    'server/rc_host.py', 'server/New-RCCertificate.ps1',
    'server/state_lock.py', 'server/state_backup.py', 'server/windows_service.py',
    'server/paths.py', 'server/profiles.py', 'server/profile_io.py', 'server/protobuf_wire.py',
    'server/simulation_worker.py', 'server/tls_listener.py', 'server/worker_client.py',
    'tools/extract_descriptors.py', 'tools/import_assets.py', 'tools/package_server.py',
)
CLIENT = COMMON + (
    'client_patch/__init__.py', 'client_patch/patcher/__init__.py',
    'client_patch/patcher/patch_client.py', 'client_patch/patcher/pe_imports.py',
    'client_patch/patcher/prediction_worker.py', 'client_patch/patcher/prediction_actor_repair.py',
    'client_patch/patcher/prediction_selection.py', 'client_patch/patcher/prediction_click_provenance.py',
    'client_patch/patcher/legacy_compliance.py',
    'client_patch/patcher/startup_tasks.py',
    'client_patch/patcher/bundle_loading.py', 'client_patch/patcher/build37822_bundles.py',
    'client_patch/patcher/telemetry.py', 'client_patch/transport/__init__.py',
    'client_patch/transport/bridge.py', 'client_patch/transport/launcher.py',
    'client_patch/transport/enrollment.py', 'client_patch/transport/client.py',
    'client_patch/transport/rc_setup.py', 'client_patch/launcher/Configure-RCClient.ps1',
    'client_patch/transport/player_name.py',
    'client_patch/launcher/ClientConfig.ps1', 'client_patch/launcher/Launch-Client.ps1',
    'client_patch/launcher/Configure-Client.ps1',
    'tools/package_client.py', 'tools/game_installer.py', 'tools/reset_deck.py',
)
# Explicit private profile only. Ordinary CLIENT and SERVER stay unchanged.
PREDICTION_CLIENT = tuple(dict.fromkeys(CLIENT + (
    'tools/prediction_client.py', 'tools/prepare_prediction_native.py',
    'tools/prediction_crt_attach.py', 'tools/prediction_native.py',
    'server/native_simulation.py', 'server/protobuf_wire.py', 'server/paths.py',
    'server/simulation_worker.py',
    'client_patch/prediction_worker/__init__.py', 'client_patch/prediction_worker/__main__.py',
    'client_patch/prediction_worker/wire.py', 'client_patch/prediction_worker/native.py',
    'client_patch/prediction_worker/checkpoint.py', 'client_patch/prediction_worker/prediction.py',
    'client_patch/prediction_worker/commands.py', 'client_patch/prediction_worker/entities.py',
    'client_patch/prediction_worker/entity_guard.py', 'client_patch/prediction_worker/presentation.py',
    'client_patch/prediction_worker/observation.py',
    'client_patch/prediction_worker/corrections.py',
)))
PREDICTION_PROFILE = 'private-custom-movement-prediction-v1'
PREDICTION_HEAP_SHA256 = '64d8805ca111cf512d0edcd04057fca66db2ab7138bcc1bfed29aa770e62f26b'
PREDICTION_COOPERATIVE_SHA256 = '889be172703008e3aee02fc2b7ee0ac5ab4b3126e5db70979f7221d26828460f'
PREDICTION_MARKERS = (b'BA_RESURRECTION_MOVEMENT_PIPELINE_V1', b'BA_RESURRECTION_MOVEMENT_PACING_V1',
                      b'OfflinePredictionActorUpdate\0', b'OfflinePredictionSelectionCommit\0')


@dataclass(frozen=True)
class PredictionClientProfile:
    heap_helper: Path
    cooperative: Path
    ordinary_gameassembly_sha256: str | None = None
    prediction_gameassembly_sha256: str | None = None
# The server installer reads an already patched local game; these are our own
# validation/export orchestration sources, not original client files or assets.
SERVER = tuple(dict.fromkeys(SERVER + CLIENT + ('tools/server_installer.py',)))
MARKERS = (
    b'BA_RESURRECTION_SOLO_AI_HOST_V1',
    b'BA_RESURRECTION_ONLINE_PRESENTATION_V1', b'OfflinePresentAvailableSimFrame\0',
    b'BA_RESURRECTION_CLIENT_REVISION_V1',
    b'BA_RESURRECTION_NATIVE_BACKUP_GUARD_V1', b'OfflineBackupInitialRead\0', b'OfflineBackupWriteText\0',
    b'BA_RESURRECTION_NATIVE_STORAGE_V1',
    b'BA_RESURRECTION_NATIVE_REPLAY_LONG_PATH_V2',
    b'BA_RESURRECTION_PUBLIC_QUEUE_V1', b'BA_RESURRECTION_COSMETICS_UNLOCK_V1', b'BA_RESURRECTION_COSMETICS_PERSIST_V1',
    b'BA_RESURRECTION_NATIVE_SETTINGS_ATOMIC_V1',
    b'BA_RESURRECTION_NATIVE_SETTINGS_NOTICE_V1',
    b'BA_RESURRECTION_NATIVE_DECK_INPUT_V1',b'OfflineLocalDeckStorageLoad\0',
    b'BA_RESURRECTION_NATIVE_SETTINGS_ERRORS_V1', b'OfflineLocalUserLoadTable\0', b'OfflineLocalUserSaveTable\0',
    b'BA_RESURRECTION_NATIVE_SETTINGS_V1', b'OfflineLocalUserConfigPath\0',
    b'BA_RESURRECTION_RECOVERY_V1', b'BA_RESURRECTION_TLS_BRIDGE_V1',
    b'BA_RESURRECTION_GAME_PROTOCOL_3', b'BA_RESURRECTION_COMMUNITY_V1',
    b'BA_RESURRECTION_COMMUNITY_ROSTER_V1', b'BA_RESURRECTION_COMMUNITY_INVITES_V1',
    b'BA_RESURRECTION_COMMUNITY_MATCH_V1', b'BA_RESURRECTION_OFFLINE_PRACTICE_V1',
    b'BA_RESURRECTION_PRACTICE_SETTINGS_V1', b'BA_RESURRECTION_MATCH_LOADING_V1',
    b'BA_RESURRECTION_TLS_BRIDGE_V2', b'BA_RESURRECTION_UNIFIED_CLIENT_V1',
)
LAUNCHER_SOURCES = ('server/build_launcher.ps1', 'server/launcher/console_launcher.cpp',
                    'server/launcher/launch_args.hpp', 'server/launcher/launch_args_tests.cpp')


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


def read_helper(path,*,source_revision=None):
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
    from .helper_provenance import validate
    return data,validate(path,data,ROOT,revision=source_revision)


def _prediction_artifact(path, *, arena):
    """Only the named frozen authored helper and its exact current sources."""
    if not isinstance(path, Path):
        raise PackageError('Prediction helpers require explicit source-bound paths')
    path = path.absolute()
    expected_name = 'BAHeap.dll' if arena else 'PredictionCooperative.dll'
    if path.name != expected_name:
        raise PackageError('Prediction helper filename differs from its fixed profile')
    root = Path(path.anchor)
    path = ordinary_file(root, path.relative_to(root).as_posix())
    receipt_path = ordinary_file(root, path.with_name('build.json').relative_to(root).as_posix())
    if not 256 <= path.stat().st_size <= 8*1024*1024 or not 1 <= receipt_path.stat().st_size <= 64*1024:
        raise PackageError('Prediction helper or receipt exceeds its size bound')
    data, raw = path.read_bytes(), receipt_path.read_bytes()
    expected_pin = PREDICTION_HEAP_SHA256 if arena else PREDICTION_COOPERATIVE_SHA256
    if sha(data) != expected_pin:
        raise PackageError('Prediction helper differs from the frozen private profile pin')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value: raise ValueError('duplicate prediction receipt field')
            value[key] = item
        return value
    try:
        value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique)
        offset, = struct.unpack_from('<I', data, 0x3c)
        signature, machine = struct.unpack_from('<4sH', data, offset)
        flags, = struct.unpack_from('<H', data, offset+22)
        magic, = struct.unpack_from('<H', data, offset+24)
        if (data[:2] != b'MZ' or signature != b'PE\0\0' or machine != 0x8664 or
                magic != 0x20b or not flags & 0x2000 or type(value) is not dict or
                value.get('experimental') is not True or value.get('dll_sha256') != expected_pin):
            raise ValueError('prediction helper type/schema')
        sources = {'source_sha256': 'client_patch/checkpoint/' + ('arena.cpp' if arena else 'cooperative.cpp')}
        if arena:
            sources.update(page_source_sha256='client_patch/checkpoint/page_checkpoint.hpp',
                           root_source_sha256='client_patch/checkpoint/thread_state.hpp',
                           entity_guard_source_sha256='client_patch/checkpoint/entityguard.hpp',
                           entity_hooks_source_sha256='client_patch/checkpoint/entityguard_hooks.hpp',
                           build_script_sha256='client_patch/checkpoint/build.ps1')
            abi = dict(entity_guard_abi=1, entity_guard_stats_bytes=96, root_bindings_abi=1,
                       root_bindings_words=7, baseline_forget_abi=1, page_storage_abi=2,
                       foreign_event_abi=1, foreign_event_bytes=472, foreign_event_capacity=8,
                       foreign_event_frames=16)
            if any(type(value.get(key)) is not int or value[key] != expected for key, expected in abi.items()):
                raise ValueError('prediction helper ABI')
        if any(value.get(key) != sha(source_file(name)) for key, name in sources.items()):
            raise ValueError('prediction helper source identity')
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, struct.error):
        raise PackageError('Prediction helper receipt/source identity differs from the frozen profile') from None
    return data, raw


def prediction_profile_files(profile, helper_data, helper_provenance_data):
    if type(profile) is not PredictionClientProfile:
        raise PackageError('Prediction client requires its explicit typed private package profile')
    pins = (profile.ordinary_gameassembly_sha256, profile.prediction_gameassembly_sha256)
    if not (all(value is None for value in pins) or
            all(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) for value in pins)):
        raise PackageError('Prediction GameAssembly pins must be a complete lowercase SHA256 pair')
    if any(marker not in helper_data for marker in PREDICTION_MARKERS):
        raise PackageError('Main helper lacks the private movement prediction ABI')
    heap, heap_receipt = _prediction_artifact(profile.heap_helper, arena=True)
    coop, coop_receipt = _prediction_artifact(profile.cooperative, arena=False)
    roles = {
        'main_helper': ('program/client-helper/BattleAcesOffline.dll', helper_data),
        'main_helper_provenance': ('program/client-helper/helper-provenance.json', helper_provenance_data),
        'heap_helper': ('program/prediction/heap/BAHeap.dll', heap),
        'heap_receipt': ('program/prediction/heap/build.json', heap_receipt),
        'cooperative': ('program/prediction/cooperative/PredictionCooperative.dll', coop),
        'cooperative_receipt': ('program/prediction/cooperative/build.json', coop_receipt),
    }
    descriptor = dict(schema=1, profile=PREDICTION_PROFILE, python='program/runtime/python.exe',
                      module_root='program/app', artifacts={
                          role: dict(path=path, sha256=sha(data)) for role, (path, data) in roles.items()})
    if pins[0] is not None:
        descriptor['gameassembly'] = dict(ordinary_sha256=pins[0], prediction_sha256=pins[1])
    files = {path: data for path, data in roles.values()}
    files['program/prediction/prediction-profile.json'] = json_bytes(descriptor)
    return files


def read_server_launcher(path):
    path = Path(path)
    if not 256 <= path.stat().st_size <= 2*1024*1024: raise PackageError('Unexpected server launcher size')
    data = path.read_bytes()
    try:
        offset, = struct.unpack_from('<I', data, 0x3c)
        signature, machine = struct.unpack_from('<4sH', data, offset)
        flags, = struct.unpack_from('<H', data, offset+22)
        magic, = struct.unpack_from('<H', data, offset+24)
        subsystem, = struct.unpack_from('<H', data, offset+24+68)
        if (data[:2] != b'MZ' or signature != b'PE\0\0' or machine != 0x8664 or magic != 0x20b or
                flags & 0x2000 or not flags & 2 or subsystem != 3 or b'BA_RESURRECTION_SERVER_CONSOLE_V1' not in data):
            raise ValueError()
    except (ValueError, struct.error): raise PackageError('Expected our AMD64 console server launcher') from None
    receipt_data = path.with_name('launcher-build.json').read_bytes()
    try:
        receipt = json.loads(receipt_data)
        expected = {name: sha(source_file(name)) for name in LAUNCHER_SOURCES}
        if (receipt.get('schema') != 1 or receipt.get('launcher_sha256') != sha(data) or
                receipt.get('source_sha256') != expected or receipt.get('argument_tests_passed') is not True):
            raise ValueError()
    except (ValueError, TypeError, AttributeError): raise PackageError('Server launcher build receipt differs from current tested sources') from None
    return data, receipt_data


def read_client_installer(path):
    path = Path(path)
    data = path.read_bytes()
    receipt_data = path.with_name('installer-build.json').read_bytes()
    from tools.build_client_installer import SOURCES
    receipt = json.loads(receipt_data)
    if (not data.startswith(b'MZ') or not 1024 <= len(data) <= 1024*1024
            or receipt.get('schema') != 1 or receipt.get('installer_sha256') != sha(data)
            or receipt.get('payload_sha256') is not None or receipt.get('powershell_required') is not False
            or receipt.get('source_sha256') != {name:sha(source_file(name)) for name in SOURCES}):
        raise PackageError('Native installer build receipt differs from current sources')
    return data, receipt_data


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
    if product == 'client':
        return ('@echo off\r\nsetlocal\r\n'
            'if "%~1"=="" (\r\n'
            '  "%~dp0Install Battle Aces.exe"\r\n'
            '  exit /b\r\n)\r\n'
            '"%~dp0program\\runtime\\python.exe" -I -B -m tools.package_client %*\r\n'
            'exit /b %errorlevel%\r\n').encode('ascii')
    return ('@echo off\r\nsetlocal\r\n'
        'if "%~1"=="" (\r\n'
        f'  "%~dp0program\\runtime\\python.exe" -I -B -m tools.package_{product} --help\r\n'
        '  echo.\r\n  echo Read QUICKSTART.txt for first-time setup.\r\n  pause\r\n  exit /b 0\r\n)\r\n'
        f'"%~dp0program\\runtime\\python.exe" -I -B -m tools.package_{product} %*\r\n'
        'exit /b %errorlevel%\r\n').encode('ascii')


def start_wrapper(product):
    return ('@echo off\r\nsetlocal\r\n'
        f'"%~dp0program\\runtime\\python.exe" -I -B -m tools.package_{product} start %*\r\n'
        'exit /b %errorlevel%\r\n').encode('ascii')


def write_zip(path, files, prefix):
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(prefix + '/' + name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0x20  # Windows archive file, not a Unix symlink.
            archive.writestr(info, data, compresslevel=9)


def build(runtime_zip, helper, output, *, allow_dirty=False, server_launcher=None, client_installer=None, certificate_tool=None, helper_source_revision=None, prediction_client=None):
    output = Path(output).absolute()
    # Developer outputs stay in ignored roots; never write archives into source
    # or over an existing package. Failed builds remain for inspection.
    resolved = output.resolve()
    if resolved.is_relative_to(ROOT) and not any(resolved.is_relative_to(ROOT / name) for name in ('local', 'dist')):
        raise PackageError('Build output inside the checkout must use local/ or dist/')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise PackageError('Choose a fresh empty output directory')
    runtime,source = read_runtime(runtime_zip),source_revision()
    helper_data,helper_provenance=read_helper(helper,source_revision=helper_source_revision)
    if helper_provenance['source']['mode']=='current-worktree':helper_provenance['source'].update(revision=source['revision'],dirty=source['dirty'])
    else:helper_provenance['source']['dirty']=False
    helper_provenance_data=json_bytes(helper_provenance)
    private_files = (prediction_profile_files(prediction_client, helper_data, helper_provenance_data)
                     if prediction_client is not None else None)
    launcher_data = launcher_receipt = installer_data = installer_receipt = None
    if private_files is None:
        launcher_data, launcher_receipt = read_server_launcher(server_launcher or ROOT/'build/server-launcher/Start Server.exe')
    installer_data, installer_receipt = read_client_installer(client_installer or ROOT/'build/client-installer/Install Battle Aces.exe')
    crypto = None
    if certificate_tool is not None:
        from .build_certificate_tool import SOURCES
        tool=Path(certificate_tool);data=tool.read_bytes();receipt=tool.with_name('certificate-build.json').read_bytes()
        value=json.loads(receipt)
        if (not data.startswith(b'MZ') or value.get('sha256')!=sha(data)
                or value.get('source_sha256')!={n:sha(source_file(n)) for n in SOURCES}):
            raise PackageError('Certificate helper build differs from current sources')
        crypto=(data,receipt)
    if source['dirty'] and not allow_dirty: raise PackageError('Commit source changes or explicitly use --allow-dirty for a local preview')
    versions = dict(package=PACKAGE_VERSION, client_revision=CLIENT_REVISION, game_build=37822, game_protocol=3, community_protocol=2,
                    community_protocol_min=1,
                    asset_format=1, patch_schema=2, python=PYTHON_VERSION, platform='windows-amd64')
    plans = {}
    products = (('client', PREDICTION_CLIENT),) if private_files is not None else (('server', SERVER), ('client', CLIENT))
    for product, sources in products:
        files = dict(runtime)
        for name in sources: files['program/app/' + name] = source_file(name)
        if private_files is not None:
            files.update(private_files)
            files['Install Battle Aces.exe'] = installer_data
            files['program/installer/installer-build.json'] = installer_receipt
            files['Start Prediction Client.cmd'] = (b'@echo off\r\nsetlocal DisableDelayedExpansion\r\n'
                b'"%~dp0program\\runtime\\python.exe" -I -B -m tools.prediction_client start %*\r\n'
                b'exit /b %errorlevel%\r\n')
            files['PREDICTION-TEST.txt'] = source_file('docs/prediction-test-guide.txt')
        else:
            files['BattleAces-' + product.title() + '.cmd'] = wrapper(product)
        if product == 'client' and private_files is None:
            files['Install Battle Aces.exe'] = installer_data
            files['program/installer/installer-build.json'] = installer_receipt
            files['Start Client.cmd'] = start_wrapper(product)
            files['Watch Replay.cmd'] = (b'@echo off\r\nsetlocal DisableDelayedExpansion\r\n'
                b'call "%~dp0Start Client.cmd" --replay\r\nexit /b %errorlevel%\r\n')
            files['Setup Client.cmd'] = wrapper(product)
        elif product == 'server':
            files['Start Server.exe'] = launcher_data
            files['program/client-helper/BattleAcesOffline.dll']=helper_data
            files['program/launcher/launcher-build.json'] = launcher_receipt
            if crypto:
                files['program/crypto/Generate Certificate.exe']=crypto[0]
                files['program/crypto/certificate-build.json']=crypto[1]
        files['QUICKSTART.txt'] = (b'PRIVATE CUSTOM AND SERVER AI MOVEMENT PREDICTION TEST\r\n\r\n'
            b'Use an independent game copy and install the matching ordinary patch with the included installer.\r\n'
            b'Then use the Battle Aces Prediction Test desktop shortcut created by the installer.\r\n'
            b'Or open Start Prediction Client.cmd inside your selected test game folder.\r\n'
            b'See PREDICTION-TEST.txt for public1v1 server AI and Custom1v1 setup.\r\n'
            b'Choose the game explicitly: Start Prediction Client.cmd --game "C:\\Games\\Battle Aces"\r\n'
            b'Use program\\runtime\\python.exe -I -B -m tools.prediction_client --help for check/prepare/start.\r\n'
            b'No original game files are included. Keep the normal client for ordinary play.\r\n'
            if private_files is not None else source_file('docs/windows-' + product + '-quickstart.txt'))
        files['program/client-helper/helper-provenance.json']=helper_provenance_data
        compatibility = dict(schema=1, product=product, versions=versions, source=source,
            maturity='development-preview', clean_windows_qualified=False,
            runtime=dict(url=PYTHON_URL, sha256=PYTHON_ZIP_SHA256, path_file_modified=True),
            helper_sha256=sha(helper_data) if product == 'client' else None,
            helper_build=dict(helper_sha256=sha(helper_data),source=helper_provenance['source'],
                provenance_path='program/client-helper/helper-provenance.json',provenance_sha256=sha(helper_provenance_data)),
            server_launcher_sha256=sha(launcher_data) if product == 'server' else None,
            game_files_included=False)
        if private_files is not None:
            compatibility.update(maturity='private-experiment', prediction_profile=PREDICTION_PROFILE,
                                 prediction_profile_path='program/prediction/prediction-profile.json')
        files['compatibility.json'] = json_bytes(compatibility)
        if product == 'server':
            files['SERVICE.txt'] = source_file('docs/windows-service.txt')
            files['DASHBOARD.txt'] = source_file('docs/server-dashboard175.txt')
            files['config/host.example.json'] = source_file('server/host-config.example.json')
            files['assets/IMPORT.txt'] = b'Import your local build37822 assets here; see QUICKSTART.txt. No game files are included.\n'
            files['data/README.txt'] = b'Writable host data belongs here. Stop the host before backup; keep credentials private.\n'
        else:
            files['program/client-helper/BattleAcesOffline.dll'] = helper_data
            files['config/client.example.json'] = source_file('client_patch/launcher/secure-client-config.example.json')
            files['config/unified-client.example.json'] = source_file('client_patch/launcher/unified-client.example.json')
            files['config/rc-client.example.json'] = source_file('client_patch/launcher/rc-client.example.json')
            files['config/practice.example.json'] = source_file('client_patch/launcher/offline-practice.example.json')
        manifest = dict(schema=1, product=product, versions=versions, source=source,
            files={name: dict(bytes=len(data), sha256=sha(data)) for name, data in sorted(files.items())})
        files['package-manifest.json'] = json_bytes(manifest)
        if len({safe_name(name).casefold() for name in files}) != len(files): raise PackageError('Duplicate output path')
        plans[product] = files
    output.mkdir(parents=True, exist_ok=True)
    report = dict(versions=versions, source=source, packages={})
    for product, files in plans.items():
        label = ('battleaces-client-prediction-private-win64' if private_files is not None
                 else 'battleaces-' + product + '-win64')
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


def build_prediction_client(runtime_zip, helper, output, *, heap_helper, cooperative,
                            ordinary_gameassembly_sha256=None, prediction_gameassembly_sha256=None,
                            allow_dirty=False, helper_source_revision=None, client_installer=None):
    """Explicit private client-only package; ordinary builder defaults stay intact."""
    return build(runtime_zip, helper, output, allow_dirty=allow_dirty,
                 client_installer=client_installer,
                 helper_source_revision=helper_source_revision,
                 prediction_client=PredictionClientProfile(heap_helper, cooperative,
                     ordinary_gameassembly_sha256, prediction_gameassembly_sha256))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-zip', type=Path, required=True)
    parser.add_argument('--helper', type=Path, required=True, help='our compiled BattleAcesOffline.dll, never a game DLL')
    parser.add_argument('--helper-source-revision',help='explicit ancestor commit for a tested frozen helper; default requires current helper sources')
    parser.add_argument('--client-installer', type=Path)
    parser.add_argument('--certificate-tool', type=Path)
    parser.add_argument('--server-launcher', type=Path, help='our compiled Start Server.exe and adjacent source-bound launcher-build.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-dirty', action='store_true', help='local development preview with exact source hashes recorded')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(args.python_zip, args.helper, args.output, allow_dirty=args.allow_dirty, server_launcher=args.server_launcher, client_installer=args.client_installer, certificate_tool=args.certificate_tool,helper_source_revision=args.helper_source_revision), indent=2))
        return 0
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print('Package build failed: ' + str(error))
        return 1


if __name__ == '__main__': raise SystemExit(main())
