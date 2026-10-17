"""Opt-in original native Custom Game Create/Leave probe on an isolated Windows copy.

Exercises native manager prediction/pending callbacks against the real community
coordinator. No invitation, match, AI or manual visual UI success is implied.
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
from server import community_protocol as community_wire
from tools.run_secure_match import read_native_log

ROOT = Path(__file__).resolve().parents[1]
PASSED = 'COMMUNITY SMOKE Create/Leave passed: two normal rounds and pending-ACK Leave/re-enter; party=0 pending=0 seat=-1 connection retained'


def require(condition, reason):
    if not condition:
        raise AssertionError(reason)


def source_hashes():
    paths = [ROOT / 'tools/verify_custom_lobby.py']
    for folder in ('client_patch/src', 'client_patch/patcher', 'server'):
        paths.extend(p for p in (ROOT / folder).rglob('*') if p.suffix in ('.cpp', '.hpp', '.h', '.py'))
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


async def run(args):
    require(os.name == 'nt', 'Windows game runtime required')
    game, assets, output = args.game.resolve(), args.assets.resolve(), args.output.resolve()
    require(output.is_relative_to(ROOT / 'local'), 'evidence must be under ignored local/')
    verify_game(game)
    manifest = json.loads((game / '.battleaces-resurrection/patch-manifest.json').read_text())
    require(manifest.get('community', {}).get('experimental'), 'install the experimental community patch into an isolated copy')
    verify_assets(assets)
    output.mkdir(parents=True, exist_ok=False)
    (game / 'investigation/runtime').mkdir(parents=True, exist_ok=True)
    template = GameTemplate.load(assets / 'map-1v1.pb.gz', catalog_path=assets / 'unit-catalog.json', descriptors_path=assets / 'descriptors')
    audit = Audit(output)
    events, processes = [], []
    profiles = ['custom_' + uuid.uuid4().hex for _ in range(2)]
    report = dict(passed=False, utc=datetime.now(timezone.utc).isoformat(), source_sha256_at_start=source_hashes(),
        scope='Native manager Create/Leave callbacks; no manual visual, invitation, AI or gameplay qualification',
        game_pids=[], client_arguments=[])
    started = time.monotonic()

    def observe(event, **fields):
        events.append(dict(event=event, **fields));audit(event, **fields)

    async def unexpected_match(_):
        raise AssertionError('Create/Leave test must not create a simulation worker')

    server = DedicatedServer(template, ProfileStore(output / 'profiles', template), audit=observe,
        sim_factory=unexpected_match, data_dir=output, lobby_timeout=300)
    # Delay only the native CREATE acknowledgment, keeping the earlier lobby
    # snapshot immediate. This forces Leave/re-enter while the original native
    # request is retained and prevents a loopback-fast ACK from hiding the race.
    original_send = server.community.send
    delayed = []
    def send(peer, kind, payload):
        if kind == community_wire.ACK and len(payload) >= 5 and payload[4] == community_wire.CREATE:
            delayed.append(asyncio.get_running_loop().call_later(.35, original_send, peer, kind, payload))
        else:
            original_send(peer, kind, payload)
    server.community.send = send
    try:
        address = await server.start('127.0.0.1', 0)
        (output / 'patch-manifest.json').write_text(json.dumps(manifest, indent=2))
        for index, profile in enumerate(profiles):
            command = [str(game / 'Battle Aces.exe'), '-offline-lan', f'-dedicated-server=127.0.0.1:{address[1]}',
                '-dedicated-community', '-community-create-smoke', '-player-id=' + profile,
                '-player-name=Custom probe ' + str(index + 1), '-screen-fullscreen', '0',
                '-screen-width', '960', '-screen-height', '540', '-logFile', str(output / f'game-{index}.log')]
            startup = subprocess.STARTUPINFO();startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow = 0
            processes.append(subprocess.Popen(command, cwd=game, startupinfo=startup,
                creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True))
            report['game_pids'].append(processes[-1].pid);report['client_arguments'].append(command)
        (output / 'processes.json').write_text(json.dumps(report, indent=2))
        deadline = time.monotonic() + args.startup_timeout
        while True:
            require(all(p.poll() is None for p in processes), 'native client exited before callback verification')
            logs = [read_native_log(game, p.pid) for p in processes]
            require(all('Offline loop stopped in ' not in log for log in logs), 'native community adapter failed; inspect retained logs')
            if all(PASSED in log for log in logs):
                break
            require(time.monotonic() < deadline, 'native community Create/Leave timed out')
            await asyncio.sleep(.2)
        await asyncio.sleep(1)
        require(len(server.community.sessions) == 2 and not server.community.lobbies,
                'presence did not survive both lobby departures')
        require(not server.rooms and not any(e['event'] == 'worker_started' for e in events), 'unexpected match/worker')
        require(sum(e['event'] == 'custom_lobby_created' for e in events) == 8, 'expected four lobby creations per client')
        for log in logs:
            require('create returned with native pending request; no early response' in log and
                    'Community native create response: success=1 pending=0' in log and
                    'Community native lobby closure delivered; party=0000000000000000' in log,
                    'native deferred create/closure evidence missing')
            require(log.count('Community native create response: success=1 pending=0') == 3 and
                    log.count('Community cancelled create acknowledged without stale native callback') == 1 and
                    'COMMUNITY SMOKE early Leave/re-enter queued behind original Create' in log,
                    'pending-ACK cancellation/re-enter was not qualified')
            require('assignedSeat=-1' in log and 'Dedicated lobby welcome slot' not in log,
                    'community presence unexpectedly acquired a simulation seat')
        report.update(passed=True, native_creates=8, native_leaves=8, presence_connections_retained=2,
            simulation_workers=0, callbacks_deferred=True, create_ack_delay_seconds=.35,
            cancelled_creates_without_stale_native_callback=2, rapid_reenters=2)
        print('Two native Create/Leave rounds plus pending-ACK Leave/re-enter passed per client; presence retained.', flush=True)
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
        for timer in delayed:
            timer.cancel()
        await server.close();audit.close()
        report.update(elapsed_seconds=time.monotonic()-started, owned_processes_reaped=all(p.poll() is not None for p in processes),
            teardown='owned test termination; not native Quit validation', source_sha256_at_finish=source_hashes())
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= report['source_files_unchanged'] and report['owned_processes_reaped']
        (output / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print('Evidence: ' + str(output / 'verification.json'), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'assets', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--startup-timeout', type=int, default=150)
    args = parser.parse_args()
    require(30 <= args.startup_timeout <= 300, 'startup timeout must be30..300 seconds')
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
