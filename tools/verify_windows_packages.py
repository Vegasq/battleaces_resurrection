"""Local portable-package qualification; never a clean-PC/internet acceptance claim."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import traceback
import zipfile

from client_patch.patcher.telemetry import COMPONENTS
from .package_integrity import safe_name, verify

ROOT = Path(__file__).resolve().parents[1]

# Executed by the bundled interpreter with isolated imports. Only the config
# filename is an argument. It opens a numeric-loopback test listener and owns all
# peers/workers; cancellation exercises the host's actual finally/close path.
HOST_LIFECYCLE = r'''
import asyncio, ctypes, dataclasses, json, socket, sys, threading
from ctypes import wintypes
from server import host, protocol as p
from server.configuration import load_config
from server.state_lock import exclusive_state, StateBusyError
from server.state_backup import backup
from server.windows_service import ServiceController, STOP, SHUTDOWN, START_PENDING, RUNNING, STOP_PENDING, STOPPED

async def probe():
    config = load_config(sys.argv[1])
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    config = dataclasses.replace(config, listen_port=port)
    service_mode = sys.argv[2] if len(sys.argv) > 2 else None
    statuses = []
    controller = ServiceController(statuses.append) if service_mode else None
    log_path = config.data_directory/'logs/events.jsonl'
    prior_rows = len(log_path.read_text().splitlines()) if log_path.exists() else 0
    if controller:
        running = asyncio.create_task(asyncio.to_thread(controller.execute,
            lambda ready, progress: host.run(config, on_ready=ready, on_progress=progress)))
    else:
        running = asyncio.create_task(host.run(config))
    peers, handles, workers = [], [], []
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    async def receive(peer, expected):
        async with asyncio.timeout(30):
            while True:
                kind, body = await p.receive(peer[0])
                if kind == expected: return body
                if kind == p.ERROR: raise RuntimeError('Protocol error during packaged lifecycle probe')
    async def send(peer, kind, body):
        peer[1].write(p.encode(kind, body)); await peer[1].drain()
    try:
        async with asyncio.timeout(45):
            while not peers:
                if running.done():
                    await running
                    raise RuntimeError('Host ended before opening its listener')
                try: peers.append(await asyncio.open_connection('127.0.0.1', port))
                except OSError: await asyncio.sleep(.05)
        peers.append(await asyncio.open_connection('127.0.0.1', port))
        for seat, peer in enumerate(peers):
            await send(peer, p.HELLO, p.hello(p.AUTO_SEAT, 'package_probe_'+str(seat), 'Package Probe', 'package_probe'))
            if p.decode_welcome(await receive(peer, p.WELCOME))[0] != seat: raise RuntimeError('Wrong seat')
        await asyncio.gather(*(send(peer, p.LOBBY_READY, b'\x01') for peer in peers))
        bootstraps = await asyncio.gather(*(receive(peer, p.BOOTSTRAP) for peer in peers))
        if bootstraps[0] != bootstraps[1]: raise RuntimeError('Bootstrap mismatch')
        records = [json.loads(line) for line in log_path.read_text().splitlines()[prior_rows:]]
        workers = [row['worker_pid'] for row in records if row['event'] == 'worker_started']
        if len(workers) != 1: raise RuntimeError('Expected one match worker')
        for pid in workers:
            handle = kernel.OpenProcess(0x100000 | 0x1000, False, pid)
            if not handle: raise RuntimeError('Cannot observe owned match worker')
            handles.append(handle)
        try: await host.run(config, check_only=True)
        except StateBusyError: second_host_blocked = True
        else: raise RuntimeError('A second host/check acquired live data')
        attempted_backup = config.source.parent/'blocked-snapshots/live.json'
        try: backup(config, attempted_backup)
        except StateBusyError: live_backup_blocked = True
        else: raise RuntimeError('A backup acquired live host data')
        if attempted_backup.exists(): raise RuntimeError('Refused live backup wrote output')
    finally:
        if controller:
            # An independent thread models SCM's callback thread, not the host
            # event loop. Stop while a native loading worker is still alive.
            control = SHUTDOWN if service_mode == 'shutdown' else STOP
            sender = threading.Thread(target=lambda: (controller.control(control), controller.control(control)))
            sender.start(); await asyncio.to_thread(sender.join, 2)
            if sender.is_alive(): raise RuntimeError('Service control handler blocked')
            if await asyncio.wait_for(asyncio.shield(running), 20) != 0:
                raise RuntimeError('Service controller reported failure')
        for _, writer in peers: writer.close()
        for _, writer in peers:
            try: await asyncio.wait_for(writer.wait_closed(), 2)
            except OSError: pass
        if not controller:
            running.cancel()
            await asyncio.wait_for(asyncio.gather(running, return_exceptions=True), 15)
    try:
        exits = []
        for handle in handles:
            if kernel.WaitForSingleObject(handle, 0) != 0: raise RuntimeError('Owned worker survived shutdown')
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 0: raise RuntimeError('Worker did not exit cleanly')
            exits.append(code.value)
        rows = [json.loads(line) for line in (config.data_directory/'logs/events.jsonl').read_text().splitlines()]
        if rows[-1]['event'] != 'server_stopped': raise RuntimeError('Host did not close cleanly')
        native_files = {p.name:p.stat().st_size for p in (config.data_directory/'workers').iterdir()}
        if native_files != {'sim.log':0}: raise RuntimeError('Native file sink is not disabled')
        if (config.data_directory/'matches').exists(): raise RuntimeError('Host wrote unbounded raw capture files')
        with socket.socket() as test:
            if test.connect_ex(('127.0.0.1', port)) == 0: raise RuntimeError('Listener survived shutdown')
        with exclusive_state(config.data_directory): pass
        if controller:
            states = [status.state for status in statuses]
            if states[-3:] != [RUNNING, STOP_PENDING, STOPPED] or statuses[-1].win32_exit:
                raise RuntimeError('Unexpected service status transitions')
            if any(status.controls for status in statuses if status.state != RUNNING):
                raise RuntimeError('Service accepted controls while pending/stopped')
        print(json.dumps(dict(port=port, peers=2, bootstrap_equal=True, worker_pids=workers,
            worker_exit_codes=exits, listener_closed=True, stopped=True, native_files=native_files,
            second_host_blocked=second_host_blocked, live_backup_blocked=live_backup_blocked, state_lock_released=True,
            service_control=service_mode, service_states=[status.state for status in statuses], scm_registration_tested=False)))
    finally:
        for handle in handles: kernel.CloseHandle(handle)

asyncio.run(probe())
'''


def require(value, message):
    if not value: raise AssertionError(message)


def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def extract(archive, target, product):
    prefix = 'battleaces-' + product + '-win64/'
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        require(len(entries) <= 2048 and sum(info.file_size for info in entries) < 256*1024*1024, 'Unbounded package')
        names = set()
        for info in entries:
            safe_name(info.orig_filename)
            require(info.filename == info.orig_filename and info.filename.startswith(prefix), 'Unexpected archive path')
            name = safe_name(info.filename.removeprefix(prefix))
            require(name.casefold() not in names and not info.is_dir(), 'Duplicate or non-file archive entry')
            names.add(name.casefold())
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream: stream.write(bundle.read(info))
    return verify(target, product)


def run(args):
    output = args.output.resolve()
    output.relative_to(ROOT / 'local')
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    report = dict(passed=False, scope='same-PC relocated packages; imported local assets and patch roundtrip; no graphical play, private ACL, clean-PC or internet acceptance', commands=[])
    package_source = args.packages.resolve()
    build = json.loads((package_source/'build-report.json').read_text())
    game = args.game_dir.resolve()
    originals = {name: digest(game/name) for name in COMPONENTS}
    require(all(originals[name] == recipe.original_sha256 for name, recipe in COMPONENTS.items()), 'Expected pristine local inputs')
    report['original_hashes'] = originals
    folders, inventories = {}, {}
    cwd = output / 'unrelated cwd'; cwd.mkdir()
    (cwd/'sitecustomize.py').write_text('raise RuntimeError("foreign site customization")')
    (cwd/'server.py').write_text('raise RuntimeError("foreign cwd module")')
    environment = os.environ.copy()
    environment.update(PATH=str(Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32'), PYTHONPATH=str(cwd))

    def command(product, label, arguments, *, success=True):
        executable = folders[product]/'program/runtime/python.exe'
        result = subprocess.run([str(executable), '-I', '-B', *arguments], cwd=cwd, env=environment,
            capture_output=True, timeout=180, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        (output/(label+'.stdout.txt')).write_bytes(result.stdout)
        (output/(label+'.stderr.txt')).write_bytes(result.stderr)
        report['commands'].append(dict(label=label, exit_code=result.returncode))
        require((result.returncode == 0) == success, 'Unexpected exit from '+label)
        return result.stdout.decode('utf-8')

    try:
        for product in ('server', 'client'):
            selected = build['packages'][product]
            archive = package_source / safe_name(selected['archive'])
            require(digest(archive) == selected['sha256'], 'Archive hash changed')
            folder = output / (product + ' package with spaces')
            folders[product] = folder
            inventories[product] = extract(archive, folder, product)
            command(product, product+'-verify', ['-m', 'tools.package_'+product, 'verify'])
            modules = sorted({name.removeprefix('program/app/').removesuffix('.py').replace('/', '.').removesuffix('.__init__')
                for name in inventories[product]['files'] if name.startswith('program/app/') and name.endswith('.py')})
            script = ('import importlib,json,ssl,sys; names=json.loads(sys.argv[1]); '
                      'loaded={name:importlib.import_module(name).__file__ for name in names}; '
                      'print(json.dumps(dict(python=sys.version,openssl=ssl.OPENSSL_VERSION,modules=loaded)))')
            imported = json.loads(command(product, product+'-imports', ['-c', script, json.dumps(modules)]))
            require(imported['python'].startswith('3.14.8 '), 'Wrong bundled Python')
            require(all(Path(path).is_relative_to(folder/'program/app') for path in imported['modules'].values()), 'Imported checkout/global modules')
            report[product+'_runtime'] = imported

        command('server', 'asset-import', ['-m', 'tools.package_server', 'import-assets',
            '--game-dir', str(game), '--export-dir', str(args.export_dir.resolve())])
        host = folders['server']
        config = json.loads((host/'config/host.example.json').read_text())
        config.update(listen_host='127.0.0.1', allow_insecure_loopback=True,
                      certificate_file=None, private_key_file=None, credential_directory=None)
        (host/'config/host.json').write_text(json.dumps(config))
        # An interrupted first start may leave an empty lock file. Actual
        # packaged health must recover it under the OS lock, without deletion.
        (host/'data/.host.lock').touch()
        health = command('server', 'host-check', ['-m', 'tools.package_server', 'check'])
        report['health'] = json.loads(health)
        require(report['health']['passed'] and report['health']['native']['reaped'], 'Native health failed')
        lifecycle = command('server', 'host-lifecycle', ['-c', HOST_LIFECYCLE, str(host/'config/host.json')])
        report['lifecycle'] = json.loads(lifecycle.splitlines()[-1])
        registration = json.loads(command('server', 'service-command', ['-m', 'tools.package_server', 'service-command']))
        require(registration['argv'][0] == str(host/'program/runtime/python.exe'), 'Service command uses a different runtime')
        require(registration['startup'] == 'Manual', 'Service registration must be deliberate')
        report['service_registration'] = registration
        command('server', 'service-console-refused', ['-m', 'server.windows_service', '--config', str(host/'config/host.json')], success=False)
        require('Windows Services' in (output/'service-console-refused.stderr.txt').read_text(), 'Expected SCM console refusal')
        report['service_lifecycles'] = []
        for mode in ('stop', 'shutdown'):
            lifecycle = command('server', 'host-service-'+mode,
                ['-c', HOST_LIFECYCLE, str(host/'config/host.json'), mode])
            report['service_lifecycles'].append(json.loads(lifecycle.splitlines()[-1]))

        # Verify the transfer format against real imported assets in the bundled
        # runtime. This authored development snapshot contains no credentials;
        # it does not claim protected backup creation/restore under this token.
        transferred = output/'authored-transfer.backup.json'
        snapshot_script = ('import json,sys,time;from pathlib import Path;'
            'from server.configuration import load_config;from server import state_backup as b;'
            'template,identity=b.load_inputs(load_config(sys.argv[1]));'
            'payload=dict(created_at=int(time.time()),compatibility=identity,'
            'profiles={"package_probe_0":list(template.default_decks[0])},credentials=None);'
            'raw=b.canonical(dict(schema=1,payload=payload,sha256=b.digest(b.canonical(payload))));'
            'stream=Path(sys.argv[2]).open("xb");stream.write(raw);stream.close();'
            'print(json.dumps(dict(bytes=len(raw),authored_development_snapshot=True)))')
        command('server', 'authored-transfer-snapshot', ['-c', snapshot_script, str(host/'config/host.json'), str(transferred)])
        report['transfer_snapshot'] = json.loads(command('server', 'verify-transfer-snapshot',
            ['-m', 'tools.package_server', 'verify-backup', '--input', str(transferred)]))
        require(report['transfer_snapshot']['verified'] and report['transfer_snapshot']['profiles'] == 1,
                'Bundled snapshot verification failed')
        preserve = output/'existing restore destination'; preserve.mkdir()
        (preserve/'owner.txt').write_bytes(b'preserve')
        command('server', 'restore-existing-rejected', ['-m', 'tools.package_server', 'restore',
            '--input', str(transferred), '--destination', str(preserve)], success=False)
        require((preserve/'owner.txt').read_bytes() == b'preserve' and len(list(preserve.iterdir())) == 1,
                'Refused restore changed existing destination')
        report['existing_restore_destination_preserved'] = True

        # A separate component-only working copy qualifies file transactions.
        # It has no graphical assets and is never launched as a game.
        working = output/'component only working copy'
        for name in COMPONENTS:
            target = working/name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(game/name, target)
        owner_note = working/'owner-notes.txt'; owner_note.write_text('keep unchanged')
        action = ['-m', 'tools.package_client', 'install', '--game', str(working)]
        dry_run = json.loads(command('client', 'patch-dry-run', [*action, '--dry-run']))
        require(all(digest(working/name) == original for name, original in originals.items()), 'Dry-run wrote a component')
        require(not (working/'.battleaces-resurrection').exists(), 'Dry-run created backup state')
        installed = json.loads(command('client', 'patch-install', action))
        require(installed == dry_run, 'Install differs from preview')
        for name, component in installed['components'].items():
            require(digest(working/name) == component['installed_sha256'], 'Installed hash mismatch')
            require(digest(working/'.battleaces-resurrection/original'/name) == originals[name], 'Original backup changed')
        require(digest(working/'BattleAcesOffline.dll') == installed['helper_sha256'], 'Helper hash mismatch')
        require(json.loads(command('client', 'patch-reinstall', action)) == installed, 'Reinstall is not idempotent')
        restored = json.loads(command('client', 'patch-restore', ['-m', 'tools.package_client', 'restore', '--game', str(working)]))
        require(restored['state'] == 'restored' and all(digest(working/name) == original for name, original in originals.items()), 'Restore failed')
        require(owner_note.read_text() == 'keep unchanged', 'Unrelated owner file changed')
        report['patch_roundtrip'] = dict(components=len(COMPONENTS), dry_run_no_writes=True, idempotent=True, original_hashes_restored=True)

        # User data must not redirect worker/module imports or mutate the bundle.
        for product, folder in folders.items(): verify(folder, product)
        require(all(digest(game/name) == original for name, original in originals.items()), 'Original source changed')
        report.update(passed=True, program_files_unchanged=True, source_game_files_unchanged=True)
    except BaseException as error:
        report.update(error=type(error).__name__ + ': ' + str(error), traceback=traceback.format_exc())
        raise
    finally:
        report['elapsed_seconds'] = time.perf_counter()-started
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        print('Package evidence: ' + str(output/'verification.json'), flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages', type=Path, required=True)
    parser.add_argument('--game-dir', type=Path, required=True, help='read-only pristine build37822 input')
    parser.add_argument('--export-dir', type=Path, required=True, help='locally produced complete native export')
    parser.add_argument('--output', type=Path, required=True, help='fresh directory under local/')
    run(parser.parse_args(argv))


if __name__ == '__main__': main()
