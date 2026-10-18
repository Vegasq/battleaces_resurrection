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
from .dedicated_server import DedicatedServer
from .admission import AdmissionController
from .host_audit import HostAudit
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


async def run(config, *, check_only=False):
    template, context, store, manifest = prepare(config)
    native = await check_native(config, template)
    health = dict(passed=True, python=platform.python_version(), openssl=ssl.OPENSSL_VERSION,
        platform=platform.platform(), pointer_bits=ctypes.sizeof(ctypes.c_void_p)*8,
        game_build=manifest['game_build'], game_protocol=protocol.VERSION, asset_format=manifest['asset_format'],
        tls=context is not None, credential_store_checked=store is not None, native=native,
        scope='local configuration, asset hashes, private storage if enabled, native create/step/close; no internet reachability proof')
    print(json.dumps(health, separators=(',', ':')), flush=True)
    if check_only: return health
    audit = HostAudit(config.data_directory / 'logs', max_bytes=config.log_max_bytes,
                      backups=config.log_backups, diagnostics=config.diagnostic_audit)
    server = None
    try:
        server = DedicatedServer(template, ProfileStore(config.data_directory / 'profiles', template),
            audit=audit, data_dir=None, audit_state=config.diagnostic_audit,
            max_rooms=config.max_rooms, input_window=config.input_window,
            tls_context=context, admission=AdmissionController(store) if store else None,
            sim_factory=lambda data: SimulationWorker.create(data, config.assets_directory / 'Simulation.dll',
                working_directory=config.data_directory / 'workers'))
        address = await server.start(config.listen_host, config.listen_port)
        print(f'Battle Aces server listening on {address[0]}:{address[1]}; Ctrl+C stops it cleanly.', flush=True)
        await server.listener.serve_forever()
    finally:
        if server is not None: await server.close()
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
    except (ConfigurationError, CredentialError, TLSConfigurationError) as error:
        print('Host configuration failed: ' + str(error), file=sys.stderr)
    except (OSError, ValueError, WorkerError) as error:
        print('Host startup/runtime check failed (' + type(error).__name__ + '): verify local assets, writable data, certificate and native runtime.', file=sys.stderr)
    return 1


if __name__ == '__main__': raise SystemExit(main())
