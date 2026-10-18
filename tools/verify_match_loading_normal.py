"""Opt-in native normal Play/Cancel/retry/loading qualification on loopback.

Uses two owned hidden clients and original patched Front callbacks, not physical
mouse input. The explicit replay is a stale S35 duplicate, not network shaping.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import json
import os
from pathlib import Path
import struct
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
from server import protocol as p
from tools.run_secure_match import read_native_log
from tools.verify_custom_lobby import require, source_hashes as core_hashes
from tools import match_loading_evidence

ROOT = Path(__file__).resolve().parents[1]
RETRY = 'MATCH LOADING NORMAL SMOKE retry submitted; stale readiness did not reopen status'


def source_hashes():
    result = core_hashes()
    for path in (Path(__file__), Path(match_loading_evidence.__file__), ROOT / 'tools/run_secure_match.py'):
        result[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


async def run(args):
    require(os.name == 'nt', 'Windows runtime required')
    game, assets, output = args.game.resolve(), args.assets.resolve(), args.output.resolve()
    require(output.is_relative_to(ROOT / 'local'), 'evidence must be under ignored local/')
    verify_game(game); verify_assets(assets)
    manifest = json.loads((game / '.battleaces-resurrection/patch-manifest.json').read_text())
    require(manifest.get('ui', {}).get('match_loading'), 'install a loading UI helper')
    output.mkdir(parents=True, exist_ok=False)
    (game / 'investigation/runtime').mkdir(parents=True, exist_ok=True)
    (output / 'patch-manifest.json').write_text(json.dumps(manifest, indent=2))
    events, processes, workers, timers, ticks = [], [], [], [], {}
    audit = Audit(output)
    clock = ctypes.WinDLL('kernel32').GetTickCount64; clock.restype = ctypes.c_ulonglong
    report = dict(passed=False, scope=__doc__, source_sha256_at_start=source_hashes(), client_arguments=[])
    started, replayed = time.monotonic(), False

    async def factory(data):
        worker = await SimulationWorker.create(data, assets / 'Simulation.dll')
        workers.append(worker)
        return worker

    def observe(event, **fields):
        nonlocal replayed
        events.append(dict(event=event, **fields)); audit(event, **fields)
        if event == 'lobby_ready' and not fields['ready'] and not replayed:
            replayed = True
            room = server.rooms[fields['room']]
            peer = room.peers[fields['slot']]
            payload = struct.pack('<BBI', sum(1 << slot for slot in room.peers), 1 << peer.slot, room.revision)
            payload += p.deck_bytes(room.decks.get(0, server.template.default_decks[0]))
            payload += p.deck_bytes(room.decks.get(1, server.template.default_decks[1]))
            timers.append(asyncio.get_running_loop().call_later(.2, peer.send, p.LOBBY, payload))
            timers.append(asyncio.get_running_loop().call_later(.7, room.lobby_state))

    template = GameTemplate.load(assets / 'map-1v1.pb.gz', catalog_path=assets / 'unit-catalog.json',
                                 descriptors_path=assets / 'descriptors')
    server = DedicatedServer(template, ProfileStore(output / 'profiles', template), audit=observe,
                             sim_factory=factory, data_dir=output, lobby_timeout=300)

    def launch(role, address):
        command = [str(game / 'Battle Aces.exe'), '-offline-lan', f'-dedicated-server=127.0.0.1:{address[1]}',
            '-player-id=loading_' + uuid.uuid4().hex, '-player-name=Loading ' + role, '-room=loading-test',
            '-match-loading-smoke', '-match-loading-normal-smoke', '-match-loading-role=' + role,
            '-lan-smoke', '-dedicated-surrender-smoke', '-dedicated-surrender-frame=160',
            '-screen-fullscreen', '0', '-screen-width', '960', '-screen-height', '540',
            '-logFile', str(output / ('game-' + role + '.log'))]
        startup = subprocess.STARTUPINFO(); startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow = 0
        tick = clock()
        process = subprocess.Popen(command, cwd=game, startupinfo=startup,
                                   creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
        processes.append(process); ticks[process.pid] = tick
        report['client_arguments'].append(command)
        (output / 'processes.json').write_text(json.dumps(dict(pids=[p.pid for p in processes], ticks=ticks), indent=2))

    try:
        address = await server.start('127.0.0.1', 0)
        launch('host', address)
        deadline = started + args.timeout
        while True:
            require(all(p.poll() is None for p in processes), 'native client exited early')
            logs = [read_native_log(game, process.pid, since_tick=ticks[process.pid]) for process in processes]
            require(not any(marker in log for log in logs for marker in
                    ('MATCH LOADING NORMAL SMOKE failed:', 'Match loading UI failed', 'Offline loop stopped in ')),
                    'native loading qualification failed')
            if len(processes) == 1 and RETRY in logs[0]: launch('guest', address)
            if len(logs) == 2 and all('gate=continue-handler-ready' in log for log in logs): break
            require(time.monotonic() < deadline, 'native normal loading deadline')
            await asyncio.sleep(.2)
        require(replayed, 'no stale readiness duplicate was injected')
        cancelled = logs[0].index('MATCH LOADING NORMAL SMOKE native Cancel;')
        retried = logs[0].index(RETRY)
        require('ready_mask=1' in logs[0][cancelled:retried], 'late readiness was not consumed between Cancel and retry')
        readies = [row for row in events if row['event'] == 'lobby_ready']
        require([row['ready'] for row in readies] == [True, False, True, True], 'duplicate Play reached wire or retry was lost')
        report['loading_ui'] = [match_loading_evidence.check(log, game, output, process.pid, source='dedicated', ready=1)
                                for log, process in zip(logs, processes)]
        require(sum(row['event'] == 'cancel' for row in report['loading_ui'][0]['events']) == 1,
                'native Cancel was not represented exactly once')
        require(sum(row['event'] == 'match_completed' for row in events) == 1, 'native match did not complete')
        report.update(passed=True, stale_readiness_replayed=True, readiness_commands=readies)
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
        raise
    finally:
        for process in processes:
            (output / f'native-{process.pid}.log').write_text(read_native_log(game, process.pid, since_tick=ticks[process.pid]), encoding='utf-8')
            if process.poll() is None: process.terminate()
            process.wait(timeout=15)
        for timer in timers: timer.cancel()
        await server.close()
        await asyncio.gather(*(worker.close() for worker in workers), return_exceptions=True)
        report.update(elapsed_seconds=time.monotonic()-started, source_sha256_at_finish=source_hashes(),
                      owned_processes_reaped=all(p.poll() is not None for p in processes),
                      workers=[dict(pid=w.pid, exit_code=w.process.poll(), closed=w.closed) for w in workers])
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= report['source_files_unchanged'] and report['owned_processes_reaped'] and all(w.process.poll() == 0 for w in workers)
        (output / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        audit.close()
        print('Evidence: ' + str(output / 'verification.json'), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'assets', 'output'): parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=360)
    args = parser.parse_args(); require(60 <= args.timeout <= 600, 'timeout must be60..600 seconds')
    asyncio.run(run(args))


if __name__ == '__main__': main()
