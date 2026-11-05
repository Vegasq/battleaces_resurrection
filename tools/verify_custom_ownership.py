"""Packaged Custom match ownership under stale invitation, departure and return commands.

Actual RC TLS/native completion and same-connection rematch; no Unity UI claim.
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
    spec = importlib.util.spec_from_file_location('transition_room_helpers', HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def rejected(peer, kind, body, expected):
    from server import community_protocol as community
    peer.request += 1
    await peer.send(kind, struct.pack('<I', peer.request) + body)
    r = community.Reader(await peer.receive(community.ACK))
    require((r.number('I'), r.number('B')) == (peer.request, kind), 'rejection acknowledgement differs')
    accepted, reason, identity = r.flag(), r.text(), r.text()
    r.end()
    require(not accepted and reason == expected and identity == '', 'wrong save refusal')
    return reason


def check_journal(rows, match, frames, replacement):
    require(not any(row['event'] in ('protocol_error', 'simulation_error', 'match_aborted')
                    for row in rows), 'control command disrupted a match')
    for identity, expected in ((match, frames), (replacement, 10)):
        selected = [row for row in rows if row.get('match') == identity]
        delivered = [row['frame'] for row in selected if row['event'] == 'frame_queued']
        require(delivered == list(range(expected)), 'match frame sequence changed')
        require(sum(row['event'] == 'match_started' for row in selected) == 1, 'match start count differs')
        completed = [row for row in selected if row['event'] == 'match_completed']
        require(len(completed) == (1 if identity == match else 0), 'completion count differs')


async def scenario(folder, assets, h):
    from server import protocol as p, community_protocol as community
    from server import dedicated_server, admission, tls_transport as tls, rc_host
    from server.game_data import GameTemplate, encode_player_input
    from server.protobuf_wire import field_bytes, field_uint, field_packed_uint, parse_fields
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
    catalog = CosmeticCatalog(assets)
    workers, peers = [], []

    async def factory(data, *, ai=None):
        worker = await SimulationWorker.create(data, assets / 'Simulation.dll', working_directory=work, ai=ai)
        workers.append(worker)
        require(worker.dll_sha256 == p.SIM_SHA and worker.game_data_sha256 == hashlib.sha256(data).hexdigest()
                and not worker._test_backend, 'real native inputs differ')
        return worker

    audit = HostAudit(folder / 'logs', max_bytes=8388608, backups=4, diagnostics=True)
    server = dedicated_server.DedicatedServer(template, ProfileStore(folder / 'profiles', template, catalog=catalog),
        sim_factory=factory, audit=audit, audit_state=True, tls_context=tls.load_server_context(cert, key),
        admission=admission.AdmissionController(None, rc_open=True))
    record = dict(passed=False)
    try:
        port = (await server.start('127.0.0.1', 0))[1]
        pair, match = await h.pair(port, 'ownership', ['ba1_' + secrets.token_urlsafe(32) for _ in range(2)],
                                 peers, server=server, custom=True, loaded=False)
        host, guest = pair
        lobby = server.community.lobbies[host.lobby_id]
        room, worker = lobby.room, lobby.room.sim
        originals = [server.community.sessions[peer.profile].peer for peer in pair]
        profile_hashes = {peer.profile: sha(server.profiles._path(peer.profile)) for peer in pair}
        rows = [json.loads(line) for line in (folder / 'logs/events.jsonl').read_text().splitlines()]
        invitations = [r for r in rows if r['event'] == 'custom_invite_created']
        require(len(invitations) == 1, 'expected one accepted invitation')
        old_invite = invitations[0]['invite']
        rejected_commands = []

        def snapshot():
            return (lobby.phase, lobby.revision, lobby.epoch, lobby.match_id, lobby.host,
                    tuple(lobby.members), frozenset(lobby.returned), id(lobby.room),
                    tuple(id(server.community.sessions[peer.profile].peer.room) for peer in pair),
                    tuple(server.community.invites), len(workers))

        async def unchanged_rejection(peer, kind, body, reason):
            before = snapshot()
            await rejected(peer, kind, body, reason)
            require(snapshot() == before, 'rejected command mutated ownership')
            rejected_commands.append(dict(kind=kind, reason=reason, phase=lobby.phase))

        async def committed_controls():
            await unchanged_rejection(host, community.LEAVE, p.encode_string(lobby.id),
                                      'return from the match before leaving the lobby')
            await unchanged_rejection(guest, community.REPLY, p.encode_string(old_invite) + b'\x01',
                                      'invitation is no longer pending')
            await unchanged_rejection(host, community.RETURN, p.encode_string(match),
                                      'match has not finished or changed')

        require(lobby.phase == community.LOADING and room.frame == 0, 'committed loading phase differs')
        await committed_controls()
        # pair(loaded=False) has already consumed and validated both bootstraps.
        bootstrap_hash = hashlib.sha256(room.match.gzip_game_data).digest()
        await asyncio.gather(*(peer.send(p.LOADED, bootstrap_hash) for peer in pair))
        require(await asyncio.gather(*(peer.receive(p.START) for peer in pair)) == [b'', b''], 'start differs')
        require(lobby.phase == community.RUNNING, 'running phase absent')
        await committed_controls()
        frames = []
        for frame in range(160):
            if frame != 140:
                frames.append(await h.advance(pair, frame))
                continue
            require(worker.frame == 139, 'surrender must use preceding native state')
            choices = [(entity['id'], entity['type'], ability)
                       for entity in worker.last_state['entities']
                       if entity.get('army') == 0 and 'type' in entity
                       for ability in template.entity_abilities.get(entity['type'], ())
                       if any(field.number == 24 for field in parse_fields(template.abilities[ability]))]
            require(choices, 'owned native surrender ability absent')
            entity, entity_type, ability = min(choices)
            group = field_uint(1, entity_type) + field_uint(2, ability) + field_packed_uint(3, [entity])
            command = field_bytes(1, field_bytes(1, group) + field_bytes(3, field_bytes(1, b'')))
            await asyncio.gather(*(peer.send(p.INPUT, struct.pack('<I', frame) +
                encode_player_input(peer.identity, [command] if index == 0 else [])) for index, peer in enumerate(pair)))
            values = await asyncio.gather(*(peer.receive(p.FRAME) for peer in pair))
            require(values[0] == values[1] and struct.unpack_from('<I', values[0])[0] == frame, 'surrender frames differ')
            frames.append(dict(frame=frame, at=time.perf_counter(), sha256=hashlib.sha256(values[0]).hexdigest()))
        results = await asyncio.gather(*(peer.receive(p.MATCH_END) for peer in pair))
        require(results[0] == results[1], 'results differ')
        result = json.loads(results[0])
        require(result['match'] == match and result['reason'] == 'native game complete' and
                result['result']['complete'] is True and result['result']['winning_alliance'] == 1 and
                result['result']['army_conceded_flag'] == 1 and result['result']['game_over_frame'] == 140,
                'native result differs')
        async with asyncio.timeout(5):
            while worker.process.poll() is None:
                await asyncio.sleep(.01)
        require(worker.process.poll() == 0, 'completed worker did not exit normally')
        await host.command(community.RETURN, p.encode_string(match))
        require(lobby.phase == community.RESULTS and lobby.returned == {host.profile} and
                originals[0].room is None and originals[1].room is room, 'partial return lost ownership')
        await unchanged_rejection(host, community.RETURN, p.encode_string(match), 'already returned from match')
        await unchanged_rejection(host, community.START, p.encode_string(lobby.id) + struct.pack('<Q', lobby.revision),
                                  'custom lobby needs two players')
        await guest.command(community.REFRESH)
        await guest.command(community.RETURN, p.encode_string(match))
        require(lobby.phase == community.OPEN and all(peer.room is None for peer in originals), 'late return did not reopen')
        _, replacement = await h.pair(port, '', [], peers, server=server, custom=True, existing=pair)
        require(replacement != match and lobby.room is not room, 'replacement identity not fresh')
        await unchanged_rejection(guest, community.RETURN, p.encode_string(match), 'match has not finished or changed')
        replacement_frames = [await h.advance(pair, frame) for frame in range(10)]
        require([server.community.sessions[peer.profile].peer for peer in pair] == originals,
                'control connection replaced')
        require({profile: sha(server.profiles._path(profile)) for profile in profile_hashes} == profile_hashes,
                'profile changed during controls/return')
        rows = [json.loads(line) for line in (folder / 'logs/events.jsonl').read_text().splitlines()]
        check_journal(rows, match, len(frames), replacement)
        for identity, expected in ((match, frames), (replacement, replacement_frames)):
            actual = [r['frame_payload_sha256'] for r in rows if r.get('match') == identity and r['event'] == 'frame_queued']
            require(actual == [frame['sha256'] for frame in expected], 'host/client frame hashes differ')
        record.update(passed=True, match=match, replacement_match=replacement, result=result,
            frames=frames, replacement_frames=replacement_frames, rejected_commands=rejected_commands,
            both_connections_reused=True, partial_return_preserved=True, profiles_preserved=profile_hashes)
    except BaseException as error:
        record.update(error=repr(error), traceback=traceback.format_exc())
        raise
    finally:
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
    require(record['passed'], 'custom ownership scenario failed')
    return record


def child(request_path):
    from tools.package_integrity import verify
    from server.assets import verify_assets
    from server import profiles, profile_io, dedicated_server
    request = json.loads(request_path.read_bytes())
    out, package, assets = request_path.parent, Path(request['package']), Path(request['assets'])
    report = dict(passed=False, scope=__doc__)
    try:
        require(sha(__file__) == request['driver_sha256'] and sha(HELPER) == request['helper_sha256'], 'driver changed')
        verify(package, 'server')
        verify_assets(assets)
        for module in (profiles, profile_io, dedicated_server):
            require(Path(module.__file__).resolve() == package / 'program/app/server' / (module.__name__.split('.')[-1] + '.py'),
                    'bundled imports differ')
        report['module_sha256'] = {str(Path(m.__file__).resolve()): sha(m.__file__) for m in (profiles, profile_io, dedicated_server)}
        require((out / 'job-ready').exists(), 'owned job gate absent')
        report['case'] = asyncio.run(scenario(out / 'transitions', assets, helper()))
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
