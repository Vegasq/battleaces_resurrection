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
from tools.verify_worker_rooms import ScriptedPeer
from tools.run_secure_match import read_native_log

ROOT = Path(__file__).resolve().parents[1]
PASSED = 'COMMUNITY SMOKE Create/Leave passed: two normal rounds and pending-ACK Leave/re-enter; party=0 pending=0 seat=-1 connection retained'
ROSTER_PASSED = 'COMMUNITY ROSTER SMOKE passed: three pooled open/close cycles; rows=0 childBindings=0 presence retained'


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
    events, processes, scripted = [], [], []
    profiles = ['custom_' + uuid.uuid4().hex for _ in range(2)]
    report = dict(passed=False, utc=datetime.now(timezone.utc).isoformat(), source_sha256_at_start=source_hashes(),
        scope=('Native Create/Leave and pooled roster binding/lifecycle' if args.roster else 'Native manager Create/Leave callbacks') +
              '; no manual visual, invitation, AI or gameplay qualification',
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
                '-dedicated-community', '-community-roster-smoke' if args.roster else '-community-create-smoke', '-player-id=' + profile,
                '-player-name=' + (('<b>Roster one</b>', 'Roster \u2605 two')[index] if args.roster else 'Custom probe ' + str(index + 1)), '-screen-fullscreen', '0',
                '-screen-width', '960', '-screen-height', '540', '-logFile', str(output / f'game-{index}.log')]
            startup = subprocess.STARTUPINFO();startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow = 0
            processes.append(subprocess.Popen(command, cwd=game, startupinfo=startup,
                creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True))
            report['game_pids'].append(processes[-1].pid);report['client_arguments'].append(command)
        (output / 'processes.json').write_text(json.dumps(report, indent=2))
        deadline = time.monotonic() + args.startup_timeout
        churn_stage = 0
        while True:
            require(all(p.poll() is None for p in processes), 'native client exited before callback verification')
            logs = [read_native_log(game, p.pid) for p in processes]
            require(all('Offline loop stopped in ' not in log for log in logs), 'native community adapter failed; inspect retained logs')
            if args.roster and churn_stage == 0 and all('Community roster populated:' in log for log in logs):
                reader, writer = await asyncio.open_connection(*address[:2])
                peer = ScriptedPeer(reader, writer);scripted.append(peer)
                await peer.send(community_wire.HELLO, community_wire.hello('roster_' + uuid.uuid4().hex, '<color=red>Peer</color>'))
                await peer.receive(community_wire.WELCOME)
                churn_stage = 1
            elif args.roster and churn_stage == 1 and all('COMMUNITY ROSTER SMOKE live join: count=3 TMP checked' in log for log in logs):
                await scripted[0].close();churn_stage = 2
            if all((ROSTER_PASSED if args.roster else PASSED) in log for log in logs):
                break
            require(time.monotonic() < deadline, 'native community Create/Leave timed out')
            await asyncio.sleep(.2)
        await asyncio.sleep(1)
        require(len(server.community.sessions) == 2 and not server.community.lobbies,
                'presence did not survive both lobby departures')
        require(not server.rooms and not any(e['event'] == 'worker_started' for e in events), 'unexpected match/worker')
        require(sum(e['event'] == 'custom_lobby_created' for e in events) == (2 if args.roster else 8), 'unexpected native lobby creations')
        for log in logs:
            require('Community native create response: success=1 pending=0' in log and
                    'Community native lobby closure delivered; reason=1 party=0000000000000000' in log,
                    'native deferred create/closure evidence missing')
            if args.roster:
                require(churn_stage == 2 and 'COMMUNITY ROSTER SMOKE live departure: count=2 TMP checked' in log,
                        'native directory join/departure not qualified')
                require(log.count('COMMUNITY ROSTER SMOKE rows verified round=') == 3 and
                        log.count('Community roster released: rows=0 childBindings=0') == 3,
                        'native picker did not complete three pooled cycles')
            else:
                require('create returned with native pending request; no early response' in log and
                    log.count('Community native create response: success=1 pending=0') == 3 and
                    log.count('Community cancelled create acknowledged without stale native callback') == 1 and
                    'COMMUNITY SMOKE early Leave/re-enter queued behind original Create' in log,
                    'pending-ACK cancellation/re-enter was not qualified')
            require('assignedSeat=-1' in log and 'Dedicated lobby welcome slot' not in log,
                    'community presence unexpectedly acquired a simulation seat')
        report.update(passed=True, native_creates=2 if args.roster else 8, native_leaves=2 if args.roster else 8, presence_connections_retained=2,
            simulation_workers=0, callbacks_deferred=True, create_ack_delay_seconds=.35,
            cancelled_creates_without_stale_native_callback=0 if args.roster else 2, rapid_reenters=0 if args.roster else 2,
            roster_open_close_cycles_per_client=3 if args.roster else 0, roster_churn_verified=bool(args.roster))
        print('Native custom ' + ('roster lifecycle and live directory' if args.roster else 'Create/Leave cancellation') + ' passed; presence retained.', flush=True)
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
        await asyncio.gather(*(peer.close() for peer in scripted), return_exceptions=True)
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
    parser.add_argument('--roster', action='store_true', help='qualify pooled directory renderer; invitation actions remain disabled')
    args = parser.parse_args()
    require(30 <= args.startup_timeout <= 300, 'startup timeout must be30..300 seconds')
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
