"""Two real native clients: picker Invite, popup Decline/Accept, cancel and expiry.

Automated native actions, not manual mouse/keyboard or match-start acceptance.
Uses the isolated experimental installation and leaves normal play untouched.
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
from server import community_protocol as wire
from tools.run_secure_match import read_native_log
from tools.verify_custom_lobby import require, source_hashes as core_hashes

ROOT = Path(__file__).resolve().parents[1]
PASSED = ('COMMUNITY INVITE SMOKE host passed:', 'COMMUNITY INVITE SMOKE guest passed:')


def source_hashes():
    result = core_hashes()
    result['tools/verify_custom_invites.py'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return result


async def run(args):
    require(os.name == 'nt', 'Windows game runtime required')
    game, assets, output = args.game.resolve(), args.assets.resolve(), args.output.resolve()
    require(output.is_relative_to(ROOT / 'local'), 'evidence must be under ignored local/')
    verify_game(game); verify_assets(assets)
    manifest = json.loads((game / '.battleaces-resurrection/patch-manifest.json').read_text())
    require(manifest.get('community', {}).get('native_scope') == 'custom-invitation-prototype',
            'install the current experimental invitation patch into an isolated copy')
    output.mkdir(parents=True, exist_ok=False)
    (game / 'investigation/runtime').mkdir(parents=True, exist_ok=True)
    template = GameTemplate.load(assets / 'map-1v1.pb.gz', catalog_path=assets / 'unit-catalog.json',
                                 descriptors_path=assets / 'descriptors')
    audit, events, processes, timers = Audit(output), [], [], []
    report = dict(passed=False, utc=datetime.now(timezone.utc).isoformat(),
        scope='Native invitation UI lifecycle; no manual visual, match-start or gameplay qualification',
        source_sha256_at_start=source_hashes(), game_pids=[], client_arguments=[])
    started = time.monotonic()

    def observe(event, **fields):
        events.append(dict(event=event, **fields)); audit(event, **fields)

    async def unexpected_match(_):
        raise AssertionError('Invitation test must not create a simulation worker')

    server = DedicatedServer(template, ProfileStore(output / 'profiles', template), audit=observe,
        sim_factory=unexpected_match, data_dir=output, lobby_timeout=300)
    original_send = server.community.send

    def send(peer, kind, payload):
        # Real state notifications remain immediate. Delayed ACKs qualify the
        # native deferred counters and retained incoming invitation identity.
        if (kind == wire.ACK and len(payload) >= 5 and payload[4] in (wire.INVITE, wire.REPLY, wire.CANCEL)
                and not (args.leave_on_accept and payload[4] == wire.REPLY)):
            timers.append(asyncio.get_running_loop().call_later(.35, original_send, peer, kind, payload))
        else:
            original_send(peer, kind, payload)

    server.community.send = send
    try:
        address = await server.start('127.0.0.1', 0)
        (output / 'patch-manifest.json').write_text(json.dumps(manifest, indent=2))
        for index, role in enumerate(('host', 'guest')):
            command = [str(game / 'Battle Aces.exe'), '-offline-lan',
                f'-dedicated-server=127.0.0.1:{address[1]}', '-dedicated-community',
                f'-community-invite-{role}-smoke', '-player-id=invite_' + uuid.uuid4().hex,
                '-player-name=' + ('<b>Host</b>', 'Guest \u2605')[index],
                '-screen-fullscreen', '0', '-screen-width', '960', '-screen-height', '540',
                '-logFile', str(output / f'game-{index}.log')]
            if args.completion_failure:
                command.append('-community-invite-recovery-smoke')
                if role == 'guest':
                    command.extend(['-dedicated-recovery-smoke', '-community-completion-failure-' + args.completion_failure])
            if args.leave_on_accept:
                command.append('-community-leave-accepted-smoke')
            startup = subprocess.STARTUPINFO(); startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow = 0
            processes.append(subprocess.Popen(command, cwd=game, startupinfo=startup,
                creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True))
            report['game_pids'].append(processes[-1].pid); report['client_arguments'].append(command)
        (output / 'processes.json').write_text(json.dumps(report, indent=2))
        deadline = time.monotonic() + args.startup_timeout
        while True:
            require(all(p.poll() is None for p in processes), 'native client exited before invitation verification')
            logs = [read_native_log(game, p.pid) for p in processes]
            failures = [line for log in logs for line in log.splitlines() if 'Offline loop stopped in ' in line]
            expected_failure = 'injected community completion failure ' + str(args.completion_failure) + ' native reply'
            require(not failures or (args.completion_failure and len(failures) == 1 and expected_failure in failures[0]),
                    'native invitation adapter failed; inspect retained logs')
            markers = (PASSED[0], 'COMMUNITY INVITE RECOVERY guest passed:') if args.completion_failure else PASSED
            if all(marker in log for marker, log in zip(markers, logs)):
                break
            require(time.monotonic() < deadline, 'native invitation flow timed out')
            await asyncio.sleep(.2)
        await asyncio.sleep(1)
        require(len(server.community.sessions) == 2 and not server.community.lobbies and not server.community.invites,
                'presence/lobby/invitation cleanup mismatch')
        require(not server.rooms and not any(e['event'] == 'worker_started' for e in events), 'unexpected match/worker')
        created = [e for e in events if e['event'] == 'custom_invite_created']
        resolved = [e for e in events if e['event'] == 'custom_invite_resolved']
        require(len(created) == 4 and [e['status'] for e in resolved] == [wire.DECLINED, wire.CANCELLED, wire.EXPIRED, wire.ACCEPTED],
                'server did not resolve exactly the four expected invitations')
        require(logs[1].count('COMMUNITY INVITE SMOKE guest popup round=') == 4 and
                logs[1].count('Community popup released: ownedModels=0') == 4 and
                logs[1].count('counter=0 popupReleased=1') == (3 if args.completion_failure else 4),
                'four native popup lifecycles not qualified')
        if args.completion_failure:
            require(expected_failure in logs[1] and 'Community native reset: party=0 prediction=0 pendingCreate=0 replyCounter=0' in logs[1] and
                    'RECOVERY SMOKE original OnConfirm returned; modalStillOwned=1 queued=1' in logs[1] and
                    sum(e['event'] == 'community_joined' for e in events) == 3, 'explicit native reconnect was not qualified')
            if args.completion_failure == 'after':
                require('interrupted native reply already settled: no duplicate counter decrement' in logs[1],
                        'already-settled callback credit was not preserved')
        if args.leave_on_accept:
            require('late acceptance after native Leave: released prediction retained, departing Party unchanged' in logs[0] and
                    'Community accepted invitation ignored after native Leave:' in logs[0] and
                    'Community host accepted invitation:' not in logs[0], 'departing host received a stale accepted callback')
        require('guest native Decline returned with one pending reply' in logs[1] and
                'guest native Accept returned with one pending reply' in logs[1] and
                'duplicate native Accept retained two replies' in logs[1], 'native reply deferral/duplicate not qualified')
        for log in logs:
            require('assignedSeat=-1' in log and 'Dedicated lobby welcome slot' not in log,
                    'community presence unexpectedly acquired a simulation seat')
        report.update(passed=True, invitations_created=4, resolved_statuses=[e['status'] for e in resolved],
            native_popup_cycles=4, invite_cancel_ack_delay_seconds=.35, reply_ack_delay_seconds=0 if args.leave_on_accept else .35,
            native_reply_counter_final=0, presence_connections_retained=2, simulation_workers=0,
            completion_failure_stage=args.completion_failure, leave_on_accept=args.leave_on_accept)
        print(('Native invitation recovery passed: interrupted reply credits settled and fresh presence restored.'
               if args.completion_failure else 'Native late-acceptance departure passed; no host lobby revival.' if args.leave_on_accept else
               'Native invitations passed: decline, cancel, expiry, accept and both lobby departures.'), flush=True)
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
        await server.close(); audit.close()
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
    parser.add_argument('--startup-timeout', type=int, default=180)
    parser.add_argument('--completion-failure', choices=('before', 'after'),
                        help='inject one reply-completion exception and qualify explicit native Reconnect cleanup')
    parser.add_argument('--leave-on-accept', action='store_true', help='release host manager just before applying an accepted notification')
    args = parser.parse_args()
    require(60 <= args.startup_timeout <= 300, 'startup timeout must be60..300 seconds')
    require(not (args.completion_failure and args.leave_on_accept), 'choose one fault scenario per run')
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
