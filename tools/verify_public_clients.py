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
from server import admission, loadout_protocol, public_protocol as q, tls_transport as tls
from server.ai_rules import RuleBook
from server.assets import verify_assets
from server.bot_catalog import BotCatalog
from server.credentials import AuthenticationError
from server.cosmetics import CosmeticCatalog
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
    paths = [Path(__file__), ROOT/'tools/run_secure_match.py', ROOT/'tools/verify_practice_ai.py'] + list((ROOT/'client_patch/transport').glob('*.py'))
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
    cosmetic_book = CosmeticCatalog(assets) if args.cosmetics_selection else None
    cosmetic_seeds, cosmetic_profiles, queue_selections, frozen_matches = [], [], [], []
    if cosmetic_book:
        require(game.is_relative_to(ROOT/'local'), 'full cosmetic probe requires a disposable game copy')
        seed = json.loads(args.cosmetics_selection.read_bytes())
        seed = seed.get('state', seed)
        require(seed['catalog_sha256'] == cosmetic_book.sha256, 'native seed/catalog mismatch')
        native_seed = cosmetic_book.validate_selection(seed['slots'])
        portrait_slot = cosmetic_book.roles['portrait']
        portraits = sorted(cosmetic_book.slots[portrait_slot].compatible_items)
        require(len(portraits) >= args.humans, 'not enough distinct installed human portraits')
        folder = game/'.battleaces-resurrection/profiles'
        folder.mkdir(parents=True, exist_ok=True)
        prefix, used = 'cosmeticstest_'+secrets.token_hex(6)+'_team', set()
        for index in range(args.humans):
            pairs = dict((native_seed if index == 0 else cosmetic_book.normalize_local()).slots)
            if pairs[portrait_slot] in used:
                pairs[portrait_slot] = next(item for item in portraits if item not in used)
            selected = cosmetic_book.validate_selection(pairs)
            used.add(selected.portrait)
            cosmetic_seeds.append(selected)
            key = prefix+'_'+str(index)
            cosmetic_profiles.append(key)
            value = dict(schema=1, build=37822, profile=key, catalog_sha256=selected.catalog_sha256, slots=selected.slots)
            with (folder/(key+'.cosmetics.json')).open('xb') as stream:
                stream.write((json.dumps(value, separators=(',', ':'))+'\n').encode('ascii'))
    runtime = game/'investigation/runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    gate_key = secrets.token_hex(16)
    gate_path = runtime/f'public-queue-{gate_key}.ready'
    retry_gate_path = runtime/f'public-queue-{gate_key}-retry.ready'
    practice_gate_path = runtime/f'public-queue-{gate_key}-practice.ready'
    require(not any(path.exists() for path in (gate_path, retry_gate_path, practice_gate_path)), 'diagnostic gate already exists')
    if args.retry:
        require(b'PUBLIC QUEUE SMOKE waiting for retry gate:' in (game/'BattleAcesOffline.dll').read_bytes(),
                'retry probe requires the current helper with a separate retry gate')
    if args.practice_between:
        require(b'PUBLIC QUEUE SMOKE waiting for practice gate:' in (game/'BattleAcesOffline.dll').read_bytes(),
                'practice transition probe requires the current helper with a separate practice gate')
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
        if event == 'match_created' and cosmetic_book:
            room = server.rooms[fields['room']]
            frozen_matches.append(dict(match=fields['match'], profiles={slot:peer.profile_id for slot, peer in room.peers.items()},
                cosmetics={slot:dict(catalog_sha256=value.catalog_sha256, slots=value.slots)
                           for slot, value in room.match.cosmetics_by_slot.items()}))

    async def factory(data, bots=None):
        worker = await SimulationWorker.create(data, assets/'Simulation.dll', working_directory=output,
                                               ai=AISetup(assets, bots) if bots else None)
        workers.append(worker)
        return worker

    templates = {mode: GameTemplate.load(assets/name, catalog_path=assets/'unit-catalog.json', descriptors_path=assets/'descriptors')
                 for mode, name in ((1, 'map-1v1.pb.gz'), (2, 'map-2v2.pb.gz'), (5, 'map-2vai.pb.gz'))}
    catalog = BotCatalog(assets, template=templates[1], rules=RuleBook(assets))
    server = DedicatedServer(templates[1], ProfileStore(output/'profiles', templates[1], catalog=cosmetic_book), templates=templates,
        bot_catalog=catalog, sim_factory=factory, ai_factory=factory, audit=observe, data_dir=output,
        audit_state=False, input_timeout=30, tls_context=tls.load_server_context(pki['cert'], pki['key']),
        admission=admission.AdmissionController(Store()))
    started, gate_created, retry_gate_created, practice_gate_created, fault = time.monotonic(), False, False, False, None
    report = dict(passed=False, scope=__doc__, mode=args.mode, humans=args.humans, visible=args.visible,
        helper_sha256=hashlib.sha256((game/'BattleAcesOffline.dll').read_bytes()).hexdigest(),
        source_sha256_at_start=source_hashes(), disconnect=args.disconnect, retry=args.retry, practice_between=args.practice_between,
        game_pids=[], client_arguments=[], launch_ticks=[])
    clock = ctypes.WinDLL('kernel32').GetTickCount64
    clock.restype = ctypes.c_ulonglong

    def refresh_clients():
        for index, record in enumerate(clients):
            require(record['process'].poll() is None, 'owned game exited before native return')
            require(not record['task'].done(), 'private bridge exited before native completion')
            record['log'] = read_native_log(game, record['process'].pid, since_tick=record['tick'])
            for failure in ('Public client failure:', 'Client lifecycle invariant failed:', 'Practice stopped in ',
                            'LAN normal-build smoke disabled', 'LAN normal-build smoke stopped',
                            'Public result Continue routing failed:'):
                require(failure not in record['log'], 'native failure: '+failure)
            for failure in re.findall(r'Offline loop stopped in [^\n]*', record['log']):
                require(fault is not None and index == 0 and re.fullmatch(
                    r'Offline loop stopped in (?:LAN update|LAN front update|dedicated session update): '
                    r'(?:match server disconnected before a result|Secure session is closed)', failure.rstrip('\r')),
                    'unexpected native stop: '+failure)
            require('inner=ProvingGroundsState' not in record['log'], 'public result entered retired progression reward flow')

    try:
        port = (await server.start('127.0.0.1', 0))[1]
        apply = server.community.public.apply
        async def capture_apply(session, kind, command, now):
            result = await apply(session, kind, command, now)
            if cosmetic_book and kind == loadout_protocol.ENTER_LOADOUT:
                entry = server.community.public.entries[session.peer.profile_id]
                queue_selections.append(dict(profile=entry.profile, ticket=entry.ticket, deck=entry.deck,
                    catalog_sha256=entry.cosmetics.catalog_sha256, slots=entry.cosmetics.slots))
            return result
        server.community.public.apply = capture_apply
        context = tls.load_client_context(pki['ca'], 'localhost')
        shutil.copyfile(game/'.battleaces-resurrection/patch-manifest.json', output/'patch-manifest.json')
        for index in range(args.humans):
            config = dict(game_directory=game, server_host='127.0.0.1', server_port=port,
                          display_name=f'Human Client {index+1}', room='community')
            if cosmetic_book:
                config['local_profile'] = cosmetic_profiles[index]
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
            if cosmetic_book:
                command += ['-local-cosmetics-experimental', '-community-cosmetics-smoke', '-human-cosmetics-smoke']
            if index == 1:
                command.append('-public-queue-smoke-edit-deck')
            if args.disconnect and index == 0:
                command.append('-dedicated-recovery-smoke')
            if args.retry:
                command += ['-public-queue-smoke-retry', '-public-queue-smoke-retry-gate', '-public-team-retry-smoke']
            if args.practice_between:
                command += ['-public-practice-transition-smoke', '-practice-ai-smoke', '-practice-ai-smoke-frames=3600']
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
            refresh_clients()
            if not gate_created and all('PUBLIC QUEUE SMOKE waiting for shared gate: key='+gate_key in row['log'] for row in clients):
                require(not any('Public search intent:' in row['log'] for row in clients), 'Play started before every menu was ready')
                with gate_path.open('xb'):
                    pass
                gate_created = True
                observe('probe_shared_gate_released', clients=len(clients))
            if args.disconnect and fault is None:
                joined = all('Public native match joined: ticket=1 ' in row['log'] for row in clients)
                received = [[int(value) for value in re.findall(r'LAN received frame (\d+),', row['log'])] for row in clients]
                reached = joined and (args.disconnect == 'loading' or all(values and max(values) >= 200 for values in received))
                if reached:
                    entry = server.community.public.entries.get(identities[0][0])
                    require(entry is not None, 'disconnect target has no current public entry')
                    peer, room = entry.session.peer, entry.session.peer.room
                    require(room is not None and not peer.closed and len(room.peers) == args.humans,
                            'disconnect target room missing or roster changed')
                    if args.disconnect == 'loading':
                        require(room.state == 'loading' and not room.loaded and
                                all('Offline world ready;' not in row['log'] for row in clients),
                                'team loading disconnect missed the asynchronous map-load window')
                    else:
                        require(room.state == 'running' and room.loaded == set(room.peers) and
                                all('Offline world ready;' in row['log'] for row in clients),
                                'team running disconnect did not reach every loaded native world')
                    fault = dict(stage=args.disconnect, match=room.match_id, victim_index=0, victim_seat=peer.slot,
                                 room_state=room.state, last_native_frames=[max(values, default=-1) for values in received],
                                 log_offsets=[len(row['log']) for row in clients])
                    observe('probe_disconnect', **fault)
                    report['injected_disconnect'] = fault
                    peer.close()
            victim_retired = 'reason=connection lost after match acceptance nativeIdle=1 disconnect=1' in clients[0]['log']
            if (fault and victim_retired and all('PUBLIC QUEUE completed return:' in row['log'] for row in clients[1:]) or
                    not args.disconnect and all('PUBLIC QUEUE completed return:' in row['log'] for row in clients)):
                break
            require(time.monotonic()-started < args.timeout, 'multi-client public match timed out')
            await asyncio.sleep(.02 if args.disconnect and fault is None else .2)
        require(gate_created, 'shared start gate was bypassed')
        completed = [row for row in events if row['event'] == 'match_completed']
        aborted = [row for row in events if row['event'] == 'match_aborted']
        offered = [row for row in events if row['event'] == 'public_match_offered']
        entered = [row for row in events if row['event'] == 'public_queue_entered']
        require(len(offered) == len(workers) == 1 and len(entered) == args.humans,
                'humans did not share exactly one offer/worker')
        if args.disconnect:
            require(fault is not None and len(aborted) == 1 and not completed and aborted[0]['match'] == fault['match'],
                    'injected team disconnect did not abort exactly its shared match')
        else:
            require(len(completed) == 1 and not aborted, 'shared match did not complete normally')
        require(sorted(authenticated) == sorted(player for player, token in identities) and attempts == [1]*args.humans,
                'authentication/connection ownership differs')
        match, offer = (aborted if args.disconnect else completed)[0]['match'], offered[0]
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
            require(log.count('Public native match joined:') == 1 and
                    log.count('PUBLIC QUEUE completed return:') == (0 if args.disconnect and index == 0 else 1) and
                    log.count('Client world acquired:') == log.count('owner=remote nativeIdle=1') == 1 and
                    'Public fallback accepted:' not in log and 'owner=local-practice' not in log,
                    'native match/world/return ownership differs')
            require('PUBLIC QUEUE SMOKE original OnMapSelected:' in log and 'Native search joining signal:' in log and
                    'Native search released:' in log, 'original search/loading lifecycle missing')
            require(log.count(f'Public result Continue routed: mode={args.mode} source=remote next=End') == (0 if args.disconnect else 1),
                    'native result Continue count differs from completed/aborted flow')
            require(index != 1 or 'DEDICATED REMATCH SMOKE automated native deck edit:' in log, 'second native deck edit missing')
            frame = 300+100*seat
            build = re.search(rf'LAN NORMAL BUILD smoke frame{frame} slot{seat} army{seat} [^\r\n]+', log)
            if not args.disconnect:
                require(build is not None and 'queued=1 commandQueueDelta=1' in build[0], 'human normal build was not queued')
            receipts = runtime/f'dedicated-receipts-{pid}-{match}.tsv'
            rows = list(csv.DictReader(receipts.read_text(encoding='utf-8').splitlines(), delimiter='\t')) if receipts.exists() else []
            minimum = 0 if args.disconnect == 'loading' else 201 if args.disconnect else 600
            require(len(rows) >= minimum and [int(row['frame']) for row in rows] == list(range(len(rows))),
                    'native receipt prefix missing/out of order')
            require(all(row['sha256'] == authoritative.get(int(row['frame'])) for row in rows), 'native frame differs from authoritative journal')
            if not args.disconnect:
                require(len(rows) == len(authoritative), 'native receipt count differs from authoritative frames')
            elif args.disconnect == 'loading':
                require(not rows and not authoritative, 'loading abort unexpectedly advanced the simulation')
            if receipts.exists():
                shutil.copyfile(receipts, output/receipts.name)
            seconds = [int(value) for ticket, value in re.findall(r'Native search timer: ticket=(\d+) seconds=(\d+)', log) if ticket == '1']
            require(seconds and seconds[0] == 0 and seconds == sorted(seconds), 'native search clock missing/nonmonotonic')
            if not full:
                require(max(seconds) >= 25, 'partial group search timer did not advance through queue wait')
            if args.disconnect:
                offset = fault['log_offsets'][index]
                if index == 0:
                    markers = ('RECOVERY SMOKE invoking original disconnected modal OnConfirm',
                               'Dedicated Reconnect callback queued:',
                               'RECOVERY SMOKE original OnConfirm returned; modalStillOwned=1 queued=1',
                               'Dedicated retry modal released on later update:',
                               'Dedicated session reset: match='+match,
                               'Client world released: generation=1 owner=remote nativeIdle=1',
                               'Public intent retired: ticket=1 reason=connection lost after match acceptance nativeIdle=1 disconnect=1')
                    positions = [log.find(value, offset) for value in markers]
                    require(all(left >= 0 and right > left for left, right in zip(positions, positions[1:])),
                            'disconnected teammate cleanup/modal/world release order incorrect')
                    deferred = re.search(r'Dedicated retry modal released on later update: requested=(\d+) current=(\d+)', log)
                    require(deferred is not None and int(deferred[1]) < int(deferred[2]) and
                            'Dedicated aborted match: requesting original CleanupGameState(reason=1)' in log,
                            'disconnected teammate bypassed deferred native cleanup')
                else:
                    require(f'Public native return: ticket=1 match={match} aborted=1 nativeIdle=1' in log[offset:],
                            'surviving teammate did not return through authoritative abort')
                    session = server.community.sessions.get(identities[index][0])
                    require(session is not None and not session.peer.closed and session.peer.room is None and
                            'Dedicated Reconnect callback queued:' not in log,
                            'surviving teammate lost its existing community connection')
            evidence.append(dict(pid=pid, seat=seat, name=record['name'], build_frame=frame, native_build=build[0] if build else None,
                                 received_frames=len(rows), native_elapsed_seconds=seconds, deck=manifest['decks'][str(seat)]))
        require({row['seat'] for row in evidence} == expected_seats, 'duplicate/missing native human seat')
        deadline = time.monotonic()+5
        while server.community.public.entries or server.community.public.offers or server.rooms or server.worker_cleanup:
            require(time.monotonic() < deadline, 'public match retained queue/room/worker capacity')
            await asyncio.sleep(.05)
        require(not server.community.public.entries and not server.community.public.offers and not server.rooms and
                not server.community.lobbies, 'completed public match retained queue/room/lobby capacity')
        report.update(passed=True, match=match, received_frames=len(authoritative), clients=evidence,
            full_human_group=full, real_queue_seconds=waits, result=completed[0]['result'] if completed else None,
            bots=manifest['bots'], remote_attempts=attempts, authentications=len(authenticated))
        if not args.disconnect:
            report['journal_human_builds'] = journal_builds(output/'matches'/match/'frames.bin', evidence, len(authoritative))
        else:
            report['aborted_match_retired'] = True
            report['surviving_connections_preserved'] = args.humans-1
        if args.retry:
            survivors = {player: server.community.sessions[player] for player, token in identities if player in server.community.sessions}
            if args.practice_between:
                from tools.verify_practice_ai import movement_evidence
                while not all('PUBLIC QUEUE SMOKE waiting for practice gate: key='+gate_key in row['log'] for row in clients):
                    require(time.monotonic()-started < args.timeout, 'retired public menus did not reach their practice gate')
                    await asyncio.sleep(.05)
                    refresh_clients()
                practice_offsets = [len(row['log']) for row in clients]
                with practice_gate_path.open('xb'):
                    pass
                practice_gate_created = True
                observe('probe_practice_gate_released', clients=len(clients), after_match=match)
                marker = 'Practice returned: completed=1 mode=4 seat=-1 presenceRetained=0 standalone=1'
                while not all(marker in row['log'][offset:] for row, offset in zip(clients, practice_offsets)):
                    require(time.monotonic()-started < args.timeout, 'remote to local practice/result/Continue timed out')
                    await asyncio.sleep(.2)
                    refresh_clients()
                local_evidence = []
                for index, record in enumerate(clients):
                    tail = record['log'][practice_offsets[index]:]
                    starts = re.findall(r'Practice requested: match=([0-9a-f]{32}) ', tail)
                    require(len(starts) == 1, 'transition did not create exactly one independent local match')
                    snapshots = [json.loads(line.split('Practice army snapshot: ', 1)[1]) for line in tail.splitlines()
                                 if 'Practice army snapshot: ' in line]
                    require(len(snapshots) == 2 and snapshots[0]['deck']['units'] == evidence[index]['deck'] and
                            snapshots[0]['players'][0]['playerHandleWithName']['playerName'] == record['name'],
                            'local transition changed the configured human name/deck')
                    if cosmetic_book:
                        selected = cosmetic_seeds[index]
                        frozen = [json.loads(line.split('HUMAN COSMETICS frozen message: ', 1)[1])
                                  for line in tail.splitlines() if 'HUMAN COSMETICS frozen message: ' in line]
                        require(len(frozen) == 2 and frozen[0]['deck'] == frozen[1]['deck'] == snapshots[0]['deck'] and
                                frozen[0]['deck']['entitlements'] == [dict(cosmeticAssetKeys=list(selected.keys))] and
                                all(value.get('portraitId', 0) == selected.portrait and value.get('bannerId', 0) == selected.banner
                                    for value in frozen), 'local transition lost full config/join cosmetic intent')
                        require(tail.count('HUMAN COSMETICS SimPlayer passed:') == 1,
                                'local transition lacks full native simulation map/unit proof')
                        for phase in ('in-game', 'result'):
                            require(any(f'HUMAN COSMETICS identity binding: phase={phase} ' in line and
                                        f'portrait={selected.portrait} banner={selected.banner} ' in line
                                        for line in tail.splitlines()), 'local transition human UI binding missing: '+phase)
                    moved, ordered = movement_evidence(tail, set(snapshots[1]['deck']['units']))
                    require(bool(moved & ordered), 'transition bot did not autonomously order and move a produced unit')
                    resources = runtime/f'lan-resources-{record["process"].pid}-{starts[0]}.tsv'
                    with resources.open(encoding='utf-8') as stream:
                        supply = max((int(row['current_supply']) for row in csv.DictReader(stream, delimiter='\t')
                                      if row['viewer'] == '1' and row['army'] == '1'), default=0)
                    require(supply > 0, 'transition bot produced no native supply')
                    for value in ('Practice native EndOfGameResponse delivered;', 'PRACTICE SMOKE native Continue',
                                  'owner=local-practice nativeIdle=1'):
                        require(tail.count(value) == 1, 'local transition lifecycle differs: '+value)
                    shutil.copyfile(resources, output/resources.name)
                    local_evidence.append(dict(pid=record['process'].pid, match=starts[0], human_deck=snapshots[0]['deck']['units'],
                        configured_name=record['name'], bot_max_supply=supply, moved_autonomous_units=sorted(moved & ordered)))
                deadline = time.monotonic()+5
                while server.community.sessions:
                    require(time.monotonic() < deadline, 'local practice retained community presence')
                    await asyncio.sleep(.05)
                require(attempts == [1]*args.humans and len(authenticated) == args.humans and len(workers) == 1 and
                        not server.community.public.entries and not server.community.public.offers and not server.rooms,
                        'local practice contacted or allocated a new multiplayer match')
                report['local_practice'] = local_evidence
            while not all('PUBLIC QUEUE SMOKE waiting for retry gate: key='+gate_key in row['log'] for row in clients):
                require(time.monotonic()-started < args.timeout, 'native retry menus did not reach their shared gate')
                await asyncio.sleep(.05)
                refresh_clients()
            offsets = [len(row['log']) for row in clients]
            require(all(row['log'].count('Public search intent:') == 1 and row['log'].count('Client world acquired:') == (2 if args.practice_between else 1)
                        for row in clients), 'retry started before first-match cleanup qualification')
            with retry_gate_path.open('xb'):
                pass
            retry_gate_created = True
            observe('probe_retry_gate_released', clients=len(clients), after_match=match)
            while True:
                refresh_clients()
                if all('Public intent retired: ticket=2 reason=returned nativeIdle=1 disconnect=0' in row['log'][offset:]
                       for row, offset in zip(clients, offsets)):
                    break
                require(time.monotonic()-started < args.timeout, 'graphical team retry/result/Continue timed out')
                await asyncio.sleep(.2)
            completed = [row for row in events if row['event'] == 'match_completed']
            offered = [row for row in events if row['event'] == 'public_match_offered']
            require(len(completed) == (1 if args.disconnect else 2) and len(offered) == len(workers) == 2 and
                    sum(row['event'] == 'match_aborted' for row in events) == (1 if args.disconnect else 0),
                    'retry did not create exactly one distinct completed replacement match')
            fresh_match = completed[-1]['match']
            require(fresh_match != match and offered[1]['match'] == fresh_match and
                    set(offered[1]['humans']) == {player for player, token in identities}, 'retry split or changed the human group')
            expected_attempts = [2]*args.humans if args.practice_between else [2]+[1]*(args.humans-1)
            expected_authenticated = [player for player, token in identities]*2 if args.practice_between else [identities[0][0]]+[player for player, token in identities]
            require(attempts == expected_attempts and sorted(authenticated) == sorted(expected_authenticated),
                    'retry authentication/connection ownership differs from its direct/offline route')
            if args.practice_between:
                require(all(server.community.sessions.get(player) is not None and server.community.sessions[player] is not session
                            for player, session in survivors.items()), 'offline practice retry reused retired community sessions')
            else:
                require(all(server.community.sessions.get(player) is session and not session.peer.closed
                            for player, session in survivors.items()), 'retry replaced a surviving community session')
            fresh_manifest = json.loads((output/'matches'/fresh_match/'match.json').read_text(encoding='utf-8'))
            require(set(map(int, fresh_manifest['profiles'])) == expected_seats and
                    set(map(int, fresh_manifest['bots'])) == set(range(total))-expected_seats,
                    'replacement human/bot roster differs')
            authoritative = {row['frame']: row['frame_payload_sha256'] for row in events
                             if row['event'] == 'frame_queued' and row['match'] == fresh_match}
            fresh_evidence = []
            for index, record in enumerate(clients):
                log, pid = record['log'], record['process'].pid
                tail = log[offsets[index]:]
                assigned = re.findall(r'Public match assignment: ticket=2 match=([0-9a-f]{32}) mode=(\d+) count=(\d+) seat=(\d+) humans=(\d+) ', tail)
                require(len(assigned) == 1, 'replacement assignment missing/duplicated')
                key, mode, count, seat, mask = assigned[0]
                seat = int(seat)
                require(key == fresh_match and int(mode) == args.mode and int(count) == total and seat in expected_seats and
                        int(mask) == sum(1 << value for value in expected_seats) and
                        fresh_manifest['profiles'][str(seat)] == identities[index][0], 'replacement assigned topology/profile differs')
                require(log.count('Public search intent:') == log.count('Public native match joined:') ==
                        log.count('owner=remote nativeIdle=1') == 2 and
                        log.count('Client world acquired:') == (3 if args.practice_between else 2) and
                        log.count('PUBLIC QUEUE completed return:') == (1 if args.disconnect and index == 0 else 2) and
                        log.count(f'Public result Continue routed: mode={args.mode} source=remote next=End') == (1 if args.disconnect else 2) and
                        'Public fallback accepted:' not in log and (args.practice_between or 'owner=local-practice' not in log),
                        'replacement native lifecycle duplicated or retained a world')
                require('Native search stale ticket rejected:' in tail and 'Native search joining signal: ticket=2 ' in tail and
                        'Native search released: ticket=2 ' in tail, 'replacement search generation/loading release missing')
                if index == 0 and not args.practice_between:
                    dismissed = tail.find('identity=public-error:1')
                    require(dismissed >= 0 and 'reason=public search restarted' in tail[dismissed:].splitlines()[0],
                            'replacement search retained the victim failure notice')
                receipts = runtime/f'dedicated-receipts-{pid}-{fresh_match}.tsv'
                rows = list(csv.DictReader(receipts.read_text(encoding='utf-8').splitlines(), delimiter='\t'))
                require(len(rows) == len(authoritative) >= 600 and [int(row['frame']) for row in rows] == list(range(len(rows))) and
                        all(row['sha256'] == authoritative.get(int(row['frame'])) for row in rows),
                        'replacement native frames differ from canonical journal')
                shutil.copyfile(receipts, output/receipts.name)
                frame = 300+100*seat
                build = re.search(rf'LAN NORMAL BUILD smoke frame{frame} slot{seat} army{seat} [^\r\n]+', tail)
                require(build is not None and 'queued=1 commandQueueDelta=1' in build[0], 'replacement native human build missing')
                require(fresh_manifest['decks'][str(seat)] == evidence[index]['deck'], 'replacement changed the selected human deck')
                fresh_evidence.append(dict(pid=pid, seat=seat, name=record['name'], build_frame=frame,
                    native_build=build[0], received_frames=len(rows), deck=fresh_manifest['decks'][str(seat)]))
            require({row['seat'] for row in fresh_evidence} == expected_seats, 'replacement duplicate/missing human seat')
            deadline = time.monotonic()+5
            while server.community.public.entries or server.community.public.offers or server.rooms or server.worker_cleanup:
                require(time.monotonic() < deadline, 'replacement retained queue/room/worker capacity')
                await asyncio.sleep(.05)
            report['replacement'] = dict(match=fresh_match, result=completed[-1]['result'], clients=fresh_evidence,
                received_frames=len(authoritative), survivor_sessions_retained=0 if args.practice_between else len(survivors),
                after_offline_practice=args.practice_between,
                journal_human_builds=journal_builds(output/'matches'/fresh_match/'frames.bin', fresh_evidence, len(authoritative)))
            report.update(remote_attempts=attempts, authentications=len(authenticated))
        if cosmetic_book:
            expected_matches = 2 if args.retry else 1
            require(len(frozen_matches) == expected_matches and len(queue_selections) == expected_matches*args.humans,
                    'complete team entries/matches missing')
            native = []
            for index, record in enumerate(clients):
                player, _ = identities[index]
                selected = cosmetic_seeds[index]
                own_entries = [value for value in queue_selections if value['profile'] == player]
                require([value['ticket'] for value in own_entries] == list(range(1, expected_matches+1)) and
                        all(value['catalog_sha256'] == cosmetic_book.sha256 and
                            cosmetic_book.validate_selection(value['slots']) == selected for value in own_entries),
                        'complete team queue intent changed or duplicated')
                for frozen in frozen_matches:
                    seats = [seat for seat, profile in frozen['profiles'].items() if profile == player]
                    require(len(seats) == 1 and set(frozen['cosmetics']) == set(frozen['profiles']),
                            'complete team server snapshot roster differs')
                    value = frozen['cosmetics'][seats[0]]
                    require(value['catalog_sha256'] == cosmetic_book.sha256 and
                            cosmetic_book.validate_selection(value['slots']) == selected,
                            'complete team server selection changed')
                snapshots = [json.loads(line.split('REMOTE COSMETICS frozen snapshot: ', 1)[1])
                             for line in record['log'].splitlines() if 'REMOTE COSMETICS frozen snapshot: ' in line]
                matches = re.findall(r'REMOTE COSMETICS SimPlayer passed: match=([0-9a-f]{32}) ', record['log'])
                expected_native = [value['match'] for value in frozen_matches]
                if args.disconnect == 'loading':
                    expected_native = expected_native[1:]
                require(matches == expected_native and len(snapshots) == len(matches) and
                        all(value['profile'] == cosmetic_profiles[index] and value['catalog_sha256'] == cosmetic_book.sha256 and
                            cosmetic_book.validate_selection(value['slots']) == selected for value in snapshots),
                        'native team full loadout/units proof missing or bound to another profile/match')
                saved = server.profiles.load_state(player, [])
                require(saved.cosmetics == selected and list(saved.deck) == list(own_entries[-1]['deck']),
                        'team return lost the saved full human loadout')
                native.append(dict(profile=player, local_profile=cosmetic_profiles[index], matches=matches, snapshots=snapshots))
            report['full_loadouts'] = dict(catalog=cosmetic_book.sha256, queue=queue_selections,
                server_matches=frozen_matches, native=native)
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
        if retry_gate_created:
            require(retry_gate_path.resolve().parent == runtime.resolve() and retry_gate_path.is_file() and not retry_gate_path.is_symlink(),
                    'owned retry gate path changed')
            retry_gate_path.unlink()
        if practice_gate_created:
            require(practice_gate_path.resolve().parent == runtime.resolve() and practice_gate_path.is_file() and not practice_gate_path.is_symlink(),
                    'owned practice gate path changed')
            practice_gate_path.unlink()
        audit.close()
        cleanup = []
        for worker in workers:
            match = next((row['match'] for row in events if row['event'] == 'worker_started' and row['worker_pid'] == worker.pid), None)
            released = any(row['event'] == 'worker_released' and row['match'] == match and row['worker_pid'] == worker.pid for row in events)
            reaped = worker.process.poll() is not None and worker._cleanup_task is not None and worker._cleanup_task.done() and not worker._stderr_thread.is_alive()
            cancelled = bool(fault and args.disconnect == 'running' and match == fault['match'] and released and
                             worker.process.poll() == 1 and (worker.failure or '').startswith('CancelledError:'))
            cleanup.append(dict(pid=worker.pid, match=match, exit_code=worker.process.poll(), failure=worker.failure,
                stderr_tail=worker.stderr_tail[-4096:], owned_resources_reaped=reaped, expected_cancelled_request=cancelled,
                passed=reaped and ((worker.process.poll() == 0 and not worker.failure) or cancelled)))
        report.update(elapsed_seconds=time.monotonic()-started, worker_cleanup=cleanup,
            owned_processes_reaped=all(record.get('process') is None or record['process'].poll() is not None for record in clients),
            cleanup='forced owned termination, not native Quit', gate_removed=not any(path.exists() for path in (gate_path, retry_gate_path, practice_gate_path)), source_sha256_at_finish=source_hashes())
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        clean = all(row['passed'] for row in cleanup)
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
    parser.add_argument('--cosmetics-selection', type=Path, help='accepted native seed; qualifies full loadouts with distinct installed portraits')
    parser.add_argument('--disconnect', choices=('loading', 'running'),
                        help='explicitly close the first owned client TLS peer; qualify native abort cleanup, not a completed match')
    parser.add_argument('--retry', action='store_true', help='after qualifying first-match cleanup, release a separate gate for a completed graphical replacement match')
    parser.add_argument('--practice-between', action='store_true', help='qualify one local Try Deck match per process between remote matches')
    args = parser.parse_args()
    require(os.name == 'nt' and args.output.resolve().is_relative_to(ROOT/'local') and 120 <= args.timeout <= 900,
            'bounded Windows/ignored probe required')
    require(args.humans <= len(q.MODES[args.mode][1]), 'too many humans for public mode')
    require(not args.retry or (args.disconnect or args.practice_between) and args.humans == len(q.MODES[args.mode][1]),
            'retry probe requires a disconnect or practice transition, and a complete human group')
    require(not args.practice_between or args.retry, 'practice transition requires a gated remote retry')
    return asyncio.run(run(args))


if __name__ == '__main__':
    raise SystemExit(main())
