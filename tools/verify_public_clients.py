"""Two to four graphical public clients in one authoritative multiplayer match.

Original Play/build/surrender/Continue callbacks are explicitly automated. This
is local process qualification, not manual, Internet or native Quit acceptance.
The shared menu gate precedes Play; the real matchmaking clock is never changed.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
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

from client_patch.transport import bridge, launcher
from server import admission, public_protocol as q, tls_transport as tls
from server.ai_rules import RuleBook
from server.assets import verify_assets
from server.bot_catalog import BotCatalog
from server.credentials import AuthenticationError
from server.dedicated_server import Audit, DedicatedServer
from server.game_data import GameTemplate, decode_frame, decode_player_input
from server.profiles import ProfileStore
from server.worker_ai import AISetup
from server.worker_client import SimulationWorker, _WindowsJob
from tests.test_tls_transport import generate_test_pki, remove_test_pki
from tools.run_secure_match import read_native_log
from tools.verify_custom_lobby import require, source_hashes as core_hashes

ROOT = Path(__file__).resolve().parents[1]


def source_hashes():
    paths = [Path(__file__), ROOT/'tools/run_secure_match.py'] + list((ROOT/'client_patch/transport').glob('*.py'))
    return core_hashes() | {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def journal_builds(path, clients, frames):
    """Check native build actions reached the authoritative input journal."""
    found = {}
    with path.open('rb') as stream:
        for number in range(frames):
            header = stream.read(4)
            require(len(header) == 4, 'truncated input journal header')
            size, = struct.unpack('<I', header)
            require(0 < size <= 1024*1024, 'unbounded input journal frame')
            raw = stream.read(size)
            require(len(raw) == size, 'truncated input journal frame')
            frame = decode_frame(raw)
            require(frame['frame'] == number, 'input journal frame sequence differs')
            for row in clients:
                if number != row['build_frame']:
                    continue
                inputs = [decode_player_input(value) for value in frame['players']]
                own = [value for value in inputs if value['identity']['player_id'] == row['seat']+1]
                require(len(own) == 1 and own[0]['actions'], 'native human build absent from authoritative input journal')
                require(own[0]['identity']['name'] == row['name'] and not own[0]['identity']['ai_profile_id'],
                        'native human input identity changed')
                found[row['seat']] = dict(frame=number, actions=len(own[0]['actions']))
        require(not stream.read(1), 'input journal has unaccounted frames')
    require(len(found) == len(clients), 'human input coverage incomplete')
    return found


async def run(args):
    game, assets, output = args.game.resolve(), args.assets.resolve(), args.output.resolve()
    launcher.verify_game(game, community=True, bridge_version=2, unified=True)
    verify_assets(assets)
    output.mkdir(parents=True, exist_ok=False)
    runtime = game/'investigation/runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    gate_key = secrets.token_hex(16)
    gate_path = runtime/f'public-queue-{gate_key}.ready'
    require(not gate_path.exists(), 'diagnostic gate already exists')
    pki_folder = output/'ephemeral-pki'
    pki = generate_test_pki(pki_folder)
    audit, events, workers, clients, sockets = Audit(output), [], [], [], []
    authenticated, attempts = [], [0]*args.humans
    identities = [('p_'+secrets.token_hex(16), 'ba1_'+secrets.token_urlsafe(32)) for _ in range(args.humans)]

    class Store:
        def authenticate(self, token):
            for player, expected in identities:
                if secrets.compare_digest(token, expected):
                    authenticated.append(player)
                    return player
            raise AuthenticationError()

    def observe(event, **fields):
        events.append(dict(event=event, observed_at=time.monotonic(), **fields))
        audit(event, **fields)

    async def factory(data, bots=None):
        worker = await SimulationWorker.create(data, assets/'Simulation.dll', working_directory=output,
                                               ai=AISetup(assets, bots) if bots else None)
        workers.append(worker)
        return worker

    templates = {mode: GameTemplate.load(assets/name, catalog_path=assets/'unit-catalog.json', descriptors_path=assets/'descriptors')
                 for mode, name in ((1, 'map-1v1.pb.gz'), (2, 'map-2v2.pb.gz'), (5, 'map-2vai.pb.gz'))}
    catalog = BotCatalog(assets, template=templates[1], rules=RuleBook(assets))
    server = DedicatedServer(templates[1], ProfileStore(output/'profiles', templates[1]), templates=templates,
        bot_catalog=catalog, sim_factory=factory, ai_factory=factory, audit=observe, data_dir=output,
        audit_state=False, input_timeout=30, tls_context=tls.load_server_context(pki['cert'], pki['key']),
        admission=admission.AdmissionController(Store()))
    started, gate_created = time.monotonic(), False
    report = dict(passed=False, scope=__doc__, mode=args.mode, humans=args.humans, visible=args.visible,
        helper_sha256=hashlib.sha256((game/'BattleAcesOffline.dll').read_bytes()).hexdigest(),
        source_sha256_at_start=source_hashes(), game_pids=[], client_arguments=[], launch_ticks=[])
    clock = ctypes.WinDLL('kernel32').GetTickCount64
    clock.restype = ctypes.c_ulonglong
    try:
        port = (await server.start('127.0.0.1', 0))[1]
        context = tls.load_client_context(pki['ca'], 'localhost')
        shutil.copyfile(game/'.battleaces-resurrection/patch-manifest.json', output/'patch-manifest.json')
        for index in range(args.humans):
            config = dict(game_directory=game, server_host='127.0.0.1', server_port=port,
                          display_name=f'Human Client {index+1}', room='community')
            parent, child = socket.socketpair(socket.AF_INET)
            sockets.extend((parent, child))
            parent.setblocking(False)
            reader, writer = await asyncio.open_connection(sock=parent)
            async def resolve(index=index):
                attempts[index] += 1
                return bridge.Remote('127.0.0.1', port, context, *identities[index])
            record = dict(name=config['display_name'], writer=writer, log='',
                          task=asyncio.create_task(bridge.Bridge(reader, writer, resolve, version=2).run()))
            clients.append(record)
            command = launcher.game_arguments(config, None, child.fileno(),
                argparse.Namespace(run_name=f'public-clients-{index}', unified_experimental=True))
            command[command.index('-logFile')+1] = str(output/f'game-{index}.log')
            command += ['-public-queue-experimental', '-public-queue-smoke', f'-public-queue-smoke-mode={args.mode}',
                        '-public-queue-smoke-gate='+gate_key, '-lan-smoke', '-lan-audit', '-dedicated-rematch-smoke',
                        '-dedicated-surrender-smoke', '-dedicated-surrender-frame=1200', '-public-team-surrender-smoke',
                        '-match-search-smoke']
            if index == 1:
                command.append('-public-queue-smoke-edit-deck')
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 1 if args.visible else 0
            startup.lpAttributeList = {'handle_list': [child.fileno()]}
            record['tick'] = clock()
            child.set_inheritable(True)
            try:
                record['process'] = subprocess.Popen(command, cwd=game, startupinfo=startup, close_fds=True,
                    creationflags=0 if args.visible else subprocess.CREATE_NO_WINDOW)
            finally:
                child.set_inheritable(False)
                child.close()
            record['job'] = _WindowsJob(record['process'].pid)
            report['game_pids'].append(record['process'].pid)
            report['client_arguments'].append(command)
            report['launch_ticks'].append(record['tick'])
            (output/'processes.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        while True:
            for record in clients:
                require(record['process'].poll() is None, 'owned game exited before native return')
                require(not record['task'].done(), 'private bridge exited before native completion')
                record['log'] = read_native_log(game, record['process'].pid, since_tick=record['tick'])
                for failure in ('Public client failure:', 'Client lifecycle invariant failed:', 'Practice stopped in ',
                                'Offline loop stopped in ', 'LAN normal-build smoke disabled', 'LAN normal-build smoke stopped',
                                'Public result Continue routing failed:'):
                    require(failure not in record['log'], 'native failure: '+failure)
                require('inner=ProvingGroundsState' not in record['log'], 'public result entered retired progression reward flow')
            if not gate_created and all('PUBLIC QUEUE SMOKE waiting for shared gate: key='+gate_key in row['log'] for row in clients):
                require(not any('Public search intent:' in row['log'] for row in clients), 'Play started before every menu was ready')
                with gate_path.open('xb'):
                    pass
                gate_created = True
                observe('probe_shared_gate_released', clients=len(clients))
            if all('PUBLIC QUEUE completed return:' in row['log'] for row in clients):
                break
            require(time.monotonic()-started < args.timeout, 'multi-client public match timed out')
            await asyncio.sleep(.2)
        require(gate_created, 'shared start gate was bypassed')
        completed = [row for row in events if row['event'] == 'match_completed']
        offered = [row for row in events if row['event'] == 'public_match_offered']
        entered = [row for row in events if row['event'] == 'public_queue_entered']
        require(len(completed) == len(offered) == len(workers) == 1 and len(entered) == args.humans,
                'humans did not complete exactly one shared match/offer/worker')
        require(not any(row['event'] == 'match_aborted' for row in events), 'shared match aborted')
        require(sorted(authenticated) == sorted(player for player, token in identities) and attempts == [1]*args.humans,
                'authentication/connection ownership differs')
        match, offer = completed[0]['match'], offered[0]
        require(match == offer['match'] and set(offer['humans']) == set(authenticated), 'human group split across matches')
        total, available_seats = q.MODES[args.mode]
        expected_seats = set(available_seats[:args.humans])
        full = args.humans == len(available_seats)
        waits = [offer['observed_at']-row['observed_at'] for row in entered]
        require(offer['fallback'] == (not full), 'full/partial human offer policy differs')
        if full:
            require(0 <= max(waits) < 5, 'full human group waited for AI fallback deadline')
        else:
            require(29 <= max(waits) <= 33, 'partial human group skipped the real30-second wait')
        manifest = json.loads((output/'matches'/match/'match.json').read_text(encoding='utf-8'))
        require(set(map(int, manifest['profiles'])) == expected_seats and
                set(map(int, manifest['bots'])) == set(range(total))-expected_seats, 'authoritative human/bot seats differ')
        require(len({tuple(manifest['decks'][str(seat)]) for seat in expected_seats}) >= 2,
                'independent native human decks were not preserved')
        authoritative = {row['frame']: row['frame_payload_sha256'] for row in events
                         if row['event'] == 'frame_queued' and row['match'] == match}
        evidence = []
        for index, record in enumerate(clients):
            log, pid = record['log'], record['process'].pid
            assigned = re.findall(r'Public match assignment: ticket=1 match=([0-9a-f]{32}) mode=(\d+) count=(\d+) seat=(\d+) humans=(\d+) ', log)
            require(len(assigned) == 1, 'client assignment duplicated/missing')
            key, mode, count, seat, mask = assigned[0]
            seat = int(seat)
            require(key == match and int(mode) == args.mode and int(count) == total and seat in expected_seats and
                    int(mask) == sum(1 << value for value in expected_seats), 'native assigned topology differs')
            require(manifest['profiles'][str(seat)] == identities[index][0], 'human seat/profile binding differs')
            require(log.count('Public native match joined:') == log.count('PUBLIC QUEUE completed return:') == 1 and
                    log.count('Client world acquired:') == log.count('owner=remote nativeIdle=1') == 1 and
                    'Public fallback accepted:' not in log and 'owner=local-practice' not in log,
                    'native match/world/return ownership differs')
            require('PUBLIC QUEUE SMOKE original OnMapSelected:' in log and 'Native search joining signal:' in log and
                    'Native search released:' in log, 'original search/loading lifecycle missing')
            require(log.count(f'Public result Continue routed: mode={args.mode} source=remote next=End') == 1,
                    'native public Continue did not finish its reward-free result flow')
            require(index != 1 or 'DEDICATED REMATCH SMOKE automated native deck edit:' in log, 'second native deck edit missing')
            frame = 300+100*seat
            build = re.search(rf'LAN NORMAL BUILD smoke frame{frame} slot{seat} army{seat} [^\r\n]+', log)
            require(build is not None and 'queued=1 commandQueueDelta=1' in build[0], 'human normal build was not queued')
            receipts = runtime/f'dedicated-receipts-{pid}-{match}.tsv'
            rows = list(csv.DictReader(receipts.read_text(encoding='utf-8').splitlines(), delimiter='\t'))
            require(len(rows) == len(authoritative) >= 600 and [int(row['frame']) for row in rows] == list(range(len(rows))),
                    'native receipt sequence/count differs from authoritative frames')
            require(all(row['sha256'] == authoritative[int(row['frame'])] for row in rows), 'native frame differs from authoritative journal')
            shutil.copyfile(receipts, output/receipts.name)
            seconds = [int(value) for ticket, value in re.findall(r'Native search timer: ticket=(\d+) seconds=(\d+)', log) if ticket == '1']
            require(seconds and seconds[0] == 0 and seconds == sorted(seconds), 'native search clock missing/nonmonotonic')
            if not full:
                require(max(seconds) >= 25, 'partial group search timer did not advance through queue wait')
            evidence.append(dict(pid=pid, seat=seat, name=record['name'], build_frame=frame, native_build=build[0],
                                 received_frames=len(rows), native_elapsed_seconds=seconds, deck=manifest['decks'][str(seat)]))
        require({row['seat'] for row in evidence} == expected_seats, 'duplicate/missing native human seat')
        require(not server.community.public.entries and not server.community.public.offers and not server.rooms and
                not server.community.lobbies, 'completed public match retained queue/room/lobby capacity')
        report.update(passed=True, match=match, received_frames=len(authoritative), clients=evidence,
            full_human_group=full, real_queue_seconds=waits, result=completed[0]['result'],
            journal_human_builds=journal_builds(output/'matches'/match/'frames.bin', evidence, len(authoritative)),
            bots=manifest['bots'], remote_attempts=attempts, authentications=len(authenticated))
    except BaseException as error:
        report.update(passed=False, error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        for record in clients:
            process = record.get('process')
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                await asyncio.to_thread(process.wait, timeout=15)
                try:
                    log = read_native_log(game, process.pid, since_tick=record['tick'])
                    (output/f'native-{process.pid}.log').write_text(log, encoding='utf-8')
                    for name in re.findall(r'file=(match-search-\d+-\d+-\d+-\w+\.png)', log):
                        source = runtime/name
                        if source.is_file():
                            shutil.copyfile(source, output/name)
                except Exception as error:
                    report.update(passed=False, evidence_error=f'{type(error).__name__}: {error}')
            if record.get('job') is not None:
                record['job'].close()
            record['task'].cancel()
        await asyncio.gather(*(record['task'] for record in clients), return_exceptions=True)
        for record in clients:
            writer = record['writer']
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 2)
            except (OSError, TimeoutError):
                writer.transport.abort()
        for sock in sockets:
            sock.close()
        await server.close()
        await asyncio.gather(*(worker.close() for worker in workers))
        remove_test_pki(pki_folder)
        if gate_created:
            require(gate_path.resolve().parent == runtime.resolve() and gate_path.is_file() and not gate_path.is_symlink(),
                    'owned diagnostic gate path changed')
            gate_path.unlink()
        audit.close()
        cleanup = [dict(pid=worker.pid, exit_code=worker.process.poll(), failure=worker.failure,
            stderr_tail=worker.stderr_tail[-4096:], owned_resources_reaped=worker.process.poll() is not None and
            worker._cleanup_task is not None and worker._cleanup_task.done() and not worker._stderr_thread.is_alive()) for worker in workers]
        report.update(elapsed_seconds=time.monotonic()-started, worker_cleanup=cleanup,
            owned_processes_reaped=all(record.get('process') is None or record['process'].poll() is not None for record in clients),
            cleanup='forced owned termination, not native Quit', gate_removed=not gate_path.exists(), source_sha256_at_finish=source_hashes())
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        clean = all(row['owned_resources_reaped'] and row['exit_code'] == 0 and not row['failure'] for row in cleanup)
        if not clean:
            report.setdefault('error', 'worker cleanup failed; see worker_cleanup')
        report['passed'] &= clean and report['owned_processes_reaped'] and report['gate_removed'] and report['source_files_unchanged']
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('passed', 'error', 'elapsed_seconds', 'received_frames', 'full_human_group') if key in report}))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'assets', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--mode', type=int, choices=(1, 2, 5), default=5)
    parser.add_argument('--humans', type=int, choices=(2, 3, 4), default=2)
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--visible', action='store_true')
    args = parser.parse_args()
    require(os.name == 'nt' and args.output.resolve().is_relative_to(ROOT/'local') and 120 <= args.timeout <= 900,
            'bounded Windows/ignored probe required')
    require(args.humans <= len(q.MODES[args.mode][1]), 'too many humans for public mode')
    return asyncio.run(run(args))


if __name__ == '__main__':
    raise SystemExit(main())
