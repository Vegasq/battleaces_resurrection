"""Opt-in native local practice -> TLS Custom Create/Leave -> local practice.

Uses in-memory test invites and ephemeral PKI, not real enrollment. Automates
native buttons/build/surrender/Continue; forced owned cleanup is not Quit proof.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
import traceback

from client_patch.transport import bridge, launcher
from server import admission, community_protocol as c, tls_transport as tls
from server.assets import verify_assets
from server.dedicated_server import Audit, DedicatedServer
from server.game_data import GameTemplate
from server.profiles import ProfileStore
from server.worker_client import _WindowsJob
from tests.test_admission import Store
from tests.test_tls_transport import generate_test_pki, remove_test_pki
from tools.run_secure_match import read_native_log
from tools.verify_custom_lobby import require, source_hashes as core_hashes, PASSED as CUSTOM_PASSED
from tools.verify_practice_ai import movement_evidence

ROOT = Path(__file__).resolve().parents[1]
PASSED = 'UNIFIED SMOKE local-practice -> authenticated-Custom -> local-practice complete; same PID and native deck storage'


def source_hashes():
    paths = [Path(__file__), ROOT / 'tools/verify_practice_ai.py', ROOT / 'tools/run_secure_match.py']
    paths += list((ROOT / 'client_patch/transport').glob('*.py'))
    return core_hashes() | {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def alternative_deck(template, deck):
    for left in range(8):
        for right in range(left + 1, 8):
            candidate = list(deck)
            candidate[left], candidate[right] = candidate[right], candidate[left]
            if candidate == deck: continue
            try: return list(template.validate_deck(candidate))
            except ValueError: pass
    raise AssertionError('no distinct valid server deck fixture')


def armies(log):
    return [json.loads(line.split('Practice army snapshot: ', 1)[1])
            for line in log.splitlines() if 'Practice army snapshot: ' in line]


async def run(args):
    require(os.name == 'nt' and 120 <= args.timeout <= 900, 'Windows and bounded timeout required')
    require(1200 <= args.frames <= 3600, 'frames must be1200..3600')
    game, assets, output = args.game.resolve(), args.assets.resolve(), args.output.resolve()
    require(output.is_relative_to(ROOT / 'local'), 'evidence must stay in ignored local/')
    launcher.verify_game(game, community=True, bridge_version=2, unified=True)
    verify_assets(assets)
    output.mkdir(parents=True, exist_ok=False)
    template = GameTemplate.load(assets / 'map-1v1.pb.gz', catalog_path=assets / 'unit-catalog.json', descriptors_path=assets / 'descriptors')
    pki_folder = output / 'ephemeral-pki'
    pki = generate_test_pki(pki_folder)
    credentials = Store()
    gate = admission.AdmissionController(credentials)
    profiles = ProfileStore(output / 'profiles', template)
    audit, events, created_decks, delayed = Audit(output), [], [], []
    process = job = writer = bridge_task = parent = child = None
    log, launch_tick, attempts, first_deck, saved_deck = '', None, 0, None, None
    report = dict(passed=False, utc=datetime.now(timezone.utc).isoformat(), scope=__doc__,
                  source_sha256_at_start=source_hashes())
    started = time.monotonic()

    def observe(event, **fields):
        events.append(dict(event=event, **fields)); audit(event, **fields)
        if event == 'custom_lobby_created':
            created_decks.append(profiles.load(credentials.player, []))

    async def unexpected_worker(_):
        raise AssertionError('practice/Create/Leave must not allocate a multiplayer worker')

    server = DedicatedServer(template, profiles, audit=observe, sim_factory=unexpected_worker,
        data_dir=output, lobby_timeout=300, tls_context=tls.load_server_context(pki['cert'], pki['key']), admission=gate)
    original_send = server.community.send

    def delayed_create(peer, kind, payload):
        if kind == c.ACK and len(payload) >= 5 and payload[4] == c.CREATE:
            delayed.append(asyncio.get_running_loop().call_later(.35, original_send, peer, kind, payload))
        else: original_send(peer, kind, payload)
    server.community.send = delayed_create

    try:
        port = (await server.start('127.0.0.1', 0))[1]
        context = tls.load_client_context(pki['ca'], 'localhost')

        async def resolve():
            nonlocal attempts
            attempts += 1
            current = read_native_log(game, process.pid, since_tick=launch_tick)
            if 'Practice returned: completed=1 mode=4 seat=-1 presenceRetained=0 standalone=1' not in current:
                raise bridge.RemoteUnavailable()
            require(saved_deck is not None, 'server profile fixture was not seeded before connection')
            return bridge.Remote('127.0.0.1', port, context, credentials.player, credentials.token)

        config = dict(game_directory=game, server_host='127.0.0.1', server_port=port,
                      display_name='Unified Config Player', room='community')
        options = argparse.Namespace(run_name='unified-probe', unified_experimental=True)
        parent, child = socket.socketpair(socket.AF_INET)
        parent.setblocking(False)
        reader, writer = await asyncio.open_connection(sock=parent)
        command = launcher.game_arguments(config, None, child.fileno(), options)
        command[command.index('-logFile') + 1] = str(output / 'game.log')
        command += ['-unified-smoke', '-practice-ai-smoke', '-practice-ai-smoke-matches=2',
                    f'-practice-ai-smoke-frames={args.frames}', '-practice-ai-deck-smoke',
                    '-community-create-smoke', '-lan-smoke', '-lan-audit']
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        startup.lpAttributeList = {'handle_list': [child.fileno()]}
        clock = ctypes.WinDLL('kernel32').GetTickCount64
        clock.restype = ctypes.c_ulonglong
        launch_tick = clock()
        child.set_inheritable(True)
        try:
            process = subprocess.Popen(command, cwd=game, startupinfo=startup, close_fds=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        finally: child.set_inheritable(False)
        job = _WindowsJob(process.pid)
        child.close()
        bridge_task = asyncio.create_task(bridge.Bridge(reader, writer, resolve, version=2).run())
        manifest = json.loads((game / '.battleaces-resurrection/patch-manifest.json').read_text())
        (output / 'patch-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        report.update(game_pid=process.pid, launch_tick=launch_tick, client_arguments=command,
                      helper_sha256=manifest['helper_sha256'])
        (output / 'process.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        deadline, previous = started + args.timeout, ''
        while True:
            require(process.poll() is None, 'owned game exited before lifecycle completion')
            require(not bridge_task.done(), 'private bridge ended before lifecycle completion')
            log = read_native_log(game, process.pid, since_tick=launch_tick)
            require(not any(marker in log for marker in ('Client lifecycle invariant failed:',
                'Local menu initialization failed:', 'Practice stopped in ', 'Offline loop stopped in ')),
                'native lifecycle failure; inspect retained log')
            snapshots = armies(log)
            if saved_deck is None and snapshots:
                first_deck = snapshots[0]['deck']['units']
                saved_deck = alternative_deck(template, first_deck)
                profiles.save(credentials.player, saved_deck)
            milestones = [line for line in log.splitlines() if any(marker in line for marker in
                ('Local menu ready:', 'optional connection unavailable', 'Practice requested:', 'Practice returned:',
                 'UNIFIED SMOKE ', 'Community presence installed:'))]
            if milestones and milestones[-1] != previous:
                previous = milestones[-1];print(previous, flush=True)
            if PASSED in log: break
            require(time.monotonic() < deadline, 'unified native lifecycle deadline reached')
            await asyncio.sleep(.2)
        await asyncio.sleep(.5)
        log = read_native_log(game, process.pid, since_tick=launch_tick)
        require(CUSTOM_PASSED in log, 'native deferred Custom cancellation/re-entry proof missing')
        require(attempts >= 2 and credentials.calls == 1, 'expected unavailable start then one authenticated Custom session')
        require(saved_deck != first_deck and len(created_decks) == 4 and all(deck == first_deck for deck in created_decks),
                'server welcome replaced the local deck or Custom began before accepted local deck')
        require(not server.rooms and not server.community.lobbies and not server.community.sessions,
                'local practice retained server room/presence')
        require(not any(row['event'] in ('match_created', 'worker_started') for row in events), 'unexpected multiplayer match/worker')
        starts = list(re.finditer(r'Practice requested: match=([0-9a-f]{32}) ', log))
        require(len(starts) == 2 and starts[0][1] != starts[1][1], 'expected two distinct local matches')
        evidence = []
        for index, start in enumerate(starts):
            segment = log[start.start():starts[index+1].start() if index+1 < len(starts) else len(log)]
            snapshot = armies(segment)
            require(len(snapshot) == 2, 'expected human and bot snapshots per local match')
            human = snapshot[0]
            require(human['players'][0]['playerHandleWithName']['playerName'] == config['display_name'],
                    'configured display name was not retained in native army identity')
            moved, ordered = movement_evidence(segment, set(snapshot[1]['deck']['units']))
            require(bool(moved & ordered), 'bot did not both receive autonomous orders and move a produced unit')
            resources = game / 'investigation/runtime' / f'lan-resources-{process.pid}-{start[1]}.tsv'
            with resources.open(encoding='utf-8') as stream:
                supply = max((int(row['current_supply']) for row in csv.DictReader(stream, delimiter='\t')
                              if row['viewer'] == '1' and row['army'] == '1'), default=0)
            require(supply > 0, 'bot did not produce native unit supply')
            evidence.append(dict(match=start[1], human_deck=human['deck']['units'], bot_max_supply=supply,
                                 moved_autonomous_units=sorted(moved & ordered)))
        require(evidence[0]['human_deck'] != evidence[1]['human_deck'], 'local deck edit did not reach second match')
        for marker in ('Practice native EndOfGameResponse delivered;', 'PRACTICE SMOKE native Continue',
                       'Client world acquired:', 'Client world released:'):
            require(log.count(marker) == 2, 'wrong native lifecycle count: ' + marker)
        report.update(passed=True, matches=evidence, remote_attempts=attempts, authentications=credentials.calls,
                      custom_lobbies=4, server_default_deck_was_distinct=True, local_deck_preserved=True,
                      configured_native_name=True, server_workers=0)
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
        raise
    finally:
        if child is not None: child.close()
        if process is not None:
            log = read_native_log(game, process.pid, since_tick=launch_tick)
            (output / f'native-{process.pid}.log').write_text(log, encoding='utf-8')
            if process.poll() is None: process.terminate()
            await asyncio.to_thread(process.wait, timeout=15)
            for match in set(re.findall(r'Practice requested: match=([0-9a-f]{32}) ', log)):
                for prefix in ('lan-audit', 'lan-resources'):
                    sample = game / 'investigation/runtime' / f'{prefix}-{process.pid}-{match}.tsv'
                    if sample.is_file(): shutil.copyfile(sample, output / sample.name)
        if job is not None: job.close()
        if bridge_task is not None:
            bridge_task.cancel();await asyncio.gather(bridge_task, return_exceptions=True)
        if writer is not None:
            writer.close()
            try: await asyncio.wait_for(writer.wait_closed(), 2)
            except (OSError, TimeoutError): writer.transport.abort()
        elif parent is not None: parent.close()
        for handle in delayed: handle.cancel()
        await server.close()
        remove_test_pki(pki_folder)
        report.update(elapsed_seconds=time.monotonic()-started,
            owned_process_reaped=process is None or process.poll() is not None,
            owned_process_exit=None if process is None else process.returncode,
            cleanup='forced owned test termination, not native Quit', source_sha256_at_finish=source_hashes())
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= report['source_files_unchanged'] and report['owned_process_reaped']
        (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        audit.close();print('Evidence: ' + str(output / 'verification.json'), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('game', 'assets', 'output'): parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--frames', type=int, default=3600,
                        help='maximum frames per match; Normal AI needs time to build before attacking')
    asyncio.run(run(parser.parse_args()))


if __name__ == '__main__': main()
