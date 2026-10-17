"""Two native UI clients: invite, Start, real simulation, results, same-lobby rematch.

Explicit automation flags concede at a bounded frame and invoke native Continue.
This does not establish manual visual acceptance or native Quit behavior.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import traceback
import uuid

from client_patch.transport.launcher import verify_game
from server.assets import verify_assets
from server.dedicated_server import Audit, DedicatedServer
from server.game_data import GameTemplate
from server.profiles import ProfileStore
from server.worker_client import SimulationWorker
from server import community_protocol as wire
from server.community import Rejected
from tools.run_secure_match import read_native_log
from tools.verify_custom_lobby import require, source_hashes as core_hashes

ROOT = Path(__file__).resolve().parents[1]
PASSED = 'COMMUNITY MATCH SMOKE passed: two native Start/result/Continue cycles; same lobby, presence retained, seat=-1'


def source_hashes():
    result = core_hashes()
    result['tools/verify_custom_match.py'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return result


async def run(args):
    require(os.name == 'nt', 'Windows game runtime required')
    game, assets, output = args.game.resolve(), args.assets.resolve(), args.output.resolve()
    require(output.is_relative_to(ROOT / 'local'), 'evidence must be under ignored local/')
    verify_game(game); verify_assets(assets)
    manifest = json.loads((game / '.battleaces-resurrection/patch-manifest.json').read_text())
    require(manifest.get('community', {}).get('native_scope') == 'custom-match-prototype',
            'install current experimental match patch into an isolated copy')
    output.mkdir(parents=True, exist_ok=False)
    (game / 'investigation/runtime').mkdir(parents=True, exist_ok=True)
    template = GameTemplate.load(assets / 'map-1v1.pb.gz', catalog_path=assets / 'unit-catalog.json',
                                 descriptors_path=assets / 'descriptors')
    audit, events, processes, timers, workers, commands = Audit(output), [], [], [], [], []
    report = dict(passed=False, utc=datetime.now(timezone.utc).isoformat(),
        scope='Automated original native UI actions; real simulation; two same-lobby matches; no manual visual/native Quit qualification',
        source_sha256_at_start=source_hashes(), game_pids=[], client_arguments=[])
    started = time.monotonic()

    def observe(event, **fields):
        events.append(dict(event=event, **fields)); audit(event, **fields)

    async def factory(data):
        worker = await SimulationWorker.create(data, assets / 'Simulation.dll')
        workers.append(worker)
        return worker

    server = DedicatedServer(template, ProfileStore(output / 'profiles', template), audit=observe,
        sim_factory=factory, data_dir=output, lobby_timeout=300)
    original_send = server.community.send

    def send(peer, kind, payload):
        if kind == wire.ACK and len(payload) >= 5 and payload[4] in (wire.START, wire.READY):
            timers.append(asyncio.get_running_loop().call_later(.35, original_send, peer, kind, payload))
        else:
            original_send(peer, kind, payload)

    server.community.send = send
    original_apply = server.community.apply
    injected = False

    async def apply(session, kind, command, now):
        nonlocal injected
        commands.append(dict(profile=session.peer.profile_id, kind=kind, **command))
        if not injected and ((args.scenario == 'reject' and kind == wire.START) or
                             (args.scenario == 'timeout' and kind == wire.READY)):
            injected = True
            if args.scenario == 'reject':
                raise Rejected('qualification: host start rejected')
            await asyncio.sleep(server.community.start_timeout + .5)
            now = time.monotonic()
        return await original_apply(session, kind, command, now)

    server.community.apply = apply
    try:
        address = await server.start('127.0.0.1', 0)
        (output / 'patch-manifest.json').write_text(json.dumps(manifest, indent=2))
        for index, role in enumerate(('host', 'guest')):
            command = [str(game / 'Battle Aces.exe'), '-offline-lan',
                f'-dedicated-server=127.0.0.1:{address[1]}', '-dedicated-community',
                f'-community-match-{role}-smoke', '-player-id=custom_' + uuid.uuid4().hex,
                '-player-name=' + ('Custom Host', 'Custom Guest')[index],
                '-lan-smoke', '-dedicated-surrender-smoke', '-dedicated-surrender-frame=160',
                '-screen-fullscreen', '0', '-screen-width', '960', '-screen-height', '540',
                '-logFile', str(output / f'game-{index}.log')]
            if args.scenario == 'duplicates-deck':
                command.extend(['-community-match-duplicate-smoke', '-community-match-deck-smoke'])
            startup = subprocess.STARTUPINFO(); startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow = 0
            processes.append(subprocess.Popen(command, cwd=game, startupinfo=startup,
                creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True))
            report['game_pids'].append(processes[-1].pid); report['client_arguments'].append(command)
        (output / 'processes.json').write_text(json.dumps(report, indent=2))
        deadline = time.monotonic() + args.timeout
        while True:
            require(all(p.poll() is None for p in processes), 'native client exited before custom match verification')
            logs = [read_native_log(game, p.pid) for p in processes]
            require(not any('Offline loop stopped in ' in log for log in logs), 'native custom match adapter failed; inspect retained logs')
            if all(PASSED in log for log in logs):
                break
            require(time.monotonic() < deadline, 'native custom match flow timed out')
            await asyncio.sleep(.2)
        require(len(server.community.sessions) == 2 and len(server.community.lobbies) == 1,
                'same community sessions/lobby not preserved')
        lobby = next(iter(server.community.lobbies.values()))
        expected_epochs = 4 if args.scenario == 'timeout' else 2
        require(lobby.phase == wire.OPEN and lobby.epoch == expected_epochs and len(lobby.members) == 2 and not lobby.room,
                'custom lobby did not reopen after two epochs')
        completed = [e for e in events if e['event'] == 'match_completed']
        require(len(completed) == 2 and len(workers) == 2 and all(w.closed and w.process.poll() == 0 for w in workers),
                'two authoritative matches/workers did not complete cleanly')
        require(sum(e['event'] == 'community_joined' for e in events) == 2 and
                sum(e['event'] == 'custom_lobby_created' for e in events) == 1,
                'native rematch reconnected or created a different lobby')
        require(not any(e['event'] in ('match_aborted', 'custom_match_setup_error') for e in events),
                'custom match aborted/setup failed')
        for log in logs:
            require(log.count('Community native custom match joined:') == 2 and
                    log.count('Community native lobby restored:') == 2 and log.count('Community native match return:') == 2,
                    'native start/return lifecycle count mismatch')
        expected_starts = 3 if args.scenario in ('reject', 'timeout') else 2
        expected_readies = 3 if args.scenario == 'timeout' else 2
        require(sum(c['kind'] == wire.START for c in commands) == expected_starts and
                sum(c['kind'] == wire.READY for c in commands) == expected_readies, 'wire Start/Ready count mismatch')
        if args.scenario in ('reject', 'timeout'):
            require(injected and 'Start rolled back to full native lobby' in logs[0], 'start failure rollback not qualified')
        if args.scenario == 'duplicates-deck':
            require(all(log.count('Community duplicate native start settled without wire replay:') == 2 for log in logs),
                    'duplicate native Start/Ready callbacks not qualified')
            created = [e for e in events if e['event'] == 'match_created']
            require(len(created) == 2 and created[0]['decks'][0] != created[1]['decks'][0] and
                    'automated native deck edit:' in logs[0], 'changed native deck did not reach rematch bootstrap')
        report.update(passed=True, lobby=lobby.id, epochs=expected_epochs, completed_matches=completed, commands=commands,
            scenario=args.scenario,
            presence_connections_retained=2, start_ready_ack_delay_seconds=.35)
        print('Native custom matches passed: two Start/result/Continue cycles on the same connections and lobby.', flush=True)
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
        raise
    finally:
        for process in processes:
            (output / f'native-{process.pid}.log').write_text(read_native_log(game, process.pid), encoding='utf-8')
            if process.poll() is None:
                process.terminate()
        for process in processes:
            process.wait(timeout=15)
        for timer in timers:
            timer.cancel()
        await server.close()
        await asyncio.gather(*(w.close() for w in workers), return_exceptions=True)
        report.update(elapsed_seconds=time.monotonic()-started, owned_processes_reaped=all(p.poll() is not None for p in processes),
            scenario=args.scenario, commands=commands,
            workers=[dict(pid=w.pid, exit_code=w.process.poll(), closed=w.closed) for w in workers],
            teardown='owned test termination; not native Quit validation', source_sha256_at_finish=source_hashes())
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= report['source_files_unchanged'] and report['owned_processes_reaped'] and all(w.process.poll() == 0 for w in workers)
        (output / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        audit.close()
        print('Evidence: ' + str(output / 'verification.json'), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'assets', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--scenario', choices=('normal', 'duplicates-deck', 'reject', 'timeout'), default='normal')
    args = parser.parse_args()
    require(60 <= args.timeout <= 300, 'timeout must be60..300 seconds')
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
