"""Packaged RC/native default120-second loading expiry and late-packet recovery.

Owned loopback Custom1v1 peers only; no Unity async-load cancellation/UI claim.
The healthy concurrent match retains ordinary50ms steps and production deadlines.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import struct
import subprocess
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'tools/verify_room_faults.py'


def require(value, message):
    if not value:
        raise AssertionError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    temp = path.with_name(path.name + '.staging')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)


def helper():
    spec = importlib.util.spec_from_file_location('loading_room_helpers', HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_journal(rows, match, healthy_match, frames):
    selected = [r for r in rows if r.get('match') == match]
    require(not any(r['event'] in ('match_started', 'frame_queued', 'simulation_error', 'native_game_over')
                    for r in selected), 'unloaded match started, stepped, completed or failed simulation')
    loaded = [r for r in selected if r['event'] == 'world_loaded']
    require(len(loaded) == 1 and loaded[0]['slot'] == 0, 'late loading acknowledgement was accepted')
    aborts = [r for r in selected if r['event'] == 'match_aborted']
    require(len(aborts) == 1 and aborts[0]['result'] is None and aborts[0]['next_frame'] == 0
            and aborts[0]['reason'] == 'world loading timeout', 'loading abort differs')
    require(not any(r['event'] == 'protocol_error' for r in rows), 'late in-flight packets disconnected a player')
    delivered = [r for r in rows if r.get('match') == healthy_match and r['event'] == 'frame_queued']
    require([r['frame'] for r in delivered] == list(range(len(frames))) and
            [r['frame_payload_sha256'] for r in delivered] == [r['sha256'] for r in frames],
            'healthy host/client journal differs')


async def scenario(folder, assets, h):
    from server import protocol as p, community_protocol as community, dedicated_server, admission, tls_transport as tls, rc_host
    from server.game_data import GameTemplate, encode_player_input
    from server.cosmetics import CosmeticCatalog
    from server.profiles import ProfileStore
    from server.worker_client import SimulationWorker
    from server.host_audit import HostAudit

    folder.mkdir()
    work = folder / 'workers'
    work.mkdir()
    cert, key = folder / 'server.pem', folder / 'server.key'
    certificate, private_key = rc_host.generate_certificate()
    cert.write_bytes(certificate)
    key.write_bytes(private_key)
    template = GameTemplate.load(assets / 'map-1v1.pb.gz', catalog_path=assets / 'unit-catalog.json',
                                 descriptors_path=assets / 'descriptors')
    workers = []

    async def factory(data, *, ai=None):
        worker = await SimulationWorker.create(data, assets / 'Simulation.dll', working_directory=work, ai=ai)
        workers.append(worker)
        require(worker.dll_sha256 == p.SIM_SHA and worker.game_data_sha256 == hashlib.sha256(data).hexdigest()
                and not worker._test_backend, 'real native inputs differ')
        require(worker.request_timeout == 3 and worker.close_timeout == 2, 'worker deadlines changed')
        return worker

    audit = HostAudit(folder / 'logs', max_bytes=8388608, backups=4, diagnostics=True)
    server = dedicated_server.DedicatedServer(template, ProfileStore(folder / 'profiles', template,
        catalog=CosmeticCatalog(assets)), sim_factory=factory, audit=audit, audit_state=True,
        tls_context=tls.load_server_context(cert, key), admission=admission.AdmissionController(None, rc_open=True))
    peers, frames = [], []
    healthy_task = None
    stop = asyncio.Event()
    record = dict(passed=False)
    try:
        require(server.loading_timeout == 120 and server.input_timeout == 10, 'server deadlines changed')
        port = (await server.start('127.0.0.1', 0))[1]
        tokens = [['ba1_' + secrets.token_urlsafe(32) for _ in range(2)] for _ in range(2)]
        (victims, match), (healthy, healthy_match) = await asyncio.gather(
            h.pair(port, 'loading', tokens[0], peers, server=server, custom=True, loaded=False),
            h.pair(port, 'healthy', tokens[1], peers, server=server, custom=True))
        victim_key, healthy_key = victims[0].room_key, healthy[0].room_key
        victim_room, healthy_room = server.rooms[victim_key], server.rooms[healthy_key]
        victim, healthy_worker = victim_room.sim, healthy_room.sim
        server_peers = [server.community.sessions[peer.profile].peer for peer in victims]
        profiles_before = {path.name: sha(path) for path in (folder / 'profiles').glob('*.json')}
        require(len(profiles_before) == 4, 'four saved profiles required')
        bootstrap = next(body for kind, body in victims[0].observed if kind == p.BOOTSTRAP)
        bootstrap_hash = hashlib.sha256(bootstrap).digest()
        require(victim_room.state == 'loading' and victim.frame == -1, 'victim already started')
        loading_at = victim_room.last_progress

        async def pump():
            for frame in range(3000):
                if stop.is_set():
                    return
                frames.append(await h.advance(healthy, frame))
            raise AssertionError('healthy frame budget exceeded')

        healthy_task = asyncio.create_task(pump())
        await victims[0].send(p.LOADED, bootstrap_hash)
        # Deliberately withhold slot1's LOADED. Do not modify server clocks/deadlines.
        async with asyncio.timeout(125):
            while victim_room.state != 'closed':
                if healthy_task.done():
                    await healthy_task
                    raise AssertionError('healthy room ended before loading timeout')
                require(victim_room.state == 'loading' and victim.frame == -1, 'unloaded world progressed')
                await asyncio.sleep(.02)
        elapsed = time.perf_counter() - loading_at
        require(120 <= elapsed < 125 and victim_room.loaded == {0}, 'default loading deadline not evidenced')
        for peer in victims:
            r = community.Reader(await peer.receive(community.ABORTED))
            require((r.text(), r.text()) == (match, 'world loading timeout'), 'explicit loading abort differs')
            r.end()
        async with asyncio.timeout(8):
            while victim_key in server.rooms or victim.process.poll() is None or server.worker_cleanup:
                await asyncio.sleep(.01)
        require(victim.process.returncode == 0 and victim.frame == -1, 'unloaded worker failed cleanup')
        # These were valid for the old world, but arrive after its abort. REFRESH
        # ACK on each same TCP stream is a barrier proving earlier packets handled.
        for peer in victims:
            await peer.send(p.LOADED, bootstrap_hash)
            await peer.send(p.INPUT, struct.pack('<I', 0) + encode_player_input(peer.identity, [peer.join]))
            await peer.command(community.REFRESH)
        require(victim_room.loaded == {0} and not victim_room.pending, 'late packet mutated closed world')
        for peer in victims:
            require(not any(kind in (p.START, p.FRAME, p.MATCH_END, p.ERROR) for kind, _ in peer.observed),
                    'unloaded match delivered start/frame/result/error')
        for peer in victims:
            await peer.command(community.RETURN, p.encode_string(match))
        lobby = server.community.lobbies[victims[0].lobby_id]
        require(lobby.phase == community.OPEN and len(lobby.members) == 2, 'lobby not reusable')
        replacement, replacement_match = await h.pair(port, 'loading', tokens[0], peers, server=server,
                                                       custom=True, existing=victims)
        require(replacement_match != match and
                all(server.community.sessions[peer.profile].peer is original for peer, original in zip(victims, server_peers)),
                'replacement identity or original connections changed')
        for frame in range(10):
            await h.advance(replacement, frame)
        require({path.name: sha(path) for path in (folder / 'profiles').glob('*.json')} == profiles_before,
                'loading abort/retry changed profiles')
        until = len(frames) + 10
        async with asyncio.timeout(3):
            while len(frames) < until:
                await asyncio.sleep(.01)
        stop.set()
        await healthy_task
        healthy_task = None
        require(server.rooms.get(healthy_key) is healthy_room and healthy_room.sim is healthy_worker and
                healthy_worker.process.poll() is None, 'unrelated room or worker replaced')
        gaps = [(b['at'] - a['at']) * 1000 for a, b in zip(frames, frames[1:])]
        require(len(frames) >= 2200 and max(gaps) < 1000, 'healthy room failed sustained progress')
        rows = [json.loads(line) for line in (folder / 'logs/events.jsonl').read_text().splitlines()]
        check_journal(rows, match, healthy_match, frames)
        record.update(passed=True, loading_timeout=server.loading_timeout, loading_elapsed_seconds=elapsed,
            victim_pid=victim.pid, victim_frames=0, healthy_pid=healthy_worker.pid,
            healthy_frames=frames, max_healthy_gap_ms=max(gaps), replacement_match=replacement_match,
            replacement_frames=10, profile_sha256=profiles_before, profiles_preserved=True,
            both_connections_reused=True, late_packets_ignored=True, unknown_result_abort=True,
            healthy_same_room_and_worker=True)
    except BaseException as error:
        record.update(error=repr(error), traceback=traceback.format_exc())
        raise
    finally:
        stop.set()
        if healthy_task:
            healthy_task.cancel()
            await asyncio.gather(healthy_task, return_exceptions=True)
        for peer in peers:
            await peer.close()
        try:
            await server.close()
        finally:
            await asyncio.gather(*(worker.close() for worker in workers))
            audit.close()
        record['worker_exits'] = [dict(pid=w.pid, exit_code=w.process.poll()) for w in workers]
        record['passed'] &= all(row['exit_code'] == 0 for row in record['worker_exits'])
        save(folder / 'result.json', record)
    require(record['passed'], 'scenario failed')
    return record


def child(request_path):
    from tools.package_integrity import verify
    from server.assets import verify_assets
    from server import worker_client, dedicated_server
    request = json.loads(request_path.read_bytes())
    out, package, assets = request_path.parent, Path(request['package']), Path(request['assets'])
    report = dict(passed=False, scope=__doc__)
    try:
        require(sha(__file__) == request['driver_sha256'] and sha(HELPER) == request['helper_sha256'], 'driver changed')
        verify(package, 'server')
        verify_assets(assets)
        for module in (worker_client, dedicated_server):
            require(Path(module.__file__).resolve() == package / 'program/app/server' / (module.__name__.split('.')[-1] + '.py'),
                    'bundled imports differ')
        report['module_sha256'] = {str(Path(m.__file__).resolve()): sha(m.__file__) for m in (worker_client, dedicated_server)}
        require((out / 'job-ready').exists(), 'owned job gate absent')
        report['case'] = asyncio.run(scenario(out / 'loading-timeout', assets, helper()))
        verify_assets(assets)
        report['passed'] = True
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        report['source_unchanged'] = sha(__file__) == request['driver_sha256'] and sha(HELPER) == request['helper_sha256']
        report['passed'] &= report['source_unchanged']
        save(out / 'child-report.json', report)
    return 0 if report['passed'] else 1


def run(package, assets, out, *, driver=None, scope=None, options=None, owned_root=None):
    from tools.owned_suspended_launch import SuspendedChild, job_accounting, diagnostic_root
    from tools.package_integrity import verify
    if owned_root is None:
        package, assets, out = helper().owned_paths(package, assets, out)
    else:
        owned_root = diagnostic_root(owned_root)
        package, assets, out = (Path(p).resolve() for p in (package, assets, out))
        require(all(p != owned_root and p.is_relative_to(owned_root) for p in (package, out)), 'package/output require the selected owned root')
        require(any(assets != r and assets.is_relative_to(r) for r in (owned_root, ROOT/'local')), 'owned read-only assets required')
        require(not out.is_relative_to(package) and not out.is_relative_to(assets), 'output must be separate')
    driver = Path(driver or __file__).resolve()
    out.mkdir(exist_ok=False)
    owner = None
    started = time.monotonic()
    report = dict(passed=False, scope=scope or __doc__, forced_harness_cleanup=False)
    try:
        verify(package, 'server')
        report.update(package_manifest_sha256=sha(package / 'package-manifest.json'),
                      asset_manifest_sha256=sha(assets / 'asset-manifest.json'),
                      driver_sha256=sha(driver), helper_sha256=sha(HELPER), harness_sha256=sha(__file__))
        save(out / 'request.json', dict(package=str(package), assets=str(assets),
             driver_sha256=report['driver_sha256'], helper_sha256=report['helper_sha256'], options=options or {}))
        owner = SuspendedChild.create([str(package / 'program/runtime/python.exe'), '-I', '-B',
            str(driver), '--child-request', str(out / 'request.json')],
            cwd=out, creationflags=subprocess.CREATE_NO_WINDOW, owned_root=owned_root)
        (out / 'job-ready').write_bytes(b'owned job attached\n')
        owner.resume()
        deadline = time.monotonic() + 160
        while owner.poll() is None:
            require(time.monotonic() < deadline, 'owned controller deadline')
            time.sleep(.02)
        report['exit_code'] = owner.returncode
        report['child'] = json.loads((out / 'child-report.json').read_bytes())
        report['job_final'] = job_accounting(owner.job)
        deadline = time.monotonic() + 5
        while report['job_final']['active_processes'] and time.monotonic() < deadline:
            time.sleep(.02)
            report['job_final'] = job_accounting(owner.job)
        require(report['job_final']['active_processes'] == 0 and report['job_final']['total_terminated_processes'] == 0,
                'owned job required termination or remains active')
        verify(package, 'server')
        require(sha(assets / 'asset-manifest.json') == report['asset_manifest_sha256'] and
                sha(driver) == report['driver_sha256'] and sha(HELPER) == report['helper_sha256'] and
                sha(__file__) == report['harness_sha256'], 'inputs changed')
        report['passed'] = report['exit_code'] == 0 and report['child']['passed'] is True
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        if owner:
            owner.close()
            report['launch'] = owner.receipt
            report['forced_harness_cleanup'] = owner.receipt['forced_cleanup']
        report['passed'] &= not report['forced_harness_cleanup']
        report['elapsed_seconds'] = time.monotonic() - started
        save(out / 'verification.json', report)
        print(json.dumps({k: report[k] for k in ('passed', 'exit_code', 'forced_harness_cleanup', 'elapsed_seconds', 'error') if k in report}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child-request', type=Path, help=argparse.SUPPRESS)
    for name in ('package', 'assets', 'output'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.child_request:
        raise SystemExit(child(args.child_request))
    require(all((args.package, args.assets, args.output)), 'package/assets/output required')
    raise SystemExit(run(args.package, args.assets, args.output))
