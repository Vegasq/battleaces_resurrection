"""Owned packaged TLS/native profile recovery under real Windows sharing locks.

Read/replace refusal and damaged JSON, explicit owned-file repair, same-profile
reconnect and concurrent native progression. No ACL changes or real player data.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
from ctypes import wintypes
import hashlib
import importlib.util
import json
import os
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
    spec = importlib.util.spec_from_file_location('storage_room_helpers', HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OwnedFileLock:
    """Hold only an existing regular file beneath an owned diagnostic directory."""
    def __init__(self, path, folder, *, allow_read):
        require(os.name == 'nt', 'Windows sharing control required')
        path, folder = Path(path), Path(folder).resolve()
        roots=(ROOT/'local', Path.home()/'AppData/Local/BattleAcesDiagnostics/local')
        require(any(folder!=base and folder.is_relative_to(base) for base in roots) and path.resolve().is_relative_to(folder)
                and path.is_file() and not path.is_symlink() and
                not getattr(path.lstat(), 'st_file_attributes', 0) & 0x400, 'owned regular profile required')
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self.kernel.CreateFileW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.CreateFileW(str(path), 0x80000000, 1 if allow_read else 0, None, 3, 0x80, None)
        if self.handle == ctypes.c_void_p(-1).value:
            self.handle = None
            raise ctypes.WinError(ctypes.get_last_error())
        # Verify the intended OS obstruction directly. Python's CRT file-open
        # path can expose only errno13, while replacement may expose WinError5.
        probe = self.kernel.CreateFileW(str(path), 0x10000 if allow_read else 0x80000000,
                                        7, None, 3, 0x80, None)
        self.probe_winerror = ctypes.get_last_error()
        if probe != ctypes.c_void_p(-1).value:
            self.kernel.CloseHandle(probe)
            self.close()
            raise AssertionError('owned sharing lock did not refuse conflicting access')
        if self.probe_winerror != 32:
            self.close()
            raise AssertionError('owned sharing lock refused for an unexpected reason')

    def close(self):
        if self.handle is not None:
            require(self.kernel.CloseHandle(self.handle), 'owned file lock release failed')
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


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


async def scenario(folder, assets, h):
    from server import protocol as p, community_protocol as community, loadout_protocol as loadout
    from server import dedicated_server, admission, tls_transport as tls, rc_host
    from server.game_data import GameTemplate
    from server.cosmetics import CosmeticCatalog
    from server.profiles import ProfileStore, read_profile_state
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
    default = catalog.normalize_local()
    selected = dict(default.slots)
    portrait_slot = catalog.roles['portrait']
    selected[portrait_slot] = next(item for item in sorted(catalog.slots[portrait_slot].compatible_items)
                                   if item not in selected.values())
    changed = catalog.validate_selection(selected)
    require(changed != default, 'distinct valid saved cosmetics required')
    workers = []

    async def factory(data, *, ai=None):
        worker = await SimulationWorker.create(data, assets / 'Simulation.dll', working_directory=work, ai=ai)
        workers.append(worker)
        require(worker.dll_sha256 == p.SIM_SHA and worker.game_data_sha256 == hashlib.sha256(data).hexdigest()
                and not worker._test_backend, 'real native inputs differ')
        require(worker.request_timeout == 3 and worker.close_timeout == 2, 'worker deadlines changed')
        return worker

    audit = HostAudit(folder / 'logs', max_bytes=8388608, backups=4, diagnostics=True)
    server = dedicated_server.DedicatedServer(template, ProfileStore(folder / 'profiles', template, catalog=catalog),
        sim_factory=factory, audit=audit, audit_state=True, tls_context=tls.load_server_context(cert, key),
        admission=admission.AdmissionController(None, rc_open=True))
    peers, frames = [], []
    healthy_task = None
    stop = asyncio.Event()
    record = dict(passed=False)
    try:
        port = (await server.start('127.0.0.1', 0))[1]
        healthy, match = await h.pair(port, 'healthy', ['ba1_' + secrets.token_urlsafe(32) for _ in range(2)],
                                     peers, server=server, custom=True)
        room = server.rooms[healthy[0].room_key]
        worker = room.sim
        healthy_saved = {peer.profile: sha(server.profiles._path(peer.profile)) for peer in healthy}

        async def pump():
            for frame in range(240):
                if stop.is_set() and frame >= 40:
                    return
                frames.append(await h.advance(healthy, frame))
            raise AssertionError('healthy frame budget exceeded')

        healthy_task = asyncio.create_task(pump())
        token = 'ba1_' + secrets.token_urlsafe(32)

        async def connect():
            reader, writer = await tls.open_verified_connection('127.0.0.1', port, tls.rc_client_context('127.0.0.1'))
            peer = h.Peer(reader, writer)
            peers.append(peer)
            peer.profile = await admission.authenticate_client(reader, writer, token, rc_open=True)
            await peer.send(community.HELLO, community.hello(peer.profile, 'Storage Player', version=2))
            r = community.Reader(await peer.receive(community.WELCOME))
            require((r.number('H'), r.number('H'), r.key()) == (2, p.VERSION, peer.profile), 'community identity differs')
            require(r.deck() == list(template.default_decks[0]), 'saved deck differs')
            r.end()
            return peer

        async def disconnect(peer):
            await peer.close()
            async with asyncio.timeout(3):
                while peer.profile in server.community.sessions:
                    await asyncio.sleep(.01)

        def body(cosmetics):
            return struct.pack('<H', loadout.VERSION) + p.deck_bytes(template.default_decks[0]) + loadout.encode(cosmetics)

        peer = await connect()
        profile = peer.profile
        path = server.profiles._path(profile)
        await peer.command(loadout.SET_LOADOUT, body(default))
        before = path.read_bytes()
        original_connection = server.community.sessions[profile].peer
        with OwnedFileLock(path, folder / 'profiles', allow_read=True) as lock:
            record['replace_lock_probe_winerror'] = lock.probe_winerror
            reason = await rejected(peer, loadout.SET_LOADOUT, body(changed), 'profile save unavailable')
            require(path.read_bytes() == before and server.community.sessions[profile].cosmetics == default,
                    'failed replacement changed saved/in-memory choice')
            require(not list((folder / 'profiles').glob('.profile-*.tmp')), 'failed save left temporary files')
            await peer.command(community.REFRESH)
            frame_count = len(frames)
            async with asyncio.timeout(2):
                while len(frames) < frame_count + 10:
                    await asyncio.sleep(.01)
        await peer.command(loadout.SET_LOADOUT, body(changed))
        require(server.community.sessions[profile].peer is original_connection, 'save retry replaced connection')
        valid = path.read_bytes()
        require(valid != before and read_profile_state(path, profile, template, catalog=catalog).cosmetics == changed,
                'same-connection retry did not publish changed choice')
        save(folder / 'replacement-refusal.json', dict(passed=True, reason=reason,
            previous_sha256=hashlib.sha256(before).hexdigest(), recovered_sha256=hashlib.sha256(valid).hexdigest(),
            same_connection=True, prior_bytes_preserved=True))

        await disconnect(peer)
        with OwnedFileLock(path, folder / 'profiles', allow_read=False) as lock:
            record['read_lock_probe_winerror'] = lock.probe_winerror
            peer = await connect()
            require(peer.profile == profile and server.community.sessions[profile].cosmetics == default,
                    'locked read fallback differs')
            await rejected(peer, loadout.SET_LOADOUT, body(changed), 'profile save unavailable')
            await peer.command(community.REFRESH)
            require(server.community.sessions[profile].cosmetics == default, 'failed locked-read save changed session')
        require(path.read_bytes() == valid, 'read fallback replaced last valid bytes')
        await disconnect(peer)
        peer = await connect()
        require(peer.profile == profile and server.community.sessions[profile].cosmetics == changed,
                'read-lock recovery failed to reload saved cosmetics')
        await disconnect(peer)

        # Explicit operator-style repair only in the disposable diagnostic file.
        # The production load/save path must neither erase nor silently repair it.
        corrupt = b'{"schema":2,"broken":'
        path.write_bytes(corrupt)
        peer = await connect()
        require(server.community.sessions[profile].cosmetics == default, 'damaged-file fallback differs')
        await rejected(peer, loadout.SET_LOADOUT, body(changed), 'invalid selection or saved profile')
        require(path.read_bytes() == corrupt and server.community.sessions[profile].cosmetics == default,
                'damaged file was silently replaced')
        await peer.command(community.REFRESH)
        await disconnect(peer)
        path.write_bytes(valid)
        peer = await connect()
        require(peer.profile == profile and server.community.sessions[profile].cosmetics == changed and
                path.read_bytes() == valid, 'explicit repair/reconnect did not restore saved choice')
        require(not list((folder / 'profiles').glob('.profile-*.tmp')), 'temporary save remains')
        require({pkey: sha(server.profiles._path(pkey)) for pkey in healthy_saved} == healthy_saved,
                'unrelated profiles changed')
        until = len(frames) + 10
        async with asyncio.timeout(3):
            while len(frames) < until:
                await asyncio.sleep(.01)
        stop.set()
        await healthy_task
        healthy_task = None
        require(server.rooms.get(healthy[0].room_key) is room and room.sim is worker and worker.process.poll() is None,
                'unrelated room/worker replaced')
        gaps = [(b['at'] - a['at']) * 1000 for a, b in zip(frames, frames[1:])]
        require(len(frames) >= 40 and max(gaps) < 1000, 'unrelated match stalled')
        rows = [json.loads(line) for line in (folder / 'logs/events.jsonl').read_text().splitlines()]
        failures = [row for row in rows if row['event'] == 'profile_save_failed']
        fallback = [row for row in rows if row['event'] == 'profile_load_fallback']
        require(len(failures) == 2 and all(row['error_kind'] == 'permission' and row['errno'] == 13 for row in failures)
                and failures[0].get('winerror') in (5, 32), 'real Windows save refusal not evidenced')
        require(len(fallback) == 2 and [row['error_kind'] for row in fallback] == ['permission', 'invalid_data'] and
                fallback[0]['errno'] == 13, 'read-failure categories differ')
        require(not any(row['event'] in ('protocol_error', 'simulation_error') for row in rows), 'unintended peer/native failure')
        delivered = [row for row in rows if row.get('match') == match and row['event'] == 'frame_queued']
        require([row['frame'] for row in delivered] == list(range(len(frames))) and
                [row['frame_payload_sha256'] for row in delivered] == [row['sha256'] for row in frames],
                'healthy host/client journal differs')
        record.update(passed=True, permission_refusals=3, replacement_refusal_preserved_bytes=True,
            same_connection_save_retry=True, read_refusal_preserved_bytes=True, damaged_json_preserved=True,
            explicit_repair_reloaded=True, saved_profile_sha256=hashlib.sha256(valid).hexdigest(),
            old_portrait=default.portrait, saved_portrait=changed.portrait,
            healthy_frames=frames, max_healthy_gap_ms=max(gaps), healthy_same_room_and_worker=True,
            healthy_profile_sha256=healthy_saved, save_failure_events=failures, load_fallback_events=fallback)
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
    require(record['passed'], 'profile storage scenario failed')
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
        report['case'] = asyncio.run(scenario(out / 'storage', assets, helper()))
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
