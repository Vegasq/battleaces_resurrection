"""Process-isolation tests use synthetic bytes unless native tests are opted in."""
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import unittest

from server import simulation_worker as ipc
from server.worker_client import SimulationWorker, WorkerError, WorkerTimeout
from server.protobuf_wire import field_bytes, field_packed_uint, field_uint

ROOT = Path(__file__).resolve().parents[1]


def frame(number):
    return field_uint(1, number) + field_uint(2, 20) + field_uint(3, 50)


class WorkerProtocolTests(unittest.TestCase):
    def test_binary_payload_is_exact_and_versioned(self):
        payload = bytes(range(256)) * 3
        packet = ipc.encode_message(ipc.STEP, 7, 19, {"dt_ms": 50}, payload)
        self.assertEqual(ipc.read_message(io.BytesIO(packet)), (ipc.STEP, 0, 7, 19, {"dt_ms": 50}, payload))

    def test_header_rejects_oversize_before_reading_payload(self):
        packet = ipc.HEADER.pack(ipc.MAGIC, ipc.VERSION, ipc.CREATE, 0, 1, 2, -1, ipc.MAX_PAYLOAD + 1)
        with self.assertRaisesRegex(ipc.ProtocolError, "limit"):
            ipc.read_message(io.BytesIO(packet))
        changed = bytearray(ipc.encode_message(ipc.CREATE, 1, -1)); changed[4] = 99
        with self.assertRaisesRegex(ipc.ProtocolError, "version"):
            ipc.read_message(io.BytesIO(changed))

    def test_truncation_and_invalid_json_rejected(self):
        packet = ipc.encode_message(ipc.CREATE, 1, -1, payload=b"test")
        with self.assertRaisesRegex(ipc.ProtocolError, "truncated"):
            ipc.read_message(io.BytesIO(packet[:-1]))
        for payload in (b"[]", b'{"x":NaN}', b"{"):
            with self.subTest(payload=payload), self.assertRaises(ipc.ProtocolError):
                ipc.decode_metadata(payload)

    def test_synthetic_cli_requires_two_explicit_gates(self):
        environment = os.environ.copy(); environment.pop("BA_ENABLE_SYNTHETIC_WORKER_TESTS", None)
        result = subprocess.run([sys.executable, "-m", "server.simulation_worker", "--stdio", "--test-backend"],
            cwd=ROOT, env=environment, input=b"", capture_output=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"explicit test environment gate", result.stderr)


class WorkerIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.workers = []

    async def make(self, data=b"synthetic world", **kwargs):
        worker = await SimulationWorker.create(data, _test_backend=True, **kwargs)
        self.workers.append(worker)
        return worker

    async def asyncTearDown(self):
        await asyncio.gather(*(worker.close() for worker in self.workers))
        for worker in self.workers:
            self.assertIsNotNone(worker.process.poll())
            self.assertFalse(worker._stderr_thread.is_alive())

    async def test_two_workers_have_independent_worlds_and_lifetimes(self):
        first, second = await asyncio.gather(self.make(b"world one"), self.make(b"world two"))
        self.assertNotEqual(first.pid, second.pid)
        result = await first.process_frame(frame(0))
        self.assertEqual((result.frame, first.frame, second.frame), (0, 0, -1))
        self.assertNotEqual(first.game_data_sha256, second.game_data_sha256)
        await first.close()
        self.assertEqual((await second.process_frame(frame(0))).state["resources"][0]["primary"], 1)
        self.assertTrue((await second.snapshot()).startswith(b"SYNTHETIC"))
        self.assertEqual((await second.state(include_entities=True))["entities"][0]["army"], 0)

    async def test_native_crash_never_acknowledges_frame_or_kills_other_world(self):
        first, second = await asyncio.gather(self.make(), self.make())
        await first._test_control("crash_next_step")
        with self.assertRaises(WorkerError):
            await first.process_frame(frame(0))
        self.assertEqual(first.frame, -1)
        self.assertEqual(first.process.poll(), 91)
        self.assertEqual((await second.process_frame(frame(0))).frame, 0)

    async def test_hung_step_times_out_without_blocking_event_loop(self):
        first, second = await asyncio.gather(self.make(request_timeout=0.15), self.make())
        await first._test_control("hang_next_step")
        ticks = 0
        async def heartbeat():
            nonlocal ticks
            for _ in range(10):
                await asyncio.sleep(0.01); ticks += 1
        heartbeat_task = asyncio.create_task(heartbeat())
        started = time.monotonic()
        with self.assertRaises(WorkerTimeout):
            await first.process_frame(frame(0))
        await heartbeat_task
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(ticks, 10)
        self.assertEqual(first.frame, -1)
        self.assertEqual((await second.process_frame(frame(0))).frame, 0)

    async def test_step_exception_is_terminal_not_retryable(self):
        worker = await self.make()
        await worker._test_control("error_next_step")
        with self.assertRaisesRegex(WorkerError, "synthetic native-step error"):
            await worker.process_frame(frame(0))
        with self.assertRaises(WorkerError):
            await worker.process_frame(frame(0))
        self.assertEqual(worker.frame, -1)

    async def test_order_and_dt_rejected_locally_without_touching_world(self):
        worker = await self.make()
        for actions, dt in ((frame(1), None), (frame(0), 49)):
            with self.assertRaises(ValueError):
                await worker.process_frame(actions, dt_ms=dt)
        self.assertEqual(worker.frame, -1)
        self.assertEqual((await worker.process_frame(frame(0), dt_ms=50)).frame, 0)

    async def test_cancellation_kills_and_reaps_inflight_worker(self):
        worker = await self.make(request_timeout=30)
        await worker._test_control("hang_next_step")
        pending = asyncio.create_task(worker.process_frame(frame(0)))
        await asyncio.sleep(0.05)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertIsNotNone(worker.process.poll())
        self.assertEqual(worker.frame, -1)

    async def test_stuck_native_destructor_is_forced_closed(self):
        worker = await self.make(close_timeout=0.15)
        await worker._test_control("hang_close")
        started = time.monotonic()
        await worker.close()
        self.assertLess(time.monotonic() - started, 3)
        self.assertIsNotNone(worker.process.poll())
        await worker.close()  # Idempotent cleanup.

    async def test_close_interrupts_inflight_hang_without_waiting_full_request_timeout(self):
        worker = await self.make(request_timeout=30, close_timeout=0.15)
        await worker._test_control("hang_next_step")
        pending = asyncio.create_task(worker.process_frame(frame(0)))
        await asyncio.sleep(0.03)
        started = time.monotonic()
        await worker.close()
        with self.assertRaises(WorkerError):
            await pending
        self.assertLess(time.monotonic() - started, 3)
        self.assertIsNotNone(worker.process.poll())

    async def test_native_stderr_is_drained_with_bounded_retention(self):
        worker = await self.make()
        await worker._test_control("stderr_flood")
        self.assertLessEqual(len(worker.stderr_tail.encode()), 32768)
        self.assertIn("synthetic stderr drain test", worker.stderr_tail)
        self.assertEqual((await worker.process_frame(frame(0))).frame, 0)

    @unittest.skipUnless(os.name == "nt", "Windows job-object cleanup test")
    async def test_abrupt_parent_exit_kills_owned_worker_job(self):
        import ctypes as c
        from ctypes import wintypes as w
        code = ("import asyncio,sys\nfrom server.worker_client import SimulationWorker\n"
                "async def main():\n"
                " worker=await SimulationWorker.create(b'synthetic parent-death test',_test_backend=True)\n"
                " print(worker.pid,flush=True)\n"
                " await asyncio.to_thread(sys.stdin.buffer.read,1)\n"
                "asyncio.run(main())\n")
        helper = subprocess.Popen([sys.executable, "-u", "-c", code], cwd=ROOT,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        kernel = c.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]; kernel.OpenProcess.restype = w.HANDLE
        kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]; kernel.WaitForSingleObject.restype = w.DWORD
        kernel.TerminateProcess.argtypes = [w.HANDLE, w.UINT]; kernel.TerminateProcess.restype = w.BOOL
        kernel.CloseHandle.argtypes = [w.HANDLE]; kernel.CloseHandle.restype = w.BOOL
        handle = None
        try:
            line = await asyncio.wait_for(asyncio.to_thread(helper.stdout.readline), 5)
            self.assertTrue(line.strip().isdigit(), "helper did not create its owned worker")
            # The PID came directly from this test's newly created helper. Hold
            # a process handle before ending the parent, avoiding PID reuse.
            handle = kernel.OpenProcess(0x101001, False, int(line))
            self.assertTrue(handle)
            self.assertEqual(kernel.WaitForSingleObject(handle, 0), 258)  # Still alive.
            helper.terminate()
            await asyncio.to_thread(helper.wait, timeout=5)
            self.assertEqual(await asyncio.to_thread(kernel.WaitForSingleObject, handle, 5000), 0)
        finally:
            if helper.poll() is None:
                helper.terminate()
                await asyncio.to_thread(helper.wait, timeout=5)
            if handle:
                if kernel.WaitForSingleObject(handle, 0) == 258:
                    kernel.TerminateProcess(handle, 92)  # Cleanup only this test's owned worker.
                kernel.CloseHandle(handle)
            for stream in (helper.stdin, helper.stdout, helper.stderr): stream.close()


