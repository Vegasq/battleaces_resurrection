"""Bounded Settings footer check on an owned native client and loopback TLS host.

Uses original UI callbacks, not physical input. Menu mode observes authenticated
Online, close/reopen, deliberate owned connection loss, Offline, and release.
Match mode opens the real in-match Settings during public server-AI then waits
for original result/Continue. Screenshots require separate visual review. Build
text is diagnostic argv metadata, not proof of a packaged manifest's provenance.
Only retained owned handles are terminated; native Quit is not qualified.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import struct
import subprocess
import time
import traceback

from client_patch.transport import bridge, client, client_info, launcher
from server import admission, tls_transport as tls
from server.ai_rules import RuleBook
from server.assets import verify_assets
from server.bot_catalog import BotCatalog
from server.cosmetics import CosmeticCatalog
from server.dedicated_server import Audit, DedicatedServer
from server.game_data import GameTemplate
from server.profiles import ProfileStore
from server.worker_ai import AISetup
from server.worker_client import SimulationWorker, _WindowsJob
from tests.test_admission import Store
from tests.test_tls_transport import generate_test_pki, remove_test_pki
from tools.run_secure_match import read_native_log
from tools.verify_custom_lobby import require
from tools.verify_original_command_scheduling import cleanup_step, stop_owned_process
from tools.verify_scheduling_server_ai import source_hashes as runtime_hashes, classify_worker_cleanup

ROOT = Path(__file__).resolve().parents[1]


def digest(value):
    return hashlib.sha256(value).hexdigest()


def source_hashes():
    values = runtime_hashes()
    values[Path(__file__).relative_to(ROOT).as_posix()] = digest(Path(__file__).read_bytes())
    return values


def validate_options(args):
    require(args.scope in ('menu', 'match'), 'menu or match Settings scope required')
    require(re.fullmatch('[a-f0-9]{64}', args.expected_helper_sha256) is not None, 'exact helper SHA256 required')
    require(type(args.timeout) in (int, float) and 60 <= args.timeout <= 240, 'bounded Settings deadline required')
    require(isinstance(args.build_label, str) and re.fullmatch(r'[A-Za-z0-9 ().,+-]{1,96}', args.build_label),
            'bounded public diagnostic build label required')


def inspect_png(path):
    from PIL import Image
    raw = path.read_bytes()
    require(len(raw) > 1024 and raw[:8] == b'\x89PNG\r\n\x1a\n' and raw[12:16] == b'IHDR' and
            raw[-12:] == b'\0\0\0\0IEND\xaeB`\x82', 'incomplete native PNG capture')
    width, height = struct.unpack_from('>II', raw, 16)
    require(640 <= width <= 8192 and 360 <= height <= 8192, 'native screenshot dimensions outside bounds')
    with Image.open(path) as image:
        extrema = image.convert('RGB').getextrema()
    require(max(high-low for low,high in extrema) > 32, 'native screenshot is black or flat; visual evidence unavailable')
    return dict(name=path.name, width=width, height=height, bytes=len(raw), sha256=digest(raw), rgb_extrema=extrema)


def idle_inventory():
    # Refuse to compete with manual gameplay; never terminate inventory PIDs.
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
        "@(Get-CimInstance Win32_Process -Filter \"Name='Battle Aces.exe'\" | Select-Object ProcessId,ExecutablePath) | ConvertTo-Json -Compress"],
        check=True, capture_output=True, text=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    values = json.loads(result.stdout) if result.stdout.strip() else []
    require(not values, 'native gameplay is already running; preserving existing processes')
    return dict(battle_aces_processes=[], manual_processes_terminated=False)


def check_log(log, scope, build_label, port, dropped):
    failures = ('SETTINGS STATUS SMOKE failed:', 'Settings build/status failed:', 'Public client failure:',
                'Client lifecycle invariant failed:', 'Offline loop stopped in ')
    require(not any(value in log for value in failures), 'native Settings/lifecycle failure; see retained log')
    phases = ['initial', 'general'] + ([] if scope == 'match' else ['reopened', 'offline'])
    rows = re.findall(r'SETTINGS STATUS SMOKE readback: phase=(\S+) online=(\d) active=1 ownedLabels=1 raycast=0 richText=0 text=(.*)', log)
    require([row[0] for row in rows] == phases, 'Settings readback phase sequence differs')
    for phase, online, label in rows:
        text = json.loads(label)
        require(build_label in text and f'localhost:{port}' in text and
                ('127.0.0.1' in text if online == '1' else '127.0.0.1' not in text),
                'footer build or actual resolved endpoint missing')
        require(online == ('0' if phase == 'offline' else '1'), 'Settings connection state differs')
    require(log.count('SETTINGS STATUS SMOKE released: nativeOwnerReleased=1 ownedChildDestroyed=1') == (1 if scope == 'match' else 2),
            'Settings close/release cleanup count differs')
    if scope == 'menu':
        require(dropped and 'SETTINGS STATUS SMOKE passed: scope=menu onlineDrop=1 reopen=1 released=1' in log,
                'owned disconnect or menu completion missing')
    else:
        require('SETTINGS STATUS SMOKE original in-match Settings ClickEvent: bindingTargetsVerified=1 serializedCallbacks=1 mouseInput=0' in log and
                'SETTINGS STATUS SMOKE passed: scope=in-match online=1 released=1' in log and
                'PUBLIC QUEUE completed return:' in log, 'actual in-match Settings or result/Continue missing')
    return phases


async def run(args):
    validate_options(args)
    game, assets, output = args.game.resolve(), args.assets.resolve(), args.output.resolve()
    local = (ROOT/'local').resolve()
    require(os.name == 'nt' and game.is_relative_to(local) and output.is_relative_to(local) and
            game != local and output != local and not game.is_relative_to(output) and not output.is_relative_to(game),
            'separate owned Windows game and ignored evidence directories required')
    launcher.verify_game(game, community=True, bridge_version=2, unified=True, player_features=True)
    helper = (game/'BattleAcesOffline.dll').read_bytes()
    require(digest(helper) == args.expected_helper_sha256 and b'BA_SETTINGS_STATUS_UI_V1' in helper,
            'exact Settings status helper required')
    inventory = idle_inventory()
    verify_assets(assets)
    output.mkdir(parents=True, exist_ok=False)
    pki_folder = output/'ephemeral-pki'; pki = generate_test_pki(pki_folder)
    audit, events, workers, errors = Audit(output), [], [], []
    credentials = Store(); started = time.monotonic()
    clock = ctypes.WinDLL('kernel32').GetTickCount64; clock.restype = ctypes.c_ulonglong
    report = dict(passed=False, scope=args.scope, evidence_scope=__doc__, helper_sha256=digest(helper),
                  build_label=args.build_label, build_label_source='diagnostic argv',
                  source_sha256_at_start=source_hashes(), screenshots=[], preflight=inventory)
    def observe(event, **fields):
        events.append(dict(event=event, **fields)); audit(event, **fields)
    async def factory(data, bots=None):
        worker = await SimulationWorker.create(data, assets/'Simulation.dll', working_directory=output,
                                               ai=AISetup(assets, bots) if bots else None)
        workers.append(worker); return worker
    template = GameTemplate.load(assets/'map-1v1.pb.gz', catalog_path=assets/'unit-catalog.json', descriptors_path=assets/'descriptors')
    server = DedicatedServer(template, ProfileStore(output/'profiles', template, catalog=CosmeticCatalog(assets)),
        bot_catalog=BotCatalog(assets, template=template, rules=RuleBook(assets)), sim_factory=factory, ai_factory=factory,
        audit=observe, data_dir=output, input_timeout=30, experimental_command_scheduling=True,
        tls_context=tls.load_server_context(pki['cert'], pki['key']), admission=admission.AdmissionController(credentials))
    process = job = parent = child = writer = task = transport = None
    launch_tick = None; dropped = False; log = ''; port = None
    try:
        port = (await server.start('127.0.0.1', 0))[1]
        context = tls.load_client_context(pki['ca'], 'localhost')
        async def resolve(): return bridge.Remote('localhost', port, context, credentials.player, credentials.token)
        config = dict(game_directory=game, server_host='localhost', server_port=port, display_name='Settings Probe',
                      room='community', fullscreen=False, local_profile='settings_ui_'+secrets.token_hex(8), solo_ai_host='server')
        options = client.player_options(build_label=args.build_label, server_label=client_info.configured_label(config))
        parent, child = socket.socketpair(socket.AF_INET); parent.setblocking(False)
        reader, writer = await asyncio.open_connection(sock=parent)
        command = launcher.game_arguments(config, None, child.fileno(), options)
        command[command.index('-logFile')+1] = str(output/'game.log')
        command += ['-settings-status-smoke']
        if args.scope == 'match':
            command += ['-settings-status-smoke-match', '-public-queue-smoke', '-public-queue-smoke-mode=1',
                        '-lan-smoke', '-dedicated-surrender-smoke', '-dedicated-surrender-frame=400', '-dedicated-rematch-smoke']
        # This explicit UI verifier needs rendering. Show only the owned game
        # without activation; hidden Unity windows can produce all-black PNGs.
        startup = subprocess.STARTUPINFO(); startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow = 4
        startup.lpAttributeList = {'handle_list':[child.fileno()]}
        launch_tick = int(clock()); child.set_inheritable(True)
        try:
            process = subprocess.Popen(command, cwd=game, startupinfo=startup, close_fds=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW | 4)
        finally: child.set_inheritable(False); child.close(); child = None
        job = _WindowsJob(process.pid)
        resume = ctypes.WinDLL('ntdll').NtResumeProcess; resume.argtypes = [ctypes.c_void_p]; resume.restype = ctypes.c_long
        require(resume(process._handle) == 0, 'owned suspended client resume failed')
        report.update(pid=process.pid, launch_tick=launch_tick, arguments=command, created_suspended=True,
                      job_assigned_before_resume=True, shown_without_activation=True, server=f'localhost:{port}')
        (output/'process.json').write_text(json.dumps(report, indent=2)+'\n')
        transport = bridge.Bridge(reader, writer, resolve, version=2, status_messages=True)
        task = asyncio.create_task(transport.run())
        while True:
            require(process.poll() is None and not task.done(), 'owned client or bridge exited before Settings completion')
            log = await asyncio.to_thread(read_native_log, game, process.pid, since_tick=launch_tick)
            require('SETTINGS STATUS SMOKE failed:' not in log and 'Settings build/status failed:' not in log,
                    'native Settings failure; see retained logs')
            if args.scope == 'menu' and not dropped and 'SETTINGS STATUS SMOKE ready for owned disconnect: offlineMode=0' in log:
                session = transport.session
                require(session is not None and session.authenticated and session.remote_writer is not None,
                        'authenticated owned remote stream unavailable for deliberate disconnect')
                session.remote_writer.close(); await session.remote_writer.wait_closed()
                dropped = True; observe('probe_owned_connection_dropped', session=session.identity)
            done = 'SETTINGS STATUS SMOKE passed:' in log and (args.scope == 'menu' or 'PUBLIC QUEUE completed return:' in log)
            if done: break
            require(time.monotonic()-started < args.timeout, 'bounded native Settings deadline reached')
            await asyncio.sleep(.2)
        phases = check_log(log, args.scope, args.build_label, port, dropped)
        for phase in phases:
            path = game/'investigation/runtime'/f'settings-status-{process.pid}-{phase}.png'
            report['screenshots'].append(inspect_png(path)); shutil.copyfile(path, output/path.name)
        if args.scope == 'match':
            require(len(workers) == 1 and len([event for event in events if event['event'] == 'match_completed']) == 1,
                    'one completed original server-AI match required')
        else: require(not workers, 'menu-only Settings check unexpectedly created a native match')
        report['passed'] = True
    except BaseException as error:
        report.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        if child is not None: child.close()
        if process is not None:
            await cleanup_step(errors, 'owned client', lambda:stop_owned_process(process))
            await cleanup_step(errors, 'native log', lambda:(output/'native.log').write_text(
                read_native_log(game, process.pid, since_tick=launch_tick), encoding='utf-8'))
        if job is not None: await cleanup_step(errors, 'owned client Job', job.close)
        if task is not None: task.cancel(); await asyncio.gather(task, return_exceptions=True)
        if writer is not None:
            writer.close()
            try: await asyncio.wait_for(writer.wait_closed(), 2)
            except (OSError, TimeoutError): writer.transport.abort()
        elif parent is not None: parent.close()
        await cleanup_step(errors, 'authority', lambda:asyncio.wait_for(server.close(), 30))
        for worker in workers: await cleanup_step(errors, 'native worker', worker.close)
        await cleanup_step(errors, 'ephemeral PKI', lambda:remove_test_pki(pki_folder))
        await cleanup_step(errors, 'audit', audit.close)
        report.update(elapsed_seconds=time.monotonic()-started, cleanup_errors=errors, dropped_owned_connection=dropped,
                      source_sha256_at_finish=source_hashes(), owned_process_reaped=process is None or process.poll() is not None,
                      worker_cleanup=[classify_worker_cleanup(worker, events, complete_match=True) for worker in workers])
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= not errors and report['owned_process_reaped'] and report['source_files_unchanged'] and all(
            item['passed'] for item in report['worker_cleanup'])
        if not report['passed']: report.setdefault('error', 'owned cleanup or source binding failed; see evidence fields')
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('passed','scope','error','elapsed_seconds') if key in report}))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expected-helper-sha256', required=True)
    parser.add_argument('--scope', choices=('menu','match'), required=True)
    parser.add_argument('--build-label', default='0.5.0-rc1 (build diagnostic)')
    parser.add_argument('--timeout', type=float, default=180)
    return asyncio.run(run(parser.parse_args()))


if __name__ == '__main__': raise SystemExit(main())
