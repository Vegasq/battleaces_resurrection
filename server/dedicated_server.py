"""Standalone two-player server with persistent decks and original native simulation."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
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
        self.peers, self.decks = {}, {}
        self.ready, self.loaded = set(), set()
        self.revision, self.frame = 0, 0
        self.state = "lobby"
        self.pending = {}
        self.match = self.validation = self.sim = None
        self.match_id = None
        self.next_tick = None
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
        peer.send(p.WELCOME, bytes([slot]) + p.deck_bytes(deck))
        self.event("player_joined", slot=slot, profile=profile_id, name=name, deck=deck)
        self.lobby_state()

    def detach(self, peer, reason):
        if self.state == "closed" or self.peers.get(peer.slot) is not peer:
            return
        if self.state == "completed":
            del self.peers[peer.slot]
            return
        if self.state != "lobby":
            self.finish(reason, aborted=True)
            return
        del self.peers[peer.slot]
        self.decks.pop(peer.slot, None)
        self.ready.discard(peer.slot)
        self.event("player_left", slot=peer.slot, reason=reason)
        if self.peers:
            self.lobby_state()
        else:
            self.finish("empty lobby", aborted=True)

    def finish(self, reason, *, aborted=False, result=None):
        if self.state == "closed":
            return
        self.state = "closed" if aborted else "completed"
        self.event("match_aborted" if aborted else "match_completed", reason=reason,
                   next_frame=self.frame, result=result)
        if self.sim is not None:
            self.sim.close()
            self.sim = None
        if self.history:
            self.history.close()
            self.history = None
        self.pending.clear()
        if aborted:
            for peer in list(self.peers.values()):
                peer.close(reason)
        else:
            # Keep the socket open for the original game's result screen. Late
            # pipelined inputs are harmless and ignored after final-frame delivery.
            self.broadcast(p.MATCH_END, json.dumps({"match": self.match_id,
                            "reason": reason, "result": result}).encode("utf-8"))
        if self.server.room is self:
            self.server.room = None
        if asyncio.current_task() is not self.task:
            self.task.cancel()

    def prepare_match(self):
        self.match_id = uuid.uuid4().hex
        roster = [{"slot": slot, "player_id": slot + 1, "army_id": slot,
                   "name": f"LAN Player {slot + 1}"} for slot in (0, 1)]
        self.match = self.server.template.build_match(roster, self.decks,
                                                      secrets.randbits(63), self.match_id)
        self.sim = self.server.sim_factory(self.match.raw_game_data)
        self.refresh_native_state()
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
                "seed": self.match.seed, "decks": self.decks,
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
                   authority="original Simulation.dll in dedicated process")

    def on_message(self, peer, kind, payload):
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
                if set(self.peers) == self.ready == {0, 1}:
                    self.prepare_match()
            except ValueError as error:
                self.event("selection_rejected", slot=peer.slot, reason=str(error))
                peer.send(p.NOTICE, str(error).encode("utf-8")[:1024])
                self.lobby_state()
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
            p.require(frame == peer.next_input and frame <= self.frame + p.MAX_AHEAD,
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
            self.detach(peer, "player left")
            peer.close()
        else:
            raise p.ProtocolError("unsupported client message (clients cannot publish match data)")

    async def tick_loop(self):
        try:
            while self.state in ("lobby", "loading", "running"):
                await asyncio.sleep(0.005)
                now = time.perf_counter()
                if self.state == "loading":
                    if now - self.last_progress > 120:
                        self.finish("world loading timeout", aborted=True)
                    continue
                if self.state != "running" or now < self.next_tick:
                    continue
                inputs = self.pending.get(self.frame, {})
                if len(inputs) != 2:
                    if now - self.last_progress > self.server.input_timeout:
                        self.finish("player input stalled", aborted=True)
                    continue
                # Native simulation accepts exactly the validated ordered actions
                # sent to clients. No bootstrap or timing comes from a client.
                actions = self.validation.encode_frame(self.frame, inputs)
                step = self.sim.process_frame(actions, dt_ms=50)
                native_state = self.refresh_native_state()
                first, second = inputs[0], inputs[1]
                payload = struct.pack("<II", self.frame, len(first)) + first + second
                if self.history:
                    self.history.write(struct.pack("<I", len(actions)) + actions)
                if self.server.audit_state and self.frame % 20 == 0:
                    self.record_snapshot()
                self.broadcast(p.FRAME, payload)
                self.event("frame_queued", frame=self.frame, interval_ms=(now - self.last_progress)*1000,
                           slot0_sha256=hashlib.sha256(first).hexdigest(),
                           slot1_sha256=hashlib.sha256(second).hexdigest(),
                           frame_payload_sha256=hashlib.sha256(payload).hexdigest())
                del self.pending[self.frame]
                self.frame += 1
                if native_state["game_state"]["complete"] and self.result is None:
                    self.result = native_state["game_state"]
                    self.result_frame = self.frame - 1
                    self.event("native_game_over", result=self.result)
                self.last_progress = now
                self.next_tick += TICK
                if self.next_tick < now + TICK/2:
                    self.next_tick = now + TICK
                    self.event("cadence_reset", next_frame=self.frame)
                if self.frame >= 0x7fffffff:
                    self.finish("frame counter exhausted", aborted=True)
                elif self.result is not None and self.frame >= self.result_frame + 20:
                    self.finish("native game complete", result=self.result)
        except asyncio.CancelledError:
            pass
        except Exception as error:
            self.event("simulation_error", error=repr(error))
            self.finish("server simulation error", aborted=True)

    def record_snapshot(self):
        from .native_simulation import canonical_snapshot
        for viewer in (0, 1):
            raw = self.sim.snapshot(viewer)
            parsed = canonical_snapshot(raw, viewer)
            self.event("native_snapshot", frame=self.frame, viewer=viewer, bytes=len(raw),
                       sha256=hashlib.sha256(raw).hexdigest(),
                       canonical_fnv1a64=parsed["canonical_fnv1a64"], counts=parsed["counts"],
                       resources=parsed["resources"], game_state=parsed["game_state"])
            if self.server.data_dir:
                folder = self.server.data_dir / "matches" / self.match_id / "snapshots"
                folder.mkdir(exist_ok=True)
                (folder / f"{self.frame:08d}-{viewer}.bin").write_bytes(raw)

    def refresh_native_state(self):
        state = self.sim.state(31, include_entities=True)
        # Retain last known owners of dead units: ordinary in-flight commands can
        # target a unit that died during input delay. Native simulation ignores it.
        for entity in state.get("entities", []):
            if "army" in entity and "type" in entity:
                self.entity_history[entity["id"]] = (entity["army"], entity["type"])
        return state


class DedicatedServer:
    def __init__(self, template, profiles, *, sim_factory=None, audit=None, data_dir=None, input_timeout=10, audit_state=True):
        self.template, self.profiles = template, profiles
        if sim_factory is None:
            try:
                from .native_simulation import NativeSimulation
            except ImportError:
                from native_simulation import NativeSimulation
            sim_factory = NativeSimulation
        self.sim_factory = sim_factory
        self.audit = audit or (lambda event, **fields: None)
        self.data_dir = Path(data_dir) if data_dir else None
        self.input_timeout = input_timeout
        self.audit_state = audit_state
        self.room, self.listener = None, None
        self.peers, self.tasks = set(), set()

    async def start(self, host="127.0.0.1", port=47623):
        self.listener = await asyncio.start_server(self.handle, host, port, limit=p.MAX_BODY + 4)
        address = self.listener.sockets[0].getsockname()
        self.audit("server_started", host=address[0], port=address[1], original_sha256=p.BUILD_SHA,
                   simulation_sha256=p.SIM_SHA, protocol=p.VERSION)
        return address

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        peer = Peer(self, reader, writer)
        sender = asyncio.create_task(peer.write_loop())
        try:
            p.require(len(self.peers) < 8, "connection limit")
            self.peers.add(peer)
            kind, payload = await asyncio.wait_for(p.receive(reader), 5)
            p.require(kind == p.HELLO, "dedicated protocol2 hello required")
            slot, profile_id, name, room_name = p.decode_hello(payload)
            if self.room is None:
                self.room = Room(self, room_name)
            p.require(self.room.name == room_name, "another room is active on this server")
            self.room.join(peer, slot, profile_id, name)
            while not peer.closed:
                kind, payload = await p.receive(reader)
                peer.room.on_message(peer, kind, payload)
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
                peer.room.detach(peer, "player disconnected")
            peer.close()
            await sender
            self.peers.discard(peer)
            self.tasks.discard(task)

    async def close(self):
        if self.listener:
            self.listener.close()
        if self.room:
            room = self.room
            room.finish("server stopped", aborted=True)
            await asyncio.gather(room.task, return_exceptions=True)
        for peer in list(self.peers):
            peer.close("server stopped")
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        if self.listener:
            await self.listener.wait_closed()
        self.audit("server_stopped")


async def main(args):
    from .assets import verify_assets
    verify_assets(args.assets)
    template = GameTemplate.load(args.template or args.assets / "map-1v1.pb.gz",
                                 catalog_path=args.assets / "unit-catalog.json",
                                 descriptors_path=args.assets / "descriptors")
    from .native_simulation import NativeSimulation
    args.data.mkdir(parents=True, exist_ok=True)
    audit = Audit(args.data)
    profiles = ProfileStore(args.data / "profiles", template)
    server = DedicatedServer(template, profiles, audit=audit, data_dir=args.data, audit_state=args.audit_state,
                             sim_factory=lambda data: NativeSimulation(data, args.dll))
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
    parser.add_argument("--dll", type=Path, default=SIMULATION_DLL)
    parser.add_argument("--template", type=Path, help="optional local map override")
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--audit-state", action="store_true", help="save native snapshots once per second for client/server comparison")
    args = parser.parse_args()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        pass
