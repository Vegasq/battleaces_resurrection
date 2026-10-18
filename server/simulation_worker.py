"""Private stdio worker: one native simulation world for one match.

Run through worker_client.SimulationWorker, never as a network service. Native
stdout is redirected before loading the DLL so it cannot corrupt the IPC pipe.
The synthetic backend requires both an explicit switch and a test environment
gate; production never selects it automatically or falls back to it.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import struct
import sys
import threading

MAGIC = b"BAWK"
VERSION = 2
HEADER = struct.Struct("<4sBBHIIiI")
MAX_METADATA = 8 * 1024 * 1024
MAX_PAYLOAD = 32 * 1024 * 1024
CREATE, STEP, STATE, SNAPSHOT, CLOSE, TEST_CONTROL, BOT_INPUT = range(1, 8)
RESPONSE = 0x80
ERROR = 1
OPERATIONS = frozenset((CREATE, STEP, STATE, SNAPSHOT, CLOSE, TEST_CONTROL, BOT_INPUT))


class ProtocolError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise ProtocolError(reason)


def encode_message(operation, request_id, frame, metadata=None, payload=b"", *, flags=0):
    require(type(request_id) is int and 0 < request_id <= 0xFFFFFFFF, "request ID out of range")
    require(type(frame) is int and -1 <= frame <= 0x7FFFFFFF, "frame out of range")
    require(isinstance(payload, bytes) and len(payload) <= MAX_PAYLOAD, "payload exceeds limit")
    require(isinstance(metadata or {}, dict), "metadata must be an object")
    encoded = json.dumps(metadata or {}, separators=(",", ":"), allow_nan=False).encode("utf-8")
    require(len(encoded) <= MAX_METADATA, "metadata exceeds limit")
    return HEADER.pack(MAGIC, VERSION, operation, flags, request_id, len(encoded), frame, len(payload)) + encoded + payload


def decode_header(data):
    require(len(data) == HEADER.size, "truncated header")
    magic, version, operation, flags, request_id, metadata_size, frame, payload_size = HEADER.unpack(data)
    require(magic == MAGIC and version == VERSION, "worker protocol version/magic mismatch")
    require(operation & ~RESPONSE in OPERATIONS, "unknown operation")
    require(flags in (0, ERROR) and request_id > 0 and frame >= -1, "invalid header values")
    require(0 < metadata_size <= MAX_METADATA and payload_size <= MAX_PAYLOAD, "message exceeds limit")
    return operation, flags, request_id, frame, metadata_size, payload_size


def decode_metadata(data):
    try:
        value = json.loads(data, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (ValueError, RecursionError, UnicodeError) as error:
        raise ProtocolError("invalid worker JSON") from error
    require(isinstance(value, dict), "worker metadata must be an object")
    return value


def read_exact(stream, size, *, eof_ok=False):
    chunks = bytearray()
    while len(chunks) < size:
        part = stream.read(size - len(chunks))
        if not part:
            if eof_ok and not chunks:
                return None
            raise ProtocolError("truncated worker message")
        chunks.extend(part)
    return bytes(chunks)


def read_message(stream):
    header = read_exact(stream, HEADER.size, eof_ok=True)
    if header is None:
        return None
    operation, flags, request_id, frame, metadata_size, payload_size = decode_header(header)
    metadata = decode_metadata(read_exact(stream, metadata_size))
    payload = read_exact(stream, payload_size)
    return operation, flags, request_id, frame, metadata, payload


def write_packet(stream, packet):
    remaining = memoryview(packet)
    while remaining:
        written = stream.write(remaining)
        if not written:
            raise ProtocolError("worker pipe write failed")
        remaining = remaining[written:]
    stream.flush()


def isolate_protocol_stdout():
    """Retain the pipe privately; redirect both CRT fd1 and Windows stdout handle."""
    sys.stdout.flush()
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    if os.name == "nt":
        import ctypes
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(protocol.fileno(), os.O_BINARY)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.SetStdHandle.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        kernel.SetStdHandle.restype = ctypes.c_int
        if not kernel.SetStdHandle(0xFFFFFFF5, msvcrt.get_osfhandle(sys.stderr.fileno())):
            raise OSError(ctypes.get_last_error(), "SetStdHandle failed")
    return protocol


class SyntheticSimulation:
    """Explicit fault-injection test double. Never a native-game substitute."""
    def __init__(self, data):
        self.frame = -1
        self.game_time_seconds = 0
        self.game_data_sha256 = hashlib.sha256(data).hexdigest()
        self.dll_sha256 = "synthetic-test-backend"
        self.fail_next = None
        self.hang_close = False
        self.complete_frame = None

    def process_frame(self, actions, dt_ms=None):
        from .native_simulation import _protobuf_header
        if self.fail_next == "crash":
            os._exit(91)
        if self.fail_next == "hang":
            threading.Event().wait()
        if self.fail_next == "error":
            raise RuntimeError("synthetic native-step error")
        frame, step = _protobuf_header(actions)
        require(frame == self.frame + 1 and dt_ms == step, "synthetic frame/dt mismatch")
        self.frame = frame
        self.game_time_seconds = (frame + 1) * step // 1000
        if self.fail_next == "complete" and self.complete_frame is None:
            self.complete_frame = frame
        return self.game_time_seconds

    def state(self, viewer=31, *, include_entities=False):
        result = {"frame": self.frame, "viewer": viewer, "synthetic_test_backend": True,
                  "game_data_sha256": self.game_data_sha256,
                  "resources": {0: {"primary": self.frame + 1}},
                  "game_state": {"complete": self.complete_frame is not None,
                                 "game_over_frame": self.complete_frame if self.complete_frame is not None else -1,
                                 "winning_alliance": 1 if self.complete_frame is not None else 31,
                                 "army_conceded_flag": 0, "game_over_checksum": 0}}
        if include_entities:
            result["entities"] = [{"id": 0, "army": 0, "type": 1}]
        return result

    def snapshot(self, viewer=31):
        return b"SYNTHETIC" + struct.pack("<iI", self.frame, viewer) + bytes.fromhex(self.game_data_sha256)

    def close(self):
        if self.hang_close:
            threading.Event().wait()


def serve(source, sink, *, test_backend=False):
    simulation, ai, last_request = None, None, 0
    try:
        while True:
            message = read_message(source)
            if message is None:
                return 0
            operation, flags, request_id, frame, metadata, payload = message
            require(not flags and operation in OPERATIONS, "expected worker request")
            require(request_id == last_request + 1, "request IDs must be consecutive")
            last_request = request_id
            try:
                response_payload = b""
                if operation == CREATE:
                    require(simulation is None and request_id == 1 and frame == -1, "exactly one CREATE is permitted")
                    require(bool(payload), "CREATE requires GameData")
                    require(not test_backend or 'ai' not in metadata, 'synthetic workers cannot enable native AI')
                    if test_backend:
                        simulation = SyntheticSimulation(payload)
                    else:
                        from .native_simulation import NativeSimulation
                        simulation = NativeSimulation(payload, metadata.get("dll_path"))
                    if 'ai' in metadata:
                        from .worker_ai import AISetup, WorkerAI
                        ai = WorkerAI(simulation, payload, AISetup.from_wire(metadata['ai']))
                    response = {"pid": os.getpid(), "game_data_sha256": simulation.game_data_sha256,
                                "dll_sha256": simulation.dll_sha256, "synthetic_test_backend": test_backend,
                                "ai": ai.info if ai is not None else None}
                else:
                    require(simulation is not None, "CREATE is required first")
                    if operation == STEP:
                        require(frame == simulation.frame + 1, "STEP frame must be consecutive")
                        from .native_simulation import _protobuf_header
                        input_frame, input_dt = _protobuf_header(payload)
                        require(input_frame == frame and metadata.get("dt_ms") == input_dt, "STEP header/wire timing differs")
                        if ai is not None: ai.before_step(frame, payload)
                        seconds = simulation.process_frame(payload, dt_ms=input_dt)
                        # No ACK is emitted until step AND authoritative state retrieval succeed.
                        state = simulation.state(31, include_entities=True)
                        require(state["frame"] == frame, "native snapshot frame differs from completed step")
                        if ai is not None: ai.after_step()
                        response = {"game_time_seconds": seconds, "state": state,
                                    "input_sha256": hashlib.sha256(payload).hexdigest()}
                    elif operation == BOT_INPUT:
                        require(ai is not None and frame == simulation.frame + 1 and not payload and not metadata,
                                'invalid bot input request')
                        from .worker_ai import pack_inputs
                        response_payload = pack_inputs(ai.prepare(frame))
                        response = {'sha256': hashlib.sha256(response_payload).hexdigest()}
                    else:
                        require(frame == simulation.frame and not payload, "query frame/payload mismatch")
                        viewer = metadata.get("viewer", 31)
                        require(type(viewer) is int and 0 <= viewer <= 31, "viewer out of range")
                        if operation == STATE:
                            include_entities = metadata.get("include_entities", False)
                            require(type(include_entities) is bool, "include_entities must be boolean")
                            response = {"state": simulation.state(viewer, include_entities=include_entities)}
                        elif operation == SNAPSHOT:
                            response_payload = simulation.snapshot(viewer)
                            require(len(response_payload) <= 16 * 1024 * 1024, "snapshot exceeds limit")
                            response = {"sha256": hashlib.sha256(response_payload).hexdigest()}
                        elif operation == CLOSE:
                            if ai is not None:
                                ai.close()
                                ai = None
                            simulation.close()
                            simulation = None
                            write_packet(sink, encode_message(operation | RESPONSE, request_id, frame, {"closed": True}))
                            return 0
                        elif operation == TEST_CONTROL:
                            require(test_backend, "test controls disabled")
                            action = metadata.get("action")
                            require(action in ("crash_next_step", "hang_next_step", "error_next_step", "complete_next_step", "hang_close", "stderr_flood"), "unknown test control")
                            if action == "hang_close": simulation.hang_close = True
                            elif action == "stderr_flood":
                                for _ in range(32):
                                    os.write(2, b"synthetic stderr drain test\n" * 4096)
                            else: simulation.fail_next = action.split("_", 1)[0]
                            response = {"test_control_applied": action}
                        else:
                            raise ProtocolError("unsupported operation")
                write_packet(sink, encode_message(operation | RESPONSE, request_id, frame, response, response_payload))
            except Exception as error:
                # Any error is terminal: a native call may have partly applied input.
                write_packet(sink, encode_message(operation | RESPONSE, request_id, frame,
                                                 {"error": type(error).__name__, "message": str(error)[:4096]}, flags=ERROR))
                return 2
    finally:
        try:
            if ai is not None: ai.close()
        finally:
            if simulation is not None: simulation.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdio", action="store_true", required=True)
    parser.add_argument("--test-backend", action="store_true")
    args = parser.parse_args(argv)
    if args.test_backend and os.environ.get("BA_ENABLE_SYNTHETIC_WORKER_TESTS") != "1":
        parser.error("synthetic backend requires explicit test environment gate")
    sink = isolate_protocol_stdout()
    try:
        return serve(sys.stdin.buffer, sink, test_backend=args.test_backend)
    except Exception as error:
        print(f"Simulation worker failed: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return 2
    finally:
        sink.close()


if __name__ == "__main__":
    raise SystemExit(main())
