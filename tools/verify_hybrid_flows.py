"""Owned native Linux/Wine functional flows over real loopback TLS.

Five ordinary completed matches: public1 humans, public1 solo AI fallback,
public2 three humans plus AI fallback, public5 two humans plus original AI,
and Custom1v1. A sixth short match proves disconnect abort and same-identity
new-session recovery, not in-place resumption. Original 30s search and 50ms
ticks remain unchanged. Ordinary configured HQ self-destruct produces results;
no fabricated result, altered economy, accelerated clock or synthetic worker.
This qualifies scripted protocol endpoints, not Unity UI or perceived latency.
--solo-team-only runs only the supplemental solo2vAI companion-search case,
then aborts by ordinary human disconnect; it never fabricates team concession.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict, deque
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import struct
import sys
import time
import traceback

from server import admission, command_scheduling as wire, community_protocol as c
from server import dedicated_server as ds, protocol as p, public_protocol as q, tls_transport as tls
from server.ai_rules import RuleBook
from server.assets import verify_assets
from server.bot_catalog import BotCatalog
from server.game_data import GameTemplate, encode_frame, encode_player_input
from server.profiles import ProfileStore
from server.protobuf_wire import field_bytes, field_packed_uint, field_uint, get_repeated_bytes, get_uint, parse_fields
from server.web_dashboard import Dashboard, read_history
from server.wine_worker import WineWorkerBackend
from server.worker_ai import AISetup
from server.worker_client import SimulationWorker
from tools.verify_hybrid_workers import file_hash, require_cleanup, worker_record
from tools.benchmark_large_armies import read_frame

ROOT = Path(__file__).resolve().parents[1]
CASES = (('public1-humans', 1, 2), ('public1-ai', 1, 1),
         ('public2-ai-fill', 2, 3), ('public5', 5, 2), ('custom1', 1, 2))


def require(ok, message):
    if not ok:
        raise ValueError(message)


async def until(predicate, seconds=15):
    async with asyncio.timeout(seconds):
        while not predicate():
            await asyncio.sleep(.02)


def sources():
    paths = sorted((ROOT/'server').glob('*.py')) + [Path(__file__), ROOT/'tools/verify_hybrid_workers.py',
                                                  ROOT/'tools/benchmark_large_armies.py']
    return {path.relative_to(ROOT).as_posix(): file_hash(path) for path in paths}


def decode_frame(kind, payload, count):
    if kind == q.FRAME:
        return q.decode_frame(payload, count)
    require(kind == p.FRAME and count == 2 and len(payload) >= 8, 'invalid Custom frame')
    frame, size = struct.unpack_from('<II', payload)
    require(0 < size <= p.MAX_INPUT and 8+size < len(payload) <= 8+size+p.MAX_INPUT, 'invalid Custom player sizes')
    return frame, {0: payload[8:8+size], 1: payload[8+size:]}


def join_body(room, slot):
    join = field_uint(1, slot)+field_bytes(2, room.match.deck_messages_by_slot[slot])
    for target, source in ((3, 5), (4, 6)):
        value = get_uint(room.match.armies_by_slot[slot], source)
        if value:
            join += field_uint(target, value)
    return encode_player_input(room.match.identities_by_slot[slot], [field_bytes(3, join)])


def concede_body(room, state, slot):
    choices = [(e['id'], e['type'], ability) for e in state['entities']
               if e.get('army') == slot and e.get('type') == 3
               for ability in room.template.entity_abilities.get(e['type'], ())
               if any(f.number == 24 for f in parse_fields(room.template.abilities[ability]))]
    require(choices, 'no owned HQ with configured ordinary self-destruct ability')
    entity, kind, ability = min(choices)
    group = field_uint(1, kind)+field_uint(2, ability)+field_packed_uint(3, [entity])
    action = field_bytes(1, field_bytes(1, group)+field_bytes(3, field_bytes(1, b'')))
    body = encode_player_input(room.match.identities_by_slot[slot], [action])
    room.validation.validate_player_input(slot, body)
    return body, dict(slot=slot, entity=entity, entity_type=kind, ability=ability)


def validate_result(result, native, losing_slots, *, match):
    require(result.get('match') == match, 'wire result match identity differs')
    require(result.get('reason') == 'native game complete' and result.get('result') == native,
            'wire result differs from original native result')
    mask = sum(1 << slot for slot in losing_slots)
    require(native.get('complete') is True and native.get('winning_alliance') == 1
            and native.get('army_conceded_flag', 0) & mask == mask,
            'ordinary concessions did not produce the expected native alliance defeat')


def validate_history(row, room, *, completed):
    require(row['id'] == room.match_id and row['mode'] == room.mode
            and row['kind'] == ('Public' if room.public_match else 'Custom')
            and row['state'] == ('completed' if completed else 'aborted')
            and row['winning_alliance'] == (1 if completed else None), 'durable history result differs')
    players = {player['slot']: player for player in row['players']}
    require(set(players) == set(room.slots), 'history roster is incomplete')
    for slot, player in players.items():
        require(player['alliance'] == room.template.alliances[slot] and player['bot'] == (slot in room.bots),
                'history player alliance/bot ownership differs')
        require(player['id'] == (None if slot in room.bots else room.match_profiles[slot]),
                'history human identity differs')


def validate_solo_team_roster(room):
    require(room.mode == 5 and set(room.peers) == {0} and set(room.bots) == {1, 2, 3}
            and room.template.alliances == {0: 0, 1: 1, 2: 0, 3: 1}, 'solo2vAI human/ally/opponent ownership differs')
    for slot, bot in room.bots.items():
        require(bot.choice.source_mode == (2 if slot == 2 else 5) and bot.choice.profile == bot.profile_id,
                'solo2vAI did not use original ally/opponent catalog profiles')


def publication_prefix(journal, delivered):
    require(delivered, 'no delivered frames before disconnect')
    recorded = []
    with io.BytesIO(journal) as stream:
        while stream.tell() < len(journal):
            require(len(recorded) < 2400, 'authoritative journal exceeds functional bound')
            frame = read_frame(stream)
            require(get_uint(frame, 1) == len(recorded), 'authoritative journal frame gap/reordering')
            recorded.append(frame)
    require(recorded[:len(delivered)] == delivered and len(recorded) >= len(delivered),
            'delivered prefix differs from authoritative journal')
    return dict(delivered_frames=len(delivered), authoritative_frames=len(recorded),
        delivered_prefix_sha256=hashlib.sha256(b''.join(struct.pack('<I', len(body))+body for body in delivered)).hexdigest(),
        authoritative_journal_sha256=hashlib.sha256(journal).hexdigest(),
        scope='all frames received before deliberate disconnect; later authoritative frames need not reach the disconnected peer')


class Peer:
    """Retain control packets and exact delivered frames; no Unity/client substitute claim."""
    def __init__(self, reader, writer, identity):
        self.reader, self.writer, self.identity = reader, writer, identity
        self.queue, self.pending = asyncio.Queue(256), defaultdict(deque)
        self.request = self.ticket = self.sequence = 0
        self.match = self.slot = None
        self.count, self.frames, self.failure = 2, [], None
        self.execute_counts = defaultdict(int)
        self.send_lock = asyncio.Lock()
        self.task = asyncio.create_task(self.pump())

    async def send(self, kind, payload=b''):
        async with self.send_lock:
            self.writer.write(p.encode(kind, payload))
            await asyncio.wait_for(self.writer.drain(), 5)

    async def pump(self):
        try:
            while True:
                kind, payload = await p.receive(self.reader)
                if kind in (p.FRAME, q.FRAME):
                    frame, inputs = decode_frame(kind, payload, self.count)
                    require(frame == len(self.frames) and frame < 2400, 'delivered frame gap/reordering/bound')
                    self.frames.append(encode_frame(frame, inputs))
                    for slot, body in inputs.items():
                        self.execute_counts[slot] += sum(bool(get_repeated_bytes(action, 1))
                            for action in get_repeated_bytes(body, 2))
                    await self.send(wire.HEARTBEAT, wire.heartbeat(self.match, frame))
                elif kind not in (c.DIRECTORY, c.LOBBY, p.LOBBY, p.NOTICE):
                    await self.queue.put((kind, payload))
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            self.failure = repr(error)
            await self.queue.put((None, str(error).encode()))

    async def receive(self, wanted, seconds=150):
        if self.pending[wanted]:
            return self.pending[wanted].popleft()
        async with asyncio.timeout(seconds):
            while True:
                kind, payload = await self.queue.get()
                require(kind not in (None, p.ERROR), f'peer failed while awaiting {wanted}: {payload!r}')
                if kind == wanted:
                    return payload
                self.pending[kind].append(payload)
                require(sum(map(len, self.pending.values())) <= 256, 'control backlog exceeded')

    async def command(self, kind, body=b'', **public):
        self.request += 1
        data = (q.command(kind, self.request, self.ticket, **public) if kind in q.COMMANDS
                else struct.pack('<I', self.request)+body)
        await self.send(kind, data)
        reply = c.Reader(await self.receive(c.ACK))
        require((reply.number('I'), reply.number('B')) == (self.request, kind), 'command ACK identity differs')
        accepted, reason, identity = reply.flag(), reply.text(), reply.text(); reply.end()
        require(accepted, 'normal command refused: '+reason)
        return identity

    async def batch(self, body):
        self.sequence += 1
        await self.send(wire.BATCH, wire.batch(self.match, self.sequence, body))

    async def close(self):
        self.writer.close(); self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        try:
            await asyncio.wait_for(self.writer.wait_closed(), 2)
        except (OSError, TimeoutError):
            self.writer.transport.abort()


class Verification:
    def __init__(self, args):
        self.args, self.peers, self.workers, self.events, self.cases = args, [], [], [], []
        self.server = self.dashboard = None
        self.started = time.monotonic()

    def audit(self, event, **fields):
        require(len(self.events) < 30000, 'functional audit event bound')
        self.events.append(dict(event=event, at_seconds=time.monotonic()-self.started, **fields))

    async def factory(self, data, bots=None):
        folder = self.args.output/f'worker-{len(self.workers)}'; folder.mkdir()
        worker = await SimulationWorker.create(data, self.args.assets/'Simulation.dll', backend=self.backend,
            working_directory=folder, ai=AISetup(self.args.assets, bots) if bots else None,
            startup_timeout=120, request_timeout=15, close_timeout=2)
        self.workers.append(worker)
        return worker

    async def start(self):
        self.backend = WineWorkerBackend(self.args.wine, self.args.windows_python, self.args.prefix_template,
                                         self.args.cgroup_parent)
        self.templates = {mode: GameTemplate.load(self.args.assets/name, catalog_path=self.args.assets/'unit-catalog.json',
            descriptors_path=self.args.assets/'descriptors') for mode, name in ((1, 'map-1v1.pb.gz'),
                (2, 'map-2v2.pb.gz'), (5, 'map-2vai.pb.gz'))}
        self.profiles = ProfileStore(self.args.output/'profiles', self.templates[1])
        catalog = BotCatalog(self.args.assets, template=self.templates[1], rules=RuleBook(self.args.assets))
        self.server = ds.DedicatedServer(self.templates[1], self.profiles, templates=self.templates,
            bot_catalog=catalog, sim_factory=self.factory, ai_factory=self.factory, audit=self.audit,
            data_dir=self.args.output, audit_state=False, experimental_command_scheduling=True,
            tls_context=tls.load_server_context(self.args.tls_cert, self.args.tls_key),
            admission=admission.AdmissionController(None, rc_open=True, burst=32), loading_timeout=180)
        self.address = await self.server.start('127.0.0.1', 0)
        self.client_tls = tls.load_client_context(self.args.tls_ca, 'localhost')
        self.dashboard = Dashboard(self.server, self.args.output/'web-matches.json')
        self.web_address = await self.dashboard.start('127.0.0.1', 0)

    async def connect(self, identity):
        reader, writer = await tls.open_verified_connection('127.0.0.1', self.address[1], self.client_tls)
        profile = await admission.authenticate_client(reader, writer, identity['token'], rc_open=True)
        peer = Peer(reader, writer, identity); peer.profile = profile; self.peers.append(peer)
        await peer.send(c.HELLO, c.hello(profile, identity['name']))
        welcome = c.Reader(await peer.receive(c.WELCOME))
        require((welcome.number('H'), welcome.number('H'), welcome.key()) == (c.VERSION, p.VERSION, profile),
                'authenticated profile differs from community welcome')
        peer.deck = welcome.deck(); welcome.end()
        await peer.send(wire.NEGOTIATE, b'\x02')
        require(await peer.receive(wire.ACK) == b'\x02', 'arrival scheduling not negotiated')
        return peer

    async def public(self, mode, peers):
        entered = time.monotonic()
        for peer in peers:
            peer.ticket += 1
            await peer.command(q.ENTER, mode=mode, deck=peer.deck, wait_ms=30000)
        expected_fallback = len(peers) < len(q.MODES[mode][1])
        offered = []
        for peer in peers:
            while True:
                state = q.decode_state(await peer.receive(q.STATE, 45))
                if state['ticket'] < peer.ticket:
                    continue  # Prior result/RETURN notifications remain ordered on this same session.
                require(state['ticket'] == peer.ticket and state['mode'] == mode, 'stale public ticket state')
                if state['phase'] == q.OFFERED:
                    offered.append(state); break
        elapsed = time.monotonic()-entered
        require(len({row['match'] for row in offered}) == 1, 'public group split across offers')
        if expected_fallback:
            require(elapsed >= 29.9 and max(row['elapsed_ms'] for row in offered) >= 30000,
                    'AI fallback occurred before ordinary30s search')
        else:
            require(elapsed < 30, 'full human cohort waited for AI deadline')
        for peer in peers:
            await peer.command(q.READY, match=offered[0]['match'])
        for peer in peers:
            assignment = q.decode_assignment(await peer.receive(q.MATCH))
            peer.slot, peer.match, peer.count = assignment['slot'], assignment['match'], assignment['count']
            require(assignment['generation'] == peer.ticket and assignment['mode'] == mode,
                    'assignment ticket/mode differs')
            peer.bootstrap = await peer.receive(p.BOOTSTRAP)
        room = self.server.rooms['public_'+offered[0]['match']]
        require(set(room.peers) == set(q.MODES[mode][1][:len(peers)]) and
                set(room.bots) == set(room.slots)-set(room.peers), 'public human/bot seats differ')
        room.match_profiles = {slot: peer.profile_id for slot, peer in room.peers.items()}
        return room, dict(search_seconds=elapsed, fallback=expected_fallback,
                          offered_elapsed_ms=[row['elapsed_ms'] for row in offered])

    async def custom(self, peers):
        first, second = peers
        lobby_id = await first.command(c.CREATE, b'\x01')
        invite = await first.command(c.INVITE, p.encode_string(second.profile))
        require(await second.command(c.REPLY, p.encode_string(invite)+b'\x01') == lobby_id, 'custom invitation differs')
        lobby = self.server.community.lobbies[lobby_id]
        await first.command(c.START, p.encode_string(lobby_id)+struct.pack('<Q', lobby.revision))
        await second.command(c.READY, p.encode_string(lobby_id)+struct.pack('<IB', lobby.epoch, 1))
        for peer in peers:
            peer.slot, _, peer.deck = p.decode_welcome(await peer.receive(p.WELCOME))
            peer.count = 2
            peer.match = (await peer.receive(p.MATCH_INFO)).decode('ascii')
            peer.bootstrap = await peer.receive(p.BOOTSTRAP)
        room = lobby.room
        room.match_profiles = {slot: peer.profile_id for slot, peer in room.peers.items()}
        require(set(room.peers) == {0, 1} and not room.bots, 'custom roster differs')
        return room, dict(lobby=lobby_id)

    async def load(self, room, peers):
        require(room.command_scheduling and all(peer.bootstrap == room.match.gzip_game_data for peer in peers),
                'scheduling/bootstrap differs')
        for peer in peers:
            peer.frames, peer.sequence = [], 0
            peer.execute_counts.clear()
            await peer.send(p.LOADED, hashlib.sha256(peer.bootstrap).digest())
        for peer in peers:
            await peer.receive(p.START)
        for peer in peers:
            await peer.batch(join_body(room, peer.slot))
        def first_frame():
            require(room.state == 'running' and all(peer.failure is None for peer in peers),
                    'match or peer failed before original startup frame')
            return all(len(peer.frames) == 1 for peer in peers)
        await until(first_frame, 30)
        for peer in peers:
            await peer.send(wire.READY, wire.ready(peer.match))

    async def web_snapshot(self):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.web_address[1])
        try:
            writer.write(b'GET /api/status HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
            await writer.drain()
            header = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)
            require(header.startswith(b'HTTP/1.1 200'), 'dashboard did not serve history')
            sizes = [int(line.partition(b':')[2]) for line in header.split(b'\r\n') if line.lower().startswith(b'content-length:')]
            require(len(sizes) == 1 and 0 < sizes[0] <= 2*1024*1024, 'invalid dashboard response size')
            body = await asyncio.wait_for(reader.readexactly(sizes[0]), 5)
            return json.loads(body)
        finally:
            writer.close(); await writer.wait_closed()

    async def history(self, room, completed):
        expected = 'completed' if completed else 'aborted'
        def persisted():
            return any(row['id'] == room.match_id and row['state'] == expected
                       for row in read_history(self.dashboard.path))
        await until(persisted)
        disk = next(row for row in read_history(self.dashboard.path) if row['id'] == room.match_id)
        validate_history(disk, room, completed=completed)
        snapshot = await self.web_snapshot()
        require(snapshot['persistence_ok'] and next(row for row in snapshot['history'] if row['id'] == room.match_id) == disk,
                'HTTP history differs from durable record')
        return disk

    async def complete(self, name, mode, peers):
        room, preparation = await (self.custom(peers) if name == 'custom1' else self.public(mode, peers))
        worker = room.sim
        await self.load(room, peers)
        await until(lambda: worker.frame >= self.args.play_frames, 60)
        losing = sorted(slot for slot in room.peers if room.template.alliances[slot] == 0)
        require(losing == sorted(slot for slot in room.slots if room.template.alliances[slot] == 0),
                'bounded ordinary concession requires every losing-alliance seat to be human')
        concessions = []
        for peer in peers:
            if peer.slot in losing:
                body, evidence = concede_body(room, worker.last_state, peer.slot)
                concessions.append(evidence); await peer.batch(body)
        results = [json.loads(await peer.receive(p.MATCH_END, 30)) for peer in peers]
        require(all(row == results[0] for row in results), 'participants received different results')
        validate_result(results[0], worker.last_state['game_state'], losing, match=room.match_id)
        await until(lambda: any(e['event'] == 'worker_released' and e.get('match') == room.match_id for e in self.events))
        require_cleanup(worker_record(worker), natural=True)
        journal = (self.args.output/'matches'/room.match_id/'frames.bin').read_bytes()
        for peer in peers:
            delivered = b''.join(struct.pack('<I', len(body))+body for body in peer.frames)
            require(journal == delivered, 'delivered frames differ from persisted authoritative journal')
        require(all(peers[0].execute_counts[slot] > 0 for slot in room.bots), 'an original bot issued no ordinary commands')
        history = await self.history(room, True)
        for peer in peers:
            if name == 'custom1':
                await peer.command(c.RETURN, p.encode_string(room.match_id))
            else:
                await peer.command(q.RETURN, match=room.match_id)
        if name == 'custom1':
            lobby = self.server.community.lobbies[preparation['lobby']]
            require(lobby.phase == c.OPEN, 'custom results did not reopen lobby')
            await peers[1].command(c.LEAVE, p.encode_string(lobby.id))
            await peers[0].command(c.LEAVE, p.encode_string(lobby.id))
        require(self.server.room_count() == 0 and all(self.server.community.sessions[peer.profile].peer.room is None for peer in peers),
                'result return retained old room/capacity')
        row = dict(case=name, match=room.match_id, mode=mode, preparation=preparation, frames=len(peers[0].frames),
            concessions=concessions, result=results[0], history=history, bootstrap_sha256=room.match.raw_sha256,
            delivered_journal_sha256=hashlib.sha256(journal).hexdigest(),
            ai=worker.ai_info, bots={slot: dict(profile=bot.profile_id, deck=list(bot.deck)) for slot, bot in room.bots.items()},
            ordinary_bot_commands={slot: peers[0].execute_counts[slot] for slot in room.bots},
            worker=worker_record(worker), passed=True)
        self.cases.append(row)
        return room

    async def reconnect(self, first, second):
        room, _ = await self.public(1, [first, second]); worker = room.sim
        await self.load(room, [first, second])
        await until(lambda: worker.frame >= 20)
        state = self.profiles.load_state(first.profile, first.deck)
        await first.close()
        notice = c.Reader(await second.receive(c.ABORTED, 15))
        require(notice.text() == room.match_id and notice.text() == 'public player disconnected', 'disconnect abort identity/reason differs')
        notice.end()
        await until(lambda: first.profile not in self.server.community.sessions and worker.process.poll() is not None)
        await until(lambda: any(e['event'] == 'worker_released' and e.get('match') == room.match_id for e in self.events))
        require_cleanup(worker_record(worker), natural=True)
        history = await self.history(room, False)
        await second.command(q.RETURN, match=room.match_id)
        again = await self.connect(first.identity)
        require(again.profile == first.profile and tuple(again.deck) == state.deck, 'reconnect changed persistent identity/deck')
        self.cases.append(dict(case='running-disconnect', match=room.match_id, history=history, worker=worker_record(worker),
            identity_preserved=True, deck_preserved=True, same_match_resumed=False, passed=True))
        return again

    async def solo_team(self, peer):
        room, preparation = await self.public(5, [peer]); worker = room.sim
        validate_solo_team_roster(room)
        require(preparation['fallback'], 'solo2vAI skipped the human companion search')
        await self.load(room, [peer])
        def played():
            require(room.state == 'running' and peer.failure is None, 'solo2vAI failed before observation window')
            return len(peer.frames) >= self.args.play_frames+1
        await until(played, 60)
        require(all(peer.execute_counts[slot] > 0 for slot in (1, 2, 3)), 'an original ally/opponent bot issued no ordinary commands')
        require(not worker.last_state['game_state']['complete'], 'solo2vAI unexpectedly completed before deliberate disconnect')
        state = self.profiles.load_state(peer.profile, peer.deck)
        await peer.close()
        await until(lambda: peer.profile not in self.server.community.sessions and
            any(e['event'] == 'worker_released' and e.get('match') == room.match_id for e in self.events))
        require_cleanup(worker_record(worker), natural=True)
        terminal = [e for e in self.events if e.get('match') == room.match_id and e['event'] in ('match_aborted', 'match_completed')]
        require(len(terminal) == 1 and terminal[0]['event'] == 'match_aborted' and
                terminal[0]['reason'] == 'public player disconnected', 'solo2vAI disconnect was misclassified as completion')
        history = await self.history(room, False)
        publication = publication_prefix((self.args.output/'matches'/room.match_id/'frames.bin').read_bytes(), peer.frames)
        require(publication['authoritative_frames'] == worker.frame+1, 'journal differs from final native frame')
        again = await self.connect(peer.identity)
        require(again.profile == peer.profile and tuple(again.deck) == state.deck, 'solo2vAI recovery changed identity/deck')
        require(self.server.room_count() == 0 and not self.server.community.public.entries and
                not self.server.community.public.offers and self.server.community.sessions[again.profile].peer.room is None,
                'solo2vAI disconnect retained room/queue capacity')
        self.cases.append(dict(case='public5-solo-companion-fallback', mode=5, match=room.match_id,
            preparation=preparation, history=history, publication=publication, ai=worker.ai_info,
            bootstrap_sha256=room.match.raw_sha256,
            bots={slot: dict(profile=bot.profile_id, source_mode=bot.choice.source_mode,
                            role='ally' if slot == 2 else 'opponent', deck=list(bot.deck)) for slot, bot in room.bots.items()},
            ordinary_bot_commands={slot: peer.execute_counts[slot] for slot in room.bots},
            identity_preserved=True, deck_preserved=True, same_match_resumed=False, match_completed=False,
            termination='ordinary human disconnect; aborted match, normal worker CLOSE', worker=worker_record(worker), passed=True))

    async def exercise(self):
        if self.args.solo_team_only:
            peer = await self.connect(dict(name='Solo Flow Player', token='ba1_'+secrets.token_urlsafe(32)))
            await self.solo_team(peer)
            return 1, 0
        identities = [dict(name=f'Flow Player {index}', token='ba1_'+secrets.token_urlsafe(32)) for index in range(3)]
        peers = [await self.connect(identity) for identity in identities]
        peers[0] = await self.reconnect(peers[0], peers[1])
        for name, mode, humans in CASES:
            await self.complete(name, mode, peers[:humans])
        return 6, 5

    async def close(self):
        if self.server:
            await self.server.close()
        for peer in self.peers:
            await peer.close()
        if self.dashboard:
            await self.dashboard.close()
        for worker in self.workers:
            await worker.close()


async def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    check = Verification(args)
    report = dict(passed=False, native_qualified=False, scope=__doc__, source_at_start=sources(),
        real_search_seconds=q.FALLBACK_SECONDS, coordinator_tick_seconds=ds.TICK,
        coordinator=dict(pid=os.getpid(), platform=sys.platform, python=sys.version, executable=sys.executable),
        requested_scope='solo2vAI companion search supplement only' if args.solo_team_only else 'original six-case functional matrix',
        unity_client_qualified=False, in_place_reconnect_supported=False, cases=check.cases)
    try:
        require(q.FALLBACK_SECONDS == 30 and ds.TICK == .05, 'production matchmaking/tick constants changed')
        verify_assets(args.assets)
        report['asset_manifest_sha256'] = file_hash(args.assets/'asset-manifest.json')
        async with asyncio.timeout(args.timeout):
            await check.start()
            report['backend'] = dict(wine=str(check.backend.wine_executable), windows_python=str(check.backend.windows_python),
                wine_sha256=file_hash(check.backend.wine_executable),
                windows_python_sha256=file_hash(check.backend.windows_python), prefix_template=str(check.backend.prefix_template),
                cgroup_parent=str(check.backend.cgroup_parent))
            expected_matches, expected_completed = await check.exercise()
            before = read_history(check.dashboard.path)
            require(len(check.workers) == expected_matches and len(before) == expected_matches and
                    sum(row['state'] == 'completed' for row in before) == expected_completed,
                    'expected exact worker/history coverage missing')
            await check.dashboard.close()
            check.dashboard = Dashboard(check.server, args.output/'web-matches.json')
            check.web_address = await check.dashboard.start('127.0.0.1', 0)
            restored = await check.web_snapshot()
            require(read_history(check.dashboard.path) == before and restored['history_total'] == expected_matches
                    and restored['history'] == list(reversed(before)),
                    'completed/aborted history did not survive dashboard restart')
            report['history_restart_preserved'] = True
            require(not any(e['event'] == 'protocol_error' for e in check.events), 'unexpected protocol error')
            report.update(passed=True, native_qualified=True)
    except BaseException as error:
        report.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        try:
            await check.close()
        except BaseException as error:
            report.update(passed=False, native_qualified=False, cleanup_error=repr(error))
        report['workers'] = [worker_record(worker) for worker in check.workers]
        report.update(source_at_finish=sources(), elapsed_seconds=time.monotonic()-check.started)
        report['source_unchanged'] = report['source_at_start'] == report['source_at_finish']
        report['passed'] &= report['source_unchanged']
        report['native_qualified'] &= report['passed']
        (args.output/'events.json').write_text(json.dumps(check.events, indent=2)+'\n', encoding='utf-8')
        report['events_sha256'] = file_hash(args.output/'events.json')
        (args.output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('passed', 'native_qualified', 'elapsed_seconds', 'error') if key in report}))
    return 0 if report['passed'] else 1


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('assets', 'output', 'wine', 'windows-python', 'prefix-template', 'tls-cert', 'tls-key', 'tls-ca'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--cgroup-parent', type=Path)
    parser.add_argument('--play-frames', type=int,
                        help='default400 for solo2vAI,120 for the completed-match matrix')
    parser.add_argument('--timeout', type=float, default=600)
    parser.add_argument('--solo-team-only', action='store_true', help='only solo2vAI companion-search supplement; skip the already-qualified matrix')
    args = parser.parse_args(argv)
    if args.play_frames is None:
        # The first ordinary original-AI command occurs at frame131 in the
        # retained runs. Completed matches include a result tail; the solo
        # disconnect check must observe enough live frames itself.
        args.play_frames = 400 if args.solo_team_only else 120
    require(sys.platform.startswith('linux'), 'requires native Linux coordinator and explicit Wine worker backend')
    for name in ('assets', 'output', 'wine', 'windows_python', 'prefix_template', 'tls_cert', 'tls_key', 'tls_ca'):
        path = getattr(args, name)
        require(path.is_absolute(), 'all runtime/input/output paths must be absolute')
        require(name != 'prefix_template' or not path.is_symlink(), 'prefix template may not be symlink')
        setattr(args, name, path.resolve())
    require(args.output.is_relative_to(ROOT/'local') and not args.output.exists(), 'new ignored output required')
    require(all(not args.output.is_relative_to(path) and not path.is_relative_to(args.output)
                for path in (args.assets, args.prefix_template)), 'output must be separate from inputs')
    require(args.cgroup_parent is None or args.cgroup_parent.is_absolute(), 'cgroup parent must be absolute')
    require(40 <= args.play_frames <= 400 and 180 <= args.timeout <= 1200, 'bounded flow duration required')
    return args


if __name__ == '__main__':
    raise SystemExit(asyncio.run(run(arguments())))
