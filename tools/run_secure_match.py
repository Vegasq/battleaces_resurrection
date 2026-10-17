"""Opt-in two-game TLS/rematch qualification with ephemeral test PKI/in-memory invites.

This is NOT a credential-store/ACL deployment test. No production invite is read,
printed, persisted or passed to either game. The supplied game must already have
the secure helper installed. Runtime evidence remains under ignored local/.
"""
from __future__ import annotations
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import time
from unittest import mock

from client_patch.transport import launcher
from client_patch.transport.bridge import Remote
from server.admission import AdmissionController
from server.assets import verify_assets
from server.credentials import AuthenticationError
from server.dedicated_server import Audit, DedicatedServer
from server.game_data import GameTemplate
from server.profiles import ProfileStore
from server import tls_transport as tls
from server.worker_client import SimulationWorker
from server.verify_dedicated_run import verify
from tests.test_tls_transport import generate_test_pki, remove_test_pki

ROOT = Path(__file__).resolve().parents[1]


async def run(args):
    if os.name != 'nt': raise ValueError('Windows game runtime required')
    if not 60 <= args.duration <= 600: raise ValueError('duration must be60..600 seconds')
    if not __import__('re').fullmatch('[A-Za-z0-9_-]{1,48}', args.run_name): raise ValueError('invalid run name')
    game, assets = args.game.resolve(), args.assets.resolve()
    launcher.verify_game(game)
    verify_assets(assets)
    destination = ROOT / 'local/matches' / args.run_name
    destination.mkdir(parents=True, exist_ok=False)
    pki = generate_test_pki(destination / 'ephemeral-test-pki')
    audit = Audit(destination)
    processes, tasks, records, completions = [], [], [], []
    players = [('p_' + secrets.token_hex(16), 'ba1_' + secrets.token_urlsafe(32)) for _ in range(2)]
    class Store:
        def authenticate(self, token):
            for player, expected in players:
                if secrets.compare_digest(token, expected): return player
            raise AuthenticationError()
    class Gate(AdmissionController):
        async def authenticate(self, reader, writer):
            player = await super().authenticate(reader, writer)
            channel = writer.get_extra_info('ssl_object')
            row = dict(player=player, tls=channel.version(), cipher=channel.cipher()[0])
            records.append(row)
            audit('qualification_tls_authenticated', **row)
            return player
    def observe(event, **data):
        audit(event, **data)
        if event == 'match_completed': completions.append(data['match'])
    template = GameTemplate.load(assets / 'map-1v1.pb.gz', catalog_path=assets / 'unit-catalog.json',
                                 descriptors_path=assets / 'descriptors')
    coordinator = DedicatedServer(template, ProfileStore(destination / 'profiles', template),
        audit=observe, data_dir=destination, audit_state=True,
        sim_factory=lambda data: SimulationWorker.create(data, assets / 'Simulation.dll'),
        tls_context=tls.load_server_context(pki['cert'], pki['key']), admission=Gate(Store()))
    manifest = dict(RunName=args.run_name, Started=datetime.now(timezone.utc).isoformat(), ServerPid=os.getpid(),
                    GamePids=[], AutoReady=True, Smoke=True, DeckSmoke=True, SurrenderSmoke=True,
                    RematchSmoke=True, TelemetryAudit=True, Transport='verified-TLS-private-inherited-stream',
                    CredentialStorage='test-only-in-memory', GameDirectory=str(game))
    manifest_path = destination / 'processes.json'
    original_spawn = launcher.spawn_game
    def record_spawn(*positional, **keywords):
        process = original_spawn(*positional, **keywords)
        processes.append(process)
        manifest['GamePids'].append(process.pid)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        return process
    try:
        address = await coordinator.start('127.0.0.1', 0)
        context = tls.load_client_context(pki['ca'], 'localhost')
        shutil.copyfile(game / '.battleaces-resurrection/patch-manifest.json', destination / 'patch-manifest.json')
        (destination / 'transport-test.json').write_text(json.dumps(dict(ca_sha256=hashlib.sha256(pki['ca'].read_bytes()).hexdigest(),
            port=address[1], note='Ephemeral local test trust; not production credential storage'), indent=2), encoding='utf-8')
        options = argparse.Namespace(run_name=args.run_name, auto_ready=True, smoke=True, deck_smoke=True,
                                     surrender_smoke=True, rematch_smoke=True, telemetry_audit=True, audit=True)
        with mock.patch.object(launcher, 'spawn_game', record_spawn):
            for index, (player, token) in enumerate(players):
                config = dict(game_directory=game, server_host='127.0.0.1', server_port=address[1],
                              display_name='TLS Player ' + str(index + 1), room='tls-rematch')
                tasks.append(asyncio.create_task(launcher.launch(config, Remote('127.0.0.1', address[1], context, player, token), options)))
            deadline = time.monotonic() + args.duration
            final_result_at = None
            while time.monotonic() < deadline and not any(task.done() for task in tasks):
                if len(completions) >= 2:
                    if final_result_at is None: final_result_at = time.monotonic()
                    if time.monotonic() - final_result_at >= 15: break
                await asyncio.sleep(.5)
    finally:
        # These exact Popen handles own only this harness's two test clients.
        # The user's separate visible test clients are never selected by name/PID.
        for process in processes:
            if process.poll() is None: process.terminate()
        await asyncio.gather(*(asyncio.to_thread(process.wait, timeout=10) for process in processes), return_exceptions=True)
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await coordinator.close()
        audit.close()
        remove_test_pki(destination / 'ephemeral-test-pki')
    results = []
    for match in completions:
        result = verify(destination, game / 'investigation/runtime', manifest_path, match)
        (destination / ('verification-' + match + '.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
        results.append(dict(match=match, status=result['status'], frames=result['server_frame_count'],
            mismatches=result['mismatch_count'], errors=result['server_errors'],
            clients=[dict(pid=row['pid'],slot=row['slot'],samples=row['common_snapshot_samples'],
                          receipts=len(row['logged_received_frames']),sufficient=row['evidence_sufficient']) for row in result['clients']]))
    summary = dict(matches=results, authenticated_sessions=records,
                   success=len(results) >= 2 and len(records) >= 4 and all(row['status']=='matching_sampled_server_and_clients' for row in results))
    (destination / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary), flush=True)
    return not summary['success']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--run-name', required=True)
    parser.add_argument('--duration', type=int, default=150)
    raise SystemExit(asyncio.run(run(parser.parse_args())))
