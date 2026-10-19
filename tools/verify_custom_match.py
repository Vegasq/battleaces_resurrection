"""Two native UI clients: invite, Start, real simulation, results, same-lobby rematch.

Explicit automation flags concede at a bounded frame and invoke native Continue.
This does not establish manual visual acceptance or native Quit behavior.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time
import traceback
import uuid

from client_patch.transport.launcher import verify_game
from client_patch.transport import bridge, client, launcher
from server.admission import AdmissionController
from server.credentials import AuthenticationError
from server import tls_transport as tls
from server.assets import verify_assets
from server.cosmetics import CosmeticCatalog
from server import loadout_protocol
from server.dedicated_server import Audit, DedicatedServer
from server.game_data import GameTemplate
from server.profiles import ProfileStore
from server.worker_client import SimulationWorker, _WindowsJob
from server import community_protocol as wire
from server.community import Rejected
from tools.run_secure_match import read_native_log
from tools.verify_custom_lobby import require, source_hashes as core_hashes
from tools import match_loading_evidence
from tests.test_tls_transport import generate_test_pki, remove_test_pki

ROOT = Path(__file__).resolve().parents[1]
PASSED = 'COMMUNITY MATCH SMOKE passed: two native Start/result/Continue cycles; same lobby, presence retained, seat=-1'


def source_hashes():
    result = core_hashes()
    result['tools/verify_custom_match.py'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result['tools/run_secure_match.py'] = hashlib.sha256((ROOT / 'tools/run_secure_match.py').read_bytes()).hexdigest()
    result['tools/match_loading_evidence.py'] = hashlib.sha256(Path(match_loading_evidence.__file__).read_bytes()).hexdigest()
    for path in (ROOT / 'client_patch/transport').glob('*.py'):
        result[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


async def run(args):
    require(os.name == 'nt', 'Windows game runtime required')
    game, assets, output = args.game.resolve(), args.assets.resolve(), args.output.resolve()
    require(output.is_relative_to(ROOT / 'local'), 'evidence must be under ignored local/')
    verify_game(game, community=True, bridge_version=2 if args.unified else 1, unified=args.unified); verify_assets(assets)
    manifest = json.loads((game / '.battleaces-resurrection/patch-manifest.json').read_text())
    require(manifest.get('community', {}).get('native_scope') == 'custom-match-prototype',
            'install current experimental match patch into an isolated copy')
    if args.loading_ui: require(manifest.get('ui', {}).get('match_loading'), 'loading UI helper required')
    output.mkdir(parents=True, exist_ok=False)
    (game / 'investigation/runtime').mkdir(parents=True, exist_ok=True)
    template = GameTemplate.load(assets / 'map-1v1.pb.gz', catalog_path=assets / 'unit-catalog.json',
                                 descriptors_path=assets / 'descriptors')
    cosmetic_book = CosmeticCatalog(assets) if args.cosmetics_selection else None
    cosmetic_seeds, cosmetic_profiles, frozen_matches = [], [], []
    if cosmetic_book:
        require(args.unified and game.is_relative_to(ROOT/'local'), 'full cosmetic proof requires a disposable unified client')
        seed=json.loads(args.cosmetics_selection.read_bytes())
        seed=seed.get('state', seed)
        require(seed['catalog_sha256']==cosmetic_book.sha256, 'native seed/catalog mismatch')
        cosmetic_seeds=[cosmetic_book.validate_selection(seed['slots']), cosmetic_book.normalize_local()]
        folder=game/'.battleaces-resurrection/profiles';folder.mkdir(parents=True,exist_ok=True)
        prefix='cosmeticstest_'+secrets.token_hex(6)
        for index, selected in enumerate(cosmetic_seeds):
            key=prefix+'_'+str(index);cosmetic_profiles.append(key)
            value=dict(schema=1,build=37822,profile=key,catalog_sha256=selected.catalog_sha256,slots=selected.slots)
            with (folder/(key+'.cosmetics.json')).open('xb') as stream:
                stream.write((json.dumps(value,separators=(',',':'))+'\n').encode('ascii'))
    audit, events, processes, timers, workers, commands = Audit(output), [], [], [], [], []
    bridges, writers, jobs, authenticated = [], [], [], []
    test_players = [('p_' + secrets.token_hex(16), 'ba1_' + secrets.token_urlsafe(32)) for _ in range(2)]
    class Store:
        def authenticate(self, token):
            for player, expected in test_players:
                if secrets.compare_digest(token, expected):
                    authenticated.append(player)
                    return player
            raise AuthenticationError()
    pki_folder = output / 'ephemeral-pki'
    pki = generate_test_pki(pki_folder) if args.unified else None
    secure = dict(tls_context=tls.load_server_context(pki['cert'], pki['key']),
                  admission=AdmissionController(Store())) if pki else {}
    process_ticks = {}
    clock = ctypes.WinDLL('kernel32').GetTickCount64
    clock.restype = ctypes.c_ulonglong
    report = dict(passed=False, utc=datetime.now(timezone.utc).isoformat(),
        scope='Automated original native UI actions; real simulation; two same-lobby matches; no manual visual/native Quit qualification',
        source_sha256_at_start=source_hashes(), game_pids=[], client_arguments=[], client_start_ticks=[])
    started = time.monotonic()
    aborted_scenario = args.scenario in ('setup-abort', 'running-abort', 'loading-abort')
    injected = False
    stale_match, old_abort_sent, return_abort_sent = None, False, False

    def observe(event, **fields):
        events.append(dict(event=event, **fields)); audit(event, **fields)
        if event=='match_created' and cosmetic_book:
            match=server.rooms[fields['room']].match
            frozen_matches.append(dict(match=fields['match'],cosmetics={slot:dict(catalog_sha256=value.catalog_sha256,slots=value.slots)
                                   for slot,value in match.cosmetics_by_slot.items()}))

    async def factory(data):
        nonlocal injected
        if args.scenario == 'setup-abort' and not injected:
            injected = True
            raise RuntimeError('qualification: worker setup failure before bootstrap')
        worker = await SimulationWorker.create(data, assets / 'Simulation.dll')
        workers.append(worker)
        return worker

    server = DedicatedServer(template, ProfileStore(output / 'profiles', template, catalog=cosmetic_book), audit=observe,
        sim_factory=factory, data_dir=output, lobby_timeout=300, **secure)
    original_send = server.community.send
    held = {}

    def release_abort_tail(peer):
        for kind, payload in held.pop(peer.connection, []):
            original_send(peer, kind, payload)

    def send(peer, kind, payload):
        if peer.connection in held:
            held[peer.connection].append((kind, payload))
            return
        if aborted_scenario and kind == wire.ABORTED:
            # Duplicate decision, then a distinct read containing ordered Results.
            original_send(peer, kind, payload)
            original_send(peer, kind, payload)
            held[peer.connection] = []
            timers.append(asyncio.get_running_loop().call_later(.6, release_abort_tail, peer))
            return
        if kind == wire.ACK and len(payload) >= 5 and payload[4] in (wire.START, wire.READY):
            timers.append(asyncio.get_running_loop().call_later(.35, original_send, peer, kind, payload))
        else:
            original_send(peer, kind, payload)

    server.community.send = send
    original_apply = server.community.apply

    async def apply(session, kind, command, now):
        nonlocal injected, return_abort_sent
        record=dict(command)
        if 'cosmetics' in record:
            value=record['cosmetics'];record['cosmetics']=dict(catalog_sha256=value.catalog_sha256,slots=value.slots)
        commands.append(dict(profile=session.peer.profile_id, kind=kind, **record))
        if not injected and ((args.scenario == 'reject' and kind == wire.START) or
                             (args.scenario == 'timeout' and kind == wire.READY)):
            injected = True
            if args.scenario == 'reject':
                raise Rejected('qualification: host start rejected')
            await asyncio.sleep(server.community.start_timeout + .5)
            now = time.monotonic()
        result = await original_apply(session, kind, command, now)
        if args.scenario == 'stale-abort' and injected and kind == wire.RETURN and not return_abort_sent:
            return_abort_sent = True
            # The first client has reset local match state and sent RETURN, but
            # the other player has not yet returned. Keep its valid result safe.
            for current in server.community.sessions.values():
                original_send(current.peer, wire.ABORTED, wire.aborted(stale_match, 'qualification: stale while returning'))
        return result

    server.community.apply = apply
    try:
        address = await server.start('127.0.0.1', 0)
        (output / 'patch-manifest.json').write_text(json.dumps(manifest, indent=2))
        for index, role in enumerate(('host', 'guest')):
            native_profile = 'nativeprobe_'+uuid.uuid4().hex[:16]
            command = [str(game / 'Battle Aces.exe'), '-offline-lan',
                '-local-profile='+native_profile,
                f'-dedicated-server=127.0.0.1:{address[1]}', '-dedicated-community',
                f'-community-match-{role}-smoke', '-player-id=custom_' + uuid.uuid4().hex,
                '-player-name=' + ('Custom Host', 'Custom Guest')[index],
                '-lan-smoke', '-dedicated-surrender-smoke', '-dedicated-surrender-frame=160',
                '-screen-fullscreen', '0', '-screen-width', '960', '-screen-height', '540',
                '-logFile', str(output / f'game-{index}.log')]
            child = None
            if args.unified:
                settings = output / f'client-{index}.json'
                local = client.defaults(game)
                local['local_profile'] = native_profile
                local['display_name'] = ('Custom Host', 'Custom Guest')[index]
                if cosmetic_book: local['local_profile']=cosmetic_profiles[index]
                settings.write_text(json.dumps(local), encoding='utf-8')
                config = client.prepare_settings(settings)
                parent, child = socket.socketpair(socket.AF_INET)
                parent.setblocking(False)
                reader, writer = await asyncio.open_connection(sock=parent)
                writers.append(writer)
                remote = bridge.Remote('127.0.0.1', address[1], tls.load_client_context(pki['ca'], 'localhost'),
                                       *test_players[index])
                bridges.append(asyncio.create_task(bridge.Bridge(reader, writer, remote, version=2).run()))
                command = launcher.game_arguments(config, None, child.fileno(),
                    argparse.Namespace(run_name=f'unified-custom-{index}', unified_experimental=True))
                command[command.index('-logFile')+1] = str(output / f'game-{index}.log')
                command += [f'-community-match-{role}-smoke', '-lan-smoke',
                            '-dedicated-surrender-smoke', '-dedicated-surrender-frame=160']
            if args.scenario == 'duplicates-deck':
                command.extend(['-community-match-duplicate-smoke', '-community-match-deck-smoke'])
            if args.loading_ui: command.append('-match-loading-smoke')
            if cosmetic_book: command.extend(['-local-cosmetics-experimental','-community-cosmetics-smoke','-human-cosmetics-smoke'])
            startup = subprocess.STARTUPINFO(); startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow = 4 if args.visible else 0
            if child is not None:
                startup.lpAttributeList = {'handle_list': [child.fileno()]}
                child.set_inheritable(True)
            launch_tick = clock()
            try:
                processes.append(subprocess.Popen(command, cwd=game, startupinfo=startup,
                    creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True))
            finally:
                if child is not None: child.set_inheritable(False);child.close()
            jobs.append(_WindowsJob(processes[-1].pid))
            process_ticks[processes[-1].pid] = launch_tick
            report['client_start_ticks'].append(launch_tick)
            report['game_pids'].append(processes[-1].pid); report['client_arguments'].append(command)
        (output / 'processes.json').write_text(json.dumps(report, indent=2))
        deadline = time.monotonic() + args.timeout
        while True:
            require(all(p.poll() is None for p in processes), 'native client exited before custom match verification')
            require(not any(task.done() for task in bridges), 'private bridge exited before native completion')
            logs = [read_native_log(game, p.pid, since_tick=process_ticks[p.pid]) for p in processes]
            require(not any('Offline loop stopped in ' in log for log in logs), 'native custom match adapter failed; inspect retained logs')
            require(not any(marker in log for log in logs for marker in
                ('Client lifecycle invariant failed:', 'Local menu initialization failed:')),
                'unified lifecycle failed; inspect retained logs')
            if args.scenario == 'stale-abort':
                if not injected and all('COMMUNITY MATCH SMOKE native result ready;' in log for log in logs):
                    injected = True
                    lobby = next(iter(server.community.lobbies.values()))
                    stale_match = lobby.match_id
                    for session in server.community.sessions.values():
                        original_send(session.peer, wire.ABORTED, wire.aborted(stale_match, 'qualification: stale after valid result'))
                elif injected and not old_abort_sent:
                    lobby = next(iter(server.community.lobbies.values()))
                    if lobby.epoch == 2 and lobby.phase == wire.RUNNING and lobby.room.frame >= 40:
                        old_abort_sent = True
                        for session in server.community.sessions.values():
                            original_send(session.peer, wire.ABORTED, wire.aborted(stale_match, 'qualification: stale during next match'))
            if not injected and args.scenario in ('running-abort', 'loading-abort'):
                for room in list(server.rooms.values()):
                    # This case qualifies a graceful server-declared abort.
                    # Cancellation inside a worker RPC deliberately terminates
                    # that worker; do not confuse it with an idle CLOSE/exit0.
                    eligible = (room.state == 'running' and room.frame >= 40 and room.sim is not None and
                                not room.sim._lock.locked()) if args.scenario == 'running-abort' else (
                        room.state == 'loading' and all('Community native custom match joined:' in log for log in logs))
                    if eligible:
                        injected = True
                        report['fault'] = dict(match=room.match_id, state=room.state, frame=room.frame,
                                              worker_rpc_inflight=room.sim._lock.locked())
                        await room.finish('qualification: ' + args.scenario, aborted=True)
                        break
            if all(PASSED in log for log in logs):
                break
            require(time.monotonic() < deadline, 'native custom match flow timed out')
            await asyncio.sleep(.05 if args.scenario == 'loading-abort' else .2)
        require(len(server.community.sessions) == 2 and len(server.community.lobbies) == 1,
                'same community sessions/lobby not preserved')
        lobby = next(iter(server.community.lobbies.values()))
        expected_epochs = 4 if args.scenario == 'timeout' else 3 if aborted_scenario else 2
        require(lobby.phase == wire.OPEN and lobby.epoch == expected_epochs and len(lobby.members) == 2 and not lobby.room,
                'custom lobby did not reopen after two epochs')
        completed = [e for e in events if e['event'] == 'match_completed']
        expected_workers = 3 if args.scenario in ('running-abort', 'loading-abort') else 2
        require(len(completed) == 2 and len(workers) == expected_workers and all(w.closed and w.process.poll() == 0 for w in workers),
                'two authoritative matches/workers did not complete cleanly')
        require(sum(e['event'] == 'community_joined' for e in events) == 2 and
                sum(e['event'] == 'custom_lobby_created' for e in events) == 1,
                'native rematch reconnected or created a different lobby')
        require(sum(e['event'] == 'match_aborted' for e in events) == (1 if aborted_scenario else 0),
                'unexpected custom match abort count')
        require(sum(e['event'] == 'custom_match_setup_error' for e in events) == (1 if args.scenario == 'setup-abort' else 0),
                'unexpected custom setup error count')
        for log in logs:
            if args.unified:
                acquired = sum('Client world acquired:' in line and 'owner=remote' in line for line in log.splitlines())
                released = sum('Client world released:' in line and 'owner=remote' in line for line in log.splitlines())
                require(acquired == expected_workers and released == expected_workers,
                        'unified remote world leases did not complete')
            require(log.count('Community native custom match joined:') == expected_workers and
                    log.count('Community native lobby restored:') == (3 if aborted_scenario else 2) and log.count('Community native match return:') == 2,
                    'native start/return lifecycle count mismatch')
            if aborted_scenario:
                require(injected and log.count('Community aborted match recovered:') == 1 and
                        log.count('Community aborted match return:') == 1, 'abort did not retain native lobby/presence')
                require(log.count('Community setup failure delivered to native Predict:') == (1 if args.scenario == 'setup-abort' else 0),
                        'native setup failure signal count mismatch')
                require(log.count('Community abort native CleanupGameState:') == (0 if args.scenario == 'setup-abort' else 1),
                        'native abort cleanup count mismatch')
                if args.scenario == 'loading-abort':
                    require(any('Community abort pending Results:' in line and 'mapLoading=1' in line for line in log.splitlines()),
                            'abort did not reach this client while its native map was loading')
            if args.scenario == 'stale-abort':
                require(injected and old_abort_sent and return_abort_sent and log.count('Community stale abort ignored:') == 3 and
                        'Community abort native CleanupGameState:' not in log and log.count('COMMUNITY MATCH SMOKE native Continue') == 2,
                        'stale abort disrupted native result/next-match flow')
        expected_starts = 3 if args.scenario in ('reject', 'timeout') or aborted_scenario else 2
        expected_readies = 3 if args.scenario == 'timeout' or aborted_scenario else 2
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
        if args.loading_ui:
            report['loading_ui'] = [match_loading_evidence.check(log, game, output, process.pid,
                source='custom', ready=2 + int(args.scenario == 'running-abort'),
                minimum_errors=int(args.scenario in ('timeout', 'setup-abort', 'loading-abort') or
                                   (args.scenario == 'reject' and index == 0)))
                for index, (log, process) in enumerate(zip(logs, processes))]
        if args.unified: require(sorted(authenticated) == sorted(player for player, _ in test_players), 'expected two authenticated sessions')
        if cosmetic_book:
            require(len(frozen_matches)==2 and all(session.full_loadout for session in server.community.sessions.values()),
                    'two full-loadout server snapshots/capabilities missing')
            selected={}
            for index,log in enumerate(logs):
                snapshots=[json.loads(line.split('REMOTE COSMETICS frozen snapshot: ',1)[1]) for line in log.splitlines()
                           if 'REMOTE COSMETICS frozen snapshot: ' in line]
                require(len(snapshots)==2 and log.count('REMOTE COSMETICS SimPlayer passed:')==2,
                        'native full-map readback missing for both matches')
                parsed=[cosmetic_book.validate_selection(value['slots']) for value in snapshots]
                require(parsed[0]==cosmetic_seeds[index], 'first native match differs from seeded complete profile')
                require((parsed[1]!=parsed[0]) if index==0 else (parsed[1]==parsed[0]), 'rematch changed/stable profile isolation failed')
                selected[index]=parsed
                for ordinal,appearance in enumerate(parsed):
                    require(frozen_matches[ordinal]['cosmetics'][index]['slots']==appearance.slots,
                            'native decoded map differs from authoritative server frozen map')
                stored=server.profiles.load_state(test_players[index][0], [])
                require(stored.cosmetics==parsed[-1], 'server stored profile differs from final native match selection')
            require(sum(command['kind']==loadout_protocol.SET_LOADOUT for command in commands)>=3,
                    'complete initial publication/rematch publication missing')
            report['full_loadouts']=dict(catalog=cosmetic_book.sha256,local_profiles=cosmetic_profiles,server_matches=frozen_matches,
                native_selections={index:[dict(slots=value.slots,catalog_sha256=value.catalog_sha256) for value in values]
                                   for index,values in selected.items()},native_full_map_each_match=True)
        report.update(passed=True, lobby=lobby.id, epochs=expected_epochs, completed_matches=completed, commands=commands,
            unified=args.unified, tls_authentications=len(authenticated),
            scenario=args.scenario,
            abort_results_delay_seconds=.6 if aborted_scenario else 0,
            duplicate_abort=aborted_scenario, stale_result_and_next_match_abort=old_abort_sent,
            stale_abort_while_returning=return_abort_sent,
            presence_connections_retained=2, start_ready_ack_delay_seconds=.35)
        print('Native custom matches passed: two Start/result/Continue cycles on the same connections and lobby.', flush=True)
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
        raise
    finally:
        for process in processes:
            (output / f'native-{process.pid}.log').write_text(
                read_native_log(game, process.pid, since_tick=process_ticks[process.pid]), encoding='utf-8')
            if process.poll() is None:
                process.terminate()
        for process in processes:
            process.wait(timeout=15)
        for job in jobs: job.close()
        for task in bridges: task.cancel()
        await asyncio.gather(*bridges, return_exceptions=True)
        for writer in writers:
            writer.close()
            try: await asyncio.wait_for(writer.wait_closed(), 2)
            except (OSError, TimeoutError): writer.transport.abort()
        for timer in timers:
            timer.cancel()
        await server.close()
        await asyncio.gather(*(w.close() for w in workers), return_exceptions=True)
        if pki is not None: remove_test_pki(pki_folder)
        report.update(elapsed_seconds=time.monotonic()-started, owned_processes_reaped=all(p.poll() is not None for p in processes),
            scenario=args.scenario, commands=commands,
            workers=[dict(pid=w.pid, exit_code=w.process.poll(), closed=w.closed,
                          failure=w.failure, stderr_tail=w.stderr_tail) for w in workers],
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
    parser.add_argument('--unified', action='store_true', help='qualify unified native ownership over real TLS with in-memory test invites')
    parser.add_argument('--loading-ui', action='store_true', help='verify native loading status and retain Unity screenshots')
    parser.add_argument('--cosmetics-selection',type=Path,help='accepted native full-map proof; enable full protocol and a fresh cosmetic rematch edit')
    parser.add_argument('--visible',action='store_true',help='show both diagnostic windows without taking focus')
    parser.add_argument('--scenario', choices=('normal', 'duplicates-deck', 'reject', 'timeout',
                                              'setup-abort', 'running-abort', 'loading-abort', 'stale-abort'), default='normal')
    args = parser.parse_args()
    require(60 <= args.timeout <= 300, 'timeout must be60..300 seconds')
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