@unittest.skipUnless(os.name == "nt" and os.environ.get("BA_RUN_NATIVE_WORKER_TESTS") == "1",
                     "native worker test requires explicit BA_RUN_NATIVE_WORKER_TESTS=1 on Windows")
class NativeWorkerSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_native_worlds_exact_inputs_selected_unit_and_cleanup(self):
        from server.game_data import GameTemplate, InputValidation, encode_player_input
        from server.native_simulation import canonical_snapshot
        import ctypes
        assets = Path(os.environ.get("BA_WORKER_TEST_ASSETS", ROOT / "local/assets/p0-export03"))
        required = (assets / "Simulation.dll", assets / "map-1v1.pb.gz", assets / "unit-catalog.json")
        if not all(path.is_file() for path in required):
            self.skipTest("native worker assets missing; run local asset import first")
        template = GameTemplate.load(required[1], catalog_path=required[2], descriptors_path=assets / "descriptors")
        roster = [{"slot": slot, "player_id": slot + 1, "name": f"Worker Player {slot + 1}"} for slot in (0, 1)]
        match = template.build_match(roster, template.default_decks, seed=12345678, game_name="worker-smoke")
        first, second = await asyncio.gather(SimulationWorker.create(match.raw_game_data, required[0]),
                                             SimulationWorker.create(match.raw_game_data, required[0]))
        report = {"pids": [first.pid, second.pid], "input_game_data_sha256": hashlib.sha256(match.raw_game_data).hexdigest(),
                  "matching_before_command": [], "command_frame": 200}
        try:
            self.assertNotEqual(first.pid, second.pid)
            initial = await first.state(31, include_entities=True)
            self.assertEqual(initial["frame"], 0xFFFFFFFF)
            self.assertTrue(initial["entities"])
            validators = [InputValidation(match, template), InputValidation(match, template)]
            for number in range(221):
                messages = []
                for changed in (False, True):
                    by_slot = {}
                    for slot in (0, 1):
                        actions = []
                        if number == 0:
                            join = field_uint(1, slot) + field_bytes(2, match.deck_messages_by_slot[slot])
                            actions.append(field_bytes(3, join))
                        if changed and slot == 0 and number == 200:
                            hq = next(entity["id"] for entity in second.last_state["entities"]
                                      if entity.get("army") == 0 and entity.get("type") == 3)
                            group = field_uint(1, 3) + field_uint(2, 34) + field_packed_uint(3, [hq])
                            actions.append(field_bytes(1, field_bytes(1, group) + field_bytes(3, field_bytes(1, b""))))
                        by_slot[slot] = encode_player_input(match.identities_by_slot[slot], actions)
                    messages.append(validators[int(changed)].encode_frame(number, by_slot))
                results = await asyncio.gather(first.process_frame(messages[0]), second.process_frame(messages[1]))
                if number in (0, 100, 199):
                    self.assertEqual(results[0].state["canonical_fnv1a64"], results[1].state["canonical_fnv1a64"])
                    report["matching_before_command"].append(number)
            unit_type = match.decks_by_slot[0][0]
            expected = template.catalog[unit_type]["primary_cost"]
            delta = second.last_state["resources"][0]["primary"] - first.last_state["resources"][0]["primary"]
            self.assertEqual(delta, -expected)
            new_units = [entity for entity in second.last_state["entities"] if entity.get("army") == 0 and entity.get("type") == unit_type]
            self.assertEqual(len(new_units), 1)
            raw = await second.snapshot(0)
            self.assertEqual(canonical_snapshot(raw, 0)["frame"], 220)
            getmodule = ctypes.WinDLL("kernel32").GetModuleHandleW
            getmodule.argtypes = [ctypes.c_wchar_p]; getmodule.restype = ctypes.c_void_p
            self.assertFalse(getmodule("Simulation.dll"), "native DLL must remain outside coordinator")
            await first.close()
            self.assertEqual((await second.process_frame(frame(221))).frame, 221)
            report.update(passed=True, selected_unit=unit_type, primary_difference=delta,
                          created_entity_ids=[entity["id"] for entity in new_units],
                          coordinator_native_dll_absent=True, survivor_frame=221)
        finally:
            await asyncio.gather(first.close(), second.close())
            report["exit_codes"] = [first.process.poll(), second.process.poll()]
            output = ROOT / "local/worker-native-smoke.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2) + "\n")
        self.assertEqual(report["exit_codes"], [0, 0])


if __name__ == "__main__":
    unittest.main()
