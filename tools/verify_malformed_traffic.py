"""Owned packaged RC TLS/native invalid-input isolation (192/202).

Active-input and loading-acknowledgement faults, a concurrent Custom match, and
same-profile replacement. No UI, Internet, SCM, fuzzing or general DoS claim.
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
CASES = {
    'oversized_header': 'packet size limit',
    'truncated_input': 'truncated varint',
    'foreign_identity': 'player identity does not match assigned slot',
    'bootstrap_mismatch': 'bootstrap acknowledgement mismatch',
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
    spec = importlib.util.spec_from_file_location('malformed_room_helpers', HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def packet(kind, other_identity):
    from server import protocol as p
    from server.game_data import encode_player_input
    if kind == 'bootstrap_mismatch':
        require(len(other_identity) == 32, 'bootstrap digest must have 32 bytes')
        return p.encode(p.LOADED, bytes([other_identity[0] ^ 1]) + other_identity[1:])
    if kind == 'oversized_header':
        return struct.pack('<I', p.MAX_BODY + 1)  # Deliberately no body.
    if kind == 'truncated_input':
        body = b'\x0a\x80'  # Player-ID length varint ends prematurely.
    elif kind == 'foreign_identity':
        body = encode_player_input(other_identity, [])
    else:
        raise ValueError('unknown malformed-traffic case')
    return p.encode(p.INPUT, struct.pack('<I', 10) + body)


def check_journal(rows, match, healthy_match, frames, reason, connection, *, frames_before=10):
    selected = [r for r in rows if r.get('match') == match]
    require([r['frame'] for r in selected if r['event'] == 'frame_queued'] == list(range(frames_before)),
            'failed frame published or prior frames missing')
    aborts = [r for r in selected if r['event'] == 'match_aborted']
    require(len(aborts) == 1 and aborts[0]['result'] is None and aborts[0]['next_frame'] == frames_before,
            'victim audit invented a result or wrong boundary')
    require(not any(r['event'] in ('simulation_error', 'match_completed') for r in selected),
            'malformed input reached simulation or completed match')
    if frames_before == 0:
        require(not any(r['event'] in ('match_started', 'native_game_over') for r in selected),
                'unloaded match started or completed')
        require([r['slot'] for r in selected if r['event'] == 'world_loaded'] == [0],
                'wrong loading acknowledgement accepted')
        require(aborts[0]['reason'] == 'player disconnected', 'loading abort reason differs')
    errors = [r for r in rows if r['event'] == 'protocol_error']
    require(len(errors) == 1 and errors[0]['reason'] == reason and errors[0]['connection'] == connection,
            'protocol rejection attribution differs')
    delivered = [r for r in rows if r.get('match') == healthy_match and r['event'] == 'frame_queued']
    require([r['frame'] for r in delivered] == list(range(len(frames))) and
            [r['frame_payload_sha256'] for r in delivered] == [r['sha256'] for r in frames],
            'healthy host/client frame journal differs')


async def scenario(folder, assets, kind, h):
    from server import protocol as p, dedicated_server as dedicated, admission, tls_transport as tls, rc_host
    from server import community_protocol as community
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
    peers, frames = [], []
    healthy_task = None
    stop = asyncio.Event()
    record = dict(kind=kind, passed=False)
    try:
        loading = kind == 'bootstrap_mismatch'
        frames_before = 0 if loading else 10
        port = (await server.start('127.0.0.1', 0))[1]
        tokens = [['ba1_' + secrets.token_urlsafe(32) for _ in range(2)] for _ in range(2)]
        (victims, match), (healthy, healthy_match) = await asyncio.gather(*(
            h.pair(port, name, token, peers, server=server, custom=True, loaded=not (loading and name == 'victim'))
            for name, token in zip(('victim', 'healthy'), tokens)))
        survivor, bad = victims
        victim_key, healthy_key = survivor.room_key, healthy[0].room_key
        victim = server.rooms[victim_key].sim
        room = server.rooms[healthy_key]
        healthy_worker = room.sim
        server_survivor = server.community.sessions[survivor.profile].peer
        bad_session = server.community.sessions[bad.profile]
        saved_deck, saved_cosmetics = list(bad_session.deck), bad_session.cosmetics
        bad_connection = bad_session.peer.connection
        profiles_before = {path.name: sha(path) for path in (folder / 'profiles').glob('*.json')}
        require(len(profiles_before) == 4, 'four persisted profiles required')

        async def pump():
            for frame in range(240):
                if stop.is_set() and frame >= 40:
                    return
                frames.append(await h.advance(healthy, frame))
            raise AssertionError('healthy frame budget exceeded')

        healthy_task = asyncio.create_task(pump())
        for frame in range(frames_before):
            await h.advance(victims, frame)
        require(victim.frame == frames_before - 1, 'injection frame boundary differs')
        fault_value = survivor.identity
        if loading:
            bootstrap = next(body for kind, body in survivor.observed if kind == p.BOOTSTRAP)
            fault_value = hashlib.sha256(bootstrap).digest()
            await survivor.send(p.LOADED, fault_value)
            await survivor.command(community.REFRESH)  # Same-stream handling barrier.
            require(server.rooms[victim_key].state == 'loading' and server.rooms[victim_key].loaded == {0},
                    'valid survivor acknowledgement was not retained')
        fault_at = time.perf_counter()
        bad.writer.write(packet(kind, fault_value))
        await bad.writer.drain()
        error, aborted = await asyncio.gather(bad.receive(p.ERROR), survivor.receive(community.ABORTED))
        require(error.decode('utf-8') == CASES[kind], 'wrong client rejection')
        reader = community.Reader(aborted)
        require((reader.text(), reader.text()) == (match, 'player disconnected'), 'wrong survivor abort')
        reader.end()
        require(await asyncio.wait_for(bad.reader.read(1), 3) == b'', 'rejected connection remains open')
        async with asyncio.timeout(8):
            while victim_key in server.rooms or victim.process.poll() is None or server.worker_cleanup:
                await asyncio.sleep(.01)
        require(victim.process.returncode == 0 and victim.frame == frames_before - 1, 'victim cleanup or invalid native step')
        require(bad.profile not in server.community.sessions, 'bad session retained')
        for peer in victims:
            require(not any(k == p.MATCH_END or (loading and k == p.START) or
                            (k == p.FRAME and struct.unpack_from('<I', body)[0] >= frames_before)
                            for k, body in peer.observed), 'invalid frame or winner delivered')
        await survivor.command(community.RETURN, p.encode_string(match))
        lobby = server.community.lobbies[survivor.lobby_id]
        require(lobby.phase == community.OPEN and list(lobby.members) == [survivor.profile], 'survivor lobby unusable')

        # Reconnect only the offender. HELLO must load its saved choices without SET_LOADOUT.
        reader, writer = await tls.open_verified_connection('127.0.0.1', port, tls.rc_client_context('127.0.0.1'))
        returning = h.Peer(reader, writer)
        peers.append(returning)
        returning.profile = await admission.authenticate_client(reader, writer, tokens[0][1], rc_open=True)
        require(returning.profile == bad.profile, 'reconnect changed identity')
        await returning.send(community.HELLO, community.hello(returning.profile, 'Fault Player 1', version=2))
        welcome = community.Reader(await returning.receive(community.WELCOME))
        require((welcome.number('H'), welcome.number('H'), welcome.key()) == (2, p.VERSION, bad.profile),
                'reconnected community identity differs')
        require(welcome.deck() == saved_deck, 'reconnected deck differs')
        welcome.end()
        require(server.community.sessions[bad.profile].cosmetics == saved_cosmetics, 'reconnected cosmetics differ')
        invitation = await survivor.command(community.INVITE, p.encode_string(returning.profile))
        require(await returning.command(community.REPLY, p.encode_string(invitation) + b'\x01') == lobby.id,
                'replacement invitation failed')
        returning.lobby_id, returning.room_key = lobby.id, survivor.room_key
        replacement, replacement_match = await h.pair(port, 'victim', tokens[0], peers, server=server,
                                                       custom=True, existing=[survivor, returning])
        require(replacement_match != match and server.community.sessions[survivor.profile].peer is server_survivor,
                'replacement identity or survivor connection changed')
        for frame in range(10):
            await h.advance(replacement, frame)
        require({path.name: sha(path) for path in (folder / 'profiles').glob('*.json')} == profiles_before,
                'malformed traffic or retry changed profiles')
        until = len(frames) + 10
        async with asyncio.timeout(3):
            while len(frames) < until:
                await asyncio.sleep(.01)
        stop.set()
        await healthy_task
        healthy_task = None
        require(server.rooms.get(healthy_key) is room and room.sim is healthy_worker and
                healthy_worker.process.poll() is None, 'healthy room or worker changed')
        gaps = [(b['at'] - a['at']) * 1000 for a, b in zip(frames, frames[1:])]
        require(len(frames) >= 40 and max(gaps) < 1000, 'healthy progression stalled')
        rows = [json.loads(line) for line in (folder / 'logs/events.jsonl').read_text().splitlines()]
        check_journal(rows, match, healthy_match, frames, CASES[kind], bad_connection, frames_before=frames_before)
        record.update(passed=True, rejection=CASES[kind], victim_frames=frames_before, victim_pid=victim.pid,
            victim_match=match, healthy_match=healthy_match, bad_connection=bad_connection,
            healthy_pid=healthy_worker.pid, healthy_frames=frames, max_healthy_gap_ms=max(gaps),
            fault_at=fault_at, replacement_match=replacement_match, replacement_frames=10,
            profile_sha256=profiles_before, profiles_preserved=True, saved_choices_reloaded=True,
            survivor_connection_reused=True, failed_frame_not_published=True, unknown_result_abort=True,
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
        record['worker_exits'] = [dict(pid=worker.pid, exit_code=worker.process.poll()) for worker in workers]
        record['clean_worker_exits'] = all(row['exit_code'] == 0 for row in record['worker_exits'])
        record['passed'] &= record['clean_worker_exits']
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
        deadline = time.monotonic() + 20
        while not (out / 'job-ready').exists():
            require(time.monotonic() < deadline, 'owned job gate absent')
            time.sleep(.02)
        h = helper()
        async def execute():
            return [await scenario(out / kind, assets, kind, h) for kind in request['cases']]
        report['cases'] = asyncio.run(execute())
        verify_assets(assets)
        report['passed'] = True
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        report['source_unchanged'] = sha(__file__) == request['driver_sha256'] and sha(HELPER) == request['helper_sha256']
        report['passed'] &= report['source_unchanged']
        save(out / 'child-report.json', report)
    return 0 if report['passed'] else 1


def run(package, assets, out, *, cases=None):
    from tools.owned_suspended_launch import SuspendedChild, job_accounting
    from tools.package_integrity import verify
    cases = list(CASES) if cases is None else list(cases)
    require(cases and len(set(cases)) == len(cases) and all(case in CASES for case in cases), 'invalid case selection')
    package, assets, out = helper().owned_paths(package, assets, out)
    out.mkdir(exist_ok=False)
    owner = None
    started = time.monotonic()
    report = dict(passed=False, scope=__doc__, forced_harness_cleanup=False)
    try:
        verify(package, 'server')
        report.update(package_manifest_sha256=sha(package / 'package-manifest.json'),
                      asset_manifest_sha256=sha(assets / 'asset-manifest.json'),
                      driver_sha256=sha(__file__), helper_sha256=sha(HELPER))
        save(out / 'request.json', dict(package=str(package), assets=str(assets), cases=cases,
             driver_sha256=report['driver_sha256'], helper_sha256=report['helper_sha256']))
        owner = SuspendedChild.create([str(package / 'program/runtime/python.exe'), '-I', '-B',
            str(Path(__file__).resolve()), '--child-request', str(out / 'request.json')],
            cwd=out, creationflags=subprocess.CREATE_NO_WINDOW)
        (out / 'job-ready').write_bytes(b'owned job attached\n')
        owner.resume()
        deadline = time.monotonic() + 90
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
                sha(__file__) == report['driver_sha256'] and sha(HELPER) == report['helper_sha256'], 'inputs changed')
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
    parser.add_argument('--case', choices=CASES, action='append', help='Run only these named cases; default: all')
    for name in ('package', 'assets', 'output'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.child_request:
        raise SystemExit(child(args.child_request))
    require(all((args.package, args.assets, args.output)), 'package/assets/output required')
    raise SystemExit(run(args.package, args.assets, args.output, cases=args.case))
