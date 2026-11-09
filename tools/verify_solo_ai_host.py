"""Owned native solo-AI routing against a reachable loopback TLS server.

Runs the original public button callback through a healthy simulation prefix.
Local policy forbids every authoritative worker; server policy uses a real
Simulation.dll worker. Forced owned teardown does not qualify results or Quit.
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
import subprocess
import time
import traceback

from client_patch.transport import bridge, launcher
from server import admission, community_protocol as c, loadout_protocol, public_protocol as q, tls_transport as tls
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

ROOT = Path(__file__).resolve().parents[1]


def source_hashes():
    names = ('client_patch/src/solo_ai_policy.hpp', 'client_patch/src/public_client.cpp',
             'client_patch/src/practice_ai.cpp', 'client_patch/src/local_loop.cpp',
             'client_patch/transport/launcher.py', 'client_patch/transport/bridge.py',
             'server/public_matchmaking.py', 'server/public_protocol.py',
             'server/dedicated_server.py', 'server/worker_client.py',
             'tools/verify_solo_ai_host.py')
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}


def route_evidence(events, log, host, mode, frames):
    """Assert transport decisions and native world ownership together."""
    commands = [row for row in events if row['event'] == 'probe_public_command']
    states = [row for row in events if row['event'] == 'probe_public_state']
    enters = [row for row in commands if row['kind'] in (q.ENTER, loadout_protocol.ENTER_LOADOUT)]
    ready = [row for row in commands if row['kind'] == q.READY]
    cancels = [row for row in commands if row['kind'] == q.CANCEL]
    assignments = [row for row in events if row['event'] == 'probe_public_assignment']
    attempts = [row for row in events if row['event'] == 'probe_worker_attempt']
    local = host == 'local'
    frame_pattern = r'Offline frame (\d+) submitted;' if local else r'LAN received frame (\d+),'
    received = [int(value) for value in re.findall(frame_pattern, log)]
    require(received and max(received) >= frames, 'native simulation prefix not reached')
    require(f'Solo AI hosting policy: host={host} mode={mode} BA_RESURRECTION_SOLO_AI_HOST_V1' in log,
            'new native hosting policy did not run')
    require('PUBLIC QUEUE SMOKE original OnMapSelected:' in log, 'original public button was not exercised')
    if local:
        require(not ready and not assignments and not attempts, 'local solo AI committed remote work')
        require('owner=local-practice' in log and 'owner=remote' not in log, 'wrong native local world owner')
        bots = 3 if mode == 5 else 1
        require(f'Local AI all ready: bots={bots} sharedSimulation=1 producers={bots+1}' in log,
                'original native AI producers did not join the local simulation')
        require('Local AI owned action:' in log, 'local AI produced no native action in the prefix')
        require(len(enters) == len(cancels) == 1, 'fallback must enter and cancel exactly one intent')
        offered = [row for row in states if row['phase'] == q.OFFERED]
        retired = [row for row in states if row['phase'] == q.RETIRED]
        require(len(offered) == len(retired) == 1 and offered[0]['reason'] == q.SOLO_AI_OFFER,
                'missing authoritative solo offer and retirement')
        require(enters[0]['ticket'] == offered[0]['ticket'] == cancels[0]['ticket'] == retired[0]['ticket'],
                'local handoff crossed queue tickets')
        require(enters[0]['sequence'] < offered[0]['sequence'] < cancels[0]['sequence'] < retired[0]['sequence'],
                'local handoff did not cancel the offered intent before retirement')
        retired_marker = log.find('Solo AI offer retired:')
        practice_marker = log.find('Practice requested:')
        require('beforeReady=1 reason=solo_ai_offer' in log and
                0 <= retired_marker < practice_marker and 'localFallback=1 readySent=0' in log,
                'native local world started before authoritative retirement')
    else:
        require(len(enters) == len(ready) == len(assignments) == len(attempts) == 1 and not cancels,
                'server preference did not preserve one remote READY/assignment/worker')
        offered = [row for row in states if row['phase'] == q.OFFERED]
        require(len(offered) == 1 and offered[0]['reason'] == q.SOLO_AI_OFFER and
                offered[0]['sequence'] < ready[0]['sequence'], 'server preference did not accept the marked solo offer')
        require('owner=remote' in log and 'owner=local-practice' not in log and
                'Public native match joined:' in log and 'Practice requested:' not in log,
                'server preference acquired the wrong native world')
    return dict(public_commands=commands, public_states=states, authoritative_assignments=assignments,
                authoritative_worker_attempts=len(attempts), native_max_frame=max(received),
                native_ai_action_count=log.count('Local AI owned action:'),
                local_world=local, healthy_prefix_only=True)


async def run(args):
    game, assets, output = args.game.resolve(), args.assets.resolve(), args.output.resolve()
    require(os.name == 'nt' and game.is_relative_to(ROOT/'local') and output.is_relative_to(ROOT/'local'),
            'only an owned Windows game and ignored evidence directory are allowed')
    launcher.verify_game(game, community=True, bridge_version=2, unified=True, player_features=True)
    helper = (game/'BattleAcesOffline.dll').read_bytes()
    require(b'BA_RESURRECTION_SOLO_AI_HOST_V1' in helper, 'install the new owned solo-AI helper first')
    verify_assets(assets)
    output.mkdir(parents=True, exist_ok=False)
    pki_folder = output/'ephemeral-pki'
    pki = generate_test_pki(pki_folder)
    credentials, workers, events = Store(), [], []
    audit = Audit(output)
    started = time.monotonic()
    def observe(event, **fields):
        events.append(dict(event=event, observed_at=time.monotonic(), sequence=len(events), **fields))
        audit(event, **fields)
    templates = {mode: GameTemplate.load(assets/name, catalog_path=assets/'unit-catalog.json', descriptors_path=assets/'descriptors')
                 for mode, name in ((1, 'map-1v1.pb.gz'), (2, 'map-2v2.pb.gz'), (5, 'map-2vai.pb.gz'))}
    catalog = BotCatalog(assets, template=templates[1], rules=RuleBook(assets))
    async def factory(data, bots=None):
        observe('probe_worker_attempt', bots=sorted(getattr(bot, 'slot', bot) for bot in (bots or {})))
        require(args.host == 'server', 'local solo AI must never allocate an authoritative worker')
        worker = await SimulationWorker.create(data, assets/'Simulation.dll', working_directory=output,
                                               ai=AISetup(assets, bots) if bots else None)
        workers.append(worker)
        return worker
    cosmetic_book = CosmeticCatalog(assets)
    server = DedicatedServer(templates[1], ProfileStore(output/'profiles', templates[1], catalog=cosmetic_book), templates=templates,
        bot_catalog=catalog, sim_factory=factory, ai_factory=factory, audit=observe, data_dir=output,
        audit_state=False, input_timeout=30, tls_context=tls.load_server_context(pki['cert'], pki['key']),
        admission=admission.AdmissionController(credentials))
    process = job = parent = child = writer = bridge_task = None
    log, launch_tick, attempts = '', None, 0
    report = dict(passed=False, scope=__doc__, host=args.host, mode=args.mode, requested_frames=args.frames,
                  helper_sha256=hashlib.sha256(helper).hexdigest(), source_sha256_at_start=source_hashes())
    try:
        address = await server.start('127.0.0.1', 0)
        report['server_listener_started'] = True
        send = server.community.send
        def witnessed_send(peer, kind, payload):
            if kind == q.STATE:
                observe('probe_public_state', **q.decode_state(payload))
            send(peer, kind, payload)
        server.community.send = witnessed_send
        apply = server.community.public.apply
        witnessed_peers = set()
        async def witnessed_apply(session, kind, command, now):
            if session.peer not in witnessed_peers:
                # Room.prepare_match sends assignments directly through Peer,
                # while queue STATE goes through Community.send.
                peer_send = session.peer.send
                def witnessed_peer_send(kind, payload=b''):
                    if kind in (q.MATCH, loadout_protocol.MATCH_LOADOUT):
                        assignment = q.decode_assignment(payload, complete=kind == loadout_protocol.MATCH_LOADOUT)
                        observe('probe_public_assignment', **{key: value for key, value in assignment.items() if key != 'cosmetics'})
                    return peer_send(kind, payload)
                session.peer.send = witnessed_peer_send
                witnessed_peers.add(session.peer)
            observe('probe_public_command', kind=kind, **{key: value for key, value in command.items()
                    if key in ('request', 'ticket', 'mode', 'wait_ms', 'match')})
            return await apply(session, kind, command, now)
        server.community.public.apply = witnessed_apply
        context = tls.load_client_context(pki['ca'], 'localhost')
        async def resolve():
            nonlocal attempts
            attempts += 1
            return bridge.Remote('127.0.0.1', address[1], context, credentials.player, credentials.token)
        config = dict(game_directory=game, server_host='127.0.0.1', server_port=address[1],
                      display_name='Solo AI Routing Probe', room='community', fullscreen=False,
                      local_profile='soloai_'+secrets.token_hex(8), solo_ai_host=args.host)
        options = argparse.Namespace(run_name='solo-ai-routing', unified_experimental=True, player_features=True)
        parent, child = socket.socketpair(socket.AF_INET)
        parent.setblocking(False)
        reader, writer = await asyncio.open_connection(sock=parent)
        command = launcher.game_arguments(config, None, child.fileno(), options)
        command[command.index('-logFile')+1] = str(output/'game.log')
        command += ['-public-queue-smoke', f'-public-queue-smoke-mode={args.mode}', '-lan-smoke', '-lan-audit',
                    '-dedicated-rematch-smoke', '-practice-ai-smoke', '-public-ai-smoke',
                    '-practice-ai-smoke-matches=1', '-practice-ai-smoke-frames=1200', '-practice-ai-smoke-natural']
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        startup.lpAttributeList = {'handle_list': [child.fileno()]}
        clock = ctypes.WinDLL('kernel32').GetTickCount64
        clock.restype = ctypes.c_ulonglong
        launch_tick = clock()
        child.set_inheritable(True)
        try:
            process = subprocess.Popen(command, cwd=game, startupinfo=startup, close_fds=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        finally:
            child.set_inheritable(False)
        job = _WindowsJob(process.pid)
        child.close()
        bridge_task = asyncio.create_task(bridge.Bridge(reader, writer, resolve, version=2).run())
        report.update(game_pid=process.pid, launch_tick=launch_tick, client_arguments=command)
        (output/'process.json').write_text(json.dumps(report, indent=2)+'\n')
        shutil.copyfile(game/'.battleaces-resurrection/patch-manifest.json', output/'patch-manifest.json')
        pattern = r'Offline frame (\d+) submitted;' if args.host == 'local' else r'LAN received frame (\d+),'
        while True:
            require(process.poll() is None, 'owned native game exited before the healthy prefix')
            log = await asyncio.to_thread(read_native_log, game, process.pid, since_tick=launch_tick)
            for failure in ('Public client failure:', 'Client lifecycle invariant failed:', 'Practice stopped in ', 'Offline loop stopped in '):
                require(failure not in log, 'native routing failure: '+failure)
            require(not any(row['event'] == 'protocol_error' for row in events), 'server reported a protocol error')
            frames = [int(value) for value in re.findall(pattern, log)]
            if frames and max(frames) >= args.frames:
                break
            require(time.monotonic()-started < args.timeout, 'bounded native routing deadline reached')
            await asyncio.sleep(.25)
        report['routing'] = route_evidence(events, log, args.host, args.mode, args.frames)
        require(all(worker.process.poll() is None and not worker.failure for worker in workers),
                'authoritative worker failed during the native prefix')
        report['passed'] = True
    except BaseException as error:
        report.update(passed=False, error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        if child is not None:
            child.close()
        if process is not None:
            if process.poll() is None:
                process.terminate()
            await asyncio.to_thread(process.wait, timeout=15)
            try:
                log = read_native_log(game, process.pid, since_tick=launch_tick)
                (output/f'native-{process.pid}.log').write_text(log, encoding='utf-8')
            except Exception as error:
                report.update(passed=False, evidence_error=repr(error))
        if job is not None:
            job.close()
        if bridge_task is not None:
            bridge_task.cancel()
            await asyncio.gather(bridge_task, return_exceptions=True)
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 2)
            except (OSError, TimeoutError):
                writer.transport.abort()
        elif parent is not None:
            parent.close()
        await server.close()
        await asyncio.gather(*(worker.close() for worker in workers))
        cleanup = [dict(pid=worker.pid, exit_code=worker.process.poll(), failure=worker.failure,
                        stderr_tail=worker.stderr_tail[-4096:],
                        reaped=worker.process.poll() is not None and worker._cleanup_task is not None and
                               worker._cleanup_task.done() and not worker._stderr_thread.is_alive()) for worker in workers]
        remove_test_pki(pki_folder)
        audit.close()
        report.update(elapsed_seconds=time.monotonic()-started, remote_attempts=attempts,
                      authentications=credentials.calls, events=events, worker_cleanup=cleanup,
                      owned_process_reaped=process is None or process.poll() is not None,
                      teardown='forced owned test termination; not native Quit or completed-game qualification',
                      source_sha256_at_finish=source_hashes())
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= report['source_files_unchanged'] and report['owned_process_reaped'] and all(row['reaped'] for row in cleanup)
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('passed', 'host', 'mode', 'elapsed_seconds', 'error') if key in report}))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'assets', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--host', choices=('local', 'server'), required=True)
    parser.add_argument('--mode', type=int, choices=(1, 5), required=True)
    parser.add_argument('--frames', type=int, default=200)
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    require(200 <= args.frames <= 1200 and 60 <= args.timeout <= 300, 'bounded routing prefix required')
    return asyncio.run(run(args))


if __name__ == '__main__':
    raise SystemExit(main())
