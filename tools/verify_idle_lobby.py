"""Opt-in native idle-menu and real connection-error regression on Windows.

Starts two owned graphical game processes with no auto-ready/gameplay/audit flags.
Reads native ownership/navigation evidence; this is not a manual visual UI check.
All local game inputs, logs and reports remain outside the Git source set.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import traceback
import uuid

from client_patch.transport.launcher import verify_game
from server.assets import verify_assets
from server.dedicated_server import Audit, DedicatedServer
from server.game_data import GameTemplate
from server.profiles import ProfileStore
from tools.run_secure_match import read_native_log

ROOT = Path(__file__).resolve().parents[1]
RELEASE = 'Dedicated healthy lobby legacy disconnect released: '
STABLE = re.compile(r'Dedicated idle lobby observation: sample=(\d+) '
    r'activeShow=0+ modal=0+ navigation=0 welcome=1 stopped=0 worldIdle=1')


def require(condition, reason):
    if not condition:
        raise AssertionError(reason)


def source_hashes():
    names = ('client_patch/src/dedicated_adapter.cpp', 'client_patch/src/lan_transport.cpp',
             'tools/verify_idle_lobby.py', 'server/dedicated_server.py', 'server/community.py')
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}


async def run(args):
    if os.name != 'nt':
        raise ValueError('Windows game runtime required')
    game, assets, output = args.game.resolve(), args.assets.resolve(), args.output.resolve()
    require(output.is_relative_to(ROOT / 'local'), 'evidence must be under ignored local/')
    verify_game(game)
    verify_assets(assets)
    output.mkdir(parents=True, exist_ok=False)
    template = GameTemplate.load(assets / 'map-1v1.pb.gz', catalog_path=assets / 'unit-catalog.json',
                                 descriptors_path=assets / 'descriptors')
    audit = Audit(output)
    events, processes, players = [], [], ['idle_' + uuid.uuid4().hex for _ in range(2)]
    report = dict(passed=False, utc=datetime.now(timezone.utc).isoformat(),
        scope='Native idle-menu ownership and genuine lobby failure; no manual visual observation',
        source_sha256_at_start=source_hashes(), client_arguments=[], game_pids=[],
        automatic_ready=False, gameplay_smoke=False, state_audits=False)
    started = time.monotonic()
    def observe(event, **fields):
        events.append(dict(event=event, **fields))
        audit(event, **fields)
    async def unexpected_match(_):
        raise AssertionError('idle lobby test must not create a simulation worker')
    server = DedicatedServer(template, ProfileStore(output / 'profiles', template),
        audit=observe, sim_factory=unexpected_match, data_dir=output, lobby_timeout=300)
    try:
        address = await server.start('127.0.0.1', 0)
        (output / 'patch-manifest.json').write_bytes((game / '.battleaces-resurrection/patch-manifest.json').read_bytes())
        for index, player in enumerate(players):
            arguments = [str(game / 'Battle Aces.exe'), '-offline-lan',
                f'-dedicated-server=127.0.0.1:{address[1]}', '-player-id=' + player,
                '-player-name=Idle probe ' + str(index + 1), '-room=idle-probe',
                '-screen-fullscreen', '0', '-screen-width', '960', '-screen-height', '540',
                '-logFile', str(output / f'game-{index}.log')]
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            processes.append(subprocess.Popen(arguments, cwd=game, startupinfo=startup,
                creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True))
            report['client_arguments'].append(arguments)
            report['game_pids'].append(processes[-1].pid)
        (output / 'processes.json').write_text(json.dumps(report, indent=2))
        deadline = time.monotonic() + args.startup_timeout
        while True:
            require(all(p.poll() is None for p in processes), 'client exited before idle verification')
            logs = [read_native_log(game, p.pid) for p in processes]
            if all(RELEASE in log and len(STABLE.findall(log)) == 6 for log in logs):
                break
            require(time.monotonic() < deadline, 'healthy idle lobby observations timed out')
            await asyncio.sleep(.2)
        room = server.rooms.get('idle-probe')
        require(room and room.state == 'lobby' and len(room.peers) == 2 and not room.ready,
                'idle clients did not remain in a two-player unready lobby')
        require(not room.match_id and room.sim is None, 'unexpected match during idle test')
        for log in logs:
            require(log.count(RELEASE) == 1 and 'navigationBefore=1' in log,
                    'native modal was not released exactly once')
            require(re.search(RELEASE + r'activeShowAfter=0+ modalAfter=0+ navigationAfter=0', log),
                    'native release did not remove its navigation entry')
            require('Offline loop stopped in ' not in log and 'Dedicated failure dialog ready:' not in log,
                    'healthy lobby reported a failure')
        report['healthy_lobby'] = dict(clients=2, releases_per_client=1,
            idle_samples_per_client=6, navigation=0, no_match_started=True, both_unready=True)
        print('Both native menus stayed unblocked for six idle observations; neither client readied.', flush=True)

        victim = next(peer for peer in room.peers.values() if peer.profile_id == players[0])
        positions = [len(log) for log in logs]
        victim.close('idle qualification: replacement server connection lost')
        deadline = time.monotonic() + 15
        while True:
            later = [read_native_log(game, p.pid)[pos:] for p,pos in zip(processes,positions)]
            if 'Dedicated failure dialog ready:' in later[0]:
                break
            require(time.monotonic() < deadline, 'real replacement-server failure was not presented')
            await asyncio.sleep(.2)
        await asyncio.sleep(3)
        later = [read_native_log(game, p.pid)[pos:] for p,pos in zip(processes,positions)]
        require(RELEASE not in later[0], 'healthy cleanup dismissed the real failure')
        require('Dedicated failure dialog ready:' not in later[1], 'unaffected peer reported a failure')
        require(len(room.peers) == 1 and room.state == 'lobby' and not room.ready,
                'unaffected peer lost its idle lobby')
        report['real_failure'] = dict(victim_pid=processes[0].pid, native_dialog_presented=True,
            healthy_cleanup_did_not_repeat=True, other_peer_remained_connected=True)
        print('Injected real lobby failure displayed the native dialog; the other client stayed connected.', flush=True)
        report['passed'] = True
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
        raise
    finally:
        for process in processes:
            (output / f'native-{process.pid}.log').write_text(read_native_log(game, process.pid), encoding='utf-8')
            if process.poll() is None:
                process.terminate()  # Owned test teardown; not a native Quit qualification.
        for process in processes:
            process.wait(timeout=15)
        await server.close()
        audit.close()
        report.update(elapsed_seconds=time.monotonic()-started,
            owned_processes_reaped=all(p.poll() is not None for p in processes),
            teardown='test-owned process termination, not a native Quit result',
            source_sha256_at_finish=source_hashes())
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= report['source_files_unchanged'] and report['owned_processes_reaped']
        (output / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print('Evidence: ' + str(output / 'verification.json'), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', required=True, type=Path)
    parser.add_argument('--assets', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--startup-timeout', type=int, default=150)
    args = parser.parse_args()
    if not 45 <= args.startup_timeout <= 300:
        parser.error('startup timeout must be45..300 seconds')
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
