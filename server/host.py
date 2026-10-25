"""Config-file Windows host with local startup checks and bounded diagnostics."""
from __future__ import annotations
import argparse
import asyncio
import ctypes
import json
import os
from pathlib import Path
import platform
import ssl
import sys
import tempfile

from .configuration import load_config, ConfigurationError
from .assets import verify_assets
from .credentials import CredentialStore, CredentialError
from .tls_transport import load_server_context, TLSConfigurationError
from .game_data import GameTemplate
from .worker_client import SimulationWorker, WorkerError
from .profiles import ProfileStore
from .cosmetics import CosmeticCatalog
from .dedicated_server import DedicatedServer
from .admission import AdmissionController
from .host_audit import HostAudit
from .web_dashboard import Dashboard
from .state_lock import exclusive_state, StateBusyError
from .protobuf_wire import field_uint
from . import protocol


def prepare(config):
    if os.name != 'nt' or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise ConfigurationError('The simulation host requires64-bit Windows')
    manifest = verify_assets(config.assets_directory)
    template = GameTemplate.load(config.assets_directory / 'map-1v1.pb.gz',
        catalog_path=config.assets_directory / 'unit-catalog.json', descriptors_path=config.assets_directory / 'descriptors')
    context = store = None
    if not config.allow_insecure_loopback:
        context = load_server_context(config.certificate_file, config.private_key_file)
        if config.access_mode == 'invite':
            store = CredentialStore(config.credential_directory)
            store.list_public()  # Exercise private locking and parsing before listening.
    config.data_directory.mkdir(parents=True, exist_ok=True)
    # Verify create/write/fsync/delete under the configured account, without
    # touching a profile, invite, existing log or program file.
    with tempfile.TemporaryFile(dir=config.data_directory) as probe:
        probe.write(b'Battle Aces host write check\n'); probe.flush(); os.fsync(probe.fileno())
    (config.data_directory / 'workers').mkdir(exist_ok=True)
    return template, context, store, manifest


async def check_native(config, template):
    match = template.build_match([dict(slot=0, player_id=1, name='Health A', army_id=0),
                                  dict(slot=1, player_id=2, name='Health B', army_id=1)],
                                 template.default_decks, seed=1, game_name='host-health-check')
    worker = await SimulationWorker.create(match.raw_game_data, config.assets_directory / 'Simulation.dll',
                                           working_directory=config.data_directory / 'workers')
    try:
        initial = await worker.state()
        result = await worker.process_frame(field_uint(1, 0) + field_uint(2, 20) + field_uint(3, 50))
        if initial['frame'] != 0xffffffff or result.frame != 0:
            raise WorkerError('native startup check returned an unexpected frame')
        report = dict(pid=worker.pid, simulation_sha256=worker.dll_sha256, created=True, stepped_frame=result.frame)
    finally:
        await worker.close()
    if worker.process.poll() != 0: raise WorkerError('native startup check did not close cleanly')
    report.update(exit_code=0, reaped=True)
    return report


async def run(config, *, check_only=False, on_progress=None, on_ready=None):
    # Claim data before checking storage, starting a worker or opening logs.
    # Check/backup/another host must never race this deployment's mutations.
    with exclusive_state(config.data_directory):
        return await _run_owned(config, check_only=check_only, on_progress=on_progress, on_ready=on_ready)


async def _run_owned(config, *, check_only=False, on_progress=None, on_ready=None):
    template, context, store, manifest = prepare(config)
    if on_progress: on_progress('assets_and_storage_checked')
    native = await check_native(config, template)
    if on_progress: on_progress('native_checked')
    health = dict(passed=True, python=platform.python_version(), openssl=ssl.OPENSSL_VERSION,
        platform=platform.platform(), pointer_bits=ctypes.sizeof(ctypes.c_void_p)*8,
        game_build=manifest['game_build'], game_protocol=protocol.VERSION, asset_format=manifest['asset_format'],
        tls=context is not None, credential_store_checked=store is not None, native=native,
        scope='local configuration, asset hashes, private storage if enabled, native create/step/close; no internet reachability proof')
    print(json.dumps(health, separators=(',', ':')), flush=True)
    if check_only: return health
    audit = HostAudit(config.data_directory / 'logs', max_bytes=config.log_max_bytes,
                      backups=config.log_backups, diagnostics=config.diagnostic_audit)
    server = dashboard = None
    try:
        from .worker_ai import AISetup
        templates, catalog = {1: template}, None
        if 'bot-catalog.json' in manifest['files']:
            from .ai_rules import RuleBook
            from .bot_catalog import BotCatalog
            for mode, filename in ((2, 'map-2v2.pb.gz'), (5, 'map-2vai.pb.gz')):
                templates[mode] = GameTemplate.load(config.assets_directory/filename,
                    catalog_path=config.assets_directory/'unit-catalog.json', descriptors_path=config.assets_directory/'descriptors')
            catalog = BotCatalog(config.assets_directory, template=template, rules=RuleBook(config.assets_directory))
        cosmetics = CosmeticCatalog(config.assets_directory) if 'cosmetic-catalog.json' in manifest['files'] else None
        if cosmetics and cosmetics.sha256 != manifest['files']['cosmetic-catalog.json']:
            raise ValueError('Cosmetic catalog changed after asset verification')
        server = DedicatedServer(template, ProfileStore(config.data_directory / 'profiles', template, catalog=cosmetics),
            audit=audit, data_dir=None, audit_state=config.diagnostic_audit,
            max_rooms=config.max_rooms, input_window=config.input_window, templates=templates, bot_catalog=catalog,
            tls_context=context, admission=AdmissionController(store, rc_open=config.access_mode == 'rc-open') if context else None,
            sim_factory=lambda data: SimulationWorker.create(data, config.assets_directory / 'Simulation.dll',
                working_directory=config.data_directory / 'workers'),
            ai_factory=lambda data, bots: SimulationWorker.create(data, config.assets_directory / 'Simulation.dll',
                working_directory=config.data_directory / 'workers', ai=AISetup(config.assets_directory, bots)))
        if config.dashboard_port:
            dashboard = Dashboard(server, config.data_directory / 'web-matches.json')
            try:
                web_address = await dashboard.start(config.dashboard_host, config.dashboard_port)
                print(f'Server dashboard: http://{web_address[0]}:{web_address[1]}', flush=True)
            except (OSError, ValueError):
                await dashboard.close()
                dashboard = None
                print('Dashboard unavailable: check its port and web-matches.json; game hosting continues.', file=sys.stderr)
        address = await server.start(config.listen_host, config.listen_port)
        if on_ready: on_ready(address)
        print(f'Battle Aces server listening on {address[0]}:{address[1]}; Ctrl+C stops it cleanly.', flush=True)
        await server.listener.serve_forever()
    finally:
        try:
            if on_progress: on_progress('stopping')
            if server is not None: await server.close()
        finally:
            try:
                if dashboard is not None: await dashboard.close()
            finally:
                audit.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--check', action='store_true', help='check assets/storage and native worker without opening a public listener')
    args = parser.parse_args(argv)
    try:
        asyncio.run(run(load_config(args.config), check_only=args.check))
        return 0
    except KeyboardInterrupt:
        return 0
    except (ConfigurationError, CredentialError, TLSConfigurationError, StateBusyError) as error:
        print('Host configuration failed: ' + str(error), file=sys.stderr)
    except (OSError, ValueError, WorkerError) as error:
        print('Host startup/runtime check failed (' + type(error).__name__ + '): verify local assets, writable data, certificate and native runtime.', file=sys.stderr)
    return 1


if __name__ == '__main__': raise SystemExit(main())
