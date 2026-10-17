"""Multi-room coordinator with one supervised native simulation worker per match."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import secrets
import struct
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import protocol as p
    from .profiles import ProfileStore
    from .game_data import GameTemplate, InputValidation
    from .protobuf_wire import get_repeated_bytes, parse_fields
except ImportError:
    import protocol as p
    from profiles import ProfileStore
    from game_data import GameTemplate, InputValidation
    from protobuf_wire import get_repeated_bytes, parse_fields

ROOT = Path(__file__).resolve().parent.parent
from .paths import ASSETS, DATA, SIMULATION_DLL
from .admission import AdmissionController, AdmissionError
TICK = 0.05


class Audit:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.session = uuid.uuid4().hex
        self.stream = (self.directory / "events.jsonl").open("a", encoding="utf-8", buffering=1)

    def __call__(self, event, **data):
        self.stream.write(json.dumps({"utc": datetime.now(timezone.utc).isoformat(),
                                      "perf_counter_ns": time.perf_counter_ns(),
                                      "session": self.session, "event": event, **data},
                                     separators=(",", ":"), sort_keys=True) + "\n")

    def close(self):
        self.stream.close()


class Peer:
    def __init__(self, owner, reader, writer):
        self.owner, self.reader, self.writer = owner, reader, writer
        self.room = None
        self.slot = None
        self.profile_id = None
        self.name = None
        self.next_input = 0
        self.joined_army = False
        self.closed = False
        self.outgoing = asyncio.Queue(32)
        self.connection = uuid.uuid4().hex[:12]

    def send(self, kind, payload=b""):
        p.require(not self.closed and not self.outgoing.full(), "client output stalled")
        self.outgoing.put_nowait(p.encode(kind, payload))

    def close(self, reason=None):
        if self.closed:
            return
        self.closed = True
        while not self.outgoing.empty():
            self.outgoing.get_nowait()
        if reason:
            self.outgoing.put_nowait(p.encode(p.ERROR, reason.encode("utf-8")[:1024]))
        self.outgoing.put_nowait(None)
        # Wake any pending read immediately while write_loop flushes the reason.
        self.writer.transport.pause_reading()
        self.reader.feed_eof()

    async def write_loop(self):
        try:
            while True:
                packet = await self.outgoing.get()
                if packet is None:
                    break
                self.writer.write(packet)
                await asyncio.wait_for(self.writer.drain(), 3)
        except (OSError, asyncio.TimeoutError):
            self.writer.transport.pause_reading()
            self.reader.feed_eof()
        finally:
            self.writer.close()
            try:
                await asyncio.wait_for(self.writer.wait_closed(), 1)
            except (OSError, asyncio.TimeoutError):
                pass


class Room:
    def __init__(self, server, name):
        self.server, self.name = server, name
        self.input_window = server.input_window  # Frozen for this room and both seats.
        self.peers, self.decks = {}, {}
        self.ready, self.loaded = set(), set()
        self.revision, self.frame = 0, 0
        self.state = "lobby"
        self.pending = {}
        self.match = self.validation = self.sim = None
        self.match_id = None
        self.next_tick = None
        self.input_wait_started = None
        self.last_progress = time.perf_counter()
        self.history = None
        self.entity_history = {}
        self.result = None
        self.result_frame = None
        self.task = asyncio.create_task(self.tick_loop())

    def event(self, event, **fields):
        self.server.audit(event, room=self.name, match=self.match_id, **fields)

    def broadcast(self, kind, payload=b""):
        for peer in list(self.peers.values()):
            peer.send(kind, payload)

    def lobby_state(self):
        self.revision += 1
        deck0 = self.decks.get(0, self.server.template.default_decks[0])
        deck1 = self.decks.get(1, self.server.template.default_decks[1])
        self.broadcast(p.LOBBY, struct.pack("<BBI", sum(1 << x for x in self.peers),
                                           sum(1 << x for x in self.ready), self.revision)
                       + p.deck_bytes(deck0) + p.deck_bytes(deck1))

    def join(self, peer, slot, profile_id, name):
        if slot == p.AUTO_SEAT:
            slot = next((seat for seat in (0, 1) if seat not in self.peers), None)
        p.require(slot in (0, 1), "room full")
        p.require(self.state == "lobby" and slot not in self.peers, "room slot unavailable")
        p.require(all(x.profile_id != profile_id for x in self.peers.values()), "profile already connected")
        peer.room, peer.slot, peer.profile_id, peer.name = self, slot, profile_id, name
        self.peers[slot] = peer
        try:
            deck = self.server.profiles.load(profile_id, self.server.template.default_decks[slot])
        except (ValueError, KeyError, OSError) as error:
            deck = list(self.server.template.default_decks[slot])
            self.event("profile_load_fallback", profile=profile_id, reason=str(error))
        self.decks[slot] = deck
        peer.send(p.WELCOME, p.welcome(slot, self.input_window, deck))
        self.event("player_joined", slot=slot, profile=profile_id, name=name, deck=deck)
        self.last_progress = time.perf_counter()
        self.lobby_state()

    async def detach(self, peer, reason):
        if self.state == "closed" or self.peers.get(peer.slot) is not peer:
            return
        if self.state == "completed":
            del self.peers[peer.slot]
            if not self.peers:
                await self.finish("completed room empty", aborted=True)
            return
        if self.state != "lobby":
            await self.finish(reason, aborted=True)
            return
        del self.peers[peer.slot]
        self.decks.pop(peer.slot, None)
        self.ready.discard(peer.slot)
        self.event("player_left", slot=peer.slot, reason=reason)
        if self.peers:
            self.lobby_state()
        else:
            await self.finish("empty lobby", aborted=True)

    async def finish(self, reason, *, aborted=False, result=None):
        if self.state == "closed":
            return
        previous_state = self.state
        self.state = "closed" if aborted else "completed"
        self.last_progress = time.perf_counter()
        event = "room_closed" if previous_state in ("lobby", "completed") and aborted else "match_aborted" if aborted else "match_completed"
        self.event(event, reason=reason,
                   next_frame=self.frame, result=result)
        if self.history:
            self.history.close()
            self.history = None
        self.pending.clear()
        self.input_wait_started = None
        if aborted:
            for peer in list(self.peers.values()):
                peer.close(None if previous_state == "completed" else reason)
        else:
            # Keep the socket open for the original game's result screen. Late
            # pipelined inputs are harmless and ignored after final-frame delivery.
            self.broadcast(p.MATCH_END, json.dumps({"match": self.match_id,
                            "reason": reason, "result": result}).encode("utf-8"))
            # Clients leave results at different times. Free the public room name
            # while retaining this match's sockets until they exit or time out.
            if self.server.rooms.get(self.name) is self:
                del self.server.rooms[self.name]
            self.server.retired.add(self)
        if aborted:
            self.server.retired.discard(self)
            if self.server.rooms.get(self.name) is self:
                del self.server.rooms[self.name]
            if asyncio.current_task() is not self.task:
                self.task.cancel()
        if self.sim is not None:
            sim, self.sim = self.sim, None
            cleanup = asyncio.create_task(self.release_worker(sim))
            self.server.worker_cleanup.add(cleanup)
            cleanup.add_done_callback(self.server.worker_cleanup.discard)
            # Disconnects may cancel the room task while its native destructor
            # runs. Keep cleanup supervised independently until process exit.
            await asyncio.shield(cleanup)

    async def release_worker(self, sim):
        await sim.close()
        self.event("worker_released", worker_pid=sim.pid)

    async def prepare_match(self):
        # Freeze lobby mutations before awaiting slow native initialization.
        self.state = "preparing"
        self.match_id = uuid.uuid4().hex
        roster = [{"slot": slot, "player_id": slot + 1, "army_id": slot,
                   "name": self.peers[slot].name} for slot in (0, 1)]
        self.match = self.server.template.build_match(roster, self.decks,
                                                      secrets.randbits(63), self.match_id)
        sim = await self.server.sim_factory(self.match.raw_game_data)
        if self.state != "preparing":
            await sim.close()
            return
        self.sim = sim
        self.event("worker_started", worker_pid=sim.pid)
        state = await sim.state(31, include_entities=True)
        if self.state != "preparing":
            return
        self.refresh_native_state(state)
        self.validation = InputValidation(self.match, self.server.template,
                                           entity_lookup=self.entity_history.get)
        self.state = "loading"
        self.last_progress = time.perf_counter()
        if self.server.data_dir:
            match_dir = self.server.data_dir / "matches" / self.match_id
            match_dir.mkdir(parents=True)
            (match_dir / "bootstrap.pb.gz").write_bytes(self.match.gzip_game_data)
            (match_dir / "match.json").write_text(json.dumps({
                "schema": 1, "match_id": self.match_id, "room": self.name,
                "seed": self.match.seed, "decks": self.decks, "input_window": self.input_window,
                "profiles": {slot: self.peers[slot].profile_id for slot in self.peers},
                "original_sha256": p.BUILD_SHA, "simulation_sha256": p.SIM_SHA,
                "bootstrap_sha256": hashlib.sha256(self.match.gzip_game_data).hexdigest()
            }, indent=2) + "\n", encoding="utf-8")
            self.history = (match_dir / "frames.bin").open("wb")
        self.broadcast(p.MATCH_INFO, self.match_id.encode("ascii"))
        self.broadcast(p.BOOTSTRAP, self.match.gzip_game_data)
        self.event("match_created", seed=self.match.seed, decks=self.decks,
                   bootstrap_bytes=len(self.match.gzip_game_data),
                   bootstrap_sha256=hashlib.sha256(self.match.gzip_game_data).hexdigest(),
                   authority="original Simulation.dll in isolated match worker", worker_pid=sim.pid,
                   input_window=self.input_window)

    async def on_message(self, peer, kind, payload):
        p.require(self.state != "closed", "room closed")
        if self.state == "completed" and kind == p.INPUT:
            return
        if kind in (p.SET_DECK, p.LOBBY_READY):
            if self.state != "lobby":
                peer.send(p.NOTICE, b"Decks are frozen for the current match.")
                return
            try:
                if kind == p.SET_DECK:
                    deck = p.decode_deck(payload)
                    self.server.template.validate_deck(deck)
                    self.server.profiles.save(peer.profile_id, deck)
                    self.decks[peer.slot] = deck
                    self.ready.discard(peer.slot)
                    self.event("deck_selected", slot=peer.slot, profile=peer.profile_id, deck=deck)
                else:
                    p.require(payload in (b"\x00", b"\x01"), "invalid ready flag")
                    if payload == b"\x01":
                        self.ready.add(peer.slot)
                    else:
                        self.ready.discard(peer.slot)
                    self.event("lobby_ready", slot=peer.slot, ready=peer.slot in self.ready)
                self.lobby_state()
                self.last_progress = time.perf_counter()
            except ValueError as error:
                self.event("selection_rejected", slot=peer.slot, reason=str(error))
                peer.send(p.NOTICE, str(error).encode("utf-8")[:1024])
                self.lobby_state()
                return
            if set(self.peers) == self.ready == {0, 1}:
                await self.prepare_match()
        elif kind == p.LOADED:
            p.require(self.state == "loading" and peer.slot not in self.loaded, "unexpected loaded acknowledgement")
            p.require(payload == hashlib.sha256(self.match.gzip_game_data).digest(), "bootstrap acknowledgement mismatch")
            self.loaded.add(peer.slot)
            self.event("world_loaded", slot=peer.slot)
            if self.loaded == {0, 1}:
                self.state = "running"
                self.last_progress = time.perf_counter()
                self.next_tick = self.last_progress + TICK
                self.broadcast(p.START)
                self.event("match_started", frame=0, tick_ms=50)
        elif kind == p.INPUT:
            p.require(self.state == "running", "input outside running match")
            p.require(4 <= len(payload) <= 4 + p.MAX_INPUT, "input size limit")
            frame, = struct.unpack_from("<I", payload)
            p.require(frame == peer.next_input and frame < self.frame + self.input_window,
                      "input frame must be contiguous and within lookahead")
            try:
                body = self.validation.validate_player_input(peer.slot, payload[4:])
                joins = sum(1 for action in get_repeated_bytes(body, 2) if parse_fields(action)[0].number == 3)
                p.require(not joins or (joins == 1 and frame == 0 and not peer.joined_army),
                          "JoinArmy is allowed once in the initial input frame")
                if joins:
                    peer.joined_army = True
            except ValueError:
                if self.server.data_dir:
                    (self.server.data_dir / "matches" / self.match_id / f"rejected-{peer.slot}-{frame}.pb").write_bytes(payload[4:])
                raise
            self.pending.setdefault(frame, {})[peer.slot] = body
            peer.next_input += 1
        elif kind == p.LEAVE:
            p.require(not payload, "leave payload must be empty")
            await self.detach(peer, "player left")
            peer.close()
        else:
            raise p.ProtocolError("unsupported client message (clients cannot publish match data)")

    async def tick_loop(self):
        try:
            while self.state != "closed":
                await asyncio.sleep(0.005)
                now = time.perf_counter()
                if self.state in ("lobby", "completed"):
                    timeout = self.server.lobby_timeout if self.state == "lobby" else self.server.completed_timeout
                    if now - self.last_progress > timeout:
                        await self.finish("room idle timeout", aborted=True)
                    continue
                if self.state == "loading":
                    if now - self.last_progress > self.server.loading_timeout:
                        await self.finish("world loading timeout", aborted=True)
                    continue
                if self.state != "running" or now < self.next_tick:
                    continue
                inputs = self.pending.get(self.frame, {})
                if len(inputs) != 2:
                    if self.input_wait_started is None:
                        self.input_wait_started = now
                    if now - self.last_progress > self.server.input_timeout:
                        await self.finish("player input stalled", aborted=True)
                    continue
                # Native simulation accepts exactly the validated ordered actions
                # sent to clients. No bootstrap or timing comes from a client.
                input_wait_ms = (now - self.input_wait_started) * 1000 if self.input_wait_started is not None else 0.0
                self.input_wait_started = None
                actions = self.validation.encode_frame(self.frame, inputs)
                worker_started = time.perf_counter()
                step = await self.sim.process_frame(actions, dt_ms=50)
                worker_ms = (time.perf_counter() - worker_started) * 1000
                if self.state != "running":
                    continue
                p.require(step.frame == self.frame, "worker returned wrong completed frame")
                native_state = self.refresh_native_state(step.state)
                first, second = inputs[0], inputs[1]
                payload = struct.pack("<II", self.frame, len(first)) + first + second
                if self.history:
                    self.history.write(struct.pack("<I", len(actions)) + actions)
                snapshot_ms = 0.0
                if self.server.audit_state and self.frame % 20 == 0:
                    snapshot_started = time.perf_counter()
                    await self.record_snapshot()
                    snapshot_ms = (time.perf_counter() - snapshot_started) * 1000
                if self.state != "running":
                    continue
                self.broadcast(p.FRAME, payload)
                self.event("frame_queued", frame=self.frame, interval_ms=(now - self.last_progress)*1000,
                           input_wait_ms=input_wait_ms,
                           tick_late_ms=max(0.0, now - self.next_tick) * 1000,
                           worker_ms=worker_ms, snapshot_ms=snapshot_ms,
                           frame_work_ms=(time.perf_counter() - now) * 1000,
                           slot0_sha256=hashlib.sha256(first).hexdigest(),
                           slot1_sha256=hashlib.sha256(second).hexdigest(),
                           frame_payload_sha256=hashlib.sha256(payload).hexdigest())
                del self.pending[self.frame]
                self.frame += 1
                if native_state["game_state"]["complete"] and self.result is None:
                    self.result = native_state["game_state"]
                    self.result_frame = self.frame - 1
                    self.event("native_game_over", result=self.result)
                self.last_progress = time.perf_counter()
                self.next_tick += TICK
                if self.next_tick < now + TICK/2:
                    self.next_tick = now + TICK
                    self.event("cadence_reset", next_frame=self.frame)
                if self.frame >= 0x7fffffff:
                    await self.finish("frame counter exhausted", aborted=True)
                elif self.result is not None and self.frame >= self.result_frame + 20:
                    await self.finish("native game complete", result=self.result)
        except asyncio.CancelledError:
            pass
        except Exception as error:
            self.event("simulation_error", error=repr(error))
            await self.finish("server simulation error", aborted=True)

    async def record_snapshot(self):
        from .native_simulation import canonical_snapshot
        for viewer in (0, 1):
            sim = self.sim
            if sim is None:
                return
            raw = await sim.snapshot(viewer)
            if self.state != "running":
                return
            parsed = canonical_snapshot(raw, viewer)
            self.event("native_snapshot", frame=self.frame, viewer=viewer, bytes=len(raw),
                       sha256=hashlib.sha256(raw).hexdigest(),
                       canonical_fnv1a64=parsed["canonical_fnv1a64"], counts=parsed["counts"],
                       resources=parsed["resources"], game_state=parsed["game_state"])
            if self.server.data_dir:
                folder = self.server.data_dir / "matches" / self.match_id / "snapshots"
                folder.mkdir(exist_ok=True)
                (folder / f"{self.frame:08d}-{viewer}.bin").write_bytes(raw)

    def refresh_native_state(self, state):
        # Retain last known owners of dead units: ordinary in-flight commands can
        # target a unit that died during input delay. Native simulation ignores it.
        for entity in state.get("entities", []):
            if "army" in entity and "type" in entity:
                self.entity_history[entity["id"]] = (entity["army"], entity["type"])
        return state


class DedicatedServer:
    def __init__(self, template, profiles, *, sim_factory=None, audit=None, data_dir=None,
                 input_timeout=10, audit_state=True, max_rooms=4, lobby_timeout=300,
                 loading_timeout=120, completed_timeout=60, tls_context=None, admission=None,
                 input_window=p.DEFAULT_INPUT_WINDOW):
        self.template, self.profiles = template, profiles
        if sim_factory is None:
            from .worker_client import SimulationWorker
            sim_factory = SimulationWorker.create
        self.sim_factory = sim_factory
        self.audit = audit or (lambda event, **fields: None)
        self.data_dir = Path(data_dir) if data_dir else None
        self.input_timeout = input_timeout
        self.input_window = p.validate_input_window(input_window)
        self.audit_state = audit_state
        if type(max_rooms) is not int or not 1 <= max_rooms <= 64:
            raise ValueError("max_rooms must be in 1..64")
        if any(not 0 < value <= 3600 for value in (input_timeout, lobby_timeout, loading_timeout, completed_timeout)):
            raise ValueError("room timeouts must be in (0,3600] seconds")
        self.max_rooms = max_rooms
        self.lobby_timeout, self.loading_timeout, self.completed_timeout = lobby_timeout, loading_timeout, completed_timeout
        self.rooms, self.listener = {}, None
        self.retired = set()
        self.closing = False
        self.peers, self.tasks = set(), set()
        self.worker_cleanup = set()
        if (tls_context is None) != (admission is None):
            raise ValueError("TLS and authenticated admission must be configured together")
        self.tls_context, self.admission = tls_context, admission

    async def start(self, host="127.0.0.1", port=47623):
        if self.tls_context is not None:
            from .tls_transport import start_tls_server
            self.listener = await start_tls_server(self.handle, host, port, self.tls_context,
                                                  stream_limit=p.MAX_BODY, backlog=64)
        else:
            try:
                loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                loopback = False
            if not loopback:
                raise ValueError("Plaintext development listeners require a numeric loopback address; configure TLS and credentials for remote hosts")
            self.listener = await asyncio.start_server(self.handle, host, port, limit=p.MAX_BODY + 4)
        address = self.listener.sockets[0].getsockname()
        self.audit("server_started", host=address[0], port=address[1], original_sha256=p.BUILD_SHA,
                   simulation_sha256=p.SIM_SHA, protocol=p.VERSION,
                   transport="tls-auth" if self.admission else "loopback-development",
                   input_window=self.input_window)
        return address

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        peer = Peer(self, reader, writer)
        sender = asyncio.create_task(peer.write_loop())
        try:
            p.require(not self.closing and len(self.peers) < self.max_rooms * 2 + 8, "connection limit")
            self.peers.add(peer)
            authenticated_id = await self.admission.authenticate(reader, writer) if self.admission else None
            kind, payload = await asyncio.wait_for(p.receive(reader), 5)
            p.require(kind == p.HELLO, "dedicated protocol3 hello required")
            slot, profile_id, name, room_name = p.decode_hello(payload)
            p.require(not self.closing, "server stopped")
            if authenticated_id is not None and profile_id != authenticated_id:
                raise AdmissionError("identity_mismatch")
            p.require(all(other is peer or other.closed or other.profile_id != profile_id for other in self.peers),
                      "profile already connected")
            room = self.rooms.get(room_name)
            if room is None:
                p.require(len(self.rooms) < self.max_rooms, "room capacity reached")
                room = self.rooms[room_name] = Room(self, room_name)
            room.join(peer, slot, profile_id, name)
            while not peer.closed:
                kind, payload = await p.receive(reader)
                await peer.room.on_message(peer, kind, payload)
        except AdmissionError as error:
            self.audit("authentication_failed", connection=peer.connection, category=error.category)
            peer.close("authentication failed")
        except (ValueError, KeyError) as error:
            self.audit("protocol_error", connection=peer.connection, slot=peer.slot, reason=str(error))
            peer.close(str(error))
        except (asyncio.IncompleteReadError, OSError, asyncio.TimeoutError):
            peer.close("connection ended")
        except Exception as error:
            self.audit("connection_error", connection=peer.connection, error=repr(error))
            peer.close("server error; see server log")
        finally:
            if peer.room:
                await peer.room.detach(peer, "player disconnected")
            peer.close()
            await sender
            self.peers.discard(peer)
            self.tasks.discard(task)

    async def close(self):
        self.closing = True
        if self.admission:
            self.admission.stop_accepting()
        if self.listener:
            self.listener.close()
        rooms = list(set(self.rooms.values()) | self.retired)
        await asyncio.gather(*(room.finish("server stopped", aborted=True) for room in rooms))
        await asyncio.gather(*(room.task for room in rooms), return_exceptions=True)
        for peer in list(self.peers):
            peer.close("server stopped")
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        await asyncio.gather(*list(self.worker_cleanup), return_exceptions=True)
        if self.admission and not await self.admission.close():
            self.audit("authentication_shutdown_incomplete", remaining=len(self.admission.verifications))
        if self.listener:
            await self.listener.wait_closed()
        self.audit("server_stopped")


async def main(args):
    secure = (args.tls_cert, args.tls_key, args.credentials)
    if any(value is not None for value in secure) and not all(value is not None for value in secure):
        raise ValueError("Supply --tls-cert, --tls-key and --credentials together")
    context = admission = None
    if all(value is not None for value in secure):
        from .credentials import CredentialStore
        from .tls_transport import load_server_context
        context = load_server_context(args.tls_cert, args.tls_key)
        admission = AdmissionController(CredentialStore(args.credentials))
    from .assets import verify_assets
    verify_assets(args.assets)
    template = GameTemplate.load(args.template or args.assets / "map-1v1.pb.gz",
                                 catalog_path=args.assets / "unit-catalog.json",
                                 descriptors_path=args.assets / "descriptors")
    from .worker_client import SimulationWorker
    args.data.mkdir(parents=True, exist_ok=True)
    audit = Audit(args.data)
    profiles = ProfileStore(args.data / "profiles", template)
    server = DedicatedServer(template, profiles, audit=audit, data_dir=args.data, audit_state=args.audit_state,
                             max_rooms=args.max_rooms, tls_context=context, admission=admission,
                             input_window=args.input_window,
                             sim_factory=lambda data: SimulationWorker.create(data, args.dll or args.assets / "Simulation.dll"))
    try:
        address = await server.start(args.host, args.port)
        print(f"Dedicated server listening on {address[0]}:{address[1]}; data {args.data}", flush=True)
        await server.listener.serve_forever()
    finally:
        await server.close()
        audit.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=47623)
    parser.add_argument("--assets", type=Path, default=ASSETS)
    parser.add_argument("--dll", type=Path, help="default: imported assets/Simulation.dll")
    parser.add_argument("--max-rooms", type=int, default=4)
    parser.add_argument("--input-window", type=int, choices=range(p.MIN_INPUT_WINDOW,p.MAX_INPUT_WINDOW+1),
                        default=p.DEFAULT_INPUT_WINDOW, help="server-selected queued input frames,2..12 (default6)")
    parser.add_argument("--template", type=Path, help="optional local map override")
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--audit-state", action="store_true", help="save native snapshots once per second for client/server comparison")
    parser.add_argument("--tls-cert", type=Path, help="owner-supplied server certificate chain PEM")
    parser.add_argument("--tls-key", type=Path, help="owner-supplied server private key PEM; never pass key material")
    parser.add_argument("--credentials", type=Path, help="private owner-issued credential store directory")
    args = parser.parse_args()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        pass
