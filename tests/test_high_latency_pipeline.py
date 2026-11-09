"""Deterministic contract model of the two-peer authoritative input pipeline.

No sockets, game assets, native DLLs, wall-clock waits or live host are used.
The actual server deadline and input-window validator are reused. The client
model follows lan_transport's initial inputs, one unpresented output, startup
reserve and online_frame_clock's50ms/25ms presentation rules. Link delays are
illustrative, not recovered RTT measurements from the Korea match. Native
two-client evidence remains necessary before accepting a production change.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
import hashlib
import heapq
import unittest

from server.dedicated_server import next_frame_deadline
from server.protocol import validate_input_window

STEP_US = 50_000


@dataclass(frozen=True)
class PeerTiming:
    down_us: int
    up_us: int
    callback_us: int = 1_000
    native_us: int = 4_000


class PresentationClock:
    """Behavioral counterpart of the separately tested native BasicClock."""
    def __init__(self):
        self.deadline = self.last = None

    def due(self, now):
        return now if self.deadline is None else max(self.deadline, self.last + 25_000)

    def published(self, now):
        if self.deadline is None:
            self.deadline = now
        self.deadline += STEP_US
        if now > self.deadline + STEP_US:
            self.deadline = now
        self.last = now


class Pipeline:
    def __init__(self, timings, *, window=6, peer_windows=None, replenish="apply", frames=600,
                 worker_us=12_000, server_poll_us=5_000, wall_commands=None):
        if len(timings) != 2 or replenish not in ("apply", "receipt"):
            raise ValueError("two peers and an explicit replenishment policy required")
        validate_input_window(window)
        peer_windows = (window, window) if peer_windows is None else tuple(peer_windows)
        if len(peer_windows) != 2 or max(map(validate_input_window, peer_windows)) != window:
            raise ValueError("room bound must equal maximum frozen peer window")
        if frames < 100 or worker_us <= 0 or server_poll_us <= 0:
            raise ValueError("bounded positive model workload required")
        self.timings, self.window, self.replenish = timings, window, replenish
        self.peer_windows = peer_windows
        # None retains the fixed authored-frame journal fixture. Explicit
        # wall-clock commands are a separate fixture: their assigned frames
        # should change with lead, and their journal hashes may therefore differ.
        self.wall_commands, self.command_records = wall_commands, {}
        self.limit, self.worker_us = frames, worker_us
        self.server_poll_us, self.server_poll_anchor = server_poll_us, 0
        self.events, self.serial, self.now = [], 0, 0
        self.server_frame, self.server_deadline = 0, STEP_US
        self.server_busy, self.server_generation, self.wait_started = False, 0, None
        self.next_input, self.pending = [0, 0], {}
        self.server_rows, self.server_payloads = [], []
        self.max_pending, self.max_input_ahead = 0, 0
        self.max_peer_input_ahead = [0, 0]
        self.clients = [dict(started=False, received=0, applied=0, published=-1,
                             next_submit=0, frames=deque(), inflight=None,
                             wake=None, generation=0, last_tick=-1, clock=PresentationClock(),
                             publications=[], payloads=[], receipts=[], applies=[], max_queue=0,
                             commands=deque())
                        for _ in timings]
        self.last_delivery = {}

    def schedule(self, when, kind, slot=None, data=None):
        self.serial += 1
        heapq.heappush(self.events, (when, self.serial, kind, slot, data))

    def deliver(self, slot, direction, when, kind, data):
        # Both directions represent ordered TCP byte streams, not reorderable
        # datagrams. A later packet cannot overtake an earlier one.
        key = slot, direction
        when = max(when, self.last_delivery.get(key, -1) + 1)
        self.last_delivery[key] = when
        self.schedule(when, kind, slot, data)

    def wake_server(self):
        if self.server_busy or self.server_frame >= self.limit:
            return
        self.server_generation += 1
        # The real coroutine checks on a5ms sleep and resumes that polling
        # after each awaited worker operation. Inputs do not wake it directly.
        when = max(self.now, self.server_deadline, self.server_poll_anchor + self.server_poll_us)
        polls = (when - self.server_poll_anchor + self.server_poll_us - 1) // self.server_poll_us
        self.schedule(self.server_poll_anchor + polls * self.server_poll_us,
                      "server", data=self.server_generation)

    def wake_client(self, slot, when):
        client, timing = self.clients[slot], self.timings[slot]
        when = max(when, client["last_tick"] + timing.callback_us)
        when = ((when + timing.callback_us - 1) // timing.callback_us) * timing.callback_us
        if client["wake"] is not None and client["wake"] <= when:
            return
        client["wake"] = when
        client["generation"] += 1
        self.schedule(when, "client", slot, client["generation"])

    def submit(self, slot, frame):
        client = self.clients[slot]
        assert frame == client["next_submit"], "local input duplicated or reordered"
        client["next_submit"] += 1
        if self.wall_commands is None:
            # Fixed authored inputs prove log identity, not physical command delay.
            command = str(frame in (60, 120))
        else:
            pending = [client["commands"].popleft() for _ in range(min(256, len(client["commands"])))]
            for identity in pending:
                self.command_records[identity].update(frame=frame, submitted_us=self.now)
            command = ",".join(pending)
        payload = f"peer={slot};frame={frame};step=50;command={command}".encode()
        self.deliver(slot, "up", self.now + self.timings[slot].up_us, "input", (frame, payload))

    def client_tick(self, slot):
        client, timing = self.clients[slot], self.timings[slot]
        client["last_tick"] = self.now
        # GameServer.ProcessUpdate runs before PresentAvailableSimFrame. A new
        # input can be pushed only after the previous output was presented.
        if client["inflight"] is None and client["frames"] and (
                client["applied"] or len(client["frames"]) >= 2):
            frame, payload = client["frames"].popleft()
            assert frame == client["applied"] == client["published"] + 1
            client["applied"] += 1
            client["applies"].append((frame, self.now))
            client["inflight"] = frame, self.now + timing.native_us, payload
            if self.replenish == "apply":
                self.submit(slot, frame + self.peer_windows[slot])
        if client["inflight"] is not None:
            frame, available, payload = client["inflight"]
            due = max(available, client["clock"].due(self.now))
            if self.now >= due:
                assert frame == client["published"] + 1
                client["published"] = frame
                client["publications"].append((frame, self.now))
                client["payloads"].append(payload)
                client["clock"].published(self.now)
                client["inflight"] = None
                if client["frames"]:
                    self.wake_client(slot, self.now + timing.callback_us)
            else:
                self.wake_client(slot, due)

    def run(self):
        for slot, timing in enumerate(self.timings):
            self.deliver(slot, "down", timing.down_us, "start", None)
        for when, slot, identity in self.wall_commands or ():
            if when < 0 or slot not in (0, 1) or not isinstance(identity, str) or not identity:
                raise ValueError("bounded wall-clock command fixture required")
            if identity in self.command_records:
                raise ValueError("wall-clock command identities must be unique")
            self.command_records[identity] = dict(slot=slot, enqueued_us=when)
            self.schedule(when, "command", slot, identity)
        self.wake_server()
        while self.events:
            self.now, _, kind, slot, data = heapq.heappop(self.events)
            assert self.now < self.limit * 2_000_000, "pipeline deadlock/slow-motion bound"
            if kind == "start":
                self.clients[slot]["started"] = True
                for frame in range(self.peer_windows[slot]):
                    self.submit(slot, frame)
            elif kind == "command":
                self.clients[slot]["commands"].append(data)
            elif kind == "input":
                frame, payload = data
                assert frame == self.next_input[slot], "server input must be contiguous"
                assert self.server_frame <= frame < self.server_frame + self.peer_windows[slot], "server future-input bound widened"
                self.max_input_ahead = max(self.max_input_ahead, frame - self.server_frame)
                self.max_peer_input_ahead[slot] = max(self.max_peer_input_ahead[slot], frame - self.server_frame)
                self.next_input[slot] += 1
                bucket = self.pending.setdefault(frame, {})
                assert slot not in bucket
                bucket[slot] = payload
                self.max_pending = max(self.max_pending, len(self.pending))
                self.wake_server()
            elif kind == "server":
                if data != self.server_generation or self.server_busy or self.server_frame >= self.limit:
                    continue
                self.server_poll_anchor = self.now
                if len(self.pending.get(self.server_frame, {})) != 2:
                    if self.wait_started is None:
                        self.wait_started = self.now
                    continue
                self.server_busy = True
                wait = 0 if self.wait_started is None else self.now - self.wait_started
                self.wait_started = None
                self.schedule(self.now + self.worker_us, "completed", data=(self.server_frame, wait))
            elif kind == "completed":
                frame, wait = data
                assert frame == self.server_frame
                inputs = self.pending.pop(frame)
                payload = (frame, tuple(inputs[peer] for peer in (0, 1)))
                self.server_payloads.append(payload)
                self.server_rows.append(dict(frame=frame, completed_us=self.now, input_wait_us=wait))
                for record in self.command_records.values():
                    if record.get("frame") == frame:
                        record["authoritative_us"] = self.now
                self.server_frame += 1
                self.server_busy = False
                self.server_poll_anchor = self.now
                deadline, _ = next_frame_deadline(self.server_deadline / 1e6, self.now / 1e6, .05)
                self.server_deadline = round(deadline * 1e6)
                for peer, timing in enumerate(self.timings):
                    self.deliver(peer, "down", self.now + timing.down_us, "frame", payload)
                self.wake_server()
            elif kind == "frame":
                client = self.clients[slot]
                frame, payload = data
                assert client["started"] and frame == client["received"]
                client["received"] += 1
                client["frames"].append((frame, data))
                client["receipts"].append((frame, self.now))
                client["max_queue"] = max(client["max_queue"], len(client["frames"]))
                assert client["max_queue"] <= 64, "client receive queue exceeded64 authoritative frames"
                if self.replenish == "receipt":
                    self.submit(slot, frame + self.peer_windows[slot])
                self.wake_client(slot, self.now)
            elif kind == "client":
                client = self.clients[slot]
                if data != client["generation"]:
                    continue
                client["wake"] = None
                self.client_tick(slot)
            else:
                raise AssertionError(kind)
            if all(c["published"] == self.limit - 1 for c in self.clients):
                break
        assert self.server_frame == self.limit
        assert self.max_pending <= self.window
        assert all(c["received"] == c["applied"] == self.limit for c in self.clients)
        assert all(c["payloads"] == self.server_payloads for c in self.clients)
        assert all("authoritative_us" in record for record in self.command_records.values())
        return self

    def command_metrics(self):
        publications = [dict(client["publications"]) for client in self.clients]
        return {identity: dict(record,
                               owner_publication_us=publications[record["slot"]][record["frame"]],
                               owner_latency_ms=(publications[record["slot"]][record["frame"]] - record["enqueued_us"]) / 1000)
                for identity, record in self.command_records.items()}

    def summary(self):
        first, last = self.server_rows[100], self.server_rows[-1]
        hz = (last["frame"] - first["frame"]) * 1e6 / (last["completed_us"] - first["completed_us"])
        long = [r["frame"] for r in self.server_rows[100:] if r["input_wait_us"] > 200_000]
        return dict(window=self.window, peer_windows=list(self.peer_windows),
                    replenishment=self.replenish, steady_server_hz=round(hz, 6),
                    long_waits=len(long), long_wait_frame_differences=dict(Counter(b-a for a, b in zip(long, long[1:]))),
                    maximum_input_ahead=self.max_input_ahead, maximum_pending_frames=self.max_pending,
                    maximum_peer_input_ahead=list(self.max_peer_input_ahead),
                    authoritative_sha256=hashlib.sha256(repr(self.server_payloads).encode()).hexdigest(),
                    client_publication_counts=[len(c["publications"]) for c in self.clients],
                    native_output_limit=1, simulation_step_ms=50)


class HighLatencyPipelineTests(unittest.TestCase):
    def test_low_latency_original_pipeline_has_no_regression(self):
        case = Pipeline((PeerTiming(65_000,65_000),PeerTiming(80_000,80_000))).run()
        self.assertGreater(case.summary()["steady_server_hz"], 19)

    def test_release_six_frame_pipeline_reproduces_periodic_slowdown(self):
        case = Pipeline((PeerTiming(65_000,65_000),PeerTiming(237_500,237_500))).run()
        report = case.summary()
        self.assertGreater(report["steady_server_hz"], 12)
        self.assertLess(report["steady_server_hz"], 13)
        self.assertGreater(report["long_waits"], 60)
        self.assertGreater(report["long_wait_frame_differences"].get(6,0), 60)

    def test_receipt_replenishment_alone_does_not_invent_latency_budget(self):
        timings = (PeerTiming(65_000,65_000),PeerTiming(237_500,237_500))
        before = Pipeline(timings).run()
        receipt = Pipeline(timings,replenish="receipt").run()
        self.assertGreaterEqual(receipt.summary()["steady_server_hz"], before.summary()["steady_server_hz"])
        self.assertLess(receipt.summary()["steady_server_hz"], 19)
        self.assertEqual(before.server_payloads,receipt.server_payloads)

    def test_actual_adaptive_policy_preserves_bounds_and_cadence(self):
        from server.latency_policy import select_input_window
        window = select_input_window(6,[130,425])
        self.assertEqual(window,11)
        timings = (PeerTiming(65_000,65_000),PeerTiming(237_500,237_500))
        fixed = Pipeline(timings).run()
        for replenish in ("apply","receipt"):
            case = Pipeline(timings,window=window,replenish=replenish).run()
            self.assertGreater(case.summary()["steady_server_hz"],19)
            self.assertLess(case.summary()["steady_server_hz"],21)
            self.assertEqual(case.server_payloads,fixed.server_payloads)
            self.assertLess(case.max_input_ahead,window)

    def test_the_existing_cap_remains_real_and_is_not_a_universal_fix(self):
        from server.latency_policy import select_input_window
        window=select_input_window(6,[130,1000])
        self.assertEqual(window,12)
        case=Pipeline((PeerTiming(65_000,65_000),PeerTiming(500_000,500_000)),window=window).run()
        self.assertLess(case.summary()["steady_server_hz"],19)
        self.assertLess(case.max_input_ahead,12)

    def test_headroom_covers_asymmetric_link_and_sixty_hz_callbacks(self):
        from server.latency_policy import select_input_window
        timings = (PeerTiming(65_000,65_000,callback_us=16_667,native_us=12_000),
                   PeerTiming(300_000,175_000,callback_us=16_667,native_us=12_000))
        fixed = Pipeline(timings).run()
        adaptive = Pipeline(timings,window=select_input_window(6,[130,425])).run()
        self.assertLess(fixed.summary()["steady_server_hz"],14)
        self.assertGreater(adaptive.summary()["steady_server_hz"],19.9)
        self.assertEqual(fixed.server_payloads,adaptive.server_payloads)

    def test_slow_consumer_backpressure_is_a_separate_bounded_limitation(self):
        from server.latency_policy import select_input_window
        timings = (PeerTiming(65_000,65_000,callback_us=31_250),
                   PeerTiming(300_000,175_000,callback_us=31_250))
        window = select_input_window(6,[130,425])
        protected = Pipeline(timings,window=window).run()
        self.assertLessEqual(protected.summary()["steady_server_hz"],16.1)
        self.assertTrue(all(client["max_queue"] < window for client in protected.clients))
        # Decoupling replenishment alone hides the consumer limit from the
        # server, eventually exceeding the unchanged native64-frame queue.
        with self.assertRaisesRegex(AssertionError,"client receive queue exceeded64"):
            Pipeline(timings,window=window,replenish="receipt").run()

    def test_actual_peer_policy_preserves_cadence_and_fixed_authored_journals(self):
        from server.latency_policy import select_input_windows
        windows = select_input_windows(6, {0:143, 1:489})
        self.assertEqual(windows, {0:6, 1:12})
        timings = (PeerTiming(65_000,65_000,callback_us=16_667,native_us=12_000),
                   PeerTiming(300_000,175_000,callback_us=16_667,native_us=12_000))
        shared = Pipeline(timings,window=12).run()
        own = Pipeline(timings,window=max(windows.values()),
                       peer_windows=[windows[slot] for slot in (0,1)]).run()
        self.assertGreater(own.summary()["steady_server_hz"],19.9)
        self.assertEqual(shared.server_payloads,own.server_payloads)
        self.assertEqual(own.summary()["client_publication_counts"],[600,600])
        self.assertEqual(own.summary()["long_waits"],0)
        self.assertTrue(all(ahead < own.peer_windows[slot]
                            for slot,ahead in enumerate(own.max_peer_input_ahead)))

    def test_same_wallclock_commands_reduce_only_the_fast_peers_avoidable_lead(self):
        from server.latency_policy import select_input_windows
        windows = select_input_windows(6, {0:143, 1:489})
        timings = (PeerTiming(65_000,65_000,callback_us=16_667,native_us=12_000),
                   PeerTiming(300_000,175_000,callback_us=16_667,native_us=12_000))
        commands = [(10_000_000,0,"fast"),(10_000_000,1,"slow")]
        shared = Pipeline(timings,window=12,wall_commands=commands).run()
        own = Pipeline(timings,window=12,peer_windows=[windows[slot] for slot in (0,1)],
                       wall_commands=commands).run()
        before,after = shared.command_metrics(),own.command_metrics()
        self.assertAlmostEqual(before["fast"]["owner_latency_ms"] - after["fast"]["owner_latency_ms"],300,delta=1)
        self.assertEqual(before["slow"],after["slow"])
        self.assertEqual(before["fast"]["enqueued_us"],after["fast"]["enqueued_us"])
        self.assertEqual(before["fast"]["frame"] - after["fast"]["frame"],6)
        # Both client journals equal their own authoritative source, as checked
        # by run(); across policies this wall-clock command changes target frame.
        self.assertNotEqual(shared.server_payloads,own.server_payloads)
        self.assertGreater(own.summary()["steady_server_hz"],19.9)

    def test_room_maximum_does_not_allow_fast_peer_to_exceed_its_own_bound(self):
        case = Pipeline((PeerTiming(65_000,65_000),PeerTiming(300_000,175_000)),
                        window=12,peer_windows=(6,12))
        # Fast inputs0..5 arrive130000..130005us, while frame0 still awaits
        # the slow peer. Frame6 is contiguous and below the room's maximum12,
        # but outside this recipient's immutable six-frame window.
        case.schedule(130_006,"input",0,(6,b"forged future input"))
        with self.assertRaisesRegex(AssertionError,"server future-input bound widened"):
            case.run()


if __name__ == "__main__":
    unittest.main()
