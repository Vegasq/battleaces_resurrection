"""Opt-in Windows native coordinator lifecycle verification using scripted peers.

All game data comes from a locally imported bundle. Evidence stays under local/.
This exercises real native simulation and TCP, not graphical/manual P2 play.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import time
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import protocol as p
from server.assets import verify_assets
from server.dedicated_server import Audit, DedicatedServer
from server.game_data import GameTemplate, encode_frame, encode_player_input
from server.native_simulation import canonical_snapshot
from server.profiles import ProfileStore
from server.protobuf_wire import field_bytes, field_packed_uint, field_uint, get_uint, parse_fields
from server.worker_client import SimulationWorker


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def journal_record(data):
    return struct.pack("<I", len(data)) + data


async def wait_until(predicate, timeout=10):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(poll(), timeout)


class ScriptedPeer:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.queue = asyncio.Queue()
        self.observed = []
        self.slot = None
        self.bootstrap = None
        self.pump = asyncio.create_task(self.read_loop())

    async def read_loop(self):
        try:
            while True:
                packet = await p.receive(self.reader)
                self.observed.append(packet)
                self.queue.put_nowait(packet)
        except (asyncio.IncompleteReadError, OSError):
            self.queue.put_nowait((None, b""))

    async def send(self, kind, payload=b""):
        self.writer.write(p.encode(kind, payload))
        await self.writer.drain()

    async def receive(self, kind, timeout=120):
        async def find():
            while True:
                actual, payload = await self.queue.get()
                if actual == kind:
                    return payload
                require(actual not in (None, p.ERROR),
                        f"waiting for {kind}, received {actual}: {payload!r}")
        return await asyncio.wait_for(find(), timeout)

    async def close(self):
        self.writer.close()
        try:
            await asyncio.wait_for(self.writer.wait_closed(), 1)
        except (OSError, TimeoutError):
            pass
        if not self.pump.done():
            self.pump.cancel()
        await asyncio.gather(self.pump, return_exceptions=True)


class Verification:
    def __init__(self, args):
        self.args = args
        self.output = args.output.resolve()
        self.output.relative_to((ROOT / "local").resolve())
        self.output.mkdir(parents=True, exist_ok=False)
        self.manifest = verify_assets(args.assets)
        self.template = GameTemplate.load(args.assets / "map-1v1.pb.gz",
            catalog_path=args.assets / "unit-catalog.json", descriptors_path=args.assets / "descriptors")
        self.audit = Audit(self.output)
        self.events, self.workers, self.peers, self.matches = [], [], [], []
        self.server = None
        self.started = time.perf_counter()
        self.report = {"schema": 1, "passed": False, "utc": datetime.now(timezone.utc).isoformat(),
            "scope": "Windows real native workers and scripted TCP peers; not graphical/manual P2 play",
            "assets": str(args.assets.resolve()), "simulation_sha256": self.manifest["simulation_sha256"],
            "tick_ms": 50, "requested_sequential_matches": args.matches,
            "surrender_frame": args.surrender_frame, "matches": self.matches}
        self.report["source_sha256_at_start"] = self.source_hashes()

    @staticmethod
    def source_hashes():
        return {name: digest((ROOT / name).read_bytes()) for name in (
            "server/dedicated_server.py", "server/worker_client.py", "server/simulation_worker.py",
            "server/native_simulation.py", "tools/verify_worker_rooms.py")}

    def event(self, event, **fields):
        self.events.append(dict(event=event, **fields))
        self.audit(event, **fields)

    async def factory(self, data):
        worker = await SimulationWorker.create(data, self.args.assets / "Simulation.dll")
        self.workers.append(worker)
        return worker

    async def connect(self, name):
        reader, writer = await asyncio.open_connection(*self.address[:2])
        peer = ScriptedPeer(reader, writer)
        self.peers.append(peer)
        await peer.send(p.HELLO, p.hello(p.AUTO_SEAT, "verify_" + uuid.uuid4().hex,
                                       "Scripted native peer", name))
        peer.slot = (await peer.receive(p.WELCOME))[0]
        return peer

    async def pair(self, name):
        peers = (await self.connect(name), await self.connect(name))
        require(tuple(peer.slot for peer in peers) == (0, 1), "incorrect automatic seats")
        await asyncio.gather(*(peer.send(p.LOBBY_READY, b"\x01") for peer in peers))
        for peer, bootstrap in zip(peers, await asyncio.gather(*(peer.receive(p.BOOTSTRAP) for peer in peers))):
            peer.bootstrap = bootstrap
        require(peers[0].bootstrap == peers[1].bootstrap, "peers received different bootstrap bytes")
        room = self.server.rooms[name]
        require(peers[0].bootstrap == room.match.gzip_game_data, "client/server bootstrap mismatch")
        folder = self.output / "matches" / room.match_id
        for peer in peers:
            (folder / f"received-bootstrap-{peer.slot}.pb.gz").write_bytes(peer.bootstrap)
        await asyncio.gather(*(peer.send(p.LOADED, hashlib.sha256(peer.bootstrap).digest()) for peer in peers))
        await asyncio.gather(*(peer.receive(p.START) for peer in peers))
        return {"room": room, "worker": room.sim, "peers": peers, "folder": folder,
                "frames": [], "inputs": [], "started": time.perf_counter()}

    def inputs(self, session, frame, surrender=False):
        room, worker = session["room"], session["worker"]
        bodies = []
        for slot in (0, 1):
            actions = []
            if frame == 0:
                join = field_uint(1, slot) + field_bytes(2, room.match.deck_messages_by_slot[slot])
                army = room.match.armies_by_slot[slot]
                for target, source in ((3, 5), (4, 6)):
                    value = get_uint(army, source)
                    if value:
                        join += field_uint(target, value)
                actions.append(field_bytes(3, join))
            if surrender and slot == 0:
                # AbilityConfig field24 is SelfDestructAbilityConfig. Select its
                # configured key and an owned entity from current native state;
                # no entity IDs, config values, or captured command bytes copied.
                choices = []
                for entity in worker.last_state["entities"]:
                    if entity.get("army") != slot or "type" not in entity:
                        continue
                    for key in self.template.entity_abilities.get(entity["type"], ()):
                        if any(field.number == 24 for field in parse_fields(self.template.abilities[key])):
                            choices.append((entity["id"], entity["type"], key))
                require(choices, "native state contains no owned self-destruct entity")
                entity_id, entity_type, ability = min(choices)
                group = field_uint(1, entity_type) + field_uint(2, ability) + field_packed_uint(3, [entity_id])
                command = field_bytes(1, group) + field_bytes(3, field_bytes(1, b""))
                actions.append(field_bytes(1, command))
                session["surrender"] = dict(frame=frame, entity_id=entity_id, entity_type=entity_type, ability=ability)
            bodies.append(encode_player_input(room.match.identities_by_slot[slot], actions))
        return bodies

    async def submit(self, session, frame, surrender=False):
        bodies = self.inputs(session, frame, surrender)
        await asyncio.gather(*(peer.send(p.INPUT, struct.pack("<I", frame) + body)
                              for peer, body in zip(session["peers"], bodies)))
        session["inputs"].append({"frame": frame, "slot_sha256": [digest(body) for body in bodies]})

    async def advance(self, session, frame, surrender=False):
        await self.submit(session, frame, surrender)
        payloads = await asyncio.gather(*(peer.receive(p.FRAME, 15) for peer in session["peers"]))
        require(payloads[0] == payloads[1], "peer frame bytes differ")
        require(struct.unpack_from("<I", payloads[0])[0] == frame, "noncontiguous public frame")
        require(session["worker"].frame == frame, "public frame preceded successful native step")
        session["frames"].append(payloads[0])

    async def finish_match(self, session, start=0):
        room, worker = session["room"], session["worker"]
        end_limit = self.args.surrender_frame + 60
        for frame in range(start, end_limit):
            await self.advance(session, frame, surrender=frame == self.args.surrender_frame)
            if room.result is not None and frame >= room.result_frame + 19:
                break
        results = await asyncio.gather(*(peer.receive(p.MATCH_END, 10) for peer in session["peers"]))
        require(results[0] == results[1], "peers received different final results")
        result = json.loads(results[0])
        native_result = worker.last_state["game_state"]
        require(result["result"] == native_result, "public result differs from final native state")
        require(native_result["complete"] and native_result["winning_alliance"] == 1
                and native_result["army_conceded_flag"] == 1, "surrender did not produce native defeat")
        require(native_result["game_over_frame"] == self.args.surrender_frame, "wrong native surrender frame")
        # Results and public-name retirement deliberately precede slow native
        # destruction. Observe supervised cleanup separately with a finite bound.
        await wait_until(lambda: any(row["event"] == "worker_released" and row["worker_pid"] == worker.pid
                                    for row in self.events), timeout=10)
        require(worker.closed and worker.process.poll() == 0, "completed native worker not released cleanly")
        require(self.server.rooms.get(room.name) is not room, "completed room still occupies active registry")
        self.capture(session, result=result, native_state=worker.last_state)
        await asyncio.gather(*(peer.close() for peer in session["peers"]))
        await wait_until(lambda: room not in self.server.retired)

    def capture(self, session, *, result=None, native_state=None, crash=None):
        room, worker, folder = session["room"], session["worker"], session["folder"]
        frames = session["frames"]
        reconstructed = bytearray()
        for payload in frames:
            frame, first_size = struct.unpack_from("<II", payload)
            first, second = payload[8:8 + first_size], payload[8 + first_size:]
            reconstructed.extend(journal_record(encode_frame(frame, {0: first, 1: second})))
        journal = (folder / "frames.bin").read_bytes()
        require(journal == reconstructed, "public frames do not reconstruct exact native ordered journal")
        public_journal = b"".join(journal_record(payload) for payload in frames)
        for peer in session["peers"]:
            received = [body for kind, body in peer.observed if kind == p.FRAME]
            require(received == frames, "client frame capture differs from matched frame sequence")
            (folder / f"received-frames-{peer.slot}.bin").write_bytes(public_journal)
        (folder / "submitted-input-digests.json").write_text(json.dumps(session["inputs"], indent=2) + "\n")
        if native_state is not None:
            (folder / "final-native-state.json").write_text(json.dumps(native_state, indent=2) + "\n")
        snapshots = []
        for path in sorted((folder / "snapshots").glob("*.bin")):
            viewer = int(path.stem.split("-")[1])
            parsed = canonical_snapshot(path.read_bytes(), viewer)
            snapshots.append({key: parsed[key] for key in ("frame", "viewer", "canonical_fnv1a64", "game_state")})
        record = {"room": room.name, "match_id": room.match_id, "worker_pid": worker.pid,
            "worker_exit_code": worker.process.poll(), "bootstrap_sha256": digest(room.match.gzip_game_data),
            "raw_game_data_sha256": worker.game_data_sha256, "native_input_journal_sha256": digest(journal),
            "received_frame_journal_sha256": digest(public_journal), "frames": len(frames),
            "both_received_bootstraps_match": True, "both_received_frame_journals_match": True,
            "native_journal_matches_received_frames": True, "result": result,
            "surrender": session.get("surrender"), "snapshots": snapshots, "crash": crash,
            "elapsed_seconds": time.perf_counter() - session["started"]}
        self.matches.append(record)
        (folder / "verification.json").write_text(json.dumps(record, indent=2) + "\n")

    async def isolation(self):
        alpha, beta = await asyncio.gather(self.pair("isolation_failed"), self.pair("isolation_healthy"))
        require(alpha["worker"].pid != beta["worker"].pid, "rooms share one native process")
        for frame in range(3):
            await asyncio.gather(self.advance(alpha, frame), self.advance(beta, frame))
        # This Popen belongs to the worker just created for this verification.
        # No PID lookup or unrelated process termination is used.
        alpha["worker"].process.kill()
        await self.submit(alpha, 3)
        await self.advance(beta, 3)
        errors = await asyncio.gather(*(peer.receive(p.ERROR, 15) for peer in alpha["peers"]))
        require(all(b"simulation error" in error for error in errors), "crashed room did not fail closed")
        await wait_until(lambda: "isolation_failed" not in self.server.rooms)
        require(not any(kind == p.FRAME and struct.unpack_from("<I", body)[0] >= 3
                        for peer in alpha["peers"] for kind, body in peer.observed),
                "failed native frame was published")
        replacement = await self.connect("isolation_failed")
        require(replacement.slot == 0, "same listener did not allocate fresh lobby after worker failure")
        await self.advance(beta, 4)
        await replacement.close()
        await wait_until(lambda: "isolation_failed" not in self.server.rooms)
        self.capture(alpha, crash={"forced_at_next_frame": 3, "failed_frame_not_published": True,
                                  "healthy_survivor_frame": beta["worker"].frame,
                                  "same_listener_fresh_lobby": True})
        await asyncio.gather(*(peer.close() for peer in alpha["peers"]))
        await self.finish_match(beta, start=5)
        print("Native two-room isolation passed; failed worker released and healthy room completed.", flush=True)

    async def run(self):
        try:
            self.server = DedicatedServer(self.template, ProfileStore(self.output / "profiles", self.template),
                sim_factory=self.factory, audit=self.event, data_dir=self.output,
                max_rooms=2, input_timeout=15, audit_state=True)
            self.address = await self.server.start("127.0.0.1", 0)
            self.report["address"] = list(self.address[:2])
            await self.isolation()
            for index in range(self.args.matches):
                session = await self.pair("sequential_reused")
                await self.finish_match(session)
                print(f"Native match {index + 1}/{self.args.matches} completed; worker {session['worker'].pid} exited0; "
                      f"elapsed {time.perf_counter() - self.started:.1f}s.", flush=True)
            require(len(self.matches) == self.args.matches + 2, "unexpected match count")
            require(not self.server.rooms and not self.server.retired, "room registry not empty after completed peers left")
            self.report["passed"] = True
        except BaseException as error:
            self.report["error"] = repr(error)
            self.report["traceback"] = traceback.format_exc()
            raise
        finally:
            if self.server is not None:
                await self.server.close()
            await asyncio.gather(*(peer.close() for peer in self.peers), return_exceptions=True)
            await asyncio.gather(*(worker.close() for worker in self.workers), return_exceptions=True)
            self.report["worker_cleanup"] = [{"pid": worker.pid, "exit_code": worker.process.poll(),
                                              "closed": worker.closed, "failure": worker.failure}
                                             for worker in self.workers]
            self.report["all_workers_reaped"] = all(worker.process.poll() is not None for worker in self.workers)
            self.report["event_counts"] = {event: sum(row["event"] == event for row in self.events)
                for event in sorted({row["event"] for row in self.events})}
            self.report["elapsed_seconds"] = time.perf_counter() - self.started
            self.report["source_sha256_at_finish"] = self.source_hashes()
            self.report["source_files_unchanged_during_run"] = (
                self.report["source_sha256_at_start"] == self.report["source_sha256_at_finish"])
            self.report["passed"] = self.report["passed"] and self.report["all_workers_reaped"]
            (self.output / "verification.json").write_text(json.dumps(self.report, indent=2) + "\n")
            self.audit.close()
            print(f"Evidence: {self.output / 'verification.json'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=ROOT / "local/assets/p0-export03")
    parser.add_argument("--output", type=Path, default=ROOT / "local" / (
        "native-worker-rooms-" + datetime.now().strftime("%Y%m%d-%H%M%S")))
    parser.add_argument("--matches", type=int, default=20)
    parser.add_argument("--surrender-frame", type=int, default=140)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("requires Windows and a locally imported exact-build native asset bundle")
    if not 1 <= args.matches <= 100 or not 5 <= args.surrender_frame <= 1000:
        parser.error("matches must be1..100 and surrender-frame5..1000")
    asyncio.run(Verification(args).run())


if __name__ == "__main__":
    main()
