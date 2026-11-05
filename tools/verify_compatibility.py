"""Packaged RC TLS compatibility rejection with concurrent native play (201).

Authored HELLO fields only; not an old client UI or damaged asset-file test.
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
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'tools/verify_room_faults.py'
CASES = {
    'direct_version': 'unsupported game protocol; update client and server together',
    'direct_build': 'client original build mismatch',
    'direct_simulation': 'client simulation build mismatch',
    'community_version': 'unsupported game protocol; update client and server together',
    'community_build': 'client original build mismatch',
    'community_simulation': 'client simulation build mismatch',
    'community_wrapper': 'unsupported community protocol',
}


def require(value, message):
    if not value:
        raise AssertionError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    temporary = path.with_name(path.name + '.staging')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def helper():
    spec = importlib.util.spec_from_file_location('compatibility_helpers', HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hello(case, profile):
    from server import protocol as p, community_protocol as community
    require(case in CASES, 'unknown compatibility case')
    mode, field = case.split('_')
    kind = community.HELLO if mode == 'community' else p.HELLO
    body = bytearray(community.hello(profile, 'Compatibility', version=2) if mode == 'community'
                     else p.hello(0, profile, 'Compatibility', 'compatibility'))
    offset = 2 if mode == 'community' else 0
    if field == 'wrapper':
        struct.pack_into('<H', body, 0, 3)
    elif field == 'version':
        struct.pack_into('<H', body, offset, p.VERSION + 1)
    else:
        body[offset + (3 if field == 'build' else 35)] ^= 1
    return kind, bytes(body)


def check_journal(rows, failures, match, frames):
    errors = [row for row in rows if row['event'] == 'protocol_error']
    require([(r['connection'], r['reason']) for r in errors] ==
            [(r['connection'], CASES[r['case']]) for r in failures], 'rejection attribution differs')
    selected = [row for row in rows if row.get('match') == match]
    delivered = [row for row in selected if row['event'] == 'frame_queued']
    require([r['frame'] for r in delivered] == list(range(len(frames))) and
            [r['frame_payload_sha256'] for r in delivered] == [r['sha256'] for r in frames],
            'healthy frame journal differs')
    require(not any(r['event'] in ('match_aborted', 'simulation_error', 'match_completed') for r in selected),
            'healthy match stopped')


async def scenario(folder, assets, h):
    from server import protocol as p, dedicated_server as dedicated, admission, tls_transport as tls, rc_host
    from server.game_data import GameTemplate
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
        require(worker.request_timeout == 3 and worker.close_timeout == 2, 'production deadlines changed')
        return worker

    audit = HostAudit(folder / 'logs', max_bytes=8388608, backups=4, diagnostics=True)
    server = dedicated.DedicatedServer(template, ProfileStore(folder / 'profiles', template,
        catalog=CosmeticCatalog(assets)), sim_factory=factory, audit=audit, audit_state=True,
        tls_context=tls.load_server_context(cert, key), admission=admission.AdmissionController(None, rc_open=True))
    peers, frames, failures = [], [], []
    healthy_task = None
    stop = asyncio.Event()
    record = dict(passed=False)
    try:
        port = (await server.start('127.0.0.1', 0))[1]
        tokens = ['ba1_' + secrets.token_urlsafe(32) for _ in range(4)]
        healthy, match = await h.pair(port, 'healthy', tokens[:2], peers, server=server, custom=True)
        room = server.rooms[healthy[0].room_key]
        worker = room.sim
        original_peers = set(server.peers)
        profiles_before = {path.name: sha(path) for path in (folder / 'profiles').glob('*.json')}
        require(len(profiles_before) == 2 and len(workers) == 1, 'healthy baseline differs')

        async def pump():
            for frame in range(600):
                if stop.is_set() and frame >= 40:
                    return
                frames.append(await h.advance(healthy, frame))
            raise AssertionError('healthy frame budget exceeded')

        healthy_task = asyncio.create_task(pump())
        rejected_profile = None
        for case in CASES:
            # Respect the unmodified default one-token/second admission budget.
            await asyncio.sleep(1.1)
            reader, writer = await tls.open_verified_connection('127.0.0.1', port, tls.rc_client_context('127.0.0.1'))
            peer = h.Peer(reader, writer)
            peers.append(peer)
            profile = await admission.authenticate_client(reader, writer, tokens[2], rc_open=True)
            require(rejected_profile in (None, profile), 'rejected identity changed')
            rejected_profile = profile
            added = set(server.peers) - original_peers
            require(len(added) == 1, 'unexpected pending connection')
            connection = next(iter(added)).connection
            await peer.send(*hello(case, profile))
            require((await peer.receive(p.ERROR)).decode('utf-8') == CASES[case], 'wrong rejection')
            require(await asyncio.wait_for(reader.read(1), 3) == b'', 'rejected connection remains open')
            async with asyncio.timeout(3):
                while set(server.peers) != original_peers:
                    await asyncio.sleep(.01)
            require(profile not in server.community.sessions and len(server.rooms) == 1 and len(workers) == 1,
                    'incompatible hello allocated session, room or worker')
            require({path.name: sha(path) for path in (folder / 'profiles').glob('*.json')} == profiles_before,
                    'incompatible hello wrote profiles')
            require([kind for kind, _ in peer.observed] == [p.ERROR], 'incompatible client received admission output')
            failures.append(dict(case=case, connection=connection, reason=CASES[case], eof=True,
                                 no_allocation=True, profiles_preserved=True))
            await peer.close()

        await asyncio.sleep(1.1)
        repaired, repaired_match = await h.pair(port, 'compatible', tokens[2:], peers, server=server, custom=True)
        require(repaired[0].profile == rejected_profile, 'compatible retry changed identity')
        for frame in range(10):
            await h.advance(repaired, frame)
        after = {path.name: sha(path) for path in (folder / 'profiles').glob('*.json')}
        require(len(after) == 4 and all(after.get(name) == value for name, value in profiles_before.items()),
                'compatible retry altered unrelated profiles')
        stop.set()
        await healthy_task
        healthy_task = None
        require(server.rooms.get(healthy[0].room_key) is room and room.sim is worker and worker.process.poll() is None,
                'healthy room or worker changed')
        gaps = [(b['at'] - a['at']) * 1000 for a, b in zip(frames, frames[1:])]
        require(len(frames) >= 40 and max(gaps) < 1000, 'healthy match stalled')
        rows = [json.loads(line) for line in (folder / 'logs/events.jsonl').read_text().splitlines()]
        check_journal(rows, failures, match, frames)
        record.update(passed=True, cases=failures, healthy_frames=frames, healthy_match=match,
            max_healthy_gap_ms=max(gaps), healthy_same_room_and_worker=True,
            profile_sha256_before=profiles_before, profiles_preserved=True,
            compatible_retry_same_identity=True, compatible_match=repaired_match, compatible_frames=10)
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
    from server import worker_client, dedicated_server, protocol, community_protocol
    request = json.loads(request_path.read_bytes())
    out, package, assets = request_path.parent, Path(request['package']), Path(request['assets'])
    report = dict(passed=False, scope=__doc__)
    try:
        require(sha(__file__) == request['driver_sha256'] and sha(HELPER) == request['helper_sha256'], 'driver changed')
        verify(package, 'server')
        verify_assets(assets)
        modules = (worker_client, dedicated_server, protocol, community_protocol)
        for module in modules:
            require(Path(module.__file__).resolve() == package / 'program/app/server' / (module.__name__.split('.')[-1] + '.py'),
                    'bundled imports differ')
        report['module_sha256'] = {str(Path(m.__file__).resolve()): sha(m.__file__) for m in modules}
        require((out / 'job-ready').exists(), 'owned job gate absent')
        report['case'] = asyncio.run(scenario(out / 'compatibility', assets, helper()))
        verify_assets(assets)
        report['passed'] = True
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        report['source_unchanged'] = sha(__file__) == request['driver_sha256'] and sha(HELPER) == request['helper_sha256']
        report['passed'] &= report['source_unchanged']
        save(out / 'child-report.json', report)
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
    from tools.verify_loading_recovery import run
    raise SystemExit(run(args.package, args.assets, args.output, driver=__file__, scope=__doc__))
