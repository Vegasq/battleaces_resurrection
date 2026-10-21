"""D2 T05: two owned native clients retain humans through remote1/2/5/1.

Original Play/build/Concede/Continue callbacks are automated. Fixture TLS and
forced final cleanup do not qualify protected enrollment, physical UI or Quit.
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
import subprocess
import time
import traceback
from types import SimpleNamespace

from client_patch.transport import bridge, client, launcher
from server import admission, loadout_protocol, public_protocol as q, tls_transport as tls
from server.ai_rules import RuleBook
from server.assets import verify_assets
from server.bot_catalog import BotCatalog
from server.cosmetics import CosmeticCatalog
from server.credentials import AuthenticationError
from server.dedicated_server import Audit, DedicatedServer
from server.game_data import GameTemplate
from server.profiles import ProfileStore
from server.worker_ai import AISetup
from server.worker_client import SimulationWorker, _WindowsJob
from tests.test_tls_transport import generate_test_pki, remove_test_pki
from tools import public_sequence_evidence as evidence
from tools import custom_transition_probe
from tools.public_profile_evidence import expected_players
from tools.run_secure_match import read_native_log
from tools.verify_native_quit import verify_build_receipt
from tools.verify_public_clients import journal_builds, source_hashes as team_sources
from tools import verify_unified_startup as startup

ROOT = Path(__file__).resolve().parents[1]
require = evidence.require


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes():
    paths = [Path(__file__), Path(evidence.__file__), ROOT/'tools/public_profile_evidence.py',
             ROOT/'tools/verify_native_quit.py', ROOT/'tests/test_tls_transport.py', Path(custom_transition_probe.__file__),
             ROOT/'tools/custom_transition_evidence.py', ROOT/'tools/verify_practice_ai.py']
    return team_sources() | {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}


def seals(preparation):
    for name, digest in preparation['installed'].items():
        require(sha(Path(preparation['game'])/name) == digest, 'installed program seal changed: '+name)
    for folder, files in preparation['untouched'].items():
        for name, digest in files.items():
            require(sha(Path(folder)/name) == digest, 'manual candidate seal changed: '+name)


async def run(args):
    game, assets, output = args.game.resolve(), args.assets.resolve(), args.output.resolve()
    custom = args.custom_transitions
    require(game.is_relative_to(ROOT/'local') and output.is_relative_to(ROOT/'local'), 'owned ignored paths required')
    launcher.verify_game(game, community=True, bridge_version=2, unified=True, player_features=True)
    helper = verify_build_receipt(game, args.helper_build.resolve())
    marker = b'BA_RESURRECTION_CUSTOM_TRANSITION_V1' if custom else b'BA_RESURRECTION_PUBLIC_SEQUENCE_V1'
    require(marker in (game/'BattleAcesOffline.dll').read_bytes(), 'sequence helper required')
    preparation = json.loads(args.preparation.read_bytes())
    require(Path(preparation['game']).resolve() == game, 'preparation selects another game')
    require(preparation['source_sha256'] == source_hashes(), 'preparation does not bind current sequence sources')
    seals(preparation)
    verify_assets(assets)
    output.mkdir(parents=True, exist_ok=False)
    runtime = game/'investigation/runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    gate_key = secrets.token_hex(16)
    gates = [runtime/f'public-queue-{gate_key}-sequence-{stage}.ready' for stage in range(1, 5)]
    if custom:
        gates = [runtime/f'custom-transition-{gate_key}-stage-{stage}.ready' for stage in range(1, 6)] + [
            runtime/f'custom-transition-{gate_key}-leave-{stage}-{role}.ready' for stage in (1, 3, 5) for role in ('guest', 'host')] + [
            runtime/f'custom-transition-{gate_key}-custom-start-{stage}.ready' for stage in (1, 3, 5)]
    require(not any(path.exists() for path in gates), 'sequence gate already exists')
    book = CosmeticCatalog(assets)
    seed = json.loads(args.cosmetics_selection.read_bytes())
    seed = seed.get('state', seed)
    require(seed['catalog_sha256'] == book.sha256, 'seed catalog differs')
    selected = [book.validate_selection(seed['slots']), book.normalize_local()]
    portrait_slot = book.roles['portrait']
    if selected[0].portrait == selected[1].portrait:
        pairs = dict(selected[1].slots)
        pairs[portrait_slot] = next(value for value in sorted(book.slots[portrait_slot].compatible_items)
                                    if value != selected[0].portrait)
        selected[1] = book.validate_selection(pairs)
    keys = ['cosmeticstest_sequence_'+secrets.token_hex(8) for _ in range(2)]
    for key, selection in zip(keys, selected):
        path = game/'.battleaces-resurrection/profiles'/(key+'.cosmetics.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        value = dict(schema=1, build=37822, profile=key, catalog_sha256=book.sha256, slots=selection.slots)
        with path.open('xb') as stream:
            stream.write((json.dumps(value, separators=(',', ':'))+'\n').encode('ascii'))
    preference = game/'.battleaces-resurrection/practice-settings.ini'
    preference_before = sha(preference) if preference.exists() else None
    pki_folder = output/'ephemeral-pki'
    pki = generate_test_pki(pki_folder)
    audit = Audit(output)
    events, workers, clients, sockets, authenticated, entries = [], [], [], [], [], []
    attempts = [0, 0]
    identities = [('p_'+secrets.token_hex(16), 'ba1_'+secrets.token_urlsafe(32)) for _ in range(2)]

    class Store:
        def authenticate(self, token):
            for profile, expected in identities:
                if secrets.compare_digest(token, expected):
                    authenticated.append(profile)
                    return profile
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
    server = DedicatedServer(templates[1], ProfileStore(output/'profiles', templates[1], catalog=book), templates=templates,
        bot_catalog=BotCatalog(assets, template=templates[1], rules=RuleBook(assets)), sim_factory=factory, ai_factory=factory,
        audit=observe, data_dir=output, audit_state=False, input_timeout=30,
        tls_context=tls.load_server_context(pki['cert'], pki['key']), admission=admission.AdmissionController(Store()))
    started = time.monotonic()
    report = dict(passed=False, scope=custom_transition_probe.__doc__ if custom else __doc__,
                  custom_transitions=custom, modes=['C', 4, 'C', 1, 'C'] if custom else list(evidence.MODES), helper_sha256=sha(game/'BattleAcesOffline.dll'),
                  helper_build_receipt_sha256=helper['sha256'], preparation_sha256=sha(args.preparation),
                  source_sha256_at_start=source_hashes(), shared_settings_before=startup.shared_state(args.shared_settings),
                  preference_before=preference_before, stages=[], game_pids=[], ordinary_player_base_arguments=[])
    clock = ctypes.WinDLL('kernel32').GetTickCount64
    clock.restype = ctypes.c_ulonglong

    def refresh():
        for record in clients:
            require(record['process'].poll() is None and not record['task'].done(), 'owned game/bridge exited during sequence')
            record['log'] = read_native_log(game, record['process'].pid, since_tick=record['tick'])
            for marker in ('Public client failure:', 'Client lifecycle invariant failed:', 'Offline loop stopped in ',
                           'Practice stopped in ', 'Public fallback accepted:', 'Public result Continue routing failed:',
                           'Cosmetic persistence unavailable:'):
                require(marker not in record['log'], 'native sequence failure: '+marker)

    async def wait_for(predicate, message):
        while True:
            refresh()
            if predicate():
                return
            require(time.monotonic()-started < args.timeout, message)
            await asyncio.sleep(.1)

    async def capacity_idle():
        deadline = time.monotonic()+8
        while server.rooms or server.worker_cleanup or server.community.public.entries or server.community.public.offers:
            require(time.monotonic() < deadline, 'old public capacity retained at mode boundary')
            await asyncio.sleep(.05)
        require(not server.community.lobbies, 'public sequence created a Custom lobby')

    try:
        port = (await server.start('127.0.0.1', 0))[1]
        apply = server.community.public.apply

        async def capture_apply(session, kind, command, now):
            result = await apply(session, kind, command, now)
            if kind == loadout_protocol.ENTER_LOADOUT:
                entry = server.community.public.entries[session.peer.profile_id]
                entries.append(dict(profile=entry.profile, ticket=entry.ticket, mode=entry.mode,
                                    deck=list(entry.deck), cosmetics=entry.cosmetics))
            return result

        server.community.public.apply = capture_apply
        context = tls.load_client_context(pki['ca'], 'localhost')
        shutil.copyfile(game/'.battleaces-resurrection/patch-manifest.json', output/'patch-manifest.json')
        for index in range(2):
            config = dict(game_directory=game, server_host='127.0.0.1', server_port=port,
                          display_name=f'Sequence Human {index+1}', room='community', local_profile=keys[index])
            parent, child = socket.socketpair(socket.AF_INET)
            sockets.extend((parent, child))
            parent.setblocking(False)
            reader, writer = await asyncio.open_connection(sock=parent)

            async def resolve(index=index):
                attempts[index] += 1
                return bridge.Remote('127.0.0.1', port, context, *identities[index])

            record = dict(name=config['display_name'], writer=writer, log='', stages=[],
                          task=asyncio.create_task(bridge.Bridge(reader, writer, resolve, version=2).run()))
            clients.append(record)
            command = launcher.game_arguments(config, None, child.fileno(), client.player_options())
            require(not any('smoke' in value or 'audit' in value or 'auto-' in value for value in command), 'ordinary arguments contain diagnostics')
            report['ordinary_player_base_arguments'].append(list(command))
            command[command.index('-logFile')+1] = str(output/f'game-{index}.log')
            command += ['-public-queue-smoke', '-lan-smoke', '-lan-audit', '-dedicated-surrender-smoke',
                        '-dedicated-surrender-frame=1200', '-public-team-surrender-smoke', '-match-search-smoke',
                        '-community-cosmetics-smoke', '-human-cosmetics-smoke']
            if custom:
                command += ['-custom-transition-smoke', '-custom-transition-gate='+gate_key,
                            '-community-match-'+('host' if index == 0 else 'guest')+'-smoke',
                            '-practice-ai-smoke', '-practice-ai-smoke-frames=3600']
                if index == 1:
                    command.append('-community-match-deck-smoke')
            else:
                command += ['-public-mode-sequence-smoke', '-public-queue-smoke-gate='+gate_key, '-dedicated-rematch-smoke']
            if index == 1 and not custom:
                command.append('-public-queue-smoke-edit-deck')
            startup_info = subprocess.STARTUPINFO()
            startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup_info.wShowWindow = 0
            startup_info.lpAttributeList = {'handle_list': [child.fileno()]}
            record['tick'] = clock()
            child.set_inheritable(True)
            try:
                record['process'] = subprocess.Popen(command, cwd=game, startupinfo=startup_info, close_fds=True,
                                                      creationflags=subprocess.CREATE_NO_WINDOW)
            finally:
                child.set_inheritable(False)
                child.close()
            record['job'] = _WindowsJob(record['process'].pid)
            report['game_pids'].append(record['process'].pid)
            record['arguments'] = command
            (output/'processes.json').write_text(json.dumps(dict(game_pids=report['game_pids'],
                processes=[dict(pid=row['process'].pid, tick=row['tick'], arguments=row['arguments']) for row in clients]), indent=2)+'\n')

        if custom:
            await custom_transition_probe.run(SimpleNamespace(game=game, assets=assets, output=output, runtime=runtime,
                server=server, clients=clients, events=events, workers=workers, entries=entries, identities=identities,
                attempts=attempts, authenticated=authenticated, report=report, selected=selected, keys=keys,
                gate_key=gate_key, wait_for=wait_for, capacity_idle=capacity_idle, observe=observe))
        else:
            sessions, decks = None, {}
            for ticket, mode in enumerate(evidence.MODES, 1):
                marker = f'PUBLIC MODE SEQUENCE waiting for gate: key={gate_key} stage={ticket} idleMenu=1'
                await wait_for(lambda: all(marker in row['log'] for row in clients), 'native mode gate not reached')
                require(all(f'BA_RESURRECTION_COSMETICS_PERSIST_V1 ready: profile={key} slots=17 restored=1 writable=1' in row['log']
                            for key, row in zip(keys, clients)), 'owned canonical cosmetic fixture was not restored')
                await capacity_idle()
                require(all(row['log'].count('Public search intent:') == ticket-1 for row in clients), 'next Play bypassed mode gate')
                offsets = [len(row['log']) for row in clients]
                with gates[ticket-1].open('xb'):
                    pass
                observe('probe_mode_gate_released', ticket=ticket, mode=mode)
                marker = f'Public intent retired: ticket={ticket} reason=returned nativeIdle=1 disconnect=0'
                await wait_for(lambda: all(marker in row['log'][offset:] for row, offset in zip(clients, offsets)), 'mode match/result/Continue timed out')
                await capacity_idle()
                offers = [row for row in events if row['event'] == 'public_match_offered']
                completed = [row for row in events if row['event'] == 'match_completed']
                entered = [row for row in events if row['event'] == 'public_queue_entered' and row['ticket'] == ticket]
                require(len(offers) == len(completed) == len(workers) == ticket and not any(row['event'] == 'match_aborted' for row in events), 'mode allocated duplicate/aborted match')
                offer, result = offers[-1], completed[-1]
                match = offer['match']
                profiles = {profile for profile, _ in identities}
                require(match == result['match'] and offer['mode'] == mode and set(offer['humans']) == profiles and
                        len(entered) == 2 and {row['profile'] for row in entered} == profiles, 'available humans split/changed')
                waits = [offer['observed_at']-row['observed_at'] for row in entered]
                require(offer['fallback'] == (mode == 2) and
                        (29 <= max(waits) <= 33 if mode == 2 else 0 <= max(waits) < 5), 'mode changed real queue policy')
                current_sessions = {profile: server.community.sessions.get(profile) for profile in profiles}
                require(attempts == [1, 1] and sorted(authenticated) == sorted(profiles) and
                        all(value is not None and not value.peer.closed and value.peer.room is None for value in current_sessions.values()), 'mode changed authentication ownership')
                if sessions is None:
                    sessions = current_sessions
                require(all(current_sessions[profile] is value for profile, value in sessions.items()), 'mode replaced an available human session')
                folder = output/'matches'/match
                manifest = json.loads((folder/'match.json').read_bytes())
                require(manifest['bootstrap_sha256'] == sha(folder/'bootstrap.pb.gz'), 'archived bootstrap differs from manifest')
                native_players = expected_players((folder/'bootstrap.pb.gz').read_bytes(), match, mode)
                total, seats = q.MODES[mode]
                expected_seats = set(seats[:2])
                require(set(map(int, manifest['profiles'])) == expected_seats and set(map(int, manifest['bots'])) == set(range(total))-expected_seats, 'mode human/bot topology differs')
                authoritative = {row['frame']: row['frame_payload_sha256'] for row in events if row['event'] == 'frame_queued' and row['match'] == match}
                stage_clients = []
                for index, (record, offset) in enumerate(zip(clients, offsets)):
                    tail, pid = record['log'][offset:], record['process'].pid
                    own_seats = [int(seat) for seat, profile in manifest['profiles'].items() if profile == identities[index][0]]
                    require(len(own_seats) == 1, 'human assigned twice or missing')
                    seat = own_seats[0]
                    proof = evidence.stage(tail, ticket, mode, gate_key, match, seat, sum(1 << value for value in expected_seats))
                    seconds = [int(value) for old_ticket, value in re.findall(r'Native search timer: ticket=(\d+) seconds=(\d+)', tail)
                               if int(old_ticket) == ticket]
                    require(seconds and seconds[0] == 0 and seconds == sorted(seconds) and
                            (mode != 2 or max(seconds) >= 25), 'original search timer missing or not advancing')
                    native = native_players[seat]
                    require(native['name'] == record['name'] and native['profile'] == 0 and
                            native['portrait'] == selected[index].portrait and native['banner'] == selected[index].banner, 'bootstrap changed configured human identity/avatar')
                    queued = [row for row in entries if row['profile'] == identities[index][0] and row['ticket'] == ticket]
                    require(len(queued) == 1 and queued[0]['mode'] == mode and queued[0]['cosmetics'] == selected[index] and
                            queued[0]['deck'] == native['units'], 'queue changed human frozen deck/17slots')
                    deck = native['units']
                    if index not in decks:
                        decks[index] = deck
                    require(deck == decks[index], 'mode changed selected human deck')
                    snapshots = [json.loads(line.split('REMOTE COSMETICS frozen snapshot: ', 1)[1]) for line in tail.splitlines()
                                 if 'REMOTE COSMETICS frozen snapshot: ' in line]
                    require(len(snapshots) == 1 and snapshots[0]['profile'] == keys[index] and
                            snapshots[0]['catalog_sha256'] == book.sha256 and book.validate_selection(snapshots[0]['slots']) == selected[index] and
                            f'REMOTE COSMETICS SimPlayer passed: match={match} army={seat} ' in tail, 'original full native appearance missing')
                    frame = 300+100*seat
                    build = re.search(rf'LAN NORMAL BUILD smoke frame{frame} slot{seat} army{seat} [^\r\n]+', tail)
                    require(build is not None and 'queued=1 commandQueueDelta=1' in build[0], 'native human build missing')
                    path = runtime/f'dedicated-receipts-{pid}-{match}.tsv'
                    raw = path.read_bytes()
                    rows = list(csv.DictReader(raw.decode('utf-8').splitlines(), delimiter='\t'))
                    require(len(rows) == len(authoritative) >= 600 and [int(row['frame']) for row in rows] == list(range(len(rows))) and
                            all(row['sha256'] == authoritative.get(int(row['frame'])) for row in rows), 'native frames differ from authoritative journal')
                    (output/path.name).write_bytes(raw)
                    record['stages'].append(proof)
                    stage_clients.append(dict(**proof, pid=pid, name=record['name'], deck=deck, build_frame=frame,
                        received_frames=len(rows), receipt_sha256=hashlib.sha256(raw).hexdigest(), complete_appearance=True))
                require(decks[0] != decks[1], 'independent human deck edit missing')
                report['stages'].append(dict(ticket=ticket, mode=mode, match=match, clients=stage_clients,
                    received_frames=len(authoritative), real_queue_seconds=waits, result=result['result'],
                    bootstrap_sha256=sha(folder/'bootstrap.pb.gz'), manifest_sha256=sha(folder/'match.json'),
                    journal_human_builds=journal_builds(folder/'frames.bin', stage_clients, len(authoritative)),
                    original_sessions_retained=True, capacity_idle=True))
                (output/'progress.json').write_text(json.dumps(report['stages'], indent=2)+'\n')
            report['native_sequences'] = [evidence.sequence(row['log'], row['stages']) for row in clients]
        report['passed'] = True
    except BaseException as error:
        report.update(passed=False, error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        for record in clients:
            process = record.get('process')
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                await asyncio.to_thread(process.wait, timeout=15)
                (output/f'native-{process.pid}.log').write_bytes(read_native_log(game, process.pid, since_tick=record['tick']).encode('utf-8'))
            if record.get('job') is not None:
                record['job'].close()
            record['task'].cancel()
            record['writer'].close()
        await asyncio.gather(*(row['task'] for row in clients), return_exceptions=True)
        for record in clients:
            try:
                await asyncio.wait_for(record['writer'].wait_closed(), 2)
            except (OSError, TimeoutError):
                record['writer'].transport.abort()
        for sock in sockets:
            sock.close()
        await server.close()
        await asyncio.gather(*(worker.close() for worker in workers))
        remove_test_pki(pki_folder)
        for gate in gates:
            if gate.exists():
                require(gate.resolve().parent == runtime.resolve() and gate.is_file() and not gate.is_symlink(), 'owned gate changed')
                gate.unlink()
        audit.close()
        cleanup = []
        for worker in workers:
            reaped = worker.process.poll() is not None and worker._cleanup_task is not None and worker._cleanup_task.done() and not worker._stderr_thread.is_alive()
            cleanup.append(dict(pid=worker.pid, exit_code=worker.process.poll(), failure=worker.failure,
                stderr_tail=worker.stderr_tail[-4096:], owned_resources_reaped=reaped,
                passed=reaped and worker.process.poll() == 0 and not worker.failure and not worker.stderr_tail))
        report.update(worker_cleanup=cleanup, remote_attempts=attempts, authentications=len(authenticated),
            elapsed_seconds=time.monotonic()-started, owned_processes_reaped=all(row.get('process') is None or row['process'].poll() is not None for row in clients),
            cleanup='forced owned termination, not native Quit', gates_removed=not any(path.exists() for path in gates),
            ephemeral_pki_removed=not pki_folder.exists(), source_sha256_at_finish=source_hashes(),
            shared_settings_after=startup.shared_state(args.shared_settings), preference_after=sha(preference) if preference.exists() else None)
        try:
            seals(preparation)
            verify_build_receipt(game, args.helper_build.resolve())
            report['program_manual71_lan03_seals_unchanged'] = True
        except Exception as error:
            report.update(passed=False, seals_error=f'{type(error).__name__}: {error}')
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['shared_settings_unchanged'] = report['shared_settings_before'] == report['shared_settings_after']
        report['practice_preference_unchanged'] = report['preference_before'] == report['preference_after']
        report['passed'] &= (all(row['passed'] for row in cleanup) and len(cleanup) == 4 and report['owned_processes_reaped'] and
            report['gates_removed'] and report['ephemeral_pki_removed'] and report['source_files_unchanged'] and
            report['shared_settings_unchanged'] and report['practice_preference_unchanged'])
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({key: report[key] for key in ('passed', 'error', 'elapsed_seconds', 'game_pids', 'remote_attempts') if key in report}))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'assets', 'output', 'helper-build', 'preparation', 'cosmetics-selection', 'shared-settings'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=900)
    parser.add_argument('--custom-transitions', action='store_true', help='qualify Custom/local4/Custom/public1/Custom through original invites and Leave')
    args = parser.parse_args()
    require(os.name == 'nt' and 300 <= args.timeout <= 900, 'bounded Windows sequence required')
    return asyncio.run(run(args))


if __name__ == '__main__':
    raise SystemExit(main())
